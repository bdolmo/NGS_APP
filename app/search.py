from app import app, db

from flask import Flask
from flask import request, render_template, url_for, redirect, flash, session, jsonify, send_file
from flask_wtf import FlaskForm
import sqlite3
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from sqlalchemy.sql import and_, or_
from sqlalchemy import func, literal, cast, Float, union_all
from flask_sqlalchemy import SQLAlchemy
from flask_sslify import SSLify
from collections import defaultdict,OrderedDict
import operator
import redis
import os
import time
import datetime
from datetime import date
import pandas as pd
import docx
import re
import json
from io import BytesIO
import plotly
import plotly.graph_objs as go
import plotly.express as px
from plotly.subplots import make_subplots
from app.models import Job, VersionControl, SampleTable, SampleVariants, Variants, TherapeuticTable, OtherVariantsTable, RareVariantsTable, BiomakerTable, SummaryQcTable, DisclaimersTable, AllCnas

CNV_VARIANT_TYPES = {"amplification", "cna", "cnv", "loss"}
SV_VARIANT_TYPES = {"sv", "fusion", "fusions"}

@app.route('/')
@app.route('/search_menu')
def search_menu():
    tumor_rows = (SampleTable.query
        .with_entities(SampleTable.tumor_origin)
        .distinct()
        .all())
    tumor_origins = sorted([t[0] for t in tumor_rows if t and t[0]])
    sex_rows = (SampleTable.query
        .with_entities(SampleTable.Sex)
        .distinct()
        .all())
    sex_options = []
    seen_sex = set()
    for row in sex_rows:
        if not row:
            continue
        raw_value = row[0] or ""
        normalized_value = raw_value.strip()
        if not normalized_value:
            continue
        lowered_value = normalized_value.lower()
        if lowered_value in {".", "none"}:
            continue
        display_value = lowered_value.capitalize()
        if display_value in seen_sex:
            continue
        seen_sex.add(display_value)
        sex_options.append(display_value)
    sex_options.sort()
    return render_template("search.html", title="Nova cerca", tumor_origins=tumor_origins, sex_options=sex_options)

class Variant:

    def __init__(self,sample_id,lab_id,ext1_id,ext2_id,tumour_purity,run_id,gene,exon,
        intron,isoform,hgvsg,hgvsc,hgvsp,vartype,read_support,depth,allele_frequency,consequence,classification):
        self.sample_id = sample_id
        self.lab_id = lab_id
        self.ext1_id= ext1_id
        self.ext2_id= ext2_id
        self.tumour_purity= tumour_purity

        self.run_id = run_id
        self.gene   = gene
        self.exon   = exon
        self.intron = intron
        self.isoform= isoform
        self.hgvsg  = hgvsg
        self.hgvsc  = hgvsc
        self.hgvsp  = hgvsp
        self.vartype= vartype
        self.read_support = read_support
        self.depth = depth
        self.allele_frequency = allele_frequency
        self.consequence = consequence
        self.classification = classification


def pie_plot_variants(variants_list):

  genes_dict    = defaultdict(dict)
  most_common_dict  = defaultdict(dict)
  for var in variants_list:
    gene = var.gene

    if not gene in genes_dict:
        genes_dict[gene] = 0
    genes_dict[gene] += 1

    gene_variant = gene + ":" + var.hgvsp
    if not gene_variant in most_common_dict:
      most_common_dict[gene_variant] = 0
    most_common_dict[gene_variant] += 1

  labels_list = []
  for gene in genes_dict:

    labels_list.append(gene)
  values_list = []
  for gene in genes_dict:
    values_list.append(genes_dict[gene])

  # colors =
  layout= go.Layout (
    width=510,
    height=350,
    margin=dict(l=0, r=0, b=0, t=0 )
  )
  fig = go.Figure(data=[go.Pie(labels=labels_list,
  values=values_list,hole=.35, opacity=0.85)], layout=layout )
  fig.update_layout(
    #title = "Localització/Efecte de les variants"
  )
  fig.update_traces(
    textposition='inside',
    marker=dict(line=dict(color='#000000', width=1))
  )
  graphJSONpie = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

  most_common_dict = OrderedDict(sorted(most_common_dict.items(),
    key=operator.itemgetter(1), reverse=True))

  labels_list = []
  n = 0
  for label in most_common_dict:
    if n >= 10:
        break

    n+=1
    labels_list.append(label)
  values_list = []
  n = 0
  for label in most_common_dict:
    if n >= 10:
        break
    n+=1
    values_list.append(most_common_dict[label])
  layout= go.Layout (
    paper_bgcolor= 'rgba(0,0,0,0)',
    plot_bgcolor = 'rgba(0,0,0,0)',
    width=370,
    height=270,
    margin=dict(l=0, r=0, b=0, t=0 )
  )
  fig = go.Figure(data=[go.Bar(y=labels_list, x=values_list,
   marker_color='rgba(110,171,245,0.9)',
  marker_line_color='black', orientation='h')], layout=layout)
  fig.update_layout(
    xaxis={'categoryorder':'total descending'}
    #xaxis_title="Tipus",
    #yaxis_title="Total",
    #title = "Tipus de variants"
  )
  fig.update_yaxes(showline=True, linewidth=1, linecolor='black', mirror=False)
  fig.update_xaxes(showline=True, linewidth=1, linecolor='black', mirror=False)
  graphJSONbar = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)


  return graphJSONpie,graphJSONbar

def _to_ddmmyyyy(raw):
    if not raw:
        return ""
    raw = raw.strip()
    for fmt in ("%d/%m/%Y", "%Y-%m-%d"):
        try:
            return datetime.datetime.strptime(raw, fmt).strftime("%d/%m/%Y")
        except Exception:
            continue
    return ""


def _build_criteria(form):
    c = {
        "lab_id": (form.get("lab_id") or "").strip(),
        "ext1_id": (form.get("ext1_id") or "").strip(),
        "ext2_id": (form.get("ext2_id") or "").strip(),
        "run_id": (form.get("run_id") or "").strip(),
        "tumor_origin": (form.get("tumor_origin") or "").strip(),
        "sex": (form.get("sex") or "").strip(),
        "age": (form.get("age") or "").strip(),
        "tumour_purity": (form.get("tumour_purity") or "").strip(),
        "initial_date": _to_ddmmyyyy(form.get("initial_date")),
        "final_date": _to_ddmmyyyy(form.get("final_date")),
        "gene": (form.get("gene") or "").strip(),
        "isoform": (form.get("isoform") or "").strip(),
        "exon": (form.get("exon") or "").strip(),
        "hgvsg": (form.get("hgvsg") or "").strip(),
        "hgvsc": (form.get("hgvsc") or "").strip(),
        "hgvsp": (form.get("hgvsp") or "").strip(),
        "dump_cnv": bool(form.get("filter_cnv")),
        "dump_sv": bool(form.get("filter_sv")),
        "dump_tier1": bool(form.get("tier_1")),
        "dump_tier2": bool(form.get("tier_2")),
        "dump_tier3": bool(form.get("tier_3")),
    }
    sample_filters = [
        "lab_id",
        "ext1_id",
        "ext2_id",
        "run_id",
        "tumor_origin",
        "sex",
        "age",
        "tumour_purity",
        "initial_date",
        "final_date",
    ]
    # Variant mode should be driven by explicit gene/variant criteria only.
    # Sample fields can optionally constrain the returned variants.
    variant_filters = ["gene", "isoform", "exon", "hgvsg", "hgvsc", "hgvsp"]
    has_sample_filters = False
    for key in sample_filters:
        if c[key]:
            has_sample_filters = True
            break

    has_variant_filters = False
    for key in variant_filters:
        if c[key]:
            has_variant_filters = True
            break
    if c["dump_cnv"] or c["dump_sv"]:
        has_variant_filters = True

    all_tiers_checked = c["dump_tier1"] and c["dump_tier2"] and c["dump_tier3"]
    any_tier_checked = c["dump_tier1"] or c["dump_tier2"] or c["dump_tier3"]
    tier_only_intent = any_tier_checked and not all_tiers_checked

    # Variant mode can be triggered by explicit gene/variant fields, or by
    # explicitly narrowing classification tiers (e.g. only "Altres variants rares").
    variant_intent = has_variant_filters or tier_only_intent

    # If user is doing a variant search but leaves all class checkboxes empty,
    # treat it as selecting all classes.
    if variant_intent and not (c["dump_tier1"] or c["dump_tier2"] or c["dump_tier3"]):
        c["dump_tier1"] = True
        c["dump_tier2"] = True
        c["dump_tier3"] = True

    c["show_samples"] = has_sample_filters
    c["show_variants"] = variant_intent
    c["mode"] = "variants" if c["show_variants"] else "samples"
    return c


def _apply_sample_filters(query, criteria):
    if criteria["lab_id"]:
        query = query.filter(SampleTable.lab_id.ilike(f"%{criteria['lab_id']}%"))
    if criteria["run_id"]:
        query = query.filter(SampleTable.run_id.ilike(f"%{criteria['run_id']}%"))
    if criteria["ext1_id"]:
        query = query.filter(SampleTable.ext1_id.ilike(f"%{criteria['ext1_id']}%"))
    if criteria["ext2_id"]:
        query = query.filter(SampleTable.ext2_id.ilike(f"%{criteria['ext2_id']}%"))
    if criteria["tumor_origin"]:
        query = query.filter(SampleTable.tumor_origin.ilike(f"%{criteria['tumor_origin']}%"))
    if criteria["sex"]:
        normalized_sex = criteria["sex"].strip().lower()
        query = query.filter(or_(
            func.lower(func.trim(SampleTable.Sex)) == normalized_sex,
            func.lower(func.trim(SampleTable.sex)) == normalized_sex,
        ))
    if criteria["age"]:
        normalized_age = criteria["age"].strip()
        query = query.filter(func.trim(SampleTable.Age) == normalized_age)
    if criteria["tumour_purity"]:
        try:
            p = max(0.0, min(100.0, float(criteria["tumour_purity"])))
            purity_num = cast(func.replace(func.trim(SampleTable.tumour_purity), "%", ""), Float)
            query = query.filter(purity_num == p)
        except Exception:
            pass
    if criteria["initial_date"] and criteria["final_date"]:
        initial_sql = datetime.datetime.strptime(criteria["initial_date"], "%d/%m/%Y").strftime("%Y-%m-%d")
        final_sql = datetime.datetime.strptime(criteria["final_date"], "%d/%m/%Y").strftime("%Y-%m-%d")
        sample_dt = func.printf(
            "%s-%s-%s",
            func.substr(SampleTable.analysis_date, 7, 4),
            func.substr(SampleTable.analysis_date, 4, 2),
            func.substr(SampleTable.analysis_date, 1, 2),
        )
        query = query.filter(sample_dt >= initial_sql, sample_dt <= final_sql)
    return query


@app.route('/advanced_search', methods = ['GET', 'POST'])
def advanced_search():
    if request.method == "GET":
        criteria = session.get("advanced_search_criteria")
        if criteria:
            return render_template(
                "search_results.html",
                title="Resultats cerca",
                search_mode=criteria.get("mode", "samples"),
                p_variants="",
                m_plot="",
            )
        return redirect(url_for('search_menu'))

    criteria = _build_criteria(request.form)
    if criteria["isoform"] and not criteria["gene"]:
        flash("No s'ha entrat el nom del gen", "warning")
        return redirect(url_for('search_menu'))
    if criteria["initial_date"] and not criteria["final_date"]:
        flash("Es requereix una data final", "warning")
        return redirect(url_for('search_menu'))
    if criteria["final_date"] and not criteria["initial_date"]:
        flash("Es requereix una data inicial", "warning")
        return redirect(url_for('search_menu'))
    if criteria["initial_date"] and criteria["final_date"]:
        i_dt = datetime.datetime.strptime(criteria["initial_date"], "%d/%m/%Y")
        f_dt = datetime.datetime.strptime(criteria["final_date"], "%d/%m/%Y")
        if i_dt > f_dt:
            flash("La data inicial és major que la data final", "warning")
            return redirect(url_for('search_menu'))
    session["advanced_search_criteria"] = criteria
    return render_template("search_results.html", title="Resultats cerca", search_mode=criteria["mode"], p_variants="", m_plot="")


@app.route('/advanced_search_data', methods=['GET', 'POST'])
def advanced_search_data():
    payload = request.form if request.method == "POST" else request.args
    draw = int(payload.get("draw", 1))
    try:
        criteria = session.get("advanced_search_criteria")
        if not criteria:
            return jsonify({"draw": draw, "recordsTotal": 0, "recordsFiltered": 0, "data": []})

        start = int(payload.get("start", 0))
        length = int(payload.get("length", 10) or 10)
        if length <= 0:
            length = 10
        search_value = (payload.get("search[value]") or "").strip()
        order_idx = int(payload.get("order[0][column]", 0))
        order_dir = payload.get("order[0][dir]", "asc")

        if criteria.get("mode") == "samples":
            return _advanced_search_samples(draw, start, length, search_value, order_idx, order_dir, criteria)
        return _advanced_search_variants(draw, start, length, search_value, order_idx, order_dir, criteria)
    except Exception as e:
        print(f"[advanced_search_data] ERROR: {e}")
        return jsonify({
            "draw": draw,
            "recordsTotal": 0,
            "recordsFiltered": 0,
            "data": [],
            "error": str(e),
        })


def _advanced_search_samples(draw, start, length, search_value, order_idx, order_dir, criteria):
    q = _apply_sample_filters(SampleTable.query, criteria)
    records_total = q.count()

    if search_value:
        s = f"%{search_value}%"
        q = q.filter(or_(
            SampleTable.lab_id.ilike(s),
            SampleTable.ext1_id.ilike(s),
            SampleTable.ext2_id.ilike(s),
            SampleTable.tumor_origin.ilike(s),
            SampleTable.tumour_purity.ilike(s),
            SampleTable.run_id.ilike(s),
            SampleTable.panel.ilike(s),
            SampleTable.subpanel.ilike(s),
            SampleTable.analysis_date.ilike(s),
        ))
    records_filtered = q.count()

    order_map = {
        0: SampleTable.lab_id,
        1: SampleTable.ext1_id,
        2: SampleTable.ext2_id,
        3: SampleTable.tumor_origin,
        4: SampleTable.tumour_purity,
        5: SampleTable.run_id,
        6: SampleTable.panel,
        7: SampleTable.analysis_date,
    }
    col = order_map.get(order_idx, SampleTable.lab_id)
    q = q.order_by(col.desc() if order_dir == "desc" else col.asc())

    rows = q.offset(start).limit(length).all()
    data = []
    for sample in rows:
        sample_link = url_for('show_sample_details', run_id=sample.run_id, sample=sample.lab_id, sample_id=sample.id, active='General')
        run_link = url_for('show_run_details', run_id=sample.run_id) if sample.run_id else ""
        bam_link = url_for('download_sample_bam', run_id=sample.run_id, sample=sample.lab_id)
        bai_link = url_for('download_sample_bai', run_id=sample.run_id, sample=sample.lab_id)
        vcf_link = url_for('download_sample_vcf', run_id=sample.run_id, sample=sample.lab_id)
        report_link = url_for('download_report', run_id=sample.run_id, sample=sample.lab_id)
        data.append([
            f'<a href="{sample_link}"><b>{sample.lab_id}</b></a>',
            sample.ext1_id or "",
            sample.ext2_id or "",
            sample.tumor_origin or "",
            sample.tumour_purity or "",
            f'<a href="{run_link}"><b>{sample.run_id}</b></a>' if sample.run_id else "",
            " / ".join([x for x in [sample.panel, sample.subpanel] if x]) if (sample.panel or sample.subpanel) else "",
            sample.analysis_date or "",
            (
                f'<a href="{bam_link}" class="btn btn-outline-secondary btn-sm m-1">BAM</a>'
                f'<a href="{bai_link}" class="btn btn-outline-secondary btn-sm m-1">BAI</a>'
                f'<a href="{vcf_link}" class="btn btn-outline-primary btn-sm m-1">VCF</a>'
                f'<a href="{report_link}" class="btn btn-outline-danger btn-sm m-1">Report</a>'
            ),
        ])

    return jsonify({"draw": draw, "recordsTotal": records_total, "recordsFiltered": records_filtered, "data": data})


def _tier_variant_query(model, classification, criteria):
    q = db.session.query(
        SampleTable.id.label("sample_id"),
        SampleTable.lab_id.label("lab_id"),
        SampleTable.ext1_id.label("ext1_id"),
        SampleTable.ext2_id.label("ext2_id"),
        SampleTable.tumor_origin.label("tumor_origin"),
        SampleTable.tumour_purity.label("tumour_purity"),
        SampleTable.run_id.label("run_id"),
        model.gene.label("gene"),
        model.enst_id.label("isoform"),
        model.hgvsp.label("hgvsp"),
        model.hgvsg.label("hgvsg"),
        model.hgvsc.label("hgvsc"),
        model.variant_type.label("vartype"),
        model.read_support.label("read_support"),
        model.depth.label("depth"),
        model.allele_frequency.label("allele_frequency"),
        model.consequence.label("consequence"),
        model.exon.label("exon"),
        literal(classification).label("classification"),
    ).join(
        SampleTable,
        and_(
            model.lab_id == SampleTable.lab_id,
            model.run_id == SampleTable.run_id,
        ),
    )

    q = _apply_sample_filters(q, criteria)
    if criteria["gene"]:
        q = q.filter(model.gene.ilike(f"%{criteria['gene']}%"))
    if criteria["isoform"]:
        q = q.filter(model.enst_id.ilike(f"%{criteria['isoform']}%"))
    if criteria["hgvsp"]:
        q = q.filter(model.hgvsp.ilike(f"%{criteria['hgvsp']}%"))
    if criteria["hgvsg"]:
        q = q.filter(model.hgvsg.ilike(f"%{criteria['hgvsg']}%"))
    if criteria["hgvsc"]:
        q = q.filter(model.hgvsc.ilike(f"%{criteria['hgvsc']}%"))
    if criteria["exon"]:
        q = q.filter(model.exon.ilike(f"%{criteria['exon']}%"))

    normalized_variant_type = func.lower(func.trim(model.variant_type))
    selected_variant_types = set()
    if criteria["dump_cnv"]:
        selected_variant_types.update(CNV_VARIANT_TYPES)
    if criteria["dump_sv"]:
        selected_variant_types.update(SV_VARIANT_TYPES)
    if selected_variant_types:
        q = q.filter(normalized_variant_type.in_(sorted(selected_variant_types)))
    return q


def _advanced_search_variants(draw, start, length, search_value, order_idx, order_dir, criteria):
    include_t1 = criteria["dump_tier1"]
    include_t2 = criteria["dump_tier2"]
    include_t3 = criteria["dump_tier3"]
    if not include_t1 and not include_t2 and not include_t3:
        include_t1 = include_t2 = include_t3 = True

    qs = []
    if include_t1:
        qs.append(_tier_variant_query(TherapeuticTable, "Therapeutic", criteria))
    if include_t2:
        qs.append(_tier_variant_query(OtherVariantsTable, "Other", criteria))
    if include_t3:
        qs.append(_tier_variant_query(RareVariantsTable, "Rare", criteria))

    if not qs:
        return jsonify({"draw": draw, "recordsTotal": 0, "recordsFiltered": 0, "data": []})

    # Use statement-level UNION ALL so labeled columns are preserved in subquery
    # (ORM Query.union_all can produce anonymous column names).
    union_stmt = union_all(*[q.statement for q in qs])

    sq = union_stmt.subquery()
    q = db.session.query(sq)
    records_total = q.count()

    if search_value:
        s = f"%{search_value}%"
        q = q.filter(or_(
            sq.c.lab_id.ilike(s),
            sq.c.ext1_id.ilike(s),
            sq.c.ext2_id.ilike(s),
            sq.c.tumor_origin.ilike(s),
            sq.c.run_id.ilike(s),
            sq.c.gene.ilike(s),
            sq.c.isoform.ilike(s),
            sq.c.hgvsp.ilike(s),
            sq.c.hgvsg.ilike(s),
            sq.c.hgvsc.ilike(s),
            sq.c.vartype.ilike(s),
            sq.c.consequence.ilike(s),
            sq.c.classification.ilike(s),
        ))
    records_filtered = q.count()

    order_map = {
        0: sq.c.lab_id,
        1: sq.c.ext1_id,
        2: sq.c.ext2_id,
        3: sq.c.tumor_origin,
        4: sq.c.tumour_purity,
        5: sq.c.run_id,
        6: sq.c.gene,
        7: sq.c.hgvsp,
        8: sq.c.exon,
        9: cast(sq.c.read_support, Float),
        10: cast(sq.c.depth, Float),
        11: cast(sq.c.allele_frequency, Float),
        12: sq.c.vartype,
        13: sq.c.consequence,
        14: sq.c.classification,
    }
    col = order_map.get(order_idx, sq.c.lab_id)
    q = q.order_by(col.desc() if order_dir == "desc" else col.asc())

    rows = q.offset(start).limit(length).all()
    data = []
    for var in rows:
        sample_link = url_for('show_sample_details', run_id=var.run_id, sample=var.lab_id, sample_id=var.sample_id, active='General')
        run_link = url_for('show_run_details', run_id=var.run_id) if var.run_id else ""
        badge = ""
        class_label = ""
        if var.classification == "Therapeutic":
            badge = '<span class="badge badge-danger" title="Variant accionable">Variant accionable</span>'
            class_label = "Variant accionable"
        elif var.classification == "Other":
            badge = "<span class=\"badge badge-warning\" title=\"Variant d'alt impacte\">Variant d'alt impacte</span>"
            class_label = "Variant d'alt impacte"
        elif var.classification == "Rare":
            badge = '<span class="badge badge-dark" title="Altres variants rares">Altres variants rares</span>'
            class_label = "Altres variants rares"
        data.append([
            f'<a href="{sample_link}"><b>{var.lab_id}</b></a>',
            var.ext1_id or "",
            var.ext2_id or "",
            var.tumor_origin or "",
            var.tumour_purity or "",
            f'<a href="{run_link}"><b>{var.run_id}</b></a>' if var.run_id else "",
            f"<i><b>{var.gene or ''}</b></i><div><i>{var.isoform or ''}</i></div>",
            f"<b>{var.hgvsp or ''}</b><br>{var.hgvsg or ''}<br>{var.hgvsc or ''}",
            var.exon or "",
            var.read_support or "",
            var.depth or "",
            var.allele_frequency or "",
            var.vartype or "",
            var.consequence or "",
            badge or class_label,
        ])

    return jsonify({"draw": draw, "recordsTotal": records_total, "recordsFiltered": records_filtered, "data": data})


@app.route('/advanced_search_export_xlsx', methods=['GET'])
def advanced_search_export_xlsx():
    criteria = session.get("advanced_search_criteria")
    if not criteria:
        flash("No hi ha cap cerca activa per exportar", "warning")
        return redirect(url_for("search_menu"))

    filename = f"advanced_search_{date.today().isoformat()}.xlsx"

    if criteria.get("mode") == "samples":
        q = _apply_sample_filters(SampleTable.query, criteria)
        rows = q.order_by(SampleTable.lab_id.asc()).all()
        data = [{
            "Lab ID": s.lab_id or "",
            "Ext1 ID": s.ext1_id or "",
            "Ext2 ID": s.ext2_id or "",
            "Run ID": s.run_id or "",
            "Tumor Origin": s.tumor_origin or "",
            "% Tumoral": s.tumour_purity or "",
            "Panel": s.panel or "",
            "Subpanel": s.subpanel or "",
            "Analysis Date": s.analysis_date or "",
        } for s in rows]
    else:
        include_t1 = criteria["dump_tier1"]
        include_t2 = criteria["dump_tier2"]
        include_t3 = criteria["dump_tier3"]
        if not include_t1 and not include_t2 and not include_t3:
            include_t1 = include_t2 = include_t3 = True

        qs = []
        if include_t1:
            qs.append(_tier_variant_query(TherapeuticTable, "Variant accionable", criteria))
        if include_t2:
            qs.append(_tier_variant_query(OtherVariantsTable, "Variant d'alt impacte", criteria))
        if include_t3:
            qs.append(_tier_variant_query(RareVariantsTable, "Altres variants rares", criteria))

        if not qs:
            data = []
        else:
            union_q = qs[0]
            for q in qs[1:]:
                union_q = union_q.union_all(q)
            rows = union_q.all()
            data = [{
                "Lab ID": r.lab_id or "",
                "Ext1 ID": r.ext1_id or "",
                "Ext2 ID": r.ext2_id or "",
                "% Tumoral": r.tumour_purity or "",
                "Run ID": r.run_id or "",
                "Gene": r.gene or "",
                "Isoform": r.isoform or "",
                "HGVSp": r.hgvsp or "",
                "HGVSg": r.hgvsg or "",
                "HGVSc": r.hgvsc or "",
                "Read support": r.read_support or "",
                "Depth": r.depth or "",
                "VAF": r.allele_frequency or "",
                "Type": r.vartype or "",
                "Consequence": r.consequence or "",
                "Classification": r.classification or "",
            } for r in rows]

    df = pd.DataFrame(data)
    output = BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df.to_excel(writer, index=False, sheet_name="SearchResults")
    output.seek(0)

    return send_file(
        output,
        as_attachment=True,
        download_name=filename,
        mimetype="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
