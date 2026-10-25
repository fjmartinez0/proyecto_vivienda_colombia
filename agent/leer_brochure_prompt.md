Extrae datos del texto de un brochure de un proyecto de vivienda en Colombia.

Proyecto: {{NOMBRE}} ({{ID}})
Tipologías conocidas (área construida según el portal): {{TIPOLOGIAS}}

Reglas:
- Usa SOLO el texto de abajo. No inventes ni calcules: cada número debe aparecer tal cual en el texto.
- `areas`: pares de área privada y área construida de la misma tipología (m²).
  Si el texto da solo una de las dos para una tipología, no la incluyas.
- `admin_m2`: solo si el texto da un valor por m². `ascensor`: true solo si el texto lo menciona.
- `acabados` ∈ {full, semi, obra gris}. `entrega` en formato AAAA-MM.
- Omite lo que no esté en el texto.

Responde ÚNICAMENTE con un objeto JSON, sin texto antes ni después:
{"areas": [{"privada": 39.1, "construida": 44.02}], "estrato": 4, "admin_m2": 7200,
 "ascensor": true, "acabados": "full", "entrega": "2028-12", "direccion": "Calle 67 # 11-86"}

--- TEXTO DEL BROCHURE ---
{{TEXTO}}
--- FIN ---
