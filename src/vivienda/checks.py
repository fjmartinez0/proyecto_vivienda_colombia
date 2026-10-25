"""Bitácora append-only de cada verificación externa (data/checks.jsonl).
Nunca se reescribe; git es el historial de auditoría."""
from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

from vivienda.config import DATA_DIR

ARCHIVO = DATA_DIR / "checks.jsonl"


class Bitacora:
    def __init__(self, path: Path = ARCHIVO):
        self.path = path
        self.pendientes: list[dict] = []

    def registrar(self, proyecto_id: str, tipo: str, resultado: str, **detalle) -> None:
        self.pendientes.append({
            "ts": datetime.now().astimezone().isoformat(timespec="seconds"),
            "proyecto_id": proyecto_id, "tipo": tipo, "resultado": resultado, **detalle,
        })

    def guardar(self) -> None:
        if not self.pendientes:
            return
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with open(self.path, "a", encoding="utf-8") as f:
            for c in self.pendientes:
                f.write(json.dumps(c, ensure_ascii=False) + "\n")
        self.pendientes.clear()
