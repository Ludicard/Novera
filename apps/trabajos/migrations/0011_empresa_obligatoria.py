import django.db.models.deletion
from django.db import migrations, models


def campo_empresa():
    return models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="+",
                             to="configuracion.empresa")


class Migration(migrations.Migration):
    dependencies = [("trabajos", "0010_empresa")]

    operations = [
        migrations.AlterField(model_name="formapago", name="empresa", field=campo_empresa()),
        migrations.AlterField(model_name="proforma", name="empresa", field=campo_empresa()),
        migrations.AlterField(model_name="ordentrabajo", name="empresa", field=campo_empresa()),
        migrations.AddConstraint(
            model_name="formapago",
            constraint=models.UniqueConstraint(fields=("empresa", "nombre"), name="forma_pago_unica_por_empresa"),
        ),
        migrations.AddConstraint(
            model_name="proforma",
            constraint=models.UniqueConstraint(fields=("empresa", "numero"), name="proforma_numero_unico_por_empresa"),
        ),
        migrations.AddConstraint(
            model_name="ordentrabajo",
            constraint=models.UniqueConstraint(fields=("empresa", "numero"), name="orden_numero_unico_por_empresa"),
        ),
    ]
