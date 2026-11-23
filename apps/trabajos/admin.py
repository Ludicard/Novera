from django.contrib import admin

from .models import Informe, LineaProforma, OrdenTrabajo, Proforma, Recurso


class LineaInline(admin.TabularInline):
    model = LineaProforma
    extra = 0


@admin.register(Proforma)
class ProformaAdmin(admin.ModelAdmin):
    list_display = ["numero", "cliente", "titulo", "fecha", "estado"]
    list_filter = ["estado"]
    search_fields = ["numero", "titulo", "cliente__nombre"]
    autocomplete_fields = ["cliente"]
    inlines = [LineaInline]


class RecursoInline(admin.TabularInline):
    model = Recurso
    extra = 0


class InformeInline(admin.StackedInline):
    model = Informe
    extra = 0
    fields = ["tecnico", "fecha", "horas_trabajadas", "trabajo_realizado", "materiales_usados", "observaciones", "trabajo_terminado"]


@admin.register(OrdenTrabajo)
class OrdenAdmin(admin.ModelAdmin):
    list_display = ["numero", "cliente", "titulo", "fecha_inicio", "fecha_fin", "estado"]
    list_filter = ["estado"]
    search_fields = ["numero", "titulo", "cliente__nombre"]
    autocomplete_fields = ["cliente"]
    inlines = [RecursoInline, InformeInline]
    filter_horizontal = ["tecnicos"]
