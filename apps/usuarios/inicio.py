"""Pantalla de inicio: menú de iconos según el rol activo (como la app de referencia del cliente)."""

from django.contrib.auth.decorators import login_required
from django.db.models import Q
from django.shortcuts import render
from django.urls import reverse
from django.utils import timezone

from apps.facturas.models import Estado, Factura
from apps.trabajos.models import OrdenTrabajo, Proforma, Tarea

from .permisos import requiere_rol
from .roles import ADMINISTRADOR, MANAGER, ROLES, TECNICO

ABIERTAS = [OrdenTrabajo.Estado.PENDIENTE, OrdenTrabajo.Estado.EN_CURSO]


def _mosaicos(request):
    hoy = timezone.localdate()
    if request.rol == TECNICO:
        mias = Tarea.objects.filter(tecnico=request.user).exclude(estado=Tarea.Estado.HECHA)
        atrasadas = mias.filter(fecha_limite__lt=hoy).count()
        return [
            {"icono": "tareas", "titulo": "Mis tareas", "url": reverse("trabajos:mis_tareas"), "color": "naranja",
             "dato": f"{mias.count()} pendiente{'s' if mias.count() != 1 else ''}",
             "alerta": f"{atrasadas} atrasada{'s' if atrasadas != 1 else ''}" if atrasadas else "", "ancho": True},
            {"icono": "orden", "titulo": "Mis órdenes de trabajo", "url": reverse("trabajos:ordenes"), "color": "azul",
             "dato": "Detalle, materiales y herramientas"},
        ]
    abiertas = OrdenTrabajo.objects.filter(estado__in=ABIERTAS)
    sin_tecnico = abiertas.filter(tareas__isnull=True).count()
    vencidas = Factura.objects.con_saldos(hoy).filter(estado=Estado.VENCIDA).count()
    if request.rol == ADMINISTRADOR:
        # El Administrador lleva las proformas; los clientes los administra el Manager (gerente)
        por_responder = Proforma.objects.filter(estado__in=[Proforma.Estado.BORRADOR, Proforma.Estado.ENVIADA]).count()
        primero = {
            "icono": "proforma", "titulo": "Administrar proformas", "url": reverse("trabajos:proformas"), "color": "verde",
            "dato": "Cotizaciones: crear, enviar y aprobar",
            "alerta": f"{por_responder} por responder" if por_responder else "",
        }
    else:
        primero = {"icono": "cliente", "titulo": "Administrar clientes", "url": reverse("clientes:lista"), "color": "verde",
                   "dato": "Datos, RUC, contacto y estado de cuenta"}
    return [
        primero,
        {"icono": "orden", "titulo": "Órdenes de trabajo", "url": reverse("trabajos:ordenes"), "color": "azul",
         "dato": f"{abiertas.count()} abierta{'s' if abiertas.count() != 1 else ''}"},
        {"icono": "asignar", "titulo": "Asignar tareas", "url": reverse("trabajos:asignar"), "color": "naranja",
         "dato": "Qué técnico hace qué orden",
         "alerta": f"{sin_tecnico} sin técnico" if sin_tecnico else ""},
        {"icono": "finanzas", "titulo": "Cargar datos financieros", "url": reverse("finanzas"), "color": "amarillo",
         "dato": "Facturas, pagos e importación",
         "alerta": f"{vencidas} factura{'s' if vencidas != 1 else ''} vencida{'s' if vencidas != 1 else ''}" if vencidas else ""},
        {"icono": "panel", "titulo": "Revisar información general", "url": reverse("dashboard"), "color": "violeta",
         "dato": "Facturación, cobros y cartera", "ancho": True},
    ]


@login_required
def inicio(request):
    return render(request, "inicio.html", {"mosaicos": _mosaicos(request), "rol_nombre_largo": ROLES.get(request.rol, "")})


@requiere_rol(ADMINISTRADOR, MANAGER)
def finanzas(request):
    hoy = timezone.localdate()
    abiertas = Factura.objects.por_cobrar(hoy)
    return render(request, "finanzas.html", {
        "n_por_cobrar": abiertas.count(),
        "n_vencidas": abiertas.filter(estado=Estado.VENCIDA).count(),
        "ultima_importada": Factura.objects.filter(importada=True).order_by("-creado").values_list("creado", flat=True).first(),
        "sin_cliente": Factura.objects.filter(Q(cliente__isnull=True), anulada=False).count(),
    })
