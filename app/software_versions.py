from __future__ import annotations

import re
import shlex
from datetime import datetime
from pathlib import Path
from typing import Any, Mapping, Optional, Tuple

import yaml
from sqlalchemy import text

from app import db
from app.models import Job, PipelineDetails


JOB_DATE_FORMATS = ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%d/%m/%y-%H:%M:%S")

SOFTWARE_VERSION_COLUMNS = {
    "CATSALUT_TIERS": "TEXT",
    "PIPELINE_VERSION_SOURCE": "TEXT",
    "SOURCE_JOB_DATE": "TEXT",
    "SOURCE_PANEL": "TEXT",
    "SOURCE_LOGFILE": "TEXT",
    "ANNOTATION_YAML_VERSION": "TEXT",
    "BINARY_YAML_VERSION": "TEXT",
    "REFERENCE_YAML_VERSION": "TEXT",
    "GENCODE_GTF_VERSION": "TEXT",
    "SPLICEAI_TRANSCRIPT_VERSION": "TEXT",
    "REVEL_VERSION": "TEXT",
    "VEP_CACHE_VERSION": "TEXT",
    "CLINVAR_VERSION": "TEXT",
    "GENE_SYNONYMS_VERSION": "TEXT",
    "GNOMAD_EXOMES_VERSION": "TEXT",
    "GNOMAD_ONLY_AF_VERSION": "TEXT",
    "GNOMAD_SV_VERSION": "TEXT",
    "CADD_VERSION": "TEXT",
    "SPLICEAI_SNV_VERSION": "TEXT",
    "SPLICEAI_INDEL_VERSION": "TEXT",
    "MAXENT_VERSION": "TEXT",
    "CANCER_HOTSPOTS_VERSION": "TEXT",
    "CIVIC_DB_VERSION": "TEXT",
    "BLACKLIST_VERSION": "TEXT",
    "PHASTCONS_VERSION": "TEXT",
    "PHYLOP_VERSION": "TEXT",
    "MAPPABILITY_VERSION": "TEXT",
    "GRAPES_DB_VERSION": "TEXT",
    "GRAPES2_DB_VERSION": "TEXT",
    "BCFTOOLS_VERSION": "TEXT",
    "BEDTOOLS_VERSION": "TEXT",
    "BGZIP_VERSION": "TEXT",
    "FREEBAYES_VERSION": "TEXT",
    "GUNZIP_VERSION": "TEXT",
    "IVAR_VERSION": "TEXT",
    "LANCET_VERSION": "TEXT",
    "MEGADEPTH_VERSION": "TEXT",
    "MOSDEPTH_VERSION": "TEXT",
    "OCTOPUS_VERSION": "TEXT",
    "SEQTK_VERSION": "TEXT",
    "STRELKA2_VERSION": "TEXT",
    "TABIX_VERSION": "TEXT",
    "FASTQC_VERSION": "TEXT",
    "MULTIQC_VERSION": "TEXT",
    "PICARD_VERSION": "TEXT",
    "FGBIO_VERSION": "TEXT",
    "GRAPES_VERSION": "TEXT",
    "GRAPES2_VERSION": "TEXT",
    "DECON_VERSION": "TEXT",
    "NGS_BINARIES_VERSION": "TEXT",
    "DOCKER_VEP_VERSION": "TEXT",
    "DOCKER_MANTA_VERSION": "TEXT",
    "SPLICEAI_DOCKER_VERSION": "TEXT",
    "DEEPVARIANT_VERSION": "TEXT",
}

ANNOTATION_TO_ATTR = {
    "yaml": "annotation_yaml_version",
    "gencode_gtf": "gencode_gtf_version",
    "spliceai_transcript": "spliceai_transcript_version",
    "dbnsfp": "dbnsfp_version",
    "revel": "revel_version",
    "vep": "vep_version",
    "vep_cache": "vep_cache_version",
    "clinvar": "clinvar_version",
    "gene_synonyms": "gene_synonyms_version",
    "thousand_genomes": "thousand_genomes_version",
    "gnomad": "gnomad_version",
    "gnomad_exomes": "gnomad_exomes_version",
    "gnomad_only_af": "gnomad_only_af_version",
    "gnomad_sv": "gnomad_sv_version",
    "cadd": "cadd_version",
    "spliceai_snv": "spliceai_snv_version",
    "spliceai_indel": "spliceai_indel_version",
    "dbscsnv": "dbscsnv_version",
    "maxent": "maxent_version",
    "tier_catsalut": "catsalut_tiers",
    "cancer_hotspots": "cancer_hotspots_version",
    "civic": "civic_db_version",
    "cgi": "cgi_version",
    "chimerdb": "chimerkb_version",
    "blacklist": "blacklist_version",
    "phastcons": "phastcons_version",
    "phylop": "phylop_version",
    "mappability": "mappability_version",
    "grapes_db": "grapes_db_version",
    "grapes2_db": "grapes2_db_version",
}

BINARY_TO_ATTR = {
    "samtools": "samtools_version",
    "bcftools": "bcftools_version",
    "bedtools": "bedtools_version",
    "bgzip": "bgzip_version",
    "bwa": "bwa_version",
    "fastp": "fastp_version",
    "freebayes": "freebayes_version",
    "gunzip": "gunzip_version",
    "ivar": "ivar_version",
    "lancet": "lancet_version",
    "manta": "manta_version",
    "megadepth": "megadepth_version",
    "mosdepth": "mosdepth_version",
    "octopus": "octopus_version",
    "seqtk": "seqtk_version",
    "strelka2": "strelka2_version",
    "tabix": "tabix_version",
}

DOCKER_TO_ATTR = {
    "fastqc": "fastqc_version",
    "multiqc": "multiqc_version",
    "gatk": "gatk_version",
    "grapes": "grapes_version",
    "grapes2": "grapes2_version",
    "picard": "picard_version",
    "cnvkit": "cnvkit_version",
    "fgbio": "fgbio_version",
    "vep": "docker_vep_version",
    "ngs_binaries": "ngs_binaries_version",
    "decon": "decon_version",
    "manta": "docker_manta_version",
    "spliceai": "spliceai_docker_version",
    "deepvariant": "deepvariant_version",
}

CMD_YAML_OPTIONS = {
    "--ann_yaml": "annotation",
    "--bin_yaml": "binary",
    "--ref_yaml": "reference",
    "--docker_yaml": "docker",
}


def normalize_version(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def parse_job_date(value: Any) -> Optional[datetime]:
    if not value:
        return None
    if isinstance(value, datetime):
        return value.replace(tzinfo=None)

    text_value = str(value).strip()
    try:
        return datetime.fromisoformat(text_value.replace("Z", "+00:00")).replace(tzinfo=None)
    except ValueError:
        pass

    for date_format in JOB_DATE_FORMATS:
        try:
            return datetime.strptime(text_value, date_format)
        except ValueError:
            continue
    return None


def normalize_job_date(value: Any) -> str:
    parsed = parse_job_date(value)
    if parsed:
        return parsed.isoformat(sep=" ", timespec="seconds")
    return normalize_version(value)


def ensure_software_version_schema() -> None:
    rows = db.session.execute(text("PRAGMA table_info(SOFTWARE_VERSION)")).fetchall()
    existing = {str(row[1]).upper() for row in rows}
    for column, column_type in SOFTWARE_VERSION_COLUMNS.items():
        if column not in existing:
            db.session.execute(text(f'ALTER TABLE SOFTWARE_VERSION ADD COLUMN "{column}" {column_type}'))


def load_yaml(path: Optional[Path]) -> dict[str, Any]:
    if not path or not path.is_file():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def existing_path(value: Any) -> Optional[Path]:
    if not value:
        return None
    path = Path(str(value))
    return path if path.is_file() else None


def extract_nested_versions(data: Mapping[str, Any]) -> dict[str, str]:
    versions: dict[str, str] = {}
    for key, value in data.items():
        if isinstance(value, dict) and "version" in value:
            versions[str(key)] = normalize_version(value.get("version"))
    return versions


def top_level_version(data: Mapping[str, Any]) -> str:
    return normalize_version(data.get("version"))


def parse_command_tokens(command: str) -> list[str]:
    try:
        return shlex.split(command or "")
    except ValueError:
        return (command or "").split()


def extract_cmd_options(command: str) -> dict[str, str]:
    tokens = parse_command_tokens(command)
    options: dict[str, str] = {}
    idx = 0
    while idx < len(tokens):
        token = tokens[idx]
        if token.startswith("--") and "=" in token:
            name, value = token.split("=", 1)
            options[name] = value
            idx += 1
            continue
        if token.startswith("-") and idx + 1 < len(tokens) and not tokens[idx + 1].startswith("-"):
            options[token] = tokens[idx + 1]
            idx += 2
            continue
        idx += 1
    return options


def extract_genome_version(command: str) -> str:
    options = extract_cmd_options(command)
    for option in ("-r", "--reference", "--genome", "--genome_version"):
        value = options.get(option)
        if value:
            return value
    return ""


def extract_yaml_paths_from_command(command: str) -> dict[str, Path]:
    options = extract_cmd_options(command)
    paths: dict[str, Path] = {}
    for option, key in CMD_YAML_OPTIONS.items():
        path = existing_path(options.get(option))
        if path:
            paths[key] = path
    return paths


def pipeline_entrypoint_from_command(command: str) -> Optional[Path]:
    for token in parse_command_tokens(command):
        if token.endswith(".py"):
            path = Path(token)
            if path.exists():
                return path.resolve()
    return None


def pipeline_version_from_entrypoint(entrypoint: Optional[Path]) -> Tuple[str, str]:
    if not entrypoint:
        return "", ""

    version_candidates = [
        entrypoint.resolve().parent / "modules" / "_version.py",
        entrypoint.resolve().parent / "_version.py",
    ]
    for version_file in version_candidates:
        if not version_file.is_file():
            continue
        match = re.search(
            r"__version__\s*=\s*['\"]([^'\"]+)['\"]",
            version_file.read_text(encoding="utf-8"),
        )
        if match:
            return match.group(1), f"entrypoint:{version_file}"
    return "", ""


def pipeline_version_from_command(command: str) -> Tuple[str, str]:
    options = extract_cmd_options(command)
    for option in ("--pipeline_version", "--pipeline-version", "--pipeline_verision"):
        version = normalize_version(options.get(option)).strip()
        if version:
            return version, f"command:{option}"
    return pipeline_version_from_entrypoint(pipeline_entrypoint_from_command(command))


def latest_job_for_run(run_name: str) -> Optional[Job]:
    base_query = Job.query.filter(Job.Job_id == run_name)
    finished_job = (
        base_query
        .filter(db.func.lower(db.func.coalesce(Job.Status, "")) == "finished")
        .order_by(Job.Date.desc(), Job.Id.desc())
        .first()
    )
    if finished_job:
        return finished_job

    return base_query.order_by(Job.Date.desc(), Job.Id.desc()).first()


def pipeline_version_anchors(exclude_run_id: str = "") -> list[tuple[datetime, str, str]]:
    query = (
        db.session.query(
            PipelineDetails.run_id,
            PipelineDetails.pipeline_version,
            db.func.max(Job.Date).label("job_date"),
        )
        .join(Job, Job.Job_id == PipelineDetails.run_id)
        .filter(db.func.trim(db.func.coalesce(PipelineDetails.run_id, "")) != "")
        .filter(db.func.trim(db.func.coalesce(PipelineDetails.pipeline_version, "")) != "")
        .filter(db.func.lower(db.func.coalesce(Job.Status, "")) == "finished")
    )
    if exclude_run_id:
        query = query.filter(PipelineDetails.run_id != exclude_run_id)
    rows = query.group_by(PipelineDetails.run_id, PipelineDetails.pipeline_version).all()

    anchors: list[tuple[datetime, str, str]] = []
    for run_id, pipeline_version, job_date in rows:
        parsed = parse_job_date(job_date)
        if parsed:
            anchors.append((parsed, str(pipeline_version), str(run_id)))
    return sorted(anchors, key=lambda item: item[0])


def infer_pipeline_version(job_date: Optional[datetime], exclude_run_id: str = "") -> Tuple[str, str]:
    anchors = pipeline_version_anchors(exclude_run_id=exclude_run_id)
    if not job_date or not anchors:
        return "", ""

    prior = [anchor for anchor in anchors if anchor[0] <= job_date]
    if prior:
        anchor_date, version, run_id = prior[-1]
        return version, f"inferred_prior:{run_id}:{anchor_date.isoformat(sep=' ')}"

    anchor_date, version, run_id = anchors[0]
    return version, f"inferred_next:{run_id}:{anchor_date.isoformat(sep=' ')}"


def recorded_pipeline_version(run_name: str) -> Tuple[str, str]:
    pipeline_details = (
        PipelineDetails.query
        .filter(PipelineDetails.run_id == run_name)
        .filter(db.func.trim(db.func.coalesce(PipelineDetails.pipeline_version, "")) != "")
        .order_by(PipelineDetails.id.desc())
        .first()
    )
    if pipeline_details and pipeline_details.pipeline_version:
        source = getattr(pipeline_details, "pipeline_version_source", "") or "recorded"
        return pipeline_details.pipeline_version.strip(), source
    return "", ""


def get_pipeline_version_info(run_name: str) -> Tuple[str, str]:
    recorded_version, recorded_source = recorded_pipeline_version(run_name)
    if recorded_version:
        return recorded_version, recorded_source

    job = latest_job_for_run(run_name)
    if not job:
        return "", ""
    return infer_pipeline_version(parse_job_date(job.Date), exclude_run_id=run_name)


def resource_paths_for_job(job: Job, preferred_paths: Optional[Mapping[str, Any]] = None) -> dict[str, Optional[Path]]:
    preferred_paths = preferred_paths or {}
    parsed_paths = extract_yaml_paths_from_command(job.Job_cmd or "")

    def pick(key: str, job_value: Any) -> Optional[Path]:
        return (
            existing_path(preferred_paths.get(key))
            or parsed_paths.get(key)
            or existing_path(job_value)
        )

    return {
        "annotation": pick("annotation", job.Config_yaml_1),
        "binary": pick("binary", job.Config_yaml_2),
        "reference": pick("reference", job.Config_yaml_3),
        "docker": pick("docker", job.Config_yaml_4),
    }


def build_software_version_values(
    job: Job,
    preferred_paths: Optional[Mapping[str, Any]] = None,
) -> dict[str, str]:
    run_id = normalize_version(job.Job_id)
    pipeline_version, pipeline_source = pipeline_version_from_command(job.Job_cmd or "")
    if not pipeline_version:
        pipeline_version, pipeline_source = infer_pipeline_version(parse_job_date(job.Date), exclude_run_id=run_id)

    values = {
        "run_id": run_id,
        "pipeline_version": pipeline_version,
        "pipeline_version_source": pipeline_source,
        "source_job_date": normalize_job_date(job.Date),
        "source_panel": normalize_version(job.Panel),
        "source_logfile": normalize_version(job.Logfile),
        "genome_version": extract_genome_version(job.Job_cmd or ""),
    }

    paths = resource_paths_for_job(job, preferred_paths=preferred_paths)
    annotation_yaml = load_yaml(paths["annotation"])
    binary_yaml = load_yaml(paths["binary"])
    reference_yaml = load_yaml(paths["reference"])
    docker_yaml = load_yaml(paths["docker"])

    values["annotation_yaml_version"] = top_level_version(annotation_yaml)
    values["binary_yaml_version"] = top_level_version(binary_yaml)
    values["reference_yaml_version"] = top_level_version(reference_yaml)

    for key, value in extract_nested_versions(annotation_yaml).items():
        attr = ANNOTATION_TO_ATTR.get(key)
        if attr:
            values[attr] = value
    for key, value in extract_nested_versions(binary_yaml).items():
        attr = BINARY_TO_ATTR.get(key)
        if attr:
            values[attr] = value
    for key, value in extract_nested_versions(docker_yaml).items():
        attr = DOCKER_TO_ATTR.get(key)
        if attr:
            values[attr] = value

    if values.get("civic_db_version"):
        values["civic_version"] = values["civic_db_version"]

    return values


def should_replace_source(details: PipelineDetails, job: Job, created: bool) -> bool:
    if created:
        return True

    incoming_date = parse_job_date(job.Date)
    existing_date = parse_job_date(getattr(details, "source_job_date", ""))
    if not existing_date:
        return True
    if incoming_date and incoming_date >= existing_date:
        return True
    return False


def set_value(details: PipelineDetails, attr: str, value: Any, overwrite: bool) -> None:
    value = normalize_version(value)
    if not value:
        return
    current_value = normalize_version(getattr(details, attr, ""))
    if overwrite or not current_value:
        setattr(details, attr, value)


def upsert_software_version_for_job(
    job: Job,
    preferred_paths: Optional[Mapping[str, Any]] = None,
) -> PipelineDetails:
    """Create/update the run-level SOFTWARE_VERSION row for a just-launched job.

    SOFTWARE_VERSION is run-level, while JOBS can have several panels per run.
    For repeat analyses, the newest launch becomes the representative source.
    """
    ensure_software_version_schema()

    run_id = normalize_version(job.Job_id)
    details = PipelineDetails.query.filter_by(run_id=run_id).order_by(PipelineDetails.id.desc()).first()
    created = details is None
    if created:
        details = PipelineDetails(run_id=run_id)
        db.session.add(details)

    values = build_software_version_values(job, preferred_paths=preferred_paths)
    overwrite = should_replace_source(details, job, created)
    for attr, value in values.items():
        set_value(details, attr, value, overwrite=overwrite)

    return details
