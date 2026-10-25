import json
import plistlib
import tempfile
import unittest
from argparse import Namespace
from datetime import date
from pathlib import Path
from unittest import mock

from vivienda import cli
from vivienda.pipeline import diario

HOY = date(2026, 10, 26)


def usado(i, zona="chu", habs=2, area=60, precio=360_000_000, detectado="2026-10-20", ascensor=True):
    return {"id": f"FR-{i}", "zona": zona, "habs": habs, "area": area, "precio": precio,
            "detectado": detectado, "ascensor": ascensor, "url": f"https://x/{i}",
            "descripcion": "texto del anuncio", "publicador": "owner"}


class TestCandado(unittest.TestCase):
    def test_segunda_corrida_no_entra(self):
        with tempfile.TemporaryDirectory() as d:
            lock = Path(d) / "x.lock"
            with diario.candado(lock) as a:
                self.assertTrue(a)
                with diario.candado(lock) as b:
                    self.assertFalse(b)
            with diario.candado(lock) as c:
                self.assertTrue(c)


class TestOportunidades(unittest.TestCase):
    def test_solo_de_hoy_con_ascensor_y_bajo_tope(self):
        base = [usado(i) for i in range(6)]   # 6 M/m²
        barato = usado("b", precio=280_000_000, detectado="2026-10-26")          # −22 %
        sin_asc = usado("s", precio=280_000_000, detectado="2026-10-26", ascensor=None)
        viejo = usado("v", precio=280_000_000)                                   # no es de hoy
        caro = usado("c", area=120, precio=650_000_000, detectado="2026-10-26")   # > tope
        ops = diario.oportunidades_usados(base + [barato, sin_asc, viejo, caro], HOY, 0.15, 600_000_000)
        self.assertEqual([o["id"] for o in ops], ["FR-b"])
        self.assertGreater(ops[0]["descuento"], 0.15)

    def test_grupo_chico_no_alerta(self):
        ops = diario.oportunidades_usados([usado(1), usado("b", precio=200_000_000, detectado="2026-10-26")],
                                          HOY, 0.15, 600_000_000)
        self.assertEqual(ops, [])


class TestMensajes(unittest.TestCase):
    R = {"proyectos_nuevos": [{"id": "PRY-0016", "nombre": "Torre X", "zona": "c72", "precio_desde": 450e6,
                               "entrega": "2028-06", "url": "https://e/x"}],
         "cambios_precio_nuevos": [{"proyecto": "A", "habs": 1, "anterior": 400e6, "nuevo": 380e6},
                                   {"proyecto": "B", "habs": 2, "anterior": 400e6, "nuevo": 420e6}],
         "usados_oportunidad": [], "errores": [], "parcial": True}

    def test_contenido(self):
        ms = diario.mensajes(self.R, "https://dash", {"bajas_precio": True, "usados_baratos": True, "fallas": True})
        titulos = [m["titulo"] for m in ms]
        self.assertEqual(titulos, ["Proyecto nuevo", "Bajó el precio (1)", "Corrida con problemas"])
        self.assertIn("Torre X", ms[0]["texto"])
        self.assertIn("$450 M", ms[0]["texto"])
        self.assertEqual(ms[0]["url"], "https://dash")

    def test_opcionales_apagadas(self):
        ms = diario.mensajes(self.R, None, {})
        self.assertEqual([m["titulo"] for m in ms], ["Proyecto nuevo"])

    def test_envio_ntfy_titulo_con_tildes(self):
        with mock.patch("urllib.request.urlopen") as uo:
            diario.enviar_ntfy("tema-largo", {"titulo": "Bajó el precio", "texto": "año", "prioridad": "high"})
        req = uo.call_args[0][0]
        self.assertEqual(req.full_url, "https://ntfy.sh/tema-largo")
        req.get_header("Title").encode("latin-1")   # no revienta
        self.assertEqual(req.data, "año".encode())


class TestPublicacion(unittest.TestCase):
    def test_sanear_quita_texto_y_anunciante(self):
        d = diario.sanear({"proyectos": [], "usados": [usado(1)]})
        self.assertNotIn("descripcion", d["usados"][0])
        self.assertNotIn("publicador", d["usados"][0])
        self.assertEqual(d["usados"][0]["precio"], 360_000_000)

    def test_preparar_docs(self):
        with tempfile.TemporaryDirectory() as t:
            dash = Path(t) / "dashboard.json"
            dash.write_text(json.dumps({"usados": [usado(1)]}), encoding="utf-8")
            with mock.patch("vivienda.pipeline.exportar.ARCHIVO", dash):
                diario.preparar_docs(Path(t) / "docs")
            pub = json.loads((Path(t) / "docs/data/processed/dashboard.json").read_text(encoding="utf-8"))
            self.assertNotIn("descripcion", pub["usados"][0])
            self.assertTrue((Path(t) / "docs/web/index.html").exists())

    def test_git_sin_repo(self):
        with tempfile.TemporaryDirectory() as t:
            self.assertIn("sin repositorio", diario.git_publicar(HOY, Path(t)))


class TestPlist(unittest.TestCase):
    def test_plist_valido(self):
        x = plistlib.loads(cli.plist_diario("06:30", "/opt/homebrew/bin/python3", Path("/u/p")).encode())
        self.assertEqual(x["StartCalendarInterval"], {"Hour": 6, "Minute": 30})
        self.assertIn("-u", x["ProgramArguments"])
        self.assertEqual(x["EnvironmentVariables"]["PYTHONPATH"], "/u/p/src")
        self.assertNotIn("vivienda=", json.dumps(x))   # sin alias de zsh


class TestCorridaDiaria(unittest.TestCase):
    """De punta a punta con los comandos simulados: un paso que falla no tumba los demás."""

    def test_rutina(self):
        nuevo = {"id": "PRY-0016", "nombre": "Torre X", "zona": None, "precio_desde": 450e6, "url": "u"}
        with tempfile.TemporaryDirectory() as t:
            t = Path(t)
            dash = t / "dashboard.json"
            dash.write_text(json.dumps({"usados": []}), encoding="utf-8")
            llamados = []
            with mock.patch.multiple(
                    cli,
                    cmd_nuevos=lambda a: llamados.append("nuevos") or {"completa": True, "tipologias_nuevas": 3,
                                                                      "desaparecidas": 0, "proyectos_nuevos": [nuevo],
                                                                      "cambios_precio": []},
                    cmd_geocodificar=lambda a: llamados.append("geo"),
                    cmd_ubicar=lambda a: llamados.append(f"ubicar:{a.max}"),
                    cmd_usados=lambda a: (_ for _ in ()).throw(RuntimeError("403 bloqueo")),
                    cmd_exportar=lambda a: llamados.append("exportar")), \
                 mock.patch.object(cli.proyectos, "cargar", lambda: {"PRY-0016": {"zona": "c72"}}), \
                 mock.patch.object(cli.exportar, "ARCHIVO", dash), \
                 mock.patch.object(diario, "LOCK", t / "l.lock"), \
                 mock.patch.object(diario, "LOGS", t / "logs"), \
                 mock.patch.object(diario, "RESUMEN", t / "ultima.json"), \
                 mock.patch.object(diario, "tema_ntfy", lambda: "tema"), \
                 mock.patch.object(diario, "enviar_ntfy") as envio, \
                 mock.patch.object(cli.cfgmod, "ROOT", t):
                cli.cmd_diario(Namespace(sin_usados=False, sin_ia=False, sin_publicar=True,
                                         sin_alertas=False, verbose=False))
            self.assertEqual(llamados, ["nuevos", "geo", "ubicar:3", "exportar"])
            r = json.loads((t / "ultima.json").read_text(encoding="utf-8"))
            self.assertEqual(r["proyectos_nuevos"][0]["zona"], "c72")
            self.assertTrue(any("usados" in e for e in r["errores"]))
            titulos = [c.args[1]["titulo"] for c in envio.call_args_list]
            self.assertEqual(titulos, ["Proyecto nuevo", "Corrida con problemas"])
            self.assertTrue(any(p.suffix == ".txt" for p in (t / "logs").iterdir()))


if __name__ == "__main__":
    unittest.main()
