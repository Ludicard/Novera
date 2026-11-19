import uuid
from pathlib import Path

from django.conf import settings
from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db.models import Q, Sum
from django.http import HttpResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.clientes.models import Cliente

from . import importador
from .dashboard import datos_panel
from .exportar import exportar_facturas
from .forms import AnularForm, FacturaForm, FiltroFacturasForm, ImportarForm, PagoForm
from .models import Factura, Pago


@login_required
def dashboard(request):
    hoy = timezone.localdate()
    if not Factura.objects.exists():
        return render(request, "dashboard.html", {"hoy": hoy, "sin_datos": True})
    contexto = datos_panel(request.GET, hoy)
    contexto["hoy"] = hoy
    return render(request, "dashboard.html", contexto)


def _filtrar(get):
    form = FiltroFacturasForm(get or None)
    qs = Factura.objects.con_saldos().select_related("cliente")
    if form.is_valid():
        d = form.cleaned_data
        if d["q"]:
            qs = qs.filter(
                Q(numero__icontains=d["q"]) | Q(objeto__icontains=d["q"]) | Q(cliente__nombre__icontains=d["q"])
            )
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


@login_required
def lista(request):
    form, qs = _filtrar(request.GET)
    totales = qs.filter(anulada=False).aggregate(
        suma_total=Sum("total"), suma_saldo=Sum("saldo"), suma_pagado=Sum("pagado")
    )
    pagina = Paginator(qs, 50).get_page(request.GET.get("page"))
    filtros = request.GET.copy()
    filtros.pop("page", None)
    return render(
        request,
        "facturas/lista.html",
        {"form": form, "pagina": pagina, "totales": totales, "filtros": filtros.urlencode()},
    )


@login_required
def exportar(request):
    _, qs = _filtrar(request.GET)
    contenido = exportar_facturas(qs)
    respuesta = HttpResponse(
        contenido, content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
    )
    nombre = f"novera-facturas-{timezone.localdate():%Y%m%d}.xlsx"
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return respuesta


def _dias_credito_clientes():
    return {str(pk): dias for pk, dias in Cliente.objects.values_list("pk", "dias_credito")}


@login_required
def nueva(request):
    inicial = {}
    if request.GET.get("cliente"):
        cliente = Cliente.objects.filter(pk=request.GET["cliente"]).first()
        if cliente:
            inicial = {"cliente": cliente, "dias_credito": cliente.dias_credito}
    form = FacturaForm(request.POST or None, initial=inicial)
    if form.is_valid():
        factura = form.save(commit=False)
        factura.creado_por = request.user
        factura.save()
        messages.success(request, f"Factura {factura.numero} registrada por ${factura.total}.")
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
        if factura.total < factura.total_pagado():
            messages.warning(request, "Ojo: lo pagado supera el nuevo total de la factura.")
        messages.success(request, "Factura actualizada.")
        return redirect(factura)
    return render(
        request,
        "facturas/form.html",
        {"form": form, "titulo": f"Editar {factura.numero}", "factura": factura, "dias_clientes": _dias_credito_clientes()},
    )


def _render_detalle(request, factura, pago_form=None, anular_form=None, status=200):
    return render(
        request,
        "facturas/detalle.html",
        {
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
    if not form.is_valid():
        return _render_detalle(request, factura, pago_form=form, status=400)
    pago = form.save(commit=False)
    pago.factura = factura
    pago.creado_por = request.user
    pago.save()
    messages.success(request, f"Pago de ${pago.monto} registrado.")
    return redirect(factura)


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
        resultado = importador.analizar(_carpeta() / datos["archivo"], datos["estado_desconocido"])
        creados = importador.aplicar(resultado, usuario=request.user)
        _borrar_pendiente(request)
        messages.success(
            request,
            f"Importación completa: {creados['facturas']} facturas, {creados['pagos']} pagos "
            f"y {creados['clientes']} clientes nuevos.",
        )
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
