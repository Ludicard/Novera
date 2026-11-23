from django.urls import path

from . import views

app_name = "clientes"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nuevo/", views.nuevo, name="nuevo"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("rapido/", views.rapido, name="rapido"),
    path("<int:pk>/editar/", views.editar, name="editar"),
    path("equipos/", views.equipos, name="equipos"),
    path("equipos/nuevo/", views.equipo_nuevo, name="equipo_nuevo"),
    path("equipos/<int:pk>/", views.equipo, name="equipo"),
    path("equipos/<int:pk>/editar/", views.equipo_editar, name="equipo_editar"),
]
