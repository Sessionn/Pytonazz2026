let currentSort = "hit_count";
let currentOrder = "desc";
let currentSection = "cache";
let debounceTimer;
let autoRefreshInterval = null;
let statsRefreshInterval = null;
let statsEventSource = null;
let lastSongIds = new Set();
let lastSongUrls = new Map();
const loadedSections = new Set();

const sectionLoaders = {
  cache: () => fetchSongs(false),
  aliases: fetchAliases,
  tracks: fetchTracks,
  sources: fetchSources,
  queries: fetchQueries,
  schema: fetchSchema,
};

document.addEventListener("DOMContentLoaded", () => {
  const saved = localStorage.getItem("theme") || "dark";
  document.documentElement.setAttribute("data-theme", saved);
  updateThemeUI(saved);
  normalizeSortArrows();
  animateCounters();
  fetchSongs(false);
  startAutoRefresh(10);
  startStatsRefresh(8);
  startRealtimeStats();
  updateGenTime();
});

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
  localStorage.setItem("theme", nextTheme);
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
  const card = el.closest(".stat-card");
  if (card && from !== to) {
    card.classList.remove("updating");
    void card.offsetWidth;
    card.classList.add("updating");
    card.addEventListener("animationend", () => card.classList.remove("updating"), { once: true });
  }

  const start = performance.now();
  const update = now => {
    const progress = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    el.textContent = Math.round(from + (to - from) * eased).toLocaleString("it-IT");
    if (progress < 1) requestAnimationFrame(update);
  };
  requestAnimationFrame(update);
}

function refreshStats() {
  fetch("/api/stats")
    .then(r => {
      if (!r.ok) throw new Error("stats fetch failed");
      return r.json();
    })
    .then(applyStatsPayload)
    .catch(() => {});
}

function applyStatsPayload(data) {
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
}

function startRealtimeStats() {
  if (!window.EventSource || statsEventSource) return;
  statsEventSource = new EventSource("/api/events");
  statsEventSource.addEventListener("stats", event => {
    try {
      applyStatsPayload(JSON.parse(event.data));
    } catch (_) {}
  });
  statsEventSource.onerror = () => {
    if (statsEventSource) {
      statsEventSource.close();
      statsEventSource = null;
    }
    startStatsRefresh(8);
  };
  stopStatsRefresh();
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

function startAutoRefresh(seconds = 10) {
  stopAutoRefresh();
  autoRefreshInterval = setInterval(() => {
    if (currentSection === "cache") {
      fetchSongs(true);
    }
    refreshStats();
  }, seconds * 1000);
}

function stopAutoRefresh() {
  if (autoRefreshInterval) {
    clearInterval(autoRefreshInterval);
    autoRefreshInterval = null;
  }
}

function fetchSongs(silent = false) {
  const q = document.getElementById("search-input")?.value || "";
  const source = document.getElementById("filter-source")?.value || "";
  const valid = document.getElementById("filter-valid")?.value || "";
  const params = new URLSearchParams({ q, source, valid, sort: currentSort, order: currentOrder });

  if (!silent) showSkeleton();

  fetch("/api/songs?" + params.toString())
    .then(r => r.json())
    .then(data => {
      if (!silent) hideSkeleton();
      if (data.length === 0) {
        const tbody = document.getElementById("songs-body");
        if (tbody) {
          tbody.innerHTML = `<tr><td colspan="11" style="text-align:center;padding:32px;color:var(--muted)">Nessun risultato trovato.</td></tr>`;
        }
        lastSongIds = new Set();
        lastSongUrls = new Map();
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

function makeActionLink(url, label, extraClass, title) {
  const aria = esc(title || label);
  if (url) {
    return `<a class="icon-btn${extraClass ? " " + extraClass : ""}" href="${esc(url)}" target="_blank" title="${aria}" aria-label="${aria}">${label}</a>`;
  }
  return `<span class="icon-btn${extraClass ? " " + extraClass : ""} disabled" title="${aria} (non disponibile)" aria-label="${aria} non disponibile" aria-disabled="true">${label}</span>`;
}

function patchRowActions(tr, song) {
  const actionsDiv = tr.querySelector(".row-actions");
  if (!actionsDiv) return;
  const webLink = makeActionLink(song.webpage_url, "↗", "", "Apri sorgente web");
  const spLink = makeActionLink(song.spotify_url, "♪", "sp", "Apri su Spotify");
  const delBtn = actionsDiv.querySelector(".del-btn");
  actionsDiv.innerHTML = webLink + spLink;
  if (delBtn) actionsDiv.appendChild(delBtn);
}

function buildSongRow(song, index = 0) {
  const src = song.source || "youtube";
  const srcColor = src === "spotify" ? "#1DB954" : "#e5173f";
  const badge = song.is_valid ? `<span class="badge ok">valida</span>` : `<span class="badge err">invalida</span>`;
  const duration = song.duration ? fmtDuration(song.duration) : "-";
  const thumbHtml = song.thumbnail
    ? `<img class="thumb" src="${esc(song.thumbnail)}" loading="lazy" onerror="this.replaceWith(makePlaceholder())">`
    : `<div class="thumb-placeholder">ART</div>`;

  const webLink = makeActionLink(song.webpage_url, "↗", "", "Apri sorgente web");
  const spLink = makeActionLink(song.spotify_url, "♪", "sp", "Apri su Spotify");
  const coverSource = song.thumbnail_source || inferCoverSource(song);

  const tr = document.createElement("tr");
  tr.style.animationDelay = `${index * 28}ms`;
  tr.dataset.id = song.id;
  tr.innerHTML = `
    <td class="id-col">${song.id}</td>
    <td>
      <div style="display:flex;align-items:center;gap:10px">
        ${thumbHtml}
        <div>
          <div class="title-text" onclick='openModal(${JSON.stringify(song)})'>${esc(song.title || "")}</div>
          <div class="artist-text">${esc(song.artist || "")}</div>
        </div>
      </div>
    </td>
    <td>
      <div class="query-cell" title="${esc(song.query_raw || "")}" onclick="setSearch('${esc(song.query_raw || "")}')">
        ${esc(song.query_raw || "")}
      </div>
    </td>
    <td><span class="src-badge" style="background:${srcColor}">${src}</span></td>
    <td>${coverBadge(coverSource, song.thumbnail_confidence)}</td>
    <td class="dim" style="text-align:center">${duration}</td>
    <td class="hits-num" style="text-align:center">${song.hit_count ?? 0}</td>
    <td class="dim">${fmtTs(song.created_at)}</td>
    <td class="dim">${fmtTs(song.last_used)}</td>
    <td>${badge}</td>
    <td>
      <div class="row-actions">
        ${webLink}${spLink}
        <button class="icon-btn del-btn" title="Elimina" aria-label="Elimina" onclick="deleteSong(${song.id})">×</button>
      </div>
    </td>
  `;
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
  const newIds = new Set(data.map(song => song.id));

  document.querySelectorAll("#songs-body tr[data-id]").forEach(tr => {
    if (!newIds.has(parseInt(tr.dataset.id, 10))) {
      tr.style.transition = "opacity .4s, transform .4s";
      tr.style.opacity = "0";
      tr.style.transform = "translateX(20px)";
      setTimeout(() => tr.remove(), 400);
    }
  });

  data.forEach(song => {
    const tr = document.querySelector(`#songs-body tr[data-id="${song.id}"]`);
    if (!tr) return;

    const hitsCell = tr.querySelector(".hits-num");
    if (hitsCell) {
      const oldValue = parseInt(hitsCell.textContent.replace(/\D/g, ""), 10) || 0;
      if (oldValue !== song.hit_count) {
        hitsCell.textContent = song.hit_count ?? 0;
        hitsCell.classList.remove("flash");
        void hitsCell.offsetWidth;
        hitsCell.classList.add("flash");
        hitsCell.addEventListener("animationend", () => hitsCell.classList.remove("flash"), { once: true });
      }
    }

    const prev = lastSongUrls.get(song.id) || {};
    if (prev.webpage_url !== song.webpage_url || prev.spotify_url !== song.spotify_url) {
      patchRowActions(tr, song);
      lastSongUrls.set(song.id, { webpage_url: song.webpage_url, spotify_url: song.spotify_url });
    }
  });

  const addedIds = [...newIds].filter(id => !lastSongIds.has(id));
  lastSongIds = newIds;

  if (addedIds.length > 0) {
    showToast(`+${addedIds.length} nuova traccia in cache`, "success");
    const tbody = document.getElementById("songs-body");
    if (!tbody) return;
    const newSongs = data.filter(song => addedIds.includes(song.id));
    newSongs.forEach(song => {
      const newTr = buildSongRow(song, 0);
      newTr.style.animation = "none";
      tbody.prepend(newTr);
      void newTr.offsetWidth;
      newTr.style.animation = "";
      newTr.classList.add("row-new");
      setTimeout(() => newTr.classList.remove("row-new"), 3000);
    });
    newSongs.forEach(song => lastSongUrls.set(song.id, { webpage_url: song.webpage_url, spotify_url: song.spotify_url }));
  }
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
  document.querySelectorAll("th[data-col]").forEach(th => {
    th.classList.remove("sorted");
    const arrow = th.querySelector(".arrow");
    if (arrow) arrow.textContent = "↕";
  });
  const currentHeader = document.querySelector(`th[data-col="${column}"]`);
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

function deleteSong(id) {
  const tr = document.querySelector(`tr[data-id="${id}"]`);
  fetch("/api/delete/" + id, { method: "DELETE" })
    .then(r => r.json())
    .then(data => {
      if (!data.ok) return;
      if (tr) {
        tr.style.transition = "opacity .3s, transform .3s";
        tr.style.opacity = "0";
        tr.style.transform = "translateX(20px)";
        setTimeout(() => tr.remove(), 300);
      }
      lastSongIds.delete(id);
      lastSongUrls.delete(id);
      showToast("Entry eliminata", "success");
      closeModal();
      setTimeout(refreshStats, 350);
    })
    .catch(() => showToast("Errore durante l'eliminazione", "error"));
}

function deleteAlias(id) {
  const tr = document.querySelector(`tr[data-alias-id="${id}"]`);
  fetch("/api/aliases/" + id, { method: "DELETE" })
    .then(r => r.json())
    .then(data => {
      if (!data.ok) return;
      if (tr) {
        tr.style.transition = "opacity .3s, transform .3s";
        tr.style.opacity = "0";
        tr.style.transform = "translateX(20px)";
        setTimeout(() => tr.remove(), 300);
      }
      showToast("Alias eliminato", "success");
      setTimeout(refreshStats, 350);
    })
    .catch(() => showToast("Errore durante l'eliminazione alias", "error"));
}

function openModal(song) {
  const thumbHtml = song.thumbnail ? `<img class="modal-thumb" src="${esc(song.thumbnail)}">` : "";
  document.getElementById("modal-content").innerHTML = `
    ${thumbHtml}
    <h3>${esc(song.title || "")}</h3>
    <div class="modal-artist" style="clear:none">${esc(song.artist || "")}</div>
    <div style="clear:both;margin-bottom:4px"></div>
    ${modalRow("ID", song.id)}
    ${modalRow("Query", song.query_raw)}
    ${modalRow("Sorgente", song.source)}
    ${modalRow("Durata", song.duration ? fmtDuration(song.duration) : "-")}
    ${modalRow("Hits", `<span style="color:var(--yellow);font-weight:700">${song.hit_count ?? 0}</span>`)}
    ${modalRow("Stato", song.is_valid ? `<span class="badge ok">valida</span>` : `<span class="badge err">invalida</span>`)}
    ${modalRow("Creata", fmtTs(song.created_at))}
    ${modalRow("Ultima usata", fmtTs(song.last_used))}
    ${song.webpage_url ? modalRow("Link", `<a class="modal-link" href="${esc(song.webpage_url)}" target="_blank">${esc(song.webpage_url)}</a>`) : ""}
    ${song.spotify_url ? modalRow("Spotify", `<a class="modal-link" href="${esc(song.spotify_url)}" target="_blank">${esc(song.spotify_url)}</a>`) : ""}
    ${modalRow("Cover", coverBadge(song.thumbnail_source || inferCoverSource(song), song.thumbnail_confidence))}
    <div class="modal-actions">
      <button class="btn btn-danger" onclick="deleteSong(${song.id})">Delete</button>
      <button class="btn btn-ghost" onclick="closeModal()">Chiudi</button>
    </div>
  `;
  document.getElementById("modal-bg").classList.add("open");
}

function modalRow(key, value) {
  return `<div class="modal-row"><span class="modal-key">${key}</span><span class="modal-val">${value}</span></div>`;
}

function closeModal() {
  document.getElementById("modal-bg").classList.remove("open");
}

document.getElementById("modal-bg")?.addEventListener("click", event => {
  if (event.target === document.getElementById("modal-bg")) {
    closeModal();
  }
});

function fetchAliases() {
  fetch("/api/aliases")
    .then(r => r.json())
    .then(data => {
      const tbody = document.getElementById("aliases-body");
      if (!tbody) return;
      if (data.length === 0) {
        tbody.innerHTML = `<tr><td colspan="6" style="text-align:center;padding:32px;color:var(--muted)">Nessun alias registrato.</td></tr>`;
        return;
      }
      tbody.innerHTML = data.map((alias, index) => {
        const webLink = makeActionLink(alias.webpage_url, "↗", "", "Apri sorgente web");
        const spLink = makeActionLink(alias.spotify_url, "♪", "sp", "Apri su Spotify");
        return `
          <tr style="animation-delay:${index * 25}ms" data-alias-id="${alias.id}">
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
                ${webLink}${spLink}
                <button class="icon-btn del-btn" title="Elimina alias" aria-label="Elimina alias" onclick="deleteAlias(${alias.id})">×</button>
              </div>
            </td>
          </tr>`;
      }).join("");
      loadedSections.add("aliases");
    });
}

function fetchTracks() {
  fetch("/api/tracks")
    .then(r => r.json())
    .then(data => {
      renderSimpleTable("tracks-body", data, 8, row => `
        <td class="id-col">${row.id}</td>
        <td><span class="title-text">${esc(row.canonical_title || "")}</span></td>
        <td><span class="artist-text">${esc(row.canonical_artist || "")}</span></td>
        <td class="dim mono">${esc(row.normalized_query || "")}</td>
        <td class="id-col">${row.source_count ?? 0}</td>
        <td class="id-col">${row.query_count ?? 0}</td>
        <td class="dim">${fmtTs(row.created_at)}</td>
        <td class="dim">${fmtTs(row.updated_at)}</td>
      `, "Nessuna traccia canonica registrata.");
      loadedSections.add("tracks");
    });
}

function fetchSources() {
  fetch("/api/sources")
    .then(r => r.json())
    .then(data => {
      renderSimpleTable("sources-body", data, 10, row => `
        <td class="id-col">${row.id}</td>
        <td class="id-col">${row.track_id}</td>
        <td>
          <span class="title-text">${esc(row.canonical_title || "")}</span>
          <span class="artist-text">${esc(row.canonical_artist || "")}</span>
        </td>
        <td><span class="src-badge" style="background:${row.source === "spotify" ? "#1DB954" : "#e5173f"}">${esc(row.source || "-")}</span></td>
        <td>
          <span class="title-text">${esc(row.resolved_title || "")}</span>
          <span class="artist-text">${esc(row.resolved_artist || "")}</span>
        </td>
        <td>${coverBadge(row.thumbnail_source || inferCoverSource(row), row.thumbnail_confidence)}</td>
        <td class="dim">${row.duration ? fmtDuration(row.duration) : "-"}</td>
        <td class="hits-num">${row.hit_count ?? 0}</td>
        <td>${row.is_valid ? `<span class="badge ok">valida</span>` : `<span class="badge err">invalida</span>`}</td>
        <td class="dim">${fmtTs(row.last_used)}</td>
      `, "Nessuna sorgente risolta registrata.");
      loadedSections.add("sources");
    });
}

function fetchQueries() {
  fetch("/api/queries")
    .then(r => r.json())
    .then(data => {
      renderSimpleTable("queries-body", data, 8, row => `
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
      `, "Nessuna query osservata registrata.");
      loadedSections.add("queries");
    });
}

function fetchSchema() {
  fetch("/api/schema")
    .then(r => r.json())
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
    });
}

function renderSimpleTable(bodyId, data, colSpan, rowBuilder, emptyMessage) {
  const tbody = document.getElementById(bodyId);
  if (!tbody) return;
  if (!data.length) {
    tbody.innerHTML = `<tr><td colspan="${colSpan}" style="text-align:center;padding:32px;color:var(--muted)">${emptyMessage}</td></tr>`;
    return;
  }
  tbody.innerHTML = data.map((row, index) => `
    <tr style="animation-delay:${index * 18}ms">
      ${rowBuilder(row)}
    </tr>
  `).join("");
}

function showSection(section, el) {
  currentSection = section;
  document.querySelectorAll("nav a").forEach(anchor => anchor.classList.remove("active"));
  el.classList.add("active");

  ["cache", "aliases", "tracks", "sources", "queries", "schema"].forEach(name => {
    const target = document.getElementById(`${name}-section`);
    if (target) target.style.display = name === section ? "grid" : "none";
  });

  if (section === "cache") {
    startAutoRefresh(10);
    startStatsRefresh(8);
  } else {
    stopAutoRefresh();
    stopStatsRefresh();
  }

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
  el.innerHTML = `<span>${icon}</span> ${message}`;
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
  return "other";
}

function coverBadge(source, confidence) {
  const src = String(source || "none").toLowerCase();
  const pct = confidence ? `${Math.round(Number(confidence) * 100)}%` : "";
  const title = src === "none" ? "Nessuna cover" : `Cover ${src}${pct ? `, confidence ${pct}` : ""}`;
  const icon = {
    spotify: `
      <svg viewBox="0 0 24 24" aria-hidden="true" focusable="false">
        <circle cx="12" cy="12" r="10"></circle>
        <path d="M7.2 9.3c3.4-1 6.9-.8 10 1"></path>
        <path d="M8 12.1c2.8-.7 5.7-.5 8 1"></path>
        <path d="M8.8 14.8c2.1-.5 4.2-.3 5.9.7"></path>
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
  }[src] || `
    <span class="cover-fallback-text" aria-hidden="true">${esc(src.slice(0, 2).toUpperCase() || "?")}</span>
  `;
  return `<span class="cover-badge cover-${esc(src)}" title="${esc(title)}" aria-label="${esc(title)}">${icon}</span>`;
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
  if (Number.isNaN(date.getTime())) return String(ts).slice(0, 16);
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
    .replace(/"/g, "&quot;");
}

function makePlaceholder() {
  const div = document.createElement("div");
  div.className = "thumb-placeholder";
  div.textContent = "ART";
  return div;
}
