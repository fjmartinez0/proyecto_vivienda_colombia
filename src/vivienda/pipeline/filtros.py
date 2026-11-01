"""Filtros duros: lo que no los pasa nunca entra al análisis."""
from __future__ import annotations

from collections import Counter

from vivienda.config import Filtros
from vivienda.models import Tipologia
from vivienda.texto import normalizar


def pertenece_al_sector(t: Tipologia, ruta: str) -> bool:
    """Las páginas de sector incluyen tarjetas recomendadas de otras ciudades.
    Solo se acepta la tarjeta si su sector coincide con el de la URL."""
    esperado = normalizar(ruta.rstrip("/").split("/")[-1])
    partes = [normalizar(p) for p in (t.sector or "").split(",")]
    return esperado in partes


def segmento(area: float | None, f: Filtros) -> str:
    """'micro' (< area_min construidos, tipo Alma 72) o 'estandar'."""
    return "micro" if (area or 0) < f.area_min else "estandar"


def motivo_descarte(t: Tipologia, f: Filtros) -> str | None:
    """Desde v0.13 las tipologías de area_min_micro a area_min ya no se descartan: son el segmento micro."""
    if not t.precio_desde:
        # un proyecto ingresado a mano puede no tener precio publicado: se muestra igual
        return None if t.fuente == "manual" and (t.area or 0) >= f.area_min_micro else "sin precio"
    if t.precio_desde > f.precio_max:
        return "sobre tope de precio"
    if (t.area or 0) < f.area_min_micro:
        return f"área < {f.area_min_micro:g} m²"
    return None


def aplicar(tipologias: list[Tipologia], f: Filtros) -> tuple[list[Tipologia], Counter]:
    ok: list[Tipologia] = []
    descartes: Counter = Counter()
    for t in tipologias:
        m = motivo_descarte(t, f)
        if m:
            descartes[m] += 1
        else:
            ok.append(t)
    return ok, descartes
