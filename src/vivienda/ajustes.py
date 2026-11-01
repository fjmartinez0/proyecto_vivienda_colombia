"""Correcciones a mano sobre proyectos que trae un portal (config/ajustes_proyectos.toml).

- [[ubicacion]]: dirección (y opcionalmente lat/lng) para un proyecto cuya ficha no la publica o la
  publica mal. Se busca por nombre (sin tildes ni mayúsculas). La dirección cuenta como 'manual'
  (precisión media) y reemplaza una ubicación de agregador.
- [excluir] nombres: proyectos que no deben aparecer en el visor (p. ej. fuera de presupuesto).
"""
from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path

from vivienda.config import CONFIG_DIR
from vivienda.texto import normalizar

ARCHIVO = CONFIG_DIR / "ajustes_proyectos.toml"


def cargar(path: Path = ARCHIVO) -> dict:
    if not path.exists():
        return {}
    with open(path, "rb") as f:
        return tomllib.load(f)


def aplicar(prys: dict[str, dict], ajustes: dict, hoy: date) -> list[str]:
    """-> lista de textos con lo que cambió (para el log)."""
    h = hoy.isoformat()
    cambios = []
    excluir = {normalizar(n) for n in (ajustes.get("excluir") or {}).get("nombres", [])}
    por_nombre: dict[str, list[dict]] = {}
    for p in prys.values():
        por_nombre.setdefault(normalizar(p.get("nombre")), []).append(p)
        p["excluido"] = normalizar(p.get("nombre")) in excluir

    for a in ajustes.get("ubicacion", []):
        for p in por_nombre.get(normalizar(a.get("nombre")), []):
            fuente = a.get("fuente") or "file://ajustes_proyectos"
            if a.get("seguimiento"):
                p["seguimiento"] = True
            if a.get("lat") is not None and a.get("lng") is not None:
                u = p.get("ubicacion") or {}
                if (u.get("lat"), u.get("lng")) != (a["lat"], a["lng"]):
                    p["ubicacion"] = {"lat": float(a["lat"]), "lng": float(a["lng"]),
                                      "direccion": a.get("direccion"), "precision": a.get("precision", "media"),
                                      "fuente": fuente, "metodo": "coordenadas manuales", "verificado": h}
                    p["zona"] = None   # la decide rezonificar
                    cambios.append(f"{p['id']} {p.get('nombre')}: coordenadas manuales")
                continue
            if a.get("direccion"):
                actual = p.get("direccion_candidata") or {}
                if actual.get("direccion") != a["direccion"] or actual.get("origen") != "manual":
                    p["direccion_candidata"] = {"direccion": a["direccion"], "fuente": fuente,
                                                "origen": "manual", "encontrada": h}
                    u = p.get("ubicacion") or {}
                    if u and u.get("direccion") != a["direccion"]:
                        p["ubicacion"] = None   # se vuelve a geocodificar con la dirección corregida
                        p["zona"] = None
                    cambios.append(f"{p['id']} {p.get('nombre')}: dirección {a['direccion']}")
    return cambios
