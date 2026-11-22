from urllib.parse import urlencode, urlparse

from django.shortcuts import redirect, render
from django.urls import reverse
from django.utils.http import url_has_allowed_host_and_scheme

from django.contrib import messages

from .roles import SESION_ROL, TECNICO, roles_de, roles_disponibles

# Secciones que no corresponden al rol Técnico (su menú: Mis tareas y sus órdenes de trabajo)
SOLO_GESTION = (
    "/panel/", "/facturas/", "/clientes/", "/finanzas/", "/usuarios/",
    "/trabajos/proformas/", "/trabajos/asignar/", "/trabajos/ordenes/nueva/",
)

# Rutas que funcionan sin rol elegido (o sin rol): estáticos, salud, salir, contraseña y el propio selector
PREFIJOS_LIBRES = ("/static/", "/media/", "/salud/", "/cuentas/password_", "/cuentas/reset/")


def ruta_libre(ruta):
    return ruta.startswith(PREFIJOS_LIBRES) or ruta in {
        reverse("logout"),
        reverse("login"),
        reverse("admin:logout"),
        reverse("usuarios:elegir_rol"),
    }


class RolMiddleware:
    """Pone en la petición los roles disponibles (`request.roles`) y el rol activo (`request.rol`).

    - Cuenta sin ningún rol: aviso, no puede usar la app.
    - Cuenta con roles pero sin rol elegido en esta sesión: va a la pantalla de selección
      (y después vuelve a donde iba). El admin de Django queda libre para superusuarios.
    """

    def __init__(self, get_response):
        self.get_response = get_response

    def __call__(self, request):
        request.roles, request.rol = [], None
        usuario = getattr(request, "user", None)
        if usuario is None or not usuario.is_authenticated:
            return self.get_response(request)

        request.roles = roles_disponibles(roles_de(usuario))
        elegido = request.session.get(SESION_ROL)
        request.rol = elegido if elegido in request.roles else None

        ruta = request.path
        if ruta_libre(ruta) or (usuario.is_superuser and ruta.startswith("/admin/")):
            return self.get_response(request)
        if not request.roles:
            return render(request, "usuarios/sin_rol.html", status=403)
        if request.rol is None:
            return redirect(self._selector(request))
        if request.rol == TECNICO and ruta.startswith(SOLO_GESTION):
            messages.info(request, "Esa sección no está disponible con el rol Técnico.")
            return redirect("inicio")
        return self.get_response(request)

    @staticmethod
    def _selector(request):
        destino = reverse("usuarios:elegir_rol")
        if request.method == "GET":
            volver = request.get_full_path()
        else:
            # Un formulario enviado sin rol activo: tras elegir, volver a la página del formulario
            referer = request.META.get("HTTP_REFERER", "")
            ok = url_has_allowed_host_and_scheme(referer, allowed_hosts={request.get_host()})
            volver = urlparse(referer).path if ok and referer else ""
        if volver and volver != "/":
            destino += "?" + urlencode({"siguiente": volver})
        return destino
