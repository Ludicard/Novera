from django.urls import path

from . import views

app_name = "trabajos"

urlpatterns = [
    path("ordenes/", views.ordenes, name="ordenes"),
    path("ordenes/nueva/", views.orden_nueva, name="orden_nueva"),
    path("ordenes/<int:pk>/", views.orden, name="orden"),
    path("ordenes/<int:pk>/editar/", views.orden_editar, name="orden_editar"),
    path("ordenes/<int:pk>/estado/", views.orden_estado, name="orden_estado"),
    path("proformas/", views.proformas, name="proformas"),
    path("proformas/nueva/", views.proforma_nueva, name="proforma_nueva"),
    path("proformas/<int:pk>/", views.proforma, name="proforma"),
    path("proformas/<int:pk>/editar/", views.proforma_editar, name="proforma_editar"),
    path("proformas/<int:pk>/estado/", views.proforma_estado, name="proforma_estado"),
    path("asignar/", views.asignar, name="asignar"),
    path("tareas/<int:pk>/quitar/", views.tarea_quitar, name="tarea_quitar"),
    path("tareas/<int:pk>/avance/", views.tarea_avance, name="tarea_avance"),
    path("mis-tareas/", views.mis_tareas, name="mis_tareas"),
]
