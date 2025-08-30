# routes_pipeline.py
import json, re, shlex
from datetime import datetime
from flask import Blueprint, request, jsonify, render_template, url_for
from werkzeug.routing import BuildError
import shutil


from app import app, db
from app.models import Pipeline, PipelineParam, PipelineConfig



# ---------- helpers to infer types ----------
_num_int  = re.compile(r'^[+-]?\d+$')
_num_float= re.compile(r'^[+-]?\d*\.\d+$')



# routes_pipeline.py (add this)
@app.route("/pipelines", endpoint="pipeline_list_page")
def pipeline_list_page():
    return render_template("pipeline_list.html", title="Pipelines")


@app.route("/pipelines/new", endpoint="pipeline_new_page")
def pipeline_new_page():
    """Render the empty/new pipeline form. Optionally prefill from a CLI (?cmd=...)."""
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


# routes_pipeline.py  (add this)
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
            group_format=pr.get("group_format")
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


# routes_pipeline.py (append these)
import os
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
            "group_format": prm.group_format
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