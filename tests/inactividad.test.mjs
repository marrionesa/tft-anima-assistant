/**
 * Reproduce la fuga de recursos del modo conversación:
 * abrir el micro y no hablar nunca debe terminar solo, sin gastar peticiones.
 *
 * Uso:  node tests/inactividad.test.mjs
 */
import { readFileSync } from 'node:fs';

// Ruta relativa al propio test: funciona desde cualquier directorio.
const html = readFileSync(new URL('../anima-ollama-tft/server/static/index.html', import.meta.url), 'utf8');
const js = html.match(/<script>\n([\s\S]*?)\n<\/script>/)[1];

/* ── DOM mínimo ───────────────────────────────────────────────────────── */
const listeners = new Map();
function makeEl(id = '') {
  return {
    id, hidden: false, disabled: false, dataset: {}, style: {}, textContent: '',
    innerHTML: '', className: '', children: [],
    classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
    append(c) { this.children.push(c); }, replaceChildren() { this.children = []; },
    addEventListener(t, fn) { listeners.set(`${id}:${t}`, fn); },
    setAttribute() {}, focus() {}, querySelector: () => null,
    scrollTop: 0, scrollHeight: 0,
  };
}
const els = {};
const $ = (sel) => (els[sel] ??= makeEl(sel.replace('#', '')));

/* ── Reloj controlado ─────────────────────────────────────────────────── */
// La prueba avanza el tiempo a mano para no esperar 60 s reales.
let clock = 0;
globalThis.performance = { now: () => clock };

let rafQueue = [];
globalThis.requestAnimationFrame = (fn) => { rafQueue.push(fn); return rafQueue.length; };
globalThis.cancelAnimationFrame = () => {};

let currentRms = 0;
class FakeAnalyser {
  constructor() { this.fftSize = 1024; this.smoothingTimeConstant = 0; }
  getByteTimeDomainData(buf) {
    const amp = Math.min(1, currentRms) * 127;
    for (let i = 0; i < buf.length; i++) buf[i] = Math.round(128 + amp * Math.sin((i / buf.length) * Math.PI * 4));
  }
}
class FakeAudioCtx {
  constructor() { this.state = 'running'; }
  createMediaStreamSource() { return { connect() {} }; }
  createAnalyser() { return new FakeAnalyser(); }
  resume() { return Promise.resolve(); }
  close() { return Promise.resolve(); }
}

const realSetInterval = globalThis.setInterval;
const realClearInterval = globalThis.clearInterval;
class FakeMediaRecorder {
  constructor(stream, opts = {}) {
    this.stream = stream; this.mimeType = opts.mimeType || 'audio/webm';
    this.state = 'inactive'; this.ondataavailable = null; this.onstop = null;
  }
  static isTypeSupported() { return true; }
  start() {
    this.state = 'recording';
    // Entrega fragmentos de audio aunque no haya voz, como el navegador real.
    this._t = realSetInterval(() => {
      if (this.state === 'recording' && this.ondataavailable) this.ondataavailable({ data: { size: 24000 } });
    }, 20);
  }
  stop() { realClearInterval(this._t); this.state = 'inactive'; if (this.onstop) this.onstop(); }
}

const fetchLog = [];
globalThis.fetch = async (url) => {
  fetchLog.push({ url, at: clock });
  if (url.includes('/transcribe')) {
    return { ok: true, json: async () => ({ ok: true, text: '', partial: url.includes('partial') }), blob: async () => new Blob([]) };
  }
  return { ok: true, json: async () => ({ ok: true, answer: 'x' }), blob: async () => new Blob([]) };
};

globalThis.location = { protocol: 'http:', host: 'x' };
globalThis.window = {
  isSecureContext: true, addEventListener() {},
  mediaDevices: { getUserMedia: async () => ({ active: true, getTracks: () => [{ stop() {} }] }) },
  MediaRecorder: FakeMediaRecorder, AudioContext: FakeAudioCtx, Audio: class {},
  location: globalThis.location,
};
Object.defineProperty(globalThis, 'navigator', {
  configurable: true,
  value: { mediaDevices: { getUserMedia: async () => ({ active: true, getTracks: () => [{ stop() {} }] }) } },
});
globalThis.MediaRecorder = FakeMediaRecorder;
globalThis.Audio = class { play() { return Promise.resolve(); } pause() {} };
globalThis.Blob = class { constructor(p) { this.size = (p || []).length ? 4096 * Math.max(1, p.length) : 0; } };
globalThis.URL = { createObjectURL: () => 'blob:x', revokeObjectURL() {} };
globalThis.AbortController = class { constructor() { this.signal = {}; } abort() {} };
globalThis.document = {
  querySelector: $, createElement: () => makeEl(), addEventListener() {}, body: { style: {} },
};
globalThis.localStorage = { getItem: () => '[]', setItem() {} };
globalThis.WebSocket = class { constructor() { this.readyState = 0; } };
globalThis.setInterval = () => 0;
globalThis.clearInterval = () => {};
globalThis.confirm = () => true;

/* ── Carga del script real ────────────────────────────────────────────── */
const patched = js.replace(
  'renderHistory(); connectSocket(); checkHealth(); setInterval(checkHealth,45000);',
  `renderHistory(); connectSocket(); checkHealth(); setInterval(checkHealth,45000);
   globalThis.__T = { VOICE, openVoiceMode, closeVoiceMode, startListening,
     MAX_TURN_MS,
     MAX_IDLE_MS: (typeof MAX_IDLE_MS !== 'undefined' ? MAX_IDLE_MS : undefined),
     IDLE_WARN_MS: (typeof IDLE_WARN_MS !== 'undefined' ? IDLE_WARN_MS : undefined) };`
);
if (!patched.includes('__T =')) throw new Error('no se pudo instrumentar');
new Function(patched)();
const T = globalThis.__T;

/* ── Utilidades ───────────────────────────────────────────────────────── */
let pass = 0, fail = 0;
const check = (name, cond, extra = '') => {
  if (cond) { pass++; console.log(`  ✅ ${name}`); }
  else { fail++; console.log(`  ❌ ${name} ${extra}`); }
};
function pump(frames, rms = 0) {
  currentRms = rms;
  for (let i = 0; i < frames; i++) {
    const q = rafQueue; rafQueue = [];
    q.forEach(fn => fn());
  }
}
const advance = (ms) => { clock += ms; };
const partials = () => fetchLog.filter(f => f.url.includes('partial=true')).length;

/* ── Escenario: abrir el micro y no decir nada ────────────────────────── */
console.log('\n▶ Fuga por inactividad · abrir el micro y olvidarse\n');
clock = 1000;

await T.openVoiceMode();
check('el modo voz se abre', T.VOICE.open === true);
console.log(`     MAX_IDLE_MS=${T.MAX_IDLE_MS ?? 'no definido'} · IDLE_WARN_MS=${T.IDLE_WARN_MS ?? 'no definido'}`);

// Simulamos 90 s de silencio absoluto, con el grabador entregando fragmentos.
const partialsBefore = partials();
for (let t = 0; t < 90; t += 1) {
  advance(1000);
  pump(60, 0);                     // 60 frames/s de silencio
  await new Promise(r => setTimeout(r, 12));   // deja entregar fragmentos
}

const wasted = partials() - partialsBefore;
console.log(`     peticiones parciales gastadas en 90 s de silencio: ${wasted}`);
console.log(`     estado final: open=${T.VOICE.open}  phase=${T.VOICE.phase}`);

check('no gasta peticiones de transcripción si no hablas', wasted === 0, `(gastó ${wasted})`);
check('el popup se cierra solo por inactividad', T.VOICE.open === false, `(open=${T.VOICE.open})`);
check('el micrófono se libera al cerrarse', T.VOICE.stream === null);

console.log(`\n${fail === 0 ? '✅' : '❌'} Resultado: ${pass} correctas, ${fail} fallidas\n`);
process.exit(fail === 0 ? 0 : 1);
