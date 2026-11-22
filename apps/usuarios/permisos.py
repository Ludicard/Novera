from functools import wraps

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect

from .roles import ROLES


def requiere_rol(*claves):
    """Solo deja pasar si el rol ACTIVO de la sesión es uno de `claves`."""

    def decorador(vista):
        @wraps(vista)
        @login_required
        def envoltura(request, *args, **kwargs):
            if request.rol not in claves:
                nombres = " o ".join(ROLES[c] for c in claves)
                messages.error(request, f"Esa sección es para el rol {nombres}.")
                return redirect("inicio")
            return vista(request, *args, **kwargs)

        return envoltura

    return decorador
