from django.contrib import admin
from django.contrib.auth.views import LoginView
from django.db import connection
from django.http import HttpResponse
from django.urls import include, path

from apps.facturas.views import dashboard
from apps.usuarios.inicio import finanzas, informacion_general, inicio
from apps.usuarios.views import registro

admin.site.site_header = "Novera · Administración"
admin.site.site_title = "Novera"



def salud(request):
    """Healthcheck: responde 200 si Django y la base de datos funcionan."""
    connection.ensure_connection()
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("salud/", salud, name="salud"),
    path("", inicio, name="inicio"),
    path("panel/", dashboard, name="dashboard"),
    path("finanzas/", finanzas, name="finanzas"),
    path("informacion/", informacion_general, name="informacion"),
    path("trabajos/", include("apps.trabajos.urls")),
    path("facturas/", include("apps.facturas.urls")),
    path("clientes/", include("apps.clientes.urls")),
    path("cuentas/registro/", registro, name="registro"),
    path("cuentas/login/", LoginView.as_view(redirect_authenticated_user=True), name="login"),
    path("cuentas/", include("django.contrib.auth.urls")),
    path("usuarios/", include("apps.usuarios.urls")),
    path("configuracion/", include("apps.configuracion.urls")),
    path("admin/", admin.site.urls),
]
