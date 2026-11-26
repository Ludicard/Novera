from django.core.management.base import BaseCommand, CommandError

from apps.facturas import importador


class Command(BaseCommand):
    help = "Importa facturas desde el Excel histórico. Sin --aplicar solo muestra lo que haría."

    def add_arguments(self, parser):
        parser.add_argument("archivo")
        parser.add_argument("--empresa", type=int, required=True, help="ID de la empresa a la que se importa.")
        parser.add_argument("--estado-desconocido", choices=["pendiente", "pagada"], default="pendiente")
        parser.add_argument("--aplicar", action="store_true", help="Guardar en la base de datos.")
        parser.add_argument("--avisos", action="store_true", help="Listar los avisos fila por fila.")

    def handle(self, archivo, empresa, **opciones):
        from apps.configuracion.actual import usar_empresa
        from apps.configuracion.models import Empresa

        e = Empresa.objects.filter(pk=empresa).first()
        if e is None:
            raise CommandError(f"No existe la empresa {empresa}.")
        self.stdout.write(f"Empresa: {e} (id {e.pk})")
        with usar_empresa(e):
            self._importar(archivo, **opciones)

    def _importar(self, archivo, estado_desconocido, aplicar, avisos, **_):
        resultado = importador.analizar(archivo, estado_desconocido)
        if resultado.errores:
            raise CommandError("; ".join(resultado.errores))
        for clave, valor in resultado.resumen().items():
            self.stdout.write(f"{clave:>16}: {valor}")
        if avisos:
            for fila in resultado.filas:
                if fila.avisos:
                    marca = "OMITIDA" if fila.omitida else "aviso"
                    self.stdout.write(f"  fila {fila.fila} [{marca}] {fila.numero}: {'; '.join(fila.avisos)}")
        if aplicar:
            creados = importador.aplicar(resultado)
            self.stdout.write(self.style.SUCCESS(f"Importado: {creados}"))
        else:
            self.stdout.write(self.style.WARNING("Simulación: no se guardó nada (usa --aplicar)."))
