import unittest
from datetime import date
from pathlib import Path

from vivienda import geo, reglas
from vivienda.checks import Bitacora
from vivienda.config import cargar_zonas
from vivienda.pipeline import aplicar, exportar, historial, proyectos
from vivienda.sources.estrenar import FUENTE, parse_html
from vivienda.verificacion import coords_de_enlace, via_de_calle_osm, vias_de_direccion

FIXTURE = Path(__file__).parent / "fixtures" / "estrenar_chapinero.html"


class VerificadorFalso:
    """Simula las verificaciones externas para no depender de internet."""

    def __init__(self, evidencia="ok", calle="Calle 67"):
        self._ev, self._calle = evidencia, calle

    def evidencia(self, url, direccion):
        return self._ev, "simulado"

    def calle_en(self, lat, lng):
        return self._calle


class BitacoraMemoria(Bitacora):
    def guardar(self):
        pass


def registro_desde_fixture():
    ts = parse_html(FIXTURE.read_text(encoding="utf-8", errors="ignore"))
    reg = {}
    historial.actualizar(reg, ts, date(2026, 10, 25), {FUENTE})
    prys = {}
    proyectos.sincronizar(reg, prys)
    return reg, prys


class TestDirecciones(unittest.TestCase):
    def test_vias_de_direccion(self):
        self.assertEqual(vias_de_direccion("Calle 67 # 5-30"), {("calle", "67"), ("carrera", "5")})
        self.assertEqual(vias_de_direccion("Cra. 13 No. 61-45"), {("carrera", "13"), ("calle", "61")})
        self.assertEqual(vias_de_direccion("Av. Calle 72 # 10-34"), {("calle", "72"), ("carrera", "10")})
        self.assertEqual(vias_de_direccion("sin dirección"), set())

    def test_via_osm(self):
        self.assertEqual(via_de_calle_osm("Avenida Calle 72"), ("calle", "72"))
        self.assertEqual(via_de_calle_osm("Carrera 7"), ("carrera", "7"))
        self.assertIsNone(via_de_calle_osm("Parque El Virrey"))


class TestEnlaces(unittest.TestCase):
    def test_google_maps_prefiere_pin_sobre_vista(self):
        u = ("https://www.google.com/maps/place/67+Estorias/@4.6588697,-74.1444089,886076m/"
             "data=!3m1!1e3!4m6!3m5!1s0x8e3f:0xe546!8m2!3d4.653336!4d-74.062162!16s")
        self.assertEqual(coords_de_enlace(u), (4.653336, -74.062162))

    def test_waze_y_q(self):
        self.assertEqual(coords_de_enlace("https://waze.com/ul?ll=4.65356,-74.06219&navigate=yes"), (4.65356, -74.06219))
        self.assertEqual(coords_de_enlace("https://maps.google.com/?q=4.6531,-74.0571"), (4.6531, -74.0571))
        self.assertIsNone(coords_de_enlace("https://maps.app.goo.gl/QvSm39"))


class TestGeo(unittest.TestCase):
    def test_zonas(self):
        z = cargar_zonas()
        self.assertEqual(geo.zona_de(4.6500, -74.0600, z), "chu")
        self.assertEqual(geo.zona_de(7.0705, -73.1065, z), "can")
        self.assertIsNone(geo.zona_de(4.60, -74.20, z))

    def test_bbox(self):
        self.assertTrue(geo.en_bbox(4.65, -74.06, "Bogotá"))
        self.assertFalse(geo.en_bbox(7.07, -73.10, "Bogotá"))


class TestReglas(unittest.TestCase):
    def test_enriquecimiento(self):
        ok, err = reglas.validar_enriquecimiento({
            "estrato": 4, "estrato_fuente": "https://constructora.com/p",
            "admin_m2": 99, "admin_m2_fuente": "https://constructora.com/p",
            "ascensor": True,
            "entrega": "1T-2029", "entrega_fuente": "https://constructora.com/p",
        })
        self.assertEqual(ok["estrato"]["valor"], 4)
        self.assertNotIn("admin_m2", ok)   # fuera de rango
        self.assertNotIn("ascensor", ok)   # sin fuente
        self.assertNotIn("entrega", ok)    # formato inválido
        self.assertEqual(len(err), 3)

    def test_agregadores(self):
        self.assertTrue(reglas.es_agregador("https://www.estrenarvivienda.com/x"))
        self.assertFalse(reglas.es_agregador("https://constructora.com.co/x"))


class TestProyectos(unittest.TestCase):
    def test_agrupacion_e_ids(self):
        _, prys = registro_desde_fixture()
        nombres = sorted(p["nombre"] for p in prys.values())
        self.assertIn("Metro 73", nombres)
        self.assertEqual(len(prys), len(set(nombres)))
        self.assertTrue(all(i.startswith("PRY-") for i in prys))
        metro = next(p for p in prys.values() if p["nombre"] == "Metro 73")
        self.assertEqual(metro["url"], "https://www.estrenarvivienda.com/metro-73/bogota")

    def test_ids_estables(self):
        reg, prys = registro_desde_fixture()
        antes = {p["clave"]: p["id"] for p in prys.values()}
        self.assertEqual(proyectos.sincronizar(reg, prys), [])
        self.assertEqual(antes, {p["clave"]: p["id"] for p in prys.values()})


class TestAplicar(unittest.TestCase):
    def setUp(self):
        self.reg, self.prys = registro_desde_fixture()
        self.pid = next(p["id"] for p in self.prys.values() if p["nombre"] == "67 Estorias")
        self.zonas = cargar_zonas()

    def _item(self, **kw):
        base = {"id": self.pid, "direccion": "Calle 67 # 5-30", "direccion_fuente": "https://accanto.co/67",
                "lat": 4.6540, "lng": -74.0570}
        return {**base, **kw}

    def test_ubicacion_alta_y_zona(self):
        res = aplicar.aplicar({"proyectos": [self._item()]}, self.prys, self.zonas,
                              VerificadorFalso(), BitacoraMemoria(), date(2026, 10, 26))
        p = self.prys[self.pid]
        self.assertEqual(res.ubicados, [self.pid])
        self.assertEqual(p["ubicacion"]["precision"], "alta")
        self.assertEqual(p["zona"], "chu")

    def test_enlace_de_mapa_sin_direccion_da_media(self):
        item = {"id": self.pid, "lat": 4.653336, "lng": -74.062162,
                "coordenadas_fuente": "https://www.google.com/maps/place/x/data=!8m2!3d4.653336!4d-74.062162"}
        aplicar.aplicar({"proyectos": [item]}, self.prys, self.zonas,
                        VerificadorFalso(evidencia="error", calle="Calle 67"), BitacoraMemoria(), date(2026, 10, 26))
        self.assertEqual(self.prys[self.pid]["ubicacion"]["precision"], "media")

    def test_rechazos(self):
        items = [self._item(lat=7.07, lng=-73.10),        # fuera de Bogotá
                 {"id": "PRY-9999", "lat": 4.65, "lng": -74.06}]  # ID inventado
        res = aplicar.aplicar({"proyectos": items}, self.prys, self.zonas,
                              VerificadorFalso(), BitacoraMemoria(), date(2026, 10, 26))
        self.assertEqual(len(res.rechazos), 2)
        self.assertIsNone(self.prys[self.pid]["ubicacion"])

    def test_no_empeora_precision(self):
        bit = BitacoraMemoria()
        aplicar.aplicar({"proyectos": [self._item()]}, self.prys, self.zonas, VerificadorFalso(), bit, date(2026, 10, 26))
        res = aplicar.aplicar({"proyectos": [self._item(lat=4.6600)]}, self.prys, self.zonas,
                              VerificadorFalso(evidencia="no_encontrada", calle="Carrera 9"), bit, date(2026, 10, 27))
        self.assertEqual(self.prys[self.pid]["ubicacion"]["lat"], 4.654)
        self.assertEqual(len(res.rechazos), 1)

    def test_exportar(self):
        aplicar.aplicar({"proyectos": [self._item(estrato=4, estrato_fuente="https://accanto.co/67")]},
                        self.prys, self.zonas, VerificadorFalso(), BitacoraMemoria(), date(2026, 10, 26))
        d = exportar.construir(self.prys, self.reg, self.zonas)
        self.assertEqual([p["id"] for p in d["proyectos"]], [self.pid])
        self.assertEqual(d["proyectos"][0]["estrato"], 4)
        self.assertEqual(len(d["sin_ubicar"]), len(self.prys) - 1)


if __name__ == "__main__":
    unittest.main()
