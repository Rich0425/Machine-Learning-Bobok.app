
from flask import Blueprint, render_template, jsonify
from flask_login import login_required, current_user
from models import User, LiveStatus

admin_bp = Blueprint('admin', __name__)


def admin_required(func):
    from functools import wraps
    @wraps(func)
    def wrapper(*args, **kwargs):
        if current_user.role != 'admin':
            return "Akses ditolak", 403
        return func(*args, **kwargs)
    return wrapper


@admin_bp.route('/admin/live')
@login_required
@admin_required
def live():
    return render_template('admin_live.html', user=current_user)


@admin_bp.route('/admin/live_data')
@login_required
@admin_required
def live_data():
    # Ambil semua status terkini pekerja
    statuses = LiveStatus.query.join(User).filter(User.role == 'pekerja').all()

    hasil = []
    for s in statuses:
        hasil.append({
            'user_id': s.user_id,
            'nama': s.user.nama if hasattr(s, 'user') else None,
            'status': s.status,
            'ear': s.ear,
            'mar': s.mar,
            'last_update': s.last_update.isoformat() if s.last_update else None
        })

    return jsonify(hasil)


@admin_bp.route('/admin/analytics')
@login_required
@admin_required
def analytics():
    return render_template('admin_analytics.html', user=current_user)