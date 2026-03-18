// ─── City → State lookup for destination auto-populate ───
export const CITY_TO_STATE = {
  "dumas": "TX", "houston": "TX", "dallas": "TX", "san antonio": "TX", "el paso": "TX", "laredo": "TX",
  "ft worth": "TX", "fort worth": "TX", "amarillo": "TX", "lubbock": "TX", "midland": "TX", "odessa": "TX",
  "beaumont": "TX", "corpus christi": "TX", "mcallen": "TX", "brownsville": "TX", "waco": "TX", "tyler": "TX",
  "los angeles": "CA", "long beach": "CA", "oakland": "CA", "san francisco": "CA", "san diego": "CA",
  "chicago": "IL", "savannah": "GA", "atlanta": "GA", "newark": "NJ", "elizabeth": "NJ",
  "charleston": "SC", "norfolk": "VA", "richmond": "VA", "baltimore": "MD", "boston": "MA",
  "seattle": "WA", "tacoma": "WA", "portland": "OR", "miami": "FL", "jacksonville": "FL", "tampa": "FL",
  "new orleans": "LA", "mobile": "AL", "memphis": "TN", "nashville": "TN", "charlotte": "NC",
  "wilmington": "NC", "philadelphia": "PA", "detroit": "MI", "cleveland": "OH", "columbus": "OH",
  "cincinnati": "OH", "indianapolis": "IN", "minneapolis": "MN", "kansas city": "MO", "st louis": "MO",
  "louisville": "KY", "denver": "CO", "salt lake city": "UT", "phoenix": "AZ", "las vegas": "NV",
  "new york": "NY", "buffalo": "NY", "pittsburgh": "PA", "milwaukee": "WI", "omaha": "NE",
  "des moines": "IA", "little rock": "AR", "jackson": "MS", "birmingham": "AL", "huntsville": "AL",
  "knoxville": "TN", "chattanooga": "TN", "raleigh": "NC", "greensboro": "NC", "greenville": "SC",
  "columbia": "SC", "augusta": "GA", "macon": "GA", "pensacola": "FL", "orlando": "FL",
  "san bernardino": "CA", "fresno": "CA", "sacramento": "CA", "stockton": "CA",
  "albuquerque": "NM", "tucson": "AZ", "boise": "ID", "spokane": "WA",
};

/**
 * Enrich a destination string with a state abbreviation.
 *
 * Resolution order:
 * 1. Already has state abbreviation → return as-is
 * 2. Quote destinations contain state for this city → extract it
 * 3. CITY_TO_STATE lookup → append known state
 * 4. Unknown city → return trimmed original
 *
 * @param {string|null|undefined} dest  Raw destination string
 * @param {Array<{destination?: string}>} [quotes]  Optional quote objects with raw destination
 * @returns {string|null|undefined}
 */
export const enrichDestWithState = (dest, quotes) => {
  if (!dest) return dest;
  const trimmed = dest.trim();
  // Already has state abbreviation (e.g. "Dumas, TX" or "Dumas TX" or "Dumas, TX 77435")
  if (/,?\s+[A-Z]{2}\s*(\d{5})?$/.test(trimmed)) return trimmed;
  // Check if any quote's raw destination has the state
  if (quotes?.length) {
    for (const q of quotes) {
      const rawDest = (q.destination || "").trim();
      const stMatch = rawDest.match(/,?\s+([A-Z]{2})\s*(\d{5})?$/);
      if (stMatch && rawDest.toLowerCase().includes(trimmed.toLowerCase())) {
        return `${trimmed}, ${stMatch[1]}`;
      }
    }
  }
  // Fallback: lookup from known cities
  const st = CITY_TO_STATE[trimmed.toLowerCase()];
  if (st) return `${trimmed.charAt(0).toUpperCase() + trimmed.slice(1)}, ${st}`;
  return trimmed;
};