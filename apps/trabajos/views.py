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

from .forms import FORMAS_PAGO_SUGERIDAS, InformeForm, LineasFormSet, OrdenForm, ProformaForm, RecursosFormSet, tecnicos
from .models import Informe, OrdenTrabajo, Proforma, Recurso

GESTION = (ADMINISTRADOR, MANAGER)


def _gestiona(request):
    return request.rol in GESTION


# ---------------------------------------------------------------- proformas


@requiere_rol(*GESTION)
def proformas(request):
    estado = request.GET.get("estado", "")
    q = request.GET.get("q", "").strip()
    qs = Proforma.objects.select_related("cliente").prefetch_related("lineas")
    if estado:
        qs = qs.filter(estado=estado)
    if q:
        qs = qs.filter(Q(numero__icontains=q) | Q(titulo__icontains=q) | Q(cliente__nombre__icontains=q))
    conteos = dict(Proforma.objects.values_list("estado").annotate(n=Count("id")))
    pestanas = [("", "Todas", sum(conteos.values()))] + [(c, n, conteos.get(c, 0)) for c, n in Proforma.Estado.choices]
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
    form = ProformaForm(request.POST or None, instance=proforma, initial=None if proforma else _cliente_inicial(request))
    lineas = LineasFormSet(request.POST or None, instance=form.instance, prefix="lineas")
    if request.method == "POST" and form.is_valid() and lineas.is_valid():
        with transaction.atomic():
            p = form.save(commit=False)
            if not p.pk:
                p.creado_por = request.user
            p.save()
            lineas.instance = p
            lineas.save()
        messages.success(request, f"Proforma {p.numero} guardada por ${p.total:,.2f}.")
        return redirect(p)
    titulo = f"Editar {proforma.numero}" if proforma else "Nueva proforma"
    return render(request, "trabajos/proforma_form.html", {
        "form": form, "lineas": lineas, "titulo": titulo, "proforma": proforma, "formas_pago": FORMAS_PAGO_SUGERIDAS,
        "campos_datos": ["cliente", "titulo", "fecha", "validez_dias", "porcentaje_iva", "descripcion"],
    })


@requiere_rol(*GESTION)
def proforma_nueva(request):
    return _guardar_proforma(request)


@requiere_rol(*GESTION)
def proforma_editar(request, pk):
    proforma = get_object_or_404(Proforma, pk=pk)
    if not proforma.editable:
        messages.error(request, "Una proforma aprobada o rechazada ya no se puede editar.")
        return redirect(proforma)
    return _guardar_proforma(request, proforma)


@requiere_rol(*GESTION)
def proforma(request, pk):
    p = get_object_or_404(Proforma.objects.select_related("cliente"), pk=pk)
    return render(request, "trabajos/proforma.html", {"p": p, "lineas": p.lineas.all(), "orden": getattr(p, "orden", None)})


@requiere_rol(*GESTION)
@require_POST
def proforma_estado(request, pk):
    """Enviar, aprobar (genera la orden de trabajo), rechazar o volver a borrador."""
    p = get_object_or_404(Proforma, pk=pk)
    accion = request.POST.get("accion")
    E = Proforma.Estado
    transiciones = {
        "enviar": ({E.BORRADOR}, E.ENVIADA),
        "aprobar": ({E.BORRADOR, E.ENVIADA}, E.APROBADA),
        "rechazar": ({E.BORRADOR, E.ENVIADA}, E.RECHAZADA),
        "reabrir": ({E.RECHAZADA}, E.BORRADOR),
    }
    if accion not in transiciones or p.estado not in transiciones[accion][0]:
        messages.error(request, "Esa acción no es posible en el estado actual de la proforma.")
        return redirect(p)
    with transaction.atomic():
        p.estado = transiciones[accion][1]
        p.fecha_respuesta = timezone.localdate() if accion in ("aprobar", "rechazar") else None
        p.save(update_fields=["estado", "fecha_respuesta", "actualizado"])
        if accion == "aprobar":
            orden = OrdenTrabajo.desde_proforma(p, request.user)
            messages.success(request, f"Proforma aprobada: se generó la orden {orden.numero}. Completa fechas, horas y herramientas.")
            return redirect("trabajos:orden_editar", pk=orden.pk)
    messages.success(request, f"Proforma {p.numero}: {p.get_estado_display().lower()}.")
    return redirect(p)


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
    return render(request, "trabajos/orden_form.html", {"form": form, "recursos": recursos, "titulo": titulo, "orden": orden})


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

    p = get_object_or_404(Proforma.objects.select_related("cliente", "creado_por"), pk=pk)
    logo = finders.find(settings.NOVERA_LOGO)
    html = render_to_string("trabajos/proforma_pdf.html", {
        "p": p, "lineas": p.lineas.all(), "empresa": settings.NOVERA_EMPRESA,
        "logo": f"file://{logo}" if logo else None,
        "elaborado_por": (p.creado_por.get_full_name() or p.creado_por.username) if p.creado_por else "",
    })
    pdf = HTML(string=html, base_url=str(settings.BASE_DIR)).write_pdf()
    respuesta = HttpResponse(pdf, content_type="application/pdf")
    nombre = f"Proforma {p.numero} - {slugify(p.cliente.nombre)[:40]}.pdf"
    disposicion = "inline" if request.GET.get("ver") else "attachment"
    respuesta["Content-Disposition"] = f'{disposicion}; filename="{nombre}"'
    return respuesta
