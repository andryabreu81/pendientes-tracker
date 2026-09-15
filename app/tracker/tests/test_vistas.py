"""Edición del código, filtro de riesgo, recordatorios, reuniones y API."""

import json
from datetime import date, timedelta

from django.contrib.auth import get_user_model
from django.test import TestCase
from django.urls import reverse

from tracker.models import Recordatorio, Reunion, Tarea, Ticket


class BaseAutenticada(TestCase):
    def setUp(self):
        self.user = get_user_model().objects.create_user(
            username="tester", password="clave-de-prueba-123"
        )
        self.client.force_login(self.user)

        self.ticket = Ticket.objects.create(
            codigo="PRY-003",
            categoria=Ticket.PROYECTO,
            nombre="Proyecto base",
            avance=30,
            estatus="Desarrollo",
        )

    def datos_edicion(self, **extra):
        datos = {
            "codigo": self.ticket.codigo,
            "nombre": self.ticket.nombre,
            "categoria": self.ticket.categoria,
            "fecha_solicitada": "",
            "fecha_fin": "",
            "funcional_solicitante": "",
            "descripcion": "",
            "avance": self.ticket.avance,
            "asignado": "",
            "observacion": "",
            "estatus": self.ticket.estatus,
        }
        datos.update(extra)
        return datos


class EditarCodigoTest(BaseAutenticada):
    def setUp(self):
        super().setUp()
        self.tarea = Tarea.objects.create(
            ticket=self.ticket, codigo="PRY-003.T01", descripcion="Tarea"
        )

    def test_renombra_y_arrastra_las_tareas(self):
        self.client.post(
            reverse("ticket_editar", args=[self.ticket.pk]),
            self.datos_edicion(codigo="PRY-050"),
        )

        self.ticket.refresh_from_db()
        self.tarea.refresh_from_db()
        self.assertEqual(self.ticket.codigo, "PRY-050")
        self.assertEqual(self.tarea.codigo, "PRY-050.T01")

    def test_queda_registrado_en_el_historial(self):
        self.client.post(
            reverse("ticket_editar", args=[self.ticket.pk]),
            self.datos_edicion(codigo="PRY-050"),
        )

        h = self.ticket.historial.filter(campo="codigo").first()
        self.assertIsNotNone(h)
        self.assertEqual(h.valor_anterior, "PRY-003")
        self.assertEqual(h.valor_nuevo, "PRY-050")
        self.assertEqual(h.usuario, self.user)

    def test_normaliza_a_mayusculas(self):
        """Escribir el código en minúsculas es válido: se normaliza."""
        self.client.post(
            reverse("ticket_editar", args=[self.ticket.pk]),
            self.datos_edicion(codigo="pry-050"),
        )
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.codigo, "PRY-050")

    def test_rechaza_formato_invalido(self):
        for malo in ("PRY-A", "PROYECTO-1", "PRY1", "PRY-01", "PRY 001"):
            with self.subTest(codigo=malo):
                self.client.post(
                    reverse("ticket_editar", args=[self.ticket.pk]),
                    self.datos_edicion(codigo=malo),
                )
                self.ticket.refresh_from_db()
                self.assertEqual(self.ticket.codigo, "PRY-003")

    def test_rechaza_prefijo_que_no_corresponde_al_tipo(self):
        self.client.post(
            reverse("ticket_editar", args=[self.ticket.pk]),
            self.datos_edicion(codigo="REQ-001"),
        )
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.codigo, "PRY-003")

    def test_rechaza_codigo_ya_tomado(self):
        Ticket.objects.create(
            codigo="PRY-009", categoria=Ticket.PROYECTO, nombre="Otro"
        )
        self.client.post(
            reverse("ticket_editar", args=[self.ticket.pk]),
            self.datos_edicion(codigo="PRY-009"),
        )
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.codigo, "PRY-003")

    def test_avisa_del_choque_de_tareas_sin_romper_nada(self):
        """
        El código de registro PRY-050 está libre, pero una tarea de otro
        registro ya ocupa PRY-050.T01. Pasa cuando los códigos de tarea
        entran por importación, donde vienen del archivo y no del sistema.

        Sin la comprobación previa, el renombrado violaría la unicidad de
        Tarea.codigo y saldría un error 500 en lugar de un aviso.
        """
        otro = Ticket.objects.create(
            codigo="PRY-009", categoria=Ticket.PROYECTO, nombre="Otro"
        )
        Tarea.objects.create(ticket=otro, codigo="PRY-050.T01", descripcion="Choca")

        respuesta = self.client.post(
            reverse("ticket_editar", args=[self.ticket.pk]),
            self.datos_edicion(codigo="PRY-050"),
            follow=True,
        )

        self.ticket.refresh_from_db()
        self.tarea.refresh_from_db()
        self.assertEqual(self.ticket.codigo, "PRY-003")
        self.assertEqual(self.tarea.codigo, "PRY-003.T01")
        self.assertContains(respuesta, "PRY-050.T01")

    def test_codigo_vacio_no_borra_el_existente(self):
        self.client.post(
            reverse("ticket_editar", args=[self.ticket.pk]),
            self.datos_edicion(codigo=""),
        )
        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.codigo, "PRY-003")


class FechaFinTest(BaseAutenticada):
    def test_se_guarda_y_se_audita(self):
        self.client.post(
            reverse("ticket_editar", args=[self.ticket.pk]),
            self.datos_edicion(fecha_fin="2026-12-31"),
        )

        self.ticket.refresh_from_db()
        self.assertEqual(self.ticket.fecha_fin, date(2026, 12, 31))
        self.assertTrue(self.ticket.historial.filter(campo="fecha_fin").exists())

    def test_rechaza_fecha_final_anterior_a_la_solicitada(self):
        self.client.post(
            reverse("ticket_editar", args=[self.ticket.pk]),
            self.datos_edicion(
                fecha_solicitada="2026-06-01", fecha_fin="2026-01-01"
            ),
        )
        self.ticket.refresh_from_db()
        self.assertIsNone(self.ticket.fecha_fin)


class FiltroRiesgoTest(BaseAutenticada):
    def test_filtra_y_el_dashboard_responde(self):
        Ticket.objects.create(
            codigo="PRY-004",
            categoria=Ticket.PROYECTO,
            nombre="Muy atrasado",
            avance=10,
            fecha_fin=date.today() - timedelta(days=90),
        )

        respuesta = self.client.get(reverse("dashboard"), {"riesgo": "critical"})
        self.assertEqual(respuesta.status_code, 200)
        self.assertContains(respuesta, "PRY-004")
        self.assertNotContains(respuesta, "PRY-003<")

    def test_exportar_respeta_el_filtro(self):
        respuesta = self.client.get(
            reverse("exportar_registros"), {"riesgo": "critical"}
        )
        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("riesgo-critical", respuesta["Content-Disposition"])


class ApiRegistrosTest(BaseAutenticada):
    def test_devuelve_risk_score_y_risk_level(self):
        respuesta = self.client.get(reverse("api_registros"))
        datos = json.loads(respuesta.content)

        self.assertEqual(datos["total"], 1)
        registro = datos["registros"][0]

        self.assertEqual(registro["codigo"], "PRY-003")
        self.assertIn("risk_score", registro)
        self.assertIn("risk_level", registro)
        self.assertTrue(0 <= registro["risk_score"] <= 1000)
        self.assertIn(
            registro["risk_level"],
            ["low", "medium", "high", "veryhigh", "critical"],
        )

    def test_pide_sesion(self):
        self.client.logout()
        respuesta = self.client.get(reverse("api_registros"))
        self.assertEqual(respuesta.status_code, 302)


class RecordatorioTest(BaseAutenticada):
    def test_alta_sobre_un_registro(self):
        self.client.post(
            reverse("recordatorio_crear_ticket", args=[self.ticket.pk]),
            {"titulo": "Revisar avance", "fecha": date.today(), "nota": "urgente"},
        )

        r = Recordatorio.objects.get()
        self.assertEqual(r.ticket, self.ticket)
        self.assertEqual(r.creado_por, self.user)
        self.assertTrue(r.activo)

    def test_aparece_en_el_panel_del_tablero(self):
        Recordatorio.objects.create(
            ticket=self.ticket, titulo="Revisar avance", fecha=date.today()
        )
        respuesta = self.client.get(reverse("dashboard"))

        self.assertContains(respuesta, "Requieren seguimiento")
        self.assertContains(respuesta, "Revisar avance")

    def test_futuro_no_aparece_todavia(self):
        Recordatorio.objects.create(
            ticket=self.ticket,
            titulo="Dentro de un mes",
            fecha=date.today() + timedelta(days=30),
        )
        respuesta = self.client.get(reverse("dashboard"))
        self.assertNotContains(respuesta, "Dentro de un mes")

    def test_marcar_como_atendido_lo_saca_del_panel(self):
        r = Recordatorio.objects.create(
            ticket=self.ticket, titulo="Revisar", fecha=date.today()
        )
        self.client.post(reverse("recordatorio_visto", args=[r.pk]))

        r.refresh_from_db()
        self.assertTrue(r.visto)
        self.assertFalse(r.activo)
        self.assertNotContains(self.client.get(reverse("dashboard")), "Revisar<")


class ReunionTest(BaseAutenticada):
    def _crear(self, **extra):
        datos = {
            "titulo": "Seguimiento semanal",
            "fecha_hora": "2026-10-15T14:30",
            "duracion_minutos": 45,
            "lugar": "Sala 3",
            "enlace": "",
            "participantes": "ana@empresa.com\nHA",
            "notas": "Revisar hitos",
        }
        datos.update(extra)
        return self.client.post(
            reverse("reunion_crear_ticket", args=[self.ticket.pk]), datos
        )

    def test_alta_sobre_un_registro(self):
        self._crear()

        m = Reunion.objects.get()
        self.assertEqual(m.ticket, self.ticket)
        self.assertEqual(m.duracion_minutos, 45)
        self.assertEqual(m.lista_participantes, ["ana@empresa.com", "HA"])

    def test_descarga_del_ics(self):
        self._crear()
        m = Reunion.objects.get()

        respuesta = self.client.get(reverse("reunion_ics", args=[m.pk]))
        contenido = respuesta.content.decode("utf-8")

        self.assertEqual(respuesta.status_code, 200)
        self.assertIn("text/calendar", respuesta["Content-Type"])
        self.assertIn(".ics", respuesta["Content-Disposition"])

        # Estructura mínima que exige el formato.
        self.assertTrue(contenido.startswith("BEGIN:VCALENDAR"))
        self.assertIn("BEGIN:VEVENT", contenido)
        self.assertIn("END:VCALENDAR", contenido)
        self.assertIn("DTSTART:", contenido)
        self.assertIn("DTEND:", contenido)
        self.assertIn("PRY-003", contenido)
        self.assertIn("mailto:ana@empresa.com", contenido)
        # El RFC exige terminaciones CRLF.
        self.assertIn("\r\n", contenido)

    def test_los_saltos_de_linea_se_escapan_una_sola_vez(self):
        """
        El formato pide "\\n" literal. Armando el texto ya escapado, el
        escapador duplicaba la barra y el calendario mostraba "\\\\n"
        dentro de la descripción de la cita.
        """
        self._crear(notas="Primera línea", enlace="https://meet.example.com/x")
        m = Reunion.objects.get()

        contenido = self.client.get(
            reverse("reunion_ics", args=[m.pk])
        ).content.decode("utf-8")

        descripcion = next(
            l for l in contenido.split("\r\n") if l.startswith("DESCRIPTION:Registro")
        )
        self.assertIn("\\n", descripcion)
        self.assertNotIn("\\\\n", descripcion)
        self.assertIn("Primera línea", descripcion)

    def test_rechaza_duracion_fuera_de_rango(self):
        self._crear(duracion_minutos=5000)
        self.assertEqual(Reunion.objects.count(), 0)

    def test_proximas_aparecen_en_el_tablero(self):
        self._crear()
        respuesta = self.client.get(reverse("dashboard"))
        self.assertContains(respuesta, "Próximas reuniones")
