import django.db.models.deletion
from django.db import migrations, models

from apps.configuracion.migracion import asignar_a_empresa_inicial


class Migration(migrations.Migration):
    dependencies = [("facturas", "0004_ordenes_de_trabajo"), ("configuracion", "0003_multiempresa")]

    operations = [
        migrations.RemoveConstraint(model_name="factura", name="factura_clave_acceso_unica"),
        migrations.AlterField(model_name="factura", name="numero",
                              field=models.CharField(max_length=40, verbose_name="Número")),
        migrations.AddField(
            model_name="factura", name="empresa",
            field=models.ForeignKey(editable=False, null=True, on_delete=django.db.models.deletion.PROTECT,
                                    related_name="+", to="configuracion.empresa"),
        ),
        migrations.RunPython(asignar_a_empresa_inicial("facturas", "Factura"), migrations.RunPython.noop),
    ]
