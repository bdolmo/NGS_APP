from app import app, db
import os
import binascii
import requests
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
from collections import defaultdict
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
)
from sqlalchemy.ext.declarative import declarative_base, DeclarativeMeta
from sqlalchemy.orm import sessionmaker
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
    Petition
)
from app.plots import var_location_pie, cnv_plot, basequal_plot, adapters_plot, snv_plot, vaf_plot


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

    for s in run_samples:
        s.is_report_ready = True
        if not os.path.isfile(s.latest_report_pdf):
            s.is_report_ready = False

    return render_template(
        "show_run_details.html",
        title=run_id,
        run_samples=run_samples,
        run_dict=run_dict,
    )


@app.route('/update_patient_info', methods=["POST"])
@login_required
def update_patient_info():
    if request.method == "POST":
        data = request.get_json()
        run_id = data["run_id"]
        old_lab_id = data["old_lab_id"]
        old_ext1_id = data["old_ext1_id"]
        lab_id = data["lab_id"]
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

        # change to YYYY-MM-DD
        tmp_date = biopsy_date.split("/")
        if len(tmp_date) == 3:
            biopsy_date = tmp_date[1]+"-"+tmp_date[0]+"-"+tmp_date[2]

        # change to YYYY-MM-DD
        tmp_date = recieved_date.split("/")
        if len(tmp_date) == 3:
            recieved_date = tmp_date[1]+"-"+tmp_date[0]+"-"+tmp_date[2]

        sample = SampleTable.query.filter_by(lab_id=old_lab_id, run_id=run_id).first()
        if sample:
            sample.lab_id = lab_id
            sample.ext1_id = ext1_id
            sample.ext2_id = ext2_id
            sample.ext3_id = ext3_id
            sample.sample_type = sample_type
            sample.medical_center = hospital
            sample.tumour_purity = tumor_pct
            sample.physician_name = physician_name
            sample.tumor_origin = tumor_origin
            db.session.commit()
        
        petition = (
            Petition.query.filter_by(AP_code=old_ext1_id).first()
        )
        if petition:
            petition.AP_code = ext1_id
            petition.HC_code = ext2_id
            petition.CIP_code = ext3_id
            petition.Tumour_pct = tumor_pct
            petition.Medical_doctor = physician_name
            petition.Tumour_origin = tumor_origin
            petition.Medical_indication = tumor_origin
            if biopsy_date:
                petition.Date_original_biopsy = biopsy_date
            if recieved_date:

                petition.Petition_date = recieved_date
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
    """ """
    uploads = os.path.join(app.config["STATIC_URL_PATH"], run_id, "GenOncology-Dx")
    summary_qc_xlsx = "GenOncology-Dx_qc.xlsx"
    test_path = os.path.join(uploads, summary_qc_xlsx)
    print(test_path)
    if not os.path.isfile(test_path):
        summary_qc_xlsx = f"{run_id}_qc.xlsx"
        test_path = os.path.join(uploads, summary_qc_xlsx)
    if not os.path.isfile(test_path):
        summary_qc_xlsx = f"{run_id}_qc.xlsx"
        uploads = os.path.join(app.config["STATIC_URL_PATH"], run_id)

    print(uploads, summary_qc_xlsx)
    return send_from_directory(
        directory=uploads, path=summary_qc_xlsx, as_attachment=True
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
    uploads = os.path.join(
        app.config["STATIC_URL_PATH"], run_id + "/" + sample + "/VCF_FOLDER/"
    )
    vcf_file = sample + ".merged.variants.vcf"
    lancet_vcf_file = f"{sample}.mutect2.lancet.vcf"
    vcf_file_path = os.path.join(uploads, vcf_file)
    if not os.path.isfile(vcf_file_path):
        uploads = os.path.join(
            app.config["STATIC_URL_PATH"],
            run_id,
            "GenOncology-Dx",
            sample,
            "VCF_FOLDER",
        )

    lancet_vcf_path = os.path.join(uploads, lancet_vcf_file)
    if os.path.isfile(lancet_vcf_path):
        vcf_file = lancet_vcf_file

    return send_from_directory(directory=uploads, path=vcf_file, as_attachment=True)


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
    if sample_info.ext1_id == ".":
        sample_info.ext1_id = sample_info.lab_id

    petition_info = (
        Petition.query.filter_by(AP_code=sample_info.ext1_id).first()
    )
    if not petition_info:
        petition_info = (
            Petition.query.filter_by(AP_code=sample_info.lab_id).first()
        )
    summary_qc = (
        SummaryQcTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).first()
    )
    pipeline_details = PipelineDetails.query.filter_by(run_id=run_id).first()
    therapeutic_variants = (
        TherapeuticTable.query.filter_by(lab_id=sample)
        .filter_by(run_id=run_id)
        .distinct()
        .all()
    )
    other_variants = (
        OtherVariantsTable.query.filter_by(lab_id=sample)
        .filter_by(run_id=run_id)
        .distinct()
        .all()
    )
    rare_variants = (
        RareVariantsTable.query.filter_by(lab_id=sample)
        .filter_by(run_id=run_id)
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

    tmp_samples = SampleTable.query.all()
    unique_samples = set()
    for s in tmp_samples:
        if "test" in s.lab_id:
            continue
        if "Undetermined" in s.lab_id:
            continue
        unique_samples.add(s.lab_id)
    n_samples = len(unique_samples)

    for var in therapeutic_variants:
        n_var = TherapeuticTable.query.filter_by(gene=var.gene, hgvsg=var.hgvsg).count()
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
        n_var = OtherVariantsTable.query.filter_by(gene=var.gene, hgvsg=var.hgvsg).count()
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

    rare_variants2 = []
    for var in rare_variants:
        if var.hgvsg == ".":
            continue
        else:
            rare_variants2.append(var)
    rare_variants = rare_variants2

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
        if len(num_id_dict.keys()) == 5:
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

    read1_basequal_dict = fastp_dict["read1_before_filtering"]["quality_curves"]
    plot_read1 = basequal_plot(read1_basequal_dict)

    read2_basequal_dict = fastp_dict["read2_before_filtering"]["quality_curves"]
    plot_read2 = basequal_plot(read2_basequal_dict)

    cnv_plotdata = json.loads(sample_info.cnv_json)
    plot_cnv = ""
    pie_plot = ""
    bar_plot = ""
    plot_cnv = cnv_plot(cnv_plotdata)
    pie_plot, bar_plot = var_location_pie(rare_variants)
    read1_adapters_dict = fastp_dict["adapter_cutting"]["read1_adapter_counts"]
    read2_adapters_dict = fastp_dict["adapter_cutting"]["read2_adapter_counts"]
    r1_adapters_plot = adapters_plot(read1_adapters_dict, read2_adapters_dict)

    if petition_info:
        tmp_date =petition_info.Date_original_biopsy.replace("-", "/").replace(" 00:00:00", "")
        tmp_date_list = tmp_date.split("/")
        newdate = f"{tmp_date_list[2]}/{tmp_date_list[1]}/{tmp_date_list[0]}"
        petition_info.Date_original_biopsy = newdate

        try:
            tmp_date =petition_info.Petition_date.replace("-", "/").replace(" 00:00:00", "")
        except:
            pass
        else:
            tmp_date_list = tmp_date.split("/")
            newdate = f"{tmp_date_list[2]}/{tmp_date_list[1]}/{tmp_date_list[0]}"
            petition_info.Petition_date = newdate

    return render_template(
        "show_sample_details.html",
        title=sample,
        active=active,
        petition_info=petition_info,
        sample_info=sample_info,
        sample_variants=sample_variants,
        summary_qc_dict=summary_qc_dict,
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
    new_active = "Therapeutic"
    if request.method == "POST":
        therapies = ""
        diseases = ""
        new_classification = ""
        if request.form.get("therapies"):
            therapies = request.form["therapies"]
        if request.form.get("diseases"):
            diseases = request.form["diseases"]
        if request.form.get("blacklist_check"):
            variant.blacklist = "yes"
        else:
            variant.blacklist = "no"
        db.session.commit()

        if variant.blacklist == "yes":
            v = (
                Variants.query.filter_by(hgvsg=variant.hgvsg)
                .filter_by(hgvsc=variant.hgvsc)
                .filter_by(hgvsp=variant.hgvsp)
                .first()
            )
            if v:
                v.blacklist = "yes"
                db.session.commit()

        if request.form.get("variant_category"):

            new_classification = request.form["variant_category"]
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
#@login_required
def remove_variant(run_id, sample, sample_id, var_id, var_classification):

    origin_table = None
    target_table = None
    if var_classification == "Therapeutic":
        origin_table = "TherapeuticTable"
        variant = TherapeuticTable.query.filter_by(id=var_id).first()
    if var_classification == "Other":
        origin_table = "OtherVariantsTable"
        variant = OtherVariantsTable.query.filter_by(id=var_id).first()
    if var_classification == "Rare":
        origin_table = "RareVariantsTable"
        variant = RareVariantsTable.query.filter_by(id=var_id).first()

    if variant:
        db.session.delete(variant)
        db.session.commit()

        # instantiate a VersionControl object and commit the change
        action_dict = {
            "origin_table": origin_table,
            "origin_action": "delete",
            "redo": True,
            "target_table": None,
            "target_action": None,
            "action_json": json.dumps(variant, cls=AlchemyEncoder),
            "msg": " Variant " + variant.hgvsg + " eliminada",
        }
        action_str = json.dumps(action_dict)
        action_name = f"Mostra: {sample} variant {variant.hgvsg} eliminada"
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

        variant_out = ""
        if variant.hgvsg:
            variant_out = variant.hgvsg
            msg = ("S'ha eliminat correctament la variant {}").format(variant.hgvsg)
            flash(msg, "success")

    sample_info = (
        SampleTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).first()
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
            vcf_folder=vcf_folder,
            active="Therapeutic",
        )
    )

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


@app.route("/download_report/<run_id>/<sample>")
#@login_required
def download_report(run_id, sample):
    sample_info = SampleTable.query.filter_by(run_id=run_id, lab_id=sample).first()

    if not sample_info.report_pdf.endswith(".pdf"):
        sample_info.report_pdf = sample_info.report_pdf + ".pdf"

    if sample_info.latest_report_pdf:
        if not sample_info.latest_report_pdf.endswith(".pdf"):
            sample_info.latest_report_pdf = sample_info.latest_report_pdf + ".pdf"
        report_file = os.path.basename(sample_info.latest_report_pdf)
        uploads = os.path.dirname(sample_info.latest_report_pdf)
    else:
        report_file = os.path.basename(sample_info.report_pdf)
        uploads = os.path.dirname(sample_info.latest_report_pdf)
    if not os.path.isfile(os.path.join(uploads, report_file)):
        print("here")
        msg = f"Informe no disponible per a la mostra {sample}"
        flash(msg, "warning")
        return redirect(url_for("show_run_details", run_id=run_id))

    return send_from_directory(directory=uploads, path=report_file, as_attachment=True)


def generate_new_report(
    sample: str, sample_id: str, run_id: str, tumor_origin:str, substitute_report: bool, lowqual_sample: bool,
    no_enac: bool, comments: str
):
    """ """

    env = Environment(loader=FileSystemLoader(app.config["SOMATIC_REPORT_TEMPLATES"]))
    template = env.get_template("report.html")

    sample_info = (
        SampleTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).first()
    )
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
    lost_exons = (
        LostExonsTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
    )
    pipeline_details = PipelineDetails.query.filter_by(run_id=run_id).first()
    summary_qc = (
        SummaryQcTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).first()
    )
    cnas = AllCnas.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()

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

    for var in high_impact_variants:
        var_str = var.to_string()
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
        comments=comments
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
        comments=comments
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
    action_name = ("Mostra: {}. Nou informe genètic").format(sample)
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
        tumor_origin = request.form["tumor_origin"]
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

        message = generate_new_report(sample, sample_id, run_id, tumor_origin,
            substitute_report, lowqual_sample, no_enac, comments)

        return make_response(jsonify(message), 200)


@app.route("/create_all_somatic_reports", methods=["POST"])
#@login_required
def create_all_somatic_reports():
    """ """
    if request.method == "POST":
        run_id = request.form["run_id"]
        print(run_id)
        substitute_report = False
        lowqual_sample = False
        samples = SampleTable.query.filter_by(run_id=run_id).all()
        comments = ""

        for sample in samples:
            generate_new_report(sample.lab_id, sample.lab_id, run_id, sample.tumor_origin, 
                substitute_report, lowqual_sample, no_enac, comments)
    return redirect(url_for("show_run_details", run_id=run_id))
    message = {
        "message_text": f"S'han generat correctament els informes",
    }
    return make_response(jsonify(message), 200)
