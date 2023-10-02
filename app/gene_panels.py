from app import app
import sys
import os
import re
import requests
from pathlib import Path
from flask import Flask
from flask import request, jsonify, render_template, url_for, redirect, flash
from flask_sqlalchemy import SQLAlchemy
from flask_wtf import FlaskForm
import sqlite3
import gzip
import json
import pybedtools
import numpy as np
import subprocess
from collections import defaultdict, OrderedDict
from app.models import Panel, Genes, PanelContent

# db = SQLAlchemy(app)

@app.route('/')
@app.route('/show_panels')
def show_panels():
    Panels = Panel.query.all()
    return redirect("www.google.com")

@app.route('/panel_register', methods = ['GET', 'POST'])
def panel_register():
    '''
    '''
    panel_name   = ""
    panel_bed    = ""
    panel_path   = ""
    panel_version= "."
    panel_ext1_id= "."
    panel_ext2_id= "."
    capture_kit  = "."
    is_ok = True
    if request.method == "POST":
        if request.form['panel_name']:
            panel_name = request.form['panel_name']
            panel_exists = Panel.query.filter_by(Panel=panel_name).first()
            if panel_exists:
                msg = (" El panell amb el nom {} ja existeix").format(panel_name)
                flash(msg, "warning")

        if request.form['panel_ext1_id']:
            panel_ext1_id = request.form['panel_ext1_id']
        if request.form['panel_ext1_id']:
            panel_ext2_id = request.form['panel_ext2_id']
        if request.form['panel_version']:
            panel_version = request.form['panel_version']
        if request.files:
            panel_bed = request.files["panel_bed"]
            panel_dir = app.config['WORKING_DIRECTORY'] + "/PANEL_FOLDER/" + "/" + panel_name
            if not os.path.isdir(panel_dir):
                os.mkdir(panel_dir)
            if not panel_bed:
                flash("Es requereix un fitxer en format .bed", "warning")
                is_ok = False
            else:
                if panel_bed.filename.endswith(".bed"):
                    panel_bed.save(os.path.join(panel_dir, panel_bed.filename))
                    panel_path = ''.join([panel_dir, "/", panel_bed.filename])

                    # Sort bed by chromosome position
                    panel_path = sort_bed(panel_path)

                    # Merge overlapping regions
                    panel_path = merge_bed(panel_path)
                else:
                    flash("Es requereix un fitxer en format .bed", "warning")
                    is_ok = False
    if is_ok is True:
        panel_summary_dict = summarize_capture_regions(panel_path)
        panel_summary_dict['panel_name']    = panel_name
        panel_summary_dict['panel_version'] = panel_version
        panel_summary_dict['capture_kit']   = capture_kit
        panel_summary_dict['panel_ext1_id'] = panel_ext1_id
        panel_summary_dict['panel_ext2_id'] = panel_ext2_id

        new_panel = Panel(Panel=panel_name, Panel_bed=panel_path,
        Version=panel_version, Size=panel_summary_dict['panel_size'],
        Genome_version='hg19', Total_rois=panel_summary_dict['n_regions'],
        Last_modified=".")
        db.session.add(new_panel)
        db.session.commit()

        return render_template("panel_wizard_step1.html", panel_summary_dict=panel_summary_dict,
            title=panel_summary_dict['panel_name'] + " Pas1")
    else:
        return redirect(url_for('panel_creation_board'))

@app.route('/annotate_capture_regions', methods = ['GET', 'POST'])
def annotate_capture_regions():
    '''
    '''
    panel_summary_dict = {}
    ann_options = {
        'CDS': False,
        'UTR': False,
        'filter_genes': [],
        'close_genes': False,
        'protein_coding' : False,
        'lnc_rna' : False,
        'pseudogenes' : False,
    }
    is_ok = True
    if request.method == "POST":
        if request.form['panel_name']:
            panel_summary_dict['panel_name'] = request.form['panel_name']
        if request.form['panel_ext1_id']:
            panel_summary_dict['panel_ext1_id'] = request.form['panel_ext1_id']
        if request.form['panel_ext2_id']:
            panel_summary_dict['panel_ext2_id'] = request.form['panel_ext2_id']
        if request.form['panel_version']:
            panel_summary_dict['panel_version'] = request.form['panel_version']
        if request.form['n_regions']:
            panel_summary_dict['n_regions'] = request.form['n_regions']
        if request.form['panel_size']:
            panel_summary_dict['panel_size'] = request.form['panel_size']
        if request.form['panel_version']:
            panel_summary_dict['panel_version'] = request.form['panel_version']
        if request.form['mean_target_size']:
            panel_summary_dict['mean_target_size'] = request.form['mean_target_size']
        if request.form['min_target_size']:
            panel_summary_dict['min_target_size'] = request.form['min_target_size']
        if request.form['max_target_size']:
            panel_summary_dict['max_target_size'] = request.form['max_target_size']
        if request.form.getlist('cds'):
            ann_options['CDS'] = True
        if request.form.getlist('utr'):
            ann_options['UTR'] = True
        if request.form.getlist('close_genes'):
            ann_options['close_genes'] = True
        if request.form.getlist('protein_coding'):
            ann_options['protein_coding'] = True
        if request.form.getlist('lnc_rna'):
            ann_options['lnc_rna'] = True
        if request.form.getlist('pseudogenes'):
            ann_options['pseudogenes'] = True
        if request.form['genes_text']:
            genes_text = request.form['genes_text']
            if genes_text:
                genes_text = genes_text.rstrip('\n')
            genes_list = re.split(r"[~\r\n]+", genes_text)
            input_genes_status = validate_genes(genes_list, 'hg19')
            err_genes = []
            for gene in input_genes_status:
                if input_genes_status[gene] is False:
                    err_genes.append(gene)
                else:
                    ann_options['filter_genes'].append(gene)
            if err_genes:
                err_genes_str = ",".join(err_genes)
                msg = "Els gens {} no s'han trobat".format(err_genes_str)
                flash(msg, "warning")
                is_ok = False
        if request.files:
            genes_file = request.files["genes_file"]
            panel_dir  = app.config['WORKING_DIRECTORY'] + "/PANEL_FOLDER/" + panel_summary_dict['panel_name']
            if not os.path.isdir(panel_dir):
                os.mkdir(panel_dir)
            if genes_file:
                if genes_file.filename.endswith(".txt"):
                    genes_file.save(os.path.join(panel_dir, genes_file.filename))
                    genes_path = ''.join([panel_dir, "/", genes_file.filename])
                else:
                    msg = "Es requereix un fitxer de text (.txt)"
                    flash(msg, "warning")
        if is_ok == True:
            # Test fixed
            panel_name = panel_summary_dict['panel_name']
            pobj= db.session.query(Panel).filter_by(Panel=panel_name).first()
            panel_path = pobj.Panel_bed

            annotation_report, gene_structure = annotate_accessible_genes(input_bed=panel_path,
                gencode_genes= app.config['GENCODE_ONLY_GENES_HG19'],
                gencode_all_features=app.config['GENCODE_ALL_HG19'],
                ann_options=ann_options)

            gene_struct_json = panel_path.replace(".bed", ".genes.transcripts.json")
            pobj.Features_json = gene_struct_json
            db.session.commit()

            all_panel_features_json = panel_path.replace(".bed", ".all.panel.features.json")
            pobj.Roi_json = all_panel_features_json
            db.session.commit()

            return render_template("panel_wizard_step2.html",
                panel_name=panel_summary_dict['panel_name'],
                annotation_report=annotation_report,
                gene_structure=gene_structure,
                title="Definició regions de capt.")
        else:
            return render_template("panel_wizard_step1.html",
                panel_summary_dict=panel_summary_dict,
                title=panel_summary_dict['panel_name'] + " Pas1")
    else:
        return redirect(url_for('panel_creation_board'))

def summarize_capture_regions(bed_file):
    '''
    '''
    bases      = 0
    total_rois = 0
    min_size   = 1000000
    max_size   = 0
    size_list  = []
    with open(bed_file) as f:
        for line in f:
            line = line.rstrip('\n')
            total_rois+=1
            tmp = line.split('\t')
            size = int(tmp[2]) - int(tmp[1])
            if size > max_size:
                max_size = size
            if size < min_size:
                min_size = size
            size_list.append(size)
            bases+=size
    f.close()
    kbases = round(bases/1000,2)
    mean_size = round(np.mean(size_list), 2)
    panel_dict = {
        'panel_size' : kbases,
        'mean_target_size': mean_size,
        'min_target_size' : min_size,
        'max_target_size' : max_size,
        'n_regions': total_rois
    }
    return panel_dict

def parse_info(sep, element):
    '''
    '''
    info = element.split(";")
    info_dict = dict()
    for field in info:
        tmp_field = field.split("=")
        if len(tmp_field) > 1:
            name  = tmp_field[0]
            value = tmp_field[1]
            info_dict[name] = value
    return info_dict

def get_exon_overlap(exon_start, exon_end, region_start, region_end):
    '''
        Calculate the overlap (in %) between a target region and an exon
    '''
    overlap = ""
    if region_start == "-1" or region_end == "-1":
        overlap = 0
        return overlap
    exon_size  = exon_end-exon_start
    region_size= region_end-region_start

    # Case 1. Whole exon inside targeted region
    if region_start <= exon_start and region_end >= exon_end:
        overlap = 100
    # Cases 2. Partial overlaps
    else:
        # Inner overlap
        if region_start > exon_start and region_end < exon_end:
            overlap = round(100*(region_size/exon_size),2)
        if region_start > exon_start and region_end >=exon_end:
            overlap = round(100*((exon_end-region_start)/exon_size),2)
        if region_start < exon_start and region_end < exon_end:
            overlap =  round(100*((region_end-exon_start)/exon_size), 2)
    return overlap

def bed_to_dict(bed):
    '''
    '''
    bed_dict  = defaultdict(dict)
    with open(bed) as f:
        for line in f:
            line = line.rstrip("\n")
            tmp = line.split("\t")
            bed_dict[line] = list()
            # bed_dict[line]['chr']  = tmp[0]
            # bed_dict[line]['start']= tmp[1]
            # bed_dict[line]['end']  = tmp[2]
            # bed_dict[line]['features'] = set()
            # bed_dict[line]['exon_id'] = set()
            # bed_dict[line]['transcript_id'] = set()
            # bed_dict[line]['exon_number'] = set()
            # # bed_dict[line]['gene_name'] = set()
            # if len(tmp) > 3:
            #     bed_dict[line]['info'] = tmp[3]
    f.close()
    return bed_dict

def sort_bed(bed):
    '''
    '''
    sorted_bed = bed.replace(".bed", ".sorted.bed")
    cmd = 'sort -V {} | uniq | cut -f 1,2,3,4 > {}'.format(bed, sorted_bed)

    p1 = subprocess.run(cmd, shell=True, stdout=subprocess.PIPE,
    stderr=subprocess.PIPE)
    output = p1.stdout.decode('UTF-8')
    error  = p1.stderr.decode('UTF-8')
    return sorted_bed

def merge_bed(bed):
    '''
    '''
    merged_bed = bed.replace(".bed", ".merged.bed")
    a = pybedtools.BedTool(bed)
    c = a.merge(c=4, o="distinct").saveas(merged_bed)

    return merged_bed

def get_overlapping_genes(capture_bed, gencode_genes_gff, ann_options):
    '''
    '''

    a = pybedtools.BedTool(capture_bed)
    b = pybedtools.BedTool(gencode_genes_gff)
    c = a.intersect(b, wao=True)

    genes_report = {
        'total_genes' : 0,
        'protein_coding' : 0,
        'coordinates' : set()
    }
    genes = set()
    for result in c:
        gene_chr   = result[4]
        gene_start = result[7]
        gene_end   = result[8]
        if gene_chr is not ".":
            info_dict = parse_info(sep=";", element=result[12])

            gene_type = info_dict['gene_type']

            if gene_type == 'protein_coding':
                if ann_options['protein_coding'] == False:
                    continue
            elif 'RNA' in gene_type:
                if ann_options['lnc_rna'] == False:
                    continue
            elif 'pseudogene' in gene_type:
                if ann_options['pseudogenes'] == False:
                    continue
            else:
                continue

            gene_name = info_dict['gene_name']
            if ann_options['filter_genes']:
                if not gene_name in ann_options['filter_genes']:
                    continue
            gene_key  = '\t'.join([gene_chr, gene_start, gene_end, gene_name])
            if not gene_name in genes:
                genes_report['total_genes'] += 1
                if info_dict['gene_type'] == 'protein_coding':
                    genes_report['protein_coding'] += 1
            genes.add(gene_name)
            genes_report['coordinates'].add(gene_key)
    return genes_report

def get_gene_features(target_genes_bed, gencode_features_gff, ann_options):
    '''
    '''
    exons    = set()
    isoforms = set()
    features_report = {
        'total_isoforms' : 0,
        'features' : set(),
        'isoforms' : set(),
    }

    a = pybedtools.BedTool(target_genes_bed)
    b = pybedtools.BedTool(gencode_features_gff)
    c = a.intersect(b, wao=True)

    for result in c:
        gene    = result[3]
        feature = result[6]
        if feature == 'gene' or feature == 'transcript':
            continue
        info_dict = parse_info(";", result[12])
        gene_name = info_dict['gene_name']
        gene_type = info_dict['gene_type']
        if gene_type == 'protein_coding':
            if ann_options['protein_coding'] == False:
                continue
        elif 'RNA' in gene_type:
            if ann_options['lnc_rna'] == False:
                continue
        elif 'pseudogene' in gene_type:
            if ann_options['pseudogenes'] == False:
                continue
        else:
            continue

        if gene == gene_name:
            new_line = '\t'.join(result[4:])
            if 'transcript_id' in info_dict:
                transcript_id = info_dict['transcript_id']
                if not transcript_id in isoforms:
                    features_report['total_isoforms'] += 1
                features_report['isoforms'].add(transcript_id)
            features_report['features'].add(new_line)
    return features_report

def annotate_accessible_genes(input_bed, gencode_genes, gencode_all_features, ann_options):
    '''
        BED is 0-based (chr 0 100)
        GFF3 is 1-based (chr 1 100)
    '''

    annotation_report_dict = {
        'total_genes'        : 0,
        'protein_coding'     : 0,
        'pct_protein_coding' : 0,
        'other_genes'        : 0,
        'total_isoforms'     : 0,
        'covered_isoforms'   : 0,
        'covered_exons'      : 0,
        'annotated_regions'  : 0,
        'unannotated_regions': 0
    }

    # Genes overlapping the panel design
    genes_report = get_overlapping_genes(input_bed, gencode_genes, ann_options)
    annotation_report_dict['protein_coding'] = genes_report['protein_coding']
    annotation_report_dict['pct_protein_coding'] \
        = round(100*(genes_report['protein_coding']/genes_report['total_genes']),2)
    annotation_report_dict['other_genes'] \
        = genes_report['total_genes']-genes_report['protein_coding']

    target_genes = input_bed.replace(".bed", ".only.genes.bed")
    o = open(target_genes, "w")
    for coordinate in genes_report['coordinates']:
        o.write(coordinate+"\n")
    o.close()

    # All individual genes features such as CDS, UTR, etc.
    features_report = get_gene_features(target_genes, gencode_all_features, ann_options)
    annotation_report_dict['total_isoforms'] = features_report['total_isoforms']
    all_features_bed = input_bed.replace(".bed", ".all.gene.features.bed")
    o = open(all_features_bed, "w")
    for exon in features_report['features']:
        o.write(exon+"\n")
    o.close()

    # Closest gene to each targeted region
    if ann_options['close_genes'] == True:
        closest_genes_bed, closest_genes_dict = annotate_close_genes(input_bed,
            gencode_genes, app.config['HG19_CHROMOSOMES'], ann_options)

    gene_structure = defaultdict(dict)
    roi_summary    = bed_to_dict(input_bed)

    a = pybedtools.BedTool(all_features_bed)
    b = pybedtools.BedTool(input_bed)
    c = a.intersect(b, wao=True)
    covered_exons = set()
    for result in c:
        feature = result[2]
        # print(feature + " " + result[8])
        if ann_options['UTR'] == False:
            if feature == 'exon':
                continue
        info_dict = parse_info(";", result[8])
        if not 'gene_name' in info_dict:
            continue
        info_dict['feature'] = feature
        gene_name = info_dict['gene_name']
        gene_id   = ""

        if 'gene_id' in info_dict:
            m = re.match(r"^(.*?)\_", info_dict['gene_id'])
            gene_id = info_dict['gene_id']
            if m:
                gene_id = m.group(1)
        transcript_id  = ""
        if 'transcript_id' in info_dict:
            m = re.match(r"^(.*?)\_", info_dict['transcript_id'])
            transcript_id = info_dict['transcript_id']
            if m:
                transcript_id = m.group(1)

        gene_type = info_dict['gene_type']
        transcript_name= info_dict['transcript_name']
        protein_id = ""
        exon_number= ""
        exon_id    = ""
        raw_exon_id = info_dict['exon_id']
        tag = ""
        if 'exon_id' in info_dict:
            m = re.match(r"^(.*?)\_", info_dict['exon_id'])
            exon_id = info_dict['exon_id']
            if m:
                exon_id = m.group(1)
        if 'exon_number' in info_dict:
            exon_number = info_dict['exon_number']
        if 'protein_id' in info_dict:
            protein_id = info_dict['protein_id']
        if 'tag' in info_dict:
            tag = info_dict['tag']
        is_appris = 0
        if 'appris_principal_1' in tag:
            is_appris = 1
        is_mane = 0
        if 'MANE_Select' in tag:
            is_mane = 1

        # From GENCODE feature coordinates
        exon_chr   = result[0]
        exon_start = result[3]
        exon_end   = result[4]

        # From panel regions coordinates
        region_chr   = result[9]
        region_start = result[10]
        region_end   = result[11]
        region_info  = result[12]
        region_coord = "\t".join(result[9:13])

        if not gene_name in gene_structure:
            gene_structure[gene_name] = defaultdict(dict)
            gene_structure[gene_name]['gene_name']  = gene_name
            gene_structure[gene_name]['gene_id']    = gene_id
            gene_structure[gene_name]['gene_type']  = gene_type
            gene_structure[gene_name]['protein_id'] = protein_id
            gene_structure[gene_name]['transcripts']= defaultdict(dict)

        if not transcript_id in gene_structure[gene_name]['transcripts']:
            gene_structure[gene_name]['transcripts'][transcript_id] = defaultdict(dict)
            gene_structure[gene_name]['transcripts'][transcript_id]['exons'] = defaultdict(dict)
            gene_structure[gene_name]['transcripts'][transcript_id]['total_exons'] = 0
            gene_structure[gene_name]['transcripts'][transcript_id]['full_covered_exons'] = 0
            gene_structure[gene_name]['transcripts'][transcript_id]['name'] = transcript_name
            gene_structure[gene_name]['transcripts'][transcript_id]['is_appris'] = is_appris
            gene_structure[gene_name]['transcripts'][transcript_id]['is_mane']   = is_mane
            gene_structure[gene_name]['transcripts'][transcript_id]['gene_name'] = gene_name
            gene_structure[gene_name]['transcripts'][transcript_id]['gene_id'] = gene_id
            gene_structure[gene_name]['transcripts'][transcript_id]['transcript_id'] = transcript_id

        exon_coordinates = ("{}:{}-{}").format(result[0], result[3], result[4])
        if region_start == "-1" or region_end == "-1":
            pct_covered = 0
        else:
            pct_covered = get_exon_overlap(int(exon_start), int(exon_end),
                int(region_start), int(region_end))

        if not exon_id in gene_structure[gene_name]['transcripts'][transcript_id]['exons']:
            if ann_options['UTR'] == True:
                if feature == "exon":
                    if pct_covered == 100:
                        gene_structure[gene_name]['transcripts'][transcript_id]['full_covered_exons'] += 1
            else:
                if feature == "CDS":
                    if pct_covered == 100:
                        gene_structure[gene_name]['transcripts'][transcript_id]['full_covered_exons'] += 1
            gene_structure[gene_name]['transcripts'][transcript_id]['total_exons'] += 1
            gene_structure[gene_name]['transcripts'][transcript_id]['exons'][exon_id] = defaultdict(dict)
            gene_structure[gene_name]['transcripts'][transcript_id]['exons'][exon_id][feature] = defaultdict(dict)
            gene_structure[gene_name]['transcripts'][transcript_id]['exons'][exon_id][feature]['exon_id'] = exon_id
            gene_structure[gene_name]['transcripts'][transcript_id]['exons'][exon_id][feature]['coordinates'] = exon_coordinates
            gene_structure[gene_name]['transcripts'][transcript_id]['exons'][exon_id][feature]['pct_covered'] = pct_covered
            gene_structure[gene_name]['transcripts'][transcript_id]['exons'][exon_id][feature]['exon_number'] = exon_number
            gene_structure[gene_name]['transcripts'][transcript_id]['exons'][exon_id][feature]['tag'] = tag

        else:
            if ann_options['UTR'] == True:
                if feature == "exon":
                    if pct_covered == 100:
                        gene_structure[gene_name]['transcripts'][transcript_id]['full_covered_exons'] += 1
            else:
                # if feature == "CDS":
                if feature == 'CDS':
                    if pct_covered == 100:
                        gene_structure[gene_name]['transcripts'][transcript_id]['full_covered_exons'] += 1
            if not feature in gene_structure[gene_name]['transcripts'][transcript_id]['exons'][exon_id]:
                gene_structure[gene_name]['transcripts'][transcript_id]['exons'][exon_id][feature] = defaultdict(dict)

            gene_structure[gene_name]['transcripts'][transcript_id]['exons'][exon_id][feature]['exon_id'] = exon_id
            gene_structure[gene_name]['transcripts'][transcript_id]['exons'][exon_id][feature]['coordinates'] = exon_coordinates
            gene_structure[gene_name]['transcripts'][transcript_id]['exons'][exon_id][feature]['pct_covered'] = pct_covered
            gene_structure[gene_name]['transcripts'][transcript_id]['exons'][exon_id][feature]['exon_number'] = exon_number
            gene_structure[gene_name]['transcripts'][transcript_id]['exons'][exon_id][feature]['tag'] = tag

        if region_coord in roi_summary and pct_covered == 100:
            if feature == "exon":
                annotation_report_dict['covered_exons'] +=1
                roi_summary[region_coord].append(json.dumps(info_dict))
            if feature == "CDS":
                roi_summary[region_coord].append(json.dumps(info_dict))
            if 'UTR' in feature:
                roi_summary[region_coord].append(json.dumps(info_dict))

    roi_summary_extended = defaultdict(dict)
    roi_summary_extended['annotated']     = list()
    roi_summary_extended['non_annotated'] = list()

    all_panel_features_bed = input_bed.replace(".bed", ".all.panel.features.bed")
    o_bed = open(all_panel_features_bed, "w")
    for region in  roi_summary:
        if not roi_summary[region]:
            annotation_report_dict['unannotated_regions']+=1
        else:
            annotation_report_dict['annotated_regions']+=1
        o_bed.write(region+"\t"+str(roi_summary[region]) + "\n")

        tmp = region.split("\t")
        coordinate_str = ("{}:{}-{}").format(tmp[0], tmp[1], tmp[2])

        for item_str in roi_summary[region]:
            item_dict = json.loads(item_str)
            if item_dict:
                item_dict['is_annotated'] = "true"
                item_dict['region_id'] = coordinate_str
                item_dict['closest_genes'] = closest_genes_dict[coordinate_str]
                roi_summary_extended['annotated'].append(item_dict)
        if not roi_summary[region]:
            unnanon_dict =  {
                'region_id' : coordinate_str,
                'is_annotated': "false",
                'closest_genes': closest_genes_dict[coordinate_str]
            }
            roi_summary_extended['non_annotated'].append(unnanon_dict)
    o_bed.close()

    all_panel_features_json= all_panel_features_bed.replace(".bed", ".json")
    with open(all_panel_features_json, "w") as jf:
        json.dump(roi_summary_extended, jf)

    gene_structure, covered_isoforms = remove_non_captured_genes(gene_structure)

    # Rewrite gene_structure as a list of dicts
    new_gene_structure = {
        'genes': []
    }
    for gene in gene_structure:
        new_gene_structure['genes'].append(gene_structure[gene])

    gene_struct_json = input_bed.replace(".bed", ".genes.transcripts.json")
    with open(gene_struct_json, "w") as outf:
        json.dump(new_gene_structure, outf)

    annotation_report_dict['covered_isoforms'] = covered_isoforms

    return annotation_report_dict, new_gene_structure

def remove_non_captured_genes(gene_dict):
    '''
    '''
    total_transcripts_covered = 0
    genes_to_remove = []
    for gene in gene_dict:
        num_transcripts_covered = 0
        for transcript_id in gene_dict[gene]['transcripts']:
            full_covered_exons = int(gene_dict[gene]['transcripts'][transcript_id]['full_covered_exons'])
            if full_covered_exons > 0:
                num_transcripts_covered+=1
                total_transcripts_covered+=1
        if num_transcripts_covered == 0:
            genes_to_remove.append(gene)
    for gene in genes_to_remove:
        del gene_dict[gene]
    return gene_dict, total_transcripts_covered

def validate_genes(gene_list, genome_version):
    '''
        Validate gene names
    '''

    gene_status = {}
    # Set server
    if genome_version == 'hg19':
        server = "https://grch37.rest.ensembl.org"
    else:
        server = "https://rest.ensembl.org"
    for gene in gene_list:
        if gene is "":
            continue
        ext = ("/lookup/symbol/homo_sapiens/{}?expand=1").format(gene)
        r = requests.get(server+ext, headers={ "Content-Type" : "application/json"})
        decoded = r.json()
        if 'error' in decoded:
            gene_status[gene] = False
        else:
            gene_status[gene] = True
    return gene_status

@app.route('/api/panel_sel/<panel_name>', methods = ['GET'])
def panel_sel(panel_name):
    '''
    '''
    pobj = Panel.query.filter_by(Panel=panel_name).first()
    sel_json = pobj.Sel_json
    with open(sel_json) as jf:
        data = json.load(jf)
    return jsonify(data)

@app.route('/api/panel_all_gene_structure/<panel_name>', methods = ['GET'])
def panel_all_gene_structure(panel_name):
    pobj = Panel.query.filter_by(Panel=panel_name).first()
    features_json = pobj.Features_json
    with open(features_json) as jf:
        data = json.load(jf)
    return jsonify(data)

@app.route('/api/gtex/expression/<gene_name>/<transcript_id>', methods = ['GET'])
def gtex_transcript_expression(gene_name, transcript_id):
    '''
      GTEX v7 transcript expression endpoint
    '''

    base_transcript_id = ""
    m = re.match(r"^(.*?)\.", transcript_id)
    if m:
        base_transcript_id = m.group(1)

    # Step1. Extract gene identifiers available from gtex
    server = "https://gtexportal.org"
    ext = ("/rest/v1/reference/gene?geneId={}&gencodeVersion=v19&genomeBuild=GRCh37%2Fhg19&pageSize=250&format=json").format(gene_name)
    r = requests.get(server+ext, headers={ "Content-Type" : "application/json"})
    r.raise_for_status()
    decoded = r.json()
    gene_id = decoded['gene'][0]['gencodeId']

    # Step2. transcript expression
    ext = ("/rest/v1/expression/medianTranscriptExpression?datasetId=gtex_v7&gencodeId={}&format=json").format(gene_id)
    r = requests.get(server+ext, headers={ "Content-Type" : "application/json"})
    r.raise_for_status()
    decoded = r.json()
    transcript_expression = []

    for item in decoded['medianTranscriptExpression']:
        if base_transcript_id in item['transcriptId']:
            transcript_expression.append(item)

    transcript_expression_sorted = sorted(transcript_expression, key=lambda d: d['tissueSiteDetailId'])
    return jsonify(transcript_expression_sorted)

@app.route('/constitute_analysis_content', methods = ['GET', 'POST'])
def constitute_analysis_content():
    '''
    '''
    if request.method == "POST":
        sel_json = ""
        if request.form['panel_name']:
            panel_name   = request.form['panel_name']
            panel_object = db.session.query(Panel).filter_by(Panel=panel_name).first()
            sel_json    = panel_object.Sel_json

        custom_tags = request.form.getlist('region_identifier')
        custom_tag_dict = dict()
        for tag in custom_tags:
            tmp_tag = tag.split("_")
            region  = tmp_tag[0]
            tag     = tmp_tag[1]
            custom_tag_dict[region] = tag

        with open(sel_json) as jf:
            sel_data = json.load(jf)

        for item in sel_data['non_annotated']:
            region_id = item['region_id']
            item['analysis_tag'] = custom_tag_dict[region_id]

        with open(sel_json, "w") as jf:
            json.dump(sel_data, jf)
            jf.close()
    return redirect(url_for('panel_configuration', panel=panel_name))

@app.route('/process_selected_isoforms', methods = ['GET', 'POST'])
def process_selected_isoforms():
    '''
    '''
    if request.method == "POST":
        panel_bed = ""
        panel_object = ""

        if request.form['panel_name']:
            panel_name   = request.form['panel_name']
            panel_object = db.session.query(Panel).filter_by(Panel=panel_name).first()
            panel_bed    = panel_object.Panel_bed

        all_panel_features_bed  = panel_bed.replace(".bed", ".all.panel.features.bed")
        all_panel_features_json = panel_bed.replace(".bed", ".all.panel.features.json")
        region_features_dict = defaultdict(list)

        annotated_regions    = defaultdict(dict)
        unannotated_regions  = defaultdict(dict)
        summary_annotations  = defaultdict(dict)

        if request.form.getlist('selected_isoforms'):
            selected_isoforms = request.form.getlist('selected_isoforms')
            selected_isoforms = set(selected_isoforms)

            with open(all_panel_features_json) as jf:
                all_panel_features_dict = json.load(jf)
                jf.close()

            selected_panel_features_dict = defaultdict(dict)
            selected_panel_features_dict['annotated'] = list()
            selected_panel_features_dict['non_annotated'] = list()

            annotated = set()
            for feature in all_panel_features_dict['annotated']:
                annotated.add(feature['region_id'])
                transcript_id = feature['transcript_id']
                m = re.match(r"^(.*?)\_", feature['transcript_id'])
                transcript_id = feature['transcript_id']
                if m:
                    transcript_id = m.group(1)

                if transcript_id in selected_isoforms:
                    selected_panel_features_dict['annotated'].append(feature)

            non_annotated = 0
            for feature in all_panel_features_dict['non_annotated']:
                non_annotated+=1
                selected_panel_features_dict['non_annotated'].append(feature)
            summary_annotations['annotated']    = len(annotated)
            summary_annotations['non_annotated'] = non_annotated

            sel_features_json = panel_bed.replace(".bed", ".sel.features.json")
            with open(sel_features_json, "w") as jf:
                json.dump(selected_panel_features_dict, jf)
                jf.close()
            panel_object.Sel_json = sel_features_json
            db.session.commit()

    return render_template("panel_wizard_step3.html", summary_annotations=summary_annotations,
    title="test", panel_name = panel_name)

def annotate_close_genes(input_bed, gencode_genes, genome_chromosomes, ann_options):
    '''
    '''
    closest_bed = input_bed.replace(".bed", ".closest.genes.bed")

    a = pybedtools.BedTool(input_bed)
    b = pybedtools.BedTool(gencode_genes)
    c = a.closest(b, g=genome_chromosomes, d=True, k=4).saveas(closest_bed)
    closest_genes_dict = defaultdict(dict)
    for result in c:
        region_chr   = result[0]
        region_start = result[1]
        region_end   = result[2]
        region_info  = result[3]
        region_coord = "\t".join(result[0:3])
        region_coord = ("{}:{}-{}").format(result[0], result[1], result[2])

        if not region_coord in closest_genes_dict:
            closest_genes_dict[region_coord] = []

        info_dict = parse_info(sep=";", element=result[12])
        gene_name = info_dict['gene_name']
        gene_type = info_dict['gene_type']

        if gene_type == 'protein_coding':
            if ann_options['protein_coding'] == False:
                continue
        elif 'RNA' in gene_type:
            if ann_options['lnc_rna'] == False:
                continue
        elif 'pseudogene' in gene_type:
            if ann_options['pseudogenes'] == False:
                continue
        else:
            continue

        distance  = result[-1]
        entry_dict = {
            'gene_name': gene_name,
            'distance': distance
        }
        closest_genes_dict[region_coord].append(entry_dict)

    return closest_bed, closest_genes_dict
