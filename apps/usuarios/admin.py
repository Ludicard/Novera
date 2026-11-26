"""Admin de Django para usuarios: solo lo usan superusuarios. El día a día va por Novera → Usuarios."""

from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import User

from .forms import RolesField
from .models import PerfilUsuario
from .roles import ROLES, asignar_roles, roles_de


class ConRoles(forms.ModelForm):
    roles = RolesField()

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["roles"].initial = roles_de(self.instance)


class FormCambio(ConRoles, UserChangeForm):
    pass


class FormAlta(ConRoles, UserCreationForm):
    pass


admin.site.unregister(User)


class PerfilInline(admin.StackedInline):
    model = PerfilUsuario
    can_delete = False
    verbose_name = "Empresa"
    verbose_name_plural = "Empresa"


@admin.register(User)
class UsuarioAdmin(UserAdmin):
    inlines = [PerfilInline]
    form = FormCambio
    add_form = FormAlta
    list_display = ["username", "first_name", "last_name", "email", "empresa", "roles_novera", "is_active", "last_login"]
    list_filter = ["is_active", "is_superuser", "perfil__empresa"]
    list_select_related = ["perfil__empresa"]
    # Sin «groups» ni «user_permissions»: los roles se manejan solo con el campo «Roles»
    fieldsets = (
        (None, {"fields": ("username", "password")}),
        ("Datos", {"fields": ("first_name", "last_name", "email")}),
        ("Acceso", {"fields": ("roles", "is_active", "is_superuser")}),
        ("Fechas", {"fields": ("last_login", "date_joined")}),
    )
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("username", "roles", "password1", "password2")}),)

    @admin.display(description="Empresa", ordering="perfil__empresa__nombre")
    def empresa(self, obj):
        perfil = getattr(obj, "perfil", None)
        return perfil.empresa if perfil else "— sin empresa —"

    @admin.display(description="Roles")
    def roles_novera(self, obj):
        return ", ".join(ROLES[c] for c in roles_de(obj)) or "— sin rol —"

    def save_model(self, request, obj, form, change):
        obj.is_staff = obj.is_superuser  # el admin de Django es solo para superusuarios
        super().save_model(request, obj, form, change)

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        asignar_roles(form.instance, form.cleaned_data["roles"])
