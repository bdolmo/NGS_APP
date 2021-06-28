from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_cors import CORS
from flask_admin import Admin
from hashlib import md5
from flask import request, render_template, url_for, redirect, flash, session
from flask_wtf import FlaskForm, RecaptchaField, Form
from wtforms import StringField,SubmitField,PasswordField,validators
from wtforms.validators import InputRequired, Email, DataRequired
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from flask_mail import Mail
from itsdangerous import TimedJSONWebSignatureSerializer as Serializer

app = Flask(__name__)
app.config.from_object("config.DevelopmentConfig")
mail = Mail(app)
CORS(app)
db = SQLAlchemy(app)

from app import complete_analysis, petitions, user, results, management
