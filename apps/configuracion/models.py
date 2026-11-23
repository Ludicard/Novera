"""Configuración de la empresa (emisor de proformas): un único registro en la base de datos.

Se guarda en PostgreSQL del servidor (no en el código, que es público). Solo el rol Administrador la edita.
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


class Empresa(models.Model):
    razon_social = models.CharField("Razón social", max_length=200)
    nombre_comercial = models.CharField("Nombre comercial", max_length=200, blank=True)
    ruc = models.CharField("RUC", max_length=13, validators=[validar_ruc])
    direccion_matriz = models.CharField("Dirección matriz", max_length=255)
    telefono = models.CharField("Teléfono", max_length=60)
    email = models.EmailField("Email")
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
        "Logo", upload_to="configuracion/", blank=True,
        help_text="PNG o JPG, hasta 2 MB. Se usa en las proformas en PDF.",
    )
    actualizado = models.DateTimeField(auto_now=True)
    actualizado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        verbose_name = "datos de la empresa"
        verbose_name_plural = "datos de la empresa"

    def __str__(self):
        return self.razon_social or "Empresa"

    def save(self, *args, **kwargs):
        self.pk = 1  # registro único
        super().save(*args, **kwargs)

    def delete(self, *args, **kwargs):
        raise ValidationError("Los datos de la empresa no se pueden borrar, solo editar.")

    @classmethod
    def actual(cls):
        """Los datos guardados (o None si aún no se han configurado)."""
        return cls.objects.filter(pk=1).first()


def datos_emisor():
    """Diccionario para el PDF. Usa la configuración guardada; si falta, las variables NOVERA_EMPRESA_* del .env."""
    e = Empresa.actual()
    if e is None:
        return dict(settings.NOVERA_EMPRESA, logo_ruta=None)
    return {
        "razon_social": e.razon_social, "nombre_comercial": e.nombre_comercial, "ruc": e.ruc,
        "direccion": e.direccion_matriz, "telefono": e.telefono, "email": e.email, "web": e.web,
        "logo_ruta": e.logo.path if e.logo else None,
    }


def tema_aplicacion():
    """Paleta del color de la aplicación (azul por defecto si no se configuró)."""
    from .colores import paleta

    e = Empresa.actual()
    return paleta(e.color_app if e else "")


def tema_proforma():
    from .colores import paleta

    e = Empresa.actual()
    return paleta(e.color_proforma if e else "")
