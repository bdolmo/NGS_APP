
from flask import Flask
from flask import request, render_template, url_for, redirect, flash
from flask_wtf import FlaskForm, RecaptchaField, Form
from wtforms import Form, StringField,PasswordField,validators
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from flask_sslify import SSLify
from sqlalchemy.sql import and_, or_
from sqlalchemy import MetaData, create_engine, Column, Integer, String, Text, desc
from sqlalchemy.ext.declarative import declarative_base, DeclarativeMeta
from sqlalchemy.orm import sessionmaker
import json
from collections import defaultdict
from rq import Queue, cancel_job
import os
import time
from command import launch_ngs_analysis, launch_lowpass_analysis
from pathlib import Path
import plotly
import plotly.graph_objs as go
import plotly.express as px
from plotly.subplots import make_subplots
from app import app, db

from app.models import Job, SampleTable, LowpassCnv, VersionControl
@app.route('/')
@app.route('/show_lowpass_run/<run_id>')
def show_lowpass_run(run_id):

  run_samples = SampleTable.query.filter_by(run_id=run_id).all()
  run_dict = defaultdict(dict)
  if run_samples:

    run_dict['RUN_ID']        = run_id
    run_dict['PETITION_ID']   = run_samples[0].petition_id
    run_dict['N_SAMPLES']     = len(run_samples)
    run_dict['ANALYSIS_DATE'] = run_samples[0].analysis_date

  return render_template("show_lowpass_run.html", title=run_id,
    run_samples=run_samples, run_dict=run_dict)

@app.route('/show_lowpass_results/<run_id>/<lab_id>')
def show_lowpass_results(run_id, lab_id):

      sample_info = SampleTable.query.filter_by(lab_id=lab_id).filter_by(run_id=run_id).first()
      All_cnvs    = LowpassCnv.query.filter_by(lab_id=lab_id).filter_by(run_id=run_id).all()
      All_jobs    = Job.query.order_by(desc(Job.Date)).limit(5).all()
      All_changes_dict = get_latest_changes(5)
      cnv_plot_dict = json.loads(sample_info.cnv_json)

      genomewide_plot = plot_genomewide_ratios(cnv_plot_dict)
      return render_template("show_lowpass_results.html",title=lab_id, active="CNV",
          sample_info=sample_info, All_changes_dict=All_changes_dict, All_jobs=All_jobs,
          All_cnvs=All_cnvs, genomewide_plot=genomewide_plot)

@app.route('/show_lowpass_variant/')
def show_lowpass_variant():

    var_id = request.args.get('var_id')
    lab_id = request.args.get('lab_id')
    run_id = request.args.get('run_id')
    sample_info = SampleTable.query.filter_by(lab_id=lab_id).filter_by(run_id=run_id).first()
    cnv = LowpassCnv.query.filter_by(id=var_id).first()
    cnv_name = ("{}:{}-{}").format(cnv.chromosome, str(cnv.start), str(cnv.end))
    acmg_keywords_dict = json.loads(cnv.acmg_keywords.replace("\'", "\""))
    return render_template("show_lowpass_variant.html",title=cnv_name, sample_info=sample_info,
        cnv_name=cnv_name, cnv=cnv, acmg_keywords_dict=acmg_keywords_dict,
        acmg_2019_keyword_del_description=acmg_2019_keyword_del_description,
        acmg_2019_keyword_dup_description=acmg_2019_keyword_dup_description)


def get_latest_changes(num):

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
          if len(num_id_dict.keys()) == num:
              break

      return All_changes_dict

def plot_genomewide_ratios(cnv_dict):

    x_list = []
    y_list = []
    z_list = []
    a_list = []
    b_list = []

    chromosome_dict = defaultdict()
    color_list = []
    for roi in cnv_dict:

      if float(cnv_dict[roi]['ratio']) > 3:
          continue

      x_list.append(float(roi))
      #print(cnv_dict[roi]['Coordinates'])
      cnv_ratio = float(cnv_dict[roi]['ratio'])
      y_list.append(cnv_ratio)
      # segment_ratio = float(cnv_dict[roi]['segment_log2'])
      # z_list.append(segment_ratio)
      chr   = cnv_dict[roi]['chr']
      start = cnv_dict[roi]['start']
      a_list.append(chr+":"+start)

      if not chr in chromosome_dict:
          chromosome_dict[chr] = roi
      if cnv_ratio < 0.6:
          status = "DEL"
          color_list.append("red")
      elif cnv_ratio > 1.4:
          status = "DUP"
          color_list.append("green")

      else:
          status = "Diploid"
          color_list.append("grey")

      b_list.append(status)
    trace1 = go.Scattergl(x=x_list, y=y_list, mode='markers', text=a_list, name='Ratio',
    marker=dict(color='lightgrey'))
    #trace2 = go.Scatter(x=x_list, y=z_list, mode='lines', text=a_list, name='Segment')
    trace3 = go.Scattergl(x=x_list, y=b_list, mode='markers', text=b_list, name='Status')
    #data = [trace1, trace2]
    data = [trace1, trace3]
    layout= go.Layout (
       paper_bgcolor= 'rgba(0,0,0,0)',
       plot_bgcolor = 'rgba(0,0,0,0)'
    )
    fig = go.Figure(data=data, layout=layout )
    fig.update_traces(marker=dict(size=1.7, line=dict(width=0.5, color='grey')))

    chr_name_list = []
    chr_start_list = []
    for chr in chromosome_dict:
        fig.add_vrect(x0=chromosome_dict[chr], x1=chromosome_dict[chr], line_width=2,
            fillcolor="black", opacity=0.4)
        chr_name_list.append(chr)
        chr_start_list.append(chromosome_dict[chr])

    # fig.update_xaxes(
    #     ticktext=chr_name_list,
    #     tickvals=chr_start_list,
    # )


    fig.update_layout(
      xaxis_title="#Regió",
      yaxis_title="Ratio",
      margin=dict(l=0, r=0, b=0, t=0 ),
      height=350,
      width=1400,
    )
    fig.update_xaxes(ticktext=chr_name_list, tickvals=chr_start_list, showline=True,
        linewidth=1.5, linecolor='black', mirror=False)
    fig.update_yaxes(showline=True, linewidth=1.5, linecolor='black', mirror=False)

    graphJSON = json.dumps(fig, cls=plotly.utils.PlotlyJSONEncoder)

    return graphJSON


acmg_2019_keyword_dup_description = {
    '1A-B': 'Contains protein-coding or other known functionally important elements',
    '2A': "Complete overlap of an established HI gene/genomic region",
    '2B': "Partial overlap of an established HI genomic region." +\
        'The observed CNV does NOT contain the known causative gene or critical region for this established HI genomic region OR' +\
            "Unclear if known causative gene or critical region is affected OR" +\
            "No specific causative gene or critical region has been established for this HI genomic region" +\
        "",
    '2C' : "Identical in gene content to the established benign copy number gain",
    '2D' : "Smaller than established benign copy numbe gain, breakpoint(s) does not interrupt proteincoding genes",
    '2E' : "Smaller than established benign copy number gain, breakpoint(s) potentially interrupts proteincoding gene",
    '2F' : "Larger than known benign copy number gain, does not include additional protein-coding genes",
    '2G' : "Overlaps a benign copy number gain but includes additional genomic material",
    '2H' : "HI gene fully contained within observed copy number gain",
    '2I' : "Both breakpoints are within the same gene (gene-level sequence variant, possibly resulting in loss of function (LOF))",
    '2J' : "One breakpoint is within an established HI gene, patient’s phenotype is either inconsistent with what is expected for LOF of that gene OR unknown",
    '2K' : "One breakpoint is within an established HI gene, patient’s phenotype is highly specific and consistent with what is expected for LOF of that gene",
    '2L' : "One or both breakpoints are within gene(s) of no established clinical significance",
    '3'  : 'Number of protein-coding RefSeq genes wholly or partially included in the copy number loss',
    '4A' : 'The reported phenotype is highly specific and relatively unique to the gene or genomic region',
    '4B' : 'The reported phenotype is consistent with the gene/genomic region, is highly specific, but not necessarily unique to the gene/genomic region',
    '4C' : 'The reported phenotype is consistent with the gene/genomic region, but not highly specific and/or with high genetic heterogeneity',
    '4D' : 'The reported phenotype is NOT consistent with what is expected for the gene/genomic region or not consistent in general',
    '4E' : 'Reported proband has a highly specific phenotype consistent with the gene/genomic region, but the inheritance of the variant is  unknown',
    '4F' : '3-4 observed segregations',
    '4G' : '5-6 observed segregations',
    '4H' : ' 7 or more observed segregations',
    '4F-H':' observed segregations',
    '4I' : ' Variant is NOT found in another individual in the proband’s family AFFECTED with a consistent, specific, well-defined phenotype (no known phenocopies)',
    '4J' : ' Variant IS found in another individual in the proband’s family UNAFFECTED with the specific, well-defined phenotype observed in the proband',
    '4K' : ' Variant IS found in another individual in the proband’s family UNAFFECTED with the non-specific phenotype observed in the proband',
    '4L' : ' Statistically significant increase amongst observations in cases (with a consistent, specific, well-defined phenotype) compared to controls',
    '4M' : ' Statistically significant increase amongst observations in cases (without a consistent, non-specific phenotype OR unknown phenotype) compared to controls',
    '4N' : ' No statistically significant difference between observations in cases and controls',
    '4O' : 'Overlap with common population variation',
    '5A' : 'Use appropriate category from de novo scoring section in Section 4.',
    '5B' : 'Patient with specific, well-defined phenotype and no family history. CNV is inherited from an apparently unaffected parent.',
    '5C' : 'Patient with non-specific phenotype and no family history. CNV is inherited from an apparently unaffected parent.',
    '5D' : 'CNV segregates with a consistent phenotype observed in the patient’s family.',
    '5E' : 'Use appropriate category from nonsegregation section in Section 4.',
    '5F' : 'Inheritance information is unavailable or uninformative.',
    '5G' : 'Inheritance information is unavailable or uninformative. The patient phenotype is nonspecific, but is consistent with what has been described in similar cases.',
    '5H' : 'Inheritance information is unavailable or uninformative. The patient phenotype is highly specific and consistent with what has been described in similar cases.',

}


acmg_2019_keyword_del_description = {
    '1A-B': 'Contains protein-coding or other known functionally important elements',
    '2A': "Complete overlap of an established HI gene/genomic region",
    '2B': "Partial overlap of an established HI genomic region." +\
        'The observed CNV does NOT contain the known causative gene or critical region for this established HI genomic region OR' +\
            "Unclear if known causative gene or critical region is affected OR" +\
            "No specific causative gene or critical region has been established for this HI genomic region" +\
        "",
    '2C' : 'Partial overlap with the 5’ end of an established HI gene (3’ end of the gene not involved)',
    '2D' : 'Partial overlap with the 3’ end of an established HI gene (5’ end of the gene not involved)',
    '2E' : 'Both breakpoints are within the same gene (intragenic CNV; gene-level sequence variant',
    '2F' : 'Completely contained within anestablished benign CNV region',
    '2G' : 'Overlaps an established benign CNV, but includes additional genomic material',
    '2H' : 'Two or more HI predictors suggest thatAT LEAST ONE gene in the interval is haploinsufficient (HI)',
    '3'  : 'Number of protein-coding RefSeq genes wholly or partially included in the copy number loss',
    '4A' : 'The reported phenotype is highly specific and relatively unique to the gene or genomic region',
    '4B' : 'The reported phenotype is consistent with the gene/genomic region, is highly specific, but not necessarily unique to the gene/genomic region',
    '4C' : 'The reported phenotype is consistent with the gene/genomic region, but not highly specific and/or with high genetic heterogeneity',
    '4D' : 'The reported phenotype is NOT consistent with what is expected for the gene/genomic region or not consistent in general',
    '4E' : 'Reported proband has a highly specific phenotype consistent with the gene/genomic region, but the inheritance of the variant is  unknown',
    '4F' : '3-4 observed segregations',
    '4G' : '5-6 observed segregations',
    '4H' : ' 7 or more observed segregations',
    '4F-H':' observed segregations',
    '4I' : ' Variant is NOT found in another individual in the proband’s family AFFECTED with a consistent, specific, well-defined phenotype (no known phenocopies)',
    '4J' : ' Variant IS found in another individual in the proband’s family UNAFFECTED with the specific, well-defined phenotype observed in the proband',
    '4K' : ' Variant IS found in another individual in the proband’s family UNAFFECTED with the non-specific phenotype observed in the proband',
    '4L' : ' Statistically significant increase amongst observations in cases (with a consistent, specific, well-defined phenotype) compared to controls',
    '4M' : ' Statistically significant increase amongst observations in cases (without a consistent, non-specific phenotype OR unknown phenotype) compared to controls',
    '4N' : ' No statistically significant difference between observations in cases and controls',
    '4O' : 'Overlap with common population variation',
    '5A' : 'Use appropriate category from de novo scoring section in Section 4.',
    '5B' : 'Patient with specific, well-defined phenotype and no family history. CNV is inherited from an apparently unaffected parent.',
    '5C' : 'Patient with non-specific phenotype and no family history. CNV is inherited from an apparently unaffected parent.',
    '5D' : 'CNV segregates with a consistent phenotype observed in the patient’s family.',
    '5E' : 'Use appropriate category from nonsegregation section in Section 4.',
    '5F' : 'Inheritance information is unavailable or uninformative.',
    '5G' : 'Inheritance information is unavailable or uninformative. The patient phenotype is nonspecific, but is consistent with what has been described in similar cases.',
    '5H' : 'Inheritance information is unavailable or uninformative. The patient phenotype is highly specific and consistent with what has been described in similar cases.',
}
