import django.db.models.deletion
import django.db.models.functions.text
from django.db import migrations, models


class Migration(migrations.Migration):
    dependencies = [("clientes", "0004_empresa")]

    operations = [
        migrations.AlterField(
            model_name="cliente", name="empresa",
            field=models.ForeignKey(editable=False, on_delete=django.db.models.deletion.PROTECT, related_name="+",
                                    to="configuracion.empresa"),
        ),
        migrations.AddConstraint(
            model_name="cliente",
            constraint=models.UniqueConstraint(models.F("empresa"), django.db.models.functions.text.Lower("nombre"),
                                               name="cliente_nombre_unico_por_empresa"),
        ),
    ]
