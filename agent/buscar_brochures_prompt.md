# Tarea: encontrar el brochure (PDF) de proyectos de vivienda — {{TODAY}}

Para cada proyecto, encuentra la URL **directa** de su brochure o ficha técnica en PDF.
Un programa descargará y leerá los PDF; tú solo encuentras los enlaces.

## Proyectos

```json
{{PROYECTOS_JSON}}
```

## Cómo buscar

1. Página oficial del proyecto en la web de la constructora; busca enlaces "Descargar brochure",
   "Ficha técnica", "Brochure", "Catálogo", "Especificaciones", o cualquier `.pdf`.
2. Búsqueda web: `"<nombre>" <constructora> brochure pdf`, `"<nombre>" filetype:pdf`.
3. Máximo 4 búsquedas por proyecto. Si el PDF solo se entrega llenando un formulario
   (nombre/correo/teléfono), NO lo llenes: anótalo en `notas`.

## Reglas

- La URL debe abrir directamente un PDF (normalmente termina en `.pdf`).
- Puede estar en el sitio de la constructora, en un CDN (wp-content, amazonaws, cloudfront)
  o en un portal; da igual el sitio, lo que importa es que sea el PDF del proyecto.
- No inventes URLs. Si no encuentras ninguna, deja la lista vacía.

## Salida (obligatoria)

Escribe `{{SALIDA}}` al empezar y actualízalo después de cada proyecto:

```json
{
  "fecha": "{{TODAY}}",
  "proyectos": [
    {"id": "PRY-0001", "brochure_urls": ["https://constructora.com/wp-content/uploads/brochure.pdf"],
     "notas": "breve"}
  ]
}
```

No modifiques ningún otro archivo.
