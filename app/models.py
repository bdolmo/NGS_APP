from app import db

class VersionControl(db.Model):
    __tablename__ = 'VERSION_CONTROL'
    Id         = db.Column(db.Integer, primary_key=True, autoincrement=True)
    User_id    = db.Column(db.String(20))
    Action_id  = db.Column(db.String(20))
    Action_json= db.Column(db.String(200))
    Action_name= db.Column(db.String(200))
    Modified_on= db.Column(db.String(20))

    def __init__(self, User_id, Action_id, Action_json, Action_name,Modified_on):
        self.User_id    = User_id
        self.Action_id  = Action_id
        self.Action_json= Action_json
        self.Action_name= Action_name
        self.Modified_on= Modified_on

class Job(db.Model):
    __tablename__ = 'JOBS'
    Id       = db.Column(db.Integer, primary_key=True, autoincrement=True)
    User_id  = db.Column(db.String(20))
    Job_id   = db.Column(db.String(20))
    Queue_id = db.Column(db.String(20))
    Date     = db.Column(db.String(20))
    Analysis = db.Column(db.String(20))
    Panel    = db.Column(db.String(20))
    Samples  = db.Column(db.String(20))
    Status   = db.Column(db.String(20))

    def __init__(self, User_id, Job_id, Queue_id, Date, Analysis, Panel, Samples, Status):
        self.User_id = User_id
        self.Job_id  = Job_id
        self.Queue_id= Queue_id
        self.Date    = Date
        self.Analysis= Analysis
        self.Panel   = Panel
        self.Samples = Samples
        self.Status  = Status

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

class Panel(db.Model):
    __tablename__  = 'PANELS'
    Id             = db.Column(db.Integer, primary_key=True, autoincrement=True)
    Panel          = db.Column(db.String(20))
    Panel_bed      = db.Column(db.String(20))
    Version        = db.Column(db.String(20))
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

class Roi(db.Model):
  __tablename__ = 'ROI_TABLE'
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

class Variants(db.Model):
    __tablename__ = 'VARIANTS'
    id = db.Column(db.Integer, primary_key=True)
    chromosome = db.Column(db.String(20))
    pos = db.Column(db.String(20))
    ref = db.Column(db.String(20))
    alt = db.Column(db.String(20))
    var_type = db.Column(db.String(20))
    genome_version = db.Column(db.String(20))
    gene = db.Column(db.String(20))
    isoform = db.Column(db.String(20))
    hgvsg = db.Column(db.String(20))
    hgvsp = db.Column(db.String(20))
    hgvsc = db.Column(db.String(20))
    count = db.Column(db.Integer)
    blacklist = db.Column(db.String(20))

class SampleVariants(db.Model):
    __tablename__ = 'SAMPLE_VARIANTS'
    id = db.Column(db.Integer, primary_key=True)
    sample_id = db.Column(db.Integer)
    var_id = db.Column(db.Integer)
    ann_id = db.Column(db.Integer)
    lab_confirmation = db.Column(db.String(20))
    confirmation_technique = db.Column(db.String(20))
    classification = db.Column(db.String(20))
    ann_key = db.Column(db.String(200))
    ann_json = db.Column(db.String(20000))

class VarAnnotation(db.Model):
    __tablename__= 'VAR_ANNOTATION'
    id = db.Column(db.Integer, primary_key=True)
    var_id   = db.Column(db.Integer)
    ann_key  = db.Column(db.String(20))
    ann_json = db.Column(db.String(20))

class SampleTable(db.Model):
    __tablename__ = 'SAMPLES'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20))
    lab_id  = db.Column(db.String(120))
    ext1_id = db.Column(db.String(80))
    ext2_id = db.Column(db.String(80))
    run_id  = db.Column(db.String(80))
    petition_id  = db.Column(db.String(80))
    extraction_date =  db.Column(db.String(80))
    analysis_date   =  db.Column(db.String(80))
    tumour_purity   =  db.Column(db.String(80))
    sex  = db.Column(db.String(80))
    diagnosis = db.Column(db.String(80))
    physician_name  = db.Column(db.String(80))
    medical_center  = db.Column(db.String(80))
    medical_address = db.Column(db.String(80))
    sample_type  = db.Column(db.String(80))
    panel    = db.Column(db.String(80))
    subpanel = db.Column(db.String(80))
    roi_bed  = db.Column(db.String(80))
    software = db.Column(db.String(80))
    software_version = db.Column(db.String(80))
    bam = db.Column(db.String(80))
    merged_vcf = db.Column(db.String(80))
    report_pdf = db.Column(db.String(80))
    report_db  = db.Column(db.String(120))
    sample_db_dir = db.Column(db.String(120))
    cnv_json   = db.Column(db.String(100000))
    def __repr__(self):
        return '<Sample %r>' % self.lab_id

class TherapeuticTable(db.Model):
    __tablename__ = 'THERAPEUTIC_VARIANTS'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20))
    lab_id  = db.Column(db.String(120))
    ext1_id = db.Column(db.String(80))
    ext2_id = db.Column(db.String(80))
    run_id  = db.Column(db.String(80))
    petition_id  = db.Column(db.String(80))
    gene  = db.Column(db.String(120))
    enst_id  = db.Column(db.String(120))
    hgvsp = db.Column(db.String(120))
    hgvsg =  db.Column(db.String(120))
    hgvsc =  db.Column(db.String(120))
    exon  = db.Column(db.String(120))
    variant_type = db.Column(db.String(120))
    consequence =  db.Column(db.String(120))
    depth = db.Column(db.String(120))
    allele_frequency = db.Column(db.String(120))
    read_support = db.Column(db.String(120))
    max_af = db.Column(db.String(120))
    max_af_pop = db.Column(db.String(120))
    therapies = db.Column(db.String(240))
    clinical_trials = db.Column(db.String(240))
    tumor_type = db.Column(db.String(240))
    var_json   = db.Column(db.String(5000))
    classification = db.Column(db.String(120))
    validated_assessor = db.Column(db.String(120))
    validated_bioinfo  = db.Column(db.String(120))
    db_detected_number = db.Column(db.Integer())
    db_sample_count    = db.Column(db.Integer())
    db_detected_freq = db.Column(db.Float())
    blacklist = db.Column(db.String(20))

    def __repr__(self):
        return '<TherapeuticVariants %r>' % self.gene

class OtherVariantsTable(db.Model):
    __tablename__ = 'OTHER_VARIANTS'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20))
    lab_id  = db.Column(db.String(120))
    ext1_id = db.Column(db.String(80))
    ext2_id = db.Column(db.String(80))
    run_id  = db.Column(db.String(80))
    petition_id  = db.Column(db.String(80))
    gene  = db.Column(db.String(120))
    enst_id  = db.Column(db.String(120))
    hgvsp = db.Column(db.String(120))
    hgvsg =  db.Column(db.String(120))
    hgvsc =  db.Column(db.String(120))
    exon  = db.Column(db.String(120))
    variant_type = db.Column(db.String(120))
    consequence =  db.Column(db.String(120))
    depth = db.Column(db.String(120))
    allele_frequency = db.Column(db.String(120))
    read_support = db.Column(db.String(120))
    max_af = db.Column(db.String(120))
    max_af_pop = db.Column(db.String(120))
    therapies = db.Column(db.String(240))
    clinical_trials = db.Column(db.String(240))
    tumor_type = db.Column(db.String(240))
    var_json   = db.Column(db.String(5000))
    classification = db.Column(db.String(120))
    validated_assessor = db.Column(db.String(120))
    validated_bioinfo  = db.Column(db.String(120))
    db_detected_number = db.Column(db.Integer())
    db_sample_count    = db.Column(db.Integer())
    db_detected_freq   = db.Column(db.Float())
    blacklist = db.Column(db.String(20))

class RareVariantsTable(db.Model):
    __tablename__ = 'RARE_VARIANTS'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20))
    lab_id  = db.Column(db.String(120))
    ext1_id = db.Column(db.String(80))
    ext2_id = db.Column(db.String(80))
    run_id  = db.Column(db.String(80))
    petition_id  = db.Column(db.String(80))
    gene     = db.Column(db.String(120))
    enst_id  = db.Column(db.String(120))
    hgvsp = db.Column(db.String(120))
    hgvsg = db.Column(db.String(120))
    hgvsc = db.Column(db.String(120))
    exon  = db.Column(db.String(120))
    variant_type     = db.Column(db.String(120))
    consequence      =  db.Column(db.String(120))
    depth            = db.Column(db.String(120))
    allele_frequency = db.Column(db.String(120))
    read_support = db.Column(db.String(120))
    max_af       = db.Column(db.String(120))
    max_af_pop = db.Column(db.String(120))
    therapies  = db.Column(db.String(240))
    clinical_trials= db.Column(db.String(240))
    tumor_type     = db.Column(db.String(240))
    var_json       = db.Column(db.String(5000))
    classification = db.Column(db.String(120))
    validated_assessor = db.Column(db.String(120))
    validated_bioinfo  = db.Column(db.String(120))
    db_detected_number = db.Column(db.Integer())
    db_sample_count    = db.Column(db.Integer())
    db_detected_freq   = db.Column(db.Float())
    blacklist          = db.Column(db.String(20))

class BiomakerTable(db.Model):
    __tablename__ = 'BIOMARKER_METRICS'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20))
    lab_id  = db.Column(db.String(120))
    ext1_id = db.Column(db.String(80))
    ext2_id = db.Column(db.String(80))
    run_id  = db.Column(db.String(80))
    gene = db.Column(db.String(80))
    variant = db.Column(db.String(80))
    exon = db.Column(db.String(80))
    chr = db.Column(db.String(80))
    pos = db.Column(db.String(80))
    end = db.Column(db.String(80))
    panel = db.Column(db.String(120))
    vaf = db.Column(db.String(80))
    depth = db.Column(db.String(80))

class SummaryQcTable(db.Model):
    __tablename__ = 'SUMMARY_QC'
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.String(20))
    lab_id  = db.Column(db.String(120))
    ext1_id = db.Column(db.String(80))
    ext2_id = db.Column(db.String(80))
    run_id  = db.Column(db.String(80))
    petition_id = db.Column(db.String(120))
    summary_json = db.Column(db.String(12000))
    fastp_json   = db.Column(db.String(10000))

class DisclaimersTable(db.Model):
    __tablename__ = 'DISCLAIMERS'
    id = db.Column(db.Integer, primary_key=True)
    genes = db.Column(db.String(3000))
    methodology = db.Column(db.String(3000))
    analysis =  db.Column(db.String(3000))
    lab_confirmation = db.Column(db.String(3000))
    technical_limitations =  db.Column(db.String(3000))
    legal_provisions = db.Column(db.String(3000))
    panel = db.Column(db.String(120))
    language = db.Column(db.String(120))
