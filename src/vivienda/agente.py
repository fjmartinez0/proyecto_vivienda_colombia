"""Invocación headless de Claude Code para la tarea de ubicación/enriquecimiento.

El agente solo puede leer la web y escribir en proposals/. Su salida es no confiable:
la valida pipeline/aplicar.py.
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
from datetime import datetime
from pathlib import Path

from vivienda.config import ROOT, AgenteConfig

log = logging.getLogger(__name__)

PROMPT = ROOT / "agent" / "ubicar_prompt.md"
PROMPT_BUSCAR_BROCHURES = ROOT / "agent" / "buscar_brochures_prompt.md"
PROMPT_LEER_BROCHURE = ROOT / "agent" / "leer_brochure_prompt.md"
HERRAMIENTAS_WEB = ("WebSearch,WebFetch,Read,Write,Edit,Glob,Grep",
                    "WebSearch,WebFetch,Read,Glob,Grep,Edit(./proposals/**)")
HERRAMIENTAS_NINGUNA = ("Read", "Read")   # lectura asistida: todo va en el prompt, sin web
PROPOSALS = ROOT / "proposals"
RUN_DIR = ROOT / ".run"


def sello(momento: datetime) -> str:
    """'2026-10-25_1342': una propuesta y un log por corrida, nunca se sobrescriben."""
    return momento.strftime("%Y-%m-%d_%H%M")


def ruta_propuesta(momento: datetime, sufijo: str = "") -> Path:
    return PROPOSALS / f"{sello(momento)}{sufijo}.json"


def construir_prompt(proyectos: list[dict], momento: datetime, plantilla: Path = PROMPT, sufijo: str = "") -> str:
    lista = [{"id": p["id"], "nombre": p.get("nombre"), "constructora": p.get("constructora"),
              "sector": p.get("sector"), "ciudad": p.get("ciudad"), "url": p.get("url"),
              "ya_tiene": sorted((p.get("enriquecimiento") or {}).keys())
              + (["ubicacion"] if (p.get("ubicacion") or {}).get("precision") in ("alta", "media") else [])}
             for p in proyectos]
    return (plantilla.read_text(encoding="utf-8")
            .replace("{{TODAY}}", momento.date().isoformat())
            .replace("{{SALIDA}}", str(ruta_propuesta(momento, sufijo).relative_to(ROOT)))
            .replace("{{PROYECTOS_JSON}}", json.dumps(lista, ensure_ascii=False, indent=1)))


def encontrar_claude() -> str | None:
    return shutil.which("claude") or next(
        (str(p) for p in [Path.home() / ".local/bin/claude"] if p.exists()), None)


def ejecutar(prompt: str, momento: datetime, cfg: AgenteConfig, etiqueta: str = "",
             herramientas: tuple[str, str] = HERRAMIENTAS_WEB, max_turns: int | None = None) -> Path:
    claude = encontrar_claude()
    if not claude:
        raise FileNotFoundError("No se encontró el comando 'claude' (Claude Code).")
    PROPOSALS.mkdir(exist_ok=True)
    RUN_DIR.mkdir(exist_ok=True)
    log_path = RUN_DIR / f"claude_{sello(momento)}{etiqueta}.json"
    cmd = [
        claude, "-p", prompt,
        "--model", cfg.modelo,
        "--tools", herramientas[0],
        "--allowedTools", herramientas[1],
        "--permission-mode", "dontAsk",
        "--max-turns", str(max_turns or cfg.max_turns),
        "--no-session-persistence",
        "--output-format", "json",
    ]
    log.info("Ejecutando agente (%s, máx. %s turnos)…", cfg.modelo, cfg.max_turns)
    with open(log_path, "w", encoding="utf-8") as out:
        proc = subprocess.run(cmd, cwd=ROOT, stdout=out, stderr=subprocess.STDOUT,
                              env={**os.environ}, timeout=cfg.timeout_minutos * 60)
    log.info("Agente terminó con código %s (log: %s)", proc.returncode, log_path.relative_to(ROOT))
    return log_path


def resumen_log(log_path: Path) -> str:
    """Turnos y respuesta final del agente (salida --output-format json)."""
    try:
        d = json.loads(log_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return "log no legible (¿el agente falló antes de terminar?)"
    partes = [f"turnos: {d.get('num_turns', '?')}"]
    if d.get("subtype") and d["subtype"] != "success":
        partes.append(f"estado: {d['subtype']}")
    texto = " ".join(str(d.get("result") or "").split())
    if texto:
        partes.append(f"respuesta: {texto[:300]}{'…' if len(texto) > 300 else ''}")
    return " | ".join(partes)


def respuesta_json(log_path: Path) -> dict | None:
    """Respuesta final del agente interpretada como JSON (lectura asistida)."""
    try:
        texto = str(json.loads(log_path.read_text(encoding="utf-8")).get("result") or "")
        return json.loads(texto[texto.index("{"): texto.rindex("}") + 1])
    except (OSError, ValueError):
        return None
