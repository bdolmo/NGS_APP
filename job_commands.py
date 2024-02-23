#from app import app
import requests
import time
import sys
import os
import subprocess
import glob
from config import data_dir

def launch_ngs_analysis(params):
    '''
        Launch an NGS analysis based on its job_id and analysis parameters.
        :param params: A dictionary containing the analysis parameters. The dictionary should have the following keys:
            - PIPELINE_EXE : str
                The path to the NGS analysis pipeline executable.
            - PANEL : str
                The name of the gene panel to be analyzed.
            - PANEL_NAME : str
                The name of the gene panel.
            - PANEL_VERSION : str
                The version of the gene panel.
            - GENOME : str
                The path to the reference genome FASTA file.
            - THREADS : int
                The number of threads to use for the analysis.
            - VARCLASS : str
                The variant class to be analyzed.
            - INPUT_DIR : str
                The path to the input directory containing the raw FASTQ files.
            - OUTPUT_DIR : str
                The path to the output directory where the analysis results will be written.
            - LAB_DATA : str
                The path to the lab data YAML file (optional).
            - DB : str
                The path to the sqlite database.
            - USER_ID : str
                The user ID for the analysis.
            - ANN_YAML : str
                The path to the annotation YAML file.
            - DOCKER_YAML : str
                The path to the Docker YAML file.
            - REF_YAML : str
                The path to the reference YAML file.
            - BIN_YAML : str
                The path to the binary YAML file.
            - RUN_NAME : str
                The name of the analysis run.
        :type params: dict

        :returns: If the analysis completes successfully and produces output, returns the analysis output as a string.
                Otherwise, returns None.
        :rtype: str or None

        :raises Exception: If the analysis fails, raises an Exception with the error message.
        
    '''

    lab_data = ""
    if os.path.isfile(params['LAB_DATA']):
        lab_data = f" --lab_data {params['LAB_DATA']}"

    cmd = [
        'python3', params['PIPELINE_EXE'], 'all', '-s', 'targeted', '--panel',
        params['PANEL'], '--panel_name', params['PANEL_NAME'], '--panel_version',
        params['PANEL_VERSION'], '-r', params['GENOME'], '-t', params['THREADS'],
        '--var_class', params['VARCLASS'], '-i', params['INPUT_DIR'], '-o',
        params['OUTPUT_DIR'], lab_data, '--db', params['DB'], '--user_id',
        params['USER_ID'], '--ann_yaml', params['ANN_YAML'], '--docker_yaml',
        params['DOCKER_YAML'], '--ref_yaml', params['REF_YAML'], '--bin_yaml',
        params['BIN_YAML'], '--run_id', params['RUN_NAME']
    ]
    cmd = [str(item) for item in cmd]
    print(' '.join([str(item) for item in cmd]))

    
    commands_file = os.path.join(data_dir, 'pipeline_logs.txt')
    with open(commands_file, 'a') as f:
        f.write(' '.join(cmd) + '\n')
    
    cmd = ' '.join([str(item) for item in cmd])

    p1 = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, shell=True)
    output = p1.stdout.decode("UTF-8").rstrip('\n')
    error = p1.stderr.decode("UTF-8").rstrip('\n')

    if p1.returncode != 0:
        for err in error.split('\n'):
            print(f'FOUND error: {err}')
        raise Exception(error)

    # Remove raw fastq files
    # fastq_list = glob.glob(os.path.join(params['OUTPUT_DIR'], '*fastq.gz'))
    # for fq in fastq_list:
    #     os.remove(fq)

    print('Task complete')
    if output:
        return output


# def launch_lowpass_analysis(job_id, params):
#
#     bashCommand = 'python3 {} call -s lowpass -r {} -t {} '\
#         ' -i {} -o {} --ann_dir {} --ref_dir {} --db_dir {} --user_id {} '\
#         ' --ann_yaml {} --docker_yaml {} --ref_yaml {} --bin_yaml {}'\
#         .format(params['PIPELINE_EXE'], params['GENOME'], params['THREADS'],
#             params['RUN_DIR'], params['RUN_DIR'],params['ANN_DIR'], params['REF_DIR'],
#             params['DB_DIR'], params['USER_ID'],params['ANN_YAML'], params['DOCKER_YAML'],
#             params['REF_YAML'], params['BIN_YAML'])
#     print(bashCommand)
#
#     p1 = subprocess.run(bashCommand, shell=True, stdout=subprocess.PIPE,
#         stderr=subprocess.PIPE)
#     output = p1.stdout.decode('UTF-8')
#     error  = p1.stderr.decode('UTF-8')
#     if not error and not output:
#         msg = " INFO: Analyzing"
#         print(msg)
#     else:
#         print(output)
#     print(bashCommand)
#     print("Task complete")
