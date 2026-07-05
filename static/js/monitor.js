/**
 * DROWSENSE — script.js
 * Polls backend Flask API, updates HUD in real-time.
 *
 * Expected backend endpoints:
 *   GET /status → { status, ear, mar, microsleep_counter, buffer_size, ear_mean, mar_mean }
 *   GET /video_feed → MJPEG stream
 *
 * Status values returned by backend:
 *   "SADAR (FOKUS)"
 *   "PERINGATAN: MATA MULAI LELAH / SAYU"
 *   "BAHAYA: MENGUAP / LELAH BERAT!"
 *   "BAHAYA: MICROSLEEP!"
 *   "Mencari Wajah..."
 */

// ── CONFIG ──────────────────────────────────────────────────────
const BACKEND_URL   = 'http://127.0.0.1:5050';
const POLL_INTERVAL = 200; // ms
const LOG_MAX       = 60;  // max log entries to keep
const MICRO_FRAMES  = 15;  // number of microsleep indicator blocks

// ── STATE ────────────────────────────────────────────────────────
let isConnected    = false;
let pollTimer      = null;
let sessionStart   = null;
let sessionTimer   = null;
let lastStatus     = '';
let lastLogStatus  = '';
let dangerFlashCooldown = false;

const stats = { bahaya: 0, peringatan: 0, sadar: 0 };

// ── DOM REFS ─────────────────────────────────────────────────────
const sysClock        = document.getElementById('sysClock');
const connDot         = document.getElementById('connDot');
const connLabel       = document.getElementById('connLabel');
const btnConnect      = document.getElementById('btnConnect');
const videoFeed       = document.getElementById('videoFeed');
const camOffline      = document.getElementById('camOffline');
const faceBox         = document.getElementById('faceBox');
const statusRing      = document.getElementById('statusRing');
const ringProgress    = document.getElementById('ringProgress');
const ringIcon        = document.getElementById('ringIcon');
const ringLabel       = document.getElementById('ringLabel');
const alertCode       = document.getElementById('alertCode');
const alertMsg        = document.getElementById('alertMsg');
const alertLog        = document.getElementById('alertLog');
const earFill         = document.getElementById('earFill');
const earVal          = document.getElementById('earVal');
const earStatus       = document.getElementById('earStatus');
const marFill         = document.getElementById('marFill');
const marVal          = document.getElementById('marVal');
const marStatus       = document.getElementById('marStatus');
const microFrames     = document.getElementById('microFrames');
const microVal        = document.getElementById('microVal');
const microStatus     = document.getElementById('microStatus');
const bufferFill      = document.getElementById('bufferFill');
const bufferVal       = document.getElementById('bufferVal');
const bufferStatus    = document.getElementById('bufferStatus');
const statSesi        = document.getElementById('statSesi');
const statBahaya      = document.getElementById('statBahaya');
const statPeringatan  = document.getElementById('statPeringatan');
const statSadar       = document.getElementById('statSadar');
const dangerFlash     = document.getElementById('dangerFlash');

// ── INIT ─────────────────────────────────────────────────────────
buildMicroFrames();
startClock();

function buildMicroFrames() {
  microFrames.innerHTML = '';
  for (let i = 0; i < MICRO_FRAMES; i++) {
    const b = document.createElement('div');
    b.className = 'micro-frame-block';
    if (i === 9) b.classList.add('threshold'); // mark 10th
    microFrames.appendChild(b);
  }
}

function startClock() {
  function tick() {
    const now = new Date();
    const hh = String(now.getHours()).padStart(2, '0');
    const mm = String(now.getMinutes()).padStart(2, '0');
    const ss = String(now.getSeconds()).padStart(2, '0');
    sysClock.textContent = `${hh}:${mm}:${ss}`;
  }
  tick();
  setInterval(tick, 1000);
}

// ── CONNECTION TOGGLE ─────────────────────────────────────────────
function toggleConnect() {
  if (!isConnected) {
    startSession();
  } else {
    stopSession();
  }
}

async function startSession() {
  setConnectionState(true);
  sessionStart = Date.now();
  sessionTimer = setInterval(updateSessionTimer, 1000);

  await fetch(`${BACKEND_URL}/start`, { method: 'POST' });

  videoFeed.src = `${BACKEND_URL}/video_feed`;
  videoFeed.onload = () => { showCamera(true); };
  videoFeed.onerror = () => { showCamera(false); };

  pollTimer = setInterval(pollStatus, POLL_INTERVAL);
  pollStatus();

  appendLog('[SISTEM] Sesi dimulai. Menghubungi backend...', 'log-sys');
}

function stopSession() {
  setConnectionState(false);
  clearInterval(pollTimer);
  clearInterval(sessionTimer);
  pollTimer = null;
  sessionTimer = null;
  sessionStart = null;

  videoFeed.src = '';
  videoFeed.style.display = 'none';
  camOffline.style.display = 'flex';
  faceBox.style.display = 'none';

  setStatus('standby');
  ringLabel.textContent = 'STANDBY';
  alertCode.textContent = 'SYS.STOP';
  alertMsg.textContent  = 'Sesi dihentikan.';
  setRingProgress(0);

  resetMetrics();
  appendLog('[SISTEM] Sesi dihentikan.', 'log-sys');
}

function setConnectionState(connected) {
  isConnected = connected;
  connDot.classList.toggle('active', connected);
  connLabel.textContent = connected ? 'ONLINE' : 'OFFLINE';
  btnConnect.innerHTML  = connected ? '<span>■ STOP</span>' : '<span>▶ MULAI</span>';
  btnConnect.classList.toggle('active', connected);
}

// ── POLLING ───────────────────────────────────────────────────────
async function pollStatus() {
  try {
    const res  = await fetch(`${BACKEND_URL}/status`, { cache: 'no-store' });
    if (!res.ok) throw new Error('HTTP ' + res.status);
    const data = await res.json();

    updateHUD(data);

  } catch (err) {
    // Backend unreachable — show error
    if (lastStatus !== 'error') {
      lastStatus = 'error';
      setStatus('standby');
      alertCode.textContent = 'ERR.CONN';
      alertMsg.textContent  = 'Tidak dapat terhubung ke backend.';
      ringLabel.textContent = 'ERROR';
      appendLog('[ERROR] Backend tidak merespons: ' + err.message, 'log-danger');
    }
  }
}

// ── HUD UPDATE ────────────────────────────────────────────────────
function updateHUD(data) {
  const {
    status            = 'Mencari Wajah...',
    ear               = null,
    mar               = null,
    microsleep_counter= 0,
    microsleep_event_count = 0,
    trigger_alarm     = false,
    buffer_size       = 0,
    ear_mean          = null,
    mar_mean          = null,
  } = data;

  // ── STATUS → UI mapping ──────────────────────────────────────
  if (status.includes('BAHAYA') && trigger_alarm) {
    // BAHAYA + ALARM: hanya jika backend sudah set trigger_alarm
    setStatus('danger');
    ringLabel.textContent = 'BAHAYA';
    alertCode.textContent = 'SYS.MICROSLEEP';
    alertMsg.textContent  = status;
    setRingProgress(100);

    if (!dangerFlashCooldown) {
      triggerDangerFlash();
      triggerAlert();  // alarm suara HANYA di sini
    }
    if (lastLogStatus !== 'danger') {
      stats.bahaya++;
      statBahaya.textContent = stats.bahaya;
      appendLog(`[BAHAYA] ${status}`, 'log-danger');
      lastLogStatus = 'danger';
    }

  } else if (status.includes('PERINGATAN') || status.includes('LELAH') || status.includes('SAYU') || status.includes('MENGUAP')) {
    // PERINGATAN: tampilan kuning, TANPA alarm suara
    setStatus('warn');
    ringLabel.textContent = 'AWAS';
    alertCode.textContent = 'SYS.WARNING';
    alertMsg.textContent  = status;
    setRingProgress(60);

    if (lastLogStatus !== 'warn') {
      stats.peringatan++;
      statPeringatan.textContent = stats.peringatan;
      appendLog(`[PERINGATAN] ${status}`, 'log-warn');
      lastLogStatus = 'warn';
    }

  } else if (status.includes('SADAR') || status.includes('FOKUS')) {
    setStatus('safe');
    ringLabel.textContent = 'FOKUS';
    alertCode.textContent = 'SYS.NORMAL';
    alertMsg.textContent  = 'Pekerja dalam kondisi waspada penuh.';
    setRingProgress(85);

    if (lastLogStatus !== 'safe') {
      stats.sadar++;
      statSadar.textContent = stats.sadar;
      appendLog(`[OK] ${status}`, 'log-safe');
      lastLogStatus = 'safe';
    }

  } else {
    // Mencari wajah / no face
    setStatus('standby');
    ringLabel.textContent = 'SCAN';
    alertCode.textContent = 'SYS.SCAN';
    alertMsg.textContent  = status;
    setRingProgress(20);
    lastLogStatus = '';
  }

  // ── EAR ─────────────────────────────────────────────────────
  if (ear !== null) {
    const earPct = Math.min((ear / 0.5) * 100, 100);
    earFill.style.width = earPct + '%';
    earFill.style.background = ear < 0.22 ? 'var(--danger)' : ear < 0.26 ? 'var(--warn)' : 'linear-gradient(90deg, var(--safe), var(--accent))';
    earVal.textContent = ear.toFixed(3);
    setMetricStatus(earStatus, ear < 0.22 ? 'KRITIS' : ear < 0.26 ? 'SAYU' : 'NORMAL',
                               ear < 0.22 ? 'st-danger' : ear < 0.26 ? 'st-warn' : 'st-safe');
  }

  // ── MAR ─────────────────────────────────────────────────────
  if (mar !== null) {
    const marPct = Math.min((mar / 0.7) * 100, 100);
    marFill.style.width = marPct + '%';
    marFill.style.background = mar > 0.4 ? 'var(--danger)' : mar > 0.25 ? 'var(--warn)' : 'linear-gradient(90deg, var(--safe), var(--accent))';
    marVal.textContent = mar.toFixed(3);
    setMetricStatus(marStatus, mar > 0.4 ? 'MENGUAP' : mar > 0.25 ? 'TERBUKA' : 'NORMAL',
                               mar > 0.4 ? 'st-danger' : mar > 0.25 ? 'st-warn' : 'st-safe');
  }

  // ── MICROSLEEP FRAMES ────────────────────────────────────────
  const blocks = microFrames.querySelectorAll('.micro-frame-block');
  blocks.forEach((b, i) => {
    b.classList.toggle('active', i < microsleep_counter);
  });
  microVal.textContent = microsleep_counter;
  setMetricStatus(microStatus,
    microsleep_counter >= 10 ? 'MICROSLEEP' : microsleep_counter > 5 ? 'WASPADA' : 'NORMAL',
    microsleep_counter >= 10 ? 'st-danger'  : microsleep_counter > 5 ? 'st-warn'  : 'st-safe'
  );

  // ── BUFFER ──────────────────────────────────────────────────
  const bufPct = Math.min((buffer_size / 30) * 100, 100);
  bufferFill.style.width = bufPct + '%';
  bufferVal.textContent = buffer_size;
  bufferStatus.textContent = buffer_size >= 30 ? 'SIAP' : 'MENGISI';
  bufferStatus.className = 'metric-status ' + (buffer_size >= 30 ? 'st-safe' : 'st-warn');

  // ── CAMERA indicator ─────────────────────────────────────────
  const hasFace = !status.includes('Mencari');
  faceBox.style.display = hasFace ? 'block' : 'none';
}

// ── HELPERS ───────────────────────────────────────────────────────
function setStatus(type) {
  document.body.classList.remove('status-safe', 'status-warn', 'status-danger', 'status-standby');
  if (type !== 'standby') {
    document.body.classList.add('status-' + type);
  }
}

function setRingProgress(pct) {
  const circumference = 2 * Math.PI * 85; // r=85
  const offset = circumference - (pct / 100) * circumference;
  ringProgress.style.strokeDashoffset = offset.toFixed(2);
}

function setMetricStatus(el, text, cls) {
  el.textContent = text;
  el.className = 'metric-status ' + cls;
}

function triggerDangerFlash() {
  dangerFlash.classList.remove('active');
  // Force reflow
  void dangerFlash.offsetWidth;
  dangerFlash.classList.add('active');
  dangerFlashCooldown = true;
  setTimeout(() => {
    dangerFlash.classList.remove('active');
    dangerFlashCooldown = false;
  }, 2000);
}

function showCamera(show) {
  videoFeed.style.display = show ? 'block' : 'none';
  camOffline.style.display = show ? 'none' : 'flex';
}

function appendLog(msg, cls = '') {
  const ts = new Date().toLocaleTimeString('id-ID', { hour12: false });
  const el = document.createElement('div');
  el.className = `log-entry ${cls}`;
  el.textContent = `[${ts}] ${msg}`;
  alertLog.appendChild(el);
  alertLog.scrollTop = alertLog.scrollHeight;

  // Trim if too long
  const entries = alertLog.querySelectorAll('.log-entry');
  if (entries.length > LOG_MAX) {
    entries[0].remove();
  }
}

function updateSessionTimer() {
  if (!sessionStart) return;
  const elapsed = Math.floor((Date.now() - sessionStart) / 1000);
  const mm = String(Math.floor(elapsed / 60)).padStart(2, '0');
  const ss = String(elapsed % 60).padStart(2, '0');
  statSesi.textContent = `${mm}:${ss}`;
}

function resetStats() {
  stats.bahaya = 0;
  stats.peringatan = 0;
  stats.sadar = 0;
  statBahaya.textContent = '0';
  statPeringatan.textContent = '0';
  statSadar.textContent = '0';
  statSesi.textContent = '00:00';
  sessionStart = isConnected ? Date.now() : null;
  alertLog.innerHTML = '';
  appendLog('[SISTEM] Statistik direset.', 'log-sys');
}

function resetMetrics() {
  earFill.style.width = '0%';
  marFill.style.width = '0%';
  earVal.textContent = '—';
  marVal.textContent = '—';
  earStatus.textContent = '—';
  marStatus.textContent = '—';
  microVal.textContent = '0';
  bufferFill.style.width = '0%';
  bufferVal.textContent = '0';

  const blocks = microFrames.querySelectorAll('.micro-frame-block');
  blocks.forEach(b => b.classList.remove('active'));

  setRingProgress(0);
}

function triggerAlert() {
  const audio = document.getElementById('alertAudio');
  if (audio) {
    audio.currentTime = 0;
    audio.play().catch(() => {});
  }
}