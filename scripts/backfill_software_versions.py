#!/usr/bin/env python3
"""Backfill and extend SOFTWARE_VERSION from JOBS and resource YAML files.

The table is currently run-level, so this script inserts at most one row per
JOBS.JOB_ID. For runs with multiple panel jobs, the newest finished job with
readable resource YAML files is used as the representative source.
"""

from __future__ import annotations

import argparse
import shlex
import sqlite3
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

import yaml


DEFAULT_DB = Path("/ngs-db/NGS_DB/NGS.db")
DEFAULT_RESULTS_ROOT = Path("/ngs-results")


BASE_COLUMNS = [
    "RUN_ID",
    "PIPELINE_VERSION",
    "GENOME_VERSION",
    "VEP_VERSION",
    "THOUSAND_GENOMES_VERSION",
    "GNOMAD_VERSION",
    "CIVIC_VERSION",
    "CGI_VERSION",
    "CHIMERKB_VERSION",
    "DBNSFP_VERSION",
    "DBSCSNV_VERSION",
    "FASTP_VERSION",
    "SAMTOOLS_VERSION",
    "GATK_VERSION",
    "BWA_VERSION",
    "MANTA_VERSION",
    "CNVKIT_VERSION",
    "CATSALUT_TIERS",
]

EXTRA_COLUMNS = {
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

ANNOTATION_TO_COLUMN = {
    "yaml": "ANNOTATION_YAML_VERSION",
    "gencode_gtf": "GENCODE_GTF_VERSION",
    "spliceai_transcript": "SPLICEAI_TRANSCRIPT_VERSION",
    "dbnsfp": "DBNSFP_VERSION",
    "revel": "REVEL_VERSION",
    "vep": "VEP_VERSION",
    "vep_cache": "VEP_CACHE_VERSION",
    "clinvar": "CLINVAR_VERSION",
    "gene_synonyms": "GENE_SYNONYMS_VERSION",
    "thousand_genomes": "THOUSAND_GENOMES_VERSION",
    "gnomad": "GNOMAD_VERSION",
    "gnomad_exomes": "GNOMAD_EXOMES_VERSION",
    "gnomad_only_af": "GNOMAD_ONLY_AF_VERSION",
    "gnomad_sv": "GNOMAD_SV_VERSION",
    "cadd": "CADD_VERSION",
    "spliceai_snv": "SPLICEAI_SNV_VERSION",
    "spliceai_indel": "SPLICEAI_INDEL_VERSION",
    "dbscsnv": "DBSCSNV_VERSION",
    "maxent": "MAXENT_VERSION",
    "tier_catsalut": "CATSALUT_TIERS",
    "cancer_hotspots": "CANCER_HOTSPOTS_VERSION",
    "civic": "CIVIC_DB_VERSION",
    "cgi": "CGI_VERSION",
    "chimerdb": "CHIMERKB_VERSION",
    "blacklist": "BLACKLIST_VERSION",
    "phastcons": "PHASTCONS_VERSION",
    "phylop": "PHYLOP_VERSION",
    "mappability": "MAPPABILITY_VERSION",
    "grapes_db": "GRAPES_DB_VERSION",
    "grapes2_db": "GRAPES2_DB_VERSION",
}

BINARY_TO_COLUMN = {
    "samtools": "SAMTOOLS_VERSION",
    "bcftools": "BCFTOOLS_VERSION",
    "bedtools": "BEDTOOLS_VERSION",
    "bgzip": "BGZIP_VERSION",
    "bwa": "BWA_VERSION",
    "fastp": "FASTP_VERSION",
    "freebayes": "FREEBAYES_VERSION",
    "gunzip": "GUNZIP_VERSION",
    "ivar": "IVAR_VERSION",
    "lancet": "LANCET_VERSION",
    "manta": "MANTA_VERSION",
    "megadepth": "MEGADEPTH_VERSION",
    "mosdepth": "MOSDEPTH_VERSION",
    "octopus": "OCTOPUS_VERSION",
    "seqtk": "SEQTK_VERSION",
    "strelka2": "STRELKA2_VERSION",
    "tabix": "TABIX_VERSION",
}

DOCKER_TO_COLUMN = {
    "fastqc": "FASTQC_VERSION",
    "multiqc": "MULTIQC_VERSION",
    "gatk": "GATK_VERSION",
    "grapes": "GRAPES_VERSION",
    "grapes2": "GRAPES2_VERSION",
    "picard": "PICARD_VERSION",
    "cnvkit": "CNVKIT_VERSION",
    "fgbio": "FGBIO_VERSION",
    "vep": "DOCKER_VEP_VERSION",
    "ngs_binaries": "NGS_BINARIES_VERSION",
    "decon": "DECON_VERSION",
    "manta": "DOCKER_MANTA_VERSION",
    "spliceai": "SPLICEAI_DOCKER_VERSION",
    "deepvariant": "DEEPVARIANT_VERSION",
}

INSERT_COLUMNS = BASE_COLUMNS + list(EXTRA_COLUMNS)


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--db", type=Path, default=DEFAULT_DB)
    parser.add_argument("--results-root", type=Path, default=DEFAULT_RESULTS_ROOT)
    parser.add_argument("--apply", action="store_true", help="Write changes. Default is dry-run.")
    parser.add_argument("--no-backup", action="store_true", help="Skip SQLite backup before --apply.")
    parser.add_argument("--limit", type=int, default=0, help="Limit inserted missing runs, for testing.")
    return parser.parse_args()


def normalize_version(value: Any) -> str:
    if value is None:
        return ""
    return str(value)


def parse_date(value: str) -> Optional[datetime]:
    if not value:
        return None
    for fmt in ("%Y-%m-%d %H:%M:%S.%f", "%Y-%m-%d %H:%M:%S", "%d/%m/%y-%H:%M:%S"):
        try:
            return datetime.strptime(value, fmt)
        except ValueError:
            continue
    return None


def table_columns(conn: sqlite3.Connection) -> List[str]:
    rows = conn.execute("PRAGMA table_info(SOFTWARE_VERSION)").fetchall()
    return [str(row["name"]).upper() for row in rows]


def load_yaml(path: Optional[Path]) -> Dict[str, Any]:
    if not path or not path.exists():
        return {}
    with path.open("r", encoding="utf-8") as handle:
        return yaml.safe_load(handle) or {}


def extract_nested_versions(data: Dict[str, Any]) -> Dict[str, str]:
    versions: Dict[str, str] = {}
    for key, value in data.items():
        if isinstance(value, dict) and "version" in value:
            versions[str(key)] = normalize_version(value.get("version"))
    return versions


def top_level_version(data: Dict[str, Any]) -> str:
    return normalize_version(data.get("version"))


def existing_path(value: Any) -> Optional[Path]:
    if not value:
        return None
    path = Path(str(value))
    return path if path.exists() else None


def infer_analysis_folder(job: sqlite3.Row, results_root: Path) -> Optional[Path]:
    logfile = existing_path(job["logfile"])
    if logfile:
        return logfile.parent

    job_id = normalize_version(job["job_id"])
    panel = normalize_version(job["panel"])
    candidate = results_root / job_id / panel
    if candidate.exists():
        return candidate
    return None


def resource_paths(job: sqlite3.Row, results_root: Path) -> Dict[str, Optional[Path]]:
    folder = infer_analysis_folder(job, results_root)
    return {
        "annotation": existing_path(job["config_yaml_1"])
        or (folder / "annotation_resources_hg19.yaml" if folder else None),
        "binary": existing_path(job["config_yaml_2"])
        or (folder / "binary_resources.yaml" if folder else None),
        "reference": existing_path(job["config_yaml_3"])
        or (folder / "reference_resources.yaml" if folder else None),
        "docker": existing_path(job["config_yaml_4"])
        or (folder / "docker_resources.yaml" if folder else None),
    }


def extract_genome_version(job_cmd: str) -> str:
    if not job_cmd:
        return ""
    try:
        tokens = shlex.split(job_cmd)
    except ValueError:
        tokens = job_cmd.split()

    for idx, token in enumerate(tokens):
        if token in {"-r", "--reference", "--genome", "--genome_version"} and idx + 1 < len(tokens):
            return tokens[idx + 1]
        if token.startswith("--genome_version="):
            return token.split("=", 1)[1]
    return ""


def get_finished_jobs(conn: sqlite3.Connection) -> List[sqlite3.Row]:
    return conn.execute(
        """
        SELECT
            ID AS id,
            JOB_ID AS job_id,
            PANEL AS panel,
            DATE AS date,
            STATUS AS status,
            LOGFILE AS logfile,
            CONFIG_YAML_1 AS config_yaml_1,
            CONFIG_YAML_2 AS config_yaml_2,
            CONFIG_YAML_3 AS config_yaml_3,
            CONFIG_YAML_4 AS config_yaml_4,
            JOB_CMD AS job_cmd
        FROM JOBS
        WHERE lower(STATUS) = 'finished'
          AND trim(coalesce(JOB_ID, '')) != ''
        ORDER BY DATE DESC, ID DESC
        """
    ).fetchall()


def newest_job_by_run(jobs: Iterable[sqlite3.Row]) -> Dict[str, sqlite3.Row]:
    by_run: Dict[str, sqlite3.Row] = {}
    for job in jobs:
        run_id = normalize_version(job["job_id"])
        if run_id not in by_run:
            by_run[run_id] = job
    return by_run


def known_pipeline_anchors(conn: sqlite3.Connection) -> List[Tuple[datetime, str, str]]:
    rows = conn.execute(
        """
        SELECT s.RUN_ID AS run_id, s.PIPELINE_VERSION AS pipeline_version, max(j.DATE) AS job_date
        FROM SOFTWARE_VERSION s
        JOIN JOBS j ON j.JOB_ID = s.RUN_ID
        WHERE trim(coalesce(s.PIPELINE_VERSION, '')) != ''
          AND trim(coalesce(s.RUN_ID, '')) != ''
          AND lower(j.STATUS) = 'finished'
        GROUP BY s.RUN_ID, s.PIPELINE_VERSION
        """
    ).fetchall()
    anchors: List[Tuple[datetime, str, str]] = []
    for row in rows:
        parsed = parse_date(row["job_date"])
        if parsed:
            anchors.append((parsed, str(row["pipeline_version"]), str(row["run_id"])))
    return sorted(anchors, key=lambda item: item[0])


def infer_pipeline_version(job_date: Optional[datetime], anchors: Sequence[Tuple[datetime, str, str]]) -> Tuple[str, str]:
    if not job_date or not anchors:
        return "", ""

    prior = [anchor for anchor in anchors if anchor[0] <= job_date]
    if prior:
        anchor_date, version, run_id = prior[-1]
        return version, f"inferred_prior:{run_id}:{anchor_date.isoformat(sep=' ')}"

    anchor_date, version, run_id = anchors[0]
    return version, f"inferred_next:{run_id}:{anchor_date.isoformat(sep=' ')}"


def build_values(
    job: sqlite3.Row,
    pipeline_version: str,
    pipeline_version_source: str,
    results_root: Path,
) -> Dict[str, str]:
    values = {column: "" for column in INSERT_COLUMNS}
    values["RUN_ID"] = normalize_version(job["job_id"])
    values["PIPELINE_VERSION"] = pipeline_version
    values["PIPELINE_VERSION_SOURCE"] = pipeline_version_source
    values["SOURCE_JOB_DATE"] = normalize_version(job["date"])
    values["SOURCE_PANEL"] = normalize_version(job["panel"])
    values["SOURCE_LOGFILE"] = normalize_version(job["logfile"])
    values["GENOME_VERSION"] = extract_genome_version(normalize_version(job["job_cmd"]))

    paths = resource_paths(job, results_root)
    annotation_yaml = load_yaml(paths["annotation"])
    binary_yaml = load_yaml(paths["binary"])
    reference_yaml = load_yaml(paths["reference"])
    docker_yaml = load_yaml(paths["docker"])

    values["ANNOTATION_YAML_VERSION"] = top_level_version(annotation_yaml)
    values["BINARY_YAML_VERSION"] = top_level_version(binary_yaml)
    values["REFERENCE_YAML_VERSION"] = top_level_version(reference_yaml)

    apply_versions(values, extract_nested_versions(annotation_yaml), ANNOTATION_TO_COLUMN)
    apply_versions(values, extract_nested_versions(binary_yaml), BINARY_TO_COLUMN)
    apply_versions(values, extract_nested_versions(docker_yaml), DOCKER_TO_COLUMN)

    civic_db_version = values.get("CIVIC_DB_VERSION", "")
    if civic_db_version:
        values["CIVIC_VERSION"] = civic_db_version

    return values


def apply_versions(values: Dict[str, str], versions: Dict[str, str], mapping: Dict[str, str]) -> None:
    for key, column in mapping.items():
        value = versions.get(key)
        if value is not None:
            values[column] = value


def add_missing_columns(conn: sqlite3.Connection, columns: Sequence[str], apply: bool) -> List[str]:
    existing = set(table_columns(conn))
    missing = [column for column in columns if column not in existing]
    if apply:
        for column in missing:
            conn.execute(f'ALTER TABLE SOFTWARE_VERSION ADD COLUMN "{column}" {EXTRA_COLUMNS[column]}')
    return missing


def backup_database(conn: sqlite3.Connection, db_path: Path) -> Path:
    backup_path = db_path.with_suffix(db_path.suffix + f".software_version_backfill_{datetime.now():%Y%m%d%H%M%S}.bak")
    with sqlite3.connect(backup_path) as backup:
        conn.backup(backup)
    return backup_path


def insert_missing_runs(
    conn: sqlite3.Connection,
    jobs_by_run: Dict[str, sqlite3.Row],
    anchors: Sequence[Tuple[datetime, str, str]],
    results_root: Path,
    apply: bool,
    limit: int,
) -> List[Dict[str, str]]:
    existing_runs = {
        str(row["run_id"])
        for row in conn.execute(
            "SELECT RUN_ID AS run_id FROM SOFTWARE_VERSION WHERE trim(coalesce(RUN_ID, '')) != ''"
        )
    }

    missing_run_ids = [run_id for run_id in jobs_by_run if run_id not in existing_runs]
    if limit > 0:
        missing_run_ids = missing_run_ids[:limit]

    inserted: List[Dict[str, str]] = []
    for run_id in missing_run_ids:
        job = jobs_by_run[run_id]
        job_date = parse_date(normalize_version(job["date"]))
        pipeline_version, source = infer_pipeline_version(job_date, anchors)
        values = build_values(job, pipeline_version, source, results_root)
        inserted.append(values)
        if apply:
            placeholders = ", ".join("?" for _ in INSERT_COLUMNS)
            columns_sql = ", ".join(f'"{column}"' for column in INSERT_COLUMNS)
            conn.execute(
                f"INSERT INTO SOFTWARE_VERSION ({columns_sql}) VALUES ({placeholders})",
                [values[column] for column in INSERT_COLUMNS],
            )
    return inserted


def update_existing_new_columns(
    conn: sqlite3.Connection,
    jobs_by_run: Dict[str, sqlite3.Row],
    anchors: Sequence[Tuple[datetime, str, str]],
    results_root: Path,
    columns: Sequence[str],
    apply: bool,
) -> int:
    existing_run_ids = [
        str(row["run_id"])
        for row in conn.execute(
            "SELECT RUN_ID AS run_id FROM SOFTWARE_VERSION WHERE trim(coalesce(RUN_ID, '')) != ''"
        )
        if str(row["run_id"]) in jobs_by_run
    ]

    updated = 0
    updatable_columns = list(columns)
    for run_id in existing_run_ids:
        job = jobs_by_run[run_id]
        job_date = parse_date(normalize_version(job["date"]))
        inferred_version, source = infer_pipeline_version(job_date, anchors)
        row = conn.execute(
            "SELECT PIPELINE_VERSION AS pipeline_version FROM SOFTWARE_VERSION WHERE RUN_ID = ? LIMIT 1",
            (run_id,),
        ).fetchone()
        pipeline_version = normalize_version(row["pipeline_version"]) or inferred_version
        values = build_values(job, pipeline_version, "recorded", results_root)
        if not normalize_version(row["pipeline_version"]):
            values["PIPELINE_VERSION"] = inferred_version
            values["PIPELINE_VERSION_SOURCE"] = source

        set_columns = [column for column in updatable_columns if values.get(column, "") != ""]
        if not set_columns:
            continue
        updated += 1
        if apply:
            assignments = ", ".join(f'"{column}" = COALESCE(NULLIF("{column}", \'\'), ?)' for column in set_columns)
            conn.execute(
                f"UPDATE SOFTWARE_VERSION SET {assignments} WHERE RUN_ID = ?",
                [values[column] for column in set_columns] + [run_id],
            )
    return updated


def summarize_insertions(inserted: Sequence[Dict[str, str]]) -> None:
    by_version: Dict[str, int] = {}
    for values in inserted:
        by_version[values.get("PIPELINE_VERSION", "")] = by_version.get(values.get("PIPELINE_VERSION", ""), 0) + 1

    print(f"Missing run rows to insert: {len(inserted)}")
    for version, count in sorted(by_version.items()):
        label = version or "<empty>"
        print(f"  {label}: {count}")

    print("Examples:")
    for values in inserted[:10]:
        print(
            "  "
            f"{values['RUN_ID']} | {values['SOURCE_PANEL']} | {values['SOURCE_JOB_DATE']} | "
            f"pipeline={values['PIPELINE_VERSION']} | "
            f"revel={values.get('REVEL_VERSION', '')} | "
            f"spliceai_snv={values.get('SPLICEAI_SNV_VERSION', '')}"
        )


def main() -> int:
    args = parse_args()
    conn = sqlite3.connect(args.db)
    conn.row_factory = sqlite3.Row

    backup_path: Optional[Path] = None
    try:
        if args.apply and not args.no_backup:
            backup_path = backup_database(conn, args.db)
        missing_columns = add_missing_columns(conn, list(EXTRA_COLUMNS), apply=args.apply)

        jobs_by_run = newest_job_by_run(get_finished_jobs(conn))
        anchors = known_pipeline_anchors(conn)
        inserted = insert_missing_runs(
            conn,
            jobs_by_run,
            anchors,
            args.results_root,
            apply=args.apply,
            limit=args.limit,
        )
        updated_existing = update_existing_new_columns(
            conn,
            jobs_by_run,
            anchors,
            args.results_root,
            columns=list(EXTRA_COLUMNS),
            apply=args.apply,
        )

        if args.apply:
            conn.commit()
        else:
            conn.rollback()

        print(f"Mode: {'apply' if args.apply else 'dry-run'}")
        print(f"Database: {args.db}")
        if backup_path:
            print(f"Backup: {backup_path}")
        print(f"Missing columns to add: {len(missing_columns)}")
        for column in missing_columns:
            print(f"  {column}")
        print(f"Existing rows with new-column data available: {updated_existing}")
        summarize_insertions(inserted)
    finally:
        conn.close()

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
