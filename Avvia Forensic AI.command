#!/usr/bin/env bash

# ==============================================================================
# Forensic AI Offline — Avvio Diretto Terminale (Universale Apple Silicon & Intel)
# ==============================================================================

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

ARCH=$(uname -m)
echo "=================================================="
echo "    Forensic AI Offline — Sistema Forense AI"
echo "    Architettura rilevata: $ARCH"
echo "=================================================="
echo "Avvio server in corso... Premi Ctrl+C per arrestare."
echo ""

exec /bin/bash "$DIR/start.sh"
