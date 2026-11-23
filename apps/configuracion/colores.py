"""Paleta derivada de un color base (#RRGGBB): tonos claros, uno oscuro legible y el color de texto encima."""

import re

AZUL_POR_DEFECTO = "#1F4E5F"
PATRON = re.compile(r"^#?([0-9a-fA-F]{6})$")


def normalizar(codigo):
    """«d9a21b», «#D9A21B» → «#D9A21B». Vacío → «». Inválido → ValueError."""
    codigo = (codigo or "").strip()
    if not codigo:
        return ""
    m = PATRON.match(codigo)
    if not m:
        raise ValueError(codigo)
    return "#" + m.group(1).upper()


def _rgb(codigo):
    codigo = codigo.lstrip("#")
    return tuple(int(codigo[i:i + 2], 16) for i in (0, 2, 4))


def _hex(rgb):
    return "#" + "".join(f"{max(0, min(255, round(c))):02X}" for c in rgb)


def _mezclar(codigo, con, proporcion):
    a, b = _rgb(codigo), _rgb(con)
    return _hex(tuple(x + (y - x) * proporcion for x, y in zip(a, b)))


def luminancia(codigo):
    def canal(c):
        c /= 255
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4

    r, g, b = (canal(c) for c in _rgb(codigo))
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def contraste(a, b):
    la, lb = sorted((luminancia(a), luminancia(b)), reverse=True)
    return (la + 0.05) / (lb + 0.05)


def paleta(codigo):
    """Todo lo que necesitan la app y el PDF a partir de un color base."""
    base = normalizar(codigo) or AZUL_POR_DEFECTO
    oscuro_texto = "#1D2733"
    sobre = "#FFFFFF" if contraste(base, "#FFFFFF") >= contraste(base, oscuro_texto) else oscuro_texto
    # Un tono del color que se lea sobre blanco (títulos, enlaces): se oscurece hasta contraste ≥ 4.5
    legible, paso = base, 0.0
    while contraste(legible, "#FFFFFF") < 4.5 and paso < 0.9:
        paso += 0.05
        legible = _mezclar(base, "#000000", paso)
    return {
        "base": base,
        "sobre": sobre,                                 # texto encima del color base
        "legible": legible,                             # el color usado como texto sobre blanco
        "claro": _mezclar(base, "#FFFFFF", 0.88),       # fondos suaves (activo, filas alternas)
        "suave": _mezclar(base, "#FFFFFF", 0.94),
        "borde": _mezclar(base, "#FFFFFF", 0.6),
        "hover": _mezclar(base, "#000000", 0.12),
        "oscuro": _mezclar(base, "#000000", 0.28),
        "es_defecto": not normalizar(codigo),
    }
