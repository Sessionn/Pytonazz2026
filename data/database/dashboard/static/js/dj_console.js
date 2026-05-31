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
  volumeValue: document.getElementById("volume-value"),
  filterSelect: document.getElementById("filter-select"),
  queue: document.getElementById("queue-list"),
  eqLow: document.getElementById("eq-low"),
  eqMid: document.getElementById("eq-mid"),
  eqHigh: document.getElementById("eq-high"),
  eqLowValue: document.getElementById("eq-low-value"),
  eqMidValue: document.getElementById("eq-mid-value"),
  eqHighValue: document.getElementById("eq-high-value"),
  platterWrap: document.getElementById("platter-wrap"),
  platterDisc: document.getElementById("platter-disc"),
};

let state = null;
let sendVolumeTimer = null;
let sendEqTimer = null;
let refreshTimer = null;
let lastErrorCode = "";
let queueKeys = new Set();
let scratchRotation = 0;
let scratchActive = false;
let scratchStartAngle = 0;
let scratchBaseRotation = 0;
let lastStateSyncAt = performance.now();
let lastVolumeTapAt = 0;
const lastEqTapAt = new WeakMap();

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

function setActiveButton(selector, predicate) {
  document.querySelectorAll(selector).forEach((button) => {
    button.classList.toggle("is-active", predicate(button));
  });
}

function summarizeTone(eq) {
  const values = [eq.low || 0, eq.mid || 0, eq.high || 0];
  const peak = Math.max(...values.map((v) => Math.abs(v)));
  if (peak < 0.25) return "flat";
  const boosted = values.filter((v) => v > 1.5).length;
  const cut = values.filter((v) => v < -1.5).length;
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

function updateEqValueLabels() {
  els.eqLowValue.textContent = `${Number(els.eqLow.value).toFixed(1)} dB`;
  els.eqMidValue.textContent = `${Number(els.eqMid.value).toFixed(1)} dB`;
  els.eqHighValue.textContent = `${Number(els.eqHigh.value).toFixed(1)} dB`;
}

function resetEqBand(input) {
  input.value = "0";
  updateEqValueLabels();
  postAction("set_eq", {
    eq: {
      low: Number(els.eqLow.value),
      mid: Number(els.eqMid.value),
      high: Number(els.eqHigh.value),
    },
  });
}

function syncPlatterMotion(next) {
  els.platterDisc.style.setProperty("--scratch-rotate", `${scratchRotation}deg`);
  const shouldSpin = Boolean(next.connected && next.current_track && !next.is_paused && !scratchActive);
  els.platterDisc.classList.toggle("is-spinning", shouldSpin);
  els.platterDisc.classList.toggle("is-scratching", scratchActive);
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
  els.volume.value = String(next.volume ?? 0.5);
  els.volumeValue.textContent = `${Math.round((next.volume || 0) * 100)}%`;
  els.filterSelect.value = next.filter_name || "off";
  setActiveButton("[data-filter-preset]", (button) => {
    const preset = QUICK_FX[button.dataset.filterPreset];
    return preset &&
      preset.filter_name === (next.filter_name || "off") &&
      eqMatches(preset.eq, next.eq || EQ_SCENES.flat);
  });
  renderQueue(next.queue || []);

  const eq = next.eq || { low: 0, mid: 0, high: 0 };
  els.toneSummary.textContent = summarizeTone(eq);
  els.eqLow.value = String(eq.low ?? 0);
  els.eqMid.value = String(eq.mid ?? 0);
  els.eqHigh.value = String(eq.high ?? 0);
  els.eqLowValue.textContent = `${Number(eq.low || 0).toFixed(1)} dB`;
  els.eqMidValue.textContent = `${Number(eq.mid || 0).toFixed(1)} dB`;
  els.eqHighValue.textContent = `${Number(eq.high || 0).toFixed(1)} dB`;
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
  els.platterWrap.setPointerCapture(event.pointerId);
  syncPlatterMotion(state || { connected: false });
});

els.platterWrap.addEventListener("pointermove", (event) => {
  if (!scratchActive) return;
  scratchRotation = scratchBaseRotation + (getPointerAngle(event) - scratchStartAngle);
  els.platterDisc.style.setProperty("--scratch-rotate", `${scratchRotation}deg`);
});

function stopScratch(event) {
  if (!scratchActive) return;
  scratchActive = false;
  if (event && els.platterWrap.hasPointerCapture(event.pointerId)) {
    els.platterWrap.releasePointerCapture(event.pointerId);
  }
  syncPlatterMotion(state || { connected: false });
}

els.platterWrap.addEventListener("pointerup", stopScratch);
els.platterWrap.addEventListener("pointercancel", stopScratch);

document.querySelectorAll("[data-filter-preset]").forEach((button) => {
  button.addEventListener("click", async () => {
    const preset = QUICK_FX[button.dataset.filterPreset];
    if (!preset) return;
    await postAction("set_filter", { filter_name: preset.filter_name });
    await postAction("set_eq", { eq: preset.eq });
  });
});

els.filterSelect.addEventListener("change", () => postAction("set_filter", { filter_name: els.filterSelect.value }));

els.volume.addEventListener("input", () => {
  els.volumeValue.textContent = `${Math.round(Number(els.volume.value) * 100)}%`;
  clearTimeout(sendVolumeTimer);
  sendVolumeTimer = setTimeout(() => postAction("set_volume", { volume: Number(els.volume.value) }), 120);
});

els.volume.addEventListener("dblclick", () => {
  clearTimeout(sendVolumeTimer);
  els.volume.value = "0.5";
  els.volumeValue.textContent = "50%";
  postAction("set_volume", { volume: 0.5 });
});

els.volume.addEventListener("pointerup", () => {
  const now = performance.now();
  if ((now - lastVolumeTapAt) <= 260) {
    clearTimeout(sendVolumeTimer);
    els.volume.value = "0.5";
    els.volumeValue.textContent = "50%";
    postAction("set_volume", { volume: 0.5 });
    lastVolumeTapAt = 0;
    return;
  }
  lastVolumeTapAt = now;
});

[els.eqLow, els.eqMid, els.eqHigh].forEach((input) => {
  input.addEventListener("input", () => {
    updateEqValueLabels();
    clearTimeout(sendEqTimer);
    sendEqTimer = setTimeout(() => {
      postAction("set_eq", {
        eq: {
          low: Number(els.eqLow.value),
          mid: Number(els.eqMid.value),
          high: Number(els.eqHigh.value),
        },
      });
    }, 220);
  });

  input.addEventListener("dblclick", () => {
    clearTimeout(sendEqTimer);
    resetEqBand(input);
  });

  input.addEventListener("pointerup", () => {
    const now = performance.now();
    const previous = lastEqTapAt.get(input) || 0;
    if ((now - previous) <= 260) {
      clearTimeout(sendEqTimer);
      resetEqBand(input);
      lastEqTapAt.set(input, 0);
      return;
    }
    lastEqTapAt.set(input, now);
  });
});

document.querySelectorAll("[data-eq-scene]").forEach((button) => {
  button.addEventListener("click", () => {
    const scene = EQ_SCENES[button.dataset.eqScene];
    if (!scene) return;
    els.eqLow.value = String(scene.low);
    els.eqMid.value = String(scene.mid);
    els.eqHigh.value = String(scene.high);
    els.eqLowValue.textContent = `${Number(scene.low).toFixed(1)} dB`;
    els.eqMidValue.textContent = `${Number(scene.mid).toFixed(1)} dB`;
    els.eqHighValue.textContent = `${Number(scene.high).toFixed(1)} dB`;
    postAction("set_eq", { eq: scene });
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
