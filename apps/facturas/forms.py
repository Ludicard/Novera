from decimal import Decimal

from django import forms
from django.conf import settings
from django.db.models import Q
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


def siguiente_recibo():
    ultimo = 0
    for n in Factura.objects.filter(numero__startswith="REC-").values_list("numero", flat=True):
        if n[4:].isdigit():
            ultimo = max(ultimo, int(n[4:]))
    return f"REC-{ultimo + 1:05d}"


class OrdenesWidget(forms.CheckboxSelectMultiple):
    """Casillas de órdenes de trabajo con data-cliente (se muestran solo las del cliente elegido)."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        opcion = super().create_option(name, value, label, selected, index, subindex, attrs)
        instancia = getattr(value, "instance", None)
        if instancia is not None:
            opcion["attrs"]["data-cliente"] = instancia.cliente_id
        return opcion


class OrdenesField(forms.ModelMultipleChoiceField):
    widget = OrdenesWidget

    def label_from_instance(self, o):
        return f"{o.numero} · {o.titulo} ({o.get_estado_display().lower()})"


class FacturaForm(forms.ModelForm):
    periodo = forms.DateField(widget=MES, input_formats=["%Y-%m", "%Y-%m-%d"])
    porcentaje_iva = forms.TypedChoiceField(label="% IVA", choices=TASAS_IVA, coerce=Decimal)
    ordenes = OrdenesField(
        queryset=None, required=False, label="Órdenes de trabajo que cobra",
        help_text="Puedes incluir varias. Solo se muestran las del cliente elegido.",
    )

    class Meta:
        model = Factura
        fields = [
            "tipo", "numero", "cliente", "ordenes", "periodo", "fecha_emision", "dias_credito",
            "fecha_cobro", "objeto", "subtotal", "porcentaje_iva", "notas",
        ]
        widgets = {
            "fecha_emision": FECHA,
            "fecha_cobro": FECHA,
            "notas": forms.Textarea(attrs={"rows": 2}),
            "subtotal": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "tipo": forms.RadioSelect,
        }
        help_texts = {
            "numero": "Factura: el número del SRI (basta el secuencial, ej. 676). Vacío = el siguiente automático.",
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cliente"].required = True
        self.fields["cliente"].widget.attrs["data-buscar"] = "cliente"
        self.fields["numero"].required = False
        from apps.trabajos.models import OrdenTrabajo

        en_uso = list(self.instance.ordenes.values_list("pk", flat=True)) if self.instance.pk else []
        self.fields["ordenes"].queryset = (
            OrdenTrabajo.objects.filter(~Q(estado=OrdenTrabajo.Estado.CANCELADA) | Q(pk__in=en_uso))
            .select_related("cliente").order_by("-creado")
        )
        self.fields["numero"].widget.attrs.update({
            "data-siguiente-factura": siguiente_numero(), "data-siguiente-recibo": siguiente_recibo(),
        })
        # Clientes activos, más el de la factura o el elegido de antemano aunque esté inactivo
        incluir = {getattr(self.instance, "cliente_id", None), getattr(self.initial.get("cliente"), "pk", None)}
        self.fields["cliente"].queryset = Cliente.objects.filter(Q(activo=True) | Q(pk__in=[x for x in incluir if x]))
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
        numero = " ".join((self.cleaned_data.get("numero") or "").split())
        tipo = self.cleaned_data.get("tipo", Factura.Tipo.FACTURA)
        if not numero:
            numero = siguiente_recibo() if tipo == Factura.Tipo.RECIBO else siguiente_numero()
        if tipo == Factura.Tipo.FACTURA and numero.isdigit():
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
        cliente = datos.get("cliente")
        ajenas = [o for o in (datos.get("ordenes") or []) if cliente and o.cliente_id != cliente.pk]
        if ajenas:
            self.add_error("ordenes", f"La orden {ajenas[0].numero} es de otro cliente.")
        subtotal, pct = datos.get("subtotal"), datos.get("porcentaje_iva")
        if self.instance.pk and subtotal is not None and pct is not None:
            total = redondear(subtotal + redondear(subtotal * pct / 100))
            pagado = self.instance.total_pagado()
            if total < pagado:
                self.add_error(
                    "subtotal",
                    f"El nuevo total (${total:,.2f}) sería menor que lo ya cobrado (${pagado:,.2f}). "
                    "Elimina o corrige los pagos primero.",
                )
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
            self.save_m2m()
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
            raise forms.ValidationError(f"El pago supera el saldo pendiente (${saldo:,.2f}).")
        return monto

    def clean(self):
        if self.factura.anulada:
            raise forms.ValidationError("No se pueden registrar pagos en una factura anulada.")
        return super().clean()


class CobroLoteForm(forms.Form):
    FECHA_ELEGIDA, FECHA_VENCIMIENTO, FECHA_EMISION = "elegida", "vencimiento", "emision"

    ids = forms.CharField(required=False)
    todas = forms.BooleanField(required=False)  # todas las facturas que cumplen los filtros, no solo la página
    filtros = forms.CharField(required=False)    # query string del listado
    fecha_modo = forms.ChoiceField(
        choices=[
            (FECHA_ELEGIDA, "Una misma fecha"),
            (FECHA_VENCIMIENTO, "La fecha de vencimiento de cada factura"),
            (FECHA_EMISION, "La fecha de emisión de cada factura"),
        ],
        initial=FECHA_ELEGIDA,
        required=False,
    )
    fecha = forms.DateField(widget=FECHA, required=False)
    forma = forms.ChoiceField(choices=Pago.Forma.choices)
    referencia = forms.CharField(max_length=100, required=False)

    def clean_ids(self):
        return [int(x) for x in (self.cleaned_data["ids"] or "").split(",") if x.strip().isdigit()]

    def clean(self):
        datos = super().clean()
        if not datos.get("todas") and not datos.get("ids"):
            raise forms.ValidationError("No hay facturas seleccionadas.")
        datos["fecha_modo"] = datos.get("fecha_modo") or self.FECHA_ELEGIDA
        if datos["fecha_modo"] == self.FECHA_ELEGIDA and not datos.get("fecha"):
            self.add_error("fecha", "Indica la fecha del cobro.")
        return datos


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
