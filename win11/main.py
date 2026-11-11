"""
Forensic Tools (Windows 11 Portable) — punto di ingresso.

1. Configura gli strumenti inclusi (Tesseract, Ghostscript, Pango/GTK) e Ollama privato.
2. Avvia il server Flask locale su una porta libera (solo 127.0.0.1).
3. Apre la finestra nativa Windows 11 (Microsoft Edge WebView2) con l'interfaccia.
"""
from __future__ import annotations

import ctypes
import json
import multiprocessing
import os
import socket
import sys
import threading

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from server import runtime  # noqa: E402

runtime.setup_environment()

import webview  # noqa: E402
from webview.dom import DOMEventHandler  # noqa: E402

webview.settings["DRAG_REGION_SELECTOR"] = ".drag"
webview.settings["DRAG_REGION_DIRECT_TARGET_ONLY"] = True
webview.settings["ALLOW_DOWNLOADS"] = True

from server.app import create_app  # noqa: E402

window: webview.Window | None = None
_maximized = False


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _system_dark() -> bool:
    try:
        import winreg
        with winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize",
        ) as key:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return int(val) == 0
    except Exception:
        return False


class NativeAPI:
    """Funzioni native esposte a JavaScript come window.pywebview.api.*"""

    def choose_folder(self, title: str = "Scegli una cartella"):
        res = window.create_file_dialog(webview.FileDialog.FOLDER)
        return res[0] if res else None

    def choose_files(self, multiple: bool = True):
        res = window.create_file_dialog(webview.FileDialog.OPEN, allow_multiple=multiple)
        return list(res) if res else []

    def save_file(self, filename: str):
        res = window.create_file_dialog(webview.FileDialog.SAVE, save_filename=filename)
        if not res:
            return None
        return res if isinstance(res, str) else res[0]

    def set_title(self, title: str):
        window.title = title

    def set_appearance(self, dark: bool):
        """Allinea barra del titolo Windows 11 (DWM) al tema dell'interfaccia."""
        _apply_window_appearance(bool(dark))

    def zoom(self):
        """Doppio clic sulla toolbar: ingrandisci/ripristina."""
        global _maximized
        try:
            if _maximized:
                window.restore()
            else:
                window.maximize()
            _maximized = not _maximized
        except Exception:
            pass


def _on_drop(event):
    """Trascinamento da Esplora file: inoltra i percorsi reali all'interfaccia."""
    files = event.get("dataTransfer", {}).get("files", [])
    paths = [f.get("pywebviewFullPath") for f in files if f.get("pywebviewFullPath")]
    if paths and window:
        window.evaluate_js(f"window.FT && FT.onNativeDrop({json.dumps(paths)})")


def _hwnd_of(win) -> int | None:
    try:
        native = win.native
        if native is None:
            return None
        handle = getattr(native, "Handle", None)
        if handle is not None:
            return int(handle.ToInt64())
    except Exception:
        pass
    try:
        return int(ctypes.windll.user32.FindWindowW(None, runtime.APP_NAME)) or None
    except Exception:
        return None


def _apply_window_appearance(dark: bool):
    """Imposta DWMWA_USE_IMMERSIVE_DARK_MODE (e sfondo caption Windows 11) sull'HWND."""
    if sys.platform != "win32" or window is None:
        return
    hwnd = _hwnd_of(window)
    if not hwnd:
        return
    try:
        dwmapi = ctypes.windll.dwmapi
        val = ctypes.c_int(1 if dark else 0)
        # DWMWA_USE_IMMERSIVE_DARK_MODE: 20 su Windows 11 / 20H1+, fallback 19
        for attr in (20, 19):
            res = dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), ctypes.c_uint(attr),
                ctypes.byref(val), ctypes.sizeof(val),
            )
            if res == 0:
                break
        # DWMWA_CAPTION_COLOR = 35 (Windows 11 22H2+): COLORREF = 0x00BBGGRR
        caption_color = ctypes.c_int(0x002A2828 if dark else 0x00F8F6F6)
        dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), ctypes.c_uint(35),
            ctypes.byref(caption_color), ctypes.sizeof(caption_color),
        )
    except Exception:
        pass


def _style_native_window():
    _apply_window_appearance(_system_dark())


def _on_loaded():
    window.dom.document.events.drop += DOMEventHandler(_on_drop, True, True)


def main():
    global window
    # Il motore IA parte in background: la finestra compare subito (l'interfaccia attende i modelli da sola)
    threading.Thread(target=runtime.start_ollama, daemon=True, name="ollama").start()
    port = _free_port()
    app = create_app()
    threading.Thread(
        target=lambda: app.run(host="127.0.0.1", port=port, threaded=True, use_reloader=False),
        daemon=True,
    ).start()

    dark = _system_dark()
    window = webview.create_window(
        runtime.APP_NAME,
        f"http://127.0.0.1:{port}/",
        js_api=NativeAPI(),
        width=1440,
        height=920,
        min_size=(1100, 700),
        background_color="#1C1C1E" if dark else "#F5F5F7",
        text_select=True,
    )
    window.events.loaded += _on_loaded
    window.events.shown += _style_native_window
    try:
        webview.start(
            gui="edgechromium",
            debug=bool(os.environ.get("FT_DEBUG")),
            private_mode=False,
            storage_path=str(runtime.CACHE_DIR / "webview"),
        )
    finally:
        runtime.stop_ollama()


if __name__ == "__main__":
    multiprocessing.freeze_support()
    main()
