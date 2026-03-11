"""
terminal_normalizer.py — Origin field standardizer for CSL Bot
================================================================
Normalizes messy terminal / port / city strings from Column G (Origin)
into canonical "Name, STATE" format so routing logic, terminal checks,
and dashboards work consistently.

Usage:
    from terminal_normalizer import normalize_origin
    clean = normalize_origin(raw)          # returns canonical string or original
    changed = normalize_origin(raw) != raw # True if bot would write back to sheet
"""

import re

# ──────────────────────────────────────────────────────────────────────────────
# Canonical names — keep these stable; update dict below if shipping landscape
# changes.  Format: "Short Name, STATE_ABBR"
# ──────────────────────────────────────────────────────────────────────────────

# Lookup: list of (substring_patterns, canonical_name)
# Evaluated in order — first match wins.
# Patterns are matched against a lower-cased, stripped version of the input.
_RULES = [
    # ── New Orleans / Napoleon Ave (Ports America) ───────────────────────────
    (["napoleon ave", "napoleon terminal", "napoleon, la"],         "Napoleon, LA"),
    (["new orleans", "nola", "port of new orleans"],                "New Orleans, LA"),

    # ── Los Angeles / Long Beach Container Terminals ─────────────────────────
    (["apm terminal island", "apm, ca", "apm ca", "apm terminal ca"],  "APM, CA"),
    (["apm elizabeth", "apm, nj", "apm nj", "apm terminal nj",
      "apm terminal elizabeth"],                                     "APM, NJ"),
    # bare "apm" is ambiguous (NJ or CA) — skip normalization

    (["lbct"],                                                        "LBCT, CA"),
    (["wbct", "west basin"],                                          "WBCT, CA"),
    (["tti terminal", "tti, ca", "tti ca", "terminal island, ca"],    "TTI, CA"),
    (["tti"],                                                         "TTI, CA"),
    (["yusen terminal island", "yusen, ca", "yusen ca"],             "Yusen Terminal, CA"),
    (["yusen"],                                                       "Yusen Terminal, CA"),
    (["trapac"],                                                      "TraPac, CA"),
    (["everport"],                                                    "Everport, CA"),
    (["pacific container terminal", "pct"],                           "PCT, CA"),
    (["ssa marine", "ssa, ca"],                                       "SSA Marine, CA"),
    (["total terminal"],                                              "Total Terminals, CA"),
    (["its terminal", "its, ca", "international transportation"],     "ITS, CA"),

    # ── New York / New Jersey ─────────────────────────────────────────────────
    (["maher terminal", "maher, nj", "maher, ny"],                   "Maher Terminal, NJ"),
    (["maher"],                                                       "Maher Terminal, NJ"),
    (["nyct", "new york container terminal", "staten island (nyct)"], "NYCT, NY"),
    (["port newark", "newark, nj"],                                   "Port Newark, NJ"),
    (["port ny", "ny port"],                                          "Port NY, NY"),

    # ── Southeast ─────────────────────────────────────────────────────────────
    (["sfct miami", "south florida container", "sfct, fl"],          "SFCT, FL"),
    (["jaxport", "jacksonville port", "blount island"],              "JAXPORT, FL"),
    (["n charleston", "north charleston"],                           "N Charleston, SC"),
    (["wando"],                                                      "N Charleston, SC"),
    (["savannah, ga", "garden city, ga", "gpa savannah"],            "Savannah, GA"),

    # ── Gulf Coast ────────────────────────────────────────────────────────────
    (["barbours cut", "bayport terminal"],                           "Houston, TX"),

    # ── Rail Terminals ────────────────────────────────────────────────────────
    (["bnsf - mn", "bnsf mn", "bsnf minneapolis", "bnsf minneapolis",
      "minnesota rail"],                                             "BNSF, MN"),
    (["cp minneapolis"],                                             "CP, MN"),
    (["ns - rossville", "ns rossville", "ns - rossville, tn"],      "NS Rossville, TN"),
    (["ns chicago"],                                                 "NS Chicago, IL"),
    (["bnsf - chicago", "bnsf chicago"],                             "BNSF Chicago, IL"),
]

# ── Regex-based state-abbreviation formatter ──────────────────────────────────
# e.g. "Long Beach CA" → "Long Beach, CA"  |  "wilmington,ca" → "Wilmington, CA"
_STATE_RE = re.compile(
    r'^(.*?)\s*,?\s*\b'
    r'(AL|AK|AZ|AR|CA|CO|CT|DE|FL|GA|HI|ID|IL|IN|IA|KS|KY|LA|ME|MD|MA|MI|'
    r'MN|MS|MO|MT|NE|NV|NH|NJ|NM|NY|NC|ND|OH|OK|OR|PA|RI|SC|SD|TN|TX|UT|'
    r'VT|VA|WA|WV|WI|WY)\b\s*(\d{5})?$',
    re.IGNORECASE,
)

_KEEP_UPPER = {"NS", "CP", "UP", "LA", "NJ", "NY", "CA", "TX", "FL", "IL",
               "IN", "SC", "GA", "TN", "MN", "OH", "MI", "VA", "NC", "MD"}

def _title_city(city: str) -> str:
    """Title-case a city name, keeping known abbreviations uppercase."""
    return " ".join(
        w.upper() if w.upper() in _KEEP_UPPER else w.capitalize()
        for w in city.strip().split()
    )

def normalize_origin(raw: str) -> str:
    """
    Return a canonical origin string.  Returns the original (stripped) value
    unchanged if no rule matches and no formatting fix is needed.

    Never returns None or empty string — passes through any non-empty input.
    """
    if not raw or not raw.strip():
        return raw

    stripped = raw.strip()
    key = stripped.lower()

    # ── Rule-based lookup ────────────────────────────────────────────────────
    for patterns, canonical in _RULES:
        for pat in patterns:
            if pat in key:
                return canonical

    # ── Regex formatting fix for "City STATE" → "City, STATE" ───────────────
    m = _STATE_RE.match(stripped)
    if m:
        city_part  = m.group(1).strip().rstrip(",").strip()
        state_part = m.group(2).upper()
        zip_part   = m.group(3) or ""
        if city_part:
            canonical = f"{_title_city(city_part)}, {state_part}"
            if zip_part:
                canonical += f" {zip_part}"
            if canonical != stripped:
                return canonical

    # ── No match — return original stripped ──────────────────────────────────
    return stripped


# ──────────────────────────────────────────────────────────────────────────────
# Self-test (python3 terminal_normalizer.py)
# ──────────────────────────────────────────────────────────────────────────────
if __name__ == "__main__":
    tests = [
        ("Total terminals",         "Total Terminals, CA"),
        ("Total Terminals",         "Total Terminals, CA"),
        ("TTI",                     "TTI, CA"),
        ("APM Elizabeth, NJ",       "APM, NJ"),
        ("APM",                     "APM"),              # ambiguous → passthrough
        ("wilmington,CA",           "Wilmington, CA"),
        ("Long Beach CA",           "Long Beach, CA"),
        ("Long Beach, CA",          "Long Beach, CA"),   # already clean
        ("New Orleans, LA",         "New Orleans, LA"),  # already clean
        ("new orleans",             "New Orleans, LA"),
        ("NOLA",                    "New Orleans, LA"),
        ("Maher, NJ",               "Maher Terminal, NJ"),
        ("Staten Island (NYCT)",    "NYCT, NY"),
        ("SFCT Miami",              "SFCT, FL"),
        ("NS - Rossville, TN",      "NS Rossville, TN"),
        ("BSNF Minneapolis, MN",    "BNSF, MN"),
        ("Minnesota Rail",          "BNSF, MN"),
        ("Tampa FL",                "Tampa, FL"),
        ("N Charleston, SC",        "N Charleston, SC"),  # already clean
        ("North Manchester IN",     "North Manchester, IN"),
        ("Greenville, NC",          "Greenville, NC"),    # already clean
        ("Wood Dale, IL 60191",     "Wood Dale, IL 60191"), # already clean
        ("FIT",                     "FIT"),                # unknown → passthrough
        ("Irving, TX",              "Irving, TX"),         # already clean
        ("San Pedro, CA",           "San Pedro, CA"),      # already clean
        ("Compton CA",              "Compton, CA"),
    ]

    pad = max(len(t[0]) for t in tests) + 2
    all_pass = True
    for raw, expected in tests:
        result = normalize_origin(raw)
        ok = "OK" if result == expected else "FAIL"
        if result != expected:
            all_pass = False
        marker = "  " if ok == "OK" else "**"
        print(f"{marker}{ok}  {raw!r:{pad}} -> {result!r}  (expected {expected!r})")

    print()
    print("ALL PASS" if all_pass else "FAILURES ABOVE ^^^")
