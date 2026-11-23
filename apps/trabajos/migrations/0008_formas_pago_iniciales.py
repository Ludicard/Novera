from django.db import migrations

INICIALES = [
    "100% Contra entrega",
    "70% Anticipo 30% Al terminar",
    "50% Anticipo 50% Al terminar",
    "40% Anticipo 60% Al terminar",
]


def crear(apps, schema_editor):
    FormaPago = apps.get_model("trabajos", "FormaPago")
    for i, nombre in enumerate(INICIALES, start=1):
        FormaPago.objects.get_or_create(nombre=nombre, defaults={"orden": i * 10})


class Migration(migrations.Migration):
    dependencies = [("trabajos", "0007_autorizacion_y_formas_pago")]
    operations = [migrations.RunPython(crear, migrations.RunPython.noop)]
