import tempfile
import unittest
from datetime import date
from pathlib import Path

from vivienda.pipeline import valorizacion as v
from vivienda.pipeline.usados import motivo_sospechoso

LAT, LNG = 4.6400, -74.0640
HOY = date(2026, 11, 16)


def proyecto(**kw):
    p = {"id": "p1", "nombre": "Torre Prueba", "zona": "chu", "lat": LAT, "lng": LNG, "entrega": "2028-03",
         "estado": "En construcción",
         "tipologias": [
             {"area": 30.0, "precio": 300e6, "precios": [{"fecha": "2025-11-01", "precio": 300e6},
                                                          {"fecha": "2026-11-01", "precio": 330e6}]},
             {"area": 50.0, "precio": 500e6, "precios": [{"fecha": "2025-11-01", "precio": 500e6}]}]}
    p.update(kw)
    return p


def usado(**kw):
    u = {"id": "FR-1", "lat": LAT + 0.0001, "lng": LNG, "zona": "chu", "area": 31.0, "area_tipo": "construida",
         "precio": 290e6, "admin": 300_000, "creado_portal": "2026-10-20", "descripcion": "apto en Torre Prueba"}
    u.update(kw)
    return u


class TestNuevoVsReventa(unittest.TestCase):
    def test_serie_base_toma_la_mas_barata(self):
        s = v.serie_base(proyecto())
        self.assertEqual([(x["area"], x["precio"]) for x in s], [(30.0, 300e6), (30.0, 330e6)])
        self.assertTrue(all(x["fuente"] == "c" for x in s))

    def test_lista_en_obra(self):
        m = v.metricas(v.serie_base(proyecto()), [], [], [], date(2028, 3, 15))["obra"]
        self.assertAlmostEqual(m["acc"], 0.10, places=3)

    def test_sin_tasa_si_cambia_el_metraje(self):
        p = proyecto(tipologias=[{"area": 30.0, "precios": [{"fecha": "2025-11-01", "precio": 300e6}]},
                                 {"area": 45.0, "precios": [{"fecha": "2026-11-01", "precio": 280e6}]}])
        self.assertIsNone(v.metricas(v.serie_base(p), [], [], [], None)["obra"])
        self.assertTrue(v.variacion(v.serie_base(p), HOY)["cambio_unidad"])

    def test_entrega_estimada_sin_senales(self):
        est = v.estado_entrega(proyecto(), [], HOY)
        self.assertEqual(est["estado"], "estimada")

    def test_entrega_confirmada_con_reventa_y_fecha(self):
        p = proyecto(entrega="2026-06")
        rev, pin = v.reventas_edificio(LAT, LNG, [usado()], p["nombre"])
        self.assertEqual(v.estado_entrega(p, pin, HOY)["estado"], "confirmada")
        self.assertEqual(rev[0]["estado"], "ok")         # el anuncio nombra el edificio

    def test_reventa_lejos_no_cuenta(self):
        rev, pin = v.reventas_edificio(LAT, LNG, [usado(lat=LAT + 0.002)], "Torre Prueba")
        self.assertEqual((rev, pin), ([], []))

    def test_construir_prima_solo_tras_entrega(self):
        datos = {"proyectos": [proyecto(entrega="2026-06")], "usados": [usado()]}
        b = v.construir(datos, HOY, semilla=Path("/no/existe.toml"))
        f = b["proyectos"][0]
        self.assertEqual(f["entrega_estado"]["estado"], "confirmada")
        self.assertAlmostEqual(f["metricas"]["prima"]["v"], (290e6 / 31) / (330e6 / 30) - 1, places=4)
        datos = {"proyectos": [proyecto()], "usados": []}
        self.assertIsNone(v.construir(datos, HOY, semilla=Path("/no/existe.toml"))["proyectos"][0]["metricas"]["prima"])

    def test_fuera_de_zona_lejos_no_entra(self):
        datos = {"proyectos": [proyecto(fuera_de_zona=True, distancia_zona_m=400)], "usados": []}
        self.assertEqual(v.construir(datos, HOY, semilla=Path("/no/existe.toml"))["proyectos"], [])

    def test_prima_automatica_fincaraiz(self):
        lat, lng = 4.70, -74.05
        us = [usado(id="c", lat=lat, lng=lng, edificio="e1", publicador="builder", precio=400e6, area=40.0),
              usado(id="r", lat=lat, lng=lng, edificio="e1", publicador="owner", precio=360e6, area=40.0)]
        auto = v.prima_automatica(us, [])
        self.assertEqual(len(auto), 1)
        self.assertAlmostEqual(auto[0]["prima"]["v"], -0.10, places=4)
        self.assertEqual(v.prima_automatica(us, [(lat, lng)]), [])   # ya es un proyecto del radar

    def test_semilla(self):
        toml = """
[[proyecto]]
id = "s"
nombre = "S"
entrega = "2025-06"
  [[proyecto.precio]]
  momento = "base"
  fecha = "2024-12"
  area = 25.0
  precio = 300_000_000
  [[proyecto.precio]]
  momento = "hoy"
  fecha = "2025-06"
  area = 25.0
  precio = 282_000_000
"""
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "s.toml"
            p.write_text(toml, encoding="utf-8")
            b = v.construir({"proyectos": [], "usados": []}, HOY, semilla=p)
        f = b["proyectos"][0]
        self.assertTrue(f["manual"])
        self.assertAlmostEqual(f["metricas"]["prima"]["v"], -0.06, places=4)
        self.assertIn("NUEVO VS REVENTA", v.reporte(b))

    def test_semilla_real_carga(self):
        self.assertEqual([s["id"] for s in v.cargar_semilla()], ["semilla-open-c60"])


class TestSospechosos(unittest.TestCase):
    def test_area_imposible(self):
        self.assertIsNotNone(motivo_sospechoso(550e6, 803, 2))      # el caso de Pasadena

    def test_m2_imposible(self):
        self.assertIsNotNone(motivo_sospechoso(50e6, 60, 2))

    def test_normal(self):
        self.assertIsNone(motivo_sospechoso(550e6, 80.3, 2))


if __name__ == "__main__":
    unittest.main()
