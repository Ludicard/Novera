"""Empresas de Novera. Cada cuenta pertenece a una empresa y solo ve sus datos (ver `actual.py`).

Quien se registra crea su empresa y queda como su Administrador; los datos del emisor de proformas (razón social,
RUC, logo…) se completan después en Configuración. Solo el rol Administrador los edita.
"""

import re

from django.conf import settings
from django.core.exceptions import ValidationError
from django.db import models

# El logo se guarda en MEDIA_ROOT/configuracion/ (volumen del servidor, fuera del repositorio). MEDIA no se publica
# por URL: el archivo solo se lee en el servidor para el PDF o se entrega desde una vista que exige sesión y rol.

PROVINCIAS_VALIDAS = {f"{n:02d}" for n in range(1, 25)} | {"30"}


def validar_ruc(valor):
    if not re.fullmatch(r"\d{13}", valor or ""):
        raise ValidationError("El RUC debe tener 13 dígitos.")
    if valor[:2] not in PROVINCIAS_VALIDAS:
        raise ValidationError("Los dos primeros dígitos del RUC deben ser un código de provincia válido (01–24 o 30).")


NOMBRE_POR_DEFECTO = "Empresa"


def ruta_logo(empresa, archivo):
    return f"configuracion/empresa-{empresa.pk or 'nueva'}/logo-empresa.png"


class Empresa(models.Model):
    nombre = models.CharField(
        "Nombre de la empresa", max_length=120, blank=True,
        help_text="Sale en la barra superior junto a «Novera».",
    )
    razon_social = models.CharField("Razón social", max_length=200, blank=True)
    nombre_comercial = models.CharField("Nombre comercial", max_length=200, blank=True)
    ruc = models.CharField("RUC", max_length=13, blank=True, validators=[validar_ruc])
    direccion_matriz = models.CharField("Dirección matriz", max_length=255, blank=True)
    telefono = models.CharField("Teléfono", max_length=60, blank=True)
    email = models.EmailField("Email", blank=True)
    web = models.URLField("Web", blank=True, help_text="Opcional. Ej.: https://www.miempresa.com")
    color_app = models.CharField(
        "Color de la aplicación", max_length=7, blank=True,
        help_text="Código de color, p. ej. #1F4E5F. Vacío = azul por defecto.",
    )
    color_proforma = models.CharField(
        "Color de la proforma (PDF)", max_length=7, blank=True,
        help_text="Código de color, p. ej. #D9A21B (mostaza). Vacío = azul por defecto.",
    )
    logo = models.ImageField(
        "Logo", upload_to=ruta_logo, blank=True,
        help_text="PNG o JPG, hasta 2 MB. Se usa en las proformas en PDF.",
    )
    creado = models.DateTimeField(auto_now_add=True, null=True)
    actualizado = models.DateTimeField(auto_now=True)
    actualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "empresa"
        verbose_name_plural = "empresas"
        ordering = ["pk"]

    def __str__(self):
        return self.nombre_visible

    def delete(self, *args, **kwargs):
        raise ValidationError("Las empresas no se pueden borrar, solo editar.")

    @property
    def nombre_visible(self):
        """El nombre de la barra superior: «Empresa» si no tiene uno guardado."""
        return (self.nombre or "").strip() or NOMBRE_POR_DEFECTO

    @classmethod
    def actual(cls):
        """La empresa de la petición en curso (o None fuera de una petición)."""
        from .actual import empresa_actual

        return empresa_actual()


def datos_emisor(empresa=None):
    """Diccionario para el PDF con los datos de la empresa (si falta la razón social, se usa su nombre)."""
    e = empresa or Empresa.actual()
    if e is None:
        return {"razon_social": NOMBRE_POR_DEFECTO, "nombre_comercial": "", "ruc": "", "direccion": "",
                "telefono": "", "email": "", "web": "", "logo_ruta": None}
    return {
        "razon_social": e.razon_social or e.nombre_visible, "nombre_comercial": e.nombre_comercial, "ruc": e.ruc,
        "direccion": e.direccion_matriz, "telefono": e.telefono, "email": e.email, "web": e.web,
        "logo_ruta": e.logo.path if e.logo else None,
    }


def tema_aplicacion(empresa=None):
    """Paleta del color de la aplicación (azul por defecto si no se configuró)."""
    from .colores import paleta

    e = empresa or Empresa.actual()
    return paleta(e.color_app if e else "")


def tema_proforma(empresa=None):
    from .colores import paleta

    e = empresa or Empresa.actual()
    return paleta(e.color_proforma if e else "")
