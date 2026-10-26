import re
import unittest
from datetime import date

from vivienda.config import cargar_zonas
from vivienda.geocodificacion import consulta_overpass, extraer_direccion, patron_via, punto_cruce
from vivienda.pipeline import aplicar, geocodificar
from vivienda.sources.estrenar.ficha import entrega_desde_texto
from test_ubicacion import BitacoraMemoria, VerificadorFalso, registro_desde_fixture


class GeocodificadorFalso:
    def __init__(self, resultado):
        self.resultado, self.llamadas = resultado, []

    def cruce(self, direccion, ciudad):
        self.llamadas.append(direccion)
        return self.resultado


class TestTexto(unittest.TestCase):
    def test_extraer_direccion(self):
        self.assertEqual(extraer_direccion("Sala de ventas: Cl. 105 No. 23 - 42, Bogotá"), "Cl 105 # 23-42")
        self.assertEqual(extraer_direccion("ubicado en Carrera 68A # 105-73"), "Carrera 68A # 105-73")
        self.assertIsNone(extraer_direccion("junto al Teatro Astor Plaza"))

    def test_entrega(self):
        self.assertEqual(entrega_desde_texto("Entrega aproximada 1T - 2029"), "2029-03")
        self.assertEqual(entrega_desde_texto("4T-2027"), "2027-12")
        self.assertIsNone(entrega_desde_texto("sin fecha"))


class TestFormatos(unittest.TestCase):
    def test_vias_para_cruce(self):
        from vivienda.geocodificacion import vias_para_cruce
        casos = {
            "Calle 73 #14-48": ["Calle 73", "Carrera 14"],
            "Carrera 53 con Calle 100": ["Carrera 53", "Calle 100"],
            "Av. Cra 68 con Calle 95": ["Carrera 68", "Calle 95"],
            "Av. Circunvalar con Calle 60 Bis": ["Circunvalar", "Calle 60"],
            "Carrera 68 A # 105-73": ["Carrera 68A", "Calle 105"],
        }
        for d, esperado in casos.items():
            self.assertEqual([e for _, e in vias_para_cruce(d)], esperado, d)
        self.assertIsNone(vias_para_cruce("cerca de la Calle 72"))

    def test_extraer_cruce_de_texto(self):
        self.assertEqual(extraer_direccion("en la intersección de Carrera 53 con Calle 100, Pasadena"),
                         "Carrera 53 con Calle 100")


class TestFichaReal(unittest.TestCase):
    """Fichas reales de Estrenar Vivienda (guardadas el 2026-10-25)."""

    def _texto(self, nombre):
        from pathlib import Path
        from bs4 import BeautifulSoup
        html = (Path(__file__).parent / "fixtures" / nombre).read_text(encoding="utf-8", errors="ignore")
        return BeautifulSoup(html, "lxml").get_text(" ")

    def test_categorias(self):
        from vivienda.sources.estrenar.ficha import categorias_desde_texto
        self.assertEqual(categorias_desde_texto(self._texto("estrenar_ficha_metro73.html")), ["Renta Corta", "CoWorking"])
        self.assertEqual(categorias_desde_texto(self._texto("estrenar_ficha_zento.html")), ["CoWorking", "Pet Friendly"])

    def test_direccion_por_cruce(self):
        self.assertEqual(extraer_direccion(self._texto("estrenar_ficha_zento.html")), "Carrera 53 con Calle 100")


class TestCruce(unittest.TestCase):
    def test_patron_via(self):
        p = re.compile(patron_via("carrera", "68a"), re.I)
        for nombre in ("Carrera 68A", "Carrera 68 A", "Avenida Carrera 68A", "Carrera 68A Bis"):
            self.assertTrue(p.match(nombre), nombre)
        for nombre in ("Carrera 68", "Carrera 168A", "Calle 68A", "Carrera 68A Sur"):
            self.assertFalse(p.match(nombre), nombre)

    def test_consulta(self):
        q = consulta_overpass(["^Calle 105$"], (4.45, 4.85, -74.25, -73.98))
        self.assertIn('(4.45,-74.25,4.85,-73.98)', q)
        self.assertIn("out geom", q)

    def test_punto_cruce(self):
        calle = [[(4.6950, -74.0600), (4.6950, -74.0550), (4.6950, -74.0500)]]
        carrera = [[(4.6900, -74.0550), (4.6950, -74.0550), (4.7000, -74.0550)]]
        lat, lng, sep = punto_cruce(calle, carrera)
        self.assertAlmostEqual(lat, 4.6950, places=4)
        self.assertAlmostEqual(lng, -74.0550, places=4)
        self.assertLess(sep, 1)
        lejos = [[(4.7200, -74.0300)]]
        self.assertIsNone(punto_cruce(calle, lejos))


class TestPasoGeocodificar(unittest.TestCase):
    def setUp(self):
        self.reg, self.prys = registro_desde_fixture()
        self.p = next(p for p in self.prys.values() if p["nombre"] == "Metro 73")
        self.zonas = cargar_zonas()

    def _correr(self, geocod):
        res = geocodificar.ResumenGeo()
        geocodificar.geocodificar(self.prys, geocod, self.zonas, BitacoraMemoria(), date(2026, 10, 26), res)
        return res

    def test_agregador_da_baja_y_asigna_zona(self):
        self.p["direccion_candidata"] = {"direccion": "Calle 73 # 13-20", "fuente": self.p["url"], "origen": "agregador"}
        res = self._correr(GeocodificadorFalso((4.6650, -74.0560, "cruce simulado")))
        self.assertEqual(res.ubicados, [self.p["id"]])
        self.assertEqual(self.p["ubicacion"]["precision"], "baja")
        self.assertEqual(self.p["zona"], "lag")

    def test_oficial_mejora_una_ubicacion_baja(self):
        self.p["ubicacion"] = {"lat": 4.0, "lng": -74.0, "precision": "baja"}
        self.p["direccion_candidata"] = {"direccion": "Calle 73 # 13-20", "fuente": "https://forjar.co", "origen": "oficial"}
        self._correr(GeocodificadorFalso((4.6585, -74.0615, "cruce simulado")))
        self.assertEqual(self.p["ubicacion"]["precision"], "media")

    def test_no_toca_ubicacion_media(self):
        self.p["ubicacion"] = {"lat": 4.6585, "lng": -74.0615, "precision": "media"}
        self.p["direccion_candidata"] = {"direccion": "Calle 73 # 13-20", "fuente": "https://x.co", "origen": "oficial"}
        g = GeocodificadorFalso((4.7, -74.0, "x"))
        self._correr(g)
        self.assertEqual(g.llamadas, [])

    def test_aplicar_guarda_direccion_de_agregador(self):
        item = {"id": self.p["id"], "lat": None, "lng": None, "direccion_agregador": "Calle 73 # 14-48",
                "direccion_agregador_fuente": "https://www.ciencuadras.com/x"}
        aplicar.aplicar({"proyectos": [item]}, self.prys, self.zonas, VerificadorFalso(), BitacoraMemoria(), date(2026, 10, 26))
        self.assertEqual(self.p["direccion_candidata"]["origen"], "agregador")
        # una oficial posterior la reemplaza; una de agregador no reemplaza a una oficial
        item2 = {"id": self.p["id"], "lat": None, "lng": None, "direccion": "Calle 73 # 14-50",
                 "direccion_fuente": "https://forjar.co/metro73"}
        aplicar.aplicar({"proyectos": [item2]}, self.prys, self.zonas, VerificadorFalso(evidencia="ok"), BitacoraMemoria(), date(2026, 10, 27))
        self.assertEqual(self.p["direccion_candidata"]["origen"], "oficial")
        aplicar.aplicar({"proyectos": [item]}, self.prys, self.zonas, VerificadorFalso(), BitacoraMemoria(), date(2026, 10, 28))
        self.assertEqual(self.p["direccion_candidata"]["origen"], "oficial")

    def test_aplicar_guarda_direccion_sin_coordenadas(self):
        item = {"id": self.p["id"], "direccion": "Calle 73 # 13-20", "direccion_fuente": "https://forjar.co/metro73",
                "lat": None, "lng": None, "notas": "sin mapa"}
        aplicar.aplicar({"proyectos": [item]}, self.prys, self.zonas, VerificadorFalso(evidencia="ok"),
                        BitacoraMemoria(), date(2026, 10, 26))
        self.assertEqual(self.p["direccion_candidata"]["origen"], "oficial")


if __name__ == "__main__":
    unittest.main()


class TestCaracas(unittest.TestCase):
    def test_caracas_acepta_carrera_14(self):
        import re
        from vivienda.geocodificacion import vias_para_cruce
        (p1, _), (p2, _) = vias_para_cruce("Calle 45 con Avenida Caracas")
        for nombre in ("Avenida Caracas", "Avenida Carrera 14", "Carrera 14"):
            self.assertTrue(re.search(p2, nombre, re.I), nombre)
        self.assertFalse(re.search(p2, "Carrera 145", re.I))
