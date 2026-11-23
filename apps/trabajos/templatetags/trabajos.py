from django import template

register = template.Library()

CLASES = {
    # órdenes y tareas
    "PENDIENTE": "pendiente", "EN_CURSO": "parcial", "TERMINADA": "pagada", "CANCELADA": "anulada", "HECHA": "pagada",
    # proformas
    "BORRADOR": "anulada", "POR_AUTORIZAR": "parcial", "DEVUELTA": "vencida", "AUTORIZADA": "pendiente",
    "ENVIADA": "pendiente", "APROBADA": "pagada", "RECHAZADA": "vencida",
}


@register.simple_tag
def insignia(obj):
    """<span class="estado …">Etiqueta</span> para proformas, órdenes y tareas."""
    from django.utils.html import format_html

    return format_html('<span class="estado {}">{}</span>', CLASES.get(obj.estado, ""), obj.get_estado_display())


@register.filter
def nombre(usuario):
    return (usuario.get_full_name() or usuario.username) if usuario else "—"
