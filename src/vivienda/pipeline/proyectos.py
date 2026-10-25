"""Registro de proyectos: agrupa tipologías en proyectos con ID estable (PRY-0001).

Archivo: data/processed/proyectos.json
- Los IDs los asigna solo este módulo.
- Nunca se borra un proyecto: si todas sus tipologías desaparecen, queda activo=false.
- Ubicación y enriquecimiento los escribe el merger (pipeline/aplicar.py), no este módulo.
"""
from __future__ import annotations

import json
from pathlib import Path
from urllib.parse import urlparse

from vivienda.config import PROCESSED_DIR
from vivienda.texto import slug

ARCHIVO = PROCESSED_DIR / "proyectos.json"


def clave_proyecto(t: dict) -> str:
    """'https://www.estrenarvivienda.com/metro-73/52297' + Bogotá -> 'estrenarvivienda:metro-73:bogota'"""
    if t.get("proyecto_clave"):
        return t["proyecto_clave"]
    partes = [p for p in urlparse(t.get("url") or "").path.split("/") if p]
    nombre = partes[0] if partes else slug(t.get("proyecto"))
    return f"{t['fuente']}:{nombre}:{slug(t.get('ciudad'))}"


def url_proyecto(clave: str) -> str | None:
    fuente, nombre, ciudad = clave.split(":")
    if fuente == "estrenarvivienda":
        return f"https://www.estrenarvivienda.com/{nombre}/{ciudad}"
    return None


def cargar(path: Path = ARCHIVO) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {p["id"]: p for p in json.loads(path.read_text(encoding="utf-8"))}


def guardar(proyectos: dict[str, dict], path: Path = ARCHIVO) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(sorted(proyectos.values(), key=lambda p: p["id"]),
                               ensure_ascii=False, indent=1), encoding="utf-8")


def _siguiente_id(proyectos: dict[str, dict]) -> str:
    n = max((int(i.split("-")[1]) for i in proyectos), default=0) + 1
    return f"PRY-{n:04d}"


def sincronizar(tipologias: dict[str, dict], proyectos: dict[str, dict]) -> list[str]:
    """Actualiza `proyectos` en sitio a partir del historial de tipologías. Devuelve IDs nuevos."""
    grupos: dict[str, list[dict]] = {}
    for t in tipologias.values():
        grupos.setdefault(clave_proyecto(t), []).append(t)

    por_clave = {p["clave"]: p for p in proyectos.values()}
    nuevos = []
    for clave, ts in sorted(grupos.items()):
        p = por_clave.get(clave)
        if p is None:
            p = {"id": _siguiente_id(proyectos), "clave": clave, "ubicacion": None,
                 "zona": None, "enriquecimiento": {}}
            proyectos[p["id"]] = p
            nuevos.append(p["id"])
        ref = max(ts, key=lambda t: t.get("ultimo_visto", ""))
        p.update(
            nombre=ref.get("proyecto"),
            constructora=ref.get("constructora"),
            sector=ref.get("sector"),
            ciudad=ref.get("ciudad"),
            url=url_proyecto(clave),
            zonas_candidatas=sorted({z for t in ts for z in t.get("zonas_candidatas") or []}),
            tipologias=sorted(f"{t['fuente']}:{t['typology_id']}" for t in ts),
            primer_visto=min(t.get("primer_visto", "") for t in ts),
            activo=any(t.get("activo") for t in ts),
        )
    return nuevos


def rezonificar(proyectos: dict[str, dict], zonas: dict) -> None:
    """Recalcula la zona de todos los proyectos ubicados (idempotente). Así un cambio en
    config.toml (sectores) o en zonas.geojson se refleja sin volver a geocodificar."""
    from vivienda import geo
    for p in proyectos.values():
        u = p.get("ubicacion")
        if u:
            p["zona"], p["zona_nota"] = geo.asignar_zona(u["lat"], u["lng"], p.get("zonas_candidatas"), zonas)


def pendientes(proyectos: dict[str, dict], limite: int | None = None, incluir_datos: bool = False) -> list[dict]:
    """Proyectos activos sin ubicación confiable (alta/media). Con incluir_datos=True, también
    los que tienen ubicación pero les faltan datos clave (más turnos de IA)."""
    def falta(p):
        u = p.get("ubicacion") or {}
        e = p.get("enriquecimiento") or {}
        sin_ubic = u.get("precision") not in ("alta", "media")
        sin_datos = not all(k in e for k in ("estrato", "admin_m2", "ascensor", "renta_corta"))
        return p.get("activo") and (sin_ubic or (incluir_datos and sin_datos))

    lista = sorted((p for p in proyectos.values() if falta(p)),
                   key=lambda p: (bool(p.get("ubicacion")), p["id"]))
    return lista[:limite] if limite else lista
