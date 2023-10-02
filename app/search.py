from app import app

from flask import Flask
from flask import request, render_template, url_for, redirect, flash
from flask_wtf import FlaskForm
import sqlite3
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from sqlalchemy.sql import and_, or_
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
import plotly
import plotly.graph_objs as go
import plotly.express as px
from plotly.subplots import make_subplots
from app.models import Job, VersionControl, SampleTable, SampleVariants, Variants, TherapeuticTable, OtherVariantsTable, RareVariantsTable, BiomakerTable, SummaryQcTable, DisclaimersTable, AllCnas

@app.route('/')
@app.route('/search_menu')
def search_menu():
    return render_template("search.html", title="Nova cerca")

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

@app.route('/advanced_search', methods = ['GET', 'POST'])
def advanced_search():

    p_variants = ""
    most_common_plot=""
    if request.method == "POST":

        show_samples  = False
        show_variants = False

        lab_id = ""
        if request.form.get('lab_id'):
            lab_id = request.form['lab_id']
            show_samples = True

        ext1_id = ""
        if request.form.get('ext1_id'):
            ext1_id = request.form['ext1_id']
            show_samples = True

        ext2_id = ""
        if request.form.get('ext2_id'):
            ext2_id = request.form['ext2_id']
            show_samples = True

        run_id = ""
        if request.form.get('run_id'):
            run_id = request.form['run_id']
            show_samples = True

        initial_date = ""
        if request.form.get('initial_date'):
            initial_date = request.form['initial_date']
            format = "%Y-%m-%d"
            try:
                datetime.datetime.strptime(initial_date, format)
                initial_date = datetime.datetime.strptime(initial_date, '%Y-%m-%d').strftime('%d/%m/%Y')
            except:
                pass

            initial_date_dt = datetime.datetime.strptime(initial_date, '%d/%m/%Y')
            show_samples = True

        final_date = ""
        if request.form.get('final_date'):
            final_date = request.form['final_date']
            format = "%Y-%m-%d"
            try:
                datetime.datetime.strptime(final_date, format)
                final_date = datetime.datetime.strptime(final_date, '%Y-%m-%d').strftime('%d/%m/%Y')
            except:
                pass
            final_date_dt = datetime.datetime.strptime(final_date, '%d/%m/%Y')
            show_samples = True

        is_error = False
        do_date  = False

        # Now checking gene input forms
        gene = ""
        if request.form.get('gene'):
            gene = request.form['gene']
            show_variants = True

        isoform = ""
        if request.form.get('isoform'):
            isoform = request.form['isoform']
            show_variants = True

        # Now checking variant input forms
        do_variant_filter   = False
        dump_small_variants = True
        dump_large_variants = False

        hgvsg = ""
        if request.form.get('hgvsg'):
            hgvsg = request.form['hgvsg']
            do_variant_filter = True
            show_variants = True

        hgvsp = ""
        if request.form.get('hgvsp'):
            hgvsp = request.form['hgvsp']
            do_variant_filter = True
            show_variants = True

        hgvsc = ""
        if request.form.get('hgvsc'):
            hgvsc = request.form['hgvsc']
            do_variant_filter = True
            show_variants = True

        # Dump SV or CNVs
        dump_cnv = False
        if request.form.get("filter_cnv"):
            dump_cnv = True
            do_variant_filter = True
            show_variants = True

        dump_sv = False
        if request.form.get("filter_sv"):
            dump_sv = True
            do_variant_filter = True
            show_variants = True

        dump_tier1 = False
        if request.form.get("tier_1"):
            dump_tier1 = True
            do_variant_filter = True
            show_variants = True
        dump_tier2 = False
        if request.form.get("tier_2"):
            dump_tier2 = True
            do_variant_filter = True
            show_variants = True
        dump_tier3 = False
        if request.form.get("tier_3"):
            dump_tier3 = True
            do_variant_filter = True
            show_variants = True

        if not show_variants and gene:
            show_variants = True
            do_variant_filter = True

        conditions = []
        sample_list = []
        variant_list= []
        if show_samples == True:

            if lab_id:
                conditions.append(SampleTable.lab_id == lab_id)
            if run_id:
                conditions.append(SampleTable.run_id == run_id)
            if ext1_id:
                conditions.append(SampleTable.ext1_id == ext1_id)
            if ext2_id:
                conditions.append(SampleTable.ext2_id == ext2_id)

            if initial_date:
                if not final_date:
                    is_error = True
                    flash ("Es requereix una data final", "warning")
            if final_date:
                if not initial_date:
                    is_error = True
                    flash ("Es requereix una data inicial", "warning")

            if initial_date and final_date:
                do_date = True
                if initial_date_dt <= final_date_dt:
                    pass
                else:
                    flash ("La data inicial és major que la data final", "warning")
                    is_error = True
                    do_date = False
            if is_error:
                return redirect(url_for('search_menu'))

            samples_raw = SampleTable.query.filter(and_(*conditions)).all()
            for sample in samples_raw:
                if do_date == True:
                    sdate_list = sample.analysis_date.split(" ")
                    sample_analysis_date = sdate_list[0]
                    sample_dt = datetime.datetime.strptime(sample_analysis_date, '%d/%m/%Y')
                    if not sample_dt:
                        continue
                    if sample_dt >= initial_date_dt and sample_dt <= final_date_dt:
                        sample_list.append(sample)
                else:
                    sample_list.append(sample)

        if show_variants:
            if not sample_list:
                sample_list =  SampleTable.query.all()
            for sample in sample_list:
                condition_tier1 = []
                condition_tier2 = []
                condition_tier3 = []

                if gene:
                    if dump_tier1:
                        condition_tier1.append(TherapeuticTable.gene == gene)
                    if dump_tier2:
                        condition_tier2.append(OtherVariantsTable.gene == gene)
                    if dump_tier3:
                        condition_tier3.append(RareVariantsTable.gene == gene)
                    if not dump_tier1 and not dump_tier2 and not dump_tier3:
                        condition_tier1.append(TherapeuticTable.gene == gene)
                        condition_tier2.append(OtherVariantsTable.gene == gene)
                        condition_tier3.append(RareVariantsTable.gene == gene)
                if isoform:
                    if not gene:
                        is_error = True
                        flash("No s'ha entrat el nom del gen", "warning")
                    if dump_tier1:
                        condition_tier1.append(TherapeuticTable.enst_id == isoform)
                    if dump_tier2:
                        condition_tier2.append(OtherVariantsTable.enst_id == isoform)
                    if dump_tier3:
                        condition_tier3.append(RareVariantsTable.enst_id == isoform)

                if hgvsp:
                    if dump_tier1:
                        condition_tier1.append(TherapeuticTable.hgvsp == hgvsp)
                    if dump_tier2:
                        condition_tier2.append(OtherVariantsTable.hgvsp == hgvsp)
                    if dump_tier3:
                        condition_tier3.append(RareVariantsTable.hgvsp == hgvsp)
                    if not dump_tier1 and not dump_tier2 and not dump_tier3:
                        condition_tier1.append(TherapeuticTable.hgvsp == hgvsp)
                        condition_tier2.append(OtherVariantsTable.hgvsp == hgvsp)
                        condition_tier3.append(RareVariantsTable.hgvsp == hgvsp)
                if dump_cnv:
                    if dump_tier1:
                        condition_tier1.append(TherapeuticTable.variant_type == "Amplification")
                    if dump_tier2:
                        condition_tier2.append(OtherVariantsTable.variant_type == "Amplification")
                    if dump_tier3:
                        condition_tier3.append(RareVariantsTable.variant_type == "Amplification")
                    if not dump_tier1 and not dump_tier2 and not dump_tier3:
                        condition_tier1.append(TherapeuticTable.variant_type == "Amplification")
                        condition_tier2.append(OtherVariantsTable.variant_type == "Amplification")
                        condition_tier3.append(RareVariantsTable.variant_type == "Amplification")

                if dump_sv:
                    if dump_tier1:
                        condition_tier1.append(TherapeuticTable.variant_type == "SV")
                    if dump_tier2:
                        condition_tier2.append(OtherVariantsTable.variant_type == "SV")
                    if dump_tier3:
                        condition_tier3.append(RareVariantsTable.variant_type == "SV")
                    if not dump_tier1 and not dump_tier2 and not dump_tier3:
                        condition_tier1.append(TherapeuticTable.variant_type == "SV")
                        condition_tier2.append(OtherVariantsTable.variant_type == "SV")
                        condition_tier3.append(RareVariantsTable.variant_type == "SV")
                vars_tier1 = []
                vars_tier2 = []
                vars_tier3 = []
                if dump_tier1:
                    condition_tier1.append(TherapeuticTable.lab_id == sample.lab_id)
                    vars_tier1 = TherapeuticTable.query.filter(and_(*condition_tier1)).all()
                if dump_tier2:
                    condition_tier2.append(OtherVariantsTable.lab_id == sample.lab_id)
                    vars_tier2 = OtherVariantsTable.query.filter(and_(*condition_tier2)).all()
                if dump_tier3:
                    condition_tier3.append(RareVariantsTable.lab_id == sample.lab_id)
                    vars_tier3 = RareVariantsTable.query.filter(and_(*condition_tier3)).all()
                if not dump_tier1 and not dump_tier2 and not dump_tier3:
                    condition_tier1.append(TherapeuticTable.lab_id == sample.lab_id)
                    condition_tier2.append(OtherVariantsTable.lab_id == sample.lab_id)
                    condition_tier3.append(RareVariantsTable.lab_id == sample.lab_id)

                    vars_tier1 = TherapeuticTable.query.filter(and_(*condition_tier1)).all()
                    vars_tier2 = OtherVariantsTable.query.filter(and_(*condition_tier2)).all()
                    vars_tier3 = RareVariantsTable.query.filter(and_(*condition_tier3)).all()

                sample_variants = vars_tier1 + vars_tier2 + vars_tier3
                for var in sample_variants:

                     print(sample.tumour_purity + " joder" + var.hgvsp)
                     v = Variant(sample_id=sample.id,lab_id=sample.lab_id, ext1_id=sample.ext1_id, ext2_id=sample.ext2_id,
                        tumour_purity=sample.tumour_purity, run_id=sample.run_id, gene=var.gene, isoform=var.enst_id, hgvsg=var.hgvsg,
                        hgvsc=var.hgvsc, hgvsp=var.hgvsp, vartype=var.variant_type, exon=var.exon,
                        intron=var.intron, consequence=var.consequence, read_support=var.read_support,
                        depth=var.depth, allele_frequency=var.allele_frequency, classification=var.classification)
                     variant_list.append(v)

            if variant_list:
                p_variants, most_common_plot = pie_plot_variants(variant_list)
                # vars = OtherVariantsTable.query.filter_by(lab_id = sample.lab_id).all()
                # for var in vars:
                #      v = Variant(lab_id=sample.lab_id, ext1_id=sample.ext1_id, ext2_id=sample.ext2_id,
                #         run_id=sample.run_id, gene=var.gene, isoform=var.enst_id, hgvsg=var.hgvsg,
                #         hgvsc=var.hgvsc, hgvsp=var.hgvsp, vartype=var.variant_type, exon=var.exon,
                #         intron=var.intron, consequence=var.consequence, classification="Other")
                #      variant_list.append(v)

        if sample_list or variant_list:
            return render_template("search_results.html", samples=sample_list, variants=variant_list, p_variants=p_variants, m_plot=most_common_plot)
    return redirect(url_for('search_menu'))
