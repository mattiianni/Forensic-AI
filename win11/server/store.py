"""
Archivio fascicoli su disco (in data\\fascicoli\\<fid>\\ nella cartella portable).

data/fascicoli/<fid>/
    fascicolo.json                  meta (nome, date)
    documenti/<doc_id>/meta.json    meta documento
    documenti/<doc_id>/originale.*  copia del file sorgente
    documenti/<doc_id>/documento.pdf  PDF ricercabile (OCR) se disponibile
    documenti/<doc_id>/pagine.json  [{"n": 1, "label": "Pag. 1", "text": "..."}]
    index.sqlite                    indice di ricerca (FTS5 + embedding)
    ricerca.json                    conversazione area Ricerca
    forensic/stato.json             report atti, chat, dossier
    forensic/estrazioni/<doc_id>.json  entità/relazioni estratte dall'IA
"""
from __future__ import annotations

import json
import os
import shutil
import threading
import uuid
from datetime import datetime
from pathlib import Path

from server.runtime import DATA_DIR

ROOT = DATA_DIR / "fascicoli"
ROOT.mkdir(parents=True, exist_ok=True)
STATE_FILE = DATA_DIR / "stato_app.json"

_lock = threading.RLock()


def _now() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _read(path: Path, default):
    try:
        with open(path, "r", encoding="utf-8") as f:
            return json.load(f)
    except Exception:
        return default


def _write(path: Path, data):
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    with open(tmp, "w", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, indent=1)
    os.replace(tmp, path)


# ── Preferenze app ────────────────────────────────────────────────────────────

def app_state() -> dict:
    return _read(STATE_FILE, {})


def set_app_state(**kw):
    with _lock:
        s = app_state()
        s.update(kw)
        _write(STATE_FILE, s)


# ── Fascicoli ─────────────────────────────────────────────────────────────────

def fdir(fid: str) -> Path:
    p = (ROOT / fid).resolve()
    if p.parent != ROOT.resolve():
        raise ValueError("Fascicolo non valido")
    return p


def exists(fid: str) -> bool:
    try:
        return (fdir(fid) / "fascicolo.json").is_file()
    except ValueError:
        return False


def create(nome: str) -> dict:
    fid = uuid.uuid4().hex[:12]
    meta = {"id": fid, "nome": nome.strip() or "Nuovo fascicolo", "creato": _now(), "aggiornato": _now()}
    with _lock:
        _write(fdir(fid) / "fascicolo.json", meta)
    return meta


def get(fid: str) -> dict:
    meta = _read(fdir(fid) / "fascicolo.json", None)
    if not meta:
        raise KeyError(fid)
    docs = list_docs(fid)
    meta["num_documenti"] = len(docs)
    meta["num_pagine"] = sum(d.get("pagine", 0) for d in docs)
    return meta


def touch(fid: str):
    with _lock:
        p = fdir(fid) / "fascicolo.json"
        meta = _read(p, None)
        if meta:
            meta["aggiornato"] = _now()
            _write(p, meta)


def rename(fid: str, nome: str) -> dict:
    with _lock:
        p = fdir(fid) / "fascicolo.json"
        meta = _read(p, {})
        meta["nome"] = nome.strip() or meta.get("nome", "Fascicolo")
        meta["aggiornato"] = _now()
        _write(p, meta)
    return meta


def delete(fid: str):
    with _lock:
        shutil.rmtree(fdir(fid), ignore_errors=True)


def list_all() -> list[dict]:
    out = []
    for p in ROOT.iterdir():
        meta = _read(p / "fascicolo.json", None)
        if meta:
            docs_dir = p / "documenti"
            meta["num_documenti"] = len([d for d in docs_dir.iterdir() if d.is_dir()]) if docs_dir.is_dir() else 0
            out.append(meta)
    out.sort(key=lambda m: m.get("aggiornato", ""), reverse=True)
    return out


def current_or_default() -> dict:
    fid = app_state().get("fascicolo_corrente")
    if fid and exists(fid):
        return get(fid)
    all_f = list_all()
    meta = get(all_f[0]["id"]) if all_f else create("Primo fascicolo")
    set_app_state(fascicolo_corrente=meta["id"])
    return get(meta["id"])


# ── Documenti ─────────────────────────────────────────────────────────────────

def ddir(fid: str, doc_id: str) -> Path:
    p = (fdir(fid) / "documenti" / doc_id).resolve()
    if p.parent != (fdir(fid) / "documenti").resolve():
        raise ValueError("Documento non valido")
    return p


def new_doc(fid: str, nome: str, sorgente: str = "", **extra) -> dict:
    doc_id = uuid.uuid4().hex[:10]
    meta = {
        "id": doc_id, "nome": nome, "sorgente": sorgente,
        "estensione": os.path.splitext(nome)[1].lower(),
        "stato": "in_coda", "messaggio": "In coda",
        "pagine": 0, "caratteri": 0, "pagine_senza_testo": [],
        "ocr": False, "pdf": False, "indicizzato": False, "analizzato": False,
        "aggiunto": _now(), **extra,
    }
    with _lock:
        _write(ddir(fid, doc_id) / "meta.json", meta)
    touch(fid)
    return meta


def doc(fid: str, doc_id: str) -> dict | None:
    return _read(ddir(fid, doc_id) / "meta.json", None)


def update_doc(fid: str, doc_id: str, **kw) -> dict | None:
    with _lock:
        p = ddir(fid, doc_id) / "meta.json"
        meta = _read(p, None)
        if meta is None:
            return None
        meta.update(kw)
        _write(p, meta)
        return meta


def list_docs(fid: str) -> list[dict]:
    base = fdir(fid) / "documenti"
    if not base.is_dir():
        return []
    out = []
    for p in base.iterdir():
        m = _read(p / "meta.json", None)
        if m:
            out.append(m)
    out.sort(key=lambda m: m.get("aggiunto", ""))
    return out


def find_doc_by_source(fid: str, sorgente: str) -> dict | None:
    for d in list_docs(fid):
        if sorgente and d.get("sorgente") == sorgente:
            return d
    return None


def delete_doc(fid: str, doc_id: str):
    with _lock:
        shutil.rmtree(ddir(fid, doc_id), ignore_errors=True)
        est = fdir(fid) / "forensic" / "estrazioni" / f"{doc_id}.json"
        if est.exists():
            est.unlink()
    touch(fid)


def save_pages(fid: str, doc_id: str, pages: list[dict]):
    _write(ddir(fid, doc_id) / "pagine.json", pages)


def load_pages(fid: str, doc_id: str) -> list[dict]:
    return _read(ddir(fid, doc_id) / "pagine.json", [])


def doc_text(fid: str, doc_id: str) -> str:
    parts = []
    for pg in load_pages(fid, doc_id):
        if pg.get("text"):
            parts.append(f"--- {pg.get('label', 'Pag. ' + str(pg.get('n')))} ---\n{pg['text']}")
    return "\n".join(parts)


def doc_pdf(fid: str, doc_id: str) -> Path | None:
    p = ddir(fid, doc_id) / "documento.pdf"
    return p if p.is_file() else None


# ── JSON generici per area ────────────────────────────────────────────────────

def load_json(fid: str, rel: str, default):
    return _read(fdir(fid) / rel, default)


def save_json(fid: str, rel: str, data):
    with _lock:
        _write(fdir(fid) / rel, data)
