from flask import Blueprint, render_template, jsonify, request
from flask_login import login_required, current_user
from models import EventKantuk, User
from extensions import db
from sqlalchemy import func

analytics_bp = Blueprint('analytics', __name__)


@analytics_bp.route('/analytics')
@login_required
def analytics_page():
    return render_template('analytics_pekerja.html', user=current_user)


@analytics_bp.route('/api/analytics')
@login_required
def analytics_data():
    # Pekerja hanya bisa lihat data dirinya sendiri
    # Admin bisa pilih user_id tertentu, atau default semua
    if current_user.role == 'pekerja':
        target_user_id = current_user.id
    else:
        target_user_id = request.args.get('user_id', type=int)

    query = EventKantuk.query
    if target_user_id:
        query = query.filter_by(user_id=target_user_id)

    events = query.order_by(EventKantuk.timestamp.desc()).all()

    hasil = []
    for e in events:
        hasil.append({
            'id': e.id,
            'user_id': e.user_id,
            'nama': e.user.nama if hasattr(e, 'user') else None,
            'timestamp': e.timestamp.isoformat(),
            'jenis': e.jenis
        })

    return jsonify(hasil)