import os
from pathlib import Path

main_dir = os.path.dirname(os.path.abspath(__file__))

pipeline_main = "/home/gencardio/Desktop/GC_NGS_PIPELINE"
ann_dir = "/home/gencardio/Desktop/ANN_DIR/"
ref_dir = "/home/gencardio/Desktop/REF_DIR/"
db_dir = "/home/gencardio/Desktop/NGS_APP/app"
db = "/home/gencardio/Desktop/NGS_APP/app/NGS.db"
data_dir = "/home/gencardio/Desktop/NGS_APP/app"
ngs_app_url = "http://172.16.78.84:8000"
gene_panels_api_url = "http://172.16.78.84:8000/api/gene_panels"
compendium_url = "http://172.16.78.84:8001"


class Config(object):
    DEBUG = False
    TESTING = False
    SQLALCHEMY_TRACK_MODIFICATIONS = False
    SECRET_KEY = "84u391jc834jcd8jcd"
    DB_NAME = "NGS"
    UPLOADS = os.path.join(main_dir, "data")
    WORKING_DIRECTORY = os.path.join(main_dir, "data")
    ALLOWED_FASTQ_EXTENSIONS = ["fastq.gz", "fq.gz"]
    MAX_INPUT_FILESIZE = 50 * 1024 * 1024
    SQLALCHEMY_DATABASE_URI = "sqlite:////home/gencardio/Desktop/NGS_APP/app/NGS.db"
    WTF_CSRF_SECRET_KEY = "a csrf secret key"
    RECAPTCHA_PUBLIC_KEY = "6Lcl-vsZAAAAAl1wU3t4-5jrYxwYrevk-6qN4mSi"
    RECAPTCHA_PRIVATE_KEY = "6Lcl-vsZAAAAACPMXWnGFFy5eRaseJGOKwKoMr_p"
    PUBLIC_DIR = os.path.join(main_dir, "data")
    STATIC_URL_PATH = os.path.join(main_dir, "data")
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
    PANEL_DIR = "/home/gencardio/Desktop/GC_NGS_PIPELINE/gene_panels/GenOncology-Dx.v1"
    ANN_DIR = ann_dir
    REF_DIR = ref_dir
    DB_DIR = db_dir
    DB = db
    ANN_YAML = os.path.join(pipeline_main, "annotation_resources.yaml")
    DOCKER_YAML = os.path.join(pipeline_main, "docker_resources.yaml")
    REF_YAML = os.path.join(pipeline_main, "reference_resources.yaml")
    BIN_YAML = os.path.join(pipeline_main, "binary_resources.yaml")
    NGS_PIPELINE_EXE = os.path.join(pipeline_main, "gc_ngs_pipeline.py")
    # SOMATIC_REPORT_TEMPLATES = os.path.join(main_dir, "reporting_templates", "1.3")
    # SOMATIC_REPORT_TEMPLATES = os.path.join(main_dir, "reporting_templates", "1.5")
    SOMATIC_REPORT_TEMPLATES = os.path.join(main_dir, "reporting_templates", "1.6")


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
