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
                         {"chu", "c72", "lag", "nav", "cas", "pas", "mor", "teu", "can", "and", "bat", "sba"})
        self.assertTrue(all(f["properties"]["forma"] == "dibujada" for f in z["features"]))

    def test_circulo_contiene_su_centro(self):
        anillo = zmod.circulo([4.65, -74.06], 1000)
        self.assertEqual(anillo[0], anillo[-1])
        self.assertTrue(geo.punto_en_poligono(4.65, -74.06, anillo))
        self.assertFalse(geo.punto_en_poligono(4.67, -74.06, anillo))   # ~2,2 km al norte

    def test_puntos_en_zonas_dibujadas(self):
        z = cargar_zonas()
        self.assertEqual(geo.zona_de(4.6950, -74.0620, z), "pas")
        self.assertEqual(geo.zona_de(4.6380, -74.0720, z), "teu")
        self.assertEqual(geo.zona_de(4.6920, -74.0470, z), "nav")
        self.assertEqual(geo.zona_de(4.6565, -74.0580, z), "c72")   # Cl. 70–76: Quinta Camacho (antes hueco)
        self.assertIsNone(geo.zona_de(4.6419, -74.0549, z))          # Chapinero Alto: excluido

    def test_punto_manda_con_tolerancia(self):
        z = cargar_zonas()
        # el sector ya no saca a un proyecto de su lugar: lejos de toda zona -> fuera
        self.assertEqual(geo.asignar_zona(4.70, -74.10, ["pas"], z), (None, None))
        # Zento (Cra. 53 con Cl. 100) cae a metros del borde dibujado de Pasadena -> pas, con nota
        zona, nota = geo.asignar_zona(4.68850, -74.06266, ["pas"], z)
        self.assertEqual(zona, "pas")
        self.assertIn("del borde", nota)
        # Metro 73 (Cl. 73 # 14-48) -> Quinta Camacho; Primera Este (Chapinero Alto) -> fuera
        self.assertEqual(geo.asignar_zona(4.65980, -74.06132, ["chu", "lag"], z)[0], "c72")
        self.assertIsNone(geo.asignar_zona(4.64189, -74.05493, ["chu"], z)[0])
        self.assertEqual(geo.asignar_zona(7.0705, -73.1065, [], z)[0], "can")

    def test_sin_traslapes_entre_zonas(self):
        import random
        z = cargar_zonas()
        anillos = {f["properties"]["id"]: f["geometry"]["coordinates"][0] for f in z["features"]}
        rnd = random.Random(7)
        for _ in range(20000):
            la, ln = rnd.uniform(4.62, 4.715), rnd.uniform(-74.095, -74.03)
            dentro = [i for i, a in anillos.items() if geo.punto_en_poligono(la, ln, a)]
            self.assertLessEqual(len(dentro), 1, (la, ln, dentro))

    def test_distancia_a_poligono(self):
        cuadro = [[-74.07, 4.63], [-74.06, 4.63], [-74.06, 4.64], [-74.07, 4.64], [-74.07, 4.63]]
        self.assertEqual(geo.distancia_a_poligono_m(4.635, -74.065, cuadro), 0)
        self.assertAlmostEqual(geo.distancia_a_poligono_m(4.645, -74.065, cuadro), 553, delta=10)



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


class TestCrucesEnCaja(unittest.TestCase):
    """Una consulta por zona: el cruce se resuelve localmente con las calles descargadas."""

    def test_esquinas_locales(self):
        from unittest import mock
        from vivienda.geocodificacion import Geocodificador
        calles = [
            {"tags": {"name": "Avenida Carrera 14"}, "geometry": [{"lat": 4.630, "lon": -74.066}, {"lat": 4.6375, "lon": -74.0652}, {"lat": 4.650, "lon": -74.064}]},
            {"tags": {"name": "Calle 45"}, "geometry": [{"lat": 4.6375, "lon": -74.080}, {"lat": 4.6375, "lon": -74.0652}]},
            {"tags": {"name": "Carrera 28"}, "geometry": [{"lat": 4.630, "lon": -74.080}, {"lat": 4.6375, "lon": -74.080}, {"lat": 4.650, "lon": -74.080}]},
        ]
        g = Geocodificador("test", pausa=0)
        with mock.patch.object(g, "_overpass", return_value=(calles, "ok")) as op:
            res = g.cruces_en_caja(["Calle 45 con Avenida Caracas", "Calle 45 con Carrera 28", "Calle 99 con Carrera 28"],
                                   (4.62, 4.66, -74.09, -74.05))
        self.assertEqual(op.call_count, 1)
        self.assertIsNotNone(res[0][0])
        self.assertIsNotNone(res[1][0])
        self.assertIsNone(res[2][0])
        self.assertIn("Calle 99", res[2][1])


class TestDibujadas(unittest.TestCase):
    def test_dibujada_gana_a_circulo(self):
        import json, tempfile
        from pathlib import Path
        from vivienda.pipeline import zonas as zm
        anillo = [[-74.07, 4.63], [-74.06, 4.63], [-74.06, 4.64], [-74.07, 4.64], [-74.07, 4.63]]
        with tempfile.TemporaryDirectory() as t:
            f = Path(t) / "z.geojson"
            f.write_text(json.dumps({"type": "FeatureCollection", "features": [
                {"type": "Feature", "properties": {"id": "chu"}, "geometry": {"type": "Polygon", "coordinates": [anillo]}}]}))
            dib = zm.cargar_dibujadas(f)
        gj = zm.a_geojson([{"id": "chu", "centro": [4.635, -74.064], "radio_m": 1300},
                           {"id": "teu", "centro": [4.638, -74.074], "radio_m": 1000}], {}, dib)
        formas = {x["properties"]["id"]: x["properties"]["forma"] for x in gj["features"]}
        self.assertEqual(formas, {"chu": "dibujada", "teu": "circulo"})
        self.assertEqual(gj["features"][0]["geometry"]["coordinates"][0], anillo)
