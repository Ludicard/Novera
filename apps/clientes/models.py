from decimal import Decimal

from django.apps import apps
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import DecimalField, ExpressionWrapper, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce, Lower
from django.urls import reverse

validar_identificacion = RegexValidator(
    r"^(\d{10}|\d{13})$",
    "Debe tener 10 dígitos (cédula) o 13 dígitos (RUC).",
)

MONEDA = DecimalField(max_digits=14, decimal_places=2)


class ClienteQuerySet(models.QuerySet):
    def con_saldos(self):
        """Anota facturado, cobrado y saldo pendiente (sin contar facturas anuladas)."""
        Factura = apps.get_model("facturas", "Factura")
        Pago = apps.get_model("facturas", "Pago")
        facturado = (
            Factura.objects.filter(cliente=OuterRef("pk"), anulada=False)
            .values("cliente")
            .annotate(s=Sum("total"))
            .values("s")
        )
        cobrado = (
            Pago.objects.filter(factura__cliente=OuterRef("pk"), factura__anulada=False)
            .values("factura__cliente")
            .annotate(s=Sum("monto"))
            .values("s")
        )
        cero = Value(Decimal("0.00"), output_field=MONEDA)
        return self.annotate(
            facturado=Coalesce(Subquery(facturado, output_field=MONEDA), cero),
            cobrado=Coalesce(Subquery(cobrado, output_field=MONEDA), cero),
        ).annotate(saldo=ExpressionWrapper(F("facturado") - F("cobrado"), output_field=MONEDA))


class Cliente(models.Model):
    nombre = models.CharField(max_length=200)
    identificacion = models.CharField(
        "RUC / Cédula", max_length=13, blank=True, validators=[validar_identificacion]
    )
    email = models.EmailField(blank=True)
    telefono = models.CharField("Teléfono", max_length=30, blank=True)
    direccion = models.CharField("Dirección", max_length=255, blank=True)
    dias_credito = models.PositiveSmallIntegerField(
        "Días de crédito", default=30, help_text="Plazo habitual para cobrarle a este cliente."
    )
    activo = models.BooleanField(default=True)
    notas = models.TextField(blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    objects = ClienteQuerySet.as_manager()

    class Meta:
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(Lower("nombre"), name="cliente_nombre_unico"),
        ]

    def __str__(self):
        return self.nombre

    def get_absolute_url(self):
        return reverse("clientes:detalle", args=[self.pk])

    @property
    def tipo_identificacion(self):
        return {10: "Cédula", 13: "RUC"}.get(len(self.identificacion), "")
