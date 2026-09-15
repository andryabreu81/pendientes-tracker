# Guía de despliegue — Seguimiento de Pendientes

Documento para el equipo que instala el sistema en el entorno corporativo.

- **Stack:** Django 5.1 · PostgreSQL 16 · Gunicorn · Docker Compose
- **Contenedores:** 2 (`web`, `db`)
- **Requisito único:** Docker instalado. No hace falta Python, PostgreSQL ni Node en la máquina.

---

## 1. Requisitos previos

| Requisito | Versión mínima | Cómo verificar |
|---|---|---|
| Docker Engine | 24.0 | `docker --version` |
| Docker Compose | v2.20 | `docker compose version` |
| RAM libre | 2 GB | — |
| Disco libre | 3 GB | `df -h` |
| Puertos libres | 8000 y 55432 | ver abajo |

Verificar que los puertos estén libres:

```bash
# Linux / macOS
lsof -i :8000 -i :55432

# Windows (PowerShell)
netstat -ano | findstr "8000 55432"
```

Si alguno está ocupado, cambiarlo en el paso 3 (`APP_PORT` / `DB_PORT_HOST`).

### Instalar Docker

**Ubuntu / Debian**
```bash
curl -fsSL https://get.docker.com | sudo sh
sudo usermod -aG docker $USER
newgrp docker
```

**RHEL / CentOS / Rocky**
```bash
sudo dnf install -y dnf-plugins-core
sudo dnf config-manager --add-repo https://download.docker.com/linux/centos/docker-ce.repo
sudo dnf install -y docker-ce docker-ce-cli containerd.io docker-compose-plugin
sudo systemctl enable --now docker
sudo usermod -aG docker $USER
```

**Windows / macOS**: instalar Docker Desktop desde docker.com.

---

## 2. Copiar el proyecto al servidor

```bash
scp -r pendientes-tracker/ usuario@servidor:/opt/
```

o con git, si el equipo lo versiona:

```bash
cd /opt && git clone <url-del-repositorio> pendientes-tracker
```

---

## 3. Configurar el entorno

```bash
cd /opt/pendientes-tracker
cp .env.example .env
```

Generar una clave secreta:

```bash
docker run --rm python:3.12-slim python -c "import secrets; print(secrets.token_urlsafe(50))"
```

Editar `.env` con esa clave y las contraseñas definitivas:

```ini
SECRET_KEY=<pegar-la-clave-generada>
DEBUG=False

# La IP o el nombre del servidor. NO dejar * en producción.
ALLOWED_HOSTS=192.168.1.50,pendientes.empresa.local

# Necesario para que los formularios funcionen al entrar por IP.
# Incluir TODAS las direcciones por las que se accede.
CSRF_TRUSTED_ORIGINS=http://192.168.1.50:8000,http://pendientes.empresa.local:8000

DB_PASSWORD=<contraseña-fuerte-de-base-de-datos>

# Cuenta de administrador que se crea automáticamente al primer arranque.
ADMIN_USER=admin
ADMIN_PASSWORD=<contraseña-fuerte-de-administrador>
ADMIN_EMAIL=soporte@empresa.com

APP_PORT=8000
DB_PORT_HOST=55432
```

Restringir los permisos del archivo, que contiene credenciales:

```bash
chmod 600 .env
```

Averiguar la IP del servidor para completar `ALLOWED_HOSTS`:

```bash
hostname -I | awk '{print $1}'      # Linux
ipconfig getifaddr en0               # macOS
```

---

## 4. Levantar el sistema

```bash
docker compose up -d --build
```

La primera vez tarda 2-4 minutos: descarga las imágenes, instala dependencias,
crea la base, aplica las migraciones y genera el usuario administrador.

Seguir el arranque:

```bash
docker compose logs -f web
```

El arranque terminó correctamente cuando aparece:

```
[entrypoint] postgres listo.
Applying tracker.0001_initial... OK
Usuario 'admin' creado.
[INFO] Listening at: http://0.0.0.0:8000
```

---

## 5. Verificar la instalación

```bash
# Los dos contenedores en pie, db en healthy
docker compose ps

# La aplicación responde
curl -I http://localhost:8000/login/     # esperado: HTTP/1.1 200 OK

# La base acepta conexiones
docker compose exec db pg_isready -U pendientes
```

Desde otra estación, abrir en el navegador:

```
http://<ip-del-servidor>:8000
```

Si no carga, revisar el cortafuegos:

```bash
sudo ufw allow 8000/tcp                                    # Ubuntu
sudo firewall-cmd --permanent --add-port=8000/tcp && sudo firewall-cmd --reload   # RHEL
```

---

## 6. Administración: crear los usuarios del equipo

**Esto es obligatorio antes de poner el sistema en uso.** Cada persona necesita
su propia cuenta: el sistema guarda **qué usuario cargó cada archivo y qué usuario
modificó cada campo**. Si todos comparten la cuenta `admin`, esa trazabilidad se pierde.

### Entrar al panel de administración

```
http://<ip-del-servidor>:8000/admin/
```

Ingresar con `ADMIN_USER` / `ADMIN_PASSWORD` del `.env`.
También se llega desde el dashboard con el ícono de escudo, arriba a la derecha
(solo visible para cuentas administradoras).

### Crear un usuario

1. En **AUTENTICACIÓN Y AUTORIZACIÓN → Usuarios**, pulsar **Añadir usuario**.
2. Completar **Nombre de usuario** y **Contraseña** (dos veces). Guardar.
3. Se abre la pantalla de edición. Completar nombre, apellido y correo.
4. Marcar los permisos según el rol:

| Casilla | Qué habilita | A quién dársela |
|---|---|---|
| **Activo** | Puede iniciar sesión | Todos. Desmarcar para dar de baja sin borrar el historial |
| **Es staff** | Entra a `/admin/` | Solo a quien administre usuarios |
| **Es superusuario** | Todos los permisos | Solo al responsable del sistema |

**Para un usuario común del equipo: marcar únicamente "Activo".** Con eso entra
al dashboard, carga archivos, crea y edita registros. No necesita nada más.

5. Guardar.

### Crear usuarios desde la terminal

```bash
# Administrador (acceso al panel)
docker compose exec web python manage.py createsuperuser

# Usuario común, sin acceso al panel
docker compose exec web python manage.py shell -c "
from django.contrib.auth.models import User
User.objects.create_user('jperez', 'jperez@empresa.com', 'ClaveInicial2026')
print('usuario creado')
"
```

### Dar de baja a alguien

**No borrar el usuario**: eso dejaría su historial sin autor. En el panel,
abrir el usuario y **desmarcar "Activo"**. Pierde el acceso y su rastro queda intacto.

### Restablecer una contraseña olvidada

```bash
docker compose exec web python manage.py changepassword jperez
```

---

## 7. Auditoría: quién cargó qué

El sistema guarda tres rastros, todos consultables desde `/admin/`:

| Sección del panel | Qué muestra |
|---|---|
| **Import batches** | Cada archivo cargado: nombre, hash, fecha, **usuario** y cuántos registros creó o actualizó |
| **Ticket histories** | Cada campo modificado: valor anterior, valor nuevo, **usuario** y fecha |
| **Tickets** | Estado actual de cada registro |

*Import batches* y *Ticket histories* son de **solo lectura** en el panel: no se
pueden editar ni borrar desde la interfaz, porque son la evidencia de auditoría.

El dashboard también muestra la última carga con su autor, al pie de la tabla.

### Consultas directas a la base

```bash
docker compose exec db psql -U pendientes -d pendientes
```

```sql
-- Qué usuario cargó cada archivo
SELECT b.creado_en, b.archivo, u.username AS usuario,
       b.creados, b.actualizados, b.omitidos
FROM tracker_importbatch b
LEFT JOIN auth_user u ON u.id = b.usuario_id
ORDER BY b.creado_en DESC;

-- Todo lo que tocó una persona
SELECT h.creado_en, t.codigo, h.campo, h.valor_anterior, h.valor_nuevo
FROM tracker_tickethistory h
JOIN tracker_ticket t ON t.id = h.ticket_id
JOIN auth_user u ON u.id = h.usuario_id
WHERE u.username = 'jperez'
ORDER BY h.creado_en DESC;

-- Evolución del avance de un registro
SELECT h.creado_en::date AS fecha, h.valor_anterior, h.valor_nuevo
FROM tracker_tickethistory h
JOIN tracker_ticket t ON t.id = h.ticket_id
WHERE t.codigo = 'PRY-003' AND h.campo = 'avance'
ORDER BY h.creado_en;
```

---

## 8. Operación diaria

```bash
docker compose ps                 # estado
docker compose logs -f web        # logs en vivo
docker compose logs --tail=100 db # últimas líneas de la base
docker compose restart web        # reiniciar tras cambiar .env
docker compose stop               # detener (los datos quedan)
docker compose up -d              # volver a levantar
```

### Actualizar a una versión nueva del código

```bash
cd /opt/pendientes-tracker
docker compose down
git pull                          # o copiar los archivos nuevos
docker compose up -d --build      # las migraciones se aplican solas
docker compose logs -f web
```

---

## 9. Respaldos

El respaldo de la base es **responsabilidad del equipo de infraestructura**.

```bash
# Respaldo manual
docker compose exec -T db pg_dump -U pendientes pendientes > respaldo_$(date +%F).sql

# Restauración
cat respaldo_2026-08-28.sql | docker compose exec -T db psql -U pendientes -d pendientes
```

Respaldo diario automático con cron (3 de la mañana, conserva 30 días):

```bash
sudo crontab -e
```

```cron
0 3 * * * cd /opt/pendientes-tracker && docker compose exec -T db pg_dump -U pendientes pendientes > /var/backups/pendientes_$(date +\%F).sql 2>/dev/null; find /var/backups -name 'pendientes_*.sql' -mtime +30 -delete
```

Probar la restauración en un entorno de prueba antes de confiar en el respaldo.
Un respaldo que nunca se restauró no es un respaldo: es un archivo.

---

## 10. Solución de problemas

| Síntoma | Causa probable | Solución |
|---|---|---|
| `port is already allocated` | El 8000 está ocupado | Cambiar `APP_PORT` en `.env` y `docker compose up -d` |
| `DisallowedHost at /` | Falta la IP en `ALLOWED_HOSTS` | Agregarla en `.env`, luego `docker compose restart web` |
| `CSRF verification failed` | Falta el origen en `CSRF_TRUSTED_ORIGINS` | Agregar `http://<ip>:8000` en `.env` y reiniciar |
| El contenedor `web` reinicia en bucle | Falta `SECRET_KEY` o la base no arranca | `docker compose logs web` para ver el error real |
| `password authentication failed` | Se cambió `DB_PASSWORD` con la base ya creada | Ver la nota siguiente |
| Los estilos no cargan | Faltan los estáticos | `docker compose exec web python manage.py collectstatic --noinput` |
| No entra desde otra máquina | Cortafuegos | Abrir el puerto 8000/tcp |
| El archivo no importa nada | Formato distinto al esperado | Ver *Import batches* en `/admin/`: la columna **detalle** dice qué filas falló |

**Sobre `DB_PASSWORD`:** PostgreSQL fija la contraseña al crear el volumen de datos.
Cambiarla en `.env` después no la cambia en la base. Para cambiarla de verdad:

```bash
docker compose exec db psql -U pendientes -d pendientes \
  -c "ALTER USER pendientes WITH PASSWORD 'nueva-clave';"
# luego actualizar DB_PASSWORD en .env y reiniciar
docker compose restart web
```

**Reinicio total (BORRA TODOS LOS DATOS):**

```bash
docker compose down -v && docker compose up -d --build
```

---

## 11. Lista de verificación antes de entregar a los usuarios

- [ ] `SECRET_KEY` generada, no la de ejemplo
- [ ] `DEBUG=False`
- [ ] `ALLOWED_HOSTS` con la IP o el dominio real, sin `*`
- [ ] `CSRF_TRUSTED_ORIGINS` con todas las direcciones de acceso
- [ ] `DB_PASSWORD` y `ADMIN_PASSWORD` cambiadas
- [ ] `chmod 600 .env`
- [ ] Puerto 8000 abierto en el cortafuegos
- [ ] Un usuario creado por cada persona del equipo
- [ ] Archivo `pendientes.xlsx` de prueba cargado y verificado
- [ ] Respaldo automático configurado y **restauración probada**
- [ ] Documentada la IP de acceso para el equipo

---

## 12. Arquitectura

```
                    Estaciones de trabajo
              (navegador, nada que instalar)
                          |
                    http://ip:8000
                          |
          ┌───────────────▼───────────────┐
          │  Contenedor: web              │
          │  Django 5.1 + Gunicorn        │
          │  3 procesos, puerto 8000      │
          │  Archivos estáticos por       │
          │  WhiteNoise (sin nginx)       │
          └───────────────┬───────────────┘
                          │ red interna de Docker
          ┌───────────────▼───────────────┐
          │  Contenedor: db               │
          │  PostgreSQL 16                │
          │  Volumen: pgdata (persistente)│
          └───────────────────────────────┘
```

Los datos viven en el volumen `pendientes-tracker_pgdata`, fuera de los
contenedores: reconstruir la imagen o actualizar el código no los toca.
Solo `docker compose down -v` los elimina.

### Detección de cambios entre estaciones

No hay WebSocket ni servicios extra. Cada pantalla consulta cada 15 segundos
un endpoint (`/api/ultimo/`) que devuelve la marca de tiempo del registro más
reciente. Si es más nueva que la que tenía, muestra el aviso *"Otra estación
cargó datos"* con un botón para actualizar.

Viaja un solo dato por consulta, no la tabla completa: el costo sobre la base
es despreciable incluso con 20 estaciones conectadas.
