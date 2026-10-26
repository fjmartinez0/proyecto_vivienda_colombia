"""Corrida diaria: candado, log por fecha, resumen legible por máquina, alertas (ntfy) y publicación.

Python puro. No consume Claude salvo que `nuevos` detecte proyectos nuevos y `[diario] ubicar_max > 0`.

- Candado: .run/diario.lock (fcntl). Si otra corrida sigue viva, esta sale sin hacer nada.
- Log: logs/AAAA-MM-DD.txt (se agrega si se corre dos veces el mismo día), sin búfer.
- Resumen: data/processed/ultima_corrida.json (y copia en logs/AAAA-MM-DD.json).
- Alertas: ntfy. El tema NUNCA va en el repo: variable VIVIENDA_NTFY_TEMA o config/ntfy_tema.txt (en .gitignore).
- Publicación: copia saneada en docs/ (sin descripción ni publicador de los anuncios) + git commit/push
  solo si hubo cambios. Apagada por defecto (`[diario] publicar = false`).
"""
from __future__ import annotations

import contextlib
import fcntl
import json
import os
import shutil
import subprocess
import sys
import urllib.request
from datetime import date
from pathlib import Path
from statistics import median

from vivienda import config as cfgmod

LOCK = cfgmod.ROOT / ".run" / "diario.lock"
LOGS = cfgmod.ROOT / "logs"
RESUMEN = cfgmod.PROCESSED_DIR / "ultima_corrida.json"
DOCS = cfgmod.ROOT / "docs"
ARCHIVO_TEMA = cfgmod.CONFIG_DIR / "ntfy_tema.txt"

# Campos de usados que no se publican (texto con derechos de autor / datos del anunciante)
CAMPOS_PRIVADOS_USADO = ("descripcion", "publicador")


# ---------------------------------------------------------------- candado y log
@contextlib.contextmanager
def candado(path: Path | None = None):
    """Cede True si obtuvo el candado; False si otra corrida lo tiene."""
    path = path or LOCK
    path.parent.mkdir(parents=True, exist_ok=True)
    f = open(path, "w")
    try:
        try:
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        except BlockingIOError:
            yield False
            return
        f.write(str(os.getpid()))
        f.flush()
        yield True
    finally:
        f.close()


class _Tee:
    def __init__(self, *destinos):
        self.destinos = destinos

    def write(self, s):
        for d in self.destinos:
            d.write(s)
            d.flush()
        return len(s)

    def flush(self):
        for d in self.destinos:
            d.flush()


@contextlib.contextmanager
def log_del_dia(hoy: date, carpeta: Path | None = None):
    carpeta = carpeta or LOGS
    carpeta.mkdir(parents=True, exist_ok=True)
    path = carpeta / f"{hoy.isoformat()}.txt"
    with open(path, "a", encoding="utf-8", buffering=1) as f:
        viejo_out, viejo_err = sys.stdout, sys.stderr
        sys.stdout = _Tee(viejo_out, f)
        sys.stderr = _Tee(viejo_err, f)
        # los handlers de logging guardan el stderr de cuando se configuraron: se redirigen también
        import logging
        handlers = [h for h in logging.getLogger().handlers if isinstance(h, logging.StreamHandler)
                    and not isinstance(h, logging.FileHandler)]
        previos = [h.setStream(sys.stderr) for h in handlers]
        try:
            yield path
        finally:
            for h, s in zip(handlers, previos):
                h.setStream(s)
            sys.stdout, sys.stderr = viejo_out, viejo_err


# ---------------------------------------------------------------- resumen
def guardar_resumen(resumen: dict, hoy: date) -> None:
    txt = json.dumps(resumen, ensure_ascii=False, indent=1)
    RESUMEN.parent.mkdir(parents=True, exist_ok=True)
    RESUMEN.write_text(txt, encoding="utf-8")
    LOGS.mkdir(parents=True, exist_ok=True)
    (LOGS / f"{hoy.isoformat()}.json").write_text(txt, encoding="utf-8")


def oportunidades_usados(usados: list[dict], hoy: date, umbral: float, precio_max: int,
                         min_grupo: int = 5) -> list[dict]:
    """Usados detectados HOY que cumplen reglas duras y cuyo $/m² está ≥ umbral por debajo de la
    mediana de su zona y número de habitaciones (grupo de al menos `min_grupo` anuncios).
    Versión simple de 'similares' del dashboard: suficiente para avisar, no para decidir."""
    grupos: dict[tuple, list[float]] = {}
    for u in usados:
        if u.get("precio") and u.get("area") and u.get("zona"):
            grupos.setdefault((u["zona"], u.get("habs")), []).append(u["precio"] / u["area"])
    out = []
    h = hoy.isoformat()
    for u in usados:
        if u.get("detectado") != h or not u.get("zona") or not u.get("ascensor") or not u.get("precio") or u["precio"] > precio_max:
            continue
        g = grupos.get((u["zona"], u.get("habs")), [])
        if len(g) < min_grupo:
            continue
        med = median(g)
        desc = 1 - (u["precio"] / u["area"]) / med
        if desc >= umbral:
            out.append({"id": u["id"], "zona": u["zona"], "habs": u.get("habs"), "area": u["area"],
                        "precio": u["precio"], "descuento": round(desc, 3), "url": u.get("url"),
                        "grupo": len(g)})
    return sorted(out, key=lambda x: -x["descuento"])


# ---------------------------------------------------------------- alertas
def _m(v) -> str:
    return f"${v / 1e6:,.0f} M".replace(",", ".") if v else "?"


def mensajes(resumen: dict, url_dashboard: str | None, alertas: dict) -> list[dict]:
    """-> [{titulo, texto, prioridad, url}] a partir del resumen de la corrida."""
    out = []
    for p in resumen.get("proyectos_nuevos") or []:
        texto = f"{p.get('nombre') or p['id']} · zona {p.get('zona') or '?'} · desde {_m(p.get('precio_desde'))}"
        if p.get("entrega"):
            texto += f" · entrega {p['entrega']}"
        if p.get("url"):
            texto += f"\n{p['url']}"
        out.append({"titulo": "Proyecto nuevo", "texto": texto, "prioridad": "high",
                    "url": url_dashboard or p.get("url")})
    if alertas.get("bajas_precio"):
        bajas = [c for c in resumen.get("cambios_precio_nuevos") or [] if c["nuevo"] < c["anterior"]]
        if bajas:
            lineas = [f"{c.get('proyecto') or '?'} {c.get('habs') or '?'} hab: {_m(c['anterior'])} → {_m(c['nuevo'])}"
                      for c in bajas[:8]]
            out.append({"titulo": f"Bajó el precio ({len(bajas)})", "texto": "\n".join(lineas),
                        "prioridad": "default", "url": url_dashboard})
    if alertas.get("usados_baratos"):
        ops = resumen.get("usados_oportunidad") or []
        if ops:
            lineas = [f"{o['zona']} {o.get('habs') or '?'} hab {o['area']:.0f} m² {_m(o['precio'])}"
                      f" (−{o['descuento'] * 100:.0f} % vs. {o['grupo']} similares)" for o in ops[:5]]
            out.append({"titulo": f"Usados por debajo de la mediana ({len(ops)})", "texto": "\n".join(lineas),
                        "prioridad": "default", "url": ops[0].get("url") if len(ops) == 1 else url_dashboard})
    if alertas.get("fallas") and (resumen.get("errores") or resumen.get("parcial")):
        detalle = "; ".join(resumen.get("errores") or []) or "corrida parcial (algún sector o barrio falló)"
        out.append({"titulo": "Corrida con problemas", "texto": detalle[:500], "prioridad": "high",
                    "url": None})
    return out


def tema_ntfy() -> str | None:
    t = os.environ.get("VIVIENDA_NTFY_TEMA")
    if not t and ARCHIVO_TEMA.exists():
        t = ARCHIVO_TEMA.read_text(encoding="utf-8").strip()
    return t or None


def enviar_ntfy(tema: str, msg: dict, servidor: str = "https://ntfy.sh") -> None:
    req = urllib.request.Request(f"{servidor.rstrip('/')}/{tema}", data=msg["texto"].encode("utf-8"),
                                 method="POST")
    # Los encabezados HTTP deben ser latin-1: ntfy acepta RFC 2047 para títulos con tildes
    req.add_header("Title", "=?UTF-8?B?" + __import__("base64").b64encode(msg["titulo"].encode()).decode() + "?=")
    req.add_header("Priority", msg.get("prioridad") or "default")
    req.add_header("Tags", "house")
    if msg.get("url"):
        req.add_header("Click", msg["url"])
    urllib.request.urlopen(req, timeout=20).read()


# ---------------------------------------------------------------- publicación
def sanear(datos: dict) -> dict:
    """Copia del dashboard apta para un sitio público: sin texto de anuncios ni datos del anunciante."""
    d = dict(datos)
    d["usados"] = [{k: v for k, v in u.items() if k not in CAMPOS_PRIVADOS_USADO} for u in datos.get("usados") or []]
    return d


def preparar_docs(destino: Path = DOCS) -> list[Path]:
    """docs/ = lo único que sirve GitHub Pages: web/index.html + dashboard saneado (mismas rutas relativas)."""
    from vivienda.pipeline import exportar
    datos = json.loads(exportar.ARCHIVO.read_text(encoding="utf-8"))
    (destino / "web").mkdir(parents=True, exist_ok=True)
    (destino / "data" / "processed").mkdir(parents=True, exist_ok=True)
    shutil.copy2(cfgmod.ROOT / "web" / "index.html", destino / "web" / "index.html")
    (destino / "data" / "processed" / "dashboard.json").write_text(
        json.dumps(sanear(datos), ensure_ascii=False, indent=1), encoding="utf-8")
    (destino / "index.html").write_text(
        '<!doctype html><meta charset="utf-8"><meta http-equiv="refresh" content="0; url=web/">'
        '<a href="web/">Dashboard</a>', encoding="utf-8")
    (destino / ".nojekyll").write_text("", encoding="utf-8")
    return [destino]


def git_publicar(hoy: date, raiz: Path = cfgmod.ROOT) -> str:
    """git add (código + docs/) → commit → push, solo si hay cambios. -> texto de lo que pasó."""
    def git(*a, check=True):
        return subprocess.run(["git", *a], cwd=raiz, capture_output=True, text=True, check=check)
    if not (raiz / ".git").exists():
        return "sin repositorio git (publicación omitida): corre scripts/configurar_github.sh"
    git("add", "-A")   # .gitignore decide qué queda fuera (data/, logs/, .run/, proposals/, ntfy_tema.txt)
    if git("diff", "--cached", "--quiet", check=False).returncode == 0:
        return "sin cambios que publicar"
    git("commit", "-m", f"corrida {hoy.isoformat()}")
    r = git("push", "-u", "origin", "HEAD", check=False)
    if r.returncode != 0:
        raise RuntimeError(f"git push falló: {(r.stderr or r.stdout).strip()[:300]}")
    return "publicado"
