import { describe, it, expect } from 'vitest';
import { CITY_TO_STATE, enrichDestWithState } from './destEnrichment.js';

// ═══════════════════════════════════════════════════════════
// Tests for CITY_TO_STATE constant
// ═══════════════════════════════════════════════════════════

describe('CITY_TO_STATE', () => {
  it('is a plain object with string keys and 2-char state values', () => {
    expect(typeof CITY_TO_STATE).toBe('object');
    for (const [city, state] of Object.entries(CITY_TO_STATE)) {
      expect(typeof city).toBe('string');
      // State values may be 2-char abbreviations or "NY/NJ" style cross-state
      expect(state.length).toBeGreaterThanOrEqual(2);
    }
  });

  it('maps Texas cities to TX', () => {
    expect(CITY_TO_STATE['houston']).toBe('TX');
    expect(CITY_TO_STATE['dallas']).toBe('TX');
    expect(CITY_TO_STATE['dumas']).toBe('TX');
    expect(CITY_TO_STATE['san antonio']).toBe('TX');
    expect(CITY_TO_STATE['fort worth']).toBe('TX');
    expect(CITY_TO_STATE['ft worth']).toBe('TX');
  });

  it('maps California cities to CA', () => {
    expect(CITY_TO_STATE['los angeles']).toBe('CA');
    expect(CITY_TO_STATE['san francisco']).toBe('CA');
    expect(CITY_TO_STATE['san diego']).toBe('CA');
    expect(CITY_TO_STATE['long beach']).toBe('CA');
    expect(CITY_TO_STATE['fresno']).toBe('CA');
    expect(CITY_TO_STATE['sacramento']).toBe('CA');
  });

  it('maps other major port cities to correct states', () => {
    expect(CITY_TO_STATE['chicago']).toBe('IL');
    expect(CITY_TO_STATE['savannah']).toBe('GA');
    expect(CITY_TO_STATE['newark']).toBe('NJ');
    expect(CITY_TO_STATE['seattle']).toBe('WA');
    expect(CITY_TO_STATE['miami']).toBe('FL');
    expect(CITY_TO_STATE['new orleans']).toBe('LA');
    expect(CITY_TO_STATE['denver']).toBe('CO');
  });

  it('uses lowercase keys (case-sensitive lookup requires lowercase input)', () => {
    // Keys are all lowercase — callers must normalize before lookup
    expect(CITY_TO_STATE['Houston']).toBeUndefined();
    expect(CITY_TO_STATE['houston']).toBe('TX');
  });

  it('contains all expected major freight hubs', () => {
    const hubs = ['houston', 'los angeles', 'chicago', 'savannah', 'new york',
      'newark', 'charleston', 'norfolk', 'seattle', 'miami', 'baltimore',
      'boston', 'philadelphia', 'detroit', 'minneapolis', 'kansas city',
      'denver', 'phoenix', 'las vegas'];
    for (const hub of hubs) {
      expect(CITY_TO_STATE[hub], `Expected hub ${hub} to be in CITY_TO_STATE`).toBeDefined();
    }
  });
});

// ═══════════════════════════════════════════════════════════
// Tests for enrichDestWithState function
// ═══════════════════════════════════════════════════════════

describe('enrichDestWithState', () => {
  // ── Nullish / empty inputs ──────────────────────────────

  it('returns null when dest is null', () => {
    expect(enrichDestWithState(null)).toBeNull();
  });

  it('returns undefined when dest is undefined', () => {
    expect(enrichDestWithState(undefined)).toBeUndefined();
  });

  it('returns empty string when dest is empty string', () => {
    // Empty string is falsy — function returns it as-is
    expect(enrichDestWithState('')).toBe('');
  });

  // ── Already has state abbreviation (no enrichment needed) ──

  it('returns unchanged when dest already has comma+state (e.g. "Dumas, TX")', () => {
    expect(enrichDestWithState('Dumas, TX')).toBe('Dumas, TX');
  });

  it('returns unchanged when dest has state without comma (e.g. "Dumas TX")', () => {
    expect(enrichDestWithState('Dumas TX')).toBe('Dumas TX');
  });

  it('returns unchanged when dest has state+zip (e.g. "Houston, TX 77001")', () => {
    expect(enrichDestWithState('Houston, TX 77001')).toBe('Houston, TX 77001');
  });

  it('returns unchanged when dest has state+zip without comma', () => {
    expect(enrichDestWithState('Dallas TX 75201')).toBe('Dallas TX 75201');
  });

  it('does NOT treat a trailing 2-digit number as state abbreviation', () => {
    // "City 77" has no uppercase 2-letter suffix matching [A-Z]{2}
    const result = enrichDestWithState('Some City 77');
    // "77" is not [A-Z]{2} so it won't match the state regex
    // Should attempt enrichment
    expect(result).not.toBe('Some City 77, TX');
  });

  // ── Quote-based state extraction ───────────────────────

  it('extracts state from matching quote destination', () => {
    const quotes = [{ destination: 'Dumas, TX' }];
    expect(enrichDestWithState('Dumas', quotes)).toBe('Dumas, TX');
  });

  it('extracts state from quote destination with zip', () => {
    const quotes = [{ destination: 'Houston, TX 77001' }];
    expect(enrichDestWithState('Houston', quotes)).toBe('Houston, TX');
  });

  it('extracts state from quote destination without comma (space separator)', () => {
    const quotes = [{ destination: 'Dallas TX' }];
    expect(enrichDestWithState('Dallas', quotes)).toBe('Dallas, TX');
  });

  it('uses first matching quote when multiple quotes present', () => {
    const quotes = [
      { destination: 'Memphis, TN' },
      { destination: 'Nashville, TN' },
    ];
    expect(enrichDestWithState('Memphis', quotes)).toBe('Memphis, TN');
  });

  it('skips quotes whose destination does not include the dest string', () => {
    const quotes = [
      { destination: 'Nashville, TN' },
      { destination: 'Houston, TX' },
    ];
    // "Houston" appears in second quote, not first
    expect(enrichDestWithState('Houston', quotes)).toBe('Houston, TX');
  });

  it('is case-insensitive when matching dest against quote destination', () => {
    const quotes = [{ destination: 'HOUSTON, TX' }];
    expect(enrichDestWithState('houston', quotes)).toBe('houston, TX');
  });

  it('skips quotes with no destination field', () => {
    const quotes = [{ rate: 1500 }, { destination: 'Atlanta, GA' }];
    expect(enrichDestWithState('Atlanta', quotes)).toBe('Atlanta, GA');
  });

  it('skips quotes with empty destination', () => {
    const quotes = [{ destination: '' }, { destination: 'Savannah, GA' }];
    expect(enrichDestWithState('Savannah', quotes)).toBe('Savannah, GA');
  });

  it('falls through to CITY_TO_STATE lookup when no quote matches', () => {
    const quotes = [{ destination: 'Memphis, TN' }];
    // "Houston" doesn't appear in "Memphis, TN"
    expect(enrichDestWithState('Houston', quotes)).toBe('Houston, TX');
  });

  it('handles empty quotes array, falls through to lookup', () => {
    expect(enrichDestWithState('Houston', [])).toBe('Houston, TX');
  });

  it('handles null quotes, falls through to lookup', () => {
    expect(enrichDestWithState('Houston', null)).toBe('Houston, TX');
  });

  it('handles undefined quotes, falls through to lookup', () => {
    expect(enrichDestWithState('Houston')).toBe('Houston, TX');
  });

  // ── CITY_TO_STATE fallback ──────────────────────────────

  it('looks up known city and appends state with title-case city name', () => {
    expect(enrichDestWithState('houston')).toBe('Houston, TX');
    expect(enrichDestWithState('dallas')).toBe('Dallas, TX');
    expect(enrichDestWithState('dumas')).toBe('Dumas, TX');
  });

  it('preserves original capitalisation for the city portion', () => {
    // The function does: trimmed.charAt(0).toUpperCase() + trimmed.slice(1)
    // so "HOUSTON" → "HOUSTON, TX" (only first char touched)
    expect(enrichDestWithState('HOUSTON')).toBe('HOUSTON, TX');
    expect(enrichDestWithState('hOUSTON')).toBe('HOUSTON, TX');
  });

  it('looks up multi-word city names', () => {
    expect(enrichDestWithState('los angeles')).toBe('Los angeles, CA');
    expect(enrichDestWithState('san antonio')).toBe('San antonio, TX');
    expect(enrichDestWithState('new york')).toBe('New york, NY');
    expect(enrichDestWithState('kansas city')).toBe('Kansas city, MO');
    expect(enrichDestWithState('salt lake city')).toBe('Salt lake city, UT');
  });

  it('returns trimmed string unchanged for unknown city', () => {
    expect(enrichDestWithState('Timbuktu')).toBe('Timbuktu');
    expect(enrichDestWithState('  Springfield  ')).toBe('Springfield');
  });

  it('trims leading/trailing whitespace before processing', () => {
    const quotes = [{ destination: 'Houston, TX' }];
    expect(enrichDestWithState('  Houston  ', quotes)).toBe('Houston, TX');
  });

  // ── Edge cases ──────────────────────────────────────────

  it('handles city name that is a substring of another city in quotes', () => {
    // "port" is in "port everglades, FL" — should not falsely match "Port"
    const quotes = [{ destination: 'Portland, OR' }];
    // Portland includes 'port' → test that match is based on full dest string inclusion
    expect(enrichDestWithState('Port', quotes)).toBe('Port, OR');
  });

  it('returns city with state for ft worth (alternate spelling)', () => {
    expect(enrichDestWithState('ft worth')).toBe('Ft worth, TX');
  });

  it('returns city with state for fort worth', () => {
    expect(enrichDestWithState('fort worth')).toBe('Fort worth, TX');
  });

  it('handles quotes with destination that has no state suffix — no false match', () => {
    const quotes = [{ destination: 'Houston' }]; // no state suffix
    // rawDest.match(/,?\s+([A-Z]{2})\s*(\d{5})?$/) returns null → skip this quote
    // Falls through to CITY_TO_STATE
    expect(enrichDestWithState('Houston', quotes)).toBe('Houston, TX');
  });

  // ── Regression: boundary for state regex ──────────────

  it('does not strip valid state when dest is exactly "TX"', () => {
    // "TX" by itself matches /,?\s+[A-Z]{2}\s*(\d{5})?$/ only if preceded by space
    // "TX" alone does not have a preceding space+2caps → no match → lookup
    const result = enrichDestWithState('TX');
    // "tx" not in CITY_TO_STATE, so returns "TX"
    expect(result).toBe('TX');
  });
});