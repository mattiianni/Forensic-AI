# Forensic Tools — Windows 11 Portable

Versione autonoma e **100% offline** di **Forensic Tools** progettata specificamente per **Windows 11 (x64)** in formato **portable** (nessun installer, nessuna chiave di registro, eseguibile da cartella o chiavetta/SSD esterno).

---

## Struttura del pacchetto portable

```text
Forensic Tools Portable\
├── Forensic Tools.exe        ← Launcher Win32 GUI (nessuna finestra console)
├── app\                      ← Applicazione (main.py, server/, core/, forensic/, ui/)
├── runtime\
│   ├── python\               ← Python 3.11 x64 portatile + librerie
│   └── tools\                ← Tesseract (ita/eng best), Ghostscript (gswin64c), DLL Pango/Cairo
├── ollama\                   ← ollama.exe + runtime CPU/CUDA/Vulkan Windows x64
├── models\                   ← Modelli locali (qwen2.5:14b, qwen2.5:7b, llama3.2:3b, embeddinggemma)
└── data\                     ← Fascicoli, indice SQLite, cache WebView2, log (creata localmente)
```

---

## Adattamenti specifici per Windows 11 Portable

- **Dati portatili**: `fascicoli/`, `stato_app.json`, `cache/` e `logs/` risiedono in `data\` accanto a `Forensic Tools.exe` (ripiega su `%LOCALAPPDATA%\Forensic Tools` solo se la cartella è in sola lettura).
- **Finestra nativa**: `pywebview` su **Microsoft Edge WebView2** (integrato in Windows 11) con tema barra del titolo sincronizzato tramite `dwmapi.DwmSetWindowAttribute`.
- **Hardware e Ollama**: rilevamento RAM/CPU via Win32 (`GlobalMemoryStatusEx` / registro Windows), avvio silenzioso di `ollama.exe serve` sulla porta privata `11439` (`CREATE_NO_WINDOW`).
- **Motore PDF / OCR / Conversioni**:
  - `ocrmypdf` con `tesseract.exe` + `tessdata_best` (`ita`, `eng`, `osd`) e `multiprocessing.freeze_support()` (`spawn` Windows).
  - `gswin64c.exe` per ottimizzazione/compressione Ghostscript.
  - `weasyprint` con `os.add_dll_directory` + `WEASYPRINT_DLL_DIRECTORIES` e `fontconfig` puntato su `C:\Windows\Fonts`.
  - `fpdf2` con font Unicode `C:\Windows\Fonts\arial.ttf`.
  - Nessun uso di `os.symlink` (usa `os.link` / `shutil.copy2` per evitare errori di privilegi Windows).
  - Apertura file ed Esplora file tramite `os.startfile` e `explorer /select,<path>`.
- **Scorciatoie**: `Ctrl+1`, `Ctrl+2`, `Ctrl+3` (cambio area), `Ctrl+Maiusc+S` (sidebar), `Ctrl+O` (aggiungi file), `Esc` (chiudi modali).

---

## Come assemblare il pacchetto su Windows 11

Su un PC **Windows 11 x64** con connessione internet (solo per il build):

```powershell
cd win11
powershell -ExecutionPolicy Bypass -File .\build\build_portable.ps1 -Zip
```

Opzioni utili dello script:
- `-Zip`: crea anche `dist_win11\Forensic_Tools_Win11_Portable.zip`.
- `-PullModels`: scarica i 4 modelli Ollama direttamente se non copi la cartella `models\` dal repository principale.
- `-SkipModels`: genera il pacchetto leggero senza i 15 GB di modelli (utile se vuoi copiare `models\` manualmente in un secondo momento).
- `-PrepareDevOnly`: prepara solo l'ambiente di sviluppo in `%USERPROFILE%\.ft-build-win` (per poi avviare con `.\run_dev.ps1`).

> **Nota sui modelli**: i ~15 GB già presenti nella cartella `models\` del repository macOS sono **identici** e compatibili al 100% con Ollama Windows: puoi copiarli direttamente in `Forensic Tools Portable\models\`.

---

## Requisiti del PC di destinazione

- **Windows 11 (x64)** (WebView2 già incluso nel sistema).
- **RAM**: consigliati ≥ 16 GB (`qwen2.5:7b` automatico); con ≥ 30 GB usa `qwen2.5:14b`; con meno RAM usa `llama3.2:3b`.
- **Spazio su disco / SSD esterno**: ~17 GB con tutti i modelli inclusi.
- **GPU (opzionale)**: se presente una GPU NVIDIA (CUDA) o compatibile Vulkan, `ollama.exe` la sfrutta automaticamente in locale.
