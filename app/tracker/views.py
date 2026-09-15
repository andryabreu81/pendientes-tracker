import os
import tempfile
from collections import Counter, defaultdict

from django.contrib import messages
from django.contrib.auth.decorators import login_required
from django.db import transaction
from django.db.models import Avg, Count, Max, Q
from django.http import HttpResponse, JsonResponse
from django.shortcuts import get_object_or_404, redirect, render
from django.utils import timezone
from django.utils.text import slugify
from django.views.decorators.http import require_POST

from . import riesgo
from .calendario import nombre_archivo_ics, reunion_a_ics
from .forms import (
    ImportForm,
    RecordatorioForm,
    ReunionForm,
    TareaForm,
    TicketForm,
)
from .exportador import exportar_tareas, exportar_tickets
from .importer import (
    aplicar_cambios,
    aplicar_cambios_tarea,
    es_archivo_de_tareas,
    importar,
    importar_tareas,
)
from .models import (
    ImportBatch,
    Recordatorio,
    Reunion,
    Tarea,
    Ticket,
    TicketHistory,
)


def _ultimo_movimiento():
    """
    Marca de tiempo del registro mas nuevo de la base.

    Es la clave del refresco: el navegador guarda este valor y pregunta
    cada tanto si cambio. Si cambio, hay datos nuevos cargados por otra
    estacion de trabajo y el dashboard se actualiza.
    """
    ts = Ticket.objects.aggregate(m=Max("actualizado_en"))["m"]
    return ts.isoformat() if ts else ""


def _estatus_disponibles():
    """
    Estatus presentes en la base, sin repetir, con su conteo.

    Ojo con el .order_by() vacio: el modelo define Meta.ordering, y Django
    agrega esas columnas al SELECT para poder ordenar. Eso rompe el DISTINCT
    porque el motor compara la fila entera, no solo el estatus:

        SELECT DISTINCT estatus, categoria, codigo ...   <- codigo es unico,
                                                            ninguna fila se
                                                            descarta

    Con order_by() se limpia el orden heredado y el DISTINCT vuelve a
    aplicarse sobre la unica columna que interesa.
    """
    conteos = dict(
        Ticket.objects.order_by()
        .values_list("estatus")
        .annotate(n=Count("id"))
        .values_list("estatus", "n")
    )

    # Orden por flujo de trabajo (Desarrollo -> Calidad -> Produccion),
    # no alfabetico: asi el desplegable sigue el avance real del trabajo.
    orden = {nombre: i for i, (nombre, _) in enumerate(Ticket.ESTATUS)}

    return [
        {"valor": nombre, "total": total}
        for nombre, total in sorted(
            conteos.items(),
            # Un estatus no catalogado va al final, ordenado por nombre.
            key=lambda par: (orden.get(par[0], len(orden)), par[0]),
        )
    ]


def _responsables_disponibles():
    """
    Personas que aparecen como asignadas o responsables, sin repetir.

    Un registro puede traer varios responsables en un solo campo
    ("HA - MLM - Banco"), asi que hay que separarlos. Se juntan los de
    registros y los de tareas: quien filtra busca a la persona, no le
    importa en cual de las dos tablas esta.
    """
    nombres = set()

    for asignado in Ticket.objects.order_by().values_list("asignado", flat=True):
        nombres.update(n.strip() for n in (asignado or "").split("-") if n.strip())

    return sorted(nombres, key=str.casefold)


def _filtros_de(request):
    """Lee los cinco filtros de la barra, tal como los mandó la pantalla."""
    return {
        "categoria": request.GET.get("categoria", ""),
        "estatus": request.GET.get("estatus", ""),
        "responsable": request.GET.get("responsable", ""),
        "riesgo": request.GET.get("riesgo", ""),
        "q": request.GET.get("q", "").strip(),
    }


def _tickets_filtrados(filtros):
    """
    Los registros que la tabla está mostrando.

    Fuente unica de verdad del filtrado: el dashboard y las tres
    exportaciones llaman a esta misma funcion. Asi "exportar lo que veo"
    deja de ser una promesa y pasa a estar garantizado por construccion:
    si el filtrado cambia, cambia para los tres a la vez.

    Devuelve un queryset, o una lista cuando se filtra por riesgo. Los
    consumidores toleran las dos cosas: se recorren, se cuentan, y el
    filtro ticket__in de las tareas acepta ambas.
    """
    qs = Ticket.objects.all()

    if filtros["categoria"]:
        qs = qs.filter(categoria=filtros["categoria"])
    if filtros["estatus"]:
        qs = qs.filter(estatus=filtros["estatus"])
    if filtros["q"]:
        qs = qs.filter(nombre__icontains=filtros["q"])
    if filtros["responsable"]:
        # Solo el campo "Asignado a" del registro. Los filtros operan
        # sobre la tabla padre; las tareas salen por arrastre de los
        # registros que quedan, no al reves.
        qs = qs.filter(asignado__icontains=filtros["responsable"])

    # El riesgo se calcula al vuelo (depende de la fecha de hoy), asi que
    # no hay columna contra la cual filtrar en SQL. El prefetch evita que
    # calcular el riesgo dispare una consulta de tareas por cada registro.
    qs = qs.order_by("categoria", "codigo").prefetch_related("tareas")

    if filtros["riesgo"]:
        return [t for t in qs if t.risk_level == filtros["riesgo"]]

    return qs


def _metricas():
    """Todo lo que alimenta los graficos, calculado en la base de datos."""
    qs = Ticket.objects.all()
    total = qs.count()

    if total == 0:
        return {
            "total": 0,
            "avance_general": 0,
            "por_categoria": [],
            "por_estatus": [],
            "por_asignado": [],
            "por_riesgo": [],
            "en_riesgo": 0,
            "vencidos": 0,
            "incompletos": 0,
            "sin_asignar": 0,
        }

    por_categoria = [
        {
            "clave": row["categoria"],
            "label": dict(Ticket.CATEGORIAS).get(row["categoria"], row["categoria"]),
            "total": row["total"],
            "avance": round(row["avance"] or 0),
        }
        for row in qs.values("categoria")
        .annotate(total=Count("id"), avance=Avg("avance"))
        .order_by("categoria")
    ]

    por_estatus = [
        {"label": row["estatus"], "total": row["total"]}
        for row in qs.values("estatus").annotate(total=Count("id")).order_by("-total")
    ]

    # Carga de trabajo por persona. Un ticket puede venir con varios
    # responsables separados por guion ("HA - MLM - Banco"): se cuenta
    # para cada uno, porque la carga es compartida.
    carga = defaultdict(lambda: {"total": 0, "suma": 0})
    for asignado, avance in qs.values_list("asignado", "avance"):
        nombres = [n.strip() for n in (asignado or "").split("-") if n.strip()]
        for nombre in nombres or ["Sin asignar"]:
            carga[nombre]["total"] += 1
            carga[nombre]["suma"] += avance

    por_asignado = sorted(
        (
            {
                "label": nombre,
                "total": d["total"],
                "avance": round(d["suma"] / d["total"]),
            }
            for nombre, d in carga.items()
        ),
        key=lambda x: (-x["total"], x["label"]),
    )

    incompletos = sum(
        1
        for f, s in qs.values_list("fecha_solicitada", "funcional_solicitante")
        if not f or not s
    )

    # El riesgo no es una columna, hay que recorrer. El prefetch evita la
    # consulta por registro que dispararia calcular las tareas de cada uno.
    conteo_riesgo = Counter()
    vencidos = 0
    for ticket in qs.prefetch_related("tareas"):
        conteo_riesgo[ticket.risk_level] += 1
        if ticket.vencido:
            vencidos += 1

    por_riesgo = [
        {
            "clave": nivel,
            "label": etiqueta,
            "total": conteo_riesgo.get(nivel, 0),
        }
        for nivel, etiqueta in riesgo.NIVELES
    ]

    # Los tres niveles superiores son los que exigen atención.
    en_riesgo = sum(
        conteo_riesgo.get(n, 0)
        for n in (riesgo.HIGH, riesgo.VERYHIGH, riesgo.CRITICAL)
    )

    return {
        "total": total,
        "avance_general": round(qs.aggregate(a=Avg("avance"))["a"] or 0),
        "por_categoria": por_categoria,
        "por_estatus": por_estatus,
        "por_asignado": por_asignado,
        "por_riesgo": por_riesgo,
        "en_riesgo": en_riesgo,
        "vencidos": vencidos,
        "incompletos": incompletos,
        "sin_asignar": qs.filter(asignado="").count(),
    }


@login_required
def dashboard(request):
    """Pantalla principal: metricas, graficos y tabla resumen."""
    filtros = _filtros_de(request)
    tickets = _tickets_filtrados(filtros)

    contexto = {
        "metricas": _metricas(),
        "tickets": tickets,
        "categorias": Ticket.CATEGORIAS,
        "estatus_lista": _estatus_disponibles(),
        "responsables": _responsables_disponibles(),
        "niveles_riesgo": riesgo.NIVELES,
        "filtros": filtros,
        "ultimo_movimiento": _ultimo_movimiento(),
        "ultima_carga": ImportBatch.objects.first(),
        "recordatorios": _recordatorios_activos(),
        "reuniones": _reuniones_proximas(),
        "form": TicketForm(),
        "import_form": ImportForm(),
    }
    return render(request, "tracker/dashboard.html", contexto)


def _recordatorios_activos():
    """
    Recordatorios cuyo día ya llegó y que nadie marcó como atendidos.

    Se muestran a todo el mundo por igual: "asignado" y "responsable" son
    texto libre, el sistema no sabe qué usuario es "HA", y no hay forma de
    dirigir el aviso a una persona concreta sin vincular antes esos
    nombres con cuentas reales.
    """
    return (
        Recordatorio.objects.filter(visto=False, fecha__lte=timezone.localdate())
        .select_related("ticket", "tarea", "tarea__ticket")
        .order_by("fecha", "-creado_en")
    )


def _reuniones_proximas(limite=5):
    """Las próximas reuniones pautadas, de hoy en adelante."""
    return (
        Reunion.objects.filter(fecha_hora__gte=timezone.now())
        .select_related("ticket", "tarea", "tarea__ticket")
        .order_by("fecha_hora")[:limite]
    )


@login_required
def ticket_detalle(request, pk):
    """
    Contenido del panel "Ver detalle". Se pide por AJAX y se inyecta
    en el modal, asi la tabla no carga las descripciones largas de entrada.
    """
    ticket = get_object_or_404(Ticket, pk=pk)

    # La agenda incluye lo colgado del registro y lo colgado de sus
    # tareas: quien mira el detalle quiere ver todo lo del proyecto.
    del_registro = Q(ticket=ticket) | Q(tarea__ticket=ticket)

    return render(
        request,
        "tracker/_detalle.html",
        {
            "t": ticket,
            "historial": ticket.historial.select_related("usuario")[:30],
            "agenda_reuniones": Reunion.objects.filter(del_registro)
            .select_related("tarea")
            .order_by("fecha_hora"),
            "agenda_recordatorios": Recordatorio.objects.filter(del_registro)
            .select_related("tarea")
            .order_by("visto", "fecha"),
        },
    )


@login_required
def ticket_crear(request):
    if request.method != "POST":
        return redirect("dashboard")

    form = TicketForm(request.POST)
    if not form.is_valid():
        messages.error(request, f"Revisá los datos: {form.errors.as_text()}")
        return redirect("dashboard")

    ticket = form.save(commit=False)
    # El formulario de alta no muestra el codigo, asi que en la practica
    # siempre llega vacio y lo genera el sistema. Se respeta si viene
    # cargado para no perder un codigo escrito a proposito.
    ticket.codigo = form.cleaned_data.get("codigo") or Ticket.siguiente_codigo(
        ticket.categoria
    )
    ticket.save()

    from .importer import _registrar_creacion

    _registrar_creacion(ticket, request.user)
    messages.success(request, f"Registro {ticket.codigo} creado.")
    return redirect("dashboard")


@login_required
def ticket_editar(request, pk):
    ticket = get_object_or_404(Ticket, pk=pk)

    if request.method == "GET":
        return render(
            request,
            "tracker/_form.html",
            {"form": TicketForm(instance=ticket), "ticket": ticket},
        )

    form = TicketForm(request.POST, instance=Ticket(pk=ticket.pk))
    if not form.is_valid():
        messages.error(request, f"Revisá los datos: {form.errors.as_text()}")
        return redirect("dashboard")

    datos = dict(form.cleaned_data)
    codigo_anterior = ticket.codigo

    # Codigo vacio en el formulario = "dejalo como esta". Sin esto, el
    # campo en blanco borraria el codigo del registro.
    if not datos.get("codigo"):
        datos.pop("codigo", None)

    renombra = bool(datos.get("codigo")) and datos["codigo"] != codigo_anterior

    # El choque de codigos de tarea se detecta ANTES de escribir nada:
    # dentro de la transaccion seria un IntegrityError y un error 500.
    if renombra:
        conflicto = ticket.tareas_en_conflicto(datos["codigo"])
        if conflicto:
            messages.error(
                request,
                f"No se puede renombrar {codigo_anterior} a {datos['codigo']}: "
                f"la tarea {conflicto} ya existe en otro registro.",
            )
            return redirect("dashboard")

    # Se pasa por aplicar_cambios (no form.save) para que cada campo
    # modificado quede registrado en el historico con su autor.
    with transaction.atomic():
        cambios = aplicar_cambios(ticket, datos, request.user)
        renombradas = (
            ticket.renombrar_tareas_hijas(codigo_anterior) if renombra else 0
        )

    if not cambios:
        messages.success(request, f"{ticket.codigo}: sin cambios.")
        return redirect("dashboard")

    aviso = f"{ticket.codigo}: {cambios} campo(s) actualizado(s)."
    if renombra:
        aviso += (
            f" Se renombró desde {codigo_anterior}"
            f"{f' y {renombradas} tarea(s) con él' if renombradas else ''}. "
            "Los archivos exportados antes de este cambio ya no coinciden: "
            "volvé a exportar antes de reimportar."
        )

    messages.success(request, aviso)
    return redirect("dashboard")


@login_required
@require_POST
def ticket_eliminar(request, pk):
    """Elimina un ticket/registro y todas sus tareas e historial asociados."""
    ticket = get_object_or_404(Ticket, pk=pk)
    codigo = ticket.codigo
    ticket.delete()
    messages.success(request, f"Registro {codigo} eliminado correctamente.")
    return redirect("dashboard")


@login_required
@require_POST
def importar_archivo(request):
    """Carga el .xlsx/.docx semanal y sincroniza los registros."""
    form = ImportForm(request.POST, request.FILES)
    if not form.is_valid():
        messages.error(request, form.errors.get("archivo", ["Archivo inválido."])[0])
        return redirect("dashboard")

    subido = form.cleaned_data["archivo"]
    sufijo = os.path.splitext(subido.name)[1]

    with tempfile.NamedTemporaryFile(delete=False, suffix=sufijo) as tmp:
        for chunk in subido.chunks():
            tmp.write(chunk)
        ruta = tmp.name

    try:
        # El sistema reconoce solo si le subieron el archivo semanal de
        # pendientes o el de tareas exportado. No hace falta que el
        # usuario elija el tipo.
        if es_archivo_de_tareas(ruta):
            batch = importar_tareas(ruta, subido.name, request.user)
            que = "tareas"
        else:
            batch = importar(ruta, subido.name, request.user)
            que = "registros"

        messages.success(
            request,
            f"{subido.name} ({que}): {batch.creados} creados, "
            f"{batch.actualizados} actualizados, {batch.sin_cambios} sin cambios, "
            f"{batch.omitidos} omitidos.",
        )
    except Exception as exc:
        messages.error(request, f"No se pudo procesar el archivo: {exc}")
    finally:
        os.unlink(ruta)

    return redirect("dashboard")


@login_required
def api_ultimo(request):
    """
    Endpoint liviano de refresco. Devuelve solo la marca del ultimo
    movimiento y los totales; el navegador lo consulta cada 15 segundos
    y recarga la pantalla unicamente si detecta datos mas nuevos.
    """
    metricas = _metricas()
    return JsonResponse(
        {
            "ultimo_movimiento": _ultimo_movimiento(),
            "total": metricas["total"],
            "avance_general": metricas["avance_general"],
            "en_riesgo": metricas["en_riesgo"],
        }
    )


@login_required
def api_registros(request):
    """
    Los registros en JSON, con su riesgo calculado.

    Responde a los mismos filtros que la pantalla, reutilizando
    _tickets_filtrados: lo que devuelve el endpoint es exactamente lo que
    muestra la tabla, sin una segunda implementacion que se desincronice.
    """
    filtros = _filtros_de(request)

    registros = [
        {
            "codigo": t.codigo,
            "categoria": t.categoria,
            "tipo": t.get_categoria_display(),
            "nombre": t.nombre,
            "fecha_solicitada": t.fecha_solicitada.isoformat()
            if t.fecha_solicitada
            else None,
            "fecha_fin": t.fecha_fin.isoformat() if t.fecha_fin else None,
            "funcional_solicitante": t.funcional_solicitante,
            "avance": t.avance,
            "asignado": t.asignado,
            "estatus": t.estatus,
            "vencido": t.vencido,
            "dias_atraso": t.dias_atraso,
            "risk_score": t.risk_score,
            "risk_level": t.risk_level,
        }
        for t in _tickets_filtrados(filtros)
    ]

    return JsonResponse(
        {
            "generado_en": timezone.now().isoformat(),
            "total": len(registros),
            "filtros": filtros,
            "registros": registros,
        }
    )


# ---------------------------------------------------------------
# Exportación
# ---------------------------------------------------------------

def _contexto_membrete(request, filtros):
    """
    Lo que el membrete estampa en cada archivo: quién exportó y con qué
    filtros. Va por acá y no dentro del exportador porque el exportador
    no conoce la petición ni tiene por qué conocerla.
    """
    return {
        "usuario": request.user,
        "filtros_args": {
            "filtros": filtros,
            "categorias": Ticket.CATEGORIAS,
            "niveles_riesgo": riesgo.NIVELES,
        },
    }


def _respuesta_excel(contenido, nombre):
    """Devuelve el libro como descarga, con el nombre ya resuelto."""
    respuesta = HttpResponse(
        contenido,
        content_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    respuesta["Content-Disposition"] = f'attachment; filename="{nombre}"'
    return respuesta


def _nombre_archivo(base, filtros):
    """Arma el nombre del archivo con los filtros que se aplicaron."""
    partes = [base]

    if filtros["categoria"]:
        partes.append(slugify(dict(Ticket.CATEGORIAS).get(
            filtros["categoria"], filtros["categoria"])))
    if filtros["estatus"]:
        partes.append(slugify(filtros["estatus"]))
    if filtros["responsable"]:
        partes.append(slugify(filtros["responsable"]))
    if filtros["riesgo"]:
        partes.append(f"riesgo-{slugify(filtros['riesgo'])}")
    if filtros["q"]:
        partes.append(slugify(filtros["q"])[:20])

    return f"{'-'.join(partes)}-{timezone.localdate():%Y-%m-%d}.xlsx"


@login_required
def exportar_registros(request):
    """
    Exporta lo que la tabla está mostrando: mismos filtros, mismos registros.

    El archivo lleva el código en la primera columna, que es lo que permite
    volver a subirlo y que cada fila actualice su propio registro en lugar
    de crear un duplicado.
    """
    filtros = _filtros_de(request)
    tickets = _tickets_filtrados(filtros)

    return _respuesta_excel(
        exportar_tickets(tickets, contexto=_contexto_membrete(request, filtros)),
        _nombre_archivo("registros", filtros),
    )


@login_required
def exportar_todas_las_tareas(request):
    """
    Las tareas de los registros que la tabla está mostrando.

    No filtra las tareas por su cuenta: parte de los registros que ve el
    usuario y baja todas sus tareas. Los filtros operan sobre la tabla
    padre; las tareas salen por arrastre.
    """
    filtros = _filtros_de(request)
    tickets = _tickets_filtrados(filtros)

    tareas = Tarea.objects.filter(ticket__in=tickets).select_related("ticket")

    return _respuesta_excel(
        exportar_tareas(
            tareas.order_by("ticket__codigo", "codigo"),
            contexto=_contexto_membrete(request, filtros),
        ),
        _nombre_archivo("tareas", filtros),
    )


@login_required
def exportar_tareas_de(request, pk):
    """Las tareas de un registro concreto: el 'exportar hijos de un padre'."""
    ticket = get_object_or_404(Ticket, pk=pk)
    tareas = ticket.tareas.select_related("ticket").order_by("codigo")

    nombre = f"tareas-{ticket.codigo}-{timezone.localdate():%Y-%m-%d}.xlsx"
    # Este export no pasa por la barra de filtros: el "filtro" es el
    # registro padre, y asi queda dicho en el membrete.
    contexto = _contexto_membrete(request, {})
    contexto["filtros_args"] = {"filtros": {"q": f"Tareas de {ticket.codigo}"}}

    return _respuesta_excel(
        exportar_tareas(tareas, titulo=f"Tareas de {ticket.codigo}", contexto=contexto),
        nombre,
    )


@login_required
def exportar_presentacion(request):
    """
    Genera y descarga la presentación ejecutiva en formato PowerPoint (.pptx)
    según el período especificado: semanal, mensual, trimestral o anual.
    """
    try:
        from .presentacion import generar_presentacion_pptx
    except ImportError as e:
        messages.error(
            request,
            "La librería 'python-pptx' no está instalada en el entorno actual. "
            "Reconstruí el contenedor con 'docker compose build' o ejecutá 'pip install python-pptx'.",
        )
        return redirect("dashboard")

    periodo = request.GET.get("periodo", "mensual").strip().lower()
    if periodo not in ["semanal", "mensual", "trimestral", "anual"]:
        periodo = "mensual"

    filtros = _filtros_de(request)
    tickets = _tickets_filtrados(filtros)
    metricas = _metricas()

    try:
        contenido_pptx = generar_presentacion_pptx(
            periodo=periodo,
            tickets=tickets,
            metricas=metricas,
        )
    except Exception as e:
        messages.error(request, f"Error al generar la presentación: {e}")
        return redirect("dashboard")

    fecha_str = timezone.localdate().strftime("%Y-%m-%d")
    nombre_archivo = f"Reporte-Ejecutivo-{periodo.capitalize()}-{fecha_str}.pptx"

    response = HttpResponse(
        contenido_pptx,
        content_type="application/vnd.openxmlformats-officedocument.presentationml.presentation",
    )
    response["Content-Disposition"] = f'attachment; filename="{nombre_archivo}"'
    return response


# ---------------------------------------------------------------
# Tareas
# ---------------------------------------------------------------

@login_required
def tarea_crear(request, pk):
    """Alta de una tarea sobre un registro que ya existe."""
    ticket = get_object_or_404(Ticket, pk=pk)

    if request.method == "GET":
        return render(
            request,
            "tracker/_tarea_form.html",
            {"form": TareaForm(), "ticket": ticket},
        )

    form = TareaForm(request.POST)
    if not form.is_valid():
        messages.error(request, f"Revisá los datos: {form.errors.as_text()}")
        return redirect("dashboard")

    tarea = form.save(commit=False)
    tarea.ticket = ticket
    tarea.codigo = Tarea.siguiente_codigo(ticket)
    tarea.save()

    from .importer import _registrar_creacion_tarea

    _registrar_creacion_tarea(tarea, request.user)
    messages.success(request, f"Tarea {tarea.codigo} creada en {ticket.codigo}.")
    return redirect("dashboard")


@login_required
def tarea_editar(request, pk):
    tarea = get_object_or_404(Tarea.objects.select_related("ticket"), pk=pk)

    if request.method == "GET":
        return render(
            request,
            "tracker/_tarea_form.html",
            {"form": TareaForm(instance=tarea), "tarea": tarea, "ticket": tarea.ticket},
        )

    form = TareaForm(request.POST, instance=Tarea(pk=tarea.pk, ticket=tarea.ticket))
    if not form.is_valid():
        messages.error(request, f"Revisá los datos: {form.errors.as_text()}")
        return redirect("dashboard")

    cambios = aplicar_cambios_tarea(tarea, form.cleaned_data, request.user)
    messages.success(
        request,
        f"{tarea.codigo}: {cambios} campo(s) actualizado(s)."
        if cambios
        else f"{tarea.codigo}: sin cambios.",
    )
    return redirect("dashboard")


@login_required
@require_POST
def tarea_eliminar(request, pk):
    """Elimina una tarea subordinada."""
    tarea = get_object_or_404(Tarea.objects.select_related("ticket"), pk=pk)
    ticket_pk = tarea.ticket_id
    codigo = tarea.codigo
    tarea.delete()
    if request.headers.get("X-Requested-With") == "XMLHttpRequest" or request.GET.get("ajax"):
        return JsonResponse({"ok": True, "codigo": codigo, "ticket_pk": ticket_pk})
    messages.success(request, f"Tarea {codigo} eliminada correctamente.")
    return redirect("dashboard")


@login_required
def tareas_de(request, pk):
    """Lista de tareas de un registro. Se pide por AJAX desde el detalle."""
    ticket = get_object_or_404(Ticket, pk=pk)
    return render(
        request,
        "tracker/_tareas.html",
        {
            "t": ticket,
            "tareas": ticket.tareas.all(),
            "resumen": ticket.resumen_tareas,
        },
    )


# ---------------------------------------------------------------
# Recordatorios
# ---------------------------------------------------------------

def _objetivo(request, ticket_pk=None, tarea_pk=None):
    """
    Resuelve sobre qué se está trabajando: un registro o una tarea.

    Recordatorios y reuniones se cuelgan de cualquiera de los dos, con la
    misma convencion de doble clave foranea que ya usa el historial.
    """
    if tarea_pk:
        tarea = get_object_or_404(Tarea.objects.select_related("ticket"), pk=tarea_pk)
        return {"tarea": tarea, "ticket": None}, tarea, tarea.ticket

    ticket = get_object_or_404(Ticket, pk=ticket_pk)
    return {"ticket": ticket, "tarea": None}, ticket, ticket


@login_required
def recordatorio_crear(request, pk, sobre="ticket"):
    """Alta de un recordatorio sobre un registro o una tarea."""
    claves, objeto, ticket = _objetivo(
        request,
        ticket_pk=pk if sobre == "ticket" else None,
        tarea_pk=pk if sobre == "tarea" else None,
    )

    if request.method == "GET":
        return render(
            request,
            "tracker/_recordatorio_form.html",
            {
                "form": RecordatorioForm(initial={"fecha": timezone.localdate()}),
                "objeto": objeto,
                "ticket": ticket,
                "sobre": sobre,
                "pk": pk,
            },
        )

    form = RecordatorioForm(request.POST)
    if not form.is_valid():
        messages.error(request, f"Revisá los datos: {form.errors.as_text()}")
        return redirect("dashboard")

    recordatorio = form.save(commit=False)
    recordatorio.ticket = claves["ticket"]
    recordatorio.tarea = claves["tarea"]
    recordatorio.creado_por = request.user
    recordatorio.save()

    messages.success(
        request, f"Recordatorio creado sobre {objeto.codigo} para el "
        f"{recordatorio.fecha:%d/%m/%Y}."
    )
    return redirect("dashboard")


@login_required
@require_POST
def recordatorio_visto(request, pk):
    """Marca el recordatorio como atendido: deja de aparecer en el panel."""
    recordatorio = get_object_or_404(Recordatorio, pk=pk)
    recordatorio.visto = True
    recordatorio.save(update_fields=["visto", "actualizado_en"])

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "pk": pk})

    messages.success(request, f"Recordatorio «{recordatorio.titulo}» atendido.")
    return redirect("dashboard")


@login_required
@require_POST
def recordatorio_eliminar(request, pk):
    recordatorio = get_object_or_404(Recordatorio, pk=pk)
    titulo = recordatorio.titulo
    recordatorio.delete()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "pk": pk})

    messages.success(request, f"Recordatorio «{titulo}» eliminado.")
    return redirect("dashboard")


# ---------------------------------------------------------------
# Reuniones
# ---------------------------------------------------------------

@login_required
def reunion_crear(request, pk, sobre="ticket"):
    """Pauta una reunión sobre un registro o una tarea."""
    claves, objeto, ticket = _objetivo(
        request,
        ticket_pk=pk if sobre == "ticket" else None,
        tarea_pk=pk if sobre == "tarea" else None,
    )

    if request.method == "GET":
        inicial = {
            "titulo": f"Seguimiento {objeto.codigo}",
            "duracion_minutos": 60,
        }
        return render(
            request,
            "tracker/_reunion_form.html",
            {
                "form": ReunionForm(initial=inicial),
                "objeto": objeto,
                "ticket": ticket,
                "sobre": sobre,
                "pk": pk,
            },
        )

    form = ReunionForm(request.POST)
    if not form.is_valid():
        messages.error(request, f"Revisá los datos: {form.errors.as_text()}")
        return redirect("dashboard")

    reunion = form.save(commit=False)
    reunion.ticket = claves["ticket"]
    reunion.tarea = claves["tarea"]
    reunion.creado_por = request.user
    reunion.save()

    messages.success(
        request,
        f"Reunión pautada sobre {objeto.codigo} para el "
        f"{timezone.localtime(reunion.fecha_hora):%d/%m/%Y %H:%M}. "
        "Descargá el .ics para agregarla a tu calendario.",
    )
    return redirect("dashboard")


@login_required
def reunion_editar(request, pk):
    reunion = get_object_or_404(
        Reunion.objects.select_related("ticket", "tarea", "tarea__ticket"), pk=pk
    )

    if request.method == "GET":
        return render(
            request,
            "tracker/_reunion_form.html",
            {
                "form": ReunionForm(instance=reunion),
                "objeto": reunion.objeto,
                "ticket": reunion.ticket_asociado,
                "reunion": reunion,
            },
        )

    form = ReunionForm(request.POST, instance=reunion)
    if not form.is_valid():
        messages.error(request, f"Revisá los datos: {form.errors.as_text()}")
        return redirect("dashboard")

    form.save()
    messages.success(request, f"Reunión «{reunion.titulo}» actualizada.")
    return redirect("dashboard")


@login_required
@require_POST
def reunion_eliminar(request, pk):
    reunion = get_object_or_404(Reunion, pk=pk)
    titulo = reunion.titulo
    reunion.delete()

    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return JsonResponse({"ok": True, "pk": pk})

    messages.success(request, f"Reunión «{titulo}» eliminada.")
    return redirect("dashboard")


@login_required
def reunion_ics(request, pk):
    """
    Descarga la reunión como archivo .ics.

    Es el formato que entienden Outlook, Google Calendar y Calendar de
    Apple: se abre el archivo y el evento queda agendado.
    """
    reunion = get_object_or_404(
        Reunion.objects.select_related("ticket", "tarea", "tarea__ticket"), pk=pk
    )

    respuesta = HttpResponse(
        reunion_a_ics(reunion), content_type="text/calendar; charset=utf-8"
    )
    respuesta["Content-Disposition"] = (
        f'attachment; filename="{nombre_archivo_ics(reunion)}"'
    )
    return respuesta


@login_required
def reuniones_de(request, pk):
    """Reuniones de un registro. Se pide por AJAX desde el detalle."""
    ticket = get_object_or_404(Ticket, pk=pk)
    return render(
        request,
        "tracker/_reuniones.html",
        {
            "t": ticket,
            "reuniones": Reunion.objects.filter(
                Q(ticket=ticket) | Q(tarea__ticket=ticket)
            ).select_related("tarea").order_by("fecha_hora"),
            "recordatorios": Recordatorio.objects.filter(
                Q(ticket=ticket) | Q(tarea__ticket=ticket)
            ).select_related("tarea").order_by("visto", "fecha"),
        },
    )
