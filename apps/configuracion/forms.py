from io import BytesIO

from django import forms
from django.core.files.base import ContentFile
from PIL import Image, UnidentifiedImageError

from .models import Empresa

MAX_LOGO = 2 * 1024 * 1024
ANCHO_MAX_LOGO = 1200


class EmpresaForm(forms.ModelForm):
    quitar_logo = forms.BooleanField(label="Quitar el logo actual", required=False)

    class Meta:
        model = Empresa
        fields = ["razon_social", "nombre_comercial", "ruc", "direccion_matriz", "telefono", "email", "web", "logo"]
        widgets = {
            "ruc": forms.TextInput(attrs={"inputmode": "numeric", "maxlength": 13, "autocomplete": "off"}),
            "logo": forms.FileInput(attrs={"accept": "image/png,image/jpeg"}),
        }

    def clean_razon_social(self):
        return " ".join(self.cleaned_data["razon_social"].split())

    def clean_ruc(self):
        return self.cleaned_data["ruc"].strip()

    def clean_logo(self):
        """Acepta solo PNG/JPG reales de hasta 2 MB y los vuelve a guardar como PNG limpio (sin metadatos ni nada oculto)."""
        archivo = self.cleaned_data.get("logo")
        if not archivo or archivo == getattr(self.instance, "logo", None):
            return archivo
        if archivo.size > MAX_LOGO:
            raise forms.ValidationError("El logo no puede pesar más de 2 MB.")
        try:
            imagen = Image.open(archivo)
            imagen.verify()  # que sea de verdad una imagen íntegra
            archivo.seek(0)
            imagen = Image.open(archivo)
            if imagen.format not in ("PNG", "JPEG"):
                raise forms.ValidationError("El logo debe ser PNG o JPG.")
            imagen = imagen.convert("RGBA")
        except (UnidentifiedImageError, OSError, SyntaxError):
            raise forms.ValidationError("El archivo no es una imagen PNG o JPG válida.")
        if imagen.width > ANCHO_MAX_LOGO:
            alto = round(imagen.height * ANCHO_MAX_LOGO / imagen.width)
            imagen = imagen.resize((ANCHO_MAX_LOGO, alto), Image.LANCZOS)
        salida = BytesIO()
        imagen.save(salida, format="PNG", optimize=True)
        return ContentFile(salida.getvalue(), name="logo-empresa.png")
