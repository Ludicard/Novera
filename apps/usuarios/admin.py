from django import forms
from django.contrib import admin
from django.contrib.auth.admin import UserAdmin
from django.contrib.auth.forms import UserChangeForm, UserCreationForm
from django.contrib.auth.models import User

from .roles import ROLES, asignar_rol, rol_de

OPCIONES = [(clave, nombre) for clave, nombre in ROLES.items()]


class ConRol(forms.ModelForm):
    rol = forms.ChoiceField(choices=OPCIONES, label="Rol en Novera")

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance.pk:
            self.fields["rol"].initial = rol_de(self.instance)


class FormCambio(ConRol, UserChangeForm):
    pass


class FormAlta(ConRol, UserCreationForm):
    pass


admin.site.unregister(User)


@admin.register(User)
class UsuarioAdmin(UserAdmin):
    form = FormCambio
    add_form = FormAlta
    list_display = ["username", "first_name", "last_name", "email", "rol_novera", "is_active", "last_login"]
    list_filter = ["groups", "is_active", "is_superuser"]
    fieldsets = ((None, {"fields": ("username", "password", "rol")}),) + UserAdmin.fieldsets[1:]
    add_fieldsets = ((None, {"classes": ("wide",), "fields": ("username", "rol", "password1", "password2")}),)

    @admin.display(description="Rol")
    def rol_novera(self, obj):
        return ROLES.get(rol_de(obj), "— sin rol —")

    def save_related(self, request, form, formsets, change):
        super().save_related(request, form, formsets, change)
        asignar_rol(form.instance, form.cleaned_data["rol"])  # después de guardar los grupos del formulario

    def get_actions(self, request):
        acciones = super().get_actions(request)
        for clave, nombre in ROLES.items():
            def accion(modeladmin, req, queryset, clave=clave, nombre=nombre):
                for usuario in queryset:
                    asignar_rol(usuario, clave)
                modeladmin.message_user(req, f"{queryset.count()} usuario(s) ahora son {nombre}.")

            acciones[f"asignar_{clave}"] = (accion, f"asignar_{clave}", f"Asignar rol: {nombre}")
        return acciones
