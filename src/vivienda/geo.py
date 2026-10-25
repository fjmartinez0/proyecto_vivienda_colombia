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


def asignar_zona(lat: float, lng: float, candidatas: list[str] | None, zonas_geojson: dict) -> tuple[str | None, None]:
    """Zona de un proyecto. El sector del sitio (o la zona del proyecto manual) manda:
    - una zona candidata -> esa;
    - varias (p. ej. Chapinero -> universitaria o calle 72) -> la de centro más cercano;
    - ninguna -> el círculo que contenga el punto, si hay.
    Devuelve (zona, None): ya no hay notas de borde."""
    candidatas = list(candidatas or [])
    if len(candidatas) == 1:
        return candidatas[0], None
    if candidatas:
        centros = {f["properties"]["id"]: _centro(f) for f in zonas_geojson["features"]}
        z = min((c for c in candidatas if c in centros), key=lambda c: distancia_m(lat, lng, *centros[c]), default=None)
        return z, None
    return zona_de(lat, lng, zonas_geojson), None


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
