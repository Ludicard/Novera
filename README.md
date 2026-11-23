# Novera

Sistema web de gestión de **facturas por cobrar**. Fase 1: reemplaza la hoja «Facturas» del Excel
histórico por una aplicación donde se registran facturas, abonos y pagos, y donde el estado de
cada factura se calcula solo.

## Qué hace

- **Registrar facturas** con número SRI (`001-001-000000676`; basta escribir `676`), periodo, fecha de
  emisión, cliente, objeto, días de crédito → **fecha de cobro automática**, valor, % IVA → IVA y total
  automáticos. Botón «Guardar y registrar otra» para cargar varias seguidas.
- **Listado de facturas** con pestañas por estado (con conteos y montos), búsqueda en vivo (tecla `/`),
  filtros con etiquetas, columnas ordenables, vencimiento relativo, cobro rápido desde la fila y selección
  múltiple para marcar varias como cobradas o exportarlas.
- **Pagos y abonos parciales** por transferencia, depósito, cheque, efectivo o retención.
- **Estado calculado** (nunca a mano): Pendiente, Abono parcial, Vencida, Pagada, Anulada.
- **Panel de inicio** con filtros (periodo y cliente): facturado, cobrado, por cobrar, vencido, ticket y días
  promedio de cobro; gráficos de facturado vs. cobrado por mes, antigüedad de la cartera, facturas por estado
  y clientes con más facturación (Chart.js, servido localmente desde `static/vendor/`).
- **Clientes** con RUC/cédula (validación de 10 o 13 dígitos), días de crédito habituales y estado de cuenta.
- **Importar el «Reporte de Factura» de FactureroMovil** (y el Excel histórico) con vista previa y avisos
  fila por fila antes de guardar.
- **Exportar a Excel** cualquier listado filtrado.
- Panel de administración de Django en `/admin/` (incluye la acción «Fusionar clientes» para unificar
  un mismo cliente escrito de varias formas).

### Menú de inicio y roles

Tras iniciar sesión y elegir rol, la pantalla de inicio muestra un menú de mosaicos según el rol:

| Rol | Menú | No accede a |
|---|---|---|
| Administrador | Administrar proformas · Administrar órdenes de trabajo · Generar factura o recibo · Cargar pagos · Revisar datos financieros (panel) | — (además: clientes, usuarios) |
| Manager | Administrar clientes y técnicos (una sección con dos pestañas) · Administrar equipos · Administrar proformas · Administrar órdenes de trabajo · Revisar información general (resumen operativo) | Facturas, pagos, panel financiero, usuarios |
| Técnico | Mis órdenes de trabajo · Generar informe | Todo lo demás |

### Órdenes de trabajo (`apps/trabajos`)

- **Proforma** (`PF-00001`): cotización con líneas (mano de obra / material) e IVA, forma de pago, garantía
  (tiempo + condiciones) y condiciones generales. Borrador → enviada → aprobada o rechazada. **Al aprobarse genera la
  orden de trabajo** con el cliente, el trabajo y los materiales cotizados.
- **Proforma en PDF** (tamaño carta, «Página X de Y»): estructura tipo RIDE del SRI —emisor, cliente, detalle,
  totales, información adicional, condiciones y firmas—. En Ecuador la proforma no tiene formato oficial ni validez
  tributaria; el PDF lo indica al pie. Generado con WeasyPrint.
  - **Datos del emisor y logo:** se cargan en Novera → menú de la cuenta → **Configuración** (solo rol
    Administrador). Se guardan en la base de datos del servidor (un único registro) y el logo en
    `media/configuracion/` (volumen del servidor, sin URL pública: se entrega solo con sesión). El logo se valida
    (PNG/JPG reales, ≤ 2 MB), se re-codifica a PNG limpio y se reduce a 1200 px. Se registra quién hizo el último cambio.
  - Respaldo si aún no se configuró: variables `NOVERA_EMPRESA_*` del `.env` y `static/img/logo-empresa.png`.
- **Orden de trabajo** (`OT-00001`): cliente, **equipos** del cliente, técnicos asignados con sus instrucciones,
  lugar, horas estimadas, inicio y fin, materiales y herramientas. Estados: pendiente, en curso, terminada, cancelada.
- **Informe** del técnico: trabajo realizado, horas, materiales usados, observaciones; puede marcar la orden como
  terminada. Los técnicos trabajan solo por órdenes (no hay tareas sueltas).
- **Equipos** (`apps/clientes`): ascensores, montacargas… de cada cliente, con su historial de órdenes.
- **Facturas y recibos** pueden cobrar **varias órdenes de trabajo**; los recibos se numeran `REC-00001`.

Pendiente: notas de crédito.

## Stack

| Pieza | Tecnología |
|---|---|
| Aplicación | Python 3.13 · Django 5.2 |
| Base de datos | PostgreSQL 17 (SQLite en desarrollo) |
| Servidor | Gunicorn + WhiteNoise (estáticos) |
| Proxy / HTTPS | Nginx Proxy Manager existente, o Caddy 2 en un VPS limpio |
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
deploy/                 deploy.sh, compose.proxy.yml, Caddyfile, entrypoint y respaldos
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

**Si el VPS ya tiene Nginx Proxy Manager** en 80/443 (caso actual): en `.env` deja
`COMPOSE_FILE=docker-compose.yml:deploy/compose.proxy.yml` (no se levanta Caddy y `web` se une a la red
`proxy_network`). En NPM crea un *Proxy Host*: dominio → `http://novera-web:8000`, con SSL de Let's Encrypt
y «Force SSL». Si el VPS está limpio, usa `COMPOSE_PROFILES=caddy` en su lugar.

### Despliegue automático (push a `main`)

`.github/workflows/ci.yml`: si las pruebas pasan, el job `deploy` entra por SSH como el usuario `novera`
y el VPS ejecuta `/usr/local/bin/novera-deploy` → `git reset` a `origin/main` → `deploy/deploy.sh`
(reconstruye, espera a que `/salud/` responda y limpia imágenes viejas). La llave de GitHub está limitada
a ese comando (*forced command* en `authorized_keys`), no da una shell.

Secretos del entorno `produccion` en GitHub: `VPS_HOST`, `VPS_USER`, `VPS_SSH_KEY`, `VPS_KNOWN_HOSTS`.
Variable opcional `NOVERA_URL` (ej. `https://novera.midominio.com`) para comprobar la web pública al final.

A mano, en el VPS: `cd /opt/proyectos/Novera && ./deploy/deploy.sh`.

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

## Importar facturas de FactureroMovil

En FactureroMovil: **Reportes → Reporte de Factura** → rango de fechas → descargar en Excel. En Novera:
**Importar** → subir el `.xlsx` → revisar la vista previa → **Importar**. El formato se detecta solo.

| En FactureroMovil | En Novera |
|---|---|
| No Factura, Clave de acceso, Fecha de emision | Número, clave de acceso SRI, fecha de emisión |
| Bases imponibles (IVA, 0 %, 5 %, 8 %, no IVA), IVA, Valor total | Valor sin IVA (suma de bases), % IVA, IVA y total |
| NID Cliente + Cliente | Cliente reconocido por RUC/cédula (o por nombre) |
| Info. adicional: Dirección, Email, Teléfonos | Se completan en la ficha del cliente si estaban vacíos |
| Info. adicional: «Mes del Servicio» (con erratas) | Periodo (si falta, el mes de emisión); el resto va a «Objeto» |
| Plazo | Días de crédito (si es 0, los del cliente) → fecha de cobro |
| Estado «Autorizado SRI» / anulada / otro | Se importa / anulada / se omite |
| Cobrada «SI» · Por cobrar «SI» con saldo | Pagada · abono parcial |
| Cobrada «N/A» (no se usa ese módulo) | Lo eliges al importar: pendientes o pagadas |
| Factura que ya existe en Novera | No se duplica (puedes subir el reporte del año completo cada vez) |
| …y ahora FactureroMovil la marca «Cobrada» o con abono | Se registra solo el cobro que falte (fecha: el día de la reimportación) |
| …y ahora está anulada en FactureroMovil | Se anula en Novera si no tiene pagos; si los tiene, aviso para revisarla |

**Sin duplicados:** una factura se considera la misma si coincide su número en forma canónica
(`676` = `001-001-676` = `001-001-000000676`) o su clave de acceso. Se comprueba en la vista previa, otra vez
justo al confirmar (por si se importó lo mismo entretanto o se pulsó dos veces) y, como última barrera, la base
de datos no admite dos números ni dos claves de acceso iguales. El alta manual usa la misma comprobación.

## Importar el Excel histórico

El mismo botón acepta el `.xlsm` anterior (hoja «Facturas»).
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
