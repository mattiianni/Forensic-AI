"""
Area Ricerca: indice ibrido (FTS5 per parole esatte + embedding per significato)
e risposte del modello locale vincolate ai soli documenti del fascicolo, con citazioni.
"""
from __future__ import annotations

import re
import sqlite3
import threading
import time

import numpy as np

from server import jobs, runtime, store

CHUNK_CHARS = 1100
CHUNK_OVERLAP = 180
EMBED_BATCH = 24

_cache: dict[str, tuple[float, np.ndarray, list[int]]] = {}
_cache_lock = threading.Lock()


# ── Database ──────────────────────────────────────────────────────────────────

def _db(fid: str) -> sqlite3.Connection:
    path = store.fdir(fid) / "index.sqlite"
    con = sqlite3.connect(path, timeout=30, check_same_thread=False)
    con.execute("PRAGMA journal_mode=WAL")
    con.executescript("""
        CREATE TABLE IF NOT EXISTS chunks (
            id INTEGER PRIMARY KEY, doc_id TEXT, page INTEGER, label TEXT, text TEXT, emb BLOB);
        CREATE INDEX IF NOT EXISTS chunks_doc ON chunks(doc_id);
        CREATE VIRTUAL TABLE IF NOT EXISTS chunks_fts USING fts5(
            text, content='chunks', content_rowid='id', tokenize='unicode61 remove_diacritics 2');
        CREATE TRIGGER IF NOT EXISTS chunks_ai AFTER INSERT ON chunks BEGIN
            INSERT INTO chunks_fts(rowid, text) VALUES (new.id, new.text); END;
        CREATE TRIGGER IF NOT EXISTS chunks_ad AFTER DELETE ON chunks BEGIN
            INSERT INTO chunks_fts(chunks_fts, rowid, text) VALUES('delete', old.id, old.text); END;
    """)
    return con


def _invalidate(fid: str):
    with _cache_lock:
        _cache.pop(fid, None)


# ── Indicizzazione ────────────────────────────────────────────────────────────

def _split(text: str) -> list[str]:
    text = re.sub(r"[ \t]+", " ", text).strip()
    if len(text) <= CHUNK_CHARS:
        return [text] if text else []
    out, start = [], 0
    while start < len(text):
        end = min(len(text), start + CHUNK_CHARS)
        if end < len(text):  # taglia su fine frase/paragrafo se possibile
            cut = max(text.rfind("\n", start + CHUNK_CHARS // 2, end), text.rfind(". ", start + CHUNK_CHARS // 2, end))
            if cut > start:
                end = cut + 1
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(end - CHUNK_OVERLAP, start + 1)
    return [c for c in out if c]


def embed_available() -> bool:
    return any(m.startswith(runtime.EMBED_MODEL) for m in runtime.installed_models())


def _embed(texts: list[str], query: bool = False) -> np.ndarray:
    prefix = "task: search result | query: " if query else "title: none | text: "
    resp = runtime.client().embed(model=runtime.EMBED_MODEL, input=[prefix + t for t in texts])
    vecs = np.asarray(getattr(resp, "embeddings", None) or resp["embeddings"], dtype=np.float32)
    norms = np.linalg.norm(vecs, axis=1, keepdims=True)
    return vecs / np.maximum(norms, 1e-9)


def index_document(fid: str, doc_id: str, job_id: str | None = None, base: float = 0.0, weight: float = 1.0):
    pages = store.load_pages(fid, doc_id)
    rows = []
    for pg in pages:
        for chunk in _split(pg.get("text", "")):
            rows.append((doc_id, pg.get("n", 0), pg.get("label", ""), chunk))
    con = _db(fid)
    with con:
        con.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        ids = []
        for r in rows:
            cur = con.execute("INSERT INTO chunks(doc_id, page, label, text) VALUES (?,?,?,?)", r)
            ids.append(cur.lastrowid)
    semantic = False
    if rows and embed_available():
        semantic = True
        for i in range(0, len(rows), EMBED_BATCH):
            if job_id and jobs.is_cancelled(job_id):
                break
            batch = rows[i:i + EMBED_BATCH]
            try:
                vecs = _embed([r[3] for r in batch])
            except Exception:
                semantic = False
                break
            with con:
                for cid, v in zip(ids[i:i + EMBED_BATCH], vecs):
                    con.execute("UPDATE chunks SET emb=? WHERE id=?", (v.tobytes(), cid))
            if job_id:
                jobs.progress(job_id, base + weight * min(1.0, (i + len(batch)) / len(rows)),
                              f"Indicizzazione semantica · {i + len(batch)}/{len(rows)} passaggi")
    con.close()
    _invalidate(fid)
    store.update_doc(fid, doc_id, indicizzato=True, passaggi=len(rows), semantico=semantic)


def remove_document(fid: str, doc_id: str):
    try:
        con = _db(fid)
        with con:
            con.execute("DELETE FROM chunks WHERE doc_id=?", (doc_id,))
        con.close()
    except Exception:
        pass
    _invalidate(fid)


# ── Ricerca ibrida ────────────────────────────────────────────────────────────

def _matrix(fid: str, con) -> tuple[np.ndarray, list[int]]:
    path = store.fdir(fid) / "index.sqlite"
    mtime = path.stat().st_mtime if path.exists() else 0
    with _cache_lock:
        hit = _cache.get(fid)
        if hit and hit[0] == mtime:
            return hit[1], hit[2]
    ids, vecs = [], []
    for cid, blob in con.execute("SELECT id, emb FROM chunks WHERE emb IS NOT NULL"):
        ids.append(cid)
        vecs.append(np.frombuffer(blob, dtype=np.float32))
    mat = np.vstack(vecs) if vecs else np.zeros((0, 1), dtype=np.float32)
    with _cache_lock:
        _cache[fid] = (mtime, mat, ids)
    return mat, ids


_STOP = set("""il lo la i gli le un uno una di a da in con su per tra fra e o ma se che chi cosa come quando
dove quale quali quanto quanti del dello della dei degli delle al allo alla ai agli alle dal dallo dalla dai
dagli dalle nel nello nella nei negli nelle sul sullo sulla sui sugli sulle è sono ha hanno c'è ci vi non più
anche questo questa quello quella essere stato stata documento documenti fascicolo dimmi trova cerca elenca""".split())


def _fts_query(q: str) -> str:
    tokens = [t for t in re.findall(r"[\wÀ-ÿ'.\-/]+", q.lower()) if len(t) > 1 and t not in _STOP]
    terms = []
    for t in tokens[:24]:
        t = t.strip(".-/'")
        if t:
            terms.append('"' + t.replace('"', "") + '"')
    return " OR ".join(terms)


def search(fid: str, query: str, k: int = 8, doc_ids: list[str] | None = None, per_doc: int = 3) -> list[dict]:
    con = _db(fid)
    scores: dict[int, float] = {}
    RRF = 60.0

    fq = _fts_query(query)
    if fq:
        try:
            rows = con.execute(
                "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT 60", (fq,)).fetchall()
            for rank, (cid,) in enumerate(rows):
                scores[cid] = scores.get(cid, 0) + 1.0 / (RRF + rank)
        except sqlite3.OperationalError:
            pass

    mat, ids = _matrix(fid, con)
    if len(ids) and embed_available():
        try:
            qv = _embed([query], query=True)[0]
            sims = mat @ qv
            top = np.argsort(-sims)[:60]
            for rank, idx in enumerate(top):
                cid = ids[int(idx)]
                scores[cid] = scores.get(cid, 0) + 1.0 / (RRF + rank)
        except Exception:
            pass

    ordered = sorted(scores.items(), key=lambda kv: -kv[1])
    docs = {d["id"]: d for d in store.list_docs(fid)}
    out, count = [], {}
    for cid, sc in ordered:
        row = con.execute("SELECT doc_id, page, label, text FROM chunks WHERE id=?", (cid,)).fetchone()
        if not row:
            continue
        doc_id, page, label, text = row
        if doc_ids and doc_id not in doc_ids:
            continue
        if doc_id not in docs or count.get(doc_id, 0) >= per_doc:
            continue
        count[doc_id] = count.get(doc_id, 0) + 1
        out.append({"chunk_id": cid, "doc_id": doc_id, "documento": docs[doc_id]["nome"], "pagina": page,
                    "label": label or f"Pag. {page}", "testo": text, "score": round(sc, 5),
                    "ha_pdf": bool(docs[doc_id].get("pdf"))})
        if len(out) >= k:
            break
    con.close()
    return out


# ── Risposta con citazioni ────────────────────────────────────────────────────

SYSTEM = """Sei un motore di ricerca documentale. Il tuo unico compito è trovare e riportare informazioni
contenute nei PASSAGGI forniti, estratti dai documenti caricati dall'utente.

Regole vincolanti:
1. Riporta SOLO ciò che è scritto nei passaggi. Nessuna conoscenza esterna, nessuna supposizione.
2. Niente analisi, deduzioni, ipotesi, valutazioni, commenti investigativi, consigli o conclusioni:
   solo i fatti richiesti (nomi, date, importi, ruoli, indirizzi, codici, eventi) esattamente come risultano.
3. Incrocia i documenti: se l'informazione compare in più documenti, riportala da ciascuno;
   se i documenti riportano dati diversi sullo stesso punto, indica entrambi i valori con le rispettive fonti.
4. Dopo OGNI dato riportato indica il numero del passaggio da cui proviene tra parentesi quadre,
   es. [1] oppure [2][4]. Ogni frase con un dato deve avere il suo riferimento.
5. Se l'informazione non è presente, rispondi soltanto:
   "Nei documenti caricati non risulta …" e nient'altro.
6. Risposta in italiano, testo semplice, breve e preciso: frasi dirette o un elenco puntato.
   Niente titoli, introduzioni, riepiloghi finali o formule di cortesia.
"""


def riferimento(f: dict) -> str:
    """«File X, pagina N» (o foglio/sezione per i dati strutturati)."""
    label = f.get("label") or f"Pag. {f.get('pagina')}"
    if label.startswith("Pag. "):
        luogo = f"pagina {label[5:]}"
    elif label.startswith("Foglio"):
        luogo = "foglio " + label[7:]
    else:
        luogo = label[0].lower() + label[1:]
    return f"File {f['documento']}, {luogo}"


def cita(testo: str, fonti: list[dict]) -> str:
    """Sostituisce [1][3] con (File …, pagina …; File …, pagina …)."""
    def sost(m):
        nums = [int(n) for n in re.findall(r"\d+", m.group(0))]
        refs = []
        for n in nums:
            if 1 <= n <= len(fonti):
                r = riferimento(fonti[n - 1])
                if r not in refs:
                    refs.append(r)
        return f" ({'; '.join(refs)})" if refs else ""
    out = re.sub(r"\s*(?:\[\s*\d+(?:\s*[,;]\s*\d+)*\s*\])+", sost, testo)
    return re.sub(r" +([.,;:])", r"\1", out)


def _history(fid: str) -> list[dict]:
    return store.load_json(fid, "ricerca.json", {"messaggi": []}).get("messaggi", [])


def history(fid: str) -> list[dict]:
    return _history(fid)


def clear_history(fid: str):
    store.save_json(fid, "ricerca.json", {"messaggi": []})


def answer_job(job_id: str, fid: str, domanda: str, model: str, doc_ids: list[str] | None):
    t0 = time.time()
    storia = _history(fid)
    jobs.progress(job_id, 0.05, "Cerco nei documenti…")

    # Domanda di ricerca: per le domande brevi di continuazione aggiungo la precedente
    query = domanda
    precedenti = [m["content"] for m in storia if m["role"] == "user"]
    if precedenti and len(domanda.split()) < 7:
        query = precedenti[-1] + " " + domanda

    budget_chars = int((runtime.context_budget(model) - 2200) * 2.6)
    k = max(4, min(12, budget_chars // (CHUNK_CHARS + 120)))
    fonti = search(fid, query, k=k, doc_ids=doc_ids)
    jobs.emit(job_id, {"type": "sources", "sources": fonti})

    if not fonti:
        testo = ("Nei documenti caricati non ho trovato passaggi pertinenti a questa domanda. "
                 "Prova a riformularla con nomi, codici fiscali, date o termini presenti negli atti.")
        jobs.emit(job_id, {"type": "token", "text": testo})
        _save_turn(fid, domanda, testo, [], model, time.time() - t0)
        jobs.emit(job_id, {"type": "done", "elapsed": round(time.time() - t0, 1)})
        return

    blocchi = []
    for i, f in enumerate(fonti, start=1):
        blocchi.append(f"[{i}] Documento: «{f['documento']}» — {f['label']}\n{f['testo']}")
    contesto = "\n\n".join(blocchi)

    messages = [{"role": "system", "content": SYSTEM}]
    for m in storia[-4:]:
        messages.append({"role": m["role"], "content": m["content"]})
    messages.append({"role": "user", "content": f"PASSAGGI DAI DOCUMENTI:\n\n{contesto}\n\nDOMANDA: {domanda}"})

    jobs.progress(job_id, 0.2, f"Il modello legge {len(fonti)} passaggi…")
    opts = {"temperature": 0.0, "num_ctx": runtime.context_budget(model), "num_predict": 1200}
    threads = runtime.cpu_threads()
    if threads:
        opts["num_thread"] = threads
    parti = []
    for chunk in runtime.client().chat(model=model, messages=messages, stream=True, options=opts):
        if jobs.is_cancelled(job_id):
            break
        msg = getattr(chunk, "message", None) or chunk.get("message", {})
        frag = getattr(msg, "content", None) if not isinstance(msg, dict) else msg.get("content", "")
        if frag:
            parti.append(frag)
            jobs.emit(job_id, {"type": "token", "text": frag})
    testo = cita("".join(parti).strip(), fonti)
    _save_turn(fid, domanda, testo, fonti, model, time.time() - t0)
    jobs.emit(job_id, {"type": "done", "text": testo, "elapsed": round(time.time() - t0, 1)})


def _save_turn(fid, domanda, risposta, fonti, model, elapsed):
    data = store.load_json(fid, "ricerca.json", {"messaggi": []})
    data["messaggi"].append({"role": "user", "content": domanda})
    data["messaggi"].append({"role": "assistant", "content": risposta, "fonti": fonti,
                             "modello": model, "secondi": round(elapsed, 1)})
    store.save_json(fid, "ricerca.json", data)
