import shutil
import tempfile
from io import BytesIO
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import override_settings

from apps.usuarios.tests.utils import TestCase
from django.urls import reverse
from PIL import Image

from apps.configuracion.models import Empresa, datos_emisor
from apps.usuarios.roles import ADMINISTRADOR, MANAGER, TECNICO
from apps.usuarios.tests.utils import entrar_como

CLAVE = "clave-segura-123"
MEDIA = Path(tempfile.mkdtemp())


def png(ancho=800, alto=300, formato="PNG"):
    salida = BytesIO()
    Image.new("RGB", (ancho, alto), (31, 78, 95)).save(salida, format=formato)
    return salida.getvalue()


def guardada():
    """La empresa de la prueba tal como quedó en la base de datos."""
    return Empresa.objects.get(pk=Empresa.actual().pk)


def datos(**extra):
    d = {"nombre": "AscenPrueba", "razon_social": "Ascensores Prueba S.A.", "nombre_comercial": "AscenPrueba", "ruc": "1790000000001",
         "direccion_matriz": "Av. Ejemplo N1-23, Quito", "telefono": "02 000 0000", "email": "ventas@ejemplo.test",
         "web": ""}
    d.update(extra)
    return d


@override_settings(MEDIA_ROOT=MEDIA)
class ConfiguracionTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        shutil.rmtree(MEDIA, ignore_errors=True)
        super().tearDownClass()

    def setUp(self):
        self.admin = User.objects.create_user("jefa", password=CLAVE, first_name="Jefa")
        entrar_como(self.client, self.admin, ADMINISTRADOR)
        self.url = reverse("configuracion:empresa")

    def test_guardar_y_usar_en_el_pdf(self):
        r = self.client.post(self.url, datos())
        self.assertRedirects(r, self.url)
        e = guardada()
        self.assertEqual((e.pk, e.nombre, e.ruc, e.actualizado_por), (self.empresa.pk, "AscenPrueba", "1790000000001", self.admin))
        self.assertEqual(datos_emisor(e)["razon_social"], "Ascensores Prueba S.A.")
        self.client.post(self.url, datos(razon_social="Otra S.A."))
        self.assertEqual(Empresa.objects.count(), 1)  # edita la empresa de la cuenta, no crea otra
        self.assertContains(self.client.get(reverse("inicio")), '<span class="marca-empresa">AscenPrueba</span>')

    def test_nombre_obligatorio_y_por_defecto_empresa(self):
        r = self.client.post(self.url, datos(nombre="  "))
        self.assertIn("nombre", r.context["form"].errors)
        Empresa.objects.filter(pk=self.empresa.pk).update(nombre="")
        self.assertContains(self.client.get(reverse("inicio")), '<span class="marca-empresa">Empresa</span>')

    def test_solo_datos_basicos_sin_ruc(self):
        r = self.client.post(self.url, {"nombre": "EmpresaAutos"})
        self.assertRedirects(r, self.url)
        self.assertEqual(guardada().nombre, "EmpresaAutos")
        self.assertEqual(datos_emisor(guardada())["razon_social"], "EmpresaAutos")

    def test_ruc_invalido(self):
        for malo in ["123", "17900000000AA", "9990000000001"]:
            r = self.client.post(self.url, datos(ruc=malo))
            self.assertIn("ruc", r.context["form"].errors, malo)
        self.assertEqual(guardada().ruc, "")

    def test_logo_se_limpia_y_reduce(self):
        logo = SimpleUploadedFile("mi logo.jpg", png(2400, 800, "JPEG"), content_type="image/jpeg")
        self.client.post(self.url, {**datos(), "logo": logo})
        e = guardada()
        with Image.open(e.logo.path) as im:
            self.assertEqual((im.format, im.width), ("PNG", 1200))
        self.assertTrue(e.logo.path.startswith(str(MEDIA)))
        r = self.client.get(reverse("configuracion:logo"))
        self.assertEqual((r.status_code, r["Content-Type"]), (200, "image/png"))
        self.assertContains(self.client.get(reverse("inicio")), 'class="marca-logo"')
        # Un técnico de la empresa también lo ve (sale en la barra superior)
        tec = User.objects.create_user("tec-logo", password=CLAVE)
        entrar_como(self.client, tec, TECNICO)
        self.assertEqual(self.client.get(reverse("configuracion:logo")).status_code, 200)
        entrar_como(self.client, self.admin, ADMINISTRADOR)
        # Reemplazar el logo borra el anterior
        anterior = e.logo.path
        self.client.post(self.url, {**datos(), "logo": SimpleUploadedFile("otro.png", png(), content_type="image/png")})
        self.assertFalse(Path(anterior).exists() and anterior != guardada().logo.path)

    def test_archivo_que_no_es_imagen(self):
        falso = SimpleUploadedFile("logo.png", b"<?php echo 'hola'; ?>", content_type="image/png")
        r = self.client.post(self.url, {**datos(), "logo": falso})
        self.assertIn("logo", r.context["form"].errors)
        grande = SimpleUploadedFile("logo.png", b"0" * (2 * 1024 * 1024 + 1), content_type="image/png")
        r = self.client.post(self.url, {**datos(), "logo": grande})
        self.assertIn("logo", r.context["form"].errors)

    def test_quitar_logo(self):
        self.client.post(self.url, {**datos(), "logo": SimpleUploadedFile("l.png", png(), content_type="image/png")})
        self.client.post(self.url, {**datos(), "quitar_logo": "on"})
        self.assertFalse(guardada().logo)

    def test_solo_el_administrador(self):
        for rol in (MANAGER, TECNICO):
            u = User.objects.create_user(f"u-{rol}", password=CLAVE)
            entrar_como(self.client, u, rol)
            r = self.client.get(self.url)
            self.assertEqual((r.status_code, r.url), (302, reverse("inicio")), rol)
            self.client.post(self.url, datos(razon_social="Hackeado"))
        self.assertEqual(guardada().razon_social, "")

    def test_logo_no_es_publico(self):
        self.client.post(self.url, {**datos(), "logo": SimpleUploadedFile("l.png", png(), content_type="image/png")})
        self.client.logout()
        r = self.client.get(reverse("configuracion:logo"))
        self.assertEqual(r.status_code, 302)  # al login

    def test_opcion_en_el_menu_solo_para_administrador(self):
        self.assertContains(self.client.get(reverse("inicio")), self.url)
        u = User.objects.create_user("mana", password=CLAVE)
        entrar_como(self.client, u, MANAGER)
        self.assertNotContains(self.client.get(reverse("inicio")), self.url)


@override_settings(MEDIA_ROOT=MEDIA)
class ColoresTests(TestCase):
    def setUp(self):
        self.admin = User.objects.create_user("jefa", password=CLAVE)
        entrar_como(self.client, self.admin, ADMINISTRADOR)
        self.url = reverse("configuracion:empresa")

    def test_por_defecto_azul(self):
        from apps.configuracion.models import tema_aplicacion, tema_proforma

        self.assertEqual((tema_aplicacion()["base"], tema_proforma()["base"]), ("#1F4E5F", "#1F4E5F"))
        self.assertNotContains(self.client.get(reverse("inicio")), "--primario:")  # usa el CSS por defecto

    def test_guardar_colores_normaliza_y_aplica(self):
        self.client.post(self.url, datos(color_app="2e7d32", color_proforma="#d9a21b"))
        e = guardada()
        self.assertEqual((e.color_app, e.color_proforma), ("#2E7D32", "#D9A21B"))
        r = self.client.get(reverse("inicio"))
        self.assertContains(r, "--primario: #2E7D32")
        # Mostaza es claro: el texto encima va oscuro y el tono para títulos se oscurece
        from apps.configuracion.models import tema_proforma

        t = tema_proforma(e)
        self.assertEqual(t["sobre"], "#1D2733")
        from apps.configuracion.colores import contraste
        self.assertGreaterEqual(contraste(t["legible"], "#FFFFFF"), 4.5)

    def test_codigo_invalido(self):
        for malo in ["azul", "#12345", "#GGGGGG", "url(x)"]:
            r = self.client.post(self.url, datos(color_app=malo))
            self.assertIn("color_app", r.context["form"].errors, malo)

    def test_vacio_vuelve_al_azul(self):
        self.client.post(self.url, datos(color_app="#2E7D32"))
        self.client.post(self.url, datos(color_app=""))
        self.assertNotContains(self.client.get(reverse("inicio")), "--primario:")

    def test_pdf_usa_el_color_de_la_proforma(self):
        from django.template.loader import render_to_string

        from apps.clientes.models import Cliente
        from apps.configuracion.models import tema_proforma
        from apps.trabajos.models import Proforma

        self.client.post(self.url, datos(color_proforma="#D9A21B"))
        p = Proforma.objects.create(cliente=Cliente.objects.create(nombre="X"), estado="AUTORIZADA")
        e = guardada()
        html = render_to_string("trabajos/proforma_pdf.html", {"p": p, "lineas": [], "empresa": datos_emisor(e), "tema": tema_proforma(e)})
        self.assertIn("background: #D9A21B", html)
