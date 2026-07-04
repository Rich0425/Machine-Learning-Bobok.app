from flask import Blueprint, render_template, redirect, url_for, request, flash
from flask_login import login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash

from extensions import db
from models import User

auth_bp = Blueprint('auth', __name__)


@auth_bp.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin.live'))
        return redirect(url_for('monitor.monitor_page'))
    return redirect(url_for('auth.login'))


@auth_bp.route('/login', methods=['GET', 'POST'])
def login():
    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')

        user = User.query.filter_by(username=username).first()

        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            if user.role == 'admin':
                return redirect(url_for('admin.live'))
            return redirect(url_for('monitor.monitor_page'))

        flash('Username atau password salah.')
        return redirect(url_for('auth.login'))

    return render_template('login.html')


@auth_bp.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        nama = request.form.get('nama')
        username = request.form.get('username')
        password = request.form.get('password')
        role = request.form.get('role')  # 'pekerja' atau 'admin'

        existing = User.query.filter_by(username=username).first()
        if existing:
            flash('Username sudah terdaftar.')
            return redirect(url_for('auth.register'))

        new_user = User(
            nama=nama,
            username=username,
            password_hash=generate_password_hash(password),
            role=role
        )
        db.session.add(new_user)
        db.session.commit()

        flash('Registrasi berhasil, silakan login.')
        return redirect(url_for('auth.login'))

    return render_template('register.html')


@auth_bp.route('/logout')
@login_required
def logout():
    logout_user()
    return redirect(url_for('auth.login'))