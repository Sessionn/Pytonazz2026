"use strict";

/* ==========================================================================
   Pytonazz · Cache console
   - Nessun handler inline: tutti gli eventi passano da delegazione, cosi'
     titoli/query provenienti da YouTube o da Discord non possono iniettare JS
     (la CSP del backend blocca comunque script inline).
   - Ogni valore dinamico passa da esc() / safeUrl() prima di finire in HTML.
   ========================================================================== */

const PAGE_SIZE = 50;
const LIVE_REFRESH_DEBOUNCE_MS = 450;
const POLL_INTERVAL_MS = 10000;
const DELETE_CONFIRM_MS = 3000;

const $ = (selector, root = document) => root.querySelector(selector);
const $$ = (selector, root = document) => Array.from(root.querySelectorAll(selector));

/* ── Formattazione ──────────────────────────────────────────────────────── */

function esc(value) {
  return String(value ?? "")
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

function safeUrl(value) {
  const raw = String(value || "").trim();
  return /^https?:\/\//i.test(raw) ? raw : "";
}

const numberFormat = new Intl.NumberFormat("it-IT");
function fmtNumber(value) {
  return numberFormat.format(Number(value) || 0);
}

function fmtDuration(seconds) {
  const total = Math.round(Number(seconds) || 0);
  if (!total) return "–";
  const h = Math.floor(total / 3600);
  const m = Math.floor((total % 3600) / 60);
  const s = String(total % 60).padStart(2, "0");
  return h ? `${h}:${String(m).padStart(2, "0")}:${s}` : `${m}:${s}`;
}

function toDate(ts) {
  if (ts === null || ts === undefined || ts === "") return null;
  const numeric = Number(ts);
  const date = Number.isFinite(numeric) && String(ts).trim() !== "" ? new Date(numeric * 1000) : new Date(ts);
  return Number.isNaN(date.getTime()) ? null : date;
}

const relativeFormat = new Intl.RelativeTimeFormat("it-IT", { numeric: "auto" });
function fmtRelative(ts) {
  const date = toDate(ts);
  if (!date) return "–";
  const diff = (date.getTime() - Date.now()) / 1000;
  const abs = Math.abs(diff);
  if (abs < 45) return "adesso";
  if (abs < 3600) return relativeFormat.format(Math.round(diff / 60), "minute");
  if (abs < 86400) return relativeFormat.format(Math.round(diff / 3600), "hour");
  if (abs < 86400 * 7) return relativeFormat.format(Math.round(diff / 86400), "day");
  return date.toLocaleDateString("it-IT", { day: "2-digit", month: "short", year: "numeric" });
}

function fmtTimestamp(ts) {
  const date = toDate(ts);
  if (!date) return "–";
  return date.toLocaleString("it-IT", { dateStyle: "medium", timeStyle: "short" });
}

function timeCell(ts) {
  return `<span class="cell-muted" title="${esc(fmtTimestamp(ts))}">${esc(fmtRelative(ts))}</span>`;
}

/* ── Piattaforme ────────────────────────────────────────────────────────── */

function normalizedSource(source, url = "") {
  const raw = String(source || "").trim().toLowerCase();
  const href = String(url || "").toLowerCase();
  if (raw === "spotify" || href.includes("spotify.com")) return "spotify";
  if (raw === "soundcloud" || href.includes("soundcloud.com")) return "soundcloud";
  if (raw === "youtube" || href.includes("youtu.be") || href.includes("youtube.com")) return "youtube";
  if (!raw && !href) return "none";
  return "other";
}

const PLATFORM_LABELS = { youtube: "YouTube", spotify: "Spotify", soundcloud: "SoundCloud", other: "Altro", none: "–" };
const PLATFORM_COLORS = { youtube: "var(--youtube)", spotify: "var(--spotify)", soundcloud: "var(--soundcloud)", other: "var(--text-subtle)" };

const PLATFORM_SVG = {
  youtube: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M21.6 7.2a2.6 2.6 0 0 0-1.8-1.8C18.2 5 12 5 12 5s-6.2 0-7.8.4A2.6 2.6 0 0 0 2.4 7.2 27 27 0 0 0 2 12a27 27 0 0 0 .4 4.8 2.6 2.6 0 0 0 1.8 1.8C5.8 19 12 19 12 19s6.2 0 7.8-.4a2.6 2.6 0 0 0 1.8-1.8A27 27 0 0 0 22 12a27 27 0 0 0-.4-4.8z"/><path class="cut" d="M10 15.2V8.8l5.4 3.2z"/></svg>',
  spotify: '<svg viewBox="0 0 24 24" aria-hidden="true"><circle cx="12" cy="12" r="10"/><path class="cut-stroke" d="M7 9.3c3.4-1 7-.7 10 1"/><path class="cut-stroke" d="M7.7 12.3c2.8-.7 5.6-.4 8 .9"/><path class="cut-stroke" d="M8.4 15.2c2-.4 4.1-.2 5.9.7"/></svg>',
  soundcloud: '<svg viewBox="0 0 24 24" aria-hidden="true"><path d="M8.5 17.5h9.2a3.3 3.3 0 0 0 .4-6.6 5 5 0 0 0-9.6-1.6z"/><rect x="5.6" y="10.5" width="1.6" height="7" rx=".8"/><rect x="3" y="12.5" width="1.6" height="5" rx=".8"/></svg>',
  other: '<svg viewBox="0 0 24 24" aria-hidden="true"><rect x="3.5" y="4.5" width="17" height="15" rx="3"/><circle class="cut" cx="9" cy="10" r="1.7"/><path class="cut" d="m6.5 17 4-4 2.5 2.5 2.5-2 2.5 3.5z"/></svg>',
};

function platformIcon(source) {
  const src = normalizedSource(source);
  if (src === "none") return '<span class="platform-icon platform-none"></span>';
  return `<span class="platform-icon platform-${src}">${PLATFORM_SVG[src]}</span>`;
}

function sourceBadge(source, url = "") {
  const src = normalizedSource(source, url);
  return `<span class="platform platform-${src}">${platformIcon(src)}<span class="platform-label">${esc(PLATFORM_LABELS[src])}</span></span>`;
}

function coverSourceOf(row) {
  if (row.thumbnail_source) return normalizedSource(row.thumbnail_source);
  const thumb = String(row.thumbnail || "").toLowerCase();
  if (!thumb) return "none";
  if (thumb.includes("i.scdn.co")) return "spotify";
  if (thumb.includes("ytimg.com") || thumb.includes("googleusercontent.com")) return "youtube";
  if (thumb.includes("sndcdn.com")) return "soundcloud";
  return "other";
}

function coverLabel(row) {
  const src = coverSourceOf(row);
  if (src === "none") return "Nessuna cover";
  const confidence = Number(row.thumbnail_confidence);
  const pct = Number.isFinite(confidence) && confidence > 0 ? ` · confidence ${Math.round(confidence * 100)}%` : "";
  return `Cover ${PLATFORM_LABELS[src]}${pct}`;
}

function makeActionLink(url, source, title) {
  const href = safeUrl(url);
  const src = normalizedSource(source);
  if (!href) {
    return `<span class="action-link platform-${src} is-disabled" aria-hidden="true">${platformIcon(src)}</span>`;
  }
  return `<a class="action-link platform-${src}" href="${esc(href)}" target="_blank" rel="noopener noreferrer" title="${esc(title)}" aria-label="${esc(title)}">${platformIcon(src)}</a>`;
}

function actionLinks(row) {
  const webpage = row.webpage_url || "";
  const youtubeUrl = normalizedSource("", webpage) === "youtube" ? webpage : "";
  const soundcloudUrl = normalizedSource("", webpage) === "soundcloud" ? webpage : "";
  // Solo i link realmente disponibili: icone disabilitate sarebbero rumore.
  return [
    [youtubeUrl, "youtube", "Apri su YouTube"],
    [row.spotify_url || "", "spotify", "Apri su Spotify"],
    [soundcloudUrl, "soundcloud", "Apri su SoundCloud"],
  ]
    .filter(([url]) => safeUrl(url))
    .map(([url, source, title]) => makeActionLink(url, source, title))
    .join("");
}

/* ── Celle riusabili ────────────────────────────────────────────────────── */

function thumbHtml(url, size = "") {
  const src = safeUrl(url);
  if (!src) {
    return `<span class="thumb thumb-empty ${size}"><svg class="icon"><use href="#i-disc"/></svg></span>`;
  }
  return `<img class="thumb ${size}" src="${esc(src)}" alt="" loading="lazy" referrerpolicy="no-referrer" data-thumb>`;
}

function trackCell(title, artist, thumbnail) {
  return `
    <div class="track">
      ${thumbHtml(thumbnail)}
      <div class="track-copy">
        <span class="track-title" title="${esc(title)}">${esc(title || "Senza titolo")}</span>
        <span class="track-artist" title="${esc(artist)}">${esc(artist || "Artista sconosciuto")}</span>
      </div>
    </div>`;
}

function textPair(title, artist) {
  return `
    <div class="track-copy">
      <span class="track-title" title="${esc(title)}">${esc(title || "–")}</span>
      <span class="track-artist" title="${esc(artist)}">${esc(artist || "–")}</span>
    </div>`;
}

function validBadge(valid, labels = ["valida", "invalida"]) {
  return valid ? `<span class="badge ok">${labels[0]}</span>` : `<span class="badge err">${labels[1]}</span>`;
}

function queryChip(value) {
  if (!value) return '<span class="cell-muted">–</span>';
  return `<button type="button" class="query-chip" data-action="search" data-value="${esc(value)}" title="Filtra per «${esc(value)}»">${esc(value)}</button>`;
}

function confidenceCell(value) {
  const num = Number(value);
  if (value === null || value === undefined || value === "" || !Number.isFinite(num)) return '<span class="cell-muted">–</span>';
  const pct = Math.max(0, Math.min(100, Math.round(num * 100)));
  return `<span class="confidence"><span class="confidence-bar"><span style="width:${pct}%"></span></span><span class="confidence-value">${num.toFixed(2)}</span></span>`;
}

function deleteButton(label) {
  return `<button type="button" class="del-btn" data-action="delete" aria-label="${esc(label)}" title="${esc(label)}"><svg class="icon"><use href="#i-trash"/></svg></button>`;
}

/* ── Definizione sezioni ────────────────────────────────────────────────── */

const SECTIONS = {
  cache: {
    title: "Panoramica cache",
    description: "Vista operativa song_cache: una riga per sorgente risolta, con query di origine, validita e utilizzo.",
    endpoint: "/api/songs",
    deleteUrl: id => `/api/delete/${id}`,
    deleteToast: "Entry eliminata",
    sort: { key: "created_at", dir: "desc" },
    filters: true,
    searchFields: ["id", "title", "artist", "query_raw", "webpage_url", "spotify_url"],
    columns: [
      { key: "id", label: "#", sortable: true, render: r => `<span class="cell-id">${Number(r.id)}</span>` },
      { key: "title", label: "Brano", sortable: true, render: r => trackCell(r.title, r.artist, r.thumbnail) },
      { key: "query_raw", label: "Query", sortable: true, render: r => queryChip(r.query_raw) },
      { key: "source", label: "Sorgente", sortable: true, render: r => sourceBadge(r.source, r.webpage_url) },
      { key: "duration", label: "Durata", sortable: true, cls: "num", render: r => `<span class="cell-muted">${fmtDuration(r.duration)}</span>` },
      { key: "hit_count", label: "Hit", sortable: true, cls: "num", render: r => `<span class="cell-strong" data-hits>${fmtNumber(r.hit_count)}</span>` },
      { key: "created_at", label: "Aggiunta", sortable: true, render: r => timeCell(r.created_at) },
      { key: "is_valid", label: "Stato", sortable: true, render: r => validBadge(r.is_valid) },
    ],
    actions: r => actionLinks(r) + deleteButton("Elimina entry"),
    detail: r => ({
      kicker: `Sorgente #${Number(r.id)}`,
      title: r.title || "Senza titolo",
      subtitle: r.artist || "Artista sconosciuto",
      thumbnail: r.thumbnail,
      props: [
        ["Query", esc(r.query_raw || "–")],
        ["Sorgente", sourceBadge(r.source, r.webpage_url)],
        ["Durata", fmtDuration(r.duration)],
        ["Hit", fmtNumber(r.hit_count)],
        ["Stato", validBadge(r.is_valid)],
        ["Cover", esc(coverLabel(r))],
        ["Creata", esc(fmtTimestamp(r.created_at))],
        ["Ultimo uso", esc(fmtTimestamp(r.last_used))],
        ["Link", linkHtml(r.webpage_url)],
        ["Spotify", linkHtml(r.spotify_url)],
      ],
      deleteLabel: "Elimina entry",
    }),
  },

  tracks: {
    title: "Tracce canoniche",
    description: "cache_tracks: una riga per identita del brano, indipendente dalle singole sorgenti che lo riproducono.",
    endpoint: "/api/tracks",
    deleteUrl: id => `/api/tracks/${id}`,
    deleteToast: "Traccia canonica eliminata",
    sort: { key: "id", dir: "desc" },
    searchFields: ["id", "canonical_title", "canonical_artist", "normalized_query"],
    columns: [
      { key: "id", label: "ID", sortable: true, render: r => `<span class="cell-id">${Number(r.id)}</span>` },
      { key: "canonical_title", label: "Brano canonico", sortable: true, render: r => textPair(r.canonical_title, r.canonical_artist) },
      { key: "normalized_query", label: "Chiave normalizzata", sortable: true, render: r => `<span class="cell-mono" title="${esc(r.normalized_query)}">${esc(r.normalized_query || "–")}</span>` },
      { key: "source_count", label: "Sorgenti", sortable: true, cls: "num", render: r => `<span class="cell-strong">${fmtNumber(r.source_count)}</span>` },
      { key: "query_count", label: "Query attive", sortable: true, cls: "num", render: r => `<span class="cell-strong">${fmtNumber(r.query_count)}</span>` },
      { key: "created_at", label: "Creata", sortable: true, render: r => timeCell(r.created_at) },
      { key: "updated_at", label: "Aggiornata", sortable: true, render: r => timeCell(r.updated_at) },
    ],
    actions: () => deleteButton("Elimina traccia"),
    detail: r => ({
      kicker: `Traccia #${Number(r.id)}`,
      title: r.canonical_title || "Senza titolo",
      subtitle: r.canonical_artist || "Artista sconosciuto",
      props: [
        ["Chiave", `<code>${esc(r.normalized_query || "–")}</code>`],
        ["Sorgenti", fmtNumber(r.source_count)],
        ["Query attive", fmtNumber(r.query_count)],
        ["Creata", esc(fmtTimestamp(r.created_at))],
        ["Aggiornata", esc(fmtTimestamp(r.updated_at))],
      ],
      deleteLabel: "Elimina traccia",
    }),
  },

  sources: {
    title: "Sorgenti risolte",
    description: "cache_sources: URL riproducibili con durata, cover, validita e legame alla traccia canonica.",
    endpoint: "/api/sources",
    deleteUrl: id => `/api/sources/${id}`,
    deleteToast: "Sorgente eliminata",
    sort: { key: "id", dir: "desc" },
    searchFields: ["id", "track_id", "canonical_title", "canonical_artist", "resolved_title", "resolved_artist", "source", "webpage_url", "spotify_url"],
    columns: [
      { key: "id", label: "ID", sortable: true, render: r => `<span class="cell-id">${Number(r.id)}</span>` },
      { key: "resolved_title", label: "Risolto come", sortable: true, render: r => trackCell(r.resolved_title || r.canonical_title, r.resolved_artist || r.canonical_artist, r.thumbnail) },
      { key: "track_id", label: "Traccia", sortable: true, render: r => `<span class="cell-id">T${Number(r.track_id)}</span>` },
      { key: "source", label: "Sorgente", sortable: true, render: r => sourceBadge(r.source, r.webpage_url) },
      { key: "duration", label: "Durata", sortable: true, cls: "num", render: r => `<span class="cell-muted">${fmtDuration(r.duration)}</span>` },
      { key: "hit_count", label: "Hit", sortable: true, cls: "num", render: r => `<span class="cell-strong" data-hits>${fmtNumber(r.hit_count)}</span>` },
      { key: "is_valid", label: "Stato", sortable: true, render: r => validBadge(r.is_valid) },
      { key: "last_used", label: "Ultimo uso", sortable: true, render: r => timeCell(r.last_used) },
    ],
    actions: r => actionLinks(r) + deleteButton("Elimina sorgente"),
    detail: r => ({
      kicker: `Sorgente #${Number(r.id)} · traccia T${Number(r.track_id)}`,
      title: r.resolved_title || r.canonical_title || "Senza titolo",
      subtitle: r.resolved_artist || r.canonical_artist || "Artista sconosciuto",
      thumbnail: r.thumbnail,
      props: [
        ["Brano canonico", esc(`${r.canonical_title || "–"} · ${r.canonical_artist || "–"}`)],
        ["Sorgente", sourceBadge(r.source, r.webpage_url)],
        ["Durata", fmtDuration(r.duration)],
        ["Hit", fmtNumber(r.hit_count)],
        ["Stato", validBadge(r.is_valid)],
        ["Cover", esc(coverLabel(r))],
        ["Stream scade", esc(fmtTimestamp(r.stream_expires_at))],
        ["Creata", esc(fmtTimestamp(r.created_at))],
        ["Ultimo uso", esc(fmtTimestamp(r.last_used))],
        ["Link", linkHtml(r.webpage_url)],
        ["Spotify", linkHtml(r.spotify_url)],
      ],
      deleteLabel: "Elimina sorgente",
    }),
  },

  queries: {
    title: "Query osservate",
    description: "cache_queries: testi cercati dagli utenti e alias confermati, con confidence e puntamento a traccia e sorgente.",
    endpoint: "/api/queries",
    deleteUrl: id => `/api/queries/${id}`,
    deleteToast: "Query eliminata",
    sort: { key: "id", dir: "desc" },
    searchFields: ["id", "track_id", "source_id", "query_raw", "alias_type", "canonical_title", "canonical_artist", "source"],
    columns: [
      { key: "id", label: "ID", sortable: true, render: r => `<span class="cell-id">${Number(r.id)}</span>` },
      { key: "query_raw", label: "Query", sortable: true, render: r => `${queryChip(r.query_raw)}<div class="track-artist">${esc(r.canonical_title || "")}${r.canonical_artist ? " · " + esc(r.canonical_artist) : ""}</div>` },
      { key: "alias_type", label: "Tipo", sortable: true, render: r => `<span class="badge plain">${esc(r.alias_type || "text")}</span>` },
      { key: "confidence", label: "Confidence", sortable: true, render: r => confidenceCell(r.confidence) },
      { key: "track_id", label: "Traccia / sorgente", sortable: true, render: r => `<span class="cell-id">T${Number(r.track_id)} · S${Number(r.source_id)}</span>` },
      { key: "hit_count", label: "Hit", sortable: true, cls: "num", render: r => `<span class="cell-strong" data-hits>${fmtNumber(r.hit_count)}</span>` },
      { key: "is_active", label: "Stato", sortable: true, render: r => validBadge(r.is_active, ["attiva", "disattiva"]) },
      { key: "last_seen", label: "Ultima vista", sortable: true, render: r => timeCell(r.last_seen) },
    ],
    actions: r => actionLinks(r) + deleteButton("Elimina query"),
    detail: r => ({
      kicker: `Query #${Number(r.id)}`,
      title: r.query_raw || "–",
      subtitle: `${r.canonical_title || "–"} · ${r.canonical_artist || "–"}`,
      props: [
        ["Normalizzata", `<code>${esc(r.query_norm || "–")}</code>`],
        ["Tipo", esc(r.alias_type || "text")],
        ["Confidence", confidenceCell(r.confidence)],
        ["Traccia", `T${Number(r.track_id)}`],
        ["Sorgente", `S${Number(r.source_id)} · ${sourceBadge(r.source, r.webpage_url)}`],
        ["Hit", fmtNumber(r.hit_count)],
        ["Stato", validBadge(r.is_active, ["attiva", "disattiva"])],
        ["Prima vista", esc(fmtTimestamp(r.created_at))],
        ["Ultima vista", esc(fmtTimestamp(r.last_seen))],
        ["Link", linkHtml(r.webpage_url)],
      ],
      deleteLabel: "Elimina query",
    }),
  },

  aliases: {
    title: "Alias",
    description: "Vista query_aliases: alias esposti al resolver e brano a cui puntano.",
    endpoint: "/api/aliases",
    deleteUrl: id => `/api/aliases/${id}`,
    deleteToast: "Alias eliminato",
    sort: { key: "id", dir: "desc" },
    searchFields: ["id", "query_raw", "alias_type", "title", "artist", "cache_id"],
    columns: [
      { key: "id", label: "ID", sortable: true, render: r => `<span class="cell-id">${Number(r.id)}</span>` },
      { key: "query_raw", label: "Alias", sortable: true, render: r => queryChip(r.query_raw) },
      { key: "alias_type", label: "Tipo", sortable: true, render: r => `<span class="badge plain">${esc(r.alias_type || "text")}</span>` },
      { key: "title", label: "Brano associato", sortable: true, render: r => textPair(r.title, r.artist) },
      { key: "cache_id", label: "Sorgente", sortable: true, render: r => `<span class="cell-id">S${Number(r.cache_id)}</span>` },
    ],
    actions: r => actionLinks(r) + deleteButton("Elimina alias"),
    detail: r => ({
      kicker: `Alias #${Number(r.id)}`,
      title: r.query_raw || "–",
      subtitle: `${r.title || "–"} · ${r.artist || "–"}`,
      props: [
        ["Tipo", esc(r.alias_type || "text")],
        ["Sorgente", `S${Number(r.cache_id)}`],
        ["Link", linkHtml(r.webpage_url)],
        ["Spotify", linkHtml(r.spotify_url)],
      ],
      deleteLabel: "Elimina alias",
    }),
  },

  schema: {
    title: "Struttura DB",
    description: "Tabelle normalizzate e viste compatibili del cache DB, con il numero di righe correnti.",
    endpoint: "/api/schema",
  },
};

const SECTION_ORDER = ["cache", "tracks", "sources", "queries", "aliases", "schema"];
const TABLE_SECTIONS = SECTION_ORDER.filter(name => name !== "schema");

function linkHtml(url) {
  const href = safeUrl(url);
  if (!href) return '<span class="cell-muted">–</span>';
  return `<a href="${esc(href)}" target="_blank" rel="noopener noreferrer">${esc(href)}</a>`;
}

/* ── Stato ──────────────────────────────────────────────────────────────── */

const state = {
  section: "cache",
  data: {},
  stale: new Set(),
  loading: new Set(),
  known: {},
  hits: {},
  view: {},
  stats: null,
  drawerRow: null,
  pollTimer: null,
  liveTimer: null,
  events: null,
};

for (const name of TABLE_SECTIONS) {
  state.view[name] = { search: "", sort: { ...SECTIONS[name].sort }, page: 1, filters: { source: "", valid: "" } };
}

const els = {};

/* ── Rete ───────────────────────────────────────────────────────────────── */

async function fetchJson(url, { headers = {}, ...options } = {}) {
  const response = await fetch(url, {
    credentials: "same-origin",
    ...options,
    headers: { Accept: "application/json", ...headers },
  });
  if (response.status === 401) {
    window.location.assign("/login");
    throw new Error("unauthorized");
  }
  if (!response.ok) throw new Error(`HTTP ${response.status}`);
  return response.json();
}

/* ── Statistiche ────────────────────────────────────────────────────────── */

function tween(el, to, duration = 700) {
  const from = Number(el.dataset.value || 0);
  el.dataset.value = String(to);
  if (from === to) {
    el.textContent = fmtNumber(to);
    return;
  }
  if (state.stats) {
    el.classList.remove("is-bumped");
    void el.offsetWidth;
    el.classList.add("is-bumped");
  }
  const start = performance.now();
  const step = now => {
    const progress = Math.min((now - start) / duration, 1);
    const eased = 1 - Math.pow(1 - progress, 3);
    el.textContent = fmtNumber(Math.round(from + (to - from) * eased));
    if (progress < 1) requestAnimationFrame(step);
  };
  requestAnimationFrame(step);
}

function applyStatsPayload(data) {
  if (!data) return;
  for (const key of ["total", "valid", "invalid", "hits", "aliases"]) {
    const el = $(`[data-stat="${key}"]`);
    if (el) tween(el, Number(data[key]) || 0);
  }
  const total = Number(data.total) || 0;
  const validRate = total ? Math.round(((Number(data.valid) || 0) / total) * 100) : 0;
  const rateEl = $('[data-stat-derived="valid-rate"]');
  if (rateEl) rateEl.textContent = total ? `${validRate}%` : "–";
  const meter = $('[data-meter="valid-rate"]');
  if (meter) meter.style.width = `${validRate}%`;
  const perSource = $('[data-stat-derived="hits-per-source"]');
  if (perSource) perSource.textContent = total ? ((Number(data.hits) || 0) / total).toFixed(1).replace(".", ",") : "–";

  setNavCount("cache", data.total);
  setNavCount("aliases", data.aliases);
  state.stats = data;
  markUpdated();
}

function refreshStats() {
  return fetchJson("/api/stats").then(applyStatsPayload).catch(() => {});
}

function refreshSchemaCounts() {
  return fetchJson(SECTIONS.schema.endpoint)
    .then(rows => {
      state.data.schema = rows;
      const map = { cache_tracks: "tracks", cache_sources: "sources", cache_queries: "queries" };
      rows.forEach(row => {
        if (map[row.name]) setNavCount(map[row.name], row.count);
      });
      if (state.section === "schema") renderSchema();
    })
    .catch(() => {});
}

function setNavCount(section, value) {
  const el = $(`[data-count="${section}"]`);
  if (!el) return;
  const next = fmtNumber(value);
  if (el.textContent !== next) {
    el.textContent = next;
    el.classList.remove("flash");
    void el.offsetWidth;
    el.classList.add("flash");
  }
}

function markUpdated() {
  if (!els.updated) return;
  const now = new Date();
  els.updated.textContent = `Aggiornato alle ${now.toLocaleTimeString("it-IT", { hour: "2-digit", minute: "2-digit", second: "2-digit" })}`;
}

function renderSourceMix() {
  const rows = state.data.cache;
  if (!rows || !els.mixBar) return;
  const counts = { youtube: 0, spotify: 0, soundcloud: 0, other: 0 };
  rows.forEach(row => {
    const src = normalizedSource(row.source, row.webpage_url);
    counts[src === "none" ? "other" : src] += 1;
  });
  const entries = Object.entries(counts).filter(([, count]) => count > 0);
  els.mixBar.innerHTML = entries
    .map(([src, count]) => `<span style="flex-grow:${count};background:${PLATFORM_COLORS[src]}" title="${esc(PLATFORM_LABELS[src])}: ${count}"></span>`)
    .join("");
  els.mixLegend.innerHTML = entries
    .map(([src, count]) => `<span><i style="background:${PLATFORM_COLORS[src]}"></i>${esc(PLATFORM_LABELS[src])} ${fmtNumber(count)}</span>`)
    .join("");
}

/* ── Live (SSE + fallback polling) ──────────────────────────────────────── */

function setLive(mode) {
  if (!els.live) return;
  els.live.dataset.state = mode;
  const labels = { live: "Live", polling: "Aggiornamento periodico", offline: "Offline", connecting: "Connessione…" };
  $(".live-label", els.live).textContent = labels[mode] || mode;
}

function startPolling() {
  if (state.pollTimer) return;
  state.pollTimer = setInterval(refreshStats, POLL_INTERVAL_MS);
}

function stopPolling() {
  clearInterval(state.pollTimer);
  state.pollTimer = null;
}

function startRealtimeStats() {
  if (!window.EventSource) {
    setLive("polling");
    startPolling();
    return;
  }
  if (state.events) return;
  const source = new EventSource("/api/events");
  state.events = source;
  source.addEventListener("open", () => {
    setLive("live");
    stopPolling();
  });
  // Le statistiche aggiornano solo i KPI: le tabelle si ricaricano
  // esclusivamente su "cache_change".
  source.addEventListener("stats", event => {
    try {
      applyStatsPayload(JSON.parse(event.data));
    } catch (_) {}
  });
  source.addEventListener("cache_change", () => scheduleLiveRefresh());
  source.onerror = () => {
    if (source.readyState === EventSource.CLOSED) {
      // Errore definitivo (es. sessione scaduta): riprova piu' tardi.
      state.events = null;
      setLive("offline");
      startPolling();
      setTimeout(startRealtimeStats, 8000);
      return;
    }
    // EventSource si riconnette da solo; nel frattempo polling.
    setLive("polling");
    startPolling();
  };
}

function scheduleLiveRefresh() {
  clearTimeout(state.liveTimer);
  state.liveTimer = setTimeout(() => {
    TABLE_SECTIONS.forEach(name => state.stale.add(name));
    if (state.section !== "schema") loadSection(state.section, { silent: true });
    refreshSchemaCounts();
  }, LIVE_REFRESH_DEBOUNCE_MS);
}

/* ── Caricamento sezioni ────────────────────────────────────────────────── */

function loadSection(name, { silent = false } = {}) {
  if (name === "schema") {
    if (!state.data.schema) showSkeleton(4);
    return refreshSchemaCounts();
  }
  if (state.loading.has(name)) return Promise.resolve();
  state.loading.add(name);
  if (!silent && !state.data[name]) showSkeleton(SECTIONS[name].columns.length + 1);

  return fetchJson(SECTIONS[name].endpoint)
    .then(rows => {
      const previousIds = state.known[name];
      const previousHits = state.hits[name] || new Map();
      state.data[name] = Array.isArray(rows) ? rows : [];
      state.stale.delete(name);
      state.known[name] = new Set(state.data[name].map(row => Number(row.id)));
      state.hits[name] = new Map(state.data[name].map(row => [Number(row.id), Number(row.hit_count) || 0]));

      let added = [];
      if (silent && previousIds) {
        added = state.data[name].filter(row => !previousIds.has(Number(row.id))).map(row => Number(row.id));
      }
      if (name === "cache") renderSourceMix();
      if (state.section === name) {
        renderTable({ highlight: new Set(added), previousHits: silent ? previousHits : null });
      }
      if (added.length && name === "cache") {
        showToast(added.length === 1 ? "Nuova sorgente in cache" : `${added.length} nuove sorgenti in cache`, "success");
      }
      markUpdated();
    })
    .catch(error => {
      if (error.message === "unauthorized") return;
      if (!silent) {
        showToast("Errore nel caricamento dei dati", "error");
        if (state.section === name) renderError();
      }
    })
    .finally(() => state.loading.delete(name));
}

/* ── Rendering tabella ──────────────────────────────────────────────────── */

function filteredRows(name) {
  const view = state.view[name];
  const section = SECTIONS[name];
  const query = view.search.trim().toLowerCase();
  const rows = (state.data[name] || []).filter(row => {
    if (section.filters) {
      if (view.filters.source && normalizedSource(row.source, row.webpage_url) !== view.filters.source) return false;
      if (view.filters.valid !== "" && String(Number(Boolean(row.is_valid))) !== view.filters.valid) return false;
    }
    if (!query) return true;
    return section.searchFields.some(field => String(row[field] ?? "").toLowerCase().includes(query));
  });
  const { key, dir } = view.sort;
  const factor = dir === "asc" ? 1 : -1;
  return rows.sort((a, b) => {
    const av = a[key];
    const bv = b[key];
    const an = Number(av);
    const bn = Number(bv);
    if (av !== "" && bv !== "" && av !== null && bv !== null && Number.isFinite(an) && Number.isFinite(bn)) {
      return (an - bn) * factor;
    }
    return String(av ?? "").localeCompare(String(bv ?? ""), "it", { numeric: true, sensitivity: "base" }) * factor;
  });
}

function renderHead(name) {
  const section = SECTIONS[name];
  const sort = state.view[name].sort;
  const cells = section.columns.map(col => {
    const classes = [col.cls || ""];
    if (col.sortable) classes.push("is-sortable");
    if (sort.key === col.key) classes.push("is-sorted", sort.dir === "asc" ? "is-asc" : "is-desc");
    const ariaSort = sort.key === col.key ? (sort.dir === "asc" ? "ascending" : "descending") : "none";
    const attrs = col.sortable ? ` data-sort-key="${esc(col.key)}" aria-sort="${ariaSort}" tabindex="0"` : "";
    const arrow = col.sortable ? '<span class="sort" aria-hidden="true">↓</span>' : "";
    return `<th class="${classes.join(" ").trim()}"${attrs}>${esc(col.label)}${arrow}</th>`;
  });
  cells.push('<th class="num"><span class="sr-only">Azioni</span></th>');
  els.head.innerHTML = `<tr>${cells.join("")}</tr>`;
}

function renderTable({ highlight = new Set(), previousHits = null } = {}) {
  const name = state.section;
  const section = SECTIONS[name];
  const view = state.view[name];
  renderHead(name);

  const rows = filteredRows(name);
  const pages = Math.max(1, Math.ceil(rows.length / PAGE_SIZE));
  view.page = Math.min(Math.max(1, view.page), pages);
  const startIndex = (view.page - 1) * PAGE_SIZE;
  const pageRows = rows.slice(startIndex, startIndex + PAGE_SIZE);
  const colspan = section.columns.length + 1;

  if (!pageRows.length) {
    const filtered = view.search || view.filters.source || view.filters.valid !== "";
    els.body.innerHTML = `<tr><td colspan="${colspan}"><div class="empty"><strong>${filtered ? "Nessun risultato" : "Nessun dato"}</strong>${filtered ? "Prova a modificare ricerca o filtri." : "La tabella e' vuota."}</div></td></tr>`;
  } else {
    // Animazione d'ingresso solo al primo render della pagina, non sui refresh live.
    const animate = !previousHits;
    els.body.innerHTML = pageRows
      .map((row, index) => {
        const id = Number(row.id);
        const cells = section.columns.map(col => `<td class="${col.cls || ""}">${col.render(row)}</td>`).join("");
        const classes = ["is-clickable"];
        if (highlight.has(id)) classes.push("row-new");
        const style = animate ? ` style="animation-delay:${Math.min(index, 20) * 14}ms"` : ' style="animation:none"';
        return `<tr class="${classes.join(" ")}" data-id="${id}"${style}>${cells}<td class="num"><div class="row-actions">${section.actions(row)}</div></td></tr>`;
      })
      .join("");
    if (previousHits) flashChangedHits(pageRows, previousHits);
  }

  els.count.textContent = rows.length
    ? `${fmtNumber(startIndex + 1)}–${fmtNumber(startIndex + pageRows.length)} di ${fmtNumber(rows.length)}`
    : "0 risultati";
  els.pageLabel.textContent = `${view.page} / ${pages}`;
  $('[data-page="prev"]', els.pager).disabled = view.page <= 1;
  $('[data-page="next"]', els.pager).disabled = view.page >= pages;
  els.pager.hidden = pages <= 1;
}

function flashChangedHits(rows, previousHits) {
  rows.forEach(row => {
    const id = Number(row.id);
    if (!previousHits.has(id) || previousHits.get(id) === (Number(row.hit_count) || 0)) return;
    const cell = $(`tr[data-id="${id}"] [data-hits]`, els.body);
    if (cell) cell.classList.add("flash");
  });
}

function showSkeleton(columns) {
  if (state.section === "schema") {
    els.schemaGrid.innerHTML = Array.from({ length: 4 })
      .map(() => '<article class="schema-card"><div class="skeleton" style="width:40%"></div><div class="skeleton" style="width:70%"></div><div class="skeleton" style="width:90%"></div></article>')
      .join("");
    return;
  }
  els.head.innerHTML = "";
  const widths = [24, 62, 48, 70, 36, 54, 40, 58, 44, 30];
  els.body.innerHTML = Array.from({ length: 8 })
    .map(() => `<tr class="skeleton-row" style="animation:none">${Array.from({ length: columns })
      .map((_, i) => `<td><div class="skeleton" style="width:${widths[i % widths.length]}%"></div></td>`)
      .join("")}</tr>`)
    .join("");
  els.count.textContent = "Caricamento…";
  els.pager.hidden = true;
}

function renderError() {
  els.body.innerHTML = `<tr><td colspan="${(SECTIONS[state.section].columns || []).length + 1}"><div class="empty"><strong>Impossibile caricare i dati</strong><button type="button" class="button" data-action="retry">Riprova</button></div></td></tr>`;
}

function renderSchema() {
  const rows = state.data.schema || [];
  els.schemaGrid.innerHTML = rows
    .map((item, index) => `
      <article class="schema-card" style="animation-delay:${index * 40}ms">
        <div class="schema-card-top">
          <span class="schema-kind ${item.kind === "view" ? "view" : ""}">${item.kind === "view" ? "Vista" : "Tabella"}</span>
          <span class="schema-count">${fmtNumber(item.count)} righe</span>
        </div>
        <h3>${esc(item.name)}</h3>
        <p>${esc(item.purpose || "")}</p>
        <p class="schema-count">PK <code>${esc(item.pk || "–")}</code></p>
      </article>`)
    .join("");
}

/* ── Navigazione ────────────────────────────────────────────────────────── */

function showSection(name, { pushHash = true } = {}) {
  if (!SECTIONS[name]) name = "cache";
  state.section = name;
  const section = SECTIONS[name];

  $$(".nav-item").forEach(item => {
    const active = item.dataset.section === name;
    item.classList.toggle("is-active", active);
    if (active) item.setAttribute("aria-current", "page");
    else item.removeAttribute("aria-current");
  });
  els.title.textContent = section.title;
  els.desc.textContent = section.description;
  document.title = `${section.title} · Pytonazz`;
  if (pushHash && location.hash !== `#${name}`) history.replaceState(null, "", `#${name}`);

  const isSchema = name === "schema";
  els.tableWrap.hidden = isSchema;
  els.schema.hidden = !isSchema;
  els.foot.hidden = isSchema;
  els.searchWrap.hidden = isSchema;
  els.reset.hidden = isSchema;
  els.filters.hidden = !section.filters;

  if (!isSchema) {
    els.search.value = state.view[name].search;
    syncFilterButtons();
  }

  els.panel.classList.remove("is-switching");
  void els.panel.offsetWidth;
  els.panel.classList.add("is-switching");
  closeNav();

  if (isSchema) {
    if (state.data.schema) renderSchema();
    loadSection("schema");
    return;
  }
  if (state.data[name]) renderTable();
  if (!state.data[name] || state.stale.has(name)) loadSection(name, { silent: Boolean(state.data[name]) });
}

function syncFilterButtons() {
  const view = state.view[state.section];
  if (!view) return;
  $$(".segmented", els.filters).forEach(group => {
    const key = group.dataset.filter;
    $$("button", group).forEach(button => button.classList.toggle("is-active", button.dataset.value === view.filters[key]));
  });
}

function setSearch(value) {
  const view = state.view[state.section];
  if (!view) return;
  view.search = value;
  view.page = 1;
  els.search.value = value;
  renderTable();
}

function openNav() {
  els.app.classList.add("nav-open");
  els.scrim.hidden = false;
  els.menu.setAttribute("aria-expanded", "true");
}

function closeNav() {
  els.app.classList.remove("nav-open");
  els.scrim.hidden = true;
  els.menu.setAttribute("aria-expanded", "false");
}

/* ── Eliminazione ───────────────────────────────────────────────────────── */

function remapId(value, map) {
  const key = String(value);
  return map && Object.prototype.hasOwnProperty.call(map, key) ? Number(map[key]) : value;
}

// Dopo ogni delete il backend ricompatta gli ID: applichiamo la nuova
// numerazione ai dati gia' in memoria invece di ricaricare tutto.
function applyCompactMaps(compact) {
  const trackMap = compact?.track_id_map || {};
  const sourceMap = compact?.source_id_map || {};
  const queryMap = compact?.query_id_map || {};
  const remap = {
    cache: row => ({ ...row, id: remapId(row.id, sourceMap) }),
    tracks: row => ({ ...row, id: remapId(row.id, trackMap) }),
    sources: row => ({ ...row, id: remapId(row.id, sourceMap), track_id: remapId(row.track_id, trackMap) }),
    queries: row => ({
      ...row,
      id: remapId(row.id, queryMap),
      track_id: remapId(row.track_id, trackMap),
      source_id: remapId(row.source_id, sourceMap),
    }),
    aliases: row => ({ ...row, id: remapId(row.id, queryMap), cache_id: remapId(row.cache_id, sourceMap) }),
  };
  for (const name of TABLE_SECTIONS) {
    if (!state.data[name]) continue;
    state.data[name] = state.data[name].map(remap[name]);
    state.known[name] = new Set(state.data[name].map(row => Number(row.id)));
    state.hits[name] = new Map(state.data[name].map(row => [Number(row.id), Number(row.hit_count) || 0]));
  }
}

function removeDashboardRow(name, id) {
  if (state.data[name]) {
    state.data[name] = state.data[name].filter(row => Number(row.id) !== Number(id));
  }
}

function markSectionsStaleAfterDelete(activeSection) {
  // Le delete propagano in cascata: le altre sezioni si ricaricano solo quando
  // vengono riaperte, senza refresh globale.
  TABLE_SECTIONS.forEach(name => {
    if (name !== activeSection) state.stale.add(name);
  });
}

function deleteRow(name, id) {
  const section = SECTIONS[name];
  const row = $(`tr[data-id="${Number(id)}"]`, els.body);
  return fetchJson(section.deleteUrl(Number(id)), { method: "DELETE" })
    .then(data => {
      if (!data.ok) throw new Error("delete failed");
      const finish = () => {
        removeDashboardRow(name, id);
        applyCompactMaps(data.compact);
        markSectionsStaleAfterDelete(name);
        if (name === "cache") renderSourceMix();
        if (state.section === name) renderTable({ previousHits: new Map() });
      };
      if (row) {
        row.classList.add("row-leaving");
        setTimeout(finish, 220);
      } else {
        finish();
      }
      showToast(section.deleteToast, "success");
      closeDrawer();
      refreshStats();
      refreshSchemaCounts();
    })
    .catch(error => {
      if (error.message !== "unauthorized") showToast("Eliminazione non riuscita", "error");
    });
}

function handleDeleteClick(button, name, id) {
  if (button.classList.contains("is-confirming")) {
    clearTimeout(Number(button.dataset.timer));
    button.disabled = true;
    deleteRow(name, id);
    return;
  }
  $$(".del-btn.is-confirming").forEach(other => {
    other.classList.remove("is-confirming");
    clearTimeout(Number(other.dataset.timer));
  });
  const label = button.getAttribute("aria-label");
  button.classList.add("is-confirming");
  button.setAttribute("aria-label", "Clicca di nuovo per confermare");
  button.title = "Clicca di nuovo per confermare";
  button.dataset.timer = String(setTimeout(() => {
    button.classList.remove("is-confirming");
    button.setAttribute("aria-label", label);
    button.title = label;
  }, DELETE_CONFIRM_MS));
}

/* ── Drawer dettaglio ───────────────────────────────────────────────────── */

let lastFocus = null;

function openDrawer(name, id) {
  const section = SECTIONS[name];
  const row = (state.data[name] || []).find(item => Number(item.id) === Number(id));
  if (!row || !section.detail) return;
  const detail = section.detail(row);
  state.drawerRow = { name, id: Number(id) };

  $("#drawer-kicker").textContent = detail.kicker;
  const hero = detail.thumbnail !== undefined
    ? `<div class="drawer-hero">${thumbHtml(detail.thumbnail)}<div><h2 id="drawer-title">${esc(detail.title)}</h2><p class="drawer-sub">${esc(detail.subtitle)}</p></div></div>`
    : `<div><h2 id="drawer-title">${esc(detail.title)}</h2><p class="drawer-sub">${esc(detail.subtitle)}</p></div>`;
  const props = detail.props.map(([label, value]) => `<dt>${esc(label)}</dt><dd>${value}</dd>`).join("");
  const links = row.webpage_url || row.spotify_url ? actionLinks(row) : "";
  els.drawerBody.innerHTML = `
    ${hero}
    <dl class="props">${props}</dl>
    <div class="drawer-actions">
      <div class="row-actions">${links}</div>
      <button type="button" class="button button-danger" data-action="drawer-delete"><svg class="icon"><use href="#i-trash"/></svg><span>${esc(detail.deleteLabel)}</span></button>
    </div>`;

  lastFocus = document.activeElement;
  els.drawer.classList.add("is-open");
  els.drawer.setAttribute("aria-hidden", "false");
  $(".drawer-panel", els.drawer).focus();
}

function closeDrawer() {
  if (!els.drawer.classList.contains("is-open")) return;
  els.drawer.classList.remove("is-open");
  els.drawer.setAttribute("aria-hidden", "true");
  state.drawerRow = null;
  if (lastFocus && typeof lastFocus.focus === "function") lastFocus.focus();
}

/* ── Toast ──────────────────────────────────────────────────────────────── */

function showToast(message, type = "success") {
  const toast = document.createElement("div");
  toast.className = `toast ${type}`;
  toast.setAttribute("role", type === "error" ? "alert" : "status");
  toast.innerHTML = `<svg class="icon"><use href="#${type === "error" ? "i-alert" : "i-check"}"/></svg><span></span>`;
  $("span", toast).textContent = message;
  els.toasts.appendChild(toast);
  setTimeout(() => {
    toast.classList.add("is-leaving");
    toast.addEventListener("animationend", () => toast.remove(), { once: true });
  }, 3200);
}

/* ── Eventi ─────────────────────────────────────────────────────────────── */

function bindEvents() {
  els.nav.addEventListener("click", event => {
    const item = event.target.closest(".nav-item");
    if (item) showSection(item.dataset.section);
  });

  els.menu.addEventListener("click", () => (els.app.classList.contains("nav-open") ? closeNav() : openNav()));
  els.scrim.addEventListener("click", closeNav);

  let searchTimer;
  els.search.addEventListener("input", () => {
    clearTimeout(searchTimer);
    searchTimer = setTimeout(() => setSearch(els.search.value), 160);
  });

  els.filters.addEventListener("click", event => {
    const button = event.target.closest(".segmented button");
    if (!button) return;
    const view = state.view[state.section];
    view.filters[button.closest(".segmented").dataset.filter] = button.dataset.value;
    view.page = 1;
    syncFilterButtons();
    renderTable();
  });

  els.reset.addEventListener("click", () => {
    const view = state.view[state.section];
    if (!view) return;
    view.search = "";
    view.filters = { source: "", valid: "" };
    view.sort = { ...SECTIONS[state.section].sort };
    view.page = 1;
    els.search.value = "";
    syncFilterButtons();
    renderTable();
  });

  els.refresh.addEventListener("click", () => {
    els.refresh.classList.add("is-spinning");
    Promise.all([refreshStats(), refreshSchemaCounts(), state.section === "schema" ? null : loadSection(state.section, { silent: true })])
      .finally(() => setTimeout(() => els.refresh.classList.remove("is-spinning"), 300));
  });

  els.head.addEventListener("click", event => {
    const th = event.target.closest("th[data-sort-key]");
    if (th) toggleSort(th.dataset.sortKey);
  });
  els.head.addEventListener("keydown", event => {
    const th = event.target.closest("th[data-sort-key]");
    if (th && (event.key === "Enter" || event.key === " ")) {
      event.preventDefault();
      toggleSort(th.dataset.sortKey);
    }
  });

  els.body.addEventListener("click", event => {
    const target = event.target;
    if (target.closest("a")) return;
    const retry = target.closest('[data-action="retry"]');
    if (retry) {
      loadSection(state.section);
      return;
    }
    const tr = target.closest("tr[data-id]");
    if (!tr) return;
    const id = Number(tr.dataset.id);
    const del = target.closest('[data-action="delete"]');
    if (del) {
      handleDeleteClick(del, state.section, id);
      return;
    }
    const chip = target.closest('[data-action="search"]');
    if (chip) {
      setSearch(chip.dataset.value || "");
      return;
    }
    openDrawer(state.section, id);
  });

  // Le cover rotte vengono sostituite dal placeholder (niente onerror inline).
  els.body.addEventListener("error", event => {
    const img = event.target;
    if (img.tagName === "IMG" && img.hasAttribute("data-thumb")) {
      img.outerHTML = thumbHtml("");
    }
  }, true);

  els.pager.addEventListener("click", event => {
    const button = event.target.closest("[data-page]");
    if (!button) return;
    const view = state.view[state.section];
    view.page += button.dataset.page === "next" ? 1 : -1;
    renderTable();
    els.tableWrap.scrollTop = 0;
  });

  els.drawer.addEventListener("click", event => {
    if (event.target.closest("[data-close-drawer]")) {
      closeDrawer();
      return;
    }
    const del = event.target.closest('[data-action="drawer-delete"]');
    if (del && state.drawerRow) {
      if (!del.classList.contains("is-confirming")) {
        del.classList.add("is-confirming");
        $("span", del).textContent = "Conferma eliminazione";
        return;
      }
      del.disabled = true;
      deleteRow(state.drawerRow.name, state.drawerRow.id);
    }
  });

  els.themeToggle.addEventListener("click", () => {
    const next = document.documentElement.getAttribute("data-theme") === "light" ? "dark" : "light";
    document.documentElement.setAttribute("data-theme", next);
    try {
      localStorage.setItem("theme", next);
    } catch (_) {}
  });

  window.addEventListener("hashchange", () => showSection(location.hash.slice(1), { pushHash: false }));

  document.addEventListener("keydown", event => {
    const typing = /^(INPUT|TEXTAREA|SELECT)$/.test(document.activeElement?.tagName || "");
    if (event.key === "Escape") {
      if (els.drawer.classList.contains("is-open")) closeDrawer();
      else if (els.app.classList.contains("nav-open")) closeNav();
      else if (typing) document.activeElement.blur();
      return;
    }
    if (typing || event.metaKey || event.ctrlKey || event.altKey) return;
    if (event.key === "/") {
      event.preventDefault();
      if (!els.searchWrap.hidden) els.search.focus();
    } else if (event.key === "r") {
      els.refresh.click();
    } else if (/^[1-6]$/.test(event.key)) {
      showSection(SECTION_ORDER[Number(event.key) - 1]);
    }
  });

  document.addEventListener("visibilitychange", () => {
    if (document.visibilityState === "visible" && state.stale.has(state.section)) {
      loadSection(state.section, { silent: true });
    }
  });
}

function toggleSort(key) {
  const view = state.view[state.section];
  if (!view) return;
  if (view.sort.key === key) {
    view.sort.dir = view.sort.dir === "desc" ? "asc" : "desc";
  } else {
    view.sort = { key, dir: "desc" };
  }
  view.page = 1;
  renderTable();
}

/* ── Avvio ──────────────────────────────────────────────────────────────── */

document.addEventListener("DOMContentLoaded", () => {
  Object.assign(els, {
    app: $("#app"),
    nav: $("#nav"),
    menu: $("#menu-toggle"),
    scrim: $("#scrim"),
    title: $("#section-title"),
    desc: $("#section-desc"),
    panel: $("#panel"),
    head: $("#table-head"),
    body: $("#table-body"),
    tableWrap: $("#table-wrap"),
    schema: $("#schema-view"),
    schemaGrid: $("#schema-grid"),
    foot: $("#panel-foot"),
    count: $("#result-count"),
    pager: $("#pager"),
    pageLabel: $("#page-label"),
    search: $("#search-input"),
    searchWrap: $(".search"),
    filters: $("#filters"),
    reset: $("#reset-button"),
    refresh: $("#refresh-button"),
    live: $("#live-status"),
    updated: $("#updated-at"),
    drawer: $("#drawer"),
    drawerBody: $("#drawer-body"),
    toasts: $("#toasts"),
    themeToggle: $("#theme-toggle"),
    mixBar: $("#source-mix-bar"),
    mixLegend: $("#source-mix-legend"),
  });

  const initial = {};
  $$("[data-stat]").forEach(el => {
    initial[el.dataset.stat] = Number(el.dataset.initial) || 0;
  });
  applyStatsPayload(initial);

  bindEvents();
  showSection(location.hash.slice(1) || "cache", { pushHash: false });
  if (state.section !== "cache") loadSection("cache", { silent: true });
  refreshSchemaCounts();
  startRealtimeStats();
});
