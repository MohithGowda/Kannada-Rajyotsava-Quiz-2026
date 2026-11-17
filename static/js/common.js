/* Shared helpers: DOM, API, clock sync, sounds, confetti */
const $ = (sel, root = document) => root.querySelector(sel);
const esc = (s) => String(s ?? '').replace(/[&<>"']/g, (c) => ({ '&': '&amp;', '<': '&lt;', '>': '&gt;', '"': '&quot;', "'": '&#39;' }[c]));

async function api(url, body) {
  const opts = { credentials: 'same-origin', headers: { 'Content-Type': 'application/json' } };
  if (body !== undefined) { opts.method = 'POST'; opts.body = JSON.stringify(body); }
  const res = await fetch(url, opts);
  let data = null;
  try { data = await res.json(); } catch (_) { /* non-JSON body */ }
  return { ok: res.ok, status: res.status, data };
}

const fmtClock = (ms) => {
  const s = Math.max(0, Math.ceil(ms / 1000));
  return `${Math.floor(s / 60)}:${String(s % 60).padStart(2, '0')}`;
};
const fmtSec = (ms) => (ms == null ? '–' : `${(ms / 1000).toFixed(2)}s`);

/* Keeps a countdown aligned to the server's clock between polls. */
class RoundClock {
  constructor() { this.status = 'waiting'; this.remaining = 0; this.duration = 300000; this.at = performance.now(); }
  update(round) {
    this.status = round.status;
    this.remaining = round.remaining_ms;
    this.duration = round.duration_s * 1000;
    this.at = performance.now();
  }
  get remainingMs() {
    if (this.status !== 'running') return this.remaining;
    return Math.max(0, this.remaining - (performance.now() - this.at));
  }
  get over() { return this.status === 'finished' || (this.status === 'running' && this.remainingMs <= 0); }
}

/* Tiny WebAudio sound effects (no asset files needed). */
const Sound = (() => {
  let ctx = null;
  let on = localStorage.getItem('kr26-sound') !== 'off';
  const tone = (freq, start, dur, type = 'sine', gain = 0.12) => {
    if (!on) return;
    try {
      ctx = ctx || new (window.AudioContext || window.webkitAudioContext)();
      const t0 = ctx.currentTime + start;
      const osc = ctx.createOscillator();
      const g = ctx.createGain();
      osc.type = type; osc.frequency.value = freq;
      g.gain.setValueAtTime(gain, t0);
      g.gain.exponentialRampToValueAtTime(0.0001, t0 + dur);
      osc.connect(g); g.connect(ctx.destination);
      osc.start(t0); osc.stop(t0 + dur);
    } catch (_) { /* audio unavailable */ }
  };
  return {
    get on() { return on; },
    toggle() { on = !on; localStorage.setItem('kr26-sound', on ? 'on' : 'off'); return on; },
    correct() { tone(660, 0, .12, 'triangle'); tone(880, .1, .12, 'triangle'); tone(1320, .2, .22, 'triangle'); },
    wrong() { tone(220, 0, .22, 'sawtooth', .08); tone(165, .16, .3, 'sawtooth', .08); },
    end() { [523, 659, 784, 1047].forEach((f, i) => tone(f, i * .14, .3, 'triangle')); },
  };
})();

/* Confetti burst in Karnataka colours. */
function confetti(durationMs = 4000) {
  const canvas = $('#confetti');
  if (!canvas) return;
  const ctx = canvas.getContext('2d');
  const resize = () => { canvas.width = innerWidth; canvas.height = innerHeight; };
  resize();
  const colors = ['#ffc61a', '#d8161f', '#fff4d6', '#ff8a3d', '#ffe27a'];
  const parts = Array.from({ length: 160 }, () => ({
    x: Math.random() * canvas.width, y: -20 - Math.random() * canvas.height * .6,
    w: 6 + Math.random() * 8, h: 10 + Math.random() * 10, vy: 2 + Math.random() * 4,
    vx: -2 + Math.random() * 4, r: Math.random() * 6, vr: -.2 + Math.random() * .4,
    c: colors[Math.floor(Math.random() * colors.length)],
  }));
  const end = performance.now() + durationMs;
  (function frame(now) {
    ctx.clearRect(0, 0, canvas.width, canvas.height);
    parts.forEach((p) => {
      p.x += p.vx; p.y += p.vy; p.r += p.vr;
      ctx.save(); ctx.translate(p.x, p.y); ctx.rotate(p.r);
      ctx.fillStyle = p.c; ctx.fillRect(-p.w / 2, -p.h / 2, p.w, p.h); ctx.restore();
    });
    if (now < end) requestAnimationFrame(frame); else ctx.clearRect(0, 0, canvas.width, canvas.height);
  })(performance.now());
}

/* Leaderboard markup shared by participant result page and the big screen. */
function boardHtml(teams, { limit = 10, meId = null, big = false } = {}) {
  return teams.slice(0, limit).map((t) => `
    <li data-id="${t.id}" class="${t.id === meId ? 'me' : ''}">
      <span class="pos">${t.rank}</span>
      <span class="tname">${esc(t.name)}<span class="tmeta">${t.correct} ✓ · ${t.answered - t.correct} ✗ · avg ${fmtSec(t.avg_ms)}</span></span>
      ${big ? `<span class="tstat">${t.answered} ಉತ್ತರ</span>` : ''}
      <span class="tscore">${t.score}</span>
    </li>`).join('');
}
