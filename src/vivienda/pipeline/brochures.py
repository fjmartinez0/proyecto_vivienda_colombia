"""Paso de brochures: URLs -> PDF -> texto -> reglas (-> lectura asistida) -> registro de proyectos.

Datos que deja en el proyecto:
- p["brochure_urls"]: URLs candidatas (las propone el agente).
- p["brochures"]: un registro por PDF (url, archivo, sha256, páginas, caracteres, estado, campos).
- p["areas_privadas"]: {"<fuente>:<typology_id>": {"valor", "construida_brochure", "fuente"}}
- enriquecimiento con el brochure como fuente oficial (reemplaza datos de agregador, no de otra fuente oficial).

Regla de asignación de área privada a una tipología (uno a uno, la más cercana primero):
  el área construida del brochure está a ≤ 5 % del área de la tipología  Y
  0,75 ≤ privada / construida ≤ 0,97.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date
from pathlib import Path

import requests

from vivienda import reglas
from vivienda.checks import Bitacora
from vivienda.pipeline.proyectos import clave_proyecto
from vivienda.sources import brochure as br

TOL_CONSTRUIDA = 0.05
RATIO_MIN, RATIO_MAX = 0.75, 0.97
CAMPOS_ENRIQ = ("estrato", "admin_m2", "ascensor", "acabados", "entrega", "estado_obra", "renta_corta", "parqueaderos")


@dataclass
class ResumenBrochures:
    descargados: int = 0
    procesados: int = 0
    areas_asignadas: int = 0
    para_ia: list[tuple[str, Path]] = field(default_factory=list)   # (proyecto_id, archivo .txt)
    detalles: list[str] = field(default_factory=list)


def asignar_areas(tipologias: list[dict], pares: list[dict], fuente: str) -> tuple[dict, list[str]]:
    """Asignación uno a uno: cada par del brochure se usa una sola vez, para la tipología más cercana.
    (Dos tipologías parecidas — 44,02 y 44,58 m² — no reciben la misma área privada.)"""
    asignadas, notas = {}, []
    completos = [a for a in pares if a.get("construida") and a.get("privada")]
    candidatos = []
    for ti, t in enumerate(tipologias):
        area = t.get("area")
        for ai, a in enumerate(completos):
            if not area:
                continue
            dif = abs(a["construida"] - area) / area
            if dif <= TOL_CONSTRUIDA and RATIO_MIN <= a["privada"] / a["construida"] <= RATIO_MAX:
                candidatos.append((dif, ti, ai))
    usadas_t, usados_a = set(), set()
    for dif, ti, ai in sorted(candidatos):
        if ti in usadas_t or ai in usados_a:
            continue
        usadas_t.add(ti)
        usados_a.add(ai)
        t, a = tipologias[ti], completos[ai]
        asignadas[f"{t['fuente']}:{t['typology_id']}"] = {
            "valor": a["privada"], "construida_brochure": a["construida"], "fuente": fuente}
    for ti, t in enumerate(tipologias):
        if ti not in usadas_t and t.get("area"):
            notas.append(f"tipología {t['area']} m² ({t.get('habs')} hab): sin par de áreas compatible y libre en el brochure")
    if pares and not completos:
        notas.append("el brochure trae áreas privadas sin la construida correspondiente: no se asignan (riesgo de error)")
    return asignadas, notas


def aplicar_datos(p: dict, datos: dict, fuente: str, tipologias: list[dict], bit: Bitacora, hoy: str) -> list[str]:
    """Aplica lo extraído de un brochure. Devuelve la lista de campos que cambiaron."""
    cambios = []
    # enriquecimiento: mismas reglas que las propuestas del agente
    item = {k: v for k, v in datos.items() if k in CAMPOS_ENRIQ}
    item["fuente_general"] = fuente
    aceptados, errores = reglas.validar_enriquecimiento(item)
    enr = p.setdefault("enriquecimiento", {})
    for k, v in aceptados.items():
        actual = enr.get(k)
        if actual is None or reglas.es_agregador(actual.get("fuente")):
            enr[k] = {**v, "verificado": hoy}
            cambios.append(k)
            bit.registrar(p["id"], f"brochure_{k}", "aceptado", valor=v["valor"], fuente=fuente)
    for e in errores:
        bit.registrar(p["id"], "brochure_dato", "rechazado", detalle=e)

    # dirección: fuente oficial (texto del brochure), sin empeorar una manual
    if datos.get("direccion"):
        actual = (p.get("direccion_candidata") or {}).get("origen")
        if actual not in ("manual", "oficial"):
            p["direccion_candidata"] = {"direccion": datos["direccion"], "fuente": fuente,
                                        "origen": "oficial", "encontrada": hoy}
            cambios.append("direccion")

    # áreas privadas por tipología
    if datos.get("areas"):
        asignadas, notas = asignar_areas(tipologias, datos["areas"], fuente)
        if asignadas:
            p.setdefault("areas_privadas", {}).update(asignadas)
            cambios.append(f"area_privada×{len(asignadas)}")
        for n in notas:
            bit.registrar(p["id"], "brochure_areas", "nota", detalle=n)
    return cambios


def _tipologias_de(p: dict, tipologias: dict[str, dict]) -> list[dict]:
    return [t for t in tipologias.values() if t.get("activo") and clave_proyecto(t) == p["clave"]]


def falta_para_ia(p: dict, tipologias_p: list[dict]) -> bool:
    """¿Vale la pena la lectura asistida? Si faltan áreas privadas o ascensor tras las reglas."""
    sin_areas = any(f"{t['fuente']}:{t['typology_id']}" not in (p.get("areas_privadas") or {}) for t in tipologias_p)
    sin_ascensor = "ascensor" not in (p.get("enriquecimiento") or {})
    return sin_areas or sin_ascensor


def procesar_archivo(p: dict, archivo: Path, fuente: str, sha: str | None, tipologias: dict[str, dict],
                     bit: Bitacora, hoy: str, res: ResumenBrochures) -> None:
    texto, paginas = br.extraer_texto(archivo)
    reg = {"url": fuente, "archivo": str(archivo), "sha256": sha, "paginas": paginas,
           "caracteres": len(texto.strip()), "procesado": hoy}
    if len(texto.strip()) < br.MIN_CARACTERES:
        reg["estado"] = "requiere_ocr"
        res.detalles.append(f"{p['id']} {p.get('nombre')}: PDF de {paginas} págs. sin texto extraíble (requiere OCR)")
    else:
        tps = _tipologias_de(p, tipologias)
        datos = br.extraer_datos(texto)
        cambios = aplicar_datos(p, datos, fuente, tps, bit, hoy)
        reg.update(estado="procesado", campos=cambios)
        res.procesados += 1
        res.areas_asignadas += sum(int(c.split("×")[1]) for c in cambios if c.startswith("area_privada×"))
        res.detalles.append(f"{p['id']} {p.get('nombre')}: {paginas} págs. → {', '.join(cambios) or 'sin datos nuevos'}")
        if falta_para_ia(p, tps):
            res.para_ia.append((p["id"], archivo.with_suffix(".txt")))
    p.setdefault("brochures", []).append(reg)
    bit.registrar(p["id"], "brochure", reg["estado"], url=fuente, paginas=paginas, caracteres=reg["caracteres"])


def procesar(proyectos: dict[str, dict], tipologias: dict[str, dict], session: requests.Session,
             bit: Bitacora, hoy: date) -> ResumenBrochures:
    """Descarga las URLs nuevas de cada proyecto activo y procesa los PDF."""
    res, h = ResumenBrochures(), hoy.isoformat()
    for p in sorted(proyectos.values(), key=lambda x: x["id"]):
        if not p.get("activo"):
            continue
        vistas = {b["url"] for b in p.get("brochures") or []}
        for url in p.get("brochure_urls") or []:
            if url in vistas:
                continue
            d = br.descargar(url, p["id"], session)
            if not d.ok:
                p.setdefault("brochures", []).append({"url": url, "estado": "no_descargable", "motivo": d.motivo, "procesado": h})
                bit.registrar(p["id"], "brochure", "no_descargable", url=url, motivo=d.motivo)
                res.detalles.append(f"{p['id']} {p.get('nombre')}: no se pudo descargar ({d.motivo})")
                continue
            if any(b.get("sha256") == d.sha256 for b in p.get("brochures") or []):
                continue  # mismo PDF desde otra URL
            res.descargados += 1
            procesar_archivo(p, d.archivo, url, d.sha256, tipologias, bit, h, res)
    return res


def agregar_urls(p: dict, urls: list[str]) -> int:
    existentes = p.setdefault("brochure_urls", [])
    nuevas = [u for u in urls if reglas.es_url(u) and u not in existentes]
    existentes.extend(nuevas)
    return len(nuevas)


# ---------- Lectura asistida (IA sin web): verificación literal ----------

def verificar_propuesta_ia(datos: dict, texto: str) -> tuple[dict, list[str]]:
    """Deja pasar solo lo que aparece en el texto del PDF."""
    import re
    from vivienda.texto import sin_tildes
    t = sin_tildes(texto)
    ok, rechazos = {}, []
    for a in datos.get("areas") or []:
        try:
            priv, cons = float(a["privada"]), float(a["construida"])
        except (KeyError, TypeError, ValueError):
            rechazos.append(f"área mal formada: {a}")
            continue
        if br.aparece_en_texto(priv, texto) and br.aparece_en_texto(cons, texto):
            ok.setdefault("areas", []).append({"privada": priv, "construida": cons})
        else:
            rechazos.append(f"área {priv}/{cons} no aparece en el PDF")
    for k in ("estrato", "admin_m2", "parqueaderos"):
        if datos.get(k) is not None:
            (ok.__setitem__(k, datos[k]) if br.aparece_en_texto(datos[k], texto)
             else rechazos.append(f"{k}={datos[k]} no aparece en el PDF"))
    if datos.get("ascensor") is not None:
        (ok.__setitem__("ascensor", bool(datos["ascensor"])) if re.search(r"\bascensor", t)
         else rechazos.append("ascensor: la palabra no aparece en el PDF"))
    if datos.get("acabados"):
        clave = "obra gris" if datos["acabados"] == "obra gris" else "acabad"
        (ok.__setitem__("acabados", datos["acabados"]) if clave in t
         else rechazos.append(f"acabados={datos['acabados']} sin respaldo en el texto"))
    if datos.get("entrega") and str(datos["entrega"])[:4] in t:
        ok["entrega"] = datos["entrega"]
    if datos.get("direccion") and br.aparece_en_texto(datos["direccion"], texto):
        ok["direccion"] = datos["direccion"]
    return ok, rechazos
