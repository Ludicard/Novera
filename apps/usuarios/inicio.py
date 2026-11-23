"""Pantalla de inicio: menú de mosaicos según el rol activo, e «Información general» del Manager."""

from django.contrib.auth.decorators import login_required
from django.db.models import Count, Q
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente, Equipo
from apps.facturas.models import Estado, Factura
from apps.trabajos.models import Informe, OrdenTrabajo, Proforma

from .permisos import requiere_rol
from .roles import ADMINISTRADOR, MANAGER, ROLES, TECNICO

ABIERTAS = [OrdenTrabajo.Estado.PENDIENTE, OrdenTrabajo.Estado.EN_CURSO]


def _plural(n, palabra, sufijo="s"):
    return f"{n} {palabra}{sufijo if n != 1 else ''}"


def _mosaicos(request):
    hoy = timezone.localdate()
    if request.rol == TECNICO:
        mias = OrdenTrabajo.objects.filter(tecnicos=request.user, estado__in=ABIERTAS)
        atrasadas = mias.filter(fecha_fin__lt=hoy).count()
        return [
            {"icono": "orden", "titulo": "Mis órdenes de trabajo", "url": reverse("trabajos:ordenes"), "color": "azul",
             "dato": _plural(mias.count(), "abierta"), "alerta": _plural(atrasadas, "atrasada") if atrasadas else ""},
            {"icono": "informe", "titulo": "Generar informe", "url": reverse("trabajos:informes"), "color": "naranja",
             "dato": "Lo realizado en una orden"},
        ]

    abiertas = OrdenTrabajo.objects.filter(estado__in=ABIERTAS)
    sin_tecnico = abiertas.filter(tecnicos__isnull=True).count()
    por_responder = Proforma.objects.filter(estado__in=[Proforma.Estado.BORRADOR, Proforma.Estado.ENVIADA]).count()
    proformas = {"icono": "proforma", "titulo": "Administrar proformas", "url": reverse("trabajos:proformas"),
                 "color": "verde", "dato": "Cotizaciones: crear, enviar y aprobar",
                 "alerta": f"{por_responder} por responder" if por_responder else ""}
    ordenes = {"icono": "orden", "titulo": "Administrar órdenes de trabajo", "url": reverse("trabajos:ordenes"),
               "color": "azul", "dato": _plural(abiertas.count(), "abierta"),
               "alerta": f"{sin_tecnico} sin técnico" if sin_tecnico else ""}

    if request.rol == MANAGER:
        from apps.clientes.views import conteos_directorio

        conteos = conteos_directorio()
        n_clientes, n_tecnicos = conteos["n_clientes"], conteos["n_tecnicos"]
        return [
            {"icono": "cliente", "titulo": "Administrar clientes y técnicos", "url": reverse("clientes:lista"),
             "color": "verde", "dato": f"{_plural(n_clientes, 'cliente')} · {_plural(n_tecnicos, 'técnico')}"},
            {"icono": "equipo", "titulo": "Administrar equipos", "url": reverse("clientes:equipos"), "color": "amarillo",
             "dato": "Ascensores y equipos de cada cliente"},
            proformas,
            ordenes,
            {"icono": "panel", "titulo": "Revisar información general", "url": reverse("informacion"), "color": "violeta",
             "dato": "Órdenes, proformas y técnicos", "ancho": True},
        ]

    # Administrador
    vencidas = Factura.objects.con_saldos(hoy).filter(estado=Estado.VENCIDA).count()
    return [
        proformas,
        ordenes,
        {"icono": "factura", "titulo": "Generar factura o recibo", "url": reverse("facturas:nueva"), "color": "amarillo",
         "dato": "Registrar o importar de FactureroMovil"},
        {"icono": "finanzas", "titulo": "Cargar pagos", "url": reverse("finanzas"), "color": "naranja",
         "dato": "Cobros, abonos y retenciones",
         "alerta": f"{_plural(vencidas, 'factura')} vencida{'s' if vencidas != 1 else ''}" if vencidas else ""},
        {"icono": "panel", "titulo": "Revisar datos financieros", "url": reverse("dashboard"), "color": "violeta",
         "dato": "Facturación, cobros y cartera", "ancho": True},
    ]


@login_required
def inicio(request):
    mosaicos = _mosaicos(request)
    return render(request, "inicio.html", {
        "mosaicos": mosaicos, "rol_nombre_largo": ROLES.get(request.rol, ""),
        "columnas": 3 if len(mosaicos) == 6 else 4,
    })


@requiere_rol(ADMINISTRADOR)
def finanzas(request):
    """«Cargar pagos»: registrar cobros de facturas, en lote o desde el reporte de FactureroMovil."""
    hoy = timezone.localdate()
    abiertas = Factura.objects.por_cobrar(hoy)
    return render(request, "finanzas.html", {
        "n_por_cobrar": abiertas.count(),
        "n_vencidas": abiertas.filter(estado=Estado.VENCIDA).count(),
        "ultima_importada": Factura.objects.filter(importada=True).order_by("-creado").values_list("creado", flat=True).first(),
    })


@requiere_rol(ADMINISTRADOR, MANAGER)
def informacion_general(request):
    """Resumen operativo para el Manager: órdenes, proformas, técnicos, equipos e informes."""
    hoy = timezone.localdate()
    inicio_mes = hoy.replace(day=1)
    abiertas = OrdenTrabajo.objects.filter(estado__in=ABIERTAS)
    pf_mes = Proforma.objects.filter(fecha__gte=inicio_mes)
    pf_respondidas = Proforma.objects.filter(estado__in=[Proforma.Estado.APROBADA, Proforma.Estado.RECHAZADA])
    aprobadas = pf_respondidas.filter(estado=Proforma.Estado.APROBADA).count()
    from apps.trabajos.views import tecnicos_y_desactivados

    carga = (
        tecnicos_y_desactivados().filter(is_active=True)
        .annotate(
            abiertas=Count("ordenes_asignadas", filter=Q(ordenes_asignadas__estado__in=ABIERTAS), distinct=True),
            informes_mes=Count("informes", filter=Q(informes__fecha__gte=inicio_mes), distinct=True),
        )
    )
    return render(request, "informacion.html", {
        "hoy": hoy,
        "kpis": {
            "abiertas": abiertas.count(),
            "atrasadas": abiertas.filter(fecha_fin__lt=hoy).count(),
            "sin_tecnico": abiertas.filter(tecnicos__isnull=True).count(),
            "terminadas_mes": OrdenTrabajo.objects.filter(estado=OrdenTrabajo.Estado.TERMINADA, actualizado__date__gte=inicio_mes).count(),
            "pf_por_responder": Proforma.objects.filter(estado__in=[Proforma.Estado.BORRADOR, Proforma.Estado.ENVIADA]).count(),
            "pf_mes": pf_mes.count(),
            "tasa_aprobacion": round(aprobadas / pf_respondidas.count() * 100) if pf_respondidas.exists() else None,
            "clientes": Cliente.objects.filter(activo=True).count(),
            "equipos": Equipo.objects.filter(activo=True).count(),
            "informes_mes": Informe.objects.filter(fecha__gte=inicio_mes).count(),
        },
        "atrasadas": abiertas.filter(fecha_fin__lt=hoy).select_related("cliente").order_by("fecha_fin")[:8],
        "proximas": abiertas.filter(fecha_fin__gte=hoy).select_related("cliente").order_by("fecha_fin")[:8],
        "carga": carga,
        "ultimos_informes": Informe.objects.select_related("orden", "tecnico").order_by("-fecha", "-creado")[:8],
    })
