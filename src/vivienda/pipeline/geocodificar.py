"""Paso determinístico (sin IA): dirección -> coordenadas por cruce de vías.

Orden de fuentes de dirección para un proyecto sin ubicación:
1. `direccion_candidata` propuesta por el agente desde una fuente oficial (la deja pipeline/aplicar.py).
2. La ficha de Estrenar Vivienda, si publica dirección (agregador: confianza baja).

Precisión resultante:
    media = dirección de una página oficial verificada (señal A) o ingresada a mano + cruce de vías en OSM
    baja  = dirección de agregador o no encontrada en la página citada
Nunca reemplaza una ubicación existente.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date

import requests

from vivienda import geo
from vivienda.checks import Bitacora
from vivienda.geocodificacion import Geocodificador
from vivienda.sources.estrenar.ficha import leer_ficha


@dataclass
class ResumenGeo:
    ubicados: list[str] = field(default_factory=list)
    fichas_leidas: int = 0
    detalles: list[str] = field(default_factory=list)


def completar_desde_fichas(proyectos: dict[str, dict], session: requests.Session, bit: Bitacora,
                           hoy: date, res: ResumenGeo) -> None:
    """Lee la ficha de cada proyecto activo que aún no tiene dirección ni entrega."""
    for p in proyectos.values():
        enr = p.setdefault("enriquecimiento", {})
        falta_dir = not p.get("ubicacion") and not p.get("direccion_candidata")
        falta_entrega = "entrega" not in enr
        falta_categorias = p.get("categorias_leidas") != hoy.isoformat()   # se refrescan a diario
        if not p.get("activo") or not p.get("url") or not (falta_dir or falta_entrega or falta_categorias):
            continue
        datos = leer_ficha(p["url"], session, hoy=hoy)
        res.fichas_leidas += 1
        if not datos:
            bit.registrar(p["id"], "ficha_estrenar", "error", url=p["url"])
            continue
        if falta_dir and datos["direccion"]:
            p["direccion_candidata"] = {"direccion": datos["direccion"], "fuente": p["url"],
                                        "origen": "agregador", "encontrada": hoy.isoformat()}
        if falta_entrega and datos["entrega"]:
            enr["entrega"] = {"valor": datos["entrega"], "fuente": p["url"], "verificado": hoy.isoformat()}
        p["categorias"] = datos.get("categorias") or []
        p["categorias_leidas"] = hoy.isoformat()
        # 'Renta Corta' en el portal = señal de que el proyecto se mercadea para renta corta.
        # Solo llena el dato si no hay otro; una fuente oficial (agente/brochure) lo reemplaza.
        if "Renta Corta" in p["categorias"] and "renta_corta" not in enr:
            enr["renta_corta"] = {"valor": "permitida", "fuente": p["url"], "verificado": hoy.isoformat(),
                                  "nota": "categoría 'Renta Corta' en el portal; confirmar en el reglamento de PH"}
        elif ("Renta Corta" not in p["categorias"] and (enr.get("renta_corta") or {}).get("fuente") == p["url"]):
            del enr["renta_corta"]   # el portal quitó la categoría: se retira lo que dependía de ella
        bit.registrar(p["id"], "ficha_estrenar", "ok", direccion=datos["direccion"], entrega=datos["entrega"],
                      categorias=datos.get("categorias"))


def geocodificar(proyectos: dict[str, dict], geocod: Geocodificador, zonas: dict, bit: Bitacora,
                 hoy: date, res: ResumenGeo) -> None:
    for p in sorted(proyectos.values(), key=lambda x: x["id"]):
        cand = p.get("direccion_candidata")
        u = p.get("ubicacion") or {}
        mejora = (u.get("precision") == "baja" and (cand or {}).get("origen") in ("oficial", "manual"))
        if not p.get("activo") or not cand or (u and not mejora) or cand.get("geocodificada"):
            continue
        if hasattr(geocod, "cruce_detallado"):
            caja = geo.bbox_zonas(p.get("zonas_candidatas"), zonas)  # alrededor de su zona, no toda la ciudad
            r, motivo = geocod.cruce_detallado(cand["direccion"], p.get("ciudad"), bbox=caja)
        else:
            r, motivo = geocod.cruce(cand["direccion"], p.get("ciudad")), "sin resultado"
        if not r:
            if "no respondió" not in motivo:  # si fue un error de red, se reintenta en la próxima corrida
                cand["geocodificada"] = hoy.isoformat()
            bit.registrar(p["id"], "cruce_osm", "sin_resultado", direccion=cand["direccion"], motivo=motivo)
            res.detalles.append(f"{p['id']} {p.get('nombre')}: '{cand['direccion']}' → {motivo}")
            continue
        cand["geocodificada"] = hoy.isoformat()
        lat, lng, detalle = r
        precision = "media" if cand.get("origen") in ("oficial", "manual") else "baja"
        p["ubicacion"] = {
            "lat": round(lat, 6), "lng": round(lng, 6), "direccion": cand["direccion"],
            "precision": precision, "fuente": cand["fuente"], "metodo": detalle,
            "verificado": hoy.isoformat(),
        }
        p["zona"], p["zona_nota"] = geo.asignar_zona(lat, lng, p.get("zonas_candidatas"), zonas)
        bit.registrar(p["id"], "cruce_osm", "ok", direccion=cand["direccion"], detalle=detalle,
                      zona=p["zona"], precision=precision)
        res.ubicados.append(p["id"])
        res.detalles.append(f"{p['id']} {p.get('nombre')}: {cand['direccion']} → {detalle} → "
                            f"zona {p['zona'] or 'fuera de zonas'} (precisión {precision}, dirección de {cand.get('origen')})")


def ejecutar(proyectos: dict[str, dict], user_agent_estrenar: str, user_agent_osm: str,
             zonas: dict, bit: Bitacora, hoy: date, leer_fichas: bool = True) -> ResumenGeo:
    res = ResumenGeo()
    if leer_fichas:
        s = requests.Session()
        s.headers.update({"User-Agent": user_agent_estrenar, "Accept-Language": "es-CO,es;q=0.9"})
        completar_desde_fichas(proyectos, s, bit, hoy, res)
    geocodificar(proyectos, Geocodificador(user_agent_osm), zonas, bit, hoy, res)
    return res
