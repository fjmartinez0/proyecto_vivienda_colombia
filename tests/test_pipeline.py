import unittest
from datetime import date

from vivienda.config import Filtros
from vivienda.models import Tipologia
from vivienda.pipeline import filtros, historial


def tip(tid, precio=400_000_000, area=45.0):
    return Tipologia(fuente="estrenarvivienda", typology_id=tid, proyecto="X", url="", constructora=None,
                     tipo_inmueble=None, sector=None, ciudad="Bogotá", area=area, area_tipo="construida",
                     habs=1, banos=1, parq=None, parq_comunal=False, precio_desde=precio)


class TestFiltros(unittest.TestCase):
    def test_descartes(self):
        f = Filtros(precio_max=600_000_000, area_min=30)
        ok, d = filtros.aplicar([tip("1"), tip("2", precio=700_000_000), tip("3", area=21), tip("4", precio=None)], f)
        self.assertEqual([t.typology_id for t in ok], ["1"])
        self.assertEqual(sum(d.values()), 3)


class TestSector(unittest.TestCase):
    def test_coincidencia_con_tildes_y_guiones(self):
        t = tip("1"); t.sector = "Cañaveral"
        self.assertTrue(filtros.pertenece_al_sector(t, "floridablanca/urbana/canaveral"))
        t.sector = "Chapinero Alto"
        self.assertTrue(filtros.pertenece_al_sector(t, "bogota/nororiente/chapinero-alto"))
        self.assertFalse(filtros.pertenece_al_sector(t, "bogota/nororiente/chapinero"))

    def test_recomendada_de_otra_ciudad(self):
        t = tip("1"); t.sector = "Rodadero"
        self.assertFalse(filtros.pertenece_al_sector(t, "bogota/noroccidente/morato"))


class TestHistorial(unittest.TestCase):
    def test_ciclo_de_vida(self):
        reg = {}
        f = {"estrenarvivienda"}
        r1 = historial.actualizar(reg, [tip("1"), tip("2")], date(2026, 10, 25), f)
        self.assertEqual(len(r1.nuevas), 2)

        r2 = historial.actualizar(reg, [tip("1", precio=390_000_000)], date(2026, 10, 26), f)
        self.assertEqual(r2.nuevas, [])
        self.assertEqual(r2.cambios_precio, ["estrenarvivienda:1"])
        self.assertEqual(r2.desaparecidas, ["estrenarvivienda:2"])
        self.assertEqual(reg["estrenarvivienda:1"]["primer_visto"], "2026-10-25")
        self.assertEqual(reg["estrenarvivienda:1"]["precio_anterior"], 400_000_000)

    def test_corrida_parcial_no_marca_desaparecidas(self):
        reg = {}
        historial.actualizar(reg, [tip("1")], date(2026, 10, 25), {"estrenarvivienda"})
        r = historial.actualizar(reg, [], date(2026, 10, 26), set())
        self.assertEqual(r.desaparecidas, [])
        self.assertTrue(reg["estrenarvivienda:1"]["activo"])


if __name__ == "__main__":
    unittest.main()
