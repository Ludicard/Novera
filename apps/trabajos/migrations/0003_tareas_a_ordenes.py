from django.db import migrations


def pasar_tareas_a_ordenes(apps, schema_editor):
    """Cada tarea pasa a ser: técnico asignado a la orden + sus responsabilidades en las instrucciones."""
    Tarea = apps.get_model("trabajos", "Tarea")
    for t in Tarea.objects.select_related("orden", "tecnico").order_by("pk"):
        orden = t.orden
        orden.tecnicos.add(t.tecnico)
        nombre = (f"{t.tecnico.first_name} {t.tecnico.last_name}".strip() or t.tecnico.username)
        bloque = f"{nombre}: {t.responsabilidades.strip()}"
        if t.fecha_limite:
            bloque += f" (hasta {t.fecha_limite:%d/%m/%Y})"
        if bloque not in orden.instrucciones:
            orden.instrucciones = f"{orden.instrucciones}\n{bloque}".strip()
            orden.save(update_fields=["instrucciones"])


class Migration(migrations.Migration):
    dependencies = [("trabajos", "0002_tecnicos_e_informes")]
    operations = [
        migrations.RunPython(pasar_tareas_a_ordenes, migrations.RunPython.noop),
        migrations.DeleteModel(name="Tarea"),
    ]
