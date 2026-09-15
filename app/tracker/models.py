import re

from django.conf import settings
from django.db import models
from django.utils import timezone

from . import riesgo


class Ticket(models.Model):
    """
    Un proyecto, requerimiento o incidencia.

    Los campos salen 1:1 de las 9 columnas del archivo pendientes.xlsx.
    """

    PROYECTO = "proyecto"
    REQUERIMIENTO = "requerimiento"
    INCIDENCIA = "incidencia"

    CATEGORIAS = [
        (PROYECTO, "Proyecto"),
        (REQUERIMIENTO, "Requerimiento"),
        (INCIDENCIA, "Incidencia"),
    ]

    PREFIJOS = {PROYECTO: "PRY", REQUERIMIENTO: "REQ", INCIDENCIA: "INC"}

    # Estatus vistos en el archivo del 28-08-2026.
    ESTATUS = [
        ("Desarrollo", "Desarrollo"),
        ("Calidad", "Calidad"),
        ("Producción", "Producción"),
        ("Producción Controlado", "Producción Controlado"),
    ]

    # Campos cuyo cambio se guarda en el historico.
    # "codigo" esta incluido porque desde ahora se puede editar a mano:
    # renombrar un registro rompe la correspondencia con los Excel ya
    # exportados, asi que tiene que quedar constancia de quien lo hizo.
    CAMPOS_AUDITADOS = [
        "codigo",
        "nombre",
        "fecha_solicitada",
        "fecha_fin",
        "funcional_solicitante",
        "descripcion",
        "avance",
        "asignado",
        "observacion",
        "estatus",
        "categoria",
    ]

    ETIQUETAS = {
        "codigo": "Número de requerimiento",
        "nombre": "Nombre",
        "fecha_solicitada": "Fecha solicitada",
        "fecha_fin": "Fecha final",
        "funcional_solicitante": "Funcional solicitante",
        "descripcion": "Descripción",
        "avance": "Porcentaje de avance",
        "asignado": "Asignado a",
        "observacion": "Observación",
        "estatus": "Estatus",
        "categoria": "Categoría",
    }

    # Formato valido del codigo. Se valida en el formulario para que
    # siguiente_codigo() siga encontrando el correlativo.
    PATRON_CODIGO = re.compile(r"^(PRY|REQ|INC)-(\d{3,})$")

    # "Numero (Id Unico)" del archivo. Viene vacio, lo genera el sistema.
    codigo = models.CharField("Número de requerimiento", max_length=20, unique=True)
    categoria = models.CharField(max_length=20, choices=CATEGORIAS, db_index=True)

    nombre = models.CharField("Nombre", max_length=500)
    fecha_solicitada = models.DateField("Fecha solicitada", null=True, blank=True)
    # Fecha comprometida de cierre. Alimenta el atraso, que es la señal
    # de mayor peso del score de riesgo.
    fecha_fin = models.DateField(
        "Fecha final", null=True, blank=True, db_index=True
    )
    funcional_solicitante = models.CharField(
        "Funcional solicitante", max_length=255, blank=True, default=""
    )
    descripcion = models.TextField("Descripción", blank=True, default="")
    avance = models.PositiveSmallIntegerField("Porcentaje de avance", default=0)
    asignado = models.CharField(
        "Asignado a", max_length=255, blank=True, default="", db_index=True
    )
    observacion = models.TextField("Observación", blank=True, default="")
    estatus = models.CharField(max_length=50, default="Desarrollo", db_index=True)

    creado_en = models.DateTimeField(auto_now_add=True)
    # Clave del refresco automatico: la vista compara este campo
    # para saber si hay algo mas nuevo que lo que ve el navegador.
    actualizado_en = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ["categoria", "codigo"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(avance__gte=0, avance__lte=100),
                name="avance_entre_0_y_100",
            ),
        ]
        indexes = [models.Index(fields=["categoria", "estatus"])]

    def __str__(self):
        return f"{self.codigo} · {self.nombre}"

    @classmethod
    def siguiente_codigo(cls, categoria):
        """
        PRY-001, PRY-002... Ordena por numero, no por texto.

        El correlativo se extrae con expresion regular en Python y no con
        SQL. La version anterior hacia CAST(SUBSTRING(codigo FROM 5) AS
        INTEGER) sobre todo lo que empezara con "PRY-": desde que el
        codigo se puede editar a mano, un valor como "PRY-00A" hacia que
        PostgreSQL abortara la consulta y se caia el alta de registros de
        esa categoria entera. Con regex, lo que no encaja simplemente se
        ignora.
        """
        prefijo = cls.PREFIJOS.get(categoria, "TKT")
        patron = re.compile(rf"^{re.escape(prefijo)}-(\d+)$")

        numeros = [
            int(m.group(1))
            for codigo in cls.objects.filter(
                codigo__startswith=f"{prefijo}-"
            ).values_list("codigo", flat=True)
            if (m := patron.match(codigo))
        ]

        return f"{prefijo}-{max(numeros, default=0) + 1:03d}"

    def tareas_en_conflicto(self, codigo_nuevo):
        """
        Primer codigo de tarea que chocaria al renombrar este registro.

        Renombrar PRY-003 a PRY-007 arrastra PRY-003.T01 -> PRY-007.T01.
        Si ese codigo ya lo tiene la tarea de otro registro, el renombrado
        violaria la unicidad. Se detecta antes de escribir para poder
        avisar con un mensaje claro en lugar de un error 500.
        """
        objetivos = [
            f"{codigo_nuevo}.{t.codigo.split('.', 1)[1]}"
            for t in self.tareas.all()
            if "." in t.codigo
        ]
        if not objetivos:
            return None

        return (
            Tarea.objects.filter(codigo__in=objetivos)
            .exclude(ticket_id=self.pk)
            .values_list("codigo", flat=True)
            .first()
        )

    def renombrar_tareas_hijas(self, codigo_anterior):
        """
        Propaga el cambio de codigo a las tareas.

        Sin esto, un registro renombrado a PRY-007 conservaria tareas
        PRY-003.T01 mientras las nuevas nacerian como PRY-007.T02: el
        mismo padre con dos prefijos distintos.

        Se usa update() y no save() a proposito: solo cambia el codigo, y
        el save() de Tarea reajusta estado y avance entre si, que no es lo
        que corresponde en un renombrado.
        """
        if codigo_anterior == self.codigo:
            return 0

        renombradas = 0
        for tarea in self.tareas.all():
            if not tarea.codigo.startswith(f"{codigo_anterior}."):
                continue
            sufijo = tarea.codigo.split(".", 1)[1]
            Tarea.objects.filter(pk=tarea.pk).update(
                codigo=f"{self.codigo}.{sufijo}"
            )
            renombradas += 1

        return renombradas

    @property
    def incompleto(self):
        """Le faltan los campos que el archivo fuente no trae."""
        return not self.fecha_solicitada or not self.funcional_solicitante

    @property
    def cerrado(self):
        """Avance completo o ya desplegado en producción."""
        return riesgo.esta_cerrado(self)

    @property
    def vencido(self):
        """Pasó la fecha final y el registro sigue abierto."""
        if not self.fecha_fin or self.cerrado:
            return False
        return self.fecha_fin < timezone.localdate()

    @property
    def dias_atraso(self):
        return 0 if self.cerrado else riesgo.dias_atraso(self)

    @property
    def risk_score(self):
        """
        Score de riesgo, 0 a 1000. Ver tracker/riesgo.py.

        No se cachea con cached_property: el score depende de las tareas,
        y despues de crear o editar una tarea en la misma peticion el
        valor viejo quedaria pegado al objeto.
        """
        return riesgo.calcular(self)

    @property
    def risk_level(self):
        """Nivel de riesgo: low, medium, high, veryhigh o critical."""
        return riesgo.nivel_de(self.risk_score)

    @property
    def risk_level_label(self):
        return riesgo.etiqueta_de(self.risk_level)

    @property
    def resumen_tareas(self):
        """
        Conteo y avance calculado de las tareas.

        El avance del padre NO se toca: sigue siendo el del archivo
        semanal. Esto se muestra al lado como referencia, para que se
        vea si hay discrepancia entre lo declarado y lo ejecutado.
        """
        tareas = list(self.tareas.all())
        if not tareas:
            return None

        listas = sum(1 for t in tareas if t.estado == Tarea.LISTA)
        return {
            "total": len(tareas),
            "listas": listas,
            "abiertas": len(tareas) - listas,
            "vencidas": sum(1 for t in tareas if t.vencida),
            "avance": round(sum(t.avance for t in tareas) / len(tareas)),
        }


class Tarea(models.Model):
    """
    Tarea concreta dentro de un proyecto, requerimiento o incidencia.

    Las tareas se cargan sobre registros que YA existen: el padre nace
    del archivo semanal, las tareas las carga el equipo desde el sistema.
    """

    PENDIENTE = "pendiente"
    EN_CURSO = "en_curso"
    LISTA = "lista"
    BLOQUEADA = "bloqueada"

    ESTADOS = [
        (PENDIENTE, "Pendiente"),
        (EN_CURSO, "En curso"),
        (LISTA, "Lista"),
        (BLOQUEADA, "Bloqueada"),
    ]

    ALTA = "alta"
    MEDIA = "media"
    BAJA = "baja"

    PRIORIDADES = [
        (ALTA, "Alta"),
        (MEDIA, "Media"),
        (BAJA, "Baja"),
    ]

    CAMPOS_AUDITADOS = [
        "descripcion",
        "responsable",
        "estado",
        "avance",
        "prioridad",
        "fecha_inicio",
        "fecha_limite",
        "observacion",
    ]

    ETIQUETAS = {
        "descripcion": "Descripción",
        "responsable": "Responsable",
        "estado": "Estado",
        "avance": "Avance",
        "prioridad": "Prioridad",
        "fecha_inicio": "Fecha de inicio",
        "fecha_limite": "Fecha límite",
        "observacion": "Observación",
    }

    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="tareas"
    )

    # Correlativo dentro del padre: PRY-003.T01, PRY-003.T02...
    # Es lo que permite reimportar el Excel de tareas sin duplicar.
    codigo = models.CharField(max_length=30, unique=True)

    descripcion = models.CharField("Descripción", max_length=500)
    responsable = models.CharField(
        "Responsable", max_length=255, blank=True, default="", db_index=True
    )
    estado = models.CharField(
        max_length=20, choices=ESTADOS, default=PENDIENTE, db_index=True
    )
    avance = models.PositiveSmallIntegerField("Avance", default=0)
    prioridad = models.CharField(
        max_length=10, choices=PRIORIDADES, default=MEDIA, db_index=True
    )
    fecha_inicio = models.DateField("Fecha de inicio", null=True, blank=True)
    fecha_limite = models.DateField("Fecha límite", null=True, blank=True)
    observacion = models.TextField("Observación", blank=True, default="")

    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True, db_index=True)

    class Meta:
        ordering = ["ticket", "codigo"]
        constraints = [
            models.CheckConstraint(
                condition=models.Q(avance__gte=0, avance__lte=100),
                name="tarea_avance_entre_0_y_100",
            ),
        ]
        indexes = [models.Index(fields=["estado", "responsable"])]

    def __str__(self):
        return f"{self.codigo} · {self.descripcion[:50]}"

    def save(self, *args, **kwargs):
        """
        Mantiene estado y avance coherentes entre si.

        Sin esto alguien marca la tarea como Lista pero deja el avance
        en 40, y los dos datos se contradicen en la misma fila.
        """
        if self.estado == self.LISTA:
            self.avance = 100
        elif self.avance == 100 and self.estado != self.LISTA:
            self.estado = self.LISTA
        elif self.estado == self.PENDIENTE and self.avance > 0:
            self.estado = self.EN_CURSO
        super().save(*args, **kwargs)

    @classmethod
    def siguiente_codigo(cls, ticket):
        """
        PRY-003.T01, PRY-003.T02... correlativo dentro del padre.

        Igual que en Ticket: el numero se extrae con regex y se toma el
        maximo, en lugar de confiar en el orden alfabetico del codigo.
        Ordenando como texto, ".T9" quedaba despues de ".T10" y el
        correlativo se repetia apenas el registro pasaba de nueve tareas.
        """
        patron = re.compile(r"\.T(\d+)$")

        numeros = [
            int(m.group(1))
            for codigo in cls.objects.filter(ticket=ticket).values_list(
                "codigo", flat=True
            )
            if (m := patron.search(codigo))
        ]

        return f"{ticket.codigo}.T{max(numeros, default=0) + 1:02d}"

    @property
    def vencida(self):
        """Pasó la fecha límite y la tarea sigue abierta."""
        if not self.fecha_limite or self.estado == self.LISTA:
            return False
        return self.fecha_limite < timezone.localdate()


class TicketHistory(models.Model):
    """
    Auditoria por campo: una fila por cada campo que cambio.
    Append-only, nunca se edita ni se borra.
    """

    CREACION = "creacion"
    EDICION = "edicion"
    IMPORTACION = "importacion"

    ORIGENES = [
        (CREACION, "Creación"),
        (EDICION, "Edición"),
        (IMPORTACION, "Importación"),
    ]

    # Una de las dos apunta a algo; la otra queda en null. Una sola
    # tabla audita tanto los registros padre como sus tareas.
    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="historial",
        null=True, blank=True,
    )
    tarea = models.ForeignKey(
        "Tarea", on_delete=models.CASCADE, related_name="historial",
        null=True, blank=True,
    )
    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    campo = models.CharField(max_length=50)
    valor_anterior = models.TextField(blank=True, default="")
    valor_nuevo = models.TextField(blank=True, default="")
    origen = models.CharField(max_length=20, choices=ORIGENES, default=EDICION)
    archivo = models.CharField(max_length=255, blank=True, default="")
    creado_en = models.DateTimeField(auto_now_add=True, db_index=True)

    class Meta:
        ordering = ["-creado_en"]
        verbose_name_plural = "Ticket histories"

    def __str__(self):
        # Una de las dos FK esta en null: en el historial de una tarea,
        # self.ticket no existe. Antes se leia self.ticket.codigo directo
        # y reventaba con AttributeError apenas Django pedia el texto del
        # objeto (confirmacion de borrado en el admin, por ejemplo).
        objeto = self.tarea or self.ticket
        return f"{objeto.codigo if objeto else 'sin registro'} · {self.campo}"

    @property
    def campo_label(self):
        if self.tarea_id:
            return Tarea.ETIQUETAS.get(self.campo, self.campo)
        return Ticket.ETIQUETAS.get(self.campo, self.campo)

    @property
    def autor(self):
        if self.usuario:
            return self.usuario.get_full_name() or self.usuario.username
        return "Importación automática" if self.origen == self.IMPORTACION else "Sistema"


class ImportBatch(models.Model):
    """Registro de cada archivo cargado: que entro, cuando y con que resultado."""

    usuario = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    archivo = models.CharField(max_length=255)
    # Detecta que suban dos veces el mismo archivo sin cambios.
    hash = models.CharField(max_length=64, db_index=True)

    filas_leidas = models.PositiveIntegerField(default=0)
    creados = models.PositiveIntegerField(default=0)
    actualizados = models.PositiveIntegerField(default=0)
    sin_cambios = models.PositiveIntegerField(default=0)
    omitidos = models.PositiveIntegerField(default=0)

    detalle = models.JSONField(null=True, blank=True)
    creado_en = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["-creado_en"]
        verbose_name_plural = "Import batches"

    def __str__(self):
        return f"{self.archivo} · {self.creado_en:%d/%m/%Y %H:%M}"


class Recordatorio(models.Model):
    """
    Alerta de seguimiento sobre un registro o una tarea.

    Es un modelo aparte y no un par de campos sueltos en Ticket/Tarea por
    dos razones: un mismo trabajo puede necesitar varios avisos en fechas
    distintas, y los recordatorios cambian de estado seguido (visto / no
    visto), lo que llenaria el historial de auditoria de ruido si viviera
    dentro de los campos auditados.

    El aviso es en pantalla, para todos por igual: hoy "asignado" y
    "responsable" son texto libre ("HA - MLM - Banco") y el sistema no
    tiene forma de saber que usuario es cada uno. Dirigir un recordatorio
    a una persona concreta requiere primero vincular esos nombres con
    usuarios reales.
    """

    # Misma convencion que TicketHistory: una de las dos apunta, la otra
    # queda en null.
    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="recordatorios",
        null=True, blank=True,
    )
    tarea = models.ForeignKey(
        Tarea, on_delete=models.CASCADE, related_name="recordatorios",
        null=True, blank=True,
    )

    titulo = models.CharField("Título", max_length=200)
    nota = models.TextField("Nota", blank=True, default="")
    # Dia a partir del cual el recordatorio aparece en el tablero.
    fecha = models.DateField("Avisar el día", db_index=True)
    visto = models.BooleanField("Atendido", default=False, db_index=True)

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fecha", "-creado_en"]
        indexes = [models.Index(fields=["visto", "fecha"])]
        verbose_name = "Recordatorio"
        verbose_name_plural = "Recordatorios"

    def __str__(self):
        return f"{self.titulo} · {self.fecha:%d/%m/%Y}"

    @property
    def objeto(self):
        """El registro o la tarea sobre la que avisa."""
        return self.tarea or self.ticket

    @property
    def ticket_asociado(self):
        """El registro padre, se haya colgado del ticket o de una tarea."""
        return self.tarea.ticket if self.tarea_id else self.ticket

    @property
    def vencido(self):
        """Ya pasó el día del aviso y nadie lo atendió."""
        return not self.visto and self.fecha < timezone.localdate()

    @property
    def activo(self):
        """Llegó el día del aviso (o ya pasó) y sigue sin atenderse."""
        return not self.visto and self.fecha <= timezone.localdate()


class Reunion(models.Model):
    """
    Reunión pautada sobre un registro o una tarea.

    El sistema guarda la cita y genera un archivo .ics descargable, que es
    el formato que entienden Outlook, Google Calendar y Calendar de Apple.
    No crea el evento en el calendario ajeno ni envia invitaciones: eso
    exigiria OAuth contra el tenant corporativo, credenciales y manejo de
    tokens, que es un proyecto en si mismo.
    """

    ticket = models.ForeignKey(
        Ticket, on_delete=models.CASCADE, related_name="reuniones",
        null=True, blank=True,
    )
    tarea = models.ForeignKey(
        Tarea, on_delete=models.CASCADE, related_name="reuniones",
        null=True, blank=True,
    )

    titulo = models.CharField("Título", max_length=200)
    fecha_hora = models.DateTimeField("Fecha y hora", db_index=True)
    duracion_minutos = models.PositiveSmallIntegerField("Duración (minutos)", default=60)
    lugar = models.CharField(
        "Lugar", max_length=255, blank=True, default="",
        help_text="Sala física, o vacío si es virtual",
    )
    enlace = models.URLField(
        "Enlace", blank=True, default="",
        help_text="Teams, Meet, Zoom…",
    )
    participantes = models.TextField(
        "Participantes", blank=True, default="",
        help_text="Un nombre o correo por línea",
    )
    notas = models.TextField("Agenda o notas", blank=True, default="")

    creado_por = models.ForeignKey(
        settings.AUTH_USER_MODEL, on_delete=models.SET_NULL, null=True, blank=True
    )
    creado_en = models.DateTimeField(auto_now_add=True)
    actualizado_en = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["fecha_hora"]
        verbose_name = "Reunión"
        verbose_name_plural = "Reuniones"

    def __str__(self):
        return f"{self.titulo} · {self.fecha_hora:%d/%m/%Y %H:%M}"

    @property
    def objeto(self):
        return self.tarea or self.ticket

    @property
    def ticket_asociado(self):
        return self.tarea.ticket if self.tarea_id else self.ticket

    @property
    def fin(self):
        from datetime import timedelta

        return self.fecha_hora + timedelta(minutes=self.duracion_minutos)

    @property
    def pasada(self):
        return self.fin < timezone.now()

    @property
    def lista_participantes(self):
        return [p.strip() for p in self.participantes.splitlines() if p.strip()]
