"""
Acquisizione documenti nel fascicolo condiviso:
copia → (P7M: estrazione) → conversione PDF → OCR italiano se servono pagine
→ testo per pagina → indice di ricerca.
Riusa il motore di Pdf50 (core/) per conversione, P7M e OCR.
"""
from __future__ import annotations

import os
import re
import shutil
import tempfile
import threading
from pathlib import Path

from core import converter, ocr_processor
from core.file_scanner import SUPPORTED_EXTENSIONS
from server import jobs, search, store

STRUCTURED = {".csv", ".xlsx", ".xls", ".xml", ".ofx", ".qfx", ".mt940", ".camt", ".bai2", ".json"}
TEXT_ONLY = {".txt", ".log", ".eml", ".md"}
ALL_EXTENSIONS = set(SUPPORTED_EXTENSIONS) | STRUCTURED | TEXT_ONLY
MIN_CHARS_PAGE = 40

_ocr_lock = threading.Semaphore(1)   # un OCR alla volta: usa già tutti i core


def expand_paths(paths: list[str]) -> list[str]:
    out = []
    for p in paths:
        p = os.path.expanduser(p)
        if os.path.isdir(p):
            for root, dirs, files in os.walk(p):
                dirs[:] = sorted(d for d in dirs if not d.startswith("."))
                for f in sorted(files):
                    if not f.startswith(".") and os.path.splitext(f)[1].lower() in ALL_EXTENSIONS:
                        out.append(os.path.join(root, f))
        elif os.path.isfile(p) and os.path.splitext(p)[1].lower() in ALL_EXTENSIONS:
            out.append(p)
    return out


def _pdf_pages(pdf_path: str) -> list[dict]:
    import pymupdf
    pages = []
    with pymupdf.open(pdf_path) as doc:
        for i, page in enumerate(doc, start=1):
            pages.append({"n": i, "label": f"Pag. {i}", "text": page.get_text("text").strip()})
    return pages


def _structured_pages(path: str) -> list[dict]:
    from forensic.parser import analizza_ed_estrai
    with open(path, "rb") as f:
        diag = analizza_ed_estrai(f)
    testo = diag.get("testo", "")
    parti = re.split(r"\n--- Foglio Excel: (.+?) ---\n", "\n" + testo)
    if len(parti) > 1:
        pages = []
        for i in range(1, len(parti), 2):
            pages.append({"n": len(pages) + 1, "label": f"Foglio «{parti[i]}»", "text": parti[i + 1].strip()})
        return pages
    # testo lungo non paginato: sezioni da ~3000 caratteri per citazioni puntuali
    sezioni, size = [], 3000
    for i in range(0, max(1, len(testo)), size):
        sezioni.append({"n": len(sezioni) + 1, "label": f"Sezione {len(sezioni) + 1}", "text": testo[i:i + size]})
    return sezioni


def process_document(fid: str, doc_id: str, src: str, job_id: str | None = None,
                     base: float = 0.0, weight: float = 1.0) -> dict:
    meta = store.doc(fid, doc_id) or {}
    nome = meta.get("nome") or os.path.basename(src)
    ddir = store.ddir(fid, doc_id)
    ext = os.path.splitext(src)[1].lower()

    def step(frac, msg):
        store.update_doc(fid, doc_id, stato="elaborazione", messaggio=msg)
        if job_id:
            jobs.progress(job_id, base + weight * frac, f"{nome} · {msg}")
            jobs.log(job_id, f"  {msg}")

    tmp = tempfile.mkdtemp(prefix="ft_ingest_")
    try:
        step(0.02, "Copia")
        shutil.copy2(src, ddir / f"originale{ext}")
        work = src
        firmato = False

        if ext == ".p7m":
            step(0.06, "Estrazione file firmato P7M")
            from core.p7m_handler import extract_p7m
            inner = extract_p7m(src, tmp)
            if not inner:
                raise RuntimeError("Impossibile estrarre il contenuto del file P7M")
            work, ext, firmato = inner, os.path.splitext(inner)[1].lower(), True

        pages: list[dict] = []
        pdf_ok = ocr_done = False

        if ext in STRUCTURED:
            step(0.2, "Lettura dati strutturati")
            pages = _structured_pages(work)
            if ext in (".csv", ".xlsx", ".xls"):
                try:
                    pdf = converter.convert_to_pdf(work, tmp)
                    shutil.copy2(pdf, ddir / "documento.pdf")
                    pdf_ok = True
                except Exception:
                    pass
        elif ext in TEXT_ONLY:
            with open(work, "r", encoding="utf-8", errors="replace") as f:
                testo = f.read()
            pages = [{"n": i + 1, "label": f"Sezione {i + 1}", "text": testo[i * 3000:(i + 1) * 3000]}
                     for i in range(max(1, (len(testo) + 2999) // 3000))]
        else:
            step(0.1, "Conversione in PDF")
            try:
                pdf = converter.convert_to_pdf(work, tmp)
            except Exception as conv_err:
                if ext == ".docx":   # ripiego: solo testo
                    from forensic.parser import analizza_ed_estrai
                    with open(work, "rb") as f:
                        testo = analizza_ed_estrai(f).get("testo", "")
                    pages = [{"n": 1, "label": "Testo", "text": testo}]
                    pdf = None
                else:
                    raise conv_err
            if pdf:
                pages = _pdf_pages(pdf)
                vuote = [p["n"] for p in pages if len(p["text"]) < MIN_CHARS_PAGE]
                if vuote and ocr_processor.is_available():
                    step(0.3, f"OCR italiano su {len(vuote)} pagine")
                    out = os.path.join(tmp, "ocr.pdf")
                    with _ocr_lock:
                        try:
                            ocr_processor.apply_ocr(pdf, out)
                            pdf, ocr_done = out, True
                        except Exception:
                            pass
                    pages = _pdf_pages(pdf)
                shutil.copy2(pdf, ddir / "documento.pdf")
                pdf_ok = True

        store.save_pages(fid, doc_id, pages)
        vuote = [p["n"] for p in pages if len(p.get("text", "")) < MIN_CHARS_PAGE]
        caratteri = sum(len(p.get("text", "")) for p in pages)
        store.update_doc(fid, doc_id, pagine=len(pages), caratteri=caratteri, pagine_senza_testo=vuote,
                         ocr=ocr_done, pdf=pdf_ok, firmato=firmato, stato="indicizzazione",
                         messaggio="Indicizzazione", indicizzato=False, analizzato=False)

        if job_id:
            if ocr_done:
                jobs.log(job_id, "  ✓ OCR italiano applicato", "success")
            if vuote:
                jobs.log(job_id, f"  ⚠ Pagine senza testo leggibile: {', '.join(map(str, vuote[:30]))}"
                         + (" …" if len(vuote) > 30 else ""), "warning")
        step(0.75, "Indicizzazione per la ricerca")
        search.index_document(fid, doc_id, job_id, base + weight * 0.75, weight * 0.25)
        msg = "Pronto" if caratteri else "Nessun testo leggibile"
        if job_id:
            n_car = f"{caratteri:,}".replace(",", ".")
            jobs.log(job_id, f"  ✓ {nome}: {len(pages)} {'pagina' if len(pages) == 1 else 'pagine'}, {n_car} caratteri"
                     if caratteri else f"  ⚠ {nome}: nessun testo leggibile", "success" if caratteri else "warning")
        return store.update_doc(fid, doc_id, stato="pronto" if caratteri else "avviso", messaggio=msg)
    except Exception as e:
        if job_id:
            jobs.log(job_id, f"  ✗ {nome}: {e}", "error")
        return store.update_doc(fid, doc_id, stato="errore", messaggio=str(e)[:300])
    finally:
        shutil.rmtree(tmp, ignore_errors=True)


def ingest_job(job_id: str, fid: str, paths: list[str]):
    files = expand_paths(paths)
    if not files:
        jobs.emit(job_id, {"type": "done", "added": 0, "message": "Nessun file supportato"})
        return
    records = []
    for p in files:
        existing = store.find_doc_by_source(fid, p)
        if existing:
            search.remove_document(fid, existing["id"])
            store.delete_doc(fid, existing["id"])
        records.append((store.new_doc(fid, os.path.basename(p), sorgente=p), p))
    jobs.emit(job_id, {"type": "docs_changed"})
    n = len(records)
    jobs.log(job_id, f"Acquisizione di {n} documenti nel fascicolo")
    for i, (meta, p) in enumerate(records):
        if jobs.is_cancelled(job_id):
            store.update_doc(fid, meta["id"], stato="errore", messaggio="Annullato")
            continue
        jobs.log(job_id, f"[{i + 1}/{n}] {os.path.basename(p)}")
        process_document(fid, meta["id"], p, job_id, base=i / n, weight=1 / n)
        jobs.emit(job_id, {"type": "docs_changed"})
    jobs.progress(job_id, 1.0, "Completato")
    jobs.log(job_id, "Acquisizione completata", "success")
    jobs.emit(job_id, {"type": "done", "added": n})


def register_pdf(fid: str, source_path: str, ready_pdf: str, ocr: bool = True):
    """Usato dall'area PDF: registra un file già convertito e passato all'OCR, evitando un secondo OCR."""
    existing = store.find_doc_by_source(fid, source_path)
    if existing:
        search.remove_document(fid, existing["id"])
        store.delete_doc(fid, existing["id"])
    meta = store.new_doc(fid, os.path.basename(source_path), sorgente=source_path, origine="Area PDF")
    ddir = store.ddir(fid, meta["id"])
    ext = os.path.splitext(source_path)[1].lower()
    try:
        shutil.copy2(source_path, ddir / f"originale{ext}")
    except Exception:
        pass
    shutil.copy2(ready_pdf, ddir / "documento.pdf")
    pages = _pdf_pages(ready_pdf)
    store.save_pages(fid, meta["id"], pages)
    caratteri = sum(len(p["text"]) for p in pages)
    store.update_doc(fid, meta["id"], pagine=len(pages), caratteri=caratteri, pdf=True, ocr=ocr,
                     pagine_senza_testo=[p["n"] for p in pages if len(p["text"]) < MIN_CHARS_PAGE],
                     stato="indicizzazione", messaggio="Indicizzazione")
    return meta["id"]


def index_pending_job(job_id: str, fid: str, doc_ids: list[str]):
    n = max(1, len(doc_ids))
    for i, d in enumerate(doc_ids):
        if jobs.is_cancelled(job_id):
            break
        try:
            jobs.log(job_id, f"[{i + 1}/{n}] Indicizzazione {(store.doc(fid, d) or {}).get('nome', d)}")
            search.index_document(fid, d, job_id, i / n, 1 / n)
            caratteri = (store.doc(fid, d) or {}).get("caratteri", 0)
            store.update_doc(fid, d, stato="pronto" if caratteri else "avviso",
                             messaggio="Pronto" if caratteri else "Nessun testo leggibile")
        except Exception as e:
            jobs.log(job_id, f"  ✗ {e}", "error")
            store.update_doc(fid, d, stato="errore", messaggio=str(e)[:300])
        jobs.emit(job_id, {"type": "docs_changed"})
    jobs.progress(job_id, 1.0, "Completato")
    jobs.emit(job_id, {"type": "done"})
