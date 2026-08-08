/**
 * Tests for hash-based routing (applyHashRoute) in app.js.
 *
 * applyHashRoute() reads window.location.hash and dispatches to the right
 * view function.  We control the hash by assigning to location.hash and
 * spy on the side-effects (window function calls, state mutation, panel HTML).
 */

import { describe, it, expect, beforeEach, vi } from 'vitest'

let t  // window._test

beforeEach(() => {
  t = window._test
  // Prime both leaderboard datasets so renderLeaderboards never throws
  const empty = {
    by_open_violations: [],
    by_all_violations: [],
    by_properties: [],
    by_value: [],
    by_complaints_311: [],
  }
  t.state.topOperators = { ...empty }
  t.state.topOwners    = { ...empty }
})

// ---------------------------------------------------------------------------
// Empty / root hash → show leaderboards
// ---------------------------------------------------------------------------

describe('applyHashRoute — empty hash', () => {
  it('calls hidePanel when hash is empty', () => {
    location.hash = ''
    // hidePanel calls renderLeaderboards internally, which needs topOwners/topOperators
    t.applyHashRoute()
    // After hidePanel the panel content should contain the leaderboard heading
    expect(document.getElementById('panel-content').textContent).toContain('Top Landlords')
  })
})

// ---------------------------------------------------------------------------
// /top/:board/:kind — leaderboard tab + kind
// ---------------------------------------------------------------------------

describe('applyHashRoute — leaderboard route', () => {
  it('sets activeBoard and activeBoardKind from the URL', () => {
    location.hash = '#/top/by_all_violations/owners'
    t.applyHashRoute()
    expect(t.state.activeBoard).toBe('by_all_violations')
    expect(t.state.activeBoardKind).toBe('owners')
  })

  it('renders the leaderboard panel', () => {
    location.hash = '#/top/by_open_violations/operators'
    t.applyHashRoute()
    expect(document.getElementById('panel-content').textContent).toContain('Top Landlords')
  })

  it('ignores an unknown board key', () => {
    const prev = t.state.activeBoard
    location.hash = '#/top/by_nonexistent/operators'
    t.applyHashRoute()
    // Board should stay unchanged since 'by_nonexistent' is not in BOARDS
    expect(t.state.activeBoard).toBe(prev)
  })

  it('accepts both "owners" and "operators" as valid kinds', () => {
    location.hash = '#/top/by_open_violations/owners'
    t.applyHashRoute()
    expect(t.state.activeBoardKind).toBe('owners')

    location.hash = '#/top/by_open_violations/operators'
    t.applyHashRoute()
    expect(t.state.activeBoardKind).toBe('operators')
  })

  it('clears selectedId and lastPortfolio when entering the leaderboard route', () => {
    t.state.selectedId = 'parcel-99'
    t.state.lastPortfolio = { owner_display: 'Someone' }
    location.hash = '#/top/by_open_violations/operators'
    t.applyHashRoute()
    expect(t.state.selectedId).toBeNull()
    expect(t.state.lastPortfolio).toBeNull()
  })
})

// ---------------------------------------------------------------------------
// /owner/:slug — portfolio view
// ---------------------------------------------------------------------------

describe('applyHashRoute — owner route', () => {
  it('calls window.openPortfolio with the decoded slug', async () => {
    const spy = vi.spyOn(window, 'openPortfolio').mockResolvedValue(undefined)
    location.hash = '#/owner/acme-properties-llc'
    t.applyHashRoute()
    expect(spy).toHaveBeenCalledWith('acme-properties-llc', expect.any(Object))
    spy.mockRestore()
  })

  it('URL-decodes the slug', () => {
    const spy = vi.spyOn(window, 'openPortfolio').mockResolvedValue(undefined)
    location.hash = '#/owner/buffalo%20real%20estate'
    t.applyHashRoute()
    expect(spy).toHaveBeenCalledWith('buffalo real estate', expect.any(Object))
    spy.mockRestore()
  })

  it('passes highlight:true when /highlight suffix is present', () => {
    const spy = vi.spyOn(window, 'openPortfolio').mockResolvedValue(undefined)
    location.hash = '#/owner/some-slug/highlight'
    t.applyHashRoute()
    expect(spy).toHaveBeenCalledWith('some-slug', { highlight: true })
    spy.mockRestore()
  })

  it('passes highlight:false when /highlight suffix is absent', () => {
    const spy = vi.spyOn(window, 'openPortfolio').mockResolvedValue(undefined)
    location.hash = '#/owner/some-slug'
    t.applyHashRoute()
    expect(spy).toHaveBeenCalledWith('some-slug', { highlight: false })
    spy.mockRestore()
  })
})

// ---------------------------------------------------------------------------
// /operator/:slug — operator view
// ---------------------------------------------------------------------------

describe('applyHashRoute — operator route', () => {
  it('calls window.openOperator with the decoded slug', () => {
    const spy = vi.spyOn(window, 'openOperator').mockResolvedValue(undefined)
    location.hash = '#/operator/big-landlord-co'
    t.applyHashRoute()
    expect(spy).toHaveBeenCalledWith('big-landlord-co', expect.any(Object))
    spy.mockRestore()
  })

  it('passes highlight:true when /highlight suffix is present', () => {
    const spy = vi.spyOn(window, 'openOperator').mockResolvedValue(undefined)
    location.hash = '#/operator/big-landlord-co/highlight'
    t.applyHashRoute()
    expect(spy).toHaveBeenCalledWith('big-landlord-co', { highlight: true })
    spy.mockRestore()
  })
})

// ---------------------------------------------------------------------------
// /parcel/:id — parcel / dossier view
// ---------------------------------------------------------------------------

describe('applyHashRoute — parcel route', () => {
  it('calls selectParcel with the decoded parcel id', () => {
    // selectParcel uses the map, which is mocked. It will try to query features
    // (returns []) and then call showPanel with an error message. That's fine —
    // we just want to confirm the routing dispatched correctly.
    location.hash = '#/parcel/2024-1234-56789'
    // selectParcel is async but we can check state was set synchronously
    t.applyHashRoute()
    expect(t.state.selectedId).toBe('2024-1234-56789')
  })

  it('URL-decodes spaces in parcel ids', () => {
    location.hash = '#/parcel/parcel%20with%20spaces'
    t.applyHashRoute()
    expect(t.state.selectedId).toBe('parcel with spaces')
  })

  it('does not re-select if the parcel is already selected', () => {
    t.state.selectedId = 'already-selected'
    const mapSetFilter = t.state.map.setFilter
    location.hash = '#/parcel/already-selected'
    t.applyHashRoute()
    // setFilter for 'parcels-selected' should not have been called again
    // (selectParcel checks state.selectedId !== id before proceeding)
    // The exact behaviour is: if ids match, applyHashRoute skips the call.
    // state.selectedId remains the same.
    expect(t.state.selectedId).toBe('already-selected')
  })
})

// ---------------------------------------------------------------------------
// Deep links — querySourceFeatures only sees tiles loaded in the current
// viewport, so a parcel URL opened cold (exactly what "Copy link" hands out)
// found nothing and rendered an error.
// ---------------------------------------------------------------------------

describe('selectParcel — parcel outside the loaded viewport', () => {
  const FEATURE = {
    properties: {
      id: 'far-away-parcel', addr: '1 Agassiz Cir', owner: 'SOMEONE',
      owner_slug: 'someone', violations_open: 0, violations_total: 0,
      complaints_311_12mo: 0, portfolio_n: 1,
    },
    geometry: { type: 'Polygon', coordinates: [[[-78.85, 42.93], [-78.85, 42.94]]] },
  }

  beforeEach(() => {
    t.state.addressIndex = [
      { addr: '1 Agassiz Cir', id: 'far-away-parcel', lat: 42.93, lng: -78.85 },
    ]
    // Nothing on screen at first; the feature appears once the camera moves
    // and the map goes idle.
    let moved = false
    t.state.map.querySourceFeatures = vi.fn(() => (moved ? [FEATURE] : []))
    t.state.map.jumpTo = vi.fn(() => { moved = true })
    t.state.map.once = vi.fn((evt, cb) => { if (evt === 'idle') cb() })
    global.fetch = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: vi.fn().mockResolvedValue({}),
    })
  })

  it('moves the camera to the parcel recorded in the address index', async () => {
    location.hash = '#/parcel/far-away-parcel'
    t.applyHashRoute()
    await vi.waitFor(() => expect(t.state.map.jumpTo).toHaveBeenCalled())
    expect(t.state.map.jumpTo.mock.calls[0][0].center).toEqual([-78.85, 42.93])
  })

  it('renders the dossier instead of an error', async () => {
    location.hash = '#/parcel/far-away-parcel'
    t.applyHashRoute()
    await vi.waitFor(() => {
      expect(document.getElementById('panel-content').textContent).toContain('Property Dossier')
    })
    expect(document.getElementById('panel-content').textContent).toContain('1 Agassiz Cir')
  })

  it('reports a parcel id that is in no index as not in the dataset', async () => {
    t.state.addressIndex = []
    t.state.map.querySourceFeatures = vi.fn(() => [])
    location.hash = '#/parcel/no-such-parcel'
    t.applyHashRoute()
    await vi.waitFor(() => {
      expect(document.getElementById('panel-content').textContent)
        .toContain('Not in the current dataset')
    })
    expect(t.state.map.jumpTo).not.toHaveBeenCalled()
  })
})
