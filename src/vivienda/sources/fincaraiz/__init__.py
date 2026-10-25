"""Fuente: Fincaraíz (vivienda usada). Lógica heredada del proyecto anterior (documento maestro)."""
from .cliente import ClienteFincaraiz, url_barrio
from .parser import TIPOS_VALIDOS, parsear

FUENTE = "fincaraiz"

__all__ = ["ClienteFincaraiz", "url_barrio", "parsear", "TIPOS_VALIDOS", "FUENTE"]
