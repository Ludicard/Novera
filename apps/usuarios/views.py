from django.contrib.auth.decorators import login_required
from django.shortcuts import redirect, render
from django.utils.http import url_has_allowed_host_and_scheme

from .roles import DESCRIPCIONES, ROLES, SESION_ROL


def _siguiente(request):
    url = request.POST.get("siguiente") or request.GET.get("siguiente") or ""
    if url and url_has_allowed_host_and_scheme(url, allowed_hosts={request.get_host()}, require_https=request.is_secure()):
        return url
    return ""


@login_required
def elegir_rol(request):
    """Pantalla de selección de rol: aparece en cada inicio de sesión, aunque la cuenta tenga un solo rol."""
    disponibles = request.roles
    if not disponibles:
        return render(request, "usuarios/sin_rol.html", status=403)
    error = ""
    if request.method == "POST":
        clave = request.POST.get("rol")
        if clave in disponibles:
            request.session[SESION_ROL] = clave
            return redirect(_siguiente(request) or "dashboard")
        error = "Ese rol no está disponible para tu cuenta."
    return render(
        request,
        "usuarios/elegir_rol.html",
        {
            "opciones": [{"clave": c, "nombre": ROLES[c], "descripcion": DESCRIPCIONES[c]} for c in disponibles],
            "siguiente": _siguiente(request),
            "error": error,
        },
        status=400 if error else 200,
    )
