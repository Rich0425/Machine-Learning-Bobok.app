from flask import Flask, Response, jsonify, render_template, redirect, url_for, request, flash
from flask_cors import CORS
from flask_sqlalchemy import SQLAlchemy
from flask_login import LoginManager, UserMixin, login_user, logout_user, login_required, current_user
from werkzeug.security import generate_password_hash, check_password_hash
from datetime import datetime, timezone
import threading
import sys
import os

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, BASE_DIR)

from ai.deteksi_bobok import start_detection, shared_state, state_lock

app = Flask(__name__)
CORS(app, supports_credentials=True)
app.config['SECRET_KEY'] = 'bobok-secret-key-2024'
app.config['SQLALCHEMY_DATABASE_URI'] = 'sqlite:///' + os.path.join(BASE_DIR, 'database.db')
app.config['SQLALCHEMY_TRACK_MODIFICATIONS'] = False

db = SQLAlchemy(app)
login_manager = LoginManager(app)
login_manager.login_view = 'login'

detection_thread = None


# ============================================================
# MODELS
# ============================================================

class User(db.Model, UserMixin):
    id            = db.Column(db.Integer, primary_key=True)
    nama          = db.Column(db.String(100), nullable=False)
    username      = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role          = db.Column(db.String(20), nullable=False)
    events        = db.relationship('EventKantuk', backref='user', lazy=True)
    live_status   = db.relationship('LiveStatus', backref='user', uselist=False)


class EventKantuk(db.Model):
    id        = db.Column(db.Integer, primary_key=True)
    user_id   = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    jenis     = db.Column(db.String(50), nullable=False)


class LiveStatus(db.Model):
    user_id     = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    status      = db.Column(db.String(100), default='OFFLINE')
    ear         = db.Column(db.Float, default=0.0)
    mar         = db.Column(db.Float, default=0.0)
    last_update = db.Column(db.DateTime, default=datetime.utcnow)


@login_manager.user_loader
def load_user(user_id):
    return User.query.get(int(user_id))


# ============================================================
# AUTH ROUTES
# ============================================================

@app.route('/')
def index():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin_live'))
        return redirect(url_for('monitor'))
    return redirect(url_for('login'))


@app.route('/login', methods=['GET', 'POST'])
def login():
    if current_user.is_authenticated:
        if current_user.role == 'admin':
            return redirect(url_for('admin_live'))
        return redirect(url_for('monitor'))

    if request.method == 'POST':
        username = request.form.get('username')
        password = request.form.get('password')
        user = User.query.filter_by(username=username).first()
        if user and check_password_hash(user.password_hash, password):
            login_user(user)
            if user.role == 'admin':
                return redirect(url_for('admin_live'))
            return redirect(url_for('monitor'))
        flash('Username atau password salah.')
    return render_template('login.html')


@app.route('/register', methods=['GET', 'POST'])
def register():
    if request.method == 'POST':
        nama     = request.form.get('nama')
        username = request.form.get('username')
        password = request.form.get('password')
        role     = 'pekerja'  # Paksa role menjadi pekerja, tidak bisa daftar sebagai admin
        if User.query.filter_by(username=username).first():
            flash('Username sudah terdaftar.')
            return redirect(url_for('register'))
        user = User(
            nama=nama,
            username=username,
            password_hash=generate_password_hash(password),
            role=role
        )
        db.session.add(user)
        db.session.commit()
        flash('Registrasi berhasil, silakan login.')
        return redirect(url_for('login'))
    return render_template('register.html')


@app.route('/logout')
@login_required
def logout():
    live = LiveStatus.query.get(current_user.id)
    if live:
        live.status = 'OFFLINE'
        db.session.commit()
    logout_user()
    return redirect(url_for('login'))


# ============================================================
# PEKERJA ROUTES
# ============================================================

@app.route('/monitor')
@login_required
def monitor():
    if current_user.role != 'pekerja':
        return redirect(url_for('admin_live'))
    return render_template('monitor.html', user=current_user)


@app.route('/analytics')
@login_required
def analytics():
    if current_user.role != 'pekerja':
        return redirect(url_for('admin_analytics'))
    return render_template('analytics_pekerja.html', user=current_user)


# ============================================================
# ADMIN ROUTES
# ============================================================

@app.route('/admin/live')
@login_required
def admin_live():
    if current_user.role != 'admin':
        return redirect(url_for('monitor'))
    return render_template('admin_live.html', user=current_user)


@app.route('/admin/analytics')
@login_required
def admin_analytics():
    if current_user.role != 'admin':
        return redirect(url_for('monitor'))
    return render_template('admin_analytics.html', user=current_user)


# ============================================================
# API ROUTES — DETEKSI
# ============================================================

@app.route('/start', methods=['POST'])
@login_required
def start():
    global detection_thread
    with state_lock:
        already_running = shared_state['running']

    if not already_running:
        detection_thread = threading.Thread(target=start_detection, daemon=True)
        detection_thread.start()

    live = LiveStatus.query.get(current_user.id)
    if not live:
        live = LiveStatus(user_id=current_user.id, status='AKTIF')
        db.session.add(live)
    else:
        live.status = 'AKTIF'
        live.last_update = datetime.utcnow()
    db.session.commit()

    return jsonify({'ok': True})


@app.route('/stop', methods=['POST'])
@login_required
def stop():
    with state_lock:
        shared_state['running'] = False

    live = LiveStatus.query.get(current_user.id)
    if live:
        live.status = 'OFFLINE'
        db.session.commit()
    return jsonify({'ok': True})


@app.route('/status')
@login_required
def status():
    with state_lock:
        data = {k: v for k, v in shared_state.items() if k != 'frame'}

    status_str = data.get('status', 'Mencari Wajah...')

    live = LiveStatus.query.get(current_user.id)
    if live:
        live.status      = status_str
        live.ear         = data.get('ear') or 0.0
        live.mar         = data.get('mar') or 0.0
        live.last_update = datetime.utcnow()
        db.session.commit()

    # Tarik data dari antrean pending_events dan catat
    pending = []
    with state_lock:
        if 'pending_events' in shared_state and shared_state['pending_events']:
            pending = list(shared_state['pending_events'])
            shared_state['pending_events'].clear()

    if pending:
        for ev_type in pending:
            ev = EventKantuk(user_id=current_user.id, jenis=ev_type)
            db.session.add(ev)
        db.session.commit()

    return jsonify(data)


@app.route('/video_feed')
@login_required
def video_feed():
    def generate():
        while True:
            with state_lock:
                frame = shared_state.get('frame')
            if frame:
                yield (b'--frame\r\n'
                       b'Content-Type: image/jpeg\r\n\r\n' + frame + b'\r\n')
    return Response(generate(), mimetype='multipart/x-mixed-replace; boundary=frame')


# ============================================================
# API ROUTES — ADMIN & ANALYTICS
# ============================================================

@app.route('/admin/live_data')
@login_required
def admin_live_data():
    if current_user.role != 'admin':
        return jsonify([]), 403
    statuses = LiveStatus.query.join(User).filter(User.role == 'pekerja').all()
    hasil = []
    for s in statuses:
        hasil.append({
            'user_id':     s.user_id,
            'nama':        s.user.nama,
            'status':      s.status,
            'ear':         s.ear,
            'mar':         s.mar,
            'last_update': s.last_update.isoformat() if s.last_update else None
        })
    return jsonify(hasil)


@app.route('/api/analytics')
@login_required
def api_analytics():
    if current_user.role == 'pekerja':
        target_id = current_user.id
    else:
        target_id = request.args.get('user_id', type=int)

    query = EventKantuk.query
    if target_id:
        query = query.filter_by(user_id=target_id)

    events = query.order_by(EventKantuk.timestamp.desc()).all()
    hasil = []
    for e in events:
        hasil.append({
            'id':        e.id,
            'user_id':   e.user_id,
            'nama':      e.user.nama,
            'timestamp': e.timestamp.isoformat(),
            'jenis':     e.jenis
        })
    return jsonify(hasil)


@app.route('/api/pekerja_list')
@login_required
def pekerja_list():
    if current_user.role != 'admin':
        return jsonify([]), 403
    pekerja = User.query.filter_by(role='pekerja').all()
    return jsonify([{'id': p.id, 'nama': p.nama} for p in pekerja])


# ============================================================
# INIT & RUN
# ============================================================

with app.app_context():
    db.create_all()

if __name__ == '__main__':
    app.run(host='0.0.0.0', port=5050, debug=False, threaded=True)
