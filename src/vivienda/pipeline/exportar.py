"""Genera data/processed/dashboard.json: lo único que lee el front end.

Solo se publican en el mapa los proyectos activos con ubicación y dentro de una zona.
Los demás se listan aparte (sin ubicar / fuera de zonas) para que se vean los pendientes.
"""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from vivienda import reglas
from vivienda.config import PROCESSED_DIR
from vivienda.pipeline.proyectos import clave_proyecto

ARCHIVO = PROCESSED_DIR / "dashboard.json"

_ESTADO = {"sobre planos": "Sobre planos", "en construccion": "En construcción",
           "entrega inmediata": "Entrega inmediata"}
_ACABADOS = {"full": "Full acabados", "semi": "Semi acabados", "obra gris": "Obra gris"}


def _valor(p: dict, campo: str, defecto=None):
    return ((p.get("enriquecimiento") or {}).get(campo) or {}).get("valor", defecto)


def _zona_mas_cercana(lat: float, lng: float, zonas: dict) -> tuple[str, float]:
    """Proyecto en seguimiento fuera de zonas: zona más cercana (para los supuestos de arriendo/ADR)."""
    from vivienda import geo
    return min(((f["properties"]["id"], geo.distancia_a_poligono_m(lat, lng, f["geometry"]["coordinates"][0]))
                for f in zonas["features"]), key=lambda x: x[1])


def construir(proyectos: dict[str, dict], tipologias: dict[str, dict], zonas: dict) -> dict:
    tips_por_clave: dict[str, list[dict]] = {}
    for t in tipologias.values():
        if t.get("activo"):
            tips_por_clave.setdefault(clave_proyecto(t), []).append(t)

    publicados, sin_ubicar, fuera = [], [], []
    for p in sorted(proyectos.values(), key=lambda x: x["id"]):
        ts = tips_por_clave.get(p["clave"], [])
        if not p.get("activo") or not ts:
            continue
        resumen = {"id": p["id"], "nombre": p.get("nombre"), "sector": p.get("sector"), "url": p.get("url")}
        u = p.get("ubicacion")
        if not u:
            sin_ubicar.append(resumen)
            continue
        zona_ref = None
        if not p.get("zona"):
            if not p.get("seguimiento"):
                fuera.append({**resumen, "lat": u["lat"], "lng": u["lng"]})
                continue
            zona_ref = _zona_mas_cercana(u["lat"], u["lng"], zonas)
        publicados.append({
            "id": p["id"],
            "nombre": p.get("nombre"),
            "constructora": p.get("constructora"),
            "zona": p.get("zona") or zona_ref[0],
            "fuera_de_zona": zona_ref is not None,
            "distancia_zona_m": round(zona_ref[1]) if zona_ref else None,
            "lat": u["lat"], "lng": u["lng"],
            "direccion": u.get("direccion"),
            "precision": u.get("precision"),
            "ubicacion_agregador": reglas.es_agregador(u.get("fuente")),
            "ubicacion_metodo": u.get("metodo"),
            "zona_nota": p.get("zona_nota"),
            "estado": _ESTADO.get(_valor(p, "estado_obra"), "Sin dato"),
            "entrega": _valor(p, "entrega"),
            "acabados": _ACABADOS.get(_valor(p, "acabados"), "Sin dato"),
            "area_tipo": "construida",
            "renta_corta": _valor(p, "renta_corta", "desconocida"),
            "renta_corta_agregador": reglas.es_agregador(((p.get("enriquecimiento") or {}).get("renta_corta") or {}).get("fuente")),
            "categorias": p.get("categorias") or [],
            "admin_m2": _valor(p, "admin_m2"),
            "estrato": _valor(p, "estrato"),
            "ascensor": _valor(p, "ascensor"),
            "brochure": next((b.get("url") for b in reversed(p.get("brochures") or [])
                              if b.get("estado") == "procesado" and reglas.es_url(b.get("url"))), None),
            "fuente": p.get("fuente_nombre") or "Estrenar Vivienda",
            "notas": p.get("notas"),
            "url": p.get("url"),
            "detectado": p.get("primer_visto"),
            "tipologias": [
                {"id": t["typology_id"], "habs": t.get("habs"), "banos": t.get("banos"),
                 "area": t.get("area"), "parq": t.get("parq") or 0, "precio": t.get("precio_desde"),
                 "url": t.get("url"),
                 "area_privada": ((p.get("areas_privadas") or {}).get(f"{t['fuente']}:{t['typology_id']}") or {}).get("valor")
                                 or t.get("area_privada")}
                for t in sorted(ts, key=lambda t: (t.get("habs") or 0, t.get("precio_desde") or 0))
            ],
        })

    return {
        "generado": datetime.now().astimezone().isoformat(timespec="seconds"),
        "zonas": zonas,
        "proyectos": publicados,
        "sin_ubicar": sin_ubicar,
        "fuera_de_zonas": fuera,
        "usados": [],
    }


def guardar(datos: dict, path: Path = ARCHIVO) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")
