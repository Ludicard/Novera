import django.utils.timezone
from django.db import migrations, models

import apps.configuracion.models


def nombre_desde_datos(apps, schema_editor):
    Empresa = apps.get_model("configuracion", "Empresa")
    for e in Empresa.objects.filter(nombre=""):
        e.nombre = (e.nombre_comercial or e.razon_social or "")[:120]
        e.save(update_fields=["nombre"])


def reajustar_secuencia(apps, schema_editor):
    """Antes la empresa se guardaba siempre con id=1 explícito, y en PostgreSQL eso no avanza la secuencia:
    sin este reajuste, la primera empresa nueva intentaría usar el id 1 y fallaría."""
    from django.core.management.color import no_style

    Empresa = apps.get_model("configuracion", "Empresa")
    conexion = schema_editor.connection
    with conexion.cursor() as cursor:
        for sql in conexion.ops.sequence_reset_sql(no_style(), [Empresa]):
            cursor.execute(sql)


class Migration(migrations.Migration):
    dependencies = [("configuracion", "0002_colores")]

    operations = [
        migrations.AlterModelOptions(
            name="empresa", options={"ordering": ["pk"], "verbose_name": "empresa", "verbose_name_plural": "empresas"},
        ),
        migrations.AddField(
            model_name="empresa", name="nombre",
            field=models.CharField(blank=True, help_text="Sale en la barra superior junto a «Novera».", max_length=120,
                                   verbose_name="Nombre de la empresa"),
        ),
        migrations.AddField(
            model_name="empresa", name="creado",
            field=models.DateTimeField(auto_now_add=True, default=django.utils.timezone.now, null=True),
            preserve_default=False,
        ),
        migrations.AlterField(model_name="empresa", name="razon_social",
                              field=models.CharField(blank=True, max_length=200, verbose_name="Razón social")),
        migrations.AlterField(model_name="empresa", name="ruc",
                              field=models.CharField(blank=True, max_length=13, validators=[apps.configuracion.models.validar_ruc], verbose_name="RUC")),
        migrations.AlterField(model_name="empresa", name="direccion_matriz",
                              field=models.CharField(blank=True, max_length=255, verbose_name="Dirección matriz")),
        migrations.AlterField(model_name="empresa", name="telefono",
                              field=models.CharField(blank=True, max_length=60, verbose_name="Teléfono")),
        migrations.AlterField(model_name="empresa", name="email",
                              field=models.EmailField(blank=True, max_length=254, verbose_name="Email")),
        migrations.AlterField(
            model_name="empresa", name="logo",
            field=models.ImageField(blank=True, help_text="PNG o JPG, hasta 2 MB. Se usa en las proformas en PDF.",
                                    upload_to=apps.configuracion.models.ruta_logo, verbose_name="Logo"),
        ),
        migrations.RunPython(nombre_desde_datos, migrations.RunPython.noop),
        migrations.RunPython(reajustar_secuencia, migrations.RunPython.noop),
    ]
