from flask import Blueprint, render_template, jsonify
from flask_login import login_required, current_user

monitor_bp = Blueprint('monitor', __name__)


@monitor_bp.route('/monitor')
@login_required
def monitor_page():
    return render_template('monitor.html', user=current_user)


@monitor_bp.route('/status')
@login_required
def status():
    # Sementara return dummy — nanti diisi dari ai/detector.py
    return jsonify({
        'status': 'Mencari Wajah...',
        'ear': None,
        'mar': None,
        'microsleep_counter': 0,
        'buffer_size': 0,
        'ear_mean': None,
        'mar_mean': None
    })


@monitor_bp.route('/video_feed')
@login_required
def video_feed():
    # Sementara kosong — diisi di step kamera/AI
    return "Video feed belum aktif"