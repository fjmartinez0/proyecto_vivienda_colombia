"""Fuente: proyectos manuales (config/proyectos_manuales.toml).

Para proyectos que ningún portal escaneado publica, o que llegaron por otro canal
(brochure, cotización, valla, referido). Se integran igual que cualquier fuente:
tipologías -> historial -> registro de proyectos -> dashboard.
"""
from __future__ import annotations

import tomllib
from datetime import date
from pathlib import Path

from vivienda import reglas
from vivienda.config import CONFIG_DIR
from vivienda.models import Tipologia
from vivienda.texto import slug

FUENTE = "manual"
ARCHIVO = CONFIG_DIR / "proyectos_manuales.toml"
CAMPOS_ENRIQ = ("estrato", "ascensor", "renta_corta", "entrega", "acabados", "estado_obra", "admin_m2", "parqueaderos")


def cargar(path: Path = ARCHIVO) -> list[dict]:
    if not path.exists():
        return []
    with open(path, "rb") as f:
        datos = tomllib.load(f)
    proyectos = datos.get("proyecto", [])
    ids = [p.get("id") for p in proyectos]
    repetidos = {i for i in ids if ids.count(i) > 1}
    if None in ids or repetidos:
        raise ValueError(f"proyectos_manuales.toml: cada proyecto necesita un 'id' único (repetidos: {repetidos or 'falta id'})")
    return proyectos


def clave(p: dict) -> str:
    return f"{FUENTE}:{p['id']}:{slug(p.get('ciudad'))}"


def tipologias(proyectos: list[dict]) -> list[Tipologia]:
    out = []
    for p in proyectos:
        for i, t in enumerate(p.get("tipologia", []), start=1):
            out.append(Tipologia(
                fuente=FUENTE, typology_id=f"{p['id']}-{i}", proyecto=p.get("nombre"),
                url=p.get("fuente") if reglas.es_url(p.get("fuente")) else "",
                constructora=p.get("constructora"), tipo_inmueble=t.get("nombre"),
                sector=p.get("sector"), ciudad=p.get("ciudad"),
                area=t.get("area"), area_tipo="construida",
                habs=t.get("habs"), banos=t.get("banos"), parq=t.get("parq"), parq_comunal=False,
                precio_desde=t.get("precio"), zonas_candidatas=list(p.get("zonas", [])),
                area_privada=t.get("area_privada"), proyecto_clave=clave(p),
            ))
    return out


def aplicar_a_proyectos(registro: dict[str, dict], manuales: list[dict], hoy: date) -> None:
    """Lleva al registro lo que el archivo dice a nivel de proyecto: dirección, datos clave, fuente.
    Lo manual no pisa una fuente oficial ya verificada (agente/brochure), salvo datos de agregador."""
    por_clave = {p["clave"]: p for p in registro.values()}
    h = hoy.isoformat()
    for m in manuales:
        p = por_clave.get(clave(m))
        if p is None:
            continue
        fuente = m.get("fuente") if reglas.es_fuente(m.get("fuente")) else f"file://manual/{m['id']}"
        p["fuente_nombre"] = "Manual"
        p["url"] = m.get("fuente") if reglas.es_url(m.get("fuente")) else None
        p["notas"] = m.get("notas")
        p["zonas_candidatas"] = list(m.get("zonas", []))
        if m.get("direccion"):
            origen = "agregador" if m.get("direccion_origen") == "agregador" else "manual"
            actual = p.get("direccion_candidata") or {}
            if actual.get("direccion") != m["direccion"] or actual.get("origen") != origen:
                p["direccion_candidata"] = {"direccion": m["direccion"], "fuente": fuente,
                                            "origen": origen, "encontrada": h}
                if (p.get("ubicacion") or {}).get("metodo", "").startswith("cruce"):
                    p["ubicacion"] = None   # la dirección cambió: se vuelve a geocodificar
        item = {k: m[k] for k in CAMPOS_ENRIQ if k in m}
        item["fuente_general"] = fuente
        aceptados, _ = reglas.validar_enriquecimiento(item)
        enr = p.setdefault("enriquecimiento", {})
        for k, v in aceptados.items():
            actual = enr.get(k)
            if actual is None or reglas.es_agregador(actual.get("fuente")) or actual.get("fuente") == fuente:
                enr[k] = {**v, "verificado": h}
