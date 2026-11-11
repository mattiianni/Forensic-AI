#!/usr/bin/env bash
set -e

# ==============================================================================
# Setup Ambiente Virtuale Universale per Forensic AI Offline (Apple Silicon & Intel)
# Compatibile al 100% con architetture arm64 (M1/M2/M3/M4) e x86_64 (Mac mini Intel 2018)
# ==============================================================================

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

ARCH=$(uname -m)
echo "=== Configurazione Ambiente Forensic AI Offline ($ARCH) ==="

# Identifica l'interprete Python 3 di sistema o Homebrew
PYTHON_CMD=""
for cmd in python3 /usr/bin/python3 /usr/local/bin/python3 /opt/homebrew/bin/python3; do
    if command -v "$cmd" &>/dev/null; then
        P_VER=$("$cmd" -c "import sys; print(f'{sys.version_info.major}.{sys.version_info.minor}')" 2>/dev/null || true)
        if [[ "$P_VER" =~ ^3\.(9|10|11|12|13) ]]; then
            PYTHON_CMD="$cmd"
            break
        fi
    fi
done

if [ -z "$PYTHON_CMD" ]; then
    echo "ERRORE: Python 3 non trovato sul sistema."
    exit 1
fi

echo "Python rilevato: $PYTHON_CMD ($ARCH)"

if [ "$ARCH" = "arm64" ]; then
    VENV_DIR="$DIR/.venv_arm64"
else
    VENV_DIR="$DIR/.venv_x86_64"
fi

# Se esiste la vecchia cartella .venv e corrisponde all'architettura corrente
if [ ! -d "$VENV_DIR" ] && [ -d "$DIR/.venv" ] && [ ! -L "$DIR/.venv" ]; then
    OLD_VENV_ARCH=$("$DIR/.venv/bin/python" -c "import platform; print(platform.machine())" 2>/dev/null || true)
    if [ "$OLD_VENV_ARCH" = "$ARCH" ]; then
        echo "Migrazione ambiente esistente in $VENV_DIR..."
        mv "$DIR/.venv" "$VENV_DIR"
    fi
fi

if [ ! -d "$VENV_DIR" ]; then
    echo "Creazione ambiente virtuale isolato in $VENV_DIR..."
    "$PYTHON_CMD" -m venv "$VENV_DIR"
fi

echo "Attivazione ambiente virtuale ($ARCH)..."
source "$VENV_DIR/bin/activate"

echo "Installazione/Verifica dipendenze da archivio locale wheels (100% offline)..."
if [ -d "$DIR/wheels" ]; then
    pip install --no-index --find-links="$DIR/wheels" -r "$DIR/requirements.txt" --quiet
else
    pip install -r "$DIR/requirements.txt"
fi

# Collega il puntatore trasparente .venv all'architettura corrente
rm -rf "$DIR/.venv"
ln -sf "$VENV_DIR" "$DIR/.venv"

echo "Verifica completata con successo per architettura $ARCH!"
