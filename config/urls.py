from django.contrib import admin
from django.urls import include, path

from apps.facturas.views import dashboard

admin.site.site_header = "Novera · Administración"
admin.site.site_title = "Novera"

urlpatterns = [
    path("", dashboard, name="dashboard"),
    path("facturas/", include("apps.facturas.urls")),
    path("clientes/", include("apps.clientes.urls")),
    path("cuentas/", include("django.contrib.auth.urls")),
    path("admin/", admin.site.urls),
]
