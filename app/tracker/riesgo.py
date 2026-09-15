"""
Cálculo del riesgo de un registro (proyecto, requerimiento o incidencia).

TODA la parametrización vive en este archivo. Ajustar el peso de una señal
es cambiar un número acá, sin tocar modelos, vistas ni plantillas.

POR QUÉ SE CALCULA Y NO SE GUARDA
---------------------------------
El riesgo depende del paso del tiempo: un proyecto se vuelve riesgoso
mañana sin que nadie toque nada. Una columna guardada en la base quedaría
vencida todos los días a la medianoche y habría que recalcularla con una
tarea programada que este proyecto no tiene. Se calcula al vuelo.

El costo de esa decisión: filtrar por nivel de riesgo no se resuelve en
SQL, hay que evaluarlo en Python (ver views._tickets_filtrados).
"""

from django.utils import timezone

# ---------------------------------------------------------------
# Escala de niveles.
#
# Los rangos vienen del pedido del negocio. Se cerraron los límites
# porque el pedido original los daba solapados: "high 800-950" y
# "veryhigh 950+" reclamaban ambos el 950, y "critical 1000" caía
# dentro de "veryhigh 950+". Sin límites cerrados, un mismo score
# devolvía dos niveles distintos según el orden de evaluación.
# ---------------------------------------------------------------

LOW = "low"
MEDIUM = "medium"
HIGH = "high"
VERYHIGH = "veryhigh"
CRITICAL = "critical"

NIVELES = [
    (LOW, "Bajo"),
    (MEDIUM, "Medio"),
    (HIGH, "Alto"),
    (VERYHIGH, "Muy alto"),
    (CRITICAL, "Crítico"),
]

# (tope inclusive del rango, nivel). Se evalúa en orden.
RANGOS = [
    (499, LOW),
    (799, MEDIUM),
    (949, HIGH),
    (999, VERYHIGH),
    (1000, CRITICAL),
]

# ---------------------------------------------------------------
# Pesos de cada señal.
# ---------------------------------------------------------------

# (dias de atraso hasta, puntos). El último tramo es el tope.
TRAMOS_ATRASO = [
    (0, 0),
    (7, 150),
    (15, 300),
    (30, 450),
]
PUNTOS_ATRASO_MAXIMO = 600

# El avance declarado va por detrás de lo que corresponde al tiempo
# transcurrido. Se reparte proporcionalmente al desvío.
PUNTOS_DESVIO_AVANCE = 200

PUNTOS_POR_TAREA_VENCIDA = 60
TOPE_TAREAS_VENCIDAS = 180

PUNTOS_POR_TAREA_BLOQUEADA = 80
TOPE_TAREAS_BLOQUEADAS = 160

PUNTOS_SIN_ASIGNAR = 60
PUNTOS_SIN_FECHA_FIN = 40

# Un registro que no dispara la condición crítica nunca llega a 1000:
# el nivel "critical" significa algo concreto, no "sumó mucho".
TOPE_NO_CRITICO = 999
SCORE_CRITICO = 1000

# Condición dura que fuerza el nivel crítico.
#
# Nota: el pedido original definía crítico como "atraso > 30 días y
# avance < 100 y estatus distinto de Producción". Con esa regla el tramo
# de 600 puntos por atraso quedaba inalcanzable, porque todo atraso mayor
# a 30 días se convertía en crítico antes de sumar. Se agregó el umbral
# de avance para que ambos tramos signifiquen algo: muy atrasado pero
# avanzado suma 600; muy atrasado y sin avance es crítico.
DIAS_ATRASO_CRITICO = 30
AVANCE_CRITICO = 50

# Estatus que se consideran cerrados: ya llegó a producción, no hay
# riesgo de ejecución que medir.
ESTATUS_CERRADOS = ("Producción", "Producción Controlado")


def esta_cerrado(ticket):
    """Terminado: avance completo o ya desplegado en producción."""
    return ticket.avance >= 100 or ticket.estatus in ESTATUS_CERRADOS


def dias_atraso(ticket, hoy=None):
    """Días vencidos contra la fecha final. 0 si no venció o no tiene fecha."""
    if not ticket.fecha_fin:
        return 0
    hoy = hoy or timezone.localdate()
    return max(0, (hoy - ticket.fecha_fin).days)


def _puntos_atraso(dias):
    for tope, puntos in TRAMOS_ATRASO:
        if dias <= tope:
            return puntos
    return PUNTOS_ATRASO_MAXIMO


def _puntos_desvio(ticket, hoy):
    """
    Cuánto va por detrás el avance declarado respecto del tiempo consumido.

    Necesita las dos fechas para saber cuánto duraba el trabajo. Sin ellas
    no hay contra qué comparar y la señal no aporta.
    """
    if not ticket.fecha_solicitada or not ticket.fecha_fin:
        return 0

    total = (ticket.fecha_fin - ticket.fecha_solicitada).days
    if total <= 0:
        return 0

    transcurrido = (hoy - ticket.fecha_solicitada).days
    esperado = max(0, min(100, transcurrido / total * 100))
    desvio = max(0, esperado - ticket.avance)

    return round(desvio / 100 * PUNTOS_DESVIO_AVANCE)


def _puntos_tareas(ticket):
    """
    Tareas vencidas y bloqueadas.

    Usa ticket.tareas.all() sin filtrar en la base a propósito: la vista
    hace prefetch_related('tareas'), y filtrar acá dispararía una consulta
    nueva por cada registro, anulando el prefetch.
    """
    tareas = list(ticket.tareas.all())
    if not tareas:
        return 0

    vencidas = sum(1 for t in tareas if t.vencida)
    bloqueadas = sum(1 for t in tareas if t.estado == t.BLOQUEADA)

    return min(vencidas * PUNTOS_POR_TAREA_VENCIDA, TOPE_TAREAS_VENCIDAS) + min(
        bloqueadas * PUNTOS_POR_TAREA_BLOQUEADA, TOPE_TAREAS_BLOQUEADAS
    )


def calcular(ticket, hoy=None):
    """
    Score de riesgo del registro, entre 0 y 1000.

    :param hoy: fecha de referencia. Se inyecta desde los tests para no
                depender del día en que se corren.
    """
    if esta_cerrado(ticket):
        return 0

    hoy = hoy or timezone.localdate()
    atraso = dias_atraso(ticket, hoy)

    if atraso > DIAS_ATRASO_CRITICO and ticket.avance < AVANCE_CRITICO:
        return SCORE_CRITICO

    puntos = (
        _puntos_atraso(atraso)
        + _puntos_desvio(ticket, hoy)
        + _puntos_tareas(ticket)
        + (PUNTOS_SIN_ASIGNAR if not ticket.asignado.strip() else 0)
        + (PUNTOS_SIN_FECHA_FIN if not ticket.fecha_fin else 0)
    )

    return min(puntos, TOPE_NO_CRITICO)


def nivel_de(score):
    """Traduce el score al nivel: low, medium, high, veryhigh o critical."""
    for tope, nivel in RANGOS:
        if score <= tope:
            return nivel
    return CRITICAL


def etiqueta_de(nivel):
    return dict(NIVELES).get(nivel, nivel)
