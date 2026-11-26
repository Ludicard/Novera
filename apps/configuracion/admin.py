from django.contrib import admin
from django.db.models import Count

from .models import Empresa


@admin.register(Empresa)
class EmpresaAdmin(admin.ModelAdmin):
    list_display = ["id", "nombre", "razon_social", "ruc", "n_cuentas", "creado"]
    search_fields = ["nombre", "razon_social", "ruc"]
    readonly_fields = ["creado", "actualizado", "actualizado_por"]

    def get_queryset(self, request):
        return super().get_queryset(request).annotate(n_cuentas=Count("miembros"))

    @admin.display(description="Cuentas", ordering="n_cuentas")
    def n_cuentas(self, obj):
        return obj.n_cuentas

    def has_delete_permission(self, request, obj=None):
        return False
