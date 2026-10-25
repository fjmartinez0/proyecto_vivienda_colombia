"""Anuncio de Fincaraíz (un item de searchFast.data) -> dict del radar.

Mapeo heredado del proyecto anterior (confirmado con datos reales):
- technicalSheet viene como lista [{field, value, text}] -> dict {field: value}.
- Administración = technicalSheet.commonExpenses (casi siempre vacía). price.admin_included NO es
  la administración: es precio + admin sumados.
- Área construida = m2Built ; área privada = m2apto.
- locations.neighbourhood/zone/locality son listas de objetos {id, name, slug}.
- link es relativo -> se completa con BASE_URL.
- isProject / isProjectUnit = vivienda nueva -> se excluye (aquí solo usados).
- Estrato válido 1–6 (llegan '110' y '0', que se descartan).
- to_number toma el PRIMER bloque numérico: '55 m2' -> 55, no 552.
Ascensor y parqueaderos no estaban en el proyecto anterior: se buscan de forma tolerante
(cualquier campo o facilidad que mencione ascensor/elevator, y la descripción).
"""
from __future__ import annotations

import re
from typing import Any

from vivienda.texto import normalizar

from .cliente import BASE_URL

TIPOS_VALIDOS = {"apartamento", "apartaestudio"}

# Antigüedad: buckets reales de Fincaraíz -> años (punto medio; extremos con ancla fija)
_ANTIGUEDAD = (("menor a 1", 0.5), ("1 a 8", 4.5), ("9 a 15", 12.0), ("16 a 30", 23.0), ("mas de 30", 35.0))

_RE_NUM = re.compile(r"\d[\d.,]*")
_RE_ASC_NO = re.compile(r"\bsin\s+ascensor\b|\bno\s+(?:tiene|hay|cuenta\s+con)\s+ascensor\b", re.I)
_RE_ASC_SI = re.compile(r"\bascensor(?:es)?\b|\belevador(?:es)?\b", re.I)
_NEGATIVOS = {"", "0", "no", "false", "ninguno", "n/a"}


def to_number(v: Any) -> float | int | None:
    if v is None or isinstance(v, bool):
        return None
    if isinstance(v, (int, float)):
        return v
    if isinstance(v, str):
        m = _RE_NUM.search(v.strip())
        if not m:
            return None
        token = m.group(0).rstrip(".,").replace(".", "").replace(",", ".")
        try:
            f = float(token)
        except ValueError:
            return None
        return int(f) if f.is_integer() else f
    return None


def ficha_tecnica(raw: Any) -> dict:
    out = {}
    if isinstance(raw, list):
        for it in raw:
            if isinstance(it, dict) and "field" in it:
                out[it["field"]] = it.get("value", it.get("text"))
    return out


def nombres(lista: Any) -> list[str]:
    if not isinstance(lista, list):
        return []
    return [e["name"] if isinstance(e, dict) else e for e in lista
            if (isinstance(e, dict) and e.get("name")) or isinstance(e, str)]


def estrato(v: Any) -> int | None:
    n = to_number(v)
    return int(n) if n is not None and int(n) in range(1, 7) else None


def antiguedad_anios(texto: Any) -> float | None:
    t = normalizar(str(texto)) if texto else ""
    for clave, anios in _ANTIGUEDAD:
        if clave in t:
            return anios
    return None


def _primero(*vals):
    return next((v for v in vals if v is not None and v != ""), None)


def _menciones_ascensor(obj: Any, ruta: str = "") -> list[tuple[str, Any]]:
    """Campos (fuera de la descripción) cuyo nombre o valor mencione ascensor/elevator."""
    hallazgos = []
    if isinstance(obj, dict):
        nombre = str(obj.get("field") or obj.get("name") or obj.get("text") or "")
        if re.search(r"ascensor|elevator", nombre, re.I):
            hallazgos.append((ruta, obj.get("value", True)))
        for k, v in obj.items():
            if k == "description":
                continue
            if re.search(r"ascensor|elevator", str(k), re.I):
                hallazgos.append((f"{ruta}.{k}", v))
            elif isinstance(v, (dict, list)):
                hallazgos += _menciones_ascensor(v, f"{ruta}.{k}")
    elif isinstance(obj, list):
        for i, v in enumerate(obj):
            if isinstance(v, str) and re.search(r"ascensor|elevator", v, re.I):
                hallazgos.append((f"{ruta}[{i}]", True))
            elif isinstance(v, (dict, list)):
                hallazgos += _menciones_ascensor(v, f"{ruta}[{i}]")
    return hallazgos


def ascensor(item: dict, pisos_edificio: float | None, piso: float | None = None) -> tuple[bool | None, str | None]:
    """-> (valor, de dónde salió). None = no se sabe.
    Orden: campo del anuncio > descripción > edificio de 6+ pisos o apartamento en piso 6+
    (la norma lo exige desde 6 pisos, así que es 'probable', no confirmado)."""
    for ruta, v in _menciones_ascensor(item):
        if isinstance(v, bool):
            return v, f"campo {ruta}"
        if v is None or normalizar(str(v)) in _NEGATIVOS:
            if v is not None:
                return False, f"campo {ruta}"
            continue
        return True, f"campo {ruta}"
    desc = item.get("description") or ""
    if _RE_ASC_NO.search(desc):
        return False, "descripción"
    if _RE_ASC_SI.search(desc):
        return True, "descripción"
    if pisos_edificio and pisos_edificio >= 6:
        return True, "probable (edificio de 6+ pisos)"
    if piso and piso >= 6:
        return True, "probable (apartamento en piso 6+)"
    return None, None


def amenidades(raw: Any) -> list[str]:
    """facilities: lista de objetos {name, ...} o de textos -> nombres, sin repetir."""
    out = []
    for f in raw if isinstance(raw, list) else []:
        n = f.get("name") if isinstance(f, dict) else f if isinstance(f, str) else None
        if n and n not in out:
            out.append(str(n).strip())
    return out


def parsear(item: dict) -> dict | None:
    """Item crudo -> anuncio del radar, o None si no sirve (sin id)."""
    if not isinstance(item, dict) or item.get("id") is None:
        return None
    ts = ficha_tecnica(item.get("technicalSheet"))
    loc = item.get("locations") or {}
    barrios, zonas, localidades = (nombres(loc.get(k)) for k in ("neighbourhood", "zone", "locality"))
    # Fincaraíz manda 0 cuando no sabe los pisos del edificio (visto en datos reales): 0 = sin dato
    pisos = to_number(_primero(item.get("floorsCount") or None, ts.get("story")))
    pisos = pisos or None
    piso = to_number(_primero(item.get("floor"), ts.get("floor")))
    asc, asc_fuente = ascensor(item, pisos, piso)
    link = item.get("link")
    tipo = ((item.get("property_type") or {}).get("name") or "").strip().lower() or None
    return {
        "id": str(item["id"]),
        "url": f"{BASE_URL}{link}" if link and link.startswith("/") else link,
        "tipo": tipo,
        "barrio": barrios[0] if barrios else None,
        "zona_portal": zonas[0] if zonas else None,
        "localidad": localidades[0] if localidades else None,
        "precio": to_number((item.get("price") or {}).get("amount")),
        "admin": to_number(ts.get("commonExpenses")),
        "habs": to_number(_primero(item.get("bedrooms"), ts.get("bedrooms"))),
        "banos": to_number(_primero(item.get("bathrooms"), ts.get("bathrooms"))),
        "area_construida": to_number(ts.get("m2Built")),
        "area_privada": to_number(ts.get("m2apto")),
        "piso": piso,
        "pisos_edificio": pisos,
        "estrato": estrato(_primero(item.get("stratum"), ts.get("stratum"))),
        "antiguedad_texto": ts.get("constructionYear"),
        "antiguedad": antiguedad_anios(ts.get("constructionYear")),
        "parq": to_number(_primero(item.get("garage"), ts.get("garage"), ts.get("garages"),
                                   ts.get("parking"), ts.get("parkingLots"))),
        "ascensor": asc,
        "ascensor_fuente": asc_fuente,
        "es_proyecto": bool(item.get("isProject") or item.get("isProjectUnit")),
        "lat": item.get("latitude"),
        "lng": item.get("longitude"),
        "publicador": (item.get("owner") or {}).get("type"),
        "actualizado_portal": item.get("updated_at"),
        "creado_portal": item.get("created_at"),       # para "publicado hace N días"
        "amenidades": amenidades(item.get("facilities")),
        "descripcion": " ".join((item.get("description") or "").split())[:700] or None,
    }
