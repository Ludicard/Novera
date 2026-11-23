"""Proformas (cotizaciones), órdenes de trabajo e informes de los técnicos.

Flujo: Proforma (borrador → enviada → aprobada/rechazada) → al aprobarse se genera la Orden de trabajo,
que lleva técnicos asignados, instrucciones, materiales, herramientas, horas estimadas y fechas.
Los técnicos trabajan solo por órdenes de trabajo y reportan con Informes. Una factura puede incluir varias órdenes.
"""

from decimal import Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.facturas.models import redondear

CERO = Decimal("0.00")


def siguiente_numero(modelo, prefijo):
    """PF-00001, OT-00001…: el siguiente número correlativo del prefijo."""
    ultimo = 0
    for numero in modelo.objects.filter(numero__startswith=f"{prefijo}-").values_list("numero", flat=True):
        sufijo = numero[len(prefijo) + 1:]
        if sufijo.isdigit():
            ultimo = max(ultimo, int(sufijo))
    return f"{prefijo}-{ultimo + 1:05d}"


class Auditoria(models.Model):
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    class Meta:
        abstract = True


# ---------------------------------------------------------------- proformas


class Proforma(Auditoria):
    class Estado(models.TextChoices):
        BORRADOR = "BORRADOR", "Borrador"
        ENVIADA = "ENVIADA", "Enviada al cliente"
        APROBADA = "APROBADA", "Aprobada"
        RECHAZADA = "RECHAZADA", "Rechazada"

    numero = models.CharField("Número", max_length=20, unique=True, editable=False)
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="proformas")
    fecha = models.DateField(default=timezone.localdate)
    validez_dias = models.PositiveSmallIntegerField("Validez (días)", default=15)
    titulo = models.CharField("Trabajo a realizar", max_length=200)
    descripcion = models.TextField("Detalle / alcance", blank=True)
    porcentaje_iva = models.DecimalField("% IVA", max_digits=5, decimal_places=2, default=Decimal("15"))
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.BORRADOR)
    fecha_respuesta = models.DateField("Fecha de aprobación/rechazo", null=True, blank=True)
    notas = models.TextField(blank=True)

    class Meta:
        ordering = ["-fecha", "-numero"]

    def __str__(self):
        return f"{self.numero} · {self.titulo}"

    def get_absolute_url(self):
        return reverse("trabajos:proforma", args=[self.pk])

    def save(self, *args, **kwargs):
        if not self.numero:
            self.numero = siguiente_numero(Proforma, "PF")
        super().save(*args, **kwargs)

    @property
    def subtotal(self):
        return redondear(sum((l.importe for l in self.lineas.all()), CERO))

    @property
    def iva(self):
        return redondear(self.subtotal * self.porcentaje_iva / 100)

    @property
    def total(self):
        return self.subtotal + self.iva

    @property
    def editable(self):
        return self.estado in (self.Estado.BORRADOR, self.Estado.ENVIADA)


class LineaProforma(models.Model):
    class Tipo(models.TextChoices):
        SERVICIO = "SERVICIO", "Mano de obra / servicio"
        MATERIAL = "MATERIAL", "Material"

    proforma = models.ForeignKey(Proforma, on_delete=models.CASCADE, related_name="lineas")
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.SERVICIO)
    descripcion = models.CharField("Descripción", max_length=255)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("1"), validators=[MinValueValidator(Decimal("0.01"))])
    unidad = models.CharField(max_length=20, blank=True, default="u")
    precio_unitario = models.DecimalField("Precio unitario", max_digits=12, decimal_places=2, validators=[MinValueValidator(Decimal("0"))])

    class Meta:
        ordering = ["pk"]

    @property
    def importe(self):
        return redondear(self.cantidad * self.precio_unitario)


# ---------------------------------------------------------------- órdenes de trabajo


class OrdenTrabajo(Auditoria):
    class Estado(models.TextChoices):
        PENDIENTE = "PENDIENTE", "Pendiente"
        EN_CURSO = "EN_CURSO", "En curso"
        TERMINADA = "TERMINADA", "Terminada"
        CANCELADA = "CANCELADA", "Cancelada"

    numero = models.CharField("Número", max_length=20, unique=True, editable=False)
    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="ordenes")
    proforma = models.OneToOneField(Proforma, on_delete=models.SET_NULL, null=True, blank=True, related_name="orden")
    titulo = models.CharField("Trabajo a realizar", max_length=200)
    descripcion = models.TextField("Detalle", blank=True)
    ubicacion = models.CharField("Lugar / dirección", max_length=255, blank=True)
    equipos = models.ManyToManyField(
        "clientes.Equipo", blank=True, related_name="ordenes", verbose_name="Equipos", help_text="Equipos del cliente en los que se trabaja."
    )
    tecnicos = models.ManyToManyField(
        settings.AUTH_USER_MODEL, blank=True, related_name="ordenes_asignadas", verbose_name="Técnicos asignados"
    )
    instrucciones = models.TextField(
        "Instrucciones y responsabilidades", blank=True, help_text="Qué debe hacer cada técnico en esta orden."
    )
    horas_estimadas = models.DecimalField("Horas estimadas", max_digits=7, decimal_places=1, null=True, blank=True)
    fecha_inicio = models.DateField("Fecha de inicio", null=True, blank=True)
    fecha_fin = models.DateField("Fecha de finalización", null=True, blank=True)
    estado = models.CharField(max_length=10, choices=Estado.choices, default=Estado.PENDIENTE)
    notas = models.TextField(blank=True)

    class Meta:
        ordering = ["-creado"]
        verbose_name = "orden de trabajo"
        verbose_name_plural = "órdenes de trabajo"

    def __str__(self):
        return f"{self.numero} · {self.titulo}"

    def get_absolute_url(self):
        return reverse("trabajos:orden", args=[self.pk])

    def save(self, *args, **kwargs):
        if not self.numero:
            self.numero = siguiente_numero(OrdenTrabajo, "OT")
        super().save(*args, **kwargs)

    @property
    def atrasada(self):
        return (
            self.fecha_fin is not None
            and self.fecha_fin < timezone.localdate()
            and self.estado in (self.Estado.PENDIENTE, self.Estado.EN_CURSO)
        )

    @classmethod
    def desde_proforma(cls, proforma, usuario=None):
        """Genera la orden de una proforma aprobada (copia cliente, trabajo y los materiales cotizados)."""
        orden = cls.objects.create(
            cliente=proforma.cliente, proforma=proforma, titulo=proforma.titulo, descripcion=proforma.descripcion,
            ubicacion=proforma.cliente.direccion, creado_por=usuario,
        )
        for linea in proforma.lineas.filter(tipo=LineaProforma.Tipo.MATERIAL):
            orden.recursos.create(
                tipo=Recurso.Tipo.MATERIAL, descripcion=linea.descripcion, cantidad=linea.cantidad, unidad=linea.unidad,
            )
        return orden


class Recurso(models.Model):
    """Material o herramienta que necesita una orden de trabajo."""

    class Tipo(models.TextChoices):
        MATERIAL = "MATERIAL", "Material"
        HERRAMIENTA = "HERRAMIENTA", "Herramienta"

    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.CASCADE, related_name="recursos")
    tipo = models.CharField(max_length=12, choices=Tipo.choices)
    descripcion = models.CharField("Descripción", max_length=255)
    cantidad = models.DecimalField(max_digits=10, decimal_places=2, default=Decimal("1"), validators=[MinValueValidator(Decimal("0.01"))])
    unidad = models.CharField(max_length=20, blank=True, default="u")

    class Meta:
        ordering = ["tipo", "pk"]


class Informe(Auditoria):
    """Informe de trabajo que el técnico genera sobre una orden."""

    orden = models.ForeignKey(OrdenTrabajo, on_delete=models.CASCADE, related_name="informes")
    tecnico = models.ForeignKey(settings.AUTH_USER_MODEL, on_delete=models.PROTECT, related_name="informes")
    fecha = models.DateField(default=timezone.localdate)
    horas_trabajadas = models.DecimalField("Horas trabajadas", max_digits=6, decimal_places=1, null=True, blank=True)
    trabajo_realizado = models.TextField("Trabajo realizado")
    materiales_usados = models.TextField("Materiales usados", blank=True)
    observaciones = models.TextField("Observaciones / pendientes", blank=True)
    trabajo_terminado = models.BooleanField("El trabajo de la orden quedó terminado", default=False)

    class Meta:
        ordering = ["-fecha", "-creado"]

    def __str__(self):
        return f"Informe {self.orden.numero} · {self.fecha:%d/%m/%Y}"


class PerfilTecnico(models.Model):
    """Datos del técnico (solo los ve el Manager). El nombre, usuario y clave están en la cuenta."""

    usuario = models.OneToOneField(settings.AUTH_USER_MODEL, on_delete=models.CASCADE, related_name="perfil_tecnico")
    grado_academico = models.CharField("Grado académico", max_length=120, blank=True)
    capacidades = models.TextField(
        "Capacidades adicionales", blank=True, help_text="Certificaciones, especialidades, equipos que domina, licencias…"
    )
    telefono = models.CharField("Teléfono (contacto directo)", max_length=30, blank=True)
    direccion = models.CharField("Dirección", max_length=255, blank=True)
    actualizado = models.DateTimeField(auto_now=True)

    class Meta:
        verbose_name = "perfil de técnico"
        verbose_name_plural = "perfiles de técnicos"

    def __str__(self):
        return f"Perfil de {self.usuario}"
