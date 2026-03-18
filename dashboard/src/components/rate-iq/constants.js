// ═══════════════════════════════════════════════════════════════
// Rate IQ — Shared constants, formatters, and normalization
// ═══════════════════════════════════════════════════════════════

export const grad = "linear-gradient(135deg, #00c853 0%, #00b8d4 50%, #2979ff 100%)";

export const fmt = (n) => {
  const num = parseFloat(n);
  return isNaN(num) ? "$0" : "$" + num.toLocaleString("en-US", { minimumFractionDigits: 0, maximumFractionDigits: 0 });
};

export const fmtDec = (n) => {
  const num = parseFloat(n);
  return isNaN(num) ? "$0.00" : "$" + num.toLocaleString("en-US", { minimumFractionDigits: 2, maximumFractionDigits: 2 });
};

// ── Port cluster normalization ──
// Maps common port name variants to canonical cluster names for grouping + autofill
export const PORT_CLUSTERS = {
  "la/lb": "LA/LB", "la/lb ports": "LA/LB", "lalb": "LA/LB", "lax": "LA/LB",
  "los angeles": "LA/LB", "long beach": "LA/LB", "los angeles/long beach": "LA/LB",
  "lbct": "LA/LB", "apm terminals": "LA/LB", "port of los angeles": "LA/LB",
  "trapac": "LA/LB", "everport": "LA/LB", "ssa marine": "LA/LB", "pct": "LA/LB",
  "san pedro": "LA/LB", "wilmington": "LA/LB", "carson": "LA/LB",
  "ny/nj": "NY/NJ", "ny/nj ports": "NY/NJ", "port newark": "NY/NJ", "pnct": "NY/NJ",
  "elizabeth": "NY/NJ", "bayonne": "NY/NJ", "maher": "NY/NJ", "newark": "NY/NJ",
  "new york": "NY/NJ", "new york, ny": "NY/NJ", "nynj": "NY/NJ", "nj/ny": "NY/NJ",
  "port liberty": "NY/NJ", "nyc port": "NY/NJ", "nyc": "NY/NJ", "new york city": "NY/NJ",
  "bayonne terminal": "NY/NJ", "apmt": "NY/NJ", "global terminal": "NY/NJ",
  "port liberty, ny": "NY/NJ", "nyc port, ny": "NY/NJ", "nyc, ny": "NY/NJ",
  "new york city, ny": "NY/NJ", "bayonne, nj": "NY/NJ", "bayonne terminal, nj": "NY/NJ",
  "elizabeth, nj": "NY/NJ", "newark, nj": "NY/NJ", "port newark, nj": "NY/NJ",
  "savannah": "Savannah", "savannah ports": "Savannah", "garden city": "Savannah",
  "houston": "Houston", "houston ports": "Houston", "barbours cut": "Houston", "barbour's cut": "Houston", "bayport": "Houston",
  "houston, tx": "Houston", "houston tx": "Houston",
  "charleston": "Charleston", "wando welch": "Charleston",
  "norfolk": "Norfolk", "virginia": "Norfolk", "portsmouth": "Norfolk", "nit": "Norfolk",
  "oakland": "Oakland",
};

// US state name → abbreviation for normalizing "Massachusetts" → "MA" etc.
export const STATE_ABBREVS = {
  alabama:"AL",alaska:"AK",arizona:"AZ",arkansas:"AR",california:"CA",colorado:"CO",connecticut:"CT",
  delaware:"DE",florida:"FL",georgia:"GA",hawaii:"HI",idaho:"ID",illinois:"IL",indiana:"IN",iowa:"IA",
  kansas:"KS",kentucky:"KY",louisiana:"LA",maine:"ME",maryland:"MD",massachusetts:"MA",michigan:"MI",
  minnesota:"MN",mississippi:"MS",missouri:"MO",montana:"MT",nebraska:"NE",nevada:"NV",
  "new hampshire":"NH","new jersey":"NJ","new mexico":"NM","new york":"NY","north carolina":"NC",
  "north dakota":"ND",ohio:"OH",oklahoma:"OK",oregon:"OR",pennsylvania:"PA","rhode island":"RI",
  "south carolina":"SC","south dakota":"SD",tennessee:"TN",texas:"TX",utah:"UT",vermont:"VT",
  virginia:"VA",washington:"WA","west virginia":"WV",wisconsin:"WI",wyoming:"WY",
  "district of columbia":"DC"
};

// Normalize a city/location string for grouping: strip zip, abbreviate state, title-case
export function normalizeLocation(text) {
  if (!text) return "";
  let s = text.trim().replace(/\s+\d{5}(-\d{4})?$/, "").trim();
  for (const [name, abbr] of Object.entries(STATE_ABBREVS)) {
    const re = new RegExp(`(,\\s*)${name}$`, "i");
    if (re.test(s)) { s = s.replace(re, `$1${abbr}`); break; }
  }
  s = s.replace(/\b\w+/g, w => w.length <= 2 ? w.toUpperCase() : w.charAt(0).toUpperCase() + w.slice(1).toLowerCase());
  s = s.replace(/,\s*([a-z]{2})$/i, (_, st) => `, ${st.toUpperCase()}`);
  return s;
}

export function normalizePort(text) {
  if (!text) return "";
  const lower = text.trim().toLowerCase();
  const noZip = lower.replace(/\s+\d{5}(-\d{4})?$/, "").trim();
  if (PORT_CLUSTERS[noZip]) return PORT_CLUSTERS[noZip];
  if (PORT_CLUSTERS[lower]) return PORT_CLUSTERS[lower];
  const noState = noZip.replace(/,\s*[a-z]{2}$/i, "").trim();
  if (noState !== noZip && PORT_CLUSTERS[noState]) return PORT_CLUSTERS[noState];
  const hasStateSuffix = /,\s*[A-Za-z]{2,}\s*(\d{5}(-\d{4})?)?$/.test(text.trim()) || Object.keys(STATE_ABBREVS).some(st => noZip.includes(`, ${st}`));
  if (!hasStateSuffix) {
    const entries = Object.entries(PORT_CLUSTERS).sort((a, b) => b[0].length - a[0].length);
    for (const [alias, cluster] of entries) {
      if (lower.includes(alias)) return cluster;
    }
  }
  return normalizeLocation(text);
}

// For lane grouping: strip state suffix so "Baltimore, MD" groups with "Baltimore"
export function normalizeLaneCity(text) {
  const port = normalizePort(text);
  const portLower = port.toLowerCase();
  if (Object.values(PORT_CLUSTERS).some(c => c.toLowerCase() === portLower)) return port;
  const noCommaState = port.replace(/,\s*[A-Z]{2}$/, "").trim();
  if (noCommaState && noCommaState !== port) return noCommaState;
  const US_STATES = new Set(Object.values(STATE_ABBREVS));
  const spaceMatch = port.match(/^(.+?)\s+([A-Z]{2})$/);
  if (spaceMatch && US_STATES.has(spaceMatch[2]) && spaceMatch[1].length >= 3) return spaceMatch[1];
  return port;
}

// Backwards compat alias
export const normalizeOrigin = normalizeLaneCity;

// Split a "City, ST" string into { city, state }
export function splitCityState(text) {
  if (!text) return { city: "", state: "" };
  const normalized = normalizeLocation(text);
  const match = normalized.match(/^(.+?),\s*([A-Z]{2})$/);
  if (match) return { city: match[1].trim(), state: match[2] };
  return { city: normalized, state: "" };
}

export const MOVE_TYPE_STYLES = {
  dray: { label: "Dray", color: "#60a5fa", bg: "rgba(59,130,246,0.12)", border: "rgba(59,130,246,0.25)" },
  ftl: { label: "FTL", color: "#FBBF24", bg: "rgba(251,191,36,0.12)", border: "rgba(251,191,36,0.25)" },
  transload: { label: "Transload", color: "#a78bfa", bg: "rgba(167,139,250,0.12)", border: "rgba(167,139,250,0.25)" },
};
