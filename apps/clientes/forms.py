from django import forms

from .models import Cliente, Equipo


class ClienteForm(forms.ModelForm):
    class Meta:
        model = Cliente
        fields = ["nombre", "identificacion", "email", "telefono", "direccion", "dias_credito", "activo", "notas"]
        widgets = {"notas": forms.Textarea(attrs={"rows": 3})}

    def clean_nombre(self):
        nombre = " ".join(self.cleaned_data["nombre"].split())
        repetido = Cliente.objects.filter(nombre__iexact=nombre).exclude(pk=self.instance.pk)
        if repetido.exists():
            raise forms.ValidationError("Ya existe un cliente con ese nombre.")
        return nombre

    def clean_identificacion(self):
        identificacion = self.cleaned_data["identificacion"].strip()
        if identificacion:
            otro = Cliente.objects.filter(identificacion=identificacion).exclude(pk=self.instance.pk).first()
            if otro:
                raise forms.ValidationError(f"Ese RUC/cédula ya es del cliente «{otro}».")
        return identificacion


class ClienteRapidoForm(ClienteForm):
    class Meta(ClienteForm.Meta):
        fields = ["nombre", "identificacion", "email", "dias_credito"]


class EquipoForm(forms.ModelForm):
    class Meta:
        model = Equipo
        fields = ["cliente", "tipo", "nombre", "marca", "modelo", "numero_serie", "ubicacion", "capacidad",
                  "fecha_instalacion", "activo", "notas"]
        widgets = {
            "fecha_instalacion": forms.DateInput(attrs={"type": "date"}, format="%Y-%m-%d"),
            "notas": forms.Textarea(attrs={"rows": 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        actual = getattr(self.instance, "cliente_id", None)
        self.fields["cliente"].queryset = Cliente.objects.filter(activo=True) | Cliente.objects.filter(pk=actual)
        self.fields["cliente"].empty_label = "Elige un cliente"

    def clean(self):
        datos = super().clean()
        cliente, nombre = datos.get("cliente"), (datos.get("nombre") or "").strip()
        if cliente and nombre:
            repetido = Equipo.objects.filter(cliente=cliente, nombre__iexact=nombre).exclude(pk=self.instance.pk)
            if repetido.exists():
                self.add_error("nombre", "Ese cliente ya tiene un equipo con ese nombre.")
        return datos
