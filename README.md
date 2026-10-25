# Proyecto Vivienda Colombia

Radar de inversión inmobiliaria: compara **proyectos nuevos** con **vivienda usada comparable** en zonas específicas de Bogotá y Bucaramanga (Floridablanca), con tope de $600 M, ascensor obligatorio y análisis de renta larga y renta corta.

## Estado

| Módulo | Estado |
|---|---|
| Proyectos nuevos — Estrenar Vivienda (descarga, filtros, historial) | ✅ |
| Registro de proyectos con IDs estables (`PRY-0001`) | ✅ |
| Geocodificación sin IA (ficha + cruce de vías en OpenStreetMap) | ✅ |
| Ubicación y datos clave vía agente + verificación determinística | ✅ |
| Brochures PDF: área privada por tipología y datos clave | ✅ |
| Dashboard con datos reales (mapa, comparador, tabla, feed) | ✅ |
| Usados — Fincaraíz por barrio (lógica del proyecto anterior) + historial | ✅ (19 rutas confirmadas) |
| Usados — Metrocuadrado, Ciencuadras | Pendiente |
| Match nuevo ↔ usado | ✅ básico en el dashboard (zona, estrato, habitaciones, área ±15 %, antigüedad) |
| Zonas por esquinas (opcional, una vez, de noche) | ✅ |
| Ejecución diaria (launchd), publicación en GitHub y alertas (ntfy) | Pendiente — ver HANDOFF.md |

## Principios (del blueprint)

1. **La IA propone; el código decide.** El agente solo escribe `proposals/AAAA-MM-DD.json`. Las reglas (rangos, valores permitidos, evidencia) se aplican en Python.
2. **Evidencia antes que afirmaciones.** Cada dato lleva su URL fuente. Los agregadores (Estrenar Vivienda, Fincaraíz, etc.) nunca cuentan como evidencia de ubicación.
3. **Historial append-only.** No se borran proyectos ni tipologías: se marcan inactivos. Cada verificación queda en `data/checks.jsonl`.
4. **Stack simple.** Python, JSON en archivos, HTML estático.
5. **Modelo más económico por defecto.** Donde se use IA, se usa el modelo que menos consume la suscripción (`haiku`). Se sube de modelo solo si la calidad medida no alcanza, y de forma puntual (`--modelo sonnet`).

## Flujo

```
vivienda nuevos     Estrenar Vivienda → filtros → historial de tipologías → registro de proyectos → dashboard.json
vivienda geocodificar   sin IA: dirección de la ficha o del agente → cruce de vías en OSM (Overpass) → zona
vivienda ubicar     geocodificar → proyectos aún pendientes → Claude Code (headless, solo web + proposals/) → propuesta
                    → verificación (bbox, dirección en la fuente, calle en OpenStreetMap, polígono) → registro → dashboard.json
vivienda web        sirve el proyecto y abre el dashboard
```

### Precisión de la ubicación

Se cuentan tres señales independientes:

- **A.** La dirección aparece en la página citada (que no sea un agregador).
- **B.** La calle de OpenStreetMap en esas coordenadas coincide con la dirección.
- **C.** Las coordenadas coinciden (a menos de 60 m) con un enlace de Google Maps o Waze citado.

| Precisión | Señales |
|---|---|
| alta | 2 o 3 |
| media | 1 |
| baja | 0 (se guarda, con bandera en el mapa) |

Nunca se reemplaza una ubicación por otra de peor precisión.

### Zona

`config/zonas.toml`: cada zona es un centro y un radio (círculo, sin consultas externas). Opcionalmente, una zona
puede traer `esquinas` (cruces de vías en orden); `vivienda zonas` las ubica **una sola vez** en OpenStreetMap y
desde ahí la zona es ese polígono (data/processed/zonas_esquinas.json). Es lento (~1 min por esquina): se corre
de noche o cuando cambian las esquinas, no en el proceso diario. Si una esquina falla, la zona sigue como círculo.

La zona de cada proyecto nuevo la decide el **sector del sitio** (Santa Bibiana = corredor) o `zonas` en los
proyectos manuales. Si el sector es ambiguo (Chapinero = universitaria o calle 72), gana el centro más cercano.
La de un **usado** la decide su punto: entra si cae dentro de la figura de una zona.

### Usados (Fincaraíz)

Lógica heredada del proyecto anterior (documento maestro, `fincaraiz_scraper.py`):
datos del `__NEXT_DATA__` (`props.pageProps.fetchResult.searchFast`), URL por barrio
(Bogotá `/venta/{ruta}/bogota`, Floridablanca `/venta/{tipo}/canaveral/floridablanca/floridablanca`),
paginación como segmento (`/pagina2`), orden "más recientes", pausas de 3–6 s y una larga cada 10 páginas,
admin = `commonExpenses`, área privada = `m2apto`, estrato válido 1–6, proyectos (`isProject`) fuera.

- La URL de barrio trae vecinos: no se filtra por nombre de barrio, sino por el punto del anuncio dentro de una zona.
- Ascensor: campo del anuncio > descripción ("sin ascensor" gana) > edificio de 6+ pisos o apartamento en piso 6+ = *probable*
  (Fincaraíz manda 0 en pisos del edificio cuando no sabe: se toma como sin dato).
  Sin dato = no cumple la regla dura (se ve en la tabla como "Ascensor sin confirmar").
- Historial en `data/processed/usados.json`: primer/último día visto y cada cambio de precio. Un anuncio deja de
  mostrarse si no aparece en 7 días (`dias_vigencia`).
- Rutas nuevas: `vivienda usados --probar` (1 página por barrio, no guarda) y comparar el total con el navegador.

### Dirección de agregador

Si la única dirección disponible es la de un agregador (ficha de Estrenar, o la que reporte el agente en
`direccion_agregador`), se usa (precisión baja, marcada "pendiente de confirmar")
hasta que aparezca una fuente oficial, que la reemplaza automáticamente.

### Proyectos manuales

`config/proyectos_manuales.toml`: proyectos que ningún portal escaneado publica (brochure, cotización,
valla, referido). Se integran solos en cada comando: historial, registro, geocodificación por cruce, dashboard.
Pueden no tener precio (se muestran con "s/precio"). Si quitas uno del archivo, queda inactivo.

### Brochures

1. **Encontrar** (haiku, con web): solo la URL directa del PDF. `ubicar` también las recoge de paso.
2. **Descargar** (código): solo PDF directos (≤ 30 MB). Nunca se llenan formularios.
3. **Texto** (pypdf) y **reglas**: áreas privada/construida, ascensores, estrato, admin/m², entrega, acabados, dirección.
4. **Lectura asistida** (haiku **sin web**, solo si faltan áreas o ascensor): todo lo que proponga debe
   **aparecer literalmente en el texto del PDF**, o se rechaza.
5. **Área privada → tipología**, uno a uno: construida a ≤ 5 % y 0,75 ≤ privada/construida ≤ 0,97.
   El dashboard la usa en vez del factor 0,88.

El brochure es fuente oficial: reemplaza datos de agregador (p. ej. la entrega de Estrenar), no los de otra fuente oficial.
PDF de solo imágenes → quedan como `requiere_ocr` (fase posterior).

### Categorías del portal (renta corta)

La ficha de Estrenar trae "categorías" del proyecto (Renta Corta, CoWorking, Pet Friendly…). Si incluye
**Renta Corta**, el proyecto queda como apto para renta corta *según el portal*, con una bandera: es
mercadeo, no el reglamento de propiedad horizontal. Una fuente oficial lo reemplaza; si el portal quita
la categoría, el dato se retira. El dashboard tiene el filtro "Solo aptos para renta corta".

### Geocodificación por cruce de vías (sin IA)

Una dirección colombiana trae su ubicación: `Calle 105 # 23-42` = sobre la Calle 105, a ~42 m de la Carrera 23.
Se buscan ambas vías en OpenStreetMap (Overpass) y se toma su cruce (error típico 50–100 m).
Dirección de fuente oficial verificada → precisión **media**; de agregador (ficha de Estrenar) → **baja**.
Se ejecuta antes del agente, para que la IA solo trabaje en lo que el código no pudo resolver.

## Estructura

```
proyecto_vivienda_colombia/
├── agent/ubicar_prompt.md       instrucciones del agente (versionadas)
├── config/
│   ├── config.toml              filtros, sectores, agente, verificación  ← lo que más se edita
│   └── zonas.toml               zonas: centro + radio (+ esquinas opcionales)
├── src/vivienda/
│   ├── cli.py                   comando `vivienda`
│   ├── config.py  models.py  texto.py  geo.py
│   ├── reglas.py                valores permitidos y validación (lo que decide)
│   ├── verificacion.py          evidencia en la fuente + reverse geocoding (Nominatim)
│   ├── checks.py                bitácora append-only
│   ├── agente.py                invocación de Claude Code
│   ├── sources/estrenar/        fetcher.py + parser.py
│   ├── sources/fincaraiz/       cliente.py (URLs, pausas, __NEXT_DATA__) + parser.py (campos)
│   └── pipeline/
│       ├── filtros.py           precio, área, sector
│       ├── historial.py         tipologías: nuevas / cambios de precio / desaparecidas
│       ├── proyectos.py         registro de proyectos (IDs)
│       ├── aplicar.py           merger de propuestas
│       ├── usados.py            recorrido por barrio, zona por punto, historial de usados
│       ├── zonas.py             círculos y polígonos por esquinas
│       └── exportar.py          dashboard.json
├── data/
│   ├── raw/                     HTML descargado por fecha (no se versiona)
│   ├── processed/               nuevos.json · proyectos.json · dashboard.json
│   └── checks.jsonl             verificaciones
├── proposals/                   salidas del agente (auditoría)
├── web/index.html               dashboard
└── tests/
```

## Instalación (sin entorno virtual, Python de Homebrew)

```bash
python3 -m pip install --user --break-system-packages requests beautifulsoup4 lxml pypdf
echo 'alias vivienda="PYTHONPATH=/Users/fernandomartinez/personal_projects/proyecto_vivienda_colombia/src python3 -m vivienda"' >> ~/.zshrc
source ~/.zshrc
```

Para `vivienda ubicar` se necesita Claude Code instalado y con sesión iniciada (`claude auth login`).

## Comandos

```bash
vivienda nuevos                      # escanear sectores y actualizar todo
vivienda estado                      # proyectos: zona, precisión de ubicación, datos completados
vivienda geocodificar [--reintentar] # sin IA y sin costo: fichas + cruce de vías
vivienda direccion PRY-0008 "Calle 73 # 14-48" --fuente URL [--agregador]   # registrar/corregir a mano
vivienda ubicar                      # agente → verificación → aplicar (15 proyectos por corrida)
vivienda ubicar --max 3              # prueba corta
vivienda ubicar --modelo sonnet      # solo esta corrida con otro modelo
vivienda ubicar --datos              # incluir proyectos ubicados a los que les faltan datos clave
vivienda ubicar --solo-prompt        # genera .run/prompt_<fecha>.md para correrlo a mano
vivienda aplicar proposals/2026-10-26.json   # verificar y aplicar una propuesta existente
vivienda brochures --buscar          # haiku busca los PDF → descarga → reglas → haiku SIN web si faltan datos
vivienda brochures --sin-ia          # solo descargar/procesar las URLs ya conocidas, sin IA
vivienda brochure PRY-0005 ~/Downloads/brochure.pdf   # brochure bajado a mano (p. ej. tras un formulario)
vivienda usados                      # usados de Fincaraíz (≈15–20 min con tope de 8 páginas: pausas de cortesía)
vivienda usados --probar             # 1 página por barrio, no guarda: confirma rutas y campos
vivienda usados --barrio palermo     # solo rutas que contengan ese texto
vivienda zonas                       # OPCIONAL, de noche: polígonos por esquinas (una vez)
vivienda exportar                    # regenerar dashboard.json
vivienda web                         # dashboard en http://localhost:8000 (?demo=1 para datos ficticios)
PYTHONPATH=src python3 -m unittest discover tests
```

## Corrida diaria (v0.7)

`vivienda diario` = `nuevos` → `geocodificar` → `ubicar` (solo si hubo proyectos nuevos, máx. `[diario] ubicar_max`,
haiku) → `usados` (tope `max_paginas_usados`) → `exportar` → publicar (si `publicar = true`) → alertas ntfy.
Candado en `.run/diario.lock`; log en `logs/AAAA-MM-DD.txt`; resumen en `data/processed/ultima_corrida.json`.
Un paso que falla no detiene los demás: queda en `errores` y dispara la alerta "Corrida con problemas".

- Instalar en launchd: `vivienda programar` (hora de `[diario] hora`) · quitar: `vivienda programar --quitar`.
- Despertar el Mac: `sudo pmset repeat wakeorpoweron MTWRFSU 06:25:00`.
- Alertas: poner un tema largo y aleatorio en `config/ntfy_tema.txt` (ignorado por git) y suscribirse en la app ntfy.
- Publicación: `docs/` = `web/index.html` + `dashboard.json` **sin descripción ni publicador** de los anuncios.
  `data/`, `logs/`, `.run/`, `proposals/` y el tema de ntfy nunca entran al repo (`.gitignore`).

## Cómo agregar o corregir un sector

En `config/config.toml`:

```toml
[[estrenar.sectores]]
ruta = "bogota/norte/nuevo-sector"   # lo que va después de /proyectos-vivienda/ en la URL
zonas = ["cor"]
verificado = false
```

## Notas de datos

- Estrenar Vivienda publica **área construida**; el dashboard estima el área privada con un factor configurable.
- Cada tarjeta del sitio es una **tipología**; los proyectos se agrupan por la URL.
- Arriendo por m² y ADR por zona en el dashboard todavía son **supuestos**, no datos de mercado.
