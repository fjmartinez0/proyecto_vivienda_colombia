"""Pestaña "Nuevo vs Reventa" (v0.17): cuánto se paga por estrenar y cómo se mueve el precio en el tiempo.

Todo sale de lo que ya se descarga; lo único manual es una semilla (config/nuevo_vs_reventa.toml, hoy Open C60)
mientras la parte automática se llena.

Por proyecto del radar, tres momentos, cada precio con su FUENTE:
  base    (constructora) unidad base = la tipología más barata ("precio desde" con su "área desde"), primer día visto
  entrega (constructora) precio de la unidad base cuando la entrega pasa a "probable" o "confirmada"
  hoy     (mercado)      reventas en el mismo edificio: usados a <= 40 m del pin, que no son unidades de proyecto

Una tasa solo se calcula entre precios de la MISMA fuente:
  ① lista en obra        constructora -> constructora, antes de la entrega, mismo metraje ±10 %, 6+ meses
  ② prima de "nuevo"     mercado vs. constructora, área ±25 %, a menos de 9 meses (diferencia, no tasa anual)
  ③ después de entregar  mercado -> mercado, mismo metraje ±10 %, 6+ meses

② también sale automático de Fincaraíz para cualquier edificio nuevo de las zonas: en un mismo punto, anuncios de
la constructora (publicador builder/developer) frente a anuncios de dueños o inmobiliarias.

Estado de la entrega (no se da por hecha con la fecha estimada, que se corre seguido):
  estimada   ninguna señal
  probable   >= 1 señal: la fecha estimada pasó · el portal dice "entrega inmediata" · anuncios con administración
             en el pin del edificio
  confirmada >= 2 señales y una es una reventa (anuncio de un dueño con administración en el edificio)
"""
from __future__ import annotations

import statistics
import tomllib
import unicodedata
from datetime import date
from pathlib import Path

from vivienda.config import CONFIG_DIR
from vivienda.geo import distancia_m

ARCHIVO_SEMILLA = CONFIG_DIR / "nuevo_vs_reventa.toml"
ARCHIVO_INDICES = CONFIG_DIR / "indices.toml"
RADIO_EDIFICIO_M = 40
TOL_ZONA_M = 150                 # proyectos del radar fuera de zona pero a <= 150 m entran
TOL_MISMO_METRAJE = 0.10
TOL_PAREJA = 0.25
MAX_ANIOS_PAREJA = 0.75
MIN_ANIOS_TASA = 0.49
MAX_ANTIG_NUEVO = 2               # años: un anuncio más viejo en el pin es de otro edificio
PUBLICADORES_CONSTRUCTORA = {"builder", "constructora", "developer"}


# ---------------------------------------------------------------- utilidades

def fecha(txt: str | None) -> date | None:
    """'2026-10' (día 15) o '2026-10-25'."""
    if not txt:
        return None
    partes = [int(x) for x in str(txt)[:10].split("-")]
    if len(partes) == 1:
        return date(partes[0], 7, 1)
    return date(partes[0], partes[1], partes[2] if len(partes) > 2 else 15)


def anios(f0: date, f1: date) -> float:
    return (f1 - f0).days / 365.25


def _med(v):
    v = [x for x in v if x is not None]
    return statistics.median(v) if v else None


def _norm(t: str | None) -> str:
    t = unicodedata.normalize("NFKD", t or "").encode("ascii", "ignore").decode().lower()
    return " ".join("".join(c if c.isalnum() else " " for c in t).split())


def area_construida(u: dict) -> float | None:
    if not u.get("area"):
        return None
    return u["area"] / 0.88 if u.get("area_tipo") == "privada" else u["area"]


def m2(p: dict) -> float:
    return p["precio"] / p["area"]


def ipc_anual(path: Path = ARCHIVO_INDICES) -> float | None:
    """Última variación anual del IPC cargada (para la línea de referencia y las tasas reales)."""
    try:
        anual = (tomllib.loads(path.read_text(encoding="utf-8")).get("ipc") or {}).get("anual") or {}
    except FileNotFoundError:
        return None
    return anual[max(anual, key=int)] / 100 if anual else None


# ---------------------------------------------------------------- unidad base y reventas

def serie_base(proyecto: dict) -> list[dict]:
    """Serie de la unidad base (tipología más barata) en el tiempo. Un punto cada vez que cambia el par
    (área desde, precio desde). Fuente constructora."""
    series = []
    for t in proyecto.get("tipologias") or []:
        s = sorted((fecha(x.get("fecha")), x.get("precio"), bool(x.get("fecha_aprox")))
                   for x in (t.get("precios") or []) if x.get("precio") and x.get("fecha"))
        if s and t.get("area"):
            series.append((t, s))
    fechas = sorted({f for _, s in series for f, _, _ in s})
    out = []
    for f in fechas:
        vigentes = []
        for t, s in series:
            ultimo = [x for x in s if x[0] <= f]
            if ultimo:
                vigentes.append((ultimo[-1][1], t["area"], ultimo[-1][2]))
        if not vigentes:
            continue
        precio, area, aprox = min(vigentes)
        if not out or (out[-1]["precio"], out[-1]["area"]) != (precio, area):
            out.append({"fecha": f.isoformat(), "area": area, "precio": precio, "fuente": "c",
                        "estado": "aprox" if aprox else "ok", "origen": proyecto.get("fuente") or "Estrenar Vivienda"})
    return out


def reventas_edificio(lat: float | None, lng: float | None, usados: list[dict], nombre: str | None = None,
                      radio_m: float = RADIO_EDIFICIO_M) -> tuple[list[dict], list[dict]]:
    """(reventas, todos_los_anuncios_del_pin). Reventa = anuncio en el pin que no es unidad de proyecto.
    'ok' si el anuncio nombra el edificio; si no, 'verificar'."""
    if lat is None or lng is None:
        return [], []
    nn = _norm(nombre)
    pin, rev = [], []
    for u in usados:
        if u.get("lat") is None or distancia_m(lat, lng, u["lat"], u["lng"]) > radio_m:
            continue
        if u.get("antiguedad") is not None and u["antiguedad"] >= MAX_ANTIG_NUEVO:
            continue                      # edificio vecino más viejo en el mismo pin: no es este proyecto
        pin.append(u)
        ac = area_construida(u)
        if u.get("unidad_proyecto") or not ac or not u.get("precio"):
            continue
        texto = _norm(u.get("descripcion"))
        rev.append({"fecha": (u.get("creado_portal") or u.get("detectado") or "")[:10], "area": round(ac, 1),
                    "precio": u["precio"], "fuente": "m", "id": u.get("id"), "url": u.get("url"),
                    "admin": u.get("admin"), "piso": u.get("piso"),
                    "estado": "ok" if nn and len(nn) >= 4 and nn in texto else "verificar",
                    "origen": "Fincaraíz (reventa)"})
    return sorted(rev, key=lambda r: r["fecha"]), pin


def estado_entrega(p: dict, pin: list[dict], hoy: date) -> dict:
    senales = []
    ent = fecha(p.get("entrega"))
    if ent and ent <= hoy:
        senales.append("la fecha estimada pasó")
    if "inmediata" in (p.get("estado") or "").lower():
        senales.append('el portal dice "entrega inmediata"')
    con_admin = [u for u in pin if u.get("admin")]
    reventa = any(not u.get("unidad_proyecto") for u in con_admin)
    if con_admin:
        senales.append(f"{len(con_admin)} anuncio(s) con administración en el edificio")
    estado = "confirmada" if len(senales) >= 2 and reventa else "probable" if senales else "estimada"
    return {"estado": estado, "senales": senales}


# ---------------------------------------------------------------- los tres números

def metricas(base: list[dict], entrega: list[dict], lista: list[dict], hoy_: list[dict],
             fin_obra: date | None) -> dict:
    C = sorted(base + entrega + lista, key=lambda x: x["fecha"])
    M = sorted(hoy_, key=lambda x: x["fecha"])
    obra = None
    CO = [c for c in C if not fin_obra or fecha(c["fecha"]) <= fin_obra]
    for i, a in enumerate(CO):
        for b in reversed(CO[i + 1:]):
            t = anios(fecha(a["fecha"]), fecha(b["fecha"]))
            if abs(b["area"] / a["area"] - 1) <= TOL_MISMO_METRAJE and t >= MIN_ANIOS_TASA:
                acc = m2(b) / m2(a) - 1
                obra = {"acc": acc, "anual": (1 + acc) ** (1 / t) - 1, "desde": a["fecha"], "hasta": b["fecha"],
                        "verificar": "verificar" in (a["estado"], b["estado"])}
                break
        if obra:
            break
    prima = None
    pares = []
    for m in M:
        cands = [c for c in C if abs(anios(fecha(c["fecha"]), fecha(m["fecha"]))) <= MAX_ANIOS_PAREJA]
        cands.sort(key=lambda c: abs(c["area"] - m["area"]))
        if cands and abs(m["area"] / cands[0]["area"] - 1) <= TOL_PAREJA:
            pares.append((m2(m) / m2(cands[0]) - 1, m["estado"] == "verificar" or cands[0]["estado"] == "verificar"))
    if pares:
        v = [x for x, _ in pares]
        prima = {"v": statistics.median(v), "min": min(v), "max": max(v), "n": len(v),
                 "verificar": any(f for _, f in pares)}
    post = None
    if len(M) > 1:
        a, b = M[0], M[-1]
        t = anios(fecha(a["fecha"]), fecha(b["fecha"]))
        if t >= MIN_ANIOS_TASA and abs(b["area"] / a["area"] - 1) <= TOL_MISMO_METRAJE:
            post = {"anual": (m2(b) / m2(a)) ** (1 / t) - 1}
    return {"obra": obra, "prima": prima, "post": post}


def variacion(base: list[dict], hoy: date) -> dict:
    """Variación del precio de la unidad base desde el primer día visto (sección 2)."""
    if not base:
        return {}
    a, b = base[0], base[-1]
    dias = (hoy - fecha(a["fecha"])).days
    if abs(b["area"] / a["area"] - 1) > TOL_MISMO_METRAJE:
        return {"dias": dias, "cambio_unidad": True}
    acc = m2(b) / m2(a) - 1
    return {"dias": dias, "cambio": acc,
            "anual": (1 + acc) ** (365.25 / dias) - 1 if dias >= 180 else None}


# ---------------------------------------------------------------- prima automática en Fincaraíz

def prima_automatica(usados: list[dict], excluir: list[tuple[float, float]]) -> list[dict]:
    """Edificios nuevos con anuncios de la constructora y de particulares en el mismo pin."""
    grupos: dict[str, list[dict]] = {}
    for u in usados:
        if u.get("lat") is None or not u.get("zona"):
            continue
        grupos.setdefault(u.get("edificio") or f"{round(u['lat'], 4)},{round(u['lng'], 4)}", []).append(u)
    out = []
    for k, g in grupos.items():
        lat, lng = g[0]["lat"], g[0]["lng"]
        if any(distancia_m(lat, lng, a, b) <= RADIO_EDIFICIO_M for a, b in excluir):
            continue
        g = [u for u in g if area_construida(u) and (u.get("antiguedad") is None or u["antiguedad"] < MAX_ANTIG_NUEVO)]
        C = [u for u in g if (u.get("publicador") or "").lower() in PUBLICADORES_CONSTRUCTORA]
        M = [u for u in g if u not in C and not u.get("unidad_proyecto")]
        if not C or not M:
            continue
        ratios = []
        for m in M:
            fm = fecha(m.get("creado_portal") or m.get("detectado"))
            cs = [c for c in C if abs(anios(fecha(c.get("creado_portal") or c.get("detectado")), fm)) <= MAX_ANIOS_PAREJA]
            cs.sort(key=lambda c: abs(area_construida(c) - area_construida(m)))
            if cs and abs(area_construida(m) / area_construida(cs[0]) - 1) <= TOL_PAREJA:
                ratios.append((m["precio"] / area_construida(m)) / (cs[0]["precio"] / area_construida(cs[0])) - 1)
        if ratios:
            out.append({"edificio": k, "zona": g[0]["zona"], "barrio": g[0].get("barrio"), "lat": lat, "lng": lng,
                        "n_constructora": len(C), "n_reventa": len(M), "url": M[0].get("url"),
                        "prima": {"v": statistics.median(ratios), "min": min(ratios), "max": max(ratios),
                                  "n": len(ratios), "verificar": False}})
    return sorted(out, key=lambda r: r["prima"]["v"])


# ---------------------------------------------------------------- semilla manual

def cargar_semilla(path: Path = ARCHIVO_SEMILLA) -> list[dict]:
    if not path.exists():
        return []
    out = []
    for p in tomllib.loads(path.read_text(encoding="utf-8")).get("proyecto", []):
        puntos = {"base": [], "entrega": [], "lista": [], "hoy": []}
        for x in p.get("precio", []):
            puntos[x["momento"]].append({"fecha": x["fecha"], "area": x["area"], "precio": x["precio"],
                                         "fuente": "m" if x["momento"] == "hoy" else "c",
                                         "estado": x.get("estado", "ok"), "origen": x.get("origen"),
                                         "url": x.get("url")})
        out.append({**{k: v for k, v in p.items() if k != "precio"}, **puntos})
    return out


# ---------------------------------------------------------------- todo junto

def construir(datos: dict, hoy: date, semilla: Path = ARCHIVO_SEMILLA) -> dict:
    usados = datos.get("usados") or []
    filas, pines = [], []
    for p in datos.get("proyectos") or []:
        if p.get("fuera_de_zona") and (p.get("distancia_zona_m") or 0) > TOL_ZONA_M:
            continue
        base = serie_base(p)
        if not base:
            continue
        rev, pin = reventas_edificio(p.get("lat"), p.get("lng"), usados, p.get("nombre"))
        est = estado_entrega(p, pin, hoy)
        entrega = []
        if est["estado"] != "estimada":
            ent = fecha(p.get("entrega")) or hoy
            antes = [b for b in base if fecha(b["fecha"]) <= max(ent, fecha(base[0]["fecha"]))]
            if antes:
                entrega = [{**antes[-1], "estado": "ok" if est["estado"] == "confirmada" else "aprox"}]
        hoy_ = rev if est["estado"] != "estimada" else []
        fin = fecha(p.get("entrega"))
        pines.append((p.get("lat"), p.get("lng")))
        filas.append({"id": p["id"], "nombre": p.get("nombre"), "constructora": p.get("constructora"),
                      "zona": p.get("zona"), "fuera_de_zona": p.get("fuera_de_zona"), "lat": p.get("lat"),
                      "lng": p.get("lng"), "entrega": p.get("entrega"), "entrega_estado": est,
                      "base": base, "entrega_pts": entrega, "lista": [], "hoy": hoy_,
                      "metricas": metricas(base, entrega, [], hoy_, fin), "variacion": variacion(base, hoy),
                      "manual": False, "contacto": p.get("contacto"),
                      "cotizacion": next((t.get("precio") for t in p.get("tipologias") or []
                                          if "cotizacion" in str(t.get("url") or "")), None)})
    for s in cargar_semilla(semilla):
        fin = fecha(s.get("entrega_obra") or s.get("entrega"))
        filas.append({"id": s["id"], "nombre": s["nombre"], "constructora": s.get("constructora"),
                      "zona": s.get("zona"), "fuera_de_zona": False, "lat": s.get("lat"), "lng": s.get("lng"),
                      "entrega": s.get("entrega"), "entrega_estado": {"estado": s.get("estado_entrega", "confirmada"),
                                                                      "senales": ["cargado a mano"]},
                      "base": s["base"], "entrega_pts": s["entrega"], "lista": s["lista"], "hoy": s["hoy"],
                      "metricas": metricas(s["base"], s["entrega"], s["lista"], s["hoy"], fin),
                      "variacion": variacion(s["base"], hoy), "manual": True, "nota": s.get("nota"),
                      "fase": s.get("fase")})
        if s.get("lat") is not None:
            pines.append((s["lat"], s["lng"]))
    auto = prima_automatica(usados, [x for x in pines if x[0] is not None])
    primas = [f["metricas"]["prima"]["v"] for f in filas if f["metricas"]["prima"]] + [a["prima"]["v"] for a in auto]
    obras = [f["metricas"]["obra"]["acc"] for f in filas if f["metricas"]["obra"]]
    return {"proyectos": filas, "prima_auto": auto, "ipc_anual": ipc_anual(),
            "resumen": {"prima_mediana": _med(primas), "n_prima": len(primas), "n_prima_auto": len(auto),
                        "obra_mediana": _med(obras), "n_obra": len(obras),
                        "entregas": {e: sum(1 for f in filas if f["entrega_estado"]["estado"] == e)
                                     for e in ("estimada", "probable", "confirmada")}}}


def _pct(v):
    return "—" if v is None else f"{v * 100:+.1f} %".replace(".", ",")


def reporte(b: dict) -> str:
    r = b["resumen"]
    lineas = [f"NUEVO VS REVENTA · prima de 'nuevo' mediana {_pct(r['prima_mediana'])} (n={r['n_prima']}, "
              f"{r['n_prima_auto']} automáticos) · lista en obra mediana {_pct(r['obra_mediana'])} (n={r['n_obra']})",
              f"Entregas: {r['entregas']}"]
    for f in b["proyectos"]:
        m = f["metricas"]
        lineas.append(f"  {'*' if f['manual'] else ' '} {f['nombre']:<24} entrega {f['entrega_estado']['estado']:<10} "
                      f"① {_pct((m['obra'] or {}).get('acc'))}  ② {_pct((m['prima'] or {}).get('v'))}  "
                      f"reventas {len(f['hoy'])}")
    for a in b["prima_auto"][:10]:
        lineas.append(f"  auto {a['barrio'] or a['edificio']:<22} ② {_pct(a['prima']['v'])} "
                      f"({a['n_constructora']} constructora / {a['n_reventa']} reventa)")
    lineas.append("  * = semilla manual (config/nuevo_vs_reventa.toml)")
    return "\n".join(lineas)
