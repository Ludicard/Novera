from decimal import Decimal, InvalidOperation

from django import template
from django.utils.html import format_html

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


@register.simple_tag(takes_context=True)
def url_con(context, **cambios):
    """Query string actual con parámetros cambiados (None o "" los quita). Reinicia la página salvo que se pase."""
    q = context["request"].GET.copy()
    if "page" not in cambios:
        q.pop("page", None)
    for clave, valor in cambios.items():
        if valor in (None, ""):
            q.pop(clave, None)
        else:
            q[clave] = valor
    return "?" + q.urlencode()


@register.simple_tag(takes_context=True)
def columna(context, clave, etiqueta, clase=""):
    """Encabezado ordenable: clic alterna ascendente/descendente."""
    actual = context.get("orden", "")
    activo = actual.lstrip("-") == clave
    desc = actual.startswith("-")
    nuevo = clave if (activo and desc) else f"-{clave}"
    flecha = ("↓" if desc else "↑") if activo else "↕"
    url = url_con(context, orden=nuevo)
    return format_html(
        '<th class="{} {}" aria-sort="{}"><a class="ordenar" href="{}">{} <span class="flecha">{}</span></a></th>',
        clase, "activo" if activo else "", ("descending" if desc else "ascending") if activo else "none",
        url, etiqueta, flecha,
    )
