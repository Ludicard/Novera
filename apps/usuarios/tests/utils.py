from apps.usuarios.roles import SESION_ROL, asignar_roles


def entrar_como(client, usuario, rol, roles=None):
    """Inicia sesión y deja elegido `rol` (asignándole a la cuenta `roles` o solo ese rol)."""
    asignar_roles(usuario, roles or [rol])
    client.force_login(usuario)
    sesion = client.session
    sesion[SESION_ROL] = rol
    sesion.save()
