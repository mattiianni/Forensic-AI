#!/usr/bin/env bash

# ==============================================================================
# Forensic AI Offline — Avvio Automatico
# ==============================================================================

export PATH="/opt/homebrew/bin:/usr/local/bin:/Library/Frameworks/Python.framework/Versions/3.11/bin:$HOME/.local/bin:/usr/bin:/bin:$PATH"

DIR="$(cd "$(dirname "$0")" && pwd)"
cd "$DIR"

LOG_DIR="$DIR/logs"
mkdir -p "$LOG_DIR"
CURRENT_DATE=$(date +"%Y-%m-%d")
LOG_FILE="$LOG_DIR/forensic_${CURRENT_DATE}.log"

echo "[$(date '+%Y-%m-%d %H:%M:%S')] === AVVIO FORENSIC AI OFFLINE ===" >> "$LOG_FILE"

# 1. Pulisci eventuali processi orfani su porta 8501 prima di avviare
OLD_PIDS=$(lsof -ti :8501 2>/dev/null)
if [ -n "$OLD_PIDS" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Pulizia processi preesistenti su porta 8501: $OLD_PIDS" >> "$LOG_FILE"
    echo "$OLD_PIDS" | xargs kill -9 2>/dev/null
    sleep 1
fi

# 2. Controllo Archivio Modelli Offline ed Ollama Engine Universale
if [ -d "$DIR/models/manifests" ]; then
    export OLLAMA_MODELS="$DIR/models"
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Archivio modelli offline locale attivo: $DIR/models" >> "$LOG_FILE"
fi

export OLLAMA_NUM_PARALLEL=2
export OLLAMA_FLASH_ATTENTION=1

if ! pgrep -x "ollama" > /dev/null; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Avvio motore locale Ollama..." >> "$LOG_FILE"
    if [ -d "/Applications/Ollama.app" ]; then
        open -a "/Applications/Ollama.app" --hide
    elif [ -d "$DIR/lib/Ollama.app" ]; then
        open -a "$DIR/lib/Ollama.app" --hide
    elif command -v ollama &> /dev/null; then
        ollama serve > /dev/null 2>&1 &
    fi
    sleep 3
fi

# 3. Rilevamento Architettura & Ambiente Virtuale (arm64 Apple Silicon vs x86_64 Intel)
ARCH=$(uname -m)
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Architettura macchina rilevata: $ARCH" >> "$LOG_FILE"

if [ "$ARCH" = "arm64" ]; then
    VENV_TARGET="$DIR/.venv_arm64"
else
    VENV_TARGET="$DIR/.venv_x86_64"
fi

# Se esiste la vecchia .venv arm64 la preserviamo
if [ ! -d "$VENV_TARGET" ] && [ -d "$DIR/.venv" ] && [ ! -L "$DIR/.venv" ]; then
    OLD_VENV_ARCH=$("$DIR/.venv/bin/python" -c "import platform; print(platform.machine())" 2>/dev/null || true)
    if [ "$OLD_VENV_ARCH" = "$ARCH" ]; then
        mv "$DIR/.venv" "$VENV_TARGET"
    fi
fi

if [ ! -d "$VENV_TARGET" ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Preparazione ambiente virtuale offline per $ARCH..." >> "$LOG_FILE"
    bash "$DIR/setup_environment.sh" >> "$LOG_FILE" 2>&1
fi

rm -rf "$DIR/.venv"
ln -sf "$VENV_TARGET" "$DIR/.venv"

source "$VENV_TARGET/bin/activate"

PORT=8501
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Avvio server Streamlit su porta $PORT..." >> "$LOG_FILE"

# Gestore di segnali: SOLO per interruzione esplicita (Ctrl+C o kill)
cleanup() {
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Segnale ricevuto: arresto Streamlit (PID $STREAMLIT_PID)..." >> "$LOG_FILE"
    if [ -n "$STREAMLIT_PID" ]; then
        kill -TERM "$STREAMLIT_PID" 2>/dev/null
        sleep 1
        kill -9 "$STREAMLIT_PID" 2>/dev/null
    fi
    lsof -ti :8501 | xargs kill -9 2>/dev/null
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Arresto completato." >> "$LOG_FILE"
    exit 0
}
trap cleanup SIGINT SIGTERM

"$DIR/.venv/bin/streamlit" run app.py \
    --server.port=$PORT \
    --server.headless=true \
    --browser.gatherUsageStats=false \
    --theme.base="dark" >> "$LOG_FILE" 2>&1 &

STREAMLIT_PID=$!
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Streamlit avviato in background (PID $STREAMLIT_PID)" >> "$LOG_FILE"

# Attendi che il server sia raggiungibile
SERVER_READY=false
for i in {1..30}; do
    if curl -s --max-time 1 "http://localhost:$PORT" > /dev/null 2>&1; then
        SERVER_READY=true
        break
    fi
    sleep 0.5
done

if [ "$SERVER_READY" = true ]; then
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] Server pronto su http://localhost:$PORT. Apertura browser..." >> "$LOG_FILE"
    open "http://localhost:$PORT"
else
    echo "[$(date '+%Y-%m-%d %H:%M:%S')] ERRORE: Timeout avvio Streamlit!" >> "$LOG_FILE"
fi

wait "$STREAMLIT_PID"
