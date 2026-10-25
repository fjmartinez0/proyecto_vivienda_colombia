"""Ficha de proyecto en Estrenar Vivienda: dirección y entrega (cuando el sitio las publica).

Es un agregador: lo que se saque de aquí entra con la confianza más baja y siempre
puede ser reemplazado por una fuente oficial.
"""
from __future__ import annotations

import re
from datetime import date
from pathlib import Path

import requests
from bs4 import BeautifulSoup

from vivienda.config import RAW_DIR
from vivienda.geocodificacion import extraer_direccion

_RE_ENTREGA = re.compile(r"\b([1-4])\s*T\s*[-–]\s*(20\d\d)\b")
_RE_CATEGORIAS = re.compile(r"categor[ií]as de este proyecto:\s*(.{0,200}?)\s*(?:\d{4,}|Filtrar por)", re.IGNORECASE | re.DOTALL)
# Categorías conocidas del portal (se ignoran las demás)
CATEGORIAS = ("Renta Corta", "CoWorking", "Pet Friendly", "Vivienda Vacacional", "Smart Home",
              "Campestre", "Sostenible", "Proyecto en Feria")


def categorias_desde_texto(texto: str) -> list[str]:
    """'Conoce las categorías de este proyecto: Renta Corta CoWorking 20612' -> ['Renta Corta', 'CoWorking']"""
    m = _RE_CATEGORIAS.search(texto or "")
    if not m:
        return []
    bloque = m.group(1).lower()
    return [c for c in CATEGORIAS if c.lower() in bloque]


def entrega_desde_texto(texto: str) -> str | None:
    """'Entrega aproximada 1T - 2029' -> '2029-03' (último mes del trimestre)"""
    m = _RE_ENTREGA.search(texto or "")
    return f"{m.group(2)}-{int(m.group(1)) * 3:02d}" if m else None


def leer_ficha(url: str, session: requests.Session, timeout: float = 30,
               raw_dir: Path = RAW_DIR, hoy: date | None = None) -> dict | None:
    """Lee la ficha (de la caché del día si ya se descargó) -> {'direccion', 'entrega', 'categorias'} o None."""
    destino = raw_dir / "estrenarvivienda" / "fichas" / (hoy or date.today()).isoformat()
    archivo = destino / (url.rstrip("/").split("/")[-2] + ".html")
    if archivo.exists():
        html = archivo.read_text(encoding="utf-8")
    else:
        try:
            r = session.get(url, timeout=timeout)
            r.raise_for_status()
        except requests.RequestException:
            return None
        html = r.text
        destino.mkdir(parents=True, exist_ok=True)
        archivo.write_text(html, encoding="utf-8")
    texto = BeautifulSoup(html, "lxml").get_text(" ")
    return {"direccion": extraer_direccion(texto), "entrega": entrega_desde_texto(texto),
            "categorias": categorias_desde_texto(texto)}
