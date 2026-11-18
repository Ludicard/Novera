from django.contrib import admin
from django.db import connection
from django.http import HttpResponse
from django.urls import include, path

from apps.facturas.views import dashboard

admin.site.site_header = "Novera · Administración"
admin.site.site_title = "Novera"



def salud(request):
    """Healthcheck: responde 200 si Django y la base de datos funcionan."""
    connection.ensure_connection()
    return HttpResponse("ok", content_type="text/plain")


urlpatterns = [
    path("salud/", salud, name="salud"),
    path("", dashboard, name="dashboard"),
    path("facturas/", include("apps.facturas.urls")),
    path("clientes/", include("apps.clientes.urls")),
    path("cuentas/", include("django.contrib.auth.urls")),
    path("admin/", admin.site.urls),
]
