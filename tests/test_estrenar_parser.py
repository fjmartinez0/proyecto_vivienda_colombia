import unittest
from pathlib import Path

from vivienda.sources.estrenar import parse_html

FIXTURE = Path(__file__).parent / "fixtures" / "estrenar_chapinero.html"


class TestParserEstrenar(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.ts = parse_html(FIXTURE.read_text(encoding="utf-8", errors="ignore"))
        cls.por_id = {t.typology_id: t for t in cls.ts}

    def test_cantidad_de_tipologias(self):
        self.assertEqual(len(self.ts), 20)

    def test_campos_de_una_tarjeta(self):
        t = self.por_id["52297"]  # Metro 73
        self.assertEqual(t.proyecto, "Metro 73")
        self.assertEqual(t.constructora, "FORJAR INVERSIONES")
        self.assertEqual((t.sector, t.ciudad), ("Chapinero", "Bogotá"))
        self.assertAlmostEqual(t.area, 30.7)
        self.assertEqual((t.habs, t.banos, t.parq), (1, 1, 1))
        self.assertFalse(t.parq_comunal)
        self.assertEqual(t.precio_desde, 399_147_000)
        self.assertEqual(t.area_tipo, "construida")

    def test_parqueadero_comunal(self):
        t = self.por_id["51772"]  # 67 Estorias
        self.assertTrue(t.parq_comunal)
        self.assertIsNone(t.parq)

    def test_todas_tienen_precio_y_area(self):
        for t in self.ts:
            self.assertTrue(t.precio_desde and t.area, t.typology_id)


if __name__ == "__main__":
    unittest.main()
