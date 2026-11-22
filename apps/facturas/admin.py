"""Admin avanzado (solo superusuarios). Aplica las mismas reglas de dinero que la app."""

from decimal import Decimal

from django import forms
from django.contrib import admin

from apps.facturas.templatetags.novera import dinero

from .models import Estado, Factura, Pago


class PagoInlineFormSet(forms.BaseInlineFormSet):
    def clean(self):
        super().clean()
        factura = self.instance
        if not factura.pk or any(f.errors for f in self.forms):
            return
        total = sum(
            (f.cleaned_data.get("monto") or Decimal("0"))
            for f in self.forms
            if f.cleaned_data and not f.cleaned_data.get("DELETE")
        )
        if factura.anulada and total:
            raise forms.ValidationError("Una factura anulada no puede tener pagos.")
        if total > factura.total:
            raise forms.ValidationError(f"Los pagos ({dinero(total)}) superan el total de la factura ({dinero(factura.total)}).")


class PagoInline(admin.TabularInline):
    model = Pago
    formset = PagoInlineFormSet
    extra = 0
    fields = ["fecha", "forma", "referencia", "monto", "notas"]


class FacturaAdminForm(forms.ModelForm):
    class Meta:
        model = Factura
        fields = "__all__"

    def clean(self):
        datos = super().clean()
        subtotal, pct = datos.get("subtotal"), datos.get("porcentaje_iva")
        if self.instance.pk and subtotal is not None and pct is not None:
            prueba = Factura(subtotal=subtotal, porcentaje_iva=pct)
            prueba.calcular_montos()
            if prueba.total < self.instance.total_pagado():
                raise forms.ValidationError(
                    f"El nuevo total ({dinero(prueba.total)}) sería menor que lo ya cobrado "
                    f"({dinero(self.instance.total_pagado())})."
                )
        return datos


@admin.register(Factura)
class FacturaAdmin(admin.ModelAdmin):
    form = FacturaAdminForm
    list_display = ["numero", "cliente", "fecha_emision", "fecha_cobro", "total", "saldo_col", "estado_col"]
    list_filter = ["anulada", "tipo", "importada"]
    search_fields = ["numero", "objeto", "cliente__nombre", "clave_acceso"]
    autocomplete_fields = ["cliente"]
    readonly_fields = ["iva", "total", "creado", "actualizado", "creado_por"]
    inlines = [PagoInline]

    def get_queryset(self, request):
        return super().get_queryset(request).con_saldos()

    @admin.display(description="Saldo", ordering="saldo")
    def saldo_col(self, obj):
        return dinero(obj.saldo) if not obj.anulada else "—"

    @admin.display(description="Estado", ordering="estado")
    def estado_col(self, obj):
        return Estado(obj.estado).label

    def save_model(self, request, obj, form, change):
        obj.calcular_montos()  # IVA y total siempre derivados del valor y el %
        if not change:
            obj.creado_por = request.user
        super().save_model(request, obj, form, change)


class PagoAdminForm(forms.ModelForm):
    class Meta:
        model = Pago
        fields = "__all__"

    def clean(self):
        datos = super().clean()
        factura, monto = datos.get("factura"), datos.get("monto")
        if factura and monto:
            if factura.anulada:
                raise forms.ValidationError("Una factura anulada no puede tener pagos.")
            otros = factura.pagos.exclude(pk=self.instance.pk).values_list("monto", flat=True)
            saldo = factura.total - sum(otros, Decimal("0"))
            if monto > saldo:
                self.add_error("monto", f"El pago supera el saldo pendiente ({dinero(saldo)}).")
        return datos


@admin.register(Pago)
class PagoAdmin(admin.ModelAdmin):
    form = PagoAdminForm
    list_display = ["factura", "fecha", "forma", "referencia", "monto"]
    list_filter = ["forma"]
    search_fields = ["factura__numero", "referencia"]
    autocomplete_fields = ["factura"]
