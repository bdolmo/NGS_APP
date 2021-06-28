from app import app

from flask import Flask
from flask import request, render_template, url_for, redirect, flash
from flask_wtf import FlaskForm, RecaptchaField, Form
from wtforms import Form, StringField,PasswordField,validators
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from flask_sslify import SSLify

import redis
from rq import Queue, cancel_job
import os
import time
from command import background_task

from app import db
from app.models import Job, SampleTable, TherapeuticTable, OtherVariantsTable, RareVariantsTable, SummaryQcTable, BiomakerTable


r = redis.Redis()
q = Queue(connection=r)

# @app.route('/cancel_redis_job')
# def cancel_redis_job(job_id):
#     if request.method == 'POST':
#         if request.form['cancel_job']:
#             queue_id = request.form['cancel_job']
#             cancel_job(queue_id)

def allowed_fastq(filename):

    if not "." in filename:
        return False
    for extension in app.config['ALLOWED_FASTQ_EXTENSIONS']:
        if filename.endswith(extension):
            return True
        else:
            return False

def validate_fastq(fastq_files, fastq):

    is_ok   = True
    fq_list = []
    errors  = []
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
            errors.append("Missing fastq pair for " + fastq.filename)
            is_ok = True
        else:
            errors.append("Missing fastq pair for " + fastq.filename)
            is_ok = False
    return errors, is_ok

def allowed_input_filesize(filesize):
    if int(filesize) <= app.config["MAX_INPUT_FILESIZE"]:
        return True
    else:
        return False

@app.route('/')
@app.route('/main')
def main():
    return render_template("main.html", title="Pàgina inicial")

@app.route('/menu')
@login_required
def menu():
    return render_template("menu.html", title="Menú principal")

@app.route('/complete_analysis')
@login_required
def complete_analysis():
    return render_template("complete_analysis.html", title="Complete analysis")

@app.route('/ngs_applications')
@login_required
def ngs_applications():
    return render_template("ngs_applications.html", title="NGS-Aplicacions")

@app.route('/status')
@login_required
def status():
    All_jobs = Job.query.all()

    completed_jobs= 0
    started_jobs  = 0
    queued_jobs   = 0
    failed_jobs   = 0

    for job in All_jobs:

        # from redis, get queued status from id
        queued_job = q.fetch_job(job.Queue_id) # Returns job having ID "my_id"

        if queued_job:
            #queued, started, deferred, finished, stopped, and failed
            queued_status = queued_job.get_status()

            if queued_status == "queued":
                queued_jobs+= 1
            elif queued_status == "started":
                started_jobs+=1
            elif queued_status == "failed":
                failed_jobs+=1

            # update job status from db
            job.Status = queued_status
            db.session.commit()

    completed_jobs = len(All_jobs)-failed_jobs-queued_jobs-started_jobs
    status_dict = {
        'Total jobs' : len(All_jobs),
        'In queue'   : queued_jobs,
        'Completed'  : completed_jobs,
        'Failed'     : failed_jobs,
        'Running'    : started_jobs
    }

    # Update job status
    return render_template('status.html', title="Job Status", Jobs=All_jobs,
        status_dict=status_dict)

@app.route('/remove_job_data/<job_id>')
@login_required
def remove_job_data(job_id):

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

    flash("S'ha eliminat el job " + job_id  + " correctament", "success")
        #db.session.delete(job_entry)
        #db.session.commit()
    return redirect(url_for('status'))

@app.route('/uploads', methods = ['GET', 'POST'])
def submit_job():

    errors   = []
    messages = []
    is_ok = True
    total_samples = 0
    user_id = "."
    if current_user.id:
        user_id = current_user.id
    if request.method == "POST":
        # First, checking input FASTQ files
        if request.files:
            fastq_files = request.files.getlist("fastqs")
            total_samples = int(len(fastq_files)/2)
            run_dir = app.config['WORKING_DIRECTORY'] + ""

            for fastq in fastq_files:
                if fastq.filename != "":
                    errors, status = validate_fastq(fastq_files, fastq)
                    if status == True:
                        pass
                    else:
                        is_ok = False
                        for error in errors:
                            flash(error, "warning")
                else:
                    flash("Missing input FASTQ files", "warning")
                    is_ok = False

        # Second, checking Gene panel
        panel = ""
        if request.form.get('select_panel'):
            panel = request.form.get('select_panel')
        if request.files.getlist("custom_bed"):
            bed = request.files.getlist("custom_bed")
            if bed[0].filename != "":
                panel = bed[0].filename
        if panel == "" or panel == '0':
            is_ok = False
            flash("A gene panel is required", "warning")

        job_id = ""
        if request.form.get('job_id'):
            job_id = request.form['job_id']
            exists = Job.query.filter_by(Job_id=job_id, User_id=user_id).first()
            if exists:
                flash("Ja existeix un Job ID amb el nom entrat", "warning")
                is_ok = False
        else:
            errors.append("Es requereix un Job ID")
            flash("Es requereix un Job ID", "warning")
            is_ok = False

        run_dir = app.config['WORKING_DIRECTORY'] + "/" + job_id
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
            if not os.path.isdir(run_dir):
                os.mkdir(run_dir)
            lab_file = ""
            if request.files.getlist("lab_file"):
                lab_files = request.files.getlist("lab_file")
                if not lab_files:
                    flash("No s'ha introduït cap document de laboratori (xlsx). És possible que no es generin tots els codis de mostra", "warning")
                    #return render_template("complete_analysis.html", title="Complete analysis", errors=errors)
                for file in lab_files:
                    if file.filename == "":
                        flash("No s'ha introduït cap document de laboratori (xlsx). És possible que no es generin tots els codis de mostra", "warning")
                        continue
                    #     flash("No s'ha introduït cap document de laboratori (xlsx)", "warning")
                    #     return render_template("complete_analysis.html", title="Complete analysis", errors=errors)
                    # else:
                    if not file.filename.endswith(".xlsx"):
                        flash("El fitxer de laboratori no és un excel (.xlsx)", "warning")
                        return render_template("complete_analysis.html", title="Complete analysis", errors=errors)
                    else:
                        lab_file = run_dir + "/" + file.filename
                        file.save(os.path.join(run_dir, file.filename))
            for fastq in fastq_files:
                fastq.save(os.path.join(run_dir, fastq.filename))

            # Hard coded
            panel_dir = "/home/bdelolmo/Escriptori/PIPELINE_CANCER/PANEL_FOLDER/GenOncology-Dx.v1"
            ann_dir   = "/home/bdelolmo/Escriptori/ANN_DIR/"
            ref_dir   = "/home/bdelolmo/Escriptori/REF_DIR/"
            db_dir    = "/home/bdelolmo/Escriptori/NGS_APP/app"

            params = {
                'PIPELINE_EXE' : app.config['NGS_PIPELINE_EXE'],
                'USER_ID'  : user_id,
                'PANEL'    : panel_dir + "/GenOncology-Dx.v1.bed",
                'GENOME'   : 'hg19',
                'THREADS'  : '4',
                'VARCLASS' : 'somatic',
                'RUN_DIR'  : run_dir,
                'LAB_DATA' : lab_file,
                'ANN_DIR'  : ann_dir,
                'REF_DIR'  : ref_dir,
                'DB_DIR'   : db_dir
                # 'STATIC_DIR' : "/home/bdelolmo/Escriptori/NGS_APP/app/static"
            }

            task = q.enqueue( background_task, job_id, params, job_timeout=50000)
            jobs = q.jobs
            q_len = len (q)
            message =  f"Task {task.id} added to queue at {task.enqueued_at}. {q_len} Tasks in queue "
            print(message)

            # Here we should update the jobs database
            job = Job( User_id =user_id, Job_id =job_id, Queue_id=task.id, Date=task.enqueued_at, Analysis="Complete",
                Panel=panel, Samples=total_samples, Status="Running")
            db.session.add(job)
            db.session.commit()

            return redirect(url_for('status'))

    return render_template("complete_analysis.html", title="Complete analysis")
