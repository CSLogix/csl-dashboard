/**
 * Compute weighted average rate-per-mile (RPM) and average miles
 * across a group's lane summaries.
 *
 * Only lanes that have both positive miles AND positive avg_rate
 * contribute to the weighted average.
 *
 * @param {object} group  Origin group with { lanes, rateCount, totalRate }
 * @param {object[]} group.lanes  Array of lane summaries
 * @param {number}   group.rateCount  Total weight of rate observations
 * @param {number}   group.totalRate  Sum of (avg_rate × load_count) for the group
 * @returns {{ avgRate: number, avgMiles: number, avgRpm: string|null }}
 */
export const computeGroupRpm = (group) => {
  const avgRate = group.rateCount > 0 ? Math.round(group.totalRate / group.rateCount) : 0;
  let totalMilesWeighted = 0;
  let milesWeightCount = 0;
  (group.lanes || []).forEach(ls => {
    if (ls.miles && ls.miles > 0 && ls.avg_rate > 0) {
      const w = ls.load_count || 1;
      totalMilesWeighted += ls.miles * w;
      milesWeightCount += w;
    }
  });
  const avgMiles = milesWeightCount > 0 ? totalMilesWeighted / milesWeightCount : 0;
  const avgRpm = avgMiles > 0 && avgRate > 0 ? (avgRate / avgMiles).toFixed(2) : null;
  return { avgRate, avgMiles: Math.round(avgMiles), avgRpm };
};