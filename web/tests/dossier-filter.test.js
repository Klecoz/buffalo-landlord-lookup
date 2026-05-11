/**
 * Tests for applyDossierFilters and buildPortfolioCsv in app.js.
 *
 * Covers:
 *   A. Dossier filter — open/closed status filter
 *   B. Dossier filter — open/closed counts in chip labels
 *   C. Dossier filter — date filter anchored to dataset max date
 *   D. Dossier filter — composes status × date
 *   E. Dossier — sorted by date desc
 *   F. buildPortfolioCsv("portfolio") — null when state.lastPortfolio is null
 *   G. buildPortfolioCsv("portfolio") — header row + RFC-4180 escaping
 *   H. buildPortfolioCsv("operator") — reads from state.lastOperator
 */

import { describe, it, expect, beforeEach } from 'vitest'

let t

beforeEach(() => {
  t = window._test
})

// ---------------------------------------------------------------------------
// Shared helpers
// ---------------------------------------------------------------------------

const baseProps = {
  addr: '123 Main St',
  owner: 'Test Owner LLC',
  owner_slug: 'test-owner-llc',
  portfolio_n: 1,
  violations_open: 0,
  violations_total: 0,
  complaints_311_12mo: 0,
  demolished: false,
  concern_score: 0,
}

/** Click a chip and trigger the filter update it wires. */
function clickChip(selector) {
  const chip = document.querySelector(selector)
  if (!chip) throw new Error(`Chip not found: ${selector}`)
  chip.click()
}

/** Return an array of computed display values for all <li>s in a list. */
function liDisplayValues(target) {
  return [...document.querySelectorAll(`#panel ul[data-list="${target}"] li`)]
    .map(li => li.style.display)
}

// ---------------------------------------------------------------------------
// A. Status filter — show/hide open vs closed
// ---------------------------------------------------------------------------

describe('applyDossierFilters — status filter', () => {
  it('hides closed <li>s when "Open" chip is clicked', () => {
    const dossier = {
      violations: [
        { date: '2026-01-01', status: 'ACTIVE',  description: 'Active violation 1' },
        { date: '2026-01-02', status: 'ACTIVE',  description: 'Active violation 2' },
        { date: '2025-06-01', status: 'Closed',  description: 'Closed violation 1' },
        { date: '2025-05-01', status: 'Closed',  description: 'Closed violation 2' },
      ],
      complaints: [],
    }
    t.renderDossier(baseProps, dossier)

    // Before filtering: counts header should show all 4, 2 open
    const countsEl = document.querySelector('#panel [data-counts="violations"]')
    expect(countsEl.textContent).toContain('4 total')
    expect(countsEl.textContent).toContain('2 open')

    // Click the "Open" chip
    clickChip('button.dossier-chip[data-target="violations"][data-filter="status"][data-value="active"]')

    const displays = liDisplayValues('violations')
    // Two ACTIVE items visible, two Closed items hidden
    const visible = displays.filter(d => d !== 'none')
    const hidden  = displays.filter(d => d === 'none')
    expect(visible.length).toBe(2)
    expect(hidden.length).toBe(2)
  })

  it('resets visibility when "All" chip is clicked after filtering', () => {
    const dossier = {
      violations: [
        { date: '2026-01-01', status: 'ACTIVE', description: 'Active' },
        { date: '2025-06-01', status: 'Closed', description: 'Closed' },
      ],
      complaints: [],
    }
    t.renderDossier(baseProps, dossier)

    // Activate "Open" filter
    clickChip('button.dossier-chip[data-target="violations"][data-filter="status"][data-value="active"]')
    // Now click "All"
    clickChip('button.dossier-chip[data-target="violations"][data-filter="status"][data-value="all"]')

    const displays = liDisplayValues('violations')
    expect(displays.every(d => d !== 'none')).toBe(true)
  })
})

// ---------------------------------------------------------------------------
// B. Chip label counts
// ---------------------------------------------------------------------------

describe('applyDossierFilters — chip label counts', () => {
  it('shows correct total, open, and closed counts in chip labels', () => {
    const active = Array.from({ length: 5 }, (_, i) => ({
      date: `2026-0${i + 1}-01`, status: 'ACTIVE', description: `Active ${i}`,
    }))
    const closed = Array.from({ length: 3 }, (_, i) => ({
      date: `2025-0${i + 1}-01`, status: 'Closed', description: `Closed ${i}`,
    }))
    const dossier = { violations: [...active, ...closed], complaints: [] }
    t.renderDossier(baseProps, dossier)

    const allChip    = document.querySelector('button.dossier-chip[data-target="violations"][data-filter="status"][data-value="all"]')
    const openChip   = document.querySelector('button.dossier-chip[data-target="violations"][data-filter="status"][data-value="active"]')
    const closedChip = document.querySelector('button.dossier-chip[data-target="violations"][data-filter="status"][data-value="closed"]')

    expect(allChip.querySelector('.chip-count').textContent).toBe('8')
    expect(openChip.querySelector('.chip-count').textContent).toBe('5')
    expect(closedChip.querySelector('.chip-count').textContent).toBe('3')
  })
})

// ---------------------------------------------------------------------------
// C. Date filter anchored to dataset max date
// ---------------------------------------------------------------------------

describe('applyDossierFilters — date filter', () => {
  beforeEach(() => {
    t.state.meta = { code_violations_max_date: '2026-05-01' }
  })

  it('shows only items within 90 days of anchor when "Last 90d" is clicked', () => {
    // Anchor: 2026-05-01. 90 days before = 2026-01-31.
    // 2026-04-25 is within 90d ✓
    // 2026-01-15 is outside 90d (before 2026-01-31) ✗
    // 2025-04-01 is way outside ✗
    const dossier = {
      violations: [
        { date: '2026-04-25', status: 'ACTIVE', description: 'Recent' },
        { date: '2026-01-15', status: 'ACTIVE', description: 'Mid-year' },
        { date: '2025-04-01', status: 'ACTIVE', description: 'Old' },
      ],
      complaints: [],
    }
    t.renderDossier(baseProps, dossier)

    clickChip('button.dossier-chip[data-target="violations"][data-filter="date"][data-value="90"]')

    const lis = [...document.querySelectorAll('#panel ul[data-list="violations"] li')]
    const visible = lis.filter(li => li.style.display !== 'none')
    const hidden  = lis.filter(li => li.style.display === 'none')
    expect(visible.length).toBe(1)
    expect(hidden.length).toBe(2)
    expect(visible[0].dataset.iso).toBe('2026-04-25')
  })

  it('shows items within last year when "Last year" is clicked', () => {
    // Anchor: 2026-05-01. 365 days before = 2025-05-01 (exclusive).
    // 2026-04-25 ✓, 2026-01-15 ✓, 2025-04-01 ✗ (before 2025-05-01)
    const dossier = {
      violations: [
        { date: '2026-04-25', status: 'ACTIVE', description: 'Recent' },
        { date: '2026-01-15', status: 'ACTIVE', description: 'Mid-year' },
        { date: '2025-04-01', status: 'ACTIVE', description: 'Old' },
      ],
      complaints: [],
    }
    t.renderDossier(baseProps, dossier)

    clickChip('button.dossier-chip[data-target="violations"][data-filter="date"][data-value="365"]')

    const lis = [...document.querySelectorAll('#panel ul[data-list="violations"] li')]
    const visible = lis.filter(li => li.style.display !== 'none')
    const hidden  = lis.filter(li => li.style.display === 'none')
    expect(visible.length).toBe(2)
    expect(hidden.length).toBe(1)
    const visibleIsos = visible.map(li => li.dataset.iso).sort()
    expect(visibleIsos).toContain('2026-04-25')
    expect(visibleIsos).toContain('2026-01-15')
    expect(hidden[0].dataset.iso).toBe('2025-04-01')
  })

  it('shows all items when "All time" is clicked', () => {
    const dossier = {
      violations: [
        { date: '2026-04-25', status: 'ACTIVE', description: 'Recent' },
        { date: '2026-01-15', status: 'ACTIVE', description: 'Mid-year' },
        { date: '2025-04-01', status: 'ACTIVE', description: 'Old' },
      ],
      complaints: [],
    }
    t.renderDossier(baseProps, dossier)

    // First filter to 90d, then reset
    clickChip('button.dossier-chip[data-target="violations"][data-filter="date"][data-value="90"]')
    clickChip('button.dossier-chip[data-target="violations"][data-filter="date"][data-value="all"]')

    const lis = [...document.querySelectorAll('#panel ul[data-list="violations"] li')]
    const hidden = lis.filter(li => li.style.display === 'none')
    expect(hidden.length).toBe(0)
  })
})

// ---------------------------------------------------------------------------
// D. Status × date composition
// ---------------------------------------------------------------------------

describe('applyDossierFilters — status × date composition', () => {
  it('shows only the recent ACTIVE item when "Open" + "Last 90d" are active', () => {
    t.state.meta = { code_violations_max_date: '2026-05-01' }
    // Anchor: 2026-05-01. 90d cutoff: 2026-01-31.
    const dossier = {
      violations: [
        { date: '2026-04-25', status: 'ACTIVE', description: 'Recent ACTIVE' },   // ✓
        { date: '2025-01-01', status: 'ACTIVE', description: 'Ancient ACTIVE' },  // ✗ too old
        { date: '2026-04-20', status: 'Closed', description: 'Recent Closed' },   // ✗ wrong status
        { date: '2025-01-02', status: 'Closed', description: 'Ancient Closed' },  // ✗ both wrong
      ],
      complaints: [],
    }
    t.renderDossier(baseProps, dossier)

    clickChip('button.dossier-chip[data-target="violations"][data-filter="status"][data-value="active"]')
    clickChip('button.dossier-chip[data-target="violations"][data-filter="date"][data-value="90"]')

    const lis = [...document.querySelectorAll('#panel ul[data-list="violations"] li')]
    const visible = lis.filter(li => li.style.display !== 'none')
    expect(visible.length).toBe(1)
    expect(visible[0].dataset.iso).toBe('2026-04-25')
    expect(visible[0].dataset.status).toBe('ACTIVE')
  })
})

// ---------------------------------------------------------------------------
// E. Violations sorted by date descending
// ---------------------------------------------------------------------------

describe('renderDossier — sort order', () => {
  it('renders violations in descending date order', () => {
    const dossier = {
      violations: [
        { date: '2024-01-01', status: 'ACTIVE', description: 'Oldest' },
        { date: '2026-04-01', status: 'ACTIVE', description: 'Newest' },
        { date: '2025-06-01', status: 'ACTIVE', description: 'Middle' },
      ],
      complaints: [],
    }
    t.renderDossier(baseProps, dossier)

    const lis = [...document.querySelectorAll('#panel ul[data-list="violations"] li')]
    expect(lis.length).toBe(3)
    expect(lis[0].dataset.iso).toBe('2026-04-01')
    expect(lis[1].dataset.iso).toBe('2025-06-01')
    expect(lis[2].dataset.iso).toBe('2024-01-01')
  })
})

// ---------------------------------------------------------------------------
// F. buildPortfolioCsv — returns null when state.lastPortfolio is null
// ---------------------------------------------------------------------------

describe('buildPortfolioCsv — null guard', () => {
  it('returns null when state.lastPortfolio is null', () => {
    t.state.lastPortfolio = null
    expect(t.buildPortfolioCsv('portfolio')).toBeNull()
  })

  it('returns null when state.lastOperator is null and scope is "operator"', () => {
    t.state.lastOperator = null
    expect(t.buildPortfolioCsv('operator')).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// G. buildPortfolioCsv — header row + RFC-4180 escaping
// ---------------------------------------------------------------------------

describe('buildPortfolioCsv — header and escaping', () => {
  it('produces the exact header row and CRLF separators', () => {
    t.state.lastPortfolio = {
      _slug: 'test-owner',
      properties: [
        {
          addr: 'Simple St',
          violations_open: 0,
          violations_total: 0,
          complaints_311_12mo: 0,
          value: 100000,
          demolished: false,
          lat: 42.88,
          lng: -78.87,
          id: 'p1',
        },
      ],
    }
    const csv = t.buildPortfolioCsv('portfolio')
    const lines = csv.split('\r\n')
    expect(lines[0]).toBe('address,open_violations,total_violations,complaints_311_12mo,value,demolished,lat,lng,parcel_id')
  })

  it('uses CRLF row separator', () => {
    t.state.lastPortfolio = {
      _slug: 'test-owner',
      properties: [
        { addr: 'A St', violations_open: 0, violations_total: 0, complaints_311_12mo: 0, value: 0, demolished: false, lat: 42.0, lng: -78.0, id: 'a1' },
        { addr: 'B St', violations_open: 1, violations_total: 2, complaints_311_12mo: 0, value: 0, demolished: false, lat: 42.1, lng: -78.1, id: 'b1' },
      ],
    }
    const csv = t.buildPortfolioCsv('portfolio')
    // Should have exactly 3 CRLF sequences: after header, after row 1, after row 2
    const crlfCount = (csv.match(/\r\n/g) || []).length
    expect(crlfCount).toBe(3)
  })

  it('quotes fields containing commas, escapes embedded double-quotes per RFC 4180', () => {
    // addr: '123, "Main" St' — contains both comma and quotes
    t.state.lastPortfolio = {
      _slug: 'acme',
      properties: [
        {
          addr: '123, "Main" St',
          violations_open: 2,
          violations_total: 5,
          complaints_311_12mo: 1,
          value: 300000,
          demolished: false,
          lat: 42.88,
          lng: -78.87,
          id: 'p1',
        },
      ],
    }
    const csv = t.buildPortfolioCsv('portfolio')
    // The field should be: "123, ""Main"" St"
    expect(csv).toContain('"123, ""Main"" St"')
  })

  it('quotes fields containing a newline character', () => {
    t.state.lastPortfolio = {
      _slug: 'acme',
      properties: [
        {
          addr: 'No newlines\nhere',
          violations_open: 0,
          violations_total: 0,
          complaints_311_12mo: 0,
          value: 0,
          demolished: true,
          lat: 42.89,
          lng: -78.88,
          id: 'p2',
        },
      ],
    }
    const csv = t.buildPortfolioCsv('portfolio')
    // Field with embedded newline must be quoted
    expect(csv).toContain('"No newlines\nhere"')
  })
})

// ---------------------------------------------------------------------------
// H. buildPortfolioCsv("operator") — reads from state.lastOperator
// ---------------------------------------------------------------------------

describe('buildPortfolioCsv — operator scope', () => {
  it('reads from state.lastOperator and includes addr and id', () => {
    t.state.lastOperator = {
      operator_slug: 'big-op',
      properties: [
        {
          addr: '1 Test St',
          violations_open: 0,
          violations_total: 0,
          complaints_311_12mo: 0,
          value: 100,
          demolished: false,
          lat: 42.0,
          lng: -78.0,
          id: 'q1',
        },
      ],
    }
    const csv = t.buildPortfolioCsv('operator')
    expect(typeof csv).toBe('string')
    expect(csv).toContain('1 Test St')
    expect(csv).toContain('q1')
  })

  it('does not read from state.lastPortfolio when scope is "operator"', () => {
    t.state.lastOperator = {
      operator_slug: 'big-op',
      properties: [{ addr: 'Op St', violations_open: 0, violations_total: 0, complaints_311_12mo: 0, value: 0, demolished: false, lat: 42.0, lng: -78.0, id: 'op1' }],
    }
    t.state.lastPortfolio = {
      _slug: 'other-owner',
      properties: [{ addr: 'Owner St', violations_open: 0, violations_total: 0, complaints_311_12mo: 0, value: 0, demolished: false, lat: 42.0, lng: -78.0, id: 'own1' }],
    }
    const csv = t.buildPortfolioCsv('operator')
    expect(csv).toContain('Op St')
    expect(csv).not.toContain('Owner St')
  })
})
