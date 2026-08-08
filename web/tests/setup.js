/**
 * Global test setup for buffalo-landlord-lookup web tests.
 *
 * Runs before every test file (vitest setupFiles). Responsibilities:
 *   1. Inject the minimal HTML skeleton that app.js reads via document.querySelector
 *   2. Mock browser globals that don't exist in jsdom (maplibregl, fetch, matchMedia)
 *   3. Dynamic-import app.js as an ES module so v8 coverage can instrument it
 *   4. Bind the module's exports to window._test for tests to consume
 *   5. Reset mutable state + DOM between tests via beforeEach
 */

import { vi, beforeAll, beforeEach } from 'vitest'

// ---------------------------------------------------------------------------
// DOM helpers
// ---------------------------------------------------------------------------

function buildMockMap() {
  return {
    addControl: vi.fn(),
    on: vi.fn(),
    addLayer: vi.fn(),
    addSource: vi.fn(),
    getLayer: vi.fn(() => true),
    setFilter: vi.fn(),
    setLayoutProperty: vi.fn(),
    flyTo: vi.fn(),
    jumpTo: vi.fn(),
    fitBounds: vi.fn(),
    getZoom: vi.fn(() => 12),
    getCanvas: vi.fn(() => ({ style: { cursor: '' } })),
    querySourceFeatures: vi.fn(() => []),
    getSource: vi.fn(() => ({ setData: vi.fn() })),
    once: vi.fn(),
  }
}

function injectDOM() {
  document.body.innerHTML = `
    <header class="masthead">
      <h1 class="masthead-title">Buffalo Landlord Lookup</h1>
      <p class="masthead-meta" id="issue-date">Public records · Buffalo, N.Y.</p>
    </header>
    <div id="search-row">
      <input type="search" id="search" autocomplete="off" />
      <ul id="search-results"></ul>
    </div>
    <div id="map"></div>
    <button id="reopen-panel" class="hidden">Top landlords</button>
    <div id="filter-chip" class="hidden" role="button" tabindex="0"></div>
    <aside id="panel" class="hidden">
      <div class="panel-handle" role="button" tabindex="0" aria-label="Resize panel"><span></span></div>
      <button id="panel-close" aria-label="Close">&times;</button>
      <div id="panel-content"></div>
    </aside>
    <footer class="colophon">
      <span id="meta-info">Loading…</span>
    </footer>
  `
}

function makeFetchMock() {
  return vi.fn().mockResolvedValue({
    ok: true,
    status: 200,
    json: vi.fn().mockResolvedValue({}),
  })
}

// ---------------------------------------------------------------------------
// Lifecycle hooks
// ---------------------------------------------------------------------------

beforeAll(async () => {
  // Stage browser-global mocks BEFORE importing app.js so its module-level
  // code (initMap → new maplibregl.Map(...), bootstrap → fetch(...)) sees
  // them on first execution.
  window.maplibregl = {
    Map: vi.fn(() => buildMockMap()),
    NavigationControl: vi.fn(),
    GeolocateControl: vi.fn(),
  }
  global.fetch = makeFetchMock()
  window.matchMedia = vi.fn(() => ({ matches: false }))
  // jsdom has no layout, so it ships no scrollIntoView. The search combobox
  // calls it to keep the highlighted option visible.
  Element.prototype.scrollIntoView = vi.fn()

  injectDOM()

  // Dynamic-import the module under test. Bootstrap runs immediately
  // (readyState === 'complete' at this point in jsdom), but its async
  // fetches won't have resolved before the awaited import returns.
  const app = await import('../app.js')

  // Bind exports to window._test so the existing test files (which expect
  // window._test) keep working without per-file imports.
  window._test = app
})

beforeEach(() => {
  // Reset DOM body (keeps everything above body intact)
  injectDOM()

  // Clear mock call histories but keep the stubs
  vi.clearAllMocks()

  // Re-apply stubs that clearAllMocks would have cleared
  global.fetch = makeFetchMock()
  window.matchMedia = vi.fn(() => ({ matches: false }))

  // Reset shared app state so every test is isolated
  if (window._test?.state) {
    const s = window._test.state
    s.map = buildMockMap()     // fresh mock map per test
    s.selectedId = null
    s.dossiers = null
    s.meta = null
    s.topOwners = null
    s.topOperators = null
    s.mapFilter = null
    s.activeBoard = 'by_open_violations'
    s.activeBoardKind = 'operators'
    s.addressIndex = []
    s.lastPortfolio = null
    s.lastOperator = null
  }
})
