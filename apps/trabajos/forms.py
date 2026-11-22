from django import forms
from django.contrib.auth import get_user_model
from django.forms import inlineformset_factory

from apps.clientes.models import Cliente
from apps.usuarios.roles import ROLES, TECNICO

from .models import LineaProforma, OrdenTrabajo, Proforma, Recurso, Tarea

FECHA = forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d")
TASAS_IVA = [("15", "15 %"), ("12", "12 %"), ("5", "5 %"), ("0", "0 %")]


def tecnicos():
    """Cuentas activas con el rol Técnico."""
    return (
        get_user_model().objects.filter(is_active=True, groups__name=ROLES[TECNICO])
        .distinct().order_by("first_name", "username")
    )


class TecnicoChoiceField(forms.ModelChoiceField):
    def label_from_instance(self, u):
        return u.get_full_name() or u.username


class ClientesActivosMixin:
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        actual = getattr(self.instance, "cliente_id", None)
        self.fields["cliente"].queryset = Cliente.objects.filter(activo=True) | Cliente.objects.filter(pk=actual)
        self.fields["cliente"].empty_label = "Elige un cliente"


class ProformaForm(ClientesActivosMixin, forms.ModelForm):
    porcentaje_iva = forms.TypedChoiceField(label="% IVA", choices=TASAS_IVA, coerce=str, initial="15")

    class Meta:
        model = Proforma
        fields = ["cliente", "titulo", "fecha", "validez_dias", "porcentaje_iva", "descripcion", "notas"]
        widgets = {"fecha": FECHA, "descripcion": forms.Textarea(attrs={"rows": 3}), "notas": forms.Textarea(attrs={"rows": 2})}


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


class OrdenForm(ClientesActivosMixin, forms.ModelForm):
    class Meta:
        model = OrdenTrabajo
        fields = ["cliente", "titulo", "ubicacion", "horas_estimadas", "fecha_inicio", "fecha_fin", "descripcion", "notas"]
        widgets = {
            "fecha_inicio": FECHA, "fecha_fin": FECHA,
            "horas_estimadas": forms.NumberInput(attrs={"step": "0.5", "min": "0"}),
            "descripcion": forms.Textarea(attrs={"rows": 3}), "notas": forms.Textarea(attrs={"rows": 2}),
        }

    def clean(self):
        datos = super().clean()
        inicio, fin = datos.get("fecha_inicio"), datos.get("fecha_fin")
        if inicio and fin and fin < inicio:
            self.add_error("fecha_fin", "La finalización no puede ser anterior al inicio.")
        return datos


class RecursoForm(forms.ModelForm):
    class Meta:
        model = Recurso
        fields = ["tipo", "descripcion", "cantidad", "unidad"]
        widgets = {"cantidad": forms.NumberInput(attrs={"step": "0.01", "min": "0.01"}), "unidad": forms.TextInput(attrs={"size": 4})}


RecursosFormSet = inlineformset_factory(OrdenTrabajo, Recurso, form=RecursoForm, extra=1, can_delete=True)


class TareaForm(forms.ModelForm):
    tecnico = TecnicoChoiceField(queryset=None, label="Técnico", empty_label="Elige un técnico")

    class Meta:
        model = Tarea
        fields = ["orden", "tecnico", "responsabilidades", "fecha_limite", "horas_estimadas"]
        widgets = {
            "fecha_limite": FECHA,
            "responsabilidades": forms.Textarea(attrs={"rows": 3, "placeholder": "Qué debe hacer: revisar…, instalar…, reportar…"}),
            "horas_estimadas": forms.NumberInput(attrs={"step": "0.5", "min": "0"}),
        }
        labels = {"orden": "Orden de trabajo"}

    def __init__(self, *args, orden=None, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["tecnico"].queryset = tecnicos()
        abiertas = OrdenTrabajo.objects.filter(estado__in=[OrdenTrabajo.Estado.PENDIENTE, OrdenTrabajo.Estado.EN_CURSO])
        self.fields["orden"].queryset = abiertas.select_related("cliente")
        self.fields["orden"].label_from_instance = lambda o: f"{o.numero} · {o.titulo} ({o.cliente})"
        self.fields["orden"].empty_label = "Elige la orden"
        if orden is not None:
            self.fields["orden"].initial = orden
            self.fields["orden"].widget = forms.HiddenInput()
            if orden.fecha_fin:
                self.fields["fecha_limite"].initial = orden.fecha_fin


class AvanceTareaForm(forms.ModelForm):
    """Lo que el técnico actualiza de su tarea."""

    class Meta:
        model = Tarea
        fields = ["estado", "comentario"]
        widgets = {"comentario": forms.Textarea(attrs={"rows": 2, "placeholder": "Opcional: qué se hizo, qué falta…"})}
