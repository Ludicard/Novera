import django.db.models.deletion
from django.db import migrations, models

from apps.configuracion.migracion import asignar_a_empresa_inicial


class Migration(migrations.Migration):
    dependencies = [("clientes", "0003_retencion_y_contacto"), ("configuracion", "0003_multiempresa")]

    operations = [
        migrations.RemoveConstraint(model_name="cliente", name="cliente_nombre_unico"),
        migrations.AddField(
            model_name="cliente", name="empresa",
            field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="+", to="configuracion.empresa"),
        ),
        migrations.RunPython(asignar_a_empresa_inicial("clientes", "Cliente"), migrations.RunPython.noop),
    ]
