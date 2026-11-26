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
        fields = ["nombre", "razon_social", "nombre_comercial", "ruc", "direccion_matriz", "telefono", "email", "web",
                  "color_app", "color_proforma", "logo"]
        widgets = {
            "ruc": forms.TextInput(attrs={"inputmode": "numeric", "maxlength": 13, "autocomplete": "off"}),
            "logo": forms.FileInput(attrs={"accept": "image/png,image/jpeg"}),
            "color_app": forms.TextInput(attrs={"placeholder": "#1F4E5F", "maxlength": 7, "data-color": "1", "autocomplete": "off"}),
            "color_proforma": forms.TextInput(attrs={"placeholder": "#1F4E5F", "maxlength": 7, "data-color": "1", "autocomplete": "off"}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["nombre"].required = True
        self.fields["nombre"].widget.attrs.setdefault("placeholder", "Ej.: EmpresaAutos")

    def clean_nombre(self):
        return " ".join(self.cleaned_data["nombre"].split())

    def clean_razon_social(self):
        return " ".join(self.cleaned_data["razon_social"].split())

    def _color(self, campo):
        from .colores import normalizar

        try:
            return normalizar(self.cleaned_data.get(campo))
        except ValueError:
            raise forms.ValidationError("Escribe un código de color de 6 dígitos hexadecimales, por ejemplo #D9A21B.")

    def clean_color_app(self):
        return self._color("color_app")

    def clean_color_proforma(self):
        return self._color("color_proforma")

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
