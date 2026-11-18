from django.contrib import admin

from .models import Factura, Pago


class PagoInline(admin.TabularInline):
    model = Pago
    extra = 0
    fields = ["fecha", "forma", "referencia", "monto", "notas"]


@admin.register(Factura)
class FacturaAdmin(admin.ModelAdmin):
    list_display = ["numero", "cliente", "periodo", "fecha_emision", "fecha_cobro", "total", "anulada"]
    list_filter = ["anulada", "tipo", "importada", "periodo"]
    search_fields = ["numero", "objeto", "cliente__nombre"]
    autocomplete_fields = ["cliente"]
    date_hierarchy = "fecha_emision"
    readonly_fields = ["creado", "actualizado", "creado_por"]
    inlines = [PagoInline]


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    list_display = ["factura", "fecha", "forma", "referencia", "monto"]
    list_filter = ["forma"]
    search_fields = ["factura__numero", "referencia"]
    autocomplete_fields = ["factura"]
    date_hierarchy = "fecha"
