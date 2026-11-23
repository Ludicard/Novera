from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.core.paginator import Paginator
from django.db import transaction
from django.db.models import Count, Q
from django.http import Http404
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.views.decorators.http import require_POST

from apps.usuarios.permisos import requiere_rol
from apps.usuarios.roles import ADMINISTRADOR, MANAGER, ROLES, TECNICO

from .forms import FormaPagoForm, InformeForm, LineasFormSet, OrdenForm, ProformaForm, RecursosFormSet, tecnicos
from .models import FormaPago, Informe, OrdenTrabajo, Proforma, Recurso

GESTION = (ADMINISTRADOR, MANAGER)


def _gestiona(request):
    return request.rol in GESTION


# ---------------------------------------------------------------- proformas


@requiere_rol(*GESTION)
def proformas(request):
    conteos = dict(Proforma.objects.values_list("estado").annotate(n=Count("id")))
    por_autorizar = conteos.get(Proforma.Estado.POR_AUTORIZAR, 0)
    defecto = Proforma.Estado.POR_AUTORIZAR if request.rol == MANAGER and por_autorizar else ""
    estado = request.GET.get("estado", defecto)
    q = request.GET.get("q", "").strip()
    qs = Proforma.objects.select_related("cliente", "autorizada_por").prefetch_related("lineas")
    if estado:
        qs = qs.filter(estado=estado)
    if q:
        qs = qs.filter(Q(numero__icontains=q) | Q(titulo__icontains=q) | Q(cliente__nombre__icontains=q))
    orden_estados = [Proforma.Estado.POR_AUTORIZAR, Proforma.Estado.DEVUELTA, Proforma.Estado.AUTORIZADA,
                     Proforma.Estado.ENVIADA, Proforma.Estado.PROCESADA, Proforma.Estado.APROBADA, Proforma.Estado.RECHAZADA]
    pestanas = [("", "Todas", sum(conteos.values()))] + [
        (c, Proforma.Estado(c).label, conteos.get(c, 0)) for c in orden_estados
    ]
    if conteos.get(Proforma.Estado.BORRADOR):
        pestanas.append((Proforma.Estado.BORRADOR, "Borrador", conteos[Proforma.Estado.BORRADOR]))
    pagina = Paginator(qs, 50).get_page(request.GET.get("page"))
    return render(request, "trabajos/proformas.html", {"pagina": pagina, "estado": estado, "q": q, "pestanas": pestanas})


def _cliente_inicial(request):
    cliente = request.GET.get("cliente", "")
    if not cliente.isdigit():
        return None
    inicial = {"cliente": cliente}
    if request.GET.get("equipo", "").isdigit():
        inicial["equipos"] = [request.GET["equipo"]]
    return inicial


def _guardar_proforma(request, proforma=None):
    """Guardar = solicitar autorización al Manager. Si quien guarda es el Manager, queda autorizada."""
    form = ProformaForm(request.POST or None, instance=proforma, initial=None if proforma else _cliente_inicial(request))
    lineas = LineasFormSet(request.POST or None, instance=form.instance, prefix="lineas")
    if request.method == "POST" and form.is_valid() and lineas.is_valid():
        with transaction.atomic():
            p = form.save(commit=False)
            if not p.pk:
                p.creado_por = request.user
            if request.rol == MANAGER:
                p.estado = Proforma.Estado.AUTORIZADA
                p.autorizada_por, p.fecha_autorizacion = request.user, timezone.now()
            else:
                p.estado = Proforma.Estado.POR_AUTORIZAR
                p.autorizada_por, p.fecha_autorizacion = None, None
            p.save()
            lineas.instance = p
            lineas.save()
            p.titulo = p.resumen_desde_lineas()
            p.save(update_fields=["titulo"])
        if request.rol == MANAGER:
            messages.success(request, f"Proforma {p.numero} guardada y autorizada (${p.total:,.2f}).")
        else:
            messages.success(request, f"Proforma {p.numero} enviada al Manager para su autorización (${p.total:,.2f}).")
        return redirect(p)
    titulo = f"Editar {proforma.numero}" if proforma else "Nueva proforma"
    return render(request, "trabajos/proforma_form.html", {
        "form": form, "lineas": lineas, "titulo": titulo, "proforma": proforma,
        "campos_datos": ["cliente", "fecha", "validez_dias", "porcentaje_iva"],
        "forma_pago_form": FormaPagoForm(),
    })


@requiere_rol(*GESTION)
def proforma_nueva(request):
    return _guardar_proforma(request)


@requiere_rol(*GESTION)
def proforma_editar(request, pk):
    proforma = get_object_or_404(Proforma, pk=pk)
    if not proforma.editable:
        messages.error(request, "Una proforma autorizada ya no se puede editar. Si hay que cambiarla, el Manager debe devolverla para corregir.")
        return redirect(proforma)
    return _guardar_proforma(request, proforma)


@requiere_rol(*GESTION)
def proforma(request, pk):
    p = get_object_or_404(Proforma.objects.select_related("cliente"), pk=pk)
    return render(request, "trabajos/proforma.html", {"p": p, "lineas": p.lineas.all(), "orden": getattr(p, "orden", None)})


@requiere_rol(*GESTION)
@require_POST
def proforma_estado(request, pk):
    """Autorizar, devolver y procesar (Manager); enviar, generar la orden de trabajo y rechazada por el cliente."""
    p = get_object_or_404(Proforma, pk=pk)
    accion = request.POST.get("accion")
    observacion = request.POST.get("observacion", "").strip()
    E = Proforma.Estado
    transiciones = {
        "autorizar": ({E.POR_AUTORIZAR, E.BORRADOR, E.DEVUELTA}, E.AUTORIZADA),
        "devolver": ({E.POR_AUTORIZAR, E.BORRADOR, E.AUTORIZADA, E.ENVIADA}, E.DEVUELTA),
        "enviar": ({E.AUTORIZADA}, E.ENVIADA),
        "procesar": ({E.ENVIADA}, E.PROCESADA),
        "generar_orden": ({E.PROCESADA}, E.APROBADA),
        "rechazar": ({E.AUTORIZADA, E.ENVIADA, E.PROCESADA}, E.RECHAZADA),
        "reabrir": ({E.RECHAZADA}, E.POR_AUTORIZAR),
    }
    if accion in ("autorizar", "devolver", "procesar") and request.rol != MANAGER:
        messages.error(request, "Solo el Manager puede autorizar, devolver o procesar proformas.")
        return redirect(p)
    if accion == "generar_orden" and getattr(p, "orden", None):
        messages.info(request, f"Esta proforma ya tiene la orden {p.orden.numero}.")
        return redirect(p.orden)
    if accion not in transiciones or p.estado not in transiciones[accion][0]:
        messages.error(request, "Esa acción no es posible en el estado actual de la proforma.")
        return redirect(p)
    if accion == "devolver" and not observacion:
        messages.error(request, "Escribe qué hay que corregir para devolver la proforma.")
        return redirect(p)
    with transaction.atomic():
        p.estado = transiciones[accion][1]
        campos = ["estado", "actualizado"]
        if accion in ("autorizar", "devolver"):
            p.autorizada_por = request.user if accion == "autorizar" else None
            p.fecha_autorizacion = timezone.now() if accion == "autorizar" else None
            p.observacion_autorizacion = observacion
            campos += ["autorizada_por", "fecha_autorizacion", "observacion_autorizacion"]
        if accion == "procesar":
            p.procesada_por, p.fecha_procesada = request.user, timezone.now()
            campos += ["procesada_por", "fecha_procesada"]
        if accion in ("procesar", "rechazar"):
            p.fecha_respuesta = timezone.localdate()
            campos.append("fecha_respuesta")
        p.save(update_fields=campos)
        if accion == "generar_orden":
            orden = OrdenTrabajo.desde_proforma(p, request.user)
            messages.success(request, f"Se generó la orden {orden.numero} a partir de {p.numero}. Completa fechas, técnicos y herramientas.")
            return redirect("trabajos:orden_editar", pk=orden.pk)
    textos = {
        "autorizar": f"Proforma {p.numero} autorizada: ya se puede enviar al cliente.",
        "devolver": f"Proforma {p.numero} devuelta para corregir.",
        "enviar": f"Proforma {p.numero} marcada como enviada al cliente.",
        "procesar": f"Proforma {p.numero} procesada: ya se puede generar la orden de trabajo.",
        "rechazar": f"Proforma {p.numero} marcada como rechazada por el cliente.",
        "reabrir": f"Proforma {p.numero} reabierta: vuelve a autorización.",
    }
    messages.success(request, textos[accion])
    if accion in ("autorizar", "devolver"):
        siguiente = Proforma.objects.filter(estado=E.POR_AUTORIZAR).order_by("creado").first()
        if siguiente:  # el Manager sigue con la próxima pendiente
            return redirect(siguiente)
        return redirect("trabajos:proformas")
    return redirect(p)


# ---------------------------------------------------------------- formas de pago (catálogo)


@requiere_rol(*GESTION)
def formas_pago(request):
    form = FormaPagoForm(request.POST or None, initial={"orden": (FormaPago.objects.order_by("-orden").values_list("orden", flat=True).first() or 0) + 10})
    if form.is_valid():
        fp = form.save()
        messages.success(request, f"Forma de pago «{fp.nombre}» agregada.")
        return redirect("trabajos:formas_pago")
    return render(request, "trabajos/formas_pago.html", {"form": form, "formas": FormaPago.objects.all()})


@requiere_rol(*GESTION)
def forma_pago_editar(request, pk):
    fp = get_object_or_404(FormaPago, pk=pk)
    form = FormaPagoForm(request.POST or None, instance=fp)
    if form.is_valid():
        form.save()
        messages.success(request, "Forma de pago actualizada.")
        return redirect("trabajos:formas_pago")
    return render(request, "trabajos/formas_pago.html", {"form": form, "formas": FormaPago.objects.all(), "editando": fp})


@requiere_rol(*GESTION)
@require_POST
def forma_pago_activar(request, pk):
    fp = get_object_or_404(FormaPago, pk=pk)
    fp.activa = not fp.activa
    fp.save(update_fields=["activa"])
    messages.success(request, f"«{fp.nombre}» {'activada' if fp.activa else 'desactivada: ya no se ofrece en proformas nuevas'}.")
    return redirect("trabajos:formas_pago")


@requiere_rol(*GESTION)
@require_POST
def forma_pago_rapida(request):
    """Alta desde el formulario de proforma (diálogo): responde JSON."""
    from django.http import JsonResponse

    form = FormaPagoForm({"nombre": request.POST.get("nombre", ""), "activa": True,
                          "orden": (FormaPago.objects.order_by("-orden").values_list("orden", flat=True).first() or 0) + 10})
    if not form.is_valid():
        return JsonResponse({"errores": [e for lista in form.errors.values() for e in lista]}, status=400)
    fp = form.save()
    return JsonResponse({"nombre": fp.nombre})


# ---------------------------------------------------------------- órdenes de trabajo


@login_required
def ordenes(request):
    """Gestión: todas. Técnico: solo las órdenes en las que está asignado."""
    estado = request.GET.get("estado", "abiertas")
    q = request.GET.get("q", "").strip()
    base = OrdenTrabajo.objects.select_related("cliente").annotate(
        n_tecnicos=Count("tecnicos", distinct=True), n_informes=Count("informes", distinct=True),
    )
    if not _gestiona(request):
        base = base.filter(tecnicos=request.user)
    abiertas = [OrdenTrabajo.Estado.PENDIENTE, OrdenTrabajo.Estado.EN_CURSO]
    conteos = {
        "abiertas": base.filter(estado__in=abiertas).count(),
        "sin_tecnico": base.filter(estado__in=abiertas, n_tecnicos=0).count(),
        **{c: base.filter(estado=c).count() for c, _ in OrdenTrabajo.Estado.choices},
    }
    qs = base
    if estado == "abiertas":
        qs = qs.filter(estado__in=abiertas)
    elif estado == "sin_tecnico":
        qs = qs.filter(estado__in=abiertas, n_tecnicos=0)
    elif estado in OrdenTrabajo.Estado.values:
        qs = qs.filter(estado=estado)
    if q:
        qs = qs.filter(Q(numero__icontains=q) | Q(titulo__icontains=q) | Q(cliente__nombre__icontains=q))
    qs = qs.order_by("fecha_fin", "-creado") if estado in ("abiertas", "sin_tecnico") else qs.order_by("-creado")
    pestanas = [("abiertas", "Abiertas"), ("sin_tecnico", "Sin técnico")] if _gestiona(request) else [("abiertas", "Abiertas")]
    pestanas += [(c, n) for c, n in OrdenTrabajo.Estado.choices]
    pagina = Paginator(qs.prefetch_related("tecnicos"), 50).get_page(request.GET.get("page"))
    return render(request, "trabajos/ordenes.html", {
        "pagina": pagina, "estado": estado, "q": q, "conteos": conteos,
        "pestanas": [(c, n, conteos.get(c, 0)) for c, n in pestanas], "gestiona": _gestiona(request),
    })


def _proformas_listas():
    return Proforma.objects.filter(estado=Proforma.Estado.PROCESADA, orden__isnull=True).select_related("cliente").order_by("fecha_procesada")


def _guardar_orden(request, orden=None):
    form = OrdenForm(request.POST or None, instance=orden, initial=None if orden else _cliente_inicial(request))
    recursos = RecursosFormSet(request.POST or None, instance=form.instance, prefix="recursos")
    if request.method == "POST" and form.is_valid() and recursos.is_valid():
        with transaction.atomic():
            o = form.save(commit=False)
            if not o.pk:
                o.creado_por = request.user
            o.save()
            form.save_m2m()
            recursos.instance = o
            recursos.save()
        messages.success(request, f"Orden {o.numero} guardada.")
        return redirect(o)
    titulo = f"Editar {orden.numero}" if orden else "Nueva orden de trabajo"
    return render(request, "trabajos/orden_form.html", {
        "form": form, "recursos": recursos, "titulo": titulo, "orden": orden,
        "proformas_listas": _proformas_listas() if not orden else None,
    })


@requiere_rol(*GESTION)
def orden_nueva(request):
    return _guardar_orden(request)


@requiere_rol(*GESTION)
def orden_editar(request, pk):
    return _guardar_orden(request, get_object_or_404(OrdenTrabajo, pk=pk))


@login_required
def orden(request, pk):
    o = get_object_or_404(OrdenTrabajo.objects.select_related("cliente", "proforma"), pk=pk)
    gestiona = _gestiona(request)
    asignado = o.tecnicos.filter(pk=request.user.pk).exists()
    if not gestiona and not asignado:
        raise Http404
    return render(request, "trabajos/orden.html", {
        "o": o, "gestiona": gestiona, "asignado": asignado,
        "materiales": o.recursos.filter(tipo=Recurso.Tipo.MATERIAL),
        "herramientas": o.recursos.filter(tipo=Recurso.Tipo.HERRAMIENTA),
        "tecnicos_asignados": o.tecnicos.order_by("first_name", "username"),
        "informes": o.informes.select_related("tecnico"),
        "facturas": o.facturas.con_saldos() if gestiona and request.rol == ADMINISTRADOR else None,
        "estados": OrdenTrabajo.Estado.choices,
    })


@requiere_rol(*GESTION)
@require_POST
def orden_estado(request, pk):
    o = get_object_or_404(OrdenTrabajo, pk=pk)
    nuevo = request.POST.get("estado")
    if nuevo not in OrdenTrabajo.Estado.values:
        messages.error(request, "Estado no válido.")
        return redirect(o)
    o.estado = nuevo
    o.save(update_fields=["estado", "actualizado"])
    messages.success(request, f"Orden {o.numero}: {o.get_estado_display().lower()}.")
    return redirect(o)


# ---------------------------------------------------------------- informes (técnico)


@login_required
def informes(request):
    """«Generar informe»: el técnico reporta lo hecho en una de sus órdenes. Debajo, sus informes anteriores."""
    form = InformeForm(request.POST or None, tecnico=request.user, initial={"orden": request.GET.get("orden")})
    if form.is_valid():
        with transaction.atomic():
            inf = form.save(commit=False)
            inf.tecnico = request.user
            inf.creado_por = request.user
            inf.save()
            orden = inf.orden
            nuevo = OrdenTrabajo.Estado.TERMINADA if inf.trabajo_terminado else OrdenTrabajo.Estado.EN_CURSO
            if orden.estado != nuevo and orden.estado != OrdenTrabajo.Estado.TERMINADA:
                orden.estado = nuevo
                orden.save(update_fields=["estado", "actualizado"])
        texto = f"Informe de {orden.numero} guardado."
        if inf.trabajo_terminado:
            texto += " La orden quedó como terminada."
        messages.success(request, texto)
        return redirect("trabajos:informes")
    mios = Informe.objects.filter(tecnico=request.user).select_related("orden", "orden__cliente")[:30]
    return render(request, "trabajos/informes.html", {
        "form": form, "mios": mios, "hay_ordenes": form.fields["orden"].queryset.exists(),
    })


# ---------------------------------------------------------------- técnicos (Manager)


@requiere_rol(MANAGER)
def tecnicos_lista(request):
    abiertas = [OrdenTrabajo.Estado.PENDIENTE, OrdenTrabajo.Estado.EN_CURSO]
    inicio_mes = timezone.localdate().replace(day=1)
    lista = (
        tecnicos_y_desactivados()
        .select_related("perfil_tecnico")
        .annotate(
            abiertas=Count("ordenes_asignadas", filter=Q(ordenes_asignadas__estado__in=abiertas), distinct=True),
            terminadas=Count("ordenes_asignadas", filter=Q(ordenes_asignadas__estado=OrdenTrabajo.Estado.TERMINADA), distinct=True),
            informes_mes=Count("informes", filter=Q(informes__fecha__gte=inicio_mes), distinct=True),
        )
    )
    from apps.clientes.views import conteos_directorio

    return render(request, "trabajos/tecnicos.html", {"tecnicos": lista, **conteos_directorio()})


def tecnicos_y_desactivados():
    from django.contrib.auth import get_user_model

    return get_user_model().objects.filter(groups__name=ROLES[TECNICO]).distinct().order_by("-is_active", "first_name", "username")


def _solo_tecnico(usuario):
    """El Manager solo puede editar cuentas que sean únicamente de técnico (no administradores ni managers)."""
    from apps.usuarios.roles import roles_de

    return not usuario.is_superuser and roles_de(usuario) == [TECNICO]


@requiere_rol(MANAGER)
def tecnico_nuevo(request):
    from apps.usuarios.forms import TecnicoForm
    from apps.usuarios.roles import asignar_roles

    form = TecnicoForm(request.POST or None, actor=request.user)
    if form.is_valid():
        u = form.save(commit=False)
        u.set_password(form.cleaned_data["password1"])
        u.save()
        asignar_roles(u, [TECNICO])
        form.guardar_perfil(u)
        messages.success(request, f"Técnico «{u.username}» creado. Ya puede iniciar sesión.")
        return redirect("trabajos:tecnicos")
    from apps.usuarios.forms import GRADOS_SUGERIDOS

    return render(request, "trabajos/tecnico_form.html", {"form": form, "titulo": "Nuevo técnico", "grados": GRADOS_SUGERIDOS})


@requiere_rol(MANAGER)
def tecnico_editar(request, pk):
    from django.contrib.auth import get_user_model
    from django.contrib.auth import update_session_auth_hash

    from apps.usuarios.forms import GRADOS_SUGERIDOS, TecnicoForm

    usuario = get_object_or_404(get_user_model(), pk=pk)
    if not _solo_tecnico(usuario):
        messages.error(request, "Esa cuenta tiene otros roles: se administra desde Usuarios.")
        return redirect("trabajos:tecnicos")
    form = TecnicoForm(request.POST or None, instance=usuario, actor=request.user)
    if form.is_valid():
        u = form.save(commit=False)
        if "activo" in form.cleaned_data and u != request.user:
            u.is_active = form.cleaned_data["activo"]
        nueva = form.cleaned_data.get("password1")
        if nueva:
            u.set_password(nueva)
        u.save()
        form.guardar_perfil(u)
        if nueva and u == request.user:
            update_session_auth_hash(request, u)
        messages.success(request, f"Técnico «{u.username}» actualizado" + (" y contraseña cambiada." if nueva else "."))
        return redirect("trabajos:tecnicos")
    ordenes = usuario.ordenes_asignadas.select_related("cliente").order_by("-creado")[:20]
    return render(request, "trabajos/tecnico_form.html", {
        "form": form, "cuenta": usuario, "titulo": f"Técnico: {usuario.get_full_name() or usuario.username}", "ordenes": ordenes,
        "grados": GRADOS_SUGERIDOS,
    })


@requiere_rol(MANAGER)
@require_POST
def tecnico_habilitar(request, pk):
    """Habilita o deshabilita la cuenta del técnico (deshabilitada: no puede iniciar sesión)."""
    from django.contrib.auth import get_user_model

    usuario = get_object_or_404(get_user_model(), pk=pk)
    if not _solo_tecnico(usuario) or usuario == request.user:
        messages.error(request, "Esa cuenta no se puede habilitar o deshabilitar desde aquí.")
        return redirect("trabajos:tecnicos")
    usuario.is_active = not usuario.is_active
    usuario.save(update_fields=["is_active"])
    nombre = usuario.get_full_name() or usuario.username
    if usuario.is_active:
        messages.success(request, f"{nombre} quedó habilitado: ya puede iniciar sesión.")
    else:
        messages.success(request, f"{nombre} quedó deshabilitado: ya no puede iniciar sesión.")
    return redirect("trabajos:tecnicos")


@requiere_rol(*GESTION)
def proforma_pdf(request, pk):
    """Proforma en PDF tamaño carta (estructura tipo RIDE: emisor, cliente, detalle, totales, condiciones)."""
    from django.conf import settings
    from django.contrib.staticfiles import finders
    from django.http import HttpResponse
    from django.template.loader import render_to_string
    from django.utils.text import slugify
    from weasyprint import HTML

    from apps.configuracion.models import datos_emisor, tema_proforma

    p = get_object_or_404(Proforma.objects.select_related("cliente", "creado_por"), pk=pk)
    if not p.autorizada:
        messages.error(request, "El PDF se puede generar cuando el Manager haya autorizado la proforma.")
        return redirect(p)
    empresa = datos_emisor()
    logo = empresa.get("logo_ruta") or finders.find(settings.NOVERA_LOGO)
    html = render_to_string("trabajos/proforma_pdf.html", {
        "p": p, "lineas": p.lineas.all(), "empresa": empresa, "tema": tema_proforma(),
        "logo": f"file://{logo}" if logo else None,
        "elaborado_por": (p.creado_por.get_full_name() or p.creado_por.username) if p.creado_por else "",
    })
    pdf = HTML(string=html, base_url=str(settings.BASE_DIR)).write_pdf()
    respuesta = HttpResponse(pdf, content_type="application/pdf")
    nombre = f"Proforma {p.numero} - {slugify(p.cliente.nombre)[:40]}.pdf"
    disposicion = "inline" if request.GET.get("ver") else "attachment"
    respuesta["Content-Disposition"] = f'{disposicion}; filename="{nombre}"'
    return respuesta
