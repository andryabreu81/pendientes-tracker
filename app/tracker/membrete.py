"""
Membrete institucional de los archivos que exporta el sistema.

Fuente única de la identidad visual: el Excel de registros, el de tareas y
la presentación de PowerPoint leen todos de acá. Cambiar el nombre o el
color en un solo lugar los cambia en los tres.

Los valores salen de settings, que a su vez los lee del .env. El nombre de
la institución NO está escrito en el código: un reporte que circula a
nivel ejecutivo con el nombre mal impreso es peor que uno sin membrete, y
quien lo detecta tiene que poder corregirlo sin editar Python.

El .ics de reuniones queda afuera: es un formato de calendario y no admite
membrete. Ahí la identificación va en el campo PRODID.
"""

from pathlib import Path

from django.conf import settings
from django.utils import timezone

# Etiqueta visible de cada filtro, para dejar constancia en el archivo de
# que lo exportado es un recorte y no el universo completo.
ETIQUETAS_FILTRO = {
    "categoria": "Tipo",
    "estatus": "Estatus",
    "responsable": "Responsable",
    "riesgo": "Riesgo",
    "q": "Búsqueda",
}


def nombre():
    return settings.ORG_NOMBRE


def sigla():
    return settings.ORG_SIGLA


def unidad():
    return settings.ORG_UNIDAD


def clasificacion():
    return settings.ORG_CLASIFICACION


def color():
    """Azul institucional, sin '#': es como lo pide openpyxl."""
    return settings.ORG_COLOR.lstrip("#").upper()


def color_rgb():
    """El mismo color como terna (r, g, b), que es lo que pide python-pptx."""
    c = color()
    return tuple(int(c[i : i + 2], 16) for i in (0, 2, 4))


def ruta_logo():
    """
    Ruta al archivo del logo, o None si no está.

    Devolver None y no reventar es deliberado: si alguien despliega sin el
    logo, el reporte sale con el membrete tipográfico en lugar de fallar
    la descarga entera.
    """
    ruta = Path(settings.ORG_LOGO)
    return ruta if ruta.is_file() else None


def encabezado_completo():
    """'Banco Digital de los Trabajadores · Gerencia X', o solo el banco."""
    partes = [nombre()]
    if unidad():
        partes.append(unidad())
    return " · ".join(partes)


def linea_emision(usuario=None):
    """Cuándo se generó el archivo y quién lo pidió."""
    momento = timezone.localtime().strftime("%d/%m/%Y a las %H:%M")
    texto = f"Emitido el {momento}"

    if usuario is not None and getattr(usuario, "is_authenticated", False):
        texto += f" por {usuario.get_full_name() or usuario.username}"

    return texto


def describir_filtros(filtros=None, categorias=None, niveles_riesgo=None):
    """
    Los filtros aplicados, en texto legible.

    Sin esto, quien recibe el archivo por correo no tiene forma de saber
    que está mirando un recorte, y suma los totales creyendo que son el
    universo completo.

    :param categorias: pares (valor, etiqueta) para traducir el tipo.
    :param niveles_riesgo: idem para el nivel de riesgo.
    """
    if not filtros:
        return "Sin filtros: todos los registros"

    traducciones = {
        "categoria": dict(categorias or []),
        "riesgo": dict(niveles_riesgo or []),
    }

    partes = []
    for campo, etiqueta in ETIQUETAS_FILTRO.items():
        valor = (filtros.get(campo) or "").strip()
        if not valor:
            continue
        partes.append(f"{etiqueta}: {traducciones.get(campo, {}).get(valor, valor)}")

    return " · ".join(partes) if partes else "Sin filtros: todos los registros"
