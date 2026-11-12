/* ASHA VoiceMate - dashboard logic (vanilla JavaScript).
 *
 * The browser NEVER sees the Gnani API key. It only talks to our own server:
 *   /api/stt  -> server -> Gnani Prisma v3.0 (REST, clips up to 30 s)
 *   /api/tts  -> server -> Gnani Timbre v3.0 (REST, MP3 audio)
 * There is deliberately NO fallback to browser speech recognition or speechSynthesis.
 */
"use strict";

const $ = (id) => document.getElementById(id);
const DRAFT_KEY = "asha_voicemate_draft_v1";
const REQUEST_TIMEOUT_MS = 30000;
const MAX_RECORD_SECONDS = 29;        // Gnani REST STT limit is 30 seconds
const STT_SAMPLE_RATE = 16000;        // inside Gnani's documented 8-44.1 kHz range

/* Browsers record WebM/Opus, which is not in Gnani's supported list
 * (WAV, MP3, OGG, FLAC, AAC, M4A). Decode it and re-encode as 16 kHz mono WAV. */
async function blobToWav(blob) {
  const buf = await blob.arrayBuffer();
  const ctx = new (window.AudioContext || window.webkitAudioContext)();
  let decoded;
  try { decoded = await ctx.decodeAudioData(buf); } finally { ctx.close(); }
  const frames = Math.ceil(decoded.duration * STT_SAMPLE_RATE);
  const offline = new OfflineAudioContext(1, Math.max(frames, 1), STT_SAMPLE_RATE);
  const src = offline.createBufferSource();
  src.buffer = decoded;
  src.connect(offline.destination);      // multi-channel input is mixed down to mono
  src.start();
  const pcm = (await offline.startRendering()).getChannelData(0);
  const out = new DataView(new ArrayBuffer(44 + pcm.length * 2));
  const str = (o, s) => { for (let i = 0; i < s.length; i++) out.setUint8(o + i, s.charCodeAt(i)); };
  str(0, "RIFF"); out.setUint32(4, 36 + pcm.length * 2, true); str(8, "WAVE");
  str(12, "fmt "); out.setUint32(16, 16, true); out.setUint16(20, 1, true); out.setUint16(22, 1, true);
  out.setUint32(24, STT_SAMPLE_RATE, true); out.setUint32(28, STT_SAMPLE_RATE * 2, true);
  out.setUint16(32, 2, true); out.setUint16(34, 16, true);
  str(36, "data"); out.setUint32(40, pcm.length * 2, true);
  for (let i = 0; i < pcm.length; i++) {
    const s = Math.max(-1, Math.min(1, pcm[i]));
    out.setInt16(44 + i * 2, s < 0 ? s * 0x8000 : s * 0x7fff, true);
  }
  return new Blob([out], { type: "audio/wav" });
}

const FIELD_ORDER = [
  "beneficiary_id", "beneficiary_name", "visit_type", "weight_kg", "vaccinations_due",
  "vaccination_status", "anc_status", "ifa_status", "tt_status", "next_visit_date", "notes",
];

const EXAMPLES = [
  { label: "ANC visit", text: "Beneficiary ID B101, ANC visit. ANC checkup done, IFA tablets given 30 tablets, TT injection due. No bleeding. Next visit on Monday." },
  { label: "Newborn visit", text: "ID B205 newborn visit, weight 2.5 kilo, BCG and OPV due, next visit after 7 days" },
  { label: "Correction", text: "No, weight is 2.8 kilo." },
  { label: "Change date", text: "Change the next visit date to Friday." },
  { label: "Confirm", text: "yes" },
  { label: "Hinglish", text: "ID B102 pregnant hai, ANC jaanch ho gayi, IFA goli le rahi hai, TT lag gaya, agli visit kal" },
  { label: "⚠ Danger: newborn", text: "ID B201 newborn visit weight 2.6 kg, baby is not feeding and has fever, next visit tomorrow", danger: true },
  { label: "⚠ Uncertain", text: "maybe there is some bleeding", danger: true },
];

const state = {
  languages: [],
  lang: "en-IN",
  session: null,
  pendingSaveId: null,
  busy: false,
  savedVisitId: null,
  status: {},
  lastRecord: {},
  dismissedAlertKey: null,
};

/* ------------------------------------------------------------------ */
/* Helpers                                                              */
/* ------------------------------------------------------------------ */
function esc(s) {
  return String(s ?? "").replace(/[&<>"']/g, (c) => ({ "&": "&amp;", "<": "&lt;", ">": "&gt;", '"': "&quot;", "'": "&#39;" }[c]));
}

function uuid() {
  if (window.crypto && crypto.randomUUID) return crypto.randomUUID();
  return "id-" + Date.now().toString(36) + "-" + Math.random().toString(36).slice(2, 12);
}

class ApiError extends Error {
  constructor(message, status) { super(message); this.status = status; }
}

async function api(path, { method = "GET", body, form, timeout = REQUEST_TIMEOUT_MS, raw = false } = {}) {
  const ctrl = new AbortController();
  const timer = setTimeout(() => ctrl.abort(), timeout);
  const opts = { method, signal: ctrl.signal, headers: {} };
  if (form) opts.body = form;
  else if (body !== undefined) { opts.body = JSON.stringify(body); opts.headers["Content-Type"] = "application/json"; }
  let res;
  try {
    res = await fetch(path, opts);
  } catch (e) {
    throw new ApiError(e.name === "AbortError"
      ? "The server took too long to respond. Check your connection and try again."
      : "Cannot reach the ASHA VoiceMate server. Check your connection; your draft is kept on this device.", 0);
  } finally {
    clearTimeout(timer);
  }
  if (!res.ok) {
    let msg = `Request failed (${res.status})`;
    try {
      const j = await res.json();
      if (typeof j.detail === "string") msg = j.detail;
      else if (Array.isArray(j.detail)) msg = "Invalid input: " + j.detail.map((d) => d.msg).join("; ");
    } catch { /* not JSON */ }
    throw new ApiError(msg, res.status);
  }
  return raw ? res : res.json();
}

function toast(message, kind = "") {
  const el = document.createElement("div");
  el.className = "toast " + kind;
  el.textContent = message;
  $("toasts").appendChild(el);
  setTimeout(() => el.remove(), kind === "error" ? 8000 : 4500);
}

function langInfo() { return state.languages.find((l) => l.code === state.lang) || state.languages[0] || { labels: {}, values: {} }; }
function label(f) { return langInfo().labels?.[f] || f; }
function valueText(v) {
  if (Array.isArray(v)) return v.length ? v.map(valueText).join(", ") : "—";
  return langInfo().values?.[v] || v;
}
function fmtDate(iso) {
  if (!iso) return "";
  const d = new Date(iso.length === 10 ? iso + "T00:00:00" : iso);
  if (isNaN(d)) return iso;
  return d.toLocaleDateString(undefined, { weekday: "short", day: "numeric", month: "short", year: "numeric" });
}
function todayIso() { const d = new Date(); return new Date(d.getTime() - d.getTimezoneOffset() * 60000).toISOString().slice(0, 10); }

/* ------------------------------------------------------------------ */
/* Draft preservation (this device only)                                */
/* ------------------------------------------------------------------ */
function saveDraft() {
  try {
    const s = state.session;
    if (!s || s.state === "cancelled" || state.savedVisitId) { localStorage.removeItem(DRAFT_KEY); return; }
    localStorage.setItem(DRAFT_KEY, JSON.stringify({
      session_id: s.session_id, language: s.language,
      utterances: (s.transcripts || []).map((t) => t.text),
      pendingSaveId: state.pendingSaveId, at: new Date().toISOString(),
    }));
  } catch { /* storage may be blocked - app still works */ }
}
function loadDraft() { try { return JSON.parse(localStorage.getItem(DRAFT_KEY) || "null"); } catch { return null; } }
function clearDraft() { try { localStorage.removeItem(DRAFT_KEY); } catch { /* ignore */ } }

/* ------------------------------------------------------------------ */
/* Status indicators                                                    */
/* ------------------------------------------------------------------ */
function setStatus(id, cls, title) {
  const el = $(id);
  el.classList.remove("ok", "warn", "err");
  if (cls) el.classList.add(cls);
  if (title) el.title = title;
}

async function refreshStatus() {
  try {
    const s = await api("/api/status", { timeout: 8000 });
    state.status = s;
    setStatus("st-db", s.database.ready ? "ok" : "err", s.database.ready ? "Database: connected" : "Database: error");
    for (const [id, name, svc] of [["st-stt", "STT", s.stt], ["st-tts", "TTS", s.tts]]) {
      if (!svc.ready) setStatus(id, "warn", `Gnani ${name}: ${svc.reason}`);
      else if (svc.last_call_ok === false) setStatus(id, "err", `Gnani ${name} (${svc.model}): last call failed - ${svc.last_error}`);
      else if (svc.last_call_ok === true) setStatus(id, "ok", `Gnani ${name} (${svc.model}): working`);
      else setStatus(id, "ok", `Gnani ${name} (${svc.model}): key configured, not used yet`);
    }
    $("ttsNote").textContent = s.tts.ready ? "" : "Voice output off: Gnani API key not set";
  } catch (e) {
    setStatus("st-db", "err", e.message);
    setStatus("st-stt", "err", e.message);
    setStatus("st-tts", "err", e.message);
  }
}

/* ------------------------------------------------------------------ */
/* Text-to-speech (Gnani via our server) - alert first, then message   */
/* ------------------------------------------------------------------ */
const speechQueue = [];
let speaking = false;
let currentAudio = null;

function speak(text, { urgent = false } = {}) {
  if (!text) return;
  if (urgent) {
    speechQueue.length = 0;
    if (currentAudio) { currentAudio.pause(); currentAudio = null; }
    speechQueue.unshift(text);
  } else {
    speechQueue.push(text);
  }
  if (!speaking) playNext();
}

async function playNext() {
  const text = speechQueue.shift();
  if (!text) { speaking = false; return; }
  speaking = true;
  if (!state.status?.tts?.ready) {           // shown on screen only - no fake voice
    speaking = false;
    speechQueue.length = 0;
    return;
  }
  try {
    const res = await api("/api/tts", { method: "POST", body: { text, language: state.lang }, raw: true });
    const url = URL.createObjectURL(await res.blob());
    currentAudio = new Audio(url);
    currentAudio.onended = currentAudio.onerror = () => { URL.revokeObjectURL(url); currentAudio = null; playNext(); };
    setStatus("st-tts", "ok", "Gnani TTS: working");
    $("ttsNote").textContent = "";
    await currentAudio.play();
  } catch (e) {
    if (e.name === "NotAllowedError") {
      $("ttsNote").textContent = "Tap anywhere on the page to allow voice playback";
    } else {
      setStatus("st-tts", "err", "Gnani TTS: " + e.message);
      $("ttsNote").textContent = "Voice output failed: " + e.message;
    }
    playNext();
  }
}

/* ------------------------------------------------------------------ */
/* Waveform                                                             */
/* ------------------------------------------------------------------ */
const wave = { analyser: null, data: null, t: 0, mode: "idle" };

function drawWave() {
  const c = $("wave");
  const dpr = window.devicePixelRatio || 1;
  const w = c.clientWidth, h = c.clientHeight;
  if (w < 50 || h < 10) { requestAnimationFrame(drawWave); return; }   // not laid out yet
  const pw = Math.round(w * dpr), ph = Math.round(h * dpr);
  if (c.width !== pw || c.height !== ph) { c.width = pw; c.height = ph; }
  const ctx = c.getContext("2d");
  ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
  ctx.clearRect(0, 0, w, h);

  const bars = Math.max(24, Math.floor(w / 7));
  const gap = 3, bw = Math.max(1, w / bars - gap);
  const grad = ctx.createLinearGradient(0, 0, w, 0);
  if (wave.mode === "recording") { grad.addColorStop(0, "#ff4d61"); grad.addColorStop(1, "#ff9a6b"); }
  else { grad.addColorStop(0, "#19d3c5"); grad.addColorStop(1, "#35c8f5"); }
  ctx.fillStyle = grad;

  if (wave.analyser) wave.analyser.getByteFrequencyData(wave.data);
  wave.t += 0.035;
  for (let i = 0; i < bars; i++) {
    let amp;
    if (wave.analyser) {
      const idx = Math.floor((i / bars) * wave.data.length * 0.7);
      amp = wave.data[idx] / 255;
      amp = Math.max(0.04, amp);
    } else if (wave.mode === "processing") {
      amp = 0.15 + 0.35 * Math.abs(Math.sin(wave.t * 3 + i * 0.35));
    } else {
      amp = 0.05 + 0.07 * (Math.sin(wave.t + i * 0.28) + 1) / 2;
    }
    const bh = Math.max(3, amp * (h - 6));
    const x = i * (bw + gap) + gap / 2;
    const y = (h - bh) / 2;
    ctx.globalAlpha = wave.analyser ? 0.95 : 0.55;
    roundRect(ctx, x, y, bw, bh, Math.min(3, bw / 2));
  }
  requestAnimationFrame(drawWave);
}
function roundRect(ctx, x, y, w, h, r) {
  ctx.beginPath();
  ctx.moveTo(x + r, y); ctx.arcTo(x + w, y, x + w, y + h, r); ctx.arcTo(x + w, y + h, x, y + h, r);
  ctx.arcTo(x, y + h, x, y, r); ctx.arcTo(x, y, x + w, y, r); ctx.closePath(); ctx.fill();
}

/* ------------------------------------------------------------------ */
/* Microphone + Gnani STT (via server)                                  */
/* ------------------------------------------------------------------ */
const rec = { stream: null, recorder: null, chunks: [], ctx: null, timer: null, started: 0 };

async function toggleMic() {
  if (rec.recorder && rec.recorder.state === "recording") { stopRecording(); return; }
  if (state.busy) return;
  if (!state.session || ["confirmed", "cancelled"].includes(state.session.state)) await startSession();
  if (!navigator.mediaDevices?.getUserMedia || !window.MediaRecorder) {
    setStatus("st-mic", "err", "This browser cannot record audio");
    toast("This browser cannot record audio. Please use a recent Chrome or Edge.", "error");
    return;
  }
  try {
    rec.stream = await navigator.mediaDevices.getUserMedia({ audio: { echoCancellation: true, noiseSuppression: true } });
  } catch (e) {
    const msg = e.name === "NotAllowedError" ? "Microphone permission was denied. Click the lock icon in the address bar and allow the microphone."
      : e.name === "NotFoundError" ? "No microphone was found. Please connect a microphone."
      : "Could not start the microphone: " + e.message;
    setStatus("st-mic", "err", msg);
    toast(msg, "error");
    return;
  }
  setStatus("st-mic", "ok", "Microphone: allowed");
  rec.ctx = new (window.AudioContext || window.webkitAudioContext)();
  const src = rec.ctx.createMediaStreamSource(rec.stream);
  wave.analyser = rec.ctx.createAnalyser();
  wave.analyser.fftSize = 256;
  wave.data = new Uint8Array(wave.analyser.frequencyBinCount);
  src.connect(wave.analyser);
  wave.mode = "recording";

  rec.chunks = [];
  rec.recorder = new MediaRecorder(rec.stream);
  rec.recorder.ondataavailable = (ev) => { if (ev.data.size) rec.chunks.push(ev.data); };
  rec.recorder.onstop = onRecordingStopped;
  rec.recorder.start();
  rec.started = Date.now();
  $("micTimer").classList.remove("hidden");
  rec.timer = setInterval(() => {
    const s = Math.floor((Date.now() - rec.started) / 1000);
    $("micTimer").textContent = `${Math.floor(s / 60)}:${String(s % 60).padStart(2, "0")}`;
    if (s >= MAX_RECORD_SECONDS) stopRecording();
  }, 250);
  setMicUi("recording");
}

function stopRecording() {
  clearInterval(rec.timer);
  if (rec.recorder && rec.recorder.state === "recording") rec.recorder.stop();
  rec.stream?.getTracks().forEach((t) => t.stop());
  rec.ctx?.close();
  wave.analyser = null;
  $("micTimer").classList.add("hidden");
}

async function onRecordingStopped() {
  const blob = new Blob(rec.chunks, { type: rec.recorder.mimeType || "audio/webm" });
  rec.chunks = [];
  if (!blob.size) { setMicUi("idle"); toast("No audio was captured. Please try again.", "warn"); return; }
  setMicUi("processing");
  let wav;
  try {
    wav = await blobToWav(blob);
  } catch (e) {
    setMicUi("idle");
    toast("Could not prepare the recording for upload. Please record again.", "error");
    return;
  }
  const form = new FormData();
  form.append("audio", wav, "recording.wav");
  form.append("language", state.lang);
  try {
    const r = await api("/api/stt", { method: "POST", form, timeout: 60000 });
    setStatus("st-stt", "ok", "Gnani STT: working");
    setMicUi("idle");
    if (r.truncated) toast("The recording was cut short by the speech service. Please say the rest separately.", "warn");
    if (r.text && r.text.trim()) await sendUtterance(r.text, "stt");
    else toast("No speech was recognised. Please speak again, closer to the phone.", "warn");
  } catch (e) {
    setMicUi("idle");
    if (e.status === 501) {
      setStatus("st-stt", "warn", "Gnani STT: " + e.message);
      toast("Audio was recorded, but Gnani speech-to-text is not connected: " + e.message + " Use the test input box for now.", "warn");
      $("typedInput").focus();
    } else {
      setStatus("st-stt", "err", "Gnani STT: " + e.message);
      toast("Speech-to-text failed: " + e.message, "error");
    }
  }
}

function setMicUi(mode) {
  const btn = $("micBtn");
  btn.classList.toggle("recording", mode === "recording");
  btn.classList.toggle("processing", mode === "processing");
  btn.disabled = mode === "processing";
  btn.setAttribute("aria-label", mode === "recording" ? "Stop recording" : "Start recording");
  wave.mode = mode;
  $("micHint").textContent = mode === "recording" ? "Listening… tap again to stop"
    : mode === "processing" ? "Processing speech…" : "Tap the microphone and speak the visit details";
  renderStateBadge(mode);
}

/* ------------------------------------------------------------------ */
/* Session flow                                                         */
/* ------------------------------------------------------------------ */
async function startSession() {
  const r = await api("/api/sessions", { method: "POST", body: { language: state.lang } });
  state.pendingSaveId = null;
  state.savedVisitId = null;
  state.lastRecord = {};
  state.dismissedAlertKey = null;
  hideAlert();
  applyResponse(r);
  return r;
}

async function withBusy(fn) {
  if (state.busy) return;
  state.busy = true;
  document.body.classList.add("busy");
  renderButtons();
  try { return await fn(); }
  catch (e) { toast(e.message, "error"); if (e.status === 404) offerRestore(); }
  finally { state.busy = false; document.body.classList.remove("busy"); renderButtons(); }
}

async function sendUtterance(text, source = "typed") {
  text = (text || "").trim();
  if (!text) return;
  await withBusy(async () => {
    if (!state.session || ["confirmed", "cancelled"].includes(state.session.state) && !state.pendingSaveId) await startSession();
    wave.mode = "processing";
    const r = await api(`/api/sessions/${state.session.session_id}/utterance`, { method: "POST", body: { text, source } });
    wave.mode = "idle";
    applyResponse(r);
    if (r.action === "save") await saveVisit();
  });
  wave.mode = "idle";
}

async function confirmByButton() {
  await withBusy(async () => {
    const r = await api(`/api/sessions/${state.session.session_id}/confirm`, { method: "POST" });
    applyResponse(r);
    if (r.action === "save") await saveVisit();
  });
}

async function saveVisit() {
  if (!state.pendingSaveId) state.pendingSaveId = uuid();   // same ID on retry = no duplicate
  saveDraft();
  try {
    const r = await api(`/api/sessions/${state.session.session_id}/save`, { method: "POST", body: { client_request_id: state.pendingSaveId } });
    state.savedVisitId = r.visit_id;
    state.pendingSaveId = null;
    clearDraft();
    hideBanner();
    $("assistantText").textContent = r.speak_text;
    speak(r.speak_text);
    toast(r.duplicate ? "This record was already saved." : `Visit saved (#${r.visit_id}).`, "ok");
    renderRecordStatus();
    renderStateBadge();
    renderButtons();
    loadFollowups();
    loadHistory();
  } catch (e) {
    showBanner(`Saving failed: ${esc(e.message)} The confirmed record is kept on this device.`,
      [{ text: "Retry save", fn: () => withBusy(saveVisit) }]);
    throw e;
  }
}

function applyResponse(r) {
  const prevKey = alertKey(state.session?.danger);
  state.session = r;
  state.lang = r.language;
  $("language").value = r.language;
  if (r.saved_visit_id) state.savedVisitId = r.saved_visit_id;

  // 1) urgent alert FIRST
  if (r.alert_text) speak(r.alert_text, { urgent: true });
  if (r.speak_text) { $("assistantText").textContent = r.speak_text; speak(r.speak_text); }
  $("assistantText").lang = r.language.slice(0, 2);

  renderAlert(r.danger, r.alert_text, prevKey);
  renderTranscript();
  renderRecord();
  renderRecordStatus();
  renderStateBadge();
  renderButtons();
  saveDraft();
}

/* ------------------------------------------------------------------ */
/* Rendering                                                            */
/* ------------------------------------------------------------------ */
function renderStateBadge(micMode) {
  const b = $("stateBadge");
  const s = state.session;
  let text = "Ready", cls = "";
  if (micMode === "recording") { text = "Recording"; cls = "recording"; }
  else if (micMode === "processing") { text = "Processing"; cls = "processing"; }
  else if (state.savedVisitId) { text = "Saved"; cls = "saved"; }
  else if (s?.state === "awaiting_confirmation") { text = "Awaiting confirmation"; cls = "awaiting"; }
  else if (s?.state === "confirmed") { text = "Saving…"; cls = "processing"; }
  else if (s?.state === "cancelled") { text = "Cancelled"; }
  else if (s?.transcripts?.length) { text = "Collecting details"; cls = "processing"; }
  b.textContent = text;
  b.className = "badge " + cls;
}

function renderRecordStatus() {
  const p = $("recordStatus");
  const s = state.session;
  let text = "Draft", cls = "draft";
  if (s?.state === "cancelled") { text = "Cancelled - not saved"; cls = "cancelled"; }
  else if (state.savedVisitId) { text = "Confirmed & saved"; cls = "confirmed"; }
  else if (s?.state === "confirmed") { text = "Confirmed - saving"; cls = "confirmed"; }
  else if (s?.state === "awaiting_confirmation") { text = "Awaiting confirmation"; cls = "awaiting"; }
  if (s?.danger?.urgent_referral) { text = (state.savedVisitId ? "Saved · " : "") + "URGENT REFERRAL"; cls = "urgent"; }
  p.textContent = text;
  p.className = "pill " + cls;
}

function renderButtons() {
  const s = state.session;
  const canConfirm = s && s.state === "awaiting_confirmation" && !s.missing_fields.length && !s.unclear_fields.length;
  $("confirmBtn").disabled = state.busy || !canConfirm;
  $("typedForm").querySelector("button").disabled = state.busy;
}

function renderTranscript() {
  const list = $("transcriptList");
  const t = state.session?.transcripts || [];
  if (!t.length) { list.innerHTML = '<li class="empty">Nothing recorded yet.</li>'; return; }
  list.innerHTML = t.map((u) => {
    const src = u.source === "stt" ? "Gnani STT" : u.source === "replay" ? "restored" : "typed";
    return `<li><span class="src ${u.source === "stt" ? "stt" : ""}">${src}</span>${esc(u.text)}</li>`;
  }).join("");
  list.scrollTop = list.scrollHeight;
}

function renderRecord() {
  const s = state.session || { record: {}, missing_fields: [], unclear_fields: [], corrections: [], warnings: [], danger: { matches: [] } };
  const rec = s.record || {};
  const html = FIELD_ORDER.map((f) => {
    let v = rec[f];
    const missing = s.missing_fields.includes(f);
    const unclear = s.unclear_fields.includes(f);
    let cls = "field";
    let shown;
    if (unclear) { cls += " unclear"; shown = "Unclear — please repeat"; }
    else if (v === undefined || v === null || v === "" || (Array.isArray(v) && !v.length && f !== "vaccinations_due")) {
      cls += missing ? " missing" : " empty";
      shown = missing ? "Needed" : "—";
    } else if (f === "weight_kg") shown = `${v} kg`;
    else if (f === "next_visit_date") shown = fmtDate(v);
    else if (["beneficiary_id", "beneficiary_name", "notes"].includes(f)) shown = v;
    else shown = valueText(v);
    if (f === "notes") cls += " wide";
    if (JSON.stringify(state.lastRecord[f]) !== JSON.stringify(v) && v !== undefined) cls += " flash";
    return `<div class="${cls}"><dt>${esc(label(f))}</dt><dd>${esc(shown)}</dd></div>`;
  }).join("");
  $("recordFields").innerHTML = html;
  state.lastRecord = { ...rec };

  $("warnings").innerHTML = (s.warnings || []).map((w) => `<div class="warning">${esc(w)}</div>`).join("");

  const m = s.danger?.matches || [];
  const tagText = { danger: "Danger", clarify: "Clarify", negated: "Absent" };
  $("signsSummary").innerHTML = m.length
    ? m.map((x) => `<div class="sign-row"><span class="tag ${x.level}">${tagText[x.level]}</span>${esc(x.name)} <small style="color:var(--muted)">“${esc(x.phrase)}”</small></div>`).join("")
    : (s.transcripts?.length ? `<div class="sign-row"><span class="tag none">Info</span>No predefined danger sign detected — this is not a safety clearance</div>` : "");

  const c = s.corrections || [];
  $("corrCount").textContent = c.length;
  $("correctionList").innerHTML = c.map((x) =>
    `<li>${esc(label(x.field))}: <s>${esc(fmtVal(x.field, x.old))}</s> → <b>${esc(fmtVal(x.field, x.new))}</b><br><small style="color:var(--dim)">“${esc(x.utterance)}”</small></li>`).join("");
}
function fmtVal(f, v) {
  if (v === null || v === undefined || v === "") return "—";
  if (f === "next_visit_date") return fmtDate(v);
  if (f === "weight_kg") return v + " kg";
  return valueText(v);
}

function alertKey(d) { return d ? d.matches.filter((m) => m.level !== "negated").map((m) => m.rule_id + m.level).sort().join("|") : ""; }

function renderAlert(danger, alertText, prevKey) {
  const panel = $("alertPanel");
  if (!danger || danger.level === "none") { hideAlert(); return; }
  const key = alertKey(danger);
  if (key === state.dismissedAlertKey) return;
  const isDanger = danger.level === "danger";
  const items = danger.matches.filter((m) => m.level === (isDanger ? "danger" : "clarify"));
  const instruction = isDanger
    ? (alertText || "Refer to the PHC immediately.")
    : "Ask the worker to clarify. Do not treat this as safe until confirmed. Flagged for supervisor review.";
  panel.className = "alert " + (isDanger ? "danger" : "clarify");
  panel.innerHTML = `
    <div class="alert-icon"><svg><use href="#i-alert"/></svg></div>
    <div>
      <h2>${isDanger ? "DANGER SIGN — REFER TO PHC IMMEDIATELY" : "Possible danger sign — clarification needed"}</h2>
      <p class="alert-instruction">${esc(instruction)}</p>
      <ul>${items.map((m) => `<li><strong>${esc(m.name)}</strong> — heard: <q>${esc(m.phrase)}</q><small>${esc(m.note || m.reason)}</small></li>`).join("")}</ul>
    </div>
    <button class="close" aria-label="Hide alert (the record stays flagged)" title="Hide alert (the record stays flagged)"><svg><use href="#i-x"/></svg></button>`;
  panel.querySelector(".close").onclick = () => { state.dismissedAlertKey = key; hideAlert(); };
  if (key !== prevKey) panel.scrollIntoView({ behavior: "smooth", block: "start" });
}
function hideAlert() { $("alertPanel").className = "alert hidden"; $("alertPanel").innerHTML = ""; }

function showBanner(html, buttons = []) {
  const b = $("banner");
  b.innerHTML = `<span>${html}</span>`;
  buttons.forEach(({ text, fn, ghost }) => {
    const btn = document.createElement("button");
    btn.className = "btn small " + (ghost ? "ghost" : "primary");
    btn.textContent = text;
    btn.onclick = fn;
    b.appendChild(btn);
  });
  b.classList.remove("hidden");
}
function hideBanner() { $("banner").classList.add("hidden"); }

/* ------------------------------------------------------------------ */
/* Follow-ups and history                                               */
/* ------------------------------------------------------------------ */
async function loadFollowups() {
  try {
    const items = await api("/api/followups");
    $("fuCount").textContent = items.length;
    const today = todayIso();
    $("followupList").innerHTML = items.length ? items.map((f) => `
      <li data-id="${f.id}">
        <span class="prio ${esc(f.priority)}"></span>
        <div class="main">
          <div class="title">${esc(f.beneficiary_id)} · ${esc(f.beneficiary_name || "")}</div>
          <div class="sub">${esc(f.reason)}</div>
        </div>
        <div class="date ${f.due_date < today ? "overdue" : ""}">${f.due_date < today ? "Overdue<br>" : ""}${esc(fmtDate(f.due_date))}</div>
        <button class="btn small ghost done-btn" title="Mark done" aria-label="Mark follow-up done"><svg><use href="#i-check"/></svg></button>
      </li>`).join("") : '<li class="empty">No open follow-ups.</li>';
    $("followupList").querySelectorAll(".done-btn").forEach((btn) => {
      btn.onclick = async () => {
        const id = btn.closest("li").dataset.id;
        try { await api(`/api/followups/${id}/complete`, { method: "POST" }); loadFollowups(); toast("Follow-up marked done.", "ok"); }
        catch (e) { toast(e.message, "error"); }
      };
    });
  } catch (e) {
    $("followupList").innerHTML = `<li class="empty">Could not load follow-ups: ${esc(e.message)}</li>`;
  }
}

let searchTimer = null;
async function loadHistory() {
  const q = $("searchInput").value.trim();
  try {
    const items = await api("/api/visits?limit=50" + (q ? "&search=" + encodeURIComponent(q) : ""));
    $("historyList").innerHTML = items.length ? items.map((v) => `
      <li class="clickable" data-id="${v.id}" tabindex="0">
        <span class="prio ${v.urgent_referral ? "urgent" : v.needs_human_review ? "high" : ""}"></span>
        <div class="main">
          <div class="title">${esc(v.beneficiary_id)} · ${esc(v.beneficiary_name || "")}</div>
          <div class="sub">${esc(valueText(v.visit_type))}${v.urgent_referral ? ' · <span class="overdue">Urgent referral</span>' : v.needs_human_review ? " · Needs review" : ""}</div>
        </div>
        <div class="date">${esc(fmtDate(v.confirmed_at))}</div>
      </li>`).join("") : `<li class="empty">${q ? "No visits match your search." : "No saved visits yet."}</li>`;
    $("historyList").querySelectorAll("li[data-id]").forEach((li) => {
      li.onclick = () => openVisit(li.dataset.id);
      li.onkeydown = (e) => { if (e.key === "Enter") openVisit(li.dataset.id); };
    });
  } catch (e) {
    $("historyList").innerHTML = `<li class="empty">Could not load visits: ${esc(e.message)}</li>`;
  }
}

async function openVisit(id) {
  try {
    const v = await api(`/api/visits/${id}`);
    const d = $("visitDialog");
    const rows = FIELD_ORDER.map((f) => {
      const val = v[f];
      if (val === null || val === undefined || val === "" || (Array.isArray(val) && !val.length)) return "";
      return `<div class="field ${f === "notes" ? "wide" : ""}"><dt>${esc(label(f))}</dt><dd>${esc(fmtVal(f, val))}</dd></div>`;
    }).join("");
    d.innerHTML = `
      <div class="d-head"><h2>Visit #${v.id} · ${esc(v.beneficiary_id)}</h2><button class="btn small ghost" id="closeDlg" aria-label="Close"><svg><use href="#i-x"/></svg></button></div>
      <div class="d-body">
        <p><span class="pill ${v.urgent_referral ? "urgent" : "confirmed"}">${v.urgent_referral ? "URGENT REFERRAL" : "Confirmed"}</span>
           ${v.needs_human_review ? '<span class="pill awaiting">Needs human review</span>' : ""}
           <small style="color:var(--muted)">Confirmed ${esc(fmtDate(v.confirmed_at))} · ${esc(v.language)}</small></p>
        <dl class="fields">${rows}</dl>
        <h3>Danger-sign checks</h3>
        <div class="signs">${v.alerts.length ? v.alerts.map((a) => `<div class="sign-row"><span class="tag ${a.level}">${a.level}</span>${esc(a.sign_name)} — “${esc(a.detected_phrase)}”<br><small style="color:var(--muted)">${esc(a.reason)}</small></div>`).join("") : '<div class="sign-row"><span class="tag none">Info</span>No predefined danger sign detected</div>'}</div>
        <h3>Transcript</h3>
        <ol class="transcript-list">${v.transcript.map((t) => `<li>${esc(t.text)}</li>`).join("")}</ol>
        <h3>Corrections</h3>
        <div class="corrections"><ul>${v.correction_history.length ? v.correction_history.map((c) => `<li>${esc(label(c.field))}: <s>${esc(fmtVal(c.field, c.old))}</s> → <b>${esc(fmtVal(c.field, c.new))}</b></li>`).join("") : "<li>None</li>"}</ul></div>
      </div>`;
    d.querySelector("#closeDlg").onclick = () => d.close();
    d.showModal();
  } catch (e) { toast(e.message, "error"); }
}

/* ------------------------------------------------------------------ */
/* Draft restore                                                        */
/* ------------------------------------------------------------------ */
function offerRestore() {
  const draft = loadDraft();
  if (!draft || !draft.utterances?.length) return;
  showBanner(`An unsaved visit draft was found on this device (${draft.utterances.length} statement${draft.utterances.length > 1 ? "s" : ""}). The server no longer has it.`, [
    { text: "Restore draft", fn: restoreDraft },
    { text: "Discard", ghost: true, fn: () => { clearDraft(); hideBanner(); startSession().catch((e) => toast(e.message, "error")); } },
  ]);
}

async function restoreDraft() {
  const draft = loadDraft();
  if (!draft) return;
  hideBanner();
  await withBusy(async () => {
    state.lang = draft.language;
    await startSession();
    for (const text of draft.utterances) {
      const r = await api(`/api/sessions/${state.session.session_id}/utterance`, { method: "POST", body: { text, source: "replay" } });
      applyResponse(r);
      if (r.action === "save") { state.pendingSaveId = draft.pendingSaveId || null; await saveVisit(); }
    }
    toast("Draft restored. Please review before confirming.", "ok");
  });
}

async function resumeOrStart() {
  const draft = loadDraft();
  if (draft?.session_id) {
    try {
      const r = await api(`/api/sessions/${draft.session_id}`);
      state.pendingSaveId = draft.pendingSaveId || null;
      applyResponse(r);
      if (r.state === "confirmed" && !r.saved_visit_id && state.pendingSaveId) {
        showBanner("A confirmed visit was not saved yet.", [{ text: "Save now", fn: () => withBusy(saveVisit) }]);
      }
      return;
    } catch (e) {
      if (e.status === 404) { await startSession(); offerRestore(); return; }
      throw e;
    }
  }
  await startSession();
}

/* ------------------------------------------------------------------ */
/* Init                                                                 */
/* ------------------------------------------------------------------ */
async function init() {
  requestAnimationFrame(drawWave);
  setStatus("st-mic", "", "Microphone: not used yet");

  $("exampleChips").innerHTML = EXAMPLES.map((e, i) =>
    `<button type="button" class="chip ${e.danger ? "danger-chip" : ""}" data-i="${i}">${esc(e.label)}</button>`).join("");
  $("exampleChips").querySelectorAll(".chip").forEach((c) => {
    c.onclick = () => { $("typedInput").value = EXAMPLES[c.dataset.i].text; $("typedInput").focus(); };
  });

  $("micBtn").onclick = () => toggleMic().catch((e) => toast(e.message, "error"));
  $("typedForm").onsubmit = (e) => {
    e.preventDefault();
    const text = $("typedInput").value;
    $("typedInput").value = "";
    sendUtterance(text, "typed");
  };
  $("confirmBtn").onclick = confirmByButton;
  $("newBtn").onclick = async () => {
    const s = state.session;
    if (s && s.transcripts?.length && !state.savedVisitId && s.state !== "cancelled") {
      if (!confirm("Discard the current unsaved visit and start a new one?")) return;
      try { await api(`/api/sessions/${s.session_id}/cancel`, { method: "POST" }); } catch { /* ignore */ }
    }
    clearDraft();
    hideBanner();
    $("typedInput").value = "";
    await withBusy(startSession);
  };
  $("language").onchange = async (e) => {
    state.lang = e.target.value;
    const s = state.session;
    await withBusy(async () => {
      if (s && s.transcripts?.length && !["confirmed", "cancelled"].includes(s.state)) {
        applyResponse(await api(`/api/sessions/${s.session_id}/language`, { method: "POST", body: { language: state.lang } }));
      } else {
        await startSession();
      }
    });
  };
  $("searchInput").oninput = () => { clearTimeout(searchTimer); searchTimer = setTimeout(loadHistory, 250); };
  window.addEventListener("online", () => { toast("Back online.", "ok"); refreshStatus(); });
  window.addEventListener("offline", () => toast("You are offline. Your draft is kept on this device.", "warn"));

  try {
    state.languages = await api("/api/languages");
    $("language").innerHTML = state.languages.map((l) =>
      `<option value="${esc(l.code)}">${esc(l.native)}${l.gnani_verified ? "" : " (unverified)"}</option>`).join("");
    const draft = loadDraft();
    if (draft?.language) state.lang = draft.language;
    $("language").value = state.lang;
  } catch (e) {
    toast("Could not load languages: " + e.message, "error");
  }
  await refreshStatus();
  setInterval(refreshStatus, 30000);
  try { await resumeOrStart(); } catch (e) { toast(e.message, "error"); }
  loadFollowups();
  loadHistory();
}

document.addEventListener("DOMContentLoaded", init);
