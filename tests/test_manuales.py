import tempfile
import unittest
from datetime import date
from pathlib import Path

from vivienda.config import Filtros, cargar_zonas
from vivienda.pipeline import exportar, filtros, historial, proyectos
from vivienda.sources import manual


class TestManuales(unittest.TestCase):
    def setUp(self):
        self.manuales = manual.cargar()   # config/proyectos_manuales.toml real

    def test_archivo_real(self):
        ids = {m["id"] for m in self.manuales}
        self.assertEqual(ids, {"lumina-77", "la-cite", "street-52", "distrito-kb", "mava-92", "heritage-97", "torres-del-valle", "verona-amarilo"})
        zonas = {z["properties"]["id"] for z in cargar_zonas()["features"]}
        for m in self.manuales:
            self.assertTrue(set(m.get("zonas", [])) <= zonas, m["id"])

    def test_sin_precio_no_se_descarta(self):
        ts = manual.tipologias(self.manuales)
        ok, desc = filtros.aplicar(ts, Filtros(precio_max=600_000_000, area_min=30))
        self.assertEqual(len(ok), len(ts) - sum(desc.values()))   # sin precio no descarta (Lumina, Street 52)
        self.assertEqual(dict(desc), {"área < 30 m²": 2, "sobre tope de precio": 2})   # solo Heritage 97
        self.assertTrue(all(t.proyecto_clave.startswith("manual:") for t in ts))

    def test_integracion_completa(self):
        reg = {}
        historial.actualizar(reg, manual.tipologias(self.manuales), date(2026, 10, 25), {manual.FUENTE})
        prys = {}
        proyectos.sincronizar(reg, prys)
        manual.aplicar_a_proyectos(prys, self.manuales, date(2026, 10, 25))
        por_nombre = {p["nombre"]: p for p in prys.values()}
        self.assertEqual(len(prys), 8)
        self.assertEqual(por_nombre["Heritage 97"]["ubicacion"]["metodo"], "coordenadas manuales")
        self.assertTrue(por_nombre["Mava 92"]["seguimiento"])
        s52 = por_nombre["Street 52"]
        self.assertEqual(s52["direccion_candidata"]["origen"], "manual")
        self.assertEqual(s52["enriquecimiento"]["renta_corta"]["valor"], "permitida")
        self.assertEqual(por_nombre["La Cité"]["direccion_candidata"]["origen"], "agregador")
        self.assertEqual(por_nombre["La Cité"]["enriquecimiento"]["estrato"]["valor"], 5)
        # al dashboard con área privada, aunque aún no tenga ubicación
        s52["ubicacion"] = {"lat": 4.6405, "lng": -74.0705, "precision": "media"}
        proyectos.rezonificar(prys, cargar_zonas())
        d = exportar.construir(prys, reg, cargar_zonas())
        pub = {p["nombre"]: p for p in d["proyectos"]}
        self.assertEqual(pub["Street 52"]["zona"], "teu")
        self.assertEqual(sorted(t["area_privada"] for t in pub["Street 52"]["tipologias"]), [34.53, 34.85, 37.0])
        self.assertEqual(pub["Street 52"]["fuente"], "Manual")

    def test_quitar_del_archivo_lo_inactiva(self):
        reg = {}
        historial.actualizar(reg, manual.tipologias(self.manuales), date(2026, 10, 25), {manual.FUENTE})
        sin_kb = [m for m in self.manuales if m["id"] != "distrito-kb"]
        r = historial.actualizar(reg, manual.tipologias(sin_kb), date(2026, 10, 26), {manual.FUENTE})
        self.assertEqual(r.desaparecidas, ["manual:distrito-kb-1"])

    def test_id_repetido_falla(self):
        with tempfile.TemporaryDirectory() as d:
            p = Path(d) / "m.toml"
            p.write_text('[[proyecto]]\nid="a"\n[[proyecto]]\nid="a"\n', encoding="utf-8")
            with self.assertRaises(ValueError):
                manual.cargar(p)


if __name__ == "__main__":
    unittest.main()


class TestSeguimiento(unittest.TestCase):
    def test_fuera_de_zona_se_publica_con_zona_de_referencia(self):
        from vivienda.config import cargar_zonas
        from vivienda.pipeline import exportar
        zonas = cargar_zonas()
        base = {"activo": True, "clave": "manual:heritage-97:bogota", "nombre": "Heritage 97", "zona": None,
                "ubicacion": {"lat": 4.681893, "lng": -74.048221, "precision": "media", "fuente": "x"}}
        tip = {"heritage": {"fuente": "manual", "typology_id": "heritage-97-1", "activo": True, "habs": 1,
                            "area": 30.62, "precio_desde": 540961887, "proyecto_clave": "manual:heritage-97:bogota"}}
        d = exportar.construir({"PRY-0099": {**base, "id": "PRY-0099", "seguimiento": True}}, tip, zonas)
        self.assertEqual(len(d["proyectos"]), 1)
        p = d["proyectos"][0]
        self.assertTrue(p["fuera_de_zona"])
        self.assertIn(p["zona"], {"nav", "lag", "pas", "cas"})
        self.assertGreater(p["distancia_zona_m"], 0)
        d2 = exportar.construir({"PRY-0099": {**base, "id": "PRY-0099"}}, tip, zonas)   # sin seguimiento -> lista aparte
        self.assertEqual((len(d2["proyectos"]), len(d2["fuera_de_zonas"])), (0, 1))
