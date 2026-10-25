"""Parser de los listados por sector de Estrenar Vivienda.

Cada tarjeta (.card-project__wrapper) es una TIPOLOGÍA, no un proyecto:
un mismo proyecto aparece varias veces con distinto typology-id.
El sitio publica área CONSTRUIDA (lo indica el tooltip de la tarjeta).
"""
from __future__ import annotations

import re

from bs4 import BeautifulSoup, Tag

from vivienda.models import Tipologia

FUENTE = "estrenarvivienda"
_RE_UBICACION = re.compile(r"^(.*?) en venta en (.*)$")


def _numero(txt: str | None) -> float | None:
    """'58.22 m2' -> 58.22 ; '2 hab.' -> 2.0"""
    if not txt:
        return None
    m = re.search(r"\d+(?:[.,]\d+)?", txt.replace(" ", ""))
    return float(m.group().replace(",", ".")) if m else None


def _pesos(txt: str | None) -> int | None:
    """'$ 1. 869. 000.000' -> 1869000000"""
    if not txt:
        return None
    digitos = re.sub(r"\D", "", txt)
    return int(digitos) if digitos else None


def _caracteristicas(card: Tag) -> dict:
    out = {"area": None, "habs": None, "banos": None, "parq": None, "parq_comunal": False}
    for el in card.select(".card-project__features-item-value"):
        t = el.get_text(" ", strip=True)
        tl = t.lower()
        if "m 2" in tl or "m2" in tl:
            out["area"] = _numero(t)
        elif "hab" in tl:
            out["habs"] = int(_numero(t) or 0) or None
        elif "bañ" in tl:
            out["banos"] = int(_numero(t) or 0) or None
        elif "comunal" in tl:
            out["parq_comunal"] = True
        elif "parq" in tl:
            out["parq"] = int(_numero(t) or 0)
    return out


def _ubicacion(card: Tag) -> tuple[str | None, str | None, str | None]:
    """'Apartamentos en venta en Chapinero Alto, Bogotá' -> (tipo, sector, ciudad)"""
    img = card.select_one("img[title]")
    titulo = img["title"] if img else ""
    m = _RE_UBICACION.match(titulo)
    if not m:
        return None, None, None
    partes = [p.strip() for p in m.group(2).split(",")]
    return m.group(1), (", ".join(partes[:-1]) or None), partes[-1]


def _parse_card(card: Tag) -> Tipologia | None:
    btn = card.select_one("button[typology-id]")
    link = card.select_one("a[href]")
    if not btn and not link:
        return None
    href = link["href"] if link else ""
    tipo, sector, ciudad = _ubicacion(card)
    precio_attr = btn.get("typology-price", "") if btn else ""
    precio_el = card.select_one(".card-project__price-value")
    banner = card.select_one("[class*=card-project__banner]")
    builder = card.select_one(".card-project__builder img")

    return Tipologia(
        fuente=FUENTE,
        typology_id=btn["typology-id"] if btn else href.rstrip("/").split("/")[-1],
        proyecto=(btn.get("typology-name") or "").strip() or None if btn else None,
        url=href,
        constructora=btn.get("builder-name") if btn
        else (builder["title"].replace("Un proyecto de ", "") if builder else None),
        tipo_inmueble=tipo,
        sector=sector,
        ciudad=ciudad,
        area_tipo="construida",
        precio_desde=int(precio_attr) if precio_attr.isdigit()
        else _pesos(precio_el.get_text(" ", strip=True) if precio_el else None),
        etiqueta=banner.get_text(" ", strip=True) if banner else None,
        **_caracteristicas(card),
    )


def parse_html(html: str) -> list[Tipologia]:
    """Devuelve las tipologías de una página, sin duplicados."""
    soup = BeautifulSoup(html, "lxml")
    vistos: set[str] = set()
    out: list[Tipologia] = []
    for card in soup.select(".card-project__wrapper"):
        t = _parse_card(card)
        if t and t.typology_id not in vistos:
            vistos.add(t.typology_id)
            out.append(t)
    return out
