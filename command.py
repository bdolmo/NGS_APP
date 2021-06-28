import requests
import time
import sys
import os
import subprocess
import glob

def background_task(job_id, params):

    print("Task working")
    delay =5
    time.sleep(delay)

    lab_data = ""
    if os.path.isfile(params['LAB_DATA'] ):
        lab_data = " --lab_data " + params['LAB_DATA']

    bashCommand = 'python3 {} all -s targeted --panel {} -r {} -t {} '\
        ' --var_class {} -i {} -o {} {} --ann_dir {} '\
        ' --ref_dir {} --db_dir {} --user_id {}'\
        .format(params['PIPELINE_EXE'], params['PANEL'], params['GENOME'], params['THREADS'],
            params['VARCLASS'], params['RUN_DIR'], params['RUN_DIR'], lab_data,
            params['ANN_DIR'], params['REF_DIR'], params['DB_DIR'], params['USER_ID'] )
    print(bashCommand)
    p1 = subprocess.run(bashCommand, shell=True, stdout=subprocess.PIPE, stderr=subprocess.PIPE)
    output = p1.stdout.decode('UTF-8')
    error  = p1.stderr.decode('UTF-8')
    if not error and not output:
        msg = " INFO: Analyzing"
        print(msg)
    else:
        # msg = " ERROR: Something went wrong with the analysis"
        # print(msg)
        print(output)

    # Copy all png IGV snapshots to static folder
    # igv_folder = params['STATIC_DIR'] + "/" + "IGV_SNAPSHOTS" + "/" + os.path.basename(params['RUN_DIR'])
    # if not os.path.isdir(igv_folder):
    #     os.mkdir(igv_folder)
    # vcf_folders =


    print("Task complete")
