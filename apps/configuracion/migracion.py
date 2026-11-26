"""Ayuda para las migraciones a multiempresa: los datos que ya existían pasan a la primera empresa."""


def empresa_inicial(apps):
    """La empresa más antigua; si no hay ninguna (había datos pero no se configuró la empresa), crea «Empresa»."""
    Empresa = apps.get_model("configuracion", "Empresa")
    empresa = Empresa.objects.order_by("pk").first()
    if empresa is None:
        empresa = Empresa.objects.create(nombre="Empresa")
    return empresa


def asignar_a_empresa_inicial(app_label, *modelos):
    """Operación RunPython: pone la empresa inicial a las filas sin empresa de esos modelos."""

    def ejecutar(apps, schema_editor):
        for nombre in modelos:
            Modelo = apps.get_model(app_label, nombre)
            pendientes = Modelo.objects.filter(empresa__isnull=True)
            if pendientes.exists():
                pendientes.update(empresa=empresa_inicial(apps))

    return ejecutar
