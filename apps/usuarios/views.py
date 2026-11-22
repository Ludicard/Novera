from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect
from django.utils.http import url_has_allowed_host_and_scheme
from django.views.decorators.http import require_POST

from .roles import ADMINISTRADOR, ROLES, SESION_ROL, roles_disponibles


@login_required
@require_POST
def cambiar_rol(request):
    """El Administrador elige con qué rol trabaja en esta sesión."""
    volver = request.POST.get("siguiente", "")
    if not url_has_allowed_host_and_scheme(volver, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        volver = "dashboard"
    clave = request.POST.get("rol")
    if request.rol_asignado != ADMINISTRADOR or clave not in roles_disponibles(ADMINISTRADOR):
        messages.error(request, "Tu cuenta no puede cambiar de rol.")
        return redirect(volver)
    request.session[SESION_ROL] = clave
    messages.info(request, f"Ahora estás usando Novera como {ROLES[clave]}.")
    return redirect(volver)
