"""Descarga de los listados por sector de Estrenar Vivienda.

Guarda cada HTML en data/raw/estrenarvivienda/AAAA-MM-DD/ para poder
re-procesar sin volver a descargar y para auditar cambios en el tiempo.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass
from datetime import date
from pathlib import Path

import requests

from vivienda.config import RAW_DIR, EstrenarConfig, Sector

log = logging.getLogger(__name__)


@dataclass
class ResultadoDescarga:
    sector: Sector
    url: str
    estado: int | str
    archivo: Path | None

    @property
    def ok(self) -> bool:
        return self.archivo is not None


class EstrenarFetcher:
    def __init__(self, cfg: EstrenarConfig, raw_dir: Path = RAW_DIR, hoy: date | None = None):
        self.cfg = cfg
        self.dir = raw_dir / "estrenarvivienda" / (hoy or date.today()).isoformat()
        self.session = requests.Session()
        self.session.headers.update({
            "User-Agent": cfg.user_agent,
            "Accept-Language": "es-CO,es;q=0.9",
        })

    def descargar_sector(self, sector: Sector) -> ResultadoDescarga:
        url = self.cfg.base_url + sector.ruta
        try:
            r = self.session.get(url, timeout=self.cfg.timeout_segundos)
        except requests.RequestException as e:
            log.warning("Error de red en %s: %s", url, e)
            return ResultadoDescarga(sector, url, f"error: {e.__class__.__name__}", None)

        if r.status_code != 200 or "card-project__wrapper" not in r.text:
            estado = r.status_code if r.status_code != 200 else "200 sin tarjetas"
            return ResultadoDescarga(sector, url, estado, None)

        self.dir.mkdir(parents=True, exist_ok=True)
        archivo = self.dir / (sector.ruta.replace("/", "__") + ".html")
        archivo.write_text(r.text, encoding="utf-8")
        return ResultadoDescarga(sector, url, 200, archivo)

    def descargar_todos(self, sectores: tuple[Sector, ...] | None = None) -> list[ResultadoDescarga]:
        sectores = sectores or self.cfg.sectores
        resultados = []
        for i, s in enumerate(sectores):
            if i:
                time.sleep(self.cfg.pausa_segundos)
            res = self.descargar_sector(s)
            log.info("%-20s %s", res.estado, s.ruta)
            resultados.append(res)
        return resultados
