from django.contrib.auth.models import Group, User
from django.test import TestCase
from django.urls import reverse

from apps.usuarios.roles import ADMINISTRADOR, MANAGER, ROLES, TECNICO, asignar_rol, rol_de


class RolesTests(TestCase):
    def test_los_tres_roles_existen(self):
        self.assertEqual(
            set(Group.objects.values_list("name", flat=True)) & set(ROLES.values()),
            {"Administrador", "Manager", "Técnico"},
        )

    def test_superusuario_sin_rol_pasa_a_administrador(self):
        admin = User.objects.create_superuser("jefe", "j@x.test", "clave-segura-123")
        self.assertEqual(rol_de(admin), ADMINISTRADOR)
        self.assertTrue(admin.groups.filter(name="Administrador").exists())

    def test_asignar_deja_un_solo_rol(self):
        u = User.objects.create_user("ana", password="clave-segura-123")
        asignar_rol(u, MANAGER)
        asignar_rol(u, TECNICO)
        self.assertEqual(list(u.groups.values_list("name", flat=True)), ["Técnico"])
        self.assertEqual(rol_de(u), TECNICO)


class RolEnLaAppTests(TestCase):
    def setUp(self):
        self.u = User.objects.create_user("ana", password="clave-segura-123")

    def test_cuenta_sin_rol_no_entra(self):
        self.client.force_login(self.u)
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.status_code, 403)
        self.assertContains(r, "aún no tiene un rol", status_code=403)
        self.assertEqual(self.client.get("/salud/").status_code, 200)

    def test_cada_rol_ve_su_rol(self):
        for clave in (MANAGER, TECNICO):
            asignar_rol(self.u, clave)
            self.client.force_login(self.u)
            r = self.client.get(reverse("dashboard"))
            self.assertEqual(r.status_code, 200)
            self.assertContains(r, f"<b>{ROLES[clave]}</b>", html=False)
            self.assertNotContains(r, 'name="rol"')  # sin selector

    def test_no_administrador_no_puede_cambiar_de_rol(self):
        asignar_rol(self.u, TECNICO)
        self.client.force_login(self.u)
        self.client.post(reverse("usuarios:cambiar_rol"), {"rol": ADMINISTRADOR, "siguiente": "/"})
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.context["rol"], TECNICO)

    def test_administrador_elige_entre_los_tres(self):
        asignar_rol(self.u, ADMINISTRADOR)
        self.client.force_login(self.u)
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.context["rol"], ADMINISTRADOR)
        self.assertEqual([c for c, _ in r.context["roles_elegibles"]], [ADMINISTRADOR, MANAGER, TECNICO])
        r = self.client.post(reverse("usuarios:cambiar_rol"), {"rol": TECNICO, "siguiente": "/facturas/"})
        self.assertRedirects(r, "/facturas/")
        r = self.client.get(reverse("dashboard"))
        self.assertEqual(r.context["rol"], TECNICO)
        self.assertEqual(r.context["rol_asignado"], ADMINISTRADOR)  # sigue pudiendo volver
        self.client.post(reverse("usuarios:cambiar_rol"), {"rol": "inventado", "siguiente": "/"})
        self.assertEqual(self.client.get(reverse("dashboard")).context["rol"], TECNICO)

    def test_cambiar_rol_no_redirige_fuera(self):
        asignar_rol(self.u, ADMINISTRADOR)
        self.client.force_login(self.u)
        r = self.client.post(reverse("usuarios:cambiar_rol"), {"rol": MANAGER, "siguiente": "https://malicioso.test/"})
        self.assertEqual(r.url, reverse("dashboard"))

    def test_admin_asigna_rol_al_crear_usuario(self):
        jefe = User.objects.create_superuser("jefe", "j@x.test", "clave-segura-123")
        self.client.force_login(jefe)
        r = self.client.post(reverse("admin:auth_user_add"), {
            "username": "tecnico1", "rol": TECNICO, "password1": "Clave-Segura-987", "password2": "Clave-Segura-987",
            "usable_password": "true",
        })
        self.assertEqual(r.status_code, 302, getattr(r, "context", None) and r.context["adminform"].form.errors)
        self.assertEqual(rol_de(User.objects.get(username="tecnico1")), TECNICO)
        r = self.client.get(reverse("admin:auth_user_changelist"))
        self.assertContains(r, "Técnico")
