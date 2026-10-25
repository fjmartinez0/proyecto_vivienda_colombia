"""Brochures de proyectos (PDF): descarga, texto y extracción por reglas. Sin IA.

- Solo se descargan enlaces directos a PDF. Nunca se llenan formularios.
- El texto se guarda junto al PDF para auditoría y para la lectura asistida.
- Toda cifra extraída existe literalmente en el texto (por construcción).
"""
from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass, field
from pathlib import Path

import requests

from vivienda.config import RAW_DIR
from vivienda.geocodificacion import extraer_direccion
from vivienda.sources.estrenar.ficha import entrega_desde_texto
from vivienda.texto import sin_tildes

MAX_BYTES = 30 * 1024 * 1024
MIN_CARACTERES = 300          # menos que esto = PDF de imágenes (requiere OCR)
DIR_BROCHURES = RAW_DIR / "brochures"


@dataclass
class Descarga:
    ok: bool
    archivo: Path | None = None
    sha256: str | None = None
    motivo: str = ""


def descargar(url: str, proyecto_id: str, session: requests.Session, timeout: float = 60,
              destino: Path = DIR_BROCHURES) -> Descarga:
    try:
        r = session.get(url, timeout=timeout, stream=True, allow_redirects=True)
        r.raise_for_status()
        datos = b""
        for trozo in r.iter_content(64 * 1024):
            datos += trozo
            if len(datos) > MAX_BYTES:
                return Descarga(False, motivo=f"supera {MAX_BYTES // 2**20} MB")
    except requests.RequestException as e:
        return Descarga(False, motivo=f"error de red: {e.__class__.__name__}")
    if not datos.startswith(b"%PDF"):
        tipo = r.headers.get("Content-Type", "?")
        return Descarga(False, motivo=f"no es un PDF directo ({tipo}); puede estar detrás de un formulario")
    return guardar_pdf(datos, proyecto_id, destino)


def guardar_pdf(datos: bytes, proyecto_id: str, destino: Path = DIR_BROCHURES) -> Descarga:
    sha = hashlib.sha256(datos).hexdigest()
    carpeta = destino / proyecto_id
    carpeta.mkdir(parents=True, exist_ok=True)
    archivo = carpeta / f"{sha[:12]}.pdf"
    if not archivo.exists():
        archivo.write_bytes(datos)
    return Descarga(True, archivo, sha)


def extraer_texto(archivo: Path) -> tuple[str, int]:
    """-> (texto, páginas). Guarda el texto en un .txt al lado del PDF."""
    from pypdf import PdfReader
    lector = PdfReader(str(archivo))
    texto = "\n".join((pag.extract_text() or "") for pag in lector.pages)
    archivo.with_suffix(".txt").write_text(texto, encoding="utf-8")
    return texto, len(lector.pages)


# ---------- Reglas ----------

_NUM = r"(\d{1,3}(?:[.,]\d{1,2})?)"
_M2 = r"\s*(?:m2|m²|mts2|mt2|metros cuadrados)"
_RE_PRIV = re.compile(rf"(?:area|a\.)\s*(?:privada|priv\.?)\s*(?:de|:)?\s*{_NUM}{_M2}")
_RE_CONS = re.compile(rf"(?:area|a\.)\s*(?:construida|const\.?)\s*(?:de|:)?\s*{_NUM}{_M2}")
_PALABRAS_NUM = {"un": 1, "uno": 1, "una": 1, "dos": 2, "tres": 3, "cuatro": 4, "cinco": 5, "seis": 6}
_RE_ASC = re.compile(r"\b(\d|un|uno|dos|tres|cuatro|cinco|seis)\s+ascensor(?:es)?\b")
_RE_ESTRATO = re.compile(r"\bestrato\s*:?\s*([1-6])\b")
_RE_ADMIN_M2 = re.compile(r"administraci[o]n[^$\d]{0,60}\$?\s*([\d.,]{3,7})\s*(?:/|por|x)\s*(?:m2|m²|mt2|metro)")
_RE_SEMESTRE = re.compile(r"\b([12])\s*(?:s|sem|semestre)\s*[-–]?\s*(?:de\s*)?(20\d\d)\b")


def _a_float(txt: str) -> float:
    return float(txt.replace(",", "."))


def _a_pesos(txt: str) -> float:
    return float(re.sub(r"[.,](?=\d{3}\b)", "", txt).replace(",", "."))


def pares_de_areas(texto: str) -> list[dict]:
    """Áreas privada/construida en el orden en que aparecen. Se emparejan por cercanía en el texto:
    cada área privada con la construida más cercana (antes o después)."""
    t = sin_tildes(texto)
    priv = [(m.start(), _a_float(m.group(1))) for m in _RE_PRIV.finditer(t)]
    cons = [(m.start(), _a_float(m.group(1))) for m in _RE_CONS.finditer(t)]
    pares, usados = [], set()
    for pos_p, val_p in priv:
        cands = [(abs(pos_c - pos_p), i, val_c) for i, (pos_c, val_c) in enumerate(cons) if i not in usados]
        if cands:
            dist, i, val_c = min(cands)
            if dist <= 400:
                usados.add(i)
                pares.append({"privada": val_p, "construida": val_c})
                continue
        pares.append({"privada": val_p, "construida": None})
    return pares


def extraer_datos(texto: str) -> dict:
    """Todo lo que las reglas pueden sacar de un brochure. Claves ausentes = no encontrado."""
    t = sin_tildes(texto)
    out: dict = {}
    areas = pares_de_areas(texto)
    if areas:
        out["areas"] = areas
    m = _RE_ASC.search(t)
    if m:
        out["ascensores"] = int(m.group(1)) if m.group(1).isdigit() else _PALABRAS_NUM[m.group(1)]
        out["ascensor"] = out["ascensores"] > 0
    elif re.search(r"\bascensor(?:es)?\b", t):
        out["ascensor"] = True
    m = _RE_ESTRATO.search(t)
    if m:
        out["estrato"] = int(m.group(1))
    m = _RE_ADMIN_M2.search(t)
    if m:
        out["admin_m2"] = _a_pesos(m.group(1))
    if re.search(r"\bobra\s+gris\b", t):
        out["acabados"] = "obra gris"
    elif re.search(r"\b(?:full\s+acabados|entrega\s+con\s+acabados|totalmente\s+acabad)", t):
        out["acabados"] = "full"
    entrega = entrega_desde_texto(texto)
    if not entrega:
        m = _RE_SEMESTRE.search(t)
        if m:
            entrega = f"{m.group(2)}-{6 if m.group(1) == '1' else 12:02d}"
    if entrega:
        out["entrega"] = entrega
    d = extraer_direccion(texto)
    if d:
        out["direccion"] = d
    return out


def aparece_en_texto(valor, texto: str) -> bool:
    """Verificación literal para lo que proponga la IA: la cifra debe estar en el PDF.
    41.25 se acepta como '41,25' o '41.25'; enteros como palabra completa."""
    t = sin_tildes(texto)
    if isinstance(valor, bool):
        return True  # booleanos se validan por la palabra clave asociada, no por cifra
    if isinstance(valor, (int, float)):
        v = float(valor)
        candidatos = {f"{v:g}", f"{v:.2f}", f"{v:.1f}"} if v != int(v) else {str(int(v)), f"{int(v):,}".replace(",", ".")}
        candidatos |= {c.replace(".", ",") for c in candidatos}
        return any(re.search(rf"(?<![\d.,]){re.escape(c)}(?![\d])", t) for c in candidatos)
    return sin_tildes(str(valor)) in t
