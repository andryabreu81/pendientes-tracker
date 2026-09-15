"""Los parseos del archivo real: fracciones, fechas, estatus sucio."""

from datetime import date

from django.test import TestCase

from tracker.importer import parse_avance, parse_estatus, parse_fecha


class ParseAvanceTest(TestCase):
    def test_fraccion_de_excel(self):
        """Excel guarda 95% como 0.95: el símbolo es solo formato."""
        self.assertEqual(parse_avance(0.95), 95)
        self.assertEqual(parse_avance(0.5), 50)

    def test_texto_con_simbolo(self):
        self.assertEqual(parse_avance("95%"), 95)
        self.assertEqual(parse_avance("45 %"), 45)

    def test_entero_suelto(self):
        self.assertEqual(parse_avance(95), 95)

    def test_coma_decimal(self):
        self.assertEqual(parse_avance("0,45"), 45)

    def test_vacio_y_basura_dan_cero(self):
        for valor in (None, "", "n/a", "pendiente"):
            with self.subTest(valor=valor):
                self.assertEqual(parse_avance(valor), 0)

    def test_se_recorta_al_rango(self):
        self.assertEqual(parse_avance(150), 100)
        self.assertEqual(parse_avance(-10), 0)

    def test_el_uno_se_interpreta_como_cien(self):
        """
        Ambigüedad conocida y aceptada: 1 puede ser "1%" o la fracción
        100%. Se resuelve como 100 porque es lo que escribe Excel al
        formatear una celda como porcentaje completo.
        """
        self.assertEqual(parse_avance(1), 100)


class ParseFechaTest(TestCase):
    def test_formatos_aceptados(self):
        casos = [
            ("27/08/2026", date(2026, 8, 27)),
            ("27-08-2026", date(2026, 8, 27)),
            ("2026-08-27", date(2026, 8, 27)),
            ("27/08/26", date(2026, 8, 27)),
        ]
        for texto, esperado in casos:
            with self.subTest(texto=texto):
                self.assertEqual(parse_fecha(texto), esperado)

    def test_objeto_date_pasa_derecho(self):
        self.assertEqual(parse_fecha(date(2026, 8, 27)), date(2026, 8, 27))

    def test_vacio_o_ilegible_da_none(self):
        for valor in (None, "", "sin fecha", "31/31/2026"):
            with self.subTest(valor=valor):
                self.assertIsNone(parse_fecha(valor))


class ParseEstatusTest(TestCase):
    def test_recorta_la_fecha_pegada(self):
        """'Desarrollo 27/8/2026' arma una barra extra en el dashboard."""
        self.assertEqual(parse_estatus("Desarrollo 27/8/2026"), "Desarrollo")

    def test_normaliza_espacios_y_acentos(self):
        self.assertEqual(parse_estatus("Calidad "), "Calidad")
        self.assertEqual(parse_estatus("produccion"), "Producción")

    def test_vacio_cae_en_desarrollo(self):
        self.assertEqual(parse_estatus(None), "Desarrollo")
        self.assertEqual(parse_estatus(""), "Desarrollo")

    def test_estatus_nuevo_se_conserva(self):
        """No se pierde información: un estatus no catalogado entra igual."""
        self.assertEqual(parse_estatus("En pausa"), "En pausa")
