from app import app, db
import os
import time
import re
from flask import Flask
from flask import request, render_template, url_for, redirect, flash, send_from_directory, make_response, jsonify
from flask_wtf import FlaskForm
import sqlite3
from flask_sqlalchemy import SQLAlchemy
from flask_sslify import SSLify
from collections import defaultdict
import redis
from datetime import date
import pandas as pd
import docx
from app.models import Petition, SampleTable, GeneVariantSummary

import hashlib
import json
from app import app, db

# db = SQLAlchemy(app)


def create_table_if_not_exists():
    """Create the table dynamically if it doesn't exist."""
    with app.app_context():
        db.create_all()

def insert_gene_variant_summaries(list_of_dicts):
    """Insert unique rows into the GENE_VARIANT_SUMMARY table."""
    create_table_if_not_exists()

    for row in list_of_dicts:
        # Extract fields and prepare JSON
        gene = row.get('Gene', None)
        hgvsg = row.get('HGVSg', None)
        hgvsc = row.get('HGVSc', None)
        hgvsp = row.get('HGVSp', None)

        data_json = json.dumps(row, ensure_ascii=False).encode('utf8')
        # Convert dictionary to JSON string
        hgvs = row.get('HGVS', None)

        # Calculate a hash from the JSON string
        hash_string = "".join([gene, hgvsg, hgvsc, hgvsp, hgvs])
        print(hash_string)
        hash_value = hashlib.sha256(hash_string.encode('utf-8')).hexdigest()

        # Check if the hash already exists
        exists = GeneVariantSummary.query.filter_by(hash=hash_value).first()
        if not exists:
            # Insert into the table
            new_entry = GeneVariantSummary(
                gene=gene, hgvsg=hgvsg, hgvsc=hgvsc, hgvsp=hgvsp, data_json=data_json, hash=hash_value
            )
            db.session.add(new_entry)
        else:
            print(f"Skipped (already exists)")

    db.session.commit()

@app.route('/upload_xlsx_variants', methods=['GET', 'POST'])
def upload_xlsx_variants():
    """Route to upload and process an XLSX file."""
    if request.method == 'POST':
        variants_xlsx_dir = os.path.join(app.config['PETITIONS_DIR'], "variants_xlsx")
        os.makedirs(variants_xlsx_dir, exist_ok=True)

        if 'xlsx_file' not in request.files:
            flash('No file part in the request')
            return redirect(request.url)

        file = request.files['xlsx_file']

        if file.filename == '':
            flash('No file selected')
            return redirect(request.url)

        if not file.filename.endswith('.xlsx'):
            flash('File type not supported. Please upload an XLSX file.')
            return redirect(request.url)

        # Save the file temporarily
        file_path = os.path.join(variants_xlsx_dir, file.filename)
        file.save(file_path)

        # Process the file with pandas
        try:
            df = pd.read_excel(file_path, engine='openpyxl', sheet_name='Variants', header=2)
            df = df.fillna(method='ffill', axis=0)
            df = df.applymap(lambda x: x.replace('\xa0', ' ') if isinstance(x, str) else x)
            # Convert the DataFrame to a list of dictionaries
            list_of_dicts = df.to_dict(orient='records')
            for item in list_of_dicts:
                if 'HGVSg' in item:
                    item['HGVSg'] = item['HGVSg'].replace(" No tier ", "")
                if 'HGVSc' in item:
                    item['HGVSc'] = item['HGVSc'].replace(" No tier ", "")
                if 'HGVSp' in item:
                    item['HGVSp'] = item['HGVSp'].replace(" No tier ", "")
            # Insert the data into the database
            print("inserting new variants")
            insert_gene_variant_summaries(list_of_dicts)

            flash(f'{file.filename} actualitzat correctament', "success")
        except Exception as e:
            flash(f'Error en el processament del document: {str(e)}', "error")
            return redirect('/view_config')

        return redirect('/view_config')
    return redirect('/view_config')


@app.route('/view_config')
def view_config():
    """ """
    return render_template("config.html", title="Configuració")


# @app.route('/upload_xlsx_variants', methods=['GET', 'POST'])
# def upload_xlsx_variants():
#     """Route to upload and process an XLSX file."""
#     if request.method == 'POST':

#         variants_xlsx_dir = app.config['PETITIONS_DIR'] + "/variants_xlsx"
#         if not os.path.isdir(variants_xlsx_dir):
#             os.mkdir(variants_xlsx_dir)

#         if 'xlsx_file' not in request.files:
#             flash('No file part in the request')
#             return redirect(request.url)

#         file = request.files['xlsx_file']

#         if file.filename == '':
#             flash('No file selected')
#             return redirect(request.url)

#         if not file.filename.endswith('.xlsx'):
#             flash('File type not supported. Please upload an XLSX file.')
#             return redirect(request.url)

#         # Save the file temporarily or process it directly
#         file_path = os.path.join(variants_xlsx_dir, file.filename)  # Ensure 'uploads' directory exists
#         file.save(file_path)


#         df = pd.read_excel(file_path, engine='openpyxl', sheet_name='Variants', header=2)
#         df = df.fillna(method='ffill', axis=0)  # resolved updating the missing row entries
#         # df.index = pd.Series(df.index).fillna(method='ffill')
#         # Display the first few rows of the DataFrame
#         # print(df.head())
#         header_variables = df.columns.tolist()
#         # print(header_variables)
#         df = df.applymap(lambda x: x.replace('\xa0', ' ') if isinstance(x, str) else x)

#         list_of_dicts = df.to_dict(orient='records')
#         for item in list_of_dicts:
#             if 'HGVSp' in item:
#                 item['HGVSp'] = item['HGVSp'].replace(" No tier ", "")


#         # Process the file (e.g., read with pandas)
#         try:
#             df = pd.read_excel(file_path)
#             # Perform operations with the dataframe (e.g., save to database)
#             flash(f'{file.filename} uploaded and processed successfully.')
#         except Exception as e:
#             flash(f'Error processing file: {str(e)}')
#             return redirect('/view_config')
#         return redirect('/view_config')
#     return redirect('/view_config')

@app.route('/petition_menu')
def petition_menu():
    '''
    '''
    All_petitions = Petition.query.all()

    return render_template("create_petition.html", title="Nova petició",
        petitions=All_petitions)

@app.route('/download_petition_example')
#@login_required
def download_petition_example():
    uploads = os.path.join(app.config['STATIC_URL_PATH'], "example")
    petition = "petition_example.xlsx"
    return send_from_directory(directory=uploads, path=petition, as_attachment=True)

@app.route('/upload_petition', methods=['GET', 'POST'])
#@login_required
def upload_petition():
    '''
        Function that checks an input xlsx file with sample petition information.
    '''
    is_ok         = True
    is_registered = False
    error_list    =  []
    if request.method == "POST":
        petitions = request.files.getlist("petition_document")
        petition_dir = app.config['PETITIONS_DIR'] + "/petitions"
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
                    try:
                        extraction_date = str(today.strftime("%d/%m/%Y"))
                    except:
                        pass
                else:
                    try:
                        extraction_date = str(pd.to_datetime(extraction_date).strftime("%d/%m/%Y"))
                    except:
                        is_ok = False
                petition_date = "."
                # Now, sample information
                df_samples = pd.read_excel(input_xlsx, sheet_name=0,
                    engine='openpyxl', header=4)


# CODI DE LA MOSTRA AP	ORIGEN TUMORAL	PERCENTATGE TUMORAL	ÀREA TUMORAL (mm2)	VOLUM  (µL) RESIDUAL  APROXIMAT	CONCENTRACIÓ NANODROP (ng/µL)	RATIO 260/280 NANODROP	DATA BIÒPSIA ORIGINAL	DATA PETICIÓ TÈCNICA	NÚMERO CIP	NÚMERO D’HISTÒRIA CLÍNICA	METGE SOL·LICITANT	UNITAT DE FACTURACIÓ	COMENTARIS
# 24P4241	PULMÓ	30%	6	90	86.4	1.87	4/5/2024	4/11/2024	GIPU0441114006	18575284	H.FIGUERES	ONCO	79ANYS HOME  B-240001638

# MOSTRA AP	MOSTRA ORIGINAL	ORIGEN TUMORAL	PERCENTATGE TUMORAL	VOLUM  (µL) RESIDUAL  APROXIMAT	DATA BIÒPSIA ORIGINAL	DATA PETICIÓ TÈCNICA	PETICIONARI	PETICIÓ MODULAB	NÚMERO CIP	NÚMERO D’HISTÒRIA CLÍNICA	EDAT	SEXE	OBSERVACIONS

                found_v9 = False
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
                    if 'MOSTRA ORIGINAL' in row:
                        found_v9 = True

                is_yet_registered = False
                for index, row in df_samples.iterrows():
                    if found_v9:
                        if pd.isnull(row['MOSTRA AP']):
                            continue
                        ap_code = str(row['MOSTRA AP']).rstrip(" ").lstrip(" ")
                        
                        if "Nota" in ap_code or "nan" in ap_code:
                            continue
                        ap_block = "."
                        if 'MOSTRA ORIGINAL' in row:
                            ap_block = row['MOSTRA ORIGINAL'].rstrip(" ").lstrip(" ")

                        tumour_type = "."
                        if 'ORIGEN TUMORAL' in row:
                            tumour_type = row['ORIGEN TUMORAL']
  
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
                            try:
                                int(row['PERCENTATGE TUMORAL'])
                            except:
                                pass
                            else:
                                tumour_pct = int(row['PERCENTATGE TUMORAL'])
                        tumour_area = "."
                        res_volume = "."
                        if 'ÀREA TUMORAL (mm2)' in row:
                            tumour_area   = row['ÀREA TUMORAL (mm2)']
                        if 'VOLUM  (µL) RESIDUAL  APROXIMAT' in row:
                            res_volume    = row['VOLUM  (µL) RESIDUAL  APROXIMAT']

                        Modulab_petition = "."
                        if 'PETICIÓ MODULAB' in row:
                            Modulab_petition = row['PETICIÓ MODULAB']
                        CIP_code = "."
                        if 'NÚMERO CIP' in row:
                            CIP_code = row['NÚMERO CIP']
                        Petition_date = "."
                        if 'DATA PETICIÓ TÈCNICA' in row:
                            # Petition_date = row['DATA PETICIÓ TÈCNICA']
                            try:
                                Petition_date = str(pd.to_datetime(row['DATA PETICIÓ TÈCNICA']).strftime("%d/%m/%Y"))
                            except:
                                is_ok = False

                        Date_original_biopsy = "."
                        if 'DATA BIÒPSIA ORIGINAL' in row:
                            Date_original_biopsy = str(row['DATA BIÒPSIA ORIGINAL'])
                        Peticionari = "."
                        if 'PETICIONARI' in row:
                            Peticionari = row['PETICIONARI']
                        Petition_date = "."
                        if 'DATA PETICIÓ TÈCNICA' in row:
                            # Petition_date = row['DATA PETICIÓ TÈCNICA']
                            try:
                                Petition_date = str(pd.to_datetime(row['DATA PETICIÓ TÈCNICA']).strftime("%d/%m/%Y"))
                            except:
                                is_ok = False

                        hc_code = "."
                        if 'NÚMERO D’HISTÒRIA CLÍNICA' in row:
                            hc_code = str(row['NÚMERO D’HISTÒRIA CLÍNICA']).replace('.0', '').rstrip("\n").lstrip("\n")
                            hc_code = hc_code.replace(" ", "")
                        age = "."
                        if 'EDAT' in row:
                            age = row['EDAT']
                        sex = "."
                        if 'SEXE' in row:
                            sex = row['SEXE'].rstrip("\n").lstrip("\n")
                        post_tape_eval= "."
                        nanodrop_conc = "."
                        nanodrop_ratio = "."
                        modulab_id = "."
                        if 'CONCENTRACIÓ NANODROP (ng/µL)' in row:
                            nanodrop_conc = row['CONCENTRACIÓ NANODROP (ng/µL)']
                        
                        if 'RATIO 260/280 NANODROP' in row:
                            nanodrop_ratio = row['RATIO 260/280 NANODROP']

                        physician_name = "."
                        billing_unit = "."
                        comments = row['OBSERVACIONS']

                        Petition_id = ("PID_{}").format(extraction_date.replace("/", ""))

                        petition = Petition( Petition_id=Petition_id, User_id=".",
                        Date=extraction_date, Petition_date=Petition_date, Tumour_origin=tumour_type,
                        AP_code=ap_code, HC_code=hc_code, CIP_code=CIP_code, Sample_block=ap_block,
                        Tumour_pct=tumour_pct, Volume=res_volume, Conc_nanodrop=nanodrop_conc,
                        Ratio_nanodrop=nanodrop_ratio,Tape_postevaluation=post_tape_eval,
                        Medical_doctor=physician_name,Billing_unit=billing_unit,
                        Medical_indication=tumour_type, Date_original_biopsy=Date_original_biopsy,
                        Age=age, Sex=sex, Service=Peticionari, Modulab_id=Modulab_petition)

                        # Check if petition is already available
                        found = Petition.query.filter_by(AP_code=ap_code)\
                            .filter_by(HC_code=hc_code).first()
                        if not found:
                            db.session.add(petition)
                            db.session.commit()
                            is_yet_registered = False
                        else:
                            print(ap_code + " " + hc_code)
                            is_yet_registered = True


# CODI DE LA MOSTRA AP	ORIGEN TUMORAL	PERCENTATGE TUMORAL	ÀREA TUMORAL (mm2)	VOLUM  (µL) RESIDUAL  APROXIMAT	CONCENTRACIÓ NANODROP (ng/µL)	RATIO 260/280 NANODROP	DATA BIÒPSIA ORIGINAL	DATA PETICIÓ TÈCNICA	NÚMERO CIP	NÚMERO D’HISTÒRIA CLÍNICA	METGE SOL·LICITANT	UNITAT DE FACTURACIÓ	COMENTARIS
# 24P4241	PULMÓ	30%	6	90	86.4	1.87	4/5/2024	4/11/2024	GIPU0441114006	18575284	H.FIGUERES	ONCO	79ANYS HOME  B-240001638

# MOSTRA AP	MOSTRA ORIGINAL	ORIGEN TUMORAL	PERCENTATGE TUMORAL	VOLUM  (µL) RESIDUAL  APROXIMAT	DATA BIÒPSIA ORIGINAL	DATA PETICIÓ TÈCNICA	PETICIONARI	PETICIÓ MODULAB	NÚMERO CIP	NÚMERO D’HISTÒRIA CLÍNICA	EDAT	SEXE	OBSERVACIONS


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
                            # Petition_date = row['DATA PETICIÓ TÈCNICA']
                            try:
                                Petition_date = str(pd.to_datetime(row['DATA PETICIÓ TÈCNICA']).strftime("%d/%m/%Y"))
                            except:
                                is_ok = False

                        Date_original_biopsy = "."
                        if 'DATA BIÒPSIA ORIGINAL' in row:
                            Date_original_biopsy = str(row['DATA BIÒPSIA ORIGINAL'])
                        
                        # DEBUGGING
                        age = "."
                        if 'EDAT' in row:
                            age = row['EDAT']
                        sex = "."
                        if 'SEXE' in row:
                            sex = row['SEXE'].rstrip("\n").lstrip("\n")
                        ap_block = "."
                        if 'MOSTRA ORIGINAL' in row:
                            ap_block = row['MOSTRA ORIGINAL'].rstrip(" ").lstrip(" ")

                        Peticionari = "."
                        if 'PETICIONARI' in row:
                            Peticionari = row['PETICIONARI']
                        


                        tumour_area   = row['ÀREA TUMORAL (mm2)']
                        res_volume    = row['VOLUM  (µL) RESIDUAL  APROXIMAT']
                        nanodrop_conc = row['CONCENTRACIÓ NANODROP (ng/µL)']
                        nanodrop_ratio= row['RATIO 260/280 NANODROP']
                        physician_name= row['METGE SOL·LICITANT']
                        billing_unit = row['UNITAT DE FACTURACIÓ']
                        comments = row['COMENTARIS']
                        Petition_id = ("PID_{}").format(extraction_date.replace("/", ""))

                        petition = Petition( Petition_id=Petition_id, User_id=".",
                        Date=extraction_date, Petition_date=Petition_date, Tumour_origin=tumour_type,
                        AP_code=ap_code, HC_code=hc_code, CIP_code=CIP_code, Sample_block=ap_block,
                        Tumour_pct=tumour_pct, Volume=res_volume, Conc_nanodrop=nanodrop_conc,
                        Ratio_nanodrop=nanodrop_ratio,Tape_postevaluation=post_tape_eval,
                        Medical_doctor=physician_name,Billing_unit=billing_unit,
                        Medical_indication=tumour_type, Date_original_biopsy=Date_original_biopsy, Age=age, Sex=sex, Service=Peticionari)

                        # Check if petition is already available
                        found = Petition.query.filter_by(AP_code=ap_code)\
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
#@login_required
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

                            petition = Petition( Petition_id=Petition_id, User_id=".", Date=date,
                            AP_code=ap_code, HC_code=hc_code, Tumour_pct=tumoral_pct, Volume=residual_volume,
                            Conc_nanodrop=conc_nanodrop, Ratio_nanodrop=ratio_nanodrop,
                            Tape_postevaluation=tape_postevaluation,Medical_doctor=medical_doctor,
                            Billing_unit=billing_unit)

                            # Check if petition is already available
                            found = Petition.query.filter_by(AP_code=ap_code)\
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
#@login_required
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
            petition = Petition( Petition_id= Petition_id, User_id=".", Date=date, AP_code=ap_code, HC_code=hc_code,
            Tumour_pct=tumoral_pct, Volume=residual_volume, Conc_nanodrop=conc_nanodrop, Ratio_nanodrop=ratio_nanodrop,
            Medical_doctor=medical_doctor, Tape_postevaluation=tape_posteval, Billing_unit=billing_unit)

            db.session.add(petition)
            db.session.commit()
            msg = "S'ha enregistrat correctament la petició " + Petition_id
            flash(msg, "success")

    All_petitions = Petition.query.all()

    return render_template("create_petition.html", title="Nova petició", petitions=All_petitions, errors=errors)



@app.route('/update_petition', methods = ['GET', 'POST'])
#@login_required
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
        tumour_pct = ""
        if request.form.get('edit_tumoral_pct'):
            tumour_pct = request.form['edit_tumoral_pct']
        else:
            errors.append("Es requereix l'origen tumoral")
            flash("Es requereix l'origen tumoral", "warning")
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
                petition.Tumour_pct = tumour_pct

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
#@login_required
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
