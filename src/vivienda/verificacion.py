"""Verificaciones externas de una ubicación propuesta.

1. Evidencia: la dirección propuesta aparece en la página citada (que no sea un agregador).
2. Calle: el reverse geocoding de OpenStreetMap (Nominatim) en esas coordenadas
   devuelve la calle principal o la transversal de la dirección.

Nominatim exige máximo 1 petición por segundo y un User-Agent identificable.
"""
from __future__ import annotations

import re
import time

import requests
from bs4 import BeautifulSoup

from vivienda import reglas
from vivienda.texto import normalizar, sin_tildes, solo_alfanumerico

NOMINATIM = "https://nominatim.openstreetmap.org/reverse"

_TIPOS = {
    "calle": "calle", "cl": "calle", "cll": "calle", "clle": "calle",
    "carrera": "carrera", "cra": "carrera", "kr": "carrera", "kra": "carrera", "cr": "carrera", "carr": "carrera",
    "avenida": "avenida", "av": "avenida", "ak": "carrera", "ac": "calle",
    "diagonal": "diagonal", "dg": "diagonal", "diag": "diagonal",
    "transversal": "transversal", "tv": "transversal", "tr": "transversal", "trans": "transversal",
}
_OPUESTO = {"calle": "carrera", "carrera": "calle", "diagonal": "transversal", "transversal": "diagonal"}
_N = r"\d+(?:\s?[a-z](?![a-z]))?"  # número con letra opcional: 68, 68A, 68 A (no la 'c' de 'con')
_RE_DIR = re.compile(rf"^\s*(?:(?:avenida|av)\.?\s+)?([a-z]+)\.?\s*({_N})\s*(?:bis\s*(?:[a-z](?![a-z]))?\s*)?"
                     rf"(?:#|no\.?|n°|numero)?\s*({_N})\s*-\s*\d")


def partes_direccion(direccion: str | None) -> tuple[str, str, str, str] | None:
    """'Calle 105 # 23-42' -> ('calle','105','carrera','23')  (vía principal y vía que cruza)"""
    d = sin_tildes(direccion).replace("#", " # ")
    m = _RE_DIR.match(d)
    if not m:
        return None
    tipo = _TIPOS.get(m.group(1))
    if tipo not in _OPUESTO:
        return None
    return tipo, m.group(2).replace(" ", ""), _OPUESTO[tipo], m.group(3).replace(" ", "")


def vias_de_direccion(direccion: str) -> set[tuple[str, str]]:
    """'Calle 67 # 5-30' -> {('calle','67'), ('carrera','5')}"""
    p = partes_direccion(direccion)
    return {(p[0], p[1]), (p[2], p[3])} if p else set()


def via_de_calle_osm(nombre: str | None) -> tuple[str, str] | None:
    """'Avenida Calle 72' -> ('calle','72') ; 'Carrera 7' -> ('carrera','7')"""
    toks = normalizar(nombre).split()
    for i, t in enumerate(toks):
        tipo = _TIPOS.get(t)
        if tipo and tipo != "avenida" and i + 1 < len(toks):
            num = re.match(r"\d+[a-z]?", toks[i + 1])
            if num:
                return tipo, num.group()
    return None


_RE_PLACE = re.compile(r"!3d(-?\d+\.\d+)!4d(-?\d+\.\d+)")           # pin del lugar (Google Maps)
_RE_PARAM = re.compile(r"[?&](?:q|ll|query|center)=(-?\d+\.\d+)(?:,|%2C)\s*(-?\d+\.\d+)")  # q=lat,lng / Waze ll=
_RE_ARROBA = re.compile(r"@(-?\d+\.\d+),(-?\d+\.\d+)")                # centro de la vista (último recurso)


def coords_de_enlace(url: str | None) -> tuple[float, float] | None:
    """Extrae coordenadas de un enlace de Google Maps o Waze.
    Prioridad: pin del lugar (!3d/!4d) > parámetro q/ll > centro de la vista (@lat,lng)."""
    if not url:
        return None
    for rx in (_RE_PLACE, _RE_PARAM, _RE_ARROBA):
        m = rx.search(url)
        if m:
            return float(m.group(1)), float(m.group(2))
    return None


class Verificador:
    def __init__(self, user_agent: str, pausa: float = 1.1, timeout: float = 20):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = user_agent
        self.pausa, self.timeout = pausa, timeout
        self._ultimo = 0.0

    def evidencia(self, url: str | None, direccion: str | None) -> tuple[str, str]:
        """-> (resultado, detalle). resultado: 'ok' | 'no_encontrada' | 'agregador' | 'error'"""
        if not reglas.es_url(url) or not direccion:
            return "error", "falta URL o dirección"
        if reglas.es_agregador(url):
            return "agregador", "los agregadores no cuentan como evidencia"
        try:
            r = self.s.get(url, timeout=self.timeout)
            r.raise_for_status()
        except requests.RequestException as e:
            return "error", e.__class__.__name__
        # se compara solo la secuencia numérica: 'Calle 67 # 5-30' y 'Cl 67 No. 5 - 30' -> '67 5 30'
        numeros = lambda txt: " ".join(re.findall(r"\b\d+[a-z]?\b", solo_alfanumerico(txt)))
        nums = numeros(direccion)
        texto = BeautifulSoup(r.text, "lxml").get_text(" ")
        if nums and f" {nums} " in f" {numeros(texto)} ":
            return "ok", f"'{nums}' encontrado en la página"
        return "no_encontrada", f"'{nums}' no aparece en la página"

    def calle_en(self, lat: float, lng: float) -> str | None:
        espera = self.pausa - (time.monotonic() - self._ultimo)
        if espera > 0:
            time.sleep(espera)
        try:
            r = self.s.get(NOMINATIM, timeout=self.timeout, params={
                "lat": lat, "lon": lng, "format": "jsonv2", "zoom": 17, "addressdetails": 1})
            r.raise_for_status()
            addr = r.json().get("address", {})
        except (requests.RequestException, ValueError):
            return None
        finally:
            self._ultimo = time.monotonic()
        return addr.get("road")
