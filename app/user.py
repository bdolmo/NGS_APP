from app import app
import os
import sys
import re
import requests
from datetime import date,datetime
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_admin import Admin
from hashlib import md5
from flask import request, render_template, url_for, redirect, flash, session
from flask_wtf import FlaskForm, RecaptchaField, Form
from wtforms import StringField,SubmitField,PasswordField,validators
from wtforms.validators import InputRequired, Email, DataRequired
# from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from itsdangerous.url_safe import URLSafeTimedSerializer as Serializer
# from flask_mail import Message
import jwt
db = SQLAlchemy(app)



class User(db.Model):
    __tablename__ = 'USERS'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(30), unique=True)
    password = db.Column(db.String(8))
    email = db.Column(db.String(30))
    role = db.Column(db.String(30))
    organization = db.Column(db.String(30))
    last_login = db.Column(db.String(30))
    registered_on = db.Column(db.String(30))

    # def get_reset_token(self, expires_sec=1800):
    #   s = Serializer(app.config['SECRET_KEY'], expires_sec )
    #   return s.dumps({'user_id': self.id} ).decode('utf-8')

    # @staticmethod
    # def verify_reset_token(token):
    #   s = Serializer(app.config['SECRET_KEY'] )
    #   try:
    #     user_id = s.loads(token)['user_id']
    #   except:
    #     return None
    #   return User.query.get(user_id)

    def avatar(self, size):
        digest = md5(self.email.lower().encode('utf-8')).hexdigest()
        return 'https://www.gravatar.com/avatar/{}?d=identicon&s={}'.format(
            digest, size)



@app.route('/login_external')
def login_external():
    """
    Redirects to the main page.

    :returns: Returns the html of the main page.
    :rtype: render_template
    """
    URL_HOME = f'http://172.16.78.83:5000/'
    # Redirect to html
    app_dict = {"app": "ngs_app"}
    info_user = requests.post(URL_HOME + "consult_user_app", json=app_dict)
    user_info_data = info_user.json()

    rols = user_info_data['rol'].split(";")
    if 'admin' in rols:
        session['rol'] = "admin"

    session["username"] = user_info_data['user']
    session['user'] = user_info_data['user']
    session["idClient"] = user_info_data['id_client']
    # session["last_access_date"] = user_info_data['last_access_date']

    dicc_delete = {"id": user_info_data['id_client']}
    requests.post(URL_HOME + "delete_user_app", json=dicc_delete)

    # print(session['rol'], "START")

    return redirect(url_for('ngs_applications'))


@app.route('/receive_token')
def receive_token():
    received_token = request.args.get('token')
    secret_key = '12345'  # Debe ser la misma clave utilizada para generar el token

    try:
        decoded_token = jwt.decode(received_token, secret_key, algorithms=['HS256'])
        session['username'] = decoded_token.get('user_tok', 'Usuario no encontrado')
        session['user'] = decoded_token.get('user_tok', 'Usuario no encontrado')
        session['rols'] = decoded_token.get('rols_tok', 'Usuario no encontrado')
        session['email'] = decoded_token.get('email_tok', 'Usuario no encontrado')
        session['idClient'] = decoded_token.get('id_client_tok', 'Usuario no encontrado')
        session['rol'] = decoded_token.get('rol_tok', 'Usuario no encontrado')
        print(session['user'])
        print(session['rols'])
        print(session['email'])
        print(session['idClient'])
        print(session['rol'])
        return redirect(url_for('ngs_applications'))
    except Exception:
        return redirect('/logout')


@app.route('/apps')
def apps():
    tocken_cookies = {'user_tok': session['user'], 'rols_tok': session['rols'], 'email_tok': session['email'],
                      'id_client_tok': session['idClient'], 'rol_tok': 'None'}
    secret_key = '12345'
    token = jwt.encode(tocken_cookies, secret_key, algorithm='HS256')
    url = f'http://172.16.78.83:5000/apps/token?token={token}'

    return redirect(url)


@app.route('/logout')
def logout():
  URL_HOME = f'http://172.16.78.83:5000/logout'
  session['username'] = None
  session['user'] = None
  session['rol'] = None

  return redirect(URL_HOME)

