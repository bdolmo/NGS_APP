from app import app,db
import os
import time
import binascii
from uuid import uuid4
from flask import Flask
from flask import request, render_template, url_for, redirect, flash, send_from_directory,current_app,send_file
from flask_wtf import FlaskForm
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from flask_sslify import SSLify
from collections import defaultdict
import redis
from rq import Queue, cancel_job
from sqlalchemy import MetaData, create_engine, Column, Integer, String, Text, desc
from sqlalchemy.ext.declarative import declarative_base, DeclarativeMeta
from sqlalchemy.orm import sessionmaker
from datetime import date,datetime
from command import background_task
import pandas as pd
import numpy as np
import docx
import re
import json
import sqlite3
import subprocess
import plotly
import plotly.graph_objs as go
import plotly.express as px
from plotly.subplots import make_subplots
from app.models import Job, VersionControl, SampleTable, SampleVariants, Variants, TherapeuticTable, OtherVariantsTable, RareVariantsTable, BiomakerTable, SummaryQcTable, DisclaimersTable

#db = SQLAlchemy(app)

# class Variants(db.Model):
#     __tablename__ = 'VARIANTS'
#     id = db.Column(db.Integer, primary_key=True)
#     chromosome = db.Column(db.String(20))
#     pos = db.Column(db.String(20))
#     ref = db.Column(db.String(20))
#     alt = db.Column(db.String(20))
#     var_type = db.Column(db.String(20))
#     genome_version = db.Column(db.String(20))
#     gene = db.Column(db.String(20))
#     isoform = db.Column(db.String(20))
#     hgvsg = db.Column(db.String(20))
#     hgvsp = db.Column(db.String(20))
#     hgvsc = db.Column(db.String(20))
#     count = db.Column(db.Integer)

# class SampleVariants(db.Model):
#     __tablename__ = 'SAMPLE_VARIANTS'
#     id = db.Column(db.Integer, primary_key=True)
#     sample_id = db.Column(db.Integer)
#     var_id = db.Column(db.Integer)
#     ann_id = db.Column(db.Integer)
#     lab_confirmation = db.Column(db.String(20))
#     confirmation_technique = db.Column(db.String(20))
#     classification = db.Column(db.String(20))
#     ann_key = db.Column(db.String(200))
#     ann_json = db.Column(db.String(20000))

# class VarAnnotation(db.Model):
#     __tablename__= 'VAR_ANNOTATION'
#     id = db.Column(db.Integer, primary_key=True)
#     var_id   = db.Column(db.Integer)
#     ann_key  = db.Column(db.String(20))
#     ann_json = db.Column(db.String(20))

# class SampleTable(db.Model):
#     __tablename__ = 'SAMPLES'
#     id = db.Column(db.Integer, primary_key=True)
#     user_id = db.Column(db.String(20))
#     lab_id  = db.Column(db.String(120))
#     ext1_id = db.Column(db.String(80))
#     ext2_id = db.Column(db.String(80))
#     run_id  = db.Column(db.String(80))
#     petition_id  = db.Column(db.String(80))
#     extraction_date =  db.Column(db.String(80))
#     analysis_date   =  db.Column(db.String(80))
#     tumour_purity   =  db.Column(db.String(80))
#     sex  = db.Column(db.String(80))
#     diagnosis = db.Column(db.String(80))
#     physician_name  = db.Column(db.String(80))
#     medical_center  = db.Column(db.String(80))
#     medical_address = db.Column(db.String(80))
#     sample_type  = db.Column(db.String(80))
#     panel    = db.Column(db.String(80))
#     subpanel = db.Column(db.String(80))
#     roi_bed  = db.Column(db.String(80))
#     software = db.Column(db.String(80))
#     software_version = db.Column(db.String(80))
#     bam = db.Column(db.String(80))
#     merged_vcf = db.Column(db.String(80))
#     report_pdf = db.Column(db.String(80))
#     report_db  = db.Column(db.String(120))
#     sample_db_dir = db.Column(db.String(120))
#     cnv_json   = db.Column(db.String(100000))
#     def __repr__(self):
#         return '<Sample %r>' % self.lab_id

# class TherapeuticTable(db.Model):
#     __tablename__ = 'THERAPEUTIC_VARIANTS'
#     id = db.Column(db.Integer, primary_key=True)
#     user_id = db.Column(db.String(20))
#     lab_id  = db.Column(db.String(120))
#     ext1_id = db.Column(db.String(80))
#     ext2_id = db.Column(db.String(80))
#     run_id  = db.Column(db.String(80))
#     petition_id  = db.Column(db.String(80))
#     gene  = db.Column(db.String(120))
#     enst_id  = db.Column(db.String(120))
#     hgvsp = db.Column(db.String(120))
#     hgvsg =  db.Column(db.String(120))
#     hgvsc =  db.Column(db.String(120))
#     exon  = db.Column(db.String(120))
#     variant_type = db.Column(db.String(120))
#     consequence =  db.Column(db.String(120))
#     depth = db.Column(db.String(120))
#     allele_frequency = db.Column(db.String(120))
#     read_support = db.Column(db.String(120))
#     max_af = db.Column(db.String(120))
#     max_af_pop = db.Column(db.String(120))
#     therapies = db.Column(db.String(240))
#     clinical_trials = db.Column(db.String(240))
#     tumor_type = db.Column(db.String(240))
#     var_json   = db.Column(db.String(5000))
#     classification = db.Column(db.String(120))
#     validated_assessor = db.Column(db.String(120))
#     validated_bioinfo  = db.Column(db.String(120))
#     db_detected_number = db.Column(db.Integer())
#     db_sample_count    = db.Column(db.Integer())
#     db_detected_freq = db.Column(db.Float())
#
#     def __repr__(self):
#         return '<TherapeuticVariants %r>' % self.gene

# class OtherVariantsTable(db.Model):
#     __tablename__ = 'OTHER_VARIANTS'
#     id = db.Column(db.Integer, primary_key=True)
#     user_id = db.Column(db.String(20))
#     lab_id  = db.Column(db.String(120))
#     ext1_id = db.Column(db.String(80))
#     ext2_id = db.Column(db.String(80))
#     run_id  = db.Column(db.String(80))
#     petition_id  = db.Column(db.String(80))
#     gene  = db.Column(db.String(120))
#     enst_id  = db.Column(db.String(120))
#     hgvsp = db.Column(db.String(120))
#     hgvsg =  db.Column(db.String(120))
#     hgvsc =  db.Column(db.String(120))
#     exon  = db.Column(db.String(120))
#     variant_type = db.Column(db.String(120))
#     consequence =  db.Column(db.String(120))
#     depth = db.Column(db.String(120))
#     allele_frequency = db.Column(db.String(120))
#     read_support = db.Column(db.String(120))
#     max_af = db.Column(db.String(120))
#     max_af_pop = db.Column(db.String(120))
#     therapies = db.Column(db.String(240))
#     clinical_trials = db.Column(db.String(240))
#     tumor_type = db.Column(db.String(240))
#     var_json   = db.Column(db.String(5000))
#     classification = db.Column(db.String(120))
#     validated_assessor = db.Column(db.String(120))
#     validated_bioinfo  = db.Column(db.String(120))
#     db_detected_number = db.Column(db.Integer())
#     db_sample_count    = db.Column(db.Integer())
#     db_detected_freq = db.Column(db.Float())
#
# class RareVariantsTable(db.Model):
#     __tablename__ = 'RARE_VARIANTS'
#     id = db.Column(db.Integer, primary_key=True)
#     user_id = db.Column(db.String(20))
#     lab_id  = db.Column(db.String(120))
#     ext1_id = db.Column(db.String(80))
#     ext2_id = db.Column(db.String(80))
#     run_id  = db.Column(db.String(80))
#     petition_id  = db.Column(db.String(80))
#     gene  = db.Column(db.String(120))
#     enst_id  = db.Column(db.String(120))
#     hgvsp = db.Column(db.String(120))
#     hgvsg =  db.Column(db.String(120))
#     hgvsc =  db.Column(db.String(120))
#     exon  = db.Column(db.String(120))
#     variant_type = db.Column(db.String(120))
#     consequence =  db.Column(db.String(120))
#     depth = db.Column(db.String(120))
#     allele_frequency = db.Column(db.String(120))
#     read_support = db.Column(db.String(120))
#     max_af = db.Column(db.String(120))
#     max_af_pop = db.Column(db.String(120))
#     therapies = db.Column(db.String(240))
#     clinical_trials = db.Column(db.String(240))
#     tumor_type = db.Column(db.String(240))
#     var_json   = db.Column(db.String(5000))
#     classification = db.Column(db.String(120))
#     validated_assessor = db.Column(db.String(120))
#     validated_bioinfo = db.Column(db.String(120))
#     db_detected_number = db.Column(db.Integer())
#     db_sample_count    = db.Column(db.Integer())
#     db_detected_freq = db.Column(db.Float())

# class BiomakerTable(db.Model):
#     __tablename__ = 'BIOMARKER_METRICS'
#     id = db.Column(db.Integer, primary_key=True)
#     user_id = db.Column(db.String(20))
#     lab_id  = db.Column(db.String(120))
#     ext1_id = db.Column(db.String(80))
#     ext2_id = db.Column(db.String(80))
#     run_id  = db.Column(db.String(80))
#     gene = db.Column(db.String(80))
#     variant = db.Column(db.String(80))
#     exon = db.Column(db.String(80))
#     chr = db.Column(db.String(80))
#     pos = db.Column(db.String(80))
#     end = db.Column(db.String(80))
#     panel = db.Column(db.String(120))
#     vaf = db.Column(db.String(80))
#     depth = db.Column(db.String(80))

# class SummaryQcTable(db.Model):
#     __tablename__ = 'SUMMARY_QC'
#     id = db.Column(db.Integer, primary_key=True)
#     user_id = db.Column(db.String(20))
#     lab_id  = db.Column(db.String(120))
#     ext1_id = db.Column(db.String(80))
#     ext2_id = db.Column(db.String(80))
#     run_id  = db.Column(db.String(80))
#     petition_id = db.Column(db.String(120))
#     summary_json = db.Column(db.String(12000))
#     fastp_json   = db.Column(db.String(10000))

# class DisclaimersTable(db.Model):
#     __tablename__ = 'DISCLAIMERS'
#     id = db.Column(db.Integer, primary_key=True)
#     genes = db.Column(db.String(3000))
#     methodology = db.Column(db.String(3000))
#     analysis =  db.Column(db.String(3000))
#     lab_confirmation = db.Column(db.String(3000))
#     technical_limitations =  db.Column(db.String(3000))
#     legal_provisions = db.Column(db.String(3000))
#     panel = db.Column(db.String(120))
#     language = db.Column(db.String(120))

class AllCnas(db.Model):
  __tablename__ = 'ALL_CNAS'
  id = db.Column(db.Integer, primary_key=True)
  user_id    = db.Column(db.String(100))
  lab_id     = db.Column(db.String(100))
  ext1_id    = db.Column(db.String(100))
  ext2_id    = db.Column(db.String(100))
  run_id     = db.Column(db.String(100))
  chromosome = db.Column(db.String(100))
  start      = db.Column(db.String(100))
  end        = db.Column(db.String(100))
  genes      = db.Column(db.String(100))
  svtype     = db.Column(db.String(100))
  ratio      = db.Column(db.String(100))
  qual       = db.Column(db.String(100))
  cn         = db.Column(db.String(100))

class AllFusions(db.Model):
  __tablename__ = 'ALL_FUSIONS'
  id         = db.Column(db.Integer, primary_key=True)
  user_id    = db.Column(db.String(100))
  lab_id     = db.Column(db.String(100))
  ext1_id    = db.Column(db.String(100))
  ext2_id    = db.Column(db.String(100))
  run_id     = db.Column(db.String(100))
  chromosome = db.Column(db.String(100))
  start      = db.Column(db.String(100))
  end        = db.Column(db.String(100))
  qual       = db.Column(db.String(100))
  svtype     = db.Column(db.String(100))
  read_pairs = db.Column(db.String(100))
  split_reads= db.Column(db.String(100))
  vaf        = db.Column(db.String(100))
  depth      = db.Column(db.String(100))
  fusion_partners= db.Column(db.String(100))
  fusion_source  = db.Column(db.String(100))
  fusion_diseases= db.Column(db.String(100))
  flanking_genes = db.Column(db.String(100))

# # Define version control class
class AlchemyEncoder(json.JSONEncoder):

    def default(self, obj):
        if isinstance(obj.__class__, DeclarativeMeta):
            # an SQLAlchemy class
            fields = {}
            for field in [x for x in dir(obj) if not x.startswith('_') and x != 'metadata']:
                data = obj.__getattribute__(field)
                try:
                    json.dumps(data) # this will fail on non-encodable values, like other classes
                    fields[field] = data
                except TypeError:
                    fields[field] = None
            # a json-encodable dict
            return fields

        return json.JSONEncoder.default(self, obj)
@app.route('/')
@app.route('/show_run_details/<run_id>')
def show_run_details(run_id):

  run_samples = SampleTable.query.filter_by(run_id=run_id).all()
  run_dict = defaultdict(dict)
  if run_samples:

    run_dict['RUN_ID']        = run_id
    run_dict['PETITION_ID']   = run_samples[0].petition_id
    run_dict['N_SAMPLES']     = len(run_samples)
    run_dict['ANALYSIS_DATE'] = run_samples[0].analysis_date

  return render_template("show_run_details.html", title=run_id,
    run_samples=run_samples, run_dict=run_dict)

@app.route('/download_summary_qc/<run_id>')
def download_summary_qc(run_id):
    uploads = os.path.join(app.config['STATIC_URL_PATH'],
        run_id)
    summary = "summary_qc.tsv"
    return send_from_directory(directory=uploads, filename=summary,
        as_attachment=True)

@app.route('/download_sample_bam/<run_id>/<sample>')
def download_sample_bam(run_id, sample):

  uploads = os.path.join(app.config['STATIC_URL_PATH'],
    run_id + "/" + sample + "/BAM_FOLDER/")
  bam_file = sample + ".rmdup.bam"
  return send_from_directory(directory=uploads, filename=bam_file,
      as_attachment=True)

@app.route('/download_sample_bai/<run_id>/<sample>')
def download_sample_bai(run_id, sample):

  uploads = os.path.join(app.config['STATIC_URL_PATH'],
    run_id + "/" + sample + "/BAM_FOLDER/")
  bai_file = sample + ".rmdup.bam.bai"
  return send_from_directory(directory=uploads, filename=bai_file,
      as_attachment=True)

@app.route('/download_sample_vcf/<run_id>/<sample>')
def download_sample_vcf(run_id, sample):
  uploads = os.path.join(app.config['STATIC_URL_PATH'],
    run_id + "/" + sample + "/VCF_FOLDER/")
  vcf_file = sample + ".merged.variants.vcf"
  return send_from_directory(directory=uploads, filename=vcf_file,
      as_attachment=True)

@app.route('/download_igv_snapshots')
def download_igv_snapshots():
    zipf = zipfile.ZipFile('IGV.zip','w', zipfile.ZIP_DEFLATED)
    for root,dirs, files in os.walk('output/'):
        for file in files:
            zipf.write('output/'+file)
    zipf.close()
    return send_file('Name.zip',
     mimetype = 'zip',
     attachment_filename= 'Name.zip',
     as_attachment = True)

def var_location_pie(variants_dict):

  location_dict = defaultdict(dict)
  vartype_dict  = defaultdict(dict)
  for var in variants_dict:
    l_list = var.consequence.split(",")
    for entry in l_list:
      if not entry in location_dict:
        location_dict[entry] = 0
      else:
        location_dict[entry] += 1
    if not var.variant_type in vartype_dict:
      vartype_dict[var.variant_type] = 0
    else:
      vartype_dict[var.variant_type] += 1
  labels_list = []
  for label in location_dict:
    labels_list.append(label)
  values_list = []
  for label in location_dict:
    values_list.append(location_dict[label])
  layout= go.Layout (
    width=400,
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

  labels_list = []
  for label in vartype_dict:
    labels_list.append(label)
  values_list = []
  for label in vartype_dict:
    values_list.append(vartype_dict[label])
  layout= go.Layout (
    paper_bgcolor= 'rgba(0,0,0,0)',
    plot_bgcolor = 'rgba(0,0,0,0)',
    width=270,
    height=270,
    margin=dict(l=0, r=0, b=0, t=0 )
  )
  fig = go.Figure(data=[go.Bar(x=labels_list, y=values_list,
   marker_color='rgba(35,203,167,0.5)',
  marker_line_color='black')], layout=layout)
  fig.update_layout(
    #xaxis_title="Tipus",
    yaxis_title="Total",
    #title = "Tipus de variants"
  )
  fig.update_yaxes(showline=True, linewidth=1, linecolor='black', mirror=False)
  fig.update_xaxes(showline=True, linewidth=1, linecolor='black', mirror=False)

  graphJSONbar = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

  return graphJSONpie, graphJSONbar

def cnv_plot(cnv_dict):

    x_list = []
    y_list = []
    z_list = []
    a_list = []
    b_list = []
    for roi in cnv_dict:
      x_list.append(float(roi))
      #print(cnv_dict[roi]['Coordinates'])
      cnv_ratio = float(cnv_dict[roi]['roi_log2'])
      y_list.append(cnv_ratio)
      segment_ratio = float(cnv_dict[roi]['segment_log2'])
      z_list.append(segment_ratio)
      gene = cnv_dict[roi]['Gene']
      a_list.append(gene)
      status = cnv_dict[roi]['Status']
      b_list.append(status)
    trace1 = go.Scatter(x=x_list, y=y_list, mode='markers', text=a_list, name='log2',
    marker=dict(color='lightgrey'))
    trace2 = go.Scatter(x=x_list, y=z_list, mode='lines', text=a_list, name='Segment')
    #trace3 = go.Scatter(x=x_list, y=b_list, mode='markers', name='Status')
    data = [trace1, trace2]
    layout= go.Layout (
       paper_bgcolor= 'rgba(0,0,0,0)',
       plot_bgcolor = 'rgba(0,0,0,0)'
    )
    fig = go.Figure(data=data, layout=layout )
    fig.update_traces(marker=dict(line=dict(width=1, color='grey')))
    fig.update_layout(
      xaxis_title="#Regió",
      yaxis_title="log2 ratio",
      margin=dict(l=0, r=0, b=0, t=0 ),
      height=350,
    )
    fig.update_xaxes(showline=True, linewidth=1, linecolor='black', mirror=False)
    fig.update_yaxes(showline=True, linewidth=1, linecolor='black', mirror=False)

    graphJSON = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

    return graphJSON

def basequal_plot(basequal_dict):

  a_list = []
  c_list = []
  t_list = []
  g_list = []

  position = []
  idx = 0
  for value in basequal_dict['A']:
    idx+=1
    position.append(idx)

  for base in basequal_dict:
    for value in basequal_dict[base]:
      if base == 'A':
        a_list.append(value)
      if base == 'C':
        c_list.append(value)
      if base == 'T':
        t_list.append(value)
      if base == 'G':
        g_list.append(value)

  trace1 = go.Scatter(x=position, y=a_list, mode='lines', name='A', marker=dict(color='green'))
  trace2 = go.Scatter(x=position, y=c_list, mode='lines', name='C',marker=dict(color='blue'))
  trace3 = go.Scatter(x=position, y=t_list, mode='lines', name='T',marker=dict(color='red'))
  trace4 = go.Scatter(x=position, y=g_list, mode='lines', name='G',marker=dict(color='black'))

  data = [trace1, trace2, trace3, trace4]
  layout= go.Layout (
    # paper_bgcolor= 'rgba(0,0,0,0)',
    # plot_bgcolor = 'rgba(0,0,0,0)'
  )
  fig2 = go.Figure(data=data, layout=layout )
  fig2.update_traces(marker=dict(line=dict(width=1, color='grey')))
  fig2.update_layout(
    autosize=False,
    xaxis_title="Posició",
    yaxis_title="Phred score",
    margin=dict(l=0, r=0, b=0, t=0 ),
    width=550,
    height=250,
  )
  fig2.update_xaxes(showline=True, linewidth=1, linecolor='black', mirror=False)
  fig2.update_yaxes(showline=True, linewidth=1, linecolor='black', mirror=False)

  graphJSON = json.dumps(fig2, cls=plotly.utils.PlotlyJSONEncoder)
  return graphJSON

def adapters_plot(r1_adapters_dict, r2_adapters_dict):

  labels_r1 = []
  values_r1 = []
  for x in r1_adapters_dict:
    labels_r1.append(x)
    values_r1.append(r1_adapters_dict[x])

  labels_r2 = []
  values_r2 = []
  for x in r2_adapters_dict:
    labels_r2.append(x)
    values_r2.append(r2_adapters_dict[x])

  fig = make_subplots(rows=1, cols=2, horizontal_spacing=0.25)
  fig.add_trace(
    go.Bar(
        x=values_r1,
        y=labels_r1,
        orientation='h'
    ),
    row=1, col=1
  )
  fig.add_trace(
    go.Bar(
        x=values_r2,
        y=labels_r2,
        orientation='h'
    ),
    row=1, col=2
  )

  fig.update_layout(height=300, width=1200, title_text="", margin=dict(l=0, r=0, b=0, t=0 ))
  graphJSONhbar = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

  return graphJSONhbar

def snv_plot(snv_dict):

  labels_list = []
  values_list = []

  for var1 in snv_dict:
      for var2 in snv_dict[var1]:
        label = var1 + ">" + var2
        value = snv_dict[var1][var2]
        labels_list.append(label)
        values_list.append(value)

  layout= go.Layout (
    paper_bgcolor= 'rgba(0,0,0,0)',
    plot_bgcolor = 'rgba(0,0,0,0)',
    width=270,
    height=270,
    margin=dict(l=0, r=0, b=0, t=0 )
  )
  fig = go.Figure(data=[go.Bar(x=labels_list, y=values_list,
   marker_color='rgba(35,203,167,0.5)',
  marker_line_color='black')], layout=layout)
  fig.update_layout(
    #xaxis_title="Tipus",
    yaxis_title="Total",
    #title = "Tipus de variants"
  )
  fig.update_yaxes(showline=True, linewidth=1, linecolor='black', mirror=False)
  fig.update_xaxes(showline=True, linewidth=1, linecolor='black', mirror=False)

  graphJSONbar = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
  return graphJSONbar

def vaf_plot(vaf_list):

    layout= go.Layout (
        margin=dict(l=0, r=0, b=0, t=0 )
    )
    fig = go.Figure(data=[go.Histogram(x=vaf_list, histfunc="count", nbinsx=100)])
    fig.update_layout(
    #xaxis_title="Tipus",
        paper_bgcolor= 'rgba(0,0,0,0)',
        plot_bgcolor = 'rgba(0,0,0,0)',
        height=270,
        width=300,

        margin=dict(l=0, r=0, b=0, t=0 ),
        yaxis_title="Total",
    #title = "Tipus de variants"
    )
    fig.update_xaxes(range=[0,1])
    graphJSONhist = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)
    return graphJSONhist

def generate_key(self):
    return binascii.hexlify(os.urandom(20)).decode()

@app.route('/apply_variant_filters/<run_id>/<sample>/<sample_id>/<variant_class>', methods = ['GET', 'POST'])
def apply_variant_filters(run_id, sample, sample_id, variant_class):

  origin_table = ""
  variants = ""
  if variant_class == 'therapeutic':
      active="Therapeutic"
      origin_table = "TherapeuticTable"
      variants = TherapeuticTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
  elif variant_class == 'other':
      origin_table = "OtherVariantsTable"
      active="Other"
      variants = OtherVariantsTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
  elif variant_class == 'rare':
      origin_table = "RareVariantsTable"
      active="Rare"
      variants = RareVariantsTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()

  if request.method == "POST":
    min_vaf   = ""
    min_depth = ""
    min_read_support = ""
    do_snv   = False
    do_indel = False
    do_sv    = False

    num_filtered = 0
    if request.form.get('vaf_perc'):
        min_vaf = request.form['vaf_perc']
        min_vaf = float(min_vaf)
    if request.form.get('min_depth'):
        min_depth = request.form['min_depth']
    if request.form.get('min_read_support'):
        min_read_support = request.form['min_read_support']
    if request.form.get('snv_check'):
        do_snv = True
    if request.form.get('indel_check'):
        do_indel = True
    if request.form.get('sv_check'):
        do_sv = True

    action_id = generate_key(16)
    for var in variants:
        remove_variant = False
        if var.variant_type == 'SNV' or var.variant_type == 'MNV':
            if not do_snv:
                continue
        elif var.variant_type == 'Deletion' or var.variant_type == 'Insertion':
            if not do_indel:
                continue
        elif var.variant_type == 'SV':
            if not do_sv:
                continue
        else:
            continue

        if min_vaf:
            if float(var.allele_frequency) < min_vaf:
                remove_variant = True
                #db.session.delete(var)
                #db.session.commit()
                num_filtered+=1
        if min_depth:
            if int(var.depth) < int(min_depth):
                remove_variant = True
                #db.session.delete(var)
                #db.session.commit()
                num_filtered+=1
        if min_read_support:
            if int(var.read_support) < int(min_read_support):
                remove_variant = True

                #db.session.delete(var)
                #db.session.commit()
                num_filtered+=1

        if remove_variant == True:
            db.session.delete(var)
            db.session.commit()
            action_name = sample + ":" + " variants filtrades(Min. VAF: " + str(min_vaf) + \
                ",Min. coverage: " + str(min_depth) + ",Min. read support:" + str(min_read_support) + ")"

            # instantiate a VersionControl object and commit the change
            action_dict = {
                "origin_table" : origin_table,
                "origin_action": "delete",
                "target_table" : None,
                "target_action": None,
                "action_json"  : json.dumps(var, cls=AlchemyEncoder),
                "msg" : " Variant " + var.hgvsg + " eliminada"
            }
            action_str = json.dumps(action_dict)
            now = datetime.now()
            dt = now.strftime("%d/%m/%y-%H:%M:%S")
            vc = VersionControl(User_id=current_user.id, Action_id = action_id,
                Action_name=action_name, Action_json=action_str, Modified_on=dt)
            db.session.add(vc)
            db.session.commit()

    if not variants:
        flash("No s'han trobat variants per filtrar", "warning")
    else:
        if min_vaf == "" and min_depth == "" and min_read_support == "":
            flash("No s'ha aplicat cap filtre", "warning")
        else:
            flash("S'han filtrat " + str(num_filtered) + " variants", "success")
  else:
      flash("No s'ha aplicat cap filtre", "warning")
  return redirect(url_for('show_sample_details', run_id=run_id, sample=sample, sample_id=sample_id,
    active=active))

@app.route('/show_sample_details/<run_id>/<sample>/<sample_id>/<active>')
def show_sample_details(run_id, sample, sample_id, active):

  sample_info = []
  sample_variants =[]
  therapeutic_variants =[]
  other_variants = []
  rare_variants = []

  sample_info          = SampleTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).first()
  #sample_variants     = SampleVariants.query.filter_by(sample_id=sample_id).all()
  summary_qc           = SummaryQcTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).first()
  therapeutic_variants = TherapeuticTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
  other_variants       = OtherVariantsTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
  rare_variants        = RareVariantsTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
  all_cnas             = AllCnas.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
  all_fusions          = AllFusions.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
  vcf_folder           = sample_info.sample_db_dir.replace("REPORT_FOLDER", "VCF_FOLDER/IGV_SNAPSHOTS")

  All_jobs    = Job.query.order_by(desc(Job.Date)).limit(5).all()
  All_changes = VersionControl.query.order_by(desc(VersionControl.Modified_on)).all()
  All_changes_dict = defaultdict(dict)

  num_id_dict = dict()
  for c in All_changes:

      id = c.Action_id
      num_id_dict[id] = 0

      if not id in All_changes_dict:
          All_changes_dict[id] = defaultdict(dict)
          num_id_dict[id]+=1
      instruction_dict = defaultdict(dict)
      instruction_dict['action_json']     = json.loads(c.Action_json)
      instruction_dict['modified_on']     = c.Modified_on
      All_changes_dict[id]['action_data'] = instruction_dict
      All_changes_dict[id]['action_name'] = c.Action_name
      if len(num_id_dict.keys()) == 5:
          break

  merged_vcf  = sample_info.merged_vcf
  merged_json = merged_vcf.replace(".vcf", ".json")

  merged_dict = dict()
  snv_dict = defaultdict()
  with open(merged_json) as js:
      merged_dict = json.load(js)
  vaf_list = []
  if os.path.isfile(merged_vcf):
      for var in merged_dict['variants']:
          if 'REF' in merged_dict['variants'][var] and 'ALT' in merged_dict['variants'][var]:
              ref =  merged_dict['variants'][var]['REF']
              alt =  merged_dict['variants'][var]['ALT']
              if len(ref) == 1 and len(alt) == 1:
                  if ref not in snv_dict:
                      snv_dict[ref] = defaultdict()
                  if alt not in snv_dict[ref]:
                      snv_dict[ref][alt] = 0
                  snv_dict[ref][alt]+=1

          if 'AF' in merged_dict['variants'][var]:
              vaf_raw = merged_dict['variants'][var]['AF']
              tmp_list = vaf_raw.split(",")
              for v in tmp_list:
                  if v == ".":
                      continue
                  vaf_list.append(float(v))
      # for var in therapeutic_variants:
      #     vaf_list.append(float(var.allele_frequency))
      # for var in other_variants:
      #     vaf_list.append(float(var.allele_frequency))
      # for var in rare_variants:
      #     vaf_list.append(float(var.allele_frequency))
      plot_vaf = vaf_plot(vaf_list)
      plot_snv = snv_plot(snv_dict)

  summary_qc_dict = json.loads(summary_qc.summary_json)
  fastp_dict = json.loads(summary_qc.fastp_json)

  read1_basequal_dict = fastp_dict['read1_before_filtering']['quality_curves']
  plot_read1 = basequal_plot(read1_basequal_dict)

  read2_basequal_dict = fastp_dict['read2_before_filtering']['quality_curves']
  plot_read2 = basequal_plot(read2_basequal_dict)

  cnv_plotdata = json.loads(sample_info.cnv_json)
  plot_cnv = cnv_plot(cnv_plotdata)
  pie_plot, bar_plot = var_location_pie(rare_variants)

  read1_adapters_dict = fastp_dict['adapter_cutting']['read1_adapter_counts']
  read2_adapters_dict = fastp_dict['adapter_cutting']['read2_adapter_counts']
  r1_adapters_plot    = adapters_plot(read1_adapters_dict, read2_adapters_dict)

  return render_template("show_sample_details.html", title=sample, active=active,
    sample_info=sample_info, sample_variants=sample_variants, summary_qc_dict=summary_qc_dict,
    fastp_dict=fastp_dict, therapeutic_variants=therapeutic_variants, other_variants=other_variants,
    rare_variants=rare_variants, plot_read1=plot_read1, plot_read2=plot_read2, cnv_plot=plot_cnv,
    pie_plot=pie_plot, r1_adapters_plot=r1_adapters_plot, bar_plot=bar_plot, vaf_plot=plot_vaf,
    snv_plot=plot_snv, all_cnas=all_cnas, all_fusions=all_fusions, vcf_folder=vcf_folder, All_jobs=All_jobs,
    All_changes=All_changes, All_changes_dict=All_changes_dict)

@app.route('/update_therapeutic_variant/<run_id>/<sample>/<sample_id>/<var_id>/<var_classification>', methods = ['GET', 'POST'])
def update_therapeutic_variant(run_id, sample, sample_id, var_id, var_classification):

  if var_classification == "Therapeutic":
    variant = TherapeuticTable.query.filter_by(id=var_id).first()
  if var_classification == "Other":
    variant = OtherVariantsTable.query.filter_by(id=var_id).first()
  if var_classification == "Rare":
    variant = RareVariantsTable.query.filter_by(id=var_id).first()

  if request.method == "POST":
    therapies = ""
    diseases  = ""
    new_classification = ""
    if request.form.get('therapies'):
        therapies = request.form['therapies']
    if request.form.get('diseases'):
        diseases  = request.form['diseases']

    if request.form.get('blacklist_check'):
        variant.blacklist = "yes"
    else:
        variant.blacklist = "no"

    if request.form.get('bioinfo_check'):
        variant.validated_bioinfo = "yes"
    else:
        variant.validated_bioinfo = "no"
    if request.form.get('assessor_check'):
        variant.validated_assessor = "yes"
    else:
        variant.validated_assessor = "no"
    variant.therapies = therapies
    variant.tumor_type= diseases
    db.session.commit()

    if variant.blacklist == "yes":
        v = Variants.query.filter_by(hgvsg=variant.hgvsg).filter_by(hgvsc=variant.hgvsc).filter_by(hgvsp=variant.hgvsp).first()
        if v:
            v.blacklist = "yes"
            db.session.commit()

    chromosome = db.Column(db.String(20))
    pos = db.Column(db.String(20))
    ref = db.Column(db.String(20))
    alt = db.Column(db.String(20))

    if request.form.get('variant_category'):
        new_classification = request.form['variant_category']
        print("newclassification " + new_classification)
        print(var_classification)
        if new_classification != var_classification:
            if var_classification == "Therapeutic" and new_classification == "2":
                db.session.delete(variant)
                db.session.commit()

                other = OtherVariantsTable(user_id=variant.user_id,lab_id=variant.lab_id,ext1_id=variant.ext1_id,ext2_id=variant.ext2_id,
                run_id=variant.run_id, petition_id=variant.petition_id, gene=variant.gene, enst_id=variant.enst_id, hgvsp=variant.hgvsp,
                hgvsg=variant.hgvsg, hgvsc=variant.hgvsc, exon=variant.exon, variant_type=variant.variant_type, consequence=variant.consequence,
                depth=variant.depth, allele_frequency=variant.allele_frequency, read_support=variant.read_support, max_af=variant.max_af,
                max_af_pop=variant.max_af_pop, therapies=variant.therapies, clinical_trials=variant.clinical_trials, tumor_type=variant.tumor_type,
                var_json=variant.var_json, classification="Other", validated_assessor=variant.validated_assessor,
                validated_bioinfo=variant.validated_bioinfo, blacklist=variant.blacklist)

                db.session.add(other)
                db.session.commit()

            if var_classification == "Therapeutic" and new_classification == "3":
                print("2")

                db.session.delete(variant)
                db.session.commit()

                rare = RareVariantsTable(user_id=variant.user_id,lab_id=variant.lab_id,ext1_id=variant.ext1_id,ext2_id=variant.ext2_id,
                run_id=variant.run_id, petition_id=variant.petition_id, gene=variant.gene, enst_id=variant.enst_id, hgvsp=variant.hgvsp,
                hgvsg=variant.hgvsg, hgvsc=variant.hgvsc, exon=variant.exon, variant_type=variant.variant_type, consequence=variant.consequence,
                depth=variant.depth, allele_frequency=variant.allele_frequency, read_support=variant.read_support, max_af=variant.max_af,
                max_af_pop=variant.max_af_pop, therapies=variant.therapies, clinical_trials=variant.clinical_trials, tumor_type=variant.tumor_type,
                var_json=variant.var_json, classification="Rare", validated_assessor=variant.validated_assessor,
                validated_bioinfo=variant.validated_bioinfo, blacklist=variant.blacklist)

                db.session.add(rare)
                db.session.commit()

            if var_classification == "Other" and new_classification == "1":
                print("3")
                db.session.delete(variant)
                db.session.commit()

                therapeutic = TherapeuticTable(user_id=variant.user_id,lab_id=variant.lab_id,ext1_id=variant.ext1_id,ext2_id=variant.ext2_id,
                run_id=variant.run_id, petition_id=variant.petition_id, gene=variant.gene, enst_id=variant.enst_id, hgvsp=variant.hgvsp,
                hgvsg=variant.hgvsg, hgvsc=variant.hgvsc, exon=variant.exon, variant_type=variant.variant_type, consequence=variant.consequence,
                depth=variant.depth, allele_frequency=variant.allele_frequency, read_support=variant.read_support, max_af=variant.max_af,
                max_af_pop=variant.max_af_pop, therapies=variant.therapies, clinical_trials=variant.clinical_trials, tumor_type=variant.tumor_type,
                var_json=variant.var_json, classification="Therapeutic", validated_assessor=variant.validated_assessor,
                validated_bioinfo=variant.validated_bioinfo, blacklist=variant.blacklist)

                db.session.add(therapeutic)
                db.session.commit()

            if var_classification == "Other" and new_classification == "3":
                print("4")
                db.session.delete(variant)
                db.session.commit()

                rare = RareVariantsTable(user_id=variant.user_id,lab_id=variant.lab_id,ext1_id=variant.ext1_id,ext2_id=variant.ext2_id,
                run_id=variant.run_id, petition_id=variant.petition_id, gene=variant.gene, enst_id=variant.enst_id, hgvsp=variant.hgvsp,
                hgvsg=variant.hgvsg, hgvsc=variant.hgvsc, exon=variant.exon, variant_type=variant.variant_type, consequence=variant.consequence,
                depth=variant.depth, allele_frequency=variant.allele_frequency, read_support=variant.read_support, max_af=variant.max_af,
                max_af_pop=variant.max_af_pop, therapies=variant.therapies, clinical_trials=variant.clinical_trials, tumor_type=variant.tumor_type,
                var_json=variant.var_json, classification="Rare", validated_assessor=variant.validated_assessor,
                validated_bioinfo=variant.validated_bioinfo, blacklist=variant.blacklist)

                db.session.add(rare)
                db.session.commit()

            if var_classification == "Rare" and new_classification == "1":
                print("5")
                db.session.delete(variant)
                db.session.commit()

                therapeutic = TherapeuticTable(user_id=variant.user_id,lab_id=variant.lab_id,ext1_id=variant.ext1_id,ext2_id=variant.ext2_id,
                run_id=variant.run_id, petition_id=variant.petition_id, gene=variant.gene, enst_id=variant.enst_id, hgvsp=variant.hgvsp,
                hgvsg=variant.hgvsg, hgvsc=variant.hgvsc, exon=variant.exon, variant_type=variant.variant_type, consequence=variant.consequence,
                depth=variant.depth, allele_frequency=variant.allele_frequency, read_support=variant.read_support, max_af=variant.max_af,
                max_af_pop=variant.max_af_pop, therapies=variant.therapies, clinical_trials=variant.clinical_trials, tumor_type=variant.tumor_type,
                var_json=variant.var_json, classification="Therapeutic", validated_assessor=variant.validated_assessor,
                validated_bioinfo=variant.validated_bioinfo, blacklist=variant.blacklist)

                db.session.add(therapeutic)
                db.session.commit()

            if var_classification == "Rare" and new_classification == "2":

                db.session.delete(variant)
                db.session.commit()

                other = OtherVariantsTable(user_id=variant.user_id,lab_id=variant.lab_id,ext1_id=variant.ext1_id,ext2_id=variant.ext2_id,
                run_id=variant.run_id, petition_id=variant.petition_id, gene=variant.gene, enst_id=variant.enst_id, hgvsp=variant.hgvsp,
                hgvsg=variant.hgvsg, hgvsc=variant.hgvsc, exon=variant.exon, variant_type=variant.variant_type, consequence=variant.consequence,
                depth=variant.depth, allele_frequency=variant.allele_frequency, read_support=variant.read_support, max_af=variant.max_af,
                max_af_pop=variant.max_af_pop, therapies=variant.therapies, clinical_trials=variant.clinical_trials, tumor_type=variant.tumor_type,
                var_json=variant.var_json, classification="Other", validated_assessor=variant.validated_assessor,
                validated_bioinfo=variant.validated_bioinfo, blacklist=variant.blacklist)

                db.session.add(other)
                db.session.commit()

    flash("La variant s'ha modificat correctament!", "success")

  sample_info          = SampleTable.query.filter_by(lab_id=sample).first()
  sample_variants      = SampleVariants.query.filter_by(sample_id=sample_id).all()
  summary_qc           = SummaryQcTable.query.filter_by(lab_id=sample).first()
  therapeutic_variants = TherapeuticTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
  other_variants       = OtherVariantsTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
  rare_variants        = RareVariantsTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
  vcf_folder           = sample_info.sample_db_dir.replace("REPORT_FOLDER", "VCF_FOLDER/IGV_SNAPSHOTS")

  return redirect(url_for('show_sample_details',run_id=run_id, sample=sample, sample_id=sample_id,
    active="Therapeutic", vcf_folder=vcf_folder))

@app.route('/redo_action/<action_id>/<run_id>/<sample>/<sample_id>/<active>')
def redo_action(action_id, run_id, sample, sample_id, active):

    actions = VersionControl.query.filter_by(Action_id=action_id).all()
    for action in actions:
        action_json = json.loads(action.Action_json)
        #db.session.delete(action)
        #db.session.commit()
        db.session.delete(action)
        db.session.commit()
        if action_json['origin_action'] == "delete":
            action_dict = json.loads(action_json['action_json'])
            rebuild_list = []
            for field in action_dict:
                rebuild_list.append(field+"="+ str(action_dict[field]))
            rebuild_str = ','.join(rebuild_list)
            origin_table = action_json['origin_table']

            if origin_table == 'TherapeuticTable':
                oc = TherapeuticTable(**action_dict)
                db.session.add(oc)
            if origin_table == 'RareVariantsTable':
                oc = RareVariantsTable(**action_dict)
                db.session.add(oc)
            if origin_table == 'OtherVariantsTable':
                oc = OtherVariantsTable(**action_dict)
                db.session.add(oc)
            try:
                db.session.commit()
                if len(actions) == 1:
                    flash("Variant tornada a insertar!", "success")
            except:
                flash("Error durant la inserció de la Variant", "error")
    # VersionControl.query.filter_by(Action_id=action_id).delete()
    # db.session.commit()
    return redirect(url_for('show_sample_details',run_id=run_id, sample=sample, sample_id=sample_id,
      active=active))

@app.route('/remove_variant/<run_id>/<sample>/<sample_id>/<var_id>/<var_classification>', methods = ['GET', 'POST'])
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
        "origin_table" : origin_table,
        "origin_action": "delete",
        "target_table" : None,
        "target_action": None,
        "action_json"  : json.dumps(variant, cls=AlchemyEncoder),
        "msg" : " Variant " + variant.hgvsg + " eliminada"
    }
    action_str = json.dumps(action_dict)
    action_name = "Mostra: " + sample + " variant " + variant.hgvsg + " eliminada"
    now = datetime.now()
    dt = now.strftime("%d/%m/%y-%H:%M:%S")
    vc = VersionControl(User_id=current_user.id, Action_id = generate_key(16),
        Action_name=action_name, Action_json=action_str, Modified_on=dt)
    db.session.add(vc)
    db.session.commit()

    # class VersionControl(db.Model):
    #     __tablename__ = 'VERSION_CONTROL'
    #     Id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    #     User_id    = db.Column(db.String(20))
    #     Action_id  = db.Column(db.String(20))
    #     Action_json= db.Column(db.String(20))
    #     Modified_on= db.Column(db.String(20))
    # Add action to the version control system

  variant_out = ""
  if variant.hgvsg:
      variant_out = variant.hgvsg
  flash("Variant " + variant_out + " eliminada!", "success")

  sample_info          = SampleTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).first()
  vcf_folder           = sample_info.sample_db_dir.replace("REPORT_FOLDER", "VCF_FOLDER/IGV_SNAPSHOTS")
  sample_variants      = SampleVariants.query.filter_by(sample_id=sample_id).all()
  summary_qc           = SummaryQcTable.query.filter_by(lab_id=sample).first()
  therapeutic_variants = TherapeuticTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
  other_variants       = OtherVariantsTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
  rare_variants        = RareVariantsTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()

  return redirect(url_for('show_sample_details',run_id=run_id, sample=sample, sample_id=sample_id,
    active="Therapeutic", vcf_folder=vcf_folder))

@app.route('/show_therapeutic_details/<sample>/<entry_id>/<var_classification>')
def show_therapeutic_details(sample, entry_id, var_classification):

  sample_info  = SampleTable.query.filter_by(lab_id=sample).first()

  if var_classification == "Therapeutic":
    variant = TherapeuticTable.query.filter_by(id=entry_id).first()
  if var_classification == "Other":
    variant = OtherVariantsTable.query.filter_by(id=entry_id).first()
  if var_classification == "Rare":
    variant = RareVariantsTable.query.filter_by(id=entry_id).first()

  hgvsg = variant.hgvsg
  bai = sample_info.bam + ".bai"
  variant_dict = json.loads(variant.var_json)
  variant_dict['INFO']['CSQ']['Consequence'] = variant_dict['INFO']['CSQ']['Consequence'].replace("_", " ").capitalize().replace("&",", ")
  variant_dict['INFO']['CSQ']['BIOTYPE'] = variant_dict['INFO']['CSQ']['BIOTYPE'].replace("_", " ").capitalize().replace("&",", ")
  variant_dict['INFO']['CSQ']['Existing_variation'] = variant_dict['INFO']['CSQ']['Existing_variation'].replace("&",", ")
  var_name = variant_dict['CHROM'] + ":" + variant_dict['POS'] + variant_dict['REF']+">"+variant_dict['ALT']
  locus = variant_dict['CHROM'] + ":" + variant_dict['POS']

  return render_template("show_therapeutic_details.html", bai=bai, sample_info=sample_info, locus=locus,var_name=var_name, title=hgvsg, variant_dict=variant_dict)

@app.route('/download_report/<run_id>/<sample>')
def download_report(run_id, sample):

  #sample_info = SampleTable.query.filter_by(run_id=run_id, lab_id=sample).first()
  #path = run_id + "/" + sample + "/REPORT_FOLDER" + "/" + sample + ".report.pdf"
  #filename = run_id + "/" + sample + "/REPORT_FOLDER/" + sample + ".report.pdf"
  uploads = os.path.join(app.config['STATIC_URL_PATH'], run_id + "/" + sample + "/REPORT_FOLDER/")
  return send_from_directory(directory=uploads, filename=sample + ".report.pdf")

@app.route('/generate_report/<run_id>/<sample>/<sample_id>/<active>')
def generate_report(run_id, sample, sample_id, active):

    sample_info  = SampleTable.query.filter_by(run_id=run_id, lab_id=sample).first()
    therapeutics = TherapeuticTable.query.filter_by(run_id=run_id, lab_id=sample).all()
    others       = OtherVariantsTable.query.filter_by(run_id=run_id, lab_id=sample).all()
    rares        = RareVariantsTable.query.filter_by(run_id=run_id, lab_id=sample).all()
    biomarkers   = BiomakerTable.query.filter_by(run_id=run_id, lab_id=sample).all()
    summaryqc    = SummaryQcTable.query.filter_by(lab_id=sample).first()
    disclaimer   = DisclaimersTable.query.filter_by(language="cat").first()

    sample_db    = sample_info.sample_db_dir + "/" + sample + ".db"
    sample_pdf   = sample_info.report_pdf.replace(".pdf", "")

    os.remove(sample_db)

    engine = create_engine("sqlite:///" +  sample_db)
    Base = declarative_base()
    meta = MetaData()
    Session = sessionmaker(bind=engine)
    Session = sessionmaker()

    class NewSampleTable(Base):
      __tablename__ = 'SAMPLE_INFORMATION'

      id = Column(Integer, primary_key=True)
      user_id = Column(Text())
      lab_id  = Column(Text())
      ext1_id = Column(Text())
      ext2_id = Column(Text())
      run_id  = Column(Text())
      petition_id  = Column(Text())
      extraction_date =  Column(Text())
      analysis_date   =  Column(Text())
      tumor_purity   =  Column(Text())
      sex  = Column(Text())
      diagnosis  = Column(Text())
      physician_name  = Column(Text())
      medical_center  = Column(Text())
      medical_address  = Column(Text())
      sample_type  = Column(Text())
      panel    =  Column(Text())
      subpanel =  Column(Text())
      roi_bed  =  Column(Text())
      software =  Column(Text())
      software_version =  Text(String())
      bam = Column(Text())
      merged_vcf = Column(Text())
      report_pdf = Column(Text())

    class NewTherapeuticTable(Base):
      __tablename__ = 'THERAPEUTIC_VARIANTS'
      id = Column(db.Integer, primary_key=True)
      user_id = Column(Text())
      lab_id  = Column(Text())
      ext1_id = Column(Text())
      ext2_id = Column(Text())
      run_id  = Column(Text())
      petition_id  = Column(Text())
      gene  = Column(Text())
      enst_id  = Column(Text())
      hgvsp = Column(Text())
      hgvsg =  Column(Text())
      hgvsc =  Column(Text())
      exon  = Column(Text(120))
      variant_type = Column(Text(120))
      consequence =  Column(Text(120))
      depth = Column(Text(120))
      allele_frequency = Column(Text(120))
      read_support = Column(Text(120))
      max_af = Column(Text(120))
      max_af_pop = Column(Text(120))
      therapies = Column(Text(240))
      clinical_trials = Column(Text(240))
      tumor_type = Column(Text(240))
      var_json   = Column(Text(5000))
      classification = Column(Text(120))
      validated_assessor = Column(Text(120))
      validated_bioinfo  = Column(Text(120))

    class NewOtherVariantsTable(Base):
      __tablename__ = 'OTHER_VARIANTS'
      id = Column(db.Integer, primary_key=True)
      user_id = Column(Text(20))
      lab_id  = Column(Text(120))
      ext1_id = Column(Text(80))
      ext2_id = Column(Text(80))
      run_id  = Column(Text(80))
      petition_id  = Column(Text(80))
      gene  = Column(Text(120))
      enst_id  = Column(Text(120))
      hgvsp = Column(Text(120))
      hgvsg =  Column(Text(120))
      hgvsc =  Column(Text(120))
      exon  = Column(Text(120))
      variant_type = Column(Text(120))
      consequence =  Column(Text(120))
      depth = Column(Text(120))
      allele_frequency = Column(Text(120))
      read_support = Column(Text(120))
      max_af = Column(Text(120))
      max_af_pop = Column(Text(120))
      therapies = Column(Text(240))
      clinical_trials = Column(Text(240))
      tumor_type = Column(Text(240))
      var_json   = Column(Text(5000))
      classification = Column(Text(120))
      validated_assessor = Column(Text(120))
      validated_bioinfo  = Column(Text(120))

    class NewRareVariantsTable(Base):
      __tablename__ = 'RARE_VARIANTS'
      id = Column(db.Integer, primary_key=True)
      user_id = Column(Text(20))
      lab_id  = Column(Text(120))
      ext1_id = Column(Text(80))
      ext2_id = Column(Text(80))
      run_id  = Column(Text(80))
      petition_id  = Column(Text(80))
      gene  = Column(Text(120))
      enst_id  = Column(Text(120))
      hgvsp = Column(Text(120))
      hgvsg =  Column(Text(120))
      hgvsc =  Column(Text(120))
      exon  = Column(Text(120))
      variant_type = Column(Text(120))
      consequence =  Column(Text(120))
      depth = Column(Text(120))
      allele_frequency = Column(Text(120))
      read_support = Column(Text(120))
      max_af = Column(Text(120))
      max_af_pop = Column(Text(120))
      therapies = Column(Text(240))
      clinical_trials = Column(Text(240))
      tumor_type = Column(Text(240))
      var_json   = Column(Text(5000))
      classification = Column(Text(120))
      validated_assessor = Column(Text(120))
      validated_bioinfo  = Column(Text(120))

    class NewBiomarkersTable(Base):
      __tablename__ = 'BIOMARKERS'
      id = Column(Integer, primary_key=True)
      gene  = Column(Text(120))
      variant = Column(Text(120))
      exon =  Column(Text(120))
      allele_fraction =  Column(Text(120))
      sequencing_depth = Column(Text(120))

    class NewSummaryQcTable(Base):
      __tablename__ = 'SUMMARY_QC'
      id = Column(db.Integer, primary_key=True)
      total_reads = Column(Text(120))
      mean_coverage = Column(Text(120))
      enrichment =  Column(Text(120))
      call_rate = Column(Text(120))
      lost_exons =  Column(Text(120))
      pct_read_duplicates = Column(Text(120))

    class NewDisclaimersTable(Base):
      __tablename__ = 'DISCLAIMERS'
      id = Column(Integer, primary_key=True)
      gene_list = Column(Text(3000))
      lab_methodology = Column(Text(3000))
      analysis =  Column(Text(3000))
      lab_confirmation = Column(Text(3000))
      technique_limitations =  Column(Text(3000))
      legal_provisions = Column(Text(3000))

    Base.metadata.create_all(bind=engine)
    Session.configure(bind=engine)
    session = Session()

    new_sample = NewSampleTable(id=sample_info.id, user_id=sample_info.user_id, lab_id=sample_info.lab_id, ext1_id=sample_info.ext1_id,
      ext2_id=sample_info.ext2_id, run_id=sample_info.run_id, petition_id=sample_info.petition_id, extraction_date=sample_info.extraction_date,
      analysis_date=sample_info.analysis_date, tumor_purity=sample_info.tumour_purity, sex=sample_info.sex, diagnosis=sample_info.diagnosis,
      physician_name=sample_info.physician_name, medical_center=sample_info.medical_center, medical_address=sample_info.medical_address,
      sample_type=sample_info.sample_type, panel=sample_info.panel, subpanel=sample_info.subpanel, roi_bed=sample_info.roi_bed,
      software=sample_info.software, software_version=sample_info.software_version, bam=sample_info.bam, merged_vcf=sample_info.merged_vcf,
      report_pdf=sample_info.report_pdf)
    session.add(new_sample)
    session.commit()

    for var in therapeutics:
      therapeutic = NewTherapeuticTable(user_id=var.user_id,lab_id=var.lab_id,ext1_id=var.ext1_id,ext2_id=var.ext2_id,
        run_id=var.run_id, petition_id=var.petition_id, gene=var.gene, enst_id=var.enst_id, hgvsp=var.hgvsp,
        hgvsg=var.hgvsg, hgvsc=var.hgvsc, exon=var.exon, variant_type=var.variant_type, consequence=var.consequence,
        depth=var.depth, allele_frequency=var.allele_frequency, read_support=var.read_support, max_af=var.max_af,
        max_af_pop=var.max_af_pop, therapies=var.therapies, clinical_trials=var.clinical_trials, tumor_type=var.tumor_type,
        var_json=var.var_json, classification="Therapeutic", validated_assessor=var.validated_assessor,validated_bioinfo=var.validated_bioinfo)
      session.add(therapeutic)
      session.commit()

    for var in others:
      other = NewOtherVariantsTable(user_id=var.user_id,lab_id=var.lab_id,ext1_id=var.ext1_id,ext2_id=var.ext2_id,
        run_id=var.run_id, petition_id=var.petition_id, gene=var.gene, enst_id=var.enst_id, hgvsp=var.hgvsp,
        hgvsg=var.hgvsg, hgvsc=var.hgvsc, exon=var.exon, variant_type=var.variant_type, consequence=var.consequence,
        depth=var.depth, allele_frequency=var.allele_frequency, read_support=var.read_support, max_af=var.max_af,
        max_af_pop=var.max_af_pop, therapies=var.therapies, clinical_trials=var.clinical_trials, tumor_type=var.tumor_type,
        var_json=var.var_json, classification="Other", validated_assessor=var.validated_assessor,validated_bioinfo=var.validated_bioinfo)
      session.add(other)
      session.commit()

    for var in rares:
      rare = NewRareVariantsTable(user_id=var.user_id,lab_id=var.lab_id,ext1_id=var.ext1_id,ext2_id=var.ext2_id,
        run_id=var.run_id, petition_id=var.petition_id, gene=var.gene, enst_id=var.enst_id, hgvsp=var.hgvsp,
        hgvsg=var.hgvsg, hgvsc=var.hgvsc, exon=var.exon, variant_type=var.variant_type, consequence=var.consequence,
        depth=var.depth, allele_frequency=var.allele_frequency, read_support=var.read_support, max_af=var.max_af,
        max_af_pop=var.max_af_pop, therapies=var.therapies, clinical_trials=var.clinical_trials, tumor_type=var.tumor_type,
        var_json=var.var_json, classification="Rare", validated_assessor=var.validated_assessor,validated_bioinfo=var.validated_bioinfo)
      session.add(rare)
      session.commit()

    for biomarker in biomarkers:
      bm = NewBiomarkersTable(gene=biomarker.gene, variant=biomarker.variant, exon=biomarker.exon, allele_fraction='.',
      sequencing_depth=biomarker.depth)
      session.add(bm)
      session.commit()

    new_disclaimer = NewDisclaimersTable(gene_list=disclaimer.genes, lab_methodology=disclaimer.methodology, analysis=disclaimer.analysis,
      lab_confirmation=disclaimer.lab_confirmation, technique_limitations=disclaimer.technical_limitations, legal_provisions=disclaimer.legal_provisions)
    session.add(new_disclaimer)
    session.commit()

    if summaryqc:
      qc_dict = json.loads(summaryqc.summary_json)
      new_summaryqc = NewSummaryQcTable(total_reads=qc_dict['TOTAL_READS'], mean_coverage=qc_dict['MEAN_COVERAGE'],
        enrichment=qc_dict['ROI_PERCENTAGE'], call_rate= qc_dict['CALL_RATE']['30X'] ,
        lost_exons=qc_dict['LOST_EXONS']['30X'], pct_read_duplicates=qc_dict['PCT_PCR_DUPLICATES'] )
      session.add(new_summaryqc)
      session.commit()

      # Create PDF report
      bashCommand = ('{} pr {} -r {} -f pdf -t generic --db-url jdbc:sqlite:{} --db-driver org.sqlite.JDBC -o {} --jdbc-dir {}') \
      .format(app.config['JASPERSTARTER'], app.config['CANCER_JRXML'], app.config['JASPERREPORT_FOLDER_CAT'], sample_db,
      sample_pdf, app.config['JDBC_FOLDER'])

      p1 = subprocess.run(bashCommand, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)

      output = p1.stdout.decode('UTF-8')
      print(output)
      error  = p1.stderr.decode('UTF-8')
      flash("L'informe s'ha generat correctament", "success")

    # sample_id = sample_info.id
    # sample_variants      = SampleVariants.query.filter_by(sample_id=sample_id).all()
    # therapeutic_variants = TherapeuticTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
    # summary_qc           = SummaryQcTable.query.filter_by(lab_id=sample).first()
    # other_variants       = OtherVariantsTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
    # rare_variants        = RareVariantsTable.query.filter_by(lab_id=sample).filter_by(run_id=run_id).all()
    # vcf_folder           = sample_info.sample_db_dir.replace("REPORT_FOLDER", "VCF_FOLDER/IGV_SNAPSHOTS")
    #
    #active = "Therapeutic"
    # summary_qc_dict = json.loads(summary_qc.summary_json)
    #
    # fastp_dict = json.loads(summary_qc.fastp_json)
    #
    # read1_basequal_dict = fastp_dict['read1_before_filtering']['quality_curves']
    # plot_read1 = basequal_plot(read1_basequal_dict)
    #
    # read2_basequal_dict = fastp_dict['read2_before_filtering']['quality_curves']
    # plot_read2 = basequal_plot(read2_basequal_dict)
    #
    # cnv_plotdata = json.loads(sample_info.cnv_json)
    # plot_cnv = cnv_plot(cnv_plotdata)
    # pie_plot, bar_plot = var_location_pie(rare_variants)
    #
    # read1_adapters_dict = fastp_dict['adapter_cutting']['read1_adapter_counts']
    # read2_adapters_dict = fastp_dict['adapter_cutting']['read2_adapter_counts']
    # r1_adapters_plot    = adapters_plot(read1_adapters_dict, read2_adapters_dict)

    return redirect(url_for('show_sample_details',run_id=run_id, sample=sample, sample_id=sample_id,
    active=active))


    #return redirect(url_for('download_report', run_id=run_id, sample=sample))
    # return render_template("show_sample_details.html", title=sample, active=active, sample_info=sample_info,
    # sample_variants=sample_variants,summary_qc_dict=summary_qc_dict, therapeutic_variants=therapeutic_variants,
    # other_variants=other_variants, rare_variants=rare_variants, plot_read1=plot_read1, plot_read2=plot_read2,
    # cnv_plot=plot_cnv, pie_plot=pie_plot, r1_adapters_plot=r1_adapters_plot, bar_plot=bar_plot, fastp_dict=fastp_dict,
    # vcf_folder=vcf_folder)
