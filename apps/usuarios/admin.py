from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import User

from .roles import ROLES, agregar_rol, asignar_roles, quitar_rol, roles_de

OPCIONES = list(ROLES.items())


class ConRoles(forms.ModelForm):
    roles = forms.MultipleChoiceField(
        choices=OPCIONES,
        widget=forms.CheckboxSelectMultiple,
        label="Roles en Novera",
        help_text="Roles con los que podrá entrar. Administrador da acceso a los tres.",
    )

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["roles"].initial = roles_de(self.instance)


class FormCambio(ConRoles, UserChangeForm):
    pass


class FormAlta(ConRoles, UserCreationForm):
    pass


admin.site.unregister(User)


@admin.register(User)
class UsuarioAdmin(UserAdmin):
    form = FormCambio
    add_form = FormAlta
    list_display = ["username", "first_name", "last_name", "email", "roles_novera", "is_active", "last_login"]
    list_filter = ["groups", "is_active", "is_superuser"]
    fieldsets = ((None, {"fields": ("username", "password", "roles")}),) + UserAdmin.fieldsets[1:]
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("username", "roles", "password1", "password2")}),)

    @admin.display(description="Roles")
    def roles_novera(self, obj):
        return ", ".join(ROLES[c] for c in roles_de(obj)) or "— sin rol —"

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        asignar_roles(form.instance, form.cleaned_data["roles"])  # después de guardar los grupos del formulario

    def get_actions(self, request):
        acciones = super().get_actions(request)
        for clave, nombre in ROLES.items():
            for verbo, funcion in (("dar", agregar_rol), ("quitar", quitar_rol)):
                def accion(modeladmin, req, queryset, clave=clave, nombre=nombre, funcion=funcion, verbo=verbo):
                    for usuario in queryset:
                        funcion(usuario, clave)
                    hecho = "ahora tienen" if verbo == "dar" else "ya no tienen"
                    modeladmin.message_user(req, f"{queryset.count()} usuario(s) {hecho} el rol {nombre}.")

                texto = f"Dar acceso: {nombre}" if verbo == "dar" else f"Quitar acceso: {nombre}"
                acciones[f"{verbo}_{clave}"] = (accion, f"{verbo}_{clave}", texto)
        return acciones
