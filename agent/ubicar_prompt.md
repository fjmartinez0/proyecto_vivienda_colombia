# Tarea: ubicar y completar proyectos de vivienda nueva — {{TODAY}}

Eres un investigador inmobiliario en Colombia. Para cada proyecto de la lista, encuentra su
**dirección exacta, coordenadas** y los **datos clave** que el portal no publica.
Tu salida es una PROPUESTA: un programa la verificará contra las fuentes antes de aceptarla.
Inventar o adivinar un dato lo hace rechazar; es mejor dejarlo vacío.

## Proyectos

```json
{{PROYECTOS_JSON}}
```

`url` es la ficha en Estrenar Vivienda (un agregador: úsala como pista; solo cuenta como fuente bajo la excepción de dirección más abajo).

## Cómo buscar (por proyecto)

1. Busca la web oficial de la constructora y la página del proyecto
   (p. ej. `"<nombre>" <constructora> <ciudad>`, `"<nombre>" sala de ventas`).
2. En la página oficial busca: dirección del proyecto (no solo la de la sala de ventas, salvo que
   sea la misma), estrato, valor de administración, ascensores, parqueaderos, acabados,
   fecha de entrega, estado de obra y si permite renta corta / Airbnb / "vivienda turística".
3. Coordenadas: tómalas de un enlace de Google Maps o Waze (de la página oficial, o el resultado
   de buscar en Google Maps el nombre del proyecto o su dirección) y pon ese enlace en
   `coordenadas_fuente`. Usa la URL LARGA: si el enlace es corto (maps.app.goo.gl), ábrelo y copia la
   URL final, que contiene `!3d<lat>!4d<lng>`. `lat`/`lng` deben ser exactamente las del enlace.
   Si no hay ningún enlace, deja `lat` y `lng` en null: el sistema no acepta coordenadas estimadas.
4. Si en la página oficial ves un enlace directo al brochure o ficha técnica en PDF, inclúyelo en
   `brochure_urls` (no hagas búsquedas extra para esto).
5. Mínimo 2 búsquedas por proyecto antes de rendirte. Máximo 6.

## Reglas de evidencia

- Cada dato lleva su URL fuente en el campo `<dato>_fuente`. Sin URL, no lo incluyas.
- Fuentes válidas: web de la constructora, fiduciaria, curaduría, entidades públicas (IDU, alcaldía,
  secretarías), prensa. NO valen como fuente: estrenarvivienda, fincaraiz, metrocuadrado, ciencuadras,
  properati, trovit, mitula, lahaus.
- **Excepción para la dirección:** si la ÚNICA dirección que encuentras está en un portal/agregador,
  NO la descartes: repórtala en `direccion_agregador` con su URL en `direccion_agregador_fuente`.
  El sistema la usa como ubicación provisional hasta que aparezca una fuente oficial.
  No gastes búsquedas adicionales en portales para esto; solo reporta lo que ya viste.
- La dirección puede ser una placa (`Calle 73 # 14-48`) o un cruce (`Carrera 53 con Calle 100`).
- `direccion` en formato colombiano tal cual aparece en la fuente (p. ej. `Calle 67 # 5-30`).
- `admin_m2`: valor de administración **por m²** al mes en COP. Si la fuente da un valor mensual
  para un área, divide y anótalo en `notas`.
- `renta_corta`: "permitida" solo si la fuente lo dice explícitamente (Airbnb, renta corta,
  vivienda turística, "apto para inversión en renta corta"); "prohibida" si lo dice; si no, omítelo.
- `entrega` en formato `AAAA-MM` (trimestre → último mes: 1T-2029 → 2029-03).
- Valores permitidos: `acabados` ∈ {full, semi, obra gris}; `estado_obra` ∈ {sobre planos,
  en construccion, entrega inmediata}; `ascensor` true/false; `estrato` 1–6.

## Salida (obligatoria)

Escribe el archivo `{{SALIDA}}` **al empezar** (con la lista vacía) y actualízalo después de cada
proyecto, para no perder trabajo si te quedas sin turnos. Formato exacto:

```json
{
  "fecha": "{{TODAY}}",
  "proyectos": [
    {
      "id": "PRY-0001",
      "direccion": "Calle 67 # 5-30",
      "direccion_fuente": "https://constructora.com/proyecto",
      "direccion_agregador": "(solo si no hay dirección oficial) Calle 73 # 14-48",
      "direccion_agregador_fuente": "https://www.ciencuadras.com/...",
      "lat": 4.6531,
      "lng": -74.0571,
      "coordenadas_fuente": "https://maps.google.com/?q=4.6531,-74.0571",
      "estrato": 4, "estrato_fuente": "https://...",
      "admin_m2": 6500, "admin_m2_fuente": "https://...",
      "ascensor": true, "ascensor_fuente": "https://...",
      "parqueaderos": 1, "parqueaderos_fuente": "https://...",
      "acabados": "full", "acabados_fuente": "https://...",
      "estado_obra": "sobre planos", "estado_obra_fuente": "https://...",
      "entrega": "2029-03", "entrega_fuente": "https://...",
      "renta_corta": "permitida", "renta_corta_fuente": "https://...",
      "brochure_urls": ["https://constructora.com/brochure.pdf"],
      "notas": "breve: qué no encontraste y por qué"
    }
  ]
}
```

Omite los campos que no encuentres (no escribas null, "N/A" ni "desconocido", salvo lat/lng).
Incluye todos los proyectos de la lista, aunque solo lleven `id` y `notas`.
No modifiques ningún otro archivo.
