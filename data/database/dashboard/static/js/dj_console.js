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
  resetMixerButton: document.getElementById("reset-mixer-button"),
  queue: document.getElementById("queue-list"),
  eqSub: document.getElementById("eq-sub"),
  eqSubHandle: document.getElementById("eq-sub-handle"),
  eqLow: document.getElementById("eq-low"),
  eqLowHandle: document.getElementById("eq-low-handle"),
  eqMid: document.getElementById("eq-mid"),
  eqMidHandle: document.getElementById("eq-mid-handle"),
  eqHigh: document.getElementById("eq-high"),
  eqHighHandle: document.getElementById("eq-high-handle"),
  eqAir: document.getElementById("eq-air"),
  eqAirHandle: document.getElementById("eq-air-handle"),
  fxHighpass: document.getElementById("fx-highpass"),
  fxLowpass: document.getElementById("fx-lowpass"),
  fxPresence: document.getElementById("fx-presence"),
  fxWidth: document.getElementById("fx-width"),
  fxHighpassKnob: document.getElementById("fx-highpass-knob"),
  fxLowpassKnob: document.getElementById("fx-lowpass-knob"),
  fxPresenceKnob: document.getElementById("fx-presence-knob"),
  fxWidthKnob: document.getElementById("fx-width-knob"),
  eqSubValue: document.getElementById("eq-sub-value"),
  eqLowValue: document.getElementById("eq-low-value"),
  eqMidValue: document.getElementById("eq-mid-value"),
  eqHighValue: document.getElementById("eq-high-value"),
  eqAirValue: document.getElementById("eq-air-value"),
  fxHighpassValue: document.getElementById("fx-highpass-value"),
  fxLowpassValue: document.getElementById("fx-lowpass-value"),
  fxPresenceValue: document.getElementById("fx-presence-value"),
  fxWidthValue: document.getElementById("fx-width-value"),
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
  flat: { sub: 0, low: 0, mid: 0, high: 0, air: 0 },
  club: { sub: 2.5, low: 4.5, mid: -1.5, high: 3.5, air: 1.5 },
  warm: { sub: 1.5, low: 3.5, mid: 1.5, high: -2, air: -1 },
  air: { sub: -1.5, low: -1, mid: 0.5, high: 3.5, air: 5.5 },
  vocal: { sub: -2, low: -1, mid: 2.5, high: 1.5, air: 1 },
  lofi: { sub: 1, low: 2.5, mid: -0.5, high: -4, air: -5 },
  "bass-tight": { sub: 3.5, low: 2, mid: -1, high: 0, air: 0 },
  "kill-low": { sub: -12, low: -12, mid: 0, high: 0, air: 0 },
  "kill-high": { sub: 0, low: 0, mid: 0, high: -12, air: -12 },
};

const EQ_BANDS = [
  { key: "sub", input: "eqSub", handle: "eqSubHandle", value: "eqSubValue" },
  { key: "low", input: "eqLow", handle: "eqLowHandle", value: "eqLowValue" },
  { key: "mid", input: "eqMid", handle: "eqMidHandle", value: "eqMidValue" },
  { key: "high", input: "eqHigh", handle: "eqHighHandle", value: "eqHighValue" },
  { key: "air", input: "eqAir", handle: "eqAirHandle", value: "eqAirValue" },
];

const TONE_CONTROLS = [
  { key: "highpass_hz", input: "fxHighpass", knob: "fxHighpassKnob", value: "fxHighpassValue", defaultValue: 0 },
  { key: "lowpass_hz", input: "fxLowpass", knob: "fxLowpassKnob", value: "fxLowpassValue", defaultValue: 20000 },
  { key: "presence_gain", input: "fxPresence", knob: "fxPresenceKnob", value: "fxPresenceValue", defaultValue: 0 },
  { key: "stereo_width", input: "fxWidth", knob: "fxWidthKnob", value: "fxWidthValue", defaultValue: 1 },
];

const FILTER_LABELS = {
  off: "Off",
  nightcore: "Sped Up",
  vaporwave: "Slowed",
  "8d": "8D Audio",
  bassboost: "Bass Boost",
  trebleboost: "Treble Boost",
  vocalboost: "Vocal Boost",
  radio: "Radio / Phone",
  reverb: "Reverb",
  echo: "Echo",
  wide: "Wide Stereo",
  night: "Night Mode",
};

function normalizeList(value) {
  return Array.isArray(value) ? value.map((entry) => String(entry || "").trim().toLowerCase()).filter(Boolean) : [];
}

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
    const active = predicate(button);
    button.classList.toggle("is-active", active);
    button.setAttribute("aria-pressed", active ? "true" : "false");
  });
}

function summarizeTone(eq) {
  const values = EQ_BANDS.map((band) => eq[band.key] || 0);
  const peak = Math.max(...values.map((value) => Math.abs(value)));
  if (peak < 0.25) return "flat";
  const boosted = values.filter((value) => value > 1.5).length;
  const cut = values.filter((value) => value < -1.5).length;
  if (boosted >= 2) return "hyped";
  if (cut >= 2) return "cut";
  return "custom";
}

function eqMatches(a, b) {
  return EQ_BANDS.every((band) => Number(a[band.key] || 0) === Number(b[band.key] || 0));
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

function syncFilterSelect(value) {
  const nextValue = String(value || "off");
  setActiveButton("[data-base-filter]", (button) => button.dataset.baseFilter === nextValue);
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

function readDefaultValue(input) {
  const fallback = input.dataset.default ?? input.defaultValue ?? input.min ?? "0";
  return Number(fallback);
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
  EQ_BANDS.forEach((band) => {
    const input = els[band.input];
    const value = els[band.value];
    if (!input || !value) return;
    value.textContent = `${getControlValue(input).toFixed(1)} dB`;
    setFaderHandlePosition(els[band.handle], input);
  });
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
  els.fxPresenceValue.textContent = `${getControlValue(els.fxPresence).toFixed(1)} dB`;
  els.fxWidthValue.textContent = `${Math.round(getControlValue(els.fxWidth) * 100)}%`;
  setKnobAngle(els.fxHighpassKnob, els.fxHighpass);
  setKnobAngle(els.fxLowpassKnob, els.fxLowpass);
  setKnobAngle(els.fxPresenceKnob, els.fxPresence);
  setKnobAngle(els.fxWidthKnob, els.fxWidth);
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
  master.gain.value = 0.88;

  const panner = context.createStereoPanner();
  panner.pan.value = 0;

  source.connect(bandpass);
  bandpass.connect(highpass);
  highpass.connect(panner);
  panner.connect(drive);
  drive.connect(master);
  master.connect(context.destination);
  source.start();

  scratchAudio = { context, source, bandpass, highpass, panner, drive, master };
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
  const baseFilterName = String(next.base_filter_name || next.filter_name || "off");
  const activeFxNames = normalizeList(next.active_fx_names);
  els.effectSummary.textContent = [baseFilterName !== "off" ? FILTER_LABELS[baseFilterName] || baseFilterName : "clean", ...activeFxNames.map((name) => FILTER_LABELS[name] || name)].join(" + ");
  els.title.textContent = current ? current.title : "Nessuna traccia";
  els.artist.textContent = current ? (current.artist || "Artista sconosciuto") : "-";
  els.requester.textContent = current ? `Requested by ${current.requester || current.requester_id}` : "-";
  renderPlaybackClock();
  syncFilterSelect(baseFilterName);
  setActiveButton("[data-base-filter]", (button) => button.dataset.baseFilter === baseFilterName);
  setActiveButton("[data-filter-fx]", (button) => activeFxNames.includes(String(button.dataset.filterFx || "").trim().toLowerCase()));
  const fxCatalog = Array.isArray(next.filter_catalog?.fx_filters) ? next.filter_catalog.fx_filters : [];
  document.querySelectorAll("[data-filter-fx]").forEach((button) => {
    const fxName = String(button.dataset.filterFx || "").trim().toLowerCase();
    const descriptor = fxCatalog.find((entry) => String(entry.name || "").trim().toLowerCase() === fxName);
    const compatible = descriptor ? Boolean(descriptor.compatible) : true;
    button.disabled = !compatible;
    button.classList.toggle("is-disabled", !compatible);
    button.title = compatible ? "" : "FX non compatibile con il filtro base attivo";
  });
  renderQueue(next.queue || []);

  const eq = next.eq || { low: 0, mid: 0, high: 0 };
  const toneFilters = next.tone_filters || { highpass_hz: 0, lowpass_hz: 20000, presence_gain: 0, stereo_width: 1 };
  els.toneSummary.textContent = summarizeTone(eq);

  if (!draggingInputs.has(els.volume)) {
    setControlValue(els.volume, next.volume ?? 0.5);
    updateVolumeReadout();
  }
  EQ_BANDS.forEach((band) => {
    const input = els[band.input];
    if (input && !draggingInputs.has(input)) {
      setControlValue(input, eq[band.key] ?? 0);
    }
  });
  TONE_CONTROLS.forEach((control) => {
    const input = els[control.input];
    if (input && !draggingInputs.has(input)) {
      setControlValue(input, toneFilters[control.key] ?? control.defaultValue);
    }
  });

  updateEqValueLabels();
  updateToneValueLabels();

  setActiveButton("[data-eq-scene]", (button) => {
    const scene = EQ_SCENES[button.dataset.eqScene];
    return scene && eqMatches(scene, eq);
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
    presence_gain: getControlValue(els.fxPresence),
    stereo_width: getControlValue(els.fxWidth),
  },
}));

const liveEqSender = makeContinuousSender("set_eq", () => ({
  eq: Object.fromEntries(EQ_BANDS.map((band) => [band.key, getControlValue(els[band.input])])),
}));

function sendEqNow() {
  clearTimeout(sendEqTimer);
  sendEqTimer = null;
  return postAction("set_eq", {
    eq: Object.fromEntries(EQ_BANDS.map((band) => [band.key, getControlValue(els[band.input])])),
  });
}

function animateControlTo(input, targetValue, { onFrame, onDone, durationMs = 260 } = {}) {
  const start = performance.now();
  const startValue = getControlValue(input);
  const endValue = Number(targetValue);

  function step(now) {
    const t = Math.min(1, (now - start) / durationMs);
    const eased = easeOutQuart(t);
    setControlValue(input, startValue + ((endValue - startValue) * eased));
    onFrame?.();
    if (t < 1) {
      window.requestAnimationFrame(step);
      return;
    }
    onDone?.();
  }

  window.requestAnimationFrame(step);
}

function resetEqBand(input) {
  cancelEqAnimation();
  const targetEq = {
    sub: getControlValue(els.eqSub),
    low: getControlValue(els.eqLow),
    mid: getControlValue(els.eqMid),
    high: getControlValue(els.eqHigh),
    air: getControlValue(els.eqAir),
  };
  EQ_BANDS.forEach((band) => {
    if (input === els[band.input]) {
      targetEq[band.key] = readDefaultValue(input);
    }
  });
  animateEqTo(targetEq, 300);
}

function resetToneBand(input) {
  animateControlTo(input, readDefaultValue(input), {
    durationMs: 300,
    onFrame: () => {
      updateToneValueLabels();
      liveToneSender();
    },
    onDone: () => {
      updateToneValueLabels();
      liveToneSender();
    },
  });
}

function resetVolume() {
  animateControlTo(els.volume, readDefaultValue(els.volume), {
    durationMs: 240,
    onFrame: () => {
      updateVolumeReadout();
      liveVolumeSender();
    },
    onDone: () => {
      updateVolumeReadout();
      liveVolumeSender();
    },
  });
}

function easeOutQuart(t) {
  return 1 - Math.pow(1 - t, 4);
}

function animateEqTo(targetEq, durationMs = 320) {
  cancelEqAnimation();
  const start = performance.now();
  const starts = Object.fromEntries(EQ_BANDS.map((band) => [band.key, getControlValue(els[band.input])]));

  function step(now) {
    const t = Math.min(1, (now - start) / durationMs);
    const eased = easeOutQuart(t);
    EQ_BANDS.forEach((band) => {
      const startValue = starts[band.key] ?? 0;
      const targetValue = Number(targetEq[band.key] ?? 0);
      setControlValue(els[band.input], startValue + ((targetValue - startValue) * eased));
    });
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

document.querySelectorAll("[data-base-filter]").forEach((button) => {
  button.addEventListener("click", async () => {
    const nextValue = button.dataset.baseFilter || "off";
    syncFilterSelect(nextValue);
    await postAction("set_base_filter", { filter_name: nextValue });
  });
});

document.querySelectorAll("[data-filter-fx]").forEach((button) => {
  button.addEventListener("click", async () => {
    if (button.disabled) return;
    const fxName = button.dataset.filterFx || "";
    const enabled = !button.classList.contains("is-active");
    button.classList.toggle("is-active", enabled);
    await postAction("toggle_filter_fx", { fx_name: fxName, enabled });
  });
});

els.resetMixerButton?.addEventListener("click", async () => {
  syncFilterSelect("off");
  document.querySelectorAll("[data-filter-fx]").forEach((button) => {
    button.classList.remove("is-active");
  });
  setControlValue(els.fxHighpass, 0);
  setControlValue(els.fxLowpass, 20000);
  setControlValue(els.fxPresence, 0);
  setControlValue(els.fxWidth, 1);
  updateToneValueLabels();
  animateEqTo(EQ_SCENES.flat, 240);
  await postAction("set_base_filter", { filter_name: "off" });
  await Promise.all([
    postAction("toggle_filter_fx", { fx_name: "bassboost", enabled: false }),
    postAction("toggle_filter_fx", { fx_name: "trebleboost", enabled: false }),
    postAction("toggle_filter_fx", { fx_name: "vocalboost", enabled: false }),
    postAction("toggle_filter_fx", { fx_name: "radio", enabled: false }),
    postAction("toggle_filter_fx", { fx_name: "reverb", enabled: false }),
    postAction("toggle_filter_fx", { fx_name: "echo", enabled: false }),
    postAction("toggle_filter_fx", { fx_name: "wide", enabled: false }),
    postAction("toggle_filter_fx", { fx_name: "8d", enabled: false }),
    postAction("set_tone_filters", { tone_filters: { highpass_hz: 0, lowpass_hz: 20000, presence_gain: 0, stereo_width: 1 } }),
  ]);
});

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

EQ_BANDS.forEach((band) => {
  setupVerticalDrag(els[band.handle], els[band.input], {
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
    onReset: () => resetEqBand(els[band.input]),
  });
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

setupKnobDrag(els.fxPresenceKnob, els.fxPresence, {
  onChange: () => {
    updateToneValueLabels();
    liveToneSender();
  },
  onCommit: () => {
    updateToneValueLabels();
    liveToneSender();
  },
  onReset: () => resetToneBand(els.fxPresence),
});

setupKnobDrag(els.fxWidthKnob, els.fxWidth, {
  onChange: () => {
    updateToneValueLabels();
    liveToneSender();
  },
  onCommit: () => {
    updateToneValueLabels();
    liveToneSender();
  },
  onReset: () => resetToneBand(els.fxWidth),
});

document.querySelectorAll("[data-eq-scene]").forEach((button) => {
  button.addEventListener("click", () => {
    const scene = EQ_SCENES[button.dataset.eqScene];
    if (!scene) return;
    animateEqTo(scene, 320);
  });
});

[els.volumeHandle, ...EQ_BANDS.map((band) => els[band.handle])].forEach((handle) => {
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

[els.fxHighpassKnob, els.fxLowpassKnob, els.fxPresenceKnob, els.fxWidthKnob].forEach((knob) => {
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
