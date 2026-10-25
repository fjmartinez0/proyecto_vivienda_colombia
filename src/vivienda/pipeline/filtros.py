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


def motivo_descarte(t: Tipologia, f: Filtros) -> str | None:
    if not t.precio_desde:
        # un proyecto ingresado a mano puede no tener precio publicado: se muestra igual
        return None if t.fuente == "manual" and (t.area or 0) >= f.area_min else "sin precio"
    if t.precio_desde > f.precio_max:
        return "sobre tope de precio"
    if (t.area or 0) < f.area_min:
        return f"área < {f.area_min:g} m²"
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
