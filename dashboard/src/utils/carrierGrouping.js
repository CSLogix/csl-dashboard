// ── City → State map for carrier geographic grouping ──
export const CITY_STATE_MAP = {
  "houston": "TX", "dallas": "TX", "san antonio": "TX", "ft worth": "TX", "fort worth": "TX", "el paso": "TX", "laredo": "TX",
  "los angeles": "CA", "long beach": "CA", "oakland": "CA", "san francisco": "CA",
  "chicago": "IL",
  "savannah": "GA", "atlanta": "GA",
  "new york": "NY", "newark": "NY/NJ", "elizabeth": "NY/NJ", "ny/nj": "NY/NJ",
  "charleston": "SC",
  "norfolk": "VA", "richmond": "VA",
  "baltimore": "MD",
  "boston": "MA",
  "seattle": "WA", "tacoma": "WA",
  "portland": "OR",
  "miami": "FL", "jacksonville": "FL", "tampa": "FL", "port everglades": "FL",
  "new orleans": "LA", "mobile": "AL", "memphis": "TN", "nashville": "TN",
  "charlotte": "NC", "wilmington": "NC",
  "philadelphia": "PA",
  "detroit": "MI",
  "cleveland": "OH", "columbus": "OH", "cincinnati": "OH",
  "indianapolis": "IN",
  "minneapolis": "MN", "st paul": "MN",
  "kansas city": "MO", "st louis": "MO",
  "louisville": "KY",
  "denver": "CO",
  "salt lake city": "UT",
  "phoenix": "AZ",
  "las vegas": "NV",
};

/**
 * Infer a state abbreviation from a carrier object.
 * Checks pickup_area first (e.g. "Houston, TX"), then markets.
 *
 * @param {object} carrier
 * @param {string} [carrier.pickup_area]
 * @param {string[]} [carrier.markets]
 * @returns {string|null}
 */
export const inferCarrierState = (carrier) => {
  if (carrier.pickup_area) {
    const parts = carrier.pickup_area.split(",").map(s => s.trim());
    if (parts.length >= 2 && parts[1].length <= 5) return parts[1].toUpperCase();
  }
  for (const m of (carrier.markets || [])) {
    const st = CITY_STATE_MAP[m.toLowerCase()];
    if (st) return st;
  }
  return null;
};

/**
 * Infer a city name from a carrier object.
 * Uses pickup_area city portion first, then first market.
 *
 * @param {object} carrier
 * @param {string} [carrier.pickup_area]
 * @param {string[]} [carrier.markets]
 * @returns {string|null}
 */
export const inferCarrierCity = (carrier) => {
  if (carrier.pickup_area) return carrier.pickup_area.split(",")[0].trim();
  if (carrier.markets?.length > 0) return carrier.markets[0];
  return null;
};

/**
 * Build a grouped state → city → carriers hierarchy from a flat carrier list.
 * Carriers within each city are sorted by tier_rank ascending (lower = better).
 * Cities within each state are sorted by carrier count descending.
 * States are sorted by total carrier count descending.
 *
 * @param {object[]} carriers  Flat array of carrier objects
 * @returns {object[]}  Array of state group objects
 */
export const buildGroupedDir = (carriers) => {
  const stateMap = {};
  carriers.forEach(c => {
    const state = inferCarrierState(c) || "Other";
    const city = inferCarrierCity(c) || "Unassigned";
    if (!stateMap[state]) {
      stateMap[state] = { state, cities: {}, totalCarriers: 0, totalTrucks: 0, tierCounts: { 1: 0, 2: 0, 3: 0 } };
    }
    if (!stateMap[state].cities[city]) stateMap[state].cities[city] = [];
    stateMap[state].cities[city].push(c);
    stateMap[state].totalCarriers++;
    if (c.trucks) stateMap[state].totalTrucks += c.trucks;
    if (c.tier_rank >= 1 && c.tier_rank <= 3) stateMap[state].tierCounts[c.tier_rank]++;
  });
  return Object.values(stateMap)
    .map(s => ({
      ...s,
      cities: Object.entries(s.cities)
        .map(([city, carriers]) => ({
          city,
          carriers: carriers.slice().sort((a, b) => (a.tier_rank || 99) - (b.tier_rank || 99)),
        }))
        .sort((a, b) => b.carriers.length - a.carriers.length),
    }))
    .sort((a, b) => b.totalCarriers - a.totalCarriers);
};