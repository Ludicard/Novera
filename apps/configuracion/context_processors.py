from .models import tema_aplicacion


def tema(request):
    """Color de la aplicación elegido en Configuración (azul por defecto)."""
    try:
        return {"tema_app": tema_aplicacion()}
    except Exception:  # p. ej. antes de migrar: la app sigue en azul
        return {"tema_app": None}
