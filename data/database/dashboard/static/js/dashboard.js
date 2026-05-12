let currentSort = "hit_count";
let currentOrder = "desc";
let debounceTimer;
let autoRefreshInterval = null;
let _lastIds = new Set();

// ── INIT ──────────────────────────────────────────────────────────────────────
document.addEventListener("DOMContentLoaded", () => {
  const saved = localStorage.getItem("theme") || "dark";
  document.documentElement.setAttribute("data-theme", saved);
  updateThemeUI(saved);
  animateCounters();
  fetchSongs();
  startAutoRefresh(10);
  document.getElementById("gen-time").textContent =
    "Aggiornato: " + new Date().toLocaleString("it-IT");

  // favicon animata
  const favicons = ["💿", "🎵"];
  let fi = 0;
  setInterval(() => {
    fi = (fi + 1) % favicons.length;
    const el = document.querySelector("link[rel='icon']");
    if (el) el.href = `data:image/svg+xml,<svg xmlns='http://www.w3.org/2000/svg' viewBox='0 0 110 110'><text y='1em' font-size='90'>${favicons[fi]}</text></svg>`;
  }, 2000);
});

// ── THEME ─────────────────────────────────────────────────────────────────────
function toggleTheme() {
  const html = document.documentElement;
  const newTheme = html.getAttribute("data-theme") === "light" ? "dark" : "light";
  html.setAttribute("data-theme", newTheme);
  localStorage.setItem("theme", newTheme);
  updateThemeUI(newTheme);
}

function updateThemeUI(theme) {
  const track = document.getElementById("toggle-track");
  const label = document.getElementById("theme-label");
  if (theme === "light") {
    track.classList.add("on");
    label.textContent = "Tema scuro";
  } else {
    track.classList.remove("on");
    label.textContent = "Tema chiaro";
  }
}

// ── COUNTER ANIMATION ─────────────────────────────────────────────────────────
function animateCounters() {
  document.querySelectorAll(".count-up").forEach(el => {
    const target = parseInt(el.dataset.target) || 0;
    const duration = 900;
    const start = performance.now();
    const update = (now) => {
      const p = Math.min((now - start) / duration, 1);
      el.textContent = Math.round((1 - Math.pow(1 - p, 3)) * target);
      if (p < 1) requestAnimationFrame(update);
    };
    requestAnimationFrame(update);
  });
}

// ── AUTO REFRESH ──────────────────────────────────────────────────────────────
function startAutoRefresh(seconds = 10) {
  stopAutoRefresh();
  autoRefreshInterval = setInterval(() => {
    fetchSongs(true);
  }, seconds * 1000);
}

function stopAutoRefresh() {
  if (autoRefreshInterval) {
    clearInterval(autoRefreshInterval);
    autoRefreshInterval = null;
  }
}

// ── FETCH SONGS ───────────────────────────────────────────────────────────────
function fetchSongs(silent = false) {
  const q      = document.getElementById("search-input").value;
  const source = document.getElementById("filter-source").value;
  const valid  = document.getElementById("filter-valid").value;
  const params = new URLSearchParams({ q, source, valid, sort: currentSort, order: currentOrder });

  if (!silent) showSkeleton();

  fetch("/api/songs?" + params)
    .then(r => r.json())
    .then(data => {
      if (!silent) hideSkeleton();
      if (data.length === 0) {
        document.getElementById("songs-body").innerHTML =
          `<tr><td colspan="10" style="text-align:center;padding:32px;color:var(--muted)">Nessun risultato trovato.</td></tr>`;
        _lastIds = new Set();
        return;
      }
      if (silent) {
        renderSongsDiff(data);
      } else {
        renderSongs(data);
      }
    })
    .catch(() => showToast("Errore nel caricamento dati", "error"));
}

function debouncedFetch() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => fetchSongs(false), 280);
}

// ── BUILD ROW ─────────────────────────────────────────────────────────────────
function buildRow(s, i = 0) {
  const src = s.source || "youtube";
  const srcColor = src === "spotify" ? "#1DB954" : "#e5173f";
  const badge = s.is_valid
    ? `<span class="badge ok">valida</span>`
    : `<span class="badge err">invalida</span>`;
  const dur = s.duration ? fmtDuration(s.duration) : "-";
  const thumbHtml = s.thumbnail
    ? `<img class="thumb" src="${esc(s.thumbnail)}" loading="lazy" onerror="this.replaceWith(makePlaceholder())">`
    : `<div class="thumb-placeholder">🎵</div>`;
  const webLink = s.webpage_url
    ? `<a class="link-btn" href="${esc(s.webpage_url)}" target="_blank">▶</a>` : "";
  const spLink = s.spotify_url
    ? `<a class="link-btn sp" href="${esc(s.spotify_url)}" target="_blank">♫</a>` : "";

  const tr = document.createElement("tr");
  tr.style.animationDelay = `${i * 28}ms`;
  tr.dataset.id = s.id;
  tr.innerHTML = `
    <td class="id-col">${s.id}</td>
    <td>
      <div style="display:flex;align-items:center;gap:10px">
        ${thumbHtml}
        <div>
          <div class="title-text" onclick='openModal(${JSON.stringify(s)})'>${esc(s.title || "")}</div>
          <div class="artist-text">${esc(s.artist || "")}</div>
        </div>
      </div>
    </td>
    <td>
      <div class="query-cell" title="${esc(s.query_raw || "")}"
        onclick="setSearch('${esc(s.query_raw || "")}')">
        ${esc(s.query_raw || "")}
      </div>
    </td>
    <td><span class="src-badge" style="background:${srcColor}">${src}</span></td>
    <td class="dim" style="text-align:center">${dur}</td>
    <td class="hits-num" style="text-align:center">${s.hit_count ?? 0}</td>
    <td class="dim">${fmtTs(s.created_at)}</td>
    <td class="dim">${fmtTs(s.last_used)}</td>
    <td>${badge}</td>
    <td>
      <div class="row-actions">
        ${webLink}${spLink}
        <button class="del-btn" title="Elimina" onclick="deleteSong(${s.id})">✖</button>
      </div>
    </td>
  `;
  return tr;
}

// ── RENDER SONGS (primo caricamento) ──────────────────────────────────────────
function renderSongs(data) {
  const tbody = document.getElementById("songs-body");
  tbody.innerHTML = "";
  data.forEach((s, i) => tbody.appendChild(buildRow(s, i)));
  _lastIds = new Set(data.map(s => s.id));
}

// ── RENDER DIFF (silent refresh) ──────────────────────────────────────────────
function renderSongsDiff(data) {
  const newIds = new Set(data.map(s => s.id));

  // rimuovi righe eliminate dal db
  document.querySelectorAll("#songs-body tr[data-id]").forEach(tr => {
    if (!newIds.has(parseInt(tr.dataset.id))) {
      tr.style.transition = "opacity .4s, transform .4s";
      tr.style.opacity = "0";
      tr.style.transform = "translateX(20px)";
      setTimeout(() => tr.remove(), 400);
    }
  });

  // aggiungi righe nuove
  const addedIds = [...newIds].filter(id => !_lastIds.has(id));
  if (addedIds.length > 0) {
    const tbody = document.getElementById("songs-body");
    const newSongs = data.filter(s => addedIds.includes(s.id));
    newSongs.reverse().forEach(s => {
      if (tbody.querySelector(`tr[data-id="${s.id}"]`)) return;
      const tr = buildRow(s);
      tr.style.animation = "none";
      tr.style.opacity = "0";
      tr.style.transform = "translateY(-10px)";
      tbody.prepend(tr);
      requestAnimationFrame(() => {
        tr.style.transition = "opacity .4s, transform .4s, background .8s";
        tr.style.opacity = "1";
        tr.style.transform = "translateY(0)";
        tr.style.background = "rgba(166,227,161,0.12)";
        setTimeout(() => { tr.style.background = ""; }, 1800);
      });
    });
    showToast(`+${addedIds.length} nuova traccia`, "success");
  }

  _lastIds = newIds;
}

function setSearch(val) {
  document.getElementById("search-input").value = val;
  fetchSongs(false);
}

// ── SORT ──────────────────────────────────────────────────────────────────────
function sortBy(col) {
  if (currentSort === col) {
    currentOrder = currentOrder === "desc" ? "asc" : "desc";
  } else {
    currentSort = col;
    currentOrder = "desc";
  }
  document.querySelectorAll("th[data-col]").forEach(th => {
    th.classList.remove("sorted");
    th.querySelector(".arrow").textContent = "↕";
  });
  const th = document.querySelector(`th[data-col="${col}"]`);
  if (th) {
    th.classList.add("sorted");
    th.querySelector(".arrow").textContent = currentOrder === "desc" ? "↓" : "↑";
  }
  fetchSongs(false);
}

function clearFilters() {
  document.getElementById("search-input").value = "";
  document.getElementById("filter-source").value = "";
  document.getElementById("filter-valid").value = "";
  fetchSongs(false);
}

// ── SKELETON ──────────────────────────────────────────────────────────────────
function showSkeleton() {
  const tbody = document.getElementById("songs-body");
  const widths = [30, 140, 90, 60, 40, 30, 80, 80, 55, 50];
  tbody.innerHTML = Array.from({ length: 6 }).map(() =>
    `<tr>${widths.map(w =>
      `<td><div class="skeleton" style="width:${w}px;height:13px"></div></td>`
    ).join("")}</tr>`
  ).join("");
}

function hideSkeleton() {
  document.querySelectorAll(".skeleton")
    .forEach(el => el.closest("tr")?.remove());
}

// ── DELETE ────────────────────────────────────────────────────────────────────
function deleteSong(id) {
  const tr = document.querySelector(`tr[data-id="${id}"]`);
  fetch("/api/delete/" + id, { method: "DELETE" })
    .then(r => r.json())
    .then(d => {
      if (d.ok) {
        if (tr) {
          tr.style.transition = "opacity .3s, transform .3s";
          tr.style.opacity = "0";
          tr.style.transform = "translateX(20px)";
          setTimeout(() => tr.remove(), 300);
        }
        _lastIds.delete(id);
        showToast("Entry eliminata", "success");
        closeModal();
      }
    })
    .catch(() => showToast("Errore durante l'eliminazione", "error"));
}

// ── MODAL ─────────────────────────────────────────────────────────────────────
function openModal(s) {
  const thumbHtml = s.thumbnail
    ? `<img class="modal-thumb" src="${esc(s.thumbnail)}">` : "";

  document.getElementById("modal-content").innerHTML = `
    ${thumbHtml}
    <h3>${esc(s.title || "")}</h3>
    <div class="modal-artist" style="clear:none">${esc(s.artist || "")}</div>
    <div style="clear:both;margin-bottom:4px"></div>
    ${mrow("ID", s.id)}
    ${mrow("Query", s.query_raw)}
    ${mrow("Sorgente", s.source)}
    ${mrow("Durata", s.duration ? fmtDuration(s.duration) : "-")}
    ${mrow("Hits", `<span style="color:var(--yellow);font-weight:700">${s.hit_count ?? 0}</span>`)}
    ${mrow("Stato", s.is_valid ? `<span class="badge ok">valida</span>` : `<span class="badge err">invalida</span>`)}
    ${mrow("Creata", fmtTs(s.created_at))}
    ${mrow("Ultima usata", fmtTs(s.last_used))}
    ${s.webpage_url ? mrow("Link", `<a class="modal-link" href="${esc(s.webpage_url)}" target="_blank">${esc(s.webpage_url)}</a>`) : ""}
    ${s.spotify_url ? mrow("Spotify", `<a class="modal-link" href="${esc(s.spotify_url)}" target="_blank">${esc(s.spotify_url)}</a>`) : ""}
    <div class="modal-actions">
      <button class="btn btn-danger" onclick="deleteSong(${s.id})">✖ Elimina</button>
      <button class="btn btn-ghost" onclick="closeModal()">Chiudi</button>
    </div>
  `;
  document.getElementById("modal-bg").classList.add("open");
}

function mrow(key, val) {
  return `<div class="modal-row">
    <span class="modal-key">${key}</span>
    <span class="modal-val">${val}</span>
  </div>`;
}

function closeModal() {
  document.getElementById("modal-bg").classList.remove("open");
}

document.getElementById("modal-bg").addEventListener("click", e => {
  if (e.target === document.getElementById("modal-bg")) closeModal();
});

// ── ALIASES ───────────────────────────────────────────────────────────────────
function fetchAliases() {
  fetch("/api/aliases").then(r => r.json()).then(data => {
    const tbody = document.getElementById("aliases-body");
    if (data.length === 0) {
      tbody.innerHTML = `<tr><td colspan="4" style="text-align:center;padding:32px;color:var(--muted)">Nessun alias registrato.</td></tr>`;
      return;
    }
    tbody.innerHTML = data.map((a, i) => `
      <tr style="animation-delay:${i * 25}ms">
        <td class="id-col">${a.id}</td>
        <td class="dim">${esc(a.query_raw || "")}</td>
        <td>
          <span class="title-text">${esc(a.title || "")}</span>
          <span class="artist-text">${esc(a.artist || "")}</span>
        </td>
        <td class="id-col">${a.cache_id}</td>
      </tr>
    `).join("");
  });
}

// ── SECTION SWITCH ────────────────────────────────────────────────────────────
function showSection(sec, el) {
  document.querySelectorAll("nav a").forEach(a => a.classList.remove("active"));
  el.classList.add("active");
  document.getElementById("cache-section").style.display   = sec === "cache"   ? "block" : "none";
  document.getElementById("aliases-section").style.display = sec === "aliases" ? "block" : "none";
  if (sec === "aliases") fetchAliases();
  if (sec === "cache") startAutoRefresh(10);
  else stopAutoRefresh();
}

// ── TOAST ─────────────────────────────────────────────────────────────────────
function showToast(msg, type = "success") {
  const container = document.getElementById("toast-container");
  const icon = type === "success" ? "✅" : "❌";
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.innerHTML = `<span>${icon}</span> ${msg}`;
  container.appendChild(el);
  setTimeout(() => {
    el.style.animation = "toastOut .3s ease forwards";
    setTimeout(() => el.remove(), 300);
  }, 2800);
}

// ── UTILS ─────────────────────────────────────────────────────────────────────
function fmtDuration(sec) {
  if (!sec) return "-";
  const m = Math.floor(sec / 60), s = sec % 60;
  return m + ":" + String(s).padStart(2, "0");
}

function fmtTs(ts) {
  if (!ts) return "-";
  const d = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  if (isNaN(d)) return String(ts).slice(0, 16);
  return d.toLocaleDateString("it-IT") + " " +
    d.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
}

function esc(s) {
  return String(s ?? "")
    .replace(/&/g, "&amp;").replace(/</g, "&lt;")
    .replace(/>/g, "&gt;").replace(/"/g, "&quot;");
}

function makePlaceholder() {
  const d = document.createElement("div");
  d.className = "thumb-placeholder";
  d.textContent = "🎵";
  return d;
}