"""Descarga de listados de Fincaraíz por barrio.

Lógica heredada del proyecto anterior (fincaraiz_scraper.py, confirmada contra el sitio real):
- Los datos vienen en el <script id="__NEXT_DATA__"> -> props.pageProps.fetchResult.searchFast
  {data: [...anuncios], paginatorInfo: {currentPage, lastPage, total}}.
- Bogotá (Patrón B): /venta/{barrio_path}/bogota[/paginaN]?ordenListado=3 — trae todos los tipos;
  el tipo se filtra en código.
- Floridablanca (Patrón C): /venta/{apartamentos|apartaestudios}/{barrio}/floridablanca/floridablanca
  — un fetch por tipo.
- La paginación es un SEGMENTO de la ruta (/pagina2); ?pagina=2 se ignora en silencio.
- barrio_path no siempre es un slug corto: 'san-felipe' resuelve a otro lugar del país;
  hay que usar 'san-felipe/zona-noroccidente'. Cada barrio nuevo se confirma comparando el
  'total' (vivienda usados --probar) con lo que muestra la página en el navegador.
- Cortesía: 3–6 s entre peticiones y una pausa de 15–25 s cada 10 (un ritmo constante es detectable).
"""
from __future__ import annotations

import json
import random
import re
import time
from dataclasses import dataclass
from pathlib import Path

import requests

BASE_URL = "https://www.fincaraiz.com.co"
ORDEN_RECIENTES = "?ordenListado=3"
TIPOS_URL = {"apartamento": "apartamentos", "apartaestudio": "apartaestudios"}

# ciudad -> patrón de URL por barrio (confirmado; no generalizar a ciudades nuevas sin probar)
PATRON_CIUDAD = {
    "bogota": {"incluye_tipo": False, "sufijo": "bogota"},
    "floridablanca": {"incluye_tipo": True, "sufijo": "floridablanca/floridablanca"},
}

HEADERS = {
    "User-Agent": ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
                   "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"),
    "Accept-Language": "es-CO,es;q=0.9",
}

_NEXT_DATA = re.compile(r'<script id="__NEXT_DATA__"[^>]*>(.*?)</script>', re.DOTALL)
_SENALES_BLOQUEO = ("captcha", "cloudflare", "access denied", "acceso denegado", "unusual traffic",
                    "verifying you are human", "attention required")


def url_barrio(barrio_path: str, ciudad: str, pagina: int = 1, tipo: str | None = None,
               operacion: str = "venta") -> str:
    patron = PATRON_CIUDAD.get(ciudad)
    if patron is None:
        raise ValueError(f"'{ciudad}' no tiene patrón de URL por barrio confirmado (hoy: {sorted(PATRON_CIUDAD)})")
    partes = [BASE_URL, operacion]
    if patron["incluye_tipo"] and tipo is None:
        raise ValueError(f"'{ciudad}' requiere el tipo en la URL")
    if tipo is not None:   # Bogotá admite el tipo como filtro opcional: /venta/apartaestudios/{barrio}/bogota
        partes.append(TIPOS_URL[tipo])
    partes += [barrio_path.strip("/"), patron["sufijo"]]
    url = "/".join(partes)
    if pagina > 1:
        url += f"/pagina{pagina}"
    return url + ORDEN_RECIENTES


def extraer_next_data(html: str) -> dict | None:
    m = _NEXT_DATA.search(html or "")
    if not m:
        return None
    try:
        return json.loads(m.group(1))
    except json.JSONDecodeError:
        return None


def search_fast(next_data: dict) -> tuple[list[dict], dict]:
    """-> (anuncios, paginatorInfo). KeyError con mensaje claro si el sitio cambió la estructura."""
    try:
        sf = next_data["props"]["pageProps"]["fetchResult"]["searchFast"]
    except (KeyError, TypeError) as e:
        raise KeyError("no está props.pageProps.fetchResult.searchFast en __NEXT_DATA__: "
                       "el sitio cambió; correr `vivienda usados --probar` y revisar la muestra guardada") from e
    return sf.get("data") or [], sf.get("paginatorInfo") or {}


def diagnosticar(html: str) -> str:
    """Hipótesis de por qué una página no trae __NEXT_DATA__."""
    low = (html or "").lower()
    for s in _SENALES_BLOQUEO:
        if s in low:
            return f"posible bloqueo anti-bot (aparece '{s}')"
    if len(low) < 2000:
        return f"HTML muy corto ({len(low)} caracteres): no parece la página real"
    if "<script" not in low:
        return "sin <script>: no parece una página Next.js"
    return "estructura desconocida: el sitio pudo cambiar"


@dataclass
class Pagina:
    url: str
    anuncios: list[dict]
    paginador: dict
    error: str | None = None


class ClienteFincaraiz:
    def __init__(self, pausa=(3.0, 6.0), cada=10, descanso=(15.0, 25.0), timeout=20, reintentos=3,
                 dir_debug: Path | None = None, avisar=print):
        self.s = requests.Session()
        self.s.headers.update(HEADERS)
        self.pausa, self.cada, self.descanso = pausa, cada, descanso
        self.timeout, self.reintentos = timeout, reintentos
        self.dir_debug, self.avisar = dir_debug, avisar
        self.peticiones = 0

    def _esperar(self) -> None:
        if self.peticiones == 0:
            return
        if self.peticiones % self.cada == 0:
            t = random.uniform(*self.descanso)
            self.avisar(f"    [pausa larga {t:.0f} s tras {self.peticiones} páginas]")
        else:
            t = random.uniform(*self.pausa)
        time.sleep(t)

    def _get(self, url: str) -> tuple[str | None, str]:
        ultimo = ""
        for intento in range(1, self.reintentos + 1):
            self._esperar()
            self.peticiones += 1
            try:
                r = self.s.get(url, timeout=self.timeout)
                if r.status_code == 200:
                    return r.text, "ok"
                ultimo = f"HTTP {r.status_code}"
                if r.status_code in (403, 429):     # bloqueo o límite: insistir empeora
                    return None, ultimo + " (bloqueo o límite del sitio)"
            except requests.RequestException as e:
                ultimo = f"error de red: {e.__class__.__name__}"
            time.sleep(2 * intento)
        return None, ultimo

    def pagina(self, url: str, etiqueta: str = "pagina") -> Pagina:
        html, estado = self._get(url)
        if html is None:
            return Pagina(url, [], {}, estado)
        nd = extraer_next_data(html)
        if nd is None:
            motivo = diagnosticar(html)
            if self.dir_debug:
                self.dir_debug.mkdir(parents=True, exist_ok=True)
                (self.dir_debug / f"{etiqueta}.html").write_text(html, encoding="utf-8")
                motivo += f" (HTML guardado en {self.dir_debug / (etiqueta + '.html')})"
            return Pagina(url, [], {}, motivo)
        try:
            items, pag = search_fast(nd)
        except KeyError as e:
            if self.dir_debug:
                self.dir_debug.mkdir(parents=True, exist_ok=True)
                (self.dir_debug / f"{etiqueta}_next_data.json").write_text(
                    json.dumps(nd, ensure_ascii=False, indent=1), encoding="utf-8")
            return Pagina(url, [], {}, str(e))
        return Pagina(url, items, pag)
