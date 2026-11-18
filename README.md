# Novera

Sistema web de gestión de **facturas por cobrar**. Fase 1: reemplaza la hoja «Facturas» del Excel
histórico por una aplicación donde se registran facturas, abonos y pagos, y donde el estado de
cada factura se calcula solo.

## Qué hace

- **Registrar facturas** con número SRI (`001-001-000000676`; basta escribir `676`), periodo, fecha de
  emisión, cliente, objeto, días de crédito → **fecha de cobro automática**, valor, % IVA → IVA y total
  automáticos. Botón «Guardar y registrar otra» para cargar varias seguidas.
- **Pagos y abonos parciales** por transferencia, depósito, cheque, efectivo o retención.
- **Estado calculado** (nunca a mano): Pendiente, Abono parcial, Vencida, Pagada, Anulada.
- **Panel de inicio**: total por cobrar, vencido, cobrado y facturado en el mes, facturas vencidas,
  las que vencen en 7 días y saldo por cliente.
- **Clientes** con RUC/cédula (validación de 10 o 13 dígitos), días de crédito habituales y estado de cuenta.
- **Importar el Excel histórico** con vista previa y avisos fila por fila antes de guardar.
- **Exportar a Excel** cualquier listado filtrado.
- Panel de administración de Django en `/admin/` (incluye la acción «Fusionar clientes» para unificar
  un mismo cliente escrito de varias formas).

## Stack

| Pieza | Tecnología |
|---|---|
| Aplicación | Python 3.13 · Django 5.2 |
| Base de datos | PostgreSQL 17 (SQLite en desarrollo) |
| Servidor | Gunicorn + WhiteNoise (estáticos) |
| Proxy / HTTPS | Caddy 2 (certificado Let's Encrypt automático) |
| Despliegue | Docker Compose |

## Estructura

```
config/                 Ajustes, URLs y WSGI del proyecto
apps/clientes/          Modelo Cliente, vistas y fusión de clientes en el admin
apps/facturas/
  models.py             Factura, Pago y el cálculo de saldo/estado (FacturaQuerySet.con_saldos)
  importador.py         Lectura y limpieza del Excel histórico
  exportar.py           Exportación a .xlsx
  management/commands/  `importar_excel` para importar desde la terminal
  tests/                Pruebas de modelos, importador y vistas
templates/  static/     Interfaz (HTML + CSS + un poco de JS, sin build)
deploy/                 Caddyfile, entrypoint y script de respaldos
```

## Desarrollo local

```bash
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
export DJANGO_DEBUG=1
.venv/bin/python manage.py migrate
.venv/bin/python manage.py createsuperuser
.venv/bin/python manage.py runserver
```

Abrir http://localhost:8000. Pruebas: `.venv/bin/python manage.py test`.

## Despliegue en el VPS

Requisitos: Docker con el plugin Compose y un dominio (o subdominio) cuyo registro **A** apunte a la IP
del VPS. Los puertos 80 y 443 deben estar abiertos.

```bash
git clone https://github.com/Ludicard/Novera.git
cd Novera
cp .env.example .env
nano .env        # DOMAIN, DJANGO_ALLOWED_HOSTS, DJANGO_CSRF_TRUSTED_ORIGINS, contraseñas
```

Generar la clave secreta:

```bash
python3 -c "import secrets; print(secrets.token_urlsafe(50))"
```

Levantar todo y crear el usuario administrador:

```bash
docker compose up -d --build
docker compose exec web python manage.py createsuperuser
```

Listo: `https://TU_DOMINIO`. Las migraciones se aplican solas cada vez que arranca el contenedor.

### Actualizar a una nueva versión

```bash
git pull
docker compose up -d --build
```

### Respaldos

```bash
./deploy/backup.sh                 # crea backups/novera-AAAAMMDD-HHMMSS.sql.gz (guarda los últimos 30)
```

Para hacerlo cada noche: `crontab -e` y añadir
`0 2 * * * cd /ruta/a/Novera && ./deploy/backup.sh >> backups/backup.log 2>&1`.

Restaurar: `gunzip -c backups/ARCHIVO.sql.gz | docker compose exec -T db psql -U novera novera`.

### Logs

```bash
docker compose logs -f web
```

## Importar el Excel histórico

Desde la web: **Importar Excel** → subir el `.xlsm` → revisar la vista previa → **Importar**.
O desde el servidor:

```bash
docker compose cp "facturas.xlsm" web:/tmp/base.xlsm
docker compose exec web python manage.py importar_excel /tmp/base.xlsm --avisos           # simulación
docker compose exec web python manage.py importar_excel /tmp/base.xlsm --aplicar          # guardar
```

Cómo interpreta el Excel:

| En el Excel | En Novera |
|---|---|
| Estado «Pagada» / «pagada» | Factura con un pago por el total (forma «Otro», ref. «Migración Excel») |
| Estado «No Pagada» | Pendiente o Vencida según la fecha de cobro |
| Estado «Anulada» | Anulada |
| Estado `#REF!` o vacío (la hoja Pagos fue borrada) | Lo eliges al importar: pendientes o pagadas |
| IVA vacío y total = valor × 1,12 | IVA 12 % (facturas de 2024) |
| Periodo «Enero», «julio - 2025» o fecha | Mes y año normalizados |
| Fecha de cobro en texto («lunes 23 de nov») | Emisión + 30 días; el texto original queda en notas |
| «Edificio Central» / «edf central» | Un solo cliente |
| RUC guardado como número (sin el 0 inicial) | RUC/cédula con el cero recuperado |
| Número de factura repetido | Se importa con sufijo `(dup 2)` para revisarlo |
| Factura que ya existe en Novera | Se salta (se puede reimportar sin duplicar) |
| Números reservados sin datos | Se omiten |

Los Excel nunca se suben al repositorio (`.gitignore`).

## Próximas fases

- Órdenes de trabajo, proformas y gastos por OT (las otras hojas del Excel).
- Recordatorios de cobro por correo.
- Usuarios con permisos diferenciados (solo lectura / registro).
