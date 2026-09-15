"""
Generación de archivos .ics (iCalendar, RFC 5545).

Se arma el texto a mano con la librería estándar. Traer una dependencia
nueva para producir veinte líneas de texto plano no se justifica, y menos
en un contenedor que hoy instala ocho paquetes contados.

Alcance: el .ics describe la cita y el usuario la agrega a su calendario
abriendo el archivo. NO envía invitaciones ni escribe en el calendario de
nadie: eso exigiría OAuth contra el tenant corporativo.
"""

from datetime import timezone as tz

from django.utils import timezone

# Longitud máxima de línea que fija el RFC. Pasarse rompe la lectura en
# algunos clientes, así que las líneas largas se parten.
LIMITE_LINEA = 75


def _escapar(texto):
    """Coma, punto y coma y barra son separadores dentro del formato."""
    return (
        str(texto or "")
        .replace("\\", "\\\\")
        .replace(";", "\\;")
        .replace(",", "\\,")
        .replace("\r\n", "\\n")
        .replace("\n", "\\n")
    )


def _plegar(linea):
    """
    Parte una línea larga en varias, con un espacio al inicio de cada
    continuación, que es como el formato marca que sigue la anterior.
    """
    bruto = linea.encode("utf-8")
    if len(bruto) <= LIMITE_LINEA:
        return linea

    partes, actual = [], ""
    for caracter in linea:
        tentativa = actual + caracter
        # El limite es en bytes: con acentos, un caracter puede ocupar dos.
        tope = LIMITE_LINEA if not partes else LIMITE_LINEA - 1
        if len(tentativa.encode("utf-8")) > tope:
            partes.append(actual)
            actual = caracter
        else:
            actual = tentativa

    partes.append(actual)
    return "\r\n ".join(partes)


def _utc(momento):
    """
    El formato pide UTC con sufijo Z.

    Se usa datetime.timezone.utc y no django.utils.timezone.utc: ese
    ultimo alias se removio en Django 5.0.
    """
    return timezone.localtime(momento, tz.utc).strftime("%Y%m%dT%H%M%SZ")


def reunion_a_ics(reunion, dominio="pendientes.local"):
    """
    Devuelve los bytes del archivo .ics de una reunión.

    :param dominio: sufijo del UID. Identifica al sistema que emitió la
                    cita, y hace que reabrir el mismo archivo actualice el
                    evento en lugar de duplicarlo.
    """
    objeto = reunion.objeto
    referencia = objeto.codigo if objeto else ""

    # Se arma con saltos de linea reales; _escapar() los convierte al
    # "\n" literal que pide el formato. Escribirlos ya escapados aca
    # hacia que el escapador duplicara la barra y el cliente de correo
    # mostrara "\\n" en el cuerpo de la cita.
    partes = []
    if referencia:
        partes.append(f"Registro: {referencia}")
    if reunion.notas:
        partes.append(reunion.notas)
    if reunion.enlace:
        partes.append(f"Enlace: {reunion.enlace}")

    descripcion = "\n\n".join(partes)

    # El lugar de una reunión virtual es su enlace.
    ubicacion = reunion.lugar or reunion.enlace

    lineas = [
        "BEGIN:VCALENDAR",
        "VERSION:2.0",
        "PRODID:-//DcGeeks//Seguimiento de Pendientes//ES",
        "CALSCALE:GREGORIAN",
        "METHOD:PUBLISH",
        "BEGIN:VEVENT",
        f"UID:reunion-{reunion.pk}@{dominio}",
        f"DTSTAMP:{_utc(reunion.creado_en or timezone.now())}",
        f"DTSTART:{_utc(reunion.fecha_hora)}",
        f"DTEND:{_utc(reunion.fin)}",
        f"SUMMARY:{_escapar(_titulo(reunion, referencia))}",
    ]

    if descripcion:
        lineas.append(f"DESCRIPTION:{_escapar(descripcion)}")
    if ubicacion:
        lineas.append(f"LOCATION:{_escapar(ubicacion)}")
    if reunion.enlace:
        lineas.append(f"URL:{reunion.enlace}")

    for participante in reunion.lista_participantes:
        if "@" in participante:
            lineas.append(
                f"ATTENDEE;CN={_escapar(participante)}:mailto:{participante}"
            )
        else:
            lineas.append(f"ATTENDEE;CN={_escapar(participante)}:invalid:nomail")

    # Aviso 15 minutos antes.
    lineas += [
        "BEGIN:VALARM",
        "TRIGGER:-PT15M",
        "ACTION:DISPLAY",
        f"DESCRIPTION:{_escapar(reunion.titulo)}",
        "END:VALARM",
        "END:VEVENT",
        "END:VCALENDAR",
    ]

    texto = "\r\n".join(_plegar(l) for l in lineas) + "\r\n"
    return texto.encode("utf-8")


def _titulo(reunion, referencia):
    """El código adelante, para que la cita se ubique sola en el calendario."""
    if referencia:
        return f"[{referencia}] {reunion.titulo}"
    return reunion.titulo


def nombre_archivo_ics(reunion):
    objeto = reunion.objeto
    base = objeto.codigo if objeto else "reunion"
    return f"reunion-{base}-{reunion.fecha_hora:%Y-%m-%d}.ics"
