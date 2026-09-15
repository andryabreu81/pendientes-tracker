from django.contrib import admin
from django.contrib.auth import views as auth_views
from django.urls import path

from tracker import views

urlpatterns = [
    path("", views.dashboard, name="dashboard"),
    path("ticket/nuevo/", views.ticket_crear, name="ticket_crear"),
    path("ticket/<int:pk>/", views.ticket_detalle, name="ticket_detalle"),
    path("ticket/<int:pk>/editar/", views.ticket_editar, name="ticket_editar"),
    path("ticket/<int:pk>/eliminar/", views.ticket_eliminar, name="ticket_eliminar"),
    path("importar/", views.importar_archivo, name="importar"),
    path("exportar/registros/", views.exportar_registros, name="exportar_registros"),
    path("exportar/tareas/", views.exportar_todas_las_tareas, name="exportar_tareas"),
    path("exportar/presentacion/", views.exportar_presentacion, name="exportar_presentacion"),
    path("ticket/<int:pk>/tareas/", views.tareas_de, name="tareas_de"),
    path("ticket/<int:pk>/tareas/exportar/", views.exportar_tareas_de, name="exportar_tareas_de"),
    path("ticket/<int:pk>/tarea/nueva/", views.tarea_crear, name="tarea_crear"),
    path("tarea/<int:pk>/editar/", views.tarea_editar, name="tarea_editar"),
    path("tarea/<int:pk>/eliminar/", views.tarea_eliminar, name="tarea_eliminar"),
    # Recordatorios: se cuelgan de un registro o de una tarea.
    path(
        "ticket/<int:pk>/recordatorio/nuevo/",
        views.recordatorio_crear,
        {"sobre": "ticket"},
        name="recordatorio_crear_ticket",
    ),
    path(
        "tarea/<int:pk>/recordatorio/nuevo/",
        views.recordatorio_crear,
        {"sobre": "tarea"},
        name="recordatorio_crear_tarea",
    ),
    path(
        "recordatorio/<int:pk>/visto/",
        views.recordatorio_visto,
        name="recordatorio_visto",
    ),
    path(
        "recordatorio/<int:pk>/eliminar/",
        views.recordatorio_eliminar,
        name="recordatorio_eliminar",
    ),
    # Reuniones.
    path(
        "ticket/<int:pk>/reunion/nueva/",
        views.reunion_crear,
        {"sobre": "ticket"},
        name="reunion_crear_ticket",
    ),
    path(
        "tarea/<int:pk>/reunion/nueva/",
        views.reunion_crear,
        {"sobre": "tarea"},
        name="reunion_crear_tarea",
    ),
    path("reunion/<int:pk>/editar/", views.reunion_editar, name="reunion_editar"),
    path("reunion/<int:pk>/eliminar/", views.reunion_eliminar, name="reunion_eliminar"),
    path("reunion/<int:pk>/ics/", views.reunion_ics, name="reunion_ics"),
    path("ticket/<int:pk>/agenda/", views.reuniones_de, name="reuniones_de"),
    path("api/ultimo/", views.api_ultimo, name="api_ultimo"),
    path("api/registros/", views.api_registros, name="api_registros"),
    path(
        "login/",
        auth_views.LoginView.as_view(template_name="tracker/login.html"),
        name="login",
    ),
    path("logout/", auth_views.LogoutView.as_view(), name="logout"),
    path("admin/", admin.site.urls),
]
