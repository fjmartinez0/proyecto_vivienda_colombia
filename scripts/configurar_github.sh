#!/bin/sh
# Primera publicación en github.com/fjmartinez0/proyecto_vivienda_colombia (una sola vez).
set -e
P="$(cd "$(dirname "$0")/.." && pwd)"
REPO="https://github.com/fjmartinez0/proyecto_vivienda_colombia.git"
cd "$P"
[ -d .git ] || git init -q -b main
git remote get-url origin >/dev/null 2>&1 || git remote add origin "$REPO"
# Freno de seguridad: nada privado puede quedar listo para subir
if git add -A -n | grep -E "'(data|logs)/|'proposals/[^.]|ntfy_tema|fixtures/.+\.html|\.run/" ; then
  echo "✗ Eso no debería publicarse: revisa .gitignore antes de seguir."; exit 1
fi
PYTHONPATH="$P/src" python3 -u -m vivienda publicar
if command -v gh >/dev/null 2>&1; then
  gh api -X POST repos/fjmartinez0/proyecto_vivienda_colombia/pages \
     -f "source[branch]=main" -f "source[path]=/docs" >/dev/null 2>&1 \
     && echo "GitHub Pages activado (main /docs)." \
     || echo "Pages: ya estaba activo o hay que activarlo a mano (abajo)."
fi
echo "Si Pages no está activo: GitHub → repo → Settings → Pages → Branch: main, carpeta /docs → Save."
echo "Dashboard: https://fjmartinez0.github.io/proyecto_vivienda_colombia/web/"
