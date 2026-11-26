import re
from datetime import timedelta
from decimal import ROUND_HALF_UP, Decimal

from django.conf import settings
from django.core.validators import MinValueValidator
from django.db import models
from django.db.models import (
    Case,
    DecimalField,
    ExpressionWrapper,
    F,
    OuterRef,
    Subquery,
    Sum,
    Value,
    When,
)
from django.db.models.functions import Coalesce
from django.urls import reverse
from django.utils import timezone

from apps.clientes.models import Cliente
from apps.configuracion.actual import DeEmpresa, por_empresa

MONEDA = DecimalField(max_digits=14, decimal_places=2)
CENTAVO = Decimal("0.01")


def redondear(valor):
    return Decimal(valor).quantize(CENTAVO, rounding=ROUND_HALF_UP)


def clave_numero(numero):
    """Forma canónica de un número de documento para detectar duplicados.

    «676», «001-001-676» y «001-001-000000676» son la misma factura; «Recibo 066» se compara sin
    distinguir mayúsculas ni espacios.
    """
    s = re.sub(r"\s+", " ", str(numero or "")).strip().lower()
    m = re.fullmatch(r"(\d{3})\s*-\s*(\d{3})\s*-\s*(\d{1,9})", s)
    if m:
        return f"{m.group(1)}-{m.group(2)}-{int(m.group(3)):09d}"
    if s.isdigit():
        return f"{settings.NOVERA_SERIE_FACTURA}-{int(s):09d}"
    return s


class Estado(models.TextChoices):
    PENDIENTE = "PENDIENTE", "Pendiente"
    PARCIAL = "PARCIAL", "Abono parcial"
    VENCIDA = "VENCIDA", "Vencida"
    PAGADA = "PAGADA", "Pagada"
    ANULADA = "ANULADA", "Anulada"


class FacturaQuerySet(models.QuerySet):
    def con_saldos(self, hoy=None):
        """Anota `pagado`, `saldo` y `estado`.

        El estado nunca se escribe a mano: se deriva de los pagos y de la fecha de cobro.
        Una factura con saldo y fecha de cobro pasada es VENCIDA aunque tenga abonos.
        """
        hoy = hoy or timezone.localdate()
        pagos = (
            Pago.objects.filter(factura=OuterRef("pk"))
            .values("factura")
            .annotate(s=Sum("monto"))
            .values("s")
        )
        return (
            self.annotate(
                pagado=Coalesce(
                    Subquery(pagos, output_field=MONEDA),
                    Value(Decimal("0.00"), output_field=MONEDA),
                )
            )
            .annotate(saldo=ExpressionWrapper(F("total") - F("pagado"), output_field=MONEDA))
            .annotate(
                estado=Case(
                    When(anulada=True, then=Value(Estado.ANULADA)),
                    When(saldo__lte=0, then=Value(Estado.PAGADA)),
                    When(fecha_cobro__lt=hoy, then=Value(Estado.VENCIDA)),
                    When(pagado__gt=0, then=Value(Estado.PARCIAL)),
                    default=Value(Estado.PENDIENTE),
                    output_field=models.CharField(),
                )
            )
        )

    def por_cobrar(self, hoy=None):
        return self.con_saldos(hoy).filter(anulada=False, saldo__gt=0)

    def buscar_duplicado(self, numero, clave_acceso="", excluir=None):
        """Factura ya registrada con el mismo número (en forma canónica) o la misma clave de acceso."""
        qs = self.exclude(pk=excluir) if excluir else self
        if clave_acceso:
            encontrada = qs.filter(clave_acceso=clave_acceso).first()
            if encontrada:
                return encontrada
        clave = clave_numero(numero)
        secuencial = clave.rsplit("-", 1)[-1].lstrip("0") or "0"
        for f in qs.filter(numero__icontains=secuencial).only("pk", "numero"):
            if clave_numero(f.numero) == clave:
                return f
        return None


class Factura(DeEmpresa):
    class Tipo(models.TextChoices):
        FACTURA = "FACTURA", "Factura"
        RECIBO = "RECIBO", "Recibo"

    numero = models.CharField("Número", max_length=40)
    tipo = models.CharField(max_length=10, choices=Tipo.choices, default=Tipo.FACTURA)
    cliente = models.ForeignKey(
        Cliente, on_delete=models.PROTECT, related_name="facturas", null=True, blank=True
    )
    periodo = models.DateField(help_text="Mes al que corresponde el servicio (se guarda como día 1).")
    fecha_emision = models.DateField("Fecha de emisión")
    dias_credito = models.PositiveSmallIntegerField("Días de crédito", default=30)
    fecha_cobro = models.DateField(
        "Fecha de cobro", null=True, blank=True, help_text="Si se deja vacía: emisión + días de crédito."
    )
    objeto = models.CharField("Objeto / concepto", max_length=255, blank=True)
    subtotal = models.DecimalField("Valor (sin IVA)", max_digits=14, decimal_places=2)
    porcentaje_iva = models.DecimalField("% IVA", max_digits=5, decimal_places=2, default=Decimal("15"))
    iva = models.DecimalField("IVA", max_digits=14, decimal_places=2, default=Decimal("0"))
    total = models.DecimalField(max_digits=14, decimal_places=2)
    clave_acceso = models.CharField(
        "Clave de acceso SRI", max_length=49, blank=True, help_text="49 dígitos del comprobante electrónico."
    )

    anulada = models.BooleanField(default=False)
    fecha_anulacion = models.DateField(null=True, blank=True)
    motivo_anulacion = models.CharField(max_length=255, blank=True)

    ordenes = models.ManyToManyField(
        "trabajos.OrdenTrabajo", blank=True, related_name="facturas", verbose_name="Órdenes de trabajo",
        help_text="Una factura puede cobrar varias órdenes de trabajo.",
    )
    notas = models.TextField(blank=True)
    importada = models.BooleanField(default=False, help_text="Creada por importación de Excel.")
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    objects = por_empresa("empresa", FacturaQuerySet)

    class Meta:
        ordering = ["-fecha_emision", "-numero"]
        indexes = [
            models.Index(fields=["periodo"]),
            models.Index(fields=["fecha_cobro"]),
        ]
        constraints = [
            models.UniqueConstraint(fields=["empresa", "numero"], name="factura_numero_unico_por_empresa"),
            models.UniqueConstraint(
                fields=["empresa", "clave_acceso"], condition=~models.Q(clave_acceso=""),
                name="factura_clave_acceso_unica_por_empresa",
            ),
        ]

    def __str__(self):
        return self.numero

    def get_absolute_url(self):
        return reverse("facturas:detalle", args=[self.pk])

    def calcular_montos(self):
        """IVA y total a partir del subtotal y el porcentaje."""
        self.iva = redondear(self.subtotal * self.porcentaje_iva / 100)
        self.total = redondear(self.subtotal + self.iva)

    def save(self, *args, **kwargs):
        if self.periodo:
            self.periodo = self.periodo.replace(day=1)
        if not self.fecha_cobro and self.fecha_emision:
            self.fecha_cobro = self.fecha_emision + timedelta(days=self.dias_credito or 0)
        super().save(*args, **kwargs)

    # Para instancias que no vienen de con_saldos()
    def total_pagado(self):
        if hasattr(self, "pagado"):
            return self.pagado
        return self.pagos.aggregate(s=Sum("monto"))["s"] or Decimal("0.00")

    def saldo_pendiente(self):
        if hasattr(self, "saldo"):
            return self.saldo
        return Decimal("0.00") if self.anulada else self.total - self.total_pagado()


class Pago(models.Model):
    class Forma(models.TextChoices):
        TRANSFERENCIA = "TRANSFERENCIA", "Transferencia"
        DEPOSITO = "DEPOSITO", "Depósito"
        CHEQUE = "CHEQUE", "Cheque"
        EFECTIVO = "EFECTIVO", "Efectivo"
        RETENCION = "RETENCION", "Retención"
        OTRO = "OTRO", "Otro"

    factura = models.ForeignKey(Factura, on_delete=models.CASCADE, related_name="pagos")
    fecha = models.DateField(default=timezone.localdate)
    forma = models.CharField("Forma de pago", max_length=15, choices=Forma.choices, default=Forma.TRANSFERENCIA)
    referencia = models.CharField(
        max_length=100, blank=True, help_text="Nº de transferencia, cheque o comprobante de retención."
    )
    monto = models.DecimalField(max_digits=14, decimal_places=2, validators=[MinValueValidator(CENTAVO)])
    notas = models.CharField(max_length=255, blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True, related_name="+"
    )

    objects = por_empresa("factura__empresa")

    class Meta:
        ordering = ["fecha", "pk"]

    def __str__(self):
        return f"{self.get_forma_display()} {self.monto} · {self.factura}"
