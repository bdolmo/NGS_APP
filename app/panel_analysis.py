import os
import time
import shutil
import redis
from app import app, db
from flask import Flask
from flask import (
    request,
    render_template,
    url_for,
    redirect,
    flash,
    send_from_directory,
    make_response,
    jsonify,
)
from flask_wtf import FlaskForm, RecaptchaField, Form
from flask_dropzone import Dropzone
from wtforms import Form, StringField, PasswordField, validators
# from flask_login import (
#     LoginManager,
#     UserMixin,
#     login_user,
#     login_required,
#     logout_user,
#     current_user,
# )
from flask_sqlalchemy import SQLAlchemy
from flask_sslify import SSLify
from sqlalchemy.sql import and_, or_
from rq import Queue, cancel_job, Retry
from rq.command import send_stop_job_command
from rq.registry import StartedJobRegistry, FinishedJobRegistry, FailedJobRegistry
from job_commands import launch_ngs_analysis
from config import compendium_url, ngs_app_url
from pathlib import Path
from app.models import (
    Job,
    SampleTable,
    TherapeuticTable,
    OtherVariantsTable,
    RareVariantsTable,
    SummaryQcTable,
    BiomakerTable,
)
import requests
import json

r = redis.Redis()
q = Queue(connection=r)
registry = FinishedJobRegistry("default", connection=r)


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


@app.route("/remove_job/<queue_id>/<job_id>/<panel>")
#@login_required
def remove_job(queue_id, job_id, panel):
    try:
        registry.remove(queue_id, delete_job=True)
    except Exception as e:
        print(str(e))

    job_entry = Job.query.filter_by(Job_id=job_id, Panel=panel).first()
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
            # panel_name = panel["Features_json"]["Panel_id"]
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


@app.route("/status")
#@login_required
def status():
    """ """

    status_dict = {
        "Total jobs": 0,
        "In queue": 0,
        "Completed": 0,
        "Failed": 0,
        "Running": 0,
    }

    All_jobs = Job.query.all()
    for job in All_jobs:
        print(job.Job_id, job.Status, job.Queue_id)
        # from redis, get queued status from id
        # Returns job having ID "my_id"
        if job.Job_id is None:
            continue
        queued_job = q.fetch_job(job.Queue_id)
        if queued_job:
            queued_status = queued_job.get_status()
            if queued_status == "queued":
                status_dict["In queue"] += 1
            elif queued_status == "started":
                status_dict["Running"] += 1
            elif queued_status == "failed":
                status_dict["Failed"] += 1
            job.Status = queued_status
        else:
            if job.Status == "started":
                job.Status = "finished"
            job.Status = "finished"
        db.session.commit()

    status_dict["Completed"] = (
        len(All_jobs)
        - status_dict["Failed"]
        - status_dict["In queue"]
        - status_dict["Running"]
    )

    # Update job status
    return render_template(
        "status.html", title="Job Status", Jobs=All_jobs, status_dict=status_dict
    )


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
    job_entry = Job.query.filter_by(Job_id=job_id).first()
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
#@login_required
def submit_ngs_job():
    """ """
    errors = []
    messages = []
    fastq_files = []

    is_ok = True
    total_samples = 0
    user_id = "."
    # if current_user.id:
    #     user_id = current_user.id

    if request.method == "POST":
        # First, checking input FASTQ files
        total, used, free = shutil.disk_usage("/")
        total_gb = total // (2 ** 30)
        used_gb = used // (2 ** 30)
        free_gb = free // (2 ** 30)

        if request.files:
            fastq_files = request.files.getlist("fastqs")
            total_samples = int(len(fastq_files) / 2)
            run_dir = app.config["UPLOADS"] + ""
            if float(free_gb) < 20:
                is_ok = False
                msg = (
                    "No hi ha prou espai al servidor d'anàlisi ({} Gb). \
                    Es recomana ampliar fins a 200Gb"
                ).format(str(free_gb))
                flash(msg, "warning")

            if is_ok is True:
                for fastq in fastq_files:
                    if fastq.filename != "":
                        if "Undetermined" in fastq.filename:
                            continue
                        errors, status = validate_fastq(fastq_files, fastq)
                        if status == True:
                            pass
                        else:
                            is_ok = False
                            for error in errors:
                                flash(error, "warning")
                    else:
                        flash("Es requereixen arxius FASTQ", "warning")
                        is_ok = False
        else:
            flash("Es requereixen arxius FASTQ", "warning")
            is_ok = False

        # Second, checking Gene panel
        panel = ""
        if request.form.get("select_panel"):
            panel = request.form.get("select_panel")
        if request.files.getlist("custom_bed"):
            bed = request.files.getlist("custom_bed")
            if bed[0].filename != "":
                panel = bed[0].filename
        if panel == "" or panel == "0":
            is_ok = False
            flash("Es requereix un panell de gens", "warning")
        print(panel)

        job_id = ""
        if request.form.get("job_id"):
            job_id = request.form["job_id"]
            exists = Job.query.filter_by(
                Job_id=job_id, User_id=user_id, Panel=panel
            ).first()
            if exists:
                flash("Ja existeix un Job ID amb el nom entrat", "warning")
                is_ok = False
        else:
            errors.append("Es requereix un Job ID")
            flash("Es requereix un Job ID", "warning")
            is_ok = False

        run_dir = os.path.join(app.config["UPLOADS"], job_id)

        # Now checking optinal parameters
        if request.form.get("gatk"):
            do_gatk = True
        if request.form.get("freebayes"):
            do_freebayes = True

        # SV algorithms
        if request.form.get("grapes"):
            do_grapes = True
        if request.form.get("manta"):
            do_manta = True

        # Population databases
        if request.form.get("1KGenomes"):
            do_1kg = True
        if request.form.get("gnomad"):
            do_gnomad = True

        # Now in-silico predictors.
        if request.form.get("sift"):
            do_sift = True
        if request.form.get("polyphen"):
            do_polyphen = True
        if request.form.get("mutationtaster"):
            do_mutationtaster = True
        if request.form.get("provean"):
            do_provean = True
        if request.form.get("revel"):
            do_revel = True
        if request.form.get("cadd"):
            do_cadd = True
        if request.form.get("fathmm"):
            do_fathmm = True
        if request.form.get("lrt"):
            do_lrt = True
        if request.form.get("eigen"):
            do_eigen = True
        if request.form.get("mutpred"):
            do_mutpred = True
        if request.form.get("metasvm"):
            do_metasvm = True

        if is_ok == True:

            panel_name = panel
            panel_version = ""

            if not os.path.isdir(run_dir):
                os.mkdir(run_dir)
            print(panel)
            print(panel)
            if panel == "GenOncology-Dx.v1":
                panel_dir = os.path.join(run_dir, "GenOncology-Dx")
            else:
                panel_dir = os.path.join(run_dir, panel_name)
            if not os.path.isdir(panel_dir):
                os.mkdir(panel_dir)

            print(panel_dir)
            print(panel_dir)

            # --panel_name SUDD_85 --panel_version v3
            var_analysis = "germline"
            print(panel)

            if panel == "GenOncology-Dx.v1":
                panel_bed = os.path.join(panel_dir, "GenOncology-Dx.v1.bed")
                panel_name = "GenOncology-Dx"
                var_analysis = "somatic"
                panel_version = "v1"
            else:
                # First, get the latest version available
                url = f"{app.config['GENE_PANEL_API']}/{panel}/latest_version"
                print(url)
                response = requests.get(url)
                r = response.json()
                if r:
                    panel_version = f"v{r['panel_version']}"
                    url = f"{app.config['GENE_PANEL_API']}/{panel}/{panel_version}"
                    response = requests.get(url)
                    r = response.json()
                    panel_bed = r["Capture_bed"]

            lab_file = ""
            if request.files.getlist("lab_file"):
                lab_files = request.files.getlist("lab_file")
                if not lab_files:
                    flash(
                        "No s'ha introduït cap document de laboratori (xlsx). És possible que no es generin tots els codis de mostra",
                        "warning",
                    )
                for file in lab_files:
                    if file.filename == "":
                        flash(
                            "No s'ha introduït cap document de laboratori (xlsx). És possible que no es generin tots els codis de mostra",
                            "warning",
                        )
                    else:
                        lab_file = os.path.join(panel_dir, file.filename)
                        file.save(os.path.join(panel_dir, file.filename))
            for fastq in fastq_files:
                fastq.save(os.path.join(panel_dir, fastq.filename))

            # Hard coded
            if "GenOncology" in panel_name:
                panel_bed = "/home/udmmp/GC_NGS_PIPELINE/gene_panels/GenOncology-Dx.v1/GenOncology-Dx.v1.bed"
            ann_dir = app.config["ANN_DIR"]
            ref_dir = app.config["REF_DIR"]
            db_sqlite = app.config["DB"]
            ann_yaml = app.config["ANN_YAML"]
            docker_yaml = app.config["DOCKER_YAML"]
            ref_yaml = app.config["REF_YAML"]
            bin_yaml = app.config["BIN_YAML"]

            input_dir = os.path.join(run_dir, panel_name)

            params = {
                "PIPELINE_EXE": app.config["NGS_PIPELINE_EXE"],
                "INPUT_DIR": input_dir,
                "OUTPUT_DIR": input_dir,
                "USER_ID": user_id,
                "PANEL": panel_bed,
                "PANEL_NAME": panel_name,
                "PANEL_VERSION": panel_version,
                "GENOME": "hg19",
                "THREADS": "12",
                "VARCLASS": var_analysis,
                "RUN_DIR": run_dir,
                "RUN_NAME": os.path.basename(run_dir),
                "LAB_DATA": lab_file,
                "DB": db_sqlite,
                "ANN_YAML": ann_yaml,
                "REF_YAML": ref_yaml,
                "BIN_YAML": bin_yaml,
                "DOCKER_YAML": docker_yaml
            }

            task = q.enqueue(launch_ngs_analysis, params, job_timeout=500000)
            print(task.result)
            jobs = q.jobs

            registry = FailedJobRegistry(queue=q)
            if registry:
                print(registry)

            print("Status: %s" % task.get_status())

            q_len = len(q)
            message = f"Task {task.id} added to queue at {task.enqueued_at}. {q_len} Tasks in queue "
            print(message)

            registry = FailedJobRegistry(queue=q)
            if registry:
                print(registry)

            # Here we should update the jobs database
            job = Job(
                User_id=user_id,
                Job_id=job_id,
                Queue_id=task.id,
                Date=task.enqueued_at,
                Analysis=var_analysis,
                Panel=panel,
                Samples=total_samples,
                Status="Running",
            )
            print(job)
            db.session.add(job)
            db.session.commit()

            # res = make_response(jsonify({"message": "File uploaded"}), 200)
            # return res
            return redirect(url_for('status'))

    res = make_response(jsonify({"message": "File upload error"}), 400)
    return res
