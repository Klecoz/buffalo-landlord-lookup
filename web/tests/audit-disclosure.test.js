/**
 * Tests for renderAuditDisclosure() in app.js.
 *
 * The audit-disclosure block is the UI surface for several recent pipeline
 * features:
 *   - co-owner evidence pills              (commit af5ae08)
 *   - linked-operator cross-references     (commit af5ae08)
 *   - service-address pool classification  (commit afb29c4 / 3de3977)
 *   - cohesion-score explanation lines     (low-confidence cluster promotion)
 *
 * None of these had web-side tests until now.
 */

import { describe, it, expect, beforeEach } from 'vitest'

let renderAuditDisclosure

beforeEach(() => {
  ;({ renderAuditDisclosure } = window._test)
})

// Minimal valid operator with the smallest audit shape that produces output.
const baseAudit = {
  shared_mailing_address: '999 OFFSITE AVE | BUFFALO | NY | 14215',
  address_kind: 'street',
  member_count: 2,
  cohesion: { score: 80, explanation: 'shared filing date and registered agent' },
  pattern: 'normal',
  service_address: { classification: 'unknown' },
  person_dedups: [],
  co_owners: [],
  linked_operators: [],
}

const baseOp = {
  operator_label: 'ACME Group',
  operator_slug: 'acme-group',
  audit: baseAudit,
  owners: [
    { display: 'ACME LLC', slug: 'acme-llc', properties: 4 },
    { display: 'ACME PROPERTIES LLC', slug: 'acme-properties-llc', properties: 3 },
  ],
}

// Helper: render to a container we can query like a real fragment.
function render(op) {
  const div = document.createElement('div')
  div.innerHTML = renderAuditDisclosure(op)
  return div
}

// ---------------------------------------------------------------------------
// Fallback path (no audit block on the operator)
// ---------------------------------------------------------------------------

describe('renderAuditDisclosure — no audit block', () => {
  it('returns a plain evidence <details> when only op.evidence is present', () => {
    const html = renderAuditDisclosure({ evidence: 'shared mailing address' })
    expect(html).toContain('<details')
    expect(html).toContain('shared mailing address')
  })

  it('returns empty string when neither audit nor evidence is present', () => {
    expect(renderAuditDisclosure({})).toBe('')
  })

  it('escapes HTML in the evidence fallback', () => {
    const html = renderAuditDisclosure({ evidence: '<script>alert(1)</script>' })
    expect(html).not.toContain('<script>')
    expect(html).toContain('&lt;script&gt;')
  })
})

// ---------------------------------------------------------------------------
// Core rendering with a populated audit block
// ---------------------------------------------------------------------------

describe('renderAuditDisclosure — populated audit', () => {
  it('shows the shared mailing address line', () => {
    const div = render(baseOp)
    expect(div.textContent).toContain('999 OFFSITE AVE')
    expect(div.textContent).toContain('Shared mailing address')
  })

  it('shows the address kind in parentheses', () => {
    const div = render(baseOp)
    expect(div.textContent).toContain('street')
  })

  it('shows the cohesion explanation when present', () => {
    const div = render(baseOp)
    expect(div.textContent).toContain('shared filing date and registered agent')
    expect(div.textContent).toContain('score 80')
  })

  it('omits the cohesion line when explanation is missing', () => {
    const op = { ...baseOp, audit: { ...baseAudit, cohesion: { score: 80 } } }
    const div = render(op)
    expect(div.textContent).not.toContain('Cohesion')
  })

  it('renders one Member line per owner in the cluster', () => {
    const div = render(baseOp)
    const memberLis = [...div.querySelectorAll('li')].filter(li =>
      li.textContent.includes('Member')
    )
    expect(memberLis.length).toBe(2)
    expect(memberLis[0].textContent).toContain('ACME LLC')
    expect(memberLis[1].textContent).toContain('ACME PROPERTIES LLC')
  })

  it('uses singular "prop" for a single-property member', () => {
    const op = {
      ...baseOp,
      owners: [{ display: 'SOLO LLC', slug: 'solo-llc', properties: 1 }],
    }
    const div = render(op)
    const li = [...div.querySelectorAll('li')].find(l => l.textContent.includes('SOLO LLC'))
    expect(li.textContent).toContain('1 prop')
    expect(li.textContent).not.toContain('1 props')
  })
})

// ---------------------------------------------------------------------------
// Service-address pool classification (NYS DOS)
// ---------------------------------------------------------------------------

describe('renderAuditDisclosure — service-address classification', () => {
  it('renders the registered_agent warning with entity count', () => {
    const op = {
      ...baseOp,
      audit: {
        ...baseAudit,
        service_address: {
          classification: 'registered_agent',
          nys_dos_entity_count: 12345,
          threshold: 100,
        },
      },
    }
    const div = render(op)
    const warn = div.querySelector('li.audit-warn')
    expect(warn).not.toBeNull()
    expect(warn.textContent).toContain('12,345')
    expect(warn.textContent).toContain('threshold 100')
    expect(warn.textContent).toContain('registered-agent')
  })

  it('renders the shared_owner positive line (no DOS pool detected)', () => {
    const op = {
      ...baseOp,
      audit: { ...baseAudit, service_address: { classification: 'shared_owner' } },
    }
    const div = render(op)
    expect(div.textContent).toContain('No registered-agent pool detected')
    // Not an audit-warn — this is positive evidence, not a warning
    expect(div.querySelectorAll('li.audit-warn').length).toBe(0)
  })

  it('stays silent on classification: unknown', () => {
    const div = render(baseOp)  // baseAudit has classification:'unknown'
    expect(div.textContent).not.toContain('No registered-agent pool')
    expect(div.textContent).not.toContain('unrelated NY entities')
  })

  it('handles a missing service_address block without crashing', () => {
    const op = { ...baseOp, audit: { ...baseAudit, service_address: undefined } }
    expect(() => render(op)).not.toThrow()
  })
})

// ---------------------------------------------------------------------------
// Co-owner evidence pills
// ---------------------------------------------------------------------------

describe('renderAuditDisclosure — co-owners', () => {
  it('renders one co-owner line per entry', () => {
    const op = {
      ...baseOp,
      audit: {
        ...baseAudit,
        co_owners: [
          { name: 'JANE DOE', parcels: 5 },
          { name: 'BOB SMITH', parcels: 2 },
        ],
      },
    }
    const div = render(op)
    const items = [...div.querySelectorAll('li')].filter(li =>
      li.textContent.includes('Co-owner')
    )
    expect(items.length).toBe(2)
    expect(items[0].textContent).toContain('JANE DOE')
    expect(items[0].textContent).toContain('5 parcels')
    expect(items[1].textContent).toContain('BOB SMITH')
    expect(items[1].textContent).toContain('2 parcels')
  })

  it('uses singular "parcel" when count is 1', () => {
    const op = {
      ...baseOp,
      audit: { ...baseAudit, co_owners: [{ name: 'SOLO PERSON', parcels: 1 }] },
    }
    const div = render(op)
    const li = [...div.querySelectorAll('li')].find(l => l.textContent.includes('SOLO PERSON'))
    expect(li.textContent).toContain('1 parcel')
    expect(li.textContent).not.toMatch(/1 parcels/)
  })

  it('escapes HTML in co-owner names', () => {
    const op = {
      ...baseOp,
      audit: {
        ...baseAudit,
        co_owners: [{ name: '<img src=x onerror=alert(1)>', parcels: 1 }],
      },
    }
    const div = render(op)
    expect(div.innerHTML).not.toContain('<img src=x')
    expect(div.innerHTML).toContain('&lt;img')
  })
})

// ---------------------------------------------------------------------------
// Linked operators (the cross-reference feature)
// ---------------------------------------------------------------------------

describe('renderAuditDisclosure — linked operators', () => {
  const opWithLinks = {
    ...baseOp,
    audit: {
      ...baseAudit,
      linked_operators: [
        {
          operator_slug: 'big-landlord',
          operator_label: 'Big Landlord Group',
          co_owner: 'JANE DOE',
          parcels: 7,
        },
      ],
    },
  }

  it('renders one linked-operator line per entry', () => {
    const div = render(opWithLinks)
    const items = [...div.querySelectorAll('li')].filter(li =>
      li.textContent.includes('Linked operator')
    )
    expect(items.length).toBe(1)
    expect(items[0].textContent).toContain('Big Landlord Group')
    expect(items[0].textContent).toContain('JANE DOE')
    expect(items[0].textContent).toContain('7 parcels')
  })

  it('builds a hash route to the linked operator', () => {
    const div = render(opWithLinks)
    const a = div.querySelector('a[href^="#/operator/"]')
    expect(a).not.toBeNull()
    expect(a.getAttribute('href')).toBe('#/operator/big-landlord')
  })

  it('URL-encodes slugs with special characters in the href', () => {
    const op = {
      ...baseOp,
      audit: {
        ...baseAudit,
        linked_operators: [{
          operator_slug: 'op with space',
          operator_label: 'Op With Space',
          co_owner: 'X', parcels: 1,
        }],
      },
    }
    const div = render(op)
    const a = div.querySelector('a[href^="#/operator/"]')
    expect(a.getAttribute('href')).toBe('#/operator/op%20with%20space')
  })
})

// ---------------------------------------------------------------------------
// Person dedups + alter-ego pattern
// ---------------------------------------------------------------------------

describe('renderAuditDisclosure — person dedups and pattern', () => {
  it('renders one Name dedup line per person_dedup with variants', () => {
    const op = {
      ...baseOp,
      audit: {
        ...baseAudit,
        person_dedups: [
          { canonical: 'JOHN SMITH', variants: ['SMITH JOHN', 'J SMITH'] },
        ],
      },
    }
    const div = render(op)
    const li = [...div.querySelectorAll('li')].find(l => l.textContent.includes('Name dedup'))
    expect(li).toBeDefined()
    expect(li.textContent).toContain('JOHN SMITH')
    expect(li.textContent).toContain('SMITH JOHN')
    expect(li.textContent).toContain('J SMITH')
  })

  it('renders the alter-ego pattern line when pattern==="alter_ego"', () => {
    const op = { ...baseOp, audit: { ...baseAudit, pattern: 'alter_ego' } }
    const div = render(op)
    expect(div.textContent).toContain('alter-ego')
    expect(div.textContent).toContain('one person + one LLC')
  })

  it('does not render the pattern line for normal patterns', () => {
    const div = render(baseOp)
    expect(div.textContent).not.toContain('alter-ego')
  })
})

// ---------------------------------------------------------------------------
// Mobile summary in the <summary> element
// ---------------------------------------------------------------------------

describe('renderAuditDisclosure — mobile summary line', () => {
  it('reports member count and cohesion score', () => {
    const div = render(baseOp)
    const mobile = div.querySelector('.audit-summary-mobile')
    expect(mobile).not.toBeNull()
    expect(mobile.textContent).toContain('2 LLCs')
    expect(mobile.textContent).toContain('cohesion 80')
  })

  it('uses singular "LLC" when member_count is 1', () => {
    const op = { ...baseOp, audit: { ...baseAudit, member_count: 1 } }
    const div = render(op)
    const mobile = div.querySelector('.audit-summary-mobile')
    expect(mobile.textContent).toContain('1 LLC')
    expect(mobile.textContent).not.toContain('1 LLCs')
  })

  it('omits "shared mailing addr" tag when address is absent', () => {
    const op = {
      ...baseOp,
      audit: { ...baseAudit, shared_mailing_address: '' },
    }
    const div = render(op)
    const mobile = div.querySelector('.audit-summary-mobile')
    expect(mobile.textContent).not.toContain('shared mailing addr')
  })
})
