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
from apps.usuarios.roles import ADMINISTRADOR, MANAGER, TECNICO

from .forms import AvanceTareaForm, LineasFormSet, OrdenForm, ProformaForm, RecursosFormSet, TareaForm, tecnicos
from .models import OrdenTrabajo, Proforma, Recurso, Tarea

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
    return {"cliente": cliente} if cliente.isdigit() else None


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
    return render(request, "trabajos/proforma_form.html", {"form": form, "lineas": lineas, "titulo": titulo, "proforma": proforma})


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
    """Gestión: todas. Técnico: solo las órdenes en las que tiene tareas (solo lectura)."""
    estado = request.GET.get("estado", "abiertas")
    q = request.GET.get("q", "").strip()
    base = OrdenTrabajo.objects.select_related("cliente").annotate(
        n_tareas=Count("tareas", distinct=True),
        n_hechas=Count("tareas", filter=Q(tareas__estado=Tarea.Estado.HECHA), distinct=True),
    )
    if not _gestiona(request):
        base = base.filter(tareas__tecnico=request.user).distinct()
    abiertas = [OrdenTrabajo.Estado.PENDIENTE, OrdenTrabajo.Estado.EN_CURSO]
    conteos = {
        "abiertas": base.filter(estado__in=abiertas).count(),
        "sin_tecnico": base.filter(estado__in=abiertas, n_tareas=0).count(),
        **{c: base.filter(estado=c).count() for c, _ in OrdenTrabajo.Estado.choices},
    }
    qs = base
    if estado == "abiertas":
        qs = qs.filter(estado__in=abiertas)
    elif estado == "sin_tecnico":
        qs = qs.filter(estado__in=abiertas, n_tareas=0)
    elif estado in OrdenTrabajo.Estado.values:
        qs = qs.filter(estado=estado)
    if q:
        qs = qs.filter(Q(numero__icontains=q) | Q(titulo__icontains=q) | Q(cliente__nombre__icontains=q))
    qs = qs.order_by("fecha_fin", "-creado") if estado in ("abiertas", "sin_tecnico") else qs.order_by("-creado")
    pestanas = [("abiertas", "Abiertas"), ("sin_tecnico", "Sin técnico")] if _gestiona(request) else [("abiertas", "Abiertas")]
    pestanas += [(c, n) for c, n in OrdenTrabajo.Estado.choices]
    pagina = Paginator(qs, 50).get_page(request.GET.get("page"))
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
    if not gestiona and not o.tareas.filter(tecnico=request.user).exists():
        raise Http404
    return render(request, "trabajos/orden.html", {
        "o": o, "gestiona": gestiona,
        "materiales": o.recursos.filter(tipo=Recurso.Tipo.MATERIAL),
        "herramientas": o.recursos.filter(tipo=Recurso.Tipo.HERRAMIENTA),
        "tareas": o.tareas.select_related("tecnico"),
        "tarea_form": TareaForm(orden=o) if gestiona else None,
        "hay_tecnicos": tecnicos().exists(),
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


# ---------------------------------------------------------------- tareas


@requiere_rol(*GESTION)
def asignar(request):
    """Qué técnico hace qué orden: formulario de asignación + carga de trabajo de cada técnico."""
    form = TareaForm(request.POST or None, initial={"orden": request.GET.get("orden")})
    if form.is_valid():
        t = form.save(commit=False)
        t.creado_por = request.user
        t.save()
        if t.orden.estado == OrdenTrabajo.Estado.PENDIENTE and t.orden.fecha_inicio and t.orden.fecha_inicio <= timezone.localdate():
            t.orden.estado = OrdenTrabajo.Estado.EN_CURSO
            t.orden.save(update_fields=["estado", "actualizado"])
        nombre = t.tecnico.get_full_name() or t.tecnico.username
        messages.success(request, f"{nombre} quedó asignado a {t.orden.numero}.")
        destino = request.POST.get("volver")
        return redirect(t.orden if destino == "orden" else "trabajos:asignar")
    if request.method == "POST" and request.POST.get("volver") == "orden" and form.cleaned_data.get("orden"):
        for e in form.errors.values():
            messages.error(request, " ".join(e))
        return redirect(form.cleaned_data["orden"])

    abiertas = [Tarea.Estado.PENDIENTE, Tarea.Estado.EN_CURSO]
    carga = tecnicos().annotate(
        pendientes=Count("tareas", filter=Q(tareas__estado__in=abiertas)),
        hechas=Count("tareas", filter=Q(tareas__estado=Tarea.Estado.HECHA)),
    )
    sin_tecnico = OrdenTrabajo.objects.filter(
        estado__in=[OrdenTrabajo.Estado.PENDIENTE, OrdenTrabajo.Estado.EN_CURSO], tareas__isnull=True
    ).select_related("cliente")
    recientes = Tarea.objects.select_related("orden", "orden__cliente", "tecnico").filter(estado__in=abiertas).order_by("fecha_limite", "-creado")[:30]
    return render(request, "trabajos/asignar.html", {
        "form": form, "carga": carga, "sin_tecnico": sin_tecnico, "recientes": recientes, "hay_tecnicos": tecnicos().exists(),
    })


@requiere_rol(*GESTION)
@require_POST
def tarea_quitar(request, pk):
    t = get_object_or_404(Tarea, pk=pk)
    orden = t.orden
    t.delete()
    messages.success(request, "Asignación eliminada.")
    return redirect(orden)


@login_required
def mis_tareas(request):
    ver = request.GET.get("ver", "pendientes")
    qs = Tarea.objects.filter(tecnico=request.user).select_related("orden", "orden__cliente")
    if ver == "pendientes":
        qs = qs.exclude(estado=Tarea.Estado.HECHA)
    elif ver == "hechas":
        qs = qs.filter(estado=Tarea.Estado.HECHA).order_by("-completada")
    conteos = {
        "pendientes": Tarea.objects.filter(tecnico=request.user).exclude(estado=Tarea.Estado.HECHA).count(),
        "hechas": Tarea.objects.filter(tecnico=request.user, estado=Tarea.Estado.HECHA).count(),
    }
    tareas = list(qs)
    for t in tareas:
        t.form = AvanceTareaForm(instance=t, prefix=f"t{t.pk}")
    return render(request, "trabajos/mis_tareas.html", {"tareas": tareas, "ver": ver, "conteos": conteos})


@login_required
@require_POST
def tarea_avance(request, pk):
    t = get_object_or_404(Tarea, pk=pk)
    if t.tecnico != request.user and not _gestiona(request):
        raise Http404
    form = AvanceTareaForm(request.POST, instance=t, prefix=f"t{t.pk}")
    if form.is_valid():
        t = form.save(commit=False)
        t.completada = timezone.now() if t.estado == Tarea.Estado.HECHA else None
        t.save()
        orden = t.orden
        if t.estado != Tarea.Estado.PENDIENTE and orden.estado == OrdenTrabajo.Estado.PENDIENTE:
            orden.estado = OrdenTrabajo.Estado.EN_CURSO
            orden.save(update_fields=["estado", "actualizado"])
        messages.success(request, f"Tarea de {orden.numero}: {t.get_estado_display().lower()}.")
    else:
        messages.error(request, "No se pudo guardar el avance.")
    if request.POST.get("volver") == "orden":
        return redirect(t.orden)
    return redirect("trabajos:mis_tareas")
