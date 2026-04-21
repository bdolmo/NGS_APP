# app/versions.py
from pathlib import Path
from typing import Dict, Tuple, Optional
import os
import yaml
from flask import request, jsonify, abort
from app import app, db  # noqa: F401  (db is imported as per your base)
from app.software_versions import get_pipeline_version_info
from app.models import (
    TherapeuticTable,
    OtherVariantsTable,
    RareVariantsTable,
    Petition,
)

ANNOTATION_FILE = "annotation_resources_hg19.yaml"
BINARIES_FILE   = "binary_resources.yaml"
DOCKER_FILE     = "docker_resources.yaml"
BASE_ROOT       = Path("/ngs-results")  # root for analysis folders


def _load_yaml(path: Path):
    if not path.exists():
        raise FileNotFoundError(f"Missing file: {path}")
    with path.open("r", encoding="utf-8") as fh:
        return yaml.safe_load(fh) or {}


def _extract_versions(d: dict, skip_keys: set = None) -> Dict[str, str]:
    """One level deep: for dict values with a 'version' key, return {section: version}."""
    skip = skip_keys or set()
    out: Dict[str, str] = {}
    for k, v in d.items():
        if k in skip:
            continue
        if isinstance(v, dict) and "version" in v:
            out[str(k)] = v.get("version", "")
    return out


def _resolve_analysis_folder(run_name: str, panel_name: Optional[str]) -> Path:
    """
    Build /ngs-results/{run_name}/{panel_name}.
    If panel_name is None, auto-resolve only if there is exactly one subdirectory.
    """
    run_dir = BASE_ROOT / run_name
    if not run_dir.exists():
        raise FileNotFoundError(f"Run folder not found: {run_dir}")

    if panel_name:
        analysis_dir = run_dir / panel_name
        if not analysis_dir.exists():
            raise FileNotFoundError(f"Panel folder not found: {analysis_dir}")
        return analysis_dir

    # Auto-resolve panel if there's exactly one subdir
    subdirs = [e.name for e in os.scandir(run_dir) if e.is_dir()]
    if len(subdirs) == 1:
        return run_dir / subdirs[0]
    elif len(subdirs) == 0:
        raise FileNotFoundError(f"No panel folders found under: {run_dir}")
    else:
        # Ambiguous; make caller specify panel_name
        raise ValueError(
            f"Multiple panel folders under {run_dir}: {', '.join(sorted(subdirs))}. "
            f"Please provide ?panel_name=..."
        )


def get_versions(folder: Path) -> Tuple[Dict[str, str], Dict[str, str], Dict[str, str]]:
    ann_yaml = _load_yaml(folder / ANNOTATION_FILE)
    bin_yaml = _load_yaml(folder / BINARIES_FILE)
    doc_yaml = _load_yaml(folder / DOCKER_FILE)

    annotations = _extract_versions(ann_yaml)
    binaries    = _extract_versions(bin_yaml, skip_keys={"version", "bin_dir"})
    docker      = _extract_versions(doc_yaml)

    return annotations, binaries, docker


@app.get("/analysis_software_versions")
def analysis_software_versions():
    """
    Query params:
      - run_name   (required), e.g. RUN20250928NextSeq
      - panel_name (optional), e.g. AGILENT_GLOBAL
        If omitted and there is exactly one subfolder under /ngs-results/{run_name},
        that one is used; otherwise you'll get a 400 listing the options.
    """
    run_name = request.args.get("run_name")
    panel_name = request.args.get("panel_name")

    if not run_name:
        abort(400, description="Missing required query param: run_name")

    try:
        analysis_folder = _resolve_analysis_folder(run_name, panel_name)
        annotations, binaries, docker = get_versions(analysis_folder)
        pipeline_version, pipeline_version_source = get_pipeline_version_info(run_name)
    except ValueError as e:
        abort(400, description=str(e))
    except FileNotFoundError as e:
        abort(404, description=str(e))
    except yaml.YAMLError as e:
        abort(400, description=f"YAML parsing error: {e}")

    return jsonify({
        "run_name": run_name,
        "panel_name": analysis_folder.name,
        "folder": str(analysis_folder),
        "pipeline_version": pipeline_version,
        "pipeline_version_source": pipeline_version_source,
        "annotations": annotations,
        "binaries":    binaries,
        "docker":      docker,
    })


def _serialize_row(row):
    return {col.name: getattr(row, col.name) for col in row.__table__.columns}


@app.get("/api/blacklisted_variants")
def api_blacklisted_variants():
    lab_id = request.args.get("lab_id")
    run_id = request.args.get("run_id")

    def _query(model):
        query = model.query.filter_by(blacklist="yes")
        if lab_id:
            query = query.filter_by(lab_id=lab_id)
        if run_id:
            query = query.filter_by(run_id=run_id)
        return query.all()

    items = []
    for model in (TherapeuticTable, OtherVariantsTable, RareVariantsTable):
        for row in _query(model):
            payload = _serialize_row(row)
            payload["source_table"] = model.__tablename__
            items.append(payload)

    return jsonify({
        "count": len(items),
        "items": items,
    })


@app.get("/api/petitions")
def api_petitions():
    rows = Petition.query.all()
    return jsonify({
        "count": len(rows),
        "items": [_serialize_row(row) for row in rows],
    })
