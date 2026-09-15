from django import template

register = template.Library()

# Color de la barra segun el estatus, para que el grafico se lea de un vistazo.
COLORES = {
    "desarrollo": "bg-amber-500",
    "calidad": "bg-brand-600",
    "produccion": "bg-emerald-600",
    "produccion controlado": "bg-emerald-700",
}

BADGES = {
    "desarrollo": "bg-amber-100 text-amber-800",
    "calidad": "bg-brand-100 text-brand-800",
    "produccion": "bg-emerald-100 text-emerald-800",
    "produccion controlado": "bg-emerald-100 text-emerald-900",
}


def _clave(valor):
    texto = str(valor or "").strip().lower()
    for a, b in (("á", "a"), ("é", "e"), ("í", "i"), ("ó", "o"), ("ú", "u")):
        texto = texto.replace(a, b)
    return texto


@register.filter
def color_estatus(valor):
    return COLORES.get(_clave(valor), "bg-slate-400")


@register.filter
def badge_estatus(valor):
    return BADGES.get(_clave(valor), "bg-slate-100 text-slate-700")


# --- Tareas ---

COLOR_PRIORIDAD = {
    "alta": "bg-rose-500",
    "media": "bg-amber-500",
    "baja": "bg-slate-300",
}

BADGE_ESTADO_TAREA = {
    "pendiente": "bg-slate-100 text-slate-700",
    "en_curso": "bg-brand-100 text-brand-800",
    "lista": "bg-emerald-100 text-emerald-800",
    "bloqueada": "bg-rose-100 text-rose-800",
}


@register.filter
def color_prioridad(valor):
    return COLOR_PRIORIDAD.get(_clave(valor), "bg-slate-300")


@register.filter
def badge_estado_tarea(valor):
    return BADGE_ESTADO_TAREA.get(_clave(valor), "bg-slate-100 text-slate-700")


# --- Riesgo ---
#
# La escala va de frio a caliente para que el nivel se lea sin tener que
# recordar que significa cada palabra.

BADGE_RIESGO = {
    "low": "bg-emerald-100 text-emerald-800",
    "medium": "bg-amber-100 text-amber-800",
    "high": "bg-orange-100 text-orange-900",
    "veryhigh": "bg-rose-100 text-rose-800",
    "critical": "bg-rose-600 text-white",
}

COLOR_RIESGO = {
    "low": "bg-emerald-600",
    "medium": "bg-amber-500",
    "high": "bg-orange-500",
    "veryhigh": "bg-rose-500",
    "critical": "bg-rose-700",
}


@register.filter
def badge_riesgo(valor):
    return BADGE_RIESGO.get(_clave(valor), "bg-slate-100 text-slate-700")


@register.filter
def color_riesgo(valor):
    return COLOR_RIESGO.get(_clave(valor), "bg-slate-400")
