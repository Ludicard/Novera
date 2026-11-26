from django import forms
from django.contrib.auth import get_user_model, password_validation

from .models import unir_a_empresa
from .roles import ADMINISTRADOR, ROLES, TECNICO, administradores_activos, roles_de

Usuario = get_user_model()


class RolesField(forms.MultipleChoiceField):
    widget = forms.CheckboxSelectMultiple

    def __init__(self, **kwargs):
        super().__init__(
            choices=list(ROLES.items()),
            label="Roles",
            help_text="Con qué roles podrá entrar. Administrador incluye también Manager y Técnico.",
            error_messages={"required": "Marca al menos un rol."},
            **kwargs,
        )


class CuentaForm(forms.ModelForm):
    """Alta y edición de cuentas desde Novera, con las reglas que evitan quedarse sin acceso."""

    roles = RolesField()
    activo = forms.BooleanField(
        label="Cuenta activa", required=False, initial=True,
        help_text="Una cuenta desactivada no puede iniciar sesión (sus datos se conservan).",
    )
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Repetir contraseña", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    class Meta:
        model = Usuario
        fields = ["first_name", "last_name", "username", "email"]
        labels = {"first_name": "Nombre", "last_name": "Apellidos", "username": "Usuario", "email": "Email"}
        help_texts = {"username": "Con esto inicia sesión. Letras, números y @ . + - _ (sin espacios)."}

    def __init__(self, *args, actor, **kwargs):
        super().__init__(*args, **kwargs)
        from .models import empresa_de

        self.actor = actor
        self.empresa = empresa_de(actor)
        self.nueva = self.instance.pk is None
        self.fields["first_name"].required = True
        if self.nueva:
            self.fields.pop("activo")
        else:
            # Cambiar la contraseña es opcional al editar: vacía = se mantiene la actual
            for campo in ("password1", "password2"):
                self.fields[campo].required = False
            self.fields["password1"].label = "Nueva contraseña"
            self.fields["password1"].help_text = "Déjala vacía para mantener la actual."
            self.fields["password2"].label = "Repetir nueva contraseña"
            self.fields["roles"].initial = roles_de(self.instance)
            self.fields["activo"].initial = self.instance.is_active
            if self.instance == actor:
                self.fields["activo"].disabled = True
                self.fields["activo"].help_text = "No puedes desactivar tu propia cuenta."
        self.fields["username"].widget.attrs.update({"autocapitalize": "none", "autocomplete": "off"})

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if Usuario.objects.filter(username__iexact=username).exclude(pk=self.instance.pk).exists():
            raise forms.ValidationError("Ya existe una cuenta con ese usuario.")
        return username

    def clean(self):
        datos = super().clean()
        roles = datos.get("roles") or []
        activo = datos.get("activo", True) if not self.nueva else True
        p1, p2 = datos.get("password1") or "", datos.get("password2") or ""
        if p1 or p2:
            if p1 != p2:
                self.add_error("password2", "Las contraseñas no coinciden.")
            else:
                usuario = self.instance if not self.nueva else Usuario(username=datos.get("username", ""))
                try:
                    password_validation.validate_password(p1, usuario)
                except forms.ValidationError as e:
                    self.add_error("password1", e)
        if self.nueva:
            return datos

        u = self.instance
        if u == self.actor and ADMINISTRADOR not in roles and not u.is_superuser:
            self.add_error("roles", "No puedes quitarte el rol Administrador a ti mismo.")
        era_admin = u.is_active and ADMINISTRADOR in roles_de(u)
        sigue_admin = activo and (ADMINISTRADOR in roles or u.is_superuser)
        if era_admin and not sigue_admin and not administradores_activos(self.empresa, excluir=u).exists():
            self.add_error(None, "Debe quedar al menos un Administrador activo.")
        return datos


GRADOS_SUGERIDOS = ["Bachiller", "Bachiller técnico", "Técnico superior", "Tecnólogo", "Ingeniero", "Máster"]


class TecnicoForm(CuentaForm):
    """Ficha del técnico para el Manager: cuenta (nombre, usuario, clave, habilitada) + datos del perfil."""

    grado_academico = forms.CharField(
        label="Grado académico", max_length=120, required=False,
        widget=forms.TextInput(attrs={"list": "grados-sugeridos", "placeholder": "Ej.: Tecnólogo en electromecánica"}),
    )
    capacidades = forms.CharField(
        label="Capacidades adicionales", required=False,
        help_text="Certificaciones, especialidades, equipos que domina, licencias…",
        widget=forms.Textarea(attrs={"rows": 3}),
    )
    telefono = forms.CharField(label="Teléfono (contacto directo)", max_length=30, required=False)
    direccion = forms.CharField(label="Dirección", max_length=255, required=False)
    CAMPOS_PERFIL = ["grado_academico", "capacidades", "telefono", "direccion"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields.pop("roles")
        self.fields.pop("email")
        self.fields["first_name"].label = "Nombre"
        if "activo" in self.fields:
            self.fields["activo"].label = "Cuenta habilitada"
            self.fields["activo"].help_text = "Deshabilitada: no puede iniciar sesión (su historial se conserva)."
        perfil = getattr(self.instance, "perfil_tecnico", None) if self.instance.pk else None
        if perfil:
            for campo in self.CAMPOS_PERFIL:
                self.fields[campo].initial = getattr(perfil, campo)

    def clean(self):
        self.cleaned_data["roles"] = [TECNICO]
        return super().clean()

    def guardar_perfil(self, usuario):
        from apps.trabajos.models import PerfilTecnico

        perfil, _ = PerfilTecnico.objects.get_or_create(usuario=usuario)
        unir_a_empresa(usuario, self.empresa)
        for campo in self.CAMPOS_PERFIL:
            setattr(perfil, campo, self.cleaned_data.get(campo, "").strip())
        perfil.save()
        return perfil


class RegistroForm(forms.ModelForm):
    """Alta de una empresa nueva: quien se registra crea la empresa y queda como su Administrador."""

    empresa = forms.CharField(
        label="Nombre de la empresa", max_length=120,
        help_text="Sale en la barra superior. Puedes cambiarlo después en Configuración.",
        widget=forms.TextInput(attrs={"placeholder": "Ej.: EmpresaAutos", "autocomplete": "organization"}),
    )
    password1 = forms.CharField(label="Contraseña", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))
    password2 = forms.CharField(label="Repetir contraseña", widget=forms.PasswordInput(attrs={"autocomplete": "new-password"}))

    class Meta:
        model = Usuario
        fields = ["first_name", "last_name", "username", "email"]
        labels = {"first_name": "Tu nombre", "last_name": "Apellidos", "username": "Usuario", "email": "Email"}
        help_texts = {"username": "Con esto inicias sesión. Letras, números y @ . + - _ (sin espacios)."}

    field_order = ["empresa", "first_name", "last_name", "username", "email", "password1", "password2"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields["first_name"].required = True
        self.fields["email"].required = True
        self.fields["username"].widget.attrs.update({"autocapitalize": "none", "autocomplete": "username"})

    def clean_empresa(self):
        nombre = " ".join(self.cleaned_data["empresa"].split())
        if not nombre:
            raise forms.ValidationError("Escribe el nombre de la empresa.")
        return nombre

    def clean_username(self):
        username = self.cleaned_data["username"].strip()
        if Usuario.objects.filter(username__iexact=username).exists():
            raise forms.ValidationError("Ya existe una cuenta con ese usuario.")
        return username

    def clean(self):
        datos = super().clean()
        p1, p2 = datos.get("password1") or "", datos.get("password2") or ""
        if p1 != p2:
            self.add_error("password2", "Las contraseñas no coinciden.")
        elif p1:
            usuario = Usuario(username=datos.get("username", ""), first_name=datos.get("first_name", ""),
                              email=datos.get("email", ""))
            try:
                password_validation.validate_password(p1, usuario)
            except forms.ValidationError as e:
                self.add_error("password1", e)
        return datos

    def crear(self):
        """Crea la empresa, la cuenta (Administrador de esa empresa) y las formas de pago iniciales."""
        from django.db import transaction

        from apps.configuracion.models import Empresa
        from apps.trabajos.models import FormaPago

        from .roles import asignar_roles

        with transaction.atomic():
            empresa = Empresa.objects.create(nombre=self.cleaned_data["empresa"])
            usuario = self.save(commit=False)
            usuario.set_password(self.cleaned_data["password1"])
            usuario.save()
            unir_a_empresa(usuario, empresa)
            asignar_roles(usuario, [ADMINISTRADOR])
            FormaPago.crear_iniciales(empresa)
        return usuario
