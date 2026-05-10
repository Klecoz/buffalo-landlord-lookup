/**
 * Tests for the address-index search box (setupSearch in app.js).
 *
 * The search input is the only client-side interactive entry point with no
 * existing test coverage. It reads from state.addressIndex (populated at
 * bootstrap from data/address_index.json) and dispatches matches into the
 * #search-results <ul>.
 *
 * Implementation notes:
 *   - Search activates only at length >= 3 (substring, case-insensitive)
 *   - Results are capped at 12 entries
 *   - Selecting a result triggers map.flyTo + selectParcel
 *   - The bootstrap's DOMContentLoaded already fired by the time setup.js
 *     runs, so we have to call setupSearch ourselves to wire the listeners.
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'

let t  // window._test

const SAMPLE_INDEX = [
  { addr: '100 MAIN ST', id: 'p-100', lat: 42.88, lng: -78.87, owner_slug: 'acme-llc' },
  { addr: '200 MAIN ST', id: 'p-200', lat: 42.881, lng: -78.871, owner_slug: 'acme-llc' },
  { addr: '300 ELM ST', id: 'p-300', lat: 42.882, lng: -78.872, owner_slug: 'john-smith' },
  { addr: '400 OAK AVE', id: 'p-400', lat: 42.883, lng: -78.873, owner_slug: 'jane-doe' },
  { addr: "O'BRIEN PLACE 12", id: 'p-12',  lat: 42.884, lng: -78.874, owner_slug: 'mystery' },
]

beforeEach(() => {
  t = window._test
  t.state.addressIndex = SAMPLE_INDEX.slice()
  t.setupSearch()
})

function dispatchInput(value) {
  const input = document.getElementById('search')
  input.value = value
  input.dispatchEvent(new Event('input', { bubbles: true }))
}

function resultItems() {
  return [...document.querySelectorAll('#search-results li')]
}

// ---------------------------------------------------------------------------
// Threshold + empty-query behavior
// ---------------------------------------------------------------------------

describe('search — query length threshold', () => {
  it('renders nothing for empty query', () => {
    dispatchInput('')
    expect(document.getElementById('search-results').classList.contains('open')).toBe(false)
  })

  it('renders nothing for queries shorter than 3 characters', () => {
    dispatchInput('ma')
    expect(document.getElementById('search-results').classList.contains('open')).toBe(false)
  })

  it('activates at exactly 3 characters', () => {
    dispatchInput('mai')
    expect(document.getElementById('search-results').classList.contains('open')).toBe(true)
    expect(resultItems().length).toBe(2)
  })
})

// ---------------------------------------------------------------------------
// Match behavior
// ---------------------------------------------------------------------------

describe('search — matching', () => {
  it('returns substring matches against addr (case-insensitive)', () => {
    dispatchInput('main')
    const items = resultItems()
    expect(items.length).toBe(2)
    expect(items.map(li => li.textContent)).toEqual(['100 MAIN ST', '200 MAIN ST'])
  })

  it('uppercases the query so lowercase user input still matches', () => {
    dispatchInput('elm st')
    const items = resultItems()
    expect(items.length).toBe(1)
    expect(items[0].textContent).toBe('300 ELM ST')
  })

  it('returns a single "No matches" placeholder when nothing matches', () => {
    dispatchInput('xyz123notfound')
    const items = resultItems()
    expect(items.length).toBe(1)
    expect(items[0].classList.contains('empty')).toBe(true)
    expect(items[0].textContent).toBe('No matches')
  })

  it('caps results at 12 entries even when more match', () => {
    // Stuff the index with 50 hits.
    t.state.addressIndex = Array.from({ length: 50 }, (_, i) => ({
      addr: `${i} TESTROAD ST`,
      id: `t-${i}`,
      lat: 42, lng: -78,
      owner_slug: 'x',
    }))
    dispatchInput('TESTROAD')
    expect(resultItems().length).toBe(12)
  })
})

// ---------------------------------------------------------------------------
// XSS defense — addr is interpolated into innerHTML, so it must be escaped
// ---------------------------------------------------------------------------

describe('search — escapes HTML in addresses', () => {
  it('does not inject raw HTML from a malicious address', () => {
    t.state.addressIndex = [
      { addr: '<img src=x onerror=alert(1)> ST', id: 'evil', lat: 0, lng: 0 },
    ]
    dispatchInput('img')
    const html = document.getElementById('search-results').innerHTML
    expect(html).not.toContain('<img src=x')
    expect(html).toContain('&lt;img')
  })

  it('handles apostrophes in addresses without breaking parsing', () => {
    // jsdom's serializer decodes &#39; back to ' inside text/attr where
    // it's unambiguous, so we can't assert on the raw entity. What we
    // CAN assert: the row parses cleanly into a single <li> with the
    // expected text and no attribute injection.
    dispatchInput("o'brien")
    const items = resultItems()
    expect(items.length).toBe(1)
    expect(items[0].textContent).toBe("O'BRIEN PLACE 12")
    expect(items[0].dataset.id).toBe('p-12')
  })
})

// ---------------------------------------------------------------------------
// Selecting a result
// ---------------------------------------------------------------------------

describe('search — selecting a result', () => {
  it('flies the map to the result coordinates and closes the dropdown', () => {
    dispatchInput('main')
    const li = resultItems()[0]
    li.click()

    expect(t.state.map.flyTo).toHaveBeenCalledWith({
      center: [-78.87, 42.88],
      zoom: 18,
    })
    expect(document.getElementById('search-results').classList.contains('open')).toBe(false)
  })

  it('puts the selected address in the input', () => {
    dispatchInput('elm')
    resultItems()[0].click()
    expect(document.getElementById('search').value).toBe('300 ELM ST')
  })

  it('does not flyTo when result has no coordinates', () => {
    t.state.addressIndex = [{ addr: '500 NOLATLNG ST', id: 'p-500' }]
    dispatchInput('nolat')
    resultItems()[0].click()
    expect(t.state.map.flyTo).not.toHaveBeenCalled()
  })

  it('does nothing when clicking the empty placeholder', () => {
    dispatchInput('xyz123notfound')
    resultItems()[0].click()
    expect(t.state.map.flyTo).not.toHaveBeenCalled()
  })
})

// ---------------------------------------------------------------------------
// Outside-click closes the dropdown
// ---------------------------------------------------------------------------

describe('search — outside click', () => {
  it('closes the results dropdown when clicking outside #search-row', () => {
    dispatchInput('main')
    expect(document.getElementById('search-results').classList.contains('open')).toBe(true)

    // Click on something outside the search row.
    document.body.click()
    expect(document.getElementById('search-results').classList.contains('open')).toBe(false)
  })

  it('keeps the dropdown open when clicking inside #search-row', () => {
    dispatchInput('main')
    document.getElementById('search').click()
    expect(document.getElementById('search-results').classList.contains('open')).toBe(true)
  })
})
