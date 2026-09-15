from django.contrib import admin

from .models import (
    ImportBatch,
    Recordatorio,
    Reunion,
    Tarea,
    Ticket,
    TicketHistory,
)


@admin.register(Ticket)
class TicketAdmin(admin.ModelAdmin):
    list_display = (
        "codigo", "nombre", "categoria", "estatus", "avance",
        "asignado", "fecha_fin", "riesgo",
    )
    list_filter = ("categoria", "estatus", "asignado")
    search_fields = ("codigo", "nombre", "descripcion")
    ordering = ("categoria", "codigo")
    readonly_fields = ("creado_en", "actualizado_en")

    @admin.display(description="Riesgo")
    def riesgo(self, obj):
        return f"{obj.risk_score} · {obj.risk_level}"


@admin.register(Tarea)
class TareaAdmin(admin.ModelAdmin):
    list_display = ("codigo", "descripcion", "ticket", "responsable", "estado", "avance", "fecha_limite")
    list_filter = ("estado", "prioridad", "responsable", "ticket__categoria")
    search_fields = ("codigo", "descripcion", "ticket__codigo", "ticket__nombre")
    readonly_fields = ("creado_en", "actualizado_en")
    autocomplete_fields = ("ticket",)


@admin.register(TicketHistory)
class TicketHistoryAdmin(admin.ModelAdmin):
    list_display = ("objeto", "campo", "valor_anterior", "valor_nuevo", "origen", "creado_en")
    list_filter = ("origen", "campo")
    search_fields = ("ticket__codigo", "ticket__nombre", "tarea__codigo")

    @admin.display(description="Registro")
    def objeto(self, obj):
        return obj.tarea or obj.ticket

    # El historico es auditoria: se consulta, no se edita.
    def has_add_permission(self, request):
        return False

    def has_change_permission(self, request, obj=None):
        return False

    def has_delete_permission(self, request, obj=None):
        return False


@admin.register(ImportBatch)
class ImportBatchAdmin(admin.ModelAdmin):
    list_display = ("archivo", "creado_en", "filas_leidas", "creados", "actualizados", "sin_cambios")
    readonly_fields = [f.name for f in ImportBatch._meta.fields]

    def has_add_permission(self, request):
        return False


@admin.register(Recordatorio)
class RecordatorioAdmin(admin.ModelAdmin):
    list_display = ("titulo", "objeto", "fecha", "visto", "creado_por")
    list_filter = ("visto", "fecha")
    search_fields = ("titulo", "nota", "ticket__codigo", "tarea__codigo")
    autocomplete_fields = ("ticket", "tarea")


@admin.register(Reunion)
class ReunionAdmin(admin.ModelAdmin):
    list_display = ("titulo", "objeto", "fecha_hora", "duracion_minutos", "creado_por")
    list_filter = ("fecha_hora",)
    search_fields = ("titulo", "notas", "ticket__codigo", "tarea__codigo")
    autocomplete_fields = ("ticket", "tarea")
