from app import app, mail
import os
import sys
import re
from datetime import date,datetime
from flask import Flask
from flask_sqlalchemy import SQLAlchemy
from flask_admin import Admin
from hashlib import md5
from flask import request, render_template, url_for, redirect, flash, session
from flask_wtf import FlaskForm, RecaptchaField, Form
from wtforms import StringField,SubmitField,PasswordField,validators
from wtforms.validators import InputRequired, Email, DataRequired
from flask_login import LoginManager, UserMixin, login_user, login_required, logout_user, current_user
from itsdangerous import TimedJSONWebSignatureSerializer as Serializer
from flask_mail import Message
db = SQLAlchemy(app)

login_manager = LoginManager()
login_manager.login_view = 'login'
login_manager.login_message=" Si us plau, identifica't a través d'aquest formulari"
login_manager.login_message_category="info"

login_manager.init_app(app)
# Usermixin has some interesting methods to speed up the coding part of logins..
# Primary key must be 'id'

class RequestResetForm(FlaskForm):
 # password = PasswordField("Password",[validators.DataRequired(), validators.Length(min=6, max=25)] )
  email    = StringField("Email", [validators.DataRequired(), validators.Email()] )
  submit   = SubmitField("Reestablir")

  def validate_email(self, email):
    user = User.query.filter_by(email=email.data).first()
    if user is None:
      flash ("No existeix cap usuari amb el correu electrònic entrat")

class ResetPasswordForm(FlaskForm):
  password = PasswordField("Password",[validators.DataRequired(), validators.Length(min=6, max=25)] )
  confirm_password = PasswordField("Password",[validators.DataRequired(), validators.EqualTo('password')] )
  submit   = SubmitField("Reinicialitza la contrassenya")

  def validate_email(self, email):
    user = User.query.filter_by(email=email.data).first()
    if user is None:
      flash ("No existeix cap usuari amb el correu electrònic entrat")

class User(db.Model, UserMixin):
    __tablename__ = 'USERS'
    id = db.Column(db.Integer, primary_key=True, autoincrement=True)
    username = db.Column(db.String(30), unique=True)
    password = db.Column(db.String(8))
    email = db.Column(db.String(30))
    role = db.Column(db.String(30))
    organization = db.Column(db.String(30))
    last_login = db.Column(db.String(30))
    registered_on = db.Column(db.String(30))

    def get_reset_token(self, expires_sec=1800):
      s = Serializer(app.config['SECRET_KEY'], expires_sec )
      return s.dumps({'user_id': self.id} ).decode('utf-8')

    @staticmethod
    def verify_reset_token(token):
      s = Serializer(app.config['SECRET_KEY'] )
      try:
        user_id = s.loads(token)['user_id']
      except:
        return None
      return User.query.get(user_id)

    def avatar(self, size):
        digest = md5(self.email.lower().encode('utf-8')).hexdigest()
        return 'https://www.gravatar.com/avatar/{}?d=identicon&s={}'.format(
            digest, size)
            
@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))

class RegisterForm(FlaskForm):
  username = StringField("Username",[validators.InputRequired("Si us plau, entra un nom d'usuari"), validators.Length(min=4, max=20)] )
  password = PasswordField("Password",[validators.DataRequired(), validators.Length(min=6, max=25)] )
  email    = StringField("Email", [validators.DataRequired(), validators.Email()] )
  organization =  StringField("Organization", [validators.Length(min=6, max=35)] )
  recaptcha = RecaptchaField()

class LoginForm(FlaskForm):
  username = StringField("Username",[validators.InputRequired("Si us plau, entra un nom d'usuari"), validators.Length(min=4, max=20)] )
  password = PasswordField("Password",[validators.DataRequired(), validators.Length(min=6, max=25)] )
  email    = StringField("Email", [validators.DataRequired(), validators.Email()] )
  organization =  StringField("Organization", [validators.Length(min=6, max=35)] )
  recaptcha = RecaptchaField()

class ProfileForm(FlaskForm):
  username = StringField("Username",[validators.InputRequired("Si us plau, entra un nom d'usuari"), validators.Length(min=4, max=20)] )
  password = PasswordField("Password",[validators.DataRequired(), validators.Length(min=6, max=25)] )
  confirm_password = PasswordField("Password",[validators.DataRequired(), validators.EqualTo('password')] )
  email    = StringField("Email", [validators.DataRequired(), validators.Email()] )
  organization =  StringField("Organization", [validators.Length(min=6, max=35)] )
  submit   = SubmitField("Envia")

class LoginForm(Form):
  username = StringField("Username",[validators.Length(min=4, max=20)] )
  password = PasswordField("Password",[validators.DataRequired(), validators.Length(min=6, max=25)] )
  submit   = SubmitField("Envia")

@app.route('/')
@app.route('/login', methods=['POST', 'GET'] )
def login():

  if current_user.is_authenticated:
    return redirect(url_for('menu'))

  form = LoginForm()
  if form.validate_on_submit():

    user = User.query.filter_by(username=form.username.data).filter_by(password=form.password.data).first()
    if not user:
      flash("No existeix cap usuari amb el nom i contrassenya entrats", "warning")
      return render_template("login.html", title="Login", form=form)

    if user.username == form.username.data and user.password == form.password.data:
      # session['user_id'] = user.id
      # session['username'] = user.username
      now = datetime.now()
      dt = now.strftime("%d/%m/%y-%H:%M:%S")
      user.last_login = dt
      db.session.commit()
      flash(" Benvingut " + form.username.data, "success")
      login_user(user)
      return redirect(url_for('ngs_applications'))
  return render_template("login.html", title="Login", form=form)

@app.route('/logout')
@login_required
def logout():
  logout_user()
  return redirect(url_for('ngs_applications'))

@app.route('/profile')
@login_required
def profile():
  form = ProfileForm()
  return render_template("profile.html", title="Login", form=form)

@app.route("/edit_account/<user_id>", methods=['POST', 'GET'])
@login_required
def edit_account(user_id):
  user = User.query.get(user_id)

  form = ProfileForm()
  if form.validate_on_submit():

    user.username     = form.username.data
    user.password     = form.password.data
    user.email        = form.email.data
    user.organization = form.organization.data
    db.session.commit()
    flash("El compte s'ha modificat!", "success")
    return redirect(url_for("profile"))
  return redirect(url_for("profile"))


@app.route("/delete_account/<user_id>")
@login_required
def delete_account(user_id):
  user = User.query.get(user_id)
  if user:
    db.session.delete(user)
    db.session.commit()
    flash("El compte s'ha eliminat amb èxit", "success")
    return redirect(url_for("login"))
  return redirect(url_for("profile"))

@app.route('/register', methods=['POST', 'GET'] )
def register():

  form = RegisterForm(request.form)
  if form.validate_on_submit():
    now = datetime.now()

    dt = now.strftime("%d/%m/%y-%H:%M:%S")

    if not User.query.filter_by(username=form.username.data).filter_by(password=form.password.data).first():
      user = User(username= form.username.data, password=form.password.data,
      email=form.email.data, organization=form.organization.data, role="Basic",
      last_login=dt, registered_on=dt)

      db.session.add(user)
      db.session.commit()
      flash("S'ha enregistrat correctament un nou usuari", "success")
      return redirect(url_for("login"))
  return render_template("register.html", form = form, title="Registre")

def send_reset_email(user):
  token = user.get_reset_token()
  msg = Message("Restablir contrassenya",
    sender="bernatdelolmo@gmail.com",
    recipients=[user.email])
  msg.body = f'''Per reinicialitzar la contrassenya, clica a la següent url:
{url_for('reset_token', token=token, _external=True)}
 Si no has fet aquesta petició, simplement ignora aquest missatge
'''
  mail.send(msg)

@app.route('/reset_password', methods=["GET", "POST"])
def reset_request():
  if current_user.is_authenticated:
    return redirect(url_for('menu'))
  form = RequestResetForm()
  if form.validate_on_submit():
    user = User.query.filter_by(email=form.email.data).first()
    send_reset_email(user)
    flash("El correu s'ha enviat amb instruccions per reinicialitzar la contrassenya", "info")
    return redirect(url_for("login"))
  return render_template("reset_request.html", title="Reset request", form=form)

@app.route('/reset_password/<token>', methods=["GET", "POST"])
def reset_token(token):
  if current_user.is_authenticated:
    return redirect(url_for('menu'))
  user = User.verify_reset_token(token)
  if not user:
    flash("Token invàlid o s'ha expirat", "warning")
    return redirect(url_for('reset_request'))
  form = ResetPasswordForm()
  if form.validate_on_submit():
    # now = datetime.now()
    # dt = now.strftime("%d/%m/%y-%H:%M:%S")
    user.password = form.password.data

    db.session.commit()
    flash("S'ha modificat correctament la contrassenya", "success")
    return redirect(url_for('login'))
  return render_template("reset_token.html", title="Reset request", form=form)
