from django.contrib import admin, messages
from django.db import transaction

from .models import Cliente


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ["nombre", "identificacion", "dias_credito", "activo"]
    list_filter = ["activo"]
    search_fields = ["nombre", "identificacion"]
    actions = ["fusionar"]

    @admin.action(description="Fusionar clientes seleccionados (mismo cliente escrito distinto)")
    def fusionar(self, request, queryset):
        """Conserva el que tiene RUC (o el más antiguo) y le pasa las facturas de los demás."""
        clientes = sorted(queryset, key=lambda c: (not c.identificacion, c.pk))
        if len(clientes) < 2:
            self.message_user(request, "Selecciona al menos dos clientes.", messages.WARNING)
            return
        destino, otros = clientes[0], clientes[1:]
        with transaction.atomic():
            for otro in otros:
                otro.facturas.update(cliente=destino)
                if not destino.notas and otro.notas:
                    destino.notas = otro.notas
                otro.delete()
            destino.save()
        nombres = ", ".join(o.nombre for o in otros)
        self.message_user(request, f"Fusionados en «{destino}»: {nombres}.", messages.SUCCESS)
