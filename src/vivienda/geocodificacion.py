"""Geocodificación determinística de direcciones colombianas por cruce de vías.

Una dirección colombiana trae su ubicación codificada:
    'Calle 105 # 23-42'  = sobre la Calle 105, a ~42 m de la Carrera 23.
Se buscan ambas vías en OpenStreetMap (API Overpass, gratuita) dentro de la ciudad y se toma
el punto donde se cruzan (o se acercan a menos de MAX_SEPARACION_M). Error típico: 50–100 m,
suficiente para asignar zona y mostrar en el mapa. No usa IA.
"""
from __future__ import annotations

import re
import time

import requests

from vivienda import geo
from vivienda.texto import normalizar
from vivienda.verificacion import partes_direccion

# Servidores públicos de Overpass: si uno falla o limita, se prueba el siguiente
OVERPASS_SERVIDORES = (
    "https://overpass-api.de/api/interpreter",
    "https://overpass.private.coffee/api/interpreter",
    "https://maps.mail.ru/osm/tools/overpass/api/interpreter",
)
MAX_SEPARACION_M = 200
TAGS_NOMBRE = ("name", "alt_name")   # más tags = consulta más pesada (el servidor la corta)

# Vías numeradas que OpenStreetMap suele nombrar por su nombre de avenida (Bogotá)
_ALIAS = {
    ("carrera", "14"): "Caracas", ("calle", "72"): "Avenida Chile", ("carrera", "30"): "Ciudad de Quito|NQS",
    ("calle", "26"): "El Dorado|Jorge Eli[eé]cer Gait[aá]n", ("carrera", "7"): "S[eé]ptima",
    ("calle", "100"): "Avenida Calle 100", ("carrera", "45"): "Autopista Norte", ("calle", "134"): "Avenida Calle 134",
    ("calle", "53"): "Pablo VI", ("calle", "63"): "Jos[eé] Celestino Mutis", ("carrera", "68"): "Avenida Carrera 68|Congreso Eucar[ií]stico",
    ("carrera", "50"): "Avenida Carrera 50", ("calle", "116"): "Pepe Sierra", ("carrera", "15"): "Avenida Carrera 15",
    ("transversal", "60"): "Avenida Suba",   # Tv 60 = Av. Suba entre Cl. 100 y 116 (Puente Largo)
}

_NOMBRE_TIPO = {"calle": "Calle", "carrera": "Carrera", "diagonal": "Diagonal", "transversal": "Transversal"}

# Dirección dentro de texto libre (fichas de proyecto, páginas de constructoras)
_RE_DIRECCION_TEXTO = re.compile(
    r"\b(?:Avenida\s+|Av\.?\s+)?(Calle|Carrera|Cra|Kra|Kr|Cr|Cll|Cl|Diagonal|Dg|Transversal|Tv|Ak|Ac)\.?\s*"
    r"(\d{1,3}\s?[A-Za-z]?)(?:\s*Bis\s*[A-Za-z]?)?\s*(?:#|No\.?|N°|Nº|Número)\s*(\d{1,3}\s?[A-Za-z]?)\s*-\s*(\d{1,3})\b",
    re.IGNORECASE)


_VIA_NUM = r"(?:(?:Avenida|Av\.?)\s+)?(?:Calle|Carrera|Cra|Kra|Kr|Cll|Cl|Diagonal|Dg|Transversal|Tv|Ak|Ac)\.?\s*\d{1,3}\s?[A-Za-z]?(?:\s*Bis)?"
# Cruce explícito: 'Carrera 53 con Calle 100', 'Av. Cra 68 con Calle 95'
_RE_CRUCE_TEXTO = re.compile(rf"\b({_VIA_NUM})\s+con\s+({_VIA_NUM})\b", re.IGNORECASE)


def extraer_direccion(texto: str) -> str | None:
    """Primera dirección en un texto. Prioridad: placa completa ('Cl. 105 No. 23 - 42' -> 'Cl 105 # 23-42');
    si no hay, un cruce explícito ('Carrera 53 con Calle 100')."""
    m = _RE_DIRECCION_TEXTO.search(texto or "")
    if m:
        tipo, n1, n2, n3 = (g.replace(" ", "") for g in m.groups())
        return f"{tipo} {n1.upper()} # {n2.upper()}-{n3}"
    m = _RE_CRUCE_TEXTO.search(texto or "")
    if m:
        return " ".join(f"{m.group(1)} con {m.group(2)}".split())
    return None


# Avenidas con nombre (Bogotá) -> regex sobre el nombre en OpenStreetMap
_AVENIDAS = {
    "circunvalar": "Circunvalar", "boyaca": "Boyac[aá]", "suba": "Avenida Suba",
    "autopista": "Autopista Norte", "caracas": "Caracas|^(Avenida )?Carrera 14( Bis)?$", "septima": "^(Avenida )?Carrera 7$",
    "pepe sierra": "Pepe Sierra", "chile": "^(Avenida )?Calle 72$",
}
_RE_VIA = re.compile(r"^(?:(?:avenida|av)\.?\s+)?([a-z]+)\.?\s*(\d+(?:\s?[a-z](?![a-z]))?)")
_TIPOS_VIA = {"calle": "calle", "cl": "calle", "cll": "calle", "ac": "calle",
              "carrera": "carrera", "cra": "carrera", "kr": "carrera", "kra": "carrera", "cr": "carrera", "ak": "carrera",
              "diagonal": "diagonal", "dg": "diagonal", "transversal": "transversal", "tv": "transversal"}


def _via(texto: str) -> tuple[str, str] | None:
    """Una vía suelta -> (regex OSM, etiqueta). 'Av. Cra 68' -> carrera 68 ; 'Av. Circunvalar' -> nombre."""
    t = normalizar(texto)
    for clave, patron in _AVENIDAS.items():
        if clave in t:
            return patron, clave.title()
    m = _RE_VIA.match(t)
    if m and _TIPOS_VIA.get(m.group(1)):
        tipo, num = _TIPOS_VIA[m.group(1)], m.group(2).replace(" ", "")
        return patron_via(tipo, num), f"{_NOMBRE_TIPO[tipo]} {num.upper()}"
    return None


def vias_para_cruce(direccion: str) -> tuple[tuple[str, str], tuple[str, str]] | None:
    """Dos vías a cruzar -> ((regex1, etiqueta1), (regex2, etiqueta2)).
    'Calle 105 # 23-42' -> Calle 105 × Carrera 23 ; 'Carrera 53 con Calle 100' -> Carrera 53 × Calle 100."""
    partes = partes_direccion(direccion)
    if partes:
        t1, n1, t2, n2 = partes
        return ((patron_via(t1, n1), f"{_NOMBRE_TIPO[t1]} {n1.upper()}"),
                (patron_via(t2, n2), f"{_NOMBRE_TIPO[t2]} {n2.upper()}"))
    trozos = re.split(r"\s+(?:con|y|x|&|esquina)\s+", normalizar(direccion))
    if len(trozos) == 2:
        v1, v2 = _via(trozos[0]), _via(trozos[1])
        if v1 and v2:
            return v1, v2
    return None


def patron_via(tipo: str, numero: str) -> str:
    """('carrera','68a') -> regex que acepta 'Carrera 68A', 'Carrera 68 A', 'Avenida Carrera 68A', '... Bis'."""
    m = re.match(r"(\d+)([a-z]?)", numero.lower())
    num, letra = m.group(1), m.group(2)
    sufijo = f" ?{letra.upper()}" if letra else ""
    base = f"^(Avenida )?{_NOMBRE_TIPO[tipo]} {num}{sufijo}( Bis)?( [A-Z])?$"
    alias = _ALIAS.get((tipo, num)) if not letra else None
    return f"{base}|{alias}" if alias else base


def consulta_overpass(patrones: list[str], bbox: tuple[float, float, float, float]) -> str:
    s, n, w, e = bbox  # BBOX_CIUDAD: (lat_min, lat_max, lng_min, lng_max)
    ways = "".join(f'way["highway"]["{t}"~"{p}",i]({s},{w},{n},{e});' for p in patrones for t in TAGS_NOMBRE)
    return f"[out:json][timeout:90];({ways});out geom;"


def punto_cruce(geom1: list[list[tuple[float, float]]], geom2: list[list[tuple[float, float]]],
                max_m: float = MAX_SEPARACION_M) -> tuple[float, float, float] | None:
    """Par de vértices más cercano entre dos conjuntos de vías -> (lat, lng, separación_m)."""
    mejor = None
    for w1 in geom1:
        for a in w1:
            for w2 in geom2:
                for b in w2:
                    d = geo.distancia_m(a[0], a[1], b[0], b[1])
                    if mejor is None or d < mejor[2]:
                        mejor = ((a[0] + b[0]) / 2, (a[1] + b[1]) / 2, d)
    return mejor if mejor and mejor[2] <= max_m else None


class Geocodificador:
    def __init__(self, user_agent: str, pausa: float = 2.0, timeout: float = 100):
        self.s = requests.Session()
        self.s.headers["User-Agent"] = user_agent
        self.pausa, self.timeout = pausa, timeout
        self._ultimo = 0.0

    def _overpass(self, q: str) -> tuple[list[dict] | None, str]:
        """-> (elementos | None, detalle del error). Prueba cada servidor; reintenta una vez si limita."""
        errores = []
        for url in OVERPASS_SERVIDORES:
            for intento in range(2):
                espera = self.pausa - (time.monotonic() - self._ultimo)
                if espera > 0:
                    time.sleep(espera)
                try:
                    r = self.s.post(url, data={"data": q}, timeout=self.timeout)
                    self._ultimo = time.monotonic()
                    if r.status_code == 429 and intento == 0:   # demasiadas peticiones: esperar y reintentar
                        time.sleep(10)
                        continue
                    r.raise_for_status()
                    return r.json().get("elements", []), "ok"
                except requests.HTTPError as e:
                    errores.append(f"{url.split('/')[2]}: HTTP {e.response.status_code}")
                except (requests.RequestException, ValueError) as e:
                    self._ultimo = time.monotonic()
                    errores.append(f"{url.split('/')[2]}: {e.__class__.__name__}")
                break
        return None, "; ".join(errores)

    def cruce_detallado(self, direccion: str, ciudad: str | None,
                        bbox: tuple[float, float, float, float] | None = None) -> tuple[tuple[float, float, str] | None, str]:
        """-> ((lat, lng, detalle) | None, motivo). El motivo explica exactamente qué falló.
        `bbox` acota la búsqueda (más liviana y sin homónimos lejanos); por defecto, toda la ciudad."""
        vias = vias_para_cruce(direccion)
        if not vias:
            return None, "formato de dirección no reconocido"
        bbox = bbox or geo.BBOX_CIUDAD.get(normalizar(ciudad))
        if not bbox:
            return None, f"ciudad sin caja definida: {ciudad}"
        (p1, e1), (p2, e2) = vias
        elementos, error = self._overpass(consulta_overpass([p1, p2], bbox))
        if elementos is None:
            return None, f"Overpass (OpenStreetMap) no respondió [{error}]; reintentar más tarde"
        return cruce_en(elementos, vias)

    def cruces_en_caja(self, direcciones: list[str], bbox: tuple[float, float, float, float]) -> list[tuple]:
        """Varias esquinas de una misma zona con UNA consulta liviana: todas las vías con nombre de la caja
        (sin regex en el servidor, que es lo que hace lentas y fallidas las consultas) y el cruce se
        resuelve aquí. -> [((lat, lng, detalle) | None, motivo)] en el mismo orden."""
        s, n, w, e = bbox
        q = f'[out:json][timeout:120];way["highway"]["name"]({s},{w},{n},{e});out tags geom;'
        elementos, error = self._overpass(q)
        if elementos is None:
            return [(None, f"Overpass (OpenStreetMap) no respondió [{error}]; reintentar más tarde")] * len(direcciones)
        out = []
        for d in direcciones:
            vias = vias_para_cruce(d)
            out.append(cruce_en(elementos, vias) if vias else (None, "formato de dirección no reconocido"))
        return out

    def cruce(self, direccion: str, ciudad: str | None) -> tuple[float, float, str] | None:
        return self.cruce_detallado(direccion, ciudad)[0]


def cruce_en(elementos: list[dict], vias) -> tuple[tuple[float, float, str] | None, str]:
    """Cruce de dos vías dentro de elementos ya descargados de Overpass (geometría incluida)."""
    (p1, e1), (p2, e2) = vias
    r1, r2 = re.compile(p1, re.I), re.compile(p2, re.I)
    g1, g2 = [], []
    for el in elementos:
        tags = el.get("tags", {})
        nombres = [tags.get(t, "") for t in TAGS_NOMBRE]
        pts = [(g["lat"], g["lon"]) for g in el.get("geometry", [])]
        if any(r1.search(n) for n in nombres if n):
            g1.append(pts)
        elif any(r2.search(n) for n in nombres if n):
            g2.append(pts)
    faltan = [e for e, g in ((e1, g1), (e2, g2)) if not g]
    if faltan:
        return None, f"no existe en OSM con ese nombre: {', '.join(faltan)}"
    res = punto_cruce(g1, g2, max_m=10**7)
    lat, lng, sep = res
    if sep > MAX_SEPARACION_M:
        return None, f"{e1} y {e2} existen pero no se cruzan (lo más cerca: {sep:.0f} m)"
    return (lat, lng, f"cruce {e1} × {e2} (separación {sep:.0f} m)"), "ok"
