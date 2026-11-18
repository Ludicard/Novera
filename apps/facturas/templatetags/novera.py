from decimal import Decimal, InvalidOperation

from django import template

from apps.facturas.models import Estado

register = template.Library()

MESES = ["", "Enero", "Febrero", "Marzo", "Abril", "Mayo", "Junio", "Julio",
         "Agosto", "Septiembre", "Octubre", "Noviembre", "Diciembre"]
CLASES_ESTADO = {
    Estado.PENDIENTE: "pendiente",
    Estado.PARCIAL: "parcial",
    Estado.VENCIDA: "vencida",
    Estado.PAGADA: "pagada",
    Estado.ANULADA: "anulada",
}


@register.filter
def dinero(valor):
    """$1,234.56 (formato del Excel original)."""
    if valor in (None, ""):
        return "—"
    try:
        valor = Decimal(valor).quantize(Decimal("0.01"))
    except (InvalidOperation, TypeError, ValueError):
        return valor
    texto = f"${abs(valor):,.2f}"
    return f"-{texto}" if valor < 0 else texto


@register.filter
def periodo(fecha):
    return f"{MESES[fecha.month]} {fecha.year}" if fecha else "—"


@register.inclusion_tag("facturas/_estado.html")
def estado(codigo):
    return {"clase": CLASES_ESTADO.get(codigo, ""), "texto": dict(Estado.choices).get(codigo, codigo)}
