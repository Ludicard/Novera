import shutil
import tempfile
from io import BytesIO
from pathlib import Path

from django.contrib.auth.models import User
from django.core.files.uploadedfile import SimpleUploadedFile
from django.test import TestCase, override_settings
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


def datos(**extra):
    d = {"razon_social": "Ascensores Prueba S.A.", "nombre_comercial": "AscenPrueba", "ruc": "1790000000001",
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
        e = Empresa.actual()
        self.assertEqual((e.pk, e.ruc, e.actualizado_por), (1, "1790000000001", self.admin))
        self.assertEqual(datos_emisor()["razon_social"], "Ascensores Prueba S.A.")
        self.client.post(self.url, datos(razon_social="Otra S.A."))
        self.assertEqual(Empresa.objects.count(), 1)  # siempre un único registro

    def test_ruc_invalido(self):
        for malo in ["123", "17900000000AA", "9990000000001"]:
            r = self.client.post(self.url, datos(ruc=malo))
            self.assertIn("ruc", r.context["form"].errors, malo)
        self.assertIsNone(Empresa.actual())

    def test_logo_se_limpia_y_reduce(self):
        logo = SimpleUploadedFile("mi logo.jpg", png(2400, 800, "JPEG"), content_type="image/jpeg")
        self.client.post(self.url, {**datos(), "logo": logo})
        e = Empresa.actual()
        with Image.open(e.logo.path) as im:
            self.assertEqual((im.format, im.width), ("PNG", 1200))
        self.assertTrue(e.logo.path.startswith(str(MEDIA)))
        r = self.client.get(reverse("configuracion:logo"))
        self.assertEqual((r.status_code, r["Content-Type"]), (200, "image/png"))
        # Reemplazar el logo borra el anterior
        anterior = e.logo.path
        self.client.post(self.url, {**datos(), "logo": SimpleUploadedFile("otro.png", png(), content_type="image/png")})
        self.assertFalse(Path(anterior).exists() and anterior != Empresa.actual().logo.path)

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
        self.assertFalse(Empresa.actual().logo)

    def test_solo_el_administrador(self):
        for rol in (MANAGER, TECNICO):
            u = User.objects.create_user(f"u-{rol}", password=CLAVE)
            entrar_como(self.client, u, rol)
            r = self.client.get(self.url)
            self.assertEqual((r.status_code, r.url), (302, reverse("inicio")), rol)
            self.client.post(self.url, datos(razon_social="Hackeado"))
        self.assertIsNone(Empresa.actual())

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
