"""Modelos de datos compartidos por todas las fuentes."""
from __future__ import annotations

from dataclasses import asdict, dataclass, field


@dataclass
class Tipologia:
    """Una tipología de un proyecto nuevo (unidad mínima de comparación)."""

    fuente: str
    typology_id: str
    proyecto: str | None
    url: str
    constructora: str | None
    tipo_inmueble: str | None
    sector: str | None
    ciudad: str | None
    area: float | None
    area_tipo: str  # "privada" | "construida" | "desconocida"
    habs: int | None
    banos: int | None
    parq: int | None
    parq_comunal: bool
    precio_desde: int | None
    etiqueta: str | None = None
    sector_url: str | None = None
    zonas_candidatas: list[str] = field(default_factory=list)
    area_privada: float | None = None      # cuando la fuente la da (p. ej. brochure de un proyecto manual)
    proyecto_clave: str | None = None      # agrupación explícita (proyectos manuales)

    @property
    def clave(self) -> str:
        """Identificador único entre fuentes."""
        return f"{self.fuente}:{self.typology_id}"

    def to_dict(self) -> dict:
        return asdict(self)
