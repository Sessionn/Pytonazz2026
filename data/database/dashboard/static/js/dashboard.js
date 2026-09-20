let currentSort = "created_at";
let currentOrder = "desc";
let currentSection = "cache";
let debounceTimer;
let tableDebounceTimer;
let statsRefreshInterval = null;
let statsEventSource = null;
let cacheChangeTimer = null;
let lastStatsSignature = "";
let lastSongIds = new Set();
let lastSongUrls = new Map();
let songsRequestId = 0;
let modalTrigger = null;
const loadedSections = new Set();
const counterFrames = new WeakMap();
const tableData = {
  aliases: [],
  tracks: [],
  sources: [],
  queries: [],
};
const tableStates = {
  aliases: { search: "", sort: "id", order: "desc" },
  tracks: { search: "", sort: "id", order: "desc" },
  sources: { search: "", sort: "id", order: "desc" },
  queries: { search: "", sort: "id", order: "desc" },
};
const sectionLoaders = {
  cache: () => fetchSongs(false),
  aliases: fetchAliases,
  tracks: fetchTracks,
  sources: fetchSources,
  queries: fetchQueries,
  schema: fetchSchema,
};

const liveSectionLoaders = {
  cache: () => fetchSongs(true),
  aliases: () => fetchAliases(true),
  tracks: () => fetchTracks(true),
  sources: () => fetchSources(true),
  queries: () => fetchQueries(true),
};

function initializeDashboard() {
  let saved = "dark";
  try { saved = localStorage.getItem("theme") === "light" ? "light" : "dark"; } catch (_) {}
  document.documentElement.setAttribute("data-theme", saved);
  updateThemeUI(saved);
  normalizeSortArrows();
  document.querySelectorAll("th[data-col]").forEach(th => {
    th.tabIndex = 0;
    th.addEventListener("keydown", event => {
      if (event.key === "Enter" || event.key === " ") { event.preventDefault(); th.click(); }
    });
  });
  document.querySelectorAll('.toolbar input').forEach(input => {
    if (!input.hasAttribute('aria-label')) input.setAttribute('aria-label', input.placeholder);
  });
  animateCounters();
  fetchSongs(false);
  startStatsRefresh(8);
  startRealtimeStats();
  updateGenTime();
}
if (document.readyState === 'loading') document.addEventListener('DOMContentLoaded', initializeDashboard, { once: true });
else initializeDashboard();

function normalizeSortArrows() {
  document.querySelectorAll("th[data-col]").forEach(th => {
    const arrow = th.querySelector(".arrow");
    if (!arrow) return;
    arrow.textContent = th.classList.contains("sorted") ? "↓" : "↕";
  });
}

function updateGenTime() {
  const target = document.getElementById("gen-time");
  if (target) {
    target.textContent = "Aggiornato: " + new Date().toLocaleString("it-IT");
  }
}

function toggleTheme() {
  const html = document.documentElement;
  const nextTheme = html.getAttribute("data-theme") === "light" ? "dark" : "light";
  html.setAttribute("data-theme", nextTheme);
  try { localStorage.setItem("theme", nextTheme); } catch (_) {}
  updateThemeUI(nextTheme);
}

function updateThemeUI(theme) {
  const track = document.getElementById("toggle-track");
  const label = document.getElementById("theme-label");
  if (!track || !label) return;
  if (theme === "light") {
    track.classList.add("on");
    label.textContent = "Tema scuro";
  } else {
    track.classList.remove("on");
    label.textContent = "Tema chiaro";
  }
}

function animateCounters() {
  document.querySelectorAll(".count-up").forEach(el => {
    const target = parseInt(el.dataset.target, 10) || 0;
    tweenCounter(el, 0, target, 900);
  });
}

function tweenCounter(el, from, to, duration = 600) {
  cancelAnimationFrame(counterFrames.get(el));
  if (window.matchMedia?.("(prefers-reduced-motion: reduce)").matches) {
    el.textContent = to.toLocaleString("it-IT");
    return;
  }
  const start = performance.now();
  const update = now => {
    const progress = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    el.textContent = Math.round(from + (to - from) * eased).toLocaleString("it-IT");
    if (progress < 1) counterFrames.set(el, requestAnimationFrame(update));
  };
  counterFrames.set(el, requestAnimationFrame(update));
}

function refreshStats(refreshData = true) {
  fetch("/api/stats")
    .then(r => {
      if (!r.ok) throw new Error("stats fetch failed");
      return r.json();
    })
    .then(data => {
      applyStatsPayload(data);
    })
    .catch(() => setConnectionStatus("offline", "Connessione non disponibile"));
}

function setConnectionStatus(state, label) {
  const target = document.getElementById("connection-status");
  if (target) { target.dataset.state = state; target.textContent = label; }
}

function readJson(response) {
  if (response.status === 401) {
    setConnectionStatus("offline", "Sessione scaduta · accedi di nuovo");
    throw new Error("Session expired");
  }
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

function applyStatsPayload(data) {
  setConnectionStatus("live", statsEventSource ? "Statistiche in diretta" : "Statistiche aggiornate ogni 8 s");
  const signature = ["total", "valid", "invalid", "hits", "aliases"]
    .map(key => `${key}:${data[key] ?? 0}`)
    .join("|");
  const changed = Boolean(lastStatsSignature && signature !== lastStatsSignature);
  lastStatsSignature = signature;

  ["total", "valid", "invalid", "hits", "aliases"].forEach(key => {
    const el = document.querySelector(`.val[data-stat="${key}"]`);
    if (!el) return;
    const current = parseInt(el.textContent.replace(/[^0-9]/g, ""), 10) || 0;
    const next = data[key] ?? 0;
    if (current !== next) {
      tweenCounter(el, current, next, 500);
    }
  });
  updateGenTime();
  return changed;
}

function refreshCurrentData(silent = true) {
  const loader = silent ? liveSectionLoaders[currentSection] : sectionLoaders[currentSection];
  if (loader) loader();
}

function startRealtimeStats() {
  if (!window.EventSource || statsEventSource) return;
  statsEventSource = new EventSource("/api/events");
  statsEventSource.addEventListener("stats", event => {
    try {
      applyStatsPayload(JSON.parse(event.data));
    } catch (_) {}
  });
  statsEventSource.addEventListener("cache_change", event => {
    try {
      handleCacheChange(JSON.parse(event.data));
    } catch (_) {}
  });
  statsEventSource.onerror = () => {
    setConnectionStatus("offline", "Diretta interrotta · controllo periodico attivo");
    if (statsEventSource) {
      statsEventSource.close();
      statsEventSource = null;
    }
    startStatsRefresh(8);
  };
  stopStatsRefresh();
}

function handleCacheChange(_payload) {
  clearTimeout(cacheChangeTimer);
  ["aliases", "tracks", "sources", "queries", "schema"].forEach(section => loadedSections.delete(section));
  const notice = document.getElementById("library-update");
  if (notice) notice.hidden = false;
}

function startStatsRefresh(seconds = 8) {
  stopStatsRefresh();
  statsRefreshInterval = setInterval(refreshStats, seconds * 1000);
}

function stopStatsRefresh() {
  if (statsRefreshInterval) {
    clearInterval(statsRefreshInterval);
    statsRefreshInterval = null;
  }
}

function fetchSongs(silent = false) {
  const requestId = ++songsRequestId;
  const q = document.getElementById("search-input")?.value || "";
  const source = document.getElementById("filter-source")?.value || "";
  const valid = document.getElementById("filter-valid")?.value || "";
  const params = pagedParams("cache", { q, source, valid, sort: currentSort, order: currentOrder });
  const scrollSnapshot = silent ? captureScrollSnapshot() : null;

  const body = document.getElementById('songs-body');
  body?.setAttribute('aria-busy','true');
  // Keep existing results readable while a filter, page or refresh is pending.
  if (!silent && !body?.children.length) showSkeleton();

  fetch("/api/songs?" + params.toString())
    .then(readJson)
    .then(data => {
      if (requestId !== songsRequestId) return;
      data = acceptPage("cache", data);
      const notice = document.getElementById("library-update");
      if (notice) notice.hidden = true;
      if (!silent) hideSkeleton();
      if (data.length === 0) {
        const tbody = document.getElementById("songs-body");
        if (tbody) {
          tbody.innerHTML = `<tr><td colspan="11" style="text-align:center;padding:32px;color:var(--muted)">Nessun risultato trovato.</td></tr>`;
        }
        lastSongIds = new Set();
        lastSongUrls = new Map();
        restoreScrollSnapshot(scrollSnapshot);
        return;
      }
      renderSongsDiff(data);
      restoreScrollSnapshot(scrollSnapshot);
    })
    .catch(() => {
      if (requestId !== songsRequestId) return;
      hideSkeleton();
      if (!body?.querySelector('[data-id]')) body.innerHTML = '<tr><td colspan="11">Caricamento non riuscito. Usa Aggiorna per riprovare.</td></tr>';
      showToast("Errore nel caricamento dati", "error");
    }).finally(() => { if(requestId === songsRequestId) body?.removeAttribute('aria-busy'); });
}

function debouncedFetch() {
  clearTimeout(debounceTimer);
  debounceTimer = setTimeout(() => fetchSongs(false), 280);
}

function debouncedTableSearch(section) {
  clearTimeout(tableDebounceTimer);
  tableDebounceTimer = setTimeout(() => {
    const state = tableStates[section];
    const input = document.getElementById(`${section}-search`);
    if (!state || !input) return;
    state.search = input.value.trim();
    fetchLibraryTable(section);
  }, 180);
}

function clearTableSearch(section) {
  const state = tableStates[section];
  const input = document.getElementById(`${section}-search`);
  if (!state || !input) return;
  input.value = "";
  state.search = "";
  fetchLibraryTable(section);
}

function sortTable(section, column) {
  const state = tableStates[section];
  if (!state) return;
  if (state.sort === column) {
    state.order = state.order === "desc" ? "asc" : "desc";
  } else {
    state.sort = column;
    state.order = "desc";
  }
  updateTableSortHeader(section);
  fetchLibraryTable(section);
}

function updateTableSortHeader(section) {
  const state = tableStates[section];
  if (!state) return;
  document.querySelectorAll(`th[data-table="${section}"][data-col]`).forEach(th => {
    th.classList.remove("sorted");
    const arrow = th.querySelector(".arrow");
    if (arrow) arrow.textContent = "↕";
  });
  const th = document.querySelector(`th[data-table="${section}"][data-col="${state.sort}"]`);
  if (!th) return;
  th.classList.add("sorted");
  const arrow = th.querySelector(".arrow");
  if (arrow) arrow.textContent = state.order === "desc" ? "↓" : "↑";
}

function tableRows(section) {
  return tableData[section] || [];
}

function normalizedSource(source, url = "") {
  const raw = String(source || "").trim().toLowerCase();
  const href = String(url || "").toLowerCase();
  if (raw === "spotify" || href.includes("spotify.com")) return "spotify";
  if (raw === "soundcloud" || href.includes("soundcloud.com")) return "soundcloud";
  if (raw === "youtube" || href.includes("youtu.be") || href.includes("youtube.com")) return "youtube";
  if (!raw && !href) return "none";
  return raw || "other";
}

function platformSvg(source) {
  const src = normalizedSource(source);
  return {
    spotify: `
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <circle cx="12" cy="12" r="10"></circle>
        <path class="cover-glyph-cutout cover-glyph-stroke" d="M7.3 9.4c3.5-1 6.9-.7 9.8 1"></path>
        <path class="cover-glyph-cutout cover-glyph-stroke" d="M8.1 12.2c2.6-.6 5.3-.3 7.5 1"></path>
        <path class="cover-glyph-cutout cover-glyph-stroke" d="M8.9 14.9c1.9-.4 3.9-.2 5.5.6"></path>
      </svg>
    `,
    youtube: `
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M21 12c0 2.6-.3 4.3-.7 5.1-.4.8-1 1.4-1.8 1.8C17.7 19.3 16 19.6 12 19.6s-5.7-.3-6.5-.7c-.8-.4-1.4-1-1.8-1.8C3.3 16.3 3 14.6 3 12s.3-4.3.7-5.1c.4-.8 1-1.4 1.8-1.8C6.3 4.7 8 4.4 12 4.4s5.7.3 6.5.7c.8.4 1.4 1 1.8 1.8.4.8.7 2.5.7 5.1Z"></path>
        <path class="cover-glyph-play" d="M10 8.7 16 12l-6 3.3Z"></path>
      </svg>
    `,
    soundcloud: `
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <path d="M6 18h10.8a3.2 3.2 0 0 0 .4-6.4A4.8 4.8 0 0 0 8 10.7V18Z"></path>
        <path d="M4.2 17.9h1V11.7h-1Z"></path>
        <path d="M2.6 17.9h1V13.2h-1Z"></path>
      </svg>
    `,
    other: `
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <rect x="4" y="5" width="16" height="14" rx="3"></rect>
        <circle class="cover-glyph-cutout" cx="9" cy="10" r="1.6"></circle>
        <path class="cover-glyph-cutout" d="M7 16.2 10.4 13l2.2 2.2 2.2-1.8 2.2 2.8H7Z"></path>
      </svg>
    `,
    none: `<span class="cover-fallback-glyph" aria-hidden="true"></span>`,
  }[src] || `<span class="cover-fallback-text" aria-hidden="true">${esc(src.slice(0, 2).toUpperCase() || "?")}</span>`;
}

function platformLabel(source) {
  return {
    youtube: "YouTube",
    spotify: "Spotify",
    soundcloud: "SoundCloud",
    other: "Altro",
    none: "-",
  }[normalizedSource(source)] || "Altro";
}

function sourceBadge(source, url = "") {
  const src = normalizedSource(source, url);
  const label = platformLabel(src);
  return `
    <span class="source-cell source-${esc(src)}" title="${esc(label)}" aria-label="${esc(label)}">
      <span class="platform-icon source-${esc(src)}">${platformSvg(src)}</span>
      <span class="source-cell-label">${esc(label)}</span>
    </span>
  `;
}

function actionIcon(source) {
  const src = normalizedSource(source);
  return `<span class="platform-icon icon-${esc(src)}">${platformSvg(src)}</span>`;
}

function makeActionLink(url, source, title) {
  url = safeHttpUrl(url);
  const src = normalizedSource(source, url);
  const aria = esc(title || src);
  if (url) {
    return `<a class="icon-btn platform-btn icon-${esc(src)}" href="${esc(url)}" target="_blank" rel="noopener noreferrer" title="${aria}" aria-label="${aria}">${actionIcon(src)}</a>`;
  }
  return `<span class="icon-btn platform-btn icon-${esc(src)} disabled" title="${aria} (non disponibile)" aria-label="${aria} non disponibile" aria-disabled="true">${actionIcon(src)}</span>`;
}

function actionLinks(row) {
  const youtubeUrl = normalizedSource("", row.webpage_url) === "youtube" ? row.webpage_url : "";
  const spotifyUrl = row.spotify_url || "";
  const soundcloudUrl = normalizedSource("", row.webpage_url) === "soundcloud" ? row.webpage_url : "";
  return [
    makeActionLink(youtubeUrl, "youtube", "Apri su YouTube"),
    makeActionLink(spotifyUrl, "spotify", "Apri su Spotify"),
    makeActionLink(soundcloudUrl, "soundcloud", "Apri su SoundCloud"),
  ].join("");
}

function patchRowActions(tr, song) {
  const actionsDiv = tr.querySelector(".row-actions");
  if (!actionsDiv) return;
  const delBtn = actionsDiv.querySelector(".del-btn");
  actionsDiv.innerHTML = actionLinks(song);
  if (delBtn) actionsDiv.appendChild(delBtn);
}

function buildSongRow(song, index = 0) {
  const badge = song.is_valid ? `<span class="badge ok">valida</span>` : `<span class="badge err">invalida</span>`;
  const duration = song.duration ? fmtDuration(song.duration) : "-";
  const thumbHtml = song.thumbnail
    ? `<img class="thumb" src="${esc(song.thumbnail)}" loading="lazy" onerror="this.replaceWith(makePlaceholder())">`
    : `<div class="thumb-placeholder">ART</div>`;
  const coverSource = song.thumbnail_source || inferCoverSource(song) || normalizedSource(song.source, song.webpage_url);

  const tr = document.createElement("tr");
  tr._song = song;
  tr._signature = JSON.stringify(song);
  tr.dataset.id = song.id;
  tr.innerHTML = `
    <td class="id-col">${song.id}</td>
    <td>
      <div style="display:flex;align-items:center;gap:10px">
        ${thumbHtml}
        <div>
          <button class="title-text song-details" type="button">${esc(song.title || "")}</button>
          <div class="artist-text">${esc(song.artist || "")}</div>
        </div>
      </div>
    </td>
    <td>
      <button type="button" class="query-cell" title="${esc(song.query_raw || "")}">
        ${esc(song.query_raw || "")}
      </button>
    </td>
    <td>${sourceBadge(song.source, song.webpage_url)}</td>
    <td>${coverBadge(coverSource, song.thumbnail_confidence)}</td>
    <td class="dim" style="text-align:center">${duration}</td>
    <td class="hits-num" style="text-align:center">${song.hit_count ?? 0}</td>
    <td class="dim">${fmtTs(song.created_at)}</td>
    <td class="dim">${fmtTs(song.last_used)}</td>
    <td>${badge}</td>
    <td>
      <div class="row-actions">
        ${actionLinks(song)}
        <button class="icon-btn del-btn" title="Elimina" aria-label="Elimina" onclick="deleteSong(${song.id})">&times;</button>
      </div>
    </td>
  `;
  tr.querySelector(".song-details").addEventListener("click", () => openModal(tr._song));
  tr.querySelector(".query-cell").addEventListener("click", () => setSearch(tr._song.query_raw || ""));
  return tr;
}

function renderSongs(data) {
  const tbody = document.getElementById("songs-body");
  if (!tbody) return;
  tbody.innerHTML = "";
  data.forEach((song, index) => tbody.appendChild(buildSongRow(song, index)));
  lastSongIds = new Set(data.map(song => song.id));
  lastSongUrls = new Map(data.map(song => [song.id, { webpage_url: song.webpage_url, spotify_url: song.spotify_url }]));
}

function renderSongsDiff(data) {
  const tbody = document.getElementById("songs-body");
  if (!tbody) return;
  const existing = new Map([...tbody.children].map(row => [Number(row.dataset.id), row]));
  const wanted = new Set(data.map(song => song.id));
  for (const [id, row] of existing) if (!wanted.has(id)) row.remove();
  data.forEach((song, index) => {
    let row = existing.get(song.id);
    const signature = JSON.stringify(song);
    if (!row) row = buildSongRow(song, index);
    else if (row._signature !== signature) {
      const next = buildSongRow(song, index);
      // Patch only changed cells: preserve unchanged buttons, focus and images.
      [...next.children].forEach((cell, i) => {
        if (row.children[i].innerHTML !== cell.innerHTML) row.children[i].replaceWith(cell);
      });
      row._song = song;
      row._signature = signature;
    }
    if (tbody.children[index] !== row) tbody.insertBefore(row, tbody.children[index] || null);
  });
  lastSongIds = wanted;
  lastSongUrls = new Map(data.map(song => [song.id, {webpage_url:song.webpage_url,spotify_url:song.spotify_url}]));
}

function setSearch(value) {
  const input = document.getElementById("search-input");
  if (!input) return;
  input.value = value;
  fetchSongs(false);
}

function sortBy(column) {
  if (currentSort === column) {
    currentOrder = currentOrder === "desc" ? "asc" : "desc";
  } else {
    currentSort = column;
    currentOrder = "desc";
  }
  document.querySelectorAll("#songs-table th[data-col]").forEach(th => {
    th.classList.remove("sorted");
    const arrow = th.querySelector(".arrow");
    if (arrow) arrow.textContent = "↕";
  });
  const currentHeader = document.querySelector(`#songs-table th[data-col="${column}"]`);
  if (currentHeader) {
    currentHeader.classList.add("sorted");
    const arrow = currentHeader.querySelector(".arrow");
    if (arrow) arrow.textContent = currentOrder === "desc" ? "↓" : "↑";
  }
  fetchSongs(false);
}

function clearFilters() {
  const search = document.getElementById("search-input");
  const source = document.getElementById("filter-source");
  const valid = document.getElementById("filter-valid");
  if (search) search.value = "";
  if (source) source.value = "";
  if (valid) valid.value = "";
  currentSort = "created_at";
  currentOrder = "desc";
  document.querySelectorAll("#songs-table th[data-col]").forEach(th => {
    th.classList.remove("sorted");
    const arrow = th.querySelector(".arrow");
    if (arrow) arrow.textContent = "↕";
  });
  const createdHeader = document.querySelector(`#songs-table th[data-col="created_at"]`);
  if (createdHeader) {
    createdHeader.classList.add("sorted");
    const arrow = createdHeader.querySelector(".arrow");
    if (arrow) arrow.textContent = "↓";
  }
  fetchSongs(false);
}

function showSkeleton() {
  const tbody = document.getElementById("songs-body");
  if (!tbody) return;
  const widths = [30, 140, 90, 60, 52, 40, 30, 80, 80, 55, 50];
  tbody.innerHTML = Array.from({ length: 6 }).map(() =>
    `<tr>${widths.map(width => `<td><div class="skeleton" style="width:${width}px;height:13px"></div></td>`).join("")}</tr>`
  ).join("");
}

function hideSkeleton() {
  document.querySelectorAll(".skeleton").forEach(el => el.closest("tr")?.remove());
}

function refreshLoadedSections() {
  loadedSections.forEach(section => {
    const loader = sectionLoaders[section];
    if (loader) loader();
  });
  if (currentSection === "cache") {
    fetchSongs(false);
  }
}

function markSectionsStaleAfterDelete(activeSection) {
  Object.keys(sectionLoaders).forEach(section => {
    if (section === activeSection || section === "schema") return;
    loadedSections.delete(section);
  });
}

function preserveScrollDuring(callback) {
  const x = window.scrollX;
  const y = window.scrollY;
  const restore = () => window.scrollTo(x, y);
  const result = callback();
  requestAnimationFrame(restore);
  setTimeout(restore, 260);
  return result;
}

function captureScrollSnapshot() {
  return { x: window.scrollX, y: window.scrollY };
}

function restoreScrollSnapshot(snapshot) {
  if (!snapshot) return;
  const restore = () => window.scrollTo(snapshot.x, snapshot.y);
  requestAnimationFrame(restore);
  setTimeout(restore, 260);
}

function remapId(value, map) {
  const key = String(value);
  return Object.prototype.hasOwnProperty.call(map || {}, key) ? Number(map[key]) : value;
}

function applyCompactMaps(compact) {
  const trackMap = compact?.track_id_map || {};
  const sourceMap = compact?.source_id_map || {};
  const queryMap = compact?.query_id_map || {};

  tableData.tracks = tableData.tracks.map(row => ({ ...row, id: remapId(row.id, trackMap) }));
  tableData.sources = tableData.sources.map(row => ({
    ...row,
    id: remapId(row.id, sourceMap),
    track_id: remapId(row.track_id, trackMap),
  }));
  tableData.queries = tableData.queries.map(row => ({
    ...row,
    id: remapId(row.id, queryMap),
    track_id: remapId(row.track_id, trackMap),
    source_id: remapId(row.source_id, sourceMap),
  }));
  tableData.aliases = tableData.aliases.map(row => ({
    ...row,
    id: remapId(row.id, queryMap),
    cache_id: remapId(row.cache_id, sourceMap),
  }));

  if (tableData[currentSection]) {
    renderStoredTable(currentSection);
  }

  const remappedSongIds = new Set();
  const remappedSongUrls = new Map();
  lastSongUrls.forEach((value, id) => {
    const nextId = remapId(id, sourceMap);
    remappedSongIds.add(nextId);
    remappedSongUrls.set(nextId, value);
  });
  lastSongIds = remappedSongIds;
  lastSongUrls = remappedSongUrls;

  document.querySelectorAll("#songs-body tr[data-id]").forEach(tr => {
    if (tr.dataset.deleting === "1") return;
    const oldId = Number(tr.dataset.id);
    const newId = remapId(oldId, sourceMap);
    if (Number(newId) === oldId) return;
    tr.dataset.id = String(newId);
    const idCell = tr.querySelector(".id-col");
    if (idCell) {
      idCell.textContent = String(newId);
      idCell.classList.remove("flash");
      void idCell.offsetWidth;
      idCell.classList.add("flash");
      idCell.addEventListener("animationend", () => idCell.classList.remove("flash"), { once: true });
    }
    const delBtn = tr.querySelector(".del-btn");
    if (delBtn) delBtn.setAttribute("onclick", `deleteSong(${newId})`);
  });
}

function removeDashboardRow(section, id) {
  if (section === "cache") {
    const row = document.querySelector(`#songs-body tr[data-id="${id}"]`);
    lastSongIds.delete(id);
    lastSongUrls.delete(id);
    if (row) {
      row.dataset.deleting = "1";
      row.dataset.id = `deleted-${id}`;
      row.style.transition = "opacity .2s, transform .2s";
      row.style.opacity = "0";
      row.style.transform = "translateX(16px)";
      setTimeout(() => row.remove(), 220);
    }
    return;
  }

  if (tableData[section]) {
    tableData[section] = tableData[section].filter(row => Number(row.id) !== Number(id));
    renderStoredTable(section);
  }
}

function deleteSong(id) {
  fetch("/api/delete/" + id, { method: "DELETE" })
    .then(readJson)
    .then(data => {
      if (!data.ok) throw new Error("delete failed");
      preserveScrollDuring(() => {
        removeDashboardRow("cache", id);
        applyCompactMaps(data.compact);
        markSectionsStaleAfterDelete("cache");
        showToast("Entry eliminata", "success");
        closeModal();
      });
    })
    .catch(() => showToast("Errore durante l'eliminazione", "error"));
}

function deleteTrack(id) {
  fetch("/api/tracks/" + id, { method: "DELETE" })
    .then(readJson)
    .then(data => {
      if (!data.ok) throw new Error("delete track failed");
      preserveScrollDuring(() => {
        showToast("Traccia canonica eliminata", "success");
        removeDashboardRow("tracks", id);
        applyCompactMaps(data.compact);
        markSectionsStaleAfterDelete("tracks");
      });
    })
    .catch(() => showToast("Errore durante l'eliminazione traccia", "error"));
}

function deleteSource(id) {
  fetch("/api/sources/" + id, { method: "DELETE" })
    .then(readJson)
    .then(data => {
      if (!data.ok) throw new Error("delete source failed");
      preserveScrollDuring(() => {
        showToast("Sorgente eliminata", "success");
        removeDashboardRow("sources", id);
        applyCompactMaps(data.compact);
        markSectionsStaleAfterDelete("sources");
      });
    })
    .catch(() => showToast("Errore durante l'eliminazione sorgente", "error"));
}

function deleteAlias(id) {
  fetch("/api/aliases/" + id, { method: "DELETE" })
    .then(readJson)
    .then(data => {
      if (!data.ok) throw new Error("delete alias failed");
      preserveScrollDuring(() => {
        showToast("Alias eliminato", "success");
        removeDashboardRow("aliases", id);
        applyCompactMaps(data.compact);
        markSectionsStaleAfterDelete("aliases");
      });
    })
    .catch(() => showToast("Errore durante l'eliminazione alias", "error"));
}

function deleteQuery(id) {
  fetch("/api/queries/" + id, { method: "DELETE" })
    .then(readJson)
    .then(data => {
      if (!data.ok) throw new Error("delete query failed");
      preserveScrollDuring(() => {
        showToast("Query eliminata", "success");
        removeDashboardRow("queries", id);
        applyCompactMaps(data.compact);
        markSectionsStaleAfterDelete("queries");
      });
    })
    .catch(() => showToast("Errore durante l'eliminazione query", "error"));
}

function openModal(song) {
  modalTrigger = document.activeElement;
  const thumbHtml = song.thumbnail ? `<img class="modal-thumb" src="${esc(song.thumbnail)}">` : "";
  document.getElementById("modal-content").innerHTML = `
    ${thumbHtml}
    <h3>${esc(song.title || "")}</h3>
    <div class="modal-artist" style="clear:none">${esc(song.artist || "")}</div>
    <div style="clear:both;margin-bottom:4px"></div>
    ${modalRow("ID", song.id)}
    ${modalRow("Query", esc(song.query_raw))}
    ${modalRow("Sorgente", esc(song.source))}
    ${modalRow("Durata", song.duration ? fmtDuration(song.duration) : "-")}
    ${modalRow("Hits", `<span style="color:var(--yellow);font-weight:700">${song.hit_count ?? 0}</span>`)}
    ${modalRow("Stato", song.is_valid ? `<span class="badge ok">valida</span>` : `<span class="badge err">invalida</span>`)}
    ${modalRow("Creata", fmtTs(song.created_at))}
    ${modalRow("Ultima usata", fmtTs(song.last_used))}
    ${safeHttpUrl(song.webpage_url) ? modalRow("Link", `<a class="modal-link" href="${esc(safeHttpUrl(song.webpage_url))}" target="_blank" rel="noopener noreferrer">${esc(song.webpage_url)}</a>`) : ""}
    ${safeHttpUrl(song.spotify_url) ? modalRow("Spotify", `<a class="modal-link" href="${esc(safeHttpUrl(song.spotify_url))}" target="_blank" rel="noopener noreferrer">${esc(song.spotify_url)}</a>`) : ""}
    ${modalRow("Cover", coverBadge(song.thumbnail_source || inferCoverSource(song), song.thumbnail_confidence))}
    <div class="modal-actions">
      <button class="btn btn-danger" onclick="deleteSong(${song.id})">Elimina</button>
      <button class="btn btn-ghost" onclick="closeModal()">Chiudi</button>
    </div>
  `;
  document.getElementById("modal-bg").classList.add("open");
  document.querySelector(".modal .close").focus();
}

function modalRow(key, value) {
  return `<div class="modal-row"><span class="modal-key">${key}</span><span class="modal-val">${value}</span></div>`;
}

function closeModal() {
  document.getElementById("modal-bg").classList.remove("open");
  modalTrigger?.focus();
}

document.addEventListener("keydown", event => {
  if (!document.getElementById("modal-bg")?.classList.contains("open")) return;
  if (event.key === "Escape") closeModal();
  if (event.key !== "Tab") return;
  const elements = document.querySelectorAll('.modal button, .modal a[href], .modal input');
  const first = elements[0], last = elements[elements.length - 1];
  if (event.shiftKey && document.activeElement === first) { event.preventDefault(); last.focus(); }
  else if (!event.shiftKey && document.activeElement === last) { event.preventDefault(); first.focus(); }
});

document.getElementById("modal-bg")?.addEventListener("click", event => {
  if (event.target === document.getElementById("modal-bg")) {
    closeModal();
  }
});

function renderStoredTable(section) {
  const rows = tableRows(section);
  updateTableSortHeader(section);
  if (section === "aliases") {
    renderSimpleTable("aliases-body", rows, 6, (alias, index) => `
      <td class="id-col">${alias.id}</td>
      <td class="dim">${esc(alias.query_raw || "")}</td>
      <td><span class="badge ${esc(alias.alias_type || "text")}">${esc(alias.alias_type || "text")}</span></td>
      <td>
        <span class="title-text">${esc(alias.title || "")}</span>
        <span class="artist-text">${esc(alias.artist || "")}</span>
      </td>
      <td class="id-col">${alias.cache_id}</td>
      <td>
        <div class="row-actions">
          ${actionLinks(alias)}
          <button class="icon-btn del-btn" title="Elimina alias" aria-label="Elimina alias" onclick="deleteAlias(${alias.id})">&times;</button>
        </div>
      </td>
    `, "Nessun alias registrato.");
    return;
  }
  if (section === "tracks") {
    renderSimpleTable("tracks-body", rows, 9, row => `
      <td class="id-col">${row.id}</td>
      <td><span class="title-text">${esc(row.canonical_title || "")}</span></td>
      <td><span class="artist-text">${esc(row.canonical_artist || "")}</span></td>
      <td class="dim mono">${esc(row.normalized_query || "")}</td>
      <td class="id-col">${row.source_count ?? 0}</td>
      <td class="id-col">${row.query_count ?? 0}</td>
      <td class="dim">${fmtTs(row.created_at)}</td>
      <td class="dim">${fmtTs(row.updated_at)}</td>
      <td><div class="row-actions"><button class="icon-btn del-btn" title="Elimina traccia canonica" aria-label="Elimina traccia canonica" onclick="deleteTrack(${row.id})">&times;</button></div></td>
    `, "Nessuna traccia canonica registrata.");
    return;
  }
  if (section === "sources") {
    renderSimpleTable("sources-body", rows, 11, row => `
      <td class="id-col">${row.id}</td>
      <td class="id-col">${row.track_id}</td>
      <td>
        <span class="title-text">${esc(row.canonical_title || "")}</span>
        <span class="artist-text">${esc(row.canonical_artist || "")}</span>
      </td>
      <td>${sourceBadge(row.source, row.webpage_url)}</td>
      <td>
        <span class="title-text">${esc(row.resolved_title || "")}</span>
        <span class="artist-text">${esc(row.resolved_artist || "")}</span>
      </td>
      <td>${coverBadge(row.thumbnail_source || inferCoverSource(row) || normalizedSource(row.source, row.webpage_url), row.thumbnail_confidence)}</td>
      <td class="dim">${row.duration ? fmtDuration(row.duration) : "-"}</td>
      <td class="hits-num">${row.hit_count ?? 0}</td>
      <td>${row.is_valid ? `<span class="badge ok">valida</span>` : `<span class="badge err">invalida</span>`}</td>
      <td class="dim">${fmtTs(row.last_used)}</td>
      <td><div class="row-actions">${actionLinks(row)}<button class="icon-btn del-btn" title="Elimina sorgente" aria-label="Elimina sorgente" onclick="deleteSource(${row.id})">&times;</button></div></td>
    `, "Nessuna sorgente risolta registrata.");
    return;
  }
  if (section === "queries") {
    renderSimpleTable("queries-body", rows, 9, row => `
      <td class="id-col">${row.id}</td>
      <td class="dim">T${row.track_id} / S${row.source_id}</td>
      <td>
        <div class="query-cell" title="${esc(row.query_raw || "")}">${esc(row.query_raw || "")}</div>
        <div class="artist-text">${esc(row.canonical_title || "")} · ${esc(row.canonical_artist || "")}</div>
      </td>
      <td><span class="badge ${esc(row.alias_type || "text")}">${esc(row.alias_type || "text")}</span></td>
      <td class="dim">${fmtConfidence(row.confidence)}</td>
      <td class="hits-num">${row.hit_count ?? 0}</td>
      <td>${row.is_active ? `<span class="badge ok">attiva</span>` : `<span class="badge err">disattiva</span>`}</td>
      <td class="dim">${fmtTs(row.last_seen)}</td>
      <td><div class="row-actions">${actionLinks(row)}<button class="icon-btn del-btn" title="Elimina query" aria-label="Elimina query" onclick="deleteQuery(${row.id})">&times;</button></div></td>
    `, "Nessuna query osservata registrata.");
  }
}

function fetchAliases(silent = false) {
  return fetchLibraryTable("aliases", silent);
}

function fetchTracks(silent = false) {
  return fetchLibraryTable("tracks", silent);
}

function fetchSources(silent = false) {
  return fetchLibraryTable("sources", silent);
}

function fetchQueries(silent = false) {
  return fetchLibraryTable("queries", silent);
}

function fetchSchema() {
  fetch("/api/schema")
    .then(readJson)
    .then(data => {
      const grid = document.getElementById("schema-grid");
      if (!grid) return;
      grid.innerHTML = data.map(item => `
        <article class="schema-card schema-card-${esc(item.kind)}">
          <div class="schema-card-top">
            <span class="schema-kind">${esc(item.kind)}</span>
            <span class="schema-count">${Number(item.count ?? 0).toLocaleString("it-IT")} righe</span>
          </div>
          <h3>${esc(item.name)}</h3>
          <p>${esc(item.purpose || "")}</p>
          <div class="schema-meta">PK: <code>${esc(item.pk || "-")}</code></div>
        </article>
      `).join("");
      loadedSections.add("schema");
      document.getElementById("library-update").hidden = true;
    })
    .catch(() => showToast("Errore nel caricamento struttura database", "error"));
}

function renderSimpleTable(bodyId, data, colSpan, rowBuilder, emptyMessage) {
  const tbody = document.getElementById(bodyId);
  if (!tbody) return;
  if (!data.length) {
    tbody.innerHTML = `<tr><td colspan="${colSpan}" style="text-align:center;padding:32px;color:var(--muted)">${emptyMessage}</td></tr>`;
    return;
  }
  const existing = new Map([...tbody.children].map(row => [row.dataset.id, row]));
  const wanted = new Set(data.map(row => String(row.id)));
  for (const [id, row] of existing) if (!wanted.has(id)) row.remove();
  data.forEach((item, index) => {
    const id = String(item.id), html = rowBuilder(item);
    let row = existing.get(id);
    if (!row) { row = document.createElement('tr'); row.dataset.id = id; }
    if (row._html !== html) { row.innerHTML = html; row._html = html; }
    if (tbody.children[index] !== row) tbody.insertBefore(row, tbody.children[index] || null);
  });
}

function showSection(section, el) {
  if (section === currentSection) return;
  currentSection = section;
  renderPagination();
  document.querySelectorAll("nav a").forEach(anchor => anchor.classList.remove("active"));
  el.classList.add("active");
  document.querySelectorAll("nav a").forEach(anchor => anchor.removeAttribute("aria-current"));
  el.setAttribute("aria-current", "page");
  document.getElementById("section-summary").textContent = el.textContent.trim();

  ["cache", "aliases", "tracks", "sources", "queries", "schema"].forEach(name => {
    const target = document.getElementById(`${name}-section`);
    if (target) {
      target.style.display = name === section ? "grid" : "none";
      if (name === section && !matchMedia('(prefers-reduced-motion: reduce)').matches) {
        target.getAnimations().forEach(animation => animation.cancel());
        target.animate([{opacity:.25,transform:'translateY(5px)'},{opacity:1,transform:'translateY(0)'}],
          {duration:220,easing:'cubic-bezier(.2,.7,.2,1)'});
      }
    }
  });

  const loader = sectionLoaders[section];
  if (!loader) return;
  if (section === "cache" || !loadedSections.has(section)) {
    loader();
  }
}

function showToast(message, type = "success") {
  const container = document.getElementById("toast-container");
  if (!container) return;
  const icon = type === "success" ? "OK" : "ERR";
  const el = document.createElement("div");
  el.className = `toast ${type}`;
  el.innerHTML = `<span>${icon}</span> ${esc(message)}`;
  container.appendChild(el);
  setTimeout(() => {
    el.style.animation = "toastOut .3s ease forwards";
    setTimeout(() => el.remove(), 300);
  }, 2800);
}

function inferCoverSource(row) {
  const thumb = String(row.thumbnail || "").toLowerCase();
  if (!thumb) return "none";
  if (thumb.includes("i.scdn.co")) return "spotify";
  if (thumb.includes("ytimg.com") || thumb.includes("googleusercontent.com")) return "youtube";
  if (thumb.includes("sndcdn.com") || thumb.includes("soundcloud.com")) return "soundcloud";
  return "other";
}

function coverBadge(source, confidence) {
  const src = normalizedSource(source);
  const pct = confidence ? `${Math.round(Number(confidence) * 100)}%` : "";
  const title = src === "none" ? "Nessuna cover" : `Cover ${src}${pct ? `, confidence ${pct}` : ""}`;
  return `<span class="cover-badge cover-${esc(src)}" title="${esc(title)}" aria-label="${esc(title)}">${platformSvg(src)}</span>`;
}

function fmtDuration(sec) {
  if (!sec) return "-";
  const minutes = Math.floor(sec / 60);
  const seconds = sec % 60;
  return minutes + ":" + String(seconds).padStart(2, "0");
}

function fmtTs(ts) {
  if (!ts) return "-";
  const date = typeof ts === "number" ? new Date(ts * 1000) : new Date(ts);
  if (Number.isNaN(date.getTime())) return esc(String(ts).slice(0, 16));
  return date.toLocaleDateString("it-IT") + " " + date.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit" });
}

function fmtConfidence(value) {
  if (value === null || value === undefined || value === "") return "-";
  const num = Number(value);
  if (Number.isNaN(num)) return esc(value);
  return num.toFixed(2);
}

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function safeHttpUrl(value) {
  try {
    const url = new URL(String(value || ""));
    return ["https:", "http:"].includes(url.protocol) ? url.href : "";
  } catch (_) { return ""; }
}

function makePlaceholder() {
  const div = document.createElement("div");
  div.className = "thumb-placeholder";
  div.textContent = "ART";
  return div;
}
