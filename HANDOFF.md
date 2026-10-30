# HANDOFF — Proyecto Vivienda Colombia (v0.10.0, 30-oct-2026)

Documento para retomar el proyecto en una conversación nueva con Claude. Contiene el contexto, las
decisiones tomadas (y por qué), el estado real, lo que falta y cómo trabajar con el usuario.
Léelo completo antes de proponer cambios. El README tiene el detalle operativo de cada módulo.

---

## 1. Qué es

Radar de inversión inmobiliaria personal. Compara **proyectos de vivienda nueva** con **vivienda usada
comparable** en zonas específicas, para decidir dónde comprar para arrendar (renta larga o corta).

- **Zonas (v0.8, dibujadas por el usuario en `config/zonas_dibujadas.geojson`):** Bogotá — Chapinero Central (chu,
  Cl. 53–72 Caracas–7ª), Country – Chapinero Norte (lag, Cl. 76–85 Caracas–11), Navarra – San Patricio (nav),
  La Castellana (cas), Pasadena (pas), Morato – Pontevedra – Potosí (mor), Galerías – Chapinero Occidental (teu).
  Floridablanca — Cañaveral – El Bosque (can, redibujada v2; en el dashboard "Bucaramanga").
  v0.8.1: c72 = Quinta Camacho – Calle 72 (Cl. 70–76, Caracas–7ª), armada con los vértices de borde de chu y lag
  (sin hueco ni traslape; hay prueba de no-traslape). Chapinero Alto EXCLUIDO (sector quitado de config.toml).
  cor se retiró. Al oeste de la Caracas no hay zona (p. ej. 64 Estorias, Cra. 15 con Cl. 64B: fuera).
- **Reglas duras:** precio total ≤ $600 M (incluye parqueadero), **con ascensor**.
- **Variables clave:** administración (y admin/m²), estrato, parqueadero (regla flexible), habitaciones, ascensor,
  antigüedad (los edificios viejos suelen prohibir renta corta), área privada vs. construida.
- Uso **personal y con propósitos educativos**. Todo debe ser **gratis** (sin APIs pagas).

## 2. Cómo trabajar con el usuario (Fernando)

- Escribe en **español**, directo, sin relleno. Le gusta un consultor que discute, no que solo asiente.
- **"Hazlo simple, no tan preciso."** Ya pidió dos veces simplificar cuando se sobre-diseñó (polígonos por
  esquinas que tardaban; demasiada precisión geográfica). Preferir lo simple que funciona.
- **Modelo de IA:** siempre el más barato (`haiku`). Subir de modelo solo con evidencia medida y por corrida
  (`--modelo sonnet`), nunca cambiando el default.
- **Dirección de agregador:** si es la única que hay, se usa (precisión baja, "pendiente de confirmar") hasta que
  aparezca una oficial.
- **Entorno:** Mac mini, Python de Homebrew, **sin entorno virtual** (`pip --user --break-system-packages`).
  Proyecto en **`/Users/fernandomartinez/personal_projects/proyecto_vivienda_colombia`**.
  Alias en `~/.zshrc`:
  `alias vivienda="PYTHONPATH=/Users/fernandomartinez/personal_projects/proyecto_vivienda_colombia/src python3 -m vivienda"`
- **Claude no puede llegar a los sitios.** El sandbox de Claude no accede a estrenarvivienda.com ni a
  fincaraiz.com.co (allowlist). Flujo de trabajo: Claude edita el código, corre las pruebas con datos
  simulados, entrega un **zip**; el usuario lo instala, corre los comandos y pega la salida.
- **Instalar un zip nuevo sin dejar basura en Descargas** (las carpetas `v064`, `v065` y `noche.txt` que
  aparecieron en Descargas venían de los comandos de instalación anteriores, no del código):
  ```bash
  T=$(mktemp -d) && unzip -q ~/Downloads/proyecto_vivienda_colombia.zip -d "$T" \
    && rsync -a "$T/proyecto_vivienda_colombia/" ~/personal_projects/proyecto_vivienda_colombia/ \
    && rm -rf "$T" ~/Downloads/proyecto_vivienda_colombia.zip
  ```
  `rsync` sin `--delete` no toca `data/`. Los logs de corridas largas van a `logs/` dentro del proyecto
  (ya está en `.gitignore`), no a Descargas: `... > ~/personal_projects/proyecto_vivienda_colombia/logs/AAAA-MM-DD.txt 2>&1`.
  El zip excluye `data/`, `__pycache__` y `.run/`.

## 3. Arquitectura (del blueprint del usuario)

1. **La IA propone; el código decide.** El agente (Claude Code headless) solo escribe JSON en `proposals/`;
   Python valida rangos, evidencia y reglas antes de aplicar.
2. **Evidencia antes que afirmaciones:** cada dato lleva URL fuente; agregadores no cuentan como evidencia oficial.
3. **Historial append-only:** nada se borra, se marca inactivo. Bitácora en `data/checks.jsonl`.
4. **Stack simple:** Python + JSON en archivos + HTML estático (Leaflet). Sin base de datos ni servidor.
5. **Pendiente del blueprint:** ejecución diaria con **launchd**, **git**, publicación en **GitHub Pages** y
   alertas con **ntfy** → ver sección 8.

## 4. Estado actual

| Módulo | Estado |
|---|---|
| Nuevos: Estrenar Vivienda por sector + historial de tipologías + registro `PRY-0001` | ✅ 15 proyectos, 13 en el mapa |
| Proyectos manuales (`config/proyectos_manuales.toml`) | ✅ lumina-77, la-cite, street-52, distrito-kb |
| Geocodificación sin IA (dirección → cruce de vías en OpenStreetMap/Overpass) | ✅ |
| Agente `ubicar` (haiku): dirección oficial, estrato, admin, ascensor, renta corta | ✅ |
| Brochures PDF (área privada por tipología) | ✅ manual (`vivienda brochure PRY-x archivo.pdf`); búsqueda automática fuera de la rutina |
| Usados: Fincaraíz por barrio + historial de precios | ✅ 1.384 en zonas / 1.188 vigentes (corrida con tope 8 páginas) |
| Dashboard: mapa (Nuevos / Usados / Ambos), panel de proyecto, **panel de usado**, Tabla, pestaña **Usados**, Detectados, Supuestos | ✅ |
| Zonas: círculos por defecto; polígono por esquinas opcional (`vivienda zonas`) | ✅ |
| Carga profunda de usados (`--max-paginas 40`) + `vivienda zonas` | ⏳ corriendo al cierre; log en `logs/carga_inicial.txt` — pedirlo |
| Arriendos reales (para yield de mercado) | ❌ hoy el arriendo/ADR por zona son **supuestos** en `web/index.html` |
| Metrocuadrado / Ciencuadras, deduplicación entre portales | ❌ |
| Corrida diaria (`vivienda diario`, `vivienda programar`), alertas ntfy (tema `fmz_proyecto_vivienda` en `config/ntfy_tema.txt`), publicación saneada en `docs/` | ✅ código. Publicación decidida: repo público github.com/fjmartinez0/proyecto_vivienda_colombia + Pages desde `main /docs` → https://fjmartinez0.github.io/proyecto_vivienda_colombia/web/ (primera vez: `scripts/configurar_github.sh`) |

80 pruebas pasan (requieren `tests/fixtures/*.html`, que no se publican): `PYTHONPATH=src python3 -m unittest discover -s tests`.

## 5. Mapa del código

```
config/config.toml              filtros, [agente], [estrenar] 15 sectores, [fincaraiz] 19 barrios  ← lo más editado
config/zonas.toml               8 zonas: centro + radio (+ esquinas opcionales en chu, c72, lag, teu)
config/proyectos_manuales.toml  proyectos que no están en portales
src/vivienda/cli.py             todos los comandos `vivienda ...`
src/vivienda/sources/estrenar/  fetcher, parser (tarjeta = tipología), ficha (dirección, entrega, categorías)
src/vivienda/sources/fincaraiz/ cliente (URLs, pausas, __NEXT_DATA__, diagnóstico de bloqueo), parser (campos)
src/vivienda/sources/manual.py, brochure.py
src/vivienda/pipeline/          historial, proyectos, filtros, geocodificar, aplicar, brochures, usados, zonas, exportar
src/vivienda/geo.py             bbox por ciudad, punto en polígono, zona_de (traslape: gana centro más cercano / radio)
src/vivienda/geocodificacion.py cruce de vías vía Overpass (3 servidores, alias de avenidas)
src/vivienda/verificacion.py    señales A/B/C de ubicación, Nominatim
src/vivienda/agente.py          Claude Code headless (haiku), solo escribe en proposals/
agent/*.md                      prompts versionados
web/index.html                  dashboard (lee ../data/processed/dashboard.json; ?demo=1 = datos ficticios)
data/processed/                 nuevos.json, proyectos.json, usados.json, dashboard.json, zonas_esquinas.json
data/raw/                       HTML/JSON crudo por fecha (no se versiona)
```

Comandos principales: `nuevos`, `geocodificar`, `ubicar`, `aplicar`, `direccion`, `brochures`, `brochure`,
`usados [--probar] [--barrio] [--max-paginas]`, `zonas [--forzar]`, `estado`, `exportar`, `web`.

**Qué consume la suscripción de Claude:** solo `ubicar`, `brochures --buscar` y la lectura asistida de
brochures (Claude Code con haiku). `nuevos`, `geocodificar`, `usados`, `zonas`, `exportar` y `web` son Python
puro: **no consumen Claude**.

## 6. Decisiones clave (no cambiar sin discutir)

**Nuevos (Estrenar Vivienda)**
- Cada tarjeta es una tipología; los proyectos se agrupan por URL. Solo cuentan para "corrida completa" los
  sectores `verificado = true` (los candidatos que den 404 no bloquean).
- **(v0.8) La zona la decide el punto**, también para proyectos: dentro del polígono, o a ≤ 150 m del borde (error de
  ubicación + dibujo; queda nota). Más lejos → "fuera de zonas". El sector del sitio solo desempata traslapes.
- Ubicación: señales A (dirección en página oficial), B (calle OSM en esas coordenadas), C (enlace Maps/Waze).
  alta = 2–3, media = 1, baja = 0. Nunca se reemplaza por una de peor precisión.
- Categoría "Renta Corta" del portal = apto según el portal, con bandera (es mercadeo, no reglamento).
- Área privada: brochure o manual; si no hay, construida × 0,88.

**Usados (Fincaraíz) — lógica heredada del proyecto anterior del usuario (documento maestro)**
- Datos en `__NEXT_DATA__` → `props.pageProps.fetchResult.searchFast {data, paginatorInfo}`.
- Bogotá: `/venta/{ruta}/bogota[/paginaN]?ordenListado=3` (sin tipo; se filtra en código).
  Floridablanca: `/venta/{apartamentos|apartaestudios}/canaveral/floridablanca/floridablanca` (un recorrido por tipo).
- La paginación es segmento de ruta (`/pagina2`); `?pagina=` se ignora en silencio.
- `san-felipe` corto lleva a otro lugar del país → usar `san-felipe/zona-noroccidente`.
- Pausas 3–6 s, pausa larga 15–25 s cada 10 páginas; si dos barrios seguidos dan bloqueo (403/429/captcha), se detiene.
- **Usados de entorno (v0.8):** los anuncios fuera de toda zona se guardan con `zona = null`: no son inventario de
  ninguna zona (no salen en mapa/tabla de usados) pero sí referencia fuera de zona (informativa).
  Sin esto, con zonas ajustadas, Country y Chapinero quedaban sin comparables.
- **La zona la da el punto del anuncio, no el barrio** (la URL de barrio trae vecinos). Zonas traslapadas:
  gana la de menor distancia/radio (si no, el corredor se tragaba a Pasadena).
- Campos: admin = `commonExpenses` (86 % lleno); área privada = `m2apto` (72 %); estrato válido 1–6;
  `isProject` fuera; `to_number` toma el primer bloque numérico ("55 m2" → 55).
- **Pisos del edificio llega en 0 cuando no se sabe** → se trata como sin dato.
- Ascensor: campo/amenidad del anuncio > descripción ("sin ascensor" gana) > edificio 6+ pisos o apartamento
  en piso 6+ = *probable*. Sin dato (~31 %) = **no cumple la regla dura**.
- Historial `usados.json`: primer/último visto y cada cambio de precio; vigente si se vio en los últimos 7 días.
- `el-lago` se quitó (mismo listado que `lago-gaitan`). `chico-norte` (2.987) y `chico-navarra` (1.709) son
  listados de sector, no de barrio: no importa porque se filtra por punto.
- Se capturan también fecha de publicación (`created_at`), amenidades (`facilities`) y descripción (700 caracteres).

**Dashboard**
- Sobreprecio real = m² del nuevo en valor presente (+ acabados si obra gris + arriendo perdido durante obra)
  vs. m² de usados comparables con descuento de negociación (7 %). Supuestos editables en la pestaña Supuestos.
- Comparables: misma zona, estrato (del proyecto si se conoce), habitaciones, área privada ±15 %, antigüedad ≤ 15
  años (si se conoce), con ascensor. Parqueadero flexible.
- **Comparables (v0.8.2): SOLO de la misma zona** (las zonas son submercados; antes Morato tomaba comparables de
  Pasadena, 14 % más cara, y el sobreprecio salía bajo). Paso 0 estricto; si hay < `min_comps` (5), paso 1 dentro de
  la zona con área ±25 %, antigüedad ≤ 25 y estrato ±1 (pin con `≈`). < 3 → `s/c`. El estrato solo filtra si el
  proyecto lo tiene confirmado. Usados de otras zonas o del entorno a ≤ 1,5 km se muestran como **referencia
  informativa** en el panel/tooltip, nunca en el pin. Se probó y descartó un ajuste por ubicación con medianas de
  zona: con 40–60 anuncios por zona las medianas son ruido (Morato salía más cara que Pasadena).
  Ojo: área ampliada hacia unidades más grandes infla el sobreprecio (el $/m² baja con el tamaño).
- Pin de proyecto = nombre + valor (v0.7.2), siempre visible.
- **Proyectos en seguimiento (v0.9):** `seguimiento = true` en proyectos_manuales.toml los muestra en el mapa aunque
  queden fuera de zonas (pin punteado). Se publican con `fuera_de_zona`, la zona más cercana (solo para supuestos de
  arriendo/ADR) y comparables por distancia (≤ 1 km estricto, ≤ 1,5 km ampliado, cualquier zona). `lat`/`lng` en el
  manual fijan la ubicación sin geocodificar. Hoy: Mava 92, Heritage 97 (Chicó, fuera) y Torres del Valle (Cañaveral).
- **Escaneo web 30-oct (WebFetch sí llega a Estrenar/Fincaraíz/Ciencuadras, pero solo a URLs salidas de WebSearch):**
  nada nuevo en zonas que pase filtros. Palco (Galerías, 22,7 m²) y Verona/Amarilo (Puente Largo, 27 m²) quedan bajo
  30 m²; Open C60 (Chapinero occidental, sin dirección), View 63 y Serendipia (Chapinero Alto, excluido), Optimus 61
  (San Luis, 20 m²), UR 67 (agotado).
- **Zonas v3 (30-oct):** + Los Andes – La Floresta (and, tal cual se dibujó), Alhambra – Batán (bat) y Santa Bárbara
  (sba); bat y sba con la rendija de 14–26 m contra Pasadena/Navarra cerrada (cierre morfológico, +0,8 % y +0,1 %).
  NO se cerró and–pas (61 m): metía a Zento en Los Andes. and–mor/cas quedan a 17–27 m (ancho de calle).
  Nombres de las 3 zonas = provisionales (deducidos de la ubicación). Rutas nuevas en config.toml como CANDIDATAS
  (Estrenar: los-andes, batan, santa-barbara; Fincaraíz: la-floresta, andes-norte, alhambra, el-batan,
  santa-barbara-central/occidental) → confirmar con `usados --probar`. Hoy esas zonas tienen 0–5 usados.
  Escaneo: Loto122 (21,9 m²), Edificio Balmes (21–22 m²), Córdoba 127 ($928 M), Solara 93 (20,8 m²) no pasan filtros.
  Verona (Amarilo) agregado como manual: Fincaraíz 32 m² $450 M (antes se descartó por los 27 m² de Ciencuadras).
- **Instagram (pendiente, solo plan):** ver respuesta del 30-oct; camino legal = Graph API Business Discovery, no scraping.
- Street 52: cotización apto 303 $365,5 M; entrega 2028-01 INFERIDA (cuota inicial termina ~dic-2027).
- Estado de obra: Estrenar no lo publica; el tooltip muestra la fecha de entrega cuando no hay estado.
- Color de usados en el mapa: $/m² vs. mediana de su zona (verde ≤ −10 %, rojo ≥ +10 %). Grupos en gris.

## 7. Limitaciones conocidas

- **Arriendo largo y ADR de renta corta por zona son supuestos** escritos en `web/index.html` (ZONAS). Los yields
  son indicativos. El siguiente módulo de mayor valor: capturar **arriendos** de Fincaraíz (mismo código con
  `operacion="arriendo"`) y estimar canon con el matching del proyecto anterior (k = 3 vecinos dentro de la
  misma zona, distancia estandarizada sobre área, estrato, antigüedad, piso, habitaciones, baños; mediana).
- Estrato "típico" por zona también es un supuesto del dashboard.
- Renta corta de usados siempre "desconocida" (el anuncio no lo dice).
- Solo una fuente de usados (Fincaraíz).
- Las zonas por esquinas solo están definidas para chu, c72, lag, teu; el resto son círculos.
- `rsync` de instalación no borra archivos que se eliminen entre versiones (inofensivo hasta ahora).

## 8. Próximos pasos (NO están codificados — hacerlos en la nueva conversación)

### 8.0 Primero
Pedir `logs/carga_inicial.txt` (carga profunda: `usados --max-paginas 40` y `zonas`) y revisar: bloqueos,
zonas que fallaron por esquina, volumen por zona.

### 8.1 Corrida diaria automática (launchd)
- Script `scripts/corrida_diaria.sh` (o comando `vivienda diario`) con candado para no solaparse, que haga:
  `nuevos` → `geocodificar` → `usados` (tope 8 páginas) → `exportar` → publicar (8.2) → alertar (8.3).
  Log en `logs/AAAA-MM-DD.txt`.
- `ubicar` (consume Claude, haiku) **no** diario: solo si `nuevos` detectó proyectos nuevos, con `--max` bajo.
- Que cada comando deje un resumen legible por máquina, p. ej. `data/processed/ultima_corrida.json`
  (proyectos nuevos, tipologías con cambio de precio, usados nuevos, errores, si la corrida fue parcial).
  Hoy los nuevos solo se imprimen en consola (`cmd_nuevos` calcula `nuevos_ids`).
- `~/Library/LaunchAgents/co.vivienda.diario.plist` a una hora fija (p. ej. 6:30 a. m.). El Mac debe estar
  despierto: `sudo pmset repeat wakeorpoweron MTWRFSU 06:25:00`. launchd no hereda el alias: usar rutas
  absolutas (`/opt/homebrew/bin/python3`, `PYTHONPATH=.../src`).
- `zonas` no va en la rutina (solo cuando cambien las esquinas).

### 8.2 Publicación en GitHub (repo público + GitHub Pages)
- Repo público con el código; GitHub Pages sirviendo `web/index.html` y `data/processed/dashboard.json`
  (el HTML ya lee `../data/processed/dashboard.json`, así que Pages desde la raíz funciona sin cambios).
- Versionar solo lo necesario: código, config, `data/processed/dashboard.json` (y si se quiere el historial
  `nuevos.json`/`proyectos.json`/`usados.json`); **nunca** `data/raw/`, `.run/`, `logs/`.
- El script hace `git add` de lo publicado, `git commit -m "corrida AAAA-MM-DD"` y `git push` solo si hubo
  cambios. Autenticación con `gh auth login` o llave SSH.
- **Decidido (25-oct):** publicar ya. El repo NO lleva `data/`, `logs/`, `proposals/`, el tema de ntfy ni las páginas
  de portales de `tests/fixtures`; `docs/` lleva el dashboard sin descripción ni publicador de los anuncios.
- Riesgos que se aceptaron:
  - Publicar datos extraídos de portales en un repo público puede ir contra sus términos de uso. Mínimo:
    **no publicar la descripción del anuncio** (texto con derechos de autor) ni datos de contacto; dejar el
    enlace al anuncio y los números. Alternativa: repo privado + Pages (requiere plan pago de GitHub) o
    publicar solo agregados por zona.
  - `proposals/` y `checks.jsonl` pueden quedarse fuera del repo público.
  - Un repo público hace visibles las zonas y la estrategia de inversión del usuario.

### 8.3 Alertas (ntfy)
- `curl -d "mensaje" ntfy.sh/<tema>` al detectar **proyecto nuevo** (requisito del usuario). Mensaje:
  nombre, zona, precio desde, entrega, enlace a la ficha y al dashboard publicado.
- Opcionales a proponer: tipología con baja de precio, usado ≥ 15 % por debajo de la mediana de sus similares,
  corrida fallida o parcial (bloqueo de Fincaraíz).
- El tema de ntfy es público para quien conozca el nombre: usar uno largo y aleatorio, guardado fuera del repo
  (variable de entorno o archivo en `.gitignore`).

### 8.4 Después
- Arriendos reales (sección 7) → yields de mercado en ambos paneles.
- Metrocuadrado / Ciencuadras + deduplicación entre portales.
- Brochures con OCR (PDF de solo imágenes quedan como `requiere_ocr`).

## 8.5 Resultado de la carga profunda (25-oct)
Usados vigentes por zona (total / cumplen ≤ $600 M y con ascensor): c72 131/23 · can 442/231 · chu 286/170 ·
cor 1.607/154 · lag 53/24 · mor 54/8 · pas 260/52 · teu 87/28. Sin bloqueos. chico-norte, chico-navarra y
santa-bibiana llegaron al tope de 40 páginas (no importa: cor sobra). **Morato (8) y c72/lag/teu (~25) tienen pocos
comparables** → agregar barrios vecinos en `[fincaraiz]`. Esquinas: "Caracas" no se encontraba por nombre en OSM
(ahora el patrón acepta "Carrera 14"); el resto fueron caídas de Overpass → reintentar `vivienda zonas`.

## 9. Historial de errores que no hay que repetir

- Usar opus por defecto (el usuario lo pidió explícitamente: siempre haiku).
- Sobre-diseñar la geografía (polígonos por esquinas en cada corrida): ahora es opcional y una sola vez.
- Asignar zona de usados por nombre de barrio o por el primer círculo que contenga el punto.
- Confiar en ceros de Fincaraíz como datos (pisos del edificio).
- Dejar carpetas y logs en Descargas con los comandos de instalación.
- Usar el alias `vivienda` dentro de `sh -c`, `caffeinate` o launchd: los alias de zsh no existen ahí
  (`sh: vivienda: command not found`). En scripts usar `PYTHONPATH=<proyecto>/src python3 -m vivienda ...`.
- Redirigir la salida a un archivo sin `python3 -u` (o `PYTHONUNBUFFERED=1`): Python la guarda en búfer y el log
  se ve vacío durante minutos aunque esté corriendo. En scripts y launchd usar siempre `python3 -u`.
