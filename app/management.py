from app import app
import os
import sys
import requests
from flask import Flask
from flask import request, render_template, url_for, redirect, flash
from flask_wtf import FlaskForm
import sqlite3
# from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_sqlalchemy import SQLAlchemy
from flask_sslify import SSLify
from collections import defaultdict
import time
from datetime import date
from datetime import datetime
import pandas as pd
import docx
import re

db = SQLAlchemy(app)
class Panel(db.Model):
    __tablename__  = 'PANELS'
    Id             = db.Column(db.Integer, primary_key=True, autoincrement=True)
    Panel          = db.Column(db.String(20))
    Panel_bed      = db.Column(db.String(20))
    Version        = db.Column(db.String(20))
    Subpanels      = db.Column(db.String(20))
    Size           = db.Column(db.Float())
    Genome_version = db.Column(db.String(20))
    Total_rois     = db.Column(db.Integer())
    Total_genes    = db.Column(db.Integer())
    Last_modified  = db.Column(db.String(20))
    Read_num_filter= db.Column(db.Float())
    Call_rate_filter  = db.Column(db.String(20))
    Call_rate_perc    = db.Column(db.Float())
    Lost_exons_filter = db.Column(db.String(20))
    Lost_exons_perc   = db.Column(db.Float())
    Enrichment_perc_filter = db.Column(db.Float())
    Variant_call   = db.Column(db.String(20))
    Language   = db.Column(db.String(20))

class PanelIsoforms(db.Model):
  __tablename__ = 'PANEL_ISOFORMS'
  id             = db.Column(db.Integer, primary_key=True)
  chromosome     = db.Column(db.String(50))
  start          = db.Column(db.String(50))
  end            = db.Column(db.String(50))
  ensg_id        = db.Column(db.String(50))
  enst_id        = db.Column(db.String(50))
  gene_name      = db.Column(db.String(50))
  genome_version = db.Column(db.String(50))
  panel          = db.Column(db.String(50))
  panel_version  = db.Column(db.String(50))

class Genes(db.Model):
  __tablename__ = 'GENES'
  id          = db.Column(db.Integer, primary_key=True)
  gene        = db.Column(db.String(50))
  hg19_chr    = db.Column(db.String(50))
  hg19_start  = db.Column(db.String(50))
  hg19_end    = db.Column(db.String(50))
  hg38_chr    = db.Column(db.String(50))
  hg38_start  = db.Column(db.String(50))
  hg38_end    = db.Column(db.String(50))
  ensg_id     = db.Column(db.String(50))
  ensg_version= db.Column(db.String(50))
  enst_id     = db.Column(db.String(50))
  enst_version= db.Column(db.String(50))
  ensp_id     = db.Column(db.String(50))
  ensp_version= db.Column(db.String(50))
  mane        = db.Column(db.String(50))
  mane_transcript  = db.Column(db.String(50))
  canonical     = db.Column(db.String(50))

def validate_gene_isoform_format(file):
    count_line = 0
    with open(file) as f:
        for line in f:
            count_line+=1
            if line.startswith('#'):
                continue
            line = line.rstrip("\n")
            tmp = line.split(',')
            if len (tmp) != 2:
                return False, count_line
    f.close()
    count_line = ""
    return True, count_line

def get_panel_size(bed_file):

    bases = 0
    total_rois = 0
    with open(bed_file) as f:
        for line in f:
            line = line.rstrip('\n')
            total_rois+=1
            tmp = line.split('\t')
            size = int(tmp[2]) - int(tmp[1])
            bases+=size
    f.close()
    kbases = bases/1000
    return kbases, total_rois

def get_gene_isoforms_list(gene_isoform_list, genome_version, autoselect_isoform):
    '''
        1- Validate gene name
        2- Check the most relevant isoform (MANE select)
        3- If no MANE, select canonical isoform from Ensembl
    '''
    is_ok = False
    errors = []
    count_line = 0
    gene_isoform_dict = defaultdict(dict)
    print(str(gene_isoform_list))
    for line in gene_isoform_list:
        line= line.rstrip('\n')
        line= line.rstrip('\r')

        count_line+=1
        tmp  = line.split(',')
        chromosome = ""
        start     = ""
        end       = ""
        gene      = ""
        isoform   = ""
        ensg      = ""
        if autoselect_isoform == False:
            if len(tmp) < 2:
                errors.append("Línea " + str(count_line) + ":" + line + " Es requereix la isoforma (codi ENST)")
            else:
                gene = tmp[0]
                isoform = tmp[1]
                # Now validate

                valid_gene  = Genes.query.filter_by(gene=gene).first()
                if not valid_gene:
                    errors.append("Línea " + str(count_line) + ":" + line + " El gen " + gene + " no és vàlid")
                valid_isoform  = Genes.query.filter_by(enst_id=isoform).first()
                if not valid_isoform:
                    errors.append("Línea " + str(count_line) + ":" + line + " El gen " + isoform + " no és vàlid")

                GeneObj  = Genes.query.filter_by(gene=gene, enst_id=isoform).first()
                if GeneObj and valid_gene and valid_isoform:
                    if genome_version == "hg19":
                        chromosome = GeneObj.hg19_chr
                        start = GeneObj.hg19_start
                        end = GeneObj.hg19_end
                        isoform = GeneObj.hg19_enst_id
                        ensg = GeneObj.hg19_ensg_id
                    if genome_version == "hg38":
                        chromosome = GeneObj.hg38_chr
                        start = GeneObj.hg38_start
                        end = GeneObj.hg38_end
                        isoform = GeneObj.hg38_enst_id
                        ensg = GeneObj.hg38_ensg_id
                else:
                    errors.append("Línea " + str(count_line) + ":" + line + ". El gen i la isoforma no són vàlids")
        else:
            gene = line
            GeneObjs = Genes.query.filter_by(gene=gene).all()
            if not GeneObjs:
                errors.append( "Línea " + str(count_line) + ":" + " No s'ha trobat el gen " + gene)
            for entry in GeneObjs:
                if entry.mane == "YES":
                    isoform = entry.enst_id
                    ensg    = entry.ensg_id
                    if genome_version == "hg19":
                        chromosome = entry.hg19_chr
                        start = entry.hg19_start
                        end = entry.hg19_end
                    if genome_version == "hg38":
                        chromosome = entry.hg38_chr
                        start = entry.hg38_start
                        end = entry.hg38_end
            if not isoform:
                for entry in GeneObjs:
                    if entry.canonical == "YES":
                        isoform = entry.enst_id
                        ensg    = entry.ensg_id
                        if genome_version == "hg19":
                            chromosome = entry.chromosome
                            start = entry.hg19_start
                            end = entry.hg19_end
                        if genome_version == "hg38":
                            chromosome = entry.chromosome
                            start = entry.hg38_start
                            end = entry.hg38_end
            if not isoform:
                errors.append("No s'ha trobat cap isoforma pel gen " + gene)

        gene_isoform_dict[gene]['CHR']  = chromosome
        gene_isoform_dict[gene]['START']= start
        gene_isoform_dict[gene]['END']  = end
        gene_isoform_dict[gene]['ENST'] = isoform
        gene_isoform_dict[gene]['ENSG'] = ensg
    return gene_isoform_dict, errors

def get_gene_isoforms_file(gene_isoform_file, genome_version, autoselect_isoform):
    '''
        1- Validate gene name
        2- Check the most relevant isoform (MANE select)
        3- If no MANE, select canonical isoform from Ensembl
    '''
    is_ok  = False
    errors = []
    count_line = 0
    gene_isoform_dict = defaultdict(dict)
    with open(gene_isoform_file) as f:
        for line in f:
            count_line+=1
            line = line.rstrip('\n')
            tmp  = line.split(',')
            chromosome = ""
            start     = ""
            end       = ""
            gene      = ""
            isoform   = ""
            ensg      = ""
            if autoselect_isoform == False:
                if len(tmp) < 2:
                    errors.append("Línea " + str(count_line) + ":" + line + " Es requereix la isoforma (codi ENST)")
                else:
                    gene = tmp[0]
                    isoform = tmp[1]
                    # Now validate

                    valid_gene  = Genes.query.filter_by(gene=gene).first()
                    if not valid_gene:
                        errors.append("Línea " + str(count_line) + ":" + line + " El gen " + gene + " no és vàlid")
                    valid_isoform  = Genes.query.filter_by(enst_id=isoform).first()
                    if not valid_isoform:
                        errors.append("Línea " + str(count_line) + ":" + line + " El gen " + isoform + " no és vàlid")

                    GeneObj  = Genes.query.filter_by(gene=gene, enst_id=isoform).first()
                    if GeneObj and valid_gene and valid_isoform:
                        if genome_version == "hg19":
                            chromosome = GeneObj.hg19_chr
                            start      = GeneObj.hg19_start
                            end        = GeneObj.hg19_end
                            isoform    = GeneObj.hg19_enst_id
                            ensg       = GeneObj.hg19_ensg_id
                        if genome_version == "hg38":
                            chromosome = GeneObj.hg38_chr
                            start      = GeneObj.hg38_start
                            end        = GeneObj.hg38_end
                            isoform    = GeneObj.hg38_enst_id
                            ensg       = GeneObj.hg38_ensg_id
                    else:
                        errors.append("Línea " + str(count_line) + ":" + line + ". El gen i la isoforma no són vàlids")
            else:
                gene = line
                GeneObjs = Genes.query.filter_by(gene=gene).all()
                if not GeneObjs:
                    errors.append( "Línea " + str(count_line) + ":" + " No s'ha trobat el gen " + gene)
                for entry in GeneObjs:
                    if entry.mane == "YES":
                        isoform = entry.enst_id
                        ensg    = entry.ensg_id
                        if genome_version == "hg19":
                            chromosome = entry.hg19_chr
                            start = entry.hg19_start
                            end = entry.hg19_end
                        if genome_version == "hg38":
                            chromosome = entry.hg38_chr
                            start = entry.hg38_start
                            end = entry.hg38_end
                if not isoform:
                    for entry in GeneObjs:
                        if entry.canonical == "YES":
                            isoform = entry.enst_id
                            ensg    = entry.ensg_id
                            if genome_version == "hg19":
                                chromosome = entry.chromosome
                                start = entry.hg19_start
                                end = entry.hg19_end
                            if genome_version == "hg38":
                                chromosome = entry.chromosome
                                start = entry.hg38_start
                                end = entry.hg38_end
                if not isoform:
                    errors.append("No s'ha trobat cap isoforma pel gen " + gene)

            gene_isoform_dict[gene]['CHR']  = chromosome
            gene_isoform_dict[gene]['START']= start
            gene_isoform_dict[gene]['END']  = end
            gene_isoform_dict[gene]['ENST'] = isoform
            gene_isoform_dict[gene]['ENSG'] = ensg
    f.close()
    return gene_isoform_dict, errors

def get_ensembl_data(gene_isoform_file, genome_version):

    errors = []
    gene_isoform_dict = defaultdict(dict)
    if genome_version == 'hg19':
        server = "https://grch37.rest.ensembl.org"
    else:
        server = "https://rest.ensembl.org"
    with open (gene_isoform_file) as f:
        for line in f:
            line = line.rstrip('\n')
            tmp  = line.split('\t')
            gene    = ""
            isoform = ""
            if len(tmp) > 1:
                gene = tmp[0]
                isoform = tmp[1]
            else:
                gene = line

            ext = "/lookup/symbol/homo_sapiens/" + gene +"?expand=1"
            r = requests.get(server+ext, headers={ "Content-Type" : "application/json"})
            decoded = r.json()
            chromosome = ""
            start = ""
            end  = ""
            ensg = ""
            canonical_transcript = ""
            if decoded:
                chromosome = decoded['seq_region_name']
                ensg = decoded['id']
                if 'Transcript' in decoded:
                    for item in decoded['Transcript']:
                        if item['is_canonical'] == 1:
                            canonical_transcript = item['id']
                            start = item['start']
                            end   = item['end']
                            break
                    if not canonical_transcript:
                        errors.append("No s'ha trobat la isoforma canònica del gen " + gene)
                    else:
                        gene_isoform_dict[gene]['CHR']  = chromosome
                        gene_isoform_dict[gene]['START']= start
                        gene_isoform_dict[gene]['END']  = end
                        gene_isoform_dict[gene]['ENST'] = canonical_transcript
                        gene_isoform_dict[gene]['ENSG'] = ensg
            else:
                errors.append("No s'ha trobat el gen " + gene)

    return gene_isoform_dict, errors

@app.route('/')
# @app.route('/show_panels')
# def show_panels():
#     Panels = Panel.query.all()
#     return render_template("panel_management.html", Panels=Panels, title="Panells")

@app.route('/panel_configuration/<panel>')
def panel_configuration(panel):
    panel_info = Panel.query.filter_by(Panel=panel).first()
    panel_isoforms = []
    if panel_info:
        panel_isoforms = PanelIsoforms.query.filter_by(panel=panel).all()
    return render_template("panel_configuration.html", panel_info=panel_info,
        roi_info=panel_isoforms, title=panel)

@app.route('/panel_creation_board')
def panel_creation_board():
    return render_template("panel_creation.html", title="Panells")

# @app.route('/create_panel', methods = ['GET', 'POST'])
# def create_panel():
#
#     is_ok = True
#     errors =[]
#     panel_name      = ""
#     panel_bed       = ""
#     panel_path      = ""
#     panel_version   = ""
#     genome_version  = ""
#     variant_analysis= ""
#     report_lang     = ""
#     call_rate_filter= ""
#     call_rate_perc  = ""
#     lost_exons_filter= ""
#     lost_exons_perc = ""
#     number_reads    = ""
#     enrichment_perc = ""
#     panel_size      = ""
#     total_genes     = ""
#     if request.method == "POST":
#         if request.form['panel_name']:
#             panel_name = request.form['panel_name']
#         else:
#             is_ok = False
#             flash("És requereix el nom del panell!", "warning")
#         if request.form['panel_version']:
#             panel_version = request.form['panel_version']
#         else:
#             is_ok = False
#             flash("És requereix una versió de panell", "warning")
#         if request.form.get('genome_version'):
#             option = request.form['genome_version']
#             if option  == "1":
#                 genome_version = "hg19"
#             elif option == "2":
#                 genome_version = "hg38"
#         else:
#             is_ok = False
#             flash("Es requereix la versió de genoma", "warning")
#         if request.form.get('variant_analysis'):
#             variant_analysis = request.form['variant_analysis']
#             if variant_analysis == "1":
#                 variant_analysis = "Germline"
#             elif variant_analysis == "2":
#                 variant_analysis = "Somatic"
#         else:
#             is_ok = False
#             flash("Es requereix el tipus d'anàlisi de variants", "warning")
#         if request.form.get('report_lang'):
#             report_lang = request.form['report_lang']
#             if report_lang == "1":
#                 report_lang = "catalan"
#             elif variant_analysis == "2":
#                 report_lang = "english"
#         else:
#             is_ok = False
#             flash("Es requereix el llenguatge dels informes", "warning")
#
#         if request.files:
#             panel_bed = request.files["panel_bed"]
#             panel_dir = app.config['WORKING_DIRECTORY'] + "/PANEL_FOLDER/" + panel_name
#             if not os.path.isdir(panel_dir):
#                 os.mkdir(panel_dir)
#             if not panel_bed:
#                 flash("Es requereix un fitxer en format .bed", "warning")
#                 is_ok = False
#             else:
#                 if panel_bed.filename.endswith(".bed"):
#                     panel_bed.save(os.path.join(panel_dir, panel_bed.filename))
#                     panel_path = panel_dir + "/" + panel_bed.filename
#                     panel_size,total_rois =  get_panel_size(panel_path)
#                 else:
#                     flash("Es requereix un fitxer en format .bed", "warning")
#                     is_ok = False
#
#             get_file_info = True
#             if request.form["gene_isoform_text"]:
#                 gene_isoform_text = request.form["gene_isoform_text"]
#                 gene_isoform_list = gene_isoform_text.split("\n")
#
#                 autoselect_isoform = False
#                 if request.form.get('canonical_isoform'):
#                     autoselect_isoform = True
#
#                 gene_isoform_dict, gene_isoform_errors = get_gene_isoforms_list(gene_isoform_list, genome_version, autoselect_isoform)
#                 total_genes = len(gene_isoform_dict.keys())
#                 if gene_isoform_errors:
#                     is_ok = False
#                     for error in gene_isoform_errors:
#                         flash(error, "warning")
#                         break
#                 else:
#                     for gene in gene_isoform_dict:
#                         Gene = panel_isoforms(chromosome=gene_isoform_dict[gene]['CHR'], start=gene_isoform_dict[gene]['START'],
#                         end=gene_isoform_dict[gene]['END'],ensg_id=gene_isoform_dict[gene]['ENSG'],
#                         enst_id=gene_isoform_dict[gene]['ENST'], gene_name=gene, genome_version=genome_version,
#                         panel=panel_name, panel_version=panel_version )
#                         db.session.add(Gene)
#                         db.session.commit()
#                 get_file_info = False
#             if request.files["gene_isoform_file"] and get_file_info == True:
#                 gene_isoform_file = request.files["gene_isoform_file"]
#                 gene_isoform_file.save(os.path.join(panel_dir, gene_isoform_file.filename))
#                 gene_iso_path = panel_dir + "/" + gene_isoform_file.filename
#
#                 autoselect_isoform = False
#                 if request.form.get('canonical_isoform'):
#                     autoselect_isoform = True
#
#                 gene_isoform_dict, gene_isoform_errors = get_gene_isoforms_file(gene_iso_path,
#                     genome_version, autoselect_isoform)
#                 total_genes = len(gene_isoform_dict.keys())
#                 if gene_isoform_errors:
#                     is_ok = False
#                     for error in gene_isoform_errors:
#                         flash(error, "warning")
#                         break
#                 else:
#                     for gene in gene_isoform_dict:
#                         Gene = panel_isoforms(chromosome=gene_isoform_dict[gene]['CHR'],
#                         start=gene_isoform_dict[gene]['START'],
#                         end=gene_isoform_dict[gene]['END'],
#                         ensg_id=gene_isoform_dict[gene]['ENSG'],
#                         enst_id=gene_isoform_dict[gene]['ENST'],
#                         gene_name=gene, genome_version=genome_version,
#                         panel=panel_name, panel_version=panel_version)
#                         db.session.add(Gene)
#                         db.session.commit()
#
#         if request.form.get('call_rate_filter'):
#             call_rate_filter = request.form['call_rate_filter']
#             if call_rate_filter == "1":
#                call_rate_filter = "1X"
#             if call_rate_filter == "2":
#                call_rate_filter = "10X"
#             if call_rate_filter == "3":
#                call_rate_filter = "20X"
#             if call_rate_filter == "4":
#                call_rate_filter = "30X"
#             if call_rate_filter == "5":
#                call_rate_filter = "100X"
#             if call_rate_filter == "6":
#                call_rate_filter = "200X"
#         else:
#             is_ok = False
#             flash("Es requereix un filtre de call rate", "warning")
#
#         if request.form.get('call_rate_perc'):
#             call_rate_perc = request.form['call_rate_perc']
#         else:
#             is_ok = False
#             flash("Es requereix un percentatge de bases", "warning")
#
#         if request.form.get('lost_exons_filter'):
#             lost_exons_filter = request.form['lost_exons_filter']
#             if lost_exons_filter == "1":
#                lost_exons_filter = "1X"
#             if lost_exons_filter == "2":
#                lost_exons_filter = "10X"
#             if lost_exons_filter == "3":
#                lost_exons_filter = "20X"
#             if lost_exons_filter == "4":
#                lost_exons_filter = "30X"
#             if lost_exons_filter == "5":
#                lost_exons_filter = "100X"
#             if lost_exons_filter == "6":
#                lost_exons_filter = "200X"
#         else:
#             is_ok = False
#             flash("Es requereix un percentatge d'exons perduts", "warning")
#         if request.form.get('lost_exons_perc'):
#             lost_exons_perc = request.form['lost_exons_perc']
#         if request.form['number_reads']:
#             number_reads = request.form['number_reads']
#         if request.form.get('enrichment_perc'):
#             enrichment_perc = request.form['enrichment_perc']
#         now = datetime.now()
#         dt_string = now.strftime("%d/%m/%Y %H:%M:%S")
#         if is_ok:
#             New_panel = Panel(Panel=panel_name, Panel_bed=panel_path, Version=panel_version, Size=panel_size,
#             Genome_version=genome_version, Total_rois=total_rois, Total_genes=total_genes, Last_modified=dt_string,
#             Read_num_filter=number_reads, Call_rate_filter=call_rate_filter, Call_rate_perc=call_rate_perc,
#             Lost_exons_filter=lost_exons_filter,Lost_exons_perc=lost_exons_perc,
#             Enrichment_perc_filter=enrichment_perc, Variant_call=variant_analysis, Language=report_lang)
#
#             panel_exists = Panel.query.filter_by(Panel=panel_name).first()
#             if panel_exists:
#                 flash("Ja existeix un panell amb el nom " + panel_name, "danger")
#
#             else:
#                 db.session.add(New_panel)
#                 db.session.commit()
#                 flash("El nou panell s'ha creat correctament!", "success")
#
#     Panels = Panel.query.all()
#     return render_template("panel_management.html", Panels=Panels, title="Panells")

@app.route('/delete_panel/<panel>', methods=['GET', 'POST'])
def delete_panel(panel):

    PanelObj = Panel.query.filter_by(Panel=panel).first()

    db.session.delete(PanelObj)
    db.session.commit()

    Isoforms = panel_isoforms.query.filter_by(panel=panel).all()
    for item in Isoforms:
        db.session.delete(item)
        db.session.commit()

    Panels = Panel.query.all()

    flash("S'ha eliminat correctament el panell " + panel, "success")
    return render_template("panel_management.html", Panels=Panels, title="Panells")

@app.route('/update_panel/<panel>', methods = ['GET', 'POST'])
def update_panel(panel):

    is_ok = True
    errors =[]
    panel_name      = ""
    panel_version   = ""
    genome_version  = ""
    variant_analysis= ""
    report_lang     = ""
    call_rate_filter= ""
    call_rate_perc  = ""
    lost_exons_filter= ""
    lost_exons_perc = ""
    number_reads    = ""
    enrichment_perc = ""
    if request.method == "POST":
        if request.form['panel_name']:
            panel_name = request.form['panel_name']
        else:
            is_ok = False
            flash("És requereix el nom del panell!", "warning")
        if request.form['panel_version']:
            panel_version = request.form['panel_version']
        else:
            is_ok = False
            flash("És requereix una versió de panell", "warning")
        if request.form.get('genome_version'):
            option = request.form['genome_version']
            if option  == "1":
                genome_version = "hg19"
            elif option == "2":
                genome_version = "hg38"
        else:
            is_ok = False
            flash("Es requereix la versió de genoma", "warning")
        if request.form.get('variant_analysis'):
            variant_analysis = request.form['variant_analysis']
            if variant_analysis == "1":
                variant_analysis = "Germline"
            elif variant_analysis == "2":
                variant_analysis = "Somatic"
        else:
            is_ok = False
            flash("Es requereix el tipus d'anàlisi de variants", "warning")
        if request.form.get('report_lang'):
            report_lang = request.form['report_lang']
            if report_lang == "1":
                report_lang = "catalan"
            elif variant_analysis == "2":
                report_lang = "english"
        else:
            is_ok = False
            flash("Es requereix el llenguatge dels informes", "warning")

        if request.form.get('call_rate_filter'):
            call_rate_filter = request.form['call_rate_filter']
            if call_rate_filter == "1":
               call_rate_filter = "1X"
            if call_rate_filter == "2":
               call_rate_filter = "10X"
            if call_rate_filter == "3":
               call_rate_filter = "20X"
            if call_rate_filter == "4":
               call_rate_filter = "30X"
            if call_rate_filter == "5":
               call_rate_filter = "100X"
            if call_rate_filter == "6":
               call_rate_filter = "200X"
        else:
            is_ok = False
            flash("Es requereix un filtre de call rate", "warning")

        if request.form.get('call_rate_perc'):
            call_rate_perc = request.form['call_rate_perc']
        else:
            is_ok = False
            flash("Es requereix un percentatge de bases", "warning")

        if request.form.get('lost_exons_filter'):
            lost_exons_filter = request.form['lost_exons_filter']
            if lost_exons_filter == "1":
               lost_exons_filter = "1X"
            if lost_exons_filter == "2":
               lost_exons_filter = "10X"
            if lost_exons_filter == "3":
               lost_exons_filter = "20X"
            if lost_exons_filter == "4":
               lost_exons_filter = "30X"
            if lost_exons_filter == "5":
               lost_exons_filter = "100X"
            if lost_exons_filter == "6":
               lost_exons_filter = "200X"
        else:
            is_ok = False
            flash("Es requereix un percentatge d'exons perduts", "warning")
        if request.form.get('lost_exons_perc'):
            lost_exons_perc = request.form['lost_exons_perc']
        if request.form['number_reads']:
            number_reads = request.form['number_reads']
        if request.form.get('enrichment_perc'):
            enrichment_perc = request.form['enrichment_perc']

    panel_info = Panel.query.filter_by(Panel=panel).first()

    if is_ok == True:
        panel_info.Panel = panel_name
        panel_info.Version = panel_version
        panel_info.Genome_version = genome_version
        panel_info.Read_num_filter = number_reads
        panel_info.Call_rate_filter = call_rate_filter
        if call_rate_perc != "":
            panel_info.Call_rate_perc = float(call_rate_perc)
        panel_info.Lost_exons_filter = lost_exons_filter
        if lost_exons_perc != "":
            panel_info.Lost_exons_perc = float(lost_exons_perc)
        panel_info.Variant_call = variant_analysis
        panel_info.Language = report_lang
        now = datetime.now()
        dt_string = now.strftime("%d/%m/%Y %H:%M:%S")
        panel_info.Last_modified = dt_string
        db.session.commit()
        flash("El panell s'ha actualitzat!", "success")
    isoforms = ""
    if panel_info:
        isoforms = PanelIsoforms.query.filter_by(panel=panel).all()
    return render_template("panel_configuration.html", panel_info=panel_info,
        roi_info=isoforms, title=panel)

@app.route('/update_gene_isoform/<panel>/<roi_id>', methods = ['GET', 'POST'])
def update_gene_isoform(panel, roi_id):

    gene = ""
    ensg = ""
    enst = ""
    if request.method == "POST":
        if request.form['gene_name']:
            gene = request.form['gene_name']
        if request.form['ensg']:
            ensg = request.form['ensg']
        if request.form['enst']:
            enst = request.form['enst']

        isoform = PanelIsoforms.query.filter_by(id=roi_id).first()
        if isoforms:
            isoform.ensg_id   = ensg
            isoform.enst_id   = enst
            isoform.gene_name = gene
            db.session.commit()
            flash("S'ha modificat correctament el gen " + isoform.gene_name , "success")

    panel_info = Panel.query.filter_by(Panel=panel).first()
    isoforms = PanelIsoforms.query.filter_by(panel=panel).all()
    return render_template("panel_configuration.html", panel_info=panel_info,
        roi_info=isoforms, title=panel)
