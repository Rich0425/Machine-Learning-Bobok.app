from datetime import datetime
from flask_login import UserMixin
from extensions import db


class User(db.Model, UserMixin):
    id = db.Column(db.Integer, primary_key=True)
    nama = db.Column(db.String(100), nullable=False)
    username = db.Column(db.String(50), unique=True, nullable=False)
    password_hash = db.Column(db.String(255), nullable=False)
    role = db.Column(db.String(20), nullable=False)  # 'pekerja' atau 'admin'

    events = db.relationship('EventKantuk', backref='user', lazy=True)
    live_status = db.relationship('LiveStatus', backref='user', uselist=False)


class EventKantuk(db.Model):
    id = db.Column(db.Integer, primary_key=True)
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), nullable=False)
    timestamp = db.Column(db.DateTime, default=datetime.utcnow)
    jenis = db.Column(db.String(50), nullable=False)


class LiveStatus(db.Model):
    user_id = db.Column(db.Integer, db.ForeignKey('user.id'), primary_key=True)
    status = db.Column(db.String(50), default='OFFLINE')
    ear = db.Column(db.Float, default=0.0)
    mar = db.Column(db.Float, default=0.0)
    last_update = db.Column(db.DateTime, default=datetime.utcnow)