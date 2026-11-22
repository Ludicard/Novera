from django.contrib import admin

from .models import LineaProforma, OrdenTrabajo, Proforma, Recurso, Tarea


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


class TareaInline(admin.TabularInline):
    model = Tarea
    extra = 0
    fields = ["tecnico", "responsabilidades", "fecha_limite", "horas_estimadas", "estado"]


@admin.register(OrdenTrabajo)
class OrdenAdmin(admin.ModelAdmin):
    list_display = ["numero", "cliente", "titulo", "fecha_inicio", "fecha_fin", "estado"]
    list_filter = ["estado"]
    search_fields = ["numero", "titulo", "cliente__nombre"]
    autocomplete_fields = ["cliente"]
    inlines = [RecursoInline, TareaInline]
