#!/usr/bin/env bash

# ==============================================================================
# Forensic AI Offline — Avvio Diretto Terminale
# ==============================================================================

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "=================================================="
echo "    Forensic AI Offline — Sistema Forense AI"
echo "=================================================="
echo "Avvio server in corso... Premi Ctrl+C per arrestare."
echo ""

bash "$DIR/start.sh"
