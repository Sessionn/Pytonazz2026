const guildId = String(document.body.dataset.guildId || "").trim();
const stateUrl = `/dj-console/state?guild_id=${guildId}`;
const eventsUrl = `/dj-console/events?guild_id=${guildId}`;

const els = {
  voice: document.getElementById("voice-channel"),
  playback: document.getElementById("playback-state"),
  playbackIndicator: document.getElementById("playback-indicator"),
  effectSummary: document.getElementById("effect-summary"),
  toneSummary: document.getElementById("tone-summary"),
  title: document.getElementById("track-title"),
  artist: document.getElementById("track-artist"),
  requester: document.getElementById("track-requester"),
  cover: document.getElementById("cover-art"),
  fallback: document.getElementById("cover-fallback"),
  position: document.getElementById("position-label"),
  duration: document.getElementById("duration-label"),
  progress: document.getElementById("progress-fill"),
  volume: document.getElementById("volume-slider"),
  volumeHandle: document.getElementById("volume-slider-handle"),
  volumeValue: document.getElementById("volume-value"),
  filterSelect: document.getElementById("filter-select"),
  queue: document.getElementById("queue-list"),
  eqLow: document.getElementById("eq-low"),
  eqLowHandle: document.getElementById("eq-low-handle"),
  eqMid: document.getElementById("eq-mid"),
  eqMidHandle: document.getElementById("eq-mid-handle"),
  eqHigh: document.getElementById("eq-high"),
  eqHighHandle: document.getElementById("eq-high-handle"),
  fxHighpass: document.getElementById("fx-highpass"),
  fxLowpass: document.getElementById("fx-lowpass"),
  fxHighpassKnob: document.getElementById("fx-highpass-knob"),
  fxLowpassKnob: document.getElementById("fx-lowpass-knob"),
  eqLowValue: document.getElementById("eq-low-value"),
  eqMidValue: document.getElementById("eq-mid-value"),
  eqHighValue: document.getElementById("eq-high-value"),
  fxHighpassValue: document.getElementById("fx-highpass-value"),
  fxLowpassValue: document.getElementById("fx-lowpass-value"),
  platterWrap: document.getElementById("platter-wrap"),
  platterDisc: document.getElementById("platter-disc"),
};

let state = null;
let refreshTimer = null;
let lastErrorCode = "";
let queueKeys = new Set();
let scratchRotation = 0;
let scratchActive = false;
let scratchStartAngle = 0;
let scratchBaseRotation = 0;
let platterWasSpinning = false;
let scratchLastAngle = 0;
let scratchLastMoveAt = 0;
let scratchAudio = null;
let lastStateSyncAt = performance.now();
let sendEqTimer = null;
let eqAnimationFrame = 0;
const lastTapAt = new WeakMap();
const draggingInputs = new Set();

const EQ_SCENES = {
  flat: { low: 0, mid: 0, high: 0 },
  club: { low: 5, mid: -1.5, high: 4 },
  warm: { low: 3.5, mid: 1.5, high: -2 },
  air: { low: -1, mid: 0.5, high: 5.5 },
  "kill-low": { low: -12, mid: 0, high: 0 },
  "kill-high": { low: 0, mid: 0, high: -12 },
};

const QUICK_FX = {
  off: { filter_name: "off", eq: EQ_SCENES.flat },
  nightcore: { filter_name: "nightcore", eq: { low: -0.5, mid: 1.5, high: 6 } },
  vaporwave: { filter_name: "vaporwave", eq: { low: 3, mid: -0.5, high: -3.5 } },
  "8d": { filter_name: "8d", eq: { low: 0, mid: 0.5, high: 1.5 } },
  bassboost: { filter_name: "bassboost", eq: { low: 7, mid: -1, high: 1 } },
  radio: { filter_name: "radio", eq: { low: -6, mid: 2, high: -2.5 } },
};

function formatTime(seconds) {
  const total = Math.max(0, Math.floor(Number(seconds || 0)));
  const m = Math.floor(total / 60);
  const s = total % 60;
  return `${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}

function makeContinuousSender(action, buildPayload, minIntervalMs = 28) {
  let timer = null;
  let dirty = false;
  let lastSentAt = 0;

  function schedule() {
    dirty = true;
    if (timer !== null) {
      return;
    }
    const wait = Math.max(0, minIntervalMs - (performance.now() - lastSentAt));
    timer = window.setTimeout(() => {
      timer = null;
      if (!dirty) {
        return;
      }
      dirty = false;
      lastSentAt = performance.now();
      void postAction(action, buildPayload());
      if (dirty) {
        schedule();
      }
    }, wait);
  }

  return schedule;
}

function setActiveButton(selector, predicate) {
  document.querySelectorAll(selector).forEach((button) => {
    button.classList.toggle("is-active", predicate(button));
  });
}

function summarizeTone(eq) {
  const values = [eq.low || 0, eq.mid || 0, eq.high || 0];
  const peak = Math.max(...values.map((value) => Math.abs(value)));
  if (peak < 0.25) return "flat";
  const boosted = values.filter((value) => value > 1.5).length;
  const cut = values.filter((value) => value < -1.5).length;
  if (boosted >= 2) return "hyped";
  if (cut >= 2) return "cut";
  return "custom";
}

function eqMatches(a, b) {
  return Number(a.low || 0) === Number(b.low || 0) &&
    Number(a.mid || 0) === Number(b.mid || 0) &&
    Number(a.high || 0) === Number(b.high || 0);
}

function setPlaybackVisual(stateName) {
  els.playback.classList.remove("state-live", "state-paused", "state-offline");
  els.playbackIndicator.classList.remove("is-live", "is-paused", "is-offline");
  if (stateName === "live") {
    els.playback.classList.add("state-live");
    els.playbackIndicator.classList.add("is-live");
    return;
  }
  if (stateName === "paused") {
    els.playback.classList.add("state-paused");
    els.playbackIndicator.classList.add("is-paused");
    return;
  }
  els.playback.classList.add("state-offline");
  els.playbackIndicator.classList.add("is-offline");
}

function renderQueue(items) {
  els.queue.innerHTML = "";
  if (!items || !items.length) {
    const li = document.createElement("li");
    li.textContent = "Coda vuota.";
    els.queue.appendChild(li);
    queueKeys = new Set();
    return;
  }
  const nextKeys = new Set();
  items.slice(0, 20).forEach((track, index) => {
    const li = document.createElement("li");
    const key = `${track.webpage_url || track.spotify_url || track.title || "track"}-${index}`;
    nextKeys.add(key);
    li.className = "queue-item";
    if (!queueKeys.has(key)) {
      li.classList.add("is-new");
    }
    li.innerHTML = `
      <div class="queue-art">
        ${track.thumbnail ? `<img src="${track.thumbnail}" alt="">` : `<div class="queue-art-fallback">NO ART</div>`}
      </div>
      <div class="queue-copy">
        <strong>${index + 1}. ${track.title}</strong>
        <span>${track.artist || "Sconosciuto"}</span>
      </div>
    `;
    els.queue.appendChild(li);
  });
  queueKeys = nextKeys;
}

function renderError(code) {
  lastErrorCode = code || "unknown_error";
  els.voice.textContent = "-";
  els.playback.textContent = "Access denied";
  setPlaybackVisual("offline");
  els.effectSummary.textContent = lastErrorCode;
  els.toneSummary.textContent = "-";
  els.title.textContent = "Console DJ non disponibile";
  els.artist.textContent = lastErrorCode;
  els.requester.textContent = "Controlla il log backend per i dettagli.";
  els.position.textContent = "00:00";
  els.duration.textContent = "00:00";
  els.progress.style.width = "0%";
  renderQueue([]);
  console.warn("DJ console access/state error", { guildId, error: lastErrorCode });
}

function getDisplayedPosition() {
  if (!state) return 0;
  const base = Number(state.position || 0);
  if (!state.connected || state.is_paused || !state.current_track) {
    return base;
  }
  const elapsed = Math.max(0, (performance.now() - lastStateSyncAt) / 1000);
  const duration = Number(state.duration || 0);
  const next = base + elapsed;
  if (duration > 0) {
    return Math.min(duration, next);
  }
  return next;
}

function renderPlaybackClock() {
  if (!state) {
    els.position.textContent = "00:00";
    els.duration.textContent = "00:00";
    els.progress.style.width = "0%";
    return;
  }
  const position = getDisplayedPosition();
  const duration = Number(state.duration || 0);
  els.position.textContent = formatTime(position);
  els.duration.textContent = formatTime(duration);
  const progress = duration > 0 ? Math.min(100, (position / duration) * 100) : 0;
  els.progress.style.width = `${progress}%`;
}

function tickPlaybackClock() {
  renderPlaybackClock();
  window.requestAnimationFrame(tickPlaybackClock);
}

function clamp(value, min, max) {
  return Math.max(min, Math.min(max, value));
}

function getRangeMeta(input) {
  return {
    min: Number(input.min || 0),
    max: Number(input.max || 1),
    step: Number(input.step || 1),
  };
}

function quantize(value, step, min, max) {
  const safeStep = step > 0 ? step : 1;
  const steps = Math.round((value - min) / safeStep);
  return clamp(min + (steps * safeStep), min, max);
}

function setControlValue(input, nextValue) {
  const { min, max, step } = getRangeMeta(input);
  const normalized = quantize(Number(nextValue), step, min, max);
  input.value = String(normalized);
  return normalized;
}

function getControlValue(input) {
  return Number(input.value || 0);
}

function getDefaultValue(input) {
  const fallback = input.dataset.default ?? input.defaultValue ?? input.min ?? "0";
  return setControlValue(input, Number(fallback));
}

function getControlRatio(input) {
  const { min, max } = getRangeMeta(input);
  const span = Math.max(1e-6, max - min);
  return clamp((getControlValue(input) - min) / span, 0, 1);
}

function setFaderHandlePosition(handle, input) {
  if (!handle || !input) return;
  handle.style.setProperty("--fader-ratio", `${getControlRatio(input)}`);
}

function updateVolumeReadout() {
  els.volumeValue.textContent = `${Math.round(getControlValue(els.volume) * 100)}%`;
  setFaderHandlePosition(els.volumeHandle, els.volume);
}

function updateEqValueLabels() {
  els.eqLowValue.textContent = `${getControlValue(els.eqLow).toFixed(1)} dB`;
  els.eqMidValue.textContent = `${getControlValue(els.eqMid).toFixed(1)} dB`;
  els.eqHighValue.textContent = `${getControlValue(els.eqHigh).toFixed(1)} dB`;
  setFaderHandlePosition(els.eqLowHandle, els.eqLow);
  setFaderHandlePosition(els.eqMidHandle, els.eqMid);
  setFaderHandlePosition(els.eqHighHandle, els.eqHigh);
}

function cancelEqAnimation() {
  if (eqAnimationFrame) {
    window.cancelAnimationFrame(eqAnimationFrame);
    eqAnimationFrame = 0;
  }
}

function formatHighpass(value) {
  const hz = Number(value || 0);
  if (hz <= 0) return "off";
  if (hz >= 1000) return `${(hz / 1000).toFixed(1)} kHz`;
  return `${Math.round(hz)} Hz`;
}

function formatLowpass(value) {
  const hz = Number(value || 0);
  if (hz >= 19900) return "off";
  if (hz >= 1000) return `${(hz / 1000).toFixed(1)} kHz`;
  return `${Math.round(hz)} Hz`;
}

function setKnobAngle(knob, input) {
  if (!knob || !input) return;
  const angle = -135 + (getControlRatio(input) * 270);
  knob.style.setProperty("--knob-angle", `${angle}deg`);
}

function updateToneValueLabels() {
  els.fxHighpassValue.textContent = formatHighpass(getControlValue(els.fxHighpass));
  els.fxLowpassValue.textContent = formatLowpass(getControlValue(els.fxLowpass));
  setKnobAngle(els.fxHighpassKnob, els.fxHighpass);
  setKnobAngle(els.fxLowpassKnob, els.fxLowpass);
}

function syncPlatterMotion(next) {
  const shouldSpin = Boolean(next.connected && next.current_track && !next.is_paused && !scratchActive);
  if (platterWasSpinning && !shouldSpin) {
    scratchRotation = getRenderedRotationDegrees();
  }
  els.platterDisc.style.setProperty("--scratch-rotate", `${scratchRotation}deg`);
  els.platterDisc.classList.toggle("is-spinning", shouldSpin);
  els.platterDisc.classList.toggle("is-scratching", scratchActive);
  platterWasSpinning = shouldSpin;
}

function getRenderedRotationDegrees() {
  const transform = window.getComputedStyle(els.platterDisc).transform;
  if (!transform || transform === "none") {
    return scratchRotation;
  }
  const match = transform.match(/matrix\(([^)]+)\)/);
  if (!match) {
    return scratchRotation;
  }
  const values = match[1].split(",").map((value) => Number(value.trim()));
  if (values.length < 2 || Number.isNaN(values[0]) || Number.isNaN(values[1])) {
    return scratchRotation;
  }
  return Math.atan2(values[1], values[0]) * (180 / Math.PI);
}

function getPointerAngle(event) {
  const rect = els.platterWrap.getBoundingClientRect();
  const cx = rect.left + rect.width / 2;
  const cy = rect.top + rect.height / 2;
  return Math.atan2(event.clientY - cy, event.clientX - cx) * (180 / Math.PI);
}

function normalizeAngleDelta(delta) {
  let next = Number(delta || 0);
  while (next > 180) next -= 360;
  while (next < -180) next += 360;
  return next;
}

function ensureScratchAudio() {
  const AudioContextCtor = window.AudioContext || window.webkitAudioContext;
  if (scratchAudio || typeof AudioContextCtor !== "function") {
    return scratchAudio;
  }

  const context = new AudioContextCtor();
  const buffer = context.createBuffer(1, context.sampleRate * 2, context.sampleRate);
  const channel = buffer.getChannelData(0);
  for (let index = 0; index < channel.length; index += 1) {
    channel[index] = (Math.random() * 2) - 1;
  }

  const source = context.createBufferSource();
  source.buffer = buffer;
  source.loop = true;

  const bandpass = context.createBiquadFilter();
  bandpass.type = "bandpass";
  bandpass.frequency.value = 1400;
  bandpass.Q.value = 1.2;

  const highpass = context.createBiquadFilter();
  highpass.type = "highpass";
  highpass.frequency.value = 170;

  const drive = context.createGain();
  drive.gain.value = 0.0001;

  const master = context.createGain();
  master.gain.value = 0.18;

  const panner = context.createStereoPanner();
  panner.pan.value = 0;

  source.connect(bandpass);
  bandpass.connect(highpass);
  highpass.connect(panner);
  panner.connect(drive);
  drive.connect(master);
  master.connect(context.destination);
  source.start();

  scratchAudio = { context, source, bandpass, highpass, panner, drive };
  return scratchAudio;
}

async function armScratchAudio() {
  const rig = ensureScratchAudio();
  if (!rig) return null;
  if (rig.context.state === "suspended") {
    try {
      await rig.context.resume();
    } catch {
      return null;
    }
  }
  return rig;
}

function updateScratchAudio(deltaAngle, deltaTimeMs) {
  if (!scratchAudio) return;
  const velocity = Math.abs(deltaAngle) / Math.max(4, deltaTimeMs);
  const intensity = clamp(velocity / 1.35, 0, 1);
  const now = scratchAudio.context.currentTime;

  scratchAudio.bandpass.frequency.setTargetAtTime(700 + (intensity * 5200), now, 0.012);
  scratchAudio.bandpass.Q.setTargetAtTime(0.9 + (intensity * 8.5), now, 0.016);
  scratchAudio.highpass.frequency.setTargetAtTime(130 + (intensity * 1450), now, 0.016);
  scratchAudio.panner.pan.setTargetAtTime(clamp(deltaAngle / 22, -0.92, 0.92), now, 0.01);
  scratchAudio.source.playbackRate.setTargetAtTime(0.86 + (intensity * 0.88), now, 0.012);
  scratchAudio.drive.gain.setTargetAtTime(0.0001 + (Math.pow(intensity, 1.2) * 0.22), now, 0.01);
}

function stopScratchAudio() {
  if (!scratchAudio) return;
  const now = scratchAudio.context.currentTime;
  scratchAudio.drive.gain.setTargetAtTime(0.0001, now, 0.018);
  scratchAudio.panner.pan.setTargetAtTime(0, now, 0.025);
}

if (!/^\d+$/.test(guildId)) {
  renderError("invalid_guild");
  throw new Error(`Invalid guild id: ${guildId}`);
}

function render(next) {
  lastErrorCode = "";
  state = next;
  lastStateSyncAt = performance.now();
  const current = next.current_track;
  els.voice.textContent = next.voice_channel_name || "-";
  els.playback.textContent = next.connected ? (next.is_paused ? "Paused" : "Live") : "Disconnected";
  setPlaybackVisual(next.connected ? (next.is_paused ? "paused" : "live") : "offline");
  els.effectSummary.textContent = next.filter_name || "off";
  els.title.textContent = current ? current.title : "Nessuna traccia";
  els.artist.textContent = current ? (current.artist || "Artista sconosciuto") : "-";
  els.requester.textContent = current ? `Requested by ${current.requester || current.requester_id}` : "-";
  renderPlaybackClock();
  els.filterSelect.value = next.filter_name || "off";
  setActiveButton("[data-filter-preset]", (button) => {
    const preset = QUICK_FX[button.dataset.filterPreset];
    return preset &&
      preset.filter_name === (next.filter_name || "off") &&
      eqMatches(preset.eq, next.eq || EQ_SCENES.flat);
  });
  renderQueue(next.queue || []);

  const eq = next.eq || { low: 0, mid: 0, high: 0 };
  const toneFilters = next.tone_filters || { highpass_hz: 0, lowpass_hz: 20000 };
  els.toneSummary.textContent = summarizeTone(eq);

  if (!draggingInputs.has(els.volume)) {
    setControlValue(els.volume, next.volume ?? 0.5);
    updateVolumeReadout();
  }
  if (!draggingInputs.has(els.eqLow)) {
    setControlValue(els.eqLow, eq.low ?? 0);
  }
  if (!draggingInputs.has(els.eqMid)) {
    setControlValue(els.eqMid, eq.mid ?? 0);
  }
  if (!draggingInputs.has(els.eqHigh)) {
    setControlValue(els.eqHigh, eq.high ?? 0);
  }
  if (!draggingInputs.has(els.fxHighpass)) {
    setControlValue(els.fxHighpass, toneFilters.highpass_hz ?? 0);
  }
  if (!draggingInputs.has(els.fxLowpass)) {
    setControlValue(els.fxLowpass, toneFilters.lowpass_hz ?? 20000);
  }

  updateEqValueLabels();
  updateToneValueLabels();

  setActiveButton("[data-eq-scene]", (button) => {
    const scene = EQ_SCENES[button.dataset.eqScene];
    return scene &&
      Number(scene.low) === Number(eq.low || 0) &&
      Number(scene.mid) === Number(eq.mid || 0) &&
      Number(scene.high) === Number(eq.high || 0);
  });

  if (current && current.thumbnail) {
    els.cover.src = current.thumbnail;
    els.cover.style.display = "block";
    els.fallback.style.display = "none";
  } else {
    els.cover.removeAttribute("src");
    els.cover.style.display = "none";
    els.fallback.style.display = "grid";
  }
  syncPlatterMotion(next);
}

async function postAction(action, payload = {}) {
  const response = await fetch("/dj-console/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ guild_id: guildId, action, ...payload }),
  });
  if (response.status === 401) {
    console.info("DJ action requires auth again", { guildId, action });
    window.location.href = `/dj-console?guild_id=${guildId}`;
    return;
  }
  if (!response.ok) {
    try {
      const body = await response.json();
      console.warn("DJ action HTTP error", { guildId, action, status: response.status, body });
      renderError(body.error || "action_failed");
    } catch {
      console.warn("DJ action HTTP error", { guildId, action, status: response.status });
      renderError("action_failed");
    }
    return;
  }
  const result = await response.json();
  if (!result.ok) {
    console.warn("DJ action failed", result);
  }
}

const liveVolumeSender = makeContinuousSender("set_volume", () => ({
  volume: getControlValue(els.volume),
}));

const liveToneSender = makeContinuousSender("set_tone_filters", () => ({
  tone_filters: {
    highpass_hz: getControlValue(els.fxHighpass),
    lowpass_hz: getControlValue(els.fxLowpass),
  },
}));

const liveEqSender = makeContinuousSender("set_eq", () => ({
  eq: {
    low: getControlValue(els.eqLow),
    mid: getControlValue(els.eqMid),
    high: getControlValue(els.eqHigh),
  },
}));

function sendEqNow() {
  clearTimeout(sendEqTimer);
  sendEqTimer = null;
  return postAction("set_eq", {
    eq: {
      low: getControlValue(els.eqLow),
      mid: getControlValue(els.eqMid),
      high: getControlValue(els.eqHigh),
    },
  });
}

function resetEqBand(input) {
  setControlValue(input, getDefaultValue(input));
  updateEqValueLabels();
  cancelEqAnimation();
  liveEqSender();
}

function resetToneBand(input) {
  setControlValue(input, getDefaultValue(input));
  updateToneValueLabels();
  liveToneSender();
}

function resetVolume() {
  setControlValue(els.volume, getDefaultValue(els.volume));
  updateVolumeReadout();
  liveVolumeSender();
}

function easeOutQuart(t) {
  return 1 - Math.pow(1 - t, 4);
}

function animateEqTo(targetEq, durationMs = 320) {
  cancelEqAnimation();
  const start = performance.now();
  const startLow = getControlValue(els.eqLow);
  const startMid = getControlValue(els.eqMid);
  const startHigh = getControlValue(els.eqHigh);

  function step(now) {
    const t = Math.min(1, (now - start) / durationMs);
    const eased = easeOutQuart(t);
    setControlValue(els.eqLow, startLow + ((Number(targetEq.low) - startLow) * eased));
    setControlValue(els.eqMid, startMid + ((Number(targetEq.mid) - startMid) * eased));
    setControlValue(els.eqHigh, startHigh + ((Number(targetEq.high) - startHigh) * eased));
    updateEqValueLabels();
    liveEqSender();
    if (t < 1) {
      eqAnimationFrame = window.requestAnimationFrame(step);
      return;
    }
    eqAnimationFrame = 0;
    void sendEqNow();
  }

  eqAnimationFrame = window.requestAnimationFrame(step);
}

function setupVerticalDrag(handle, input, { onChange, onCommit, onReset }) {
  let pointerId = null;
  let startY = 0;
  let startValue = 0;

  handle.addEventListener("pointerdown", (event) => {
    pointerId = event.pointerId;
    startY = event.clientY;
    startValue = getControlValue(input);
    draggingInputs.add(input);
    handle.setPointerCapture(event.pointerId);
    event.preventDefault();
  });

  handle.addEventListener("pointermove", (event) => {
    if (pointerId !== event.pointerId) return;
    const slot = handle.closest(".fader-slot");
    const travel = Math.max(160, (slot?.clientHeight || 240) - 24);
    const { min, max } = getRangeMeta(input);
    const nextValue = startValue + (((startY - event.clientY) / travel) * (max - min));
    setControlValue(input, nextValue);
    onChange();
  });

  function finish(event) {
    if (pointerId !== event.pointerId) return;
    if (handle.hasPointerCapture(event.pointerId)) {
      handle.releasePointerCapture(event.pointerId);
    }
    draggingInputs.delete(input);
    pointerId = null;
    onCommit();
  }

  handle.addEventListener("pointerup", finish);
  handle.addEventListener("pointercancel", finish);
  handle.addEventListener("dblclick", (event) => {
    event.preventDefault();
    onReset();
  });
}

function setupKnobDrag(knob, input, { onChange, onCommit, onReset }) {
  let pointerId = null;
  let startY = 0;
  let startValue = 0;

  knob.addEventListener("pointerdown", (event) => {
    pointerId = event.pointerId;
    startY = event.clientY;
    startValue = getControlValue(input);
    draggingInputs.add(input);
    knob.setPointerCapture(event.pointerId);
    event.preventDefault();
  });

  knob.addEventListener("pointermove", (event) => {
    if (pointerId !== event.pointerId) return;
    const { min, max } = getRangeMeta(input);
    const travel = 180;
    const nextValue = startValue + (((startY - event.clientY) / travel) * (max - min));
    setControlValue(input, nextValue);
    onChange();
  });

  function finish(event) {
    if (pointerId !== event.pointerId) return;
    if (knob.hasPointerCapture(event.pointerId)) {
      knob.releasePointerCapture(event.pointerId);
    }
    draggingInputs.delete(input);
    pointerId = null;
    onCommit();
  }

  knob.addEventListener("pointerup", finish);
  knob.addEventListener("pointercancel", finish);
  knob.addEventListener("dblclick", (event) => {
    event.preventDefault();
    onReset();
  });
}

async function bootstrap() {
  const response = await fetch(stateUrl);
  if (response.status === 401) {
    console.info("DJ state requires auth again", { guildId });
    window.location.href = `/dj-console?guild_id=${guildId}`;
    return;
  }
  if (!response.ok) {
    try {
      const body = await response.json();
      renderError(body.error || "state_failed");
    } catch {
      renderError("state_failed");
    }
    return;
  }
  const payload = await response.json();
  console.debug("DJ state loaded", {
    guildId,
    connected: payload.connected,
    title: payload.current_track?.title || null,
  });
  render(payload);
}

els.platterWrap.addEventListener("pointerdown", (event) => {
  scratchRotation = getRenderedRotationDegrees();
  scratchActive = true;
  scratchBaseRotation = scratchRotation;
  scratchStartAngle = getPointerAngle(event);
  scratchLastAngle = scratchStartAngle;
  scratchLastMoveAt = performance.now();
  els.platterWrap.setPointerCapture(event.pointerId);
  void armScratchAudio();
  syncPlatterMotion(state || { connected: false });
});

els.platterWrap.addEventListener("pointermove", (event) => {
  if (!scratchActive) return;
  const pointerAngle = getPointerAngle(event);
  const now = performance.now();
  const deltaAngle = normalizeAngleDelta(pointerAngle - scratchLastAngle);
  const deltaTime = Math.max(1, now - scratchLastMoveAt);
  scratchRotation = scratchBaseRotation + normalizeAngleDelta(pointerAngle - scratchStartAngle);
  els.platterDisc.style.setProperty("--scratch-rotate", `${scratchRotation}deg`);
  updateScratchAudio(deltaAngle, deltaTime);
  scratchLastAngle = pointerAngle;
  scratchLastMoveAt = now;
});

function stopScratch(event) {
  if (!scratchActive) return;
  scratchActive = false;
  if (event && els.platterWrap.hasPointerCapture(event.pointerId)) {
    els.platterWrap.releasePointerCapture(event.pointerId);
  }
  stopScratchAudio();
  syncPlatterMotion(state || { connected: false });
}

els.platterWrap.addEventListener("pointerup", stopScratch);
els.platterWrap.addEventListener("pointercancel", stopScratch);
els.platterWrap.addEventListener("lostpointercapture", stopScratch);
window.addEventListener("blur", () => stopScratch());

document.querySelectorAll("[data-filter-preset]").forEach((button) => {
  button.addEventListener("click", async () => {
    const preset = QUICK_FX[button.dataset.filterPreset];
    if (!preset) return;
    animateEqTo(preset.eq, 360);
    await postAction("set_filter", { filter_name: preset.filter_name });
  });
});

els.filterSelect.addEventListener("change", () => postAction("set_filter", { filter_name: els.filterSelect.value }));

setupVerticalDrag(els.volumeHandle, els.volume, {
  onChange: () => {
    updateVolumeReadout();
    liveVolumeSender();
  },
  onCommit: () => {
    updateVolumeReadout();
    liveVolumeSender();
  },
  onReset: resetVolume,
});

setupVerticalDrag(els.eqLowHandle, els.eqLow, {
  onChange: () => {
    updateEqValueLabels();
    cancelEqAnimation();
    liveEqSender();
  },
  onCommit: () => {
    updateEqValueLabels();
    cancelEqAnimation();
    void sendEqNow();
  },
  onReset: () => resetEqBand(els.eqLow),
});

setupVerticalDrag(els.eqMidHandle, els.eqMid, {
  onChange: () => {
    updateEqValueLabels();
    cancelEqAnimation();
    liveEqSender();
  },
  onCommit: () => {
    updateEqValueLabels();
    cancelEqAnimation();
    void sendEqNow();
  },
  onReset: () => resetEqBand(els.eqMid),
});

setupVerticalDrag(els.eqHighHandle, els.eqHigh, {
  onChange: () => {
    updateEqValueLabels();
    cancelEqAnimation();
    liveEqSender();
  },
  onCommit: () => {
    updateEqValueLabels();
    cancelEqAnimation();
    void sendEqNow();
  },
  onReset: () => resetEqBand(els.eqHigh),
});

setupKnobDrag(els.fxHighpassKnob, els.fxHighpass, {
  onChange: () => {
    updateToneValueLabels();
    liveToneSender();
  },
  onCommit: () => {
    updateToneValueLabels();
    liveToneSender();
  },
  onReset: () => resetToneBand(els.fxHighpass),
});

setupKnobDrag(els.fxLowpassKnob, els.fxLowpass, {
  onChange: () => {
    updateToneValueLabels();
    liveToneSender();
  },
  onCommit: () => {
    updateToneValueLabels();
    liveToneSender();
  },
  onReset: () => resetToneBand(els.fxLowpass),
});

document.querySelectorAll("[data-eq-scene]").forEach((button) => {
  button.addEventListener("click", () => {
    const scene = EQ_SCENES[button.dataset.eqScene];
    if (!scene) return;
    animateEqTo(scene, 320);
  });
});

[els.volumeHandle, els.eqLowHandle, els.eqMidHandle, els.eqHighHandle].forEach((handle) => {
  handle.addEventListener("pointerup", () => {
    const now = performance.now();
    const previous = lastTapAt.get(handle) || 0;
    if ((now - previous) <= 260) {
      handle.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
      lastTapAt.set(handle, 0);
      return;
    }
    lastTapAt.set(handle, now);
  });
});

[els.fxHighpassKnob, els.fxLowpassKnob].forEach((knob) => {
  knob.addEventListener("pointerup", () => {
    const now = performance.now();
    const previous = lastTapAt.get(knob) || 0;
    if ((now - previous) <= 260) {
      knob.dispatchEvent(new MouseEvent("dblclick", { bubbles: true }));
      lastTapAt.set(knob, 0);
      return;
    }
    lastTapAt.set(knob, now);
  });
});

bootstrap();
window.requestAnimationFrame(tickPlaybackClock);
refreshTimer = window.setInterval(bootstrap, 4000);
if (window.EventSource) {
  const source = new EventSource(eventsUrl);
  source.addEventListener("dj_state", (event) => {
    try {
      render(JSON.parse(event.data));
    } catch (err) {
      console.warn("DJ SSE parse failed", err);
    }
  });
  source.onerror = () => {
    console.warn("DJ SSE error", { guildId, lastErrorCode });
  };
}
