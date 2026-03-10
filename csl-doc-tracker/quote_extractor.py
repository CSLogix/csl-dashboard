"""
Quote Extractor — Uses Claude API to extract carrier rate data from images, PDFs, and emails.
Includes universal port/rail hub normalization and LoadMatch screenshot intelligence.
"""
import base64
import json
import logging
import re
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-sonnet-4-6"

# ── Terminal Hub Definitions ─────────────────────────────────────────────────
# Maps common aliases/substrings → canonical display name + default address
TERMINAL_HUBS = {
    # LA/LB Port Cluster
    "la/lb":                    {"name": "LA/LB Ports",              "address": "700 Pier A Plaza, Long Beach, CA 90802"},
    "lax":                      {"name": "LA/LB Ports",              "address": "700 Pier A Plaza, Long Beach, CA 90802"},
    "los angeles/long beach":   {"name": "LA/LB Ports",              "address": "700 Pier A Plaza, Long Beach, CA 90802"},
    "long beach container":     {"name": "LA/LB Ports (LBCT)",       "address": "Long Beach Container Terminal, Long Beach, CA 90802"},
    "lbct":                     {"name": "LA/LB Ports (LBCT)",       "address": "Long Beach Container Terminal, Long Beach, CA 90802"},
    "apm terminals":            {"name": "LA/LB Ports (APM)",        "address": "APM Terminals, 2500 Navy Way, San Pedro, CA 90731"},
    "apm san pedro":            {"name": "LA/LB Ports (APM)",        "address": "APM Terminals, 2500 Navy Way, San Pedro, CA 90731"},
    "port of los angeles":      {"name": "LA/LB Ports (POLA)",       "address": "425 S Palos Verdes St, San Pedro, CA 90731"},
    "trapac":                   {"name": "LA/LB Ports (TraPac)",     "address": "1000 Yukon Ave, Wilmington, CA 90744"},
    "everport":                 {"name": "LA/LB Ports (Everport)",   "address": "1519 N Panacea Ave, Wilmington, CA 90744"},
    "ssa marine":               {"name": "LA/LB Ports (SSA)",        "address": "2401 E Sepulveda Blvd, Long Beach, CA 90810"},
    "pct":                      {"name": "LA/LB Ports (PCT)",        "address": "Pier J, Long Beach, CA 90802"},
    # NY/NJ Port Cluster
    "ny/nj":                    {"name": "NY/NJ Ports",              "address": "1210 Corbin St, Elizabeth, NJ 07201"},
    "port newark":              {"name": "NY/NJ Ports (Newark)",     "address": "Port Newark Container Terminal, Newark, NJ 07114"},
    "pnct":                     {"name": "NY/NJ Ports (PNCT)",       "address": "241 Port St, Port Newark, NJ 07114"},
    "elizabeth":                {"name": "NY/NJ Ports (Elizabeth)",  "address": "1210 Corbin St, Elizabeth, NJ 07201"},
    "bayonne":                  {"name": "NY/NJ Ports (Bayonne)",    "address": "Port of Bayonne, Bayonne, NJ 07002"},
    "maher":                    {"name": "NY/NJ Ports (Maher)",      "address": "1210 Corbin St, Elizabeth, NJ 07201"},
    # Savannah
    "savannah":                 {"name": "Savannah Ports",           "address": "2 Main St, Garden City, GA 31408"},
    "garden city terminal":     {"name": "Savannah Ports (GCT)",     "address": "2 Main St, Garden City, GA 31408"},
    "ocean terminal savannah":  {"name": "Savannah Ports (Ocean)",   "address": "1 Ocean Terminal Blvd, Savannah, GA 31401"},
    # Houston
    "houston":                  {"name": "Houston Ports",            "address": "1515 E Barbours Cut Blvd, La Marque, TX 77568"},
    "barbours cut":             {"name": "Houston Ports (Barbours)", "address": "1515 E Barbours Cut Blvd, La Marque, TX 77568"},
    "bayport":                  {"name": "Houston Ports (Bayport)",  "address": "Bayport Container Terminal, Seabrook, TX 77586"},
    # BNSF Rail
    "bnsf cicero":              {"name": "BNSF Cicero (Chicago)",    "address": "2600 S 25th Ave, Broadview, IL 60155"},
    "bnsf corwith":             {"name": "BNSF Corwith (Chicago)",   "address": "4848 W 40th St, Chicago, IL 60632"},
    "bnsf hobart":              {"name": "BNSF Hobart (LA)",         "address": "2401 E Carson St, Carson, CA 90810"},
    "bnsf alliance":            {"name": "BNSF Alliance (Dallas)",   "address": "3400 Westport Pkwy, Fort Worth, TX 76177"},
    "bnsf mariposa":            {"name": "BNSF Mariposa (Chicago)",  "address": "Mariposa Intermodal, Chicago, IL 60609"},
    "bnsf memphis":             {"name": "BNSF Memphis",             "address": "3588 Paul R Lowry Rd, Memphis, TN 38109"},
    "bnsf kansas city":         {"name": "BNSF Kansas City",         "address": "1100 W 8th St, Kansas City, MO 64101"},
    # Union Pacific Rail
    "up global":                {"name": "UP Global I (City of Industry)", "address": "15501 Gale Ave, City of Industry, CA 91745"},
    "up ictf":                  {"name": "UP ICTF (Long Beach)",     "address": "2401 E Sepulveda Blvd, Long Beach, CA 90810"},
    "union pacific ictf":       {"name": "UP ICTF (Long Beach)",     "address": "2401 E Sepulveda Blvd, Long Beach, CA 90810"},
    "up interbay":              {"name": "UP Interbay (Seattle)",    "address": "2300 W Commodore Way, Seattle, WA 98199"},
    "up mesquite":              {"name": "UP Mesquite (Dallas)",     "address": "3400 N Belt Line Rd, Mesquite, TX 75150"},
    # Norfolk Southern Rail
    "ns 47th":                  {"name": "NS 47th St (Chicago)",     "address": "4747 S Halsted St, Chicago, IL 60609"},
    "ns landers":               {"name": "NS Landers (Chicago)",     "address": "6800 S Loomis Blvd, Chicago, IL 60636"},
    "ns austell":               {"name": "NS Austell (Atlanta)",     "address": "1501 Veterans Memorial Hwy, Austell, GA 30168"},
    "ns whitaker":              {"name": "NS Whitaker (Memphis)",    "address": "6000 Horn Lake Rd, Memphis, TN 38109"},
    # CSX Rail
    "csx bedford park":         {"name": "CSX Bedford Park (Chicago)", "address": "7300 W 65th St, Bedford Park, IL 60638"},
    "csx fairburn":             {"name": "CSX Fairburn (Atlanta)",   "address": "8400 Senoia Rd, Fairburn, GA 30213"},
    "csx north baltimore":      {"name": "CSX North Baltimore",      "address": "3100 US-68, North Baltimore, OH 45872"},
    # City Centroids
    "chicago":                  {"name": "Chicago",                  "address": "436 W 25th Pl, Chicago, IL 60616"},
    "memphis":                  {"name": "Memphis",                  "address": "3588 Paul R Lowry Rd, Memphis, TN 38109"},
    "kansas city":              {"name": "Kansas City",              "address": "1100 W 8th St, Kansas City, MO 64101"},
    "atlanta":                  {"name": "Atlanta",                  "address": "1600 Marietta Blvd NW, Atlanta, GA 30318"},
}

FIRMS_CODES = {
    "Y183": {"name": "APM Terminals (Y183)",    "address": "APM Terminals, 2500 Navy Way, San Pedro, CA 90731"},
    "W158": {"name": "LBCT (W158)",             "address": "Long Beach Container Terminal, Long Beach, CA 90802"},
    "Y790": {"name": "TraPac (Y790)",           "address": "1000 Yukon Ave, Wilmington, CA 90744"},
    "E472": {"name": "Everport (E472)",         "address": "1519 N Panacea Ave, Wilmington, CA 90744"},
    "Y256": {"name": "SSA Marine (Y256)",       "address": "2401 E Sepulveda Blvd, Long Beach, CA 90810"},
    "E204": {"name": "PNCT (E204)",             "address": "241 Port St, Port Newark, NJ 07114"},
    "E023": {"name": "Port Newark (E023)",      "address": "Port Newark Container Terminal, Newark, NJ 07114"},
}


def normalize_hub(text: str) -> dict | None:
    """Match a fuzzy origin/destination string to a known terminal hub.
    Returns {"name": ..., "address": ...} or None if no match.
    FIRMS code takes priority over substring match."""
    if not text:
        return None
    # FIRMS code check first
    for code, hub in FIRMS_CODES.items():
        if code.upper() in text.upper():
            return hub
    lower = text.lower().strip()
    # Exact match
    if lower in TERMINAL_HUBS:
        return TERMINAL_HUBS[lower]
    # Longest substring match
    best_key = None
    for key in TERMINAL_HUBS:
        if key in lower and (best_key is None or len(key) > len(best_key)):
            best_key = key
    if best_key:
        return TERMINAL_HUBS[best_key]
    return None


def post_process_extraction(result: dict) -> dict:
    """Apply hub normalization to origin/destination fields after Claude extraction."""
    for field in ("origin", "destination"):
        raw = result.get(field, "")
        hub = normalize_hub(raw)
        if hub:
            result[field] = hub["name"]
            # Inject terminal_address only if not already set
            addr_key = "origin_address" if field == "origin" else "destination_address"
            if not result.get(addr_key):
                result[addr_key] = hub["address"]
    return result


EXTRACTION_PROMPT = """You are an expert freight logistics rate extraction AI.

━━━ UNIVERSAL INTERMODAL HUB LOGIC ━━━

PORT CLUSTERS — normalize any mention to the cluster name unless a specific terminal sub-name is given:
- LA/LB: Los Angeles, Long Beach, LAX port, LBCT, APM Terminals, Port of LA, TraPac, Everport, SSA Marine → "LA/LB Ports"
- NY/NJ: Port Newark, Elizabeth, Bayonne, Staten Island, Maher, PNCT → "NY/NJ Ports"
- SAVANNAH: Garden City Terminal, Ocean Terminal → "Savannah Ports"
- HOUSTON: Barbours Cut, Bayport Terminal → "Houston Ports"
- SEATTLE/TACOMA: Terminal 46, Terminal 18, T-5, Husky → "Seattle/Tacoma Ports"
- CHARLESTON: Wando Welch, North Charleston → "Charleston Ports"

RAIL HUBS — always include the railroad prefix and yard name:
- BNSF terminals: Corwith, Cicero, Hobart, Alliance, Mariposa → e.g. "BNSF Cicero (Chicago)"
- UP terminals: Global I-IV, ICTF, Interbay, Mesquite → e.g. "UP ICTF (Long Beach)"
- NS terminals: 47th St, Landers, Austell, Whitaker → e.g. "NS 47th St (Chicago)"
- CSX terminals: Bedford Park, Fairburn, North Baltimore → e.g. "CSX Bedford Park (Chicago)"

FIRMS CODES: If you see Y183, W158, Y790, E472, E204, E023 — include the code in the origin field verbatim.

━━━ LOADMATCH SCREENSHOT LOGIC ━━━
When you see a table with BASE / FSC / TOTAL columns (LoadMatch, DAT, Truckstop format):
- BASE = carrier base rate before fuel surcharge
- FSC% = fuel surcharge percentage applied to BASE
- TOTAL = BASE × (1 + FSC%) = the all-in rate. Use TOTAL for all rate comparisons.
- Market Average is shown in the header row — use that as the authoritative average
- Floor = lowest TOTAL value in the visible results
- Ceiling = highest TOTAL value in the visible results
- data_points = the number shown in parentheses in the page title e.g. "(16 results)" → 16
- Multiple terminal rows in LA/LB (Long Beach Container Terminal, Port of Los Angeles, APM) = same cluster, create one linehaul_item per terminal type found
- Accessorials hidden in text/notes column: extract chassis, pre-pull, pier pass, storage, hazmat if mentioned

━━━ CARRIER EMAIL LOGIC ━━━
- Identify carrier name from From/Signature
- Look for linehaul rate, fuel surcharge line, accessorial lines
- If "scrap" or "scrap material" mentioned anywhere → add scrap_premium accessorial with amount 150

━━━ OUTPUT FORMAT ━━━
Return ONLY valid JSON, no markdown, no backticks:
{
  "carrier_name": "string (use 'Market Data - LoadMatch' for load board screenshots)",
  "origin": "string (normalized hub name e.g. 'LA/LB Ports')",
  "destination": "string",
  "shipment_type": "Dray|FTL|OTR|Transload|Dray+Transload|LTL",
  "round_trip_miles": "string or empty",
  "one_way_miles": "string or empty",
  "transit_time": "string or empty",
  "market_floor": "string (lowest rate, or empty)",
  "market_average": "string (stated average from page header, or empty)",
  "market_ceiling": "string (highest rate, or empty)",
  "data_points": "string (result count, or empty)",
  "linehaul_items": [
    {"description": "string", "rate": "number as string e.g. 350.00"}
  ],
  "accessorials": [
    {"charge": "string", "rate": "string", "frequency": "per day|per hour|flat|per mile", "amount": "string"}
  ],
  "notes": "any extra info, detected fees from notes column, special instructions"
}

RULES:
- Rates must be numeric strings without $ sign
- For a rate range like 275-550, split into two linehaul_items (floor and ceiling) with descriptive labels
- Use empty string for unknown fields, never null or 0 for unknown rates
- Linehaul = main transport charges. Accessorials = extras (chassis, storage, pre-pull, tolls, etc.)
"""


def _get_api_key():
    import os
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    return key


def _call_claude(messages, max_tokens=2000):
    api_key = _get_api_key()
    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": CLAUDE_MODEL,
            "max_tokens": max_tokens,
            "messages": messages,
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["content"][0]["text"]


def _parse_json_response(text):
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end+1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse JSON from Claude response: {text[:200]}")


def extract_from_image(file_path: str) -> dict:
    path = Path(file_path)
    suffix = path.suffix.lower()
    media_map = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp",
    }
    media_type = media_map.get(suffix, "image/png")

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    messages = [{
        "role": "user",
        "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
            {"type": "text", "text": EXTRACTION_PROMPT},
        ]
    }]

    raw = _call_claude(messages)
    return post_process_extraction(_parse_json_response(raw))


def extract_from_pdf(file_path: str) -> dict:
    path = Path(file_path)
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    messages = [{
        "role": "user",
        "content": [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
            {"type": "text", "text": EXTRACTION_PROMPT},
        ]
    }]

    raw = _call_claude(messages)
    return post_process_extraction(_parse_json_response(raw))


def extract_from_text(text: str) -> dict:
    messages = [{
        "role": "user",
        "content": f"{EXTRACTION_PROMPT}\n\nHere is the text to extract from:\n\n{text}"
    }]
    raw = _call_claude(messages)
    return post_process_extraction(_parse_json_response(raw))


def extract_from_email(file_path: str) -> dict:
    """Extract rate data from .msg (Outlook) or .eml email files."""
    path = Path(file_path)
    suffix = path.suffix.lower()

    body = ""
    attachments = []

    if suffix == ".msg":
        import extract_msg
        msg = extract_msg.Message(str(path))
        body = f"Subject: {msg.subject or ''}\nFrom: {msg.sender or ''}\nDate: {msg.date or ''}\n\n{msg.body or ''}"
        for att in (msg.attachments or []):
            if hasattr(att, "filename") and att.filename:
                ext = Path(att.filename).suffix.lower()
                if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"):
                    att_path = Path("/tmp") / att.filename
                    att.save(customPath=str(att_path.parent), customFilename=att_path.name)
                    attachments.append((str(att_path), ext))
        msg.close()
    elif suffix == ".eml":
        import email
        from email import policy
        with open(path, "rb") as f:
            msg = email.message_from_binary_file(f, policy=policy.default)
        body = f"Subject: {msg.get('subject', '')}\nFrom: {msg.get('from', '')}\nDate: {msg.get('date', '')}\n\n"
        if msg.get_body(preferencelist=("plain",)):
            body += msg.get_body(preferencelist=("plain",)).get_content()
        elif msg.get_body(preferencelist=("html",)):
            body += msg.get_body(preferencelist=("html",)).get_content()

    if attachments:
        att_path, ext = attachments[0]
        try:
            if ext == ".pdf":
                return extract_from_pdf(att_path)
            else:
                return extract_from_image(att_path)
        finally:
            for p, _ in attachments:
                try:
                    import os; os.unlink(p)
                except OSError:
                    pass

    if body.strip():
        return extract_from_text(body)

    raise ValueError("No extractable content found in email")
