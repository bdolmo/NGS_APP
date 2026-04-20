from app import app, db
import glob
import os
import binascii
import requests
import io
import re
import sqlite3
from rq import Queue, cancel_job
from uuid import uuid4
from functools import wraps
from flask import Flask
from flask import (
    request,
    render_template,
    url_for,
    redirect,
    flash,
    send_from_directory,
    current_app,
    send_file,
    make_response,
    jsonify,
    session
)
from flask_wtf import FlaskForm
from flask_sqlalchemy import SQLAlchemy
from flask_sslify import SSLify
from collections import defaultdict, Counter
from weasyprint import HTML
from jinja2 import Environment, FileSystemLoader
from sqlalchemy import (
    MetaData,
    create_engine,
    Column,
    Integer,
    Float,
    String,
    Text,
    desc,
    distinct,
    func,
    tuple_,
)
from sqlalchemy.ext.declarative import declarative_base, DeclarativeMeta
from sqlalchemy.orm import sessionmaker, load_only
from datetime import date, datetime
from job_commands import launch_ngs_analysis
import pandas as pd
import numpy as np
import json
import zipfile

from app.models import (
    Job,
    VersionControl,
    SampleTable,
    SampleVariants,
    Variants,
    TherapeuticTable,
    OtherVariantsTable,
    RareVariantsTable,
    BiomakerTable,
    SummaryQcTable,
    DisclaimersTable,
    AllCnas,
    LostExonsTable,
    PipelineDetails,
    Petition,
    GeneVariantSummary
)
from app.plots import var_location_pie, cnv_plot, basequal_plot, adapters_plot, snv_plot, vaf_plot
from app.utils import convert_long_to_short
from app.cgi_clinics import create_direct_analysis_from_vcf, build_analysis_url

from config import api_gene_panels
from app.gene_info import GENE_MECH

class AllFusions(db.Model):
    __tablename__ = "ALL_FUSIONS"
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(100))
    lab_id = db.Column(db.String(100))
    ext1_id = db.Column(db.String(100))
    ext2_id = db.Column(db.String(100))
    run_id = db.Column(db.String(100))
    chromosome = db.Column(db.String(100))
    start = db.Column(db.String(100))
    end = db.Column(db.String(100))
    qual = db.Column(db.String(100))
    svtype = db.Column(db.String(100))
    read_pairs = db.Column(db.String(100))
    split_reads = db.Column(db.String(100))
    vaf = db.Column(db.String(100))
    depth = db.Column(db.String(100))
    fusion_partners = db.Column(db.String(100))
    fusion_source = db.Column(db.String(100))
    fusion_diseases = db.Column(db.String(100))
    flanking_genes = db.Column(db.String(100))


def parse_hgvsg(hgvsg_str):
    """
    Parse chr, pos, ref, alt from HGVSg string like 'chr6:g.117656917C>T'
    Returns (chrom, pos, ref, alt) or default '.' values if invalid
    """
    if not hgvsg_str or "g." not in hgvsg_str:
        return ".", ".", ".", "."

    match = re.match(r"^(chr[\w]+):g\.(\d+)([ACGT]+)>([ACGT]+)$", hgvsg_str)
    if match:
        chrom, pos, ref, alt = match.groups()
        return chrom, pos, ref, alt
    return ".", ".", ".", "."

# # Define version control class
class AlchemyEncoder(json.JSONEncoder):
    def default(self, obj):
        if isinstance(obj.__class__, DeclarativeMeta):
            # an SQLAlchemy class
            fields = {}
            for field in [
                x for x in dir(obj) if not x.startswith("_") and x != "metadata"
            ]:
                data = obj.__getattribute__(field)
                try:
                    json.dumps(
                        data
                    )  # this will fail on non-encodable values, like other classes
                    fields[field] = data
                except TypeError:
                    fields[field] = None
            # a json-encodable dict
            return fields

        return json.JSONEncoder.default(self, obj)


def login_required(f):
    @wraps(f)
    def decorated_function(*args, **kwargs):
        if not session.get("username"):
            URL_HOME = f'http://172.16.83.23:5000/logout'
            return redirect(URL_HOME)
            # return render_template("login.html", title="Identificació")
        return f(*args, **kwargs)
    return decorated_function


def _ensure_sample_cgi_columns():
    db_path = app.config.get("DB")
    if not db_path:
        return

    expected_columns = {
        "CGI_SENT": "TEXT",
        "CGI_SEND_COUNT": "INTEGER",
        "CGI_ANALYSIS_UUID": "TEXT",
        "CGI_ANALYSIS_URL": "TEXT",
        "CGI_SENT_ON": "TEXT",
    }

    conn = sqlite3.connect(db_path)
    try:
        cur = conn.cursor()
        cur.execute("PRAGMA table_info(SAMPLES)")
        existing_columns = {row[1].upper() for row in cur.fetchall()}
        altered = False
        for column_name, column_type in expected_columns.items():
            if column_name in existing_columns:
                continue
            cur.execute(f"ALTER TABLE SAMPLES ADD COLUMN {column_name} {column_type}")
            altered = True
        if altered:
            conn.commit()
    finally:
        conn.close()


def _normalize_sample_cgi_urls():
    try:
        samples = (
            SampleTable.query
            .filter(SampleTable.cgi_analysis_uuid.isnot(None))
            .all()
        )
    except Exception:
        return

    has_changes = False
    for sample in samples:
        analysis_uuid = str(getattr(sample, "cgi_analysis_uuid", "") or "").strip()
        if not analysis_uuid or analysis_uuid == ".":
            continue
        expected_url = build_analysis_url(None, analysis_uuid)
        current_url = str(getattr(sample, "cgi_analysis_url", "") or "").strip()
        if current_url == expected_url:
            continue
        sample.cgi_analysis_url = expected_url
        has_changes = True

    if has_changes:
        db.session.commit()


with app.app_context():
    _ensure_sample_cgi_columns()
    _normalize_sample_cgi_urls()


def _current_cgi_send_count(sample_info):
    raw_value = getattr(sample_info, "cgi_send_count", None)
    try:
        if raw_value is not None and str(raw_value).strip() != "":
            return int(raw_value)
    except Exception:
        pass

    cgi_sent = str(getattr(sample_info, "cgi_sent", "") or "").strip().lower()
    if cgi_sent == "yes":
        return 1
    for attr_name in ("cgi_analysis_uuid", "cgi_analysis_url", "cgi_sent_on"):
        attr_value = str(getattr(sample_info, attr_name, "") or "").strip()
        if attr_value and attr_value not in {".", "None", "NULL"}:
            return 1
    return 0

@app.route("/")
@app.route("/main")
@login_required
def main():
    return render_template("main.html", title="Pàgina inicial")


@app.route("/return_home")
@login_required
def return_home():
    home_url = "http://172.16.83.23:5000"
    return redirect(home_url)


@app.route("/show_run_details/<run_id>")
@login_required
def show_run_details(run_id):
    """ """
    run_samples = SampleTable.query.filter_by(run_id=run_id).all()
    run_dict = defaultdict(dict)

    if run_samples:
        run_dict["RUN_ID"] = run_id
        run_dict["PETITION_ID"] = run_samples[0].petition_id
        run_dict["N_SAMPLES"] = len(run_samples)
        run_dict["ANALYSIS_DATE"] = run_samples[0].analysis_date

    def _report_exists(path_value):
        if not path_value:
            return False
        path_str = str(path_value).strip()
        if not path_str:
            return False
        candidates = [path_str]
        if not path_str.lower().endswith(".pdf"):
            candidates.append(f"{path_str}.pdf")
        for candidate in candidates:
            if os.path.isfile(candidate):
                return True
        return False

    def _clean_display_value(value):
        text = str(value).strip() if value is not None else ""
        return text if text and text != "." else ""

    for s in run_samples:
        tumor_origin = _clean_display_value(getattr(s, "tumor_origin", ""))
        if not tumor_origin:
            petition = None
            ext1_id = _clean_display_value(getattr(s, "ext1_id", ""))
            if ext1_id:
                petition = Petition.query.filter_by(AP_code=ext1_id).first()
            if not petition:
                petition = Petition.query.filter_by(AP_code=s.lab_id).first()
            if not petition:
                petition_id = _clean_display_value(getattr(s, "petition_id", ""))
                if petition_id:
                    petition = Petition.query.filter_by(Petition_id=petition_id).first()
            if petition:
                tumor_origin = _clean_display_value(getattr(petition, "Tumour_origin", ""))

        s.display_tumor_origin = tumor_origin or "-"
        s.is_report_ready = (
            _report_exists(getattr(s, "latest_short_report_pdf", None))
            or _report_exists(getattr(s, "latest_report_pdf", None))
            or _report_exists(getattr(s, "report_pdf", None))
        )

    return render_template(
        "show_run_details.html",
        title=run_id,
        run_samples=run_samples,
        run_dict=run_dict,
    )


def _delete_sample_related_data(run_id, lab_id=None):
    """
    Delete stored DB rows for one sample or for all samples in a run.
    When the run no longer has samples, also delete the related Job rows.
    """
    targets = [
        ("therapeutic_variants", TherapeuticTable),
        ("other_variants", OtherVariantsTable),
        ("rare_variants", RareVariantsTable),
        ("all_cnas", AllCnas),
        ("lost_exons", LostExonsTable),
        ("summary_qc", SummaryQcTable),
        ("samples", SampleTable),
    ]

    query_kwargs = {"run_id": run_id}
    if lab_id is not None:
        query_kwargs["lab_id"] = lab_id

    sample_q = SampleTable.query.filter_by(**query_kwargs)
    target_samples = sample_q.count()
    if target_samples == 0:
        return None

    deleted = {}
    for label, model in targets:
        q = model.query.filter_by(**query_kwargs)
        n = q.count()
        if n:
            q.delete(synchronize_session=False)
        deleted[label] = n

    remaining = SampleTable.query.filter_by(run_id=run_id).count()
    deleted_jobs = 0
    if remaining == 0:
        job_q = Job.query.filter_by(Analysis=run_id)
        deleted_jobs = job_q.count()
        if deleted_jobs:
            job_q.delete(synchronize_session=False)

    return {
        "deleted": deleted,
        "remaining_samples_in_run": remaining,
        "deleted_jobs": deleted_jobs,
        "target_samples": target_samples,
    }


@app.route("/remove_sample_data/<run_id>/<lab_id>", methods=["POST"])
@login_required
def remove_sample_data(run_id, lab_id):
    """
    Delete all DB records linked to a sample (run_id + lab_id).
    If this was the last sample of the run, also delete the Job row(s) for that run.
    Returns JSON with counts deleted per table + job cleanup info.
    """

    try:
        deletion_result = _delete_sample_related_data(run_id, lab_id=lab_id)
        if deletion_result is None:
            return jsonify({"ok": False, "error": "sample_not_found", "run_id": run_id, "lab_id": lab_id}), 404

        db.session.commit()

        return jsonify({
            "ok": True,
            "run_id": run_id,
            "lab_id": lab_id,
            "deleted": deletion_result["deleted"],
            "remaining_samples_in_run": deletion_result["remaining_samples_in_run"],
            "deleted_jobs": deletion_result["deleted_jobs"],
        }), 200

    except Exception as e:
        db.session.rollback()
        return jsonify({
            "ok": False,
            "run_id": run_id,
            "lab_id": lab_id,
            "error": str(e),
        }), 500


@app.route("/remove_run_data/<run_id>", methods=["POST"])
@login_required
def remove_run_data(run_id):
    """Delete all stored DB rows for every sample in a run, then remove the Job."""
    try:
        deletion_result = _delete_sample_related_data(run_id)
        if deletion_result is None:
            return jsonify({"ok": False, "error": "run_not_found", "run_id": run_id}), 404

        db.session.commit()

        return jsonify({
            "ok": True,
            "run_id": run_id,
            "deleted": deletion_result["deleted"],
            "remaining_samples_in_run": deletion_result["remaining_samples_in_run"],
            "deleted_jobs": deletion_result["deleted_jobs"],
            "deleted_samples": deletion_result["target_samples"],
        }), 200
    except Exception as e:
        db.session.rollback()
        return jsonify({
            "ok": False,
            "run_id": run_id,
            "error": str(e),
        }), 500


@app.route('/update_patient_info', methods=["POST"])
@login_required
def update_patient_info():
    if request.method == "POST":
        data = request.get_json()
        run_id = data["run_id"]
        old_lab_id = data["old_lab_id"]
        old_ext1_id = data["old_ext1_id"]
        lab_id = data["lab_id"]
        modulab_id = data["modulab_id"]
        ext1_id = data["ext1_id"]
        ext2_id = data["ext2_id"]
        ext3_id = data["ext3_id"]
        sample_type = data["sample_type"]
        hospital = data["hospital"]
        tumor_pct = data["tumor_pct"]
        physician_name = data["physician_name"]
        recieved_date = data["recieved_date"]
        biopsy_date = data["biopsy_date"]
        tumor_origin = data["tumor_origin"]
        sex = data["sex"]
        age = data["age"]
        service = data["service"]
        sample_block = data["sample_block"]

        sample = SampleTable.query.filter_by(lab_id=old_lab_id, run_id=run_id).first()
        if sample:
            sample.lab_id = lab_id
            sample.ext1_id = ext1_id
            sample.ext2_id = ext2_id
            sample.ext3_id = ext3_id
            sample.modulab_id = modulab_id
            sample.sample_type = sample_type
            sample.medical_center = hospital
            sample.tumour_purity = tumor_pct
            sample.physician_name = physician_name
            sample.tumor_origin = tumor_origin
            sample.Sex = sex
            sample.Age = age
            sample.sample_block = sample_block
            sample.service = service
            sample.date_original_biopsy = biopsy_date
            sample.petition_date = recieved_date
            db.session.commit()

        petition = (
            Petition.query.filter_by(AP_code=old_lab_id).first()
        )
        if petition:
            print("petition_found")
            petition.AP_code = lab_id
            petition.HC_code = ext2_id
            petition.CIP_code = ext3_id
            petition.Tumour_pct = tumor_pct
            petition.Medical_doctor = physician_name
            petition.Tumour_origin = tumor_origin
            petition.Medical_indication = tumor_origin
            petition.Modulab_id = modulab_id
            petition.Sex = sex
            petition.Age = age
            petition.Sample_block = sample_block
            petition.Service = service

            if biopsy_date:
                petition.Date_original_biopsy = biopsy_date
                sample.date_original_biopsy = biopsy_date
                db.session.commit()

            if recieved_date:
                petition.Petition_date = recieved_date
                sample.petition_date = recieved_date
            db.session.commit()


        tvars = TherapeuticTable.query.filter_by(lab_id=old_lab_id, run_id=run_id).all()
        for variant in tvars:
            variant.lab_id=lab_id
            variant.ext1_id=ext1_id
            variant.ext2_id=ext2_id
            db.session.commit()

        ovars = OtherVariantsTable.query.filter_by(lab_id=old_lab_id, run_id=run_id).all()
        for variant in ovars:
            variant.lab_id=lab_id
            variant.ext1_id=ext1_id
            variant.ext2_id=ext2_id
            # db.session.commit()

        rvars = RareVariantsTable.query.filter_by(lab_id=old_lab_id, run_id=run_id).all()
        for variant in rvars:
            variant.lab_id=lab_id
            variant.ext1_id=ext1_id
            variant.ext2_id=ext2_id
            db.session.commit()

        cnas = AllCnas.query.filter_by(lab_id=old_lab_id, run_id=run_id).all()
        for cna in cnas:
            cna.lab_id=lab_id
            cna.ext1_id=ext1_id
            cna.ext2_id=ext2_id
            db.session.commit()

        fusions = AllFusions.query.filter_by(lab_id=old_lab_id, run_id=run_id).all()
        for fusion in fusions:
            fusion.lab_id=lab_id
            fusion.ext1_id=ext1_id
            fusion.ext2_id=ext2_id
            db.session.commit()

        summaries = SummaryQcTable.query.filter_by(lab_id=old_lab_id, run_id=run_id).all()
        for summary in summaries:
            summary.lab_id = lab_id
            summary.ext1_id=ext1_id
            summary.ext2_id=ext2_id
            db.session.commit()

        message = {"info": "S'han realitzat els canvis correctament"}
        return make_response(jsonify(message), 200)

@app.route('/add_new_variant', methods=['POST'])
def add_new_variant():
    data = request.json or {}

    # Remap tier if needed
    if data.get("tier_catsalut") == "4":
        data["tier_catsalut"] = "None"

    # Clean access helper
    def get(field, default="."):
        return data.get(field) or default
    
    chrom, pos, ref, alt = parse_hgvsg(get("hgvsg"))
    # Construct var_json in required nested structure
    var_json = {
        "CHROM": chrom,  # Could be enhanced to infer from hgvsg
        "POS": pos,        # Same here — unless provided
        "ID": ".",
        "REF": ref,        # Could be parsed from hgvsg, optionally
        "ALT": alt,
        "QUAL": ".",
        "FILTER": "manual",
        "INFO": {
            "DP": get("depth"),
            "AF": get("allele_frequency"),
            "AD": get("read_support"),
            "CSQ": [{
                "SYMBOL": get("gene"),
                "Feature": get("enst_id"),
                "HGVSc": get("hgvsc"),
                "HGVSp": get("hgvsp"),
                "Consequence": get("consequence"),
                "HGVSg": get("hgvsg"),
            }],
            "REFSEQ_ANALYSIS_ISOFORM" : get("enst_id")
        }
    }

    # Create DB entry
    new_variant = TherapeuticTable(
        user_id="manual",
        lab_id=get("lab_id"),
        run_id=get("run_id"),
        ext1_id=get("ext1_id"),
        ext2_id=get("ext2_id"),
        gene=get("gene"),
        enst_id=get("enst_id"),
        hgvsg=get("hgvsg"),
        hgvsc=get("hgvsc"),
        hgvsp=get("hgvsp"),
        variant_type=get("variant_type"),
        exon=get("exon"),
        intron=get("intron"),
        depth=get("depth"),
        allele_frequency=get("allele_frequency"),
        read_support=get("read_support"),
        tier_catsalut=get("tier_catsalut"),
        classification=get("classification"),
        consequence=get("consequence"),
        tumor_type=".",
        var_json=json.dumps(var_json),
        validated_assessor="no",
        validated_bioinfo="no",
        db_detected_number=0,
        db_sample_count=0,
        db_detected_freq=0.0,
        blacklist="no"
    )

    db.session.add(new_variant)
    db.session.commit()

    return jsonify({"info": "S'ha enregistrat una nova variant!"}), 201





@app.route("/modify_tier", methods=["POST"])
#@login_required
def modify_tier():
    """ """
    if request.method == "POST":
        data = request.get_json()
        # print(data)
        tier = data["tier"]
        var_id = data["var_id"]
        var = TherapeuticTable.query.filter_by(id=var_id).first()
        if not var:
            var = OtherVariantsTable.query.filter_by(id=var_id).first()

        if var:
            if tier == "4":
                var.tier_catsalut = "None"
            else:
                var.tier_catsalut = tier
            db.session.commit()
            if tier == "4":
                message = {"info": f"S'ha eliminat la tier per la La variant {var.hgvsg }", "tier": tier}
            else:
                message = {"info": f"La variant {var.hgvsg } s'ha modificat com a tier {tier}", "tier": tier}
            return make_response(jsonify(message), 200)
        message = {"info": f"No s'ha pogut modificar la tier {tier}", "tier": tier}
        return make_response(jsonify(message), 400)


@app.route("/download_summary_qc/<run_id>")
#@login_required
def download_summary_qc(run_id):
    base_path = os.path.join(app.config["STATIC_URL_PATH"], run_id)
    sources = ["GenOncology-Dx", "GenOncology-Dx_1.5", "GenOncology-Dx_1.6", "GenOncology-Dx_2"]
    filenames = [f"GenOncology-Dx_qc.xlsx", f"{run_id}_qc.xlsx"]

    overall_data = []
    overall_header = None
    lost_exons_data = {}

    for source in sources:
        folder = os.path.join(base_path, source)
        if not os.path.isdir(folder):
            continue
        for fname in filenames:
            fpath = os.path.join(folder, fname)
            if os.path.isfile(fpath):
                try:
                    xls = pd.read_excel(fpath, sheet_name=None, header=None)

                    # === Handle Overall_Metrics sheet ===
                    if "Overall_Metrics" in xls:
                        df = xls["Overall_Metrics"]
                        if df.shape[0] >= 3:
                            if overall_header is None:
                                overall_header = df.iloc[0:2]
                            data_part = df.iloc[2:]
                            data_part = data_part[data_part.iloc[:, 0] != "Ext1 ID"]
                            overall_data.append(data_part)

                    # === Handle Lost_Exons sheet ===
                    if "Lost_Exons" in xls:
                        df = xls["Lost_Exons"]
                        if df.shape[0] >= 3:
                            lost_exons_data[source] = df  # keep full with header
                except Exception as e:
                    print(f"Error processing {fpath}: {e}")

    # Stop if nothing was read
    if overall_header is None and not lost_exons_data:
        return "No valid data found in any input file.", 404

    # Write output
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        # Sheet 1: Overall_Metrics
        if overall_header is not None and overall_data:
            merged_overall = pd.concat(overall_data, ignore_index=True)
            overall_header.to_excel(writer, index=False, header=False, startrow=0, sheet_name="Overall_Metrics")
            merged_overall.to_excel(writer, index=False, header=False, startrow=2, sheet_name="Overall_Metrics")

        # Sheet 2 and 3: Lost_Exons from each source
        for source, df in lost_exons_data.items():
            sheet_name = f"Lost_Exons_{source}"
            df.to_excel(writer, index=False, header=False, sheet_name=sheet_name)

    output.seek(0)
    return send_file(
        output,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        download_name=f"{run_id}_summary_qc.xlsx",
        as_attachment=True,
    )


@app.route("/download_sample_bam/<run_id>/<sample>")
#@login_required
def download_sample_bam(run_id, sample):

    sample_object = SampleTable.query.filter_by(lab_id=sample, run_id=run_id).first()
    # print(sample.bam)
    bam_dir = os.path.dirname(sample_object.bam)
    bam_file = sample_object.bam

    bam_file = f"{sample}.rmdup.bam"

    uploads = os.path.join(
        app.config["STATIC_URL_PATH"], run_id, "GenOncology-Dx", sample, "BAM_FOLDER"
    )
    if not os.path.isdir(uploads):
        uploads = os.path.join(
            app.config["STATIC_URL_PATH"], run_id, "GenOncology-Dx_1.5", sample, "BAM_FOLDER"
        )
    if not os.path.isdir(uploads):
        uploads = os.path.join(
            app.config["STATIC_URL_PATH"], run_id, "GenOncology-Dx_1.6", sample, "BAM_FOLDER"
        )



    expected_bam_path = os.path.join(uploads, bam_file)
    if not os.path.isfile(expected_bam_path):
        uploads = os.path.join(
            app.config["STATIC_URL_PATH"], run_id, sample, "BAM_FOLDER"
        )

    print(uploads, bam_file)
    # bam_file = f"{lab_id}.rmdup.bam"
    return send_from_directory(directory=uploads, path=bam_file, as_attachment=True)


@app.route("/download_sample_bai/<run_id>/<sample>")
#@login_required
def download_sample_bai(run_id, sample):
    sample_object = SampleTable.query.filter_by(lab_id=sample, run_id=run_id).first()

    bam_dir = os.path.dirname(sample_object.bam)
    bai_file = f"{sample}.rmdup.bam.bai"

    uploads = os.path.join(
        app.config["STATIC_URL_PATH"], run_id, "GenOncology-Dx", sample, "BAM_FOLDER"
    )
    if not os.path.isdir(uploads):
        uploads = os.path.join(
            app.config["STATIC_URL_PATH"], run_id, "GenOncology-Dx_1.5", sample, "BAM_FOLDER"
        )
    if not os.path.isdir(uploads):
        uploads = os.path.join(
            app.config["STATIC_URL_PATH"], run_id, "GenOncology-Dx_1.6", sample, "BAM_FOLDER"
        )


    expected_bai_path = os.path.join(uploads, bai_file)
    print(expected_bai_path)
    if not os.path.isfile(expected_bai_path):
        uploads = os.path.join(
            app.config["STATIC_URL_PATH"], run_id, sample, "BAM_FOLDER"
        )

    print(uploads, bai_file)
    return send_from_directory(directory=uploads, path=bai_file, as_attachment=True)


@app.route("/download_sample_vcf/<run_id>/<sample>")
#@login_required
def download_sample_vcf(run_id, sample):
    sample_info = (
        SampleTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).first()
    )
    if not sample_info:
        return make_response(f"No s'ha trobat la mostra {sample}", 404)

    vcf_path = _resolve_sample_vcf_path(sample_info)
    if not vcf_path:
        return make_response(f"No s'ha trobat el VCF de la mostra {sample}", 404)

    return send_file(vcf_path, as_attachment=True, download_name=os.path.basename(vcf_path))


def _resolve_sample_vcf_path(sample_info):
    if not sample_info:
        return None

    run_id = str(getattr(sample_info, "run_id", "") or "").strip()
    sample = str(getattr(sample_info, "lab_id", "") or "").strip()
    panel = str(getattr(sample_info, "panel", "") or "").strip()
    static_root = app.config["STATIC_URL_PATH"]

    candidates = []
    seen = set()

    def add_candidate(path_value):
        if not path_value:
            return
        path_str = str(path_value).strip()
        if not path_str or path_str in seen:
            return
        seen.add(path_str)
        candidates.append(path_str)

    def add_vcf_folder_candidates(folder_path):
        if not folder_path:
            return
        add_candidate(os.path.join(folder_path, f"{sample}.mutect2.lancet.vcf"))
        add_candidate(os.path.join(folder_path, f"{sample}.mutect2.lancet.vcf.gz"))
        add_candidate(os.path.join(folder_path, f"{sample}.merged.variants.vcf"))
        add_candidate(os.path.join(folder_path, f"{sample}.merged.variants.vcf.gz"))

    if run_id and panel and sample:
        add_vcf_folder_candidates(
            os.path.join(static_root, run_id, panel, sample, "VCF_FOLDER")
        )
    if run_id and sample:
        add_vcf_folder_candidates(os.path.join(static_root, run_id, sample, "VCF_FOLDER"))
        for folder_path in glob.glob(os.path.join(static_root, run_id, "*", sample, "VCF_FOLDER")):
            add_vcf_folder_candidates(folder_path)

    sample_db_dir = str(getattr(sample_info, "sample_db_dir", "") or "").strip()
    if sample_db_dir:
        add_vcf_folder_candidates(sample_db_dir.replace("REPORT_FOLDER", "VCF_FOLDER"))

    merged_vcf = str(getattr(sample_info, "merged_vcf", "") or "").strip()
    if merged_vcf:
        add_candidate(merged_vcf)
        if merged_vcf.endswith(".gz"):
            add_candidate(merged_vcf[:-3])
        else:
            add_candidate(f"{merged_vcf}.gz")
        merged_dir = os.path.dirname(merged_vcf)
        if merged_dir:
            add_vcf_folder_candidates(merged_dir)

    for path_str in candidates:
        if os.path.isfile(path_str):
            return path_str
    return None


def _get_cgi_sample_metadata(sample_info):
    tumor_origin = getattr(sample_info, "tumor_origin", None)
    diagnosis = getattr(sample_info, "diagnosis", None)
    patient_age = getattr(sample_info, "Age", None)
    patient_sex = getattr(sample_info, "Sex", None)

    def _has_value(value):
        text = str(value).strip() if value is not None else ""
        return bool(text and text not in {".", "None", "NULL"})

    petition = None
    ext1_id = getattr(sample_info, "ext1_id", None)
    if _has_value(ext1_id):
        petition = Petition.query.filter_by(AP_code=str(ext1_id).strip()).first()
    if not petition:
        petition = Petition.query.filter_by(AP_code=sample_info.lab_id).first()
    if not petition:
        petition_id = getattr(sample_info, "petition_id", None)
        if _has_value(petition_id):
            petition = Petition.query.filter_by(Petition_id=str(petition_id).strip()).first()

    if petition:
        if not _has_value(tumor_origin):
            tumor_origin = petition.Tumour_origin
        if not _has_value(patient_age):
            patient_age = petition.Age
        if not _has_value(patient_sex):
            patient_sex = petition.Sex

    return tumor_origin, diagnosis, patient_age, patient_sex


def _send_sample_to_cgi_internal(sample_info, run_id):
    sample = str(getattr(sample_info, "lab_id", "") or "").strip()
    if not run_id or not sample:
        raise ValueError("Cal indicar run_id i mostra per enviar a CGI")

    vcf_path = _resolve_sample_vcf_path(sample_info)
    if not vcf_path:
        raise FileNotFoundError(f"No s'ha trobat el VCF descarregable de la mostra {sample}")

    tumor_origin, diagnosis, patient_age, patient_sex = _get_cgi_sample_metadata(sample_info)
    next_send_count = _current_cgi_send_count(sample_info) + 1
    cgi_result = create_direct_analysis_from_vcf(
        final_vcf=vcf_path,
        run_id=run_id,
        lab_id=sample,
        sequencing_type="GenOncology-Dx",
        tumor_origin=tumor_origin,
        diagnosis=diagnosis,
        update_sample_metadata=True,
        patient_age=patient_age,
        patient_sex=patient_sex,
        send_iteration=next_send_count,
    )
    used_send_count = int(cgi_result.get("_send_iteration") or next_send_count)

    analysis_uuid = (
        cgi_result.get("uuid")
        or cgi_result.get("analysisUuid")
        or cgi_result.get("analysis_uuid")
        or "."
    )
    project_uuid = cgi_result.get("_project_uuid")
    analysis_url = (
        cgi_result.get("_analysis_url")
        or build_analysis_url(project_uuid, analysis_uuid)
    )
    kept_records = cgi_result.get("_kept_records", 0)
    tumor_type = cgi_result.get("_tumor_type", ".")
    sent_on = datetime.now().strftime("%d/%m/%y %H:%M")

    sample_info.cgi_sent = "yes"
    sample_info.cgi_send_count = used_send_count
    sample_info.cgi_analysis_uuid = analysis_uuid if analysis_uuid and analysis_uuid != "." else None
    sample_info.cgi_analysis_url = analysis_url or None
    sample_info.cgi_sent_on = sent_on

    action_dict = {
        "origin_table": None,
        "origin_action": "cgi_direct_analysis",
        "redo": False,
        "target_table": "CGI Clinics",
        "target_action": "create_direct_analysis",
        "analysis_uuid": analysis_uuid,
        "analysis_url": analysis_url,
        "send_iteration": used_send_count,
        "tumor_type": tumor_type,
        "kept_records": kept_records,
        "vcf_path": vcf_path,
        "msg": f"Mostra enviada a CGI Clinics ({analysis_uuid})",
    }
    now = datetime.now()
    vc = VersionControl(
        User_id=7,
        Action_id=generate_key(16),
        Action_name=f"{sample}: enviada a CGI Clinics",
        Action_json=json.dumps(action_dict),
        Modified_on=now.strftime("%d/%m/%y-%H:%M:%S"),
    )
    db.session.add(vc)
    db.session.commit()

    return {
        "sample": sample,
        "analysis_uuid": analysis_uuid,
        "analysis_url": analysis_url,
        "send_iteration": used_send_count,
        "kept_records": kept_records,
        "tumor_type": tumor_type,
        "cgi_sent_on": sent_on,
    }


@app.route("/send_sample_to_cgi", methods=["POST"])
@login_required
def send_sample_to_cgi():
    run_id = (request.form.get("run_id") or "").strip()
    sample = (request.form.get("sample") or "").strip()
    if not run_id or not sample:
        message_text = "Cal indicar run_id i mostra per enviar a CGI"
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return make_response(jsonify({"message_text": message_text}), 400)
        flash(message_text, "danger")
        return redirect(url_for("status"))

    sample_info = (
        SampleTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).first()
    )
    if not sample_info:
        message_text = f"No s'ha trobat la mostra {sample}"
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return make_response(jsonify({"message_text": message_text}), 404)
        flash(message_text, "danger")
        return redirect(url_for("show_run_details", run_id=run_id))

    try:
        response_payload = _send_sample_to_cgi_internal(sample_info, run_id)
        message_text = f"Mostra enviada correctament a CGI Clinics"
        response_payload["message_text"] = message_text
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return make_response(jsonify(response_payload), 200)
        flash(message_text, "success")
        return redirect(
            url_for(
                "show_sample_details",
                run_id=run_id,
                sample=sample,
                sample_id=sample_info.id,
                active="Therapeutic",
            )
        )
    except Exception as exc:
        db.session.rollback()
        message_text = f"No s'ha pogut enviar la mostra a CGI: {exc}"
        status_code = 400
        if isinstance(exc, requests.exceptions.HTTPError):
            status_code = 502
        if request.headers.get("X-Requested-With") == "XMLHttpRequest":
            return make_response(jsonify({"message_text": message_text}), status_code)
        flash(message_text, "danger")
        return redirect(
            url_for(
                "show_sample_details",
                run_id=run_id,
                sample=sample,
                sample_id=sample_info.id,
                active="Therapeutic",
            )
        )


@app.route("/send_run_to_cgi/<run_id>", methods=["POST"])
@login_required
def send_run_to_cgi(run_id):
    run_id = (run_id or "").strip()
    if not run_id:
        flash("Cal indicar el run_id per enviar mostres a CGI", "danger")
        return redirect(url_for("status"))

    run_samples = (
        SampleTable.query.filter_by(run_id=run_id)
        .order_by(SampleTable.lab_id.asc())
        .all()
    )
    if not run_samples:
        flash(f"No s'han trobat mostres per al run {run_id}", "warning")
        return redirect(url_for("show_run_details", run_id=run_id))

    sent_samples = []
    failed_samples = []

    for sample_info in run_samples:
        try:
            payload = _send_sample_to_cgi_internal(sample_info, run_id)
            sent_samples.append(payload["sample"])
        except Exception as exc:
            db.session.rollback()
            failed_samples.append(f"{sample_info.lab_id}: {exc}")

    if sent_samples and not failed_samples:
        flash(
            f"S'han enviat correctament {len(sent_samples)} mostres del run {run_id} a CGI",
            "success",
        )
    elif sent_samples and failed_samples:
        failed_preview = "; ".join(failed_samples[:4])
        if len(failed_samples) > 4:
            failed_preview += "; ..."
        flash(
            f"S'han enviat {len(sent_samples)} mostres a CGI, però {len(failed_samples)} han fallat: {failed_preview}",
            "warning",
        )
    else:
        failed_preview = "; ".join(failed_samples[:4]) or "Error desconegut"
        if len(failed_samples) > 4:
            failed_preview += "; ..."
        flash(
            f"No s'ha pogut enviar cap mostra del run {run_id} a CGI: {failed_preview}",
            "danger",
        )

    return redirect(url_for("show_run_details", run_id=run_id))


@app.route("/download_sample_vep_vcf/<run_id>/<sample>")
#@login_required
def download_sample_vep_vcf(run_id, sample):

    sample_info = (
        SampleTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).first()
    )
    panel = sample_info.panel

    uploads = os.path.join(app.config["STATIC_URL_PATH"], run_id, panel, sample, "VCF_FOLDER")

    vcf_file = f"{sample}.merged.variants.vcf"
    vcf_file_path = os.path.join(uploads, vcf_file)

    return send_from_directory(directory=uploads, path=vcf_file, as_attachment=True)



@app.route("/download_merged_vcf/<run_id>/<sample>")
def download_merged_vcf(run_id, sample):

    sample_info = (
        SampleTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).first()
    )
    panel = sample_info.panel

    uploads = os.path.join(app.config["STATIC_URL_PATH"], run_id, panel, sample, "VCF_FOLDER")

    vcf_file = sample + ".merged.variants.vcf.gz"
    # lancet_vcf_file = f"{sample}.mutect2.lancet.vcf.tbi"
    vcf_file_path = os.path.join(uploads, vcf_file)

    return send_from_directory(directory=uploads, path=vcf_file, as_attachment=True)


@app.route("/download_merged_vcf_tbi/<run_id>/<sample>")
def download_merged_vcf_tbi(run_id, sample):

    sample_info = (
        SampleTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).first()
    )
    panel = sample_info.panel

    uploads = os.path.join(app.config["STATIC_URL_PATH"], run_id, panel, sample, "VCF_FOLDER")

    vcf_file = sample + ".merged.variants.vcf.gz.tbi"
    # lancet_vcf_file = f"{sample}.mutect2.lancet.vcf.tbi"
    vcf_file_path = os.path.join(uploads, vcf_file)

    return send_from_directory(directory=uploads, path=vcf_file, as_attachment=True)


@app.route('/download_cnv_vcf/<run_id>/<sample>')
def download_cnv_vcf(run_id, sample):

    sample_info = (
        SampleTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).first()
    )
    panel = sample_info.panel

    uploads = os.path.join(app.config["STATIC_URL_PATH"], run_id, panel, sample, "VCF_FOLDER", "CNV_FOLDER")

    vcf_file = sample + ".CNV.vcf.gz"
    # lancet_vcf_file = f"{sample}.mutect2.lancet.vcf.tbi"
    vcf_file_path = os.path.join(uploads, vcf_file)
    return send_from_directory(directory=uploads, path=vcf_file, as_attachment=True)

@app.route('/download_cnv_vcf_tbi/<run_id>/<sample>')
def download_cnv_vcf_tbi(run_id, sample):
    sample_info = (
        SampleTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).first()
    )
    panel = sample_info.panel

    uploads = os.path.join(app.config["STATIC_URL_PATH"], run_id, panel, sample, "VCF_FOLDER", "CNV_FOLDER")

    vcf_file = sample + ".CNV.vcf.gz.tbi"
    # lancet_vcf_file = f"{sample}.mutect2.lancet.vcf.tbi"
    vcf_file_path = os.path.join(uploads, vcf_file)
    return send_from_directory(directory=uploads, path=vcf_file, as_attachment=True)


@app.route('/get_annotation_gff')
def get_annotation_gff():

    annotation_gff = app.config["MANE_TRANSCRIPTS"]
    annotation_gff_name = os.path.basename(annotation_gff)
    annotation_gff_dirname = os.path.dirname(annotation_gff)
    return send_from_directory(
        directory=annotation_gff_dirname,
        path=annotation_gff_name,
        as_attachment=False,
    )


@app.route('/download_cnv_seg/<run_id>/<sample>')
def download_cnv_seg(run_id, sample):

    sample_info = (
        SampleTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).first()
    )
    panel = sample_info.panel

    uploads = os.path.join(app.config["STATIC_URL_PATH"], run_id, panel, sample, "VCF_FOLDER", "CNV_FOLDER")

    seg_file = sample + ".seg"
    # lancet_vcf_file = f"{sample}.mutect2.lancet.vcf.tbi"
    seg_file_path = os.path.join(uploads, seg_file)
    return send_from_directory(directory=uploads, path=seg_file, as_attachment=True)



@app.route("/download_all_reports/<run_id>")
#@login_required
def download_all_reports(run_id):
    run_samples = SampleTable.query.filter_by(run_id=run_id).all()
    run_id_zip_name = f"{run_id}.zip"
    run_id_zip_path = os.path.join(
        app.config["UPLOADS"], run_id, run_id_zip_name
    )

    zipf = zipfile.ZipFile(run_id_zip_path, "w", zipfile.ZIP_DEFLATED)
    for sample in run_samples:
        if sample.latest_report_pdf:
            if not sample.latest_report_pdf.endswith(".pdf"):
                sample.latest_report_pdf = f"{sample.latest_report_pdf}.pdf"
            if os.path.isfile(sample.latest_report_pdf):
                report_pdf_path = sample.latest_report_pdf
                zipf.write(report_pdf_path, os.path.basename(report_pdf_path))
        else:
            if os.path.isfile(sample.report_pdf):
                if not sample.report_pdf.endswith(".pdf"):
                    sample.report_pdf = f"{sample.report_pdf}.pdf"
                report_pdf_path = os.path.join(
                    sample.report_pdf, run_id, os.path.basename(sample.report_pdf)
                )
                if os.path.isfile(report_pdf_path):
                    zipf.write(report_pdf_path, os.path.basename(report_pdf_path))
        if sample.latest_short_report_pdf:
            if not sample.latest_short_report_pdf.endswith(".pdf"):
                sample.latest_report_pdf = f"{sample.latest_short_report_pdf}.pdf"
            if os.path.isfile(sample.latest_short_report_pdf):
                report_pdf_path = sample.latest_short_report_pdf
                zipf.write(report_pdf_path, os.path.basename(report_pdf_path))
    zipf.close()
    return send_file(
        run_id_zip_path,
        mimetype="zip",
        download_name=run_id_zip_name,
        as_attachment=True,
    )


def generate_key(self):
    return binascii.hexlify(os.urandom(20)).decode()


@app.route("/show_sample_details/<run_id>/<sample>/<sample_id>/<active>")
#@login_required
def show_sample_details(run_id, sample, sample_id, active):

    sample_info = []
    sample_variants = []
    therapeutic_variants = []
    other_variants = []
    rare_variants = []

    sample_info = (
        SampleTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).first()
    )
    if sample_info:
        if hasattr(sample_info, "ext1_id"):
            if sample_info.ext1_id == ".":
                sample_info.ext1_id = sample_info.lab_id
        else:
            sample_info.ext1_id = sample

    petition_info = (
        Petition.query.filter_by(AP_code=sample_info.ext1_id).first()
    )
    if not petition_info:
        petition_info = (
            Petition.query.filter_by(AP_code=sample_info.lab_id).first()
        )

    if sample_info and petition_info:
        sample_info.modulab_id = petition_info.Modulab_id
        petition_info.Modulab_id = sample_info.modulab_id
        sample_info.ext1_id = petition_info.AP_code
        sample_info.ext2_id = petition_info.HC_code
        sample_info.ext3_id = petition_info.CIP_code
        sample_info.tumour_purity = petition_info.Tumour_pct
        sample_info.Age = petition_info.Age
        sample_info.Sex = petition_info.Sex
        sample_info.service = petition_info.Service
        sample_info.sample_block = petition_info.Sample_block
        sample_info.petition_date = petition_info.Petition_date
        sample_info.tumor_origin = petition_info.Tumour_origin
        db.session.commit()

    summary_qc = (
        SummaryQcTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).first()
    )
    pipeline_details = PipelineDetails.query.filter_by(run_id=run_id).first()
    therapeutic_variants = (
        TherapeuticTable.query.options(
            load_only(
                TherapeuticTable.id,
                TherapeuticTable.gene,
                TherapeuticTable.enst_id,
                TherapeuticTable.hgvsg,
                TherapeuticTable.hgvsc,
                TherapeuticTable.hgvsp,
                TherapeuticTable.exon,
                TherapeuticTable.intron,
                TherapeuticTable.variant_type,
                TherapeuticTable.consequence,
                TherapeuticTable.depth,
                TherapeuticTable.allele_frequency,
                TherapeuticTable.read_support,
                TherapeuticTable.max_af,
                TherapeuticTable.max_af_pop,
                TherapeuticTable.tier_catsalut,
                TherapeuticTable.tumor_type,
                TherapeuticTable.var_json,
                TherapeuticTable.classification,
                TherapeuticTable.blacklist,
                TherapeuticTable.removal_reason,
                TherapeuticTable.removed,
                TherapeuticTable.db_detected_number,
                TherapeuticTable.db_sample_count,
                TherapeuticTable.db_detected_freq,
            )
        )
        .filter_by(lab_id=sample)
        .filter_by(run_id=run_id)
        .distinct()
        .all()
    )
    other_variants = (
        OtherVariantsTable.query.options(
            load_only(
                OtherVariantsTable.id,
                OtherVariantsTable.gene,
                OtherVariantsTable.enst_id,
                OtherVariantsTable.hgvsg,
                OtherVariantsTable.hgvsc,
                OtherVariantsTable.hgvsp,
                OtherVariantsTable.exon,
                OtherVariantsTable.intron,
                OtherVariantsTable.variant_type,
                OtherVariantsTable.consequence,
                OtherVariantsTable.depth,
                OtherVariantsTable.allele_frequency,
                OtherVariantsTable.read_support,
                OtherVariantsTable.max_af,
                OtherVariantsTable.max_af_pop,
                OtherVariantsTable.tier_catsalut,
                OtherVariantsTable.tumor_type,
                OtherVariantsTable.var_json,
                OtherVariantsTable.classification,
                OtherVariantsTable.blacklist,
                OtherVariantsTable.removal_reason,
                OtherVariantsTable.removed,
                OtherVariantsTable.db_detected_number,
                OtherVariantsTable.db_sample_count,
                OtherVariantsTable.db_detected_freq,
            )
        )
        .filter_by(lab_id=sample)
        .filter_by(run_id=run_id)
        .distinct()
        .all()
    )
    rare_variants = (
        RareVariantsTable.query.options(
            load_only(
                RareVariantsTable.id,
                RareVariantsTable.gene,
                RareVariantsTable.enst_id,
                RareVariantsTable.hgvsg,
                RareVariantsTable.hgvsc,
                RareVariantsTable.hgvsp,
                RareVariantsTable.exon,
                RareVariantsTable.intron,
                RareVariantsTable.variant_type,
                RareVariantsTable.consequence,
                RareVariantsTable.depth,
                RareVariantsTable.allele_frequency,
                RareVariantsTable.read_support,
                RareVariantsTable.max_af,
                RareVariantsTable.max_af_pop,
                RareVariantsTable.tier_catsalut,
                RareVariantsTable.tumor_type,
                RareVariantsTable.var_json,
                RareVariantsTable.classification,
                RareVariantsTable.blacklist,
                RareVariantsTable.db_detected_number,
                RareVariantsTable.db_sample_count,
                RareVariantsTable.db_detected_freq,
            )
        )
        .filter_by(lab_id=sample)
        .filter_by(run_id=run_id)
        .filter(RareVariantsTable.hgvsg != ".")
        .distinct()
        .all()
    )
    all_cnas = AllCnas.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
    all_fusions = (
        AllFusions.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
    )
    vcf_folder = sample_info.sample_db_dir.replace(
        "REPORT_FOLDER", "VCF_FOLDER/IGV_SNAPSHOTS"
    )

    tier_variants = {"tier_I": [], "tier_II": [], "tier_III": [], "no_tier": []}
    bad_qual_variants = []

    n_samples = (
        db.session.query(func.count(distinct(SampleTable.lab_id)))
        .filter(~SampleTable.lab_id.contains("test"))
        .filter(~SampleTable.lab_id.contains("Undetermined"))
        .scalar()
        or 0
    )

    def _load_variant_stats(model, variants):
        count_keys = {(v.gene, v.hgvsg) for v in variants if v.gene and v.hgvsg}
        summary_keys = {
            (v.gene or "", v.hgvsg or "", v.hgvsc or "", v.hgvsp or "")
            for v in variants
            if v.gene and v.hgvsg
        }
        if not count_keys and not summary_keys:
            return {}, {}

        count_rows = (
            db.session.query(model.gene, model.hgvsg, func.count(model.id))
            .filter(tuple_(model.gene, model.hgvsg).in_(count_keys))
            .group_by(model.gene, model.hgvsg)
            .all()
        )
        counts = {(g, h): c for g, h, c in count_rows}

        latest_ids = (
            db.session.query(
                func.coalesce(GeneVariantSummary.gene, "").label("gene"),
                func.coalesce(GeneVariantSummary.hgvsg, "").label("hgvsg"),
                func.coalesce(GeneVariantSummary.hgvsc, "").label("hgvsc"),
                func.coalesce(GeneVariantSummary.hgvsp, "").label("hgvsp"),
                func.max(GeneVariantSummary.id).label("max_id"),
            )
            .filter(
                tuple_(
                    func.coalesce(GeneVariantSummary.gene, ""),
                    func.coalesce(GeneVariantSummary.hgvsg, ""),
                    func.coalesce(GeneVariantSummary.hgvsc, ""),
                    func.coalesce(GeneVariantSummary.hgvsp, ""),
                ).in_(summary_keys)
            )
            .group_by(
                func.coalesce(GeneVariantSummary.gene, ""),
                func.coalesce(GeneVariantSummary.hgvsg, ""),
                func.coalesce(GeneVariantSummary.hgvsc, ""),
                func.coalesce(GeneVariantSummary.hgvsp, ""),
            )
            .subquery()
        )
        summary_rows = (
            db.session.query(GeneVariantSummary)
            .join(latest_ids, GeneVariantSummary.id == latest_ids.c.max_id)
            .all()
        )
        summaries = {
            (s.gene or "", s.hgvsg or "", s.hgvsc or "", s.hgvsp or ""): s
            for s in summary_rows
        }
        return counts, summaries

    t_counts, t_summaries = _load_variant_stats(TherapeuticTable, therapeutic_variants)
    o_counts, o_summaries = _load_variant_stats(OtherVariantsTable, other_variants)
    r_counts, r_summaries = _load_variant_stats(RareVariantsTable, rare_variants)

    def _internal_classification_score(var):
        kb = getattr(var, "kb", None) or {}
        if not isinstance(kb, dict):
            return 0
        ranked_fields = (
            "Oncogenic summary",
            "Oncogenic prediction",
            "ClinVar Germline",
            "ClinVar Somatic",
            "OncoKB",
            "Franklin ACMG",
            "Franklin Oncogenicity",
            "MTBP",
            "Càncer",
            "Data Classificació",
        )
        return sum(1 for f in ranked_fields if str(kb.get(f, "")).strip())

    def _variant_rank_key(var):
        return (
            -getattr(var, "_internal_classification_score", 0),
            -int(getattr(var, "db_detected_number", 0) or 0),
            (var.gene or ""),
            (var.hgvsg or ""),
        )

    def _collect_numeric_values(value):
        vals = []
        if value is None:
            return vals
        if isinstance(value, (int, float)):
            return [float(value)]
        if isinstance(value, (list, tuple, set)):
            for it in value:
                vals.extend(_collect_numeric_values(it))
            return vals
        if isinstance(value, dict):
            for it in value.values():
                vals.extend(_collect_numeric_values(it))
            return vals
        if isinstance(value, str):
            for tok in re.findall(r"-?\d+(?:\.\d+)?", value):
                try:
                    vals.append(float(tok))
                except Exception:
                    pass
        return vals

    def _extract_predictor_scores(variant_dict):
        revel_score = None
        spliceai_score = None
        info = variant_dict.get("INFO", {}) if isinstance(variant_dict, dict) else {}
        if not isinstance(info, dict):
            return revel_score, spliceai_score
        csq = info.get("CSQ", {})
        csq_candidates = []
        if isinstance(csq, dict):
            csq_candidates.append(csq)
        elif isinstance(csq, list):
            for entry in csq:
                if isinstance(entry, dict):
                    csq_candidates.append(entry)

        # REVEL: direct key first, fallback to any key containing revel.
        revel_keys = ["REVEL", "REVEL_score", "REVEL_SCORE", "revel", "revel_score"]
        revel_vals = []
        for source in [info] + csq_candidates:
            for key in revel_keys:
                if key in source:
                    revel_vals.extend(_collect_numeric_values(source.get(key)))
        if not revel_vals:
            for source in [info] + csq_candidates:
                for key, val in source.items():
                    if "revel" in str(key).lower():
                        revel_vals.extend(_collect_numeric_values(val))
        if revel_vals:
            revel_score = max(revel_vals)

        # SpliceAI: prefer DS_* keys (commonly under CSQ), fallback to any key containing spliceai.
        splice_vals = []
        ds_keys = [
            "SpliceAI_DS_AG", "SpliceAI_DS_AL", "SpliceAI_DS_DG", "SpliceAI_DS_DL",
            "SpliceAI_pred_DS_AG", "SpliceAI_pred_DS_AL", "SpliceAI_pred_DS_DG", "SpliceAI_pred_DS_DL",
            "DS_AG", "DS_AL", "DS_DG", "DS_DL",
        ]
        for source in [info] + csq_candidates:
            for key in ds_keys:
                if key in source:
                    splice_vals.extend(_collect_numeric_values(source.get(key)))
        if not splice_vals:
            for source in [info] + csq_candidates:
                for key, val in source.items():
                    if "spliceai" in str(key).lower():
                        splice_vals.extend(_collect_numeric_values(val))
        if splice_vals:
            spliceai_score = max(splice_vals)

        return revel_score, spliceai_score

    def _extract_filter_tag(variant_dict):
        if not isinstance(variant_dict, dict):
            return None

        info = variant_dict.get("INFO", {})
        raw_filter = variant_dict.get("FILTER")
        if raw_filter is None and isinstance(info, dict):
            for key in ("FILTER", "filter", "FILTERS", "filters"):
                if key in info:
                    raw_filter = info.get(key)
                    break

        if raw_filter is None:
            return None

        if isinstance(raw_filter, (list, tuple, set)):
            parts = [str(v).strip() for v in raw_filter if str(v).strip()]
            return ";".join(parts) if parts else None

        if isinstance(raw_filter, dict):
            parts = []
            for key, value in raw_filter.items():
                if isinstance(value, bool):
                    if value:
                        parts.append(str(key))
                elif value is None or str(value).strip() == "":
                    parts.append(str(key))
                else:
                    parts.append(f"{key}:{value}")
            return ";".join(parts) if parts else None

        value = str(raw_filter).strip()
        if value in ("", ".", "-", "None", "null"):
            return None
        return value

    remove_filter_tags = [
        "base_qual",
        "orientation",
        "strand_bias",
        "weak_evidence",
        "panel_of_normals",
    ]
    remove_filter_tags_set = set(remove_filter_tags)

    def _has_removed_filter_tag(filter_tag_value):
        if not filter_tag_value:
            return False

        raw_parts = re.split(r"[;,\|]", str(filter_tag_value))
        for raw_part in raw_parts:
            normalized = str(raw_part).strip().lower()
            if not normalized:
                continue
            normalized = normalized.split(":", 1)[0].strip()
            if normalized in remove_filter_tags_set:
                return True
        return False

    for var in therapeutic_variants:
        var.kb = {}
        var.revel_score = None
        var.spliceai_score = None
        var.filter_tag = None
        try:
            variant_dict = json.loads(var.var_json)
        except:
            var.refseq = var.enst_id
        else:
            var.refseq = variant_dict["INFO"]["REFSEQ_ANALYSIS_ISOFORM"]
            var.revel_score, var.spliceai_score = _extract_predictor_scores(variant_dict)
            var.filter_tag = _extract_filter_tag(variant_dict)
        if _has_removed_filter_tag(var.filter_tag):
            continue

 
        n_var = t_counts.get((var.gene, var.hgvsg), 0)
        var_kb = t_summaries.get((var.gene or "", var.hgvsg or "", var.hgvsc or "", var.hgvsp or ""))
        if var_kb:
            var_kb_str = var_kb.data_json
            # var.kb = json.loads(var_kb_str.encode('utf-8').decode('utf-8'))
            if isinstance(var_kb_str, bytes):
                var_kb_str = var_kb_str.decode('utf-8')  # Decode bytes to string

            # Parse the JSON string into a Python dictionary
            var.kb = json.loads(var_kb_str)
        var._internal_classification_score = _internal_classification_score(var)

        var.db_detected_number = n_var
        var.db_sample_count = n_samples
        if var.tier_catsalut != "None":
            if var.tier_catsalut == "1":
                if var not in tier_variants["tier_I"]:
                    tier_variants["tier_I"].append(var)
            if var.tier_catsalut == "2":
                if var not in tier_variants["tier_II"]:
                    tier_variants["tier_II"].append(var)
            if var.tier_catsalut == "3":
                if var not in tier_variants["tier_III"]:

                    tier_variants["tier_III"].append(var)
            if var.tier_catsalut == "":
                if var not in tier_variants["no_tier"]:
                    tier_variants["no_tier"].append(var)
        else:
            if var.blacklist == "no":
                tier_variants["no_tier"].append(var)
            else:
                bad_qual_variants.append(var)

    for var in other_variants:

        var.kb = {}
        var.revel_score = None
        var.spliceai_score = None
        var.filter_tag = None
        variant_dict = json.loads(var.var_json)
        try: 
            variant_dict["INFO"]["REFSEQ_ANALYSIS_ISOFORM"]
        except:
            var.refseq = var.enst_id
        else:
            var.refseq = variant_dict["INFO"]["REFSEQ_ANALYSIS_ISOFORM"]
        var.revel_score, var.spliceai_score = _extract_predictor_scores(variant_dict)
        var.filter_tag = _extract_filter_tag(variant_dict)
        if _has_removed_filter_tag(var.filter_tag):
            continue
            
        n_var = o_counts.get((var.gene, var.hgvsg), 0)
        var_kb = o_summaries.get((var.gene or "", var.hgvsg or "", var.hgvsc or "", var.hgvsp or ""))

        var.db_detected_number = n_var
        var.db_sample_count = n_samples
        if var_kb:
            var_kb_str = var_kb.data_json
            if isinstance(var_kb_str, bytes):
                var_kb_str = var_kb_str.decode('utf-8')  # Decode bytes to string

            # Parse the JSON string into a Python dictionary
            var.kb = json.loads(var_kb_str)
        var._internal_classification_score = _internal_classification_score(var)

        if var.tier_catsalut != "None":
            if var.tier_catsalut == "1":
                if var not in tier_variants["tier_I"]:
                    tier_variants["tier_I"].append(var)
            if var.tier_catsalut == "2":
                if var not in tier_variants["tier_II"]:
                    tier_variants["tier_II"].append(var)
            if var.tier_catsalut == "3":
                if var not in tier_variants["tier_III"]:
                    tier_variants["tier_III"].append(var)
            if var.tier_catsalut == "":
                if var not in tier_variants["no_tier"]:
                    tier_variants["no_tier"].append(var)
        else:
            if var.blacklist == "no":
                tier_variants["no_tier"].append(var)
            else:
                bad_qual_variants.append(var)

    for var in rare_variants:
        var.kb = {}
        var.revel_score = None
        var.spliceai_score = None
        var.filter_tag = None
        variant_dict = json.loads(var.var_json)

        try: 
            variant_dict["INFO"]["REFSEQ_ANALYSIS_ISOFORM"]
        except:
            var.refseq = var.enst_id
        else:
            var.refseq = variant_dict["INFO"]["REFSEQ_ANALYSIS_ISOFORM"]
        var.revel_score, var.spliceai_score = _extract_predictor_scores(variant_dict)
        var.filter_tag = _extract_filter_tag(variant_dict)
        if _has_removed_filter_tag(var.filter_tag):
            continue

        n_var = r_counts.get((var.gene, var.hgvsg), 0)
        var.db_detected_number = n_var
        var.db_sample_count = n_samples
        var_kb = r_summaries.get((var.gene or "", var.hgvsg or "", var.hgvsc or "", var.hgvsp or ""))
        if var_kb:
            var_kb_str = var_kb.data_json
            if isinstance(var_kb_str, bytes):
                var_kb_str = var_kb_str.decode("utf-8")
            var.kb = json.loads(var_kb_str)
        var._internal_classification_score = _internal_classification_score(var)

        if var.hgvsg == ".":
            continue

    for tier_name in ("tier_I", "tier_II", "tier_III", "no_tier"):
        tier_variants[tier_name].sort(key=_variant_rank_key)
    bad_qual_variants.sort(key=_variant_rank_key)

    tier_list = (
        tier_variants["tier_I"]
        + tier_variants["tier_II"]
        + tier_variants["tier_III"]
        + tier_variants["no_tier"]
    )
    seen_dict = dict()
    out_tier_list = []
    for t in tier_list:
        key = f"{t.hgvsg}-{t.gene}"
        if not key in seen_dict:
            seen_dict[key] = 0
        seen_dict[key] +=1
        if seen_dict[key] > 1:
            continue
        out_tier_list.append(t)

    relevant_variants = out_tier_list + bad_qual_variants

    All_jobs = Job.query.order_by(desc(Job.Date)).limit(5).all()
    All_changes = VersionControl.query.order_by(desc(VersionControl.Id)).all()
    All_changes_dict = defaultdict(dict)

    num_id_dict = dict()
    for c in All_changes:
        id = c.Action_id
        num_id_dict[id] = 0

        if not id in All_changes_dict:
            All_changes_dict[id] = defaultdict(dict)
            num_id_dict[id] += 1
        instruction_dict = defaultdict(dict)
        instruction_dict["action_json"] = json.loads(c.Action_json)
        instruction_dict["modified_on"] = c.Modified_on
        All_changes_dict[id]["action_data"] = instruction_dict
        All_changes_dict[id]["action_name"] = c.Action_name
        if len(num_id_dict.keys()) == 15:
            break

    merged_vcf = sample_info.merged_vcf
    merged_json = merged_vcf.replace(".vcf", ".json")

    merged_dict = dict()
    snv_dict = defaultdict()
    with open(merged_json) as js:
        merged_dict = json.load(js)
    vaf_list = []

    plot_vaf = ""
    plot_snv = ""
    if os.path.isfile(merged_vcf):
        for var in merged_dict["variants"]:
            if (
                "REF" in merged_dict["variants"][var]
                and "ALT" in merged_dict["variants"][var]
            ):
                ref = merged_dict["variants"][var]["REF"]
                alt = merged_dict["variants"][var]["ALT"]
                if len(ref) == 1 and len(alt) == 1:
                    if ref not in snv_dict:
                        snv_dict[ref] = defaultdict()
                    if alt not in snv_dict[ref]:
                        snv_dict[ref][alt] = 0
                    snv_dict[ref][alt] += 1

            if "AF" in merged_dict["variants"][var]:
                vaf_raw = merged_dict["variants"][var]["AF"]
                tmp_list = vaf_raw.split(",")
                for v in tmp_list:
                    if v == ".":
                        continue
                    vaf_list.append(float(v))
        plot_vaf = vaf_plot(vaf_list)
        plot_snv = snv_plot(snv_dict)

    summary_qc_dict = json.loads(summary_qc.summary_json)
    fastp_dict = json.loads(summary_qc.fastp_json)

    lost_exons_100x = []
    lost_exons_dict = summary_qc_dict.get("LOST_EXONS", {}).get("exons", {})
    for roi_key, roi_dict in lost_exons_dict.items():
        exon_number = str(roi_dict.get("EXON_NUMBER", "") or "").strip()
        if exon_number in ("", ".", "None", "nan"):
            continue

        call_rate_100x = roi_dict.get("COV_THRESHOLD", {}).get("100X")
        try:
            call_rate_100x = float(str(call_rate_100x).replace("%", "").strip())
        except (TypeError, ValueError):
            continue

        if call_rate_100x < 100:
            lost_exons_100x.append((roi_key, roi_dict))

    read1_basequal_dict = fastp_dict["read1_before_filtering"]["quality_curves"]
    plot_read1 = basequal_plot(read1_basequal_dict)

    read2_basequal_dict = fastp_dict["read2_before_filtering"]["quality_curves"]
    plot_read2 = basequal_plot(read2_basequal_dict)
    cnv_plotdata = {}
    try:
        cnv_plotdata = json.loads(sample_info.cnv_json)
    except:
        pass
    
    plot_cnv = ""
    pie_plot = ""
    bar_plot = ""
    plot_cnv = cnv_plot(cnv_plotdata)


    def chrom_key(chrom):
        m = re.search(r'(\d+)$', str(chrom))
        if m:
            return int(m.group(1))
        else:
            # non-numeric chrs (like X, Y, MT) go after 1–22
            return float('inf')

    cnv_entries = []
    for k,v in cnv_plotdata.items():
        try:
            region = float(k)
        except ValueError:
            continue    

        tmp_coordinates = re.split(r":|-",  v["Coordinates"])
        chromosome = tmp_coordinates[0]
        pos = tmp_coordinates[1]

        cnv_entries.append({
            "region":        region,
            "roi_log2":      float(v.get("roi_log2",0)),
            "segment_log2":  float(v.get("segment_log2",0)),
            "gene":          v.get("Gene",""),
            "chromosome":    chromosome,  # <— ensure this is set
            "position": pos
        })
   
    cnv_entries.sort(
        key=lambda d: (
            chrom_key(d["chromosome"]),
            d["region"]
        )
    )


    # then pass json.dumps(cnv_entries) as cnv_data

    pie_plot, bar_plot = var_location_pie(rare_variants)
    read1_adapters_dict = fastp_dict["adapter_cutting"]["read1_adapter_counts"]
    read2_adapters_dict = fastp_dict["adapter_cutting"]["read2_adapter_counts"]
    r1_adapters_plot = adapters_plot(read1_adapters_dict, read2_adapters_dict)

    if petition_info:
        pattern = r'^\d{4}-\d{2}-\d{2}'
        match = re.match(pattern, petition_info.Date_original_biopsy)
        if match:
            tmp_date =petition_info.Date_original_biopsy.replace("-", "/").replace(" 00:00:00", "")
            tmp_date_list = tmp_date.split("/")
            newdate = f"{tmp_date_list[2]}/{tmp_date_list[1]}/{tmp_date_list[0]}"
            petition_info.Date_original_biopsy = newdate
            db.session.commit()
        print(petition_info.Petition_date)
        match = re.match(pattern, petition_info.Petition_date)
        if match:
            tmp_date = petition_info.Petition_date.replace("-", "/").replace(" 00:00:00", "")
            tmp_date_list = tmp_date.split("/")
            newdate = f"{tmp_date_list[2]}/{tmp_date_list[1]}/{tmp_date_list[0]}"
            petition_info.Petition_date = newdate
            db.session.commit()

    cons_counter = Counter()
    vartype_counter = Counter()
    for var in rare_variants:
        normalized_consequences = set()
        for entry in re.split(r"[,&]", var.consequence or ""):
            entry = entry.strip()
            if entry:
                normalized_entry = "splicing_variant" if "splice" in entry.lower() else entry
                normalized_consequences.add(normalized_entry)
        for entry in normalized_consequences:
            cons_counter[entry] += 1
        if var.variant_type:
            vartype_counter[var.variant_type] += 1


    return render_template(
        "show_sample_details.html",
        title=sample,
        active=active,
        petition_info=petition_info,
        sample_info=sample_info,
        sample_id=sample_id,
        sample_variants=sample_variants,
        summary_qc_dict=summary_qc_dict,
        lost_exons_100x=lost_exons_100x,
        fastp_dict=fastp_dict,
        pipeline_details=pipeline_details,
        # therapeutic_variants=therapeutic_variants,
        other_variants=other_variants,
        relevant_variants=relevant_variants,
        rare_variants=rare_variants,
        plot_read1=plot_read1,
        plot_read2=plot_read2,
        cnv_plot=plot_cnv,
        pie_plot=pie_plot,
        r1_adapters_plot=r1_adapters_plot,
        bar_plot=bar_plot,
        vaf_plot=plot_vaf,
        snv_plot=plot_snv,
        all_cnas=all_cnas,
        gene_mech=GENE_MECH,
        snv_data=json.dumps(snv_dict),
        vaf_data=json.dumps(vaf_list),
        cons_data=json.dumps(cons_counter),
        vartype_data=json.dumps(vartype_counter),
        cnv_data=json.dumps(cnv_entries),
        all_fusions=all_fusions,
        vcf_folder=vcf_folder,
        All_jobs=All_jobs,
        All_changes=All_changes,
        All_changes_dict=All_changes_dict,
    )

@app.route(
    "/update_therapeutic_variant/<run_id>/<sample>/<sample_id>/<var_id>/<var_classification>",
    methods=["GET", "POST"],
)
#@login_required
def update_therapeutic_variant(run_id, sample, sample_id, var_id, var_classification):

    if var_classification == "Therapeutic":
        variant = TherapeuticTable.query.filter_by(id=var_id).first()
    if var_classification == "Other":
        variant = OtherVariantsTable.query.filter_by(id=var_id).first()
    if var_classification == "Rare":
        variant = RareVariantsTable.query.filter_by(id=var_id).first()
    new_active = "Rare" if var_classification == "Rare" else "Therapeutic"
    if request.method == "POST":
        therapies = ""
        diseases = ""
        new_classification = ""
        if request.form.get("therapies"):
            therapies = request.form["therapies"]
        if request.form.get("diseases"):
            diseases = request.form["diseases"]

        blacklist_value = "yes" if request.form.get("blacklist_check") else "no"
        variant.blacklist = blacklist_value

        matched_variants = (
            Variants.query.filter_by(hgvsg=variant.hgvsg)
            .filter_by(hgvsc=variant.hgvsc)
            .filter_by(hgvsp=variant.hgvsp)
            .all()
        )
        for matched_variant in matched_variants:
            matched_variant.blacklist = blacklist_value

        db.session.commit()

        if request.form.get("variant_category"):

            new_classification = request.form["variant_category"].strip()
            new_active = var_classification

            if new_classification != var_classification:
                if var_classification == "Therapeutic" and new_classification == "2":
                    db.session.delete(variant)
                    db.session.commit()

                    other = OtherVariantsTable(
                        user_id=variant.user_id,
                        lab_id=variant.lab_id,
                        ext1_id=variant.ext1_id,
                        ext2_id=variant.ext2_id,
                        run_id=variant.run_id,
                        petition_id=variant.petition_id,
                        gene=variant.gene,
                        enst_id=variant.enst_id,
                        hgvsp=variant.hgvsp,
                        hgvsg=variant.hgvsg,
                        hgvsc=variant.hgvsc,
                        exon=variant.exon,
                        intron=variant.intron,
                        variant_type=variant.variant_type,
                        consequence=variant.consequence,
                        depth=variant.depth,
                        allele_frequency=variant.allele_frequency,
                        read_support=variant.read_support,
                        max_af=variant.max_af,
                        max_af_pop=variant.max_af_pop,
                        therapies=variant.therapies,
                        clinical_trials=variant.clinical_trials,
                        tier_catsalut="None",
                        tumor_type=variant.tumor_type,
                        var_json=variant.var_json,
                        classification="Other",
                        validated_assessor=variant.validated_assessor,
                        validated_bioinfo=variant.validated_bioinfo,
                        blacklist=variant.blacklist,
                    )

                    db.session.add(other)
                    db.session.commit()
                    new_active = "Other"

                if var_classification == "Therapeutic" and new_classification == "3":
                    db.session.delete(variant)
                    db.session.commit()

                    rare = RareVariantsTable(
                        user_id=variant.user_id,
                        lab_id=variant.lab_id,
                        ext1_id=variant.ext1_id,
                        ext2_id=variant.ext2_id,
                        run_id=variant.run_id,
                        petition_id=variant.petition_id,
                        gene=variant.gene,
                        enst_id=variant.enst_id,
                        hgvsp=variant.hgvsp,
                        hgvsg=variant.hgvsg,
                        hgvsc=variant.hgvsc,
                        exon=variant.exon,
                        intron=variant.intron,
                        variant_type=variant.variant_type,
                        consequence=variant.consequence,
                        depth=variant.depth,
                        allele_frequency=variant.allele_frequency,
                        read_support=variant.read_support,
                        max_af=variant.max_af,
                        max_af_pop=variant.max_af_pop,
                        therapies=variant.therapies,
                        clinical_trials=variant.clinical_trials,
                        tier_catsalut="None",
                        tumor_type=variant.tumor_type,
                        var_json=variant.var_json,
                        classification="Rare",
                        validated_assessor=variant.validated_assessor,
                        validated_bioinfo=variant.validated_bioinfo,
                        blacklist=variant.blacklist,
                    )

                    db.session.add(rare)
                    db.session.commit()
                    new_active = "Rare"

                if var_classification == "Other" and new_classification == "1":
                    db.session.delete(variant)
                    db.session.commit()

                    therapeutic = TherapeuticTable(
                        user_id=variant.user_id,
                        lab_id=variant.lab_id,
                        ext1_id=variant.ext1_id,
                        ext2_id=variant.ext2_id,
                        run_id=variant.run_id,
                        petition_id=variant.petition_id,
                        gene=variant.gene,
                        enst_id=variant.enst_id,
                        hgvsp=variant.hgvsp,
                        hgvsg=variant.hgvsg,
                        hgvsc=variant.hgvsc,
                        exon=variant.exon,
                        intron=variant.intron,
                        variant_type=variant.variant_type,
                        consequence=variant.consequence,
                        depth=variant.depth,
                        allele_frequency=variant.allele_frequency,
                        read_support=variant.read_support,
                        max_af=variant.max_af,
                        max_af_pop=variant.max_af_pop,
                        therapies=variant.therapies,
                        clinical_trials=variant.clinical_trials,
                        tier_catsalut="None",
                        tumor_type=variant.tumor_type,
                        var_json=variant.var_json,
                        classification="Therapeutic",
                        validated_assessor=variant.validated_assessor,
                        validated_bioinfo=variant.validated_bioinfo,
                        blacklist=variant.blacklist,
                    )

                    db.session.add(therapeutic)
                    db.session.commit()
                    new_active = "Therapeutic"

                if var_classification == "Other" and new_classification == "3":
                    db.session.delete(variant)
                    db.session.commit()

                    rare = RareVariantsTable(
                        user_id=variant.user_id,
                        lab_id=variant.lab_id,
                        ext1_id=variant.ext1_id,
                        ext2_id=variant.ext2_id,
                        run_id=variant.run_id,
                        petition_id=variant.petition_id,
                        gene=variant.gene,
                        enst_id=variant.enst_id,
                        hgvsp=variant.hgvsp,
                        hgvsg=variant.hgvsg,
                        hgvsc=variant.hgvsc,
                        exon=variant.exon,
                        intron=variant.intron,
                        variant_type=variant.variant_type,
                        consequence=variant.consequence,
                        depth=variant.depth,
                        allele_frequency=variant.allele_frequency,
                        read_support=variant.read_support,
                        max_af=variant.max_af,
                        max_af_pop=variant.max_af_pop,
                        therapies=variant.therapies,
                        clinical_trials=variant.clinical_trials,
                        tier_catsalut="None",
                        tumor_type=variant.tumor_type,
                        var_json=variant.var_json,
                        classification="Rare",
                        validated_assessor=variant.validated_assessor,
                        validated_bioinfo=variant.validated_bioinfo,
                        blacklist=variant.blacklist,
                    )

                    db.session.add(rare)
                    db.session.commit()
                    new_active = "Rare"

                if var_classification == "Rare" and new_classification != "3":
                    db.session.delete(variant)
                    db.session.commit()

                    therapeutic = TherapeuticTable(
                        user_id=variant.user_id,
                        lab_id=variant.lab_id,
                        ext1_id=variant.ext1_id,
                        ext2_id=variant.ext2_id,
                        run_id=variant.run_id,
                        petition_id=variant.petition_id,
                        gene=variant.gene,
                        enst_id=variant.enst_id,
                        hgvsp=variant.hgvsp,
                        hgvsg=variant.hgvsg,
                        hgvsc=variant.hgvsc,
                        exon=variant.exon,
                        intron=variant.intron,
                        variant_type=variant.variant_type,
                        consequence=variant.consequence,
                        depth=variant.depth,
                        allele_frequency=variant.allele_frequency,
                        read_support=variant.read_support,
                        max_af=variant.max_af,
                        max_af_pop=variant.max_af_pop,
                        therapies=variant.therapies,
                        clinical_trials=variant.clinical_trials,
                        tier_catsalut="None",
                        tumor_type=variant.tumor_type,
                        var_json=variant.var_json,
                        classification="Therapeutic",
                        validated_assessor=variant.validated_assessor,
                        validated_bioinfo=variant.validated_bioinfo,
                        blacklist=variant.blacklist,
                    )

                    db.session.add(therapeutic)
                    db.session.commit()
                    new_active = "Therapeutic"


        msg = ("La variant {} s'ha modificat correctament").format(variant.hgvsg)
        flash(msg, "success")

    sample_info = SampleTable.query.filter_by(lab_id=sample).first()
    sample_variants = SampleVariants.query.filter_by(sample_id=sample_id).all()
    summary_qc = SummaryQcTable.query.filter_by(lab_id=sample).first()
    therapeutic_variants = (
        TherapeuticTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
    )
    other_variants = (
        OtherVariantsTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
    )
    rare_variants = (
        RareVariantsTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
    )
    vcf_folder = sample_info.sample_db_dir.replace(
        "REPORT_FOLDER", "VCF_FOLDER/IGV_SNAPSHOTS"
    )

    return redirect(
        url_for(
            "show_sample_details",
            run_id=run_id,
            sample=sample,
            sample_id=sample_id,
            active=new_active,
            vcf_folder=vcf_folder,
        )
    )


@app.route("/redo_action/<action_id>/<run_id>/<sample>/<sample_id>/<active>")
#@login_required
def redo_action(action_id, run_id, sample, sample_id, active):

    actions = VersionControl.query.filter_by(Action_id=action_id).all()
    for action in actions:
        action_json = json.loads(action.Action_json)
        db.session.delete(action)
        db.session.commit()
        if action_json["origin_action"] == "delete":
            action_dict = json.loads(action_json["action_json"])
            rebuild_list = []
            for field in action_dict:
                rebuild_list.append(field + "=" + str(action_dict[field]))
            rebuild_str = ",".join(rebuild_list)
            origin_table = action_json["origin_table"]

            if origin_table == "TherapeuticTable":
                oc = TherapeuticTable(**action_dict)
                db.session.add(oc)
            if origin_table == "RareVariantsTable":
                oc = RareVariantsTable(**action_dict)
                db.session.add(oc)
            if origin_table == "OtherVariantsTable":
                oc = OtherVariantsTable(**action_dict)
                db.session.add(oc)
            try:
                db.session.commit()
                if len(actions) == 1:
                    flash("Variant insertada de nou!", "success")
            except:
                flash("Error durant la inserció de la Variant", "error")

    return redirect(
        url_for(
            "show_sample_details",
            run_id=run_id,
            sample=sample,
            sample_id=sample_id,
            active=active,
        )
    )

@app.route(
    "/remove_variant/<run_id>/<sample>/<sample_id>/<var_id>/<var_classification>",
    methods=["GET", "POST"],
)
def remove_variant(run_id, sample, sample_id, var_id, var_classification):
    """Soft-delete a variant (mark removed, capture reason)."""

    # Pull reason from POST or JSON
    reason = (request.form.get("reason")
              or (request.get_json(silent=True) or {}).get("reason")
              or "").strip()

    # Locate the record
    origin_table = None
    variant = None
    if var_classification == "Therapeutic":
        origin_table = "TherapeuticTable"
        variant = TherapeuticTable.query.get(var_id)
    elif var_classification == "Other":
        origin_table = "OtherVariantsTable"
        variant = OtherVariantsTable.query.get(var_id)
    elif var_classification == "Rare":
        origin_table = "RareVariantsTable"
        variant = RareVariantsTable.query.get(var_id)

    msg = "No s'ha trobat la variant."
    status = "error"

    if variant:
        hgvsg = getattr(variant, "hgvsg", None) or var_id

        # Soft-delete fields (if present on the model)
        if hasattr(variant, "removal_reason"):
            variant.removal_reason = reason[:1000] if reason else None
        if hasattr(variant, "removed"):
            variant.removed = "yes"

        # VersionControl bookkeeping
        action_dict = {
            "origin_table": origin_table,
            "origin_action": "soft_delete",
            "redo": True,
            "target_table": None,
            "target_action": None,
            "action_json": json.dumps(variant, cls=AlchemyEncoder),
            "delete_reason": reason,
            "msg": f"Variant {hgvsg} marcada com eliminada"
        }
        action_str = json.dumps(action_dict)
        action_name = f"{sample}: {hgvsg} marcada com eliminada"
        dt = datetime.now().strftime("%d/%m/%y-%H:%M:%S")
        vc = VersionControl(
            User_id=7,  # TODO: current_user.id
            Action_id=generate_key(16),
            Action_name=action_name,
            Action_json=action_str,
            Modified_on=dt
        )
        db.session.add(vc)

        db.session.commit()
        status = "ok"
        msg = f"S'ha marcat com eliminada la variant {hgvsg} de la taula {origin_table}"
        if not request.headers.get("X-Requested-With") == "XMLHttpRequest":
            flash(msg, "success")

    # AJAX → JSON
    if request.headers.get("X-Requested-With") == "XMLHttpRequest":
        return jsonify({"status": status, "message": msg, "deleted_var_id": var_id, "reason": reason})

    # Non-AJAX → redirect as before
    sample_info = SampleTable.query.filter_by(lab_id=sample, run_id=run_id).first()
    vcf_folder = sample_info.sample_db_dir.replace("REPORT_FOLDER","VCF_FOLDER/IGV_SNAPSHOTS")
    return redirect(url_for(
        "show_sample_details",
        run_id=run_id, sample=sample, sample_id=sample_id,
        vcf_folder=vcf_folder, active="Therapeutic",
    ))


# @app.route(
#     "/remove_variant/<run_id>/<sample>/<sample_id>/<var_id>/<var_classification>",
#     methods=["GET", "POST"],
# )
# def remove_variant(run_id, sample, sample_id, var_id, var_classification):
#     """Delete a variant. Return JSON if AJAX, else flash+redirect."""
#     # 1) Locate the variant in the appropriate table
#     origin_table = None
#     variant = None

#     if var_classification == "Therapeutic":
#         origin_table = "TherapeuticTable"
#         variant = TherapeuticTable.query.get(var_id)
#     elif var_classification == "Other":
#         origin_table = "OtherVariantsTable"
#         variant = OtherVariantsTable.query.get(var_id)
#     elif var_classification == "Rare":
#         origin_table = "RareVariantsTable"
#         variant = RareVariantsTable.query.get(var_id)

#     msg = "No s'ha trobat la variant."
#     if variant:
#         hgvsg = variant.hgvsg or var_id

#         # --- your VersionControl bookkeeping ---
#         action_dict = {
#             "origin_table": origin_table,
#             "origin_action": "delete",
#             "redo": True,
#             "target_table": None,
#             "target_action": None,
#             # serialize the deleted record
#             "action_json": json.dumps(variant, cls=AlchemyEncoder),
#             "msg": f"Variant {hgvsg} eliminada"
#         }
#         action_str = json.dumps(action_dict)
#         action_name = f"Mostra: {sample} variant {hgvsg} eliminada"
#         dt = datetime.now().strftime("%d/%m/%y-%H:%M:%S")
#         vc = VersionControl(
#             User_id=7,  # <-- you should pull the real current_user.id here
#             Action_id=generate_key(16),
#             Action_name=action_name,
#             Action_json=action_str,
#             Modified_on=dt
#         )
#         db.session.add(vc)
#         # --- end VersionControl ---

#         # now delete the variant itself
#         db.session.delete(variant)
#         db.session.commit()

#         msg = f"S'ha eliminat correctament la variant {hgvsg}"
#         flash(msg, "success")

#     # 2) If this was an XHR (AJAX) request, return JSON directly
#     if request.headers.get("X-Requested-With") == "XMLHttpRequest":
#         return jsonify({
#             "status": "ok" if variant else "error",
#             "message": msg,
#             "deleted_var_id": var_id
#         })

#     # 3) Otherwise, fall back to your original redirect+flash behavior
#     sample_info = SampleTable.query.filter_by(
#         lab_id=sample, run_id=run_id
#     ).first()
#     vcf_folder = sample_info.sample_db_dir.replace(
#         "REPORT_FOLDER", "VCF_FOLDER/IGV_SNAPSHOTS"
#     )
#     return redirect(
#         url_for(
#             "show_sample_details",
#             run_id=run_id,
#             sample=sample,
#             sample_id=sample_id,
#             vcf_folder=vcf_folder,
#             active="Therapeutic",
#         )
#     )


# @app.route(
#     "/remove_variant/<run_id>/<sample>/<sample_id>/<var_id>/<var_classification>",
#     methods=["GET", "POST"],
# )
# #@login_required
# def remove_variant(run_id, sample, sample_id, var_id, var_classification):

#     origin_table = None
#     target_table = None
#     if var_classification == "Therapeutic":
#         origin_table = "TherapeuticTable"
#         variant = TherapeuticTable.query.filter_by(id=var_id).first()
#     if var_classification == "Other":
#         origin_table = "OtherVariantsTable"
#         variant = OtherVariantsTable.query.filter_by(id=var_id).first()
#     if var_classification == "Rare":
#         origin_table = "RareVariantsTable"
#         variant = RareVariantsTable.query.filter_by(id=var_id).first()

#     if variant:
#         db.session.delete(variant)
#         db.session.commit()

#         # instantiate a VersionControl object and commit the change
#         action_dict = {
#             "origin_table": origin_table,
#             "origin_action": "delete",
#             "redo": True,
#             "target_table": None,
#             "target_action": None,
#             "action_json": json.dumps(variant, cls=AlchemyEncoder),
#             "msg": " Variant " + variant.hgvsg + " eliminada",
#         }
#         action_str = json.dumps(action_dict)
#         action_name = f"Mostra: {sample} variant {variant.hgvsg} eliminada"
#         now = datetime.now()
#         dt = now.strftime("%d/%m/%y-%H:%M:%S")
#         vc = VersionControl(
#             User_id=7,
#             Action_id=generate_key(16),
#             Action_name=action_name,
#             Action_json=action_str,
#             Modified_on=dt,
#         )
#         db.session.add(vc)
#         db.session.commit()

#         variant_out = ""
#         if variant.hgvsg:
#             variant_out = variant.hgvsg
#             msg = ("S'ha eliminat correctament la variant {}").format(variant.hgvsg)
#             flash(msg, "success")

#     sample_info = (
#         SampleTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).first()
#     )
#     vcf_folder = sample_info.sample_db_dir.replace(
#         "REPORT_FOLDER", "VCF_FOLDER/IGV_SNAPSHOTS"
#     )

#     return redirect(
#         url_for(
#             "show_sample_details",
#             run_id=run_id,
#             sample=sample,
#             sample_id=sample_id,
#             vcf_folder=vcf_folder,
#             active="Therapeutic",
#         )
#     )

def myvariant_request(hgvsg: str) -> dict:
    """ """
    myvariant_url = f"https://myvariant.info/v1/variant/{hgvsg}"
    response_dict ={}
    try:
        response = requests.get(myvariant_url)
        response_dict = response.json()
    except:
        pass
    return response_dict


@app.route("/show_therapeutic_details/<sample>/<run_id>/<entry_id>/<var_classification>")
#@login_required
def show_therapeutic_details(sample, run_id, entry_id, var_classification):

    sample_info = SampleTable.query.filter_by(lab_id=sample, run_id=run_id).first()

    if var_classification == "Therapeutic":
        variant = TherapeuticTable.query.filter_by(id=entry_id).first()
    if var_classification == "Other":
        variant = OtherVariantsTable.query.filter_by(id=entry_id).first()
    if var_classification == "Rare":
        variant = RareVariantsTable.query.filter_by(id=entry_id).first()

    hgvsg = variant.hgvsg
    bai = ("{}{}").format(sample_info.bam, ".bai")
    variant_dict = json.loads(variant.var_json)
    variant_dict["INFO"]["CSQ"][0]["Consequence"] = (
        variant_dict["INFO"]["CSQ"][0]["Consequence"]
        .replace("_", " ")
        .capitalize()
        .replace("&", ", ")
    )
    variant_dict["INFO"]["CSQ"][0]["BIOTYPE"] = (
        variant_dict["INFO"]["CSQ"][0]["BIOTYPE"]
        .replace("_", " ")
        .capitalize()
        .replace("&", ", ")
    )
    variant_dict["INFO"]["CSQ"][0]["Existing_variation"] = variant_dict["INFO"]["CSQ"][
        0
    ]["Existing_variation"].replace("&", ", ")
    var_name = (
        variant_dict["CHROM"]
        + ":"
        + variant_dict["POS"]
        + variant_dict["REF"]
        + ">"
        + variant_dict["ALT"]
    )
    locus = variant_dict["CHROM"] + ":" + variant_dict["POS"]
    civic_items = []

    myvariant_info =  myvariant_request(variant_dict["INFO"]["CSQ"][0]["HGVSg"])

    if "CIVIC" in variant_dict["INFO"]:
        for item in variant_dict["INFO"]["CIVIC"]:
            if item not in civic_items:
                if 'EV_SIGNIFICANCE' in item:
                    if item['EV_SIGNIFICANCE'] == "Sensitivity/Response":
                        civic_items.append(item)

        for item in variant_dict["INFO"]["CIVIC"]:
            if item not in civic_items:
                if 'EV_SIGNIFICANCE' in item:
                    if item['EV_SIGNIFICANCE'] == "Resistance":
                        civic_items.append(item)

        for item in variant_dict["INFO"]["CIVIC"]:
            if item not in civic_items:
                if 'EV_SIGNIFICANCE' in item:
                    civic_items.append(item)


    variant_dict["INFO"]["CIVIC"] = civic_items

    return render_template(
        "show_therapeutic_details.html",
        bai=bai,
        sample_info=sample_info,
        locus=locus,
        var_name=var_name,
        title=hgvsg,
        variant_dict=variant_dict,
        myvariant_info=myvariant_info
    )


def get_genes_from_panel(panel):
    """ """
    gene_panel_version = ""
    url_api_panel = f"{api_gene_panels}/api/gene_panels/{panel}/latest_version"
    response = requests.get(url_api_panel)
    if response.status_code == 200:
        response_json = response.json()
        gene_panel_version = int(response_json["panel_version"])

    url_api_panel = f"{api_gene_panels}/api/gene_panels/{panel}/v{gene_panel_version}"
    response = requests.get(url_api_panel)
    genes = []
    if response.status_code == 200:
        response_json = response.json()
        genes = response_json["Genes"]
        clean_genes = []
        for gene in genes:
            if gene == "":
                continue
            clean_genes.append(gene)
        genes = clean_genes
    return genes

def get_subpanels_from_panel(panel):
    """ """
    url_api_panel = f"{api_gene_panels}/api/gene_panels/{panel}/latest_version"
    response = requests.get(url_api_panel)
    if response.status_code == 200:
        response_json = response.json()
        gene_panel_version = int(response_json["panel_version"])

    url_api_panel = f"{api_gene_panels}/api/gene_panels/{panel}/v{gene_panel_version}"
    response = requests.get(url_api_panel)
    if response.status_code == 200:
        response_json = response.json()
        subpanels = response_json["subpanels"]
        return subpanels

@app.route('/new_virtual_panel/<panel>')
def new_virtual_panel(panel):
    panel_genes = get_genes_from_panel(panel)
    url_api_panel = f"{api_gene_panels}/api/gene_panels/{panel}/latest_version"
    response = requests.get(url_api_panel)
    panel_version = "."

    subpanels = get_subpanels_from_panel(panel)  # <- list of existing virtual panels

    if response.status_code == 200:
        response_json = response.json()
        panel_version = int(response_json["panel_version"])

    return render_template(
        "virtual_panels.html",
        panel=panel,
        panel_genes=panel_genes,
        panel_version=panel_version,
        subpanels=subpanels,
        title="Nou panell virtual"
    )

@app.route('/virtual_panels/<panel>')
def list_virtual_panels(panel):
    subpanels = get_subpanels_from_panel(panel)
    return render_template(
        "virtual_panels_list.html",
        panel=panel,
        subpanels=subpanels,
        title=f"Panells virtuals - {panel}"
    )



@app.route('/save_virtual_panel', methods=['POST'])
def save_virtual_panel():
    """ """
    data = request.get_json()
    parent_panel = data["parent_panel"]
    panel_version = data["panel_version"]
    name = data["virtual_panel_name"]
    genes = data["genes"]

    old_virtual_panel_name = ""
    if "old_virtual_panel_name" in data:
        old_virtual_panel_name = data["old_virtual_panel_name"]

    if old_virtual_panel_name:
        # Update data from VirtualPanel mongo collection
        # virtual_panel = VirtualPanel.objects(name=old_virtual_panel_name).first()
        # virtual_panel.update(set__name=name)
        # virtual_panel.update(set__parent_panel=parent_panel)
        # virtual_panel.update(set__genes = genes)
        # virtual_panel.update(set__hpo_terms = hpo_terms)Ç
        
        
        # Now update data from the Gene Panels API (external to COMPENDIUM)
        subpanel_data = {
            'old_subpanel_name': old_virtual_panel_name,
            'new_subpanel_name': name,
            'panel_version': panel_version,
            'genes': genes,
        }
        url_api_panel = f"{api_gene_panels}/api/gene_panels/update_subpanel/{parent_panel}/{old_virtual_panel_name}"
        
        try:
            response = requests.post(url_api_panel, json=subpanel_data)
            if response.status_code == 200:
                msg = f"S'ha actualitzat el panell virtual {name}"
            else:
                msg = f"error {name}"
                return make_response(jsonify(msg), 400)
        except Exception as e:
            msg = "error"
        return make_response(jsonify(msg), 200)

    else:
        # virtual_panel = VirtualPanel.objects(name=name).first()
        # if not virtual_panel:
        #     new_virtual_panel = VirtualPanel(
        #         name=name,
        #         parent_panel=parent_panel,
        #         panel_version=panel_version,
        #         genes=genes,
        #         hpo_terms=hpo_terms
        #     )
        #     new_virtual_panel.save()

        # Prepare data for the subpanel addition
        subpanel_data = {
            'subpanel_name': name,
            'panel_version': panel_version,
            'genes': genes,
        }

        url_api_panel = f"{api_gene_panels}/api/gene_panels/add_subpanel/{parent_panel}"
        try:
            response = requests.post(url_api_panel, json=subpanel_data)
            if response.status_code == 201:
                msg = f"S'ha creat el panell virtual {name}"
            else:
                msg = f"S'ha actualitzat el panell virtual {name}"

        except Exception as e:
            # Log or handle exception during the API call
            pass  # Add logic to handle or log the exception

        return make_response(jsonify(msg), 200)


@app.route("/download_report/<run_id>/<sample>")
#@login_required
def download_report(run_id, sample):
    sample_info = SampleTable.query.filter_by(run_id=run_id, lab_id=sample).first()
    uploads = ""
    try:
        if not sample_info.report_pdf.endswith(".pdf"):
            sample_info.report_pdf = sample_info.report_pdf + ".pdf"

        if sample_info.latest_short_report_pdf:
            if not sample_info.latest_short_report_pdf.endswith(".pdf"):
                sample_info.latest_short_report_pdf = sample_info.latest_short_report_pdf + ".pdf"
            report_file = os.path.basename(sample_info.latest_short_report_pdf)
            uploads = os.path.dirname(sample_info.latest_short_report_pdf)
        else:
            report_file = os.path.basename(sample_info.report_pdf)
            uploads = os.path.dirname(sample_info.latest_short_report_pdf)

        if not os.path.isfile(os.path.join(uploads, report_file)):
            msg = f"Informe no disponible per a la mostra {sample}"
            flash(msg, "warning")
            return redirect(url_for("show_run_details", run_id=run_id))

    except:
        if not os.path.isfile(os.path.join(uploads, report_file)):
            msg = f"Informe no disponible per a la mostra {sample}"
            flash(msg, "warning")
            return redirect(url_for("show_run_details", run_id=run_id))

    return send_from_directory(directory=uploads, path=report_file, as_attachment=True)


def generate_new_report(
    sample: str, sample_id: str, run_id: str, tumor_origin:str, substitute_report: bool, lowqual_sample: bool,
    no_enac: bool, comments: str, repeat_notes: str, genes, panel_version
):
    """ """

    env = Environment(loader=FileSystemLoader(app.config["SOMATIC_REPORT_TEMPLATES"]))
    template = env.get_template("report.html")

    sample_info = (
        SampleTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).first()
    )

    remove_filter_tags = [
        "base_qual",
        "orientation",
        "strand_bias",
        "weak_evidence",
        "panel_of_normals",
    ]
    remove_filter_tags_set = set(remove_filter_tags)

    def _extract_filter_tag(variant_dict):
        if not isinstance(variant_dict, dict):
            return None

        info = variant_dict.get("INFO", {})
        raw_filter = variant_dict.get("FILTER")
        if raw_filter is None and isinstance(info, dict):
            for key in ("FILTER", "filter", "FILTERS", "filters"):
                if key in info:
                    raw_filter = info.get(key)
                    break

        if raw_filter is None:
            return None

        if isinstance(raw_filter, (list, tuple, set)):
            parts = [str(v).strip() for v in raw_filter if str(v).strip()]
            return ";".join(parts) if parts else None

        if isinstance(raw_filter, dict):
            parts = []
            for key, value in raw_filter.items():
                if isinstance(value, bool):
                    if value:
                        parts.append(str(key))
                elif value is None or str(value).strip() == "":
                    parts.append(str(key))
                else:
                    parts.append(f"{key}:{value}")
            return ";".join(parts) if parts else None

        value = str(raw_filter).strip()
        if value in ("", ".", "-", "None", "null"):
            return None
        return value

    def _has_removed_filter_tag(filter_tag_value):
        if not filter_tag_value:
            return False

        raw_parts = re.split(r"[;,\|]", str(filter_tag_value))
        for raw_part in raw_parts:
            normalized = str(raw_part).strip().lower()
            if not normalized:
                continue
            normalized = normalized.split(":", 1)[0].strip()
            if normalized in remove_filter_tags_set:
                return True
        return False

    def _prepare_and_filter_report_variants(variants):
        out = []
        for variant in variants:
            try:
                variant_dict = json.loads(variant.var_json)
            except:
                variant.refseq = variant.enst_id
                out.append(variant)
                continue

            try:
                variant.refseq = variant_dict["INFO"]["REFSEQ_ANALYSIS_ISOFORM"]
            except:
                variant.refseq = variant.enst_id

            filter_tag = _extract_filter_tag(variant_dict)
            if _has_removed_filter_tag(filter_tag):
                continue

            out.append(variant)
        return out

    tumor_origin = sample_info.tumor_origin
    
    rare_variants = (
        RareVariantsTable.query.filter_by(lab_id=sample)
        .filter_by(run_id=run_id)
        .filter_by(blacklist="no")
        .distinct()
        .all()
    )
    high_impact_variants = (
        OtherVariantsTable.query.filter_by(lab_id=sample)
        .filter_by(run_id=run_id)
        .filter_by(blacklist="no")
        .distinct()
        .all()
    )
    actionable_variants = (
        TherapeuticTable.query.filter_by(lab_id=sample)
        .filter_by(run_id=run_id)
        .filter_by(blacklist="no")
        .distinct()
        .all()
    )
    high_impact_variants = _prepare_and_filter_report_variants(high_impact_variants)
    actionable_variants = _prepare_and_filter_report_variants(actionable_variants)
    rare_variants = _prepare_and_filter_report_variants(rare_variants)

    lost_exons = (
        LostExonsTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
    )
    pipeline_details = PipelineDetails.query.filter_by(run_id=run_id).first()
    summary_qc = (
        SummaryQcTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).first()
    )
    filtered_cnas = []
    cnas = AllCnas.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
    for cna in cnas:
        tmp_cna_genes = cna.genes.split(",")
        genes_list = []
        for item in tmp_cna_genes:
            tmp_item = item.split("_")
            if len(tmp_item) > 1:
                gene = tmp_item[0]
            else:
                gene = item
            if gene not in genes_list:
                genes_list.append(gene)
        cna.genes = ','.join(genes_list)
        filtered_cnas.append(cna)

    petition_dict = {
        "Petition_date" : "",
        "Date_original_biopsy": ""
    }

    petition_info = Petition.query.filter_by(AP_code=sample_info.ext1_id).first()
    if petition_info:
        print(petition_info.Petition_date)
        tmp_date = petition_info.Petition_date.split("-")
        if len(tmp_date) == 1:
            tmp_date = petition_info.Petition_date.split("/")

        petition_dict["Petition_date"] = f"{tmp_date[0]}/{tmp_date[1]}/{tmp_date[2]}"
        petition_dict["Date_original_biopsy"]  = petition_info.Petition_date

        tmp_date = petition_info.Date_original_biopsy.split("-")
        if len(tmp_date) == 1:
            tmp_date = petition_info.Date_original_biopsy.split("/")

        petition_dict["Date_original_biopsy"] = f"{tmp_date[2]}/{tmp_date[1]}/{tmp_date[0]}"

    if not tumor_origin:
        tumor_origin = "PULMÓ"

    cna_list = []
    seen_cnas = set()
    for cna in cnas:
        cna_str = cna.to_string()
        if cna_str in seen_cnas:
            continue
        seen_cnas.add(cna_str)
        cna_list.append(cna)

    tier_variants = {"tier_I": [], "tier_II": [], "tier_III": [], "no_tier": []}

    low_concentration = False
    if sample_info.concentration:
        if "<10ng/ul" in sample_info.concentration:
            low_concentration = True

    seen_vars = set()
    for var in actionable_variants:
        var_str = var.to_string()

        short_hgvsp =  convert_long_to_short(var.hgvsp)
        var.short_hgvsp = short_hgvsp
        if var_str in seen_vars:
            continue
        seen_vars.add(var_str)
        if var.removed == "yes":
            continue

        if var.tier_catsalut != "None":
            if var.tier_catsalut == "1":
                tier_variants["tier_I"].append(var)
            if var.tier_catsalut == "2":
                tier_variants["tier_II"].append(var)
            if var.tier_catsalut == "3":
                tier_variants["tier_III"].append(var)
        else:
            tier_variants["no_tier"].append(var)

    for var in high_impact_variants:
        var_str = var.to_string()
        if var.hgvsp != ".":
            short_hgvsp =  convert_long_to_short(var.hgvsp)
            var.short_hgvsp = short_hgvsp

        if var.removed == "yes":
            continue

        if var_str in seen_vars:
            continue
        seen_vars.add(var_str)
        if var.tier_catsalut != "None":
            if var.tier_catsalut == "1":
                tier_variants["tier_I"].append(var)
            if var.tier_catsalut == "2":
                tier_variants["tier_II"].append(var)
            if var.tier_catsalut == "3":
                tier_variants["tier_III"].append(var)
        else:
            tier_variants["no_tier"].append(var)

    rare_variants2 = []
    for var in rare_variants:
        if var.max_af != ".":
            if float(var.max_af) > 0.001:
                continue

        var_str = var.to_string()
        if var_str in seen_vars:
            continue
        seen_vars.add(var_str)
        if var.hgvsg == ".":
            continue
        else:
            rare_variants2.append(var)
    rare_variants = rare_variants2

    tier_list = []
    for tier in tier_variants:
        tier_list.append(tier_variants[tier])

    tier_list = (
        tier_variants["tier_I"]
        + tier_variants["tier_II"]
        + tier_variants["tier_III"]
        + tier_variants["no_tier"]
    )
    relevant_variants = tier_list

    summary_qc_dict = json.loads(summary_qc.summary_json)
    fastp_dict = json.loads(summary_qc.fastp_json)

    now = datetime.now()

    report_date = sample_info.last_report_emission_date

    substituted_date = ""
    if substitute_report:
        substituted_date = sample_info.last_report_emission_date
        if not substituted_date:
            substituted_date = report_date
        report_date = now.strftime("%d/%m/%Y")

    else:
        if not sample_info.last_report_emission_date:
            report_date = now.strftime("%d/%m/%Y")
    lowqual_msg = ""
    if lowqual_sample:
        lowqual_msg = "La mostra no compleix els criteris de qualitat establerts"


    if sample_info.date_original_biopsy:
        sample_info.date_original_biopsy = sample_info.date_original_biopsy.replace(
            "00:00:00", ""
        )
        sample_info.date_original_biopsy = sample_info.date_original_biopsy.replace(
            "-", "/"
        )

    lost_genes = ["BRAF", "EGFR", "FGFR1", "FGFR2", "FGFR3", "KRAS", 
        "MET", "ERBB2", "TP53", "NRAS", "ROS1", "ALK"]

    filtered_lost_exons = []
    for lost_exon in lost_exons:
        if lost_exon.gene in lost_genes:
            filtered_lost_exons.append(lost_exon)


    sample_info.last_report_emission_date = report_date
    latest_report_pdf_name = os.path.basename(sample_info.latest_report_pdf)
    # render template
    rendered = template.render(
        title="Somatic_report",
        tumor_origin=tumor_origin,
        rare_variants=rare_variants,
        actionable_variants=actionable_variants,
        sample_info=sample_info,
        relevant_variants=relevant_variants,
        tier_list=tier_list,
        petition_info=petition_dict,
        high_impact_variants=high_impact_variants,
        lost_exons=filtered_lost_exons,
        summary_qc_dict=summary_qc_dict,
        fastp_dict=fastp_dict,
        pipeline_details=pipeline_details,
        cnas=cna_list,
        is_substitute=substitute_report,
        lowqual_msg=lowqual_msg,
        substituted_date=substituted_date,
        latest_report_pdf_name=latest_report_pdf_name,
        report_date=report_date,
        low_concentration=low_concentration,
        no_enac=no_enac,
        comments=comments,
        repeat_notes=repeat_notes,
        genes=genes,
        panel_version=panel_version
    )

    now = datetime.now()
    dt = now.strftime("%d%m%y%H%M%S")
    new_report_name = f"{sample}.analitic.{dt}.pdf"

    report_folder = os.path.dirname(sample_info.latest_report_pdf)
    new_report_pdf = os.path.join(report_folder, new_report_name)

    HTML(string=rendered, base_url=app.config["SOMATIC_REPORT_IMG"]).write_pdf(
        new_report_pdf, stylesheets=[app.config["SOMATIC_REPORT_CSS"]]
    )

    # now for short report
    template = env.get_template("report_short.html")
    rendered_short = template.render(
        title="Somatic_report",
        tumor_origin=tumor_origin,
        rare_variants=rare_variants,
        actionable_variants=actionable_variants,
        sample_info=sample_info,
        relevant_variants=relevant_variants,
        tier_list=tier_list,
        high_impact_variants=high_impact_variants,
        petition_info=petition_dict,
        lost_exons=filtered_lost_exons,
        summary_qc_dict=summary_qc_dict,
        fastp_dict=fastp_dict,
        pipeline_details=pipeline_details,
        cnas=cna_list,
        is_substitute=substitute_report,
        lowqual_msg=lowqual_msg,
        substituted_date=substituted_date,
        latest_report_pdf_name=latest_report_pdf_name,
        report_date=report_date,
        low_concentration=low_concentration,
        no_enac=no_enac,
        comments=comments,
        repeat_notes=repeat_notes,
        genes=genes,
        panel_version=panel_version
    )

    new_report_name_short = f"{sample}.genetic.{dt}.pdf"
    report_folder = os.path.dirname(sample_info.latest_report_pdf)
    new_report_pdf2 = os.path.join(report_folder, new_report_name_short)
    HTML(string=rendered_short, base_url=app.config["SOMATIC_REPORT_IMG"]).write_pdf(
        new_report_pdf2, stylesheets=[app.config["SOMATIC_REPORT_CSS"]]
    )

    sample_info.latest_report_pdf = new_report_pdf

    sample_info.latest_short_report_pdf = new_report_pdf2
    sample_info.last_short_report_emission_date = report_date
    db.session.commit()

    action_dict = {
        "origin_table": None,
        "origin_action": "Create report",
        "redo": False,
        "target_table": None,
        "target_action": None,
        "action_json": None,
        "msg": " Report generat per la mostra  {} ".format(sample),
    }
    action_str = json.dumps(action_dict)
    action_name = ("{}: Nou informe genètic").format(sample)
    now = datetime.now()
    dt = now.strftime("%d/%m/%y-%H:%M:%S")
    vc = VersionControl(
        User_id=7,
        Action_id=generate_key(16),
        Action_name=action_name,
        Action_json=action_str,
        Modified_on=dt,
    )
    db.session.add(vc)
    db.session.commit()

    message = {
        "message_text": f"S'ha generat correctament l'informe per la mostra {sample}",
    }
    return message


@app.route("/create_somatic_report", methods=["POST", "GET"])
#@login_required
def create_somatic_report():

    if request.method == "POST":
        run_id = request.form["run_id"]
        sample = request.form["sample"]
        sample_id = request.form["sample_id"]
        comments = request.form["comments"]
        repeat_notes = request.form["repeat_notes"]
        tumor_origin = request.form["tumor_origin"]
        gene_panel = request.form["gene_panel"]
        
        lowqual_sample = False
        if "lowqual_sample" in request.form:
            if request.form["lowqual_sample"]:
                lowqual_sample = True
        no_enac = False
        if "no_enac" in request.form:
            if request.form["no_enac"]:
                no_enac = True
        substitute_report = False
        if request.form.get("substitute_report"):
            substitute_report = True

        genes_list = get_genes_from_panel(gene_panel)
        genes = ','.join(genes_list)

        panel_version = "1"
        if gene_panel == "GenOncology-Dx_1.5":
            panel_version = "1.5"
        panel_version = "1"
        if gene_panel == "GenOncology-Dx_1.6":
            panel_version = "1.6"

        message = generate_new_report(sample, sample_id, run_id, tumor_origin,
            substitute_report, lowqual_sample, no_enac, comments, repeat_notes, genes, panel_version)

        return make_response(jsonify(message), 200)


@app.route("/create_all_somatic_reports", methods=["POST"])
#@login_required
def create_all_somatic_reports():
    """ """
    if request.method == "POST":
        run_id = request.form["run_id"]
        substitute_report = False
        lowqual_sample = False
        samples = SampleTable.query.filter_by(run_id=run_id).all()
        comments = ""
        repeat_notes = ""

        for sample in samples:
            generate_new_report(sample.lab_id, sample.lab_id, run_id, sample.tumor_origin, 
                substitute_report, lowqual_sample, no_enac, comments, repeat_notes)
    return redirect(url_for("show_run_details", run_id=run_id))
    message = {
        "message_text": f"S'han generat correctament els informes",
    }
    return make_response(jsonify(message), 200)


ALLOWED_FIELDS = {'chromosome', 'start', 'end', 'genes', 'svtype', 'ratio', 'qual', 'cn'}
@app.post('/edit_cnas')
def edit_cnas():
    data = request.get_json(silent=True) or request.form.to_dict()
    cna_id = data.get('id')
    try:
        cna_id = int(cna_id)
    except (TypeError, ValueError):
        abort(400, description='Invalid or missing id')

    cna = AllCnas.query.get_or_404(cna_id)

    # TODO: add authorization checks if needed (e.g., current_user.id == cna.user_id)

    changed = False
    for field in ALLOWED_FIELDS:
        if field in data:
            setattr(cna, field, str(data[field]).strip() if data[field] is not None else '')
            changed = True

    if not changed:
        return jsonify({'message': 'No changes'}), 400

    db.session.commit()
    return jsonify({**{f: getattr(cna, f) for f in ALLOWED_FIELDS}, 'id': cna.id}), 200


@app.post('/remove_cnas')
def remove_cnas():
    data = request.get_json(silent=True) or request.form.to_dict()
    cna_id = data.get('id')
    try:
        cna_id = int(cna_id)
    except (TypeError, ValueError):
        abort(400, description='Invalid or missing id')

    cna = AllCnas.query.get_or_404(cna_id)

    # TODO: add authorization checks

    db.session.delete(cna)
    db.session.commit()
    return jsonify({'deleted': True, 'id': cna_id}), 200


@app.route('/get_all_analysis_samples', methods=['GET'])
def get_all_analysis_samples():
    samples = SampleTable.query.all()

    def to_dict(s: SampleTable) -> dict:
        return {
            "id": s.id,
            "user_id": s.user_id,
            "lab_id": s.lab_id,
            "ext1_id": s.ext1_id,
            "ext2_id": s.ext2_id,
            "ext3_id": s.ext3_id,
            "run_id": s.run_id,
            "petition_id": s.petition_id,
            "extraction_date": s.extraction_date,
            "date_original_biopsy": s.date_original_biopsy,
            "concentration": s.concentration,
            "analysis_date": s.analysis_date,
            "tumour_purity": s.tumour_purity,
            "sex": s.sex,
            "diagnosis": s.diagnosis,
            "physician_name": s.physician_name,
            "medical_center": s.medical_center,
            "medical_address": s.medical_address,
            "sample_type": s.sample_type,
            "panel": s.panel,
            "subpanel": s.subpanel,
            "roi_bed": s.roi_bed,
            "software": s.software,
            "software_version": s.software_version,
            "bam": s.bam,
            "merged_vcf": s.merged_vcf,
            "report_pdf": s.report_pdf,
            "latest_report_pdf": s.latest_report_pdf,
            "last_report_emission_date": s.last_report_emission_date,
            "report_db": s.report_db,
            "sample_db_dir": s.sample_db_dir,
            "cnv_json": s.cnv_json,
            "latest_short_report_pdf": s.latest_short_report_pdf,
            "last_short_report_emission_date": s.last_short_report_emission_date,
            "petition_date": s.petition_date,
            "tumor_origin": s.tumor_origin,
            "service": s.service,
            "sample_block": s.sample_block,
            "Sex": s.Sex,
            "Age": s.Age,
            "modulab_id": s.modulab_id,
            "report_changes": s.report_changes,
            "virtual_panel": s.virtual_panel,
        }

    return jsonify([to_dict(s) for s in samples]), 200


from sqlalchemy import or_

def _is_missing(v) -> bool:
    # treat None, "", "None", "null" as missing
    if v is None:
        return True
    s = str(v).strip()
    return s == "" or s.lower() in {"none", "null", "nan"}


@app.route("/backfill_sample_tumor_origin_from_petitions")
def backfill_sample_tumor_origin_from_petitions():
    samples = SampleTable.query.all()
    tumors = []
    petitions_id = []

    for sample in samples:
        # if tumor_origin missing, try to fetch from Petition using petition_id
        if not sample.tumor_origin and sample.petition_id:

            petition = Petition.query.filter_by(AP_code=sample.lab_id).first()
            if not petition:
                continue
            if petition and petition.Tumour_origin:
                sample.tumor_origin = petition.Tumour_origin
                db.session.add(sample)

        tumors.append({sample.lab_id: sample.tumor_origin})

    db.session.commit()
    return jsonify(tumors), 200
