import django.db.models.deletion
from django.db import migrations, models

from apps.configuracion.migracion import asignar_a_empresa_inicial


def campo_empresa():
    return models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.PROTECT,
                             related_name="+", to="configuracion.empresa")


class Migration(migrations.Migration):
    dependencies = [("trabajos", "0009_procesar"), ("configuracion", "0003_multiempresa")]

    operations = [
        migrations.AlterField(model_name="formapago", name="nombre", field=models.CharField(max_length=120)),
        migrations.AlterField(model_name="proforma", name="numero",
                              field=models.CharField(editable=False, max_length=20, verbose_name="Número")),
        migrations.AlterField(model_name="ordentrabajo", name="numero",
                              field=models.CharField(editable=False, max_length=20, verbose_name="Número")),
        migrations.AddField(model_name="formapago", name="empresa", field=campo_empresa()),
        migrations.AddField(model_name="proforma", name="empresa", field=campo_empresa()),
        migrations.AddField(model_name="ordentrabajo", name="empresa", field=campo_empresa()),
        migrations.RunPython(asignar_a_empresa_inicial("trabajos", "FormaPago", "Proforma", "OrdenTrabajo"),
                             migrations.RunPython.noop),
    ]
