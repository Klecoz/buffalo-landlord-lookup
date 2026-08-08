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

// ---------------------------------------------------------------------------
// Owner rows
//
// address_index.json carries owner rows alongside address rows; owner rows are
// tagged t === "o" and route to the portfolio view instead of the map.
// ---------------------------------------------------------------------------

// Owner rows put their name in a .name span so the "42 properties" sub-label
// doesn't bleed into the row's text; address rows are bare text.
function labelOf(li) {
  return (li.querySelector('.name') || li).textContent
}

const OWNER_INDEX = [
  ...SAMPLE_INDEX,
  { t: 'o', name: 'ACME LLC', slug: 'acme-llc', n: 42 },
  { t: 'o', name: 'MAINSAIL HOLDINGS LLC', slug: 'mainsail-holdings-llc', n: 7 },
  { t: 'o', name: 'SOLO OWNER LLC', slug: 'solo-owner-llc', n: 1 },
]

describe('search — owner matching', () => {
  beforeEach(() => {
    t.state.addressIndex = OWNER_INDEX.slice()
    window.openPortfolio = vi.fn()
  })

  it('matches owner names case-insensitively', () => {
    dispatchInput('acme')
    const items = resultItems()
    expect(items.length).toBe(1)
    expect(items[0].dataset.slug).toBe('acme-llc')
  })

  it('labels an owner row with its portfolio size', () => {
    dispatchInput('acme')
    expect(resultItems()[0].querySelector('.sub').textContent).toBe('42 properties')
  })

  it('singularizes the sub-label for a one-property owner', () => {
    dispatchInput('solo')
    expect(resultItems()[0].querySelector('.sub').textContent).toBe('1 property')
  })

  it('marks owner rows so they read differently from addresses', () => {
    dispatchInput('mainsail')
    const items = resultItems()
    expect(items[0].classList.contains('owner-hit')).toBe(true)
    expect(items[0].dataset.id).toBeUndefined()
  })

  it('opens the portfolio instead of the map when an owner row is chosen', () => {
    dispatchInput('acme')
    resultItems()[0].click()
    expect(window.openPortfolio).toHaveBeenCalledWith('acme-llc')
    expect(t.state.map.flyTo).not.toHaveBeenCalled()
    expect(document.getElementById('search-results').classList.contains('open')).toBe(false)
  })

  it('puts the owner name — not the sub-label — in the input', () => {
    dispatchInput('acme')
    resultItems()[0].click()
    expect(document.getElementById('search').value).toBe('ACME LLC')
  })

  it('escapes HTML in owner names', () => {
    t.state.addressIndex = [
      { t: 'o', name: '<img src=x onerror=alert(1)> LLC', slug: 'evil', n: 1 },
    ]
    dispatchInput('img')
    const html = document.getElementById('search-results').innerHTML
    expect(html).not.toContain('<img src=x')
    expect(html).toContain('&lt;img')
  })

  it('renders a non-numeric portfolio size as 0 rather than markup', () => {
    t.state.addressIndex = [
      { t: 'o', name: 'SNEAKY LLC', slug: 'sneaky', n: '<b>9</b>' },
    ]
    dispatchInput('sneaky')
    expect(resultItems()[0].querySelector('.sub').textContent).toBe('0 properties')
    expect(document.getElementById('search-results').innerHTML).not.toContain('<b>')
  })
})

describe('search — mixed address and owner results', () => {
  beforeEach(() => {
    t.state.addressIndex = OWNER_INDEX.slice()
    window.openPortfolio = vi.fn()
  })

  it('returns both kinds for a query that hits both', () => {
    dispatchInput('main')
    const items = resultItems()
    // Two MAIN ST addresses plus MAINSAIL HOLDINGS LLC.
    expect(items.length).toBe(3)
    expect(items.map(labelOf)).toEqual([
      '100 MAIN ST', '200 MAIN ST', 'MAINSAIL HOLDINGS LLC',
    ])
  })

  it('ranks prefix matches above mid-string matches within each kind', () => {
    t.state.addressIndex = [
      { addr: '10 NORTH ELM ST', id: 'p-mid', lat: 42, lng: -78, owner_slug: 'x' },
      { addr: 'ELM CIRCLE 4', id: 'p-pre', lat: 42, lng: -78, owner_slug: 'x' },
      { t: 'o', name: 'WEST ELM HOLDINGS LLC', slug: 'west-elm', n: 2 },
      { t: 'o', name: 'ELM STREET PARTNERS LLC', slug: 'elm-street-partners', n: 3 },
    ]
    dispatchInput('elm')
    expect(resultItems().map(labelOf)).toEqual([
      'ELM CIRCLE 4', '10 NORTH ELM ST',
      'ELM STREET PARTNERS LLC', 'WEST ELM HOLDINGS LLC',
    ])
  })

  it('keeps addresses ahead of an owner whose name merely starts with the street', () => {
    // "100 MAIN ST" matches mid-string and "MAINSAIL" matches at position 0.
    // Ranking on prefix alone would put the LLC first, which is wrong: every
    // address begins with a house number, so street queries never prefix-match.
    dispatchInput('main')
    expect(resultItems().map(labelOf)[0]).toBe('100 MAIN ST')
  })

  it('reserves rows for owners when addresses would otherwise fill the list', () => {
    t.state.addressIndex = [
      ...Array.from({ length: 30 }, (_, i) => ({
        addr: `${i} CLOVER ST`, id: `c-${i}`, lat: 42, lng: -78, owner_slug: 'x',
      })),
      { t: 'o', name: 'CLOVER HOLDINGS LLC', slug: 'clover-holdings', n: 9 },
    ]
    dispatchInput('clover')
    const items = resultItems()
    expect(items.length).toBe(12)
    expect(labelOf(items[11])).toBe('CLOVER HOLDINGS LLC')
  })

  it('puts addresses before owners when both match at the same position', () => {
    t.state.addressIndex = [
      { t: 'o', name: 'OAKWOOD LLC', slug: 'oakwood', n: 5 },
      { addr: 'OAK AVE 12', id: 'p-oak', lat: 42, lng: -78, owner_slug: 'x' },
    ]
    dispatchInput('oak')
    expect(resultItems().map(labelOf)).toEqual(['OAK AVE 12', 'OAKWOOD LLC'])
  })

  it('caps mixed results at 12', () => {
    t.state.addressIndex = [
      ...Array.from({ length: 20 }, (_, i) => ({
        addr: `${i} TESTROAD ST`, id: `t-${i}`, lat: 42, lng: -78, owner_slug: 'x',
      })),
      ...Array.from({ length: 20 }, (_, i) => ({
        t: 'o', name: `TESTROAD HOLDINGS ${i} LLC`, slug: `tr-${i}`, n: i + 1,
      })),
    ]
    dispatchInput('TESTROAD')
    expect(resultItems().length).toBe(12)
  })
})

describe('search — keyboard navigation across both result kinds', () => {
  beforeEach(() => {
    t.state.addressIndex = OWNER_INDEX.slice()
    window.openPortfolio = vi.fn()
  })

  function press(key) {
    document.getElementById('search')
      .dispatchEvent(new KeyboardEvent('keydown', { key, bubbles: true }))
  }

  it('arrows through address rows and owner rows alike', () => {
    dispatchInput('main')
    const input = document.getElementById('search')
    press('ArrowDown')
    expect(input.getAttribute('aria-activedescendant')).toBe('search-opt-0')
    press('ArrowDown')
    press('ArrowDown')
    expect(input.getAttribute('aria-activedescendant')).toBe('search-opt-2')
    expect(resultItems()[2].classList.contains('owner-hit')).toBe(true)
  })

  it('wraps from the last owner row back to the first address row', () => {
    dispatchInput('main')
    press('ArrowUp')  // no active row yet → last option
    expect(document.getElementById('search').getAttribute('aria-activedescendant'))
      .toBe('search-opt-2')
  })

  it('opens the highlighted owner row on Enter', () => {
    dispatchInput('main')
    press('ArrowDown'); press('ArrowDown'); press('ArrowDown')
    press('Enter')
    expect(window.openPortfolio).toHaveBeenCalledWith('mainsail-holdings-llc')
  })

  it('Enter with no highlight still opens the first (address) match', () => {
    dispatchInput('main')
    press('Enter')
    expect(window.openPortfolio).not.toHaveBeenCalled()
    expect(t.state.map.flyTo).toHaveBeenCalled()
  })

  it('does not select the "No matches" row with Enter', () => {
    dispatchInput('xyz123notfound')
    press('Enter')
    expect(window.openPortfolio).not.toHaveBeenCalled()
    expect(t.state.map.flyTo).not.toHaveBeenCalled()
  })
})
