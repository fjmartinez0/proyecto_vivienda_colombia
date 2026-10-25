"""Carga de configuración y rutas del proyecto."""
from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
CONFIG_DIR = ROOT / "config"
DATA_DIR = ROOT / "data"
RAW_DIR = DATA_DIR / "raw"
PROCESSED_DIR = DATA_DIR / "processed"


@dataclass(frozen=True)
class Sector:
    ruta: str
    zonas: tuple[str, ...]
    verificado: bool


@dataclass(frozen=True)
class EstrenarConfig:
    base_url: str
    pausa_segundos: float
    timeout_segundos: float
    user_agent: str
    sectores: tuple[Sector, ...]


@dataclass(frozen=True)
class Filtros:
    precio_max: int
    area_min: float


@dataclass(frozen=True)
class AgenteConfig:
    modelo: str
    max_turns: int
    max_proyectos: int
    timeout_minutos: int


@dataclass(frozen=True)
class BarrioFR:
    ruta: str
    ciudad: str
    verificado: bool


@dataclass(frozen=True)
class FincaraizConfig:
    max_paginas: int
    dias_vigencia: int
    pausa_segundos: tuple[float, float]
    barrios: tuple[BarrioFR, ...]


@dataclass(frozen=True)
class DiarioConfig:
    hora: str = "06:30"
    max_paginas_usados: int | None = None   # None = [fincaraiz] max_paginas
    max_paginas_profundo: int = 40          # un día a la semana, para refrescar el inventario viejo
    dia_profundo: int = 6                   # 0 = lunes … 6 = domingo; -1 = nunca
    ubicar_max: int = 3                     # 0 = nunca llamar al agente en la rutina
    publicar: bool = False
    url_dashboard: str = ""
    alerta_bajas_precio: bool = True
    alerta_usados_baratos: bool = True
    umbral_usado_barato: float = 0.15
    alerta_fallas: bool = True


@dataclass(frozen=True)
class Config:
    nombre: str
    filtros: Filtros
    estrenar: EstrenarConfig
    agente: AgenteConfig
    nominatim_user_agent: str
    fincaraiz: FincaraizConfig | None = None
    diario: DiarioConfig = DiarioConfig()


def cargar(path: Path = CONFIG_DIR / "config.toml") -> Config:
    with open(path, "rb") as f:
        raw = tomllib.load(f)
    e = raw["estrenar"]
    return Config(
        nombre=raw["proyecto"]["nombre"],
        filtros=Filtros(**raw["filtros"]),
        estrenar=EstrenarConfig(
            base_url=e["base_url"],
            pausa_segundos=e["pausa_segundos"],
            timeout_segundos=e["timeout_segundos"],
            user_agent=e["user_agent"],
            sectores=tuple(
                Sector(s["ruta"], tuple(s["zonas"]), s.get("verificado", False))
                for s in e["sectores"]
            ),
        ),
        agente=AgenteConfig(**raw["agente"]),
        nominatim_user_agent=raw["verificacion"]["nominatim_user_agent"],
        fincaraiz=_fincaraiz(raw.get("fincaraiz")),
        diario=DiarioConfig(**raw.get("diario", {})),
    )


def _fincaraiz(f: dict | None) -> FincaraizConfig | None:
    if not f:
        return None
    return FincaraizConfig(
        max_paginas=f.get("max_paginas", 8),
        dias_vigencia=f.get("dias_vigencia", 7),
        pausa_segundos=tuple(f.get("pausa_segundos", (3, 6))),
        barrios=tuple(BarrioFR(b["ruta"], b["ciudad"], b.get("verificado", False)) for b in f.get("barrios", [])),
    )


def cargar_zonas() -> dict:
    """Zonas como GeoJSON desde config/zonas.toml. Usa el polígono por esquinas si `vivienda zonas`
    ya lo calculó; si no, el círculo. Nunca consulta internet."""
    from vivienda.pipeline.zonas import a_geojson, cargar_definiciones, cargar_poligonos
    return a_geojson(cargar_definiciones(), cargar_poligonos())
