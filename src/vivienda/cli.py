"""Línea de comandos de Proyecto Vivienda Colombia.

    vivienda nuevos                       # descarga sectores -> historial -> proyectos -> dashboard
    vivienda nuevos --offline pagina.html # procesa HTML guardados (sin internet, no guarda)
    vivienda geocodificar                 # sin IA: fichas de Estrenar + cruce de vías en OpenStreetMap
    vivienda ubicar                       # geocodificar -> agente (Claude Code) para lo que falte -> aplica
    vivienda ubicar --solo-prompt         # genera el prompt para correrlo a mano
    vivienda aplicar proposals/AAAA-MM-DD.json   # verifica y aplica una propuesta
    vivienda brochures [--buscar] [--sin-ia]   # PDF de proyectos: descarga, texto, reglas (+ haiku sin web)
    vivienda brochure PRY-0005 archivo.pdf     # brochure descargado a mano (p. ej. detrás de formulario)
    vivienda usados                       # usados de Fincaraíz por barrio -> historial -> dashboard
    vivienda usados --probar              # 1 página por barrio: confirma rutas y campos (no guarda)
    vivienda zonas                        # OPCIONAL, de noche: polígonos de zona por esquinas (OSM)
    vivienda diario                       # rutina: nuevos, geocodificar, usados, exportar, publicar, alertas
    vivienda publicar                     # docs/ (dashboard sin texto de anuncios) + git commit/push
    vivienda programar [--hora 06:30]     # deja `diario` en launchd (macOS); --quitar la desinstala
    vivienda estado                       # qué proyectos están ubicados / pendientes
    vivienda exportar                     # regenera data/processed/dashboard.json
    vivienda web                          # abre el dashboard
"""
from __future__ import annotations

import argparse
import logging
import sys
from datetime import date, datetime
from pathlib import Path

from vivienda import agente
from vivienda import config as cfgmod
from vivienda.checks import Bitacora
from vivienda.models import Tipologia
from vivienda.pipeline import aplicar as merger
from vivienda.pipeline import brochures as brpipe
from vivienda.pipeline import exportar, filtros, geocodificar, historial, proyectos
from vivienda.pipeline import usados as usados_mod
from vivienda.pipeline import zonas as zonas_mod
from vivienda.sources import estrenar
from vivienda.sources import manual

log = logging.getLogger("vivienda")
ARCHIVO_NUEVOS = cfgmod.PROCESSED_DIR / "nuevos.json"


def _leer_estrenar(args, cfg) -> tuple[list[Tipologia], bool, int]:
    """Devuelve (tipologías, descarga_completa, tarjetas_fuera_de_sector)."""
    tipologias: list[Tipologia] = []
    fuera = 0

    if args.offline:
        for p in args.offline:
            ts = estrenar.parse_html(Path(p).read_text(encoding="utf-8", errors="ignore"))
            log.info("%3d tipologías  %s", len(ts), Path(p).name)
            tipologias += ts
        return tipologias, False, 0

    sectores = cfg.estrenar.sectores
    if args.sector:
        sectores = tuple(s for s in sectores if s.ruta in args.sector)
        if not sectores:
            sys.exit(f"Ningún sector de config.toml coincide con {args.sector}")

    resultados = estrenar.EstrenarFetcher(cfg.estrenar).descargar_todos(sectores)
    for res in resultados:
        if not res.ok:
            continue
        for t in estrenar.parse_html(res.archivo.read_text(encoding="utf-8")):
            if not filtros.pertenece_al_sector(t, res.sector.ruta):
                fuera += 1
                continue
            t.sector_url = res.sector.ruta
            t.zonas_candidatas = list(res.sector.zonas)
            tipologias.append(t)

    fallidos = [r for r in resultados if not r.ok]
    if fallidos:
        print("\nSectores sin datos (revisar ruta en config/config.toml):")
        for r in fallidos:
            marca = "" if r.sector.verificado else "  (candidato no verificado)"
            print(f"  {str(r.estado):18} {r.sector.ruta}{marca}")
    # completa = se corrieron todos los sectores y no falló ninguno VERIFICADO
    # (un candidato no verificado que da 404 no impide marcar desaparecidas)
    fallidos_verificados = [r for r in fallidos if r.sector.verificado]
    return tipologias, (not args.sector and not fallidos_verificados), fuera


def _dedup(ts: list[Tipologia]) -> list[Tipologia]:
    vistos, out = set(), []
    for t in ts:
        if t.clave not in vistos:
            vistos.add(t.clave)
            out.append(t)
    return out


def _reporte(ok: list[Tipologia], total: int, descartes) -> None:
    print(f"\nTipologías leídas: {total} | pasan filtros: {len(ok)}")
    if descartes:
        print("Descartadas -> " + ", ".join(f"{m}: {n}" for m, n in descartes.most_common()))
    proyectos: dict[tuple, list[Tipologia]] = {}
    for t in ok:
        proyectos.setdefault((t.proyecto or "?", t.sector or "?"), []).append(t)
    if proyectos:
        print(f"\n  {'Proyecto':28} {'Sector':18} {'Tip.':>4}  {'Precio (M)':>11}  {'M/m² constr.':>12}")
    for (nom, sec), ts in sorted(proyectos.items(), key=lambda kv: (kv[0][1], kv[0][0])):
        precios = [t.precio_desde for t in ts]
        m2 = sorted(t.precio_desde / t.area / 1e6 for t in ts if t.area)
        print(f"  {nom[:28]:28} {sec[:18]:18} {len(ts):>4}  "
              f"{min(precios)/1e6:>5.0f}–{max(precios)/1e6:<5.0f}  {m2[0]:>5.1f}–{m2[-1]:<5.1f}")


def cmd_nuevos(args) -> None:
    cfg = cfgmod.cargar()
    tipologias, completa, fuera = _leer_estrenar(args, cfg)
    tipologias = _dedup(tipologias)
    ok, descartes = filtros.aplicar(tipologias, cfg.filtros)
    if fuera:
        descartes["recomendadas de otros sectores"] = fuera
    _reporte(ok, len(tipologias) + fuera, descartes)

    if args.sin_guardar or args.offline:
        if args.offline:
            print("\n(Modo offline: no se actualiza el historial.)")
        return None

    registros = historial.cargar(ARCHIVO_NUEVOS)
    fuentes = {estrenar.FUENTE} if completa else set()
    res = historial.actualizar(registros, ok, date.today(), fuentes)
    historial.guardar(ARCHIVO_NUEVOS, registros)
    print(f"\nHistorial: {len(res.nuevas)} nuevas, {len(res.cambios_precio)} con cambio de precio, "
          f"{len(res.desaparecidas)} desaparecidas -> {ARCHIVO_NUEVOS.relative_to(cfgmod.ROOT)}")
    if not completa:
        print("(Corrida parcial: no se marcan desaparecidas.)")

    antes = set(proyectos.cargar())
    prys = _proyectos_al_dia(registros)
    nuevos_ids = sorted(set(prys) - antes)
    print(f"Proyectos: {len(prys)} en registro, {len(nuevos_ids)} nuevos "
          f"({', '.join(nuevos_ids) if nuevos_ids else '—'})")
    _exportar(prys, registros)
    return {"completa": completa, "tipologias_nuevas": len(res.nuevas), "desaparecidas": len(res.desaparecidas),
            "proyectos_nuevos": [_ficha_alerta(prys[i], registros) for i in nuevos_ids],
            "cambios_precio": [{"clave": k, "proyecto": registros[k].get("proyecto"), "habs": registros[k].get("habs"),
                                "area": registros[k].get("area"), "anterior": registros[k].get("precio_anterior"),
                                "nuevo": registros[k].get("precio_desde"), "url": registros[k].get("url")}
                               for k in res.cambios_precio if registros[k].get("precio_anterior")]}


def _ficha_alerta(p: dict, registros: dict[str, dict]) -> dict:
    from vivienda.pipeline.proyectos import clave_proyecto
    precios = [t.get("precio_desde") for t in registros.values()
               if t.get("activo") and clave_proyecto(t) == p.get("clave") and t.get("precio_desde")]
    return {"id": p["id"], "nombre": p.get("nombre"), "zona": p.get("zona"), "sector": p.get("sector"),
            "precio_desde": min(precios) if precios else None, "url": p.get("url"),
            "entrega": ((p.get("enriquecimiento") or {}).get("entrega") or {}).get("valor")}


def _exportar(prys=None, registros=None) -> None:
    prys = prys if prys is not None else proyectos.cargar()
    registros = registros if registros is not None else historial.cargar(ARCHIVO_NUEVOS)
    zonas = cfgmod.cargar_zonas()
    proyectos.rezonificar(prys, zonas)
    proyectos.guardar(prys)
    datos = exportar.construir(prys, registros, zonas)
    cfg = cfgmod.cargar()
    if cfg.fincaraiz:
        datos["usados"] = usados_mod.para_dashboard(usados_mod.cargar(), date.today(),
                                                    cfg.fincaraiz.dias_vigencia, cfg.filtros.area_min, zonas)
    exportar.guardar(datos)
    print(f"Dashboard: {len(datos['proyectos'])} proyectos en el mapa, {len(datos['sin_ubicar'])} sin ubicar, "
          f"{len(datos['fuera_de_zonas'])} fuera de zonas, {len(datos['usados'])} usados vigentes "
          f"-> {exportar.ARCHIVO.relative_to(cfgmod.ROOT)}")


def _integrar_manuales(registros: dict[str, dict]) -> list[dict]:
    """Proyectos de config/proyectos_manuales.toml -> historial (sin internet, idempotente)."""
    try:
        manuales = manual.cargar()
    except ValueError as e:
        sys.exit(str(e))
    ok, descartes = filtros.aplicar(manual.tipologias(manuales), cfgmod.cargar().filtros)
    for motivo, n in descartes.items():
        log.info("Manuales: %d tipología(s) descartadas (%s)", n, motivo)
    historial.actualizar(registros, ok, date.today(), {manual.FUENTE})
    return manuales


def _proyectos_al_dia(registros: dict[str, dict] | None = None) -> dict[str, dict]:
    """Sincroniza el registro de proyectos con el historial de tipologías (barato e idempotente)."""
    registros = registros if registros is not None else historial.cargar(ARCHIVO_NUEVOS)
    manuales = _integrar_manuales(registros)
    historial.guardar(ARCHIVO_NUEVOS, registros)
    prys = proyectos.cargar()
    proyectos.sincronizar(registros, prys)
    manual.aplicar_a_proyectos(prys, manuales, date.today())
    proyectos.rezonificar(prys, cfgmod.cargar_zonas())
    proyectos.guardar(prys)
    return prys


def cmd_exportar(args) -> None:
    _exportar(_proyectos_al_dia())


def cmd_estado(args) -> None:
    prys = _proyectos_al_dia()
    if not prys:
        sys.exit("No hay proyectos. Corre primero: vivienda nuevos")
    print(f"{'ID':9} {'Proyecto':26} {'Sector':16} {'Zona':5} {'Ubicación':9} Datos")
    for p in sorted(prys.values(), key=lambda x: x["id"]):
        if not p.get("activo"):
            continue
        u = p.get("ubicacion") or {}
        datos = ",".join(sorted((p.get("enriquecimiento") or {}).keys())) or "—"
        print(f"{p['id']:9} {(p.get('nombre') or '?')[:26]:26} {(p.get('sector') or '?')[:16]:16} "
              f"{p.get('zona') or '—':5} {u.get('precision', 'pendiente'):9} {datos}")
    print(f"\nSin ubicación confiable: {len(proyectos.pendientes(prys))} | "
          f"con datos clave incompletos: {len(proyectos.pendientes(prys, incluir_datos=True))}")


def _geocodificar(prys: dict, cfg, leer_fichas: bool) -> None:
    bit = Bitacora()
    res = geocodificar.ejecutar(prys, cfg.estrenar.user_agent, cfg.nominatim_user_agent,
                                cfgmod.cargar_zonas(), bit, date.today(), leer_fichas=leer_fichas)
    proyectos.guardar(prys)
    bit.guardar()
    if res.fichas_leidas or res.detalles:
        print(f"Geocodificación sin IA: {res.fichas_leidas} fichas leídas, {len(res.ubicados)} ubicados por cruce de vías")
        for d in res.detalles:
            print(f"  • {d}")


def cmd_direccion(args) -> None:
    """Herramienta manual: registrar o corregir la dirección de un proyecto y geocodificarla."""
    cfg = cfgmod.cargar()
    prys = _proyectos_al_dia()
    p = prys.get(args.id)
    if not p:
        sys.exit(f"No existe {args.id}. Usa: vivienda estado")
    origen = "agregador" if args.agregador else "manual"
    p["direccion_candidata"] = {"direccion": args.direccion, "fuente": args.fuente or "manual",
                                "origen": origen, "encontrada": date.today().isoformat()}
    if args.reemplazar:
        p["ubicacion"] = None
    bit = Bitacora()
    bit.registrar(p["id"], "direccion_manual", origen, direccion=args.direccion, url=args.fuente)
    bit.guardar()
    print(f"{p['id']} {p.get('nombre')}: dirección registrada ({origen}): {args.direccion}")
    _geocodificar(prys, cfg, leer_fichas=False)
    _exportar(prys)


def _sesion_web(cfg):
    import requests
    s = requests.Session()
    s.headers.update({"User-Agent": cfg.estrenar.user_agent, "Accept-Language": "es-CO,es;q=0.9"})
    return s


def _agente_cfg(cfg, modelo):
    if not modelo:
        return cfg.agente
    from dataclasses import replace
    return replace(cfg.agente, modelo=modelo)


def _buscar_brochures(prys: dict, cfg, args) -> None:
    sin_url = [p for p in sorted(prys.values(), key=lambda x: x["id"])
               if p.get("activo") and not p.get("brochure_urls")
               and not any(b.get("estado") == "procesado" for b in p.get("brochures") or [])]
    sin_url = sin_url[: args.max or cfg.agente.max_proyectos]
    if not sin_url:
        print("Todos los proyectos activos ya tienen brochure o URL candidata.")
        return
    momento = datetime.now()
    prompt = agente.construir_prompt(sin_url, momento, agente.PROMPT_BUSCAR_BROCHURES, "_brochures")
    acfg = _agente_cfg(cfg, args.modelo)
    print(f"Buscando brochures de {len(sin_url)} proyectos con {acfg.modelo}…")
    try:
        log_path = agente.ejecutar(prompt, momento, acfg, etiqueta="_brochures", max_turns=60)
    except FileNotFoundError as e:
        sys.exit(str(e))
    print(f"Agente ({acfg.modelo}) → {agente.resumen_log(log_path)}")
    salida = agente.ruta_propuesta(momento, "_brochures")
    if not salida.exists():
        print("El agente no dejó propuesta de brochures.")
        return
    prop = merger.leer_propuesta(salida)
    for item in prop.get("proyectos") or []:
        p = prys.get(item.get("id"))
        if p:
            n = brpipe.agregar_urls(p, item.get("brochure_urls") or [])
            nota = " ".join(str(item.get("notas") or "").split())[:160]
            print(f"  • {p['id']} {p.get('nombre')}: {n} URL(s) nuevas{' — ' + nota if nota else ''}")


def _lectura_asistida(prys: dict, tipologias: dict, pendientes: list, cfg, args, bit: Bitacora) -> None:
    from vivienda.pipeline.proyectos import clave_proyecto
    acfg = _agente_cfg(cfg, args.modelo)
    for pid, txt in pendientes:
        p = prys[pid]
        texto = txt.read_text(encoding="utf-8")
        tps = [t for t in tipologias.values() if t.get("activo") and clave_proyecto(t) == p["clave"]]
        prompt = (agente.PROMPT_LEER_BROCHURE.read_text(encoding="utf-8")
                  .replace("{{NOMBRE}}", p.get("nombre") or "").replace("{{ID}}", pid)
                  .replace("{{TIPOLOGIAS}}", ", ".join(f"{t.get('habs')} hab {t.get('area')} m²" for t in tps))
                  .replace("{{TEXTO}}", texto[:25000]))
        momento = datetime.now()
        try:
            log_path = agente.ejecutar(prompt, momento, acfg, etiqueta=f"_leer_{pid}",
                                       herramientas=agente.HERRAMIENTAS_NINGUNA, max_turns=2)
        except FileNotFoundError as e:
            sys.exit(str(e))
        datos = agente.respuesta_json(log_path)
        if datos is None:
            print(f"  • {pid}: la lectura asistida no devolvió JSON válido ({agente.resumen_log(log_path)[:120]})")
            continue
        ok, rechazos = brpipe.verificar_propuesta_ia(datos, texto)
        fuente = next((b["url"] for b in reversed(p.get("brochures") or []) if b.get("archivo", "").endswith(txt.with_suffix(".pdf").name)), "brochure")
        cambios = brpipe.aplicar_datos(p, ok, fuente, tps, bit, date.today().isoformat())
        print(f"  • {pid} {p.get('nombre')} (IA {acfg.modelo}, sin web): {', '.join(cambios) or 'sin datos nuevos'}"
              + (f" | rechazado por no estar en el PDF: {'; '.join(rechazos)}" if rechazos else ""))


def cmd_brochures(args) -> None:
    cfg = cfgmod.cargar()
    prys = _proyectos_al_dia()
    if args.buscar:
        _buscar_brochures(prys, cfg, args)
        proyectos.guardar(prys)
    tipologias = historial.cargar(ARCHIVO_NUEVOS)
    bit = Bitacora()
    res = brpipe.procesar(prys, tipologias, _sesion_web(cfg), bit, date.today())
    print(f"Brochures: {res.descargados} descargados, {res.procesados} procesados, "
          f"{res.areas_asignadas} áreas privadas asignadas")
    for d in res.detalles:
        print(f"  • {d}")
    if res.para_ia and not args.sin_ia:
        print(f"Lectura asistida (sin web) para {len(res.para_ia)} brochure(s) con datos incompletos:")
        _lectura_asistida(prys, tipologias, res.para_ia, cfg, args, bit)
    elif res.para_ia:
        print(f"{len(res.para_ia)} brochure(s) con datos incompletos (lectura asistida desactivada con --sin-ia)")
    proyectos.guardar(prys)
    bit.guardar()
    _geocodificar(prys, cfg, leer_fichas=False)   # direcciones nuevas salidas de los brochures
    _exportar(prys)


def cmd_brochure(args) -> None:
    """Brochure descargado a mano: se procesa igual que uno descargado por el sistema."""
    from pathlib import Path as _P
    from vivienda.sources import brochure as br
    cfg = cfgmod.cargar()
    prys = _proyectos_al_dia()
    p = prys.get(args.id)
    if not p:
        sys.exit(f"No existe {args.id}. Usa: vivienda estado")
    origen = _P(args.archivo).expanduser()
    datos = origen.read_bytes() if origen.exists() else sys.exit(f"No existe {origen}")
    if not datos.startswith(b"%PDF"):
        sys.exit("El archivo no es un PDF.")
    d = br.guardar_pdf(datos, p["id"])
    if any(b.get("sha256") == d.sha256 for b in p.get("brochures") or []):
        sys.exit("Ese PDF ya estaba procesado para este proyecto.")
    tipologias = historial.cargar(ARCHIVO_NUEVOS)
    bit = Bitacora()
    res = brpipe.ResumenBrochures()
    brpipe.procesar_archivo(p, d.archivo, origen.resolve().as_uri(), d.sha256, tipologias, bit,
                            date.today().isoformat(), res)
    for x in res.detalles:
        print(f"  • {x}")
    if res.para_ia and not args.sin_ia:
        _lectura_asistida(prys, tipologias, res.para_ia, cfg, args, bit)
    proyectos.guardar(prys)
    bit.guardar()
    _geocodificar(prys, cfg, leer_fichas=False)
    _exportar(prys)


def cmd_geocodificar(args) -> None:
    cfg = cfgmod.cargar()
    prys = _proyectos_al_dia()
    if args.reintentar:
        for p in prys.values():
            (p.get("direccion_candidata") or {}).pop("geocodificada", None)
    _geocodificar(prys, cfg, leer_fichas=True)
    _exportar(prys)


def cmd_aplicar(args) -> None:
    cfg = cfgmod.cargar()
    path = Path(args.propuesta)
    if not path.exists():
        sys.exit(f"No existe {path}")
    try:
        prop = merger.leer_propuesta(path)
    except ValueError as e:
        sys.exit(f"Propuesta con JSON inválido: {e}")
    prys = proyectos.cargar()
    bit = Bitacora()
    from vivienda.verificacion import Verificador
    print(f"Verificando {len(prop.get('proyectos') or [])} proyectos (≈1 s por proyecto por Nominatim)…")
    res = merger.aplicar(prop, prys, cfgmod.cargar_zonas(), Verificador(cfg.nominatim_user_agent),
                         bit, date.today())
    proyectos.guardar(prys)
    bit.guardar()
    print(f"Ubicados: {len(res.ubicados)} | con datos nuevos: {len(res.enriquecidos)} | rechazos: {len(res.rechazos)}")
    for d in res.detalles:
        print(f"  • {d}")
    for r in res.rechazos:
        print(f"  ✗ {r}")
    _geocodificar(prys, cfg, leer_fichas=False)
    _exportar(prys)


def cmd_ubicar(args) -> None:
    cfg = cfgmod.cargar()
    prys = _proyectos_al_dia()
    if not args.solo_prompt:
        _geocodificar(prys, cfg, leer_fichas=True)  # primero lo gratis y determinístico
    pend = proyectos.pendientes(prys, args.max or cfg.agente.max_proyectos, incluir_datos=args.datos)
    if not pend:
        print("No hay proyectos pendientes de ubicar o completar.")
        return
    momento = datetime.now()
    prompt = agente.construir_prompt(pend, momento)
    print(f"{len(pend)} proyectos para el agente: {', '.join(p['id'] for p in pend)}")
    salida = agente.ruta_propuesta(momento)

    if args.solo_prompt:
        agente.RUN_DIR.mkdir(exist_ok=True)
        out = agente.RUN_DIR / f"prompt_{agente.sello(momento)}.md"
        out.write_text(prompt, encoding="utf-8")
        print(f"Prompt en {out.relative_to(cfgmod.ROOT)}. Al terminar: vivienda aplicar "
              f"{salida.relative_to(cfgmod.ROOT)}")
        return

    agente_cfg = cfg.agente
    if args.modelo:
        from dataclasses import replace
        agente_cfg = replace(agente_cfg, modelo=args.modelo)
    try:
        log_path = agente.ejecutar(prompt, momento, agente_cfg)
    except FileNotFoundError as e:
        sys.exit(f"{e} Usa --solo-prompt para correrlo a mano.")
    print(f"Agente ({agente_cfg.modelo}) → {agente.resumen_log(log_path)}")
    if not salida.exists():
        sys.exit(f"El agente no dejó propuesta en {salida.relative_to(cfgmod.ROOT)}. Revisa {log_path.relative_to(cfgmod.ROOT)}")
    args.propuesta = str(salida)
    cmd_aplicar(args)


def _cliente_fr(cfg, hoy: date):
    from vivienda.sources.fincaraiz import ClienteFincaraiz
    return ClienteFincaraiz(pausa=cfg.fincaraiz.pausa_segundos,
                            dir_debug=cfgmod.RAW_DIR / "fincaraiz" / hoy.isoformat())


def _resumen_campos(anuncios: list[dict]) -> None:
    """Qué tan llenos vienen los campos clave (para saber si el mapeo sigue sirviendo)."""
    n = len(anuncios)
    if not n:
        return
    def lleno(k):
        return sum(1 for a in anuncios if a.get(k) is not None)
    asc = {}
    for a in anuncios:
        k = "sin dato" if a.get("ascensor") is None else ("no" if a["ascensor"] is False else
             (a.get("ascensor_fuente") or "").split(" ")[0])
        asc[k] = asc.get(k, 0) + 1
    print(f"\nCampos en {n} usados dentro de zonas:")
    for k, nombre in (("precio", "precio"), ("area_privada", "área privada"), ("area_construida", "área construida"),
                      ("habs", "habitaciones"), ("estrato", "estrato"), ("admin", "administración"),
                      ("parq", "parqueaderos"), ("antiguedad", "antigüedad"), ("pisos_edificio", "pisos del edificio")):
        print(f"  {nombre:20} {lleno(k):4}/{n}")
    print(f"  {'ascensor':20} " + ", ".join(f"{k}: {v}" for k, v in sorted(asc.items())))


def cmd_usados(args) -> None:
    cfg = cfgmod.cargar()
    if not cfg.fincaraiz or not cfg.fincaraiz.barrios:
        sys.exit("Falta la sección [fincaraiz] con barrios en config/config.toml")
    hoy = date.today()
    zonas = cfgmod.cargar_zonas()
    barrios = [b for b in cfg.fincaraiz.barrios if not args.barrio or any(x in b.ruta for x in args.barrio)]
    max_pag = 1 if args.probar else (args.max_paginas or cfg.fincaraiz.max_paginas)
    cliente = _cliente_fr(cfg, hoy)
    todos, resumenes, bloqueos = [], [], 0
    for i, b in enumerate(barrios, 1):
        print(f"[{i}/{len(barrios)}] {b.ciudad}: {b.ruta}{'' if b.verificado else '  (candidata)'}")
        anuncios, r = usados_mod.recorrer_barrio(cliente, b.ruta, b.ciudad, zonas, max_pag, hoy,
                                                 avisar=print if args.verbose else (lambda *_: None))
        resumenes.append((b, r))
        todos += anuncios
        zonas_txt = ", ".join(f"{z}: {n}" for z, n in sorted(r.en_zona.items())) or "ninguno en zonas"
        print(f"    total en el portal {r.total_portal if r.total_portal is not None else '?'} · "
              f"{r.paginas} pág. · {r.leidos} leídos → {zonas_txt}"
              + (f" · {r.fuera_de_zonas} fuera de zonas" if r.fuera_de_zonas else "")
              + (f" · {r.sin_coordenadas} sin coordenadas" if r.sin_coordenadas else "")
              + (f"\n    ✗ {r.error}" if r.error else ""))
        bloqueos = bloqueos + 1 if r.error and ("bloqueo" in r.error or "403" in r.error or "429" in r.error) else 0
        if bloqueos >= 2:
            print("\nDos barrios seguidos bloqueados: se detiene para no empeorar el bloqueo. "
                  "Reintenta más tarde (o mañana).")
            break

    todos = list({a["id"]: a for a in todos}.values())   # un anuncio puede salir en dos barrios vecinos
    _resumen_campos([a for a in todos if a.get("zona")])
    fallidas = [b.ruta for b, r in resumenes if r.error and b.verificado]
    vacias = [b.ruta for b, r in resumenes if not r.error and not r.total_portal]
    if vacias:
        print(f"\n⚠ Sin resultados (ruta mal escrita o que lleva a otro lugar): {', '.join(vacias)}")
    if args.probar:
        muestra = cfgmod.RAW_DIR / "fincaraiz" / "muestra_usados.json"
        muestra.parent.mkdir(parents=True, exist_ok=True)
        import json
        muestra.write_text(json.dumps(todos[:5], ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"\nPrueba: nada se guardó en el historial. Muestra parseada en {muestra.relative_to(cfgmod.ROOT)}")
        print("Compara 'total en el portal' de cada candidata con lo que muestra la misma URL en el navegador;"
              " si coincide, márcala verificado = true en config.toml.")
        return None

    reg = usados_mod.cargar()
    c = usados_mod.actualizar(reg, todos, hoy)
    usados_mod.guardar(reg)
    en_z = sum(1 for a in todos if a.get("zona"))
    print(f"\nUsados: {en_z} vistos hoy en zonas (+{len(todos) - en_z} de entorno, solo comparables) · {c['nuevos']} nuevos · {c['cambio_precio']} cambiaron de precio"
          f" · historial {len(reg)} -> {usados_mod.ARCHIVO.relative_to(cfgmod.ROOT)}")
    if fallidas:
        print(f"⚠ Corrida parcial: fallaron barrios verificados ({', '.join(fallidas)}). "
              "Lo no visto hoy no se retira hasta pasar {} días.".format(cfg.fincaraiz.dias_vigencia))
    _exportar(_proyectos_al_dia())
    return {"vistos": len(todos), "nuevos": c["nuevos"], "cambio_precio": c["cambio_precio"],
            "barrios_fallidos": fallidas, "bloqueo": bloqueos >= 2, "barrios_vacios": vacias}


def cmd_zonas(args) -> None:
    from vivienda.geocodificacion import Geocodificador
    cfg = cfgmod.cargar()
    defs = zonas_mod.cargar_definiciones()
    con = [z["id"] for z in defs if z.get("esquinas")]
    if not con:
        sys.exit("Ninguna zona tiene `esquinas` en config/zonas.toml: todas siguen como círculo.")
    print(f"Polígonos por esquinas para: {', '.join(con)} (una consulta a OpenStreetMap por zona, ~1–3 min c/u)")
    res = zonas_mod.calcular(defs, Geocodificador(cfg.nominatim_user_agent), date.today(),
                             forzar=args.forzar, solo=args.zona)
    if res.calculadas:
        print(f"Calculadas: {', '.join(res.calculadas)}")
    if res.al_dia:
        print(f"Ya estaban al día (usa --forzar para recalcular): {', '.join(res.al_dia)}")
    if res.fallidas:
        print("Esquinas que no se pudieron ubicar (esas zonas siguen como círculo):")
        for f in res.fallidas:
            print(f"  - {f}")
    _exportar(_proyectos_al_dia())


def cmd_diario(args) -> None:
    """Rutina diaria completa. Cada paso falla por separado: un error no tumba los siguientes."""
    from argparse import Namespace
    from vivienda.pipeline import diario
    hoy = date.today()
    with diario.candado() as libre:
        if not libre:
            print("Otra corrida diaria sigue en marcha: esta se omite.")
            return
        with diario.log_del_dia(hoy) as log_path:
            cfg = cfgmod.cargar()
            d = cfg.diario
            inicio = datetime.now()
            print(f"\n===== Corrida diaria {inicio:%Y-%m-%d %H:%M} =====")
            r = {"fecha": hoy.isoformat(), "inicio": inicio.isoformat(timespec="seconds"), "errores": [],
                 "parcial": False, "proyectos_nuevos": [], "cambios_precio_nuevos": [], "usados": None,
                 "usados_oportunidad": [], "ubicar": None, "publicacion": None, "alertas_enviadas": 0}

            def paso(nombre, fn):
                print(f"\n--- {nombre} ---")
                try:
                    return fn()
                except SystemExit as e:
                    r["errores"].append(f"{nombre}: {e}")
                except Exception as e:  # noqa: BLE001 — se registra y se sigue
                    log.exception("Falló %s", nombre)
                    r["errores"].append(f"{nombre}: {type(e).__name__}: {e}")
                return None

            n = paso("nuevos", lambda: cmd_nuevos(Namespace(offline=None, sector=None, sin_guardar=False)))
            if n:
                r["parcial"] |= not n["completa"]
                r["proyectos_nuevos"] = n["proyectos_nuevos"]
                r["cambios_precio_nuevos"] = n["cambios_precio"]
                r["tipologias_nuevas"] = n["tipologias_nuevas"]
            paso("geocodificar", lambda: cmd_geocodificar(Namespace(reintentar=False)))
            if r["proyectos_nuevos"] and d.ubicar_max > 0 and not args.sin_ia:
                paso("ubicar (haiku)", lambda: cmd_ubicar(Namespace(max=d.ubicar_max, solo_prompt=False,
                                                                     modelo=None, datos=False)))
                r["ubicar"] = f"hasta {d.ubicar_max} proyectos"
            if not args.sin_usados:
                paginas = d.max_paginas_profundo if hoy.weekday() == d.dia_profundo else d.max_paginas_usados
                r["usados_paginas"] = paginas
                u = paso(f"usados (tope {paginas or 'config'} pág.)",
                         lambda: cmd_usados(Namespace(probar=False, barrio=None, verbose=args.verbose,
                                                      max_paginas=paginas)))
                if u:
                    r["usados"] = u
                    r["parcial"] |= bool(u["barrios_fallidos"] or u["bloqueo"])
            paso("exportar", lambda: cmd_exportar(None))
            # zona y entrega de proyectos nuevos pueden haber llegado con geocodificar/ubicar
            prys = proyectos.cargar()
            for p in r["proyectos_nuevos"]:
                q = prys.get(p["id"]) or {}
                p["zona"] = q.get("zona") or p.get("zona")
            if exportar.ARCHIVO.exists():
                import json
                usados_dash = json.loads(exportar.ARCHIVO.read_text(encoding="utf-8")).get("usados") or []
                r["usados_oportunidad"] = diario.oportunidades_usados(
                    usados_dash, hoy, d.umbral_usado_barato, cfg.filtros.precio_max)

            if d.publicar and not args.sin_publicar:
                def publicar():
                    diario.preparar_docs()
                    return diario.git_publicar(hoy)
                r["publicacion"] = paso("publicar", publicar)
                print(f"Publicación: {r['publicacion']}")

            r["fin"] = datetime.now().isoformat(timespec="seconds")
            alertas = {"bajas_precio": d.alerta_bajas_precio, "usados_baratos": d.alerta_usados_baratos,
                       "fallas": d.alerta_fallas}
            msgs = diario.mensajes(r, d.url_dashboard or None, alertas)
            tema = diario.tema_ntfy()
            print(f"\n--- alertas: {len(msgs)} ---")
            for m in msgs:
                print(f"  [{m['titulo']}] {m['texto'].splitlines()[0]}")
                if tema and not args.sin_alertas:
                    try:
                        diario.enviar_ntfy(tema, m)
                        r["alertas_enviadas"] += 1
                    except Exception as e:  # noqa: BLE001
                        r["errores"].append(f"ntfy: {e}")
            if msgs and not tema:
                print("  (sin tema de ntfy: crea config/ntfy_tema.txt para recibirlas en el celular)")
            diario.guardar_resumen(r, hoy)
            print(f"\nResumen: {len(r['proyectos_nuevos'])} proyectos nuevos · "
                  f"{len(r['cambios_precio_nuevos'])} tipologías con cambio de precio · "
                  f"{(r['usados'] or {}).get('nuevos', 0)} usados nuevos · {len(r['usados_oportunidad'])} oportunidades · "
                  f"{len(r['errores'])} errores{' · PARCIAL' if r['parcial'] else ''} "
                  f"({(datetime.now() - inicio).seconds // 60} min) -> {log_path.relative_to(cfgmod.ROOT)}")


def cmd_publicar(args) -> None:
    """Regenera docs/ (dashboard saneado) y hace commit + push si hubo cambios."""
    from vivienda.pipeline import diario
    _exportar(_proyectos_al_dia())
    diario.preparar_docs()
    print(f"docs/ listo · git: {diario.git_publicar(date.today())}")
    url = cfgmod.cargar().diario.url_dashboard
    if url:
        print(f"Dashboard público: {url}  (GitHub Pages tarda 1–2 min en actualizar)")


PLIST = Path.home() / "Library" / "LaunchAgents" / "co.vivienda.diario.plist"


def plist_diario(hora: str, python: str, raiz: Path) -> str:
    hh, mm = (int(x) for x in hora.split(":"))
    path = ":".join([str(Path(python).parent), "/opt/homebrew/bin", str(Path.home() / ".local/bin"),
                     "/usr/local/bin", "/usr/bin", "/bin", "/usr/sbin", "/sbin"])
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
  <key>Label</key><string>co.vivienda.diario</string>
  <key>ProgramArguments</key>
  <array>
    <string>/usr/bin/caffeinate</string><string>-i</string>
    <string>{python}</string><string>-u</string><string>-m</string><string>vivienda</string><string>diario</string>
  </array>
  <key>WorkingDirectory</key><string>{raiz}</string>
  <key>EnvironmentVariables</key>
  <dict>
    <key>PYTHONPATH</key><string>{raiz / 'src'}</string>
    <key>PATH</key><string>{path}</string>
    <key>PYTHONUNBUFFERED</key><string>1</string>
  </dict>
  <key>StartCalendarInterval</key>
  <dict><key>Hour</key><integer>{hh}</integer><key>Minute</key><integer>{mm}</integer></dict>
  <key>StandardOutPath</key><string>{raiz / 'logs' / 'launchd.txt'}</string>
  <key>StandardErrorPath</key><string>{raiz / 'logs' / 'launchd.txt'}</string>
</dict>
</plist>
"""


def cmd_programar(args) -> None:
    """Instala (o quita) la corrida diaria en launchd del usuario. Solo macOS."""
    import os
    import subprocess
    dominio = f"gui/{os.getuid()}"
    subprocess.run(["launchctl", "bootout", dominio, str(PLIST)], capture_output=True)
    if args.quitar:
        PLIST.unlink(missing_ok=True)
        print("Corrida diaria desinstalada.")
        return
    hora = args.hora or cfgmod.cargar().diario.hora
    (cfgmod.ROOT / "logs").mkdir(exist_ok=True)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    PLIST.write_text(plist_diario(hora, sys.executable, cfgmod.ROOT), encoding="utf-8")
    r = subprocess.run(["launchctl", "bootstrap", dominio, str(PLIST)], capture_output=True, text=True)
    if r.returncode != 0:
        sys.exit(f"launchctl no la cargó: {r.stderr.strip()}")
    hh, mm = (int(x) for x in hora.split(":"))
    despertar = f"{hh:02d}:{max(mm - 5, 0):02d}:00" if mm >= 5 else f"{(hh - 1) % 24:02d}:{mm + 55:02d}:00"
    print(f"Corrida diaria programada a las {hora} ({PLIST}).\n"
          f"Para que el Mac despierte solo, una vez:  sudo pmset repeat wakeorpoweron MTWRFSU {despertar}\n"
          f"Probarla ya sin esperar:  launchctl kickstart {dominio}/co.vivienda.diario")


def cmd_web(args) -> None:
    """Sirve el proyecto en http://localhost:<puerto> y abre el dashboard."""
    import functools
    import http.server
    import webbrowser

    handler = functools.partial(http.server.SimpleHTTPRequestHandler, directory=str(cfgmod.ROOT))
    handler.log_message = lambda *a: None  # consola limpia
    with http.server.ThreadingHTTPServer(("127.0.0.1", args.puerto), handler) as srv:
        url = f"http://localhost:{args.puerto}/web/index.html"
        print(f"Dashboard en {url}  (Ctrl+C para detener)")
        webbrowser.open(url)
        try:
            srv.serve_forever()
        except KeyboardInterrupt:
            print("\nServidor detenido.")


def main(argv: list[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="vivienda", description="Proyecto Vivienda Colombia")
    parser.add_argument("-v", "--verbose", action="store_true", help="más detalle en consola")
    sub = parser.add_subparsers(dest="comando", required=True)

    p = sub.add_parser("nuevos", help="proyectos nuevos (Estrenar Vivienda)")
    p.add_argument("--sector", nargs="+", help="solo estas rutas de config.toml")
    p.add_argument("--offline", nargs="+", metavar="HTML", help="procesar HTML guardados")
    p.add_argument("--sin-guardar", action="store_true", help="no actualizar el historial")
    p.set_defaults(func=cmd_nuevos)

    u = sub.add_parser("ubicar", help="agente: ubicación y datos clave de proyectos pendientes")
    u.add_argument("--max", type=int, help="máximo de proyectos en esta corrida")
    u.add_argument("--solo-prompt", action="store_true", help="solo generar el prompt")
    u.add_argument("--modelo", help="sobrescribe el modelo de config.toml solo para esta corrida")
    u.add_argument("--datos", action="store_true",
                   help="incluir proyectos ya ubicados a los que les faltan estrato, admin, ascensor o renta corta")
    u.set_defaults(func=cmd_ubicar)

    a = sub.add_parser("aplicar", help="verificar y aplicar una propuesta del agente")
    a.add_argument("propuesta")
    a.set_defaults(func=cmd_aplicar)

    g = sub.add_parser("geocodificar", help="sin IA: dirección de fichas + cruce de vías en OSM")
    g.add_argument("--reintentar", action="store_true", help="volver a intentar direcciones que ya fallaron")
    g.set_defaults(func=cmd_geocodificar)

    d = sub.add_parser("direccion", help="registrar a mano la dirección de un proyecto")
    d.add_argument("id", help="ID del proyecto, p. ej. PRY-0008")
    d.add_argument("direccion", help='p. ej. "Calle 73 # 14-48" o "Carrera 53 con Calle 100"')
    d.add_argument("--fuente", help="URL donde la viste")
    d.add_argument("--agregador", action="store_true", help="la fuente es un portal: queda como pendiente de confirmar")
    d.add_argument("--reemplazar", action="store_true", help="descartar la ubicación actual aunque sea media/alta")
    d.set_defaults(func=cmd_direccion)
    b = sub.add_parser("brochures", help="brochures PDF: descarga, texto, reglas y lectura asistida")
    b.add_argument("--buscar", action="store_true", help="el agente busca URLs de brochures (usa web)")
    b.add_argument("--sin-ia", action="store_true", help="solo reglas, sin lectura asistida")
    b.add_argument("--max", type=int, help="máximo de proyectos para la búsqueda")
    b.add_argument("--modelo", help="modelo solo para esta corrida")
    b.set_defaults(func=cmd_brochures)

    b1 = sub.add_parser("brochure", help="procesar un brochure descargado a mano")
    b1.add_argument("id")
    b1.add_argument("archivo")
    b1.add_argument("--sin-ia", action="store_true")
    b1.add_argument("--modelo")
    b1.set_defaults(func=cmd_brochure)

    us = sub.add_parser("usados", help="vivienda usada de Fincaraíz por barrio")
    us.add_argument("--probar", action="store_true", help="1 página por barrio, no guarda: confirma rutas y campos")
    us.add_argument("--barrio", nargs="+", help="solo rutas que contengan este texto")
    us.add_argument("--max-paginas", type=int, help="tope de páginas por barrio en esta corrida")
    us.set_defaults(func=cmd_usados)

    zo = sub.add_parser("zonas", help="OPCIONAL (de noche): polígonos de zona desde las esquinas de zonas.toml")
    zo.add_argument("--forzar", action="store_true", help="recalcular aunque ya estén")
    zo.add_argument("--zona", nargs="+", help="solo estas zonas (ids)")
    zo.set_defaults(func=cmd_zonas)

    di = sub.add_parser("diario", help="rutina diaria: nuevos, geocodificar, usados, exportar, publicar, alertas")
    di.add_argument("--sin-usados", action="store_true", help="omitir Fincaraíz (más rápido)")
    di.add_argument("--sin-ia", action="store_true", help="no llamar al agente aunque haya proyectos nuevos")
    di.add_argument("--sin-publicar", action="store_true")
    di.add_argument("--sin-alertas", action="store_true", help="calcula las alertas pero no las envía")
    di.set_defaults(func=cmd_diario)

    sub.add_parser("publicar", help="docs/ saneado + git commit/push").set_defaults(func=cmd_publicar)

    pr = sub.add_parser("programar", help="instalar la corrida diaria en launchd (macOS)")
    pr.add_argument("--hora", help='HH:MM; por defecto [diario] hora de config.toml')
    pr.add_argument("--quitar", action="store_true", help="desinstalar")
    pr.set_defaults(func=cmd_programar)

    sub.add_parser("estado", help="estado de ubicación de los proyectos").set_defaults(func=cmd_estado)
    sub.add_parser("exportar", help="regenerar dashboard.json").set_defaults(func=cmd_exportar)

    w = sub.add_parser("web", help="abrir el dashboard en el navegador")
    w.add_argument("--puerto", type=int, default=8000)
    w.set_defaults(func=cmd_web)

    args = parser.parse_args(argv)
    logging.basicConfig(level=logging.DEBUG if args.verbose else logging.INFO,
                        format="%(message)s")
    logging.getLogger("urllib3").setLevel(logging.WARNING)
    args.func(args)


if __name__ == "__main__":
    main()
