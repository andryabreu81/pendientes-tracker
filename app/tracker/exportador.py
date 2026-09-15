"""
Exportación a Excel de registros y tareas.

El archivo generado está pensado para volver: el equipo lo descarga, lo
actualiza y lo vuelve a subir. Por eso la PRIMERA COLUMNA es siempre el
código (PRY-001, PRY-003.T01).

Sin el código, al reimportar habría que identificar cada fila por su
nombre, y bastaría con que alguien corrigiera una tilde para que se
creara un registro duplicado en lugar de actualizar el existente.
"""

from io import BytesIO

from openpyxl import Workbook
from openpyxl.drawing.image import Image as ImagenExcel
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import get_column_letter

from . import membrete
from .models import Tarea, Ticket

# Paleta del sistema. El azul sale del logo institucional (ver
# tracker/membrete.py); antes era #1E40AF, que se parecia pero no era el
# color del banco.
AZUL_CLARO = "EEF2FC"
GRIS_BORDE = "D8DEE9"
GRIS_TEXTO = "64748B"
AMBAR = "FEF3C7"

_BORDE = Border(*[Side(style="thin", color=GRIS_BORDE)] * 4)

# Estructura fija de la cabecera de cada hoja:
#
#   fila 1   logo + nombre de la institucion
#   fila 2   clasificacion de confidencialidad
#   fila 3   franja de color institucional
#   fila 4   titulo del reporte
#   fila 5   emision, usuario y filtros aplicados
#   fila 6   encabezados de columna
#   fila 7+  datos
#
# El importador tolera estas filas: descarta todo hasta encontrar la fila
# de encabezados, y la fila 4 le sigue sirviendo para deducir la categoria.
FILA_NOMBRE = 1
FILA_CLASIFICACION = 2
FILA_FRANJA = 3
FILA_TITULO = 4
FILA_EMISION = 5
FILA_ENCABEZADOS = 6
FILA_DATOS = 7

# El logo se dibuja flotando sobre la celda A1. Se mantiene angosto para
# no invadir la columna del nombre.
LOGO_ALTO_PX = 44


# Columnas del archivo de registros: encabezado -> atributo del modelo.
COLUMNAS_TICKET = [
    ("Código", "codigo", 14),
    ("Tipo", "categoria_label", 15),
    ("Nombre", "nombre", 52),
    ("Fecha solicitada", "fecha_solicitada", 16),
    ("Fecha final", "fecha_fin", 14),
    ("Funcional solicitante", "funcional_solicitante", 22),
    ("Descripción", "descripcion", 60),
    ("Avance", "avance", 9),
    ("Asignado a", "asignado", 20),
    ("Observación", "observacion", 45),
    ("Estatus", "estatus", 20),
    # El riesgo es calculado: sale en el archivo como referencia, y al
    # reimportar se ignora porque no esta en el mapa de columnas del
    # importador. Vuelve a calcularse solo, siempre fresco.
    ("Score de riesgo", "risk_score", 14),
    ("Nivel de riesgo", "risk_level", 14),
]

COLUMNAS_TAREA = [
    ("Código tarea", "codigo", 16),
    ("Código registro", "_ticket_codigo", 16),
    ("Registro", "_ticket_nombre", 42),
    ("Descripción", "descripcion", 55),
    ("Responsable", "responsable", 20),
    ("Estado", "_estado_label", 14),
    ("Avance", "avance", 9),
    ("Prioridad", "_prioridad_label", 12),
    ("Fecha inicio", "fecha_inicio", 14),
    ("Fecha límite", "fecha_limite", 14),
    ("Observación", "observacion", 40),
]


def _membretar(hoja, total_columnas, contexto):
    """
    Banda institucional al tope de la hoja: logo, nombre y clasificación.

    El logo se inserta como imagen flotante. Si el archivo no está, la
    banda sale igual con el membrete tipográfico: un despliegue sin el
    logo no debe hacer fallar la descarga entera.
    """
    azul = membrete.color()
    ultima = get_column_letter(total_columnas)

    ruta = membrete.ruta_logo()
    if ruta:
        imagen = ImagenExcel(str(ruta))
        # Se respeta la proporción original para no deformar la marca.
        proporcion = imagen.width / imagen.height
        imagen.height = LOGO_ALTO_PX
        imagen.width = int(LOGO_ALTO_PX * proporcion)
        hoja.add_image(imagen, "A1")

    # El nombre arranca en la columna B para no pisar el logo.
    columna_texto = 2 if ruta and total_columnas > 1 else 1

    hoja.merge_cells(
        start_row=FILA_NOMBRE, start_column=columna_texto,
        end_row=FILA_NOMBRE, end_column=total_columnas,
    )
    c = hoja.cell(row=FILA_NOMBRE, column=columna_texto, value=membrete.encabezado_completo())
    c.font = Font(bold=True, size=14, color=azul)
    c.alignment = Alignment(horizontal="left", vertical="center", indent=1)

    hoja.merge_cells(
        start_row=FILA_CLASIFICACION, start_column=columna_texto,
        end_row=FILA_CLASIFICACION, end_column=total_columnas,
    )
    c = hoja.cell(row=FILA_CLASIFICACION, column=columna_texto, value=membrete.clasificacion())
    c.font = Font(size=9, italic=True, color=GRIS_TEXTO)
    c.alignment = Alignment(horizontal="left", vertical="center", indent=1)

    # Franja de color institucional que cierra la banda.
    hoja.merge_cells(
        start_row=FILA_FRANJA, start_column=1,
        end_row=FILA_FRANJA, end_column=total_columnas,
    )
    hoja.cell(row=FILA_FRANJA, column=1).fill = PatternFill("solid", fgColor=azul)

    hoja.row_dimensions[FILA_NOMBRE].height = 26
    hoja.row_dimensions[FILA_CLASIFICACION].height = 14
    hoja.row_dimensions[FILA_FRANJA].height = 5

    # Pie con la clasificación en cada página impresa.
    hoja.oddFooter.left.text = f"{membrete.sigla()} · {membrete.clasificacion()}"
    hoja.oddFooter.left.size = 8
    hoja.oddFooter.left.color = GRIS_TEXTO
    hoja.oddFooter.right.text = "Página &P de &N"
    hoja.oddFooter.right.size = 8
    hoja.oddFooter.right.color = GRIS_TEXTO
    # La banda del membrete se repite arriba de cada página impresa.
    hoja.print_title_rows = f"{FILA_NOMBRE}:{FILA_ENCABEZADOS}"


def _encabezar(hoja, columnas, titulo, contexto=None):
    """Membrete + título + línea de emisión + encabezados de columna."""
    contexto = contexto or {}
    total = len(columnas)
    azul = membrete.color()

    _membretar(hoja, total, contexto)

    hoja.merge_cells(
        start_row=FILA_TITULO, start_column=1, end_row=FILA_TITULO, end_column=total
    )
    celda = hoja.cell(row=FILA_TITULO, column=1, value=titulo)
    celda.font = Font(bold=True, size=13, color="FFFFFF")
    celda.fill = PatternFill("solid", fgColor=azul)
    celda.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    hoja.row_dimensions[FILA_TITULO].height = 26

    # Emisión y filtros: dejan constancia de que el archivo es un recorte
    # con fecha, y no el universo completo en su estado actual.
    hoja.merge_cells(
        start_row=FILA_EMISION, start_column=1, end_row=FILA_EMISION, end_column=total
    )
    celda = hoja.cell(
        row=FILA_EMISION,
        column=1,
        value=f"{membrete.linea_emision(contexto.get('usuario'))}"
        f"  ·  {membrete.describir_filtros(**contexto.get('filtros_args', {}))}",
    )
    celda.font = Font(size=9, color=GRIS_TEXTO)
    celda.alignment = Alignment(horizontal="left", vertical="center", indent=1)
    hoja.row_dimensions[FILA_EMISION].height = 16

    for i, (rotulo, _, ancho) in enumerate(columnas, start=1):
        c = hoja.cell(row=FILA_ENCABEZADOS, column=i, value=rotulo)
        c.font = Font(bold=True, size=10, color=azul)
        c.fill = PatternFill("solid", fgColor=AZUL_CLARO)
        c.alignment = Alignment(horizontal="left", vertical="center", wrap_text=True)
        c.border = _BORDE
        hoja.column_dimensions[get_column_letter(i)].width = ancho

    hoja.row_dimensions[FILA_ENCABEZADOS].height = 30
    # La cabecera queda fija al desplazarse: con 17 filas ya se agradece.
    hoja.freeze_panes = f"A{FILA_DATOS}"


def _escribir(hoja, fila, columnas, obj, resaltar=False):
    for i, (_, campo, _) in enumerate(columnas, start=1):
        valor = getattr(obj, campo, "")
        c = hoja.cell(row=fila, column=i, value=valor if valor != "" else None)
        c.border = _BORDE
        c.alignment = Alignment(vertical="top", wrap_text=campo in (
            "nombre", "descripcion", "observacion", "_ticket_nombre"
        ))

        if campo == "avance":
            # Se guarda como fracción con formato de porcentaje: es lo que
            # Excel entiende, y lo que el importador ya sabe volver a leer.
            c.value = (valor or 0) / 100
            c.number_format = "0%"
            c.alignment = Alignment(horizontal="center", vertical="top")
        elif campo in (
            "fecha_solicitada",
            "fecha_fin",
            "fecha_inicio",
            "fecha_limite",
        ) and valor:
            c.number_format = "DD/MM/YYYY"
        elif campo == "codigo":
            c.font = Font(bold=True, size=10)

        if resaltar:
            c.fill = PatternFill("solid", fgColor=AMBAR)


def exportar_tickets(queryset, titulo="Registros", contexto=None):
    """
    Un libro con los registros. Si el filtro abarca varias categorías,
    cada una va en su propia hoja, igual que el archivo original.

    :param contexto: usuario y filtros que se estampan en el membrete.
    """
    libro = Workbook()
    libro.remove(libro.active)
    _describir_libro(libro, titulo)

    nombres = {
        Ticket.PROYECTO: "Proyectos",
        Ticket.REQUERIMIENTO: "Requerimientos",
        Ticket.INCIDENCIA: "Incidencias",
    }

    por_categoria = {}
    for t in queryset:
        por_categoria.setdefault(t.categoria, []).append(t)

    if not por_categoria:
        hoja = libro.create_sheet("Registros")
        _encabezar(hoja, COLUMNAS_TICKET, "Sin registros para exportar", contexto)
        return _guardar(libro)

    for categoria in (Ticket.PROYECTO, Ticket.REQUERIMIENTO, Ticket.INCIDENCIA):
        items = por_categoria.get(categoria)
        if not items:
            continue

        hoja = libro.create_sheet(nombres[categoria])
        _encabezar(
            hoja, COLUMNAS_TICKET,
            f"{nombres[categoria].upper()} · {len(items)} registro"
            f"{'s' if len(items) != 1 else ''}",
            contexto,
        )

        for n, t in enumerate(items, start=FILA_DATOS):
            t.categoria_label = t.get_categoria_display()
            # Los registros a los que les falta información van en ámbar:
            # el color señala qué completar sin leer fila por fila.
            _escribir(hoja, n, COLUMNAS_TICKET, t, resaltar=t.incompleto)

        ultima = get_column_letter(len(COLUMNAS_TICKET))
        hoja.auto_filter.ref = (
            f"A{FILA_ENCABEZADOS}:{ultima}{len(items) + FILA_ENCABEZADOS}"
        )

    return _guardar(libro)


def exportar_tareas(queryset, titulo="Tareas", contexto=None):
    """
    Un libro con las tareas. Cada fila lleva el código de su registro
    padre, que es lo que permite reimportarlas sin ambigüedad.
    """
    libro = Workbook()
    hoja = libro.active
    hoja.title = "Tareas"
    _describir_libro(libro, titulo)

    tareas = list(queryset.select_related("ticket"))
    _encabezar(
        hoja, COLUMNAS_TAREA,
        f"{titulo.upper()} · {len(tareas)} tarea{'s' if len(tareas) != 1 else ''}",
        contexto,
    )

    for n, t in enumerate(tareas, start=FILA_DATOS):
        t._ticket_codigo = t.ticket.codigo
        t._ticket_nombre = t.ticket.nombre
        t._estado_label = t.get_estado_display()
        t._prioridad_label = t.get_prioridad_display()
        _escribir(hoja, n, COLUMNAS_TAREA, t, resaltar=t.vencida)

    if tareas:
        ultima = get_column_letter(len(COLUMNAS_TAREA))
        hoja.auto_filter.ref = (
            f"A{FILA_ENCABEZADOS}:{ultima}{len(tareas) + FILA_ENCABEZADOS}"
        )

    return _guardar(libro)


def _describir_libro(libro, titulo):
    """
    Propiedades del archivo: se ven en 'Obtener información' del sistema
    operativo y en el panel de detalles de Excel, aunque nadie abra la
    planilla.
    """
    libro.properties.creator = membrete.encabezado_completo()
    libro.properties.title = titulo
    libro.properties.description = membrete.clasificacion()
    libro.properties.category = membrete.sigla()


def _guardar(libro):
    """Devuelve el libro como bytes, listo para la respuesta HTTP."""
    buffer = BytesIO()
    libro.save(buffer)
    buffer.seek(0)
    return buffer.getvalue()
