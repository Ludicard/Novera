from .roles import ROLES


def rol(request):
    roles = getattr(request, "roles", [])
    actual = getattr(request, "rol", None)
    return {
        "rol": actual,
        "rol_nombre": ROLES.get(actual, ""),
        "puede_cambiar_rol": len(roles) > 1,
    }
