"""Reglas de negocio y valores permitidos.

"La IA propone; el código decide": todo lo que importa se valida aquí,
no solo en el prompt del agente. El merger y las pruebas usan estas reglas.
"""
from __future__ import annotations

import re
from urllib.parse import urlparse

RENTA_CORTA = {"permitida", "prohibida", "desconocida"}
ACABADOS = {"full", "semi", "obra gris", "desconocido"}
ESTADO_OBRA = {"sobre planos", "en construccion", "entrega inmediata", "desconocido"}
PRECISION = ("alta", "media", "baja")  # de mejor a peor

# Copias de terceros: nunca cuentan como evidencia de ubicación.
AGREGADORES = (
    "estrenarvivienda.com", "fincaraiz.com", "metrocuadrado.com", "ciencuadras.com",
    "properati.com", "trovit.", "mitula.", "lahaus.com", "habi.co", "nuroa.", "icasas.",
)

_RE_ENTREGA = re.compile(r"^\d{4}-(0[1-9]|1[0-2])$")


def es_url(u) -> bool:
    return isinstance(u, str) and urlparse(u).scheme in ("http", "https") and bool(urlparse(u).netloc)


def es_fuente(u) -> bool:
    """URL web o archivo local (brochure ingresado a mano: file://...)."""
    return es_url(u) or (isinstance(u, str) and u.startswith("file://"))


def es_agregador(u: str | None) -> bool:
    host = urlparse(u or "").netloc.lower()
    return any(a in host for a in AGREGADORES)


def mejor_precision(a: str | None, b: str | None) -> str | None:
    """Devuelve la mejor de dos precisiones (None = sin ubicación)."""
    orden = {p: i for i, p in enumerate(PRECISION)}
    cands = [p for p in (a, b) if p in orden]
    return min(cands, key=orden.get) if cands else None


def validar_enriquecimiento(item: dict) -> tuple[dict, list[str]]:
    """Valida los campos opcionales de enriquecimiento de una propuesta.

    Devuelve (campos_aceptados, motivos_de_rechazo). Un campo sin fuente URL se rechaza.
    """
    ok, errores = {}, []

    def campo(nombre, valor, valido, transformar=lambda v: v):
        if valor in (None, "", "desconocido", "desconocida"):
            return
        fuente = item.get(f"{nombre}_fuente") or item.get("fuente_general")
        if not es_fuente(fuente):
            errores.append(f"{nombre}: sin fuente URL")
            return
        try:
            v = transformar(valor)
        except (TypeError, ValueError):
            errores.append(f"{nombre}: valor inválido {valor!r}")
            return
        if not valido(v):
            errores.append(f"{nombre}: fuera de rango {valor!r}")
            return
        ok[nombre] = {"valor": v, "fuente": fuente}

    campo("estrato", item.get("estrato"), lambda v: 1 <= v <= 6, int)
    campo("admin_m2", item.get("admin_m2"), lambda v: 1_500 <= v <= 30_000, float)
    campo("ascensor", item.get("ascensor"), lambda v: isinstance(v, bool))
    campo("parqueaderos", item.get("parqueaderos"), lambda v: 0 <= v <= 4, int)
    campo("acabados", item.get("acabados"), lambda v: v in ACABADOS, lambda v: str(v).lower())
    campo("renta_corta", item.get("renta_corta"), lambda v: v in RENTA_CORTA, lambda v: str(v).lower())
    campo("estado_obra", item.get("estado_obra"), lambda v: v in ESTADO_OBRA, lambda v: str(v).lower())
    campo("entrega", item.get("entrega"), lambda v: bool(_RE_ENTREGA.match(v)), str)
    return ok, errores
