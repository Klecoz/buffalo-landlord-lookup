/**
 * Tests for DOM-rendering functions in app.js.
 *
 * Covers:
 *   - showPanel / hidePanel / fullyHidePanel
 *   - freshnessPill  (depends on state.meta)
 *   - updateFilterChip
 *   - renderDossier  (property detail panel)
 *   - renderPortfolio (owner portfolio panel)
 *   - renderLeaderboards (top-landlord tabs)
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'

// Resolved from window._test by setup.js
let t   // shorthand for window._test

beforeEach(() => {
  t = window._test
})

// ---------------------------------------------------------------------------
// showPanel / hidePanel / fullyHidePanel
// ---------------------------------------------------------------------------

describe('showPanel', () => {
  it('injects HTML into #panel-content', () => {
    t.showPanel('<p id="test-p">hello</p>')
    expect(document.getElementById('test-p')).not.toBeNull()
    expect(document.getElementById('test-p').textContent).toBe('hello')
  })

  it('removes the hidden class from #panel', () => {
    const panel = document.getElementById('panel')
    panel.classList.add('hidden')
    t.showPanel('<p>hi</p>')
    expect(panel.classList.contains('hidden')).toBe(false)
  })

  it('hides #reopen-panel when panel opens', () => {
    const btn = document.getElementById('reopen-panel')
    btn.classList.remove('hidden')
    t.showPanel('<p>hi</p>')
    expect(btn.classList.contains('hidden')).toBe(true)
  })

  it('resets panel scroll to top', () => {
    const panel = document.getElementById('panel')
    panel.scrollTop = 200
    t.showPanel('<p>hi</p>')
    expect(panel.scrollTop).toBe(0)
  })
})

describe('hidePanel', () => {
  it('clears state.selectedId', () => {
    // Prime the leaderboard state so renderLeaderboards doesn't crash
    t.state.topOperators = { by_open_violations: [], by_all_violations: [], by_properties: [], by_value: [], by_complaints_311: [] }
    t.state.topOwners = { by_open_violations: [], by_all_violations: [], by_properties: [], by_value: [], by_complaints_311: [] }
    t.state.selectedId = 'parcel-123'
    t.hidePanel()
    expect(t.state.selectedId).toBeNull()
  })

  it('removes the map selection highlight', () => {
    t.state.selectedId = 'parcel-123'
    t.state.topOperators = { by_open_violations: [], by_all_violations: [], by_properties: [], by_value: [], by_complaints_311: [] }
    t.state.topOwners = { by_open_violations: [], by_all_violations: [], by_properties: [], by_value: [], by_complaints_311: [] }
    t.hidePanel()
    expect(t.state.map.setFilter).toHaveBeenCalledWith('parcels-selected', ['==', 'id', ''])
  })
})

describe('fullyHidePanel', () => {
  it('adds hidden class to #panel', () => {
    const panel = document.getElementById('panel')
    panel.classList.remove('hidden')
    t.fullyHidePanel()
    expect(panel.classList.contains('hidden')).toBe(true)
  })

  it('shows #reopen-panel', () => {
    const btn = document.getElementById('reopen-panel')
    btn.classList.add('hidden')
    t.fullyHidePanel()
    expect(btn.classList.contains('hidden')).toBe(false)
  })
})

// ---------------------------------------------------------------------------
// freshnessPill
// ---------------------------------------------------------------------------

describe('freshnessPill', () => {
  it('returns empty string when state.meta is null', () => {
    t.state.meta = null
    expect(t.freshnessPill('violations')).toBe('')
  })

  it('returns empty string when meta has no relevant dates', () => {
    t.state.meta = { generated_at: '' }
    expect(t.freshnessPill('violations')).toBe('')
  })

  it('returns a fresh pill for a recent violations date', () => {
    const recent = new Date(Date.now() - 5 * 86400000).toISOString().slice(0, 10)
    t.state.meta = { code_violations_max_date: recent }
    const html = t.freshnessPill('violations')
    expect(html).toContain('freshness-pill')
    expect(html).toContain('fresh')
    expect(html).toContain(recent)
  })

  it('returns an aging pill for a 60-day-old violations date', () => {
    const old = new Date(Date.now() - 60 * 86400000).toISOString().slice(0, 10)
    t.state.meta = { code_violations_max_date: old }
    const html = t.freshnessPill('violations')
    expect(html).toContain('aging')
  })

  it('returns a stale pill for a 200-day-old violations date', () => {
    const stale = new Date(Date.now() - 200 * 86400000).toISOString().slice(0, 10)
    t.state.meta = { code_violations_max_date: stale }
    const html = t.freshnessPill('violations')
    expect(html).toContain('stale')
  })

  it('returns the frozen 311 pill when 311 date is > 180 days old', () => {
    t.state.meta = { complaints_311_max_date: '2024-05-10' }
    const html = t.freshnessPill('311')
    expect(html).toContain('stale')
    expect(html).toContain('frozen')
    expect(html).toContain('2024-05')
  })

  it('returns a fresh 311 pill for a recent date', () => {
    const recent = new Date(Date.now() - 10 * 86400000).toISOString().slice(0, 10)
    t.state.meta = { complaints_311_max_date: recent }
    const html = t.freshnessPill('311')
    expect(html).toContain('fresh')
    expect(html).not.toContain('frozen')
  })
})

// ---------------------------------------------------------------------------
// updateFilterChip
// ---------------------------------------------------------------------------

describe('updateFilterChip', () => {
  it('hides the chip when there is no active filter', () => {
    t.state.mapFilter = null
    t.updateFilterChip()
    const chip = document.getElementById('filter-chip')
    expect(chip.classList.contains('hidden')).toBe(true)
    expect(chip.innerHTML).toBe('')
  })

  it('shows the chip with label and count when filter is set', () => {
    t.state.mapFilter = { kind: 'owner', slug: 'acme-properties', label: 'ACME Properties', count: 7 }
    t.updateFilterChip()
    const chip = document.getElementById('filter-chip')
    expect(chip.classList.contains('hidden')).toBe(false)
    expect(chip.textContent).toContain('ACME Properties')
    expect(chip.textContent).toContain('7')
  })

  it('uses singular "parcel" when count is 1', () => {
    t.state.mapFilter = { kind: 'operator', slug: 'solo-llc', label: 'Solo LLC', count: 1 }
    t.updateFilterChip()
    expect(document.getElementById('filter-chip').textContent).toContain('parcel')
    expect(document.getElementById('filter-chip').textContent).not.toContain('parcels')
  })

  it('uses plural "parcels" when count is 0 or > 1', () => {
    t.state.mapFilter = { kind: 'owner', slug: 'multi', label: 'Multi', count: 3 }
    t.updateFilterChip()
    expect(document.getElementById('filter-chip').textContent).toContain('parcels')
  })
})

// ---------------------------------------------------------------------------
// renderDossier
// ---------------------------------------------------------------------------

describe('renderDossier', () => {
  const baseProps = {
    addr: '123 Main St',
    owner: 'ACME LLC',
    owner_slug: 'acme-llc',
    portfolio_n: 1,
    violations_open: 0,
    violations_total: 2,
    complaints_311_12mo: 1,
    demolished: false,
    concern_score: 2,
  }

  it('shows the property address', () => {
    t.renderDossier(baseProps, null)
    expect(document.getElementById('panel-content').textContent).toContain('123 Main St')
  })

  it('shows the owner name', () => {
    t.renderDossier(baseProps, null)
    expect(document.getElementById('panel-content').textContent).toContain('ACME LLC')
  })

  it('shows "Owner not on record" when owner is missing', () => {
    t.renderDossier({ ...baseProps, owner: '' }, null)
    expect(document.getElementById('panel-content').textContent).toContain('Owner not on record')
  })

  it('shows violation and complaint counts in the stat grid', () => {
    const props = { ...baseProps, violations_open: 3, violations_total: 10, complaints_311_12mo: 5 }
    t.renderDossier(props, null)
    const content = document.getElementById('panel-content').textContent
    expect(content).toContain('3')   // open violations
    expect(content).toContain('10')  // total violations
    expect(content).toContain('5')   // 311 complaints
  })

  it('marks open-violation stat as bad when violations > 0', () => {
    t.renderDossier({ ...baseProps, violations_open: 2 }, null)
    const badStat = document.querySelector('#panel-content .stat.bad')
    expect(badStat).not.toBeNull()
  })

  it('shows empty state when no violations dossier', () => {
    t.renderDossier(baseProps, null)
    const content = document.getElementById('panel-content').textContent
    expect(content).toContain('No code violations on record')
  })

  it('shows empty state when dossier has empty arrays', () => {
    t.renderDossier(baseProps, { violations: [], complaints: [] })
    const content = document.getElementById('panel-content').textContent
    expect(content).toContain('No code violations on record')
    expect(content).toContain('No housing-related 311 complaints')
  })

  it('renders violation list items', () => {
    const dossier = {
      violations: [
        { date: '2024-01-15T00:00:00Z', status: 'Open', description: 'Broken windows' },
        { date: '2023-06-01T00:00:00Z', status: 'Closed', description: 'Peeling paint' },
      ],
      complaints: [],
    }
    t.renderDossier(baseProps, dossier)
    const items = document.querySelectorAll('#panel-content .violations li')
    expect(items.length).toBe(2)
    expect(items[0].textContent).toContain('Broken windows')
    expect(items[0].textContent).toContain('2024-01-15')
  })

  it('renders complaint list items', () => {
    const dossier = {
      violations: [],
      complaints: [
        { date: '2024-03-10', subject: 'No heat' },
        { date: '2024-02-01', subject: 'Mold' },
      ],
    }
    t.renderDossier(baseProps, dossier)
    const items = document.querySelectorAll('#panel-content .complaints li')
    expect(items.length).toBe(2)
    expect(items[0].textContent).toContain('No heat')
  })

  it('caps displayed violations at 10', () => {
    const manyViols = Array.from({ length: 15 }, (_, i) => ({
      date: '2024-01-01', status: 'Open', description: `Issue ${i + 1}`,
    }))
    t.renderDossier(baseProps, { violations: manyViols, complaints: [] })
    const items = document.querySelectorAll('#panel-content .violations li')
    expect(items.length).toBe(10)
  })

  it('shows portfolio CTA for multi-property owners', () => {
    const props = { ...baseProps, portfolio_n: 5, owner_slug: 'acme-llc' }
    t.renderDossier(props, null)
    const cta = document.querySelector('#panel-content .cta')
    expect(cta).not.toBeNull()
    expect(cta.textContent).toContain('4 other')
  })

  it('omits portfolio CTA for single-property owners', () => {
    t.renderDossier({ ...baseProps, portfolio_n: 1 }, null)
    expect(document.querySelector('#panel-content .cta')).toBeNull()
  })

  it('shows demolished status', () => {
    t.renderDossier({ ...baseProps, demolished: true }, null)
    expect(document.getElementById('panel-content').textContent).toContain('Yes')
  })

  it('escapes HTML in address and owner fields', () => {
    const props = { ...baseProps, addr: '<b>XSS</b>', owner: '<script>evil()</script>' }
    t.renderDossier(props, null)
    const html = document.getElementById('panel-content').innerHTML
    expect(html).not.toContain('<b>XSS</b>')
    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;b&gt;XSS&lt;/b&gt;')
  })
})

// ---------------------------------------------------------------------------
// renderPortfolio
// ---------------------------------------------------------------------------

describe('renderPortfolio', () => {
  const basePortfolio = {
    _slug: 'acme-llc',
    owner_display: 'ACME LLC',
    owner_variants: ['ACME LLC'],
    operator_slug: null,
    operator_confidence: null,
    total_properties: 3,
    total_violations: 5,
    total_value: 500000,
    properties: [
      { id: 'p1', addr: '123 Main St', lat: 42.88, lng: -78.87, violations_open: 2, complaints_311_12mo: 0, demolished: false },
      { id: 'p2', addr: '456 Elm Ave', lat: 42.89, lng: -78.88, violations_open: 0, complaints_311_12mo: 1, demolished: false },
    ],
  }

  it('shows the owner display name', () => {
    t.renderPortfolio(basePortfolio)
    expect(document.getElementById('panel-content').textContent).toContain('ACME LLC')
  })

  it('shows the property count in the stat grid', () => {
    t.renderPortfolio(basePortfolio)
    expect(document.getElementById('panel-content').textContent).toContain('3')
  })

  it('shows the formatted portfolio value', () => {
    t.renderPortfolio(basePortfolio)
    expect(document.getElementById('panel-content').textContent).toContain('$500K')
  })

  it('renders a table row for each property', () => {
    t.renderPortfolio(basePortfolio)
    const rows = document.querySelectorAll('#panel-content .portfolio tbody tr')
    expect(rows.length).toBe(2)
    expect(rows[0].textContent).toContain('123 Main St')
    expect(rows[1].textContent).toContain('456 Elm Ave')
  })

  it('marks open-violation cells as bad', () => {
    t.renderPortfolio(basePortfolio)
    const badCell = document.querySelector('#panel-content .portfolio .bad')
    expect(badCell).not.toBeNull()
    expect(badCell.textContent.trim()).toBe('2')
  })

  it('shows operator CTA when operator_slug is set', () => {
    const p = { ...basePortfolio, operator_slug: 'big-operator' }
    t.renderPortfolio(p)
    const cta = document.querySelector('#panel-content .cta')
    expect(cta).not.toBeNull()
    expect(cta.textContent).toContain('mailing address')
  })

  it('shows highlight button', () => {
    t.renderPortfolio(basePortfolio)
    const btn = document.querySelector('#panel-content .highlight-btn')
    expect(btn).not.toBeNull()
    expect(btn.textContent.trim()).toContain('Highlight on map')
  })

  it('shows "toggled" state on highlight button when mapFilter matches', () => {
    t.state.mapFilter = { kind: 'owner', slug: 'acme-llc', label: 'ACME LLC', count: 2 }
    t.renderPortfolio(basePortfolio)
    const btn = document.querySelector('#panel-content .highlight-btn')
    expect(btn.classList.contains('toggled')).toBe(true)
    expect(btn.textContent).toContain('✓')
  })

  it('shows name variants when there are multiple', () => {
    const p = { ...basePortfolio, owner_variants: ['ACME LLC', 'Acme Properties LLC', 'ACME PROP LLC'] }
    t.renderPortfolio(p)
    expect(document.getElementById('panel-content').textContent).toContain('Acme Properties LLC')
  })

  it('escapes HTML in owner display name', () => {
    const p = { ...basePortfolio, owner_display: '<b>Bad Actor</b>' }
    t.renderPortfolio(p)
    // The .addr div renders the owner name as text content — verify it's
    // encoded there (jsdom re-serializes attribute data-label without
    // re-escaping, so we check the rendered text node, not the raw innerHTML).
    const addrDiv = document.querySelector('#panel-content .addr')
    expect(addrDiv).not.toBeNull()
    // innerHTML of the addr div should show the entity-encoded form
    expect(addrDiv.innerHTML).not.toContain('<b>')
    expect(addrDiv.innerHTML).toContain('&lt;b&gt;')
    // textContent will be the decoded literal string — no HTML injection
    expect(addrDiv.textContent).toBe('<b>Bad Actor</b>')
  })
})

// ---------------------------------------------------------------------------
// renderLeaderboards
// ---------------------------------------------------------------------------

describe('renderLeaderboards', () => {
  const emptyBoards = {
    by_open_violations: [],
    by_all_violations: [],
    by_properties: [],
    by_value: [],
    by_complaints_311: [],
  }

  it('shows a loading message when topOperators is null', () => {
    t.state.topOperators = null
    t.state.topOwners = null
    t.renderLeaderboards()
    expect(document.getElementById('panel-content').textContent).toContain('Loading')
  })

  it('renders the five tab buttons', () => {
    t.state.topOperators = emptyBoards
    t.state.topOwners = emptyBoards
    t.renderLeaderboards()
    const tabs = document.querySelectorAll('#panel-content .tabs button')
    expect(tabs.length).toBe(5)
  })

  it('marks the active tab', () => {
    t.state.topOperators = emptyBoards
    t.state.topOwners = emptyBoards
    t.state.activeBoard = 'by_open_violations'
    t.renderLeaderboards()
    const active = document.querySelector('#panel-content .tabs button.active')
    expect(active).not.toBeNull()
    expect(active.dataset.board).toBe('by_open_violations')
  })

  it('renders a kind toggle with two buttons', () => {
    t.state.topOperators = emptyBoards
    t.state.topOwners = emptyBoards
    t.renderLeaderboards()
    const toggle = document.querySelectorAll('#panel-content .kind-toggle button')
    expect(toggle.length).toBe(2)
  })

  it('shows operator rows from topOperators data', () => {
    t.state.activeBoardKind = 'operators'
    t.state.topOperators = {
      ...emptyBoards,
      by_open_violations: [
        { slug: 'big-llc', label: 'Big LLC Group', owners_n: 3, properties: 12, open: 25, total_value: 1_200_000, all_violations: 50, complaints_311_12mo: 10, confidence: 'high', evidence: '' },
        { slug: 'mid-llc', label: 'Mid Properties',  owners_n: 1, properties: 4,  open: 8,  total_value: 400_000,   all_violations: 20, complaints_311_12mo: 3,  confidence: 'medium', evidence: '' },
      ],
    }
    t.state.topOwners = emptyBoards
    t.renderLeaderboards()
    const items = document.querySelectorAll('#panel-content .leaderboard li')
    expect(items.length).toBe(2)
    expect(items[0].textContent).toContain('Big LLC Group')
    expect(items[1].textContent).toContain('Mid Properties')
  })

  it('shows owner rows when activeBoardKind is owners', () => {
    t.state.activeBoardKind = 'owners'
    t.state.topOwners = {
      ...emptyBoards,
      by_open_violations: [
        { slug: 'john-smith', display: 'John Smith', properties: 2, open: 5, total_value: 200_000, all_violations: 12, complaints_311_12mo: 2 },
      ],
    }
    t.state.topOperators = emptyBoards
    t.renderLeaderboards()
    const items = document.querySelectorAll('#panel-content .leaderboard li')
    expect(items.length).toBe(1)
    expect(items[0].textContent).toContain('John Smith')
  })

  it('assigns rank classes to the top 3 items', () => {
    t.state.activeBoardKind = 'owners'
    t.state.topOwners = {
      ...emptyBoards,
      by_open_violations: [
        { slug: 'a', display: 'A', properties: 1, open: 10, total_value: 0, all_violations: 10, complaints_311_12mo: 0 },
        { slug: 'b', display: 'B', properties: 1, open: 8,  total_value: 0, all_violations: 8,  complaints_311_12mo: 0 },
        { slug: 'c', display: 'C', properties: 1, open: 6,  total_value: 0, all_violations: 6,  complaints_311_12mo: 0 },
      ],
    }
    t.state.topOperators = emptyBoards
    t.renderLeaderboards()
    const items = document.querySelectorAll('#panel-content .leaderboard li')
    expect(items[0].classList.contains('top1')).toBe(true)
    expect(items[1].classList.contains('top2')).toBe(true)
    expect(items[2].classList.contains('top3')).toBe(true)
  })

  it('shows "no entries" message for an empty board', () => {
    t.state.topOperators = emptyBoards
    t.state.topOwners = emptyBoards
    t.renderLeaderboards()
    expect(document.getElementById('panel-content').textContent).toContain('No entries')
  })
})
