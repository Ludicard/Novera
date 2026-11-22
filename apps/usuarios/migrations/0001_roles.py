from django.db import migrations

ROLES = ["Administrador", "Manager", "Técnico"]


def crear_roles(apps, schema_editor):
    Group = apps.get_model("auth", "Group")
    User = apps.get_model("auth", "User")
    grupos = {n: Group.objects.get_or_create(name=n)[0] for n in ROLES}
    # Las cuentas que ya existen: superusuarios -> Administrador
    for usuario in User.objects.filter(is_superuser=True):
        if not usuario.groups.filter(name__in=ROLES).exists():
            usuario.groups.add(grupos["Administrador"])


class Migration(migrations.Migration):
    dependencies = [("auth", "0012_alter_user_first_name_max_length")]
    operations = [migrations.RunPython(crear_roles, migrations.RunPython.noop)]
