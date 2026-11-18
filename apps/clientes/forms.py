from django import forms

from .models import Cliente


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
        return self.cleaned_data["identificacion"].strip()
