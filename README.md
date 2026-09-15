# Seguimiento de Pendientes

Sistema de seguimiento y control de **proyectos, requerimientos e incidencias**.
Carga el archivo semanal de pendientes (`.xlsx` o `.docx`), guarda el histórico
de cada cambio y genera el dashboard automáticamente.

Stack: **Django 5.1 + PostgreSQL 16 + Docker**.

> **Para instalar en el servidor corporativo, seguir [DESPLIEGUE.md](DESPLIEGUE.md)**
> — incluye requisitos, configuración, creación de usuarios y solución de problemas.

---

## Puesta en marcha

Requisito único: Docker Desktop (o Docker Engine + Compose).

```bash
cd pendientes-tracker
./instalar.sh
```

El script verifica los requisitos, genera el archivo `.env` con claves
aleatorias, detecta la IP del servidor y levanta el sistema. Al terminar
muestra la dirección de acceso y la credencial inicial.

Se puede volver a ejecutar sin romper nada: si el `.env` ya existe, lo conserva.

**A mano**, si se prefiere:

```bash
cp .env.example .env      # completar los valores marcados como CAMBIAR
docker compose up -d --build
```

Listo. Abrir **http://localhost:8000**

Usuario inicial: el que definan `ADMIN_USER` / `ADMIN_PASSWORD` en `.env`
(definidos en `.env`). Se crea solo al primer arranque.

### Acceso desde otras estaciones de trabajo

El sistema corre en una máquina y las demás entran por la red:

```bash
ipconfig getifaddr en0        # macOS
hostname -I                   # Linux
```

Las otras estaciones abren `http://<esa-ip>:8000`.
Si el navegador rechaza el formulario, agregar la IP en `.env`:

```
CSRF_TRUSTED_ORIGINS=http://192.168.1.50:8000
```

y reiniciar con `docker compose restart web`.

---

## Uso

### 1. Cargar el archivo semanal

Botón **Cargar archivo** → seleccionar el `.xlsx`.

Los registros se identifican por **nombre + tipo**:

| Situación | Qué hace |
|---|---|
| El registro no existe | Lo crea con código automático (`PRY-001`, `REQ-001`, `INC-001`) |
| Ya existe y cambió algo | Actualiza y anota cada campo en el historial |
| Ya existe y es idéntico | No hace nada, no ensucia el historial |
| El archivo trae un campo vacío | **No pisa** el dato cargado a mano en la app |

**Nada se borra nunca.** Volver a cargar el mismo archivo es seguro.

### 2. Alta y edición manual

Botón **+ Nuevo registro** para dar de alta.
**Ver detalle → Editar** para modificar. Cada campo que cambia queda
registrado con el usuario y la fecha.

### 3. Dashboard

Se genera solo a partir de los datos cargados:

- Total de registros, avance general, sin asignar, datos incompletos
- Distribución por tipo (proyecto / requerimiento / incidencia)
- Distribución por estatus
- Carga de trabajo por responsable, con avance promedio

Cuando un registro trae varios responsables (`HA - MLM - Banco`), se cuenta
para cada uno: la carga es compartida.

### 5. Exportar a Excel

Botón **Exportar**, arriba a la derecha. Dos opciones:

| Opción | Qué baja |
|---|---|
| **Registros** | Proyectos, requerimientos e incidencias, con los filtros aplicados. Una hoja por tipo. |
| **Tareas** | Todas las tareas, cada una con el código de su registro padre. |

Desde el detalle de un registro también se exportan **solo sus tareas**.

El archivo lleva el **código en la primera columna**. Eso permite el
round-trip: se descarga, se actualiza en Excel y se vuelve a subir con el
mismo botón **Cargar archivo**.

| En el archivo reimportado | Qué hace el sistema |
|---|---|
| Fila con código existente | Actualiza y anota cada cambio en el historial |
| Fila sin código | Crea un registro o tarea nueva |
| Fila sin cambios | No hace nada |

El archivo de registros se exporta con **una hoja por tipo**, y al
reimportarlo se leen **todas**. Las columnas *Score de riesgo* y *Nivel de
riesgo* se ignoran al subir: son calculadas y se recalculan solas.

El sistema **reconoce solo** si le subieron el archivo semanal de pendientes
o el de tareas: no hay que elegir el tipo.

### 6. Tareas

Las tareas se cargan sobre registros que ya existen. En **Ver detalle** de
cualquier registro está la sección **Tareas** con los botones *Nueva tarea*
y *Exportar*.

Cada tarea tiene descripción, responsable, estado, avance, prioridad, fecha
de inicio, fecha límite y observación. El código es correlativo dentro del
padre: `PRY-003.T01`, `PRY-003.T02`.

**El avance del registro padre no cambia**: sigue siendo el del archivo
semanal. Al lado se muestra el avance calculado según sus tareas, como
referencia. Si el registro declara 90% pero sus tareas van al 20%, esa
diferencia se ve de inmediato.

En la tabla principal, la columna **Tareas** muestra `listas/total`: en
verde si están todas, en rojo si alguna está vencida.

### 7. Filtro por responsable

El desplegable **Todos los responsables** filtra por persona. Alcanza con
que figure en el registro **o** en alguna de sus tareas: quien filtra
quiere ver todo lo que la involucra.

Se combina con los demás filtros, y la exportación respeta lo filtrado.

### 8. Detección de datos nuevos

Cada 15 segundos la pantalla consulta el registro más reciente de la base.
Si otra estación cargó algo, aparece el aviso **"Hay datos nuevos"** con un
botón para actualizar. Solo viaja esa marca de tiempo, no la tabla entera.

### 9. Fecha final y riesgo

Cada proyecto, requerimiento e incidencia tiene una **fecha final**
comprometida. De ella sale el atraso, que es la señal de mayor peso del
**score de riesgo**.

El riesgo se calcula solo, en una escala de 0 a 1000:

| Nivel | Rango | Significado |
|---|---|---|
| `low` | 0 – 499 | Sin señales relevantes |
| `medium` | 500 – 799 | Atención |
| `high` | 800 – 949 | Requiere seguimiento |
| `veryhigh` | 950 – 999 | Crítico en la práctica |
| `critical` | 1000 | Atraso grave con avance bajo |

Suman: días de atraso contra la fecha final, avance por detrás del tiempo
transcurrido, tareas vencidas, tareas bloqueadas, falta de responsable y
falta de fecha final. Todos los pesos están en un solo archivo,
`tracker/riesgo.py`: ajustar la escala es cambiar un número ahí.

`critical` **no se alcanza sumando**: se reserva para una condición dura
(más de 30 días de atraso con menos de 50% de avance), para que el nivel
signifique algo concreto y no "acumuló mucho".

**El riesgo no se guarda en la base**: depende del día, así que se calcula
al momento y nunca queda desactualizado.

El desplegable **Todos los riesgos** filtra por nivel, y la exportación
respeta el filtro. Las dos columnas van también en el Excel exportado.

### 10. Recordatorios y reuniones

Desde **Ver detalle** de cualquier registro, o desde la fila de una tarea:

- **Recordatorio**: un aviso con fecha. Desde ese día aparece en el panel
  **Requieren seguimiento**, arriba del tablero, hasta que alguien lo marca
  como atendido. Los vencidos se muestran en rojo.
- **Reunión**: título, fecha y hora, duración, lugar, enlace y participantes.
  Se descarga como archivo **`.ics`**, que se abre en Outlook, Google
  Calendar o Calendar y agenda la cita.

Los avisos se muestran a **todo el equipo por igual**. El sistema todavía no
puede dirigirlos a una persona concreta: los responsables se cargan como
texto libre (`HA - MLM - Banco`) y no están vinculados a cuentas de usuario.

El `.ics` describe la cita; **no envía invitaciones** ni escribe en el
calendario de nadie.

### 11. Editar el código de un registro

El código se genera solo al dar de alta, pero se puede cambiar desde
**Ver detalle → Editar**.

Debe respetar el formato `PRY-000`, `REQ-000` o `INC-000`, con el prefijo
correspondiente al tipo. Se admite escribirlo en minúsculas: se normaliza.

Al cambiarlo:

- las **tareas se renombran en cascada** (`PRY-003.T01` → `PRY-007.T01`),
- el cambio queda en el **historial**, con autor y fecha,
- **los Excel exportados antes del cambio dejan de coincidir**: hay que
  volver a exportar antes de reimportar, o esas filas se cargarían como
  registros nuevos.

### 12. API de consulta

`GET /api/registros/` devuelve en JSON los registros con los mismos filtros
que la pantalla, incluyendo `risk_score` y `risk_level`. Requiere sesión
iniciada.

---

## Formato del archivo de entrada

Verificado contra `pendientes.xlsx` del 28-08-2026.

Una sola hoja con tres bloques, cada uno precedido por su fila de título:

```
PROYECTOS EN EJECUCIÓN            <- fila de título (combinada A:I)
Nombre del Proyecto | Numero (Id Único) | Fecha de Solicitada | ...
Master Debit        |                   |                     | ...
...
REQUERIMIENTOS EN PROCESO
...
INCIDENCIAS EN PROCESO
...
```

Las 9 columnas se ubican **por nombre de encabezado**, no por posición: si
alguien reordena las columnas en el Excel, el importador las sigue encontrando.

### Particularidades del archivo que el importador resuelve

1. **Registros partidos en dos filas.** En el archivo original, la fila 4 dice
   `Master Debit (Autogestión Banca` y la fila 5 dice `en línea)`. Una fila con
   texto únicamente en la columna Nombre se toma como continuación de la anterior.

2. **El avance viene como fracción.** Excel guarda `95%` como `0.95`; el símbolo
   de porcentaje es solo formato de pantalla. Se convierte a entero 0-100. También
   acepta `"95%"` en texto, por si el archivo se armó copiando del Word.

3. **Estatus con basura pegada.** El archivo trae `"Calidad "` con espacio sobrante
   y `"Desarrollo 27/8/2026"` con la fecha adherida. Se limpian; sin esto el
   dashboard mostraría seis estatus donde en realidad hay cuatro.

Las columnas *Numero (Id Único)*, *Fecha de Solicitada* y *Funcional Solicitante*
vienen vacías en el archivo. El sistema genera el código y marca los otros dos
con el punto ámbar de **"Pendiente de completar"**, para que se carguen a mano.

También se aceptan archivos `.docx` con tres tablas (el formato anterior).

---

## Base de datos

Tres tablas, sin nada de más.

**`tracker_ticket`** — estado actual de cada registro.

| Campo | Tipo | Notas |
|---|---|---|
| `codigo` | varchar(20) único | `PRY-001` / `REQ-001` / `INC-001` |
| `categoria` | varchar(20) | proyecto / requerimiento / incidencia |
| `nombre` | varchar(500) | |
| `fecha_solicitada` | date, nulo | |
| `funcional_solicitante` | varchar(255) | |
| `descripcion` | text | |
| `avance` | smallint | 0-100, con CHECK a nivel de motor |
| `asignado` | varchar(255) | |
| `observacion` | text | |
| `estatus` | varchar(50) | |
| `actualizado_en` | timestamp | dispara el aviso de datos nuevos |

**`tracker_tickethistory`** — auditoría por campo. Una fila por cada campo que
cambió: valor anterior, valor nuevo, quién y cuándo. Es lo que permite ver la
evolución del avance semana a semana. Es **append-only**: el admin de Django
tiene deshabilitado editar y borrar.

**`tracker_importbatch`** — registro de cada archivo cargado: hash SHA-256,
cuántos se crearon, actualizaron y omitieron.

### Consultar la base directamente

Postgres queda expuesto en el puerto **55432** del anfitrión:

```bash
psql -h localhost -p 55432 -U pendientes -d pendientes
```

```sql
-- Evolución del avance de un registro
SELECT h.creado_en::date, h.valor_anterior, h.valor_nuevo
FROM tracker_tickethistory h
JOIN tracker_ticket t ON t.id = h.ticket_id
WHERE t.codigo = 'PRY-003' AND h.campo = 'avance'
ORDER BY h.creado_en;
```

---

## Panel de administración y usuarios

**http://localhost:8000/admin/** — o el ícono de escudo del dashboard, arriba a
la derecha (visible solo para cuentas administradoras).

Cada persona del equipo necesita **su propia cuenta**: el sistema registra qué
usuario cargó cada archivo y qué usuario modificó cada campo. Con una cuenta
compartida esa trazabilidad se pierde.

Crear un usuario común desde el panel: **Usuarios → Añadir usuario**, definir
nombre y contraseña, y marcar únicamente **"Activo"**. Con eso entra al
dashboard, carga archivos y edita registros.

Desde la terminal:

```bash
# Administrador (con acceso al panel)
docker compose exec web python manage.py createsuperuser

# Cambiar una contraseña olvidada
docker compose exec web python manage.py changepassword jperez
```

Para dar de baja a alguien, **desmarcar "Activo"** en lugar de borrar el
usuario: borrarlo dejaría su historial sin autor.

El paso 6 de [DESPLIEGUE.md](DESPLIEGUE.md) tiene el detalle completo,
incluidas las consultas SQL de auditoría.

---

## Estructura

```
pendientes-tracker/
├── compose.yaml              # web (Django+gunicorn) + db (PostgreSQL)
├── Dockerfile
├── entrypoint.sh             # espera a Postgres, migra, crea admin
├── .env / .env.example
├── requirements.txt
└── app/
    ├── manage.py
    ├── core/                 # settings, urls, wsgi
    └── tracker/
        ├── models.py         # Ticket, TicketHistory, ImportBatch
        ├── importer.py       # lectura de xlsx/docx y auditoría
        ├── views.py          # dashboard, detalle, alta, edición
        ├── forms.py
        ├── admin.py
        └── templates/tracker/
```

---

## Operación

```bash
docker compose logs -f web        # ver logs
docker compose restart web        # reiniciar tras cambiar .env
docker compose down               # detener (los datos quedan)
docker compose down -v            # detener y BORRAR la base
```

Respaldo y restauración:

```bash
docker compose exec db pg_dump -U pendientes pendientes > respaldo.sql
cat respaldo.sql | docker compose exec -T db psql -U pendientes -d pendientes
```

---

## Antes de producción

1. Cambiar `SECRET_KEY` en `.env` por 50 caracteres aleatorios:
   `python -c "import secrets; print(secrets.token_urlsafe(50))"`
2. Cambiar `DB_PASSWORD` y `ADMIN_PASSWORD`.
3. Dejar `DEBUG=False`.
4. Reemplazar `ALLOWED_HOSTS=*` por la IP o el dominio real.
5. Programar el respaldo de la base.
