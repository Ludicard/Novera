from django.urls import path

from . import views

app_name = "usuarios"

urlpatterns = [
    path("", views.usuarios_lista, name="lista"),
    path("nueva/", views.usuario_nuevo, name="nueva"),
    path("<int:pk>/", views.usuario_editar, name="editar"),
    path("<int:pk>/activar/", views.usuario_activar, name="activar"),
    path("rol/", views.elegir_rol, name="elegir_rol"),
]
