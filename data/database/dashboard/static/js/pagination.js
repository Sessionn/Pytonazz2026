/* Shared server pagination for the library read models. */
const libraryPages = {};
const libraryRequests = {};

function pageState(section) {
  return libraryPages[section] ||= { page: 1, pages: 1, total: 0, page_size: 50, query: "" };
}

function pagedParams(section, options) {
  const state = pageState(section);
  const query = JSON.stringify(options);
  if (state.query !== query) state.page = 1;
  state.query = query;
  return new URLSearchParams({ ...options, page: state.page, page_size: state.page_size });
}

function acceptPage(section, data) {
  // Accept the legacy array format for older servers and local fixtures.
  const rows = Array.isArray(data) ? data : data?.items;
  if (!Array.isArray(rows)) throw new Error("Invalid library response");
  Object.assign(pageState(section), Array.isArray(data)
    ? { page: 1, pages: 1, total: rows.length } : data);
  delete pageState(section).items;
  renderPagination();
  return rows;
}

function renderPagination() {
  const target = document.getElementById("library-pagination");
  if (!target) return;
  target.hidden = currentSection === "schema";
  const state = pageState(currentSection);
  target.querySelector("span").textContent = `Pagina ${state.page} di ${state.pages} · ${state.total} risultati`;
  target.querySelector('[data-step="-1"]').disabled = state.page <= 1;
  target.querySelector('[data-step="1"]').disabled = state.page >= state.pages;
}

function changeLibraryPage(step) {
  const state = pageState(currentSection);
  state.page = Math.max(1, Math.min(state.pages, state.page + step));
  sectionLoaders[currentSection]?.();
}

function fetchLibraryTable(section, silent = false) {
  const requestId = libraryRequests[section] = (libraryRequests[section] || 0) + 1;
  const state = tableStates[section];
  const params = pagedParams(section, { q: state.search, sort: state.sort, order: state.order });
  return fetch(`/api/${section}?${params}`)
    .then(readJson)
    .then(data => {
      if (libraryRequests[section] !== requestId) return;
      tableData[section] = acceptPage(section, data);
      renderStoredTable(section);
      loadedSections.add(section);
      document.getElementById("library-update").hidden = true;
    })
    .catch(() => !silent && showToast("Errore nel caricamento dei dati", "error"));
}
