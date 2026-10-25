"""Historial de tipologías: detecta nuevas, actualiza vistas y marca las que desaparecen.

Archivo: data/processed/nuevos.json  (lista de registros)
Cada registro = campos de la tipología + primer_visto, ultimo_visto, activo,
precio_anterior (si cambió el precio).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from vivienda.models import Tipologia


@dataclass
class ResumenHistorial:
    nuevas: list[str] = field(default_factory=list)
    cambios_precio: list[str] = field(default_factory=list)
    desaparecidas: list[str] = field(default_factory=list)


def _clave(r: dict) -> str:
    return f"{r['fuente']}:{r['typology_id']}"


def cargar(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    return {_clave(r): r for r in json.loads(path.read_text(encoding="utf-8"))}


def guardar(path: Path, registros: dict[str, dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    datos = sorted(registros.values(), key=lambda r: (r.get("ciudad") or "", r.get("proyecto") or "", r["typology_id"]))
    path.write_text(json.dumps(datos, ensure_ascii=False, indent=1), encoding="utf-8")


def actualizar(
    registros: dict[str, dict],
    vistas: list[Tipologia],
    hoy: date,
    fuentes_consultadas: set[str],
) -> ResumenHistorial:
    """Fusiona lo visto hoy con el historial (modifica `registros` en sitio).

    Solo marca como desaparecidas las tipologías de fuentes consultadas hoy,
    para no "borrar" datos de una fuente que falló o no se corrió.
    """
    h = hoy.isoformat()
    res = ResumenHistorial()
    claves_hoy = set()

    for t in vistas:
        k = t.clave
        claves_hoy.add(k)
        nuevo = t.to_dict()
        previo = registros.get(k)
        if previo is None:
            nuevo.update(primer_visto=h, ultimo_visto=h, activo=True)
            res.nuevas.append(k)
        else:
            nuevo["primer_visto"] = previo["primer_visto"]
            nuevo["ultimo_visto"] = h
            nuevo["activo"] = True
            if previo.get("precio_desde") != t.precio_desde:
                nuevo["precio_anterior"] = previo.get("precio_desde")
                res.cambios_precio.append(k)
            elif "precio_anterior" in previo:
                nuevo["precio_anterior"] = previo["precio_anterior"]
        registros[k] = nuevo

    for k, r in registros.items():
        if r["fuente"] in fuentes_consultadas and k not in claves_hoy and r.get("activo"):
            r["activo"] = False
            res.desaparecidas.append(k)
    return res
