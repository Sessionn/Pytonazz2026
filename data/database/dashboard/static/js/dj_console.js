const guildId = Number(document.body.dataset.guildId || 0);
const stateUrl = `/dj-console/state?guild_id=${guildId}`;
const eventsUrl = `/dj-console/events?guild_id=${guildId}`;

const els = {
  voice: document.getElementById("voice-channel"),
  playback: document.getElementById("playback-state"),
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
};

let state = null;
let sendVolumeTimer = null;
let sendEqTimer = null;
const EQ_SCENES = {
  flat: { low: 0, mid: 0, high: 0 },
  club: { low: 5, mid: -1.5, high: 4 },
  warm: { low: 3.5, mid: 1.5, high: -2 },
  air: { low: -1, mid: 0.5, high: 5.5 },
  "kill-low": { low: -12, mid: 0, high: 0 },
  "kill-high": { low: 0, mid: 0, high: -12 },
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

function renderQueue(items) {
  els.queue.innerHTML = "";
  if (!items || !items.length) {
    const li = document.createElement("li");
    li.textContent = "Coda vuota.";
    els.queue.appendChild(li);
    return;
  }
  items.slice(0, 20).forEach((track, index) => {
    const li = document.createElement("li");
    li.innerHTML = `<strong>${index + 1}. ${track.title}</strong><br><span>${track.artist || "Sconosciuto"}</span>`;
    els.queue.appendChild(li);
  });
}

function render(next) {
  state = next;
  const current = next.current_track;
  els.voice.textContent = next.voice_channel_name || "-";
  els.playback.textContent = next.connected ? (next.is_paused ? "Paused" : "Live") : "Disconnected";
  els.effectSummary.textContent = next.filter_name || "off";
  els.title.textContent = current ? current.title : "Nessuna traccia";
  els.artist.textContent = current ? (current.artist || "Artista sconosciuto") : "-";
  els.requester.textContent = current ? `Requested by ${current.requester || current.requester_id}` : "-";
  els.position.textContent = formatTime(next.position);
  els.duration.textContent = formatTime(next.duration);
  const progress = next.duration > 0 ? Math.min(100, (next.position / next.duration) * 100) : 0;
  els.progress.style.width = `${progress}%`;
  els.volume.value = String(next.volume ?? 0.5);
  els.volumeValue.textContent = `${Math.round((next.volume || 0) * 100)}%`;
  els.filterSelect.value = next.filter_name || "off";
  setActiveButton("[data-filter-preset]", (button) => button.dataset.filterPreset === (next.filter_name || "off"));
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
}

async function postAction(action, payload = {}) {
  const response = await fetch("/dj-console/action", {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify({ guild_id: guildId, action, ...payload }),
  });
  if (!response.ok) {
    return;
  }
  const result = await response.json();
  if (!result.ok) {
    console.warn("DJ action failed", result);
  }
}

async function bootstrap() {
  const response = await fetch(stateUrl);
  if (!response.ok) {
    return;
  }
  render(await response.json());
}

document.querySelectorAll("[data-filter-preset]").forEach((button) => {
  button.addEventListener("click", () => postAction("set_filter", { filter_name: button.dataset.filterPreset }));
});

els.filterSelect.addEventListener("change", () => postAction("set_filter", { filter_name: els.filterSelect.value }));

els.volume.addEventListener("input", () => {
  els.volumeValue.textContent = `${Math.round(Number(els.volume.value) * 100)}%`;
  clearTimeout(sendVolumeTimer);
  sendVolumeTimer = setTimeout(() => postAction("set_volume", { volume: Number(els.volume.value) }), 120);
});

[els.eqLow, els.eqMid, els.eqHigh].forEach((input) => {
  input.addEventListener("input", () => {
    els.eqLowValue.textContent = `${Number(els.eqLow.value).toFixed(1)} dB`;
    els.eqMidValue.textContent = `${Number(els.eqMid.value).toFixed(1)} dB`;
    els.eqHighValue.textContent = `${Number(els.eqHigh.value).toFixed(1)} dB`;
    clearTimeout(sendEqTimer);
    sendEqTimer = setTimeout(() => {
      postAction("set_eq", {
        eq: {
          low: Number(els.eqLow.value),
          mid: Number(els.eqMid.value),
          high: Number(els.eqHigh.value),
        },
      });
    }, 160);
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
if (window.EventSource) {
  const source = new EventSource(eventsUrl);
  source.addEventListener("dj_state", (event) => {
    try {
      render(JSON.parse(event.data));
    } catch (err) {
      console.warn("DJ SSE parse failed", err);
    }
  });
}
