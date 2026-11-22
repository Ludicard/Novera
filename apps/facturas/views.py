import uuid
from urllib.parse import urlparse
from decimal import Decimal
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import IntegrityError, transaction
from django.db.models import Q, Sum
from django.http import HttpResponse, QueryDict
from django.shortcuts import get_object_or_404, redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.clientes.models import Cliente

from . import importador
from .dashboard import datos_panel
from .exportar import exportar_facturas
from .forms import AnularForm, CobroLoteForm, FacturaForm, FiltroFacturasForm, ImportarForm, PagoForm
from .models import Estado, Factura, Pago


@login_required
def dashboard(request):
    hoy = timezone.localdate()
    if not Factura.objects.exists():
        return render(request, "dashboard.html", {"hoy": hoy, "sin_datos": True})
    contexto = datos_panel(request.GET, hoy)
    contexto["hoy"] = hoy
    return render(request, "dashboard.html", contexto)


PESTANAS = [
    ("", "Todas"),
    ("ABIERTAS", "Por cobrar"),
    (Estado.VENCIDA, "Vencidas"),
    (Estado.PARCIAL, "Abono parcial"),
    (Estado.PENDIENTE, "Pendientes"),
    (Estado.PAGADA, "Pagadas"),
    (Estado.ANULADA, "Anuladas"),
]
ORDENES = {
    "numero": "numero",
    "emision": "fecha_emision",
    "cliente": "cliente__nombre",
    "vence": "fecha_cobro",
    "total": "total",
    "saldo": "saldo",
}
ORDEN_DEFECTO = "-emision"
TAMANOS_PAGINA = [25, 50, 100]


def _filtrar(get, con_estado=True):
    """Devuelve (form, queryset). Con `con_estado=False` ignora el filtro de estado (para las pestañas)."""
    form = FiltroFacturasForm(get or None)
    qs = Factura.objects.con_saldos().select_related("cliente")
    if form.is_bound:
        form.is_valid()  # un campo inválido (p. ej. ?desde=2025-13) no anula el resto de filtros
        d = {campo: form.cleaned_data.get(campo) for campo in form.fields}
        if d["q"]:
            q = d["q"].strip()
            filtro = Q(numero__icontains=q) | Q(objeto__icontains=q) | Q(cliente__nombre__icontains=q)
            filtro |= Q(cliente__identificacion__startswith=q) | Q(clave_acceso=q)
            if q.isdigit():  # «676» encuentra 001-001-000000676
                filtro |= Q(numero__endswith=q.zfill(9))
            qs = qs.filter(filtro)
        if con_estado:
            if d["estado"] == "ABIERTAS":
                qs = qs.filter(anulada=False, saldo__gt=0)
            elif d["estado"]:
                qs = qs.filter(estado=d["estado"])
        if d["cliente"]:
            qs = qs.filter(cliente=d["cliente"])
        if d["desde"]:
            qs = qs.filter(periodo__gte=d["desde"].replace(day=1))
        if d["hasta"]:
            qs = qs.filter(periodo__lte=d["hasta"].replace(day=1))
        if d["emitida_desde"]:
            qs = qs.filter(fecha_emision__gte=d["emitida_desde"])
        if d["emitida_hasta"]:
            qs = qs.filter(fecha_emision__lte=d["emitida_hasta"])
    return form, qs


def _conteos_por_pestana(qs):
    conteos = {clave: {"n": 0, "monto": Decimal("0.00")} for clave, _ in PESTANAS}
    for estado, total, saldo in qs.values_list("estado", "total", "saldo"):
        conteos[""]["n"] += 1
        conteos[""]["monto"] += total if estado != Estado.ANULADA else 0
        if estado in conteos:
            conteos[estado]["n"] += 1
            conteos[estado]["monto"] += saldo if estado in (Estado.VENCIDA, Estado.PARCIAL, Estado.PENDIENTE) else total
        if estado != Estado.ANULADA and saldo > 0:
            conteos["ABIERTAS"]["n"] += 1
            conteos["ABIERTAS"]["monto"] += saldo
    return [{"clave": clave, "nombre": nombre, **conteos[clave]} for clave, nombre in PESTANAS]


def _filtros_activos(form, get):
    """Etiquetas de los filtros aplicados (menos búsqueda y estado), con la URL para quitarlas."""
    if not form.is_bound:
        return []
    d = {campo: form.cleaned_data.get(campo) for campo in form.fields}
    chips = []

    def sin(*campos):
        resto = get.copy()
        for c in (*campos, "page"):
            resto.pop(c, None)
        return "?" + resto.urlencode()

    if d["cliente"]:
        chips.append((f"Cliente: {d['cliente']}", sin("cliente")))
    if d["emitida_desde"] or d["emitida_hasta"]:
        rango = f"{d['emitida_desde']:%d/%m/%Y}" if d["emitida_desde"] else "…"
        rango += " – " + (f"{d['emitida_hasta']:%d/%m/%Y}" if d["emitida_hasta"] else "…")
        chips.append((f"Emitidas {rango}", sin("emitida_desde", "emitida_hasta")))
    if d["desde"] or d["hasta"]:
        rango = (f"{d['desde']:%m/%Y}" if d["desde"] else "…") + " – " + (f"{d['hasta']:%m/%Y}" if d["hasta"] else "…")
        chips.append((f"Periodo {rango}", sin("desde", "hasta")))
    return chips


@login_required
def lista(request):
    hoy = timezone.localdate()
    form, base = _filtrar(request.GET, con_estado=False)
    _, qs = _filtrar(request.GET)
    totales = qs.filter(anulada=False).aggregate(
        suma_total=Sum("total"), suma_saldo=Sum("saldo", filter=Q(saldo__gt=0)), suma_pagado=Sum("pagado")
    )

    orden = request.GET.get("orden", ORDEN_DEFECTO)
    campo = ORDENES.get(orden.lstrip("-"))
    if not campo:
        orden, campo = ORDEN_DEFECTO, ORDENES[ORDEN_DEFECTO.lstrip("-")]
    desc = orden.startswith("-")
    qs = qs.order_by(("-" if desc else "") + campo, "-numero")

    try:
        por_pagina = int(request.GET.get("por_pagina", 50))
    except ValueError:
        por_pagina = 50
    por_pagina = por_pagina if por_pagina in TAMANOS_PAGINA else 50
    pagina = Paginator(qs, por_pagina).get_page(request.GET.get("page"))
    for f in pagina:
        f.dias_para_cobro = (f.fecha_cobro - hoy).days if f.fecha_cobro else None
        f.dias_vencida = -f.dias_para_cobro if f.dias_para_cobro and f.dias_para_cobro < 0 else 0
        f.pct_cobrado = min(100, round(f.pagado / f.total * 100)) if f.total else 0

    filtros = request.GET.copy()
    filtros.pop("page", None)
    d = getattr(form, "cleaned_data", {})
    return render(
        request,
        "facturas/lista.html",
        {
            "form": form,
            "pagina": pagina,
            "rango_paginas": pagina.paginator.get_elided_page_range(pagina.number, on_each_side=2, on_ends=1),
            "totales": totales,
            "filtros": filtros.urlencode(),
            "pestanas": _conteos_por_pestana(base),
            "estado_actual": d.get("estado", ""),
            "chips": _filtros_activos(form, request.GET),
            "mas_filtros_abiertos": any(d.get(c) for c in ("cliente", "desde", "hasta", "emitida_desde", "emitida_hasta")),
            "orden": orden,
            "por_pagina": por_pagina,
            "tamanos": TAMANOS_PAGINA,
            "formas_pago": Pago.Forma.choices,
            "por_cobrar_filtradas": qs.filter(anulada=False, saldo__gt=0).count(),
            "hoy": hoy,
        },
    )


@login_required
def exportar(request):
    _, qs = _filtrar(request.GET)
    campo = ORDENES.get(request.GET.get("orden", ORDEN_DEFECTO).lstrip("-"))
    if campo:
        qs = qs.order_by(("-" if request.GET.get("orden", ORDEN_DEFECTO).startswith("-") else "") + campo, "-numero")
    ids = [int(x) for x in request.GET.get("ids", "").split(",") if x.isdigit()]
    if ids:
        qs = Factura.objects.con_saldos().select_related("cliente").filter(pk__in=ids)
    contenido = exportar_facturas(qs)
    respuesta = HttpResponse(
        contenido, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    nombre = f"novera-facturas-{timezone.localdate():%Y%m%d}.xlsx"
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return respuesta


def _siguiente(request, defecto):
    """URL de retorno segura (solo del propio sitio)."""
    url = request.POST.get("siguiente") or request.GET.get("siguiente")
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return url
    return defecto


@login_required
@require_POST
def cobrar_lote(request):
    """Registra un pago por el saldo completo de cada factura seleccionada (o de todas las filtradas)."""
    form = CobroLoteForm(request.POST)
    volver = _siguiente(request, reverse("facturas:lista"))
    if not form.is_valid():
        errores = "; ".join(e for lista in form.errors.values() for e in lista)
        messages.error(request, f"No se registró el cobro: {errores}")
        return redirect(volver)
    d = form.cleaned_data
    if d["todas"]:
        _, facturas = _filtrar(QueryDict(d["filtros"] or ""))
        facturas = facturas.filter(anulada=False, saldo__gt=0)
    else:
        facturas = Factura.objects.por_cobrar().filter(pk__in=d["ids"])
    hoy = timezone.localdate()
    total, n = Decimal("0.00"), 0
    with transaction.atomic():
        for f in facturas:
            if d["fecha_modo"] == CobroLoteForm.FECHA_VENCIMIENTO:
                fecha = min(f.fecha_cobro or f.fecha_emision, hoy)
            elif d["fecha_modo"] == CobroLoteForm.FECHA_EMISION:
                fecha = f.fecha_emision
            else:
                fecha = d["fecha"]
            Pago.objects.create(
                factura=f, fecha=fecha, forma=d["forma"], referencia=d["referencia"], monto=f.saldo,
                notas="Cobro en lote desde el listado", creado_por=request.user,
            )
            total += f.saldo
            n += 1
    if n:
        s = "s" if n != 1 else ""
        messages.success(request, f"{n} factura{s} marcada{s} como cobrada{s} por ${total:,.2f}.")
    else:
        messages.info(request, "Las facturas seleccionadas no tenían saldo pendiente.")
    return redirect(volver)


def _dias_credito_clientes():
    return {str(pk): dias for pk, dias in Cliente.objects.values_list("pk", "dias_credito")}


@login_required
def nueva(request):
    inicial = {}
    if request.GET.get("cliente", "").isdigit():
        cliente = Cliente.objects.filter(pk=request.GET["cliente"]).first()
        if cliente:
            inicial = {"cliente": cliente, "dias_credito": cliente.dias_credito}
            if not cliente.activo:
                messages.warning(request, f"«{cliente}» está marcado como inactivo; puedes facturarle igualmente.")
    form = FacturaForm(request.POST or None, initial=inicial)
    if form.is_valid():
        factura = form.save(commit=False)
        factura.creado_por = request.user
        factura.save()
        messages.success(request, f"Factura {factura.numero} registrada por ${factura.total:,.2f}.")
        if "otra" in request.POST:
            return redirect("facturas:nueva")
        return redirect(factura)
    return render(
        request,
        "facturas/form.html",
        {"form": form, "titulo": "Nueva factura", "dias_clientes": _dias_credito_clientes()},
    )


@login_required
def editar(request, pk):
    factura = get_object_or_404(Factura, pk=pk)
    if factura.anulada:
        messages.error(request, "Una factura anulada no se puede editar.")
        return redirect(factura)
    form = FacturaForm(request.POST or None, instance=factura)
    if form.is_valid():
        factura = form.save()
        messages.success(request, "Factura actualizada.")
        return redirect(factura)
    return render(
        request,
        "facturas/form.html",
        {"form": form, "titulo": f"Editar {factura.numero}", "factura": factura, "dias_clientes": _dias_credito_clientes()},
    )


def _render_detalle(request, factura, pago_form=None, anular_form=None, status=200):
    hoy = timezone.localdate()
    dias = (factura.fecha_cobro - hoy).days if factura.fecha_cobro else None
    # «Volver»: a la página de la que se vino (listado filtrado, cliente, panel…), salvo las de esta misma factura
    referer = request.META.get("HTTP_REFERER", "")
    propia = factura.get_absolute_url()
    volver = reverse("facturas:lista")
    if referer and url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()}):
        ruta = urlparse(referer).path
        if not ruta.startswith(propia):
            volver = referer
            request.session[f"volver_factura_{factura.pk}"] = referer
        else:
            volver = request.session.get(f"volver_factura_{factura.pk}", volver)
    return render(
        request,
        "facturas/detalle.html",
        {
            "volver": volver,
            "dias_para_cobro": dias,
            "dias_vencida": -dias if dias is not None and dias < 0 else 0,
            "pct_cobrado": min(100, round(factura.pagado / factura.total * 100)) if factura.total else 0,
            "factura": factura,
            "pagos": factura.pagos.all(),
            "pago_form": pago_form or PagoForm(factura=factura),
            "anular_form": anular_form or AnularForm(),
        },
        status=status,
    )


def _factura_con_saldo(pk):
    return get_object_or_404(Factura.objects.con_saldos().select_related("cliente"), pk=pk)


@login_required
def detalle(request, pk):
    return _render_detalle(request, _factura_con_saldo(pk))


@login_required
@require_POST
def registrar_pago(request, pk):
    factura = _factura_con_saldo(pk)
    form = PagoForm(request.POST, factura=factura)
    volver = _siguiente(request, None)
    if not form.is_valid():
        if volver:  # viene del diálogo «Cobrar» del listado
            errores = "; ".join(e for lista in form.errors.values() for e in lista)
            messages.error(request, f"No se registró el pago de {factura.numero}: {errores}")
            return redirect(volver)
        return _render_detalle(request, factura, pago_form=form, status=400)
    pago = form.save(commit=False)
    pago.factura = factura
    pago.creado_por = request.user
    pago.save()
    messages.success(request, f"Pago de ${pago.monto:,.2f} registrado en {factura.numero}.")
    return redirect(volver or factura)


@login_required
@require_POST
def eliminar_pago(request, pk, pago_pk):
    pago = get_object_or_404(Pago, pk=pago_pk, factura_id=pk)
    pago.delete()
    messages.success(request, "Pago eliminado.")
    return redirect("facturas:detalle", pk=pk)


@login_required
@require_POST
def anular(request, pk):
    factura = _factura_con_saldo(pk)
    form = AnularForm(request.POST)
    if factura.anulada:
        messages.info(request, f"La factura {factura.numero} ya estaba anulada.")
        return redirect(factura)
    if factura.pagos.exists():
        messages.error(request, "La factura tiene pagos registrados: elimínalos antes de anularla.")
        return redirect(factura)
    if not form.is_valid():
        return _render_detalle(request, factura, anular_form=form, status=400)
    factura.anulada = True
    factura.fecha_anulacion = timezone.localdate()
    factura.motivo_anulacion = form.cleaned_data["motivo"]
    factura.save(update_fields=["anulada", "fecha_anulacion", "motivo_anulacion", "actualizado"])
    messages.success(request, f"Factura {factura.numero} anulada.")
    return redirect(factura)


# ------------------------------------------------------------ importación



def _carpeta():
    return Path(settings.MEDIA_ROOT) / "importaciones"

SESION = "importacion"


def _borrar_pendiente(request):
    datos = request.session.pop(SESION, None)
    if datos:
        (_carpeta() / datos["archivo"]).unlink(missing_ok=True)


@login_required
def importar(request):
    if request.method == "POST" and request.POST.get("accion") in {"confirmar", "cancelar"}:
        datos = request.session.get(SESION)
        if not datos:
            messages.error(request, "La importación expiró. Vuelve a subir el archivo.")
            return redirect("facturas:importar")
        if request.POST["accion"] == "cancelar":
            _borrar_pendiente(request)
            messages.info(request, "Importación cancelada.")
            return redirect("facturas:importar")
        # Se saca de la sesión antes de aplicar: un doble clic en «Importar» no puede repetirlo
        request.session.pop(SESION)
        request.session.modified = True
        archivo = _carpeta() / datos["archivo"]
        try:
            resultado = importador.analizar(archivo, datos["estado_desconocido"])
            creados = importador.aplicar(resultado, usuario=request.user)
        except IntegrityError:
            messages.error(request, "Esas facturas ya se estaban importando. Revisa el listado antes de reintentar.")
            return redirect("facturas:lista")
        finally:
            archivo.unlink(missing_ok=True)
        partes = []
        if creados["facturas"]:
            partes.append(
                f"{creados['facturas']} factura{'s' if creados['facturas'] != 1 else ''} nueva{'s' if creados['facturas'] != 1 else ''}, "
                f"{creados['pagos']} pago{'s' if creados['pagos'] != 1 else ''} y {creados['clientes']} cliente{'s' if creados['clientes'] != 1 else ''} nuevo{'s' if creados['clientes'] != 1 else ''}"
            )
        if creados["cobros_actualizados"]:
            n = creados["cobros_actualizados"]
            partes.append(f"cobro actualizado en {n} factura{'s' if n != 1 else ''} que ya existía{'n' if n != 1 else ''}")
        if creados["anuladas"]:
            n = creados["anuladas"]
            partes.append(f"{n} factura{'s' if n != 1 else ''} anulada{'s' if n != 1 else ''}")
        if not partes:
            messages.info(request, "No había nada nuevo en ese archivo: todo ya estaba en Novera y al día.")
        else:
            messages.success(request, "Importación completa: " + "; ".join(partes) + ".")
        return redirect("facturas:lista")

    form = ImportarForm(request.POST or None, request.FILES or None)
    if request.method == "POST" and form.is_valid():
        _borrar_pendiente(request)
        _carpeta().mkdir(parents=True, exist_ok=True)
        archivo = form.cleaned_data["archivo"]
        nombre = f"{uuid.uuid4().hex}{Path(archivo.name).suffix.lower()}"
        with open(_carpeta() / nombre, "wb") as destino:
            for trozo in archivo.chunks():
                destino.write(trozo)
        try:
            resultado = importador.analizar(_carpeta() / nombre, form.cleaned_data["estado_desconocido"])
        except Exception:  # archivo corrupto o no es un Excel
            (_carpeta() / nombre).unlink(missing_ok=True)
            form.add_error("archivo", "No se pudo leer el archivo. ¿Es un Excel válido?")
            return render(request, "facturas/importar.html", {"form": form})
        if resultado.errores:
            (_carpeta() / nombre).unlink(missing_ok=True)
            for error in resultado.errores:
                form.add_error("archivo", error)
            return render(request, "facturas/importar.html", {"form": form})
        request.session[SESION] = {
            "archivo": nombre,
            "original": archivo.name,
            "estado_desconocido": form.cleaned_data["estado_desconocido"],
        }
        return render(
            request,
            "facturas/importar_preview.html",
            {"resultado": resultado, "resumen": resultado.resumen(), "original": archivo.name},
        )
    return render(request, "facturas/importar.html", {"form": form})
