"""Merger: aplica una propuesta del agente al registro de proyectos.

Reglas:
- Un proyecto desconocido en la propuesta se rechaza (el agente no crea proyectos).
- Coordenadas fuera de la ciudad se rechazan.
- Precisión de la ubicación, según cuántas de estas 3 señales independientes se cumplen:
    A. la dirección aparece en la página citada (que no sea un agregador)
    B. la calle de OpenStreetMap en esas coordenadas coincide con la dirección
    C. las coordenadas coinciden (< 60 m) con un enlace de mapa citado (Google Maps / Waze)
  alta = 2 o más · media = 1 · baja = 0 (se guarda, pero el dashboard lo marca)
- Nunca se reemplaza una ubicación por otra de peor precisión.
- Cada campo de enriquecimiento necesita su propia fuente URL y pasar reglas.validar_enriquecimiento.
- Todas las verificaciones quedan en data/checks.jsonl.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

from vivienda import geo, reglas
from vivienda.checks import Bitacora
from vivienda.verificacion import Verificador, coords_de_enlace, via_de_calle_osm, vias_de_direccion

TOLERANCIA_ENLACE_M = 60


@dataclass
class ResumenAplicar:
    ubicados: list[str] = field(default_factory=list)
    enriquecidos: list[str] = field(default_factory=list)
    rechazos: list[str] = field(default_factory=list)
    detalles: list[str] = field(default_factory=list)


def _precision(*senales: bool) -> str:
    n = sum(senales)
    return "alta" if n >= 2 else "media" if n == 1 else "baja"


def _ubicar(p: dict, item: dict, ver: Verificador, zonas: dict, bit: Bitacora, hoy: str,
            detalles: list[str] | None = None) -> str | None:
    """Devuelve un motivo de rechazo o None si se aceptó (o no había ubicación)."""
    lat, lng = item.get("lat"), item.get("lng")
    if lat is None or lng is None:
        return None
    try:
        lat, lng = float(lat), float(lng)
    except (TypeError, ValueError):
        return "coordenadas no numéricas"
    if not geo.en_bbox(lat, lng, p.get("ciudad")):
        bit.registrar(p["id"], "bbox", "fuera", lat=lat, lng=lng, ciudad=p.get("ciudad"))
        return f"coordenadas fuera de {p.get('ciudad')}"

    direccion = (item.get("direccion") or "").strip() or None
    ev, ev_det = ver.evidencia(item.get("direccion_fuente"), direccion)
    bit.registrar(p["id"], "evidencia_direccion", ev, url=item.get("direccion_fuente"), detalle=ev_det)

    calle = ver.calle_en(lat, lng)
    via_osm = via_de_calle_osm(calle)
    calle_ok = bool(direccion and via_osm and via_osm in vias_de_direccion(direccion))
    bit.registrar(p["id"], "calle_osm", "ok" if calle_ok else "no_coincide", calle_osm=calle, direccion=direccion)

    enlace = coords_de_enlace(item.get("coordenadas_fuente"))
    dist = geo.distancia_m(lat, lng, *enlace) if enlace else None
    enlace_ok = dist is not None and dist <= TOLERANCIA_ENLACE_M
    bit.registrar(p["id"], "enlace_mapa", "ok" if enlace_ok else ("lejos" if enlace else "sin_enlace"),
                  url=item.get("coordenadas_fuente"), distancia_m=round(dist) if dist is not None else None)

    precision = _precision(ev == "ok", calle_ok, enlace_ok)
    if detalles is not None:
        txt_enlace = (f"{dist:.0f} m → {'coincide' if enlace_ok else 'no coincide'}" if enlace
                      else "sin enlace de mapa")
        detalles.append(
            f"{p['id']} {p.get('nombre')}: precisión {precision}\n"
            f"      A dirección en fuente: {ev} ({direccion or 'sin dirección'})\n"
            f"      B calle OSM: {calle or '—'} → {'coincide' if calle_ok else 'no coincide'}\n"
            f"      C enlace de mapa: {txt_enlace}")
    actual = (p.get("ubicacion") or {}).get("precision")
    if actual and reglas.mejor_precision(actual, precision) == actual and actual != precision:
        return f"ya tiene ubicación de precisión {actual} (propuesta: {precision})"

    p["ubicacion"] = {
        "lat": round(lat, 6), "lng": round(lng, 6), "direccion": direccion,
        "precision": precision, "fuente": item.get("direccion_fuente"),
        "coordenadas_fuente": item.get("coordenadas_fuente"),
        "calle_osm": calle, "verificado": hoy,
    }
    p["zona"], p["zona_nota"] = geo.asignar_zona(lat, lng, p.get("zonas_candidatas"), zonas)
    bit.registrar(p["id"], "zona", p["zona"] or "fuera_de_zonas", precision=precision)
    return None


_RANGO_ORIGEN = {"manual": 4, "oficial": 3, "oficial_sin_verificar": 2, "agregador": 1}


def _guardar_direccion_candidata(p: dict, item: dict, ver: Verificador, bit: Bitacora, hoy: str,
                                 res: ResumenAplicar) -> None:
    """Dirección sin coordenadas: se guarda para el paso de geocodificación por cruce de vías.
    Fuente oficial > oficial no verificada > agregador (regla: el agregador se usa si es lo único)."""
    cand = None
    direccion, fuente = (item.get("direccion") or "").strip(), item.get("direccion_fuente")
    if direccion and reglas.es_url(fuente) and not reglas.es_agregador(fuente):
        ev, det = ver.evidencia(fuente, direccion)
        bit.registrar(p["id"], "evidencia_direccion", ev, url=fuente, detalle=det)
        cand = {"direccion": direccion, "fuente": fuente,
                "origen": "oficial" if ev == "ok" else "oficial_sin_verificar"}
    else:
        d_ag, f_ag = (item.get("direccion_agregador") or "").strip(), item.get("direccion_agregador_fuente")
        if d_ag and reglas.es_url(f_ag):
            cand = {"direccion": d_ag, "fuente": f_ag, "origen": "agregador"}
    if not cand:
        return
    actual = p.get("direccion_candidata") or {}
    if _RANGO_ORIGEN.get(actual.get("origen"), 0) > _RANGO_ORIGEN[cand["origen"]]:
        return  # no empeorar
    if actual.get("direccion") == cand["direccion"] and actual.get("origen") == cand["origen"]:
        return  # ya la teníamos
    p["direccion_candidata"] = {**cand, "encontrada": hoy}
    bit.registrar(p["id"], "direccion_candidata", cand["origen"], direccion=cand["direccion"], url=cand["fuente"])
    res.detalles.append(f"      dirección guardada para geocodificar: {cand['direccion']} ({cand['origen']})")


def aplicar(propuesta: dict, proyectos: dict[str, dict], zonas: dict, ver: Verificador,
            bit: Bitacora, hoy: date) -> ResumenAplicar:
    res = ResumenAplicar()
    h = hoy.isoformat()
    items = propuesta.get("proyectos")
    if not isinstance(items, list):
        res.rechazos.append("propuesta sin lista 'proyectos'")
        return res

    for item in items:
        pid = item.get("id") if isinstance(item, dict) else None
        p = proyectos.get(pid)
        if p is None:
            res.rechazos.append(f"{pid}: ID desconocido")
            continue

        if item.get("lat") is None or item.get("lng") is None:
            nota = " ".join(str(item.get("notas") or "sin notas").split())
            res.detalles.append(f"{pid} {p.get('nombre')}: sin coordenadas — {nota[:220]}")
            _guardar_direccion_candidata(p, item, ver, bit, h, res)
        motivo = _ubicar(p, item, ver, zonas, bit, h, res.detalles)
        if motivo:
            res.rechazos.append(f"{pid}: {motivo}")
        elif item.get("lat") is not None:
            res.ubicados.append(pid)

        urls = item.get("brochure_urls") or []
        if isinstance(urls, list) and urls:
            from vivienda.pipeline.brochures import agregar_urls
            n = agregar_urls(p, urls)
            if n:
                res.detalles.append(f"      {n} brochure(s) por descargar: vivienda brochures")

        campos, errores = reglas.validar_enriquecimiento(item)
        for e in errores:
            res.rechazos.append(f"{pid}: {e}")
        if campos:
            enr = p.setdefault("enriquecimiento", {})
            for k, v in campos.items():
                enr[k] = {**v, "verificado": h}
                bit.registrar(pid, f"dato_{k}", "aceptado", valor=v["valor"], fuente=v["fuente"])
            res.enriquecidos.append(pid)
    return res


def leer_propuesta(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8"))
