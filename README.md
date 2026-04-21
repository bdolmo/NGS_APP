# NGS_APP

Flask application used to launch, monitor, inspect, and report NGS analyses. It stores run metadata in the NGS SQLite database, queues analyses with RQ/Redis, serves analysis results from `/ngs-results`, and integrates with `GC_NGS_PIPELINE` and `AutoLauncherNGS`.

## Main Components

- `NGS.py`: Flask entrypoint. Runs the web application on `0.0.0.0:5000` in debug mode.
- `app/`: Flask routes, models, templates, and helper modules.
- `app/panel_analysis.py`: manual NGS job submission, RQ monitoring, status pages, stop/rerun actions.
- `app/pipelines.py`: workflow configuration, result tree browsing, single-file download, and FASTQ.GZ bundle download.
- `app/api.py`: JSON APIs, including `/analysis_software_versions`.
- `app/software_versions.py`: launch-time `SOFTWARE_VERSION` creation/update helper.
- `scripts/backfill_software_versions.py`: one-off/idempotent historical backfill for missing `SOFTWARE_VERSION` rows and extended metadata columns.
- `AutoLauncherNGS/`: automatic run detection, panel matching, RQ launch, and direct `JOBS`/`SOFTWARE_VERSION` population.

## Production Paths

These are configured in `config.py` and `AutoLauncherNGS/config.py`.

- App root: `/home/udmmp/NGS_APP`
- Pipeline root: `/home/udmmp/GC_NGS_PIPELINE`
- Pipeline executable: `/home/udmmp/GC_NGS_PIPELINE/gc_ngs_pipeline.py`
- Results/upload root: `/ngs-results/`
- NGS database: `/ngs-db/NGS_DB/NGS.db`
- Annotation resources: `/ngs-annotations/`
- Gene panel API: `http://172.16.83.24:8000`
- NGS app URL: `http://172.16.83.24:5000`
- Compendium URL: `http://172.16.83.24:8001`

## Requirements

- Python 3.10+
- Redis server
- SQLite database at `/ngs-db/NGS_DB/NGS.db`
- `GC_NGS_PIPELINE` checkout with resource YAML files
- Access to `/ngs-results`, `/ngs-db`, and `/ngs-annotations`

Install Python dependencies:

```bash
cd /home/udmmp/NGS_APP
python3 -m pip install -r requirements.txt
```

Install/start Redis if needed:

```bash
sudo apt install redis-server
sudo systemctl enable --now redis-server
```

## Running The App

Start Flask:

```bash
cd /home/udmmp/NGS_APP
python3 NGS.py
```

Start an RQ worker:

```bash
cd /home/udmmp/NGS_APP
rq worker default
```

Or use the watchdog script, which starts `NGS.py` if needed and keeps a default RQ worker alive:

```bash
cd /home/udmmp/NGS_APP
./run_rq_edit.sh
```

## Manual Job Launch

Manual NGS submissions are handled by:

- Browser route: `/submit_ngs_analysis`
- Workflow route: `/workflows/<pipeline_id>`
- JSON execution endpoint: `/workflows/execute_job`

When a job is launched, the app:

- saves uploaded FASTQ files under `/ngs-results/<RUN>/<PANEL>/`;
- enqueues the analysis in Redis/RQ;
- inserts a row in `JOBS`;
- creates or updates the run-level row in `SOFTWARE_VERSION`;
- records pipeline/resource versions from pipeline version files and YAML resources.

## AutoLauncherNGS

AutoLauncherNGS scans sequencing output folders, detects the best panel for each sample group, creates panel-specific analysis folders, queues pipeline jobs, and writes directly to the same SQLite database.

Run it with:

```bash
cd /home/udmmp/NGS_APP
python3 AutoLauncherNGS/run.py \
  --ngs_db /ngs-db/NGS_DB/NGS.db \
  --run_dir /path/to/sequencing_runs \
  --ref_fasta /ngs-annotations/REF_DIR/hg19/ucsc.hg19.fasta \
  --output_dir /ngs-results/
```

The helper script `AutoLauncherNGS/run_autolauncherngs.sh` is configured for production paths.

Important: AutoLauncherNGS does not call the Flask launch endpoint. It inserts into `JOBS` directly in `AutoLauncherNGS/modules/panel_matcher.py`, so it also has its own `AutoLauncherNGS/modules/software_versions.py` helper to populate `SOFTWARE_VERSION` at launch time.

## Result Tree And Downloads

The status page links to the result tree:

```text
/workflows/tree_view?job_id=<RUN_ID>&panel=<PANEL>
```

Features:

- folders are shown before files;
- folders and files are sorted by name within their group;
- file context menus are clamped to the viewport;
- individual files can be downloaded;
- all available `.fastq.gz`/`.fq.gz` files under a run/panel can be downloaded as a single ZIP via the compact `FASTQ.GZ` button.

Direct FASTQ bundle endpoint:

```text
/workflows/download_fastq_gz?job_id=<RUN_ID>&panel=<PANEL>
```

## Software Version Tracking

`SOFTWARE_VERSION` is run-level. `JOBS` can contain several panel jobs for the same run, so the app stores one representative software-version row per `RUN_ID`.

The table tracks:

- pipeline version and provenance;
- source job date, panel, and logfile;
- annotation YAML versions, including REVEL, SpliceAI, ClinVar, VEP cache, gnomAD, CADD, CIViC, CGI, ChimerDB, tiers, conservation resources, and GRAPES databases;
- binary versions, including samtools, bcftools, bedtools, bwa, fastp, manta, mosdepth, strelka2, tabix, and others;
- Docker/tool versions, including GATK, CNVkit, VEP, FastQC, MultiQC, Picard, fgbio, GRAPES, DECoN, SpliceAI, and DeepVariant.

Pipeline version resolution order for new jobs:

1. explicit command flag, if present: `--pipeline_version`, `--pipeline-version`, or legacy typo `--pipeline_verision`;
2. `modules/_version.py` next to the pipeline executable;
3. inferred version from the nearest dated `SOFTWARE_VERSION` anchor.


## Useful API Endpoints

Software versions for one analysis folder:

```text
/analysis_software_versions?run_name=<RUN_ID>&panel_name=<PANEL>
```

Response includes:

- `pipeline_version`
- `pipeline_version_source`
- `annotations`
- `binaries`
- `docker`

RQ overview:

```text
/rq
/api/rq/queues
/api/rq/metrics
```

Job config and logs:

```text
/api/job/<job_id>/config
/api/job/<job_id>/logline
```

## Database Notes

Main tables used by the launch/status flow:

- `JOBS`: queued/running/finished analysis jobs.
- `SOFTWARE_VERSION`: run-level software and database versions.
- `SUMMARY_QC`, variant tables, CNV tables, petitions, and report-related tables are populated by downstream analysis/reporting code.

The app uses SQLAlchemy models in `app/models.py`. AutoLauncherNGS uses its own SQLAlchemy declarations in `AutoLauncherNGS/modules/db.py` plus `AutoLauncherNGS/modules/software_versions.py`.

## Development Checks

Syntax check changed Python files:

```bash
python3 - <<'PY'
from pathlib import Path
for path in [
    'app/api.py',
    'app/models.py',
    'app/panel_analysis.py',
    'app/pipelines.py',
    'app/software_versions.py',
    'AutoLauncherNGS/modules/software_versions.py',
    'AutoLauncherNGS/modules/panel_matcher.py',
]:
    compile(Path(path).read_text(), path, 'exec')
print('syntax ok')
PY
```

Check app endpoint locally:

```bash
curl -sS 'http://172.16.83.24:5000/analysis_software_versions?run_name=RUN20260414NextSeq&panel_name=AGILENT_GLOBAL_V2'
```

## Troubleshooting

- If jobs stay queued, check Redis and `rq worker default`.
- If the result tree is empty, verify `/ngs-results/<RUN>/<PANEL>` exists and permissions allow the app user to read it.
- If `/analysis_software_versions` returns 404, verify the run/panel folder exists under `/ngs-results`.
- If `pipeline_version` is inferred, check whether the launched command contains the pipeline executable and whether `/home/udmmp/GC_NGS_PIPELINE/modules/_version.py` exists.
- If `SOFTWARE_VERSION` is missing rows, run `scripts/backfill_software_versions.py` in dry-run mode first, then `--apply`.
- If AutoLauncher jobs miss version metadata, verify `AutoLauncherNGS/modules/panel_matcher.py` imports `upsert_software_version_for_job` and calls it before `session.commit()`.


