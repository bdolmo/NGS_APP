import os
from pathlib import Path

main_dir = os.path.dirname(os.path.abspath(__file__))
ngs_results_dir = "/ngs-results/"
pipeline_main = "/home/udmmp/GC_NGS_PIPELINE"
ann_dir = "/ngs-annotations/ANN_DIR/"
ref_dir = "/ngs-annotations/REF_DIR/"
# db_dir = "/home/bdelolmo/Desktop/"
# db = "/home/bdelolmo/Desktop/NGS.db"
db_dir = "/ngs-db/NGS_DB/"
db = "/ngs-db/NGS_DB/NGS.db"
data_dir = "/ngs-results/"
ngs_app_url = "http://172.16.83.24:5000"
gene_panels_api_url = "http://172.16.83.24:8000/api/gene_panels"
api_gene_panels = "http://172.16.83.24:8000"
compendium_url = "http://172.16.83.24:8001"


class Config(object):
    DEBUG = False
    TESTING = False
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "84u391jc834jcd8jcd"
    DB_NAME = "NGS"
    UPLOADS = ngs_results_dir
    PETITIONS_DIR = ngs_results_dir
    WORKING_DIRECTORY = os.path.join(main_dir, "data")
    ALLOWED_FASTQ_EXTENSIONS = ["fastq.gz", "fq.gz"]
    MAX_INPUT_FILESIZE = 50 * 1024 * 1024
    SQLALCHEMY_DATABASE_URI = "sqlite:////ngs-db/NGS_DB/NGS.db"
    # SQLALCHEMY_DATABASE_URI = "sqlite:////home/bdelolmo/Desktop/NGS.db"

    WTF_CSRF_SECRET_KEY = "a csrf secret key"
    RECAPTCHA_PUBLIC_KEY = "6Lcl-vsZAAAAAl1wU3t4-5jrYxwYrevk-6qN4mSi"
    RECAPTCHA_PRIVATE_KEY = "6Lcl-vsZAAAAACPMXWnGFFy5eRaseJGOKwKoMr_p"
    PUBLIC_DIR = os.path.join(main_dir, "data")
    STATIC_URL_PATH = os.path.join(ngs_results_dir)
    ENABLE_CORS_REQUEST = True
    HG19_CHROMOSOMES = os.path.join(main_dir, "/app/bait_resources/hg19.txt")
    GENCODE_ALL_HG19 = str(
        Path(main_dir)
        / "app/bait_resources/GENCODE/hg19/gencode.v39lift37.annotation.gff3.gz"
    )
    GENCODE_ONLY_GENES_HG19 = str(
        Path(main_dir)
        / "app/bait_resources/GENCODE/hg19/gencode.v39lift37.annotation.only.genes.gff3.gz"
    )
    PANEL_DIR = "/home/udmmp/GC_NGS_PIPELINE/gene_panels/GenOncology-Dx.v1"
    ANN_DIR = ann_dir
    REF_DIR = ref_dir
    DB_DIR = db_dir
    DB = db
    ANN_YAML = os.path.join(pipeline_main, "annotation_resources.yaml")
    ANN_YAML_HG19 = os.path.join(pipeline_main, "annotation_resources_hg19.yaml")
    ANN_YAML_HG38 = os.path.join(pipeline_main, "annotation_resources_hg38.yaml")

    DOCKER_YAML = os.path.join(pipeline_main, "docker_resources.yaml")
    REF_YAML = os.path.join(pipeline_main, "reference_resources.yaml")
    BIN_YAML = os.path.join(pipeline_main, "binary_resources.yaml")
    NGS_PIPELINE_EXE = os.path.join(pipeline_main, "gc_ngs_pipeline.py")
    # SOMATIC_REPORT_TEMPLATES = os.path.join(main_dir, "reporting_templates", "1.9")
    SOMATIC_REPORT_TEMPLATES = os.path.join(main_dir, "reporting_templates", "1.10")


    SOMATIC_REPORT_IMG = os.path.join(main_dir, "reporting_templates", "img")
    SOMATIC_REPORT_CSS = os.path.join(
        main_dir, "reporting_templates", "css", "style.css"
    )
    GENE_PANEL_API = gene_panels_api_url
    #SERVER_NAME = "udmmp.ngs:5000"

class DevelopmentConfig(Config):
    DEBUG = True
    pass


class ProductionConfig(Config):
    DEBUG = False
    pass
