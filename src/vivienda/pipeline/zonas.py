"""Zonas del radar.

Por defecto cada zona es un círculo (centro + radio en config/zonas.toml): instantáneo, sin internet.

Opcional: si la zona trae `esquinas` (cruces de vías en orden, p. ej. "Calle 39 con Avenida Caracas"),
`vivienda zonas` las ubica UNA vez en OpenStreetMap y guarda el polígono en
data/processed/zonas_esquinas.json. Es lento (una consulta por esquina), por eso no corre en el
proceso diario: se lanza a mano o de noche. Mientras no exista el polígono, o si falló alguna
esquina, la zona sigue siendo el círculo. Solo se recalcula si cambian las esquinas o con --forzar.
"""
from __future__ import annotations

import hashlib
import json
import math
import tomllib
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from vivienda.config import CONFIG_DIR, PROCESSED_DIR

ARCHIVO_TOML = CONFIG_DIR / "zonas.toml"
ARCHIVO_ESQUINAS = PROCESSED_DIR / "zonas_esquinas.json"


def circulo(centro: list[float], radio_m: float, n: int = 36) -> list[list[float]]:
    """-> anillo GeoJSON [[lng, lat], ...] cerrado."""
    lat0, lng0 = centro
    anillo = [[round(lng0 + radio_m / (111_320 * math.cos(math.radians(lat0))) * math.sin(2 * math.pi * i / n), 6),
               round(lat0 + radio_m / 111_320 * math.cos(2 * math.pi * i / n), 6)] for i in range(n)]
    return anillo + [anillo[0]]


def cargar_definiciones(path: Path = ARCHIVO_TOML) -> list[dict]:
    with open(path, "rb") as f:
        zonas = tomllib.load(f).get("zona", [])
    for z in zonas:
        if not (z.get("id") and z.get("centro") and z.get("radio_m")):
            raise ValueError(f"zonas.toml: la zona {z.get('id')!r} necesita id, centro y radio_m")
        if z.get("esquinas") and len(z["esquinas"]) < 3:
            raise ValueError(f"zonas.toml: la zona {z['id']!r} necesita al menos 3 esquinas (o ninguna)")
    return zonas


def firma(esquinas: list[str]) -> str:
    return hashlib.sha1("|".join(esquinas).encode()).hexdigest()[:12]


def cargar_poligonos(path: Path = ARCHIVO_ESQUINAS) -> dict:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def poligono_vigente(z: dict, cache: dict) -> list[list[float]] | None:
    """Polígono calculado para esta zona, solo si corresponde a sus esquinas actuales y salió completo."""
    c = cache.get(z["id"])
    if z.get("esquinas") and c and c.get("firma") == firma(z["esquinas"]) and c.get("anillo"):
        return c["anillo"]
    return None


ARCHIVO_DIBUJADAS = Path(__file__).resolve().parents[3] / "config" / "zonas_dibujadas.geojson"


def cargar_dibujadas(path: Path | None = None) -> dict[str, list[list[float]]]:
    """Polígonos dibujados a mano (p. ej. en geojson.io): Feature con properties.id = id de la zona.
    Tienen prioridad sobre esquinas y círculo. -> {id: anillo [[lng, lat], ...]}"""
    path = path or ARCHIVO_DIBUJADAS
    try:
        datos = json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}
    out = {}
    for f in datos.get("features", []):
        zid = (f.get("properties") or {}).get("id")
        g = f.get("geometry") or {}
        if zid and g.get("type") == "Polygon" and g.get("coordinates") and len(g["coordinates"][0]) >= 4:
            out[zid] = [[round(x, 6), round(y, 6)] for x, y, *_ in g["coordinates"][0]]
    return out


def a_geojson(definiciones: list[dict], cache: dict | None = None, dibujadas: dict | None = None) -> dict:
    cache = cache if cache is not None else {}
    dibujadas = dibujadas or {}
    feats = []
    for z in definiciones:
        anillo = dibujadas.get(z["id"]) or (None if z["id"] in dibujadas else poligono_vigente(z, cache))
        feats.append({
            "type": "Feature",
            "properties": {"id": z["id"], "nombre": z.get("nombre"), "ciudad": z.get("ciudad"),
                           "descripcion": z.get("descripcion"), "centro": z["centro"], "radio_m": z["radio_m"],
                           "forma": "dibujada" if z["id"] in dibujadas else "esquinas" if anillo else "circulo"},
            "geometry": {"type": "Polygon", "coordinates": [anillo or circulo(z["centro"], z["radio_m"])]},
        })
    return {"type": "FeatureCollection", "features": feats}


@dataclass
class ResumenZonas:
    calculadas: list[str] = field(default_factory=list)
    al_dia: list[str] = field(default_factory=list)
    sin_esquinas: list[str] = field(default_factory=list)
    fallidas: list[str] = field(default_factory=list)    # 'zona: esquina -> motivo'


def calcular(definiciones: list[dict], geocod, hoy: date, forzar: bool = False,
             solo: list[str] | None = None, path: Path = ARCHIVO_ESQUINAS, avisar=print) -> ResumenZonas:
    """Ubica las esquinas de cada zona (las que cambiaron) y guarda los polígonos completos."""
    from vivienda import geo   # import tardío: geo no depende de este módulo

    cache = cargar_poligonos(path)
    circulos = a_geojson(definiciones)        # caja de búsqueda alrededor de cada zona
    res = ResumenZonas()
    for z in definiciones:
        if solo and z["id"] not in solo:
            continue
        esq = z.get("esquinas") or []
        if not esq:
            res.sin_esquinas.append(z["id"])
            continue
        if not forzar and poligono_vigente(z, cache):
            res.al_dia.append(z["id"])
            continue
        anillo, fallas = [], []
        if hasattr(geocod, "cruces_en_caja"):
            # una sola consulta por zona; margen corto: las esquinas de un cuadro quedan a ≤ r·√2 del centro
            caja = geo.bbox_zonas([z["id"]], circulos, margen_m=700)
            avisar(f"  {z['id']}: descargando calles de la zona (una consulta) …")
            resultados = geocod.cruces_en_caja(esq, caja)
        else:
            caja = geo.bbox_zonas([z["id"]], circulos, margen_m=1500)
            resultados = [geocod.cruce_detallado(e, z.get("ciudad"), bbox=caja) for e in esq]
        for e, (r, motivo) in zip(esq, resultados):
            if r:
                anillo.append([round(r[1], 6), round(r[0], 6)])
            else:
                fallas.append(f"{e} → {motivo}")
        if fallas:
            res.fallidas += [f"{z['id']}: {f}" for f in fallas]
            previo = poligono_vigente(z, cache)   # con --forzar: si falla, se conserva el que ya servía
            cache[z["id"]] = {"firma": firma(esq), "anillo": previo, "fallas": fallas, "calculado": hoy.isoformat()}
        else:
            cache[z["id"]] = {"firma": firma(esq), "anillo": anillo + [anillo[0]], "calculado": hoy.isoformat()}
            res.calculadas.append(z["id"])
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(cache, ensure_ascii=False, indent=1), encoding="utf-8")  # guarda a medida que avanza
    return res
