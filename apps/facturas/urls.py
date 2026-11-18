from django.urls import path

from . import views

app_name = "facturas"

urlpatterns = [
    path("", views.lista, name="lista"),
    path("nueva/", views.nueva, name="nueva"),
    path("exportar/", views.exportar, name="exportar"),
    path("importar/", views.importar, name="importar"),
    path("<int:pk>/", views.detalle, name="detalle"),
    path("<int:pk>/editar/", views.editar, name="editar"),
    path("<int:pk>/anular/", views.anular, name="anular"),
    path("<int:pk>/pagos/", views.registrar_pago, name="registrar_pago"),
    path("<int:pk>/pagos/<int:pago_pk>/eliminar/", views.eliminar_pago, name="eliminar_pago"),
]
