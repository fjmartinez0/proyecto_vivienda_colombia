import tempfile
import unittest
from datetime import date
from pathlib import Path

from vivienda.pipeline import brochures as brp
from vivienda.sources import brochure as br
from test_ubicacion import BitacoraMemoria, registro_desde_fixture

TEXTO = """TIPO A - 1 Alcoba   Área construida: 44,02 m2   Área privada: 39,10 m2
TIPO B - 2 Alcobas  Área Construida 53,55 m²    Área Privada 47,80 m²
Torre de 12 pisos con dos ascensores. Estrato 4. Administración aproximada $7.200 por m2.
Entrega 2S - 2028. Entrega con acabados. Sala de ventas Calle 67 # 11-86."""


def pdf_de_prueba(directorio: Path, texto: str = TEXTO) -> Path:
    from reportlab.lib.pagesizes import letter
    from reportlab.pdfgen import canvas
    ruta = directorio / "brochure.pdf"
    c = canvas.Canvas(str(ruta), pagesize=letter)
    y = 740
    for linea in texto.splitlines():
        c.drawString(40, y, linea)
        y -= 18
    c.save()
    return ruta


class RespuestaFalsa:
    def __init__(self, contenido, tipo="text/html"):
        self.contenido, self.headers = contenido, {"Content-Type": tipo}

    def raise_for_status(self):
        pass

    def iter_content(self, n):
        yield self.contenido


class SesionFalsa:
    def __init__(self, contenido, tipo="text/html"):
        self.r = RespuestaFalsa(contenido, tipo)

    def get(self, *a, **k):
        return self.r


class TestReglas(unittest.TestCase):
    def test_extraer_datos(self):
        d = br.extraer_datos(TEXTO)
        self.assertEqual(d["areas"], [{"privada": 39.1, "construida": 44.02}, {"privada": 47.8, "construida": 53.55}])
        self.assertEqual((d["ascensores"], d["estrato"], d["admin_m2"]), (2, 4, 7200.0))
        self.assertEqual((d["acabados"], d["entrega"], d["direccion"]), ("full", "2028-12", "Calle 67 # 11-86"))

    def test_aparece_en_texto(self):
        self.assertTrue(br.aparece_en_texto(39.1, TEXTO))
        self.assertTrue(br.aparece_en_texto(7200, TEXTO))
        self.assertFalse(br.aparece_en_texto(41.2, TEXTO))
        self.assertFalse(br.aparece_en_texto(4.02, TEXTO))   # no vale un pedazo de 44,02


class TestPDF(unittest.TestCase):
    def test_texto_desde_pdf(self):
        with tempfile.TemporaryDirectory() as d:
            texto, paginas = br.extraer_texto(pdf_de_prueba(Path(d)))
            self.assertEqual(paginas, 1)
            self.assertIn("44,02", texto)

    def test_descarga_rechaza_lo_que_no_es_pdf(self):
        with tempfile.TemporaryDirectory() as d:
            res = br.descargar("https://x.co/brochure", "PRY-0001", SesionFalsa(b"<html>formulario</html>"), destino=Path(d))
            self.assertFalse(res.ok)
            self.assertIn("formulario", res.motivo)
            ok = br.descargar("https://x.co/b.pdf", "PRY-0001", SesionFalsa(b"%PDF-1.4 ..."), destino=Path(d))
            self.assertTrue(ok.ok and ok.archivo.exists())


class TestAsignacion(unittest.TestCase):
    TIPS = [{"fuente": "estrenarvivienda", "typology_id": "1", "area": 44.02, "habs": 1},
            {"fuente": "estrenarvivienda", "typology_id": "2", "area": 53.55, "habs": 2},
            {"fuente": "estrenarvivienda", "typology_id": "3", "area": 70.0, "habs": 3}]

    def test_asigna_solo_compatibles(self):
        pares = [{"privada": 39.1, "construida": 44.02}, {"privada": 47.8, "construida": 53.55},
                 {"privada": 68.0, "construida": 69.5}]   # ratio 0,98: demasiado alto, se rechaza
        asignadas, notas = brp.asignar_areas(self.TIPS, pares, "https://x.co/b.pdf")
        self.assertEqual({k: v["valor"] for k, v in asignadas.items()},
                         {"estrenarvivienda:1": 39.1, "estrenarvivienda:2": 47.8})
        self.assertEqual(len(notas), 1)

    def test_sin_construida_no_asigna(self):
        asignadas, notas = brp.asignar_areas(self.TIPS, [{"privada": 39.1, "construida": None}], "u")
        self.assertEqual(asignadas, {})
        self.assertTrue(any("sin la construida" in n for n in notas))


class TestProcesar(unittest.TestCase):
    def test_flujo_completo_con_fixture(self):
        reg, prys = registro_desde_fixture()
        p = next(x for x in prys.values() if x["nombre"] == "67 Estorias")
        with tempfile.TemporaryDirectory() as d:
            pdf = pdf_de_prueba(Path(d))
            res = brp.ResumenBrochures()
            brp.procesar_archivo(p, pdf, "https://accanto.co/67.pdf", "abc", reg, BitacoraMemoria(), "2026-10-26", res)
        self.assertEqual(res.areas_asignadas, 2)          # 44,02 y 53,55 m² existen en el fixture
        self.assertEqual(p["enriquecimiento"]["estrato"]["valor"], 4)
        self.assertEqual(p["direccion_candidata"]["origen"], "oficial")
        self.assertEqual(p["brochures"][0]["estado"], "procesado")
        self.assertTrue(res.para_ia)                      # otras tipologías siguen sin área privada

    def test_brochure_reemplaza_dato_de_agregador_pero_no_oficial(self):
        reg, prys = registro_desde_fixture()
        p = next(x for x in prys.values() if x["nombre"] == "67 Estorias")
        p["enriquecimiento"] = {"entrega": {"valor": "2029-03", "fuente": "https://www.estrenarvivienda.com/x"},
                                "estrato": {"valor": 5, "fuente": "https://accanto.co"}}
        brp.aplicar_datos(p, {"entrega": "2028-12", "estrato": 4}, "https://accanto.co/67.pdf", [], BitacoraMemoria(), "h")
        self.assertEqual(p["enriquecimiento"]["entrega"]["valor"], "2028-12")
        self.assertEqual(p["enriquecimiento"]["estrato"]["valor"], 5)


class TestVerificacionIA(unittest.TestCase):
    def test_rechaza_lo_que_no_esta_en_el_pdf(self):
        propuesta = {"areas": [{"privada": 39.1, "construida": 44.02}, {"privada": 41.0, "construida": 46.0}],
                     "estrato": 4, "admin_m2": 8000, "ascensor": True, "acabados": "obra gris"}
        ok, rechazos = brp.verificar_propuesta_ia(propuesta, TEXTO)
        self.assertEqual(ok["areas"], [{"privada": 39.1, "construida": 44.02}])
        self.assertEqual(ok["estrato"], 4)
        self.assertNotIn("admin_m2", ok)
        self.assertNotIn("acabados", ok)
        self.assertEqual(len(rechazos), 3)


if __name__ == "__main__":
    unittest.main()
