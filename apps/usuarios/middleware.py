from urllib.parse import urlencode

from django.shortcuts import redirect, render
from django.urls import reverse

from .roles import SESION_ROL, roles_de, roles_disponibles


class RolMiddleware:
    """Pone en la petición los roles disponibles (`request.roles`) y el rol activo (`request.rol`).

    - Cuenta sin ningún rol: aviso, no puede usar la app.
    - Cuenta con roles pero sin rol elegido en esta sesión: va a la pantalla de selección.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.roles, request.rol = [], None
        usuario = getattr(request, "user", None)
        if usuario is not None and usuario.is_authenticated:
            request.roles = roles_disponibles(roles_de(usuario))
            elegido = request.session.get(SESION_ROL)
            request.rol = elegido if elegido in request.roles else None
            if not self._exento(request.path):
                if not request.roles:
                    return render(request, "usuarios/sin_rol.html", status=403)
                if request.rol is None:
                    destino = reverse("usuarios:elegir_rol")
                    if request.method == "GET" and request.get_full_path() != "/":
                        destino += "?" + urlencode({"siguiente": request.get_full_path()})
                    return redirect(destino)
        return self.get_response(request)

    @staticmethod
    def _exento(ruta):
        return ruta.startswith(("/static/", "/media/", "/salud/")) or ruta in {
            reverse("logout"),
            reverse("usuarios:elegir_rol"),
        }
