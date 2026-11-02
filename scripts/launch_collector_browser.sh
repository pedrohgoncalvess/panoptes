#!/bin/sh
# A separate normal profile keeps collector tabs independent of personal browsing.
set -eu
project_dir=$(CDPATH= cd -- "$(dirname -- "$0")/.." && pwd)
extension_dir="$project_dir/extensions/session-bridge"
profile_dir="${XDG_DATA_HOME:-$HOME/.local/share}/panoptes-browser"
if ! command -v brave-browser >/dev/null 2>&1; then
    printf '%s\n' 'Brave não encontrado. Instale o Brave antes de abrir o coletor.' >&2
    exit 1
fi
test -f "$extension_dir/manifest.json"
mkdir -p "$profile_dir"
chmod 700 "$profile_dir"
set --
if [ -n "${WAYLAND_DISPLAY:-}" ]; then
    set -- --ozone-platform=wayland
fi
exec brave-browser "$@" --user-data-dir="$profile_dir" \
    --load-extension="$extension_dir" --no-first-run --no-default-browser-check \
    http://localhost:3001/connections \
    https://www.pichau.com.br/ https://www.terabyteshop.com.br/
