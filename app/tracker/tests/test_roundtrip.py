"""
Ciclo exportar -> reimportar.

Es el flujo que documenta el README: se descarga el Excel, se edita y se
vuelve a subir. Estos tests existen porque ese ciclo estaba roto: el
importador leía solo la primera hoja y no reconocía el encabezado
"Código" que escribe el propio exportador, así que reimportar un archivo
generado por el sistema no actualizaba nada.
"""

import os
import tempfile
from datetime import date

from django.test import TestCase

from tracker.exportador import exportar_tareas, exportar_tickets
from tracker.importer import (
    es_archivo_de_tareas,
    importar,
    importar_tareas,
    leer_filas,
)
from tracker.models import Tarea, Ticket


def a_disco(contenido, sufijo=".xlsx"):
    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=sufijo)
    tmp.write(contenido)
    tmp.close()
    return tmp.name


class RoundTripRegistrosTest(TestCase):
    def setUp(self):
        self.pry = Ticket.objects.create(
            codigo="PRY-001",
            categoria=Ticket.PROYECTO,
            nombre="Master Debit",
            fecha_solicitada=date(2026, 1, 10),
            fecha_fin=date(2026, 12, 31),
            funcional_solicitante="Banca",
            avance=45,
            asignado="HA - MLM",
            estatus="Desarrollo",
        )
        self.req = Ticket.objects.create(
            codigo="REQ-001",
            categoria=Ticket.REQUERIMIENTO,
            nombre="Reporte mensual",
            avance=80,
            estatus="Calidad",
        )
        self.inc = Ticket.objects.create(
            codigo="INC-001",
            categoria=Ticket.INCIDENCIA,
            nombre="Caída del cajero",
            avance=100,
            estatus="Producción",
        )

    def _exportar_y_leer(self):
        ruta = a_disco(exportar_tickets(Ticket.objects.all()))
        try:
            return leer_filas(ruta)
        finally:
            os.unlink(ruta)

    def test_lee_las_tres_hojas(self):
        """Antes solo se leía worksheets[0] y se perdían dos categorías."""
        filas, avisos = self._exportar_y_leer()

        self.assertEqual(len(filas), 3, f"avisos: {avisos}")
        self.assertEqual(
            {f["categoria"] for f in filas},
            {Ticket.PROYECTO, Ticket.REQUERIMIENTO, Ticket.INCIDENCIA},
        )

    def test_reconoce_el_codigo_que_escribe_el_exportador(self):
        filas, _ = self._exportar_y_leer()
        self.assertEqual(
            {f["codigo"] for f in filas}, {"PRY-001", "REQ-001", "INC-001"}
        )

    def test_conserva_la_fecha_final(self):
        filas, _ = self._exportar_y_leer()
        proyecto = next(f for f in filas if f["codigo"] == "PRY-001")

        self.assertEqual(proyecto["fecha_fin"], date(2026, 12, 31))
        self.assertEqual(proyecto["fecha_solicitada"], date(2026, 1, 10))

    def test_conserva_el_avance_pese_al_formato_porcentaje(self):
        """El exportador escribe 45% como 0.45; el importador debe leer 45."""
        filas, _ = self._exportar_y_leer()
        proyecto = next(f for f in filas if f["codigo"] == "PRY-001")

        self.assertEqual(proyecto["avance"], 45)

    def test_reimportar_actualiza_y_no_duplica(self):
        ruta = a_disco(exportar_tickets(Ticket.objects.all()))
        try:
            batch = importar(ruta, "registros.xlsx")
        finally:
            os.unlink(ruta)

        self.assertEqual(Ticket.objects.count(), 3)
        self.assertEqual(batch.creados, 0)
        self.assertEqual(batch.filas_leidas, 3)

    def test_el_codigo_manda_sobre_el_nombre(self):
        """
        Es la razón de ser de la primera columna: si alguien corrige el
        nombre en el Excel, la fila debe actualizar su registro y no
        crear uno nuevo.
        """
        ruta = a_disco(exportar_tickets(Ticket.objects.all()))
        try:
            self.pry.nombre = "Nombre viejo distinto"
            self.pry.save()

            importar(ruta, "registros.xlsx")
        finally:
            os.unlink(ruta)

        self.assertEqual(Ticket.objects.count(), 3)
        self.pry.refresh_from_db()
        self.assertEqual(self.pry.nombre, "Master Debit")


class RoundTripTareasTest(TestCase):
    def setUp(self):
        self.ticket = Ticket.objects.create(
            codigo="PRY-001", categoria=Ticket.PROYECTO, nombre="Proyecto"
        )
        Tarea.objects.create(
            ticket=self.ticket,
            codigo="PRY-001.T01",
            descripcion="Analizar",
            responsable="HA",
            estado=Tarea.EN_CURSO,
            avance=40,
            prioridad=Tarea.ALTA,
            fecha_limite=date(2026, 8, 1),
        )

    def test_se_reconoce_como_archivo_de_tareas(self):
        ruta = a_disco(exportar_tareas(Tarea.objects.all()))
        try:
            self.assertTrue(es_archivo_de_tareas(ruta))
        finally:
            os.unlink(ruta)

    def test_reimportar_no_duplica_ni_pierde_datos(self):
        ruta = a_disco(exportar_tareas(Tarea.objects.all()))
        try:
            batch = importar_tareas(ruta, "tareas.xlsx")
        finally:
            os.unlink(ruta)

        self.assertEqual(Tarea.objects.count(), 1)
        self.assertEqual(batch.creados, 0)

        tarea = Tarea.objects.get()
        self.assertEqual(tarea.avance, 40)
        self.assertEqual(tarea.estado, Tarea.EN_CURSO)
        self.assertEqual(tarea.prioridad, Tarea.ALTA)
        self.assertEqual(tarea.fecha_limite, date(2026, 8, 1))

    def test_el_registro_padre_inexistente_se_omite(self):
        ruta = a_disco(exportar_tareas(Tarea.objects.all()))
        try:
            Tarea.objects.all().delete()
            self.ticket.delete()

            batch = importar_tareas(ruta, "tareas.xlsx")
        finally:
            os.unlink(ruta)

        self.assertEqual(Tarea.objects.count(), 0)
        self.assertEqual(batch.omitidos, 1)
