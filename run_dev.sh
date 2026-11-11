#!/usr/bin/env bash
# Avvio in sviluppo di Forensic Tools (runtime e strumenti in ~/.ft-build, vedi BLUEPRINT.md §3)
DIR="$(cd "$(dirname "$0")" && pwd)"
export DYLD_FALLBACK_LIBRARY_PATH="$HOME/.ft-build/tools-arm64/lib:/usr/lib"
exec "$HOME/.ft-build/py-aarch64/python/bin/python3" "$DIR/main.py" "$@"
