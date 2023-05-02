from app import app, db
import os
import time
import re
from flask import Flask
from flask import request, render_template, url_for, redirect, flash, send_from_directory, make_response, jsonify
from flask_wtf import FlaskForm
import sqlite3
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from flask_sslify import SSLify
from collections import defaultdict
import redis
from datetime import date
import pandas as pd
import docx
from app.models import Petition, SampleTable

# db = SQLAlchemy(app)

@app.route('/')
@app.route('/petition_menu')
def petition_menu():

    All_petitions = Petition.query.all()

    return render_template("create_petition.html", title="Nova petició",
        petitions=All_petitions)

@app.route('/download_petition_example')
@login_required
def download_petition_example():
    uploads = os.path.join(app.config['STATIC_URL_PATH'], "example")
    petition = "petition_example.xlsx"
    return send_from_directory(directory=uploads, path=petition, as_attachment=True)

@app.route('/upload_petition', methods=['GET', 'POST'])
@login_required
def upload_petition():
    '''
        Function that checks an input xlsx file with sample petition information.
    '''
    is_ok         = True
    is_registered = False
    error_list    =  []
    if request.method == "POST":
        petitions = request.files.getlist("petition_document")
        petition_dir = app.config['WORKING_DIRECTORY'] + "/petitions"
        if not os.path.isdir(petition_dir):
            os.mkdir(petition_dir)

        for petition in petitions:
            if petition.filename != "":
                if not petition.filename.endswith(".xlsx"):
                    flash("Es requereix un document de peticions en format .xlsx", "warning")
                    is_ok = False
            else:
                flash("Es requereix un document de peticions en format .xlsx", "warning")
                is_ok = False

        if is_ok == True:
            for f in petitions:
                f.save(os.path.join(petition_dir, f.filename))
                input_xlsx = petition_dir + "/" + f.filename

                # First, get extraction date
                df_date = pd.read_excel(input_xlsx, sheet_name=0,
                    engine='openpyxl', usecols = "C")
                df_date = df_date.iloc[:1]
                extraction_date = df_date.columns.values[0]
                if not extraction_date:
                    today = date.today()
                    extraction_date = today.strftime("%d/%m/%Y")
                else:
                    extraction_date = str(pd.to_datetime(extraction_date).strftime("%d/%m/%Y"))

                # Now, sample information
                df_samples = pd.read_excel(input_xlsx, sheet_name=0,
                    engine='openpyxl', header=4)

                for index, row in df_samples.iterrows():
                    # Valid rows
                    if 'CODI DE LA MOSTRA AP' in row:

                        if pd.isnull(row['CODI DE LA MOSTRA AP']):
                            continue

                        ap_code = str(row['CODI DE LA MOSTRA AP'])
                        if "Nota" in ap_code or "nan" in ap_code:
                            continue

                        print(row['PERCENTATGE TUMORAL'])
                        print("\n")

                is_yet_registered = False
                for index, row in df_samples.iterrows():

                    if 'CODI DE LA MOSTRA AP' in row:
                        if pd.isnull(row['CODI DE LA MOSTRA AP']):
                            continue
                        ap_code = str(row['CODI DE LA MOSTRA AP'])
                        if "Nota" in ap_code or "nan" in ap_code:
                            continue
                        tumour_type = "."

                        if 'ORIGEN TUMORAL' in row:
                            tumour_type = row['ORIGEN TUMORAL']
                        else:
                            tumour_type = "."
                        if 'TIPUS DE TUMOR' in row:
                            tumour_type = row['TIPUS DE TUMOR']
                        else:
                            tumour_type = row['ORIGEN TUMORAL']

                        ap_code = ap_code.rstrip(" ").lstrip(" ")

                        hc_code = str(row['NÚMERO D’HISTÒRIA CLÍNICA']).replace('.0', '').rstrip("\n").lstrip("\n")
                        hc_code = hc_code.replace(" ", "")
                        tumour_pct = "."
                        post_tape_eval= "."

                        if pd.isna(row['PERCENTATGE TUMORAL']):
                            row['PERCENTATGE TUMORAL'] = 100
                        if row['PERCENTATGE TUMORAL'] < 1:
                            tumour_pct = row['PERCENTATGE TUMORAL']*100
                            tumour_pct = int(tumour_pct)
                        elif int(row['PERCENTATGE TUMORAL']) > 100:
                            tumour_pct = 100
                        else:
                            print(row['PERCENTATGE TUMORAL'])
                            try:
                                int(row['PERCENTATGE TUMORAL'])
                            except:
                                pass
                            else:
                                tumour_pct = int(row['PERCENTATGE TUMORAL'])
                        CIP_code = "."
                        if 'NÚMERO CIP' in row:
                            CIP_code = row['NÚMERO CIP']
                        Petition_date = "."
                        if 'DATA PETICIÓ TÈCNICA' in row:
                            Petition_date = row['DATA PETICIÓ TÈCNICA']
                        Date_original_biopsy = "."
                        if 'DATA BIÒPSIA ORIGINAL' in row:
                            Date_original_biopsy = str(row['DATA BIÒPSIA ORIGINAL'])

                        tumour_area   = row['ÀREA TUMORAL (mm2)']
                        res_volume    = row['VOLUM  (µL) RESIDUAL  APROXIMAT']
                        nanodrop_conc = row['CONCENTRACIÓ NANODROP (ng/µL)']
                        nanodrop_ratio= row['RATIO 260/280 NANODROP']
                        physician_name= row['METGE SOL·LICITANT']
                        billing_unit  = row['UNITAT DE FACTURACIÓ']
                        comments      = row['COMENTARIS']
                        Petition_id    = ("PID_{}").format(extraction_date.replace("/", ""))

                        petition = Petition( Petition_id=Petition_id, User_id=current_user.id,
                        Date=extraction_date, Tumour_origin=tumour_type,
                        AP_code=ap_code, HC_code=hc_code, CIP_code=CIP_code,
                        Tumour_pct=tumour_pct, Volume=res_volume, Conc_nanodrop=nanodrop_conc,
                        Ratio_nanodrop=nanodrop_ratio,Tape_postevaluation=post_tape_eval,
                        Medical_doctor=physician_name,Billing_unit=billing_unit,
                        Medical_indication=tumour_type, Date_original_biopsy=Date_original_biopsy)

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
    return render_template("create_petition.html", title="Nova petició",
        petitions=All_petitions, errors=error_list)


@app.route('/upload_legacy_petition', methods = ['GET', 'POST'])
@login_required
def upload_legacy_petition():

    is_ok = True
    is_yet_registered = False
    errors = []

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

        ap_code         = ""
        purity          = ""
        residual_volume = ""
        nanodrop_conc   = ""
        nanodrop_ratio  = ""
        hc_number       = ""
        medical_doctor  = ""
        tape_postevaluation = ""
        billing_unit    = ""

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



@app.route('/update_petition', methods = ['GET', 'POST'])
@login_required
def update_petition():
    errors   = []
    is_ok = True
    if request.method == "POST":
        ap_code = ""
        if request.form.get('edit_ap_code'):
            ap_code = request.form['edit_ap_code']
        else:
            errors.append("Es requereix el codi AP")
            flash("Es requereix el codi AP", "warning")
            # is_ok = False

        hc_code = ""
        if request.form.get('edit_hc_code'):
            hc_code = request.form['edit_hc_code']
        else:
            errors.append("Es requereix el codi HC")
            flash("Es requereix el codi HC", "warning")
            # is_ok = False

        cip_code = ""
        if request.form.get('edit_cip_code'):
            cip_code = request.form['edit_cip_code']
        else:
            errors.append("Es requereix el codi CIP")
            flash("Es requereix el codi CIP", "warning")
            # is_ok = False


        tumour_origin = ""
        if request.form.get('edit_origin_tumor'):
            tumour_origin = request.form['edit_origin_tumor']
        else:
            errors.append("Es requereix l'origen tumoral")
            flash("Es requereix l'origen tumoral", "warning")
            # is_ok = False
        print(tumour_origin)

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
        if request.form.get('edit_medical_doctor'):
            medical_doctor = request.form['edit_medical_doctor']

        billing_unit = ""
        if request.form.get('edit_billing_doctor'):
            billing_unit = request.form['edit_billing_doctor']

        if is_ok == True:
            petition = Petition.query.filter_by(AP_code=ap_code).first()
            if petition:
                print("here", ap_code)
                petition.AP_code = ap_code
                petition.HC_code = hc_code
                petition.CIP_code = cip_code
                petition.Tumour_origin = tumour_origin
                petition.billing_unit = billing_unit
                petition.medical_doctor = medical_doctor

                # Petition_id = "PID_"+ date.replace("/", "")
                # petition = Petition( Petition_id= Petition_id, 
                # User_id=current_user.id, Date=date, 
                # AP_code=ap_code, HC_code=hc_code,
                # Tumour_origin=tumour_origin,
                # Tumour_pct=".", Volume=residual_volume, 
                # Conc_nanodrop=conc_nanodrop, Ratio_nanodrop=ratio_nanodrop,
                # Medical_doctor=medical_doctor, Tape_postevaluation=tape_posteval, 
                # Billing_unit=billing_unit)

                # db.session.add(petition)
                db.session.commit()

            sample = SampleTable.query.filter_by(ext1_id=ap_code).first()
            if sample:
                sample.ext1_id = ap_code
                sample.ext2_id = hc_code
                sample.ext3_id = cip_code
                sample.diagnosis = tumour_origin
                sample.physician_name = medical_doctor
                sample.medical_center = billing_unit
                db.session.commit()
            msg = "S'ha actualitzat correctament la petició "
            flash(msg, "success")
    All_petitions = Petition.query.all()

    return render_template("create_petition.html", title="Nova petició", petitions=All_petitions, errors=errors)


@app.route('/remove_sample/<id>', methods=["POST"])
@login_required
def remove_sample(id):
    errors   = []
    if request.method == "POST":
        entry = Petition.query.filter_by(Id=id).first()
        if not entry:
            msg = f"No s'ha pogut eliminar la mostra amb l'identificador {id}"
            message = {
                "info": msg,
                "status": 400,
            }
            return make_response(jsonify(message), 400)

        # flash(msg, "warning")
        db.session.delete(entry)
        db.session.commit()
        msg = f"S'ha eliminat correctament la mostra amb l'identificador {id}"
        message = {
            "info": msg,
            "status": 200,
        }
        return make_response(jsonify(message), 200)

    # All_petitions = Petition.query.all()
    # return render_template("create_petition.html", title="Nova petició", petitions=All_petitions, errors=errors)
