from decimal import Decimal

from django.apps import apps
from django.core.validators import RegexValidator
from django.db import models
from django.db.models import DecimalField, ExpressionWrapper, F, OuterRef, Subquery, Sum, Value
from django.db.models.functions import Coalesce, Lower
from django.urls import reverse

from apps.configuracion.actual import DeEmpresa, por_empresa

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


class Cliente(DeEmpresa):
    nombre = models.CharField(max_length=200)
    identificacion = models.CharField(
        "RUC / Cédula", max_length=13, blank=True, validators=[validar_identificacion]
    )
    email = models.EmailField(blank=True)
    telefono = models.CharField("Teléfono", max_length=30, blank=True)
    telefono_contacto = models.CharField(
        "Teléfono de contacto", max_length=60, blank=True,
        help_text="Contacto informal: persona y número para coordinar (no sale en la factura).",
    )
    direccion = models.CharField("Dirección", max_length=255, blank=True)
    agente_retencion = models.BooleanField(
        "Agente de retención", default=False,
        help_text="Marca si el cliente es agente de retención (te retendrá IVA/renta al pagar).",
    )
    dias_credito = models.PositiveSmallIntegerField(
        "Días de crédito", default=30, help_text="Plazo habitual para cobrarle a este cliente."
    )
    activo = models.BooleanField(default=True)
    notas = models.TextField(blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    objects = por_empresa("empresa", ClienteQuerySet)

    class Meta:
        ordering = ["nombre"]
        constraints = [
            models.UniqueConstraint(F("empresa"), Lower("nombre"), name="cliente_nombre_unico_por_empresa"),
        ]

    def __str__(self):
        return self.nombre

    def get_absolute_url(self):
        return reverse("clientes:detalle", args=[self.pk])

    @property
    def faltan_para_facturar(self):
        """Datos que el SRI exige en una factura y que a este cliente le faltan."""
        faltan = []
        if not self.identificacion:
            faltan.append("RUC/cédula")
        if not self.direccion:
            faltan.append("dirección")
        if not self.email:
            faltan.append("email")
        return faltan

    @property
    def tipo_identificacion(self):
        return {10: "Cédula", 13: "RUC"}.get(len(self.identificacion), "")


class Equipo(models.Model):
    """Equipo instalado en un cliente (ascensor, montacargas…), con su historial de órdenes de trabajo."""

    class Tipo(models.TextChoices):
        ASCENSOR = "ASCENSOR", "Ascensor"
        MONTACARGAS = "MONTACARGAS", "Montacargas"
        ESCALERA = "ESCALERA", "Escalera eléctrica"
        PLATAFORMA = "PLATAFORMA", "Plataforma / salvaescaleras"
        OTRO = "OTRO", "Otro"

    cliente = models.ForeignKey(Cliente, on_delete=models.PROTECT, related_name="equipos")
    tipo = models.CharField(max_length=12, choices=Tipo.choices, default=Tipo.ASCENSOR)
    nombre = models.CharField("Nombre / identificación", max_length=120, help_text="Cómo lo identifica el cliente: «Ascensor 2 – Torre Sur».")
    marca = models.CharField(max_length=80, blank=True)
    modelo = models.CharField(max_length=80, blank=True)
    numero_serie = models.CharField("Nº de serie", max_length=80, blank=True)
    ubicacion = models.CharField("Ubicación", max_length=200, blank=True, help_text="Torre, bloque, piso…")
    capacidad = models.CharField(max_length=60, blank=True, help_text="Ej.: 8 personas / 630 kg, 6 paradas")
    fecha_instalacion = models.DateField("Fecha de instalación", null=True, blank=True)
    activo = models.BooleanField(default=True, help_text="Desmarca si se retiró o ya no se le da servicio.")
    notas = models.TextField(blank=True)
    creado = models.DateTimeField(auto_now_add=True)
    actualizado = models.DateTimeField(auto_now=True)

    objects = por_empresa("cliente__empresa")

    class Meta:
        ordering = ["cliente__nombre", "nombre"]
        constraints = [models.UniqueConstraint(fields=["cliente", "nombre"], name="equipo_nombre_unico_por_cliente")]

    def __str__(self):
        return f"{self.nombre} · {self.cliente}"

    def get_absolute_url(self):
        return reverse("clientes:equipo", args=[self.pk])
