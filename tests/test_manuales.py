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
        self.assertEqual(ids, {"lumina-77", "la-cite", "street-52", "distrito-kb"})
        zonas = {z["properties"]["id"] for z in cargar_zonas()["features"]}
        for m in self.manuales:
            self.assertTrue(set(m["zonas"]) <= zonas, m["id"])

    def test_sin_precio_no_se_descarta(self):
        ts = manual.tipologias(self.manuales)
        ok, desc = filtros.aplicar(ts, Filtros(precio_max=600_000_000, area_min=30))
        self.assertEqual(len(ok), len(ts))            # Lumina y Street 52 no tienen precio
        self.assertTrue(all(t.proyecto_clave.startswith("manual:") for t in ts))

    def test_integracion_completa(self):
        reg = {}
        historial.actualizar(reg, manual.tipologias(self.manuales), date(2026, 10, 25), {manual.FUENTE})
        prys = {}
        proyectos.sincronizar(reg, prys)
        manual.aplicar_a_proyectos(prys, self.manuales, date(2026, 10, 25))
        por_nombre = {p["nombre"]: p for p in prys.values()}
        self.assertEqual(len(prys), 4)
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
        self.assertEqual([t["area_privada"] for t in pub["Street 52"]["tipologias"]], [34.53, 34.85, 37.0])
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
