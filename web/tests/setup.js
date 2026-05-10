/**
 * Global test setup for buffalo-landlord-lookup web tests.
 *
 * Runs before every test file (vitest setupFiles). Responsibilities:
 *   1. Inject the minimal HTML skeleton that app.js reads via document.querySelector
 *   2. Mock browser globals that don't exist in jsdom (maplibregl, fetch, matchMedia)
 *   3. Load app.js via new Function(), passing explicit browser globals as params so
 *      const-declared internal functions are in scope for the trailing expose block
 *   4. Expose internal functions as window._test for tests to consume
 *   5. Reset mutable state + DOM between tests via beforeEach
 */

import { vi, beforeAll, beforeEach } from 'vitest'
import { readFileSync } from 'fs'
import { fileURLToPath } from 'url'
import { dirname, join } from 'path'

const __dirname = dirname(fileURLToPath(import.meta.url))

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
// Load app.js ONCE using new Function() so all const-declared internals are
// in scope within the same function body.  Browser globals are passed as
// explicit parameters so they're available without relying on jsdom's
// global scope injection.
// ---------------------------------------------------------------------------

let appLoaded = false

function loadApp() {
  if (appLoaded) return
  appLoaded = true

  const appCode = readFileSync(join(__dirname, '../app.js'), 'utf8')

  // Append the expose block *inside* the same function body so that all
  // top-level `const` declarations from app.js are in scope here.
  const expose = `
;(function __expose() {
  try {
    window._test = {
      // pure helpers
      escapeHtml,
      fmtDate,
      fmtMoney,
      freshnessPill,
      // mutable state object (shared reference — reset in beforeEach)
      state,
      // panel helpers
      showPanel,
      hidePanel,
      fullyHidePanel,
      // view renderers
      renderDossier,
      renderPortfolio,
      renderLeaderboards,
      renderOperator,
      renderAuditDisclosure,
      // routing
      applyHashRoute,
      // map filter
      applyMapFilter,
      clearMapFilter,
      updateFilterChip,
      // search (event handlers wired by setupSearch — call from tests
      // because the bootstrap's DOMContentLoaded already fired by the
      // time setup.js loads app.js)
      setupSearch,
      // constants
      BOARDS,
    }
  } catch (e) {
    // Capture the error so tests can report a readable failure
    window._testLoadError = String(e)
  }
})()
`

  // new Function() runs in non-strict mode, so top-level `const` declarations
  // inside the function body are accessible throughout, including in `expose`.
  // We pass all browser globals that app.js references as explicit parameters
  // rather than relying on the global scope.
  const fn = new Function(
    'window',
    'document',
    'location',
    'history',
    'sessionStorage',
    'navigator',
    'console',
    'Date',
    'Math',
    'fetch',
    appCode + expose,
  )

  fn(
    window,
    window.document,
    window.location,
    window.history,
    window.sessionStorage ?? {},
    window.navigator ?? {},
    console,
    Date,
    Math,
    global.fetch,
  )
}

// ---------------------------------------------------------------------------
// Lifecycle hooks
// ---------------------------------------------------------------------------

beforeAll(() => {
  // Set up mocks before app.js executes so initMap() sees them
  window.maplibregl = {
    Map: vi.fn(() => buildMockMap()),
    NavigationControl: vi.fn(),
  }
  global.fetch = makeFetchMock()
  window.matchMedia = vi.fn(() => ({ matches: false }))

  injectDOM()
  loadApp()

  if (window._testLoadError) {
    throw new Error(`app.js failed to load: ${window._testLoadError}`)
  }
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
