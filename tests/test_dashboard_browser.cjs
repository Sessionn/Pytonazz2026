// Run against a local dashboard with disposable demo data; never production.
// DASHBOARD_TEST_URL=http://127.0.0.1:5055 node tests/test_dashboard_browser.cjs
const { chromium } = require('playwright');
const assert = require('node:assert/strict');
const fs = require('node:fs');

(async () => {
  const base = process.env.DASHBOARD_TEST_URL || 'http://127.0.0.1:5055';
  assert(['127.0.0.1', 'localhost'].includes(new URL(base).hostname), 'Use a disposable local preview');
  const browser = await chromium.launch({ headless: true, executablePath: process.env.BROWSER_EXECUTABLE || undefined });
  const page = await browser.newPage({ viewport: { width: 1440, height: 1000 }, reducedMotion: 'reduce' });
  const errors = [];
  page.on('pageerror', error => errors.push(error.message));
  fs.mkdirSync('data/tmp/web-review', { recursive: true });
  await page.goto(base + '/login');
  await page.screenshot({ path: 'data/tmp/web-review/login-desktop.png', fullPage: true });
  await page.getByLabel('Utente', { exact: true }).fill('preview');
  await page.getByLabel('Password', { exact: true }).fill('preview-only');
  await page.getByRole('button', { name: 'Accedi', exact: true }).click();
  await page.locator('.song-details').first().waitFor();
  await page.screenshot({ path: 'data/tmp/web-review/library-desktop.png', fullPage: true });
  await page.getByRole('button', { name: "L'amour toujours", exact: true }).click();
  await page.getByRole('dialog').waitFor();
  assert((await page.getByRole('dialog').innerText()).includes("Gigi D'Agostino"));
  await page.keyboard.press('Escape');
  assert.equal(await page.getByRole('dialog').isVisible(), false);
  const query = page.locator('.query-cell').filter({ hasText: "L'amour" });
  await query.click();
  await page.waitForFunction(() => document.querySelectorAll('.song-details').length === 1);
  await page.getByRole('button', { name: 'Reset', exact: true }).first().click();
  await page.waitForFunction(() => document.querySelectorAll('.song-details').length === 6);
  for (const name of ['Alias di ricerca', 'Catalogo tracce', 'Sorgenti audio', 'Query e alias', 'Struttura DB']) {
    await page.getByRole('link', { name, exact: true }).click();
    await page.waitForFunction(() => document.querySelector('.section-stack[style="display: grid;"] tbody tr, .section-stack[style="display: grid;"] .schema-card'));
  }
  await page.getByRole('link', { name: 'Tutti i brani', exact: true }).click();
  await page.waitForFunction(() => document.querySelectorAll('.song-details').length === 6);

  // Pagination retrieves disjoint SQL pages and search resets the current page.
  await page.evaluate(() => { pageState('cache').page_size = 2; fetchSongs(); });
  await page.waitForFunction(() => document.querySelectorAll('.song-details').length === 2);
  const firstPage = await page.locator('#songs-body tr[data-id]').evaluateAll(rows => rows.map(row => row.dataset.id));
  await page.getByRole('button', { name: 'Successiva', exact: true }).click();
  await page.waitForFunction(() => pageState('cache').page === 2 && document.querySelector('#library-pagination span').textContent.includes('2 di 3'));
  const secondPage = await page.locator('#songs-body tr[data-id]').evaluateAll(rows => rows.map(row => row.dataset.id));
  assert(secondPage.every(id => !firstPage.includes(id)));
  await page.locator('#search-input').fill('Midnight');
  await page.waitForFunction(() => pageState('cache').total === 1);
  assert.equal(await page.locator('.song-details').innerText(), 'Midnight City');
  assert.equal(await page.getByRole('button', { name: 'Successiva', exact: true }).isDisabled(), true);
  await page.evaluate(() => { pageState('cache').page_size = 50; });
  await page.getByRole('button', { name: 'Reset', exact: true }).first().click();
  await page.waitForFunction(() => document.querySelectorAll('.song-details').length === 6);

  // User-controlled query text must remain inert when inserted in a row/modal.
  await page.evaluate(() => {
    const song = {id: 999, title: "A 'quoted' title", artist: 'Test',
      query_raw: '<img src=x onerror="window.__injected=true">', source: 'youtube',
      webpage_url: 'javascript:window.__injected=true', spotify_url: 'javascript:alert(1)'};
    document.getElementById('songs-body').appendChild(buildSongRow(song));
    openModal(song);
  });
  assert.equal(await page.locator('#modal-content img').count(), 0);
  assert.equal(await page.locator('a[href^="javascript:"]').count(), 0);
  assert.equal(await page.evaluate(() => Boolean(window.__injected)), false);
  await page.keyboard.press('Escape');

  // Live changes notify without moving or replacing rows under the pointer.
  const before = await page.locator('#songs-body').innerHTML();
  await page.evaluate(() => handleCacheChange({ action: 'put' }));
  assert.equal(await page.locator('#library-update').isVisible(), true);
  assert.equal(await page.locator('#songs-body').innerHTML(), before);
  await page.getByRole('button', { name: 'Aggiorna elenco' }).click();
  await page.waitForFunction(() => document.querySelectorAll('.song-details').length === 6);

  // Simulate inverted network response order for two consecutive searches.
  await page.route('**/api/songs?*', async route => {
    const q = new URL(route.request().url()).searchParams.get('q');
    if (!['older', 'newer'].includes(q)) return route.continue();
    await new Promise(resolve => setTimeout(resolve, q === 'older' ? 350 : 10));
    await route.fulfill({ json: [{ id: 10, title: q, artist: 'Test', query_raw: q }] });
  });
  await page.evaluate(() => {
    document.getElementById('search-input').value = 'older'; fetchSongs();
    document.getElementById('search-input').value = 'newer'; fetchSongs();
  });
  await page.locator('.song-details').filter({ hasText: 'newer' }).waitFor();
  await page.waitForTimeout(450);
  assert.equal(await page.locator('.song-details').innerText(), 'newer');
  await page.unroute('**/api/songs?*');
  await page.getByRole('button', { name: 'Reset', exact: true }).first().click();
  await page.waitForFunction(() => document.querySelectorAll('.song-details').length === 6);
  await page.getByRole('button', { name: 'Tema chiaro' }).click();
  await page.screenshot({ path: 'data/tmp/web-review/library-light.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await page.screenshot({ path: 'data/tmp/web-review/library-mobile.png', fullPage: true });
  const djState = { connected: false, queue: [], volume: 0.5, eq: {}, tone_filters: {}, filter_fx: [] };
  await page.route('**/dj-console/state?*', route => route.fulfill({ json: djState }));
  await page.route('**/dj-console/events?*', route => route.fulfill({ contentType: 'text/event-stream', body: ': preview\n\n' }));
  await page.setViewportSize({ width: 1440, height: 1000 });
  await page.goto(base + '/preview-dj');
  await page.locator('#track-title').waitFor();
  await page.screenshot({ path: 'data/tmp/web-review/dj-desktop.png', fullPage: true });
  await page.setViewportSize({ width: 390, height: 844 });
  await page.screenshot({ path: 'data/tmp/web-review/dj-mobile.png', fullPage: true });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  await page.goto(base + '/login');
  await page.screenshot({ path: 'data/tmp/web-review/login-mobile.png', fullPage: true });
  assert(await page.evaluate(() => document.documentElement.scrollWidth <= window.innerWidth));
  assert.deepEqual(errors, []);
  await browser.close();
  console.log('OK: desktop/mobile, login, apostrophes, modal, XSS, safe URLs, live notice, search race, themes');
})().catch(error => { console.error(error); process.exit(1); });
