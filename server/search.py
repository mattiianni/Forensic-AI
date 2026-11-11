"""
Area Ricerca: indice ibrido (FTS5 per parole esatte + embedding per significato)
e risposte del modello locale vincolate ai soli documenti del fascicolo, con citazioni.
"""
from __future__ import annotations

import json
import re
import sqlite3
import threading
import time

import numpy as np

from server import jobs, runtime, store

CHUNK_CHARS = 1100
CHUNK_OVERLAP = 180
EMBED_BATCH = 24
SOGLIA_SIM = 0.12      # distanza massima (coseno) dal passaggio più pertinente

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


def _stem(t: str) -> str | None:
    """Radice grezza per l'italiano: «acquisito» → acquis* trova acquisizione, acquisto, acquisire…"""
    if len(t) < 6 or re.search(r"\d", t):
        return None
    return t[:max(5, len(t) - 3)]


def _fts_query(q: str) -> str:
    tokens = [t for t in re.findall(r"[\wÀ-ÿ'.\-/]+", q.lower()) if len(t) > 1 and t not in _STOP]
    terms: list[str] = []
    for t in tokens[:40]:
        t = t.strip(".-/'")
        if not t:
            continue
        for term in ('"' + t.replace('"', "") + '"', (f'"{_stem(t)}"*' if _stem(t) else None)):
            if term and term not in terms:
                terms.append(term)
    return " OR ".join(terms)


_vocab_cache: dict[str, tuple[float, set, dict]] = {}


def _vocab(fid: str, con) -> tuple[set, dict]:
    """Parole presenti nell'indice (per correggere nomi scritti male: «mannelli» → «manelli»)."""
    path = store.fdir(fid) / "index.sqlite"
    mtime = path.stat().st_mtime if path.exists() else 0
    hit = _vocab_cache.get(fid)
    if hit and hit[0] == mtime:
        return hit[1], hit[2]
    con.execute("CREATE VIRTUAL TABLE IF NOT EXISTS chunks_vocab USING fts5vocab(chunks_fts, 'row')")
    words = {t for (t,) in con.execute("SELECT term FROM chunks_vocab WHERE length(term) >= 4")}
    by_len: dict[int, list[str]] = {}
    for w in words:
        if not re.search(r"\d", w):
            by_len.setdefault(len(w), []).append(w)
    _vocab_cache[fid] = (mtime, words, by_len)
    return words, by_len


def correggi(fid: str, testo: str) -> dict[str, str]:
    """Parole della domanda assenti dai documenti → parola dei documenti più simile (errori di battitura)."""
    import difflib
    import unicodedata
    con = _db(fid)
    try:
        words, by_len = _vocab(fid, con)
    finally:
        con.close()
    out = {}
    for t in re.findall(r"[\wÀ-ÿ]+", testo.lower()):
        if len(t) < 5 or t in _STOP or re.search(r"\d", t):
            continue
        norm = "".join(c for c in unicodedata.normalize("NFD", t) if unicodedata.category(c) != "Mn")
        if norm in words or t in words:
            continue
        cand = [w for L in range(len(norm) - 2, len(norm) + 3) for w in by_len.get(L, [])]
        m = difflib.get_close_matches(norm, cand, n=1, cutoff=0.8)
        if m:
            out[t] = m[0]
    return out


def _unisci(a: str, b: str) -> str:
    """Unisce due passaggi consecutivi della stessa pagina togliendo la sovrapposizione."""
    for n in range(min(len(a), len(b), CHUNK_OVERLAP + 120), 15, -1):
        if a.endswith(b[:n]):
            return a + b[n:]
    return a + "\n" + b


def search(fid: str, query: str, k: int = 10, doc_ids: list[str] | None = None, per_doc: int = 5,
           termini: list[str] | None = None, min_k: int = 3) -> list[dict]:
    """
    Ricerca ibrida: parole (FTS5, anche per radice) + significato (embedding), fuse con RRF.
    Il numero di passaggi è variabile: si tengono solo quelli davvero vicini al migliore,
    e i passaggi consecutivi della stessa pagina vengono uniti in uno solo.
    """
    con = _db(fid)
    scores: dict[int, float] = {}
    fts_rank: dict[int, int] = {}
    sims_by_id: dict[int, float] = {}
    RRF = 60.0

    # nomi scritti male: aggiungo la forma presente nei documenti
    corr = correggi(fid, query + " " + " ".join(termini or []))
    # (le forme corrette si aggiungono, non sostituiscono: «soldi» non deve diventare «soli»)
    query_sem = query + (" " + " ".join(corr.values()) if corr else "")
    fq = _fts_query(query_sem + " " + " ".join(termini or []) + " " + " ".join(corr.values()))
    if fq:
        try:
            rows = con.execute(
                "SELECT rowid FROM chunks_fts WHERE chunks_fts MATCH ? ORDER BY bm25(chunks_fts) LIMIT 80", (fq,)).fetchall()
            for rank, (cid,) in enumerate(rows):
                fts_rank[cid] = rank
                scores[cid] = scores.get(cid, 0) + 1.0 / (RRF + rank)
        except sqlite3.OperationalError:
            pass

    mat, ids = _matrix(fid, con)
    if len(ids) and embed_available():
        try:
            qv = _embed([query_sem], query=True)[0]
            sims = mat @ qv
            sims_by_id = {ids[i]: float(sims[i]) for i in range(len(ids))}
            top = np.argsort(-sims)[:80]
            for rank, idx in enumerate(top):
                cid = ids[int(idx)]
                scores[cid] = scores.get(cid, 0) + 1.2 / (RRF + rank)   # il significato pesa un po' di più
        except Exception:
            pass

    ordered = sorted(scores.items(), key=lambda kv: -kv[1])
    best_sim = max((sims_by_id.get(c, 0.0) for c, _ in ordered[:10]), default=0.0)
    docs = {d["id"]: d for d in store.list_docs(fid)}
    out: list[dict] = []
    count: dict[str, int] = {}
    for cid, sc in ordered:
        if len(out) >= k:
            break
        row = con.execute("SELECT doc_id, page, label, text FROM chunks WHERE id=?", (cid,)).fetchone()
        if not row:
            continue
        doc_id, page, label, text = row
        if doc_ids and doc_id not in doc_ids:
            continue
        if doc_id not in docs:
            continue
        # soglia di pertinenza: oltre i primi min_k, solo passaggi vicini al migliore o forti per parole chiave
        if len(out) >= min_k and sims_by_id:
            sim = sims_by_id.get(cid, 0.0)
            if sim < best_sim - SOGLIA_SIM and fts_rank.get(cid, 999) > 4:
                continue
        # passaggio consecutivo di uno già scelto (stessa pagina): unisci invece di sprecare un posto
        vicino = next((f for f in out if f["doc_id"] == doc_id and f["pagina"] == page
                       and (cid - 1 in f["_ids"] or cid + 1 in f["_ids"]) and len(f["_ids"]) < 3), None)
        if vicino:
            if cid > max(vicino["_ids"]):
                vicino["testo"] = _unisci(vicino["testo"], text)
            else:
                vicino["testo"] = _unisci(text, vicino["testo"])
            vicino["_ids"].append(cid)
            continue
        if count.get(doc_id, 0) >= per_doc:
            continue
        count[doc_id] = count.get(doc_id, 0) + 1
        out.append({"chunk_id": cid, "_ids": [cid], "doc_id": doc_id, "documento": docs[doc_id]["nome"], "pagina": page,
                    "label": label or f"Pag. {page}", "testo": text, "score": round(sc, 5),
                    "pertinenza": round(sims_by_id.get(cid, 0.0), 3),
                    "ha_pdf": bool(docs[doc_id].get("pdf"))})
    con.close()
    for f in out:
        f.pop("_ids", None)
    return out


# ── Risposta con citazioni ────────────────────────────────────────────────────

SYSTEM = """Sei un motore di ricerca documentale. Il tuo unico compito è rispondere alla DOMANDA usando
SOLO i PASSAGGI forniti, estratti dai documenti caricati dall'utente.

Come lavori:
1. Leggi TUTTI i passaggi prima di rispondere e individua quelli che riguardano davvero i soggetti e il fatto chiesti.
2. Rispondi esattamente a ciò che è chiesto. Se la domanda chiede «quando», la risposta inizia con la data.
3. Se il fatto non è descritto con le stesse parole della domanda, riporta i fatti dei passaggi che vi rispondono
   (es. per «quando X ha acquisito Y»: costituzione, conferimenti, cessioni o trasferimenti di quote, data da cui
   X risulta socio), in ordine cronologico, e precisa che un atto con quel nome non risulta.
4. Ogni data, importo, nome o codice va copiato esattamente dal passaggio in cui è riferito a QUEL fatto:
   non attribuire mai una data o un importo a un fatto diverso da quello a cui il passaggio lo collega.
5. Nessuna conoscenza esterna, supposizione, analisi, valutazione, consiglio o conclusione: solo fatti.
6. Incrocia i documenti: se il dato compare in più passaggi riportalo con tutte le fonti; se i documenti
   riportano valori diversi sullo stesso punto, indica entrambi con le rispettive fonti.
7. Dopo OGNI dato indica tra parentesi quadre il numero del passaggio da cui proviene, es. [1] oppure [2][4].
8. Le risposte precedenti della conversazione possono essere sbagliate o incomplete: verifica sempre sui passaggi
   e, se l'utente corregge o precisa la domanda, rispondi alla domanda precisata.
9. Se nessun passaggio contiene l'informazione, rispondi soltanto: "Nei documenti caricati non risulta …".
10. Italiano, testo semplice, breve e preciso: frasi dirette o elenco puntato. Niente titoli, introduzioni,
    riepiloghi o formule di cortesia.
"""

RIFORMULA = """Ricevi una conversazione e l'ultima domanda dell'utente su un fascicolo di documenti.
1. Riscrivi l'ultima domanda come domanda autonoma e completa: sostituisci pronomi e riferimenti impliciti
   («l'ha», «lei», «quella società», «e invece…») con i nomi a cui si riferiscono nella conversazione,
   e tieni conto delle correzioni dell'utente («non ti ho chiesto X, ti ho chiesto Y» → la domanda è Y).
2. Elenca da 3 a 8 termini di ricerca: nomi propri, sigle, codici, e i termini giuridico-amministrativi
   con cui il fatto può essere scritto negli atti (es. acquisizione → cessione di quote, trasferimento di
   partecipazioni, conferimento, socio unico; presidente → presidente del consiglio di amministrazione).
Rispondi SOLO con JSON: {"domanda": "...", "termini": ["...", "..."]}"""


def _senza_citazioni(t: str) -> str:
    return re.sub(r"\s*\((?:File [^()]*)\)", "", t or "").strip()


def riformula(storia: list[dict], domanda: str, model: str) -> tuple[str, list[str]]:
    """Domanda autonoma + termini di ricerca (risolve i riferimenti alle domande precedenti)."""
    turni = []
    for m in storia[-6:]:
        chi = "Utente" if m["role"] == "user" else "Risposta"
        turni.append(f"{chi}: {_senza_citazioni(m['content'])[:500]}")
    prompt = ("CONVERSAZIONE:\n" + ("\n".join(turni) if turni else "(nessuna)") +
              f"\n\nULTIMA DOMANDA: {domanda}")
    try:
        r = runtime.client().chat(model=model, format="json", stream=False,
                                  messages=[{"role": "system", "content": RIFORMULA}, {"role": "user", "content": prompt}],
                                  options={"temperature": 0.0, "num_ctx": 4096, "num_predict": 220})
        msg = getattr(r, "message", None) or r["message"]
        data = json.loads(getattr(msg, "content", None) if not isinstance(msg, dict) else msg["content"])
        q = str(data.get("domanda") or "").strip() or domanda
        termini = [str(t).strip() for t in (data.get("termini") or []) if str(t).strip()][:10]
        return q, termini
    except Exception:
        precedenti = [m["content"] for m in storia if m["role"] == "user"]
        if precedenti and len(domanda.split()) < 7:
            return precedenti[-1] + " " + domanda, []
        return domanda, []


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
    jobs.progress(job_id, 0.04, "Interpreto la domanda…")
    query, termini = riformula(storia, domanda, model)
    if jobs.is_cancelled(job_id):
        return
    corr = correggi(fid, query + " " + domanda)   # «mannelli» → «manelli»

    jobs.progress(job_id, 0.12, "Cerco nei documenti…")
    budget_chars = int((runtime.context_budget(model) - 2600) * 2.6)
    k = max(4, min(10, budget_chars // (CHUNK_CHARS * 2)))
    fonti = search(fid, query, k=k, doc_ids=doc_ids, termini=termini)
    jobs.emit(job_id, {"type": "sources", "sources": fonti, "query": query})

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

    turni = []
    for m in storia[-4:]:
        chi = "Utente" if m["role"] == "user" else "Risposta precedente"
        turni.append(f"{chi}: {_senza_citazioni(m['content'])[:600]}")
    conv = ("CONVERSAZIONE PRECEDENTE (solo per capire la domanda; può contenere errori):\n" + "\n".join(turni) + "\n\n") if turni else ""
    precisata = f"\n(Domanda completa: {query})" if query.strip().lower() != domanda.strip().lower() else ""
    if corr:
        precisata += ("\n(Parole della domanda che nei documenti potrebbero essere scritte così: "
                      + ", ".join(f"{a} → {b}" for a, b in corr.items()) + ")")

    messages = [{"role": "system", "content": SYSTEM},
                {"role": "user", "content": f"{conv}PASSAGGI DAI DOCUMENTI:\n\n{contesto}\n\nDOMANDA: {domanda}{precisata}"}]

    jobs.progress(job_id, 0.2, f"Il modello legge {len(fonti)} passaggi pertinenti…")
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
