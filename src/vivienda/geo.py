"""Geometría simple sin dependencias: polígonos de zona, cajas por ciudad, distancias."""
from __future__ import annotations

import math

from vivienda.texto import normalizar

# Cajas generosas por municipio (lat_min, lat_max, lng_min, lng_max).
# Sirven para descartar coordenadas absurdas, no para asignar zona.
BBOX_CIUDAD = {
    "bogota": (4.45, 4.85, -74.25, -73.98),
    "floridablanca": (7.03, 7.09, -73.13, -73.07),  # estrecha: Bucaramanga repite numeración
    "bucaramanga": (7.03, 7.19, -73.18, -73.05),
}


def en_bbox(lat: float, lng: float, ciudad: str | None) -> bool:
    caja = BBOX_CIUDAD.get(normalizar(ciudad))
    if not caja:
        return False
    return caja[0] <= lat <= caja[1] and caja[2] <= lng <= caja[3]


def punto_en_poligono(lat: float, lng: float, anillo: list[list[float]]) -> bool:
    """anillo en formato GeoJSON: [[lng, lat], ...]"""
    dentro = False
    j = len(anillo) - 1
    for i in range(len(anillo)):
        xi, yi = anillo[i]
        xj, yj = anillo[j]
        if (yi > lat) != (yj > lat) and lng < (xj - xi) * (lat - yi) / (yj - yi) + xi:
            dentro = not dentro
        j = i
    return dentro


def zona_de(lat: float, lng: float, zonas_geojson: dict) -> str | None:
    """Zona que contiene el punto. Las zonas se traslapan (el corredor es grande y se come el borde de
    Pasadena; Teusaquillo y Chapinero comparten borde): si hay varias, gana la que tenga el punto
    más cerca de su centro en proporción a su radio. Así una zona grande no se traga a las chicas."""
    def cercania(f):
        c, r = _centro(f), f["properties"].get("radio_m") or 1000
        return distancia_m(lat, lng, *c) / r
    dentro = [f for f in zonas_geojson["features"] if punto_en_poligono(lat, lng, f["geometry"]["coordinates"][0])]
    return min(dentro, key=cercania)["properties"]["id"] if dentro else None


def distancia_m(lat1: float, lng1: float, lat2: float, lng2: float) -> float:
    r = 6_371_000
    p1, p2 = math.radians(lat1), math.radians(lat2)
    dp, dl = p2 - p1, math.radians(lng2 - lng1)
    a = math.sin(dp / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dl / 2) ** 2
    return 2 * r * math.asin(math.sqrt(a))


def _centro(feature: dict) -> tuple[float, float]:
    c = feature["properties"].get("centro")
    if c:
        return c[0], c[1]
    anillo = feature["geometry"]["coordinates"][0]
    return (sum(p[1] for p in anillo) / len(anillo), sum(p[0] for p in anillo) / len(anillo))


TOLERANCIA_PROYECTO_M = 150   # error típico de la ubicación por cruce de vías + del dibujo de la zona


def distancia_a_poligono_m(lat: float, lng: float, anillo: list[list[float]]) -> float:
    """0 si el punto está dentro; si no, metros al borde más cercano (aproximación plana, sobra a esta escala)."""
    if punto_en_poligono(lat, lng, anillo):
        return 0.0
    kx = 111_320 * math.cos(math.radians(lat))
    ky = 110_574
    px, py = lng * kx, lat * ky
    mejor = float("inf")
    for (x1, y1), (x2, y2) in zip(anillo, anillo[1:] + anillo[:1]):
        ax, ay, bx, by = x1 * kx, y1 * ky, x2 * kx, y2 * ky
        dx, dy = bx - ax, by - ay
        t = 0.0 if dx == dy == 0 else max(0.0, min(1.0, ((px - ax) * dx + (py - ay) * dy) / (dx * dx + dy * dy)))
        mejor = min(mejor, math.hypot(px - (ax + t * dx), py - (ay + t * dy)))
    return mejor


def asignar_zona(lat: float, lng: float, candidatas: list[str] | None, zonas_geojson: dict,
                 tolerancia_m: float = TOLERANCIA_PROYECTO_M) -> tuple[str | None, str | None]:
    """Zona de un proyecto: la decide su punto (zonas bien demarcadas).
    - dentro de una zona -> esa; dentro de varias -> la candidata del sector, si no la de centro más cercano;
    - fuera pero a ≤ tolerancia del borde -> esa zona, con nota (absorbe el error de ubicación y del dibujo);
    - más lejos -> None (queda en 'fuera de zonas').
    -> (zona, nota)"""
    candidatas = list(candidatas or [])
    d = {f["properties"]["id"]: distancia_a_poligono_m(lat, lng, f["geometry"]["coordinates"][0])
         for f in zonas_geojson["features"]}
    dentro = [z for z, x in d.items() if x == 0]
    if not dentro:
        cerca = sorted((x, z) for z, x in d.items() if x <= tolerancia_m)
        if not cerca:
            return None, None
        return cerca[0][1], f"a {cerca[0][0]:.0f} m del borde de la zona"
    if len(dentro) == 1:
        return dentro[0], None
    pref = [z for z in dentro if z in candidatas] or dentro
    centros = {f["properties"]["id"]: _centro(f) for f in zonas_geojson["features"]}
    return min(pref, key=lambda z: distancia_m(lat, lng, *centros[z])), None


def bbox_zonas(ids: list[str] | None, zonas_geojson: dict, margen_m: float = 2500) -> tuple[float, float, float, float] | None:
    """Caja (lat_min, lat_max, lng_min, lng_max) que contiene las zonas indicadas, con margen."""
    pts = [p for f in zonas_geojson["features"] if f["properties"]["id"] in (ids or [])
           for p in f["geometry"]["coordinates"][0]]
    if not pts:
        return None
    dlat = margen_m / 111_320
    lat0 = sum(p[1] for p in pts) / len(pts)
    dlng = margen_m / (111_320 * math.cos(math.radians(lat0)))
    return (min(p[1] for p in pts) - dlat, max(p[1] for p in pts) + dlat,
            min(p[0] for p in pts) - dlng, max(p[0] for p in pts) + dlng)
