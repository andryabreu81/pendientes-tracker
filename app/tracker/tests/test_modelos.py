"""Correlativos de código, coherencia de tareas y renombrado en cascada."""

from datetime import date, timedelta

from django.test import TestCase

from tracker.models import Tarea, Ticket, TicketHistory


def crear_ticket(**extra):
    datos = {"categoria": Ticket.PROYECTO, "nombre": "Proyecto de prueba"}
    datos.update(extra)
    datos.setdefault("codigo", Ticket.siguiente_codigo(datos["categoria"]))
    return Ticket.objects.create(**datos)


class SiguienteCodigoTest(TestCase):
    def test_arranca_en_001_por_categoria(self):
        self.assertEqual(Ticket.siguiente_codigo(Ticket.PROYECTO), "PRY-001")
        self.assertEqual(Ticket.siguiente_codigo(Ticket.REQUERIMIENTO), "REQ-001")
        self.assertEqual(Ticket.siguiente_codigo(Ticket.INCIDENCIA), "INC-001")

    def test_ordena_por_numero_y_no_por_texto(self):
        """PRY-010 debe seguir a PRY-009, no quedar antes por orden alfabético."""
        for n in range(1, 11):
            crear_ticket(codigo=f"PRY-{n:03d}", nombre=f"P{n}")

        self.assertEqual(Ticket.siguiente_codigo(Ticket.PROYECTO), "PRY-011")

    def test_ignora_codigos_que_no_siguen_el_patron(self):
        """
        El bug que motivó el blindaje: con el código editable, un valor
        como PRY-00A hacía que PostgreSQL abortara el CAST y se caía el
        alta de toda la categoría.
        """
        crear_ticket(codigo="PRY-001", nombre="Normal")
        crear_ticket(codigo="PRY-00A", nombre="Codigo raro")

        self.assertEqual(Ticket.siguiente_codigo(Ticket.PROYECTO), "PRY-002")

    def test_categorias_no_se_pisan(self):
        crear_ticket(codigo="PRY-005", nombre="P")
        self.assertEqual(Ticket.siguiente_codigo(Ticket.REQUERIMIENTO), "REQ-001")


class SiguienteCodigoTareaTest(TestCase):
    def setUp(self):
        self.ticket = crear_ticket(codigo="PRY-003")

    def test_correlativo_dentro_del_padre(self):
        self.assertEqual(Tarea.siguiente_codigo(self.ticket), "PRY-003.T01")

    def test_pasa_de_nueve_sin_repetir(self):
        """Ordenando como texto, .T9 quedaba después de .T10 y se repetía."""
        for n in range(1, 10):
            Tarea.objects.create(
                ticket=self.ticket, codigo=f"PRY-003.T{n:02d}", descripcion=f"T{n}"
            )

        self.assertEqual(Tarea.siguiente_codigo(self.ticket), "PRY-003.T10")

        Tarea.objects.create(
            ticket=self.ticket, codigo="PRY-003.T10", descripcion="T10"
        )
        self.assertEqual(Tarea.siguiente_codigo(self.ticket), "PRY-003.T11")


class CoherenciaTareaTest(TestCase):
    def setUp(self):
        self.ticket = crear_ticket()

    def _tarea(self, **extra):
        datos = {"ticket": self.ticket, "descripcion": "Hacer algo"}
        datos.update(extra)
        datos.setdefault("codigo", Tarea.siguiente_codigo(self.ticket))
        return Tarea.objects.create(**datos)

    def test_lista_fuerza_avance_100(self):
        t = self._tarea(estado=Tarea.LISTA, avance=40)
        self.assertEqual(t.avance, 100)

    def test_avance_100_fuerza_lista(self):
        t = self._tarea(estado=Tarea.EN_CURSO, avance=100)
        self.assertEqual(t.estado, Tarea.LISTA)

    def test_pendiente_con_avance_pasa_a_en_curso(self):
        t = self._tarea(estado=Tarea.PENDIENTE, avance=30)
        self.assertEqual(t.estado, Tarea.EN_CURSO)

    def test_vencida_solo_si_sigue_abierta(self):
        ayer = date.today() - timedelta(days=1)
        self.assertTrue(self._tarea(fecha_limite=ayer).vencida)
        self.assertFalse(
            self._tarea(fecha_limite=ayer, estado=Tarea.LISTA).vencida
        )


class RenombrarCodigoTest(TestCase):
    def setUp(self):
        self.ticket = crear_ticket(codigo="PRY-003")
        self.tarea = Tarea.objects.create(
            ticket=self.ticket, codigo="PRY-003.T01", descripcion="Una tarea"
        )

    def test_renombra_las_tareas_hijas(self):
        self.ticket.codigo = "PRY-007"
        self.ticket.save()
        renombradas = self.ticket.renombrar_tareas_hijas("PRY-003")

        self.tarea.refresh_from_db()
        self.assertEqual(renombradas, 1)
        self.assertEqual(self.tarea.codigo, "PRY-007.T01")

    def test_detecta_conflicto_antes_de_escribir(self):
        """Renombrar a un código cuyas tareas ya existen debe avisar."""
        otro = crear_ticket(codigo="PRY-009", nombre="Otro")
        Tarea.objects.create(ticket=otro, codigo="PRY-009.T01", descripcion="Choca")

        self.assertEqual(self.ticket.tareas_en_conflicto("PRY-009"), "PRY-009.T01")
        self.assertIsNone(self.ticket.tareas_en_conflicto("PRY-050"))


class HistorialTest(TestCase):
    def test_str_no_revienta_en_historial_de_tarea(self):
        """
        El historial de una tarea deja ticket en null. Antes se leía
        self.ticket.codigo directo y tiraba AttributeError.
        """
        ticket = crear_ticket()
        tarea = Tarea.objects.create(
            ticket=ticket, codigo="PRY-001.T01", descripcion="X"
        )
        h = TicketHistory.objects.create(tarea=tarea, campo="estado", valor_nuevo="lista")

        self.assertIn("PRY-001.T01", str(h))
