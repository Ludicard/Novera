"""La migración a varias empresas con datos ya cargados (lo que pasa en producción). En CI corre sobre PostgreSQL."""

from datetime import date

from django.db import connection
from django.db.migrations.executor import MigrationExecutor
from django.test import TransactionTestCase

ANTES = [
    ("configuracion", "0002_colores"),
    ("clientes", "0003_retencion_y_contacto"),
    ("facturas", "0004_ordenes_de_trabajo"),
    ("trabajos", "0009_procesar"),
    ("usuarios", "0001_roles"),
]


class MigracionMultiempresaTests(TransactionTestCase):
    def migrar(self, destino):
        executor = MigrationExecutor(connection)
        executor.loader.build_graph()
        executor.migrate(destino)
        return executor.loader.project_state(destino).apps

    def tearDown(self):
        self.migrar(MigrationExecutor(connection).loader.graph.leaf_nodes())

    def test_los_datos_existentes_pasan_a_la_empresa_que_ya_habia(self):
        apps = self.migrar(ANTES)
        Empresa = apps.get_model("configuracion", "Empresa")
        User = apps.get_model("auth", "User")
        Cliente = apps.get_model("clientes", "Cliente")
        Equipo = apps.get_model("clientes", "Equipo")
        Factura = apps.get_model("facturas", "Factura")
        Pago = apps.get_model("facturas", "Pago")
        Proforma = apps.get_model("trabajos", "Proforma")
        OrdenTrabajo = apps.get_model("trabajos", "OrdenTrabajo")
        FormaPago = apps.get_model("trabajos", "FormaPago")

        Empresa.objects.create(pk=1, razon_social="Ascensores S.A.", nombre_comercial="Ascen", ruc="1790000000001",
                               direccion_matriz="Quito", telefono="1", email="a@ejemplo.test")
        User.objects.create(username="jefe", is_superuser=True)
        tec = User.objects.create(username="tec")
        cliente = Cliente.objects.create(nombre="Edificio")
        Equipo.objects.create(cliente=cliente, nombre="A1")
        factura = Factura.objects.create(numero="001-001-000000001", cliente=cliente, periodo=date(2026, 1, 1),
                                         fecha_emision=date(2026, 1, 1), subtotal=100, total=115, clave_acceso="1" * 49)
        Pago.objects.create(factura=factura, monto=10)
        proforma = Proforma.objects.create(numero="PF-00001", cliente=cliente)
        orden = OrdenTrabajo.objects.create(numero="OT-00001", cliente=cliente, titulo="T", proforma=proforma)
        orden.tecnicos.add(tec)
        FormaPago.objects.create(nombre="Contado")

        apps = self.migrar([("configuracion", "0003_multiempresa"), ("clientes", "0005_empresa_obligatoria"),
                            ("facturas", "0006_empresa_obligatoria"), ("trabajos", "0011_empresa_obligatoria"),
                            ("usuarios", "0002_perfil_empresa")])
        Empresa = apps.get_model("configuracion", "Empresa")
        self.assertEqual(list(Empresa.objects.values_list("pk", "nombre")), [(1, "Ascen")])
        # La empresa 1 se había guardado con id explícito: una empresa nueva debe poder crearse (secuencia al día)
        self.assertEqual(Empresa.objects.create(nombre="Nueva").pk, 2)
        PerfilUsuario = apps.get_model("usuarios", "PerfilUsuario")
        self.assertEqual(sorted(PerfilUsuario.objects.values_list("usuario__username", "empresa_id")),
                         [("jefe", 1), ("tec", 1)])
        for app, modelo in [("clientes", "Cliente"), ("facturas", "Factura"), ("trabajos", "Proforma"),
                            ("trabajos", "OrdenTrabajo"), ("trabajos", "FormaPago")]:
            filas = list(apps.get_model(app, modelo).objects.values_list("empresa_id", flat=True))
            self.assertEqual(filas, [1], modelo)
