import { describe, it, expect } from 'vitest';
import {
  CITY_STATE_MAP,
  inferCarrierState,
  inferCarrierCity,
  buildGroupedDir,
} from './carrierGrouping.js';

// ═══════════════════════════════════════════════════════════
// Tests for CITY_STATE_MAP constant
// ═══════════════════════════════════════════════════════════

describe('CITY_STATE_MAP', () => {
  it('is a plain object', () => {
    expect(typeof CITY_STATE_MAP).toBe('object');
  });

  it('maps Texas cities to TX', () => {
    expect(CITY_STATE_MAP['houston']).toBe('TX');
    expect(CITY_STATE_MAP['dallas']).toBe('TX');
    expect(CITY_STATE_MAP['fort worth']).toBe('TX');
    expect(CITY_STATE_MAP['ft worth']).toBe('TX');
  });

  it('maps NY/NJ area to combined identifier', () => {
    expect(CITY_STATE_MAP['newark']).toBe('NY/NJ');
    expect(CITY_STATE_MAP['elizabeth']).toBe('NY/NJ');
    expect(CITY_STATE_MAP['ny/nj']).toBe('NY/NJ');
    expect(CITY_STATE_MAP['new york']).toBe('NY');
  });

  it('maps West Coast port cities correctly', () => {
    expect(CITY_STATE_MAP['los angeles']).toBe('CA');
    expect(CITY_STATE_MAP['long beach']).toBe('CA');
    expect(CITY_STATE_MAP['seattle']).toBe('WA');
    expect(CITY_STATE_MAP['tacoma']).toBe('WA');
    expect(CITY_STATE_MAP['oakland']).toBe('CA');
    expect(CITY_STATE_MAP['portland']).toBe('OR');
  });

  it('maps Florida port cities to FL', () => {
    expect(CITY_STATE_MAP['miami']).toBe('FL');
    expect(CITY_STATE_MAP['jacksonville']).toBe('FL');
    expect(CITY_STATE_MAP['tampa']).toBe('FL');
    expect(CITY_STATE_MAP['port everglades']).toBe('FL');
  });

  it('has lowercase keys', () => {
    expect(CITY_STATE_MAP['Houston']).toBeUndefined();
    expect(CITY_STATE_MAP['houston']).toBe('TX');
  });
});

// ═══════════════════════════════════════════════════════════
// Tests for inferCarrierState
// ═══════════════════════════════════════════════════════════

describe('inferCarrierState', () => {
  // ── pickup_area-based inference ──────────────────────────

  it('extracts state from pickup_area with comma separator', () => {
    expect(inferCarrierState({ pickup_area: 'Houston, TX' })).toBe('TX');
    expect(inferCarrierState({ pickup_area: 'Los Angeles, CA' })).toBe('CA');
    expect(inferCarrierState({ pickup_area: 'Chicago, IL' })).toBe('IL');
  });

  it('extracts state from pickup_area and uppercases it', () => {
    expect(inferCarrierState({ pickup_area: 'Houston, tx' })).toBe('TX');
    expect(inferCarrierState({ pickup_area: 'Dallas, Tx' })).toBe('TX');
  });

  it('ignores pickup_area if the part after comma is longer than 5 chars', () => {
    // "Houston, Texas" — parts[1] = "Texas" length 5, edge case: length <= 5 passes
    expect(inferCarrierState({ pickup_area: 'Houston, Texas' })).toBe('TEXAS');
    // "Houston, California" — length > 5, should not use pickup_area
    const result = inferCarrierState({ pickup_area: 'Houston, California', markets: ['houston'] });
    expect(result).toBe('TX'); // falls through to markets lookup
  });

  it('prefers pickup_area over markets', () => {
    const carrier = { pickup_area: 'Dallas, TX', markets: ['chicago'] };
    expect(inferCarrierState(carrier)).toBe('TX');
  });

  // ── markets-based inference ──────────────────────────────

  it('infers state from first matching market', () => {
    expect(inferCarrierState({ markets: ['houston'] })).toBe('TX');
    expect(inferCarrierState({ markets: ['savannah'] })).toBe('GA');
    expect(inferCarrierState({ markets: ['chicago'] })).toBe('IL');
  });

  it('uses first market that matches in CITY_STATE_MAP', () => {
    const carrier = { markets: ['unknowncity', 'houston'] };
    expect(inferCarrierState(carrier)).toBe('TX');
  });

  it('is case-insensitive for market lookup', () => {
    expect(inferCarrierState({ markets: ['Houston'] })).toBe('TX');
    expect(inferCarrierState({ markets: ['HOUSTON'] })).toBe('TX');
    expect(inferCarrierState({ markets: ['Los Angeles'] })).toBe('CA');
  });

  // ── No match cases ───────────────────────────────────────

  it('returns null when no pickup_area and no markets', () => {
    expect(inferCarrierState({})).toBeNull();
    expect(inferCarrierState({ carrier_name: 'Acme Trucking' })).toBeNull();
  });

  it('returns null when markets is empty array', () => {
    expect(inferCarrierState({ markets: [] })).toBeNull();
  });

  it('returns null when all markets are unknown cities', () => {
    expect(inferCarrierState({ markets: ['timbuktu', 'atlantis'] })).toBeNull();
  });

  it('returns null when pickup_area has only one part (no comma)', () => {
    // No comma → split gives 1 part → parts.length < 2 → no state extracted
    // Falls through to markets
    expect(inferCarrierState({ pickup_area: 'Houston' })).toBeNull();
  });

  it('handles undefined markets gracefully', () => {
    expect(inferCarrierState({ pickup_area: undefined, markets: undefined })).toBeNull();
  });
});

// ═══════════════════════════════════════════════════════════
// Tests for inferCarrierCity
// ═══════════════════════════════════════════════════════════

describe('inferCarrierCity', () => {
  it('extracts city from pickup_area before the comma', () => {
    expect(inferCarrierCity({ pickup_area: 'Houston, TX' })).toBe('Houston');
    expect(inferCarrierCity({ pickup_area: 'Los Angeles, CA' })).toBe('Los Angeles');
    expect(inferCarrierCity({ pickup_area: 'New York, NY' })).toBe('New York');
  });

  it('returns full pickup_area when no comma present', () => {
    expect(inferCarrierCity({ pickup_area: 'Houston' })).toBe('Houston');
  });

  it('prefers pickup_area over markets', () => {
    const carrier = { pickup_area: 'Dallas, TX', markets: ['chicago'] };
    expect(inferCarrierCity(carrier)).toBe('Dallas');
  });

  it('falls back to first market when no pickup_area', () => {
    expect(inferCarrierCity({ markets: ['houston'] })).toBe('houston');
    expect(inferCarrierCity({ markets: ['savannah', 'atlanta'] })).toBe('savannah');
  });

  it('returns null when no pickup_area and no markets', () => {
    expect(inferCarrierCity({})).toBeNull();
  });

  it('returns null when markets is empty array', () => {
    expect(inferCarrierCity({ markets: [] })).toBeNull();
  });

  it('trims whitespace from pickup_area city part', () => {
    expect(inferCarrierCity({ pickup_area: '  Houston  , TX' })).toBe('Houston');
  });
});

// ═══════════════════════════════════════════════════════════
// Tests for buildGroupedDir
// ═══════════════════════════════════════════════════════════

describe('buildGroupedDir', () => {
  // ── Empty input ─────────────────────────────────────────

  it('returns empty array for empty carrier list', () => {
    expect(buildGroupedDir([])).toEqual([]);
  });

  // ── Single carrier ───────────────────────────────────────

  it('creates a single state group with one city and one carrier', () => {
    const carriers = [{ id: 1, carrier_name: 'ACME', pickup_area: 'Houston, TX', tier_rank: 1 }];
    const result = buildGroupedDir(carriers);
    expect(result).toHaveLength(1);
    expect(result[0].state).toBe('TX');
    expect(result[0].totalCarriers).toBe(1);
    expect(result[0].cities).toHaveLength(1);
    expect(result[0].cities[0].city).toBe('Houston');
    expect(result[0].cities[0].carriers).toHaveLength(1);
  });

  // ── State grouping ───────────────────────────────────────

  it('groups carriers from the same state together', () => {
    const carriers = [
      { id: 1, carrier_name: 'A', pickup_area: 'Houston, TX' },
      { id: 2, carrier_name: 'B', pickup_area: 'Dallas, TX' },
    ];
    const result = buildGroupedDir(carriers);
    expect(result).toHaveLength(1);
    expect(result[0].state).toBe('TX');
    expect(result[0].totalCarriers).toBe(2);
  });

  it('creates separate state groups for carriers in different states', () => {
    const carriers = [
      { id: 1, carrier_name: 'A', pickup_area: 'Houston, TX' },
      { id: 2, carrier_name: 'B', pickup_area: 'Los Angeles, CA' },
    ];
    const result = buildGroupedDir(carriers);
    const states = result.map(g => g.state).sort();
    expect(states).toContain('TX');
    expect(states).toContain('CA');
  });

  // ── City grouping within state ────────────────────────────

  it('groups carriers from the same city within a state', () => {
    const carriers = [
      { id: 1, carrier_name: 'A', pickup_area: 'Houston, TX' },
      { id: 2, carrier_name: 'B', pickup_area: 'Houston, TX' },
      { id: 3, carrier_name: 'C', pickup_area: 'Dallas, TX' },
    ];
    const result = buildGroupedDir(carriers);
    expect(result).toHaveLength(1);
    const txGroup = result[0];
    expect(txGroup.state).toBe('TX');
    const cityNames = txGroup.cities.map(c => c.city);
    expect(cityNames).toContain('Houston');
    expect(cityNames).toContain('Dallas');
    const houstonCity = txGroup.cities.find(c => c.city === 'Houston');
    expect(houstonCity.carriers).toHaveLength(2);
    const dallasCity = txGroup.cities.find(c => c.city === 'Dallas');
    expect(dallasCity.carriers).toHaveLength(1);
  });

  // ── Fallbacks for carriers with no location data ──────────

  it('places carrier with no location in "Other" state / "Unassigned" city', () => {
    const carriers = [{ id: 1, carrier_name: 'Mystery Inc' }];
    const result = buildGroupedDir(carriers);
    expect(result[0].state).toBe('Other');
    expect(result[0].cities[0].city).toBe('Unassigned');
  });

  it('infers state from markets when no pickup_area', () => {
    const carriers = [{ id: 1, carrier_name: 'A', markets: ['houston'] }];
    const result = buildGroupedDir(carriers);
    expect(result[0].state).toBe('TX');
  });

  // ── Truck count aggregation ───────────────────────────────

  it('sums trucks per state group', () => {
    const carriers = [
      { id: 1, carrier_name: 'A', pickup_area: 'Houston, TX', trucks: 5 },
      { id: 2, carrier_name: 'B', pickup_area: 'Dallas, TX', trucks: 3 },
      { id: 3, carrier_name: 'C', pickup_area: 'Los Angeles, CA', trucks: 10 },
    ];
    const result = buildGroupedDir(carriers);
    const txGroup = result.find(g => g.state === 'TX');
    const caGroup = result.find(g => g.state === 'CA');
    expect(txGroup.totalTrucks).toBe(8);
    expect(caGroup.totalTrucks).toBe(10);
  });

  it('ignores carriers with no trucks field in truck total', () => {
    const carriers = [
      { id: 1, carrier_name: 'A', pickup_area: 'Houston, TX', trucks: 4 },
      { id: 2, carrier_name: 'B', pickup_area: 'Dallas, TX' }, // no trucks
    ];
    const result = buildGroupedDir(carriers);
    expect(result[0].totalTrucks).toBe(4);
  });

  it('counts truck=0 as falsy (not added to totalTrucks)', () => {
    const carriers = [
      { id: 1, carrier_name: 'A', pickup_area: 'Houston, TX', trucks: 0 },
    ];
    const result = buildGroupedDir(carriers);
    expect(result[0].totalTrucks).toBe(0);
  });

  // ── Tier count aggregation ────────────────────────────────

  it('counts tier 1/2/3 carriers per state', () => {
    const carriers = [
      { id: 1, carrier_name: 'A', pickup_area: 'Houston, TX', tier_rank: 1 },
      { id: 2, carrier_name: 'B', pickup_area: 'Dallas, TX', tier_rank: 1 },
      { id: 3, carrier_name: 'C', pickup_area: 'Houston, TX', tier_rank: 2 },
      { id: 4, carrier_name: 'D', pickup_area: 'Houston, TX', tier_rank: 3 },
      { id: 5, carrier_name: 'E', pickup_area: 'Houston, TX', tier_rank: 0 }, // DNU — not counted
    ];
    const result = buildGroupedDir(carriers);
    const txGroup = result[0];
    expect(txGroup.tierCounts[1]).toBe(2);
    expect(txGroup.tierCounts[2]).toBe(1);
    expect(txGroup.tierCounts[3]).toBe(1);
  });

  it('does not count DNU (tier 0) or unranked (null/undefined) in tierCounts', () => {
    const carriers = [
      { id: 1, carrier_name: 'A', pickup_area: 'Houston, TX', tier_rank: 0 },
      { id: 2, carrier_name: 'B', pickup_area: 'Houston, TX', tier_rank: null },
      { id: 3, carrier_name: 'C', pickup_area: 'Houston, TX' }, // no tier_rank
    ];
    const result = buildGroupedDir(carriers);
    const txGroup = result[0];
    expect(txGroup.tierCounts[1]).toBe(0);
    expect(txGroup.tierCounts[2]).toBe(0);
    expect(txGroup.tierCounts[3]).toBe(0);
  });

  // ── Sort order ─────────────────────────────────────────────

  it('sorts states by total carrier count descending', () => {
    const carriers = [
      { id: 1, carrier_name: 'A', pickup_area: 'Los Angeles, CA' },
      { id: 2, carrier_name: 'B', pickup_area: 'Houston, TX' },
      { id: 3, carrier_name: 'C', pickup_area: 'Dallas, TX' },
      { id: 4, carrier_name: 'D', pickup_area: 'Austin, TX' },
    ];
    const result = buildGroupedDir(carriers);
    expect(result[0].state).toBe('TX'); // 3 carriers
    expect(result[1].state).toBe('CA'); // 1 carrier
  });

  it('sorts cities within state by carrier count descending', () => {
    const carriers = [
      { id: 1, carrier_name: 'A', pickup_area: 'Dallas, TX' },
      { id: 2, carrier_name: 'B', pickup_area: 'Houston, TX' },
      { id: 3, carrier_name: 'C', pickup_area: 'Houston, TX' },
      { id: 4, carrier_name: 'D', pickup_area: 'Houston, TX' },
    ];
    const result = buildGroupedDir(carriers);
    const txGroup = result[0];
    // Houston has 3, Dallas has 1
    expect(txGroup.cities[0].city).toBe('Houston');
    expect(txGroup.cities[1].city).toBe('Dallas');
  });

  it('sorts carriers within city by tier_rank ascending (T1 first)', () => {
    const carriers = [
      { id: 1, carrier_name: 'Tier3', pickup_area: 'Houston, TX', tier_rank: 3 },
      { id: 2, carrier_name: 'Tier1', pickup_area: 'Houston, TX', tier_rank: 1 },
      { id: 3, carrier_name: 'Tier2', pickup_area: 'Houston, TX', tier_rank: 2 },
    ];
    const result = buildGroupedDir(carriers);
    const hCity = result[0].cities[0];
    expect(hCity.carriers[0].carrier_name).toBe('Tier1');
    expect(hCity.carriers[1].carrier_name).toBe('Tier2');
    expect(hCity.carriers[2].carrier_name).toBe('Tier3');
  });

  it('sorts unranked carriers (no tier_rank) to end of city list', () => {
    const carriers = [
      { id: 1, carrier_name: 'Unranked', pickup_area: 'Houston, TX' },
      { id: 2, carrier_name: 'Tier1', pickup_area: 'Houston, TX', tier_rank: 1 },
    ];
    const result = buildGroupedDir(carriers);
    const hCity = result[0].cities[0];
    expect(hCity.carriers[0].carrier_name).toBe('Tier1');
    expect(hCity.carriers[1].carrier_name).toBe('Unranked');
  });

  // ── Mixed location data ───────────────────────────────────

  it('handles mix of pickup_area and market-based carriers in same state', () => {
    const carriers = [
      { id: 1, carrier_name: 'A', pickup_area: 'Houston, TX' },
      { id: 2, carrier_name: 'B', markets: ['houston'] }, // no pickup_area, market matches TX
    ];
    const result = buildGroupedDir(carriers);
    expect(result).toHaveLength(1);
    expect(result[0].state).toBe('TX');
    expect(result[0].totalCarriers).toBe(2);
  });

  it('does not mutate the input carriers array', () => {
    const carriers = [
      { id: 1, carrier_name: 'A', pickup_area: 'Houston, TX', tier_rank: 2 },
      { id: 2, carrier_name: 'B', pickup_area: 'Houston, TX', tier_rank: 1 },
    ];
    const originalOrder = carriers.map(c => c.id);
    buildGroupedDir(carriers);
    expect(carriers.map(c => c.id)).toEqual(originalOrder);
  });

  // ── Regression / boundary ─────────────────────────────────

  it('handles carrier with null markets field', () => {
    const carriers = [{ id: 1, carrier_name: 'A', markets: null }];
    // Should not throw; falls back to "Other" / "Unassigned"
    expect(() => buildGroupedDir(carriers)).not.toThrow();
    const result = buildGroupedDir(carriers);
    expect(result[0].state).toBe('Other');
  });

  it('totalCarriers matches actual number of carriers in all cities', () => {
    const carriers = Array.from({ length: 10 }, (_, i) => ({
      id: i + 1,
      carrier_name: `Carrier ${i + 1}`,
      pickup_area: i < 5 ? 'Houston, TX' : 'Los Angeles, CA',
    }));
    const result = buildGroupedDir(carriers);
    for (const stateGroup of result) {
      const cityTotal = stateGroup.cities.reduce((sum, c) => sum + c.carriers.length, 0);
      expect(stateGroup.totalCarriers).toBe(cityTotal);
    }
  });
});