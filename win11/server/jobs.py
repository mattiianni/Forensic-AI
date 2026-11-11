"""Gestore job in background con stream di eventi SSE (stesso protocollo di Pdf50)."""
from __future__ import annotations

import json
import threading
import time
import traceback
import uuid
from datetime import datetime

from flask import Response, request

_jobs: dict[str, dict] = {}
_lock = threading.Lock()


def create(kind: str, label: str = "", fid: str | None = None, **meta) -> str:
    job_id = uuid.uuid4().hex
    with _lock:
        _jobs[job_id] = {
            "id": job_id, "kind": kind, "label": label, "fid": fid,
            "events": [], "status": "running", "cancelled": False,
            "created_at": time.time(), "progress": 0.0, "message": "", **meta,
        }
    return job_id


def get(job_id: str) -> dict | None:
    with _lock:
        return _jobs.get(job_id)


def meta(job_id: str, key: str, default=None):
    with _lock:
        return _jobs.get(job_id, {}).get(key, default)


def emit(job_id: str, event: dict):
    event = dict(event)
    event["ts"] = datetime.now().strftime("%H:%M:%S")
    with _lock:
        job = _jobs.get(job_id)
        if not job:
            return
        if event.get("type") == "progress":
            if "fraction" in event:
                job["progress"] = float(event["fraction"])
            if event.get("message"):
                job["message"] = event["message"]
        job["events"].append(event)


def progress(job_id: str, fraction: float, message: str = "", **extra):
    emit(job_id, {"type": "progress", "fraction": max(0.0, min(1.0, fraction)), "message": message, **extra})


def log(job_id: str, message: str, level: str = "info"):
    """Riga per la finestra di log (stesso evento usato dalla pipeline Pdf50)."""
    emit(job_id, {"type": "log", "message": message, "level": level})


def is_cancelled(job_id: str) -> bool:
    with _lock:
        return bool(_jobs.get(job_id, {}).get("cancelled"))


def cancel(job_id: str):
    with _lock:
        if job_id in _jobs:
            _jobs[job_id]["cancelled"] = True


def finish(job_id: str):
    with _lock:
        if job_id in _jobs:
            _jobs[job_id]["status"] = "done"
    emit(job_id, {"type": "eos"})


def run(job_id: str, target, *args, **kwargs):
    """Esegue target(job_id, ...) in un thread, gestendo errori ed eos."""
    def _wrapper():
        try:
            target(job_id, *args, **kwargs)
        except Exception as e:  # noqa: BLE001
            emit(job_id, {"type": "log", "level": "error", "message": f"ERRORE: {e}"})
            emit(job_id, {"type": "fatal_error", "message": str(e), "detail": traceback.format_exc()})
        finally:
            finish(job_id)
    threading.Thread(target=_wrapper, daemon=True, name=f"job-{job_id[:6]}").start()
    return job_id


def active(fid: str | None = None) -> list[dict]:
    now = time.time()
    with _lock:
        out = []
        for j in _jobs.values():
            if j["status"] == "running" and (fid is None or j.get("fid") in (fid, None)):
                lv = [e.get("level") for e in j["events"] if e.get("type") == "log"]
                out.append({"id": j["id"], "kind": j["kind"], "label": j["label"],
                            "progress": j["progress"], "message": j["message"],
                            "elapsed": int(now - j["created_at"]),
                            "errors": lv.count("error"), "warnings": lv.count("warning")})
        # pulizia job conclusi da più di un'ora
        for k in [k for k, j in _jobs.items() if j["status"] == "done" and now - j["created_at"] > 3600]:
            del _jobs[k]
        return out


def recent(fid: str | None = None, limit: int = 12) -> list[dict]:
    with _lock:
        items = [j for j in _jobs.values() if fid is None or j.get("fid") in (fid, None)]
        items.sort(key=lambda j: j["created_at"], reverse=True)
        out = []
        for j in items[:limit]:
            lv = [e.get("level") for e in j["events"] if e.get("type") == "log"]
            out.append({"id": j["id"], "kind": j["kind"], "label": j["label"], "status": j["status"],
                        "progress": j["progress"], "message": j["message"], "created_at": j["created_at"],
                        "errors": lv.count("error"), "warnings": lv.count("warning")})
        return out


def stream(job_id: str) -> Response:
    cursor = int(request.args.get("cursor", 0))

    def generate():
        idx = cursor
        last_beat = time.time()
        while True:
            with _lock:
                job = _jobs.get(job_id)
                if not job:
                    yield f'data: {json.dumps({"type": "eos"})}\n\n'
                    return
                events = job["events"][idx:]
                status = job["status"]
            for ev in events:
                yield f"data: {json.dumps({**ev, 'idx': idx}, ensure_ascii=False)}\n\n"
                idx += 1
                if ev.get("type") == "eos":
                    return
            if status == "done" and not events:
                return
            if time.time() - last_beat > 10:
                last_beat = time.time()
                yield f'data: {json.dumps({"type": "heartbeat"})}\n\n'
            time.sleep(0.08)

    return Response(generate(), content_type="text/event-stream",
                    headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"})
