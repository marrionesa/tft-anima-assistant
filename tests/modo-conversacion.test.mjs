/**
 * Pruebas de regresión del modo conversación.
 * Cubre el ciclo normal (silencio de 3 s), la interrupción y los casos límite,
 * para asegurar que la lógica de inactividad no haya roto nada.
 *
 * Uso:  node tests/modo-conversacion.test.mjs
 */
import { readFileSync } from 'node:fs';

// Ruta relativa al propio test: funciona desde cualquier directorio.
const html = readFileSync(new URL('../anima-ollama-tft/server/static/index.html', import.meta.url), 'utf8');
const js = html.match(/<script>\n([\s\S]*?)\n<\/script>/)[1];

/* ── Reloj y DOM ──────────────────────────────────────────────────────── */
let clock = 0;
globalThis.performance = { now: () => clock };
let rafQ = [];
globalThis.requestAnimationFrame = (fn) => { rafQ.push(fn); return rafQ.length; };
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
    this._t = realSetInterval(() => {
      if (this.state === 'recording' && this.ondataavailable) this.ondataavailable({ data: { size: 24000 } });
    }, 20);
  }
  stop() { realClearInterval(this._t); this.state = 'inactive'; if (this.onstop) this.onstop(); }
}

const fetchLog = [];
globalThis.fetch = async (url) => {
  fetchLog.push(url);
  if (url.includes('/transcribe')) {
    const partial = url.includes('partial=true');
    return { ok: true, json: async () => ({ ok: true, text: partial ? '' : 'hola qué tal' }), blob: async () => new Blob([]) };
  }
  if (url.includes('/api/chat')) return { ok: true, json: async () => ({ ok: true, answer: 'respuesta de prueba' }) };
  if (url.includes('/speak')) return { ok: false, blob: async () => new Blob([]) };
  return { ok: true, json: async () => ({ ok: true }), blob: async () => new Blob([]) };
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
const els = {};
const mk = () => ({
  hidden: false, dataset: {}, style: {}, textContent: '', innerHTML: '',
  classList: { add() {}, remove() {}, toggle() {}, contains: () => false },
  append() {}, replaceChildren() {}, addEventListener() {}, setAttribute() {}, focus() {},
  querySelector: () => null, scrollTop: 0, scrollHeight: 0,
});
globalThis.document = { querySelector: s => (els[s] ??= mk()), createElement: mk, addEventListener() {}, body: { style: {} } };
globalThis.localStorage = { getItem: () => '[]', setItem() {} };
globalThis.WebSocket = class { constructor() { this.readyState = 0; } };
globalThis.setInterval = () => 0;
globalThis.clearInterval = () => {};
globalThis.confirm = () => true;

const patched = js.replace(
  'renderHistory(); connectSocket(); checkHealth(); setInterval(checkHealth,45000);',
  `renderHistory(); connectSocket(); checkHealth(); setInterval(checkHealth,45000);
   globalThis.__T = { VOICE, openVoiceMode, closeVoiceMode, interrupt,
     SILENCE_MS, INTERRUPT_FRAMES, MAX_IDLE_MS };`
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
    const q = rafQ; rafQ = [];
    q.forEach(fn => fn());
  }
}
const advance = (ms) => { clock += ms; };

console.log('\n▶ Modo conversación · regresión del flujo normal\n');
clock = 1000;
await T.openVoiceMode();
check('abre y empieza escuchando', T.VOICE.open === true && T.VOICE.phase === 'listening');

// Silencio inicial: no debe gastar peticiones
const p0 = fetchLog.filter(u => u.includes('partial=true')).length;
pump(60, 0);
await new Promise(r => setTimeout(r, 60));
check('sin voz no pide transcripciones', fetchLog.filter(u => u.includes('partial=true')).length === p0);

// Hablar: sí debe transcribir en vivo
pump(20, 0.25);
await new Promise(r => setTimeout(r, 150));
check('al hablar pide transcripción en vivo',
  fetchLog.filter(u => u.includes('partial=true')).length > p0);
check('detecta voz', T.VOICE.heardVoice === true);

// Silencio de 2 s: sigue escuchando
advance(2000); pump(60, 0);
check('2 s de silencio aún no cierra', T.VOICE.phase === 'listening', `(phase=${T.VOICE.phase})`);

// Silencio de 3 s: cierra el turno
advance(1100); pump(5, 0);
await new Promise(r => setTimeout(r, 250));
check('3 s de silencio cierra y transcribe',
  fetchLog.filter(u => u === '/api/voice/transcribe').length >= 1);
check('pide respuesta al modelo', fetchLog.some(u => u.includes('/api/chat')));

// Interrupción
T.VOICE.sending = true; T.VOICE.phase = 'speaking'; T.VOICE.loudFrames = 0;
pump(T.INTERRUPT_FRAMES - 1, 0.5);
check('voz breve no interrumpe', T.VOICE.phase === 'speaking');
pump(2, 0.5);
check('voz sostenida interrumpe', T.VOICE.phase === 'listening');
check('la interrupción limpia el turno', T.VOICE.heardVoice === false);

// El eco no debe interrumpir
T.VOICE.phase = 'speaking'; T.VOICE.loudFrames = 0;
pump(40, 0.02);
check('el eco del altavoz no corta', T.VOICE.phase === 'speaking');

// Tras hablar, el cierre por inactividad NO debe dispararse antes de tiempo
T.VOICE.phase = 'listening';
T.VOICE.heardVoice = true;
T.VOICE.lastVoiceAt = clock;
T.VOICE.turnStart = clock;
advance(5000); pump(10, 0);
check('hablando no se cierra por inactividad', T.VOICE.open === true);

// Cierre manual
T.closeVoiceMode();
check('cierre manual libera el micro', T.VOICE.open === false && T.VOICE.stream === null);

console.log(`\n${fail === 0 ? '✅' : '❌'} Resultado: ${pass} correctas, ${fail} fallidas\n`);
process.exit(fail === 0 ? 0 : 1);
