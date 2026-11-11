"""
Runtime di Forensic Tools: percorsi, strumenti inclusi (Tesseract, Ghostscript,
pango), motore Ollama privato e scelta automatica del modello.

Layout dentro il bundle:
    Forensic Tools.app/Contents/Resources/
        app/                      ← questo codice
        runtime/<arch>/python/    ← Python portatile
        runtime/<arch>/tools/     ← bin/ lib/ share/ (tesseract, gs, pango)
        ollama/                   ← binario ollama universale + librerie
        models/                   ← modelli Ollama
In sviluppo i percorsi ripiegano sul repository e su ~/.ft-build.
"""
from __future__ import annotations

import atexit
import glob
import os
import platform
import shutil
import socket
import subprocess
import sys
import time
from pathlib import Path

APP_NAME = "Forensic Tools"
APP_DIR = Path(__file__).resolve().parent.parent          # .../app  (o il repository)
ARCH = platform.machine()                                   # arm64 | x86_64

_bundle_res = APP_DIR.parent if APP_DIR.name == "app" else None
IS_BUNDLED = bool(_bundle_res and (_bundle_res / "runtime").is_dir())
RES_DIR = _bundle_res if IS_BUNDLED else APP_DIR

DATA_DIR = Path.home() / "Library" / "Application Support" / APP_NAME
CACHE_DIR = Path.home() / "Library" / "Caches" / APP_NAME
LOG_DIR = Path.home() / "Library" / "Logs" / APP_NAME
for _d in (DATA_DIR, CACHE_DIR, LOG_DIR):
    _d.mkdir(parents=True, exist_ok=True)

OLLAMA_PORT = 11439                     # porta privata: non interferisce con un Ollama di sistema
OLLAMA_HOST = f"127.0.0.1:{OLLAMA_PORT}"

EMBED_MODEL = "embeddinggemma"


# ── Strumenti inclusi ─────────────────────────────────────────────────────────

def tools_dir() -> Path | None:
    if IS_BUNDLED:
        p = RES_DIR / "runtime" / ARCH / "tools"
        return p if p.is_dir() else None
    dev = Path.home() / ".ft-build" / ("tools-arm64" if ARCH == "arm64" else "tools-x86_64")
    if dev.is_dir():
        return dev
    brew = Path.home() / ".ft-build" / ("brew-arm64" if ARCH == "arm64" else "brew-x86")
    return brew if brew.is_dir() else None


def ollama_bin() -> Path | None:
    candidates = [
        RES_DIR / "ollama" / "ollama",
        APP_DIR / "lib" / "Ollama.app" / "Contents" / "Resources" / "ollama",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def models_dir() -> Path:
    return RES_DIR / "models"


def _write_fontconfig(tools: Path) -> Path:
    conf_dir = CACHE_DIR / "fontconfig"
    conf_dir.mkdir(parents=True, exist_ok=True)
    conf = conf_dir / "fonts.conf"
    conf.write_text(f"""<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>/System/Library/Fonts</dir>
  <dir>/System/Library/Fonts/Supplemental</dir>
  <dir>/Library/Fonts</dir>
  <dir>~/Library/Fonts</dir>
  <cachedir>{conf_dir}/cache</cachedir>
  <match target="pattern"><test qual="any" name="family"><string>sans-serif</string></test>
    <edit name="family" mode="prepend" binding="strong"><string>Helvetica Neue</string></edit></match>
  <match target="pattern"><test qual="any" name="family"><string>serif</string></test>
    <edit name="family" mode="prepend" binding="strong"><string>Times New Roman</string></edit></match>
  <match target="pattern"><test qual="any" name="family"><string>monospace</string></test>
    <edit name="family" mode="prepend" binding="strong"><string>Menlo</string></edit></match>
</fontconfig>
""", encoding="utf-8")
    return conf


def setup_environment() -> dict:
    """Configura PATH e variabili per tesseract, ghostscript, pango, ollama."""
    info = {"tools": None}
    tools = tools_dir()
    if tools:
        info["tools"] = str(tools)
        os.environ["PATH"] = f"{tools / 'bin'}:{os.environ.get('PATH', '/usr/bin:/bin:/usr/sbin:/sbin')}"
        tessdata = tools / "share" / "tessdata"
        if tessdata.is_dir():
            os.environ["TESSDATA_PREFIX"] = str(tessdata)
        gs_res = sorted(glob.glob(str(tools / "share" / "ghostscript" / "*" / "Resource")))
        if gs_res:
            base = Path(gs_res[-1])
            gs_lib = [base / "Init", base.parent / "lib", base / "Font", tools / "share" / "ghostscript" / "fonts"]
            os.environ["GS_LIB"] = ":".join(str(p) for p in gs_lib if p.exists())
        os.environ["FONTCONFIG_FILE"] = str(_write_fontconfig(tools))
        lib = tools / "lib"
        fallback = os.environ.get("DYLD_FALLBACK_LIBRARY_PATH", "")
        if str(lib) not in fallback:
            os.environ["DYLD_FALLBACK_LIBRARY_PATH"] = f"{lib}:{fallback}" if fallback else f"{lib}:/usr/lib"
    os.environ["OLLAMA_HOST"] = OLLAMA_HOST
    return info


# ── Hardware e modelli ────────────────────────────────────────────────────────

def ram_gb() -> float:
    try:
        out = subprocess.run(["sysctl", "-n", "hw.memsize"], capture_output=True, text=True, timeout=3).stdout
        return int(out.strip()) / (1024 ** 3)
    except Exception:
        return 16.0


def cpu_name() -> str:
    try:
        return subprocess.run(["sysctl", "-n", "machdep.cpu.brand_string"],
                              capture_output=True, text=True, timeout=3).stdout.strip()
    except Exception:
        return ARCH


MODEL_CATALOG = [
    # id, etichetta, descrizione, RAM minima consigliata (GB)
    {"id": "qwen2.5:14b", "label": "Qwen 2.5 14B", "desc": "Massima qualità · consigliato", "min_ram": 15},
    {"id": "qwen2.5:7b", "label": "Qwen 2.5 7B", "desc": "Più rapido · meno preciso", "min_ram": 8},
    {"id": "llama3.2:3b", "label": "Llama 3.2 3B", "desc": "Rapido · leggero", "min_ram": 0},
]


def recommended_model(installed: list[str]) -> str:
    ram = ram_gb()
    for m in MODEL_CATALOG:
        if ram >= m["min_ram"] and m["id"] in installed:
            return m["id"]
    chat = [n for n in installed if "embed" not in n]
    return chat[0] if chat else "qwen2.5:7b"


def context_budget(model: str) -> int:
    """num_ctx prudente per evitare swap: dipende da RAM e dimensione del modello."""
    ram = ram_gb()
    if "14b" in model:
        return 8192 if ram < 30 else 16384
    if "7b" in model:
        return 8192 if ram < 14 else 12288
    return 8192


def cpu_threads() -> int | None:
    """Lasciamo decidere a Ollama, tranne su Intel dove conviene usare i core fisici."""
    if ARCH == "arm64":
        return None
    try:
        out = subprocess.run(["sysctl", "-n", "hw.physicalcpu"], capture_output=True, text=True, timeout=3).stdout
        return int(out.strip())
    except Exception:
        return None


# ── Motore Ollama privato ─────────────────────────────────────────────────────

_ollama_proc: subprocess.Popen | None = None


def _port_open(port: int) -> bool:
    with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as s:
        s.settimeout(0.3)
        return s.connect_ex(("127.0.0.1", port)) == 0


def start_ollama(log=print) -> bool:
    global _ollama_proc
    if _port_open(OLLAMA_PORT):
        return True
    binary = ollama_bin()
    if not binary:
        log("Motore Ollama non trovato nel pacchetto")
        return False
    env = os.environ.copy()
    env.update({
        "OLLAMA_HOST": OLLAMA_HOST,
        "OLLAMA_MODELS": str(models_dir()),
        "OLLAMA_NUM_PARALLEL": "1",
        "OLLAMA_MAX_LOADED_MODELS": "2",
        "OLLAMA_FLASH_ATTENTION": "1",
        "OLLAMA_KV_CACHE_TYPE": "q8_0",
        "OLLAMA_KEEP_ALIVE": "15m",
        "OLLAMA_NOPRUNE": "1",
        "OLLAMA_NO_CLOUD": "1",          # nessuna funzione cloud: tutto resta sul Mac
    })
    logf = open(LOG_DIR / "ollama.log", "ab")
    _ollama_proc = subprocess.Popen([str(binary), "serve"], env=env, stdout=logf, stderr=logf,
                                    start_new_session=True)
    atexit.register(stop_ollama)
    for _ in range(80):
        if _port_open(OLLAMA_PORT):
            return True
        time.sleep(0.25)
    log("Ollama non ha risposto entro 20 secondi")
    return False


def stop_ollama():
    global _ollama_proc
    if _ollama_proc and _ollama_proc.poll() is None:
        _ollama_proc.terminate()
        try:
            _ollama_proc.wait(timeout=5)
        except Exception:
            _ollama_proc.kill()
    _ollama_proc = None


def installed_models() -> list[str]:
    try:
        import ollama
        resp = ollama.Client(host=f"http://{OLLAMA_HOST}").list()
        models = getattr(resp, "models", None) or resp.get("models", [])
        names = []
        for m in models:
            n = getattr(m, "model", None) or (m.get("model") if isinstance(m, dict) else None) \
                or (m.get("name") if isinstance(m, dict) else None)
            if n:
                names.append(n.replace(":latest", ""))
        return names
    except Exception:
        return []


def client():
    import ollama
    return ollama.Client(host=f"http://{OLLAMA_HOST}")


def system_status() -> dict:
    tools = tools_dir()
    def has(binname):
        return bool(shutil.which(binname))
    ita = False
    if has("tesseract"):
        try:
            out = subprocess.run(["tesseract", "--list-langs"], capture_output=True, text=True, timeout=10)
            ita = "ita" in (out.stdout + out.stderr).split()
        except Exception:
            pass
    try:
        import weasyprint  # noqa: F401
        pango = True
    except Exception:
        pango = False
    models = installed_models()
    return {
        "arch": ARCH,
        "cpu": cpu_name(),
        "ram_gb": round(ram_gb()),
        "bundled": IS_BUNDLED,
        "tools_dir": str(tools) if tools else None,
        "tesseract": has("tesseract"),
        "tesseract_italian": ita,
        "ghostscript": has("gs"),
        "pango": pango,
        "ollama": _port_open(OLLAMA_PORT),
        "models": models,
        "embed_model": EMBED_MODEL if any(m.startswith(EMBED_MODEL) for m in models) else None,
        "recommended_model": recommended_model(models),
    }
