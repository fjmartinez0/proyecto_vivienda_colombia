import json
import unittest
from datetime import date

from vivienda.config import cargar_zonas
from vivienda.pipeline import usados
from vivienda.sources.fincaraiz import parsear, url_barrio
from vivienda.sources.fincaraiz.cliente import Pagina, extraer_next_data, search_fast
from vivienda.sources.fincaraiz.parser import antiguedad_anios, estrato, to_number


def item(id_=1, tipo="Apartamento", lat=4.6500, lng=-74.0600, **kw):
    """Anuncio con la forma real de searchFast.data (según el proyecto anterior)."""
    base = {
        "id": id_, "link": f"/apartamento-en-venta-en-marly-bogota/{id_}",
        "property_type": {"name": tipo},
        "price": {"amount": 420000000, "admin_included": 420350000},
        "bedrooms": 2, "bathrooms": 2, "floor": 5, "floorsCount": 8, "stratum": 4,
        "latitude": lat, "longitude": lng,
        "locations": {"neighbourhood": [{"id": 1, "name": "Marly", "slug": "marly"}],
                      "zone": [{"name": "Zona Chapinero"}], "locality": [{"name": "Chapinero"}]},
        "technicalSheet": [
            {"field": "m2Built", "value": "55 m2"}, {"field": "m2apto", "value": "48"},
            {"field": "commonExpenses", "value": "$ 350.000"},
            {"field": "constructionYear", "value": "9 a 15 años"},
        ],
        "description": "Apartamento exterior, edificio con portería.",
        "isProject": False, "owner": {"type": "inmobiliaria"},
    }
    base.update(kw)
    return base


class TestParser(unittest.TestCase):
    def test_numeros(self):
        self.assertEqual(to_number("55 m2"), 55)          # no 552
        self.assertEqual(to_number("$ 190.000"), 190000)
        self.assertIsNone(to_number(""))
        self.assertEqual(estrato("110"), None)
        self.assertEqual(estrato(0), None)
        self.assertEqual(estrato("4"), 4)
        self.assertEqual(antiguedad_anios("Más de 30 años"), 35.0)

    def test_mapeo(self):
        a = parsear(item())
        self.assertEqual(a["id"], "1")
        self.assertEqual(a["url"], "https://www.fincaraiz.com.co/apartamento-en-venta-en-marly-bogota/1")
        self.assertEqual((a["tipo"], a["precio"], a["admin"]), ("apartamento", 420000000, 350000))
        self.assertEqual((a["area_construida"], a["area_privada"]), (55, 48))
        self.assertEqual((a["barrio"], a["estrato"], a["antiguedad"]), ("Marly", 4, 12.0))
        self.assertFalse(a["es_proyecto"])
        a = parsear(item(facilities=[{"name": "Gimnasio"}, {"name": "Ascensor"}, "Gimnasio"], created_at="2026-09-01"))
        self.assertEqual((a["amenidades"], a["creado_portal"]), (["Gimnasio", "Ascensor"], "2026-09-01"))

    def test_ascensor(self):
        # 8 pisos sin mención -> probable
        self.assertEqual(parsear(item())["ascensor"], True)
        self.assertTrue(parsear(item())["ascensor_fuente"].startswith("probable"))
        # facilidad explícita
        a = parsear(item(floorsCount=3, facilities=[{"name": "Ascensor"}]))
        self.assertEqual((a["ascensor"], a["ascensor_fuente"]), (True, "campo .facilities[0]"))
        # descripción negativa gana a los pisos
        a = parsear(item(description="Edificio sin ascensor, piso 4"))
        self.assertEqual(a["ascensor"], False)
        # nada que diga
        self.assertIsNone(parsear(item(floorsCount=4))["ascensor"])
        # pisos del edificio = 0 es "sin dato"; un apartamento en piso 7 implica edificio de 7+
        a = parsear(item(floorsCount=0, floor=7))
        self.assertEqual((a["pisos_edificio"], a["ascensor"]), (None, True))
        self.assertIsNone(parsear(item(floorsCount=0, floor=3))["ascensor"])
        # campo técnico con valor negativo
        a = parsear(item(technicalSheet=[{"field": "elevator", "value": "No"}], floorsCount=10))
        self.assertEqual(a["ascensor"], False)


class TestCliente(unittest.TestCase):
    def test_urls(self):
        self.assertEqual(url_barrio("palermo", "bogota"),
                         "https://www.fincaraiz.com.co/venta/palermo/bogota?ordenListado=3")
        self.assertEqual(url_barrio("san-felipe/zona-noroccidente", "bogota", 2),
                         "https://www.fincaraiz.com.co/venta/san-felipe/zona-noroccidente/bogota/pagina2?ordenListado=3")
        self.assertEqual(url_barrio("canaveral", "floridablanca", 1, "apartaestudio"),
                         "https://www.fincaraiz.com.co/venta/apartaestudios/canaveral/floridablanca/floridablanca?ordenListado=3")
        with self.assertRaises(ValueError):
            url_barrio("cabecera", "bucaramanga")

    def test_next_data(self):
        nd = {"props": {"pageProps": {"fetchResult": {"searchFast": {
            "data": [item()], "paginatorInfo": {"currentPage": 1, "lastPage": 1, "total": 1}}}}}}
        html = f'<html><script id="__NEXT_DATA__" type="application/json">{json.dumps(nd)}</script></html>'
        items, pag = search_fast(extraer_next_data(html))
        self.assertEqual((len(items), pag["total"]), (1, 1))
        with self.assertRaises(KeyError):
            search_fast({"props": {}})


class ClienteFalso:
    def __init__(self, paginas):
        self.paginas, self.urls = paginas, []

    def pagina(self, url, etiqueta=""):
        self.urls.append(url)
        return self.paginas.pop(0) if self.paginas else Pagina(url, [], {}, "sin más páginas")


class TestRecorrido(unittest.TestCase):
    def setUp(self):
        self.zonas = cargar_zonas()

    def test_filtra_y_zonifica(self):
        p1 = Pagina("u1", [item(1), item(2, tipo="Casa"), item(3, isProject=True),
                           item(4, lat=4.60, lng=-74.20), item(5, lat=None, lng=None)],
                    {"lastPage": 2, "total": 7})
        p2 = Pagina("u2", [item(6, lat=4.6650, lng=-74.0560), item(1)], {"lastPage": 2})
        cli = ClienteFalso([p1, p2])
        anuncios, r = usados.recorrer_barrio(cli, "marly/zona-chapinero", "bogota", self.zonas, 8,
                                             date(2026, 10, 26), avisar=lambda *_: None)
        self.assertEqual(sorted(a["id"] for a in anuncios), ["1", "4", "6"])   # dedup del 1; el 4 queda de entorno
        self.assertIsNone(next(a for a in anuncios if a["id"] == "4")["zona"])
        self.assertEqual((r.total_portal, r.paginas, r.otros_tipos, r.proyectos), (7, 2, 1, 1))
        self.assertEqual((r.fuera_de_zonas, r.sin_coordenadas), (1, 1))
        self.assertEqual(r.en_zona, {"chu": 2, "lag": 1})
        self.assertIn("/pagina2", cli.urls[1])

    def test_floridablanca_un_recorrido_por_tipo(self):
        cli = ClienteFalso([Pagina("a", [item(9, lat=7.0705, lng=-73.1065)], {"lastPage": 1, "total": 1}),
                            Pagina("b", [], {"lastPage": 1, "total": 0})])
        anuncios, r = usados.recorrer_barrio(cli, "canaveral", "floridablanca", self.zonas, 8,
                                             date(2026, 10, 26), avisar=lambda *_: None)
        self.assertEqual(len(cli.urls), 2)
        self.assertEqual(anuncios[0]["zona"], "can")

    def test_tope_de_paginas(self):
        cli = ClienteFalso([Pagina("a", [], {"lastPage": 30, "total": 600})] * 3)
        _, r = usados.recorrer_barrio(cli, "palermo", "bogota", self.zonas, 2, date(2026, 10, 26),
                                      avisar=lambda *_: None)
        self.assertEqual(r.paginas, 2)


class TestHistorial(unittest.TestCase):
    def test_precio_y_vigencia(self):
        a = {**parsear(item(1)), "zona": "chu", "ciudad": "bogota", "ruta": "marly"}
        reg = {}
        self.assertEqual(usados.actualizar(reg, [a], date(2026, 10, 20))["nuevos"], 1)
        b = {**a, "precio": 400000000}
        self.assertEqual(usados.actualizar(reg, [b], date(2026, 10, 22))["cambio_precio"], 1)
        r = reg["fincaraiz:1"]
        self.assertEqual([x["precio"] for x in r["precios"]], [420000000, 400000000])
        self.assertEqual((r["primer_visto"], r["ultimo_visto"]), ("2026-10-20", "2026-10-22"))
        self.assertEqual(len(usados.vigentes(reg, date(2026, 10, 29), 7)), 1)
        self.assertEqual(len(usados.vigentes(reg, date(2026, 10, 30), 7)), 0)

    def test_para_dashboard(self):
        reg = {}
        usados.actualizar(reg, [{**parsear(item(1)), "zona": "chu", "ciudad": "bogota", "ruta": "marly"},
                                {**parsear(item(2, technicalSheet=[{"field": "m2Built", "value": "25"}])),
                                 "zona": "chu", "ciudad": "bogota", "ruta": "marly"}], date(2026, 10, 25))
        d = usados.para_dashboard(reg, date(2026, 10, 25), 7, area_min=30)
        self.assertEqual(len(d), 1)                      # el de 25 m² queda fuera
        u = d[0]
        self.assertEqual((u["id"], u["area"], u["area_tipo"], u["habs"]), ("FR-1", 48, "privada", 2))
        self.assertEqual(u["fuentes"], ["Fincaraíz"])


if __name__ == "__main__":
    unittest.main()


class TestRezonificarUsados(unittest.TestCase):
    def test_zona_desde_el_punto_al_exportar(self):
        from datetime import date
        from vivienda.pipeline import usados as um
        from vivienda.pipeline.zonas import a_geojson
        zonas = a_geojson([{"id": "nueva", "centro": [4.65, -74.06], "radio_m": 500}])
        reg = {"a": {"id": "1", "zona": "vieja", "lat": 4.65, "lng": -74.06, "precio": 1, "area_privada": 40,
                     "tipo": "apartamento", "primer_visto": "2026-10-25", "ultimo_visto": "2026-10-25"},
               "b": {"id": "2", "zona": "vieja", "lat": 4.70, "lng": -74.06, "precio": 1, "area_privada": 40,
                     "tipo": "apartamento", "primer_visto": "2026-10-25", "ultimo_visto": "2026-10-25"}}
        out = um.para_dashboard(reg, date(2026, 10, 26), 7, 30, zonas)
        self.assertEqual(sorted((u["id"], u["zona"]) for u in out), [("FR-1", "nueva"), ("FR-2", None)])
