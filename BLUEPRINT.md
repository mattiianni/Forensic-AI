# Forensic Tools — Blueprint di ricostruzione

> Documento destinato a un agente IA (o a uno sviluppatore) che debba **ricostruire l'app da zero** o
> **completarla**. Contiene requisiti, decisioni già prese con l'utente, architettura, contratti di ogni
> modulo, API, formati su disco, procedura di build, specifiche grafiche, insidie già scoperte e stato
> di avanzamento. Dove il codice esiste, questo documento ne descrive il contratto: il codice resta la
> fonte di verità per i dettagli.
>
> Lingua dell'interfaccia e dei messaggi: **italiano**. Ultimo aggiornamento: 2026-11-11.

---

## 1. Cosa è l'app

**Forensic Tools** è un'app macOS **nativa, standalone e 100% offline** per professionisti forensi
(CTU, periti, investigatori AML). In alto ha **tre grandi tab** (macro-aree), scelte dall'utente:

| # | Area | Scopo | Usa IA |
|---|------|-------|--------|
| 1 | **PDF** | Replica al 100% l'app *Pdf50* (github.com/mattiianni/Pdf50): carica cartelle/file → converte in PDF → OCR italiano → unisce → divide oltre 50 MB; post-elaborazione: comprimi, dividi per dimensione o per range, estrai testo. | No |
| 2 | **Ricerca** | Campo di testo stile chat (come i grandi LLM). Risponde **solo** cercando nei documenti caricati e **nient'altro**: risposte testuali precise, ricavate incrociando i documenti. **Nessuna** analisi, deduzione, ipotesi o commento. **Ogni dato riporta “File ___, pagina ___”.** Se il dato non c'è, lo dice. | Sì (modello locale + embedding) |
| 3 | **Forensic AI** | L'app esistente: estrazione entità/relazioni con LLM, grafo (link analysis), chat ibrida con cammini minimi, dossier CTU in 7 capitoli, pattern AML, UBO FollowTheMoney, riconciliazione finanziaria DuckDB, timeline, anagrafiche, console SQL, export. | Sì |

Le tre aree condividono **un unico “fascicolo”** di documenti (caricati una volta, disponibili ovunque),
salvato su disco e riapribile.

### 1.1 Decisioni vincolanti prese con l'utente

1. **Architettura**: finestra macOS nativa (pywebview → WKWebView) + interfaccia HTML/CSS/JS scritta a mano
   secondo le **Apple Human Interface Guidelines** + backend Python (Flask su 127.0.0.1). Niente Streamlit,
   niente browser esterno, niente SwiftUI.
2. **Icone**: **solo Material Symbols** (Rounded), font incluso localmente. **Vietate emoji** e icone “vecchie”
   ovunque nell'interfaccia (anche nei messaggi mostrati all'utente: il backend ripulisce le emoji
   prodotte dai motori esistenti).
3. **Coerenza grafica** totale fra le tre aree (stesso design system).
4. **Solo Apple Silicon (arm64)**. L'utente ha **abbandonato completamente Intel**: non aggiungere supporto x86_64.
5. **Tutto incluso nell'app**: Python, librerie, Ollama, modelli IA, **Tesseract con italiano**, **Ghostscript**,
   **pango** (per weasyprint). **Niente LibreOffice** (scelta esplicita: conversione Office via
   mammoth/weasyprint/fpdf2, o Microsoft Word se presente).
6. **Nessuna risorsa da internet a runtime** (niente CDN, niente Google Fonts).
7. **Fascicoli persistenti** su disco.
8. **Ricerca**: ibrida (significato + parole esatte) con citazioni “File X, pagina N”.
9. **Modello predefinito automatico in base alla RAM** (16 GB → qwen2.5:7b; ≥30 GB → qwen2.5:14b; meno → llama3.2:3b),
   sempre modificabile dall'utente. Contesto (`num_ctx`) ridotto per evitare swap.
10. **Uso personale/interno**: app non firmata con Developer ID (firma ad-hoc), licenze AGPL (Ghostscript, PyMuPDF) accettate.
11. **Nome**: “Forensic Tools”. Icona: `build/icon-source.png` (valigetta + lente con impronta, fornita dall'utente).
12. L'area **PDF deve restare identica a Pdf50** nel comportamento (“è perfetta così”): cambia solo la grafica.

---

## 2. Struttura del repository

```
Forensics AI Offline/            (repository git, branch main)
├── BLUEPRINT.md                 questo documento
├── main.py                      ingresso: env → Ollama → Flask → finestra nativa
├── requirements.txt             dipendenze Python (runtime 3.11)
├── server/
│   ├── runtime.py               percorsi, strumenti inclusi, Ollama privato, scelta modello, stato sistema
│   ├── app.py                   create_app(): UI statica + API fascicoli/ricerca/stato
│   ├── jobs.py                  job in background + stream SSE (protocollo Pdf50)
│   ├── store.py                 archivio fascicoli/documenti su disco
│   ├── pipeline.py              acquisizione documenti → PDF → OCR → pagine → indice
│   ├── search.py                indice FTS5+embedding, ricerca ibrida, risposta con citazioni
│   ├── pdf_area.py              blueprint Flask: motore Pdf50 (pipeline + post-elaborazione)
│   └── forensic_area.py         blueprint Flask: analisi forense, grafo, chat, dossier, export
├── core/                        motore di Pdf50 copiato (converter, ocr, p7m, merge, split, compress, extract)
├── forensic/                    motori storici: ai_engine, graph_manager, ftm_engine, parser, logger
├── ui/
│   ├── index.html               struttura: toolbar, sidebar fascicolo, 3 aree
│   ├── app-icon.png             icona 256 px per la toolbar
│   ├── css/app.css              design system (token, controlli, card, popover, modali, markdown)
│   ├── css/areas.css            stili specifici delle tre aree
│   ├── js/app.js                nucleo FT: API, SSE, aree, fascicolo, modelli, drop, popover/modali/toast
│   ├── js/pdf.js                porting di static/js/app.js di Pdf50 (oggetto globale PDF)
│   ├── js/ricerca.js            chat Ricerca (oggetto RC)
│   ├── js/forensic.js           area Forensic (oggetto FX)
│   └── vendor/                  marked 12.0.2, DOMPurify 3.1.6, vis-network 9.1.2, Material Symbols Rounded woff2
├── build/
│   ├── icon-source.png, AppIcon.icns
│   ├── bundle_tools.py          copia tesseract/gs/pango da conda-forge nel runtime dell'app
│   ├── launcher.c               eseguibile nativo del bundle (§3.4)
│   └── build_app.sh             assemblaggio dist/Forensic Tools.app (+ --zip sulla Scrivania)
├── models/                      modelli Ollama (NON in git, ~16 GB)
├── lib/Ollama.app               runtime Ollama (NON in git; si usa Contents/Resources/ollama)
└── wheels/                      vecchio archivio wheel (NON in git; usato solo come ripiego)
```

La vecchia app Streamlit (`app.py`, `start.sh`, `setup_environment.sh`, launcher e `.app` precedenti) è stata rimossa;
resta nella cronologia git (commit `419ff90`). `README.md` è ancora quello vecchio e va riscritto.
`dist/` (bundle generato) è escluso da git.

---

## 3. Runtime e strumenti inclusi

### 3.1 Layout del bundle (obiettivo)

```
Forensic Tools.app/Contents/
├── Info.plist                   CFBundleName "Forensic Tools", CFBundleIdentifier it.forensictools.app,
│                                LSMinimumSystemVersion 13.0, LSArchitecturePriority arm64, icona AppIcon
├── MacOS/Forensic Tools         launcher C (vedi 3.4)
└── Resources/
    ├── AppIcon.icns
    ├── app/                     main.py, server/, core/, forensic/, ui/
    ├── runtime/arm64/python/    Python 3.11 portatile con site-packages installati
    ├── runtime/arm64/tools/     bin/{tesseract,gs} lib/*.dylib share/{tessdata,ghostscript}
    ├── ollama/                  contenuto di lib/Ollama.app/Contents/Resources (binario `ollama` + librerie)
    └── models/                  blobs/ manifests/ (qwen2.5:14b, qwen2.5:7b, llama3.2:3b, embeddinggemma)
```

`server/runtime.py` riconosce il bundle se `APP_DIR.name == "app"` e `Resources/runtime` esiste; in sviluppo
ripiega su `~/.ft-build/tools-arm64` e su `lib/Ollama.app/...` e `models/` del repository.

### 3.2 Python

- **python-build-standalone** 3.11 (astral-sh), asset `cpython-3.11.18+20261110-aarch64-apple-darwin-install_only.tar.gz`.
  Ha `lib/libpython3.11.dylib` (serve al launcher) e SQLite con **FTS5** (verificato).
- In sviluppo è estratto in `~/.ft-build/py-aarch64/python`; le dipendenze si installano con
  `python3 -m pip install -r requirements.txt` direttamente nel suo site-packages (nessun venv).
- Versioni verificate: Flask 3.1.3, pywebview 6.2.1 (pyobjc 13), pymupdf 2.1, ocrmypdf 17.14, weasyprint 70, numpy, duckdb, networkx, ollama.

### 3.3 Tesseract, Ghostscript, pango

- **Fonte: conda-forge `osx-arm64`**, non Homebrew. Motivi scoperti: Homebrew installato fuori da `/opt/homebrew`
  (serve sudo, non disponibile) compila tutto dal sorgente; inoltre Homebrew non pubblica più bottle x86.
  I pacchetti conda-forge usano `@rpath` + `LC_RPATH @loader_path/../lib`, quindi sono spostabili senza
  riscrivere gli install name.
- Comandi (micromamba scaricato da `https://micro.mamba.pm/api/micromamba/osx-arm64/latest`):
  ```bash
  ./bin/micromamba create -y -r ~/.ft-build/mamba -p ~/.ft-build/conda-arm64 \
      --platform osx-arm64 -c conda-forge tesseract ghostscript pango
  python3 build/bundle_tools.py ~/.ft-build/conda-arm64 ~/.ft-build/tools-arm64
  ```
- `build/bundle_tools.py`: copia `bin/tesseract`, `bin/gs` e la **chiusura delle dipendenze** (`otool -L`)
  più le librerie che weasyprint apre con `dlopen` (gobject, pango, harfbuzz, harfbuzz-subset, fontconfig, pangoft2);
  crea gli **alias** `libpango-1.0.dylib` e `libpangoft2-1.0.dylib` (weasyprint cerca quei nomi);
  scarica **tessdata_best** `ita` e `eng` (8,6 MB + 15 MB) da `github.com/tesseract-ocr/tessdata_best`
  (in caso di errore usa i modelli “fast” di conda), copia `osd`, `configs`, `tessconfigs`, `pdf.ttf`
  e `share/ghostscript`; firma ad-hoc tutto. Risultato ≈127 MB.
- Variabili impostate da `runtime.setup_environment()`: `PATH` (tools/bin in testa), `TESSDATA_PREFIX`,
  `GS_LIB`, `FONTCONFIG_FILE` (generato in `~/Library/Caches/Forensic Tools/fontconfig/fonts.conf` con i font di
  sistema), `DYLD_FALLBACK_LIBRARY_PATH` (tools/lib), `OLLAMA_HOST`.
- **Attenzione**: `DYLD_FALLBACK_LIBRARY_PATH` viene letto da dyld **solo all'avvio del processo**. Per questo
  il launcher deve impostarlo e poi rieseguire se stesso (3.4). In sviluppo va esportato nella shell prima di
  lanciare Python.

### 3.4 Launcher nativo (fatto: `build/launcher.c`)

`build/launcher.c`, compilato `clang -arch arm64 -O2 -o "Forensic Tools" launcher.c`:
1. Ricava `Resources/` da `_NSGetExecutablePath`.
2. Se `FT_LAUNCHED` non è impostata: imposta `PYTHONHOME=Resources/runtime/arm64/python`,
   `DYLD_FALLBACK_LIBRARY_PATH=Resources/runtime/arm64/tools/lib:/usr/lib`, `PYTHONDONTWRITEBYTECODE=1`,
   `FT_LAUNCHED=1` e fa `execv` di se stesso con argomenti `[exe, "-I", "Resources/app/main.py"]`
   (scarta argomenti `-psn_*` di LaunchServices).
3. Altrimenti `dlopen("…/python/lib/libpython3.11.dylib")` e chiama `Py_BytesMain(argc, argv)`.
   Così il processo resta `Contents/MacOS/Forensic Tools`, cioè `NSBundle.mainBundle` è l'app: nome nel Dock e
   nel menu, icona corretta. Il passaggio degli argomenti fa funzionare anche i sottoprocessi Python
   (`sys.executable` = launcher, es. multiprocessing di ocrmypdf o `python -m docx2pdf`).
4. Firma ad-hoc del bundle intero: `codesign --force --deep -s - "Forensic Tools.app"`.

### 3.5 Ollama

- Si usa il binario universale `lib/Ollama.app/Contents/Resources/ollama` (`ollama serve`), **non** `open -a`
  (che non passa le variabili d'ambiente). Porta privata **127.0.0.1:11439**, così non interferisce con un
  Ollama di sistema.
- Variabili: `OLLAMA_MODELS=<Resources>/models`, `OLLAMA_NUM_PARALLEL=1`, `OLLAMA_MAX_LOADED_MODELS=2`
  (chat + embedding), `OLLAMA_FLASH_ATTENTION=1`, `OLLAMA_KV_CACHE_TYPE=q8_0`, `OLLAMA_KEEP_ALIVE=15m`.
  Log in `~/Library/Logs/Forensic Tools/ollama.log`. Il processo viene chiuso all'uscita (`atexit`).
- Modelli: `qwen2.5:14b`, `qwen2.5:7b`, `llama3.2:3b`, **`embeddinggemma`** (embedding multilingue, ~620 MB,
  scaricato con `OLLAMA_MODELS=$PWD/models ollama pull embeddinggemma` usando il binario incluso).
- Prefissi embeddinggemma: documenti `"title: none | text: …"`, query `"task: search result | query: …"`.
- `runtime.context_budget(model)`: 14b → 8192 (16384 con ≥30 GB); 7b → 12288 (8192 sotto 14 GB); altri 8192.

### 3.6 Dati utente

- Fascicoli: `~/Library/Application Support/Forensic Tools/fascicoli/<fid>/` (vedi §5).
- Preferenze: `~/Library/Application Support/Forensic Tools/stato_app.json`
  (`fascicolo_corrente`, `model`, `area`, `sidebar_hidden`).
- Log: `~/Library/Logs/Forensic Tools/` (`forensic_YYYY-MM-DD.log`, `ollama.log`).
- Cache: `~/Library/Caches/Forensic Tools/` (fontconfig, storage WebKit).

---

## 4. Backend

### 4.1 `main.py`
1. `runtime.setup_environment()` **prima** di importare webview/ollama.
2. `webview.settings`: `DRAG_REGION_SELECTOR=".drag"`, `DRAG_REGION_DIRECT_TARGET_ONLY=True`
   (solo l'elemento `.drag` stesso trascina la finestra, non i pulsanti contenuti), `ALLOW_DOWNLOADS=True`.
3. `runtime.start_ollama()`; Flask su porta libera in un thread (`threaded=True`).
4. `webview.create_window("Forensic Tools", url, js_api=NativeAPI(), width=1440, height=920, min_size=(1100,700),
   background_color` scuro/chiaro secondo `defaults read -g AppleInterfaceStyle`, `text_select=True`).
5. All'evento `shown` (e a ogni cambio di tema, tramite `NativeAPI.set_appearance(dark)`), via PyObjC su
   `window.native` (NSWindow): `setTitlebarAppearsTransparent_(True)`, `setTitleVisibility_(1)` (titolo nascosto),
   `setTitlebarSeparatorStyle_(1)` (nessun separatore), `setAppearance_` Aqua/DarkAqua e `setBackgroundColor_` uguale
   al colore pieno della toolbar (`--toolbar-solid`: #F6F6F8 chiaro, #28282A scuro). La barra nativa con i semafori
   resta sopra la toolbar HTML e appare come un'unica toolbar unificata.
   **Non usare `NSWindowStyleMaskFullSizeContentView`**: WKWebView finisce sotto la barra del titolo e la parte alta
   dell'interfaccia viene tagliata (bug visto e segnalato dall'utente).
6. All'evento `loaded`: `window.dom.document.events.drop += DOMEventHandler(_on_drop, True, True)`.
   pywebview inserisce in ogni file `pywebviewFullPath` (percorso reale, anche cartelle); `_on_drop` chiama
   `FT.onNativeDrop(paths)` in JS.
7. `NativeAPI` (esposta come `window.pywebview.api`): `choose_folder()`, `choose_files(multiple)`,
   `save_file(filename)` → percorso o null, `set_title()`, `zoom()` (doppio clic sulla toolbar → `NSWindow.zoom_`).

### 4.2 `server/jobs.py` — job in background
- `create(kind, label, fid, **meta) → job_id`; `run(job_id, target, *args)` esegue `target(job_id, *args)` in un
  thread, cattura le eccezioni come evento `fatal_error` e chiude con `eos`.
- `emit(job_id, event)` aggiunge `ts`; `progress(job_id, fraction, message)` aggiorna anche lo stato
  riassuntivo per l'indicatore attività.
- `stream(job_id)` → risposta SSE `text/event-stream`, parametro `?cursor=N` per riprendere; ogni evento ha `idx`;
  heartbeat ogni 10 s.
- `active(fid)` → job in corso (`id, kind, label, progress, message, elapsed`); pulisce quelli finiti da più di 1 h.
- Tipi di evento usati: `progress`, `log`, `step`, `scan_done`, `split_progress`, `folder_start`, `done`,
  `fatal_error`, `eos`, `heartbeat`, `docs_changed`, `token` (streaming LLM), `sources` (Ricerca), `graph_fact` (chat forense).

### 4.3 `server/store.py` — archivio su disco
Funzioni: `create/get/rename/delete/list_all/current_or_default/touch`, `new_doc/doc/update_doc/list_docs/
find_doc_by_source/delete_doc`, `save_pages/load_pages/doc_text/doc_pdf`, `load_json/save_json`,
`app_state/set_app_state`. Scritture atomiche (file `.tmp` + `os.replace`), lock rientrante.
Controllo anti path-traversal sugli id (`fdir`, `ddir`).

### 4.4 `server/pipeline.py` — acquisizione nel fascicolo
`expand_paths(paths)`: espande le cartelle ricorsivamente (salta i file nascosti) tenendo le estensioni supportate:
estensioni di Pdf50 (`core.file_scanner.SUPPORTED_EXTENSIONS`) + strutturati
(`.csv .xlsx .xls .xml .ofx .qfx .mt940 .camt .bai2 .json`) + testo (`.txt .log .eml .md`).

`process_document(fid, doc_id, src, job_id, base, weight)`:
1. Copia l'originale in `documenti/<id>/originale<ext>`.
2. `.p7m` → `core.p7m_handler.extract_p7m` e si prosegue sul contenuto (`firmato=True`).
3. **Strutturati**: testo da `forensic.parser.analizza_ed_estrai`; pagine = un foglio Excel per pagina
   (etichetta `Foglio «Nome»`) oppure sezioni da 3000 caratteri (`Sezione N`); per csv/xlsx/xls genera anche un PDF
   di visualizzazione (senza OCR).
4. **Testo semplice**: sezioni da 3000 caratteri.
5. **Altro**: `core.converter.convert_to_pdf` → testo per pagina con PyMuPDF; **OCR solo se** ci sono pagine con
   meno di 40 caratteri (`core.ocr_processor.apply_ocr`, un OCR alla volta tramite semaforo), poi rilettura delle pagine;
   salva `documento.pdf`. Se la conversione di un `.docx` fallisce, ripiega sul testo da python-docx.
6. Salva `pagine.json`, aggiorna i metadati e indicizza (`search.index_document`). Stato finale `pronto`,
   oppure `avviso` (nessun testo) o `errore` (messaggio).

`ingest_job(job_id, fid, paths)`: crea subito tutti i record (`stato=in_coda`, visibili nella sidebar), sostituisce i
documenti con la stessa sorgente, li elabora in sequenza ed emette `docs_changed`.
`register_pdf(fid, source, ready_pdf)`: usata dall'area PDF per registrare un file già convertito e passato all'OCR
(nessun secondo OCR). `index_pending_job(job_id, fid, doc_ids)`: indicizza i documenti registrati.

### 4.5 `server/search.py` — Ricerca
- **Indice** `index.sqlite` per fascicolo: tabella `chunks(id, doc_id, page, label, text, emb BLOB float32 normalizzato)`
  + `chunks_fts` FTS5 a contenuto esterno (`tokenize='unicode61 remove_diacritics 2'`) con trigger di insert/delete.
- **Chunking**: passaggi da ~1100 caratteri con sovrapposizione di 180, tagliati a fine frase/paragrafo, **sempre
  dentro una singola pagina** (così la citazione di pagina è esatta).
- Embedding a lotti da 24 via `client.embed(model="embeddinggemma")`; senza modello di embedding resta solo la
  ricerca per parole (`semantico=False` sul documento).
- `search(fid, query, k, doc_ids, per_doc=3)`: FTS5 (`bm25`, top 60, query OR di termini senza stopword italiane)
  + coseno sugli embedding (top 60) fusi con **Reciprocal Rank Fusion** (k=60); massimo 3 passaggi per documento,
  per favorire l'incrocio fra documenti. Matrice embedding in cache per fascicolo (invalidata dal mtime del db).
- `answer_job(job_id, fid, domanda, model, doc_ids)`:
  - per le domande brevi di continuazione, la query di ricerca include la domanda precedente;
  - `k` dipende dal contesto disponibile (4–12 passaggi);
  - emette `sources` (lista passaggi), poi `token` in streaming, infine `done` con `text` già convertito;
  - prompt di sistema: **solo fatti dai passaggi**, niente analisi/deduzioni/ipotesi/commenti/consigli, incrocio fra
    documenti, valori discordanti riportati entrambi, citazione `[n]` dopo ogni dato, se manca rispondere solo
    “Nei documenti caricati non risulta …”, testo semplice senza titoli né riepiloghi;
  - `temperature=0`, `num_predict=1200`, ultimi 4 messaggi come storia;
  - **post-elaborazione deterministica** `cita(testo, fonti)`: `[1]`, `[2][4]`, `[1, 2]` →
    `(File <nome>, pagina N; File <nome>, foglio «X»)`. Il modello non scrive mai nomi di file: li inserisce il server.
  - Se non trova passaggi risponde senza chiamare il modello.
- Storia in `ricerca.json` (`{"messaggi":[{role, content, fonti?, modello?, secondi?}]}`).

### 4.6 `server/pdf_area.py` — motore Pdf50
Generato copiando **letteralmente** da Pdf50 `app.py` le funzioni `_convert_and_ocr`, `_save_or_split`,
`_run_unified`, `_run_per_folder` e le route `/api/post/*`, con queste sole modifiche:
`_emit`→`jobs.emit`, `_is_cancelled`→`jobs.is_cancelled`, stato del job via `jobs.meta`, prefisso URL `/api/pdf/`,
e un hook dopo l'OCR di ogni file: `_register_in_fascicolo(job_id, src, ocr_pdf)` (se l'opzione
“Aggiungi al fascicolo” è attiva); a fine pipeline `_index_registered` avvia l'indicizzazione.
Route aggiunte: `POST /api/pdf/scan {path}`, `POST /api/pdf/prepare-files {paths}` (PDF singolo → modalità PDF
diretta; altrimenti symlink in una cartella temporanea), `POST /api/pdf/cleanup-temp`, `POST /api/pdf/start`
(`source_path, output_path, mode, folder_name, source_is_temp, fid, add_to_fascicolo`), `GET /api/pdf/system-info`.
Post-elaborazione: `/api/pdf/post/{compress,split-size,split-ranges,page-count,extract-text}` (identiche a Pdf50).

### 4.7 `core/` — motore Pdf50 (copiato) e modifiche
Copiato dal repository Pdf50. Modifiche a `core/converter.py` (bug reali):
1. **fpdf2 ≥ 2.7**: `multi_cell(0, …)` lasciava il cursore al margine destro (“Not enough horizontal space”).
   Aggiunto `new_x="LMARGIN", new_y="NEXT"` a ogni `multi_cell`.
2. **Unicode**: i font core Helvetica sono solo Latin-1 (“€” mandava in errore la conversione XLSX, e l'errore veniva
   nascosto). Aggiunti `_new_fpdf()` (registra Arial di sistema da `/System/Library/Fonts/Supplemental` come font
   `UNI`) e `_set_font()`; sostituiti tutti gli `FPDF(...)`/`set_font('Helvetica', …)`. Errori XLSX ora riportati.
3. **DOCX**: nuovo passo 2, *mammoth → HTML → weasyprint* (usa pango incluso, conserva titoli, elenchi e tabelle),
   prima del ripiego *mammoth → testo → fpdf2*. Ordine: Word (docx2pdf, se installato) → weasyprint → fpdf2.
Test eseguiti: DOCX, XLSX (con €), TXT, PNG → PDF; OCR italiano su scansione sintetica (testo riconosciuto
perfettamente); compressione Ghostscript.

### 4.8 `forensic/` — motori storici adattati
- Import di pacchetto (`from forensic.logger import log`, ecc.); log in `~/Library/Logs/Forensic Tools`, senza
  handler su console (eliminava le righe duplicate).
- `graph_manager.py`: rimossa la dipendenza pyvis; `genera_html_mappa`/`esporta_grafo_html` sostituite da
  **`dati_vis()`** → `{nodi:[{id,label,tipo,cf_piva,fonti,size}], archi:[{id,from,to,label,dettagli,fonte,valore}]}`.
- `ai_engine.py`:
  - client Ollama privato (`runtime.client()`) e `_opzioni(model, …)` con `num_ctx` da `context_budget`;
  - rimossi i parametri fissi “Metal M1 Pro”;
  - **timer di sicurezza calcolato dal primo token**, non dall'avvio. Prima il dossier veniva interrotto durante
    la lettura dell'input (log reale: “1 token in 317 s”). Limiti di generazione: blocco 240 s, deduzioni 300 s, dossier 900 s;
  - **budget di caratteri** calibrato sul contesto: `caratteri_per_contesto(model, riserva_token)` ≈ (ctx − riserva) × 2,6;
    l'estrazione ri-spezza i blocchi, il dossier divide il budget fra i documenti, le deduzioni troncano di conseguenza;
  - rimossa la scrittura di `logs/ultimo_dossier_unificato.md` (percorso relativo).

### 4.9 `server/forensic_area.py`
- Stato in `forensic/stato.json`: `{ordine:[doc_id], storico:[{doc_id,file,analisi,caratteri,secondi,modello,timestamp}],
  chat:[…], dossier, dossier_ts, dossier_modello}`; estrazioni grezze dell'IA in `forensic/estrazioni/<doc_id>.json`.
- **Il grafo non viene serializzato**: `grafo(fid)` lo ricostruisce rigiocando `aggiungi_dati` sulle estrazioni salvate,
  nell'ordine di analisi (così si rigenerano anche FtM, DuckDB e timeline). Cache in memoria per fascicolo.
- Route (`<fid>` = fascicolo):
  `POST /api/forensic/<fid>/analyze {doc_ids?, model}` (senza `doc_ids` analizza i documenti pronti non ancora analizzati),
  `POST …/reset`, `GET …/overview`, `GET|POST|DELETE …/chat`, `GET|POST …/dossier`, `GET …/graph` (+ `cicli`),
  `GET …/patterns` (`centralita, ubo, finanza, schemi`), `GET …/timeline`, `GET …/registry`
  (`trasversali, soggetti, ftm`), `POST …/sql {query}`, `POST …/export {tipo, path}` con
  `tipo ∈ ftm | cytoscape | mermaid_td | mermaid_lr | dossier | sessione`.
- Chat forense: stessa logica deterministica di prima (riconoscimento dei soggetti, `analizza_contatti` per contatti,
  `calcola_partecipazioni` per quote/cariche), il riscontro viene emesso come `graph_fact`; risposta in streaming.
- I messaggi di avanzamento passano da `_pulisci()` (rimuove emoji e “[Fase x/y]”).

### 4.10 `server/app.py` — altre API
`GET /` (index.html), `GET /ui/<file>`, `GET /api/status`, `GET /api/models`, `GET|POST /api/prefs`,
`GET /api/jobs/active?fid=`, `GET /api/jobs/<id>/stream`, `POST /api/jobs/<id>/cancel`,
`GET|POST /api/fascicoli`, `GET|PATCH|DELETE /api/fascicoli/<fid>`, `GET|POST /api/fascicoli/<fid>/documenti`
(POST `{paths}` → job di acquisizione), `DELETE …/documenti/<doc>`, `POST …/documenti/<doc>/reprocess`,
`GET …/documenti/<doc>/pdf`, `GET …/documenti/<doc>/pagine`, `POST …/documenti/<doc>/apri` (Anteprima),
`GET|DELETE /api/ricerca/<fid>`, `POST /api/ricerca/<fid>/ask {question, model, doc_ids?}`,
`POST /api/ricerca/<fid>/cerca {query}` (solo passaggi), `POST /api/reveal {path}` (Finder).

---

## 5. Formati su disco (fascicolo)

```
fascicoli/<fid>/
  fascicolo.json                 {id, nome, creato, aggiornato}
  documenti/<doc_id>/
    meta.json                    {id, nome, sorgente, estensione, stato: in_coda|elaborazione|indicizzazione|pronto|avviso|errore,
                                  messaggio, pagine, caratteri, pagine_senza_testo[], ocr, pdf, firmato, indicizzato,
                                  semantico, passaggi, analizzato, aggiunto, origine?}
    originale.<ext>              copia del file sorgente
    documento.pdf                PDF ricercabile (se disponibile)
    pagine.json                  [{n, label: "Pag. 3" | "Foglio «X»" | "Sezione 2", text}]
  index.sqlite                   chunks + chunks_fts (WAL)
  ricerca.json                   conversazione Ricerca
  forensic/stato.json            vedi 4.9
  forensic/estrazioni/<doc>.json {entita:[{id,tipo,cf_piva}], relazioni:[{sorgente,destinazione,tipo,dettagli,valore_numerico}]}
```

---

## 6. Interfaccia (Apple HIG + Material Symbols)

### 6.1 Design system (`ui/css/app.css`)
- Font di sistema (`-apple-system`, SF Pro Text/Display), corpo 13 px come macOS, `font-variant-numeric: tabular-nums`
  per i numeri.
- **Token** per chiaro/scuro: `--window --toolbar --sidebar --content --elevated --grouped --label --label-2/3/4
  --separator(-strong) --fill(-2,-hover) --accent(#007AFF / #0A84FF) --green --orange --red --purple --teal --indigo`
  (+ varianti `-soft`), ombre `--shadow-1/2/pop`. Tema: Sistema / Chiaro / Scuro (`data-theme` su `<html>`,
  salvato in localStorage).
- Materiali: toolbar e sidebar traslucide (`backdrop-filter: saturate(180%) blur(…)`), separatori da 0,5 px.
- Componenti: `.btn` (primary/plain/danger, lg/xl), `.icon-btn`, `.segmented`, `.switch` (stile macOS),
  `.input`, `.card`, `.stat` (tile), `.chip`, `.list`, `table.grid`, `.progress` (anche indeterminata), `.spinner`,
  `.empty` (stati vuoti con icona), `.banner`, `.popover` + `.menu-item` (evidenziazione con l'accento come i menu
  macOS), `.modal` (+ `.large`), `.toast`, `.drop-zone`, `.md` (markdown, con `.ref` per i riferimenti).
- Icone: `<span class="ms">nome</span>`; `.fill` per la versione piena (stato attivo), dimensioni `.xs .sm .lg .xl .xxl`.
  Font `ui/vendor/material-symbols-rounded.woff2` (asse variabile FILL/wght/GRAD/opsz).
- Testo non selezionabile di default (come un'app nativa); `.selectable` e `.md` selezionabili.

### 6.2 Struttura
- **Toolbar** (66 px sotto la barra nativa, stesso colore pieno; area di trascinamento `.drag`, doppio clic = zoom): a sinistra il pulsante sidebar e il marchio
  (icona + “Forensic Tools”); al centro le **tre tab giganti** (segmented control grande: icona in riquadro colorato,
  titolo, sottotitolo; colore per area: PDF rosso, Ricerca blu, Forensic viola); a destra l'indicatore attività
  (spinner + job), il selettore modello e le impostazioni (tema e stato dei motori offline).
- **Sidebar Fascicolo** (290 px, nascondibile con ⌘⇧S): selettore del fascicolo (menu: elenco, nuovo, rinomina,
  elimina), pulsanti “File” e “Cartella”, elenco documenti (icona per tipo, nome, metadati “N pag. · OCR · firmato”,
  stato: spinner / spunta / spunta piena se analizzato / avviso / errore), menu contestuale (visualizza, apri con
  Anteprima, mostra nel Finder, rielabora, rimuovi), piè di pagina (archiviazione locale, elaborazioni, tipo di ricerca).
  Trascinare file o cartelle sulla sidebar (o su qualsiasi area tranne la drop zone del PDF) li aggiunge al fascicolo.
- **Visualizzatore documento** (modale grande): PDF in iframe alla pagina citata (`#page=N`) + pannello con il testo
  riconosciuto e le parole del passaggio evidenziate; pulsante “Apri con Anteprima”.
- Scorciatoie: ⌘1/⌘2/⌘3 per le aree, ⌘O aggiungi file, ⌘⇧S sidebar, Esc chiude le modali.

### 6.3 Area PDF (`ui/js/pdf.js`, oggetto `PDF`)
Porting di `static/js/app.js` di Pdf50 con **gli stessi id DOM e la stessa logica**. Cambiano solo:
le emoji diventano icone Material; le cartelle si scelgono con il dialogo nativo (`pywebview.api.choose_folder`)
seguito da `/api/pdf/scan`; il trascinamento usa i percorsi reali (`PDF.onNativeDrop(paths)`: una cartella → sorgente;
un PDF → modalità PDF diretta; altri file → `/api/pdf/prepare-files`); le URL hanno il prefisso `/api/pdf/`;
lo stream usa `FT.stream`; c'è lo switch “Aggiungi i documenti anche al fascicolo” (attivo di default);
c'è il pulsante “Mostra nel Finder”. Flussi: setup → progresso (5 step: Scansione, Conversione, OCR, Unione,
Salvataggio; barra, file corrente, log) → risultato (statistiche, parti, errori, log comprimibile, post-elaborazione inline).

### 6.4 Area Ricerca (`ui/js/ricerca.js`, oggetto `RC`)
Colonna centrale di 820 px stile chat. Stato iniziale: icona, titolo, frase e suggerimenti di domande. Messaggi
dell'utente in bolle blu a destra; risposta con avatar, testo markdown semplice, riferimenti “(File …, pagina …)”
resi come chip cliccabili che aprono il visualizzatore alla pagina; sotto, “Fonti consultate” comprimibile
(numero, documento, etichetta pagina, estratto). Composer in basso arrotondato con textarea che cresce, invio
con Invio, a capo con Maiusc+Invio, pulsante invia/stop. Barra superiore con l'ambito (“N documenti indicizzati”)
e “Nuova conversazione”. Avviso se nessun documento è indicizzato.

### 6.5 Area Forensic (`ui/js/forensic.js`, oggetto `FX`)
Segmented control secondario: **Panoramica** (tile: entità, relazioni, documenti analizzati, soggetti trasversali,
volumi €, flussi circolari, incongruenze; card “Analizza N documenti nuovi” con avanzamento del job;
report per atto espandibili in markdown), **Chat** (come Ricerca ma con avatar viola e riquadro “Riscontro sul grafo”),
**Dossier CTU** (pulsante compila/aggiorna, progresso con conteggio token, documento in “foglio” markdown,
esporta .md), **Link analysis** (vis-network con colori per tipo, ricerca soggetto, pannello dettagli del nodo,
legenda, cicli evidenziati), **Pattern AML** (tabella centralità, schede UBO con catene, matrice finanziaria,
flussi circolari, incongruenze), **Timeline** (verticale), **Anagrafiche** (soggetti trasversali, registro unificato,
statistiche FtM, console SQL DuckDB), **Esporta** (FtM .ftm.json, Cytoscape .relazioni.json, Mermaid TD/LR,
Dossier .md, Sessione .json → dialogo di salvataggio nativo + `POST …/export`).

---

## 7. Stato di avanzamento

### Fatto e verificato
- [x] Runtime Python 3.11 portatile con tutte le dipendenze (arm64).
- [x] Tesseract (ita/eng best), Ghostscript, pango da conda-forge copiati e funzionanti fuori dall'ambiente conda.
- [x] OCR italiano, compressione Ghostscript, weasyprint, conversioni DOCX/XLSX/TXT/immagini (bug corretti).
- [x] Modello di embedding `embeddinggemma` aggiunto a `models/`.
- [x] Backend completo: runtime, jobs, store, pipeline, search, pdf_area, forensic_area, app.
- [x] **Test end-to-end senza interfaccia** (Flask test client): fascicolo creato; PDF scansionato + XLSX + DOCX acquisiti
      (OCR applicato al solo PDF scansionato), indicizzati con embedding; domanda alla Ricerca con qwen2.5:7b → risposta in
      9 s: “L'amministratore unico di ALFA S.R.L. è MARIO ROSSI, C.F. … (File scan.pdf, pagina 1). Mario Rossi ha
      ricevuto l'importo di € 75.000 (File t.xlsx, foglio «Sheet»).”
- [x] Icona dell'app (`build/AppIcon.icns`), asset vendor locali.
- [x] UI: `index.html`, `css/app.css`, `css/areas.css`, `js/app.js`, `js/pdf.js`, `js/ricerca.js`, `js/forensic.js`.
- [x] `run_dev.sh` e primo avvio reale della finestra (nessun errore lato server).

### Da fare (in ordine)
- [ ] Verifica visiva completa con l'utente (chiaro/scuro, tre aree, trascinamento dal Finder, dialoghi nativi,
      visualizzatore PDF alla pagina citata). Lo screenshot automatico della finestra non è disponibile senza
      il permesso “Registrazione schermo”.
- [x] `build/launcher.c` + `build/build_app.sh`: `dist/Forensic Tools.app` (16 GB) assemblato e avviato con doppio clic:
      launcher → Python incluso → Ollama del bundle sulla porta 11439 con i 4 modelli interni. I modelli sono copiati con
      cloni APFS (`cp -c`); la firma ad-hoc con `--deep` richiede circa un minuto perché sigilla anche i modelli.
      Per aggiornare solo l'interfaccia in sviluppo: `rsync` di `ui/` dentro `Contents/Resources/app/ui/` e di nuovo `codesign`.
- [ ] Zip finale `./build/build_app.sh --zip` (≈16 GB, alcuni minuti).
- [ ] Test sull'app compilata in un account/percorso pulito: nessun accesso a internet (verificare con la rete disattivata),
      acquisizione, OCR, Ricerca, analisi forense, dossier, export, area PDF completa.
- [x] Rimozione dei file della vecchia app Streamlit (recuperabili dal commit 419ff90).
- [ ] Nuovo README per l'utente finale.
- [ ] Facoltativi/futuri: Ricerca limitata a una selezione di documenti (l'API supporta già `doc_ids`); menu dell'app macOS
      (pywebview `menu=`); avviso se la RAM è insufficiente per il 14B; pulizia dei job/cartelle temporanee all'avvio.

---

## 8. Insidie già scoperte (non ripeterle)

1. **Homebrew** senza sudo non installa i bottle (compila tutto); Homebrew non ha più bottle per Intel → usare conda-forge.
2. **PyMuPDF** recente non ha wheel x86_64 (irrilevante ora, ma spiega perché Intel è stato abbandonato).
3. **weasyprint** cerca `libpango-1.0.dylib` / `libpangoft2-1.0.dylib` (senza versione) → servono gli alias.
4. **DYLD_FALLBACK_LIBRARY_PATH** va impostato prima dell'avvio del processo (launcher che rilancia se stesso).
5. **fpdf2**: `multi_cell` richiede `new_x/new_y`; i font core non supportano “€” → font TTF di sistema.
6. **Timer di sicurezza degli LLM**: va misurato dal primo token; con contesti grandi la lettura dell'input (prefill)
   può durare minuti.
7. **14B su 16 GB**: con `num_ctx` 24k e due slot paralleli il Mac usa il disco come memoria → contesto ridotto,
   `OLLAMA_NUM_PARALLEL=1`, cache KV q8_0.
8. **`open -a Ollama.app`** non passa le variabili d'ambiente → avviare direttamente il binario `ollama serve`.
9. **pyvis/CDN e Google Fonts** rompono l'offline → vis-network e font inclusi localmente.
10. Il grafo forense non va serializzato con `esporta_stato/importa_stato` (non ricostruisce FtM): rigiocare le estrazioni.
11. Niente `FullSizeContentView` con pywebview/WKWebView (contenuto tagliato in alto): barra nativa trasparente
    colorata come la toolbar.
12. pywebview: il trascinamento della finestra dalla toolbar HTML richiede `.drag` +
    `DRAG_REGION_DIRECT_TARGET_ONLY=True`; i percorsi dei file trascinati arrivano solo tramite `DOMEventHandler` sul drop
    (`pywebviewFullPath`), non dal `DataTransfer` JavaScript.
13. Le citazioni non vanno fatte scrivere al modello (sbaglia i nomi dei file): il modello usa `[n]`, il server li sostituisce.

---

## 9. Come provare

```bash
# ambiente di sviluppo (una tantum): §3.2 e §3.3
export DYLD_FALLBACK_LIBRARY_PATH=$HOME/.ft-build/tools-arm64/lib:/usr/lib
~/.ft-build/py-aarch64/python/bin/python3 main.py          # FT_DEBUG=1 per l'inspector WebKit
```
Smoke test senza interfaccia: creare un fascicolo con `create_app().test_client()`, `POST /api/fascicoli/<fid>/documenti`
con alcuni file, attendere che `jobs.active(fid)` sia vuoto, poi `POST /api/ricerca/<fid>/ask` e leggere l'evento `done`.
