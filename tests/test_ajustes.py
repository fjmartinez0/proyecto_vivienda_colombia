import unittest
import unittest.mock
from datetime import date

from vivienda import ajustes
from vivienda.pipeline import exportar

HOY = date(2026, 11, 1)


def pry(i, nombre, **kw):
    return {"id": i, "nombre": nombre, "clave": f"e:{i}", "activo": True, **kw}


class TestAjustes(unittest.TestCase):
    A = {"ubicacion": [{"nombre": "Novus Florida", "direccion": "Carrera 8 con Calle 10", "seguimiento": True},
                       {"nombre": "Nau House", "lat": 4.68, "lng": -74.07}],
         "excluir": {"nombres": ["Signature Virrey"]}}

    def test_direccion_manual_y_seguimiento(self):
        prys = {"P1": pry("P1", "NOVUS FLORIDA",
                          ubicacion={"lat": 1, "lng": 2, "direccion": "otra", "metodo": "cruce"})}
        ajustes.aplicar(prys, self.A, HOY)
        p = prys["P1"]
        self.assertEqual(p["direccion_candidata"]["origen"], "manual")
        self.assertIsNone(p["ubicacion"])          # se vuelve a geocodificar
        self.assertTrue(p["seguimiento"])
        # idempotente: una segunda pasada no toca nada
        self.assertEqual(ajustes.aplicar(prys, self.A, HOY), [])

    def test_coordenadas(self):
        prys = {"P2": pry("P2", "Nau House")}
        ajustes.aplicar(prys, self.A, HOY)
        self.assertEqual(prys["P2"]["ubicacion"]["lat"], 4.68)

    def test_excluido_no_se_exporta(self):
        prys = {"P3": pry("P3", "Signature Virrey", ubicacion={"lat": 4.67, "lng": -74.05}, zona="chu")}
        ajustes.aplicar(prys, self.A, HOY)
        self.assertTrue(prys["P3"]["excluido"])
        tips = {"t": {"activo": True, "proyecto_clave": "e:P3", "precio_desde": 1, "area": 40}}
        with unittest.mock.patch.object(exportar, "clave_proyecto", lambda t: t["proyecto_clave"]):
            d = exportar.construir(prys, tips, {"type": "FeatureCollection", "features": []})
        self.assertEqual(d["proyectos"] + d["sin_ubicar"], [])


if __name__ == "__main__":
    unittest.main()
