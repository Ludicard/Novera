import django.db.models.deletion
from django.conf import settings
from django.db import migrations, models

from apps.configuracion.migracion import empresa_inicial


def cuentas_a_empresa_inicial(apps, schema_editor):
    """Las cuentas que ya existían pertenecen a la empresa que ya estaba configurada."""
    User = apps.get_model("auth", "User")
    PerfilUsuario = apps.get_model("usuarios", "PerfilUsuario")
    sin_empresa = User.objects.filter(perfil__isnull=True)
    if sin_empresa.exists():
        empresa = empresa_inicial(apps)
        PerfilUsuario.objects.bulk_create([PerfilUsuario(usuario=u, empresa=empresa) for u in sin_empresa])


class Migration(migrations.Migration):
    dependencies = [
        ("usuarios", "0001_roles"),
        ("configuracion", "0003_multiempresa"),
        migrations.swappable_dependency(settings.AUTH_USER_MODEL),
    ]

    operations = [
        migrations.CreateModel(
            name="PerfilUsuario",
            fields=[
                ("id", models.BigAutoField(auto_created=True, primary_key=True, serialize=False, verbose_name="ID")),
                ("empresa", models.ForeignKey(on_delete=django.db.models.deletion.PROTECT, related_name="miembros",
                                              to="configuracion.empresa")),
                ("usuario", models.OneToOneField(on_delete=django.db.models.deletion.CASCADE, related_name="perfil",
                                                 to=settings.AUTH_USER_MODEL)),
            ],
            options={"verbose_name": "empresa de la cuenta", "verbose_name_plural": "empresas de las cuentas"},
        ),
        migrations.RunPython(cuentas_a_empresa_inicial, migrations.RunPython.noop),
    ]
