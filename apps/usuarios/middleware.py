from django.shortcuts import render
from django.urls import reverse

from .roles import ADMINISTRADOR, SESION_ROL, rol_de, roles_disponibles


class RolMiddleware:
    """Pone en la petición el rol asignado (`request.rol_asignado`) y el rol con el que se trabaja
    (`request.rol`). Una cuenta sin rol no puede usar la app hasta que se le asigne uno."""

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.rol_asignado = request.rol = None
        usuario = getattr(request, "user", None)
        if usuario is not None and usuario.is_authenticated:
            request.rol_asignado = rol_de(usuario)
            request.rol = request.rol_asignado
            if request.rol_asignado == ADMINISTRADOR:
                elegido = request.session.get(SESION_ROL)
                if elegido in roles_disponibles(ADMINISTRADOR):
                    request.rol = elegido
            if request.rol is None and not self._exento(request.path):
                return render(request, "usuarios/sin_rol.html", status=403)
        return self.get_response(request)

    @staticmethod
    def _exento(ruta):
        return ruta.startswith(("/static/", "/media/", "/salud/")) or ruta == reverse("logout")
