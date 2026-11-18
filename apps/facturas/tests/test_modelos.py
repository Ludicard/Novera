from datetime import date, timedelta
from decimal import Decimal

from django.test import TestCase

from apps.clientes.models import Cliente
from apps.facturas.models import Estado, Factura, Pago

HOY = date(2026, 11, 18)


def crear_factura(numero="001-001-000000001", total="115.00", emision=HOY, dias=30, **extra):
    cliente = extra.pop("cliente", None) or Cliente.objects.get_or_create(nombre="Edificio Central")[0]
    subtotal = Decimal(total) / Decimal("1.15")
    return Factura.objects.create(
        numero=numero, cliente=cliente, periodo=emision, fecha_emision=emision, dias_credito=dias,
        subtotal=subtotal.quantize(Decimal("0.01")), porcentaje_iva=15, iva=Decimal(total) - subtotal.quantize(Decimal("0.01")),
        total=Decimal(total), **extra,
    )


def estado(factura, hoy=HOY):
    return Factura.objects.con_saldos(hoy).get(pk=factura.pk).estado


class EstadoFacturaTests(TestCase):
    def test_pendiente_si_no_vence(self):
        self.assertEqual(estado(crear_factura()), Estado.PENDIENTE)

    def test_vencida_si_paso_fecha_cobro(self):
        f = crear_factura(emision=HOY - timedelta(days=40))
        self.assertEqual(estado(f), Estado.VENCIDA)

    def test_parcial_con_abono(self):
        f = crear_factura()
        Pago.objects.create(factura=f, monto=Decimal("50"))
        anotada = Factura.objects.con_saldos(HOY).get(pk=f.pk)
        self.assertEqual(anotada.estado, Estado.PARCIAL)
        self.assertEqual(anotada.saldo, Decimal("65.00"))

    def test_vencida_aunque_tenga_abono(self):
        f = crear_factura(emision=HOY - timedelta(days=40))
        Pago.objects.create(factura=f, monto=Decimal("50"))
        self.assertEqual(estado(f), Estado.VENCIDA)

    def test_pagada_con_varios_pagos(self):
        f = crear_factura()
        Pago.objects.create(factura=f, monto=Decimal("100"))
        Pago.objects.create(factura=f, monto=Decimal("15"), forma=Pago.Forma.RETENCION)
        self.assertEqual(estado(f), Estado.PAGADA)

    def test_anulada(self):
        self.assertEqual(estado(crear_factura(anulada=True)), Estado.ANULADA)

    def test_fecha_cobro_por_defecto_y_periodo_dia_1(self):
        f = crear_factura(emision=date(2026, 11, 6), dias=15)
        self.assertEqual(f.fecha_cobro, date(2026, 11, 21))
        self.assertEqual(f.periodo, date(2026, 11, 1))

    def test_calcular_montos(self):
        f = Factura(subtotal=Decimal("180"), porcentaje_iva=Decimal("15"))
        f.calcular_montos()
        self.assertEqual((f.iva, f.total), (Decimal("27.00"), Decimal("207.00")))

    def test_saldo_por_cliente(self):
        f = crear_factura()
        crear_factura(numero="001-001-000000002", total="50.00", anulada=True)
        Pago.objects.create(factura=f, monto=Decimal("15"))
        cliente = Cliente.objects.con_saldos().get(pk=f.cliente_id)
        self.assertEqual((cliente.facturado, cliente.cobrado, cliente.saldo), (Decimal("115"), Decimal("15"), Decimal("100")))
