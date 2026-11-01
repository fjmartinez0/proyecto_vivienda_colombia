# HANDOFF — Proyecto Vivienda Colombia (v0.14.1, 01-nov-2026)

Documento para retomar el proyecto en una conversación nueva con Claude. Contiene el contexto, las
decisiones tomadas (y por qué), el estado real, lo que falta y cómo trabajar con el usuario.
Léelo completo antes de proponer cambios. El README tiene el detalle operativo de cada módulo.

**Para arrancar un chat nuevo:** sube `proyecto_vivienda_colombia.zip` + este archivo y pega:
> Retomo el Proyecto Vivienda Colombia. Lee HANDOFF.md completo, descomprime el zip, corre las pruebas
> y dime en 5 líneas el estado. No cambies nada todavía.

El repo público (https://github.com/fjmartinez0/proyecto_vivienda_colombia) refleja la última publicación del
usuario; el zip es la fuente de verdad del código (puede ir adelante del repo hasta que el usuario lo instale y publique).

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
  v3 (30-oct): + Los Andes (and), El Batán (bat), Santa Bárbara (sba). Total 12 polígonos.
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
5. **Blueprint completo:** corrida diaria con launchd (`vivienda programar`), git + GitHub Pages
   (`vivienda publicar`) y alertas ntfy ya están implementados (v0.10+).

## 4. Estado actual (v0.14.1, 01-nov-2026)

| Módulo | Estado |
|---|---|
| Nuevos: Estrenar Vivienda, 17 sectores (`[estrenar]`) + historial de tipologías + registro `PRY-xxxx` | ✅ |
| Proyectos manuales (`config/proyectos_manuales.toml`, 20) | ✅ lumina-77, la-cite, street-52, distrito-kb, mava-92, heritage-97, torres-del-valle, verona-amarilo, viu-park-home, alma-72, ivin-refugio, ivin-lago, palco, loto-122, edificio-balmes, altus-124, 64-estorias, kobe-50, reserva-26, g95 |
| Correcciones a proyectos de portal (`config/ajustes_proyectos.toml`, v0.14) | ✅ dirección/pin por nombre + `[excluir]` |
| Geocodificación sin IA (cruce de vías en Overpass, una consulta por zona, alias de avenidas) | ✅ |
| Agente `ubicar` (haiku) | ✅ solo si hay proyectos nuevos |
| Usados: Fincaraíz, 29 barrios, + pasada extra de apartaestudios en Bogotá | ✅ |
| Limpieza de muestra: puntos genéricos, unidades de proyecto, duplicados, máx. 2 por edificio | ✅ v0.13.1 |
| Segmentos Estándar (≥ 30 m²) / Micro (18–30 m²) en pestañas separadas | ✅ v0.13 |
| Zonas dibujadas (geojson, 12 polígonos) | ✅ |
| Corrida diaria (`diario`, `programar` → launchd), alertas ntfy `fmz_proyecto_vivienda`, publicación en Pages | ✅ |
| Dashboard publicado | https://fjmartinez0.github.io/proyecto_vivienda_colombia/web/ (repo público fjmartinez0/proyecto_vivienda_colombia) |
| Arriendos reales / ADR medido | ❌ supuestos en `web/index.html` |
| Segunda fuente de usados (Metrocuadrado/Ciencuadras) + dedupe entre portales | ❌ siguiente módulo recomendado |
| Instagram de constructoras | ❌ solo plan (Graph API Business Discovery) |

93 pruebas pasan: `PYTHONPATH=src python3 -m unittest discover -s tests` (los fixtures HTML no se publican en el repo).

## 5. Mapa del código

```
config/config.toml               filtros (precio_max, area_min=30, area_min_micro=18), [agente], [estrenar] 17 sectores,
                                 [fincaraiz] 29 barrios, [diario] (publicar=true, url_dashboard, alertas)
config/zonas_dibujadas.geojson   12 zonas dibujadas por el usuario (mandan sobre zonas.toml): chu c72 lag nav cas pas
                                 mor teu can and bat sba
config/zonas.toml                nombres/metadatos y respaldo de círculos
config/proyectos_manuales.toml   proyectos fuera de portales (lat/lng, precision, seguimiento, tipologías)
config/ajustes_proyectos.toml    correcciones por nombre a proyectos de Estrenar + exclusiones
config/ntfy_tema.txt             tema ntfy (fuera del repo)
src/vivienda/cli.py              todos los comandos; _proyectos_al_dia = manuales → sincronizar → ajustes → rezonificar
src/vivienda/ajustes.py          aplica ajustes_proyectos.toml (marca `excluido`, dirección 'manual', lat/lng)
src/vivienda/sources/estrenar/   fetcher, parser (tarjeta = tipología), ficha (dirección, entrega, categorías)
src/vivienda/sources/fincaraiz/  cliente + parser (ascensor, antigüedad, área, publicador)
src/vivienda/sources/manual.py, brochure.py
src/vivienda/pipeline/           historial, proyectos, filtros (segmento), geocodificar, aplicar, brochures,
                                 usados (para_dashboard: rezonifica, segmento, ubicaciones genéricas, unidades de proyecto),
                                 zonas, exportar (construir: seguimiento/fuera_de_zona, segmento por tipología), diario
src/vivienda/geo.py              asignar_zona (tolerancia 150 m para proyectos), distancia_a_poligono_m, bbox
src/vivienda/geocodificacion.py  cruce de vías (Overpass, 3 servidores), alias (Caracas=Cra 14, Tv 60=Av. Suba…)
src/vivienda/agente.py           Claude Code headless (haiku), solo escribe en proposals/
web/index.html                   dashboard Leaflet (comparables, segmentos, paneles, tabla, supuestos)
scripts/configurar_github.sh     primera configuración del repo/Pages
docs/                            copia saneada que sirve GitHub Pages (la genera `vivienda publicar`)
```

Comandos: `nuevos`, `geocodificar`, `ubicar`, `aplicar`, `direccion`, `brochures`, `brochure`, `usados`, `zonas`,
`diario`, `publicar`, `programar`, `estado`, `exportar`, `web`.
Solo `ubicar` y la lectura asistida de brochures consumen Claude (haiku); el resto es Python puro.

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
- Ascensor (misma regla para comprar y para comparar): campo/amenidad del anuncio > descripción ("sin ascensor"
  gana) > edificio 6+ pisos o apartamento en piso 6+ = *probable* (cuenta como sí). Sin dato = **descartado**.
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
- Tooltip de comparables (v0.11.1) = el mismo de la capa de usados (tipo, m², barrio, precio, $/m² vs. zona) + $/m² ajustado.
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
- **Comparables de unidades pequeñas (30-oct, sin zip aún):** (1) en Bogotá `usados` hace además un recorrido
  `/venta/apartaestudios/{barrio}/bogota` por barrio: el general (más recientes, tope de páginas) enterraba los
  apartaestudios; un error en ese recorrido extra no marca el barrio como fallido. (2) Se probó admitir para comparar usados sin
  dato de ascensor con edificio ≤ 15 años y el USUARIO LO RECHAZÓ: la regla es una sola para comprar y comparar —
  ascensor confirmado, o edificio de 6+ pisos / apto en piso 6+ ("probable"); si no, se descarta. No reabrir. En Fincaraíz hay una reventa de Ciento5I (33 m², $362 M)
  vs. lista nueva $422 M. Rutas nuevas candidatas: navarra/zona-norte, san-patricio/zona-norte.
- Torres del Valle salía "sin ubicar" (el cruce Calle 158 × Carrera 18 no está así en OSM): ahora usa el pin de
  Google Maps del usuario (7.069997, -73.1151028). OJO: el punto de "FOSUNAB" del círculo viejo (7.0705, -73.1065)
  quedaba ~950 m al oriente; no usarlo como referencia. Verona: dirección cambiada a "Avenida Suba con Calle 106" (Tv 60 = Av. Suba;
  "Tv 60 # 106" se interpretaba como Diagonal 106). Alias nuevo ("transversal","60") → Avenida Suba.
- Escaneo profundo zonas nuevas: Viu Park Home (Gradeco, Santa Bárbara Occ., 36,45 m², $395 M, publicado 2024 —
  confirmar vigencia) agregado. El Polo (Cl 84 # 28B-45, 28 m²), UBA y Torre de Los Andes (retirados), Altus 124
  (18 m², obra gris) no entran.
- **Carga 30-oct (apartaestudios + rutas nuevas):** 29 barrios, sin bloqueos, las 10 rutas candidatas verificadas.
  4.960 usados vigentes (391 apartaestudios), 2.066 de entorno. Zonas (total/cumplen): nav 987/85, sba 659/77,
  pas 316/70, bat 181/47, chu 129/62, can 264/103, mor 87/26, lag 64/22, teu 61/26, cas 58/15, c72 56/4, and 32/13.
- **Muestra limpia (v0.12):** `unidad_proyecto` = la publica una constructora o es de un edificio con ≥ 4 anuncios
  todos sin antigüedad / < 1 año (inventario nuevo subido unidad por unidad: El Refugio/IVIN en Country, Chicó Norte,
  Santa Paula; 55 marcadas). No cuentan como comparables. Máximo 2 comparables por edificio (clave = punto a ~11 m).
  Efecto: La Cité, Lumina 77 y Metro 73 → s/c (sus "comparables" eran El Refugio). Nueva referencia informativa
  **vs. proyectos nuevos cercanos** (unidades de proyecto + otros proyectos del radar, ≤ 1,5 km, mismas alcobas, área
  ±25 %, $/m² de lista, mediana por edificio): La Cité −11 % (4 proyectos), Lumina −24 %, Metro 73 +8 %.
- 77 Estorias ya no aparece en Estrenar (inactivo: vendido o retirado).
- **Segmento MICRO (v0.13, 01-nov):** pestaña aparte en el visor ("Estándar · ≥ 30 m²" | "Micro · < 30 m²"), nunca
  mezcladas; se recuerda en el navegador. Corte = `[filtros] area_min` (30 m² CONSTRUIDOS); piso `area_min_micro` = 18.
  Las tipologías de 18–30 m² ya no se descartan: se exportan con `segmento: "micro"`; los usados igual (área construida,
  o privada ÷ 0,88). Un proyecto mixto (Metro 73, Ciento5I, Zento, Heritage) sale en ambas pestañas con sus tipos.
  Comparables micro (decisión del usuario: la renta corta es un producto nuevo): SOLO edificios con antigüedad
  CONOCIDA ≤ `micro_max_antig` (8 años = tramos Fincaraíz "menor a 1" y "1 a 8"); sin dato de antigüedad no entra;
  no exige alcobas; área ±20 % (±30 % ampliado, la antigüedad NO se amplía); misma zona; misma regla de ascensor,
  limpieza de unidades de proyecto y máx. 2 por edificio. ADR micro = ADR 1 alcoba × `adr_micro` (0,85, supuesto).
  Bandera de reglamento/regulación de renta corta en cada ficha micro. Manuales micro agregados: Alma 72, IVIN
  Refugio, El Polo, Palco, Loto122, Edificio Balmes, Altus 124 (+ tipos micro de Verona y Mava 92). Sin ubicar aún:
  Signature Virrey, Solara 93, Paloverde, Atelier 68, Nau House. Mockup previo: claude.ai/artifact/YJXfg9hJcSThVjee9kRryH
- **Limpieza de muestra v0.13.1 (01-nov):** (1) `ubicacion_generica`: un punto con ≥ 10 anuncios de ≥ 6 barrios
  distintos es el centroide que Fincaraíz pone a los anuncios sin ubicación; se sacan del export (eran 174: 72 caían en
  Cañaveral, 46 en Quinta Camacho). (2) Comparables cruzan segmentos: la pestaña decide qué se MUESTRA, el área ± tolerancia
  qué se COMPARA (pool COMP_U/COMP_UT con todos los usados). (3) Duplicados: mismo precio, área y alcobas a ≤ 150 m = uno.
  Resultado: La Cité y Lumina 77 tienen 2 comparables reales (s/c por el mínimo de 3); Metro 73 0 (Quinta Camacho casi
  no tiene unidades pequeñas ubicadas). El Polo manual se quitó: lo trae Estrenar (micro). Ampliar cobertura = segunda
  fuente de usados (Metrocuadrado/Ciencuadras) y probar la ruta `el-lago/zona-nororiental` para apartaestudios.
- **v0.14.0 (01-nov):** (1) Tabla de comparables: columna Precio (2.ª). (2) `config/ajustes_proyectos.toml` +
  `src/vivienda/ajustes.py`: correcciones por NOMBRE a proyectos de Estrenar (dirección en forma de cruce o lat/lng,
  `seguimiento`) y `[excluir] nombres` (marca `excluido`, no se exporta). Se aplica en `_proyectos_al_dia` antes de
  rezonificar/geocodificar. Cargados: Novus Florida (Cra 8 con Cl 10, Floridablanca: la ficha no publica dirección,
  por eso salía sin ubicar), Atelier 68 (Cra 15 con Cl 67), Nau House (Cl 85A con Cra 28C); excluido Signature Virrey
  (fuera de presupuesto). (3) IVIN Refugio corregido: estaba con las coordenadas de IVIN Lago; ahora dirección
  Transversal 5 con Calle 86A (fuera de zonas, seguimiento). Quitar lat/lng de un manual borra la ubicación manual y
  la re-geocodifica. (4) IVIN Lago agregado (Cra 16A # 79-76, micro 22–29 m²). (5) SOHO 26 (Marval, Salitre/Av. 26)
  analizado: sin precios hasta el lanzamiento (5-nov-2026); agregar como manual en seguimiento cuando haya lista.
- **v0.14.1 (01-nov):** shortlist de Estrenar agregada como manuales en seguimiento con lat/lng de las fichas:
  64 Estorias (a 260 m de chu, al oeste de la Caracas), Kobe 50 (DENTRO de teu, micro), Reserva de la 26 (La Soledad,
  ~1 km de teu) y G95 (Chicó Norte, ~490 m de nav). Nueva regla en `ajustes.aplicar`: si un manual y un proyecto de
  portal tienen el mismo nombre, manda el manual y el del portal se marca `excluido` + `duplicado_de` (evita doble pin).
  Si Estrenar usa otro nombre, agregar ese nombre a `[excluir]`. Zonas nuevas: NO se crearon (ver recomendación).
- **Instagram (pendiente, solo plan):** ver respuesta del 30-oct; camino legal = Graph API Business Discovery, no scraping.
- Street 52: cotización apto 303 $365,5 M; entrega 2028-01 INFERIDA (cuota inicial termina ~dic-2027).
- Estado de obra: Estrenar no lo publica; el tooltip muestra la fecha de entrega cuando no hay estado.
- Color de usados en el mapa: $/m² vs. mediana de su zona (verde ≤ −10 %, rojo ≥ +10 %). Grupos en gris.

## 7. Limitaciones conocidas

- Arriendo largo y ADR de renta corta por zona son **supuestos** en `web/index.html`; yields indicativos.
- Pocos comparables en Country/Lago (La Cité, Lumina 77: 2 reales → "s/c" por mínimo de 3) y Quinta Camacho
  (Metro 73: 0). Causa: una sola fuente (Fincaraíz) y pocos anuncios pequeños bien ubicados.
- Renta corta de usados siempre "desconocida" (el anuncio no lo dice).
- Claude (sandbox) no llega a estrenarvivienda.com, fincaraiz, Nominatim ni Overpass desde la shell: no puede
  geocodificar ni correr el scraper; WebFetch sí lee fichas de Estrenar y webs de constructoras.
- Mapas en artifacts de claude.ai salen grises (no cargan teselas remotas).
- `rsync` de instalación no borra archivos eliminados entre versiones.

## 8. Próximos pasos

1. **Verificar v0.14** con la salida de `vivienda nuevos && vivienda geocodificar && vivienda publicar`: que Novus
   Florida, Atelier 68, Nau House e IVIN Refugio queden ubicados; si alguno sigue "sin ubicar", pedir el pin de
   Google Maps y ponerlo como lat/lng en `ajustes_proyectos.toml` (o en el manual, para IVIN).
2. **SOHO 26** (Marval): lanzamiento 5-nov-2026. Con lista de precios, plan de pagos, reglamento (renta corta),
   fiducia y punto de equilibrio → agregarlo como manual `seguimiento = true`; considerar barrios de Salitre en
   `[fincaraiz]` para tener comparables.
3. **64 Estorias y Kobe 50**: se ofreció agregarlos en seguimiento (pendiente respuesta del usuario).
4. Segunda fuente de usados (Metrocuadrado/Ciencuadras) con dedupe entre portales; probar la ruta Fincaraíz
   `el-lago/zona-nororiental` para apartaestudios.
5. Arriendos reales (Fincaraíz `operacion="arriendo"`) → yields de mercado.
6. Instagram: ejecutar el plan solo si el usuario lo pide.

## 9. Historial de errores que no hay que repetir

- Poner comentarios `#` dentro de comandos para copiar/pegar: zsh los rompe. Comandos limpios, sin comentarios.
- Asignar coordenadas sin verificar: IVIN Refugio tuvo las de IVIN Lago (corregido v0.14); Torres del Valle tuvo un
  punto de referencia a ~950 m (corregido con el pin del usuario).
- Relajar la regla del ascensor (p. ej. "≤ 15 años"): el usuario la rechazó. Regla única: dice ascensor → sí;
  no dice → 6+ pisos se asume con ascensor; si no → descartado, como compra y como comparable.
- Comparar entre zonas distintas (Morato vs. Pasadena): solo misma zona.

- Usar opus por defecto (el usuario lo pidió explícitamente: siempre haiku).
- Sobre-diseñar la geografía (polígonos por esquinas en cada corrida): ahora es opcional y una sola vez.
- Asignar zona de usados por nombre de barrio o por el primer círculo que contenga el punto.
- Confiar en ceros de Fincaraíz como datos (pisos del edificio).
- Dejar carpetas y logs en Descargas con los comandos de instalación.
- Usar el alias `vivienda` dentro de `sh -c`, `caffeinate` o launchd: los alias de zsh no existen ahí
  (`sh: vivienda: command not found`). En scripts usar `PYTHONPATH=<proyecto>/src python3 -m vivienda ...`.
- Redirigir la salida a un archivo sin `python3 -u` (o `PYTHONUNBUFFERED=1`): Python la guarda en búfer y el log
  se ve vacío durante minutos aunque esté corriendo. En scripts y launchd usar siempre `python3 -u`.

## 10. Análisis de mercado entregados (01-nov-2026)

**SOHO 26 Distrito Urbano (Marval)** — Av. Calle 26 / Ciudad Salitre, sala de ventas Cra 66 # 23-69; lote de la
antigua Empresa de Energía (48.300 m²), ~2.000 viviendas (otras fuentes: 2.500–3.000), primera etapa 40/60/80 m²,
primera torre 2030, lanzamiento 5-nov-2026, sin precios; primer proyecto con certificados CDCD de Renobo; EDGE;
TransMilenio Salitre El Greco, RegioTram futuro, aeropuerto 15 min. Fuera de las zonas.
Veredicto: buena ubicación, negocio no evaluable aún. Riesgos: plata comprometida ~4 años, oferta masiva de
unidades iguales al entregar, renta corta incierta en conjunto grande, mecanismo CDCD sin historial. A favor:
precio de lanzamiento. Regla de decisión: su $/m² del tipo 40 m² debe ser claramente menor que 64 Estorias
(8,5 M/m², entrega 2028) y Kobe 50 (10,6 M/m²); si no, la espera extra no compensa.

**Shortlist Estrenar (fuera o al borde de zonas):**
| Proyecto | Dirección | Base | $/m² | Entrega | Nota |
|---|---|---|---|---|---|
| 64 Estorias (Accanto) | Cra 15 # 64B-11, Chapinero, E3 (4.652834,-74.065246) | 32,93 m² $280,6 M; 37,15 m² $306,9 M | 8,5 M | 1T-2028 | mejor valor; renta corta permitida; 14 pisos, 2 asc.; Fid. Davivienda |
| Kobe 50 (CSB) | Cl 50 # 19-38, Teusaquillo, E3 (4.638341,-74.07151) | 22,38 m² $238 M | 10,6 M | 2T-2028 | renta corta permitida; 5–6 pisos, 1 asc. |
| Reserva de la 26 (AR) | Cl 34 # 29-38, La Soledad, E4 (4.624891,-74.079283) | 27 m² $294 M; 30 m² $371 M | 10,9 M | 4T-2028 | 481 unidades, 24 pisos; política de renta corta no explícita |
| G95 (Gallery) | Cl 95 # 14-48, Chicó, E6 (4.68083,-74.049505) | 36,76 m² ~$522 M | 14,2 M | 4T-2026 | casi entregado; caro; precios inconsistentes en la ficha |
Descartados: 77 Estorias (Chapinero Alto, excluido), Essenza 72 (Engativá), VIS del centro (restricciones).

**Otros datos:** Novus Florida = Marval VIS, Cra 8 # 10-172 Floridablanca, 41–54 m² desde $263,976 M, 4 torres × 16
pisos. IVIN Lago: 72 % vendido, obra ~40 %, Fiduciaria Aval.
