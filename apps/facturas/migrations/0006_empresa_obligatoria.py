import django.db.models.deletion
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("facturas", "0005_empresa")]

    operations = [
        migrations.AlterField(
            model_name="factura", name="empresa",
            field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="+",
                                    to="configuracion.empresa"),
        ),
        migrations.AddConstraint(
            model_name="factura",
            constraint=models.UniqueConstraint(fields=("empresa", "numero"), name="factura_numero_unico_por_empresa"),
        ),
        migrations.AddConstraint(
            model_name="factura",
            constraint=models.UniqueConstraint(condition=models.Q(("clave_acceso", ""), _negated=True),
                                               fields=("empresa", "clave_acceso"),
                                               name="factura_clave_acceso_unica_por_empresa"),
        ),
    ]
