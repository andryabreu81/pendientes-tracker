"""Escala de riesgo y cálculo del score."""

from datetime import date, timedelta

from django.test import TestCase

from tracker import riesgo
from tracker.models import Tarea, Ticket


class EscalaTest(TestCase):
    """
    Los rangos vienen del pedido del negocio, con los límites cerrados
    porque venían solapados (950 en high y veryhigh; 1000 en veryhigh y
    critical).
    """

    def test_limites_de_cada_nivel(self):
        casos = [
            (0, "low"), (499, "low"),
            (500, "medium"), (799, "medium"),
            (800, "high"), (949, "high"),
            (950, "veryhigh"), (999, "veryhigh"),
            (1000, "critical"),
        ]
        for score, esperado in casos:
            with self.subTest(score=score):
                self.assertEqual(riesgo.nivel_de(score), esperado)

    def test_cada_score_devuelve_un_solo_nivel(self):
        for score in range(0, 1001):
            self.assertIn(riesgo.nivel_de(score), dict(riesgo.NIVELES))


class CalculoTest(TestCase):
    def setUp(self):
        self.hoy = date(2026, 6, 15)

    def _ticket(self, **extra):
        datos = {
            "codigo": extra.pop("codigo", "PRY-001"),
            "categoria": Ticket.PROYECTO,
            "nombre": "Proyecto",
            "asignado": "HA",
            "avance": 50,
            "estatus": "Desarrollo",
        }
        datos.update(extra)
        return Ticket.objects.create(**datos)

    def test_cerrado_no_tiene_riesgo(self):
        """Ya terminado o en producción: no hay riesgo de ejecución."""
        vencido_hace_mucho = self.hoy - timedelta(days=200)

        completo = self._ticket(avance=100, fecha_fin=vencido_hace_mucho)
        self.assertEqual(riesgo.calcular(completo, self.hoy), 0)

        produccion = self._ticket(
            codigo="PRY-002", estatus="Producción", fecha_fin=vencido_hace_mucho
        )
        self.assertEqual(riesgo.calcular(produccion, self.hoy), 0)

    def test_sin_fecha_fin_suma_pero_es_bajo(self):
        t = self._ticket()
        score = riesgo.calcular(t, self.hoy)

        self.assertEqual(score, riesgo.PUNTOS_SIN_FECHA_FIN)
        self.assertEqual(riesgo.nivel_de(score), "low")

    def test_sin_asignar_suma(self):
        t = self._ticket(asignado="", fecha_fin=self.hoy + timedelta(days=30))
        self.assertGreaterEqual(riesgo.calcular(t, self.hoy), riesgo.PUNTOS_SIN_ASIGNAR)

    def test_atraso_escala_por_tramos(self):
        esperados = [(3, 150), (12, 300), (25, 450)]

        for dias, puntos in esperados:
            with self.subTest(dias=dias):
                t = self._ticket(
                    codigo=f"PRY-{dias:03d}",
                    fecha_fin=self.hoy - timedelta(days=dias),
                    avance=80,
                )
                # Sin fecha_solicitada no hay desvío que sumar.
                self.assertEqual(riesgo.calcular(t, self.hoy), puntos)

    def test_critico_es_exactamente_1000(self):
        """Muy atrasado y con poco avance: condición dura, score exacto."""
        t = self._ticket(
            fecha_fin=self.hoy - timedelta(days=45),
            avance=20,
        )
        self.assertEqual(riesgo.calcular(t, self.hoy), 1000)
        self.assertEqual(riesgo.nivel_de(riesgo.calcular(t, self.hoy)), "critical")

    def test_muy_atrasado_pero_avanzado_no_es_critico(self):
        """
        El tramo de 600 puntos tiene que ser alcanzable: si todo atraso
        mayor a 30 días fuera crítico, ese tramo sería código muerto.
        """
        t = self._ticket(
            fecha_fin=self.hoy - timedelta(days=45),
            avance=80,
        )
        score = riesgo.calcular(t, self.hoy)

        self.assertEqual(score, riesgo.PUNTOS_ATRASO_MAXIMO)
        self.assertNotEqual(riesgo.nivel_de(score), "critical")

    def test_nunca_llega_a_1000_sin_la_condicion_dura(self):
        """Sumando señales el tope es 999: critical significa algo concreto."""
        t = self._ticket(
            asignado="",
            avance=60,
            fecha_solicitada=self.hoy - timedelta(days=100),
            fecha_fin=self.hoy - timedelta(days=20),
        )
        for n in range(6):
            Tarea.objects.create(
                ticket=t,
                codigo=f"{t.codigo}.T{n:02d}",
                descripcion=f"T{n}",
                estado=Tarea.BLOQUEADA,
                fecha_limite=self.hoy - timedelta(days=5),
            )

        score = riesgo.calcular(t, self.hoy)
        self.assertLessEqual(score, riesgo.TOPE_NO_CRITICO)
        self.assertNotEqual(riesgo.nivel_de(score), "critical")

    def test_tareas_vencidas_y_bloqueadas_suman_con_tope(self):
        t = self._ticket(fecha_fin=self.hoy + timedelta(days=30))
        base = riesgo.calcular(t, self.hoy)

        for n in range(10):
            Tarea.objects.create(
                ticket=t,
                codigo=f"{t.codigo}.T{n:02d}",
                descripcion=f"T{n}",
                fecha_limite=self.hoy - timedelta(days=1),
            )

        # 10 tareas vencidas, pero el aporte está topeado.
        t.refresh_from_db()
        self.assertEqual(
            riesgo.calcular(t, self.hoy), base + riesgo.TOPE_TAREAS_VENCIDAS
        )


class PropiedadesTest(TestCase):
    def test_risk_score_y_level_coinciden(self):
        t = Ticket.objects.create(
            codigo="PRY-001", categoria=Ticket.PROYECTO, nombre="P"
        )
        self.assertEqual(t.risk_level, riesgo.nivel_de(t.risk_score))
        self.assertIn(t.risk_level, dict(riesgo.NIVELES))

    def test_vencido_y_dias_atraso(self):
        t = Ticket.objects.create(
            codigo="PRY-002",
            categoria=Ticket.PROYECTO,
            nombre="P",
            fecha_fin=date.today() - timedelta(days=3),
        )
        self.assertTrue(t.vencido)
        self.assertEqual(t.dias_atraso, 3)
