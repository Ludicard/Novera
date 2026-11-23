from django.contrib import admin, messages
from django.db import transaction

from .models import Cliente, Equipo


@admin.register(Cliente)
class ClienteAdmin(admin.ModelAdmin):
    list_display = ["nombre", "identificacion", "dias_credito", "activo"]
    list_filter = ["activo"]
    search_fields = ["nombre", "identificacion"]
    actions = ["fusionar"]

    @admin.action(description="Fusionar clientes seleccionados (mismo cliente escrito distinto)")
    def fusionar(self, request, queryset):
        """Conserva el que tiene RUC (o el más antiguo), le pasa las facturas de los demás y completa sus datos vacíos."""
        clientes = sorted(queryset, key=lambda c: (not c.identificacion, c.pk))
        if len(clientes) < 2:
            self.message_user(request, "Selecciona al menos dos clientes.", messages.WARNING)
            return
        destino, otros = clientes[0], clientes[1:]
        with transaction.atomic():
            for otro in otros:
                otro.facturas.update(cliente=destino)
                # Completa los datos vacíos del que se conserva con los de los demás
                for campo in ("identificacion", "email", "telefono", "direccion", "notas"):
                    if not getattr(destino, campo) and getattr(otro, campo):
                        setattr(destino, campo, getattr(otro, campo))
                otro.delete()
            destino.save()
        nombres = ", ".join(o.nombre for o in otros)
        self.message_user(request, f"Fusionados en «{destino}»: {nombres}.", messages.SUCCESS)


@admin.register(Equipo)
class EquipoAdmin(admin.ModelAdmin):
    list_display = ["nombre", "cliente", "tipo", "marca", "modelo", "activo"]
    list_filter = ["tipo", "activo"]
    search_fields = ["nombre", "cliente__nombre", "marca", "modelo", "numero_serie"]
    autocomplete_fields = ["cliente"]
