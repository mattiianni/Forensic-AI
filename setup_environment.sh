#!/usr/bin/env bash
set -e

# ==============================================================================
# Setup Ambiente Virtuale per Forensic AI Offline (macOS Universal / arm64)
# ==============================================================================

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

echo "=== Configurazione Ambiente Forensic AI Offline ==="

# Verifica presenza di Python 3
if ! command -v python3 &> /dev/null; then
    echo "ERRORE: Python 3 non trovato. Installa Python da python.org o con Homebrew."
    exit 1
fi

PYTHON_ARCH=$(python3 -c "import platform; print(platform.machine())")
echo "Architettura Python rilevata: $PYTHON_ARCH"

if [ ! -d ".venv" ]; then
    echo "Creazione ambiente virtuale isolato in .venv..."
    python3 -m venv .venv
fi

echo "Attivazione ambiente virtuale..."
source .venv/bin/activate

echo "Aggiornamento pip..."
pip install --upgrade pip --quiet

echo "Installazione dipendenze da requirements.txt..."
pip install -r requirements.txt

echo "Verifica installazione completata con successo!"
