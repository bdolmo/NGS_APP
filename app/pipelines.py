# routes_pipeline.py
import json, os, re, shlex, tempfile, zipfile
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, url_for, abort, send_file
from werkzeug.routing import BuildError
from werkzeug.utils import secure_filename

import shutil
from app import app, db
from sqlalchemy.orm import joinedload
from app.models import Pipeline, PipelineParam, PipelineConfig

from config import api_gene_panels, Config
import requests

from typing import List, Dict, Tuple, Any
import subprocess
from pathlib import Path
from typing import Optional
COMPRESSED_EXTS = {".gz", ".bgz", ".bz2", ".xz", ".zip", ".zst"}

BIO_MAP = {
    "FASTQ":     {".fastq", ".fq"},
    "FASTA":     {".fasta", ".fa", ".fna"},
    "SAM":       {".sam"},
    "BAM":       {".bam"},
    "CRAM":      {".cram"},
    "VCF":       {".vcf"},
    "BCF":       {".bcf"},
    "MAF":       {".maf"},
    "GTF":       {".gtf"},
    "GFF":       {".gff", ".gff3"},
    "BED":       {".bed", ".bedgraph", ".bedpe"},
    "WIG":       {".wig"},
    "BigWig":    {".bw", ".bigwig"},
    "BigBed":    {".bb", ".bigbed"},
    "SEG":       {".seg"},
    "CNVkit":    {".cnr", ".cns"},
    "PAF":       {".paf"},
    "PILEUP":    {".pileup"},
    "HDF5":      {".h5", ".hdf5"},
    "AnnData":   {".h5ad"},
    "Loom":      {".loom"},
    "MatrixMTX": {".mtx"},
    "RDS":       {".rds", ".rdata"},
    "CSV":       {".csv"},
    "TSV":       {".tsv"},
    "PARQUET":   {".parquet"},
    "FEATHER":   {".feather"},
    "NPZ":       {".npz"},
    "PICKLE":    {".pkl"},
    "JSON":      {".json"},
    "YAML":      {".yaml", ".yml"},
    "TOML":      {".toml"},
    "INI":       {".ini", ".cfg"},
    "MARKDOWN":  {".md"},
    "HTML":      {".html", ".htm"},
    "PDF":       {".pdf"},
    "TEXT":      {".txt", ".log"},
    "Notebook":  {".ipynb"},
    "Python":    {".py"},
    "R":         {".r"},
    "Shell":     {".sh"},
    "Nextflow":  {".nf"},
    "Snakemake": {".smk"},
    "WDL":       {".wdl"},
    "CWL":       {".cwl"},
    "Image":     {".png", ".jpg", ".jpeg", ".tif", ".tiff", ".svg"},
}

INDEX_EXTS = {
    ".bai":  "BAM",
    ".crai": "CRAM",
    ".tbi":  "VCF",
    ".csi":  "VCF/BCF",
}



def multi_extension(p: Path) -> str:
    suffs = p.suffixes
    if not suffs or p.is_dir():
        return ""
    s_low = [s.lower() for s in suffs]
    if s_low[-1] in COMPRESSED_EXTS and len(suffs) >= 2:
        return "".join(suffs[-2:])  # e.g. '.vcf.gz'
    return suffs[-1]

def detect_codec(p: Path) -> str:
    last = p.suffix.lower() if p.suffix else ""
    if last in (".gz", ".bgz"):
        return "gzip/bgzip"
    if last == ".bz2":
        return "bzip2"
    if last == ".xz":
        return "xz"
    if last == ".zip":
        return "zip"
    if last == ".zst":
        return "zstd"
    return "none"

def human_size(n: int) -> str:
    units = ["B","KB","MB","GB","TB","PB"]
    i, f = 0, float(n)
    while f >= 1024 and i < len(units)-1:
        f /= 1024.0; i += 1
    return f"{f:.0f}{units[i]}" if f >= 100 else (f"{f:.1f}{units[i]}" if f >= 10 else f"{f:.2f}{units[i]}")

def classify_format(p: Path) -> Dict[str, Any]:
    """Minimal, safe classifier. Replace with your bio-aware one if you have it."""
    if p.is_dir():
        return {"ext": "", "codec": "none", "format": "DIR", "is_index": False, "index_of": "", "role": "dir"}
    suffs = "".join(p.suffixes).lower()
    last  = p.suffix.lower() if p.suffix else ""
    fmt = "Unknown"
    if suffs.endswith((".fastq.gz", ".fq.gz")) or last in (".fastq",".fq"): fmt = "FASTQ"
    elif last in (".bam",".sam",".cram"): fmt = last[1:].upper()
    elif suffs.endswith(".vcf.gz") or last in (".vcf",".bcf"): fmt = last[1:].upper() if last in (".vcf",".bcf") else "VCF"
    elif last in (".json",".yaml",".yml",".toml",".ini",".cfg"): fmt = last[1:].upper()
    elif last in (".csv",".tsv"): fmt = last[1:].upper()
    elif suffs.endswith(".xlsx"): fmt = "XLSX"
    elif suffs.endswith(".bed"): fmt = "BED"
    elif suffs.endswith(".pdf"): fmt = "PDF"
    elif suffs.endswith(".png"): fmt = "PNG"
    elif suffs.endswith(".html"): fmt = "HTML"
    codec = "gzip/bgzip" if suffs.endswith(".gz") else "none"
    is_index = last in (".bai",".tbi",".csi",".crai")
    index_of = ""
    if last == ".bai":  index_of = re.sub(r"\.bai$", ".bam", p.name, flags=re.I)
    if last == ".crai": index_of = re.sub(r"\.crai$", ".cram", p.name, flags=re.I)
    if last in (".tbi",".csi"): index_of = re.sub(r"\.(tbi|csi)$", "", p.name, flags=re.I)
    return {"ext": suffs or last, "codec": codec, "format": fmt, "is_index": is_index, "index_of": index_of, "role": "index" if is_index else "data"}


def is_fastq_gz_name(name: str) -> bool:
    return name.lower().endswith((".fastq.gz", ".fq.gz"))


def list_fastq_gz_files(base: Path) -> List[Path]:
    base = Path(base).resolve()
    files: List[Path] = []

    for dirpath, dirnames, filenames in os.walk(base, followlinks=False):
        safe_dirnames = []
        for dirname in dirnames:
            if dirname.startswith("."):
                continue
            dir_path = Path(dirpath) / dirname
            if dir_path.is_symlink():
                continue
            safe_dirnames.append(dirname)
        dirnames[:] = safe_dirnames

        for filename in filenames:
            if filename.startswith(".") or not is_fastq_gz_name(filename):
                continue
            file_path = Path(dirpath) / filename
            try:
                if file_path.is_symlink():
                    continue
                resolved = file_path.resolve()
                resolved.relative_to(base)
            except (OSError, PermissionError, ValueError):
                continue
            if resolved.is_file():
                files.append(resolved)

    return sorted(files, key=lambda p: p.relative_to(base).as_posix().casefold())


def fastq_gz_summary(base: Path) -> Dict[str, Any]:
    files = list_fastq_gz_files(base)
    total = 0
    for file_path in files:
        try:
            total += file_path.stat().st_size
        except (OSError, PermissionError):
            pass
    return {
        "count": len(files),
        "size_bytes": total,
        "size_human": human_size(total),
    }


def build_tree(
    root: Path,
    ignore_hidden: bool = True,
    follow_symlinks: bool = False,
    max_depth: Optional[int] = None,
) -> Dict[str, Any]:
    root = Path(root)
    node: Dict[str, Any] = {
        "name": root.name or str(root),
        "path": str(root),
        "kind": "dir" if root.is_dir() else "file",
        "size_bytes": 0,
        "size_human": "0B",
    }

    # File node
    if root.is_file() and (follow_symlinks or not root.is_symlink()):
        try:
            sz = root.stat().st_size
        except (OSError, PermissionError):
            sz = 0
        node["size_bytes"] = sz
        node["size_human"] = human_size(sz)
        node.update(classify_format(root))
        return node

    # Dir node
    if root.is_dir():
        node["children"] = []  # ensure present

        # depth guard: when below 0, don't list children but return a dir stub
        if max_depth is not None and max_depth < 0:
            node.update({"ext": "", "codec": "none", "format": "DIR", "is_index": False, "index_of": "", "role": "dir"})
            return node

        total = 0
        children: List[Dict[str, Any]] = []
        try:
            with os.scandir(root) as it:
                for entry in it:
                    if ignore_hidden and entry.name.startswith("."):
                        continue
                    try:
                        p = Path(entry.path)
                        if (not follow_symlinks) and entry.is_symlink():
                            continue
                        child = build_tree(
                            p,
                            ignore_hidden=ignore_hidden,
                            follow_symlinks=follow_symlinks,
                            max_depth=None if max_depth is None else max_depth - 1,
                        )
                        total += int(child.get("size_bytes", 0))
                        children.append(child)
                    except (OSError, PermissionError):
                        children.append({
                            "name": entry.name,
                            "path": str(Path(entry.path)),
                            "kind": "unknown",
                            "size_bytes": 0,
                            "size_human": "0B",
                            "ext": "",
                            "codec": "none",
                            "format": "Unknown",
                            "is_index": False,
                            "index_of": "",
                            "role": "unknown",
                        })
        except (OSError, PermissionError):
            pass

        children.sort(
            key=lambda child: (
                child.get("kind") != "dir",
                str(child.get("name", "")).casefold(),
            )
        )
        node["children"] = children
        node["size_bytes"] = total
        node["size_human"] = human_size(total)
        node.update({"ext": "", "codec": "none", "format": "DIR", "is_index": False, "index_of": "", "role": "dir"})
    return node


def safe_join_under_uploads(*parts: str) -> Path:
    # simple, safe join under UPLOADS
    candidate = (UPLOADS_ROOT / Path(*[secure_filename(p) for p in parts])).resolve()
    if not str(candidate).startswith(str(UPLOADS_ROOT)):
        raise ValueError("Path outside UPLOADS root")
    return candidate

@app.route("/workflows/tree", methods=["GET"])
def workflows_tree():
    job_id = (request.args.get("job_id") or "").strip()
    panel  = (request.args.get("panel")  or "").strip()
    path   = (request.args.get("path")   or "").strip()
    max_depth = request.args.get("max_depth", type=int)  # may be None
    follow_symlinks = (request.args.get("follow_symlinks","0") or "").lower() in ("1","true","yes")

    try:
        if path:
            root = safe_join_under_uploads(path)
        elif job_id and panel:
            root = safe_join_under_uploads(job_id, panel)
        elif job_id:
            root = safe_join_under_uploads(job_id)
        else:
            root = UPLOADS_ROOT

        if not root.exists():
            return jsonify(error=f"Path not found: {root}"), 404

        tree = build_tree(root, ignore_hidden=True, follow_symlinks=follow_symlinks, max_depth=max_depth if max_depth is not None else 5)
        return jsonify(tree), 200
    except ValueError as e:
        return jsonify(error=str(e)), 400
    except Exception as e:
        return jsonify(error=f"Server error: {e}"), 500


def _safe_join_under_uploads(*parts: str) -> Path:
    """Prevent path traversal outside UPLOADS."""
    p = (UPLOADS_ROOT / Path(*[secure_filename(x) for x in parts if x])).resolve()
    if not str(p).startswith(str(UPLOADS_ROOT)):
        raise ValueError("Path outside UPLOADS")
    return p

@app.route("/workflows/tree_view", methods=["GET"])
def workflows_tree_view():
    """
    Server-side rendered directory tree.
    Example: /workflows/tree_view?job_id=TEST_NEW_CMD&panel=GenOncology-Dx.v1&max_depth=5
    """
    job_id: str = (request.args.get("job_id") or "").strip()
    panel:  str = (request.args.get("panel") or "").strip()
    max_depth: Optional[int] = request.args.get("max_depth", type=int) or 5

    try:
        if job_id and panel:
            root = _safe_join_under_uploads(job_id, panel)
        elif job_id:
            root = _safe_join_under_uploads(job_id)
        else:
            root = UPLOADS_ROOT

        if not root.exists():
            return render_template(
                "tree_modal.html",
                tree=None,
                error=f"Path not found: {root}",
                job_id=job_id,
                panel=panel,
                resolved_path=str(root),
                max_depth=max_depth,
                fastq_count=0,
                fastq_total_human="0B",
                title=f"Directori {job_id}"
            )

        tree = build_tree(root, ignore_hidden=True, follow_symlinks=False, max_depth=max_depth)
        fastq_summary = fastq_gz_summary(root)
        return render_template(
            "tree_modal.html",
            tree=tree,
            error=None,
            job_id=job_id,
            panel=panel,
            resolved_path=str(root),
            max_depth=max_depth,
            fastq_count=fastq_summary["count"],
            fastq_total_human=fastq_summary["size_human"],
            title=f"Directori {job_id}"
        )
    except ValueError as e:
        return render_template(
            "tree_modal.html",
            tree=None,
            error=str(e),
            job_id=job_id,
            panel=panel,
            resolved_path="",
            max_depth=max_depth,
            fastq_count=0,
            fastq_total_human="0B",
            title=f"Directori {job_id}"
        )


@app.route("/workflows/download", methods=["GET"])
def workflows_download():
    """
    Download a single file from UPLOADS, scoped by (job_id, panel) and a rel path.

    Expected query:
      ?job_id=RUN123&panel=GenOncology-Dx.v1&rel=reports/sample1/sample1.vcf.gz
    If job_id/panel are omitted, rel is considered relative to UPLOADS root.
    """
    job_id = (request.args.get("job_id") or "").strip()
    panel  = (request.args.get("panel")  or "").strip()
    rel    = (request.args.get("rel")    or "").lstrip("/").strip()

    if not rel:
        abort(400, "Missing rel")

    try:
        # Build the base directory (UPLOADS[/job_id][/panel]) safely
        base = _safe_join_under_uploads(*(p for p in [job_id, panel] if p))
        target = (base / rel).resolve()
        # Final containment check
        if not str(target).startswith(str(UPLOADS_ROOT)):
            abort(400, "Invalid path")
        if not target.exists() or not target.is_file():
            abort(404, "File not found")
    except ValueError as e:
        abort(400, str(e))
    except Exception:
        abort(500, "Server error resolving download")

    # Send as attachment
    return send_file(
        str(target),
        as_attachment=True,
        download_name=target.name  # Flask >= 2.0
    )


@app.route("/workflows/download_fastq_gz", methods=["GET"])
def workflows_download_fastq_gz():
    """Download all FASTQ.GZ files under UPLOADS[/job_id][/panel] as one ZIP."""
    job_id = (request.args.get("job_id") or "").strip()
    panel = (request.args.get("panel") or "").strip()

    try:
        base = _safe_join_under_uploads(*(p for p in [job_id, panel] if p))
        if not base.exists() or not base.is_dir():
            abort(404, "Directory not found")
        fastq_files = list_fastq_gz_files(base)
        if not fastq_files:
            abort(404, "No FASTQ.GZ files found")
    except ValueError as e:
        abort(400, str(e))

    archive_stem = secure_filename("_".join(p for p in [job_id, panel, "fastq_gz"] if p)) or "fastq_gz"
    download_name = f"{archive_stem}.zip"

    tmp = tempfile.NamedTemporaryFile(delete=False, suffix=".zip")
    zip_path = tmp.name
    tmp.close()

    try:
        with zipfile.ZipFile(zip_path, "w", compression=zipfile.ZIP_STORED, allowZip64=True) as zip_file:
            for fastq_file in fastq_files:
                arcname = fastq_file.relative_to(base).as_posix()
                zip_file.write(fastq_file, arcname)
    except Exception:
        try:
            os.remove(zip_path)
        except OSError:
            pass
        raise

    response = send_file(
        zip_path,
        mimetype="application/zip",
        as_attachment=True,
        download_name=download_name,
    )
    def cleanup_zip():
        try:
            os.remove(zip_path)
        except OSError:
            pass

    response.call_on_close(cleanup_zip)
    return response

# ---------- helpers to infer types ----------
_num_int  = re.compile(r'^[+-]?\d+$')
_num_float= re.compile(r'^[+-]?\d*\.\d+$')

def get_gene_panels():
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
    return gene_panels

UPLOADS_ROOT = Path(Config.UPLOADS).resolve()

def safe_join_under_uploads(*parts: str) -> Path:
    candidate = (UPLOADS_ROOT / Path(*[secure_filename(p) for p in parts])).resolve()
    if not str(candidate).startswith(str(UPLOADS_ROOT)):
        raise ValueError("Path outside UPLOADS root")
    return candidate


# routes_pipeline.py (add this)
@app.route("/workflows/config", endpoint="workflows_config")
def pipeline_list_page():
    return render_template("pipeline_list.html", title="Pipelines")


@app.route("/pipelines/new", endpoint="pipeline_new_page")
def pipeline_new_page():
    """
        Render the empty/new pipeline form. Optionally prefill from a CLI (?cmd=...).
    """
    cmd = (request.args.get("cmd") or "").strip()

    # default empty seed
    seed = {
        "pipeline": {
            "interpreter": "",
            "entrypoint": "",
            "workdir": "",
            "suggested_name": ""
        },
        "params": []
    }

    # If a CLI was provided, prefill using the same parser you expose via API
    if cmd:
        try:
            seed = parse_cli(cmd)  # call function directly, no HTTP hop
        except Exception:
            pass  # keep empty seed on parse failure

    return render_template(
        "pipeline_config.html",
        title="Nou workflow",
        pipeline_id=None,   # important so the template knows it's a new one
        mode="create",      # your template/JS can switch POST vs PUT based on this
        seed=seed
    )


# routes_pipeline.py  (add these)
@app.route("/pipelines/<int:pipeline_id>/edit", endpoint="pipeline_edit_page")
def pipeline_edit_page(pipeline_id):
    # same template, but open in "edit" mode
    # get pipeline name
    pipeline = Pipeline.query.filter_by(id=pipeline_id).first()
    pipeline_name = pipeline.name

    return render_template(
        "pipeline_config.html",
        title="Edita Workflow",
        pipeline_id=pipeline_id,
        pipeline_name=pipeline_name,
        mode="edit",
    )

@app.route("/workflows/analysis")
def analyze_workflows():
    pipelines = Pipeline.query.all()

    return render_template("analyze_workflow.html", workflows=pipelines)

@app.route('/workflows/<int:pipeline_id>')
def view_workflow(pipeline_id):
    pipeline = (
        Pipeline.query.options(
            joinedload(Pipeline.params),
            joinedload(Pipeline.configs)
        ).get(pipeline_id)
    )
    if not pipeline:
        abort(404)

    def parse_json(s, default):
        try:
            return json.loads(s) if s else default
        except Exception:
            return default

    def param_sort_key(p):
        return (not bool(p.is_positional), p.position or 1_000_000, (p.name or '').lower())

    PATH_HINT = re.compile(r"(path|dir|folder|file|fastq|fq|bam|vcf|outdir|output|input)s?$", re.I)

    all_params = []
    for p in sorted(pipeline.params, key=param_sort_key):
        p_type = (p.type or "string").lower()
        name = p.name or ""
        is_pathlike = (p_type in {"file","dir"}) or bool(PATH_HINT.search(name))
        choices = parse_json(p.choices_json, [])
        norm_choices = []
        for c in choices:
            if isinstance(c, (list, tuple)) and len(c) >= 2:
                norm_choices.append({"value": c[0], "label": c[1]})
            else:
                norm_choices.append({"value": c, "label": c})
        all_params.append({
            "id": p.id,
            "name": name,
            "type": p_type,
            "default": p.default,
            "required": bool(p.required),
            "is_positional": bool(p.is_positional),
            "position": p.position,
            "description": p.description,
            "choices": norm_choices,
            "group_name": (p.group_name or "").strip() or "General",
            "group_format": (p.group_format or "").strip(),   # e.g., 'multi' or 'radio'
            "is_pathlike": is_pathlike,
        })

    workflow_command = {
        "interpreter": pipeline.interpreter,
        "entrypoint": pipeline.entrypoint,
        "params": []
    }
    for item in pipeline.params:
        param_dict = {}
        param_dict["positional"] = item.is_positional
        param_dict["id"] = item.id
        if item.is_positional:
            param_dict["name"] =  item.default
        else:
            param_dict["name"] =  item.name
    
        param_dict["default_value"] = item.default
        workflow_command["params"].append(param_dict)

    # Inputs shown at the top as real <input type="file"> controls
    def is_input(x):
        n = x["name"].lower(); g = x["group_name"].lower()
        return g in {"io","input","inputs"} or n in {"input","inputs","r1","r2","fastq","fastqs","bam"}

    inputs = [x for x in all_params if is_input(x)]

    # Bottom panel params: everything except inputs (no Outputs section anymore)
    others = [x for x in all_params if x not in inputs]

    # Group for the collapsible panel
    grouped = {}
    for x in others:
        if x["required"] == 1:
            grouped.setdefault(x["group_name"], []).append(x)

    grouped_params = []
    for key, items in grouped.items():
        items.sort(key=lambda z: ((z.get("position") or 1_000_000), z["name"].lower()))
        grouped_params.append({"name": key, "params": items})
    grouped_params.sort(key=lambda g: (g["name"] != "General", g["name"].lower()))

    gene_panels = get_gene_panels()

    return render_template(
        "workflow_run.html",
        gene_panels=gene_panels,
        pipeline=pipeline,
        workflow_command=workflow_command,
        inputs=inputs,
        grouped_params=grouped_params,
        total_params=len(all_params),
    )

@app.put("/api/pipelines/<int:pipeline_id>")
def api_update_pipeline(pipeline_id):
    p = Pipeline.query.get_or_404(pipeline_id)
    payload = request.get_json(force=True)
    base = (payload.get("pipeline") or {})
    params = (payload.get("params") or [])

    # update base fields
    p.name        = (base.get("name") or p.name).strip()
    p.version     = (base.get("version") or "").strip()
    p.entrypoint  = (base.get("entrypoint") or "").strip()
    p.workdir     = (base.get("workdir") or "").strip()
    p.interpreter = (base.get("interpreter") or "").strip()
    p.env_vars_json = json.dumps(base.get("env_vars") or {}, ensure_ascii=False)
    p.meta_json     = json.dumps(base.get("meta") or {}, ensure_ascii=False)
    p.is_set_default =(base.get("lockdefault") or "").strip()
    p.description = (base.get("description") or "").strip()

    # replace params
    PipelineParam.query.filter_by(pipeline_id=p.id).delete(synchronize_session=False)
    for pr in params:
        db.session.add(PipelineParam(
            pipeline_id=p.id,
            name=pr.get("name"),
            short=pr.get("short"),
            type=pr.get("type") or "string",
            default=str(pr.get("default") if pr.get("default") is not None else ""),
            required=bool(pr.get("required")),
            is_positional=bool(pr.get("is_positional")),
            position=pr.get("position"),
            description=pr.get("description"),
            choices_json=json.dumps(pr.get("choices") or [], ensure_ascii=False),
            group_name=pr.get("group_name"),
            group_format=pr.get("group_format"),
            is_set_default=pr.get("lockdefault")
        ))

    db.session.commit()
    return jsonify({"ok": True, "pipeline_id": p.id})


# routes_pipeline.py (add this under your other APIs)
@app.delete("/api/pipelines/<int:pipeline_id>")
def api_delete_pipeline(pipeline_id):
    p = Pipeline.query.get_or_404(pipeline_id)
    # If your relationships lack cascade delete, remove children explicitly:
    PipelineParam.query.filter_by(pipeline_id=pipeline_id).delete(synchronize_session=False)
    PipelineConfig.query.filter_by(pipeline_id=pipeline_id).delete(synchronize_session=False)
    db.session.delete(p)
    db.session.commit()
    return jsonify({"ok": True})

@app.route("/configure", endpoint="pipeline_config_page")
def pipeline_config_page():
    return render_template("pipeline_config.html", title="Configure Pipeline")

def _infer_simple_type(val:str):
    if val is None: return "string"
    s = str(val).strip()
    if s.lower() in ("true","false","yes","no","on","off","0","1"):
        return "bool"
    if _num_int.match(s): return "int"
    if _num_float.match(s): return "float"
    if any(s.endswith(ext) for ext in (".fastq.gz", ".fastq", ".bam",".vcf",".vcf.gz",".csv",".tsv",".yaml",".yml",".json",".txt",".bed",".py",".sh")) or "/" in s:
        # rough heuristic
        return "file"
    return "string"

def _coerce(v, t):
    if t == "int":
        try: return int(v)
        except: return v
    if t == "float":
        try: return float(v)
        except: return v
    if t == "bool":
        if isinstance(v, bool): return v
        return str(v).lower() in ("1","true","yes","y","on")
    return v


HELP_SECT_RE = re.compile(r'^\s*([A-Za-z].*?):\s*$')             # e.g. "optional arguments:"
USAGE_RE     = re.compile(r'^\s*usage:\s*(.+)$', re.I)
# Lines like: "  -j N, --cores N    Number of cores [default: 1]"
# or:         "  --genome GENOME    Reference genome {hg19,hg38}"
OPT_SPLIT_RE = re.compile(r'^\s{0,8}(.+?)\s{2,}(.*)$')           # left  /  right (help text)
IS_FLAG_RE   = re.compile(r'^\s*-\S')                            # starts with a dash (flag)
CHOICES_RE   = re.compile(r'\{([^}]+)\}')                        # {a,b,c}
DEFAULTS_RES = [
    re.compile(r'\[default:\s*([^\]]+)\]', re.I),
    re.compile(r'\(default:\s*([^)]+)\)', re.I),
    re.compile(r'default\s*=\s*([^\s,;]+)', re.I),
]
REQUIRED_RE  = re.compile(r'\brequired\b', re.I)

# Heuristic type inference from metavar / text
def _infer_type_from_metavar(metavar: str) -> str:
    mv = (metavar or '').strip().upper()
    if not mv:
        return 'bool'  # flags without metavar
    if any(k in mv for k in ['INT', 'N', 'NUM', 'COUNT', 'THREAD', 'CORES']):
        return 'int'
    if any(k in mv for k in ['FLOAT', 'DOUBLE', 'FP', 'ALPHA', 'BETA']):
        return 'float'
    if any(k in mv for k in ['DIR', 'DIRECTORY']):
        return 'dir'
    if any(k in mv for k in ['FILE', 'PATH', 'FASTQ', 'BAM', 'VCF', 'BED', 'YAML', 'JSON', 'TSV', 'CSV']):
        return 'file'
    if CHOICES_RE.search(mv):
        return 'choice'
    return 'string'

def _extract_default(text: str) -> str:
    if not text: return ''
    for rx in DEFAULTS_RES:
        m = rx.search(text)
        if m:
            return m.group(1).strip()
    return ''

def _extract_choices(text_or_mv: str) -> List[str]:
    m = CHOICES_RE.search(text_or_mv or '')
    if not m: return []
    return [c.strip() for c in m.group(1).split(',') if c.strip()]

def _tokenize_flags(left: str) -> Tuple[List[str], str]:
    """
    Split left column: "-j N, --cores N" -> flags ["-j", "--cores"], metavar "N"
    Also supports "--flag", "--flag VALUE", "--flag=VALUE"
    """
    # Normalize commas and multiple spaces
    parts = [p.strip() for p in left.split(',')]
    flags = []
    metavar = ''
    for part in parts:
        toks = part.split()
        if not toks: continue
        # "--flag=VALUE" style
        if '=' in toks[0] and toks[0].startswith('-'):
            flag, mv = toks[0].split('=', 1)
            flags.append(flag)
            if mv and not metavar: metavar = mv
            continue
        # "--flag VALUE" or "--flag"
        if toks[0].startswith('-'):
            flags.append(toks[0])
            # take last token as metavar if it is not a flag and is uppercase-like
            if len(toks) >= 2 and not toks[-1].startswith('-'):
                metavar = toks[-1]
        else:
            # positional (no leading dash)
            pass
    return flags, metavar

def _clean_desc(s: str) -> str:
    s = (s or '').strip()
    # Common argparse filler
    return re.sub(r'\s+', ' ', s)

def parse_help_command(command: str) -> Dict:
    """
    Execute `<command> --help` (or -h) and parse argparse-like help into our schema.
    Returns { "pipeline": {...}, "params": [...] } similar to parse_cli.
    """
    cmd = (command or '').strip()
    if not cmd:
        return {"pipeline": {}, "params": []}

    # Ensure we try with help; if the user already included -h/--help, keep it.
    toks = shlex.split(cmd)
    has_help = any(t in ('-h', '--help') or t.endswith('help') for t in toks)
    if not has_help:
        # For nextflow, prefer inserting before params only if "run" present
        if toks and toks[0] == 'nextflow':
            # nextflow run PIPELINE --help  (works)
            toks.append('--help')
        else:
            toks.append('--help')

    # Run help safely
    try:
        proc = subprocess.run(
            toks,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            timeout=10,
            check=False,
            text=True,
            env={**os.environ, 'PYTHONWARNINGS': 'ignore'}
        )
        help_text = proc.stdout or ''
    except Exception as e:
        # If execution fails, return empty but keep pipeline meta from CLI parse
        base = parse_cli(command).get('pipeline', {})
        return {"pipeline": base, "params": []}

    # Parse meta via your existing CLI heuristics (interpreter/entrypoint/name)
    base_meta = parse_cli(command).get('pipeline', {})

    lines = help_text.splitlines()
    # Join wrapped description lines: collect option blocks under current section
    section = None
    params: Dict[str, Dict] = {}
    positionals: List[Dict] = []
    buf_left, buf_right = None, None

    def flush_option():
        nonlocal buf_left, buf_right, section
        if not buf_left: return
        left = buf_left
        desc = _clean_desc(buf_right or '')
        buf_left, buf_right = None, None

        if IS_FLAG_RE.match(left):
            flags, metavar = _tokenize_flags(left)
            long_name = None
            short = None
            for f in flags:
                if f.startswith('--'):
                    long_name = f
                elif f.startswith('-') and len(f) == 2:
                    short = f[1]
            # Fallback: if no long flag, use first token as name (without dashes)
            if not long_name:
                long_name = flags[0] if flags else left.strip()
            clean = long_name.lstrip('-')

            default = _extract_default(desc)
            choices = _extract_choices(desc) or _extract_choices(metavar)
            typ = _infer_type_from_metavar(metavar)
            if choices and typ != 'bool':
                typ = 'choice'
            required = bool(REQUIRED_RE.search(desc) or (section and 'required' in section.lower()))
            is_bool = (typ == 'bool')

            p = params.get(clean, {
                "name": clean,
                "short": short,
                "type": None,
                "default": "",
                "required": False,
                "is_positional": False,
                "is_set_default": False,
                "position": None,
                "description": "",
                "choices": [],
                "group_name": section or None
            })
            # Prefer first discovered short if any
            if short and not p.get('short'):
                p['short'] = short

            p['choices'] = p.get('choices') or choices
            # Type & default
            if not p['type']:
                p['type'] = typ if typ else 'string'
            if is_bool:
                # boolean flags default to "", set True if "store_true"-like (no explicit default)
                p['default'] = True if default in ('', None) else (default.lower() in ('1','true','yes','on'))
                # normalize (UI expects True/"" pattern)
                p['default'] = True if p['default'] else ""
            else:
                if default != '':
                    p['default'] = default
            # Description
            if desc:
                p['description'] = (p['description'] + ' ' + desc).strip()
            params[clean] = p
        else:
            # positional
            name = left.strip().split()[0]
            pos = {
                "name": name,
                "short": None,
                "type": _infer_type_from_metavar(name),
                "default": "",
                "required": True,
                "is_positional": True,
                "is_set_default":True,
                "position": len(positionals)+1,
                "description": _clean_desc(desc),
                "choices": [],
                "group_name": section or None
            }
            positionals.append(pos)

    for raw in lines:
        # Section headers
        msect = HELP_SECT_RE.match(raw)
        if msect:
            # flush pending
            flush_option()
            section = msect.group(1).strip()
            continue

        # usage line? just flush and skip
        if USAGE_RE.match(raw):
            flush_option()
            continue

        m = OPT_SPLIT_RE.match(raw)
        if m:
            # new option/positional line begins
            flush_option()
            buf_left, buf_right = m.group(1), m.group(2)
        else:
            # continuation of previous description (wrapped)
            if buf_left is not None:
                if raw.strip():
                    buf_right = (buf_right or '') + ' ' + raw.strip()

    # flush tail
    flush_option()

    # Merge positionals into params dict (keep your schema)
    for pos in positionals:
        params[pos['name']] = pos

    # Final normalization like parse_cli
    # Fill missing types/default normalization for bools
    for p in params.values():
        if p['type'] in (None, ''):
            p['type'] = 'bool' if isinstance(p.get('default'), bool) else 'string'
        if p['type'] == 'bool':
            p['default'] = True if p.get('default') else ""

    # Sort: positionals first by position, then by name
    sorted_params = sorted(
        params.values(),
        key=lambda x: (not x.get('is_positional'), x.get('position') or 0, x.get('name') or '')
    )

    return {
        "pipeline": {
            "interpreter": base_meta.get('interpreter', ''),
            "entrypoint": base_meta.get('entrypoint', ''),
            "workdir": base_meta.get('workdir', ''),
            "suggested_name": base_meta.get('suggested_name') or base_meta.get('interpreter') or ''
        },
        "params": sorted_params
    }


# ---------- the CLI parser ----------
def parse_cli(command:str):
    """
    Parse a full CLI into:
      - interpreter (first token)
      - entrypoint (heuristics: snakemake -s, nextflow run, python script.py, bash script.sh, else first non-flag)
      - params: list of {name, short, type, default, required, is_positional, position, description, choices}
    Also expands snakemake --config key=val [key2=val2,...].
    """
    toks = shlex.split(command)
    if not toks:
        return {"pipeline": {}, "params": []}

    interpreter = toks[0]
    i = 1
    entrypoint = None
    params = {}
    positionals = []

    def put_param(name, value, short=None, is_flag=True):
        # make a clean name (no leading dashes)
        clean = name.lstrip('-')
        if not clean:
            return
        p = params.get(clean, {
            "name": clean, "short": short, "type": None, "default": "",
            "required": False, "is_positional": False, "position": None,
            "description": "", "choices": []
        })
        if is_flag:
            if isinstance(value, bool):
                p["type"] = p["type"] or "bool"
                if value: p["default"] = True
                else:     p["default"] = ""
            else:
                # try to infer type from value
                p["type"] = p["type"] or _infer_simple_type(value)
                p["default"] = str(value)
        params[clean] = p

    # helper to expand snakemake --config
    def expand_config_value(raw_parts):
        # raw_parts is a list of tokens that belong to --config until a flag starts
        # supports "k=v a=b" and "k=v,a=b"
        pairs = {}
        buf = []
        for part in raw_parts:
            if part.startswith('-'): break
            buf.append(part)
        joined = " ".join(buf).replace(",", " ")
        for piece in joined.split():
            if "=" in piece:
                k,v = piece.split("=",1)
                k = k.strip(); v = v.strip()
                if k: pairs[k] = v
        return pairs, len(buf)

    # detect entrypoint for common interpreters
    def detect_entrypoint_for(interp, toks, start_index):
        j = start_index
        if interp == "snakemake":
            # look for -s/--snakefile
            jj = j
            while jj < len(toks):
                t = toks[jj]
                if t in ("-s","--snakefile"):
                    if jj+1 < len(toks) and not toks[jj+1].startswith("-"):
                        return toks[jj+1], start_index
                if t.startswith("--snakefile=") or t.startswith("-s="):
                    return t.split("=",1)[1], start_index
                jj += 1
            return None, start_index
        if interp in ("python","python3","py"):
            # next non-flag token that looks like a script
            while j < len(toks):
                t = toks[j]
                if t == "-m" and j+1 < len(toks):
                    return f"-m {toks[j+1]}", j+2
                if not t.startswith("-") and (t.endswith(".py") or "/" in t or t.endswith(".ipynb")):
                    return t, j+1
                j += 1
            return None, start_index
        if interp in ("bash","sh","zsh"):
            while j < len(toks):
                t = toks[j]
                if not t.startswith("-") and (t.endswith(".sh") or "/" in t):
                    return t, j+1
                j += 1
            return None, start_index
        if interp == "nextflow":
            # nextflow run <pipeline_main.nf> [params...]
            if j < len(toks) and toks[j] == "run" and (j+1) < len(toks):
                return toks[j+1], j+2
            return None, start_index
        # generic: first non-flag after interpreter
        while j < len(toks):
            t = toks[j]
            if not t.startswith("-"):
                return t, j+1
            j += 1
        return None, start_index

    entrypoint, i = detect_entrypoint_for(interpreter, toks, i)

    # sweep remaining tokens into flags/values/positionals
    pos_counter = 1
    n = len(toks)
    while i < n:
        t = toks[i]

        # long flags
        if t.startswith("--"):
            # handle --flag=value
            if "=" in t:
                name, v = t.split("=", 1); put_param(name, v, is_flag=True)
                i += 1; continue

            name = t
            # special: snakemake --config ...
            if interpreter == "snakemake" and name == "--config":
                # capture following non-flag tokens
                pairs, consumed = expand_config_value(toks[i+1:])
                for k, v in pairs.items():
                    put_param(k, v, is_flag=True)
                i += 1 + consumed
                continue

            # normal flag: boolean if next is a flag or end; else take next as value
            if i+1 < n and not toks[i+1].startswith("-"):
                put_param(name, toks[i+1], is_flag=True); i += 2
            else:
                put_param(name, True, is_flag=True); i += 1
            continue

        # short flags like -k or -j 8
        if t.startswith("-") and len(t) >= 2:
            # collapse cluster like -abc into -a -b -c (as booleans)
            if len(t) > 2 and "=" not in t:
                for ch in t[1:]:
                    put_param("-"+ch, True, short=ch, is_flag=True)
                i += 1; continue

            # handle -k=value
            if "=" in t:
                name, v = t.split("=", 1); put_param(name, v, short=t[1], is_flag=True)
                i += 1; continue

            # -k [value]?
            if i+1 < n and not toks[i+1].startswith("-"):
                put_param(t, toks[i+1], short=t[1], is_flag=True); i += 2
            else:
                put_param(t, True, short=t[1], is_flag=True); i += 1
            continue

        # positional
        positionals.append(t)
        i += 1

    # add positionals
    for idx, val in enumerate(positionals, start=1):
        name = f"pos{idx}"
        params[name] = {
            "name": name, "short": None, "type": _infer_simple_type(val),
            "default": str(val), "required": True, "is_positional": True,
            "position": idx, "description": f"Positional argument #{idx}", "choices": []
        }

    # finalize types for flags with defaults
    for p in params.values():
        if p["type"] in (None, ""):
            p["type"] = "bool" if isinstance(p.get("default"), bool) else "string"
        # normalize bool default to True/"" string for transport
        if p["type"] == "bool":
            p["default"] = True if p.get("default") else ""

    # suggest a name from entrypoint
    suggested = None
    if entrypoint:
        base = entrypoint.split()[-1]  # handles "-m package.module"
        suggested = os.path.splitext(os.path.basename(base))[0] or base

    return {
        "pipeline": {
            "interpreter": interpreter,
            "entrypoint": entrypoint or "",
            "workdir": "",
            "suggested_name": suggested or interpreter
        },
        "params": sorted(params.values(), key=lambda x: (not x["is_positional"], x.get("position") or 0, x["name"]))
    }

# ---------- API: parse CLI ----------
@app.post("/api/pipelines/parse-cli")
def api_parse_cli():
    payload = request.get_json(force=True)
    command = (payload.get("command") or "").strip()
    if not command:
        return jsonify({"ok": False, "error": "Empty command"}), 400
    parsed = parse_cli(command)
    return jsonify({"ok": True, **parsed})


@app.post("/api/pipelines/parse-help")
def api_parse_help():
    payload = request.get_json(force=True)
    command = (payload.get("command") or "").strip()
    if not command:
        return jsonify({"ok": False, "error": "Empty command"}), 400
    try:
        parsed = parse_help_command(command)
        return jsonify({"ok": True, **parsed})
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 500


# routes_pipeline.py (append these)
from hashlib import md5

# CREATE pipeline
@app.post("/api/pipelines")
def api_create_pipeline():
    payload = request.get_json(force=True)
    base = (payload.get("pipeline") or {})
    params = (payload.get("params") or [])

    name = (base.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "Pipeline name is required"}), 400

    p = Pipeline(
        name=name,
        version=(base.get("version") or "").strip(),
        entrypoint=(base.get("entrypoint") or "").strip(),
        workdir=(base.get("workdir") or "").strip(),
        interpreter=(base.get("interpreter") or "").strip(),
        env_vars_json=json.dumps(base.get("env_vars") or {}, ensure_ascii=False),
        meta_json=json.dumps(base.get("meta") or {}, ensure_ascii=False),
        created_by=(base.get("created_by") or "system"),
        description = (base.get("description") or "").strip()
    )
    db.session.add(p)
    db.session.flush()  # to get p.id

    for pr in params:
        prm = PipelineParam(
            pipeline_id=p.id,
            name=pr.get("name"),
            short=pr.get("short"),
            type=pr.get("type") or "string",
            default=str(pr.get("default") if pr.get("default") is not None else ""),
            required=bool(pr.get("required")),
            is_positional=bool(pr.get("is_positional")),
            position=pr.get("position"),
            description=pr.get("description"),
            choices_json=json.dumps(pr.get("choices") or [], ensure_ascii=False),
            group_name=pr.get("group_name")
        )
        db.session.add(prm)

    db.session.commit()
    return jsonify({"ok": True, "pipeline_id": p.id})


# LIST pipelines
@app.get("/api/pipelines")
def api_list_pipelines():
    rows = Pipeline.query.order_by(Pipeline.created_at.desc()).all()
    data = [{"id": r.id, "name": r.name, "version": r.version, "interpreter": r.interpreter, "description": r.description} for r in rows]
    return jsonify({"pipelines": data})


# GET single pipeline (with params)
@app.get("/api/pipelines/<int:pipeline_id>")
def api_get_pipeline(pipeline_id):
    p = Pipeline.query.get_or_404(pipeline_id)
    params = []
    for prm in p.params:
        try:
            choices = json.loads(prm.choices_json) if prm.choices_json else []
        except Exception:
            choices = []
        params.append({
            "id": prm.id,
            "name": prm.name,
            "short": prm.short,
            "type": prm.type,
            "default": prm.default,
            "required": prm.required,
            "is_positional": prm.is_positional,
            "position": prm.position,
            "description": prm.description,
            "choices": choices,
            "group_name": prm.group_name,
            "group_format": prm.group_format,
            "is_set_default": prm.is_set_default,
        })

    try:
        env_vars = json.loads(p.env_vars_json) if p.env_vars_json else {}
    except Exception:
        env_vars = {}
    try:
        meta = json.loads(p.meta_json) if p.meta_json else {}
    except Exception:
        meta = {}

    return jsonify({
        "pipeline": {
            "id": p.id, "name": p.name, "version": p.version,
            "entrypoint": p.entrypoint, "workdir": p.workdir, "interpreter": p.interpreter,
            "env_vars": env_vars, "meta": meta
        },
        "params": params
    })


# SAVE a configuration for a pipeline
@app.post("/api/pipelines/<int:pipeline_id>/configs")
def api_create_config(pipeline_id):
    _ = Pipeline.query.get_or_404(pipeline_id)
    payload = request.get_json(force=True)
    name    = (payload.get("name") or f"cfg-{datetime.utcnow().isoformat()}").strip()
    values  = payload.get("values") or {}
    created_by = (payload.get("created_by") or "system")

    values_json = json.dumps(values, ensure_ascii=False)
    # compute a stable hash even if key order differs
    try:
        canonical = json.dumps(json.loads(values_json), sort_keys=True, ensure_ascii=False)
    except Exception:
        canonical = values_json
    cfg_hash = md5(canonical.encode("utf-8")).hexdigest()

    cfg = PipelineConfig(
        pipeline_id=pipeline_id,
        name=name,
        values_json=values_json,
        created_by=created_by,
        hash=cfg_hash
    )
    db.session.add(cfg)
    db.session.commit()
    return jsonify({"ok": True, "config_id": cfg.id, "hash": cfg.hash})


# helper to compose command from pipeline + params + values (uses your _coerce)
def _compose_command(p, params, values: dict):
    parts = []
    interp = (p.interpreter or "").strip()
    entry  = (p.entrypoint  or "").strip()

    if interp:
        parts.append(interp)
        # small convenience: if snakemake and we have an entrypoint, add -s <file>
        if interp == "snakemake" and entry:
            parts.extend(["-s", entry])
        elif entry:
            parts.append(entry)
    elif entry:
        parts.append(entry)

    # positionals first
    pos = [pr for pr in params if pr.is_positional]
    pos.sort(key=lambda x: (x.position or 0))
    for pr in pos:
        v = values.get(pr.name, pr.default)
        v = _coerce(v, pr.type)
        if (v is None or v == "") and pr.required:
            raise ValueError(f"Missing required positional: {pr.name}")
        if v not in (None, ""):
            parts.append(str(v))

    # named flags
    named = [pr for pr in params if not pr.is_positional]
    for pr in named:
        v = values.get(pr.name, pr.default)
        v = _coerce(v, pr.type)
        flag = f"--{pr.name}" if pr.name and not pr.name.startswith('-') else pr.name
        if pr.type == "bool":
            if v:
                parts.append(flag)
        else:
            if (v is None or v == "") and pr.required:
                raise ValueError(f"Missing required option: {pr.name}")
            if v not in (None, ""):
                parts.append(flag)
                parts.append(str(v))

    return " ".join(shlex.quote(x) for x in parts)


# RENDER a command from values
@app.post("/api/pipelines/render-cmd")
def api_render_cmd():
    payload = request.get_json(force=True)
    pid = payload.get("pipeline_id")
    values = payload.get("values") or {}
    if not pid:
        return jsonify({"ok": False, "error": "pipeline_id required"}), 400

    p = Pipeline.query.get_or_404(pid)
    params = PipelineParam.query.filter_by(pipeline_id=pid).all()

    try:
        cmd = _compose_command(p, params, values)
    except Exception as e:
        return jsonify({"ok": False, "error": str(e)}), 400

    return jsonify({"ok": True, "command": cmd})


@app.get("/api/pipelines/check-interpreter")
def api_check_interpreter():
    name = (request.args.get("name") or "").strip()
    if not name:
        return jsonify({"ok": False, "error": "name required"}), 400
    # Agafa només el primer token com a binari a buscar
    try:
        binary = shlex.split(name)[0]
    except Exception:
        binary = name.split()[0]
    path = shutil.which(binary)
    return jsonify({"ok": True, "name": binary, "found": bool(path), "path": path})
