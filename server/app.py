"""Server Flask locale di Forensic Tools: UI statica + API delle tre aree e del fascicolo."""
from __future__ import annotations

import os
import subprocess

from flask import Flask, abort, jsonify, request, send_file, send_from_directory

from server import forensic_area, jobs, pipeline, runtime, search, store
from server.pdf_area import bp as pdf_bp

UI_DIR = runtime.APP_DIR / "ui"


def create_app() -> Flask:
    app = Flask(__name__, static_folder=None)
    app.config["MAX_CONTENT_LENGTH"] = 10 * 1024 ** 3
    app.json.ensure_ascii = False
    app.register_blueprint(pdf_bp)
    app.register_blueprint(forensic_area.bp)

    @app.after_request
    def _no_cache(resp):
        resp.headers["Cache-Control"] = "no-store"
        return resp

    # ── UI ────────────────────────────────────────────────────────────────
    @app.route("/")
    def index():
        return send_from_directory(UI_DIR, "index.html")

    @app.route("/ui/<path:filename>")
    def ui(filename):
        return send_from_directory(UI_DIR, filename)

    # ── Stato generale ────────────────────────────────────────────────────
    @app.route("/api/status")
    def status():
        return jsonify(runtime.system_status())

    @app.route("/api/models")
    def models():
        installed = runtime.installed_models()
        out = []
        for m in runtime.MODEL_CATALOG:
            if m["id"] in installed:
                out.append(m)
        for n in installed:
            if n not in [m["id"] for m in out] and "embed" not in n:
                out.append({"id": n, "label": n, "desc": "", "min_ram": 0})
        return jsonify({"models": out, "recommended": runtime.recommended_model(installed),
                        "ram_gb": round(runtime.ram_gb())})

    @app.route("/api/prefs", methods=["GET", "POST"])
    def prefs():
        if request.method == "POST":
            store.set_app_state(**(request.get_json() or {}))
        return jsonify(store.app_state())

    @app.route("/api/jobs/active")
    def jobs_active():
        return jsonify({"jobs": jobs.active(request.args.get("fid"))})

    @app.route("/api/jobs/recent")
    def jobs_recent():
        return jsonify({"jobs": jobs.recent(request.args.get("fid"))})

    @app.route("/api/jobs/<job_id>/stream")
    def job_stream(job_id):
        return jobs.stream(job_id)

    @app.route("/api/jobs/<job_id>/cancel", methods=["POST"])
    def job_cancel(job_id):
        jobs.cancel(job_id)
        return jsonify({"ok": True})

    # ── Fascicoli ─────────────────────────────────────────────────────────
    @app.route("/api/fascicoli", methods=["GET", "POST"])
    def fascicoli():
        if request.method == "POST":
            meta = store.create((request.get_json() or {}).get("nome", ""))
            store.set_app_state(fascicolo_corrente=meta["id"])
            return jsonify(store.get(meta["id"]))
        return jsonify({"fascicoli": store.list_all(), "corrente": store.current_or_default()})

    @app.route("/api/fascicoli/<fid>", methods=["GET", "PATCH", "DELETE"])
    def fascicolo(fid):
        if not store.exists(fid):
            abort(404)
        if request.method == "PATCH":
            store.rename(fid, (request.get_json() or {}).get("nome", ""))
        elif request.method == "DELETE":
            store.delete(fid)
            forensic_area.invalida(fid)
            return jsonify({"ok": True, "corrente": store.current_or_default()})
        else:
            store.set_app_state(fascicolo_corrente=fid)
        return jsonify(store.get(fid))

    @app.route("/api/fascicoli/<fid>/documenti")
    def documenti(fid):
        if not store.exists(fid):
            abort(404)
        return jsonify({"documenti": store.list_docs(fid), "jobs": jobs.active(fid)})

    @app.route("/api/fascicoli/<fid>/documenti", methods=["POST"])
    def aggiungi(fid):
        paths = (request.get_json() or {}).get("paths", [])
        if not store.exists(fid) or not paths:
            return jsonify({"error": "Nessun file"}), 400
        n = len(pipeline.expand_paths(paths))
        if n == 0:
            return jsonify({"error": "Nessun file in un formato supportato"}), 400
        job_id = jobs.create("ingest", label=f"Acquisizione {n} documenti", fid=fid)
        jobs.run(job_id, pipeline.ingest_job, fid, paths)
        return jsonify({"job_id": job_id, "count": n})

    @app.route("/api/fascicoli/<fid>/documenti/<doc_id>", methods=["DELETE"])
    def rimuovi(fid, doc_id):
        search.remove_document(fid, doc_id)
        forensic_area.rimuovi_documento(fid, doc_id)
        store.delete_doc(fid, doc_id)
        return jsonify({"ok": True})

    @app.route("/api/fascicoli/<fid>/documenti/<doc_id>/reprocess", methods=["POST"])
    def rielabora(fid, doc_id):
        meta = store.doc(fid, doc_id)
        if not meta:
            abort(404)
        orig = next(iter(store.ddir(fid, doc_id).glob("originale*")), None)
        src = meta.get("sorgente") if meta.get("sorgente") and os.path.exists(meta["sorgente"]) else str(orig)
        job_id = jobs.create("ingest", label=f"Rielaborazione {meta['nome']}", fid=fid)
        jobs.run(job_id, lambda j: (pipeline.process_document(fid, doc_id, src, j),
                                    jobs.emit(j, {"type": "done"})))
        return jsonify({"job_id": job_id})

    @app.route("/api/fascicoli/<fid>/documenti/<doc_id>/pdf")
    def doc_pdf(fid, doc_id):
        p = store.doc_pdf(fid, doc_id)
        if not p:
            abort(404)
        return send_file(p, mimetype="application/pdf")

    @app.route("/api/fascicoli/<fid>/documenti/<doc_id>/pagine")
    def doc_pages(fid, doc_id):
        return jsonify({"pagine": store.load_pages(fid, doc_id), "meta": store.doc(fid, doc_id)})

    @app.route("/api/fascicoli/<fid>/documenti/<doc_id>/apri", methods=["POST"])
    def doc_open(fid, doc_id):
        """Apre il PDF (o l'originale) nell'app predefinita di macOS."""
        p = store.doc_pdf(fid, doc_id) or next(iter(store.ddir(fid, doc_id).glob("originale*")), None)
        if p:
            subprocess.Popen(["open", str(p)])
        return jsonify({"ok": bool(p)})

    # ── Ricerca ───────────────────────────────────────────────────────────
    @app.route("/api/ricerca/<fid>", methods=["GET", "DELETE"])
    def ricerca_storia(fid):
        if request.method == "DELETE":
            search.clear_history(fid)
            return jsonify({"ok": True})
        return jsonify({"messaggi": search.history(fid)})

    @app.route("/api/ricerca/<fid>/ask", methods=["POST"])
    def ricerca_ask(fid):
        data = request.get_json() or {}
        domanda = (data.get("question") or "").strip()
        if not domanda:
            return jsonify({"error": "Domanda vuota"}), 400
        model = data.get("model") or runtime.recommended_model(runtime.installed_models())
        job_id = jobs.create("ricerca", label="Ricerca nei documenti", fid=fid)
        jobs.run(job_id, search.answer_job, fid, domanda, model, data.get("doc_ids") or None)
        return jsonify({"job_id": job_id})

    @app.route("/api/ricerca/<fid>/cerca", methods=["POST"])
    def ricerca_passaggi(fid):
        """Solo recupero passaggi (senza modello): utile per la ricerca testuale istantanea."""
        q = ((request.get_json() or {}).get("query") or "").strip()
        return jsonify({"risultati": search.search(fid, q, k=20) if q else []})

    # ── Utilità native ────────────────────────────────────────────────────
    @app.route("/api/reveal", methods=["POST"])
    def reveal():
        path = (request.get_json() or {}).get("path", "")
        if path and os.path.exists(path):
            subprocess.Popen(["open", "-R", path] if os.path.isfile(path) else ["open", path])
        return jsonify({"ok": True})

    return app
