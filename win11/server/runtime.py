"""
Runtime di Forensic Tools (Windows 11 Portable): percorsi portatili, strumenti
inclusi (Tesseract, Ghostscript, GTK/Pango), motore Ollama privato e scelta
automatica del modello.

Layout del pacchetto portable:
    Forensic Tools Portable\\
        Forensic Tools.exe        <- launcher Win32 GUI
        app\\                      <- questo codice (main.py, server/, core/, forensic/, ui/)
        runtime\\
            python\\               <- Python 3.11 x64 standalone
            tools\\                <- bin/ (tesseract.exe, gswin64c.exe, DLL Pango/Cairo), share/
        ollama\\                   <- ollama.exe + lib/ollama/
        models\\                   <- modelli Ollama (blobs/ + manifests/)
        data\\                     <- fascicoli/, stato_app.json, cache/, logs/ (modalita portable)

In sviluppo i percorsi ripiegano sul repository e su %USERPROFILE%\\.ft-build-win.
"""
from __future__ import annotations

import atexit
import ctypes
import glob
import os
import platform
import shutil
import socket
import subprocess
import time
from pathlib import Path

APP_NAME = "Forensic Tools"
APP_DIR = Path(__file__).resolve().parent.parent          # .../app (o la cartella win11)
ARCH = platform.machine() or "AMD64"

_bundle_root = APP_DIR.parent if APP_DIR.name == "app" else None
IS_BUNDLED = bool(_bundle_root and (_bundle_root / "runtime").is_dir())
RES_DIR = Path(os.environ["FT_PORTABLE_ROOT"]) if os.environ.get("FT_PORTABLE_ROOT") else (
    _bundle_root if IS_BUNDLED else APP_DIR
)

_CREATE_NO_WINDOW = getattr(subprocess, "CREATE_NO_WINDOW", 0x08000000)


def _is_writable_dir(path: Path) -> bool:
    try:
        path.mkdir(parents=True, exist_ok=True)
        probe = path / ".ft_write_test"
        probe.write_text("ok", encoding="utf-8")
        probe.unlink()
        return True
    except Exception:
        return False


def _resolve_portable_dirs() -> tuple[Path, Path, Path]:
    """
    In modalita portable conserva tutto accanto all'eseguibile in <ROOT>\\data\\.
    Se la cartella dell'app non e scrivibile (es. Program Files / supporto sola lettura),
    ripiega su %LOCALAPPDATA%\\Forensic Tools\\.
    """
    override = os.environ.get("FT_DATA_DIR")
    if override:
        base = Path(override)
    elif IS_BUNDLED:
        candidate = RES_DIR / "data"
        if _is_writable_dir(candidate):
            base = candidate
        else:
            local = Path(os.environ.get("LOCALAPPDATA") or (Path.home() / "AppData" / "Local"))
            base = local / APP_NAME
    else:
        base = APP_DIR / "data"

    data_dir = base
    cache_dir = base / "cache"
    log_dir = base / "logs"
    for d in (data_dir, cache_dir, log_dir):
        d.mkdir(parents=True, exist_ok=True)
    return data_dir, cache_dir, log_dir


DATA_DIR, CACHE_DIR, LOG_DIR = _resolve_portable_dirs()

OLLAMA_PORT = 11439                     # porta privata: non interferisce con un Ollama di sistema
OLLAMA_HOST = f"127.0.0.1:{OLLAMA_PORT}"

EMBED_MODEL = "embeddinggemma"

_dll_handles: list = []


# ── Strumenti inclusi ─────────────────────────────────────────────────────────

def tools_dir() -> Path | None:
    if IS_BUNDLED:
        p = RES_DIR / "runtime" / "tools"
        return p if p.is_dir() else None
    dev = Path.home() / ".ft-build-win" / "tools-win64"
    if dev.is_dir():
        return dev
    local = APP_DIR / "runtime" / "tools"
    return local if local.is_dir() else None


def ollama_bin() -> Path | None:
    candidates = [
        RES_DIR / "ollama" / "ollama.exe",
        APP_DIR / "ollama" / "ollama.exe",
        APP_DIR.parent / "ollama" / "ollama.exe",
    ]
    for c in candidates:
        if c.is_file():
            return c
    return None


def models_dir() -> Path:
    for c in (RES_DIR / "models", APP_DIR / "models", APP_DIR.parent / "models"):
        if c.is_dir():
            return c
    return RES_DIR / "models"


def _write_fontconfig(tools: Path) -> Path:
    conf_dir = CACHE_DIR / "fontconfig"
    conf_dir.mkdir(parents=True, exist_ok=True)
    conf = conf_dir / "fonts.conf"
    win_dir = Path(os.environ.get("WINDIR", r"C:\Windows"))
    win_fonts = (win_dir / "Fonts").as_posix()
    local_fonts = (Path(os.environ.get("LOCALAPPDATA", Path.home() / "AppData" / "Local"))
                   / "Microsoft" / "Windows" / "Fonts").as_posix()
    cache_posix = (conf_dir / "cache").as_posix()

    conf.write_text(f"""<?xml version="1.0"?>
<!DOCTYPE fontconfig SYSTEM "fonts.dtd">
<fontconfig>
  <dir>{win_fonts}</dir>
  <dir>{local_fonts}</dir>
  <cachedir>{cache_posix}</cachedir>
  <match target="pattern"><test qual="any" name="family"><string>sans-serif</string></test>
    <edit name="family" mode="prepend" binding="strong"><string>Segoe UI</string></edit></match>
  <match target="pattern"><test qual="any" name="family"><string>serif</string></test>
    <edit name="family" mode="prepend" binding="strong"><string>Times New Roman</string></edit></match>
  <match target="pattern"><test qual="any" name="family"><string>monospace</string></test>
    <edit name="family" mode="prepend" binding="strong"><string>Consolas</string></edit></match>
</fontconfig>
""", encoding="utf-8")
    return conf


def setup_environment() -> dict:
    """Configura PATH, DLL directory, Fontconfig, Tesseract, Ghostscript e Ollama."""
    info = {"tools": None}
    tools = tools_dir()
    if tools:
        info["tools"] = str(tools)
        bin_dir = tools / "bin"
        lib_bin_dir = tools / "Library" / "bin"

        path_entries = [str(p) for p in (bin_dir, lib_bin_dir) if p.is_dir()]
        cur_path = os.environ.get("PATH", "")
        if path_entries:
            os.environ["PATH"] = os.pathsep.join(path_entries + ([cur_path] if cur_path else []))

        # Python 3.8+ su Windows richiede os.add_dll_directory per ctypes/cffi (WeasyPrint/Pango)
        if hasattr(os, "add_dll_directory"):
            for d in (bin_dir, lib_bin_dir):
                if d.is_dir():
                    try:
                        _dll_handles.append(os.add_dll_directory(str(d)))
                    except Exception:
                        pass

        if bin_dir.is_dir():
            os.environ["WEASYPRINT_DLL_DIRECTORIES"] = str(bin_dir)
        elif lib_bin_dir.is_dir():
            os.environ["WEASYPRINT_DLL_DIRECTORIES"] = str(lib_bin_dir)

        tessdata = tools / "share" / "tessdata"
        if not tessdata.is_dir():
            tessdata = tools / "Library" / "share" / "tessdata"
        if tessdata.is_dir():
            os.environ["TESSDATA_PREFIX"] = str(tessdata)

        gs_res = sorted(glob.glob(str(tools / "share" / "ghostscript" / "*" / "Resource")))
        if not gs_res:
            gs_res = sorted(glob.glob(str(tools / "Library" / "share" / "ghostscript" / "*" / "Resource")))
        if gs_res:
            base = Path(gs_res[-1])
            gs_lib = [
                base / "Init",
                base.parent / "lib",
                base / "Font",
                base.parent.parent / "fonts",
            ]
            os.environ["GS_LIB"] = os.pathsep.join(str(p) for p in gs_lib if p.exists())

        os.environ["FONTCONFIG_FILE"] = str(_write_fontconfig(tools))

    os.environ["OLLAMA_HOST"] = OLLAMA_HOST
    return info


# ── Hardware e modelli ────────────────────────────────────────────────────────

class _MEMORYSTATUSEX(ctypes.Structure):
    _fields_ = [
        ("dwLength", ctypes.c_ulong),
        ("dwMemoryLoad", ctypes.c_ulong),
        ("ullTotalPhys", ctypes.c_ulonglong),
        ("ullAvailPhys", ctypes.c_ulonglong),
        ("ullTotalPageFile", ctypes.c_ulonglong),
        ("ullAvailPageFile", ctypes.c_ulonglong),
        ("ullTotalVirtual", ctypes.c_ulonglong),
        ("ullAvailVirtual", ctypes.c_ulonglong),
        ("ullAvailExtendedVirtual", ctypes.c_ulonglong),
    ]


def ram_gb() -> float:
    try:
        stat = _MEMORYSTATUSEX()
        stat.dwLength = ctypes.sizeof(_MEMORYSTATUSEX)
        if ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(stat)):
            return stat.ullTotalPhys / (1024 ** 3)
    except Exception:
        pass
    try:
        import psutil
        return psutil.virtual_memory().total / (1024 ** 3)
    except Exception:
        return 16.0


def cpu_name() -> str:
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_LOCAL_MACHINE,
            r"HARDWARE\DESCRIPTION\System\CentralProcessor\0",
        ) as key:
            val, _ = winreg.QueryValueEx(key, "ProcessorNameString")
            if val:
                return " ".join(str(val).split())
    except Exception:
        pass
    return platform.processor() or ARCH


MODEL_CATALOG = [
    # id, etichetta, descrizione, RAM minima consigliata (GB)
    {"id": "qwen2.5:14b", "label": "Qwen 2.5 14B", "desc": "Massima qualità · lento", "min_ram": 30},
    {"id": "qwen2.5:7b", "label": "Qwen 2.5 7B", "desc": "Bilanciato · consigliato", "min_ram": 12},
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
    """num_ctx prudente per evitare paging eccessivo: dipende da RAM e dimensione modello."""
    ram = ram_gb()
    if "14b" in model:
        return 8192 if ram < 30 else 16384
    if "7b" in model:
        return 8192 if ram < 14 else 12288
    return 8192


def cpu_threads() -> int | None:
    try:
        import psutil
        phys = psutil.cpu_count(logical=False)
        if phys and phys > 0:
            return phys
    except Exception:
        pass
    n = os.cpu_count()
    return max(2, n // 2) if n and n >= 4 else None


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
        log("Motore Ollama (ollama.exe) non trovato nel pacchetto portable")
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
        "OLLAMA_NO_CLOUD": "1",          # nessuna funzione cloud: tutto resta in locale
    })
    logf = open(LOG_DIR / "ollama.log", "ab")
    _ollama_proc = subprocess.Popen(
        [str(binary), "serve"],
        env=env,
        cwd=str(binary.parent),
        stdout=logf,
        stderr=logf,
        creationflags=_CREATE_NO_WINDOW,
    )
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

    def has(*binnames):
        return any(shutil.which(b) for b in binnames)

    ita = False
    if has("tesseract"):
        try:
            out = subprocess.run(
                ["tesseract", "--list-langs"],
                capture_output=True, text=True, timeout=10,
                creationflags=_CREATE_NO_WINDOW,
            )
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
        "portable_data": str(DATA_DIR),
        "tools_dir": str(tools) if tools else None,
        "tesseract": has("tesseract"),
        "tesseract_italian": ita,
        "ghostscript": has("gswin64c", "gswin32c", "gs"),
        "pango": pango,
        "ollama": _port_open(OLLAMA_PORT),
        "models": models,
        "embed_model": EMBED_MODEL if any(m.startswith(EMBED_MODEL) for m in models) else None,
        "recommended_model": recommended_model(models),
    }
