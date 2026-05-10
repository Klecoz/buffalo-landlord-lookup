/**
 * Unit tests for the pure helper functions in app.js.
 *
 * These functions have no side effects and don't touch the DOM:
 *   escapeHtml  — XSS-safe HTML encoding
 *   fmtDate     — ISO date-string truncation
 *   fmtMoney    — compact dollar formatting
 *
 * They are accessed via window._test, set up by tests/setup.js.
 */

import { describe, it, expect, beforeEach } from 'vitest'

// Grab helpers after setup.js has loaded app.js
let escapeHtml, fmtDate, fmtMoney

beforeEach(() => {
  ;({ escapeHtml, fmtDate, fmtMoney } = window._test)
})

// ---------------------------------------------------------------------------
// escapeHtml
// ---------------------------------------------------------------------------

describe('escapeHtml', () => {
  it('leaves plain text unchanged', () => {
    expect(escapeHtml('hello world')).toBe('hello world')
  })

  it('escapes ampersand', () => {
    expect(escapeHtml('a & b')).toBe('a &amp; b')
  })

  it('escapes less-than', () => {
    expect(escapeHtml('<script>')).toBe('&lt;script&gt;')
  })

  it('escapes greater-than', () => {
    expect(escapeHtml('1 > 0')).toBe('1 &gt; 0')
  })

  it('escapes double quotes', () => {
    expect(escapeHtml('"hello"')).toBe('&quot;hello&quot;')
  })

  it('escapes single quotes', () => {
    expect(escapeHtml("it's")).toBe("it&#39;s")
  })

  it('escapes a full XSS payload so it cannot be rendered as live HTML', () => {
    const payload = `<img src=x onerror="alert('xss')">`
    const result = escapeHtml(payload)
    // The angle brackets must be encoded so the tag is inert
    expect(result).not.toContain('<img')
    expect(result).toContain('&lt;img')
    // Quotes must be encoded so attribute injection is impossible
    expect(result).toContain('&quot;')
    expect(result).toContain('&#39;')
    // The literal text "onerror" stays in the encoded output — that is correct;
    // escapeHtml encodes HTML syntax, it does not strip attribute names.
    expect(result).toContain('onerror')
  })

  it('escapes all five special characters in one string', () => {
    const result = escapeHtml(`& < > " '`)
    expect(result).toBe('&amp; &lt; &gt; &quot; &#39;')
  })

  it('handles null by returning empty string', () => {
    expect(escapeHtml(null)).toBe('')
  })

  it('handles undefined by returning empty string', () => {
    expect(escapeHtml(undefined)).toBe('')
  })

  it('converts numbers to string before escaping', () => {
    expect(escapeHtml(42)).toBe('42')
    expect(escapeHtml(0)).toBe('0')
  })

  it('returns empty string for empty input', () => {
    expect(escapeHtml('')).toBe('')
  })

  it('does not double-escape already-escaped entities', () => {
    // escapeHtml is not a sanitizer that detects pre-escaped content;
    // it should escape the raw ampersand in "&amp;" → "&amp;amp;"
    expect(escapeHtml('&amp;')).toBe('&amp;amp;')
  })
})

// ---------------------------------------------------------------------------
// fmtDate
// ---------------------------------------------------------------------------

describe('fmtDate', () => {
  it('returns empty string for empty input', () => {
    expect(fmtDate('')).toBe('')
  })

  it('returns empty string for null', () => {
    expect(fmtDate(null)).toBe('')
  })

  it('returns empty string for undefined', () => {
    expect(fmtDate(undefined)).toBe('')
  })

  it('truncates a full ISO datetime to YYYY-MM-DD', () => {
    expect(fmtDate('2024-03-15T10:30:00Z')).toBe('2024-03-15')
  })

  it('returns a plain date string unchanged', () => {
    expect(fmtDate('2024-03-15')).toBe('2024-03-15')
  })

  it('returns only first 10 chars for longer strings', () => {
    expect(fmtDate('2023-11-01 some trailing text')).toBe('2023-11-01')
  })

  it('handles a date at year boundary', () => {
    expect(fmtDate('2024-01-01T00:00:00.000Z')).toBe('2024-01-01')
  })
})

// ---------------------------------------------------------------------------
// fmtMoney
// ---------------------------------------------------------------------------

describe('fmtMoney', () => {
  it('returns $0 for zero (distinguishable from missing data)', () => {
    expect(fmtMoney(0)).toBe('$0')
  })

  it('returns em-dash for null, undefined, and empty string', () => {
    expect(fmtMoney(null)).toBe('—')
    expect(fmtMoney(undefined)).toBe('—')
    expect(fmtMoney('')).toBe('—')
  })

  it('formats small amounts as rounded dollars', () => {
    expect(fmtMoney(500)).toBe('$500')
    expect(fmtMoney(999)).toBe('$999')
  })

  it('formats thousands with K suffix', () => {
    expect(fmtMoney(1000)).toBe('$1K')
    expect(fmtMoney(1500)).toBe('$2K')   // Math.round(1500/1000) = 2
    expect(fmtMoney(250000)).toBe('$250K')
    expect(fmtMoney(999999)).toBe('$1000K')
  })

  it('formats millions with M suffix (1 decimal)', () => {
    expect(fmtMoney(1_000_000)).toBe('$1.0M')
    expect(fmtMoney(1_500_000)).toBe('$1.5M')
    expect(fmtMoney(12_345_678)).toBe('$12.3M')
  })

  it('formats billions with B suffix (1 decimal)', () => {
    expect(fmtMoney(1_000_000_000)).toBe('$1.0B')
    expect(fmtMoney(2_500_000_000)).toBe('$2.5B')
  })

  it('handles numeric strings', () => {
    expect(fmtMoney('500000')).toBe('$500K')
  })

  it('handles negative values without crashing', () => {
    // Negative values are unusual in this dataset but shouldn't throw
    const result = fmtMoney(-1000)
    expect(typeof result).toBe('string')
  })
})
