from flask import Flask
from flask import request, render_template, url_for, redirect, flash
from flask_wtf import FlaskForm
import sqlite3
from flask_sqlalchemy import SQLAlchemy
from flask_sslify import SSLify
from flask_pymongo import PyMongo

import redis
from rq import Queue, cancel_job
import os
import time
#from command import launch_ngs_analysis

from app import app
if __name__ == '__main__':
    app.run(debug=True, host='0.0.0.0', port='5000')
