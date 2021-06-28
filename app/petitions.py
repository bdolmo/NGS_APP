from app import app

from flask import Flask
from flask import request, render_template, url_for, redirect, flash
from flask_wtf import FlaskForm
import sqlite3
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user

from flask_sqlalchemy import SQLAlchemy
from flask_sslify import SSLify
from collections import defaultdict
import redis
from rq import Queue, cancel_job
import os
import time
from datetime import date
from command import background_task
import pandas as pd
import docx
import re

# @app.route('/cancel_redis_job')
# def cancel_redis_job(job_id):
#     if request.method == 'POST':
#         if request.form['cancel_job']:
#             queue_id = request.form['cancel_job']
#             cancel_job(queue_id)

db = SQLAlchemy(app)

class Petition(db.Model):
    __tablename__ = 'PETITIONS'
    Id             = db.Column(db.Integer(), primary_key=True, autoincrement=True)
    Petition_id    = db.Column(db.String(20))
    User_id        = db.Column(db.String(20))
    Date           = db.Column(db.String(20))
    AP_code        = db.Column(db.String(20))
    HC_code        = db.Column(db.String(20))
    Tumour_pct     = db.Column(db.String(20))
    Volume         = db.Column(db.String(20))
    Conc_nanodrop  = db.Column(db.String(20))
    Ratio_nanodrop = db.Column(db.String(20))
    Tape_postevaluation = db.Column(db.String(20))
    Medical_doctor = db.Column(db.String(50))
    Billing_unit   = db.Column(db.String(50))

    def __init__(self, Petition_id, User_id, Date, AP_code, HC_code, Tumour_pct,
        Volume, Conc_nanodrop, Ratio_nanodrop, Tape_postevaluation, Medical_doctor, Billing_unit):
        self.Petition_id = Petition_id
        self.Date   = Date
        self.User_id = User_id
        self.AP_code= AP_code
        self.HC_code  = HC_code
        self.Tumour_pct= Tumour_pct
        self.Volume = Volume
        self.Conc_nanodrop = Conc_nanodrop
        self.Ratio_nanodrop = Ratio_nanodrop
        self.Tape_postevaluation = Tape_postevaluation
        self.Medical_doctor = Medical_doctor
        self.Billing_unit = Billing_unit

@app.route('/')
@app.route('/petition_menu')
def petition_menu():

    All_petitions = Petition.query.all()

    return render_template("create_petition.html", title="Nova petició", petitions=All_petitions)

@app.route('/upload_petition', methods = ['GET', 'POST'])
@login_required
def upload_petition():

    is_ok = True
    is_yet_registered = False
    errors =[]

    if request.method == "POST":

        # First, checking input FASTQ files
        if request.files:
            petition_documents = request.files.getlist("petition_document")
            petition_dir = app.config['WORKING_DIRECTORY'] + "/petitions"
            if not os.path.isdir(petition_dir):
                os.mkdir(petition_dir)

            for f in petition_documents:
                if f.filename != "":
                    pass
                else:
                    flash("Es requereix un document de peticions en format .docx", "warning")
                    is_ok = False

            if is_ok == True:
                for f in petition_documents:
                    f.save(os.path.join(petition_dir, f.filename))
                    file_path = petition_dir + "/" + f.filename
                    print(file_path)
                    is_ok, sample_dict, tmp_errors  = validate_petition_document(file_path)
                    for err in tmp_errors:
                        print(err)
                        flash(err, "warning")
                        errors.append(err)
                    if is_ok == True:
                        for sample in sample_dict:
                            Petition_id    = "PID_" + sample_dict[sample]['Date'].replace("/", "")
                            date           = sample_dict[sample]['Date']
                            ap_code        = sample_dict[sample]['AP_code']
                            hc_code        = sample_dict[sample]['HC_number']
                            tumoral_pct    = sample_dict[sample]['Tumour_purity']
                            tape_postevaluation = sample_dict[sample]['Tape_postevaluation']
                            residual_volume= sample_dict[sample]['Residual_volume']
                            conc_nanodrop  = sample_dict[sample]['Nanodrop_conc']
                            ratio_nanodrop = sample_dict[sample]['Nanodrop_ratio']
                            medical_doctor = sample_dict[sample]['Medical_doctor']
                            billing_unit   = sample_dict[sample]['Billing_unit']

                            petition = Petition( Petition_id=Petition_id, User_id=current_user.id, Date=date,
                            AP_code=ap_code, HC_code=hc_code, Tumour_pct=tumoral_pct, Volume=residual_volume,
                            Conc_nanodrop=conc_nanodrop, Ratio_nanodrop=ratio_nanodrop,
                            Tape_postevaluation=tape_postevaluation,Medical_doctor=medical_doctor,
                            Billing_unit=billing_unit)

                            # Check if petition is already available
                            found = Petition.query.filter_by(User_id=current_user.id).filter_by(AP_code=ap_code)\
                                .filter_by(HC_code=hc_code).first()
                            if not found:
                                db.session.add(petition)
                                db.session.commit()
                                is_yet_registered = False
                            else:
                                print(ap_code + " " + hc_code)
                                is_yet_registered = True


            if is_ok == True:
                if is_yet_registered == True:
                    flash("Les mostres d'aquesta petició ja s'han enregistrat prèviament!", "warning")
                else:
                    flash("S'ha enregistrat la petició correctament!", "success")
    else:
        flash("Es requereix un document de peticions en format word (docx)", "warning")


    All_petitions = Petition.query.all()
    return render_template("create_petition.html", title="Nova petició", petitions=All_petitions, errors=errors)

def validate_petition_document(file):

    is_ok = True
    errors = []
    sample_dict = defaultdict(dict)

    if os.path.isfile(file):
        print(file)
        if not file.endswith(".docx"):
            errors.append("El document "+ os.path.basename(file) + " no és un docx")
            is_ok = False
            return is_ok, sample_dict, errors
        doc = docx.Document(file)

        # Getting all tables
        all_t = doc.tables
        is_date   = False
        is_sample = False
        petition_date = ""

        ap_code = ""
        purity  = ""
        residual_volume = ""
        nanodrop_conc = ""
        nanodrop_ratio = ""
        hc_number = ""
        medical_doctor = ""
        tape_postevaluation = ""
        billing_unit = ""

        abs_idx = 0
        for t in all_t:
            row_idx = 0
            for row in t.rows:
                abs_idx+=1
                cell_idx = 0
                if is_sample:
                    print(str(len(row.cells)))
                    if len(row.cells) > 13:
                        errors.append("La fila " + str(abs_idx) + " conté més de 8 cel·les")
                        is_ok = False
                        break
                for cell in row.cells:
                    cell.text = cell.text.rstrip("\n")
                    if cell.text == "":
                        continue
                    if cell.text.startswith('DATA'):
                        is_date = True
                       # break
                        continue
                    if cell.text.startswith('CODI'):
                        is_date = False
                        is_sample= True
                    if is_date:
                        if row_idx == 0:
                            petition_date = cell.text
                            tmp_date = petition_date.split("/")
                            if len(tmp_date) != 3:
                                errors.append("El format de la data és incorrecte. Hauria de seguir el format dd/mm/yyyy")
                                is_ok = False
                            if len(tmp_date) == 3:
                                days   = int(tmp_date[0])
                                month  = int(tmp_date[1])
                                year   = int(tmp_date[2])
                                if days > 31 or month > 12:
                                    errors.append("El format de la data és incorrecte. Hauria de seguir el format dd/mm/yyyy")
                                    is_ok = False
                            is_date = False
                    if is_sample:
                        if row_idx > 1:
                            # AP code, must be alphanumeric
                            if cell_idx == 0:
                                ap_code = cell.text

                                print("codi ap: " + ap_code)
                                # Not checking names for now
                                check = True
                                #check = re.search('\d+[A-Z]+\d+?(\s+)?([A-Z])?(\d+)?', ap_code)
                                if check:
                                    pass
                                else:
                                    errors.append("Fila: " + str(abs_idx) + ". El codi AP entrat ("+ap_code+") no té el format adequat")
                                    is_ok = False
                                if not ap_code:
                                   errors.append("Fila: " + str(abs_idx) + ". No s'ha trobat el codi AP")
                            # Tumour purity (%)
                            if cell_idx == 1:
                                purity = re.search('^\d+%', cell.text)
                                if purity:
                                    purity = purity.group(0).replace("%", "")
                                    if purity:
                                        if re.search('\d+', purity):
                                            if int(purity) >= 0 and int(purity) <= 100:
                                                pass
                                            else:
                                                is_ok = False
                                                errors.append("Mostra " + ap_code + ": el valor de %Tumoral no es troba entre 0-100")
                                        else:
                                            is_ok = False
                                            errors.append("Mostra " + ap_code + ": el valor de %Tumoral no és numèric")
                                    else:
                                        is_ok = False
                                        errors.append("Mostra " + ap_code + ": el valor de %Tumoral no és numèric")
                                else:
                                    is_ok = False
                                    errors.append("Mostra " + ap_code + ": no s'ha trobat el valor de %Tumoral")
                                print("purity: " + cell.text)

                            # Residual volume
                            if cell_idx == 2:
                                residual_volume = cell.text
                                print("residual:" +  residual_volume)
                                if re.search('\d+', residual_volume):
                                    pass
                                else:
                                    residual_volume = "ND"
                                    #errors.append("Mostra " + ap_code + ": el valor del Volum residual no és numèric")
                                if not residual_volume:
                                   residual_volume = "ND"
                                   #is_ok = False
                                   #errors.append("Mostra " + ap_code + ": no s'ha trobat el volum residual")
                            # Nanodrop concentration
                            if cell_idx == 3:
                                nanodrop_conc = cell.text.replace(",", ".")
                                print("nanodrop conc:" +  nanodrop_conc)
                                if re.search('\d+?\.?\d+', nanodrop_conc):
                                    pass
                                else:
                                    #is_ok = False
                                    nanodrop_conc = "ND"
                                    #errors.append("Mostra " + ap_code + ": el valor de concentració del Nanodrop " + nanodrop_conc + " no és vàlid")
                                if not nanodrop_conc:
                                   #is_ok = False
                                   nanodrop_conc = "ND"
                                   #errors.append("Mostra " + ap_code + ": no s'ha trobat el valor de concentració del Nanodrop")
                            # Nanodrop ratio
                            if cell_idx == 4:
                                nanodrop_ratio = cell.text.replace(",", ".")
                                if re.search('\d+?\.?\d+', nanodrop_ratio):
                                    pass
                                else:
                                    nanodrop_ratio = "ND"
                                    #is_ok = False
                                    #errors.append("Mostra " + ap_code + ": el valor del ratio 260/280 no és vàlid")
                                if not nanodrop_ratio:
                                    nanodrop_ratio = "ND"
                                   #is_ok = False
                                   #errors.append("Mostra " + ap_code + ": no s'ha trobat el valor del ratio 260/280 del Nanodrop")
                            # Tape postevaluation
                            if cell_idx == 5:
                                tape_postevaluation = cell.text
                                if not tape_postevaluation:
                                   is_ok = False
                                   errors.append("Mostra " + ap_code + ": falta informació de la valoració post tape")
                            # HC number
                            if cell_idx == 6:
                                hc_number = cell.text
                                if not hc_number:
                                   is_ok = False
                                   errors.append("Mostra " + ap_code + ": no s'ha trobat el número d'Història Clínica")
                            # Medical doctor solicitant
                            if cell_idx == 7:
                                medical_doctor = cell.text
                                if not medical_doctor:
                                   is_ok = False
                                   errors.append("Mostra " + ap_code + ": no s'ha trobat el metge sol·licitant")
                            # Billing unit
                            if cell_idx == 8:
                                billing_unit = cell.text
                                if not billing_unit:
                                    is_ok = False
                                    errors.append("Mostra " + ap_code + ": no s'ha trobat la unitat de facturació")

                            sample_dict[ap_code] = defaultdict(dict)
                            sample_dict[ap_code]['Date']           = petition_date
                            sample_dict[ap_code]['AP_code']        = ap_code
                            sample_dict[ap_code]['HC_number']      = hc_number
                            sample_dict[ap_code]['Tumour_purity']  = purity
                            sample_dict[ap_code]['Residual_volume']= residual_volume
                            sample_dict[ap_code]['Nanodrop_conc']  = nanodrop_conc
                            sample_dict[ap_code]['Nanodrop_ratio'] = nanodrop_ratio
                            sample_dict[ap_code]['Medical_doctor'] = medical_doctor
                            sample_dict[ap_code]['Tape_postevaluation'] = tape_postevaluation
                            sample_dict[ap_code]['Billing_unit']   = billing_unit

                    cell_idx+=1
                row_idx += 1
        return is_ok, sample_dict, errors

    else:
        flash("El document {} no no té el format word (.docx)", "warning").format(file)
        is_ok = False
        return is_ok, sample_dict, errors

@app.route('/create_petition', methods = ['GET', 'POST'])
@login_required
def create_petition():
    errors   = []
    is_ok = True
    if request.method == "POST":
        ap_code = ""
        if request.form.get('AP_code'):
            ap_code = request.form['AP_code']

            # This can change a lot, so we now do not provide any regex evaluation
            check = True
            #check = re.search('\d+[A-Z]+\d+?\s+[A-Z]\d+', ap_code)
            if check:
                pass
            else:
                flash("El codi AP entrat " + ap_code + " no segueix la nomenclatura esperada", "warning")
                is_ok = False
        else:
            errors.append("Es requereix el codi AP")
            flash("Es requereix el codi AP", "warning")
            is_ok = False

        hc_code = ""
        if request.form.get('HC_code'):
            hc_code = request.form['HC_code']
        else:
            errors.append("Es requereix el codi HC")
            flash("Es requereix el codi HC", "warning")
            is_ok = False

        date = ""
        if request.form.get('Date'):
            date = request.form['Date']
            tmp_date = date.split("-")
            print(str(tmp_date))
            if len(tmp_date) != 3:
                flash("El format de la data és incorrecte. Hauria de seguir el format dd/mm/yyyy")
                is_ok = False
            if len(tmp_date) == 3:
                days   = int(tmp_date[2])
                month  = int(tmp_date[1])
                year   = int(tmp_date[0])
                date = str(days) + "/" + str(month) + "/" + str(year)
                if days > 31 or month > 12:
                    flash("El format de la data és incorrecte. Hauria de seguir el format dd/mm/yyyy")
                    is_ok = False
        else:
            errors.append("Es requereix la data d'extracció")
            flash("Es requereix la data d'extracció", "warning")
            is_ok = False

        tumoral_pct = ""
        if request.form.get('Tumoral_pct'):
            tumoral_pct = request.form['Tumoral_pct']
            if tumoral_pct:
                tumoral_pct = tumoral_pct.replace("%", "")
                if re.search('\d+', tumoral_pct):
                    if int(tumoral_pct) >= 0 and int(tumoral_pct) <= 100:
                        pass
                    else:
                        is_ok = False
                        flash("Mostra " + ap_code + ": el valor de %Tumoral no es troba entre 0-100", "warning")
                else:
                    is_ok = False
                    flash("Mostra " + ap_code + ": el valor de %Tumoral no és numèric", "warning")
        else:
            errors.append("Es requereix el %Tumoral")
            flash("Es requereix el %Tumoral", "warning")
            is_ok = False

        residual_volume = ""
        if request.form.get('Residual_volume'):
            residual_volume = request.form['Residual_volume']

        tape_posteval = ""
        if request.form.get('tape_postevaluation'):
            option = request.form['tape_postevaluation']
            if option  == "1":
                tape_posteval = "Sí"
            elif option == "2":
                tape_posteval = "No"

        conc_nanodrop = ""
        if request.form.get('Nanodrop_conc'):
            conc_nanodrop = request.form['Nanodrop_conc']

        ratio_nanodrop = ""
        if request.form.get('Nanodrop_ratio'):
            ratio_nanodrop = request.form['Nanodrop_ratio']

        medical_doctor = ""
        if request.form.get('Medical_doctor'):
            medical_doctor = request.form['Medical_doctor']

        billing_unit = ""
        if request.form.get('Billing_unit'):
            billing_unit = request.form['Billing_unit']

        if is_ok == True:
            Petition_id = "PID_"+ date.replace("/", "")
            petition = Petition( Petition_id= Petition_id, User_id=current_user.id, Date=date, AP_code=ap_code, HC_code=hc_code,
            Tumour_pct=tumoral_pct, Volume=residual_volume, Conc_nanodrop=conc_nanodrop, Ratio_nanodrop=ratio_nanodrop,
            Medical_doctor=medical_doctor, Tape_postevaluation=tape_posteval, Billing_unit=billing_unit)

            db.session.add(petition)
            db.session.commit()
            msg = "S'ha enregistrat correctament la petició " + Petition_id
            flash(msg, "success")

    All_petitions = Petition.query.all()

    return render_template("create_petition.html", title="Nova petició", petitions=All_petitions, errors=errors)

@app.route('/remove_sample/<id>')
@login_required
def remove_sample(id):
    errors   = []

    entry = Petition.query.filter_by(Id=id).first()
    if entry:
        db.session.delete(entry)
        db.session.commit()
        msg = "S'ha eliminat correctament la mostra amb l'identificador  " + id
        flash(msg, "success")
    else:
        msg = "No s'ha pogut eliminar la mostra amb l'identificador  " + id
        flash(msg, "warning")


    All_petitions = Petition.query.all()
    return render_template("create_petition.html", title="Nova petició", petitions=All_petitions, errors=errors)
