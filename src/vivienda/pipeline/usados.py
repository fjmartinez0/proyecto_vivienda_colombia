"""Vivienda usada (Fincaraíz): recorrido por barrio, zona por coordenadas, historial.

Reglas (heredadas del proyecto anterior + las de este radar):
- La URL de barrio NO es un filtro geográfico estricto: trae anuncios de barrios vecinos.
  Aquí no se filtra por nombre de barrio sino por el punto del anuncio: entra si cae dentro
  de una zona del radar (círculo o polígono). Así sirve el ruido de barrios vecinos que sí
  caen en la zona.
- Solo apartamento / apartaestudio, solo usados (isProject fuera).
- Historial en data/processed/usados.json: primer y último día visto, y cada cambio de precio.
  Un anuncio deja de mostrarse si no se ve en `dias_vigencia` días (el recorrido trae primero los
  más recientes y tiene tope de páginas, así que no verlo un día no significa que se vendió).
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from datetime import date, timedelta
from pathlib import Path

from vivienda import geo
from vivienda.config import PROCESSED_DIR
from vivienda.sources.fincaraiz import TIPOS_VALIDOS, parsear, url_barrio
from vivienda.sources.fincaraiz.cliente import PATRON_CIUDAD

ARCHIVO = PROCESSED_DIR / "usados.json"


@dataclass
class ResumenBarrio:
    ruta: str
    ciudad: str
    total_portal: int | None = None      # paginatorInfo.total de la página 1 (comparar con el navegador)
    paginas: int = 0
    leidos: int = 0
    otros_tipos: int = 0
    proyectos: int = 0
    sin_coordenadas: int = 0
    fuera_de_zonas: int = 0
    en_zona: dict[str, int] = field(default_factory=dict)
    error: str | None = None
    apartaestudios_portal: int | None = None   # Bogotá: total del recorrido extra de apartaestudios


def recorrer_barrio(cliente, ruta: str, ciudad: str, zonas: dict, max_paginas: int,
                    hoy: date, avisar=print) -> tuple[list[dict], ResumenBarrio]:
    res = ResumenBarrio(ruta, ciudad)
    # Bogotá: recorrido general (todos los tipos, más recientes primero) + uno solo de apartaestudios.
    # Sin el segundo, el tope de páginas se lo comen los apartamentos grandes y casi no entran unidades
    # pequeñas, que son justo los comparables de los proyectos nuevos (Ciento5I: 34 de ~70 en Navarra).
    tipos = sorted(TIPOS_VALIDOS) if PATRON_CIUDAD[ciudad]["incluye_tipo"] else [None, "apartaestudio"]
    vistos: dict[str, dict] = {}
    for tipo_url in tipos:
        pagina, ultima = 1, 1
        while pagina <= min(ultima, max_paginas):
            url = url_barrio(ruta, ciudad, pagina, tipo_url)
            etiqueta = f"{ruta.replace('/', '-')}_{tipo_url or 'todos'}_p{pagina}"
            p = cliente.pagina(url, etiqueta)
            if p.error:
                extra = tipo_url == "apartaestudio" and not PATRON_CIUDAD[ciudad]["incluye_tipo"]
                if extra and not any(s in p.error for s in ("403", "429", "bloqueo", "captcha")):
                    avisar(f"    · recorrido de apartaestudios sin datos: {p.error}")   # no tumba el barrio
                    break
                res.error = f"{url}: {p.error}"
                avisar(f"    ✗ {p.error}")
                break
            res.paginas += 1
            if pagina == 1 and (tipo_url is None or PATRON_CIUDAD[ciudad]["incluye_tipo"]):
                res.total_portal = (res.total_portal or 0) + (p.paginador.get("total") or 0)
            if pagina == 1 and tipo_url == "apartaestudio" and not PATRON_CIUDAD[ciudad]["incluye_tipo"]:
                res.apartaestudios_portal = p.paginador.get("total")
            ultima = p.paginador.get("lastPage") or pagina
            for item in p.anuncios:
                a = parsear(item)
                if not a:
                    continue
                res.leidos += 1
                if a["tipo"] not in TIPOS_VALIDOS:
                    res.otros_tipos += 1
                    continue
                if a["es_proyecto"]:
                    res.proyectos += 1
                    continue
                if a["lat"] is None or a["lng"] is None or not geo.en_bbox(a["lat"], a["lng"], ciudad):
                    res.sin_coordenadas += 1
                    continue
                z = geo.zona_de(a["lat"], a["lng"], zonas)
                if z:
                    res.en_zona[z] = res.en_zona.get(z, 0) + 1
                else:
                    res.fuera_de_zonas += 1   # se guarda igual: sirve de comparable cercano (entorno)
                vistos[a["id"]] = {**a, "zona": z, "ciudad": ciudad, "ruta": ruta}
            avisar(f"    pág. {pagina}/{min(ultima, max_paginas)}: {len(p.anuncios)} anuncios")
            pagina += 1
    return list(vistos.values()), res


def cargar(path: Path = ARCHIVO) -> dict[str, dict]:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (FileNotFoundError, ValueError):
        return {}


def guardar(registro: dict[str, dict], path: Path = ARCHIVO) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(registro, ensure_ascii=False, indent=1), encoding="utf-8")


def actualizar(registro: dict[str, dict], anuncios: list[dict], hoy: date) -> dict[str, int]:
    """Funde lo leído hoy en el historial. -> conteo de nuevos / con cambio de precio / vistos."""
    c = {"nuevos": 0, "cambio_precio": 0, "vistos": 0}
    h = hoy.isoformat()
    for a in anuncios:
        clave = f"fincaraiz:{a['id']}"
        previo = registro.get(clave)
        if previo is None:
            registro[clave] = {**a, "primer_visto": h, "ultimo_visto": h,
                               "precios": [{"fecha": h, "precio": a["precio"]}]}
            c["nuevos"] += 1
            continue
        precios = previo.get("precios") or []
        if a["precio"] and precios and precios[-1]["precio"] != a["precio"]:
            precios.append({"fecha": h, "precio": a["precio"]})
            c["cambio_precio"] += 1
        previo.update({**a, "ultimo_visto": h, "precios": precios})
        c["vistos"] += 1
    return c


def vigentes(registro: dict[str, dict], hoy: date, dias: int) -> list[dict]:
    limite = (hoy - timedelta(days=dias)).isoformat()
    return [r for r in registro.values() if r.get("ultimo_visto", "") >= limite]


def para_dashboard(registro: dict[str, dict], hoy: date, dias: int, area_min: float,
                   zonas: dict | None = None) -> list[dict]:
    """Formato que espera web/index.html (mismo contrato que los usados de demostración).
    Con `zonas`, la zona se recalcula desde el punto del anuncio: si cambias una zona, los usados
    guardados se reubican en la siguiente exportación (y los que quedan fuera dejan de mostrarse)."""
    out = []
    for r in sorted(vigentes(registro, hoy, dias), key=lambda x: x["primer_visto"], reverse=True):
        if zonas is not None:
            if r.get("lat") is None:
                continue
            # fuera de toda zona -> zona None: no es inventario de ninguna zona, pero sí comparable por distancia
            r = {**r, "zona": geo.zona_de(r["lat"], r["lng"], zonas)}
        area, tipo_area = (r["area_privada"], "privada") if r.get("area_privada") else \
                          (r["area_construida"], "construida") if r.get("area_construida") else (None, None)
        if not r.get("precio") or not area or area < area_min:
            continue
        precios = r.get("precios") or []
        out.append({
            "id": "FR-" + r["id"], "zona": r["zona"], "lat": r["lat"], "lng": r["lng"],
            "estrato": r.get("estrato"), "habs": int(r["habs"]) if r.get("habs") else (1 if r["tipo"] == "apartaestudio" else None),
            "area": area, "area_tipo": tipo_area, "parq": r.get("parq"),
            "precio": r["precio"], "admin": r.get("admin"),
            "ascensor": r.get("ascensor"), "ascensor_fuente": r.get("ascensor_fuente"),
            "antiguedad": r.get("antiguedad"), "antiguedad_texto": r.get("antiguedad_texto"),
            "piso": r.get("piso"), "barrio": r.get("barrio"), "tipo": r.get("tipo"),
            "renta_corta": "desconocida", "fuentes": ["Fincaraíz"], "url": r.get("url"),
            "detectado": r["primer_visto"], "ultimo_visto": r["ultimo_visto"],
            "precio_inicial": precios[0]["precio"] if precios else r["precio"],
            "precios": precios, "banos": r.get("banos"), "pisos_edificio": r.get("pisos_edificio"),
            "publicador": r.get("publicador"), "creado_portal": (r.get("creado_portal") or "")[:10] or None,
            "amenidades": r.get("amenidades") or [], "descripcion": r.get("descripcion"),
        })
    return out
