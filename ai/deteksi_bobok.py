"""
deteksi_bobok.py
================
Sistem deteksi kantuk real-time BOBOK
Menggunakan FaceLandmarker + CatBoost

Cara pakai:
    python deteksi_bobok.py

Kebutuhan:
    pip install mediapipe==0.10.14 catboost opencv-python numpy

File yang dibutuhkan di folder yang sama:
    - model_kantuk_v1.cbm
    - face_landmarker.task  (download otomatis jika tidak ada)
"""

import cv2
import mediapipe as mp
from mediapipe.tasks import python as mp_python
from mediapipe.tasks.python import vision as mp_vision
import numpy as np
from catboost import CatBoostClassifier
from collections import deque
import urllib.request
import os
import time

# ============================================================
# KONFIGURASI — sesuaikan path jika perlu
# ============================================================

BASE_DIR        = os.path.dirname(os.path.abspath(__file__))
MODEL_PATH      = os.path.join(BASE_DIR, "model_kantuk_v1.cbm")
LANDMARKER_PATH = os.path.join(BASE_DIR, "face_landmarker.task")
LANDMARKER_URL  = ("https://storage.googleapis.com/mediapipe-models/"
                   "face_landmarker/face_landmarker/float16/1/face_landmarker.task")

print("BASE_DIR:", BASE_DIR)
print("MODEL_PATH:", MODEL_PATH)
print("File exists:", os.path.exists(MODEL_PATH))

WINDOW_SIZE      = 30     # harus sama dengan saat training
BLINK_THRESH     = 0.30   # JANGAN DIUBAH: harus sama dengan saat model di-training
LONG_BLINK_FRAME = 8      # JANGAN DIUBAH: harus sama dengan saat model di-training
YAWN_THRESH      = 0.30   # JANGAN DIUBAH: harus sama dengan saat model di-training
YAWN_MIN_FRAME   = 10     # JANGAN DIUBAH: harus sama dengan saat model di-training
NOD_THRESH       = 10
MICROSLEEP_THRESH = 0.55  # Threshold terpisah khusus untuk menghitung microsleep (agar tidak sensitif)

KALIBRASI_DETIK  = 10     # durasi fase kalibrasi (detik)
KAMERA_IDX       = 0      # 0 = kamera default laptop

LABEL_NAMES = {0: "FOKUS", 1: "MULAI MENGANTUK", 2: "MENGANTUK"}
WARNA       = {
    0: (50, 205, 50),    # Hijau  — Alert
    1: (0, 165, 255),    # Oranye — Low Vigilant
    2: (0, 0, 255),      # Merah  — Drowsy
}

# ============================================================
# FACE 3D MODEL untuk head pose
# ============================================================

FACE_3D  = np.array([
    [0.0,    0.0,    0.0   ],
    [0.0,   -330.0, -65.0  ],
    [-225.0, 170.0, -135.0 ],
    [225.0,  170.0, -135.0 ],
    [-150.0,-150.0, -125.0 ],
    [150.0, -150.0, -125.0 ],
], dtype=np.float64)
POSE_IDX = [1, 152, 33, 263, 78, 308]


# ============================================================
# HELPER FUNCTIONS
# ============================================================

def download_landmarker():
    """Download face_landmarker.task jika belum ada."""
    if os.path.exists(LANDMARKER_PATH):
        return
    print("Mengunduh face_landmarker.task...")
    urllib.request.urlretrieve(LANDMARKER_URL, LANDMARKER_PATH)
    print("Download selesai.")


def buat_detector():
    opts = mp_vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(
            model_asset_path=LANDMARKER_PATH
        ),
        num_faces=1,
        min_face_detection_confidence=0.5,
        min_tracking_confidence=0.5,
        output_face_blendshapes=True,
        running_mode=mp_vision.RunningMode.LIVE_STREAM,
        result_callback=None  # akan di-override
    )
    # Untuk kamera, gunakan mode IMAGE agar lebih mudah dikontrol
    opts2 = mp_vision.FaceLandmarkerOptions(
        base_options=mp_python.BaseOptions(
            model_asset_path=LANDMARKER_PATH
        ),
        num_faces=1,
        min_face_detection_confidence=0.5,
        min_tracking_confidence=0.5,
        output_face_blendshapes=True,
        running_mode=mp_vision.RunningMode.VIDEO
    )
    return mp_vision.FaceLandmarker.create_from_options(opts2)


def ambil_blendshapes(blendshapes):
    target = {'eyeBlinkLeft', 'eyeBlinkRight', 'jawOpen', 'mouthFunnel'}
    hasil  = {}
    if not blendshapes:
        return None
    for bs in blendshapes[0]:
        if bs.category_name in target:
            hasil[bs.category_name] = bs.score
    return hasil if len(hasil) == 4 else None


def hitung_head_pose(lm, fw, fh):
    try:
        face_2d = np.array([
            [lm[i].x * fw, lm[i].y * fh]
            for i in POSE_IDX
        ], dtype=np.float64)
        cam  = np.array([[fw,0,fw/2],[0,fw,fh/2],[0,0,1]], dtype=np.float64)
        dist = np.zeros((4,1), dtype=np.float64)
        ok, rv, _ = cv2.solvePnP(FACE_3D, face_2d, cam, dist,
                                  flags=cv2.SOLVEPNP_ITERATIVE)
        if not ok:
            return None, None, None
        rm, _ = cv2.Rodrigues(rv)
        ang, _, _, _, _, _ = cv2.RQDecomp3x3(rm)
        p = float(ang[0])
        y = float(ang[1])
        r = float(ang[2])
        p = p - 180 if p > 90 else (p + 180 if p < -90 else p)
        y = y - 180 if y > 90 else (y + 180 if y < -90 else y)
        r = r - 180 if r > 90 else (r + 180 if r < -90 else r)
        return round(p,4), round(y,4), round(r,4)
    except:
        return None, None, None


def deteksi_blink_events(eye_list):
    events   = []
    in_blink = False
    dur      = 0
    for val in eye_list:
        if val >= BLINK_THRESH:
            in_blink = True
            dur     += 1
        else:
            if in_blink and dur > 0:
                events.append(dur)
            in_blink = False
            dur      = 0
    if in_blink and dur > 0:
        events.append(dur)
    return events


def hitung_fitur_dari_window(eye_list, jaw_list, pitch_list, yaw_list):
    """
    Hitung 14 fitur dari buffer window saat ini.
    Harus identik dengan feature engineering saat training.
    """
    eye   = np.array(eye_list)
    jaw   = np.array(jaw_list)
    pitch = np.array(pitch_list)
    yaw_v = np.array(yaw_list)

    # Eye blendshape
    blink_mean = float(np.mean(eye))
    blink_max  = float(np.max(eye))
    blink_std  = float(np.std(eye))

    # Blink events
    events           = deteksi_blink_events(eye_list)
    blink_rate       = len(events)
    blink_dur_mean   = float(np.mean(events)) if events else 0.0
    blink_dur_max    = float(np.max(events))  if events else 0.0
    long_n           = sum(1 for d in events if d > LONG_BLINK_FRAME)
    long_blink_ratio = long_n / len(events) if events else 0.0

    # Mouth
    jaw_mean   = float(np.mean(jaw))
    jaw_max    = float(np.max(jaw))
    yawn_count = 0
    in_yawn    = False
    yawn_dur   = 0
    for val in jaw_list:
        if val >= YAWN_THRESH:
            in_yawn  = True
            yawn_dur += 1
        else:
            if in_yawn and yawn_dur >= YAWN_MIN_FRAME:
                yawn_count += 1
            in_yawn  = False
            yawn_dur = 0

    # Head pose
    pitch_mean     = float(np.mean(pitch))
    pitch_std      = float(np.std(pitch))
    yaw_std        = float(np.std(yaw_v))
    head_nod_count = int(np.sum(pitch > NOD_THRESH))

    return np.array([[
        blink_mean, blink_max, blink_std,
        blink_rate, blink_dur_mean, blink_dur_max, long_blink_ratio,
        jaw_mean, jaw_max, yawn_count,
        pitch_mean, pitch_std, yaw_std, head_nod_count
    ]])


def gambar_ui(frame, status, label_pred, warna, deteksi_rate,
              fase_kalibrasi, kalibrasi_sisa, no_face):
    """Render overlay UI pada frame."""
    h, w = frame.shape[:2]

    # Background bar atas
    # cv2.rectangle(frame, (0, 0), (w, 70), (20, 20, 20), -1)

    if no_face:
        pass
        # cv2.putText(frame, "Wajah tidak terdeteksi",
        #             (20, 42), cv2.FONT_HERSHEY_SIMPLEX, 0.9,
        #             (0, 200, 255), 2)
    else:

        # Indikator kelas (lingkaran kecil)
        for i, (nama, col) in enumerate(zip(
            ["FOKUS", "MULAI", "KANTUK"],
            [(50,205,50), (0,165,255), (0,0,255)]
        )):
            alpha = 1.0 if i == label_pred else 0.3
            c     = tuple(int(v * alpha) for v in col)
            cv2.circle(frame, (w - 120 + i * 35, 35), 10, c, -1)

    # Detection rate bar kecil di pojok kanan bawah
    rate_text = f"Det: {deteksi_rate:.0f}%"
    cv2.putText(frame, rate_text,
                (w - 100, h - 10),
                cv2.FONT_HERSHEY_SIMPLEX, 0.4,
                (150, 150, 150), 1)

    return frame


# ============================================================
# MAIN
# ============================================================

def main():
    # 1. Download model jika belum ada
    download_landmarker()

    # 2. Load model CatBoost
    if not os.path.exists(MODEL_PATH):
        print(f"ERROR: {MODEL_PATH} tidak ditemukan.")
        print("Letakkan file model di folder yang sama dengan script ini.")
        return

    print("Memuat model CatBoost...")
    model = CatBoostClassifier()
    model.load_model(MODEL_PATH)
    print("Model siap.")

    # 3. Inisialisasi FaceLandmarker
    print("Menyiapkan FaceLandmarker...")
    detector = buat_detector()
    print("FaceLandmarker siap.")

    # 4. Buka kamera
    cap = cv2.VideoCapture(KAMERA_IDX)
    if not cap.isOpened():
        print(f"ERROR: Kamera {KAMERA_IDX} tidak bisa dibuka.")
        return

    fw  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    fh  = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0
    print(f"Kamera: {fw}x{fh} @ {fps:.0f}fps")
    print("Tekan 'q' untuk keluar.")

    # Buffer sliding window
    buf_eye   = deque(maxlen=WINDOW_SIZE)
    buf_jaw   = deque(maxlen=WINDOW_SIZE)
    buf_pitch = deque(maxlen=WINDOW_SIZE)
    buf_yaw   = deque(maxlen=WINDOW_SIZE)

    # State
    frame_idx       = 0
    ts_ms           = 0
    status          = "Memulai..."
    label_pred      = 0
    warna_status    = WARNA[0]
    deteksi_history = deque(maxlen=90)  # 3 detik

    # Fase kalibrasi
    kalibrasi_aktif = True
    kalibrasi_mulai = time.time()

    while True:
        ret, frame = cap.read()
        if not ret:
            break

        frame_idx += 1
        ts_ms      = int(frame_idx / fps * 1000)

        # Flip horizontal (efek cermin)
        frame = cv2.flip(frame, 1)
        rgb   = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = detector.detect_for_video(mp_img, ts_ms)

        no_face = (not result.face_landmarks or
                   len(result.face_landmarks) == 0)

        deteksi_history.append(0 if no_face else 1)
        det_rate = sum(deteksi_history) / len(deteksi_history) * 100

        if not no_face:
            lm = result.face_landmarks[0]
            bs = ambil_blendshapes(result.face_blendshapes)
            p, y, r = hitung_head_pose(lm, fw, fh)

            if bs is not None and p is not None:
                eye_avg = (bs['eyeBlinkLeft'] + bs['eyeBlinkRight']) / 2.0
                buf_eye.append(eye_avg)
                buf_jaw.append(bs['jawOpen'])
                buf_pitch.append(p)
                buf_yaw.append(y)

        # Cek status kalibrasi
        sisa_kalibrasi = KALIBRASI_DETIK - (time.time() - kalibrasi_mulai)
        if kalibrasi_aktif and sisa_kalibrasi <= 0:
            kalibrasi_aktif = False
            print("Kalibrasi selesai. Mulai deteksi.")

        # Prediksi (hanya jika kalibrasi selesai dan buffer penuh)
        if not kalibrasi_aktif and len(buf_eye) == WINDOW_SIZE:
            fitur  = hitung_fitur_dari_window(
                list(buf_eye), list(buf_jaw),
                list(buf_pitch), list(buf_yaw)
            )
            pred       = int(model.predict(fitur).flatten()[0])
            label_pred = pred
            status     = LABEL_NAMES[pred]
            warna_status = WARNA[pred]

        # Render UI
        frame = gambar_ui(
            frame, status, label_pred, warna_status,
            det_rate, kalibrasi_aktif, sisa_kalibrasi, no_face
        )

        cv2.imshow("BOBOK — Deteksi Kantuk", frame)

        if cv2.waitKey(1) & 0xFF == ord('q'):
            break

    cap.release()
    detector.close()
    cv2.destroyAllWindows()
    print("Selesai.")


if __name__ == "__main__":
    main()

# ============================================================
# SHARED STATE — dibaca oleh Flask
# ============================================================
import threading

state_lock = threading.Lock()
shared_state = {
    'status': 'Mencari Wajah...',
    'ear': None,
    'mar': None,
    'microsleep_counter': 0,
    'microsleep_event_count': 0,
    'trigger_alarm': False,
    'buffer_size': 0,
    'ear_mean': None,
    'mar_mean': None,
    'frame': None,
    'running': False,
}

def start_detection():
    global shared_state

    download_landmarker()

    if not os.path.exists(MODEL_PATH):
        print(f"ERROR: {MODEL_PATH} tidak ditemukan.")
        return

    model = CatBoostClassifier()
    model.load_model(MODEL_PATH)
    detector = buat_detector()

    cap = cv2.VideoCapture(KAMERA_IDX)
    if not cap.isOpened():
        print("ERROR: Kamera tidak bisa dibuka.")
        return

    fw  = int(cap.get(cv2.CAP_PROP_FRAME_WIDTH))
    fh  = int(cap.get(cv2.CAP_PROP_FRAME_HEIGHT))
    fps = cap.get(cv2.CAP_PROP_FPS) or 30.0

    buf_eye   = deque(maxlen=WINDOW_SIZE)
    buf_jaw   = deque(maxlen=WINDOW_SIZE)
    buf_pitch = deque(maxlen=WINDOW_SIZE)
    buf_yaw   = deque(maxlen=WINDOW_SIZE)

    frame_idx        = 0
    ts_ms            = 0
    status           = 'Mencari Wajah...'
    label_pred       = 0
    warna_status     = WARNA[0]
    microsleep_counter = 0
    microsleep_event_count = 0       # total event microsleep dalam sesi
    prev_microsleep_active = False   # apakah frame sebelumnya sedang microsleep
    MICROSLEEP_EVENT_THRESHOLD = 10  # alarm baru bunyi setelah 10 event
    deteksi_history  = deque(maxlen=90)
    kalibrasi_aktif  = True
    kalibrasi_mulai  = time.time()

    with state_lock:
        shared_state['running'] = True

    while shared_state['running']:
        ret, frame = cap.read()
        if not ret:
            break

        frame_idx += 1
        ts_ms      = int(frame_idx / fps * 1000)
        frame      = cv2.flip(frame, 1)
        rgb        = cv2.cvtColor(frame, cv2.COLOR_BGR2RGB)

        mp_img = mp.Image(image_format=mp.ImageFormat.SRGB, data=rgb)
        result = detector.detect_for_video(mp_img, ts_ms)

        no_face = (not result.face_landmarks or len(result.face_landmarks) == 0)
        deteksi_history.append(0 if no_face else 1)

        ear_val = None
        mar_val = None

        if not no_face:
            lm = result.face_landmarks[0]
            bs = ambil_blendshapes(result.face_blendshapes)
            p, y, r = hitung_head_pose(lm, fw, fh)

            if bs is not None and p is not None:
                eye_avg = (bs['eyeBlinkLeft'] + bs['eyeBlinkRight']) / 2.0
                ear_val = float(eye_avg)
                mar_val = float(bs['jawOpen'])
                buf_eye.append(eye_avg)
                buf_jaw.append(bs['jawOpen'])
                buf_pitch.append(p)
                buf_yaw.append(y)

        sisa_kalibrasi = KALIBRASI_DETIK - (time.time() - kalibrasi_mulai)
        if kalibrasi_aktif and sisa_kalibrasi <= 0:
            kalibrasi_aktif = False

        if no_face:
            status = 'Mencari Wajah...'
            microsleep_counter = 0
        elif kalibrasi_aktif:
            status = f'Kalibrasi... ({sisa_kalibrasi:.0f}s)'
        elif len(buf_eye) == WINDOW_SIZE:
            fitur  = hitung_fitur_dari_window(
                list(buf_eye), list(buf_jaw),
                list(buf_pitch), list(buf_yaw)
            )
            pred       = int(model.predict(fitur).flatten()[0])
            label_pred = pred
            warna_status = WARNA[pred]

            # Microsleep counter (menghitung frame saat mata tertutup beruntun)
            if ear_val is not None and ear_val >= MICROSLEEP_THRESH:
                microsleep_counter += 1
            else:
                microsleep_counter = 0

            # Alarm terpicu jika mata tertutup terus-menerus selama 720 frame (24 detik)
            trigger_alarm = (microsleep_counter >= 720)

            if microsleep_counter >= 720:
                status = 'BAHAYA: TERTIDUR PULAS!'
            elif pred == 2:
                status = 'PERINGATAN: MENGUAP / LELAH BERAT'
            elif pred == 1:
                status = 'PERINGATAN: MATA MULAI LELAH / SAYU'
            else:
                status = 'SADAR (FOKUS)'

        # Render overlay di frame
        frame = gambar_ui(
            frame, status, label_pred, warna_status,
            sum(deteksi_history) / len(deteksi_history) * 100,
            kalibrasi_aktif, max(0, sisa_kalibrasi), no_face
        )

        # Encode frame ke JPEG
        _, jpeg = cv2.imencode('.jpg', frame)

        with state_lock:
            shared_state['status']               = status
            shared_state['ear']                  = ear_val
            shared_state['mar']                  = mar_val
            shared_state['microsleep_counter']   = microsleep_counter
            shared_state['microsleep_event_count'] = microsleep_event_count
            shared_state['trigger_alarm']        = trigger_alarm if 'trigger_alarm' in dir() else False
            shared_state['buffer_size']          = len(buf_eye)
            shared_state['ear_mean']             = float(np.mean(buf_eye)) if buf_eye else None
            shared_state['mar_mean']             = float(np.mean(buf_jaw)) if buf_jaw else None
            shared_state['frame']                = jpeg.tobytes()

    cap.release()
    detector.close()
    with state_lock:
        shared_state['running'] = False


if __name__ == "__main__":
    start_detection()