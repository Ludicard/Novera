from decimal import Decimal

from django import forms
from django.conf import settings
from django.utils import timezone

from apps.clientes.models import Cliente

from .importador import ESTADO_DESCONOCIDO_OPCIONES
from .models import Estado, Factura, Pago, redondear

FECHA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
MES = forms.DateInput(attrs={"type": "month"}, format="%Y-%m")
TASAS_IVA = [("15", "15 %"), ("12", "12 %"), ("5", "5 %"), ("0", "0 %")]


def siguiente_numero():
    """Siguiente secuencial SRI de la serie configurada: 001-001-000000676."""
    serie = settings.NOVERA_SERIE_FACTURA
    secuenciales = [
        int(n[len(serie) + 1 :])
        for n in Factura.objects.filter(numero__startswith=f"{serie}-").values_list("numero", flat=True)
        if n[len(serie) + 1 :].isdigit()
    ]
    return f"{serie}-{(max(secuenciales, default=0) + 1):09d}"


class FacturaForm(forms.ModelForm):
    periodo = forms.DateField(widget=MES, input_formats=["%Y-%m", "%Y-%m-%d"])
    porcentaje_iva = forms.TypedChoiceField(label="% IVA", choices=TASAS_IVA, coerce=Decimal)

    class Meta:
        model = Factura
        fields = [
            "tipo", "numero", "cliente", "periodo", "fecha_emision", "dias_credito",
            "fecha_cobro", "objeto", "subtotal", "porcentaje_iva", "notas",
        ]
        widgets = {
            "fecha_emision": FECHA,
            "fecha_cobro": FECHA,
            "notas": forms.Textarea(attrs={"rows": 2}),
            "subtotal": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
        }
        help_texts = {"numero": "Si escribes solo el secuencial (ej. 676) se completa con la serie."}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cliente"].required = True
        self.fields["cliente"].queryset = Cliente.objects.filter(activo=True) | Cliente.objects.filter(
            pk=getattr(self.instance, "cliente_id", None)
        )
        if self.instance.pk:
            tasa = str(int(self.instance.porcentaje_iva)) if self.instance.porcentaje_iva % 1 == 0 else None
            if tasa and tasa not in dict(TASAS_IVA):
                self.fields["porcentaje_iva"].choices = TASAS_IVA + [(tasa, f"{tasa} %")]
        else:
            hoy = timezone.localdate()
            self.initial.setdefault("numero", siguiente_numero())
            self.initial.setdefault("fecha_emision", hoy)
            self.initial.setdefault("periodo", hoy.replace(day=1))
            self.initial.setdefault("porcentaje_iva", str(settings.NOVERA_IVA_DEFECTO))
            self.initial.setdefault("dias_credito", settings.NOVERA_DIAS_CREDITO_DEFECTO)

    def clean_numero(self):
        numero = " ".join(self.cleaned_data["numero"].split())
        if self.cleaned_data.get("tipo", Factura.Tipo.FACTURA) == Factura.Tipo.FACTURA and numero.isdigit():
            numero = f"{settings.NOVERA_SERIE_FACTURA}-{int(numero):09d}"
        duplicada = Factura.objects.buscar_duplicado(numero, excluir=self.instance.pk)
        if duplicada:
            raise forms.ValidationError(f"Ya existe el documento {duplicada.numero}.")
        return numero

    def clean(self):
        datos = super().clean()
        emision, cobro = datos.get("fecha_emision"), datos.get("fecha_cobro")
        if emision and cobro and cobro < emision:
            self.add_error("fecha_cobro", "La fecha de cobro no puede ser anterior a la emisión.")
        return datos

    def save(self, commit=True):
        factura = super().save(commit=False)
        factura.calcular_montos()
        if "fecha_cobro" not in self.changed_data and (
            "fecha_emision" in self.changed_data or "dias_credito" in self.changed_data
        ):
            factura.fecha_cobro = None  # se recalcula en save()
        if commit:
            factura.save()
        return factura


class PagoForm(forms.ModelForm):
    class Meta:
        model = Pago
        fields = ["fecha", "forma", "referencia", "monto", "notas"]
        widgets = {"fecha": FECHA, "monto": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"})}

    def __init__(self, *args, factura, **kwargs):
        super().__init__(*args, **kwargs)
        self.factura = factura
        self.initial.setdefault("monto", redondear(factura.saldo_pendiente()))
        self.initial.setdefault("fecha", timezone.localdate())

    def clean_monto(self):
        monto = self.cleaned_data["monto"]
        saldo = self.factura.saldo_pendiente()
        if monto > saldo:
            raise forms.ValidationError(f"El pago supera el saldo pendiente (${saldo}).")
        return monto

    def clean(self):
        if self.factura.anulada:
            raise forms.ValidationError("No se pueden registrar pagos en una factura anulada.")
        return super().clean()


class CobroLoteForm(forms.Form):
    ids = forms.CharField()
    fecha = forms.DateField(widget=FECHA)
    forma = forms.ChoiceField(choices=Pago.Forma.choices)
    referencia = forms.CharField(max_length=100, required=False)

    def clean_ids(self):
        ids = [int(x) for x in self.cleaned_data["ids"].split(",") if x.strip().isdigit()]
        if not ids:
            raise forms.ValidationError("No hay facturas seleccionadas.")
        return ids


class AnularForm(forms.Form):
    motivo = forms.CharField(max_length=255, label="Motivo de la anulación")


class FiltroFacturasForm(forms.Form):
    q = forms.CharField(
        required=False, label="Buscar",
        widget=forms.TextInput(attrs={"placeholder": "Buscar por número, cliente, RUC u objeto…", "type": "search", "autocomplete": "off"}),
    )
    estado = forms.ChoiceField(
        required=False, choices=[("", "Todos"), ("ABIERTAS", "Por cobrar")] + list(Estado.choices)
    )
    cliente = forms.ModelChoiceField(required=False, queryset=Cliente.objects.all(), empty_label="Todos")
    desde = forms.DateField(required=False, label="Periodo desde", widget=MES, input_formats=["%Y-%m"])
    hasta = forms.DateField(required=False, label="hasta", widget=MES, input_formats=["%Y-%m"])
    emitida_desde = forms.DateField(required=False, label="Emitida desde", widget=FECHA)
    emitida_hasta = forms.DateField(required=False, label="hasta", widget=FECHA)


class ImportarForm(forms.Form):
    archivo = forms.FileField(
        label="Archivo Excel (.xlsx / .xlsm)",
        widget=forms.ClearableFileInput(attrs={"accept": ".xlsx,.xlsm"}),
    )
    estado_desconocido = forms.ChoiceField(
        label="Facturas sin estado de cobro en el archivo",
        help_text="FactureroMovil no registra los cobros (columna «Cobrada: N/A»). Si importas el histórico, "
        "las ya cobradas puedes marcarlas como pagadas; lo nuevo, mejor como pendiente.",
        choices=ESTADO_DESCONOCIDO_OPCIONES,
        initial="pendiente",
        widget=forms.RadioSelect,
    )

    def clean_archivo(self):
        archivo = self.cleaned_data["archivo"]
        if not archivo.name.lower().endswith((".xlsx", ".xlsm")):
            raise forms.ValidationError("Sube un archivo .xlsx o .xlsm.")
        if archivo.size > 20 * 1024 * 1024:
            raise forms.ValidationError("El archivo supera los 20 MB.")
        return archivo
