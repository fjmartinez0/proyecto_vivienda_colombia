"""Utilidades de texto compartidas."""
from __future__ import annotations

import re
import unicodedata


def normalizar(txt: str | None) -> str:
    """'Cañaveral' -> 'canaveral' ; 'chapinero-alto' -> 'chapinero alto'"""
    if not txt:
        return ""
    t = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()
    return " ".join(t.lower().replace("-", " ").split())


def sin_tildes(txt: str | None) -> str:
    """Como normalizar() pero conserva guiones y '#': 'Cra. 13 No. 61-45' -> 'cra. 13 no. 61-45'"""
    if not txt:
        return ""
    t = unicodedata.normalize("NFKD", txt).encode("ascii", "ignore").decode()
    return " ".join(t.lower().split())


def slug(txt: str | None) -> str:
    return normalizar(txt).replace(" ", "-")


def solo_alfanumerico(txt: str | None) -> str:
    """Para buscar una dirección dentro de una página: 'Cl. 67 # 5-30' -> 'cl 67 5 30'"""
    return " ".join(re.sub(r"[^a-z0-9]+", " ", normalizar(txt)).split())
