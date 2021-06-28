import os
from pathlib import Path

main_dir = os.path.dirname(os.path.abspath(__file__))

class Config(object):
  DEBUG                   = False
  TESTING                 = False
  SECRET_KEY              = "84u391jc834jcd8jcd"
  DB_NAME                 = "NGS"
  UPLOADS                 = main_dir + "/data"
  WORKING_DIRECTORY       = main_dir + "/data"
  ALLOWED_FASTQ_EXTENSIONS= ["fastq.gz", "fq.gz"]
  MAX_INPUT_FILESIZE      = 50 * 1024 * 1024
  SQLALCHEMY_DATABASE_URI = 'sqlite:///NGS.db'
  WTF_CSRF_SECRET_KEY     = "a csrf secret key"
  RECAPTCHA_PUBLIC_KEY    = "6Lcl-vsZAAAAAl1wU3t4-5jrYxwYrevk-6qN4mSi"
  RECAPTCHA_PRIVATE_KEY   = "6Lcl-vsZAAAAACPMXWnGFFy5eRaseJGOKwKoMr_p"
  MAIL_SERVER             = "smtp.gmail.com"
  MAIL_PORT               = "465"
  MAIL_USE_TLS            = False
  MAIL_USE_SSL            = True
  PUBLIC_DIR              = main_dir + "/data"
  STATIC_URL_PATH         = main_dir + "/data" 
  ENABLE_CORS_REQUEST     = True
  MAIL_USERNAME           = ''
  MAIL_PASSWORD           = ''
  NGS_PIPELINE_EXE  = "~/Escriptori/PIPELINE_CANCER/pipeline_2020.py"
  JASPERSTARTER     = "~/Escriptori/PIPELINE_CANCER/BIN_FOLDER/JASPERREPORTS/jasperstarter/bin/jasperstarter"
  JASPERREPORT_FOLDER_CAT = "~/Escriptori/PIPELINE_CANCER/BIN_FOLDER/JASPERREPORTS/MyReports/cat"
  JDBC_FOLDER       = "~/Escriptori/PIPELINE_CANCER/BIN_FOLDER/JASPERREPORTS/JDBC"
  CANCER_JRXML      = "~/Escriptori/PIPELINE_CANCER/BIN_FOLDER/JASPERREPORTS/MyReports/cat/LungCancer_Report_v1_cat.jrxml"

class DevelopmentConfig(Config):
  DEBUG = True
  DB_NAME = "NGS"
  SECRET_KEY = "84u391jc834jcd8jcd"
  UPLOADS = main_dir + "/data"
  WORKING_DIRECTORY = main_dir + "/data"
  ALLOWED_FASTQ_EXTENSIONS =  ["fastq.gz", "fq.gz"]
  MAX_INPUT_FILESIZE = 50 * 1024 * 1024
  SQLALCHEMY_DATABASE_URI = 'sqlite:///NGS.db'
  WTF_CSRF_SECRET_KEY="a csrf secret key"
  RECAPTCHA_PUBLIC_KEY = "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"
  RECAPTCHA_PRIVATE_KEY = "6LeIxAcTAAAAAGG-vFI1TnRWxMZNFuojJ4WifJWe"
  MAIL_SERVER = "smtp.gmail.com"
  MAIL_PORT = "465"
  MAIL_USE_TLS = False
  MAIL_USE_SSL = True
  PUBLIC_DIR          = main_dir + "/data"
  ENABLE_CORS_REQUEST = True
  STATIC_URL_PATH   = main_dir + "/data" 
  # MAIL_USERNAME = os.environ.get('EMAIL_USER')
  # MAIL_PASSWORD = os.environ.get('EMAIL_PASS')
  MAIL_USERNAME     = ''
  MAIL_PASSWORD     = ''
  NGS_PIPELINE_EXE  = "~/Escriptori/PIPELINE_CANCER/pipeline_2020.py"
  JASPERSTARTER     = "~/Escriptori/PIPELINE_CANCER/BIN_FOLDER/JASPERREPORTS/jasperstarter/bin/jasperstarter"
  JASPERREPORT_FOLDER_CAT = "~/Escriptori/PIPELINE_CANCER/BIN_FOLDER/JASPERREPORTS/MyReports/cat"
  JDBC_FOLDER       = "~/Escriptori/PIPELINE_CANCER/BIN_FOLDER/JASPERREPORTS/JDBC"
  CANCER_JRXML      = "~/Escriptori/PIPELINE_CANCER/BIN_FOLDER/JASPERREPORTS/MyReports/cat/LungCancer_Report_v1_cat.jrxml"


class ProductionConfig(Config):
  DEBUG = False
  DB_NAME = "NGS"
  SECRET_KEY = "84u391jc834jcd8jcd"
  UPLOADS = main_dir + "/data"
  WORKING_DIRECTORY = main_dir + "/data"
  ALLOWED_FASTQ_EXTENSIONS =  ["fastq.gz", "fq.gz"]
  MAX_INPUT_FILESIZE = 50 * 1024 * 1024
  SQLALCHEMY_DATABASE_URI = 'sqlite:///NGS.db'
  WTF_CSRF_SECRET_KEY="a csrf secret key"
  RECAPTCHA_PUBLIC_KEY = "6LeIxAcTAAAAAJcZVRqyHh71UMIEGNQ_MXjiZKhI"
  RECAPTCHA_PRIVATE_KEY = "6LeIxAcTAAAAAGG-vFI1TnRWxMZNFuojJ4WifJWe"
  MAIL_SERVER = "smtp.gmail.com"
  MAIL_PORT = "465"
  MAIL_USE_TLS = False
  MAIL_USE_SSL = True
  PUBLIC_DIR          = main_dir + "/data"
  ENABLE_CORS_REQUEST = True
  STATIC_URL_PATH   = main_dir + "/data" 
  MAIL_USERNAME     = ''
  MAIL_PASSWORD     = ''
  NGS_PIPELINE_EXE  = "~/Escriptori/PIPELINE_CANCER/pipeline_2020.py"
  JASPERSTARTER     = "~/Escriptori/PIPELINE_CANCER/BIN_FOLDER/JASPERREPORTS/jasperstarter/bin/jasperstarter"
  JASPERREPORT_FOLDER_CAT = "~/Escriptori/PIPELINE_CANCER/BIN_FOLDER/JASPERREPORTS/MyReports/cat"
  JDBC_FOLDER       = "~/Escriptori/PIPELINE_CANCER/BIN_FOLDER/JASPERREPORTS/JDBC"
  CANCER_JRXML      = "~/Escriptori/PIPELINE_CANCER/BIN_FOLDER/JASPERREPORTS/MyReports/cat/LungCancer_Report_v1_cat.jrxml"