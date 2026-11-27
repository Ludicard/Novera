from django import forms
from django.db.models import Q
from django.forms import inlineformset_factory

from apps.clientes.models import Cliente, Equipo
from apps.usuarios.roles import ROLES, TECNICO

from .models import FormaPago, Informe, LineaProforma, OrdenTrabajo, Proforma, Recurso

FECHA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
TASAS_IVA = [("15", "15 %"), ("12", "12 %"), ("5", "5 %"), ("0", "0 %")]


def cuentas_empresa():
    from apps.configuracion.actual import empresa_actual
    from apps.usuarios.models import cuentas_de

    return cuentas_de(empresa_actual())


def tecnicos():
    """Cuentas activas con el rol Técnico de la empresa activa."""
    return (
        cuentas_empresa().filter(is_active=True, groups__name=ROLES[TECNICO])
        .distinct().order_by("first_name", "username")
    )


class ClientesActivosMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["cliente"].widget.attrs["data-buscar"] = "cliente"
        actual = getattr(self.instance, "cliente_id", None)
        self.fields["cliente"].queryset = Cliente.objects.filter(activo=True) | Cliente.objects.filter(pk=actual)
        self.fields["cliente"].empty_label = "Elige un cliente"


class ProformaForm(ClientesActivosMixin, forms.ModelForm):
    porcentaje_iva = forms.TypedChoiceField(label="% IVA", choices=TASAS_IVA, coerce=str, initial="15")
    forma_pago = forms.ChoiceField(label="Forma de pago", required=False)

    class Meta:
        model = Proforma
        fields = [
            "cliente", "fecha", "validez_dias", "porcentaje_iva", "descripcion",
            "forma_pago", "garantia_cantidad", "garantia_unidad", "garantia_nota",
            "ejecucion_cantidad", "ejecucion_unidad", "ejecucion_nota", "condiciones_generales", "notas",
        ]
        widgets = {
            "fecha": FECHA,
            "cliente": forms.Select(attrs={"data-buscar": "cliente"}),
            "descripcion": forms.Textarea(attrs={"rows": 2, "placeholder": "Opcional: indicaciones para la orden de trabajo (no sale en el PDF)"}),
            "garantia_cantidad": forms.NumberInput(attrs={"min": "0", "placeholder": "Ej.: 3"}),
            "ejecucion_cantidad": forms.NumberInput(attrs={"min": "0", "placeholder": "Ej.: 15"}),
            "ejecucion_nota": forms.TextInput(attrs={"placeholder": "Ej.: a partir de la recepción del anticipo"}),
            "garantia_nota": forms.Textarea(attrs={"rows": 2, "placeholder": "Ej.: cubre defectos de instalación y repuestos; no cubre mal uso…"}),
            "condiciones_generales": forms.Textarea(attrs={"rows": 4, "placeholder": "Plazos, alcance, exclusiones, responsabilidades del cliente…"}),
            "notas": forms.Textarea(attrs={"rows": 2}),
        }
        labels = {"garantia_cantidad": "Garantía (tiempo)", "garantia_unidad": "Unidad", "ejecucion_unidad": "Unidad",
                  "descripcion": "Indicaciones para la orden de trabajo"}

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        opciones = list(FormaPago.objects.filter(activa=True).values_list("nombre", flat=True))
        actual = self.instance.forma_pago if self.instance.pk else ""
        if actual and actual not in opciones:
            opciones.append(actual)  # una forma de pago ya usada que luego se desactivó
        self.fields["forma_pago"].choices = [("", "Elige la forma de pago")] + [(o, o) for o in opciones]
        self.fields["forma_pago"].widget.attrs["data-buscar"] = "forma_pago"
        if not self.instance.pk:
            # Para no reescribirlas cada vez: se proponen las de la última proforma
            ultima = Proforma.objects.order_by("-creado").first()
            if ultima:
                for campo in ("forma_pago", "garantia_cantidad", "garantia_unidad", "garantia_nota", "condiciones_generales",
                              "ejecucion_unidad", "ejecucion_nota"):
                    self.initial.setdefault(campo, getattr(ultima, campo))


class FormaPagoForm(forms.ModelForm):
    class Meta:
        model = FormaPago
        fields = ["nombre", "orden", "activa"]
        widgets = {"nombre": forms.TextInput(attrs={"placeholder": "Ej.: 60% Anticipo 40% Al terminar"})}

    def clean_nombre(self):
        nombre = " ".join(self.cleaned_data["nombre"].split())
        if FormaPago.objects.filter(nombre__iexact=nombre).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Esa forma de pago ya existe.")
        return nombre


class LineaForm(forms.ModelForm):
    class Meta:
        model = LineaProforma
        fields = ["tipo", "descripcion", "cantidad", "unidad", "precio_unitario"]
        widgets = {
            "cantidad": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}),
            "precio_unitario": forms.NumberInput(attrs={"step": "0.01", "min": "0"}),
            "unidad": forms.TextInput(attrs={"size": 4}),
        }


LineasFormSet = inlineformset_factory(
    Proforma, LineaProforma, form=LineaForm, extra=0, can_delete=True, min_num=1, validate_min=True
)


class TecnicosField(forms.ModelMultipleChoiceField):
    widget = forms.CheckboxSelectMultiple

    def label_from_instance(self, u):
        return u.get_full_name() or u.username


class EquiposWidget(forms.CheckboxSelectMultiple):
    """Casillas de equipos con data-cliente para mostrar solo los del cliente elegido."""

    def create_option(self, name, value, label, selected, index, subindex=None, attrs=None):
        opcion = super().create_option(name, value, label, selected, index, subindex, attrs)
        instancia = getattr(value, "instance", None)
        if instancia is not None:
            opcion["attrs"]["data-cliente"] = instancia.cliente_id
        return opcion


class EquiposField(forms.ModelMultipleChoiceField):
    widget = EquiposWidget

    def label_from_instance(self, e):
        detalle = " ".join(x for x in (e.get_tipo_display(), e.marca, e.ubicacion) if x)
        return f"{e.nombre} ({detalle})" if detalle else e.nombre


class OrdenForm(ClientesActivosMixin, forms.ModelForm):
    tecnicos = TecnicosField(queryset=None, required=False, label="Técnicos asignados")
    equipos = EquiposField(queryset=None, required=False, label="Equipos del cliente")

    class Meta:
        model = OrdenTrabajo
        fields = [
            "cliente", "titulo", "equipos", "ubicacion", "horas_estimadas", "fecha_inicio", "fecha_fin",
            "tecnicos", "instrucciones", "descripcion", "notas",
        ]
        widgets = {
            "fecha_inicio": FECHA, "fecha_fin": FECHA,
            "horas_estimadas": forms.NumberInput(attrs={"step": "0.5", "min": "0"}),
            "instrucciones": forms.Textarea(attrs={"rows": 3, "placeholder": "Luis: desmontar y cambiar cables. Ana: pruebas de frenado…"}),
            "descripcion": forms.Textarea(attrs={"rows": 3}), "notas": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Técnicos activos, más los ya asignados a esta orden aunque hoy estén deshabilitados
        asignados = list(self.instance.tecnicos.values_list("pk", flat=True)) if self.instance.pk else []
        self.fields["tecnicos"].queryset = (
            cuentas_empresa()
            .filter(Q(is_active=True, groups__name=ROLES[TECNICO]) | Q(pk__in=asignados))
            .distinct().order_by("first_name", "username")
        )
        self.fields["tecnicos"].help_text = "Cuentas con el rol Técnico. Verán esta orden y podrán generar informes."
        en_uso = list(self.instance.equipos.values_list("pk", flat=True)) if self.instance.pk else []
        self.fields["equipos"].queryset = (
            Equipo.objects.filter(Q(activo=True) | Q(pk__in=en_uso)).select_related("cliente").order_by("cliente__nombre", "nombre")
        )
        self.fields["equipos"].help_text = "Solo se muestran los del cliente elegido."

    def clean(self):
        datos = super().clean()
        inicio, fin = datos.get("fecha_inicio"), datos.get("fecha_fin")
        if inicio and fin and fin < inicio:
            self.add_error("fecha_fin", "La finalización no puede ser anterior al inicio.")
        cliente = datos.get("cliente")
        ajenos = [e for e in (datos.get("equipos") or []) if cliente and e.cliente_id != cliente.pk]
        if ajenos:
            self.add_error("equipos", f"«{ajenos[0].nombre}» es de otro cliente.")
        return datos


class RecursoForm(forms.ModelForm):
    class Meta:
        model = Recurso
        fields = ["tipo", "descripcion", "cantidad", "unidad"]
        widgets = {"cantidad": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}), "unidad": forms.TextInput(attrs={"size": 4})}


RecursosFormSet = inlineformset_factory(OrdenTrabajo, Recurso, form=RecursoForm, extra=1, can_delete=True)


class InformeForm(forms.ModelForm):
    class Meta:
        model = Informe
        fields = ["orden", "fecha", "horas_trabajadas", "trabajo_realizado", "materiales_usados", "observaciones", "trabajo_terminado"]
        widgets = {
            "fecha": FECHA,
            "horas_trabajadas": forms.NumberInput(attrs={"step": "0.5", "min": "0"}),
            "trabajo_realizado": forms.Textarea(attrs={"rows": 4, "placeholder": "Qué se hizo, en qué equipo, resultado de las pruebas…"}),
            "materiales_usados": forms.Textarea(attrs={"rows": 2, "placeholder": "Ej.: 30 m de cable de acero, 2 poleas"}),
            "observaciones": forms.Textarea(attrs={"rows": 2, "placeholder": "Pendientes, recomendaciones, novedades del cliente…"}),
        }
        labels = {"orden": "Orden de trabajo"}

    def __init__(self, *args, tecnico, **kwargs):
        super().__init__(*args, **kwargs)
        ordenes = OrdenTrabajo.objects.filter(
            tecnicos=tecnico, estado__in=[OrdenTrabajo.Estado.PENDIENTE, OrdenTrabajo.Estado.EN_CURSO]
        ).select_related("cliente")
        self.fields["orden"].queryset = ordenes
        self.fields["orden"].label_from_instance = lambda o: f"{o.numero} · {o.titulo} ({o.cliente})"
        self.fields["orden"].empty_label = "Elige la orden de trabajo"
