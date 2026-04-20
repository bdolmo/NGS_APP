from app import app, db
import os
import time
import re
from flask import Flask
from flask import request, render_template, url_for, redirect, flash, send_from_directory, make_response, jsonify, send_file
from flask_wtf import FlaskForm
import sqlite3
from flask_sqlalchemy import SQLAlchemy
from flask_sslify import SSLify
from collections import defaultdict
import redis
from datetime import date, datetime
import pandas as pd
import docx
from app.models import Petition, SampleTable, GeneVariantSummary
import hashlib
import json
import html
from io import BytesIO
from app import app, db
from sqlalchemy import or_, cast, String

def _normalize_date_ddmmyyyy(raw):
    """Normalize many date input formats to DD/MM/YYYY."""
    if raw is None:
        return ""
    try:
        if pd.isna(raw):
            return ""
    except Exception:
        pass

    value = str(raw).strip()
    if not value or value in {".", "nan", "NaT", "None"}:
        return ""

    # Strip time component if present.
    value = value.split("T")[0].split(" ")[0].strip()
    if not value:
        return ""

    # Common explicit formats first.
    for fmt in (
        "%d/%m/%Y", "%d-%m-%Y", "%d.%m.%Y",
        "%Y-%m-%d", "%Y/%m/%d", "%Y.%m.%d",
        "%m/%d/%Y", "%m-%d-%Y", "%m.%d.%Y",
        "%d/%m/%y", "%d-%m-%y", "%Y%m%d",
    ):
        try:
            dt = datetime.strptime(value, fmt)
            return dt.strftime("%d/%m/%Y")
        except Exception:
            pass

    # Fallbacks for less strict incoming formats.
    try:
        dt = pd.to_datetime(value, errors="coerce", dayfirst=True)
        if pd.notna(dt):
            return dt.strftime("%d/%m/%Y")
    except Exception:
        pass
    try:
        dt = pd.to_datetime(value, errors="coerce", dayfirst=False)
        if pd.notna(dt):
            return dt.strftime("%d/%m/%Y")
    except Exception:
        pass

    return ""

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
        hgvs = row.get('HGVS', None)

        converted_row = {
            str(key): (str(value) if value is not None else "")
            for key, value in row.items()
        }
        gene  = converted_row.get('Gene', "")
        hgvsg = converted_row.get('HGVSg', "")
        hgvsc = converted_row.get('HGVSc', "")
        hgvsp = converted_row.get('HGVSp', "")
        hgvs  = converted_row.get('HGVS', "")


        data_json = json.dumps(converted_row, ensure_ascii=False).encode('utf8')
        # Convert dictionary to JSON string

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
            df = pd.read_excel(file_path, engine='openpyxl', sheet_name='Variants', header=0)
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
    """Render config page; variants table is loaded server-side via AJAX."""
    return render_template("config.html", vars_kb=[], title="Base de dades de coneixement")


@app.route('/view_config_data', methods=['GET', 'POST'])
def view_config_data():
    payload = request.form if request.method == "POST" else request.args
    draw = int(payload.get("draw", 1))
    start = int(payload.get("start", 0))
    length = int(payload.get("length", 10) or 10)
    if length <= 0:
        length = 10

    search_value = (payload.get("search[value]") or "").strip()
    order_idx = int(payload.get("order[0][column]", 0))
    order_dir = payload.get("order[0][dir]", "asc")

    q = GeneVariantSummary.query
    records_total = q.count()

    if search_value:
        s = f"%{search_value}%"
        q = q.filter(or_(
            GeneVariantSummary.gene.ilike(s),
            GeneVariantSummary.hgvsp.ilike(s),
            GeneVariantSummary.hgvsc.ilike(s),
            GeneVariantSummary.hgvsg.ilike(s),
            cast(GeneVariantSummary.data_json, String).ilike(s),
        ))

    records_filtered = q.count()

    order_map = {
        0: GeneVariantSummary.gene,
        1: GeneVariantSummary.hgvsp,
        2: GeneVariantSummary.hgvsc,
        3: GeneVariantSummary.hgvsg,
    }
    col = order_map.get(order_idx, GeneVariantSummary.id)
    q = q.order_by(col.desc() if order_dir == "desc" else col.asc())

    rows = q.offset(start).limit(length).all()
    data = []
    for var in rows:
        kb_raw = var.data_json
        if isinstance(kb_raw, bytes):
            kb_raw = kb_raw.decode("utf-8", errors="ignore")
        try:
            kb = json.loads(kb_raw or "{}")
        except Exception:
            kb = {}

        def kbv(key):
            return kb.get(key, "") or ""

        variant_id = var.id or ""
        gene = var.gene or ""
        hgvsp = var.hgvsp or ""
        hgvsc = var.hgvsc or ""
        hgvsg = var.hgvsg or ""
        cancer = kbv("Càncer")
        cgi_summary = kbv("Oncogenic summary")
        cgi_prediction = kbv("Oncogenic prediction")
        oncokb = kbv("OncoKB")
        franklin_germline = kbv("Franklin ACMG")
        franklin_somatic = kbv("Franklin Oncogenicity")
        mtbp = kbv("MTBP")
        clinvar_germline = kbv("ClinVar Germline")
        clinvar_somatic = kbv("ClinVar Somatic")
        classified_date = kbv("Data Classificació")

        actions = (
            f'<div class="btn-group btn-group-sm">'
            f'<button class="btn btn-outline-primary edit-button" '
            f'data-variant-id="{variant_id}" '
            f'data-gene="{html.escape(str(gene), quote=True)}" '
            f'data-hgvsg="{html.escape(str(hgvsg), quote=True)}" '
            f'data-hgvsc="{html.escape(str(hgvsc), quote=True)}" '
            f'data-hgvsp="{html.escape(str(hgvsp), quote=True)}" '
            f'data-cancer-type="{html.escape(str(cancer), quote=True)}" '
            f'data-cgi-summary="{html.escape(str(cgi_summary), quote=True)}" '
            f'data-cgi-prediction="{html.escape(str(cgi_prediction), quote=True)}" '
            f'data-oncokb="{html.escape(str(oncokb), quote=True)}" '
            f'data-franklin-germline="{html.escape(str(franklin_germline), quote=True)}" '
            f'data-franklin-somatic="{html.escape(str(franklin_somatic), quote=True)}" '
            f'data-mtbp="{html.escape(str(mtbp), quote=True)}" '
            f'data-clinvar-germline="{html.escape(str(clinvar_germline), quote=True)}" '
            f'data-clinvar-somatic="{html.escape(str(clinvar_somatic), quote=True)}">'
            f'Edita</button>'
            f'<button class="btn btn-outline-danger delete-button" data-variant-id="{variant_id}">Elimina</button>'
            f'</div>'
        )

        data.append([
            f"<b><i>{gene}</i></b>",
            hgvsp,
            hgvsc,
            hgvsg,
            cancer,
            cgi_summary,
            cgi_prediction,
            oncokb,
            franklin_germline,
            franklin_somatic,
            mtbp,
            clinvar_germline,
            clinvar_somatic,
            classified_date,
            actions,
        ])

    return jsonify({
        "draw": draw,
        "recordsTotal": records_total,
        "recordsFiltered": records_filtered,
        "data": data,
    })


@app.route('/download_variants_xlsx')
def download_variants_xlsx():
    """Download KB variants as XLSX with two sheets:
    - Classifications: unique variant-level classifications (no sample identifiers)
    - Sample_classifications: sample-linked classifications (with identifiers)
    """
    variants = GeneVariantSummary.query.order_by(GeneVariantSummary.gene.asc()).all()

    def _first_value(d, *keys):
        for key in keys:
            value = d.get(key)
            if value not in (None, ""):
                return value
        return ""

    def _clean_pct(v):
        if v in (None, ""):
            return ""
        s = str(v).strip()
        return s if s.endswith("%") else s

    def _lookup_tumour_purity(lab_id, ext1_id, ext2_id, run_id):
        sample = None
        if run_id and lab_id:
            sample = SampleTable.query.filter_by(run_id=run_id, lab_id=lab_id).first()
        if not sample and run_id and ext1_id:
            sample = SampleTable.query.filter_by(run_id=run_id, ext1_id=ext1_id).first()
        if not sample and run_id and ext2_id:
            sample = SampleTable.query.filter_by(run_id=run_id, ext2_id=ext2_id).first()
        if not sample and lab_id:
            sample = SampleTable.query.filter_by(lab_id=lab_id).first()
        if not sample and ext1_id:
            sample = SampleTable.query.filter_by(ext1_id=ext1_id).first()
        if not sample and ext2_id:
            sample = SampleTable.query.filter_by(ext2_id=ext2_id).first()
        return sample.tumour_purity if sample else ""

    sample_rows = []
    for variant in variants:
        raw = variant.data_json
        if isinstance(raw, bytes):
            raw = raw.decode("utf-8", errors="ignore")
        try:
            kb = json.loads(raw or "{}")
        except Exception:
            kb = {}

        lab_id = _first_value(kb, "Lab ID", "lab_id", "Patient", "Sample", "AP code", "AP_code")
        ext1_id = _first_value(kb, "Ext1 ID", "ext1_id", "AP code", "AP_code")
        ext2_id = _first_value(kb, "Ext2 ID", "ext2_id", "HC code", "HC_code")
        run_id = _first_value(kb, "RUN", "Run ID", "run_id")
        tumour_pct = _first_value(kb, "% Tumoral", "Tumour_purity", "tumour_purity", "Tumoral_pct", "tumoral_pct")
        if not tumour_pct:
            tumour_pct = _lookup_tumour_purity(lab_id, ext1_id, ext2_id, run_id)
        tumour_pct = _clean_pct(tumour_pct)

        sample_rows.append({
            "Lab ID": lab_id,
            "Ext1 ID": ext1_id,
            "Ext2 ID": ext2_id,
            "Run ID": run_id,
            "% Tumoral": tumour_pct,
            "Gene": variant.gene or "",
            "HGVSp": variant.hgvsp or "",
            "HGVSc": variant.hgvsc or "",
            "HGVSg": variant.hgvsg or "",
            "Cancer Type": _first_value(kb, "Càncer", "Cancer Type"),
            "CGI Summary": _first_value(kb, "Oncogenic summary", "CGI Summary"),
            "CGI Prediction": _first_value(kb, "Oncogenic prediction", "CGI Prediction"),
            "OncoKB": kb.get("OncoKB", ""),
            "Franklin Germline": _first_value(kb, "Franklin ACMG", "Franklin Germline"),
            "Franklin Somatic": _first_value(kb, "Franklin Oncogenicity", "Franklin Somatic"),
            "MTBP": kb.get("MTBP", ""),
            "ClinVar Germline": kb.get("ClinVar Germline", ""),
            "ClinVar Somatic": kb.get("ClinVar Somatic", ""),
            "Date": kb.get("Data Classificació", ""),
        })

    sample_df = pd.DataFrame(sample_rows)

    classification_cols = [
        "Gene",
        "HGVSp",
        "HGVSc",
        "HGVSg",
        "Cancer Type",
        "CGI Summary",
        "CGI Prediction",
        "OncoKB",
        "Franklin Germline",
        "Franklin Somatic",
        "MTBP",
        "ClinVar Germline",
        "ClinVar Somatic",
        "Date",
    ]
    classifications_df = sample_df[classification_cols].copy() if not sample_df.empty else pd.DataFrame(columns=classification_cols)
    classifications_df = classifications_df.drop_duplicates(subset=["Gene", "HGVSp", "HGVSc", "HGVSg"], keep="first")

    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        classifications_df.to_excel(writer, index=False, sheet_name="Classifications")
        sample_df.to_excel(writer, index=False, sheet_name="Sample_classifications")
    output.seek(0)

    filename = f"knowledge_variants_{date.today().isoformat()}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route('/delete_all_variants', methods=['POST'])
def delete_all_variants():
    try:
        # Delete all entries in the GeneVariantSummary table
        GeneVariantSummary.query.delete()
        db.session.commit()
        return jsonify({"success": True, "message": "S'han eliminat totes les entrades correctament"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500

@app.route('/update_variant', methods=['POST'])
def update_variant():
    try:
        variant_id = request.form.get('variant_id')
        gene = request.form.get('gene')
        hgvsg = request.form.get('hgvsg')
        hgvsc = request.form.get('hgvsc')
        hgvsp = request.form.get('hgvsp')
        cgi_summary = request.form.get('cgi_summary')
        cgi_prediction = request.form.get('cgi_prediction')
        cancer_type = request.form.get('cancer_type')
        oncokb = request.form.get('oncokb')
        franklin_germline = request.form.get('franklin_germline')
        franklin_somatic = request.form.get('franklin_somatic')
        mtbp = request.form.get('mtbp')
        clinvar_germline = request.form.get('clinvar_germline')
        clinvar_somatic = request.form.get('clinvar_somatic')

        variant = GeneVariantSummary.query.filter_by(id=variant_id).first()
        if not variant:
            return jsonify({"success": False, "message": "Variant no trobada"}), 404

        variant.gene = gene
        variant.hgvsg = hgvsg
        variant.hgvsc = hgvsc
        variant.hgvsp = hgvsp
        variant.data_json = json.dumps({
            "Oncogenic summary": cgi_summary,
            "Oncogenic prediction": cgi_prediction,
            "Càncer": cancer_type,
            "OncoKB": oncokb,
            "Franklin ACMG": franklin_germline,
            "Franklin Oncogenicity": franklin_somatic,
            "MTBP": mtbp,
            "ClinVar Germline": clinvar_germline,
            "ClinVar Somatic": clinvar_somatic,
        }, ensure_ascii=False)
        db.session.commit()
        return jsonify({"success": True, "message": "Variant actualitzada correctament"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/add_variant', methods=['POST'])
def add_variant():
    try:
        # Extract form data
        gene = request.form.get('gene')
        hgvsg = request.form.get('hgvsg')
        hgvsc = request.form.get('hgvsc')
        hgvsp = request.form.get('hgvsp')
        cancer_type = request.form.get('cancer_type')
        cgi_prediction = request.form.get('cgi_prediction')
        cgi_summary = request.form.get('cgi_summary')

        oncokb = request.form.get('oncokb')
        franklin_germline = request.form.get('franklin_germline')
        franklin_somatic = request.form.get('franklin_somatic')
        mtbp = request.form.get('mtbp')
        clinvar_germline = request.form.get('clinvar_germline')
        clinvar_somatic = request.form.get('clinvar_somatic')

        # Create a new variant record
        new_variant = GeneVariantSummary(
            gene=gene,
            hgvsg=hgvsg,
            hgvsc=hgvsc,
            hgvsp=hgvsp,
            data_json=json.dumps({
                "Càncer": cancer_type,
                "Oncogenic summary": cgi_summary,
                "Oncogenic prediction": cgi_prediction,
                "OncoKB": oncokb,
                "Franklin ACMG": franklin_germline,
                "Franklin Oncogenicity": franklin_somatic,
                "MTBP": mtbp,
                "ClinVar Germline": clinvar_germline,
                "ClinVar Somatic": clinvar_somatic
            }, ensure_ascii=False)
        )
        db.session.add(new_variant)
        db.session.commit()

        # Respond with the new variant's data
        return jsonify({
            "success": True,
            "variant": {
                "id": new_variant.id,
                "gene": new_variant.gene,
                "hgvsg": new_variant.hgvsg,
                "hgvsc": new_variant.hgvsc,
                "hgvsp": new_variant.hgvsp,
                "cancer_type": cancer_type,
                "cgi_summary": cgi_summary,
                "cgi_prediction": cgi_prediction,
                "oncokb": oncokb,
                "franklin_germline": franklin_germline,
                "franklin_somatic": franklin_somatic,
                "mtbp": mtbp,
                "clinvar_germline": clinvar_germline,
                "clinvar_somatic": clinvar_somatic
            }
        })
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500


def _norm_gene(g):
    return (g or '').upper().strip()


def _norm_hgvs(s):
    return re.sub(r'\s+', '', (s or '')).strip()


def make_variant_hash(gene, hgvsg, hgvsc, hgvsp):
    payload = {
        "gene": _norm_gene(gene),
        "hgvsg": _norm_hgvs(hgvsg),
        "hgvsc": _norm_hgvs(hgvsc),
        "hgvsp": _norm_hgvs(hgvsp),
    }
    msg = json.dumps(payload, sort_keys=True, separators=(',', ':'))
    return hashlib.sha256(msg.encode('utf-8')).hexdigest()


@app.route('/api/variant_summary', methods=['POST'])
def create_or_update_variant_summary():
    data = request.form if request.form else request.json

    gene   = data.get('kb_gene')
    hgvsg  = data.get('kb_hgvsg')
    hgvsc  = data.get('kb_hgvsc')
    hgvsp  = data.get('kb_hgvsp')

    # NEW: tumor type (prefer modal field, fallback to existing hidden)
    tumor_type = (data.get('modal_edit_tumor_origin')
                  or data.get('tumor_origin')
                  or "")

    # Date: prefer incoming DD-MM-YYYY; else default to today (Europe/Madrid) in DD-MM-YYYY
    date_in = (data.get('data_classificacio') or '').strip()
    if not date_in:
        today_es = datetime.now(ZoneInfo("Europe/Madrid"))
        date_in = today_es.strftime("%d-%m-%Y")  # DD-MM-YYYY

    if not gene: 
        return jsonify({"status": "ERROR", "id": "missing gene info", "kb": f"{gene}"}), 400

    if not hgvsg: 
        return jsonify({"status": "ERROR", "id": "missing hgvsg info", "kb": f"{hgvsg}"}), 400

    if not hgvsc: 
        return jsonify({"status": "ERROR", "id": "missing hgvsc info", "kb": f"{hgvsc}"}), 400

    if not hgvsp: 
        return jsonify({"status": "ERROR", "id": "missing hgvsp info", "kb": f"{hgvsp}"}), 400

    curated_fields = {
        "Oncogenic summary":     data.get('oncogenic_summary') or "",
        "Oncogenic prediction":  data.get('oncogenic_prediction') or "",
        "ClinVar Germline":      data.get('clinvar_germline') or "",
        "ClinVar Somatic":       data.get('clinvar_somatic') or "",
        "OncoKB":                data.get('oncokb_class') or "",
        "Franklin ACMG":         data.get('franklin_acmg') or "",
        "Franklin Oncogenicity": data.get('franklin_oncogenicity') or "",
        "MTBP":                  data.get('mtbp') or "",
        "Comentaris":            data.get('comentaris') or "",
        "Data Classificació":    date_in,          # keep DD-MM-YYYY
        "Especialista":          data.get('especialista') or "",
    }

    run_id = data.get('run_id')
    sample = data.get('sample')

    data_json = {
        "Patient": sample or "",
        "Càncer": tumor_type,                     # <-- NEW
        "RUN": run_id or "",
        "Data RUN": data.get('data_run') or "",
        "Gene": gene,
        "Isoforma": data.get('isoform') or "",
        "HGVSp": hgvsp,
        "HGVSg": hgvsg,
        "HGVSc": hgvsc,
        "Effecte": data.get('effecte') or "",
        **curated_fields
    }
    try:
        vhash = make_variant_hash(gene, hgvsg, hgvsc, hgvsp)
    except:
        return jsonify({"status": "ERROR", "id": "make_variant_hash", "kb": curated_fields}), 400
    else:
        pass

    existing = GeneVariantSummary.query.filter_by(hash=vhash).first()
    if existing:
        existing.gene = gene
        existing.hgvsg = hgvsg
        existing.hgvsc = hgvsc
        existing.hgvsp = hgvsp
        existing.data_json = json.dumps(data_json, ensure_ascii=False)
        db.session.commit()
        status, gvs_id = "updated", existing.id
    else:
        try:
            new = GeneVariantSummary(
                gene=gene, hgvsg=hgvsg, hgvsc=hgvsc, hgvsp=hgvsp,
                data_json=json.dumps(data_json, ensure_ascii=False),
                hash=vhash,
            )
            db.session.add(new)
            db.session.commit()
            status, gvs_id = "created", new.id
        except:
            return jsonify({"status": "Error while introducing a new variant", "id": "Error while introducing a new variant", "kb": curated_fields}), 400
        else:
            pass

    response_kb = dict(curated_fields)
    response_kb["Càncer"] = tumor_type
    return jsonify({"status": status, "id": gvs_id, "kb": response_kb}), 200


############# Petitions

@app.route('/delete_variant/<int:variant_id>', methods=['DELETE'])
def delete_variant(variant_id):
    try:
        variant = GeneVariantSummary.query.get(variant_id)
        if not variant:
            return jsonify({"success": False, "message": "Variant no trobada"}), 404

        db.session.delete(variant)
        db.session.commit()
        return jsonify({"success": True, "message": "Variant eliminada"})
    except Exception as e:
        db.session.rollback()
        return jsonify({"success": False, "message": str(e)}), 500


@app.route('/petition_menu')
def petition_menu():
    '''
    '''
    return render_template("create_petition.html", title="Nova petició")


@app.route('/download_all_petitions_xlsx', methods=['GET'])
def download_all_petitions_xlsx():
    rows = Petition.query.order_by(Petition.Id.desc()).all()
    data = [{
        "ID": p.Id or "",
        "Petition ID": p.Petition_id or "",
        "Date": _normalize_date_ddmmyyyy(p.Date),
        "Petition Date": _normalize_date_ddmmyyyy(p.Petition_date),
        "Tumour Origin": p.Tumour_origin or "",
        "AP Code": p.AP_code or "",
        "HC Code": p.HC_code or "",
        "CIP Code": p.CIP_code or "",
        "Tumour %": p.Tumour_pct or "",
        "Volume": p.Volume or "",
        "Conc Nanodrop": p.Conc_nanodrop or "",
        "Ratio Nanodrop": p.Ratio_nanodrop or "",
        "Tape Postevaluation": p.Tape_postevaluation or "",
        "Medical Doctor": p.Medical_doctor or "",
        "Billing Unit": p.Billing_unit or "",
        "Medical Indication": p.Medical_indication or "",
        "Date Original Biopsy": _normalize_date_ddmmyyyy(p.Date_original_biopsy),
        "Service": p.Service or "",
        "Sample Block": p.Sample_block or "",
        "Sex": p.Sex or "",
        "Age": p.Age or "",
        "Modulab ID": p.Modulab_id or "",
    } for p in rows]

    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="Petitions")
    output.seek(0)

    filename = f"petitions_{date.today().isoformat()}.xlsx"
    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )


@app.route('/petition_menu_data', methods=['GET', 'POST'])
def petition_menu_data():
    payload = request.form if request.method == "POST" else request.args
    draw = int(payload.get("draw", 1))
    start = int(payload.get("start", 0))
    length = int(payload.get("length", 10) or 10)
    if length <= 0:
        length = 10

    search_value = (payload.get("search[value]") or "").strip()
    order_idx = int(payload.get("order[0][column]", 0))
    order_dir = payload.get("order[0][dir]", "asc")

    q = Petition.query
    records_total = q.count()

    if search_value:
        s = f"%{search_value}%"
        q = q.filter(or_(
            cast(Petition.Id, String).ilike(s),
            Petition.Tumour_origin.ilike(s),
            Petition.CIP_code.ilike(s),
            Petition.AP_code.ilike(s),
            Petition.HC_code.ilike(s),
            Petition.Date.ilike(s),
            Petition.Date_original_biopsy.ilike(s),
            Petition.Petition_date.ilike(s),
            Petition.Tumour_pct.ilike(s),
            Petition.Medical_doctor.ilike(s),
            Petition.Billing_unit.ilike(s),
        ))

    records_filtered = q.count()

    order_map = {
        0: Petition.Id,
        1: Petition.Tumour_origin,
        2: Petition.CIP_code,
        3: Petition.AP_code,
        4: Petition.HC_code,
        5: Petition.Date,
        6: Petition.Date_original_biopsy,
        7: Petition.Petition_date,
        8: Petition.Tumour_pct,
    }
    col = order_map.get(order_idx, Petition.Id)
    q = q.order_by(col.desc() if order_dir == "desc" else col.asc())

    rows = q.offset(start).limit(length).all()
    data = []
    for p in rows:
        p_id = p.Id or ""
        tumour_origin = p.Tumour_origin or ""
        cip_code = p.CIP_code or ""
        ap_code = p.AP_code or ""
        hc_code = p.HC_code or ""
        extraction_date = _normalize_date_ddmmyyyy(p.Date)
        petition_date = _normalize_date_ddmmyyyy(p.Petition_date)
        biopsy_date = _normalize_date_ddmmyyyy(p.Date_original_biopsy)
        tumour_pct = p.Tumour_pct or ""
        medical_doctor = p.Medical_doctor or ""
        billing_unit = p.Billing_unit or ""

        actions = (
            f'<a role="button" onclick="updatePetition(this);" '
            f'data-petition-id="{p_id}" '
            f'data-tumour-origin="{html.escape(str(tumour_origin), quote=True)}" '
            f'data-cip-code="{html.escape(str(cip_code), quote=True)}" '
            f'data-ap-code="{html.escape(str(ap_code), quote=True)}" '
            f'data-hc-code="{html.escape(str(hc_code), quote=True)}" '
            f'data-extraction-date="{html.escape(str(extraction_date), quote=True)}" '
            f'data-petition-date="{html.escape(str(petition_date), quote=True)}" '
            f'data-biopsy-date="{html.escape(str(biopsy_date), quote=True)}" '
            f'data-tumour-pct="{html.escape(str(tumour_pct), quote=True)}" '
            f'data-medical-doctor="{html.escape(str(medical_doctor), quote=True)}" '
            f'data-billing-unit="{html.escape(str(billing_unit), quote=True)}">'
            f'<i class="fas fa-edit fa-lg" style="color:rgb(109, 106, 106)"></i></a> '
            f'<a role="button" onclick="removePetition(this);" data-petition-id="{p_id}">'
            f'<i class="fas fa-trash fa-lg" style="color: rgba(209, 20, 20, 0.938)"></i></a>'
        )

        data.append([
            p_id,
            tumour_origin,
            cip_code,
            f"<b>{ap_code}</b>",
            hc_code,
            extraction_date,
            biopsy_date,
            petition_date,
            tumour_pct,
            actions,
        ])

    return jsonify({
        "draw": draw,
        "recordsTotal": records_total,
        "recordsFiltered": records_filtered,
        "data": data,
    })

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
                        Date=_normalize_date_ddmmyyyy(extraction_date), Petition_date=_normalize_date_ddmmyyyy(Petition_date), Tumour_origin=tumour_type,
                        AP_code=ap_code, HC_code=hc_code, CIP_code=CIP_code, Sample_block=ap_block,
                        Tumour_pct=tumour_pct, Volume=res_volume, Conc_nanodrop=nanodrop_conc,
                        Ratio_nanodrop=nanodrop_ratio,Tape_postevaluation=post_tape_eval,
                        Medical_doctor=physician_name,Billing_unit=billing_unit,
                        Medical_indication=tumour_type, Date_original_biopsy=_normalize_date_ddmmyyyy(Date_original_biopsy),
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
                        Date=_normalize_date_ddmmyyyy(extraction_date), Petition_date=_normalize_date_ddmmyyyy(Petition_date), Tumour_origin=tumour_type,
                        AP_code=ap_code, HC_code=hc_code, CIP_code=CIP_code, Sample_block=ap_block,
                        Tumour_pct=tumour_pct, Volume=res_volume, Conc_nanodrop=nanodrop_conc,
                        Ratio_nanodrop=nanodrop_ratio,Tape_postevaluation=post_tape_eval,
                        Medical_doctor=physician_name,Billing_unit=billing_unit,
                        Medical_indication=tumour_type, Date_original_biopsy=_normalize_date_ddmmyyyy(Date_original_biopsy), Age=age, Sex=sex, Service=Peticionari)

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

                            petition = Petition( Petition_id=Petition_id, User_id=".", Date=_normalize_date_ddmmyyyy(date),
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

        cip_code = ""
        if request.form.get('CIP_code'):
            cip_code = request.form['CIP_code']

        tumour_origin = ""
        if request.form.get('Tumour_origin'):
            tumour_origin = request.form['Tumour_origin']

        date = ""
        if request.form.get('Date'):
            date = _normalize_date_ddmmyyyy(request.form['Date'])
            if not date:
                flash("El format de la data és incorrecte. Hauria de seguir el format dd/mm/yyyy", "warning")
                is_ok = False
        else:
            errors.append("Es requereix la data d'extracció")
            flash("Es requereix la data d'extracció", "warning")
            is_ok = False

        petition_date = ""
        if request.form.get('Petition_date'):
            petition_date = _normalize_date_ddmmyyyy(request.form['Petition_date'])
            if request.form.get('Petition_date') and not petition_date:
                flash("El format de la data de petició és incorrecte. Hauria de seguir el format dd/mm/yyyy", "warning")
                is_ok = False

        date_original_biopsy = ""
        if request.form.get('Date_original_biopsy'):
            date_original_biopsy = _normalize_date_ddmmyyyy(request.form['Date_original_biopsy'])
            if request.form.get('Date_original_biopsy') and not date_original_biopsy:
                flash("El format de la data origen biòpsia és incorrecte. Hauria de seguir el format dd/mm/yyyy", "warning")
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
            Medical_doctor=medical_doctor, Tape_postevaluation=tape_posteval, Billing_unit=billing_unit,
            Petition_date=petition_date, Date_original_biopsy=date_original_biopsy,
            Tumour_origin=tumour_origin, CIP_code=cip_code, Medical_indication=".",
            Service=".", Sample_block=".", Sex=".", Age=".", Modulab_id=".")

            db.session.add(petition)
            db.session.commit()
            msg = "S'ha enregistrat correctament la petició " + Petition_id
            flash(msg, "success")

    All_petitions = Petition.query.all()

    return render_template("create_petition.html", title="Nova petició", petitions=All_petitions, errors=errors)

@app.route('/update_petition', methods = ['GET', 'POST'])
#@login_required
def update_petition():
    errors = []
    if request.method == "POST":
        petition_id = (request.form.get("edit_petition_id") or "").strip()
        ap_code = (request.form.get("edit_ap_code") or "").strip()
        hc_code = (request.form.get("edit_hc_code") or "").strip()
        cip_code = (request.form.get("edit_cip_code") or "").strip()
        tumour_pct = (request.form.get("edit_tumoral_pct") or "").strip()
        tumour_origin = (request.form.get("edit_origin_tumor") or "").strip()
        medical_doctor = (request.form.get("edit_medical_doctor") or "").strip()
        billing_unit = (request.form.get("edit_billing_unit") or "").strip()
        extraction_date = (request.form.get("edit_extraction_date") or "").strip()
        petition_date = (request.form.get("edit_petition_date") or "").strip()
        biopsy_date = (request.form.get("edit_biopsy_petition_date") or "").strip()

        if not petition_id:
            flash("No s'ha trobat l'identificador de la petició", "warning")
            All_petitions = Petition.query.all()
            return render_template("create_petition.html", title="Nova petició", petitions=All_petitions, errors=errors)

        petition = Petition.query.filter_by(Id=petition_id).first()
        if not petition:
            flash("No s'ha trobat la petició a editar", "warning")
            All_petitions = Petition.query.all()
            return render_template("create_petition.html", title="Nova petició", petitions=All_petitions, errors=errors)

        old_ap_code = petition.AP_code or ""

        petition.AP_code = ap_code
        petition.HC_code = hc_code
        petition.CIP_code = cip_code
        petition.Tumour_origin = tumour_origin
        petition.Billing_unit = billing_unit
        petition.Medical_doctor = medical_doctor
        petition.Tumour_pct = tumour_pct
        if extraction_date:
            normalized_extraction_date = _normalize_date_ddmmyyyy(extraction_date)
            if normalized_extraction_date:
                petition.Date = normalized_extraction_date
        if petition_date:
            normalized_petition_date = _normalize_date_ddmmyyyy(petition_date)
            if normalized_petition_date:
                petition.Petition_date = normalized_petition_date
        if biopsy_date:
            normalized_biopsy_date = _normalize_date_ddmmyyyy(biopsy_date)
            if normalized_biopsy_date:
                petition.Date_original_biopsy = normalized_biopsy_date

        sample = SampleTable.query.filter_by(ext1_id=old_ap_code).first()
        if not sample and ap_code:
            sample = SampleTable.query.filter_by(ext1_id=ap_code).first()
        if sample:
            sample.ext1_id = ap_code
            sample.ext2_id = hc_code
            sample.ext3_id = cip_code
            sample.diagnosis = tumour_origin
            sample.physician_name = medical_doctor
            sample.medical_center = billing_unit

        db.session.commit()
        flash("S'ha actualitzat correctament la petició", "success")

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
