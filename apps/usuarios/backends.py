from django.contrib.auth import get_user_model
from django.contrib.auth.backends import ModelBackend


class UsuarioSinMayusculasBackend(ModelBackend):
    """Inicio de sesión con el usuario sin distinguir mayúsculas ni espacios al inicio/final.

    «Prueba22», «prueba22 » y «PRUEBA22» entran a la misma cuenta. La contraseña sí distingue mayúsculas.
    (Los usuarios ya son únicos sin distinguir mayúsculas: lo valida el formulario de cuentas.)
    """

    def authenticate(self, request, username=None, password=None, **kwargs):
        Usuario = get_user_model()
        if username is None:
            username = kwargs.get(Usuario.USERNAME_FIELD)
        if username is None or password is None:
            return None
        username = username.strip()
        coincidencias = list(Usuario._default_manager.filter(username__iexact=username)[:2])
        if len(coincidencias) != 1:
            # Ninguna, o dos que solo difieren en mayúsculas (datos antiguos): se exige la forma exacta
            exacta = next((u for u in coincidencias if u.username == username), None)
            if exacta is None:
                Usuario().set_password(password)  # mismo coste que una comprobación real (evita adivinar usuarios)
                return None
            coincidencias = [exacta]
        usuario = coincidencias[0]
        if usuario.check_password(password) and self.user_can_authenticate(usuario):
            return usuario
        return None
