import { describe, it, expect } from 'vitest';
import { computeGroupRpm } from './rpmCalc.js';

// ═══════════════════════════════════════════════════════════
// Tests for computeGroupRpm
// ═══════════════════════════════════════════════════════════

describe('computeGroupRpm', () => {
  // ── avgRate calculation ──────────────────────────────────

  it('returns avgRate=0 when rateCount is 0', () => {
    const group = { rateCount: 0, totalRate: 0, lanes: [] };
    const result = computeGroupRpm(group);
    expect(result.avgRate).toBe(0);
  });

  it('computes avgRate as totalRate/rateCount rounded to integer', () => {
    const group = { rateCount: 3, totalRate: 4500, lanes: [] };
    const result = computeGroupRpm(group);
    expect(result.avgRate).toBe(1500);
  });

  it('rounds avgRate to nearest integer', () => {
    // 4501 / 3 = 1500.333... → rounds to 1500
    const group = { rateCount: 3, totalRate: 4501, lanes: [] };
    expect(computeGroupRpm(group).avgRate).toBe(1500);
    // 4502 / 3 = 1500.667... → rounds to 1501
    const group2 = { rateCount: 3, totalRate: 4502, lanes: [] };
    expect(computeGroupRpm(group2).avgRate).toBe(1501);
  });

  // ── avgMiles / avgRpm with no lanes ──────────────────────

  it('returns avgMiles=0 and avgRpm=null when lanes is empty', () => {
    const group = { rateCount: 2, totalRate: 3000, lanes: [] };
    const result = computeGroupRpm(group);
    expect(result.avgMiles).toBe(0);
    expect(result.avgRpm).toBeNull();
  });

  it('returns avgRpm=null when lanes is undefined', () => {
    const group = { rateCount: 1, totalRate: 1500, lanes: undefined };
    const result = computeGroupRpm(group);
    expect(result.avgRpm).toBeNull();
    expect(result.avgMiles).toBe(0);
  });

  // ── Miles filtering: only lanes with both miles>0 AND avg_rate>0 ──

  it('ignores lanes with no miles', () => {
    const group = {
      rateCount: 1, totalRate: 1500,
      lanes: [{ avg_rate: 1500, miles: 0, load_count: 1 }],
    };
    expect(computeGroupRpm(group).avgRpm).toBeNull();
    expect(computeGroupRpm(group).avgMiles).toBe(0);
  });

  it('ignores lanes with null miles', () => {
    const group = {
      rateCount: 1, totalRate: 1500,
      lanes: [{ avg_rate: 1500, miles: null, load_count: 1 }],
    };
    expect(computeGroupRpm(group).avgRpm).toBeNull();
  });

  it('ignores lanes with zero avg_rate', () => {
    const group = {
      rateCount: 0, totalRate: 0,
      lanes: [{ avg_rate: 0, miles: 300, load_count: 1 }],
    };
    expect(computeGroupRpm(group).avgRpm).toBeNull();
    expect(computeGroupRpm(group).avgMiles).toBe(0);
  });

  it('ignores lanes with negative avg_rate', () => {
    const group = {
      rateCount: 0, totalRate: 0,
      lanes: [{ avg_rate: -100, miles: 300, load_count: 1 }],
    };
    // avg_rate <= 0 so lane is excluded from miles calculation
    expect(computeGroupRpm(group).avgMiles).toBe(0);
  });

  // ── Simple single-lane RPM ───────────────────────────────

  it('computes correct avgRpm for a single lane', () => {
    // avgRate = 1500 / 1 = 1500; avgMiles = 300; rpm = 1500/300 = 5.00
    const group = {
      rateCount: 1, totalRate: 1500,
      lanes: [{ avg_rate: 1500, miles: 300, load_count: 1 }],
    };
    const result = computeGroupRpm(group);
    expect(result.avgRate).toBe(1500);
    expect(result.avgMiles).toBe(300);
    expect(result.avgRpm).toBe('5.00');
  });

  it('formats avgRpm as a string with 2 decimal places', () => {
    const group = {
      rateCount: 1, totalRate: 1000,
      lanes: [{ avg_rate: 1000, miles: 300, load_count: 1 }],
    };
    const result = computeGroupRpm(group);
    // 1000/300 = 3.333... → "3.33"
    expect(result.avgRpm).toBe('3.33');
    expect(typeof result.avgRpm).toBe('string');
  });

  // ── Weighted average miles across multiple lanes ──────────

  it('computes weighted average miles with equal load counts', () => {
    // Lane1: 200 miles × 1 load; Lane2: 400 miles × 1 load → avg 300
    const group = {
      rateCount: 2, totalRate: 3000,
      lanes: [
        { avg_rate: 1500, miles: 200, load_count: 1 },
        { avg_rate: 1500, miles: 400, load_count: 1 },
      ],
    };
    const result = computeGroupRpm(group);
    expect(result.avgMiles).toBe(300);
  });

  it('weights miles by load_count when computing average', () => {
    // Lane1: 100 miles × 3 loads; Lane2: 400 miles × 1 load
    // totalMilesWeighted = 100×3 + 400×1 = 700; weightCount = 4
    // avgMiles = 700/4 = 175
    const group = {
      rateCount: 4, totalRate: 6000,
      lanes: [
        { avg_rate: 1500, miles: 100, load_count: 3 },
        { avg_rate: 1500, miles: 400, load_count: 1 },
      ],
    };
    const result = computeGroupRpm(group);
    expect(result.avgMiles).toBe(175);
  });

  it('uses default load_count of 1 when not provided', () => {
    const group = {
      rateCount: 2, totalRate: 3000,
      lanes: [
        { avg_rate: 1500, miles: 200 }, // no load_count
        { avg_rate: 1500, miles: 400 }, // no load_count
      ],
    };
    const result = computeGroupRpm(group);
    expect(result.avgMiles).toBe(300); // (200×1 + 400×1) / 2
  });

  it('rounds avgMiles to nearest integer', () => {
    // 100×1 + 200×1 = 300, weight=2, avg=150
    const group = {
      rateCount: 2, totalRate: 3000,
      lanes: [
        { avg_rate: 1500, miles: 100, load_count: 1 },
        { avg_rate: 1500, miles: 201, load_count: 1 },
      ],
    };
    const result = computeGroupRpm(group);
    // avg = 301/2 = 150.5 → rounds to 151
    expect(result.avgMiles).toBe(151);
  });

  // ── RPM is null when either avgRate or avgMiles is 0 ──────

  it('returns avgRpm=null when avgRate is 0 even if avgMiles > 0', () => {
    const group = {
      rateCount: 0, totalRate: 0,
      lanes: [{ avg_rate: 1500, miles: 300, load_count: 1 }],
    };
    const result = computeGroupRpm(group);
    expect(result.avgRate).toBe(0);
    // avgMiles computed from lanes (lane has avg_rate>0), but group avgRate=0 → rpm null
    expect(result.avgRpm).toBeNull();
  });

  it('returns avgRpm=null when avgMiles is 0 even if avgRate > 0', () => {
    // All lanes have 0 miles so avgMiles = 0
    const group = {
      rateCount: 1, totalRate: 1500,
      lanes: [{ avg_rate: 1500, miles: 0, load_count: 1 }],
    };
    const result = computeGroupRpm(group);
    expect(result.avgRate).toBe(1500);
    expect(result.avgMiles).toBe(0);
    expect(result.avgRpm).toBeNull();
  });

  // ── Mixed lanes (some valid, some excluded) ───────────────

  it('only includes valid lanes in miles average', () => {
    // Lane1: valid (rate>0, miles>0); Lane2: no miles; Lane3: no rate
    const group = {
      rateCount: 1, totalRate: 1500,
      lanes: [
        { avg_rate: 1500, miles: 300, load_count: 1 }, // valid
        { avg_rate: 1500, miles: 0,   load_count: 1 }, // miles=0, excluded
        { avg_rate: 0,   miles: 400, load_count: 1 }, // avg_rate=0, excluded
      ],
    };
    const result = computeGroupRpm(group);
    // Only lane1 counts: avgMiles = 300
    expect(result.avgMiles).toBe(300);
    expect(result.avgRpm).toBe('5.00');
  });

  // ── Output shape ──────────────────────────────────────────

  it('returns an object with exactly avgRate, avgMiles, avgRpm fields', () => {
    const group = { rateCount: 1, totalRate: 1200, lanes: [{ avg_rate: 1200, miles: 400, load_count: 1 }] };
    const result = computeGroupRpm(group);
    expect(result).toHaveProperty('avgRate');
    expect(result).toHaveProperty('avgMiles');
    expect(result).toHaveProperty('avgRpm');
  });

  it('spreads correctly onto a group object', () => {
    const group = {
      origin: 'Houston',
      rateCount: 1, totalRate: 1500,
      lanes: [{ avg_rate: 1500, miles: 300, load_count: 1 }],
    };
    const result = { ...group, ...computeGroupRpm(group) };
    expect(result.origin).toBe('Houston');
    expect(result.avgRate).toBe(1500);
    expect(result.avgRpm).toBe('5.00');
  });

  // ── Regression: large real-world-scale values ─────────────

  it('handles typical freight rates (1000-5000) and distances (100-500 miles)', () => {
    const group = {
      rateCount: 3, totalRate: 6600, // avg ~2200
      lanes: [
        { avg_rate: 2000, miles: 180, load_count: 1 },
        { avg_rate: 2500, miles: 250, load_count: 1 },
        { avg_rate: 1800, miles: 150, load_count: 1 },
      ],
    };
    const result = computeGroupRpm(group);
    expect(result.avgRate).toBe(2200);
    // avgMiles = (180 + 250 + 150) / 3 = 580/3 ≈ 193
    expect(result.avgMiles).toBe(193);
    // avgRpm = 2200 / 193.33... ≈ "11.38"
    expect(result.avgRpm).toBeDefined();
    expect(parseFloat(result.avgRpm)).toBeCloseTo(2200 / (580 / 3), 1);
  });
});