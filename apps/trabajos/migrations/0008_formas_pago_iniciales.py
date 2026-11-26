from django.db import migrations

# Antes sembraba aquí las formas de pago iniciales (ya aplicada en producción). Con varias empresas, cada empresa
# recibe las suyas al registrarse (FormaPago.crear_iniciales), así que en una base nueva esta migración no hace nada.


class Migration(migrations.Migration):
    dependencies = [("trabajos", "0007_autorizacion_y_formas_pago")]
    operations = []
