import os
import time
from datetime import datetime
import shutil
import redis
import yaml
from app import app, db
from flask import Flask, abort
from flask import (
    request,
    render_template,
    url_for,
    redirect,
    flash,
    send_from_directory,
    make_response,
    jsonify,
    current_app
)
from flask_wtf import FlaskForm, RecaptchaField, Form
from flask_dropzone import Dropzone
from wtforms import Form, StringField, PasswordField, validators
from flask_sqlalchemy import SQLAlchemy
from flask_sslify import SSLify
from sqlalchemy.sql import and_, or_, func
from rq import Queue, cancel_job, Retry, Worker
from rq.command import send_stop_job_command
from rq.registry import StartedJobRegistry, FinishedJobRegistry, FailedJobRegistry, DeferredJobRegistry, ScheduledJobRegistry, CanceledJobRegistry
from rq.job import Job as RQJob  # <-- add this

from job_commands import launch_ngs_analysis
from config import compendium_url, ngs_app_url
from pathlib import Path
from app.models import (
    SampleTable,
    TherapeuticTable,
    OtherVariantsTable,
    RareVariantsTable,
    SummaryQcTable,
    BiomakerTable,
)
from app.models import Job as DBJob
# from app.server_info import _server_stats

import requests
import json
import sys
import time
from werkzeug.routing import BuildError
import platform
import subprocess
import shutil


r = redis.Redis()
q = Queue(connection=r)
registry = FinishedJobRegistry("default", connection=r)

sys.path.append("/home/udmmp/AutoLauncherNGS")
sys.path.append("/home/udmmp/NGS_APP")
sys.path.append("/home/udmmp/AutoLauncherNGS/modules")
sys.path.append("/home/udmmp/NGS_APP/modules")



# Comma-separated env, default to /ngs-results
MONITOR_VOLUMES = ["/ngs-results", "/raw-data", "/ngs-db", "/ngs-annotations", "/home/udmmp"]

def _disk_stats(paths):
    out = []
    for p in paths:
        try:
            try:
                import psutil
                du = psutil.disk_usage(p)
                total = du.total; used = du.used; free = du.free
            except Exception:
                total, used, free = shutil.disk_usage(p)
            out.append({
                "path": p,
                "total_gb": round(total / (1024**3), 2),
                "used_gb":  round(used  / (1024**3), 2),
                "free_gb":  round(free  / (1024**3), 2),
                "used_pct": round(100.0 * used / total, 1) if total else 0.0,
                "ok": True,
            })
        except Exception:
            out.append({
                "path": p, "total_gb": 0.0, "used_gb": 0.0, "free_gb": 0.0,
                "used_pct": 0.0, "ok": False
            })
    return out



def _cpu_model_name():
    # Try py-cpuinfo first (best cross-platform)
    try:
        import cpuinfo  # pip install py-cpuinfo
        info = cpuinfo.get_cpu_info()
        name = info.get("brand_raw") or info.get("brand") or ""
        if name:
            return name.strip()
    except Exception:
        pass

    # Linux: /proc/cpuinfo
    try:
        if os.path.exists("/proc/cpuinfo"):
            with open("/proc/cpuinfo", "r") as f:
                for line in f:
                    if "model name" in line or "Processor" in line or "Hardware" in line:
                        return line.split(":", 1)[1].strip()
    except Exception:
        pass

    # macOS: sysctl
    try:
        if platform.system() == "Darwin":
            out = subprocess.check_output(["sysctl", "-n", "machdep.cpu.brand_string"]).decode().strip()
            if out:
                return out
    except Exception:
        pass

    # Windows / generic fallback
    try:
        name = platform.processor() or os.environ.get("PROCESSOR_IDENTIFIER", "")
        if name:
            return name.strip()
    except Exception:
        pass

    return "Unknown CPU"

def _cpu_freq_ghz():
    """Return (current_ghz, max_ghz) if available, else (None, None)."""
    try:
        import psutil
        f = psutil.cpu_freq()
        if f:
            cur = round((f.current or 0.0) / 1000.0, 2)
            mx  = round((f.max or 0.0) / 1000.0, 2) if f.max else None
            return (cur if cur > 0 else None, mx if (mx and mx > 0) else None)
    except Exception:
        pass
    return (None, None)


def _server_metrics():
    try:
        import psutil
        cpu_count   = psutil.cpu_count(logical=True) or (os.cpu_count() or 0)
        cpu_percent = float(psutil.cpu_percent(interval=None))
        vm = psutil.virtual_memory()
        used = vm.total - vm.available

        # Optional: CPU model/freq if you added helpers earlier
        try:
            cpu_model = _cpu_model_name()
            cur_ghz, max_ghz = _cpu_freq_ghz()
        except Exception:
            cpu_model = None; cur_ghz = None; max_ghz = None

        return dict(
            cpu_model=cpu_model,
            cpu_count=cpu_count,
            cpu_percent=round(cpu_percent, 1),
            cpu_freq_ghz=cur_ghz,
            cpu_max_ghz=max_ghz,
            mem_total_gb=round(vm.total / (1024**3), 2),
            mem_used_gb=round(used / (1024**3), 2),
            mem_used_pct=round(100.0 * used / vm.total, 1) if vm.total else 0.0,
            disks=_disk_stats(MONITOR_VOLUMES),   # ← here
            ts=int(time.time())
        )
    except Exception:
        cpu_count = os.cpu_count() or 0
        # (…your existing fallback for memory…)
        return dict(
            cpu_model=None,
            cpu_count=cpu_count,
            cpu_percent=0.0,
            cpu_freq_ghz=None,
            cpu_max_ghz=None,
            mem_total_gb=total_gb,
            mem_used_gb=used_gb,
            mem_used_pct=used_pct,
            disks=_disk_stats(MONITOR_VOLUMES),   # ← still report disks
            ts=int(time.time())
        )

def _server_stats():
    try:
        import psutil
        cpu_count = psutil.cpu_count(logical=True) or (os.cpu_count() or 0)
        cpu_percent = float(psutil.cpu_percent(interval=0.2))
        vm = psutil.virtual_memory()
        mem_used = vm.total - vm.available

        # Optional: CPU model/freq if you added helpers earlier
        try:
            cpu_model = _cpu_model_name()
            cur_ghz, max_ghz = _cpu_freq_ghz()
        except Exception:
            cpu_model = None; cur_ghz = None; max_ghz = None

        return dict(
            cpu_model=cpu_model,
            cpu_count=cpu_count,
            cpu_percent=round(cpu_percent, 1),
            cpu_freq_ghz=cur_ghz,
            cpu_max_ghz=max_ghz,
            mem_total_gb=round(vm.total / (1024 ** 3), 2),
            mem_used_gb=round(mem_used / (1024 ** 3), 2),
            mem_used_pct=round(100.0 * mem_used / vm.total, 1) if vm.total else 0.0,
            disks=_disk_stats(MONITOR_VOLUMES),   # ← initial render
        )
    except Exception:
        # (…your existing fallback…)
        return dict(
            cpu_model=None,
            cpu_count=cpu_count,
            cpu_percent=0.0,
            cpu_freq_ghz=None,
            cpu_max_ghz=None,
            mem_total_gb=total_gb,
            mem_used_gb=used_gb,
            mem_used_pct=used_pct,
            disks=_disk_stats(MONITOR_VOLUMES),   # ← initial render
        )


@app.get("/api/rq/metrics")
def api_rq_metrics():
    return jsonify(_server_metrics())


# ---------- RQ helper utilities ----------
def get_queue(name="default"):
    # Reuse your global Redis connection
    return Queue(name, connection=r)


def _chunked(seq, n=500):
    for i in range(0, len(seq), n):
        yield seq[i:i+n]


def _split_failed_vs_stopped(failed_reg, connection):
    """Return (failed_list, stopped_list) by inspecting statuses in FailedJobRegistry."""
    failed_list, stopped_list = [], []
    ids = failed_reg.get_job_ids()
    for chunk in _chunked(ids, 500):
        jobs = RQJob.fetch_many(chunk, connection=connection)
        for j in jobs:
            try:
                status = (j.get_status(refresh=False) or "").lower()
            except Exception:
                status = "failed"
            (stopped_list if status == "stopped" else failed_list).append(j)
    return failed_list, stopped_list


def _queue_summary(name: str):
    qx = Queue(name, connection=r)

    started_reg   = StartedJobRegistry(name,   connection=r)
    failed_reg    = FailedJobRegistry(name,    connection=r)
    deferred_reg  = DeferredJobRegistry(name,  connection=r)
    scheduled_reg = ScheduledJobRegistry(name, connection=r)
    finished_reg  = FinishedJobRegistry(name,  connection=r)
    canceled_reg  = CanceledJobRegistry(name,  connection=r)

    failed_list, stopped_list = _split_failed_vs_stopped(failed_reg, connection=r)

    return {
        "name": name,
        "pending_count":   qx.count,
        "started_count":   started_reg.count,
        "failed_count":    len(failed_list),      # only real failures
        "stopped_count":   len(stopped_list),     # NEW: explicitly stopped
        "canceled_count":  canceled_reg.count,
        "deferred_count":  deferred_reg.count,
        "scheduled_count": scheduled_reg.count,
        "finished_count":  finished_reg.count,
    }

def _discover_queue_names():
    """Descobreix cues existents i n’afegeix d’extra (p.ex. via env)."""
    discovered = {q.name for q in Queue.all(connection=r)}  # pot estar buit si no hi ha claus a Redis
    # Permet forçar cues “fixes” via env, p.ex. RQ_QUEUES="default,high,low"
    extra = [s.strip() for s in (os.getenv("RQ_QUEUES") or "").split(",") if s.strip()]
    discovered.update(extra)
    # Garanteix que 'default' aparegui encara que estigui buida
    discovered.add("default")
    return sorted(discovered)
@app.get("/rq")
def rq_queues_view():
    names = _discover_queue_names()
    queues = [_queue_summary(name) for name in names]
    sysinfo = _server_stats()
    return render_template(
        "rq_all_queues.html",  # el teu template de llistat
        title="Cues RQ",
        queues=queues,
        **sysinfo  # <-- passa cpu_count, cpu_percent, mem_total_gb, mem_used_gb, mem_used_pct
    )

@app.get("/api/rq/queues")
def api_rq_queues():
    """API JSON opcional per a totes les cues."""
    names = _discover_queue_names()
    data = [_queue_summary(name) for name in names]
    return jsonify({"queues": data, "count": len(data)})

def fetch_jobs_by_ids(job_ids):
    jobs = []
    for jid in job_ids:
        try:
            jobs.append(RQJob.fetch(jid, connection=r))  # <-- RQJob
        except Exception:
            pass
    return jobs



@app.get("/rq/<queue_name>")
def rq_queue_view(queue_name):
    qx = get_queue(queue_name)

    # Lists
    pending   = list(qx.jobs)

    started_reg   = StartedJobRegistry(queue_name, connection=r)
    failed_reg    = FailedJobRegistry(queue_name, connection=r)
    deferred_reg  = DeferredJobRegistry(queue_name, connection=r)
    scheduled_reg = ScheduledJobRegistry(queue_name, connection=r)
    finished_reg  = FinishedJobRegistry(queue_name, connection=r)

    failed_list, stopped_list = _split_failed_vs_stopped(failed_reg, connection=r)
    started   = fetch_jobs_by_ids(started_reg.get_job_ids())
    deferred  = fetch_jobs_by_ids(deferred_reg.get_job_ids())
    scheduled = fetch_jobs_by_ids(scheduled_reg.get_job_ids())

    # Optional: canceled (not used in your template yet)
    canceled = []

    # Counts for badges
    context = {
        "title": f"RQ — {queue_name}",
        "queue_name": queue_name,

        # lists for tables
        "pending": pending,
        "started": started,
        "failed": failed_list,
        "stopped": stopped_list,
        "deferred": deferred,
        "scheduled": scheduled,
        "canceled": canceled,

        # counters for tab badges
        "pending_count":   len(pending),
        "started_count":   len(started),
        "failed_count":    len(failed_list),
        "stopped_count":   len(stopped_list),
        "deferred_count":  len(deferred),
        "scheduled_count": len(scheduled),
        "canceled_count":  len(canceled),

        "finished_count":  finished_reg.count,
    }

    return render_template("rq_queue.html", **context)


@app.post("/rq/cleanup_workers")
def rq_cleanup_workers():
    cleaned = []
    for w in Worker.all(connection=r):
        try:
            if not w.is_alive():
                w.register_death(); cleaned.append(w.name)
        except Exception:
            pass
    return jsonify({"cleaned": cleaned})

@app.get("/rq/job/<job_id>")
def rq_job_detail_view(job_id):
    job = RQJob.fetch(job_id, connection=r)  # <-- RQJob
    queue_name = job.origin or "default"

    db_row = DBJob.query.filter_by(Queue_id=job_id).first()  # <-- DB model
    return render_template("rq_job.html", title=f"RQ Job: {job_id}", job=job, queue_name=queue_name, db_job=db_row)


@app.post("/rq/job/<job_id>/requeue")
def rq_job_requeue(job_id):
    job = RQJob.fetch(job_id, connection=r)  # <-- RQJob
    qx = get_queue(job.origin or "default")
    qx.enqueue_job(job)

    db_job = DBJob.query.filter_by(Queue_id=job_id).first()
    if db_job:
        db_job.Status = "queued"
        db.session.commit()

    flash(f"Job {job_id} requeued on '{qx.name}'.", "success")
    return redirect(url_for("rq_job_detail_view", job_id=job_id))

@app.post("/rq/job/<job_id>/delete")
def rq_job_delete(job_id):
    job = RQJob.fetch(job_id, connection=r)  # <-- RQJob
    # Remove from its registries and delete data
    try:
        job.cancel()   # ensures it’s removed from queue/registries if present
    except Exception:
        pass
    try:
        job.delete()
    except Exception:
        pass

    # Optionally reflect in DB
    db_job = DBJob.query.filter_by(Queue_id=job_id).first()
    if db_job:
        db_job.Status = "deleted"
        db.session.commit()

    flash(f"Job {job_id} deleted from RQ.", "success")
    return redirect(url_for("rq_queue_view", queue_name=(job.origin or "default")))

@app.get("/api/rq/<queue_name>/pending")
def api_rq_pending(queue_name):
    qx = get_queue(queue_name)
    items = [{
        "id": j.id,
        "func": j.func_name,
        "args": j.args,
        "kwargs": j.kwargs,
        "enqueued_at": (j.enqueued_at or j.created_at).isoformat() if (j.enqueued_at or j.created_at) else None,
    } for j in qx.jobs]
    return jsonify({"queue": queue_name, "pending": items})

@app.get("/api/rq/<queue_name>/started")
def api_rq_started(queue_name):
    reg = StartedJobRegistry(queue_name, connection=r)
    jobs = fetch_jobs_by_ids(reg.get_job_ids())
    items = [{"id": j.id, "func": j.func_name, "started_at": j.started_at.isoformat() if j.started_at else None} for j in jobs]
    return jsonify({"queue": queue_name, "started": items})

@app.get("/api/rq/<queue_name>/failed")
def api_rq_failed(queue_name):
    reg = FailedJobRegistry(queue_name, connection=r)
    jobs = fetch_jobs_by_ids(reg.get_job_ids())
    items = [{"id": j.id, "func": j.func_name, "ended_at": j.ended_at.isoformat() if j.ended_at else None} for j in jobs]
    return jsonify({"queue": queue_name, "failed": items})

@app.get("/api/rq/<queue_name>/deferred")
def api_rq_deferred(queue_name):
    reg = DeferredJobRegistry(queue_name, connection=r)
    jobs = fetch_jobs_by_ids(reg.get_job_ids())
    items = [{"id": j.id, "func": j.func_name} for j in jobs]
    return jsonify({"queue": queue_name, "deferred": items})

@app.get("/api/rq/<queue_name>/scheduled")
def api_rq_scheduled(queue_name):
    reg = ScheduledJobRegistry(queue_name, connection=r)
    jobs = fetch_jobs_by_ids(reg.get_job_ids())
    items = [{"id": j.id, "func": j.func_name} for j in jobs]
    return jsonify({"queue": queue_name, "scheduled": items})


# ---------- Helpers ----------
def serialize_job(job):
    # adjust field names if your model differs
    date_val = job.Date.isoformat() if hasattr(job.Date, 'isoformat') else str(job.Date or "")
    return {
        "Job_id": job.Job_id,
        "Queue_id": job.Queue_id,
        "Panel": job.Panel,
        "Analysis": job.Analysis,
        "Status": job.Status,
        "Date": date_val,
        "Samples": job.Samples,
        "HasLog": bool(job.Logfile and os.path.isfile(job.Logfile)),
        "HasConfig": any([
            bool(job.Config_yaml_1),
            bool(job.Config_yaml_2),
            bool(job.Config_yaml_3),
            bool(job.Config_yaml_4),
        ]),
    }

def counts_summary():
    # group counts by Status, compute Completed
    rows = db.session.query(DBJob.Status, func.count(DBJob.Job_id)).group_by(DBJob.Status).all()
    cnt = {k or "": v for k, v in rows}
    total = db.session.query(func.count(DBJob.Job_id)).scalar() or 0
    running = (cnt.get('started', 0) or 0) + (cnt.get('running', 0) or 0)
    completed = total - running - (cnt.get('queued', 0) or 0) - (cnt.get('failed', 0) or 0)
    return {
        "Total jobs": total,
        "Completed": max(completed, 0),
        "Failed": cnt.get('failed', 0) or 0,
        "Running": running,
    }

# ---------- API: server-side list ----------
@app.get("/api/jobs")
def api_jobs():
    page     = request.args.get("page", 1, type=int)
    per_page = request.args.get("per_page", 9, type=int)
    search   = (request.args.get("search", "") or "").strip()
    status   = (request.args.get("status", "") or "").strip()
    sort     = (request.args.get("sort", "date") or "date").lower()
    order    = (request.args.get("order", "desc") or "desc").lower()

    # --- SQL query (avoid shadowing global RQ queue 'q')
    q_sql = DBJob.query

    if status:
        q_sql = q_sql.filter(DBJob.Status.ilike(status))

    if search:
        like = f"%{search}%"
        q_sql = q_sql.filter(or_(
            DBJob.Job_id.ilike(like),
            DBJob.Queue_id.ilike(like),
            DBJob.Panel.ilike(like),
            DBJob.Analysis.ilike(like),
        ))

    # server-side sorting
    col = DBJob.Job_id if sort == "job_id" else DBJob.Date
    q_sql = q_sql.order_by(col.asc() if order == "asc" else col.desc())

    # paginate
    pagination = q_sql.paginate(page=page, per_page=per_page, error_out=False)

    # --- Build live status maps (single pass to avoid per-row Redis hits)
    queue_name = "default"  # adjust if multiple queues

    started_ids   = set(StartedJobRegistry(queue_name, connection=r).get_job_ids())
    failed_ids    = set(FailedJobRegistry(queue_name,  connection=r).get_job_ids())
    finished_ids  = set(FinishedJobRegistry(queue_name,connection=r).get_job_ids())
    deferred_ids  = set(DeferredJobRegistry(queue_name, connection=r).get_job_ids())
    try:
        from rq.registry import ScheduledJobRegistry
        scheduled_ids = set(ScheduledJobRegistry(queue_name, connection=r).get_job_ids())
    except Exception:
        scheduled_ids = set()

    # Enqueued (pending) job ids
    try:
        enqueued_ids = set(q.job_ids)  # uses the global RQ queue 'q'
    except Exception:
        enqueued_ids = set()

    jobs = []
    dirty_rows = []  # DB rows to update if we detect drift

    for row in pagination.items:
        live = None
        jid = row.Queue_id

        if jid:
            # 1) Try to read the job directly (works until pruned)
            try:
                rq_job = q.fetch_job(jid)
                if rq_job:
                    live = (rq_job.get_status(refresh=True) or "").lower()
            except Exception:
                live = None

            # 2) Fallback to registry membership (robust, cheap)
            if not live:
                if jid in started_ids:       live = "started"
                elif jid in enqueued_ids:    live = "queued"
                elif jid in failed_ids:      live = "failed"
                elif jid in finished_ids:    live = "finished"
                elif jid in deferred_ids:    live = "deferred"
                elif jid in scheduled_ids:   live = "scheduled"

            # 3) Last-resort inference: if nowhere in Redis and DB says running/started/queued,
            #    we assume it finished (likely cleaned by TTL or worker crash-recovery)
            if not live and (row.Status or "").lower() in ("running", "started", "queued"):
                live = "finished"

        item = serialize_job(row)

        if live:
            # Override card status to live RQ status
            item["Status"] = live

            # Opportunistically sync DB if it drifted
            if (row.Status or "").lower() != live:
                row.Status = live
                dirty_rows.append(row)

        jobs.append(item)

    # Single commit for any drift we fixed
    if dirty_rows:
        try:
            db.session.commit()
        except Exception:
            db.session.rollback()

    return jsonify({
        "page": pagination.page,
        "pages": pagination.pages,
        "per_page": per_page,
        "total": pagination.total,
        "jobs": jobs,
        "status_summary": counts_summary(),  # optionally switch to a live version below
    })

# ---------- API: lazy-load config for a job ----------
@app.get("/api/job/<job_id>/config")
def api_job_config(job_id):
    job = DBJob.query.filter_by(Job_id=job_id).first()
    if not job:
        abort(404)

    cfg = {}
    # load only on demand
    if job.Config_yaml_1 and os.path.isfile(job.Config_yaml_1):
        cfg['ann_yaml'] = load_annotation_resources(job.Config_yaml_1)
    if job.Config_yaml_2 and os.path.isfile(job.Config_yaml_2):
        cfg['bin_yaml'] = load_annotation_resources(job.Config_yaml_2)
    if job.Config_yaml_3 and os.path.isfile(job.Config_yaml_3):
        cfg['ref_yaml'] = load_annotation_resources(job.Config_yaml_3)
    if job.Config_yaml_4 and os.path.isfile(job.Config_yaml_4):
        cfg['docker_yaml'] = load_annotation_resources(job.Config_yaml_4)

    return jsonify({
        "job_id": job.Job_id,
        "cmd": job.Job_cmd or "",
        "config": cfg,
    })

# ---------- API: lazy-read last log line ----------
@app.get("/api/job/<job_id>/logline")
def api_job_logline(job_id):
    job = DBJob.query.filter_by(Job_id=job_id).first()
    if not job or not job.Logfile or not os.path.isfile(job.Logfile):
        return jsonify({"last_line": None}), 404
    return jsonify({"last_line": read_last_line(job.Logfile)})


from rq.registry import StartedJobRegistry, DeferredJobRegistry, ScheduledJobRegistry

@app.post("/api/job/<queue_id>/stop", endpoint="api_stop_job")
def api_stop_job(queue_id):
    try:
        rq_job = q.fetch_job(queue_id)
        if rq_job is None:
            return jsonify({"ok": False, "error": "Job not found in RQ"}), 404

        status = rq_job.get_status()  # 'queued', 'started', 'deferred', 'scheduled', 'finished', 'failed', etc.

        # Try to stop/cancel depending on current RQ status
        if status in ("started", "running"):  # running workers report 'started'
            try:
                send_stop_job_command(r, queue_id)  # graceful stop
            except Exception as e:
                return jsonify({"ok": False, "error": f"Stop command failed: {e}"}), 500
        elif status in ("queued", "deferred", "scheduled"):
            try:
                cancel_job(queue_id, connection=r)  # remove from queue/registries
            except Exception:
                # Fallback: Queue.remove if needed
                try:
                    q.remove(rq_job)
                except Exception as e:
                    return jsonify({"ok": False, "error": f"Cancel failed: {e}"}), 500
        else:
            # finished/failed/etc — nothing to stop
            return jsonify({"ok": False, "error": f"Job is '{status}', cannot stop"}), 409

        # Update our SQL row to 'stopped' (best-effort)
        j = DBJob.query.filter_by(Queue_id=queue_id).first()
        if j:
            j.Status = "stopped"
            db.session.commit()

        return jsonify({"ok": True, "status": "stopped"})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500

def load_annotation_resources(yaml_file_path):
    """
    Read a YAML file defining annotation resources and return a structured dict:
      - 'config': top-level scalar settings
      - 'predictors': categories of predictors (lists)
      - 'resources': list of dicts for each resource entry

    """
    if not os.path.exists(yaml_file_path):
        raise FileNotFoundError(f"YAML file not found: {yaml_file_path}")

    with open(yaml_file_path) as f:
        data = yaml.safe_load(f)

    # Top-level config: scalar values
    config_keys = ['version', 'genome_reference', 'ann_dir', 'main_yaml_path']
    config = {k: data.get(k) for k in config_keys if k in data}

    # Predictor categories: lists
    predictor_keys = [k for k, v in data.items() if isinstance(v, list)]
    predictors = {k: data[k] for k in predictor_keys}

    # Resource entries: dicts beyond the above
    resources = []
    for key, entry in data.items():
        if key in config_keys or key in predictor_keys:
            continue
        if not isinstance(entry, dict):
            continue
        # Collect resource attributes, preserving all fields
        resource = {'key': key}
        resource.update(entry)
        # Normalize missing common fields
        resource.setdefault('version', None)
        resource.setdefault('resource_name', key)
        resources.append(resource)

    return {
        'config': config,
        'predictors': predictors,
        'resources': resources
    }



def clear_rq_queue(queue_name="default"):
    """
    Clears all jobs from the specified RQ queue:
    - Removes enqueued jobs
    - Removes started jobs (if possible)
    - Clears finished and failed registries
    """
    from rq import Queue
    from rq.registry import (
        StartedJobRegistry,
        FinishedJobRegistry,
        FailedJobRegistry,
        DeferredJobRegistry,
    )

    # Connect to Redis and queue
    r = redis.Redis()
    q = Queue(queue_name, connection=r)

    # Clear enqueued jobs
    for job in q.jobs:
        print(f"Removing enqueued job: {job.id}")
        q.remove(job)

    # Clear started jobs
    started_registry = StartedJobRegistry(queue_name, connection=r)
    for job_id in started_registry.get_job_ids():
        job = q.fetch_job(job_id)
        if job:
            print(f"Removing started job: {job.id}")
            job.cancel()
            job.delete()

    # Clear finished jobs
    finished_registry = FinishedJobRegistry(queue_name, connection=r)
    for job_id in finished_registry.get_job_ids():
        job = q.fetch_job(job_id)
        if job:
            print(f"Removing finished job: {job.id}")
            job.delete()

    # Clear failed jobs
    failed_registry = FailedJobRegistry(queue_name, connection=r)
    for job_id in failed_registry.get_job_ids():
        job = q.fetch_job(job_id)
        if job:
            print(f"Removing failed job: {job.id}")
            job.delete()

    # Clear deferred jobs
    deferred_registry = DeferredJobRegistry(queue_name, connection=r)
    for job_id in deferred_registry.get_job_ids():
        job = q.fetch_job(job_id)
        if job:
            print(f"Removing deferred job: {job.id}")
            job.delete()

    print(f"Queue '{queue_name}' cleared.")


@app.route("/clear_queue", methods=["POST", "GET"])
def clear_queue():
    try:
        clear_rq_queue()  # clear default queue
        flash(" INFO:  Queue cleared successfully.", "success")
    except Exception as e:
        flash(f" ERROR: Failed to clear queue: {e}", "danger")
    return redirect(url_for("status"))


def validate_fastq(fastq_files, fastq):
    """
    Validate that FASTQs are valid:
    - Allowed extensions
    - Paired R1, R2
    - Gzipped
    """

    is_ok = True
    fq_list = []
    errors = []
    for fq in fastq_files:
        fq_list.append(fq.filename)

    fq_1 = fastq.filename
    fq_1 = fq_1.replace("R2", "R1")
    fq_2 = fq_1.replace("R1", "R2")

    # Check if paired fq's are available
    if not fq_1.endswith(".fq.gz") and not fq_1.endswith(".fastq.gz"):
        errors.append("Input files " + fq_1 + " are not fastq's")
        is_ok = False
    else:
        if fq_1 != fq_2 and fq_1 in fq_list and fq_2 in fq_list:
            errors.append(
                "Es requereix una parella de fitxers fastq per la mostra "
                + fastq.filename
            )
            is_ok = True
        else:
            errors.append(
                "Es requereix una parella de fitxers fastq per la mostra "
                + fastq.filename
            )
            is_ok = False
    return errors, is_ok


def allowed_input_filesize(filesize):
    """ """
    if int(filesize) <= app.config["MAX_INPUT_FILESIZE"]:
        return True
    else:
        return False


@app.route("/test_upload", methods=["POST", "GET"])
def test_upload():
    if request.method == "POST":
        f = request.files.get("file")
        file_path = os.path.join(app.config["WORKING_DIRECTORY"], f.filename)
        f.save(file_path)
    return render_template("lowpass_analysis.html", title=" NGS - Lowpass")


@app.route("/stop_job/<queue_id>")
#@login_required
def stop_job(queue_id):
    send_stop_job_command(r, queue_id)
    return redirect(url_for("status"))

@app.route('/change_status', methods=['POST'])
def change_status():
    data = request.get_json()
    job_id = data.get('job_id')
    new_status = data.get('new_status')

    # Validate and update the job status in the database or backend
    if not job_id or not new_status:
        return jsonify(success=False, error="Invalid input"), 400

    # Update the job status in your database
    try:
        # Replace this with actual database logic
        job = DBJob.query.filter_by(Job_id=job_id).first()
        if not job:
            return jsonify(success=False, error="Job not found"), 404
        job.Status = new_status
        db.session.commit()

        return jsonify(success=True)
    except Exception as e:
        return jsonify(success=False, error=str(e)), 500


@app.route("/remove_job/<queue_id>/<job_id>/<panel>")
#@login_required
def remove_job(queue_id, job_id, panel):
    try:
        registry.remove(queue_id, delete_job=True)
    except Exception as e:
        print(str(e))

    job_entry = DBJob.query.filter_by(Job_id=job_id, Panel=panel).first()
    if job_entry:
        db.session.delete(job_entry)
        db.session.commit()

    samples = SampleTable.query.filter_by(run_id=job_id).all()
    if samples:
        for sample in samples:
            db.session.delete(sample)
            db.session.commit()

    therapeutic_variants = TherapeuticTable.query.filter_by(run_id=job_id).all()
    if therapeutic_variants:
        for variant in therapeutic_variants:
            db.session.delete(variant)
            db.session.commit()

    other_variants = OtherVariantsTable.query.filter_by(run_id=job_id).all()
    if other_variants:
        for variant in other_variants:
            db.session.delete(variant)
            db.session.commit()

    rare_variants = RareVariantsTable.query.filter_by(run_id=job_id).all()
    if rare_variants:
        for variant in rare_variants:
            db.session.delete(variant)
            db.session.commit()

    summary_entries = SummaryQcTable.query.filter_by(run_id=job_id).all()
    if summary_entries:
        for entry in summary_entries:
            db.session.delete(entry)
            db.session.commit()

    biomarker_entries = BiomakerTable.query.filter_by(run_id=job_id).all()
    if biomarker_entries:
        for entry in biomarker_entries:
            db.session.delete(entry)
            db.session.commit()

    flash("S'ha eliminat el job " + job_id + " correctament", "success")
    return redirect(url_for("status"))


@app.route("/panels_app")
#@login_required
def panels_app():
    url = f"{ngs_app_url}"
    return redirect(url, code=302)


@app.route("/targeted_seq_analysis")
#@login_required
def complete_analysis():

    url = f"{app.config['GENE_PANEL_API']}/show_all"
    response = requests.get(url)
    gene_panels = []
    if response:
        r = response.json()
        # r = json.loads(r)
        for panel in r["panels"]:
            panel_name = panel["Panel_id"]
            if panel_name == "GenOncology-Dx":
                panel_name = "GenOncology-Dx.v1"
            gene_panels.append(panel_name)
    return render_template(
        "targeted_seq_analysis.html",
        title=" NGS - Anàlisi de Panells de Gens",
        gene_panels=gene_panels,
    )


@app.route("/pipeline_docs/<file>")
def pipeline_docs(file):
    docs_folder = "docs"
    uploads = os.path.join(app.config["STATIC_URL_PATH"], docs_folder)
    return send_from_directory(
        directory=uploads, filename=file, path=file, as_attachment=True
    )


@app.route("/lowpass_analysis")
#@login_required
def lowpass_analysis():
    """ """
    return render_template("lowpass_analysis.html", title=" NGS - Lowpass")


@app.route("/ngs_applications")
#@login_required
def ngs_applications():
    """ """
    return render_template("ngs_applications.html", title=" NGS - Aplicacions")


def read_last_line(filepath):
    try:
        with open(filepath, "rb") as f:
            f.seek(-2, os.SEEK_END)
            while f.read(1) != b"\n":
                f.seek(-2, os.SEEK_CUR)
            return f.readline().decode().strip()
    except Exception as e:
        return None  # or return f"[Error reading log: {e}]"

@app.route("/status")
def status():
    # Try to construct a template STOP URL without touching current_app.
    # 1) Try string token directly (works if queue_id is a string converter)
    try:
        stop_url_template = url_for("stop_job", queue_id="__Q__")
    except BuildError:
        # 2) Try integer placeholder, then swap the last "/0" with "/__Q__"
        try:
            tmp = url_for("stop_job", queue_id=0)
            if tmp.endswith("/0"):
                stop_url_template = tmp[:-2] + "/__Q__"
            elif "/0" in tmp:
                head, tail = tmp.rsplit("/0", 1)
                stop_url_template = head + "/__Q__" + tail
            else:
                stop_url_template = "#"
        except BuildError:
            # stop_job route not registered (or otherwise not buildable)
            stop_url_template = "#"

    return render_template(
        "status.html",
        title="Job Status",
        status_dict=counts_summary(),  # your existing helper
        STOP_URL=stop_url_template,    # consumed by the template JS
    )


@app.route("/download_log/<job_id>")
#@login_required
def download_log(job_id):
    """ """
    job_entry = DBJob.query.filter_by(Job_id=job_id).first()
    if job_entry:
        log_file = job_entry.Logfile
        if os.path.isfile(log_file):

            return send_from_directory(
                directory=os.path.dirname(log_file), path=os.path.basename(log_file), as_attachment=True
            )
        else:
            flash("El fitxer no existeix", "warning")
    else:
        flash("No s'ha trobat el fitxer", "warning")

@app.route("/show_compendium_run/<run_id>")
#@login_required
def show_compendium_run(run_id):
    """ """
    url = f"{compendium_url}/view_run/{run_id}"
    return redirect(url, code=302)


@app.route("/remove_job_data/<job_id>")
#@login_required
def remove_job_data(job_id):
    """ """
    job_entry = DBJob.query.filter_by(Job_id=job_id).first()
    if job_entry:
        db.session.delete(job_entry)
        db.session.commit()

    samples = SampleTable.query.filter_by(run_id=job_id).all()
    if samples:
        for sample in samples:
            db.session.delete(sample)
            db.session.commit()

    therapeutic_variants = TherapeuticTable.query.filter_by(run_id=job_id).all()
    if therapeutic_variants:
        for variant in therapeutic_variants:
            db.session.delete(variant)
            db.session.commit()

    other_variants = OtherVariantsTable.query.filter_by(run_id=job_id).all()
    if other_variants:
        for variant in other_variants:
            db.session.delete(variant)
            db.session.commit()

    rare_variants = RareVariantsTable.query.filter_by(run_id=job_id).all()
    if rare_variants:
        for variant in rare_variants:
            db.session.delete(variant)
            db.session.commit()

    summary_entries = SummaryQcTable.query.filter_by(run_id=job_id).all()
    if summary_entries:
        for entry in summary_entries:
            db.session.delete(entry)
            db.session.commit()

    biomarker_entries = BiomakerTable.query.filter_by(run_id=job_id).all()
    if biomarker_entries:
        for entry in biomarker_entries:
            db.session.delete(entry)
            db.session.commit()
    msg = f"S'ha eliminat el job, {job_id}, correctament"
    flash(msg, "success")
    return redirect(url_for("status"))


@app.route("/submit_ngs_analysis", methods=["GET", "POST"])
def submit_ngs_job():
    """
    Submit an NGS analysis:
      - Validates FASTQs and panel
      - Prepares run folder
      - Enqueues job in RQ
      - Saves DB row with RQ-derived status (queued/started)
    """
    if request.method != "POST":
        return make_response(jsonify({"message": "File upload error"}), 400)

    user_id = "."  # TODO: plug your auth user id here
    is_ok = True

    # ---- 1) Disk space guardrail ----
    try:
        _, _, free = shutil.disk_usage("/ngs-results")
        free_gb = free // (2 ** 30)
        if free_gb < 20:
            flash(
                f"No hi ha prou espai al servidor d'anàlisi ({free_gb} Gb). "
                "Es recomana ampliar fins a 200Gb",
                "warning",
            )
            is_ok = False
    except Exception as e:
        flash(f"No s'ha pogut comprovar l'espai de disc: {e}", "warning")

    # ---- 2) FASTQs ----
    fastq_files = []
    total_samples = 0
    if not request.files:
        flash("Es requereixen arxius FASTQ", "warning")
        is_ok = False
    else:
        fastq_files = request.files.getlist("fastqs") or []
        if not fastq_files:
            flash("Es requereixen arxius FASTQ", "warning")
            is_ok = False
        else:
            total_samples = max(1, int(len([f for f in fastq_files if f.filename]) / 2))
            if is_ok:
                for fq in fastq_files:
                    if not fq.filename:
                        flash("Es requereixen arxius FASTQ", "warning")
                        is_ok = False
                        break
                    if "Undetermined" in fq.filename:
                        continue
                    errors, valid = validate_fastq(fastq_files, fq)
                    if not valid:
                        is_ok = False
                        for err in errors:
                            flash(err, "warning")

    # ---- 3) Panel / BED ----
    panel = (request.form.get("select_panel") or "").strip()
    custom_beds = request.files.getlist("custom_bed") if request.files else []
    if custom_beds and custom_beds[0].filename:
        # user-supplied BED overrides
        panel = custom_beds[0].filename

    if not panel or panel == "0":
        flash("Es requereix un panell de gens", "warning")
        is_ok = False

    # ---- 4) Job ID uniqueness ----
    job_id = (request.form.get("job_id") or "").strip()
    if not job_id:
        flash("Es requereix un Job ID", "warning")
        is_ok = False
    else:
        exists = DBJob.query.filter_by(Job_id=job_id, User_id=user_id, Panel=panel).first()
        if exists:
            flash("Ja existeix un Job ID amb el nom entrat", "warning")
            is_ok = False

    if not is_ok:
        return make_response(jsonify({"message": "File upload error"}), 400)

    # ---- 5) Paths & folders ----
    run_dir = os.path.join(app.config["UPLOADS"], job_id)
    try:
        os.makedirs(run_dir, exist_ok=True)
    except Exception as e:
        flash(f"No s'ha pogut crear el directori del RUN: {e}", "danger")
        return make_response(jsonify({"message": "File upload error"}), 400)

    # Decide analysis type & subdir
    var_analysis = "germline"
    if panel == "GenOncology-Dx.v1":
        panel_dir = os.path.join(run_dir, "GenOncology-Dx")
        var_analysis = "somatic"
    elif panel == "GenOncology-Dx_1.5":
        panel_dir = os.path.join(run_dir, "GenOncology-Dx_1.5")
        var_analysis = "somatic"
    else:
        panel_dir = os.path.join(run_dir, panel)

    os.makedirs(panel_dir, exist_ok=True)

    # Resolve BED (API or fixed)
    panel_name = panel
    panel_version = ""
    try:
        if panel == "GenOncology-Dx.v1":
            panel_bed = os.path.join(panel_dir, "GenOncology-Dx.v1.bed")
            panel_name = "GenOncology-Dx"
            panel_version = "v1"
        else:
            # Get latest version
            url = f"{app.config['GENE_PANEL_API']}/{panel}/latest_version"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            j = r.json()
            panel_version = f"v{int(j['panel_version'])}" if j and 'panel_version' in j else ""
            # Fetch specific version info
            url = f"{app.config['GENE_PANEL_API']}/{panel}/{panel_version}"
            r = requests.get(url, timeout=10)
            r.raise_for_status()
            panel_bed = r.json().get("Capture_bed")
            if not panel_bed:
                raise ValueError("No s'ha trobat 'Capture_bed' al servei.")
    except Exception as e:
        flash(f"No s'ha pogut resoldre el panell {panel}: {e}", "danger")
        return make_response(jsonify({"message": "Panel resolution error"}), 400)

    # ---- 6) Save optional lab file & FASTQs ----
    lab_file = ""
    try:
        lab_files = request.files.getlist("lab_file") or []
        for f in lab_files:
            if not f or not f.filename:
                continue
            lab_file = os.path.join(panel_dir, f.filename)
            f.save(lab_file)
        for fq in fastq_files:
            if fq and fq.filename:
                fq.save(os.path.join(panel_dir, fq.filename))
    except Exception as e:
        flash(f"Error desant fitxers: {e}", "danger")
        return make_response(jsonify({"message": "Save files error"}), 400)

    # ---- 7) Compose params & logging ----
    input_dir = panel_dir
    now = datetime.now()
    date_time = now.strftime("%Y%m%d")
    logname = os.path.basename(os.path.normpath(input_dir))
    log_file = os.path.join(input_dir, f"{logname}.{date_time}.pipeline.log")

    params = {
        "PIPELINE_EXE": app.config["NGS_PIPELINE_EXE"],
        "INPUT_DIR": input_dir,
        "OUTPUT_DIR": input_dir,
        "USER_ID": user_id,
        "PANEL": panel_bed,
        "PANEL_NAME": panel_name,
        "PANEL_VERSION": panel_version,
        "GENOME": "hg19",
        "THREADS": "16",
        "VARCLASS": var_analysis,
        "RUN_DIR": run_dir,
        "RUN_NAME": os.path.basename(run_dir),
        "LAB_DATA": lab_file,
        "DB": app.config["DB"],
        "ANN_YAML": app.config["ANN_YAML_HG19"],
        "REF_YAML": app.config["REF_YAML"],
        "BIN_YAML": app.config["BIN_YAML"],
        "DOCKER_YAML": app.config["DOCKER_YAML"],
    }

    # Optional: touch the log file so the UI can download it immediately
    try:
        Path(log_file).touch(exist_ok=True)
    except Exception:
        pass

    # ---- 8) Enqueue in RQ ----
    try:
        task = q.enqueue(launch_ngs_analysis, params, job_timeout=-1)
        # IMPORTANT: get actual RQ status (usually 'queued', but could be 'started' right away)
        rq_status = (task.get_status(refresh=True) or "").lower()
        if rq_status not in ("queued", "started", "deferred", "scheduled", "running"):
            # RQ normalizes to 'queued'/'started'/'finished'/'failed' — keep a sane default
            rq_status = "queued"
    except Exception as e:
        flash(f"No s'ha pogut encolar el job: {e}", "danger")
        return make_response(jsonify({"message": "Enqueue error"}), 500)

    # ---- 9) Persist DB row using RQ-derived status ----
    try:
        cmd = [
            "python3", params["PIPELINE_EXE"], "all", "-s", "targeted",
            "--panel", params["PANEL"], "--bwamem2",
            "--panel_name", params["PANEL_NAME"], "--panel_version", params["PANEL_VERSION"],
            "-r", params["GENOME"], "-t", params["THREADS"],
            "--var_class", params["VARCLASS"],
            "-i", params["INPUT_DIR"], "-o", params["OUTPUT_DIR"],
            "--db", params["DB"], "--user_id", params["USER_ID"],
            "--ann_yaml", params["ANN_YAML"], "--docker_yaml", params["DOCKER_YAML"],
            "--ref_yaml", params["REF_YAML"], "--bin_yaml", params["BIN_YAML"],
            "--run_id", params["RUN_NAME"], "--bwamem2",
        ]
        cmd_str = " ".join(cmd)

        row = DBJob(
            User_id=user_id,
            Job_id=job_id,
            Queue_id=task.id,
            Date=task.enqueued_at or now,
            Analysis=var_analysis,
            Panel=panel,
            Samples=total_samples,
            Status=rq_status,                 # ← take it from RQ (key change)
            Logfile=log_file,
            Config_yaml_1=params["ANN_YAML"],
            Config_yaml_2=params["BIN_YAML"],
            Config_yaml_3=params["REF_YAML"],
            Config_yaml_4=params["DOCKER_YAML"],
            Job_cmd=cmd_str,
        )
        db.session.add(row)
        db.session.commit()
    except Exception as e:
        flash(f"Error desant el job a base de dades: {e}", "danger")
        return make_response(jsonify({"message": "DB save error"}), 500)

    # ---- 10) Done ----
    flash(
        f"Tasca {task.id} afegida a la cua a {task.enqueued_at}. Estat inicial: {rq_status}",
        "success",
    )
    return redirect(url_for("status"))
