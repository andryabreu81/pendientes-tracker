"""
Importador del archivo semanal de pendientes.

FORMATO REAL (verificado sobre pendientes.xlsx del 28-08-2026):

  UNA sola hoja con TRES bloques, cada uno precedido por una fila-titulo
  combinada (merged A:I):

      fila  1  "PROYECTOS EN EJECUCIÓN"      -> categoria proyecto
      fila  2  encabezados (9 columnas)
      filas 3-9   datos
      fila 12  "REQUERIMIENTOS EN PROCESO"   -> categoria requerimiento
      fila 13  encabezados
      filas 14-17 datos
      fila 20  "INCIDENCIAS EN PROCESO"      -> categoria incidencia
      fila 21  encabezados
      filas 22-28 datos

  Las columnas se ubican POR NOMBRE de encabezado y no por posicion,
  para tolerar que alguien reordene columnas en el Excel.

TRES TRAMPAS DEL ARCHIVO QUE SE RESUELVEN ACA:

  1. Filas de continuacion. La fila 4 dice "Master Debit (Autogestión Banca"
     y la fila 5 dice "en línea)": es UN solo ticket partido en dos.
     Una fila con texto SOLO en la columna Nombre se pega a la anterior.

  2. El avance viene como fraccion (0.95), no como texto "95%". Excel
     guarda los porcentajes asi; el simbolo % es solo formato de pantalla.

  3. Estatus sucio: "Calidad " con espacio sobrante y "Desarrollo 27/8/2026"
     con la fecha pegada. Sin normalizar, el dashboard arma 6 barras
     donde en realidad hay 4 estatus.
"""

import hashlib
import re
import unicodedata
from datetime import date, datetime

from django.db import transaction

from .models import ImportBatch, Tarea, Ticket, TicketHistory

# Titulo de bloque (normalizado) -> categoria.
BLOQUES = {
    "proyectos en ejecucion": Ticket.PROYECTO,
    "requerimientos en proceso": Ticket.REQUERIMIENTO,
    "incidencias en proceso": Ticket.INCIDENCIA,
}

# Nombre de hoja (normalizado) -> categoria. Es como el propio sistema
# nombra las hojas al exportar, y permite reimportar ese archivo sin que
# dependa de la fila-titulo.
HOJAS = {
    "proyectos": Ticket.PROYECTO,
    "requerimientos": Ticket.REQUERIMIENTO,
    "incidencias": Ticket.INCIDENCIA,
}

# Valor de la columna "Tipo" (normalizado) -> categoria.
CATEGORIAS_TEXTO = {
    "proyecto": Ticket.PROYECTO,
    "proyectos": Ticket.PROYECTO,
    "requerimiento": Ticket.REQUERIMIENTO,
    "requerimientos": Ticket.REQUERIMIENTO,
    "incidencia": Ticket.INCIDENCIA,
    "incidencias": Ticket.INCIDENCIA,
}


def _categoria_de_titulo(texto):
    """
    Categoria a partir de la fila-titulo de un bloque.

    Acepta tanto el rotulo del archivo semanal ("PROYECTOS EN EJECUCIÓN")
    como el que escribe el exportador ("PROYECTOS · 3 registros"), que
    lleva el conteo pegado y por eso no coincidia exacto con BLOQUES.
    """
    if texto in BLOQUES:
        return BLOQUES[texto]

    primera = texto.split("·")[0].strip().split(" ")[0]
    return HOJAS.get(primera)

# Encabezado (normalizado) -> campo del modelo.
# Se aceptan variantes porque el .docx usaba "Nombre del Requerimiento"
# y "Nombre de la Incidencia" donde el .xlsx usa "Nombre del Proyecto".
COLUMNAS = {
    "nombre del proyecto": "nombre",
    "nombre del requerimiento": "nombre",
    "nombre de la incidencia": "nombre",
    "nombre": "nombre",
    "numero (id unico)": "codigo",
    "numero id unico": "codigo",
    "id unico": "codigo",
    # El exportador rotula esa misma columna "Codigo". Sin esta entrada,
    # reimportar un archivo generado por el sistema no reconocia el codigo
    # y cada fila se identificaba por nombre, que es justamente lo que la
    # primera columna existe para evitar.
    "codigo": "codigo",
    "codigo registro": "codigo",
    # "Tipo" es la categoria en los archivos que exporta el sistema.
    "tipo": "_categoria",
    "categoria": "_categoria",
    "fecha de solicitada": "fecha_solicitada",
    "fecha solicitada": "fecha_solicitada",
    # La fecha final la agrego el sistema; el archivo semanal original no
    # la traia. Se aceptan variantes porque cada quien la rotula distinto.
    "fecha final": "fecha_fin",
    "fecha fin": "fecha_fin",
    "fecha de fin": "fecha_fin",
    "fecha finalizacion": "fecha_fin",
    "fecha de finalizacion": "fecha_fin",
    "fecha estimada de fin": "fecha_fin",
    "fecha compromiso": "fecha_fin",
    "funcional solicitante": "funcional_solicitante",
    "descripcion": "descripcion",
    "porcentaje de avance": "avance",
    "avance": "avance",
    "asignado": "asignado",
    "asignado a": "asignado",
    "observacion": "observacion",
    "estatus": "estatus",
    "estado": "estatus",
}

# Encabezados del archivo de TAREAS exportado por el sistema.
COLUMNAS_TAREA = {
    "codigo tarea": "codigo",
    "codigo registro": "ticket_codigo",
    "registro": "_ignorar",
    "descripcion": "descripcion",
    "responsable": "responsable",
    "estado": "estado",
    "avance": "avance",
    "prioridad": "prioridad",
    "fecha inicio": "fecha_inicio",
    "fecha limite": "fecha_limite",
    "observacion": "observacion",
}

# Texto visible -> valor guardado.
ESTADOS_TAREA = {
    "pendiente": Tarea.PENDIENTE,
    "en curso": Tarea.EN_CURSO,
    "lista": Tarea.LISTA,
    "bloqueada": Tarea.BLOQUEADA,
}

PRIORIDADES_TAREA = {
    "alta": Tarea.ALTA,
    "media": Tarea.MEDIA,
    "baja": Tarea.BAJA,
}


MAX_COL = 14


def clave(valor):
    """Normaliza para comparar: sin acentos, minusculas, un solo espacio."""
    texto = str(valor or "").strip().lower()
    texto = unicodedata.normalize("NFKD", texto)
    texto = "".join(c for c in texto if not unicodedata.combining(c))
    return re.sub(r"\s+", " ", texto).strip()


def limpiar_texto(valor):
    if valor is None:
        return ""
    return re.sub(r"\s+", " ", str(valor).strip())


def parse_avance(valor):
    """
    El avance llega de tres formas:
        0.95   float, formato porcentaje de Excel  -> 95
        "95%"  texto copiado del Word              -> 95
        95     entero suelto                       -> 95
    """
    if valor is None or valor == "":
        return 0

    if isinstance(valor, (int, float)):
        n = float(valor)
    else:
        texto = str(valor).replace("%", "").replace(",", ".").strip()
        if not texto:
            return 0
        try:
            n = float(texto)
        except ValueError:
            return 0

    # Excel guarda 95% como 0.95: un valor entre 0 y 1 es fraccion.
    if 0 < n <= 1:
        n *= 100

    return max(0, min(100, int(round(n))))


def parse_fecha(valor):
    if valor is None or valor == "":
        return None
    if isinstance(valor, datetime):
        return valor.date()
    if isinstance(valor, date):
        return valor

    texto = str(valor).strip()
    for formato in ("%d/%m/%Y", "%d-%m-%Y", "%Y-%m-%d", "%d/%m/%y"):
        try:
            return datetime.strptime(texto, formato).date()
        except ValueError:
            continue
    return None


def parse_estatus(valor):
    """Quita espacios sobrantes y fechas pegadas al estatus."""
    texto = limpiar_texto(valor)
    if not texto:
        return "Desarrollo"

    # "Desarrollo 27/8/2026" -> "Desarrollo"
    texto = re.sub(r"\s*\d{1,2}[/-]\d{1,2}[/-]\d{2,4}\s*$", "", texto).strip()

    conocidos = [c[0] for c in Ticket.ESTATUS]
    for conocido in conocidos:
        if clave(texto) == clave(conocido):
            return conocido

    # Estatus nuevo: se conserva tal cual para no perder informacion.
    return texto or "Desarrollo"


def _es_encabezado(celdas):
    """Con 4 columnas reconocidas ya es inequivocamente la fila de titulos."""
    return sum(1 for v in celdas if clave(v) in COLUMNAS) >= 4


def _mapear(celdas):
    """indice de columna -> campo del modelo."""
    return {i: COLUMNAS[clave(v)] for i, v in enumerate(celdas) if clave(v) in COLUMNAS}


def _es_continuacion(fila):
    """Trae solo el Nombre y ningun otro dato: es cola de la fila anterior."""
    if not fila.get("nombre"):
        return False
    otros = (
        "codigo",
        "fecha_solicitada",
        "fecha_fin",
        "funcional_solicitante",
        "descripcion",
        "asignado",
        "observacion",
    )
    if any(fila.get(c) for c in otros):
        return False
    if fila.get("avance"):
        return False
    # El estatus por defecto es "Desarrollo"; solo cuenta si vino explicito.
    return not fila.get("_estatus_explicito")


def leer_filas(ruta):
    """
    Recorre el libro detectando bloques y devuelve filas normalizadas.

    Recorre TODAS las hojas, no solo la primera: el archivo semanal trae
    los tres bloques en una sola hoja, pero el que exporta el sistema
    reparte una categoria por hoja, y leyendo solo la primera se perdian
    los requerimientos y las incidencias enteros.

    La categoria se deduce de tres fuentes, de mayor a menor prioridad:
      1. la columna "Tipo" de la propia fila (archivos exportados),
      2. la fila-titulo del bloque (archivo semanal),
      3. el nombre de la hoja (archivos exportados sin fila-titulo).

    :return: (filas, avisos)
    """
    import openpyxl

    wb = openpyxl.load_workbook(ruta, data_only=True)
    filas, avisos = [], []

    for ws in wb.worksheets:
        # La hoja arranca con la categoria que sugiere su nombre; una
        # fila-titulo posterior la pisa.
        categoria = HOJAS.get(clave(ws.title))
        mapa = None

        for n, row in enumerate(
            ws.iter_rows(min_row=1, max_col=MAX_COL, values_only=True), start=1
        ):
            celdas = list(row) + [None] * (MAX_COL - len(row))

            if not any(v not in (None, "") for v in celdas):
                continue

            # Fila-titulo: cambia la categoria en curso. Solo cuenta si es
            # el unico dato de la fila, para no confundirla con una fila
            # de datos cuyo primer valor sea un codigo.
            solo_primera = not any(v not in (None, "") for v in celdas[1:])
            if solo_primera:
                del_titulo = _categoria_de_titulo(clave(celdas[0]))
                if del_titulo:
                    categoria, mapa = del_titulo, None
                    continue

            if _es_encabezado(celdas):
                mapa = _mapear(celdas)
                continue

            if mapa is None:
                continue

            fila = {"_fila": n, "_hoja": ws.title}
            for idx, campo in mapa.items():
                valor = celdas[idx]
                if campo == "avance":
                    fila[campo] = parse_avance(valor)
                elif campo in ("fecha_solicitada", "fecha_fin"):
                    fila[campo] = parse_fecha(valor)
                elif campo == "estatus":
                    fila["_estatus_explicito"] = bool(limpiar_texto(valor))
                    fila[campo] = parse_estatus(valor)
                elif campo == "_categoria":
                    fila[campo] = CATEGORIAS_TEXTO.get(clave(valor))
                else:
                    fila[campo] = limpiar_texto(valor)

            # La columna "Tipo" de la fila manda sobre el contexto.
            fila["categoria"] = fila.get("_categoria") or categoria

            # TRAMPA 1: fila de continuacion, se pega a la anterior.
            if _es_continuacion(fila) and filas:
                filas[-1]["nombre"] = f"{filas[-1]['nombre']} {fila['nombre']}".strip()
                continue

            if not fila.get("nombre"):
                avisos.append(
                    {
                        "fila": n,
                        "hoja": ws.title,
                        "motivo": "Sin nombre: no se puede identificar el registro.",
                    }
                )
                continue

            if not fila["categoria"]:
                avisos.append(
                    {
                        "fila": n,
                        "hoja": ws.title,
                        "motivo": "No se pudo determinar el tipo (proyecto, "
                        "requerimiento o incidencia).",
                    }
                )
                continue

            filas.append(fila)

    return filas, avisos


def leer_filas_docx(ruta):
    """
    Lectura del formato anterior (.docx), donde los mismos datos venian
    en tres tablas separadas en lugar de tres bloques de una hoja.
    """
    import docx

    doc = docx.Document(ruta)
    orden = [Ticket.PROYECTO, Ticket.REQUERIMIENTO, Ticket.INCIDENCIA]
    filas, avisos = [], []

    for i, tabla in enumerate(doc.tables):
        categoria = orden[i] if i < len(orden) else Ticket.INCIDENCIA
        if not tabla.rows:
            continue

        encabezados = [clave(c.text) for c in tabla.rows[0].cells]
        mapa = {j: COLUMNAS[h] for j, h in enumerate(encabezados) if h in COLUMNAS}

        for n, row in enumerate(tabla.rows[1:], start=2):
            fila = {"categoria": categoria, "_fila": n}
            for idx, campo in mapa.items():
                if idx >= len(row.cells):
                    continue
                valor = row.cells[idx].text
                if campo == "avance":
                    fila[campo] = parse_avance(valor)
                elif campo in ("fecha_solicitada", "fecha_fin"):
                    fila[campo] = parse_fecha(valor)
                elif campo == "estatus":
                    fila[campo] = parse_estatus(valor)
                else:
                    fila[campo] = limpiar_texto(valor)

            if not fila.get("nombre"):
                avisos.append({"fila": n, "motivo": "Fila sin nombre."})
                continue

            filas.append(fila)

    return filas, avisos


@transaction.atomic
def importar(ruta, nombre_archivo, usuario=None):
    """
    Crea o actualiza tickets a partir del archivo y devuelve el ImportBatch
    con el resumen. Todo ocurre en una transaccion: si algo falla, la base
    queda como estaba.
    """
    with open(ruta, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()

    if str(nombre_archivo).lower().endswith(".docx"):
        filas, avisos = leer_filas_docx(ruta)
    else:
        filas, avisos = leer_filas(ruta)

    resumen = {"creados": 0, "actualizados": 0, "sin_cambios": 0, "omitidos": len(avisos)}

    for fila in filas:
        datos = {
            "categoria": fila["categoria"],
            "nombre": fila.get("nombre", ""),
            "fecha_solicitada": fila.get("fecha_solicitada"),
            "fecha_fin": fila.get("fecha_fin"),
            "funcional_solicitante": fila.get("funcional_solicitante", ""),
            "descripcion": fila.get("descripcion", ""),
            "avance": fila.get("avance", 0),
            "asignado": fila.get("asignado", ""),
            "observacion": fila.get("observacion", ""),
            "estatus": fila.get("estatus", "Desarrollo"),
        }

        # Se busca primero por codigo; el archivo no lo trae, asi que en
        # la practica identifica por nombre + categoria.
        ticket = None
        if fila.get("codigo"):
            ticket = Ticket.objects.filter(codigo=fila["codigo"]).first()
        if ticket is None:
            ticket = Ticket.objects.filter(
                categoria=fila["categoria"], nombre__iexact=datos["nombre"]
            ).first()

        if ticket is None:
            datos["codigo"] = fila.get("codigo") or Ticket.siguiente_codigo(
                fila["categoria"]
            )
            ticket = Ticket.objects.create(**datos)
            _registrar_creacion(ticket, usuario, nombre_archivo)
            resumen["creados"] += 1
            continue

        # Un campo vacio en el archivo NO pisa un dato cargado a mano
        # en la aplicacion: la carga manual es mas fresca que el reporte.
        datos = {k: v for k, v in datos.items() if v not in (None, "", 0) or k == "avance"}
        if datos.get("avance") == 0:
            datos.pop("avance", None)

        cambios = aplicar_cambios(
            ticket, datos, usuario, TicketHistory.IMPORTACION, nombre_archivo
        )
        if cambios:
            resumen["actualizados"] += 1
        else:
            resumen["sin_cambios"] += 1

    return ImportBatch.objects.create(
        usuario=usuario,
        archivo=nombre_archivo,
        hash=digest,
        filas_leidas=len(filas),
        detalle=avisos or None,
        **resumen,
    )


def _normalizar(valor):
    """
    Lleva cualquier valor a texto comparable.

    Sin esto, comparar 95 (int de la BD) contra "95" (string del
    formulario) daria "cambio" en cada guardado y llenaria el
    historico de filas basura.
    """
    if valor is None or valor == "":
        return ""
    if isinstance(valor, (date, datetime)):
        return valor.strftime("%Y-%m-%d")
    return str(valor).strip()


def _registrar_creacion(ticket, usuario, archivo=""):
    """Guarda el estado inicial de cada campo con valor_anterior vacio."""
    origen = TicketHistory.IMPORTACION if archivo else TicketHistory.CREACION
    filas = [
        TicketHistory(
            ticket=ticket,
            usuario=usuario,
            campo=campo,
            valor_anterior="",
            valor_nuevo=_normalizar(getattr(ticket, campo)),
            origen=origen,
            archivo=archivo,
        )
        for campo in Ticket.CAMPOS_AUDITADOS
        if _normalizar(getattr(ticket, campo))
    ]
    TicketHistory.objects.bulk_create(filas)


def aplicar_cambios(ticket, datos, usuario, origen=TicketHistory.EDICION, archivo=""):
    """
    Aplica cambios y registra en el historico SOLO los campos que
    realmente cambiaron de valor.

    :return: cantidad de campos modificados (0 = sin cambios)
    """
    historial, tocados = [], []

    for campo, nuevo in datos.items():
        if campo not in Ticket.CAMPOS_AUDITADOS:
            continue

        anterior = _normalizar(getattr(ticket, campo))
        nuevo_norm = _normalizar(nuevo)

        if anterior == nuevo_norm:
            continue

        setattr(ticket, campo, nuevo)
        tocados.append(campo)
        historial.append(
            TicketHistory(
                ticket=ticket,
                usuario=usuario,
                campo=campo,
                valor_anterior=anterior,
                valor_nuevo=nuevo_norm,
                origen=origen,
                archivo=archivo,
            )
        )

    if not tocados:
        return 0

    # actualizado_en es auto_now: se refresca solo al guardar, y es
    # lo que dispara el aviso de "hay datos nuevos" en las otras pantallas.
    ticket.save(update_fields=tocados + ["actualizado_en"])
    TicketHistory.objects.bulk_create(historial)

    return len(tocados)


def es_archivo_de_tareas(ruta):
    """
    Reconoce si el archivo subido es el de tareas o el semanal de pendientes.

    Se detecta por los encabezados, no por el nombre del archivo: el
    usuario sube lo que tiene y el sistema entiende qué es. Pedirle que
    elija el tipo sería trasladarle un trabajo que la máquina resuelve sola.
    """
    import openpyxl

    try:
        ws = openpyxl.load_workbook(ruta, data_only=True, read_only=True).worksheets[0]
    except Exception:
        return False

    # Se miran 15 filas y no 6: con el membrete institucional arriba, los
    # encabezados bajaron a la fila 6, y con 6 el margen era de cero. Si
    # manana el membrete crece una linea, dejaria de reconocer el archivo.
    for fila in ws.iter_rows(min_row=1, max_row=15, max_col=MAX_COL, values_only=True):
        claves = {clave(v) for v in fila if v}
        if "codigo tarea" in claves and "codigo registro" in claves:
            return True
    return False


def leer_tareas(ruta):
    """
    Lee el archivo de tareas exportado por el sistema.

    :return: (filas, avisos)
    """
    import openpyxl

    ws = openpyxl.load_workbook(ruta, data_only=True).worksheets[0]
    filas, avisos, mapa = [], [], None

    for n, row in enumerate(
        ws.iter_rows(min_row=1, max_col=MAX_COL, values_only=True), start=1
    ):
        celdas = list(row) + [None] * (MAX_COL - len(row))

        if not any(v not in (None, "") for v in celdas):
            continue

        if mapa is None:
            reconocidas = {
                i: COLUMNAS_TAREA[clave(v)]
                for i, v in enumerate(celdas)
                if clave(v) in COLUMNAS_TAREA
            }
            # Con 4 encabezados reconocidos ya es la fila de títulos.
            if len(reconocidas) >= 4:
                mapa = {i: c for i, c in reconocidas.items() if c != "_ignorar"}
            continue

        fila = {"_fila": n}
        for idx, campo in mapa.items():
            valor = celdas[idx]
            if campo == "avance":
                fila[campo] = parse_avance(valor)
            elif campo in ("fecha_inicio", "fecha_limite"):
                fila[campo] = parse_fecha(valor)
            elif campo == "estado":
                fila[campo] = ESTADOS_TAREA.get(clave(valor), Tarea.PENDIENTE)
            elif campo == "prioridad":
                fila[campo] = PRIORIDADES_TAREA.get(clave(valor), Tarea.MEDIA)
            else:
                fila[campo] = limpiar_texto(valor)

        if not fila.get("descripcion"):
            avisos.append({"fila": n, "motivo": "Tarea sin descripción."})
            continue

        if not fila.get("ticket_codigo"):
            avisos.append(
                {"fila": n, "motivo": "Falta el código del registro al que pertenece."}
            )
            continue

        filas.append(fila)

    return filas, avisos


@transaction.atomic
def importar_tareas(ruta, nombre_archivo, usuario=None):
    """
    Crea o actualiza tareas a partir del archivo exportado.

    Cada fila se identifica por su código de tarea. Si viene sin código,
    se crea una tarea nueva bajo el registro que indique la columna
    'Código registro'. Nada se borra.
    """
    with open(ruta, "rb") as fh:
        digest = hashlib.sha256(fh.read()).hexdigest()

    filas, avisos = leer_tareas(ruta)
    resumen = {"creados": 0, "actualizados": 0, "sin_cambios": 0, "omitidos": len(avisos)}

    for fila in filas:
        padre = Ticket.objects.filter(codigo__iexact=fila["ticket_codigo"]).first()
        if padre is None:
            resumen["omitidos"] += 1
            avisos.append({
                "fila": fila["_fila"],
                "motivo": f"No existe el registro {fila['ticket_codigo']}.",
            })
            continue

        datos = {
            "descripcion": fila.get("descripcion", ""),
            "responsable": fila.get("responsable", ""),
            "estado": fila.get("estado", Tarea.PENDIENTE),
            "avance": fila.get("avance", 0),
            "prioridad": fila.get("prioridad", Tarea.MEDIA),
            "fecha_inicio": fila.get("fecha_inicio"),
            "fecha_limite": fila.get("fecha_limite"),
            "observacion": fila.get("observacion", ""),
        }

        tarea = (
            Tarea.objects.filter(codigo=fila["codigo"]).first()
            if fila.get("codigo")
            else None
        )

        if tarea is None:
            tarea = Tarea.objects.create(
                ticket=padre,
                codigo=fila.get("codigo") or Tarea.siguiente_codigo(padre),
                **datos,
            )
            _registrar_creacion_tarea(tarea, usuario, nombre_archivo)
            resumen["creados"] += 1
            continue

        cambios = aplicar_cambios_tarea(
            tarea, datos, usuario, TicketHistory.IMPORTACION, nombre_archivo
        )
        if cambios:
            resumen["actualizados"] += 1
        else:
            resumen["sin_cambios"] += 1

    return ImportBatch.objects.create(
        usuario=usuario,
        archivo=nombre_archivo,
        hash=digest,
        filas_leidas=len(filas),
        detalle=avisos or None,
        **resumen,
    )


def _registrar_creacion_tarea(tarea, usuario, archivo=""):
    """Estado inicial de cada campo, con valor_anterior vacío."""
    origen = TicketHistory.IMPORTACION if archivo else TicketHistory.CREACION
    TicketHistory.objects.bulk_create([
        TicketHistory(
            tarea=tarea,
            usuario=usuario,
            campo=campo,
            valor_anterior="",
            valor_nuevo=_normalizar(getattr(tarea, campo)),
            origen=origen,
            archivo=archivo,
        )
        for campo in Tarea.CAMPOS_AUDITADOS
        if _normalizar(getattr(tarea, campo))
    ])


def aplicar_cambios_tarea(tarea, datos, usuario, origen=TicketHistory.EDICION, archivo=""):
    """
    Igual que aplicar_cambios pero sobre una tarea.

    No se usa update_fields: el save() del modelo sincroniza estado y
    avance entre sí, y con update_fields ese ajuste no se guardaría.

    :return: cantidad de campos modificados (0 = sin cambios)
    """
    historial, tocados = [], []

    for campo, nuevo in datos.items():
        if campo not in Tarea.CAMPOS_AUDITADOS:
            continue

        anterior = _normalizar(getattr(tarea, campo))
        nuevo_norm = _normalizar(nuevo)

        if anterior == nuevo_norm:
            continue

        setattr(tarea, campo, nuevo)
        tocados.append(campo)
        historial.append(
            TicketHistory(
                tarea=tarea,
                usuario=usuario,
                campo=campo,
                valor_anterior=anterior,
                valor_nuevo=nuevo_norm,
                origen=origen,
                archivo=archivo,
            )
        )

    if not tocados:
        return 0

    tarea.save()
    TicketHistory.objects.bulk_create(historial)

    return len(tocados)
