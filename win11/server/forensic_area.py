"""Area Forensic AI: estrazione entità/relazioni, grafo, chat ibrida, dossier, analytics, export."""
from __future__ import annotations

import json
import threading
import time
from datetime import datetime

from flask import Blueprint, jsonify, request

from forensic.ai_engine import (estrai_entita_e_relazioni_avanzato, genera_deduzioni,
                                genera_dossier_forense_globale)
from forensic.graph_manager import GestoreGrafo
from forensic.parser import suddividi_in_blocchi
from server import jobs, runtime, store

bp = Blueprint("forensic_area", __name__)

_grafi: dict[str, GestoreGrafo] = {}
_grafi_lock = threading.RLock()


def _jsonable(o):
    if isinstance(o, set):
        return sorted(o)
    if isinstance(o, (datetime,)):
        return o.isoformat()
    return str(o)


def _ok(data):
    return app_json(data)


def app_json(data, status=200):
    return (json.dumps(data, ensure_ascii=False, default=_jsonable), status,
            {"Content-Type": "application/json; charset=utf-8"})


# ── Stato persistente ─────────────────────────────────────────────────────────

def _stato(fid: str) -> dict:
    return store.load_json(fid, "forensic/stato.json",
                           {"ordine": [], "storico": [], "chat": [], "dossier": None, "dossier_ts": None})


def _salva_stato(fid: str, stato: dict):
    store.save_json(fid, "forensic/stato.json", stato)


def grafo(fid: str) -> GestoreGrafo:
    """Grafo in memoria ricostruito rigiocando le estrazioni salvate (nessuna chiamata IA)."""
    with _grafi_lock:
        g = _grafi.get(fid)
        if g is None:
            g = GestoreGrafo()
            docs = {d["id"]: d for d in store.list_docs(fid)}
            for doc_id in _stato(fid)["ordine"]:
                if doc_id in docs:
                    est = store.load_json(fid, f"forensic/estrazioni/{doc_id}.json", None)
                    if est:
                        g.aggiungi_dati(est, docs[doc_id]["nome"])
            _grafi[fid] = g
        return g


def invalida(fid: str):
    with _grafi_lock:
        _grafi.pop(fid, None)


# ── Analisi documenti ─────────────────────────────────────────────────────────

def _analizza_job(job_id: str, fid: str, doc_ids: list[str], model: str):
    n = len(doc_ids)
    g = grafo(fid)
    for i, doc_id in enumerate(doc_ids):
        if jobs.is_cancelled(job_id):
            break
        meta = store.doc(fid, doc_id)
        if not meta:
            continue
        nome = meta["nome"]
        base, peso = i / n, 1 / n
        testo = store.doc_text(fid, doc_id)
        jobs.log(job_id, f"[{i + 1}/{n}] {nome}")
        if not testo.strip():
            jobs.log(job_id, "  ⚠ Nessun testo leggibile: documento saltato", "warning")
            store.update_doc(fid, doc_id, analizzato=True, analisi_avviso="Nessun testo leggibile")
            continue
        t0 = time.time()

        def cb(perc, msg, tokens=0, elapsed=0.0, _b=base, _p=peso, _n=nome):
            frac = _b + _p * min(0.99, perc)
            extra = f" · {tokens} token" if tokens else ""
            jobs.progress(job_id, frac, f"{_n} · {_pulisci(msg)}{extra}", doc_id=doc_id)

        jobs.progress(job_id, base, f"{nome} · Estrazione soggetti e relazioni", doc_id=doc_id)
        blocchi = suddividi_in_blocchi(testo, dimensione_blocco=22000, sovrapposizione=2000)
        dati = estrai_entita_e_relazioni_avanzato(blocchi, nome, model=model, callback_progresso=cb,
                                                  base_perc=0.0, peso_perc=0.6)
        store.save_json(fid, f"forensic/estrazioni/{doc_id}.json", dati)
        ne, nr = len(dati.get("entita", [])), len(dati.get("relazioni", []))
        jobs.log(job_id, f"  ✓ Estratti {ne} soggetti e {nr} relazioni", "success" if ne else "warning")
        with _grafi_lock:
            g.aggiungi_dati(dati, nome)

        jobs.progress(job_id, base + peso * 0.65, f"{nome} · Deduzioni incrociate", doc_id=doc_id)
        deduzione = genera_deduzioni(g.ottieni_riassunto(), testo, nome, model=model,
                                     callback_progresso=cb, base_perc=0.65, peso_perc=0.34)
        stato = _stato(fid)
        if doc_id not in stato["ordine"]:
            stato["ordine"].append(doc_id)
        stato["storico"] = [s for s in stato["storico"] if s.get("doc_id") != doc_id]
        stato["storico"].insert(0, {"doc_id": doc_id, "file": nome, "analisi": deduzione,
                                    "caratteri": len(testo), "secondi": round(time.time() - t0),
                                    "modello": model, "timestamp": datetime.now().strftime("%d/%m/%Y %H:%M")})
        _salva_stato(fid, stato)
        store.update_doc(fid, doc_id, analizzato=True)
        if deduzione.startswith("Errore"):
            jobs.log(job_id, f"  ✗ {deduzione[:300]}", "error")
        else:
            jobs.log(job_id, f"  ✓ Deduzioni incrociate completate ({round(time.time() - t0)} s)", "success")
        jobs.emit(job_id, {"type": "docs_changed"})
    jobs.progress(job_id, 1.0, "Analisi completata")
    jobs.emit(job_id, {"type": "done"})


def _pulisci(msg: str) -> str:
    """Toglie emoji e prefissi tecnici dai messaggi del motore."""
    import re
    msg = re.sub(r"[\U0001F300-\U0001FAFF☀-➿]️?", "", msg)
    msg = re.sub(r"\[Fase \d/\d\]\s*", "", msg)
    return msg.strip()


@bp.route("/api/forensic/<fid>/analyze", methods=["POST"])
def analyze(fid):
    data = request.get_json() or {}
    model = data.get("model") or runtime.recommended_model(runtime.installed_models())
    docs = store.list_docs(fid)
    if data.get("doc_ids"):
        ids = [d["id"] for d in docs if d["id"] in set(data["doc_ids"])]
    else:
        ids = [d["id"] for d in docs if not d.get("analizzato") and d.get("stato") in ("pronto", "avviso")]
    if not ids:
        return jsonify({"error": "Nessun documento da analizzare"}), 400
    job_id = jobs.create("forensic", label=f"Analisi forense · {len(ids)} documenti", fid=fid)
    jobs.run(job_id, _analizza_job, fid, ids, model)
    return jsonify({"job_id": job_id, "count": len(ids)})


@bp.route("/api/forensic/<fid>/reset", methods=["POST"])
def reset(fid):
    _salva_stato(fid, {"ordine": [], "storico": [], "chat": [], "dossier": None, "dossier_ts": None})
    import shutil
    shutil.rmtree(store.fdir(fid) / "forensic" / "estrazioni", ignore_errors=True)
    for d in store.list_docs(fid):
        store.update_doc(fid, d["id"], analizzato=False)
    invalida(fid)
    return jsonify({"ok": True})


def rimuovi_documento(fid: str, doc_id: str):
    stato = _stato(fid)
    if doc_id in stato["ordine"]:
        stato["ordine"].remove(doc_id)
        stato["storico"] = [s for s in stato["storico"] if s.get("doc_id") != doc_id]
        _salva_stato(fid, stato)
    invalida(fid)


# ── Panoramica ────────────────────────────────────────────────────────────────

@bp.route("/api/forensic/<fid>/overview")
def overview(fid):
    g = grafo(fid)
    stato = _stato(fid)
    schemi = g.rileva_schemi_investigativi_topologici()
    try:
        tot = g.db.execute("SELECT SUM(valore_numerico), COUNT(*) FROM relazioni WHERE valore_numerico > 0").fetchall()[0]
    except Exception:
        tot = (0, 0)
    docs = store.list_docs(fid)
    return _ok({
        "entita": len(g.grafo.nodes), "relazioni": len(g.grafo.edges),
        "documenti_analizzati": len(stato["ordine"]),
        "documenti_da_analizzare": len([d for d in docs if not d.get("analizzato") and d.get("stato") in ("pronto", "avviso")]),
        "documenti_in_lavorazione": len([d for d in docs if d.get("stato") in ("in_coda", "elaborazione", "indicizzazione")]),
        "flussi_circolari": len(schemi.get("flussi_circolari", [])),
        "hub": len(schemi.get("hub_dominus", [])),
        "scatole_cinesi": len(schemi.get("scatole_cinesi", [])),
        "incongruenze": len(schemi.get("incongruenze", [])),
        "soggetti_trasversali": len(g.trova_soggetti_trasversali()),
        "volume_euro": tot[0] or 0, "transazioni": tot[1] or 0,
        "storico": stato["storico"],
        "dossier_ts": stato.get("dossier_ts"),
    })


# ── Chat ibrida (cammini minimi deterministici + LLM) ─────────────────────────

_PAROLE_VUOTE = {"chi", "che", "cosa", "con", "tra", "del", "della", "delle", "dei", "negli", "nella", "ha",
                 "hanno", "avuto", "contatti", "legami", "quote", "detiene", "partecipazioni", "società",
                 "conto", "iban"}


def _chat_job(job_id: str, fid: str, domanda: str, model: str):
    g = grafo(fid)
    stato = _stato(fid)
    q_lower = domanda.lower()
    soggetti = []
    norm_q = domanda.upper().replace(" ", "_")
    for n in list(g.grafo.nodes):
        norm_n = g.normalizza_nome(n)
        if n.lower() in q_lower or (len(norm_n) > 4 and norm_n in norm_q):
            soggetti.append(n)
    if len(soggetti) < 2:
        for p in [p for p in domanda.split() if len(p) >= 3 and p.lower() not in _PAROLE_VUOTE]:
            r = g._risolvi_nome_per_ricerca(p)
            if r and r not in soggetti:
                soggetti.append(r)

    riscontro = ""
    if any(k in q_lower for k in ["contatt", "collegat", "legam", "rapport", "passaggi", "conness"]) and len(soggetti) >= 2:
        riscontro = g.analizza_contatti(soggetti[0], soggetti[1])
    elif any(k in q_lower for k in ["detiene", "partecip", "possied", "quot", "carich", "amministra", "ruol"]) and soggetti:
        riscontro = g.calcola_partecipazioni(soggetti[0])
    if riscontro:
        jobs.emit(job_id, {"type": "graph_fact", "text": riscontro})

    sistema = f"""Sei un Perito Forense Antiriciclaggio (AML) e Investigatore della Guardia di Finanza.
Rispondi alla domanda dell'utente con massimo rigore, chiarezza motivazionale e citando le fonti degli atti.

RISCONTRI MATEMATICI DETERMINISTICI (PREVALENZA ASSOLUTA - NON CONTRADDIRE QUESTI FATTI):
{riscontro or "Nessun vincolo di cammino matematico puntuale applicabile."}

QUADRO COMPLESSIVO DELLA RETE D'INDAGINE:
{g.ottieni_riassunto()[:int((runtime.context_budget(model) - 3000) * 2.6)]}
"""
    messaggi = [{"role": "system", "content": sistema}]
    messaggi += [{"role": m["role"], "content": m["content"]} for m in stato["chat"][-6:]]
    messaggi.append({"role": "user", "content": domanda})
    opts = {"temperature": 0.1, "num_ctx": runtime.context_budget(model), "num_predict": 1500}
    parti = []
    t0 = time.time()
    for chunk in runtime.client().chat(model=model, messages=messaggi, stream=True, options=opts):
        if jobs.is_cancelled(job_id):
            break
        msg = getattr(chunk, "message", None) or chunk.get("message", {})
        frag = msg.get("content", "") if isinstance(msg, dict) else (msg.content or "")
        if frag:
            parti.append(frag)
            jobs.emit(job_id, {"type": "token", "text": frag})
    risposta = "".join(parti).strip()
    stato = _stato(fid)
    stato["chat"].append({"role": "user", "content": domanda})
    stato["chat"].append({"role": "assistant", "content": risposta, "riscontro": riscontro,
                          "modello": model, "secondi": round(time.time() - t0, 1)})
    _salva_stato(fid, stato)
    jobs.emit(job_id, {"type": "done"})


@bp.route("/api/forensic/<fid>/chat", methods=["GET", "POST", "DELETE"])
def chat(fid):
    if request.method == "GET":
        return _ok({"messaggi": _stato(fid)["chat"]})
    if request.method == "DELETE":
        stato = _stato(fid)
        stato["chat"] = []
        _salva_stato(fid, stato)
        return jsonify({"ok": True})
    data = request.get_json() or {}
    domanda = (data.get("message") or "").strip()
    if not domanda:
        return jsonify({"error": "Domanda vuota"}), 400
    model = data.get("model") or runtime.recommended_model(runtime.installed_models())
    job_id = jobs.create("forensic_chat", label="Chat forense", fid=fid)
    jobs.run(job_id, _chat_job, fid, domanda, model)
    return jsonify({"job_id": job_id})


# ── Dossier ───────────────────────────────────────────────────────────────────

def _dossier_job(job_id: str, fid: str, model: str):
    g = grafo(fid)
    stato = _stato(fid)
    docs = {d["id"]: d for d in store.list_docs(fid)}
    testi = {docs[d]["nome"]: store.doc_text(fid, d) for d in stato["ordine"] if d in docs}
    ricevuti = []

    def cb(perc, msg, tokens=0, elapsed=0.0):
        # il motore storico riporta 0,72 → 1,0 (fase finale della vecchia pipeline): riscalato su 0 → 1
        frac = max(0.0, (perc - 0.72) / 0.28) if perc >= 0.72 else perc
        jobs.progress(job_id, frac, _pulisci(msg) + (f" · {tokens} token" if tokens else ""))

    # streaming del testo: intercettiamo i token dal client
    jobs.log(job_id, f"Redazione del dossier su {len(testi)} atti con {model}")
    testo = genera_dossier_forense_globale(g, testi, model=model, ha_grafo=True, callback_progresso=cb)
    if testo.startswith("Errore"):
        jobs.log(job_id, testo[:300], "error")
    else:
        jobs.log(job_id, f"✓ Dossier completato ({len(testo.split())} parole)", "success")
    jobs.progress(job_id, 1.0, "Dossier completato")
    stato = _stato(fid)
    stato["dossier"] = testo
    stato["dossier_ts"] = datetime.now().strftime("%d/%m/%Y %H:%M")
    stato["dossier_modello"] = model
    _salva_stato(fid, stato)
    jobs.emit(job_id, {"type": "done", "text": testo})
    del ricevuti


@bp.route("/api/forensic/<fid>/dossier", methods=["GET", "POST"])
def dossier(fid):
    if request.method == "GET":
        s = _stato(fid)
        return _ok({"testo": s.get("dossier"), "ts": s.get("dossier_ts"), "modello": s.get("dossier_modello")})
    if not _stato(fid)["ordine"]:
        return jsonify({"error": "Analizza prima almeno un documento"}), 400
    model = (request.get_json() or {}).get("model") or runtime.recommended_model(runtime.installed_models())
    job_id = jobs.create("dossier", label="Dossier CTU", fid=fid)
    jobs.run(job_id, _dossier_job, fid, model)
    return jsonify({"job_id": job_id})


# ── Grafo, pattern, timeline, anagrafiche ─────────────────────────────────────

@bp.route("/api/forensic/<fid>/graph")
def graph(fid):
    g = grafo(fid)
    data = g.dati_vis()
    data["cicli"] = g.trova_cicli()
    return _ok(data)


@bp.route("/api/forensic/<fid>/patterns")
def patterns(fid):
    g = grafo(fid)
    try:
        ubos = [u for u in g.ftm_dataset.risolvi_titolari_effettivi() if u["titolari_effettivi"] or u["amministratori"]]
    except Exception:
        ubos = []
    fin = [m for m in g.calcola_matrice_riconciliazione_finanziaria() if m["entrate_euro"] > 0 or m["uscite_euro"] > 0]
    return _ok({
        "centralita": g.calcola_metriche_centralita_forense()[:15],
        "ubo": ubos,
        "finanza": fin,
        "schemi": g.rileva_schemi_investigativi_topologici(),
    })


@bp.route("/api/forensic/<fid>/timeline")
def timeline(fid):
    return _ok({"eventi": grafo(fid).ottieni_timeline_forense()})


@bp.route("/api/forensic/<fid>/registry")
def registry(fid):
    g = grafo(fid)
    soggetti = []
    for nodo_id, data in sorted(g.grafo.nodes(data=True), key=lambda x: x[0]):
        meta = g.dati_nodi.get(nodo_id, {})
        soggetti.append({"id": nodo_id, "tipo": meta.get("tipo") or data.get("tipo", "ALTRO"),
                         "cf_piva": meta.get("cf_piva") or data.get("cf_piva", ""),
                         "fonti": sorted(meta.get("fonti") or {data.get("fonte", "")}),
                         "ruoli": sorted(meta.get("ruoli", set()))[:12]})
    return _ok({"trasversali": g.trova_soggetti_trasversali(), "soggetti": soggetti, "ftm": g.statistiche_ftm()})


@bp.route("/api/forensic/<fid>/sql", methods=["POST"])
def sql(fid):
    q = ((request.get_json() or {}).get("query") or "").strip()
    if not q:
        return jsonify({"error": "Query vuota"}), 400
    righe = grafo(fid).esegui_query_sql(q)
    return _ok({"righe": righe})


# ── Esportazioni ──────────────────────────────────────────────────────────────

def contenuto_export(fid: str, tipo: str) -> str:
    g = grafo(fid)
    stato = _stato(fid)
    if tipo == "ftm":
        return g.esporta_followthemoney_jsonl()
    if tipo == "cytoscape":
        return json.dumps(g.esporta_progetto_pdf_relations(), indent=2, ensure_ascii=False, default=_jsonable)
    if tipo == "mermaid_td":
        return g.esporta_mermaid(orientamento="TD")
    if tipo == "mermaid_lr":
        return g.esporta_mermaid(orientamento="LR")
    if tipo == "dossier":
        return stato.get("dossier") or ""
    if tipo == "sessione":
        return json.dumps({"grafo_dati": g.esporta_stato(), "dossier_globale": stato.get("dossier"),
                           "storico": stato["storico"], "chat_messages": stato["chat"]},
                          indent=2, ensure_ascii=False, default=_jsonable)
    raise ValueError("Formato non supportato")


@bp.route("/api/forensic/<fid>/export", methods=["POST"])
def export(fid):
    data = request.get_json() or {}
    path = (data.get("path") or "").strip()
    if not path:
        return jsonify({"error": "Percorso mancante"}), 400
    try:
        testo = contenuto_export(fid, data.get("tipo", ""))
    except ValueError as e:
        return jsonify({"error": str(e)}), 400
    with open(path, "w", encoding="utf-8") as f:
        f.write(testo)
    return jsonify({"ok": True, "path": path})
