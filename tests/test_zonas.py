import tempfile
import unittest
from datetime import date
from pathlib import Path

from vivienda import geo
from vivienda.config import cargar_zonas
from vivienda.pipeline import zonas as zmod


class TestZonas(unittest.TestCase):
    def test_archivo_real(self):
        z = cargar_zonas()
        self.assertEqual({f["properties"]["id"] for f in z["features"]},
                         {"chu", "c72", "cor", "pas", "mor", "lag", "teu", "can"})

    def test_circulo_contiene_su_centro(self):
        anillo = zmod.circulo([4.65, -74.06], 1000)
        self.assertEqual(anillo[0], anillo[-1])
        self.assertTrue(geo.punto_en_poligono(4.65, -74.06, anillo))
        self.assertFalse(geo.punto_en_poligono(4.67, -74.06, anillo))   # ~2,2 km al norte

    def test_traslape_gana_la_mas_cercana_a_su_centro(self):
        z = cargar_zonas()
        self.assertEqual(geo.zona_de(4.6920, -74.0610, z), "pas")   # también cae dentro del corredor
        self.assertEqual(geo.zona_de(4.6385, -74.0730, z), "teu")   # Palermo: también dentro de chu

    def test_sector_manda(self):
        z = cargar_zonas()
        self.assertEqual(geo.asignar_zona(4.70, -74.10, ["cor"], z), ("cor", None))
        # ambiguo: gana el centro más cercano
        self.assertEqual(geo.asignar_zona(4.6360, -74.0640, ["chu", "c72"], z)[0], "chu")
        self.assertEqual(geo.asignar_zona(4.6560, -74.0580, ["chu", "c72"], z)[0], "c72")
        # sin sector: el círculo que lo contenga
        self.assertEqual(geo.asignar_zona(7.0705, -73.1065, [], z)[0], "can")
        self.assertIsNone(geo.asignar_zona(4.60, -74.20, [], z)[0])



class GeoFalso:
    """Cruces simulados: devuelve un punto por esquina; falla las que contengan 'Falla'."""
    def __init__(self):
        self.llamadas = 0

    def cruce_detallado(self, esquina, ciudad, bbox=None):
        self.llamadas += 1
        if "Falla" in esquina:
            return None, "no existe en OSM con ese nombre: Falla"
        n = int(esquina.split()[1])
        return (4.60 + n / 1000, -74.07 + (0.01 if "Carrera 5" in esquina else 0), "cruce"), "ok"


class TestEsquinas(unittest.TestCase):
    def _defs(self, esquinas):
        return [{"id": "x", "ciudad": "Bogotá", "centro": [4.65, -74.06], "radio_m": 500, "esquinas": esquinas}]

    def test_calcula_una_vez_y_usa_poligono(self):
        esq = ["Calle 40 con Avenida Caracas", "Calle 60 con Avenida Caracas", "Calle 60 con Carrera 5", "Calle 40 con Carrera 5"]
        with tempfile.TemporaryDirectory() as d:
            arch = Path(d) / "zonas_esquinas.json"
            geo_f = GeoFalso()
            r = zmod.calcular(self._defs(esq), geo_f, date(2026, 10, 25), path=arch, avisar=lambda *_: None)
            self.assertEqual(r.calculadas, ["x"])
            r = zmod.calcular(self._defs(esq), geo_f, date(2026, 10, 26), path=arch, avisar=lambda *_: None)
            self.assertEqual((r.al_dia, geo_f.llamadas), (["x"], 4))      # no repite consultas
            gj = zmod.a_geojson(self._defs(esq), zmod.cargar_poligonos(arch))
            f = gj["features"][0]
            self.assertEqual(f["properties"]["forma"], "esquinas")
            self.assertEqual(len(f["geometry"]["coordinates"][0]), 5)
            # si cambian las esquinas, vuelve al círculo hasta recalcular
            gj = zmod.a_geojson(self._defs(esq[:3]), zmod.cargar_poligonos(arch))
            self.assertEqual(gj["features"][0]["properties"]["forma"], "circulo")

    def test_esquina_fallida_deja_circulo(self):
        esq = ["Calle 40 con Avenida Caracas", "Calle 60 con Falla", "Calle 60 con Carrera 5"]
        with tempfile.TemporaryDirectory() as d:
            arch = Path(d) / "zonas_esquinas.json"
            r = zmod.calcular(self._defs(esq), GeoFalso(), date(2026, 10, 25), path=arch, avisar=lambda *_: None)
            self.assertEqual(len(r.fallidas), 1)
            gj = zmod.a_geojson(self._defs(esq), zmod.cargar_poligonos(arch))
            self.assertEqual(gj["features"][0]["properties"]["forma"], "circulo")


if __name__ == "__main__":
    unittest.main()
