from django import forms
from django.contrib.auth import get_user_model, password_validation

from .roles import ADMINISTRADOR, ROLES, administradores_activos, roles_de

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
        self.actor = actor
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
        if era_admin and not sigue_admin and not administradores_activos(excluir=u).exists():
            self.add_error(None, "Debe quedar al menos un Administrador activo.")
        return datos
