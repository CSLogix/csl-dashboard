import json
import os
import re
import smtplib
import requests
import gspread
from datetime import datetime, timezone
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.service_account import Credentials
from playwright.sync_api import sync_playwright, TimeoutError as PlaywrightTimeout
from playwright_stealth.stealth import Stealth
_stealth = Stealth()
import time as _time
import random as _random
import argparse
from urllib.parse import urlparse

POLL_INTERVAL = 3 * 60 * 60  # 3 hours in seconds


# ── Bot detection ───────────────────────────────────────────────────────────
CLOUDFLARE_TITLES = ["just a moment", "attention required", "checking your browser"]
AKAMAI_TITLES = ["access denied"]

def detect_bot_block(page):
    """Check if page is showing a bot detection challenge."""
    try:
        title = page.title().lower()
        for t in CLOUDFLARE_TITLES:
            if t in title:
                return "cloudflare"
        for t in AKAMAI_TITLES:
            if t in title:
                return "akamai"
    except Exception:
        pass
    return None

def block_resources(page):
    """Block images, fonts, CSS, and analytics to speed up page loads."""
    def _route_handler(route):
        if route.request.resource_type in ("image", "media", "font", "stylesheet"):
            route.abort()
        elif any(d in route.request.url for d in (
            "google-analytics.com", "googletagmanager.com",
            "facebook.net", "doubleclick.net")):
            route.abort()
        else:
            route.fallback()
    page.route("**/*", _route_handler)


def check_proxy_health(browser, timeout=15000):
    """Quick proxy health check - try loading a lightweight page."""
    try:
        page = browser.new_page()
        page.goto("https://httpbin.org/ip", timeout=timeout)
        body = page.inner_text("body")
        page.close()
        if "origin" in body:
            print(f"  Proxy OK (response: {body.strip()[:60]})")
            return True
        print("  Proxy returned unexpected response")
        return False
    except Exception as exc:
        print(f"  Proxy FAILED: {exc.__class__.__name__}: {str(exc)[:80]}")
        try:
            page.close()
        except Exception:
            pass
        return False


# ── Google Sheets retry wrapper ─────────────────────────────────────────────
def sheets_retry(func, *args, max_retries=5, **kwargs):
    """Retry Google Sheets API calls on 429 quota errors."""
    for attempt in range(max_retries):
        try:
            return func(*args, **kwargs)
        except Exception as exc:
            if "429" in str(exc) and attempt < max_retries - 1:
                wait = min(2 ** attempt + _random.uniform(0, 1), 60)
                print(f"  QUOTA HIT (429) — waiting {wait:.1f}s "
                      f"(attempt {attempt+1}/{max_retries})")
                _time.sleep(wait)
            else:
                raise
    return None


# ── Circuit breaker ─────────────────────────────────────────────────────────
class CircuitBreaker:
    """Skip a carrier domain after consecutive failures within a run."""
    def __init__(self, threshold=3):
        self._failures = {}
        self._threshold = threshold

    def should_skip(self, domain):
        return self._failures.get(domain, 0) >= self._threshold

    def record_failure(self, domain):
        self._failures[domain] = self._failures.get(domain, 0) + 1

    def record_success(self, domain):
        self._failures[domain] = 0


# ── JsonCargo API helpers (for Maersk + HMM) ───────────────────────────────
def _get_jsoncargo_key():
    return os.environ.get("JSONCARGO_API_KEY", "")
JSONCARGO_BASE = "https://api.jsoncargo.com/api/v1"

# -- JsonCargo API response cache (reduces monthly API calls by ~70%%) --
import json as _json
import time as _time_mod

_JSONCARGO_CACHE_FILE = "/root/csl-bot/jsoncargo_cache.json"
_JSONCARGO_CACHE_TTL = 6 * 3600

def _load_jc_cache():
    try:
        with open(_JSONCARGO_CACHE_FILE, "r") as f:
            return _json.load(f)
    except Exception:
        return {}

def _save_jc_cache(cache):
    try:
        with open(_JSONCARGO_CACHE_FILE, "w") as f:
            _json.dump(cache, f)
    except Exception as e:
        print(f"    Cache save error: {e}")

def _jc_cache_get(container_num):
    cache = _load_jc_cache()
    entry = cache.get(container_num)
    if entry and (_time_mod.time() - entry.get("ts", 0)) < _JSONCARGO_CACHE_TTL:
        return entry.get("data")
    return None

def _jc_cache_set(container_num, data):
    cache = _load_jc_cache()
    cache[container_num] = {"ts": _time_mod.time(), "data": data}
    cutoff = _time_mod.time() - 48 * 3600
    cache = {k: v for k, v in cache.items() if v.get("ts", 0) > cutoff}
    _save_jc_cache(cache)


_SSL_LINE_MAP = {
    "cma": "CMA_CGM", "cgm": "CMA_CGM", "maersk": "MAERSK",
    "hapag": "HAPAG_LLOYD", "msc": "MSC", "evergreen": "EVERGREEN",
    "one": "ONE", "cosco": "COSCO", "zim": "ZIM",
    "yang ming": "YANG_MING", "hmm": "HMM",
}

def _detect_ssl_line(vessel, carrier_name=""):
    combined = f"{vessel} {carrier_name}".lower()
    for key, val in _SSL_LINE_MAP.items():
        if key in combined:
            return val
    return None

# -- SeaRates Container Tracking API ─────────────────────────────────────
def _searates_container_track(container_num, ssl_line):
    """Track a container via SeaRates API. Returns 4-tuple or None if not configured."""
    sr_key = os.environ.get("SEARATES_API_KEY", "")
    if not sr_key:
        return None
    try:
        resp = requests.get(
            "https://tracking.searates.com/tracking",
            params={"api_key": sr_key, "number": container_num, "sealine": "auto"},
            timeout=25,
        )
        data = resp.json()
        if data.get("status") != "success":
            msg = data.get("message", "unknown error")
            print(f"    SeaRates: {msg}")
            if any(kw in msg.lower() for kw in ("not found", "invalid", "not recognized")):
                return None, None, None, "_fallback"
            return None, None, None, None

        # Gather event descriptions
        events = []
        raw = data.get("data", {}).get("events", [])
        for ev in raw:
            desc = (ev.get("description") or "").lower()
            if desc:
                events.append(desc)

        # Fallback: container-level status
        if not events:
            for c in data.get("data", {}).get("containers", []):
                cs = (c.get("status") or "").lower()
                if cs:
                    events.append(cs)

        if not events:
            meta_st = (data.get("data", {}).get("metadata", {}).get("status") or "").lower()
            if meta_st:
                events.append(meta_st)

        if not events:
            print("    SeaRates: response OK but no events")
            return None, None, None, None

        print(f"    SeaRates: {len(events)} events found")
        all_text = " ".join(events)

        # Status extraction — same keyword priority as JSONCargo
        status = None
        for kw in ["empty container returned", "empty container return",
                    "empty return", "empty in", "gate in empty"]:
            if kw in all_text:
                status = "Returned to Port"; break
        if not status:
            for kw in ["gate out", "full out", "out gate",
                        "pick-up by merchant haulage"]:
                if kw in all_text:
                    status = "Released"; break
        if not status and ("discharged" in all_text or "discharge" in all_text
                           or "unloaded from vessel" in all_text):
            status = "Discharged"
        if not status:
            for kw in ["container to consignee", "pick up by consignee",
                        "delivery to consignee"]:
                if kw in all_text:
                    status = "Released"; break
        if not status:
            for kw in ["vessel departure", "vessel sailed", "departed by vessel",
                        "departed from"]:
                if kw in all_text:
                    status = "Vessel"; break
        if not status:
            for kw in ["vessel arrived", "actual arrival", "arrival in",
                        "arrived at port"]:
                if kw in all_text:
                    status = "Vessel Arrived"; break
        if not status:
            for kw in ["rail", "on rail", "ramp arrival", "intermodal"]:
                if kw in all_text:
                    status = "Rail"; break
        if not status:
            for kw in ["vessel eta", "estimated arrival", "expected arrival"]:
                if kw in all_text:
                    status = "Vessel"; break

        # SeaRates event_code fallback
        if not status:
            codes = [ev.get("event_code", "").upper() for ev in raw]
            if "DISC" in codes: status = "Discharged"
            elif "ARRI" in codes: status = "Vessel Arrived"
            elif "DEPA" in codes: status = "Vessel"
            elif "LOAD" in codes: status = "Vessel"
            elif "PICK" in codes: status = "Released"

        # SeaRates metadata status fallback
        if not status:
            meta_st = (data.get("data", {}).get("metadata", {}).get("status") or "").upper()
            sr_status_map = {
                "IN_TRANSIT": "Vessel", "ARRIVED": "Vessel Arrived",
                "DISCHARGED": "Discharged", "DELIVERED": "Released",
            }
            status = sr_status_map.get(meta_st)

        # Date extraction
        eta = pickup = ret = None
        for ev in raw:
            desc = (ev.get("description") or "").lower()
            d = ev.get("date") or ""
            if not d:
                continue
            if not eta and any(k in desc for k in [
                "vessel eta", "estimated arrival", "expected", "arrival"]):
                eta = d
            if not pickup and any(k in desc for k in [
                "gate out", "full out", "pick-up", "available", "discharged"]):
                pickup = d
            if not ret and any(k in desc for k in [
                "empty container return", "empty return", "empty in", "gate in empty"]):
                ret = d

        # ETA from containers array
        if not eta:
            for c in data.get("data", {}).get("containers", []):
                if c.get("eta"):
                    eta = c["eta"]; break

        return eta, pickup, ret, status

    except Exception as e:
        print(f"    SeaRates error: {e}")
        return None, None, None, None


def _jsoncargo_container_track(container_num, ssl_line):
    """Track a container via JsonCargo API. Returns (eta, pickup, ret, status)."""
    container_num = container_num.strip()
    cached = _jc_cache_get(container_num)
    if cached is not None:
        print(f"    Tracking: cache hit for {container_num}")
        return tuple(cached)
    # -- Try SeaRates first (if SEARATES_API_KEY is configured) --
    if os.environ.get("SEARATES_API_KEY"):
        sr = _searates_container_track(container_num, ssl_line)
        if sr is not None:
            _eta, _pu, _ret, _st = sr
            if _st and _st != "_fallback":
                print(f"    SeaRates: resolved → {_st}")
                _jc_cache_set(container_num, list(sr))
                return sr
            # SeaRates returned _fallback or empty — try JSONCargo
    # -- Fall back to JSONCargo --
    JSONCARGO_API_KEY = _get_jsoncargo_key()
    if not JSONCARGO_API_KEY:
        # Neither SeaRates nor JSONCargo available
        print("    No tracking API keys configured")
        return None, None, None, "_fallback"
    try:
        url = f"{JSONCARGO_BASE}/containers/{container_num}/"
        resp = requests.get(url, headers={"x-api-key": JSONCARGO_API_KEY},
                           params={"shipping_line": ssl_line}, timeout=20)
        data = resp.json()
        if "error" in data:
            err_title = data['error'].get('title', 'error')
            print(f"    JsonCargo: {err_title}")
            # Signal fallback for unrecognized container prefixes
            if any(kw in err_title.lower() for kw in ("prefix not found", "not valid tracking")):
                return None, None, None, "_fallback"
            return None, None, None, None

        events = []
        raw = (data.get("data", {}).get("events", [])
               or data.get("data", {}).get("moves", []) or [])
        for ev in raw:
            desc = (ev.get("description") or ev.get("move")
                    or ev.get("status") or "").lower()
            if desc:
                events.append(desc)

        # Flat response fallback (e.g. Evergreen) -- no events array,
        # status + dates are top-level fields in data
        d = data.get("data", {})
        flat_status = (d.get("container_status") or "").lower()
        if not events and flat_status:
            events.append(flat_status)
            print(f"    JsonCargo: flat response -- container_status=\"{flat_status}\"")
        else:
            print(f"    JsonCargo: {len(events)} events found")

        all_text = " ".join(events)
        status = None
        for kw in ["empty container returned", "empty container return",
                    "empty return", "empty in", "gate in empty"]:
            if kw in all_text:
                status = "Returned to Port"; break
        if not status:
            for kw in ["gate out", "full out", "out gate",
                        "pick-up by merchant haulage"]:
                if kw in all_text:
                    status = "Released"; break
        if not status and ("discharged" in all_text or "discharge" in all_text
                           or "unloaded from vessel" in all_text):
            status = "Discharged"
        if not status:
            for kw in ["container to consignee", "pick up by consignee",
                        "delivery to consignee"]:
                if kw in all_text:
                    status = "Released"; break
        if not status:
            for kw in ["vessel departure", "vessel sailed", "departed by vessel",
                        "departed from"]:
                if kw in all_text:
                    status = "Vessel"; break
        if not status:
            for kw in ["vessel arrived", "actual arrival", "arrival in",
                        "arrived at port"]:
                if kw in all_text:
                    status = "Vessel Arrived"; break
        if not status:
            for kw in ["rail", "on rail", "ramp arrival", "intermodal"]:
                if kw in all_text:
                    status = "Rail"; break
        if not status:
            for kw in ["vessel eta", "estimated arrival", "expected arrival"]:
                if kw in all_text:
                    status = "Vessel"; break

        eta = pickup = ret = None
        for ev in raw:
            desc = (ev.get("description") or ev.get("move")
                    or ev.get("status") or "").lower()
            d = (ev.get("date") or ev.get("actual_date")
                 or ev.get("estimated_date") or "")
            if not d:
                continue
            if not eta and any(k in desc for k in [
                "vessel eta", "estimated arrival", "expected", "arrival"]):
                eta = d
            if not pickup and any(k in desc for k in [
                "gate out", "full out", "pick-up", "available"]):
                pickup = d
            if not ret and any(k in desc for k in [
                "empty container return", "empty return", "empty in", "gate in empty"]):
                ret = d

        # Flat response date fallback (e.g. Evergreen, some Maersk)
        if not raw and d:
            ts = d.get("timestamp_of_last_location") or d.get("last_movement_timestamp") or ""
            if not eta:
                eta = d.get("eta_final_destination") or d.get("eta_next_destination") or None
            if not pickup and ts:
                if flat_status and any(k in flat_status for k in [
                    "gate out", "full out", "pick-up", "discharged", "discharge",
                    "unloaded from vessel", "container to consignee"]):
                    pickup = ts
            if not ret and ts:
                if flat_status and any(k in flat_status for k in [
                    "empty container return", "empty return", "empty in"]):
                    ret = ts

        if status and status != "_fallback":
            _jc_cache_set(container_num, [eta, pickup, ret, status])
        return eta, pickup, ret, status
    except Exception as e:
        print(f"    JsonCargo error: {e}")
        return None, None, None, None

from dotenv import load_dotenv

load_dotenv()

from csl_pg_writer import pg_update_shipment, pg_archive_shipment
from csl_sheet_writer import sheet_update_import, sheet_archive_row
try:
    from terminal_nola import check_nola_containers as _check_nola
    _TERMINAL_NOLA_OK = True
except ImportError:
    _TERMINAL_NOLA_OK = False
    def _check_nola(_): return {}

try:
    from terminal_normalizer import normalize_origin as _normalize_origin
except ImportError:
    def _normalize_origin(x): return x  # no-op fallback

SHEET_ID         = os.environ["SHEET_ID"]
CREDENTIALS_FILE = os.environ.get("GOOGLE_CREDENTIALS_FILE", "/root/csl-credentials.json")
STATUS_FILTER    = "Tracking Waiting for Update"
LAST_CHECK_FILE  = "/root/csl-bot/last_check.json"

# ── SMTP / email ────────────────────────────────────────────────────────────────
SMTP_HOST      = "smtp.gmail.com"
SMTP_PORT      = 587
SMTP_USER      = os.environ["SMTP_USER"]
SMTP_PASSWORD  = os.environ["SMTP_PASSWORD"]
EMAIL_CC       = os.environ.get("EMAIL_CC", "efj-operations@evansdelivery.com")
EMAIL_FALLBACK = os.environ.get("EMAIL_CC", "efj-operations@evansdelivery.com")

# ── Tab config ──────────────────────────────────────────────────────────────────
ACCOUNT_LOOKUP_TAB = "Account Rep"
SKIP_TABS = {
    "Sheet 4", "DTCELNJW", "Account Rep", "SSL Links", "Completed Eli", "Completed Radka",
}

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets",
    "https://www.googleapis.com/auth/drive",
]

# Column numbers (1-indexed, for gspread)
COL_MOVE_TYPE = 2   # B — determines workflow
COL_TRACKING  = 3   # C — hyperlink URL
COL_BOL       = 4   # D — BOL / booking number
COL_ETA       = 9   # I
COL_PICKUP    = 11  # K
COL_RETURN    = 16  # P — Return to Port date
COL_STATUS    = 13  # M — dropdown status
COL_TIMESTAMP = 15  # O

# Statuses the bot sets -- only overwrite if current status is empty or one of these
BOT_MANAGED_STATUSES = {'', 'Vessel', 'Vessel Arrived', 'Discharged', 'Rail', 'Released', 'Returned to Port', 'On Vessel'}

# ── Postgres migration: hardcoded lookups (replaces sheet tabs) ──────────
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv as _pg_load_dotenv
_pg_load_dotenv("/root/csl-bot/csl-doc-tracker/.env")

def _pg_connect():
    """Connect to Postgres using dashboard .env credentials."""
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "csl_dispatch"),
        user=os.getenv("DB_USER", "csl_user"),
        password=os.getenv("DB_PASSWORD", ""),
    )

SSL_LINKS = {
    "maersk":    {"code": "MAERSK",      "url": "https://www.maersk.com/tracking"},
    "hapag":     {"code": "HAPAG_LLOYD",  "url": "https://www.hapag-lloyd.com/en/online-business/track"},
    "hapag-lloyd": {"code": "HAPAG_LLOYD","url": "https://www.hapag-lloyd.com/en/online-business/track"},
    "one":       {"code": "ONE",          "url": "https://ecomm.one-line.com/one-ecom/manage-shipment/cargo-tracking"},
    "evergreen": {"code": "EVERGREEN",    "url": "https://www.shipmentlink.com/tvs2/jsp/TVS2_498.jsp"},
    "hmm":       {"code": "HMM",          "url": "https://www.hmm21.com/cms/business/ebiz/trackTrace"},
    "cma cgm":   {"code": "CMA_CGM",      "url": "https://www.cma-cgm.com/ebusiness/tracking"},
    "cma":       {"code": "CMA_CGM",      "url": "https://www.cma-cgm.com/ebusiness/tracking"},
    "apl":       {"code": "CMA_CGM",      "url": "https://www.apl.com/tracking"},
    "msc":       {"code": "MSC",          "url": "https://www.msc.com/en/track-a-shipment"},
    "cosco":     {"code": "COSCO",        "url": "https://elines.coscoshipping.com/ebusiness/cargoTracking"},
    "zim":       {"code": "ZIM",          "url": "https://www.zim.com/tools/track-a-shipment"},
    "yang ming": {"code": "YANG_MING",    "url": "https://www.yangming.com/e-service/Track_Trace/track_trace_cargo_tracking.aspx"},
    "acl":       {"code": "CMA_CGM",      "url": "https://www.aclcargo.com/track-trace/"},
    "sm line":   {"code": "SM_LINE",      "url": "https://www.smlines.com/smline/CUP_HOM_3000.do"},
    "sml":       {"code": "SM_LINE",      "url": "https://www.smlines.com/smline/CUP_HOM_3000.do"},
    "matson":    {"code": "MATSON",        "url": "https://www.matson.com/tracking"},
}

ACCOUNT_REPS = {
    "Allround": {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Boviet":   {"rep": "",      "email": "Boviet-efj@evansdelivery.com"},
    "Cadi":     {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "CNL":      {"rep": "Janice","email": "Janice.Cortes@evansdelivery.com"},
    "DHL":      {"rep": "John F","email": "John.Feltz@evansdelivery.com"},
    "DSV":      {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "EShipping":{"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "IWS":      {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Kishco":   {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "Kripke":   {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "MAO":      {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "Mamata":   {"rep": "John F","email": "John.Feltz@evansdelivery.com"},
    "Meiko":    {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "MGF":      {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Mitchell's Transport": {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "Rose":     {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "SEI Acquisition": {"rep": "John F", "email": "John.Feltz@evansdelivery.com"},
    "Sutton":   {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Tanera":   {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "TCR":      {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Texas International": {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "USHA":     {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "MD Metal": {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
}




# ── Dynamic rep lookup (TTL-cached, refreshes every 20 min) ──────────────
import time as _time

_REP_CACHE = {"data": {}, "ts": 0.0}
_REP_CACHE_TTL = 20 * 60  # 20 minutes

def _load_account_reps_from_sheet(sh, force=False):
    """Load ACCOUNT_REPS dynamically from the Account Rep sheet tab."""
    now = _time.time()
    if not force and now - _REP_CACHE["ts"] < _REP_CACHE_TTL:
        return _REP_CACHE["data"]
    try:
        ws = sh.worksheet("Account Rep")
        rows = ws.get_all_values()
        result = {}
        for row in rows[1:]:
            if len(row) >= 3 and row[0].strip():
                acct = row[0].strip().lower()
                result[acct] = {
                    "rep":   row[1].strip(),
                    "email": row[2].strip() if len(row) > 2 else "",
                }
        _REP_CACHE["data"] = result
        _REP_CACHE["ts"] = now
        print(f"  [rep_cache] loaded {len(result)} accounts from Account Rep sheet")
        return result
    except Exception as e:
        print(f"  [rep_cache] WARNING: sheet load failed ({e}) — using hardcoded fallback")
        return {}

def _get_rep_for_account(sh, account_name):
    """
    Lookup rep info for an account. Uses TTL-cached sheet data.
    Falls back to hardcoded ACCOUNT_REPS. Case-insensitive strip match.
    On cache miss, forces a live re-read before giving up.
    Returns dict with 'rep' and 'email', or None if not found.
    """
    key = account_name.strip().lower()
    # Try dynamic sheet data first
    reps = _load_account_reps_from_sheet(sh)
    if key in reps:
        return reps[key]
    # Cache miss: force a live re-read
    reps = _load_account_reps_from_sheet(sh, force=True)
    if key in reps:
        return reps[key]
    # Fall back to hardcoded ACCOUNT_REPS (normalized key)
    for acct_key, info in ACCOUNT_REPS.items():
        if acct_key.strip().lower() == key:
            return info
    return None

def _resolve_ssl_pg(vessel, carrier):
    """Resolve SSL code + URL from vessel/carrier text using hardcoded SSL_LINKS."""
    for text in (vessel or "", carrier or ""):
        val = text.strip().lower()
        if not val:
            continue
        # Exact match
        if val in SSL_LINKS:
            return SSL_LINKS[val]
        # Substring match
        for key, info in SSL_LINKS.items():
            if key in val:
                return info
        # Word-boundary match
        for key, info in SSL_LINKS.items():
            if any(w.startswith(key) for w in val.split()):
                return info
    return None


# ShipmentLink status keyword → sheet dropdown value mapping
SHIPMENTLINK_STATUS_MAP = {
    "vessel eta":                  "Vessel",
    "estimated arrival":           "Vessel",
    "expected arrival":            "Vessel",
    "expected":                    "Vessel",
    "eta":                         "Vessel",
    "rail":                        "Rail",
    "on rail":                     "Rail",
    "ramp arrival":                "Rail",
    "intermodal":                  "Rail",
    "ramp":                        "Rail",
    "vessel arrived":              "Vessel Arrived",
    "ata":                         "Vessel Arrived",
    "actual arrival":              "Vessel Arrived",
    "arrival":                     "Vessel Arrived",
    "discharged":                  "Discharged",
    "pick-up by merchant haulage": "Released",
    "merchant haulage":            "Released",
    "gate out":                    "Released",
    "full out":                    "Released",
    "out gate":                    "Released",
    "full gate out":               "Released",
    "empty container returned":    "Returned to Port",
    "empty return":                "Returned to Port",
    "empty in":                    "Returned to Port",
    "gate in empty":               "Returned to Port",
    "returned":                    "Returned to Port",
}


# ─────────────────────────────────────────────
# Google Sheets helpers
# ─────────────────────────────────────────────

def get_sheet_hyperlinks(creds, sheet_id, tab_name):
    """
    Call Sheets API v4 directly to fetch the hyperlink property for every cell.
    Returns a 2-D list [row][col] of URL strings or None.
    """
    creds.refresh(GoogleRequest())
    api_url = (
        f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
        f"?ranges={requests.utils.quote(tab_name)}"
        f"&fields=sheets.data.rowData.values.hyperlink"
        f"&includeGridData=true"
    )
    resp = requests.get(api_url, headers={"Authorization": f"Bearer {creds.token}"})
    resp.raise_for_status()
    data = resp.json()

    result = []
    for row_data in data["sheets"][0]["data"][0].get("rowData", []):
        result.append([cell.get("hyperlink") for cell in row_data.get("values", [])])
    return result


def col_letter(n):
    """Convert 1-indexed column number to A1 letter(s).  9 → 'I', 15 → 'O'."""
    s = ""
    while n > 0:
        n, r = divmod(n - 1, 26)
        s = chr(65 + r) + s
    return s


def write_tracking_results(ws, sheet_row, eta, pickup, return_date, status=None):
    """
    Write ETA (I), Pickup (K), Return (P), and Timestamp (O) as RAW values.
    Status (M) is written USER_ENTERED so Sheets validates the dropdown.
    """
    timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")

    ws.batch_update(
        [
            {"range": f"{col_letter(COL_ETA)}{sheet_row}",       "values": [[eta or ""]]},
            {"range": f"{col_letter(COL_PICKUP)}{sheet_row}",    "values": [[pickup or ""]]},
            {"range": f"{col_letter(COL_RETURN)}{sheet_row}",    "values": [[return_date or ""]]},
            {"range": f"{col_letter(COL_TIMESTAMP)}{sheet_row}", "values": [[timestamp]]},
        ],
        value_input_option="RAW",
    )

    if status:
        ws.batch_update(
            [{"range": f"{col_letter(COL_STATUS)}{sheet_row}", "values": [[status]]}],
            value_input_option="USER_ENTERED",
        )

    if status == "Returned to Port":
        ws.format(
            f"{col_letter(COL_STATUS)}{sheet_row}",
            {"backgroundColor": {"red": 144 / 255, "green": 238 / 255, "blue": 144 / 255}},
        )

    print(f"  Written → ETA={eta!r}  Pickup={pickup!r}  Return={return_date!r}  "
          f"Status={status!r}  [{timestamp}]")


# ─────────────────────────────────────────────
# Playwright — generic browser helpers
# ─────────────────────────────────────────────

INPUT_SELECTORS = [
    "input[placeholder*='BOL' i]",
    "input[placeholder*='B/L' i]",
    "input[placeholder*='bill of lading' i]",
    "input[placeholder*='booking' i]",
    "input[placeholder*='tracking' i]",
    "input[placeholder*='container' i]",
    "input[placeholder*='search' i]",
    "input[placeholder*='reference' i]",
    "input[name*='bol' i]",
    "input[name*='bl' i]",
    "input[name*='booking' i]",
    "input[name*='tracking' i]",
    "input[name*='search' i]",
    "input[name*='query' i]",
    "input[id*='bol' i]",
    "input[id*='bl' i]",
    "input[id*='booking' i]",
    "input[id*='tracking' i]",
    "input[id*='search' i]",
    "input[type='search']",
    "input[type='text']",
    "textarea",
]

SUBMIT_SELECTORS = [
    "button[type='submit']",
    "input[type='submit']",
    "button:has-text('Track')",
    "button:has-text('Search')",
    "button:has-text('Submit')",
    "button:has-text('Go')",
    "[role='button']:has-text('Track')",
    "[role='button']:has-text('Search')",
]

DISMISS_SELECTORS = [
    "button:has-text('Accept all')",
    "button:has-text('Accept')",
    "button:has-text('Agree')",
    "button:has-text('Close')",
    "button:has-text('Got it')",
]

DATE_RE = re.compile(
    r"\b("
    r"\d{1,2}[/\-]\d{1,2}[/\-]\d{2,4}"
    r"|\d{4}[/\-]\d{2}[/\-]\d{2}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{1,2},?\s+\d{4}"
    r"|\d{1,2}\s+(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*\.?\s+\d{2,4}"
    r"|(?:Jan|Feb|Mar|Apr|May|Jun|Jul|Aug|Sep|Oct|Nov|Dec)[a-z]*-\d{1,2}-\d{4}"
    r")\b",
    re.IGNORECASE,
)

ETA_KEYWORDS    = ["eta", "estimated arrival", "est. arrival", "vessel arrival",
                   "arrival date", "arrives", "port arrival", "ata", "atd"]
PICKUP_KEYWORDS = ["pickup", "pick up", "pick-up", "available", "lfd",
                   "last free day", "free time", "available for pickup", "avail",
                   "gate out", "out gate", "out-gate", "full out"]
RETURN_KEYWORDS = ["return", "empty return", "empty due", "return date",
                   "empty out", "empty in", "gate in empty"]


def _find_date_near_keyword(text, keywords):
    """Return the first date found on the keyword line itself, or the immediately
    following line only.  The old 3-line window caused dates from the next field
    to bleed into the wrong column when carrier pages list fields tightly.
    """
    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for i, line in enumerate(lines):
        if any(kw in line.lower() for kw in keywords):
            # Prefer date on the same line (e.g. "ETA: 03/15")
            m = DATE_RE.search(line)
            if m:
                return m.group(0)
            # Fall back to next line only -- avoids grabbing dates 2+ rows away
            if i + 1 < len(lines):
                m = DATE_RE.search(lines[i + 1])
                if m:
                    return m.group(0)
    return None


def _find_input(page):
    for selector in INPUT_SELECTORS:
        try:
            loc = page.locator(selector).first
            if loc.is_visible(timeout=500) and loc.is_enabled(timeout=500):
                return loc
        except Exception:
            continue
    return None


def _dismiss_dialogs(page):
    for sel in DISMISS_SELECTORS:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=800):
                btn.click()
                page.wait_for_timeout(500)
        except Exception:
            pass


def _scrape_jitter():
    """Brief randomized pause before form submission — mimics human read time.
    Keeps browser scrapers from looking like automated scripts to rate limiters."""
    import random, time
    time.sleep(random.uniform(0.8, 2.2))


def _submit(page, input_loc, value):
    _scrape_jitter()
    input_loc.click()
    input_loc.fill(value)
    input_loc.press("Enter")

    try:
        page.wait_for_load_state("networkidle", timeout=15_000)
    except PlaywrightTimeout:
        pass

    for sel in SUBMIT_SELECTORS:
        try:
            btn = page.locator(sel).first
            if btn.is_visible(timeout=500):
                btn.click()
                page.wait_for_load_state("networkidle", timeout=15_000)
                break
        except Exception:
            continue


def _scrape_dates(page):
    try:
        text = page.inner_text("body")
    except Exception:
        return None, None, None

    return (
        _find_date_near_keyword(text, ETA_KEYWORDS),
        _find_date_near_keyword(text, PICKUP_KEYWORDS),
        _find_date_near_keyword(text, RETURN_KEYWORDS),
    )


def run_dray_import(browser, url, bol):
    page = browser.new_page()
    _stealth.apply_stealth_sync(page)
    block_resources(page)
    try:
        print(f"    Loading {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        blocked = detect_bot_block(page)
        if blocked:
            print(f"    BLOCKED ({blocked}) — skipping")
            return None, None, None, None
        _dismiss_dialogs(page)

        input_loc = _find_input(page)
        if input_loc is None:
            print(f"    WARNING: no search input found on page")
            return None, None, None, None

        _submit(page, input_loc, bol)
        page.wait_for_timeout(2_000)

        eta, pickup, ret = _scrape_dates(page)

        if ret:
            status = "Returned to Port"
        elif pickup:
            status = "Released"
        elif eta:
            status = "Vessel"
        else:
            status = None

        return eta, pickup, ret, status

    except PlaywrightTimeout as exc:
        print(f"    TIMEOUT: {exc}")
        return None, None, None, None
    except Exception as exc:
        print(f"    ERROR: {exc}")
        return None, None, None, None
    finally:
        page.close()


# ─────────────────────────────────────────────
# Shipmentlink-specific scraper
# ─────────────────────────────────────────────

SHIPMENTLINK_ETA_STATUSES = [
    "vessel eta", "estimated arrival", "expected arrival", "expected", "eta",
    "vessel arrived", "ata", "actual arrival", "arrival", "discharged",
]
SHIPMENTLINK_PRE_ARRIVAL_STATUSES = {
    "vessel eta", "estimated arrival", "expected arrival", "expected", "eta",
}
SHIPMENTLINK_RAIL_STATUSES = [
    "rail", "on rail", "ramp arrival", "intermodal", "ramp", "train",
]
SHIPMENTLINK_PICKUP_STATUSES = [
    "pick-up by merchant haulage", "merchant haulage",
    "gate out", "full out", "out gate", "full gate out",
]
SHIPMENTLINK_RETURN_STATUSES = [
    "empty container returned", "empty return", "empty in", "gate in empty",
]

_CONTAINER_ID_RE = re.compile(r'\b[A-Z]{4}\d{7}\b', re.IGNORECASE)


_SHIPMENTLINK_UA = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/121.0.0.0 Safari/537.36"
)


def run_shipmentlink(browser, url, bol, container):
    """
    Shipmentlink (ct.shipmentlink.com) scraper.
    Uses a real-browser User-Agent and retries once on timeout.
    """
    for attempt in range(1, 3):
        context = browser.new_context(user_agent=_SHIPMENTLINK_UA)
        page = context.new_page()
        _stealth.apply_stealth_sync(page)
        block_resources(page)
        try:
            label = " (retry)" if attempt == 2 else ""
            print(f"    Loading {url}{label}")
            page.goto(url, wait_until="domcontentloaded", timeout=60_000)
            blocked = detect_bot_block(page)
            if blocked:
                print(f"    BLOCKED ({blocked}) — skipping")
                return None, None, None, None
            page.wait_for_timeout(3_000)

            try:
                if page.locator("#btn_cookie_accept_all").is_visible(timeout=2_000):
                    page.locator("#btn_cookie_accept_all").click()
                    page.wait_for_timeout(800)
            except Exception:
                pass

            page.locator("#s_bl").check()
            inp = page.locator("input#NO")
            inp.fill(bol)
            inp.press("Enter")
            try:
                page.wait_for_load_state("networkidle", timeout=20_000)
            except PlaywrightTimeout:
                pass
            page.wait_for_timeout(3_000)

            if bol not in page.inner_text("body"):
                print(f"    WARNING: B/L {bol} not found in results page")
                return None, None, None, None

            try:
                page.evaluate("getDispInfo('PickupRefTitle','PickupRefInfo')")
                page.wait_for_function(
                    "document.getElementById('PickupRefInfo') && "
                    "document.getElementById('PickupRefInfo').innerText.trim().length > 0",
                    timeout=8_000,
                )
            except Exception:
                pass
            page.wait_for_timeout(1_500)

            try:
                page.evaluate("getDispInfo('RlsStatusTitle','RlsStatusInfo')")
                page.wait_for_function(
                    "document.getElementById('RlsStatusInfo') && "
                    "document.getElementById('RlsStatusInfo').innerText.trim().length > 0",
                    timeout=5_000,
                )
            except Exception:
                pass
            page.wait_for_timeout(1_000)

            body_text = page.inner_text("body")
            lines = [l.strip() for l in body_text.split("\n") if l.strip()]
            container_upper = container.upper()

            # ── ETA ──────────────────────────────────────────────────────────────
            eta = None
            eta_status_kw = None
            for line in lines:
                if container_upper in line.upper():
                    ll = line.lower()
                    for kw in SHIPMENTLINK_ETA_STATUSES:
                        if kw in ll:
                            m = DATE_RE.search(line)
                            if m:
                                eta = m.group(0)
                                eta_status_kw = kw
                                break
                if eta:
                    break

            # ── Pickup Date — popup scrape ────────────────────────────────────────
            pickup = None
            pickup_status_kw = None
            popup_eta = None
            popup_eta_kw = None
            try:
                cont_link = page.locator(f"a:has-text('{container_upper}')").first
                if cont_link.is_visible(timeout=3_000):
                    with page.expect_popup(timeout=15_000) as popup_info:
                        cont_link.click()
                    popup = popup_info.value
                    try:
                        popup.wait_for_load_state("domcontentloaded", timeout=15_000)
                        popup.wait_for_timeout(2_000)
                        popup_lines = [
                            l.strip()
                            for l in popup.inner_text("body").split("\n")
                            if l.strip()
                        ]
                        popup_matches = []
                        for line in popup_lines:
                            ll = line.lower()
                            for kw in SHIPMENTLINK_PICKUP_STATUSES:
                                if kw in ll:
                                    m = DATE_RE.search(line)
                                    if m:
                                        popup_matches.append((m.group(0), kw))
                                    break
                        if popup_matches:
                            pickup, pickup_status_kw = popup_matches[-1]
                        print(f"    Popup pickup: {pickup!r}  (kw={pickup_status_kw!r})")

                        popup_eta_matches = []
                        for line in popup_lines:
                            ll = line.lower()
                            for kw in SHIPMENTLINK_ETA_STATUSES:
                                if kw in ll:
                                    m = DATE_RE.search(line)
                                    if m:
                                        popup_eta_matches.append((m.group(0), kw))
                                    break
                        if popup_eta_matches:
                            popup_eta, popup_eta_kw = popup_eta_matches[-1]
                        print(f"    Popup ETA:    {popup_eta!r}  (kw={popup_eta_kw!r})")
                    finally:
                        popup.close()
                else:
                    print(f"    WARNING: container link not visible for {container_upper}")
            except Exception as exc:
                print(f"    WARNING: pickup popup scrape failed: {exc}")

            if eta is None and popup_eta is not None:
                eta = popup_eta
                eta_status_kw = popup_eta_kw

            # ── Return Date ───────────────────────────────────────────────────────
            return_date = None
            return_status_kw = None
            for line in lines:
                if container_upper in line.upper():
                    ll = line.lower()
                    for kw in SHIPMENTLINK_RETURN_STATUSES:
                        if kw in ll:
                            m = DATE_RE.search(line)
                            if m:
                                return_date = m.group(0)
                                return_status_kw = kw
                                break
                if return_date:
                    break

            # ── Rail transit detection ────────────────────────────────────────────
            rail_detected = False
            for line in lines:
                if container_upper in line.upper():
                    ll = line.lower()
                    if any(kw in ll for kw in SHIPMENTLINK_RAIL_STATUSES):
                        rail_detected = True
                        break

            # ── Status dropdown value ─────────────────────────────────────────────
            if return_status_kw:
                status = SHIPMENTLINK_STATUS_MAP.get(return_status_kw, "Returned to Port")
            elif pickup_status_kw:
                status = SHIPMENTLINK_STATUS_MAP.get(pickup_status_kw, "Released")
            elif rail_detected:
                status = "Rail"
            elif eta_status_kw:
                if eta_status_kw in SHIPMENTLINK_PRE_ARRIVAL_STATUSES:
                    status = "Vessel"
                else:
                    status = SHIPMENTLINK_STATUS_MAP.get(eta_status_kw, "Vessel Arrived")
            else:
                status = None

            return eta, pickup, return_date, status

        except PlaywrightTimeout as exc:
            print(f"    TIMEOUT: {exc}")
            if attempt < 2:
                print(f"    Retrying once more...")
            else:
                return None, None, None, None
        except Exception as exc:
            print(f"    ERROR: {exc}")
            return None, None, None, None
        finally:
            page.close()
            context.close()

    return None, None, None, None


# ─────────────────────────────────────────────
# Hapag-Lloyd scraper
# ─────────────────────────────────────────────

def run_hapag_lloyd(browser, url, bol, container):
    context = browser.new_context(user_agent=_SHIPMENTLINK_UA)
    page = context.new_page()
    _stealth.apply_stealth_sync(page)
    block_resources(page)
    try:
        direct_url = f"https://www.hapag-lloyd.com/en/online-business/track/track-by-booking-solution.html?blno={bol}"
        print(f"    Loading {direct_url}")
        page.goto(direct_url, wait_until="domcontentloaded", timeout=60_000)
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except PlaywrightTimeout:
            pass
        page.wait_for_timeout(4_000)
        title = page.title()
        print(f"    Page title: {title!r}")
        if "just a moment" in title.lower() or "attention required" in title.lower():
            print(f"    WARNING: Cloudflare challenge")
            return None, None, None, None
        _dismiss_dialogs(page)
        try:
            result_row = page.locator("table tbody tr:first-child").first
            if result_row.is_visible(timeout=5_000):
                result_row.click()
                page.wait_for_timeout(1_500)
        except Exception:
            pass
        try:
            details_btn = page.locator("button:has-text('Details'), a:has-text('Details')").first
            if details_btn.is_visible(timeout=5_000):
                details_btn.click()
                try:
                    page.wait_for_load_state("networkidle", timeout=15_000)
                except PlaywrightTimeout:
                    pass
                page.wait_for_timeout(3_000)
        except Exception:
            pass
        body_text = page.inner_text("body")
        lines = [l.strip() for l in body_text.split("\n") if l.strip()]
        eta = None
        discharged = None
        pickup = None
        ret = None
        for i, line in enumerate(lines):
            ll = line.lower()
            if "vessel arrival" in ll:
                ctx = " ".join(lines[i:i+3])
                m = DATE_RE.search(ctx)
                if m: eta = m.group(0)
            if "discharg" in ll:
                ctx = " ".join(lines[i:i+3])
                m = DATE_RE.search(ctx)
                if m: discharged = m.group(0)
            if any(kw in ll for kw in ["gate out","full out","merchant haulage","pick-up"]):
                ctx = " ".join(lines[i:i+3])
                m = DATE_RE.search(ctx)
                if m and not pickup: pickup = m.group(0)
            if any(kw in ll for kw in ["empty return","empty in","gate in empty"]):
                ctx = " ".join(lines[i:i+3])
                m = DATE_RE.search(ctx)
                if m and not ret: ret = m.group(0)
        final_eta = discharged or eta
        if ret: status = "Returned to Port"
        elif pickup: status = "Released"
        elif discharged: status = "Discharged"
        elif final_eta: status = "Vessel"
        else: status = None
        print(f"    Hapag result: eta={final_eta!r} pickup={pickup!r} ret={ret!r} status={status!r}")
        return final_eta, pickup, ret, status
    except PlaywrightTimeout as exc:
        print(f"    TIMEOUT: {exc}")
        return None, None, None, None
    except Exception as exc:
        print(f"    ERROR: {exc}")
        return None, None, None, None
    finally:
        page.close()
        context.close()

def run_one_line(browser, url, bol, container):
    context = browser.new_context(user_agent=_SHIPMENTLINK_UA)
    page = context.new_page()
    _stealth.apply_stealth_sync(page)
    block_resources(page)
    try:
        print(f"    Loading {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=60_000)
        blocked = detect_bot_block(page)
        if blocked:
            print(f"    BLOCKED ({blocked}) — skipping")
            return None, None, None, None
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except PlaywrightTimeout:
            pass
        page.wait_for_timeout(3_000)
        _dismiss_dialogs(page)
        try:
            bl_tab = page.locator("button:has-text('BL'), button:has-text('B/L'), button:has-text('Booking')").first
            if bl_tab.is_visible(timeout=5_000):
                bl_tab.click()
                page.wait_for_timeout(1_000)
        except Exception:
            pass
        _ONE_SEL = ("input[data-testid='tnt-search-multiple-placeholder'], "
                    "input[placeholder*='BL No' i], input[placeholder*='B/L' i]")
        try:
            page.wait_for_selector(_ONE_SEL, timeout=20_000)
        except PlaywrightTimeout:
            print(f"    WARNING: ONE Line form did not render in time")
            return None, None, None, None
        print(f"    Page title: {page.title()!r}")
        input_loc = page.locator(_ONE_SEL).first
        # ONE Line wants the last 12 chars only, no 'ONEY' prefix
        one_bol = bol.upper().replace('ONEY', '').strip()[-12:]
        print(f"    ONE BOL submitted: {one_bol!r}")
        input_loc.fill(one_bol)
        input_loc.press("Enter")
        try:
            page.wait_for_load_state("networkidle", timeout=20_000)
        except PlaywrightTimeout:
            pass
        page.wait_for_timeout(4_000)
        try:
            result_row = page.locator("table tbody tr:first-child").first
            if result_row.is_visible(timeout=5_000):
                result_row.click()
                try:
                    page.wait_for_load_state("networkidle", timeout=15_000)
                except PlaywrightTimeout:
                    pass
                page.wait_for_timeout(3_000)
        except Exception:
            pass
        body_text = page.inner_text("body")
        lines = [l.strip() for l in body_text.split("\n") if l.strip()]
        eta = None
        pickup = None
        ret = None
        for i, line in enumerate(lines):
            ll = line.lower()
            if any(kw in ll for kw in ["vessel arrival","eta","estimated arrival","ata","discharg"]):
                ctx = " ".join(lines[i:i+3])
                m = DATE_RE.search(ctx)
                if m and not eta: eta = m.group(0)
            if any(kw in ll for kw in ["gate out","full out","merchant haulage","pick-up","available"]):
                ctx = " ".join(lines[i:i+3])
                m = DATE_RE.search(ctx)
                if m and not pickup: pickup = m.group(0)
            if any(kw in ll for kw in ["empty return","empty in","gate in empty","empty container"]):
                ctx = " ".join(lines[i:i+3])
                m = DATE_RE.search(ctx)
                if m and not ret: ret = m.group(0)
        if ret: status = "Returned to Port"
        elif pickup: status = "Released"
        elif eta: status = "Vessel"
        else: status = None
        print(f"    ONE result: eta={eta!r} pickup={pickup!r} ret={ret!r} status={status!r}")
        return eta, pickup, ret, status
    except PlaywrightTimeout as exc:
        print(f"    TIMEOUT: {exc}")
        return None, None, None, None
    except Exception as exc:
        print(f"    ERROR: {exc}")
        return None, None, None, None
    finally:
        page.close()
        context.close()



# ─────────────────────────────────────────────
# SM Line-specific scraper
# ─────────────────────────────────────────────

_SMLINE_EXTRACT_JS = """() => {
    const result = {sailing_eta: null, sailing_eta_actual: false, tracking: [], lfd: null};

    // ── Sailing Information table ──
    const allTables = document.querySelectorAll('table');
    for (const table of allTables) {
        const hdr = Array.from(table.querySelectorAll('th')).map(h => h.textContent.trim()).join(' ');
        if (hdr.includes('Vessel') && hdr.includes('Arrival Time')) {
            const rows = table.querySelectorAll('tbody tr');
            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length >= 5) {
                    const arrCell = cells[cells.length - 1];
                    const dateMatch = arrCell.textContent.match(/(\d{4}-\d{2}-\d{2})/);
                    const imgs = arrCell.querySelectorAll('img');
                    const isActual = Array.from(imgs).some(i =>
                        i.src.includes('icon-a') && !i.src.includes('grey'));
                    if (dateMatch) {
                        result.sailing_eta = dateMatch[1];
                        result.sailing_eta_actual = isActual;
                    }
                }
            }
        }

        // ── Cargo Tracking Details table ──
        if (hdr.includes('No') && hdr.includes('Status') && hdr.includes('Event Date')) {
            const rows = table.querySelectorAll('tbody tr');
            for (const row of rows) {
                const cells = row.querySelectorAll('td');
                if (cells.length >= 4) {
                    const dateCell = cells[cells.length - 1];
                    const imgs = dateCell.querySelectorAll('img');
                    const isActual = Array.from(imgs).some(i =>
                        i.src.includes('icon-a') && !i.src.includes('grey'));
                    const statusText = cells[1].textContent.trim();
                    const dateMatch = dateCell.textContent.match(/(\d{4}-\d{2}-\d{2})/);
                    if (statusText && dateMatch) {
                        result.tracking.push({
                            status: statusText.toLowerCase(),
                            date: dateMatch[1],
                            actual: isActual
                        });
                    }
                }
            }
        }
    }

    // ── Last Free Date ──
    const body = document.body.textContent;
    const lfdMatch = body.match(/Last Free Date[^]*?(\d{4}-\d{2}-\d{2})/);
    if (lfdMatch) result.lfd = lfdMatch[1];

    return result;
}"""


def _parse_smline_detail(page):
    """Extract ETA, pickup, return date, and status from SM Line detail page.

    Uses DOM icon inspection to distinguish actual events (icon-a.gif)
    from estimated/scheduled events (icon_e_grey.gif).  Only ACTUAL events
    are used for pickup and return dates.  ETA uses the sailing arrival
    regardless of actual/estimated (it's useful either way).
    """
    try:
        data = page.evaluate(_SMLINE_EXTRACT_JS)
    except Exception as exc:
        print(f"    SM Line DOM extraction failed: {exc}")
        return None, None, None, None

    eta = data.get("sailing_eta")
    eta_actual = data.get("sailing_eta_actual", False)
    lfd = data.get("lfd")
    pickup = None
    ret = None

    # Walk tracking events — only use ACTUAL events for pickup/return
    latest_actual_status = None
    for evt in data.get("tracking", []):
        s = evt["status"]
        if not evt["actual"]:
            continue  # skip estimated events
        latest_actual_status = s
        if ("gate out" in s or "shuttled to odcy" in s or
                "delivery to consignee" in s):
            if not pickup:
                pickup = evt["date"]
        if "empty container returned" in s or "empty return" in s:
            if not ret:
                ret = evt["date"]

    # LFD as pickup fallback — only when no actual gate-out event
    if lfd and not pickup:
        pickup = lfd

    # Determine status from latest ACTUAL event
    if ret:
        status = "Returned to Port"
    elif pickup:
        status = "Released"
    elif latest_actual_status:
        if "unloaded" in latest_actual_status and "discharging" in latest_actual_status:
            status = "Released"
        elif "arrival at port of discharging" in latest_actual_status:
            status = "Vessel"
        elif "departure" in latest_actual_status:
            status = "Vessel"
        elif "loaded on" in latest_actual_status:
            status = "Vessel"
        else:
            status = "Vessel" if eta else None
    elif eta:
        status = "Vessel"
    else:
        status = None

    return eta, pickup, ret, status


def run_sm_line(browser, url, bol, container):
    """SM Line scraper: search by container first, fall back to BL + click-through."""
    page = browser.new_page()
    _stealth.apply_stealth_sync(page)
    try:
        print(f"    Loading {url}")
        page.goto(url, wait_until="domcontentloaded", timeout=30_000)
        blocked = detect_bot_block(page)
        if blocked:
            print(f"    BLOCKED ({blocked}) — skipping")
            return None, None, None, None
        page.wait_for_timeout(2_000)

        # ── Search by container number first ────────────────────────
        print(f"    SM Line: searching by container {container}")
        try:
            page.select_option("#searchType", "C")
            page.wait_for_timeout(300)
            page.fill("#searchName", container)
            page.wait_for_timeout(300)
            page.click("#btnSearch")
            page.wait_for_timeout(4_000)
        except Exception as exc:
            print(f"    SM Line form interaction failed: {exc}")
            return None, None, None, None

        body = page.inner_text("body")
        if container.upper() in body.upper() and "Sailing Information" in body:
            eta, pickup, ret, status = _parse_smline_detail(page)
            if eta or pickup or ret or status:
                return eta, pickup, ret, status

        # ── Container search returned list or nothing — try BL ──────
        if bol and bol.strip() != container.strip():
            print(f"    SM Line: container search insufficient, trying BL {bol}")
            page.goto(url, wait_until="domcontentloaded", timeout=30_000)
            page.wait_for_timeout(2_000)
            try:
                page.select_option("#searchType", "B")
                page.wait_for_timeout(300)
                page.fill("#searchName", bol)
                page.wait_for_timeout(300)
                page.click("#btnSearch")
                page.wait_for_timeout(4_000)
            except Exception as exc:
                print(f"    SM Line BL form failed: {exc}")
                return None, None, None, None

            try:
                cntr_link = page.locator(f"a:has-text('{container}')").first
                if cntr_link.is_visible(timeout=3_000):
                    cntr_link.click()
                    page.wait_for_timeout(4_000)
                    return _parse_smline_detail(page)
            except Exception:
                pass

        return None, None, None, None
    except PlaywrightTimeout as exc:
        print(f"    TIMEOUT: {exc}")
        return None, None, None, None
    except Exception as exc:
        print(f"    ERROR: {exc}")
        return None, None, None, None
    finally:
        page.close()

def dray_import_workflow(browser, ws, sheet_row, url, bol, container,
                          circuit_breaker=None, vessel="", carrier_name="",
                          pending_updates=None, proxy_ok=True, ssl_code=None,
                          existing_row=None):
    print(f"\n  [Dray Import] row {sheet_row} — Container: {container}  BOL: {bol}")
    url_lower = url.lower() if url else ""

    # Extract carrier domain for circuit breaker
    carrier_domain = ""
    try:
        carrier_domain = urlparse(url).netloc.replace("www.", "")
    except Exception:
        pass

    # Determine if this carrier uses a fast API route (no circuit breaker needed)
    api_route = any(d in url_lower for d in ("maersk.com", "hmm21.com", "hapag-lloyd.com", "shipmentlink.com", "apl.com", "cma-cgm.com", "one-line.com"))

    # Circuit breaker check — only for browser scrapers (API calls are <1s, no benefit)
    if circuit_breaker and carrier_domain and not api_route and circuit_breaker.should_skip(carrier_domain):
        print(f"    CIRCUIT BREAKER: skipping {carrier_domain} (too many failures)")
        return None, None, None, None

    # Route via ssl_code (from SSL Links tab) when available
    if ssl_code:
        print(f"    Using SSL Links lookup (ssl_code={ssl_code})")
        eta, pickup, ret, status = _jsoncargo_container_track(container, ssl_code)
        if status == "_fallback":
            if proxy_ok and url:
                print("    API prefix not found - falling back to browser scraper")
                # Route browser scraper based on ssl_code
                if ssl_code == "EVERGREEN":
                    eta, pickup, ret, status = run_shipmentlink(browser, url, bol, container)
                elif ssl_code == "HAPAG_LLOYD":
                    eta, pickup, ret, status = run_hapag_lloyd(browser, url, bol, container)
                elif ssl_code == "ONE":
                    eta, pickup, ret, status = run_one_line(browser, url, bol, container)
                elif ssl_code == "SM_LINE":
                    eta, pickup, ret, status = run_sm_line(browser, url, bol, container)
                else:
                    eta, pickup, ret, status = run_dray_import(browser, url, bol)
                api_route = False
            else:
                print("    API prefix not found + no fallback available - skipping")
                eta, pickup, ret, status = None, None, None, None
    # Route to carrier-specific scraper or API (legacy hyperlink-based routing)
    elif "maersk.com" in url_lower:
        ssl = "MAERSK"
        print(f"    Using Container API (ssl_line={ssl})")
        eta, pickup, ret, status = _jsoncargo_container_track(container, ssl)
        if status == "_fallback":
            if proxy_ok:
                print("    API prefix not found - falling back to browser scraper")
                eta, pickup, ret, status = run_dray_import(browser, url, bol)
                api_route = False  # enable circuit breaker for browser fallback
            else:
                print("    API prefix not found + proxy down - skipping")
                eta, pickup, ret, status = None, None, None, None
    elif "hmm21.com" in url_lower:
        ssl = "HMM"
        print(f"    Using Container API (ssl_line={ssl})")
        eta, pickup, ret, status = _jsoncargo_container_track(container, ssl)
        if status == "_fallback":
            if proxy_ok:
                print("    API prefix not found - falling back to browser scraper")
                eta, pickup, ret, status = run_dray_import(browser, url, bol)
                api_route = False
            else:
                print("    API prefix not found + proxy down - skipping")
                eta, pickup, ret, status = None, None, None, None
    elif "apl.com" in url_lower:
        ssl = "CMA_CGM"
        print(f"    Using JsonCargo API (ssl_line={ssl}) [APL/CMA CGM]")
        eta, pickup, ret, status = _jsoncargo_container_track(container, ssl)
        if status == "_fallback":
            if proxy_ok:
                print("    API prefix not found - falling back to browser scraper")
                eta, pickup, ret, status = run_dray_import(browser, url, bol)
                api_route = False
            else:
                print("    API prefix not found + proxy down - skipping")
                eta, pickup, ret, status = None, None, None, None
    elif not proxy_ok:
        # Proxy is down - skip all browser-based scrapers
        print("    SKIPPED (proxy down - browser scraping unavailable)")
        eta, pickup, ret, status = None, None, None, None
    elif "shipmentlink.com" in url_lower:
        ssl = "EVERGREEN"
        print(f"    Using Container API (ssl_line={ssl})")
        eta, pickup, ret, status = _jsoncargo_container_track(container, ssl)
        if status == "_fallback":
            if proxy_ok:
                print("    API prefix not found - falling back to browser scraper")
                eta, pickup, ret, status = run_shipmentlink(browser, url, bol, container)
                api_route = False
            else:
                print("    API prefix not found + proxy down - skipping")
                eta, pickup, ret, status = None, None, None, None
    elif "hapag-lloyd.com" in url_lower:
        ssl = "HAPAG_LLOYD"
        print(f"    Using Container API (ssl_line={ssl})")
        eta, pickup, ret, status = _jsoncargo_container_track(container, ssl)
        if status == "_fallback":
            if proxy_ok:
                print("    API prefix not found - falling back to browser scraper")
                eta, pickup, ret, status = run_hapag_lloyd(browser, url, bol, container)
                api_route = False
            else:
                print("    API prefix not found + proxy down - skipping")
                eta, pickup, ret, status = None, None, None, None
    elif "one-line.com" in url_lower:
        ssl = "ONE"
        print(f"    Using Container API (ssl_line={ssl})")
        eta, pickup, ret, status = _jsoncargo_container_track(container, ssl)
        if status == "_fallback":
            if proxy_ok:
                print("    API prefix not found - falling back to browser scraper")
                eta, pickup, ret, status = run_one_line(browser, url, bol, container)
                api_route = False
            else:
                print("    API prefix not found + proxy down - skipping")
                eta, pickup, ret, status = None, None, None, None
    elif "cma-cgm.com" in url_lower:
        ssl = "CMA_CGM"
        print(f"    Using Container API (ssl_line={ssl})")
        eta, pickup, ret, status = _jsoncargo_container_track(container, ssl)
        if status == "_fallback":
            if proxy_ok:
                print("    API prefix not found - falling back to browser scraper")
                eta, pickup, ret, status = run_dray_import(browser, url, bol)
                api_route = False
            else:
                print("    API prefix not found + proxy down - skipping")
                eta, pickup, ret, status = None, None, None, None
    else:
        eta, pickup, ret, status = run_dray_import(browser, url, bol)

    # Track circuit breaker (browser scrapers only — API routes and proxy-down skips excluded)
    if circuit_breaker and carrier_domain and not api_route and proxy_ok:
        if eta or pickup or ret or status:
            circuit_breaker.record_success(carrier_domain)
        else:
            circuit_breaker.record_failure(carrier_domain)

    # Fallback: if browser scraper returned nothing with BOL, retry with container number
    if not (eta or pickup or ret or status) and container and bol and container.strip() != bol.strip() and proxy_ok and url:
        print(f"    BOL search returned nothing — retrying with container: {container}")
        url_lower_fb = url.lower() if url else ""
        if "shipmentlink.com" in url_lower_fb:
            eta, pickup, ret, status = run_shipmentlink(browser, url, container, container)
        elif "hapag-lloyd.com" in url_lower_fb:
            eta, pickup, ret, status = run_hapag_lloyd(browser, url, container, container)
        elif "one-line.com" in url_lower_fb:
            eta, pickup, ret, status = run_one_line(browser, url, container, container)
        elif "smlines.com" in url_lower_fb:
            eta, pickup, ret, status = run_sm_line(browser, url, container, container)
        elif not any(d in url_lower_fb for d in ("maersk.com", "hmm21.com", "cma-cgm.com", "apl.com")):
            eta, pickup, ret, status = run_dray_import(browser, url, container)
        if eta or pickup or ret or status:
            print(f"    Container search found results!")

    # Don't report pickup/LFD if it's the same as ETA (not a real LFD)
    if pickup and eta and pickup == eta:
        pickup = None

    print(f"    ETA={eta!r}  Pickup={pickup!r}  Return={ret!r}  Status={status!r}")

    # Collect updates for batching or write immediately
    if pending_updates is not None:
        ts = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
        # Guard: don't overwrite manually-entered dates (ETA/Pickup/Return)
        ex_eta    = (existing_row[COL_ETA - 1].strip()    if existing_row and len(existing_row) > COL_ETA - 1    else "")
        ex_pickup = (existing_row[COL_PICKUP - 1].strip() if existing_row and len(existing_row) > COL_PICKUP - 1 else "")
        ex_return = (existing_row[COL_RETURN - 1].strip() if existing_row and len(existing_row) > COL_RETURN - 1 else "")
        if eta and not ex_eta:
            pending_updates.append({"range": f"{col_letter(COL_ETA)}{sheet_row}", "values": [[eta]]})
        elif eta and ex_eta:
            print(f"    I{sheet_row} already has {ex_eta!r} — not overwriting with {eta!r}")
        if pickup and not ex_pickup:
            pending_updates.append({"range": f"{col_letter(COL_PICKUP)}{sheet_row}", "values": [[pickup]]})
        elif pickup and ex_pickup:
            print(f"    K{sheet_row} already has {ex_pickup!r} — not overwriting with {pickup!r}")
        if ret and not ex_return:
            pending_updates.append({"range": f"{col_letter(COL_RETURN)}{sheet_row}", "values": [[ret]]})
        elif ret and ex_return:
            print(f"    P{sheet_row} already has {ex_return!r} — not overwriting with {ret!r}")
        if status:
            ex_status = (existing_row[COL_STATUS - 1].strip() if existing_row and len(existing_row) > COL_STATUS - 1 else '')
            if ex_status in BOT_MANAGED_STATUSES:
                pending_updates.append({"range": f"{col_letter(COL_STATUS)}{sheet_row}", "values": [[status]]})
            else:
                print(f'    M{sheet_row} has manual status {ex_status!r} -- not overwriting with {status!r}')
        pending_updates.append({"range": f"{col_letter(COL_TIMESTAMP)}{sheet_row}", "values": [[ts]]})
    else:
        write_tracking_results(ws, sheet_row, eta, pickup, ret, status)

    return eta, pickup, ret, status


# ─────────────────────────────────────────────
# State persistence
# ─────────────────────────────────────────────

def load_last_check():
    """Return the previously saved state dict, keyed by tab:container."""
    if os.path.exists(LAST_CHECK_FILE):
        try:
            with open(LAST_CHECK_FILE) as f:
                return json.load(f)
        except Exception as exc:
            print(f"  WARNING: Could not read {LAST_CHECK_FILE}: {exc}")
    return {}


def save_last_check(data):
    """Persist the current state dict to disk (atomic write)."""
    try:
        import shutil
        if os.path.exists(LAST_CHECK_FILE):
            shutil.copy2(LAST_CHECK_FILE, LAST_CHECK_FILE + ".bak")
        tmp = LAST_CHECK_FILE + ".tmp"
        with open(tmp, "w") as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, LAST_CHECK_FILE)
    except Exception as exc:
        print(f"  WARNING: Could not save {LAST_CHECK_FILE}: {exc}")


# ─────────────────────────────────────────────
# Account lookup + tab discovery
# ─────────────────────────────────────────────

def load_account_lookup(sheet):
    """Read 'Account Rep' tab → dict mapping account_name → {rep, email}."""
    try:
        ws   = sheet.worksheet(ACCOUNT_LOOKUP_TAB)
        rows = ws.get_all_values()
        lookup = {}
        for row in rows:
            if len(row) >= 3 and row[0].strip():
                account = row[0].strip()
                rep     = row[1].strip()
                email   = row[2].strip()
                if account and email:
                    lookup[account] = {"rep": rep, "email": email}
        print(f"  Loaded {len(lookup)} account(s) from '{ACCOUNT_LOOKUP_TAB}'")
        return lookup
    except Exception as exc:
        print(f"  WARNING: Could not load '{ACCOUNT_LOOKUP_TAB}' tab: {exc}")
        return {}




SSL_LINKS_TAB = "SSL Links"

def load_ssl_links(sheet):
    """Read 'SSL Links' tab -> dict mapping lowercase ssl name -> {url, code}."""
    try:
        ws = sheet.worksheet(SSL_LINKS_TAB)
        rows = ws.get_all_values()
        lookup = {}
        for row in rows[1:]:  # skip header
            if len(row) >= 3 and row[0].strip():
                ssl_name = row[0].strip()
                url = row[1].strip()
                code = row[2].strip()
                if ssl_name and (url or code):
                    lookup[ssl_name.lower()] = {"url": url, "code": code}
        print(f"  Loaded {len(lookup)} SSL link(s) from '{SSL_LINKS_TAB}'")
        return lookup
    except Exception as exc:
        print(f"  WARNING: Could not load '{SSL_LINKS_TAB}' tab: {exc}")
        return {}


def resolve_ssl_from_column_f(col_f_value, ssl_links):
    """Match Column F value to an SSL Links entry using keyword matching.
    Returns {url, code} or None."""
    if not col_f_value or not ssl_links:
        return None
    val = col_f_value.strip().lower()
    if not val:
        return None
    # Try exact match first
    if val in ssl_links:
        return ssl_links[val]
    # Try keyword: check if any SSL key is contained in the Column F value
    for ssl_key, info in ssl_links.items():
        if ssl_key in val or val in ssl_key:
            return info
    # Try partial word matching (e.g. "hapag" matches "hapag-lloyd")
    for ssl_key, info in ssl_links.items():
        key_words = ssl_key.replace("-", " ").split()
        for word in key_words:
            if len(word) >= 3 and word in val:
                return info
    return None

def get_account_tabs(sheet, account_lookup):
    """Return tab titles that are in account_lookup and not in SKIP_TABS."""
    all_tabs = [ws.title for ws in sheet.worksheets()]
    tabs = [t for t in all_tabs if t not in SKIP_TABS and t in account_lookup]
    print(f"  Account tabs to process: {tabs}")
    return tabs


# ─────────────────────────────────────────────
# Email notification
# ─────────────────────────────────────────────

# ── EFJ Pro alert ───────────────────────────────────────────────────────────────
def send_pro_alert(row, tab_name, account_lookup):
    """Email rep daily when a row has no EFJ# pro number."""
    info      = account_lookup.get(tab_name, {})
    rep_email = info.get("email", "")
    rep_name  = info.get("rep", "")
    to_email  = rep_email if rep_email else EMAIL_FALLBACK
    cc_email  = EMAIL_CC if rep_email else None
    headers   = ["EFJ#","Move Type","Container/Load#","BOL/Booking#","SSL/Vessel",
                 "Carrier","Origin","Destination","ETA/ERD","LFD/Cutoff",
                 "Pickup Date","Delivery Date","Status","Driver/Truck","Notes"]
    detail_rows = ""
    for i, val in enumerate(row):
        if val and str(val).strip():
            label = headers[i] if i < len(headers) else f"Col {i+1}"
            detail_rows += (f'<tr><td style="padding:4px 10px;color:#555;font-size:13px;">{label}</td>'
                           f'<td style="padding:4px 10px;font-size:13px;">{str(val).strip()}</td></tr>')
    container = str(row[2]).strip() if len(row) > 2 and row[2] else "Unknown"
    vessel    = str(row[4]).strip() if len(row) > 4 and row[4] else "Unknown"
    origin    = str(row[6]).strip() if len(row) > 6 and row[6] else ""
    dest      = str(row[7]).strip() if len(row) > 7 and row[7] else ""
    extra     = " | ".join(filter(None, [container, vessel, origin, dest]))
    subject   = f"Please Pro Load ASAP: Load Needs EFJ Pro - {extra}"
    rep_line  = f" &mdash; Rep: {rep_name}" if rep_name else ""
    body      = (
        f'<div style="font-family:Arial,sans-serif;max-width:700px;">'
        f'<div style="background:#e65100;color:white;padding:10px 14px;border-radius:6px 6px 0 0;font-size:15px;">'
        f'<b>Please Pro Load ASAP</b></div>'
        f'<div style="border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;padding:12px;">'
        f'<p style="margin:0 0 8px 0;font-size:13px;color:#555;">Account: <b>{tab_name}</b>{rep_line}</p>'
        f'<table style="border-collapse:collapse;width:100%;">{detail_rows}</table>'
        f'</div></div>'
    )
    _send_email(to_email, cc_email, subject, body)

def _send_email(to_email, cc_email, subject, body):
    """Send a plain-text email via Office 365 SMTP/STARTTLS."""
    msg = MIMEMultipart("alternative")
    msg["Subject"] = subject
    msg["From"]    = SMTP_USER
    msg["To"]      = to_email
    if cc_email and cc_email != to_email:
        msg["Cc"] = cc_email
    msg.attach(MIMEText(body, "html"))

    recipients = [to_email]
    if cc_email and cc_email != to_email:
        recipients.append(cc_email)

    try:
        with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as smtp:
            smtp.ehlo()
            smtp.starttls()
            smtp.login(SMTP_USER, SMTP_PASSWORD)
            smtp.sendmail(SMTP_USER, recipients, msg.as_string())
        print(f"  Email sent → {to_email}  (cc: {cc_email or 'none'})")
    except Exception as exc:
        print(f"  WARNING: Email failed: {exc}")


def send_account_notification(account_name, account_lookup, changes):
    """Route a change-alert email to the rep assigned to this account tab."""
    if not changes:
        return

    info      = account_lookup.get(account_name, {})
    rep_email = info.get("email", "")
    rep_name  = info.get("rep",   "")

    if rep_email:
        to_email = rep_email
        cc_email = EMAIL_CC
    else:
        to_email = EMAIL_FALLBACK
        cc_email = None

    now     = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    subject = f"{account_name} Container Update — {now}"
    th = 'style="padding:6px 10px;text-align:left;border-bottom:1px solid #ddd;color:white;font-size:13px;"'
    td = 'style="padding:6px 10px;border-bottom:1px solid #eee;font-size:13px;"'
    hdr_color = "#1565c0"
    hdrs = ["Container", "ETA", "LFD", "Status", "Return", "Changed"]
    hdr_cells = "".join(f'<th {th}>{h}</th>' for h in hdrs)
    rows_html = ""
    for i, c in enumerate(changes):
        alt = ' style="background:#f9f9f9;"' if i % 2 == 1 else ''
        field_str = ", ".join(c.get("changed_fields", []))
        rows_html += (f'<tr{alt}>'
                     f'<td {td}><b>{c.get("container") or "N/A"}</b></td>'
                     f'<td {td}>{c.get("eta") or "—"}</td>'
                     f'<td {td}>{c.get("lfd") or "—"}</td>'
                     f'<td {td}>{c.get("status") or "—"}</td>'
                     f'<td {td}>{c.get("return_date") or "—"}</td>'
                     f'<td {td}>{field_str}</td>'
                     f'</tr>')
    rep_line = f'<br>Rep: {rep_name}' if rep_name else ''
    body = (f'<div style="font-family:Arial,sans-serif;max-width:900px;">'
            f'<h2 style="margin:0 0 4px 0;color:#333;">{account_name} Container Update</h2>'
            f'<p style="color:#888;font-size:12px;margin:0 0 4px 0;">{now} &mdash; {len(changes)} Container(s){rep_line}</p>'
            f'<div style="background:{hdr_color};color:white;padding:8px 14px;'
            f'border-radius:6px 6px 0 0;font-size:15px;margin-top:12px;">'
            f'<b>Container Updates ({len(changes)})</b></div>'
            f'<table style="border-collapse:collapse;width:100%;border:1px solid #ddd;border-top:none;">'
            f'<tr style="background:{hdr_color};">{hdr_cells}</tr>'
            f'{rows_html}</table></div>')
    _send_email(to_email, cc_email, subject, body)


# ─────────────────────────────────────────────
# Archive helpers
# ─────────────────────────────────────────────

def _completed_tab_for(account_name, account_lookup):
    """Return 'Completed Eli', 'Completed Radka', or None based on rep name."""
    rep_name = account_lookup.get(account_name, {}).get("rep", "")
    rl = rep_name.lower()
    if "eli" in rl:
        return "Completed Eli"
    if "radka" in rl:
        return "Completed Radka"
    if "john" in rl:
        return "Completed John F"
    return None


def archive_completed_row(sheet, tab_name, sheet_row, row_data, url, eta, pickup,
                          return_date, status, account_lookup):
    """
    Copy the row to the rep's Completed tab, then delete it from the account tab.
    Performs a duplicate EFJ# check before appending.
    Sends an archive email to the rep, or writes a note to Col O if no email found.
    Returns True on full success, False on any failure or skip.
    """
    rep_info  = account_lookup.get(tab_name, {})
    rep_name  = rep_info.get("rep", "unknown")
    rep_email = rep_info.get("email", "")
    dest_tab  = _completed_tab_for(tab_name, account_lookup)
    efj_num   = (row_data[0].strip() if row_data else "") or ""
    container = (row_data[2].strip() if len(row_data) > 2 else "") or ""

    # ── No completed tab — write note to Col O on source tab, bail ───────────
    if not dest_tab:
        note = f"No completed tab for rep '{rep_name}' — manual archive needed"
        print(f"  WARNING: {note} (account '{tab_name}', row {sheet_row})")
        try:
            src_ws = sheet.worksheet(tab_name)
            src_ws.update_cell(sheet_row, COL_TIMESTAMP, note)
        except Exception as exc:
            print(f"  WARNING: Could not write fallback note to Col O: {exc}")
        return False

    try:
        dest_ws = sheet.worksheet(dest_tab)
    except Exception as exc:
        print(f"  WARNING: Could not open '{dest_tab}': {exc}")
        return False

    # ── Duplicate check — skip if EFJ# already in completed tab ──────────────
    if efj_num:
        try:
            existing_efjs = dest_ws.col_values(1)  # Col A
            if efj_num in existing_efjs:
                dup_note = (f"WARNING: EFJ# {efj_num} already in '{dest_tab}' "
                            f"— archive skipped")
                print(f"  {dup_note}")
                try:
                    src_ws = sheet.worksheet(tab_name)
                    src_ws.update_cell(sheet_row, COL_TIMESTAMP, dup_note)
                except Exception:
                    pass
                return False
        except Exception as exc:
            print(f"  WARNING: Duplicate EFJ# check failed: {exc}")

    # ── Build archive row — patch tracking columns with current values ────────
    timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    row = list(row_data)
    max_col = max(COL_ETA, COL_PICKUP, COL_RETURN, COL_STATUS, COL_TIMESTAMP)
    while len(row) < max_col:
        row.append("")
    row[COL_ETA - 1]    = eta         or ""
    row[COL_PICKUP - 1] = pickup      or ""
    row[COL_RETURN - 1] = return_date or ""
    row[COL_STATUS - 1] = status      or ""
    # Col O: timestamp if we have an email to send, fallback note otherwise
    if rep_email:
        row[COL_TIMESTAMP - 1] = timestamp
    else:
        row[COL_TIMESTAMP - 1] = "No rep email found — alert not sent"

    # Reconstruct Col C as =HYPERLINK formula so the link is preserved
    if url and len(row) > 2:
        display      = row[2] or ""
        safe_url     = url.replace('"', '%22')
        safe_display = display.replace('"', "'")
        row[2] = f'=HYPERLINK("{safe_url}","{safe_display}")'

    # ── Append to completed tab ───────────────────────────────────────────────
    try:
        dest_ws.append_row(row, value_input_option="USER_ENTERED")
        pg_archive_shipment(efj_num)
        print(f"  Archived row {sheet_row} → '{dest_tab}'")
    except Exception as exc:
        print(f"  WARNING: Archive append failed for row {sheet_row}: {exc}")
        return False

    # ── Send archive email ────────────────────────────────────────────────────
    if rep_email:
        subject = f"CSL Archived | {efj_num} | {container} | Returned to Port"
        _td = 'style="padding:4px 10px;font-size:13px;"'
        _tl = 'style="padding:4px 10px;color:#555;font-size:13px;"'
        body = (
            f'<div style="font-family:Arial,sans-serif;max-width:700px;">'
            f'<div style="background:#1b5e20;color:white;padding:10px 14px;border-radius:6px 6px 0 0;font-size:15px;">'
            f'<b>Container Archived &mdash; Returned to Port</b></div>'
            f'<div style="border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;padding:12px;">'
            f'<p style="margin:0 0 8px 0;font-size:12px;color:#888;">Archived: {timestamp}</p>'
            f'<table style="border-collapse:collapse;">'
            f'<tr><td {_tl}>EFJ#</td><td {_td}><b>{efj_num}</b></td></tr>'
            f'<tr><td {_tl}>Container</td><td {_td}><b>{container}</b></td></tr>'
            f'<tr><td {_tl}>Account</td><td {_td}>{tab_name}</td></tr>'
            f'<tr><td {_tl}>Rep</td><td {_td}>{rep_name}</td></tr>'
            f'<tr><td {_tl}>ETA</td><td {_td}>{eta or "—"}</td></tr>'
            f'<tr><td {_tl}>Pickup</td><td {_td}>{pickup or "—"}</td></tr>'
            f'<tr><td {_tl}>Returned</td><td {_td}>{return_date or "—"}</td></tr>'
            f'<tr><td {_tl}>Status</td><td {_td}>{status}</td></tr>'
            f'</table></div></div>'
        )
        _send_email(rep_email, EMAIL_CC, subject, body)

    # ── Delete from source tab ────────────────────────────────────────────────
    try:
        src_ws = sheet.worksheet(tab_name)
        src_ws.delete_rows(sheet_row)
        print(f"  Deleted row {sheet_row} from '{tab_name}'")
    except Exception as exc:
        print(f"  WARNING: Delete failed for row {sheet_row} in '{tab_name}': {exc}")
        return False

    return True


# ─────────────────────────────────────────────
# Main
# ─────────────────────────────────────────────

def run_once(args):
    from zoneinfo import ZoneInfo as _ZI
    from collections import defaultdict
    now_str = _time.strftime("%Y-%m-%d %H:%M ET", _time.localtime())
    print(f"\n[{now_str}] Dray Import cycle (Postgres mode)...")

    # ── Read active dray import loads from Postgres ──────────────────────────
    try:
        conn = _pg_connect()
        with conn.cursor(cursor_factory=psycopg2.extras.RealDictCursor) as cur:
            cur.execute("""
                SELECT efj, container, bol, vessel, carrier, origin, destination,
                       CAST(eta AS TEXT) AS eta, CAST(lfd AS TEXT) AS lfd,
                       CAST(pickup_date AS TEXT) AS pickup_date,
                       CAST(delivery_date AS TEXT) AS delivery_date,
                       status, bot_notes,
                       CAST(return_date AS TEXT) AS return_date,
                       account, rep
                FROM shipments
                WHERE move_type = 'Dray Import' AND archived = FALSE
                ORDER BY account, efj
            """)
            all_loads = cur.fetchall()
        conn.close()
    except Exception as exc:
        print(f"FATAL: Could not read from Postgres: {exc}")
        return

    # Group by account
    by_account = defaultdict(list)
    for row in all_loads:
        acct = row["account"] or "Unknown"
        by_account[acct].append(row)

    account_tabs = sorted(by_account.keys())
    print(f"  Loaded {len(all_loads)} active Dray Import load(s) across {len(account_tabs)} account(s)")
    print(f"  Accounts: {account_tabs}")

    if args.tab:
        if args.tab in by_account:
            account_tabs = [args.tab]
        else:
            print(f"Tab '{args.tab}' not found. Available: {account_tabs}")
            return

    if not account_tabs:
        print("No active Dray Import loads found.")
        return

    last_check = load_last_check()
    new_check  = {}

    with sync_playwright() as pw:
        browser = pw.chromium.launch(
            headless=True,
            proxy={
                "server":   os.environ["PROXY_SERVER"],
                "username": os.environ["PROXY_USERNAME"],
                "password": os.environ["PROXY_PASSWORD"],
            },
        )
        circuit_breaker = CircuitBreaker(threshold=5)

        # Quick proxy health check before scraping
        proxy_ok = check_proxy_health(browser)
        if not proxy_ok:
            print()
            print("  WARNING: Proxy is down - browser scrapers will be skipped.")
            print("  Only API-based routes will run.")
            print()

        for tab_name in account_tabs:
            loads = by_account[tab_name]
            print(f"\n{'='*60}")
            print(f"Account: {tab_name}")
            print(f"  Loads: {len(loads)}")

            dray_jobs = []
            origin_fixes = []  # (efj, old_origin, new_origin) for write-back
            for row in loads:
                efj_val = (row["efj"] or "").strip()
                container = (row["container"] or "").strip()
                bol = (row["bol"] or "").strip()
                vessel = (row["vessel"] or "").strip()
                carrier = (row["carrier"] or "").strip()

                if not efj_val:
                    continue

                # Resolve SSL code from vessel/carrier
                ssl_match = _resolve_ssl_pg(vessel, carrier)

                dray_jobs.append({
                    "efj":       efj_val,
                    "sheet_row": 0,  # Not used in PG mode
                    "container": container,
                    "url":       ssl_match["url"] if ssl_match else None,
                    "ssl_code":  ssl_match["code"] if ssl_match else None,
                    "bol":       bol,
                    "vessel":    vessel,
                    "carrier":   carrier,
                    "account":   tab_name,
                    "rep":       (row["rep"] or "").strip(),
                    "origin":    _normalize_origin(row["origin"] or ""),
                    "row_data":  [
                        efj_val, "Dray Import", container, bol, vessel, carrier,
                        _normalize_origin(row["origin"] or ""), row["destination"] or "",
                        row["eta"] or "", row["lfd"] or "",
                        row["pickup_date"] or "", row["delivery_date"] or "",
                        row["status"] or "", "", row["bot_notes"] or "",
                        row["return_date"] or "",
                    ],
                    # Existing values for overwrite guard
                    "existing_eta":    row["eta"] or "",
                    "existing_pickup": row["pickup_date"] or "",
                    "existing_return": row["return_date"] or "",
                    "existing_status": row["status"] or "",
                })
                # Track origin changes for write-back
                raw_origin = (row["origin"] or "").strip()
                norm_origin = _normalize_origin(raw_origin)
                if norm_origin and norm_origin != raw_origin:
                    origin_fixes.append((efj_val, raw_origin, norm_origin))

            print(f"  Dray Import rows: {len(dray_jobs)}")

            # ── Write back normalized origins ─────────────────────────────
            if origin_fixes and not args.dry_run:
                print(f"  Normalizing {len(origin_fixes)} origin field(s):")
                for efj_fix, old_orig, new_orig in origin_fixes:
                    print(f"    {efj_fix}: {old_orig!r} -> {new_orig!r}")
                    try:
                        pg_update_shipment(efj_fix, origin=new_orig)
                    except Exception as _oe:
                        print(f"    WARNING: PG origin update failed for {efj_fix}: {_oe}")
                    try:
                        from csl_sheet_writer import _get_gc, _find_row_by_efj
                        import gspread
                        gc = _get_gc()
                        if gc:
                            sh = gc.open_by_key(os.environ.get("SHEET_ID", ""))
                            ws = sh.worksheet(tab_name)
                            srow = _find_row_by_efj(ws, efj_fix)
                            if srow:
                                ws.update(f"G{srow}", [[new_orig]], value_input_option="RAW")
                    except Exception as _se:
                        pass  # sheet write is best-effort

            tab_changes  = []
            archive_jobs = []
            for job in dray_jobs:
                if not job["ssl_code"] and not job["url"]:
                    print(f"  {job['efj']}: no SSL match for vessel={job['vessel']!r} carrier={job['carrier']!r} — skipped.")
                    continue
                if not job["bol"] and not job["container"]:
                    print(f"  {job['efj']}: no BOL or container — skipped.")
                    continue

                # Use a throwaway list for pending_updates (sheet writes we discard)
                _discard = []
                try:
                    eta, pickup, ret, status = dray_import_workflow(
                        browser, None, job["sheet_row"], job["url"], job["bol"],
                        job["container"], circuit_breaker=circuit_breaker,
                        vessel=job.get("vessel", ""),
                        carrier_name=job.get("carrier", ""),
                        pending_updates=_discard,
                        proxy_ok=proxy_ok,
                        ssl_code=job.get("ssl_code"),
                        existing_row=job.get("row_data"),
                    )
                except Exception as _wf_err:
                    print(f"    ERROR: Workflow crashed for {job['container']}: {_wf_err}")
                    eta, pickup, ret, status = None, None, None, None

                container_id  = job["container"].strip() or job["efj"]
                container_key = f"{tab_name}:{container_id}"

                # If API returned nothing (timeout/error), carry forward previous state
                # to prevent false "change" alerts from state oscillation
                if eta is None and pickup is None and ret is None and status is None:
                    prev = last_check.get(container_key, {})
                    new_check[container_key] = prev  # keep previous good state
                    print(f"    ⚠ No data returned for {container_id} — skipping comparison")
                    continue

                current = {
                    "eta":         eta    or "",
                    "lfd":         pickup or "",
                    "return_date": ret    or "",
                    "status":      status or "",
                }
                new_check[container_key] = current

                # ── Write to Postgres (primary) ──────────────────────────────
                if job["efj"] and not args.dry_run:
                    # ETA: always update — vessel ETA is carrier-driven and naturally fluid
                    write_eta = eta if eta else None
                    # Pickup/Return: guarded — reps enter these after manual coordination
                    write_pickup = pickup if (pickup and not job["existing_pickup"]) else None
                    write_return = ret if (ret and not job["existing_return"]) else None
                    write_status = status if (status and job["existing_status"] in BOT_MANAGED_STATUSES) else None

                    ts = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
                    # Preserve terminal data (Avail:...) — only stamp if no structured terminal notes exist
                    existing_bn = (job.get("row_data", [""] * 15)[14] or "").strip()
                    write_bot_notes = ts if not existing_bn.startswith("Avail:") else None
                    # Preserve existing LFD from PG/sheet (row_data[9])
                    existing_lfd = (job.get("row_data", [""] * 16)[9] or "").strip()
                    write_lfd = existing_lfd if existing_lfd else None
                    pg_update_shipment(
                        job["efj"],
                        eta=write_eta,
                        lfd=write_lfd,
                        pickup_date=write_pickup,
                        return_date=write_return,
                        status=write_status,
                        bot_notes=write_bot_notes,
                        account=tab_name,
                        move_type="Dray Import",
                    )
                    # Dual-write: update Master Sheet (best-effort)
                    sheet_update_import(
                        job["efj"], tab_name,
                        eta=write_eta, pickup=write_pickup,
                        return_date=write_return, status=write_status,
                    )

                prev           = last_check.get(container_key, {})
                changed_fields = [
                    field.replace("_", " ").title()
                    for field in ("eta", "lfd", "return_date", "status")
                    if current[field] != prev.get(field, "")
                ]

                if changed_fields:
                    # Skip if all current values are empty (API returned partial garbage)
                    has_data = any(current[f] for f in ("eta", "lfd", "return_date", "status"))
                    if has_data:
                        tab_changes.append({
                            "container":      container_id,
                            "eta":            current["eta"],
                            "lfd":            current["lfd"],
                            "return_date":    current["return_date"],
                            "status":         current["status"],
                            "changed_fields": changed_fields,
                        })
                    else:
                        print(f"    ⚠ Suppressed empty-value alert for {container_id}")

                # Queue for archiving if container has been returned to port
                if status == "Returned to Port":
                    archive_jobs.append({
                        "efj":         job["efj"],
                        "container":   container_id,
                        "eta":         eta,
                        "pickup":      pickup,
                        "return_date": ret,
                        "status":      status,
                    })

            # ── Terminal cross-check for NOLA containers ────────────────────
            if _TERMINAL_NOLA_OK and not args.dry_run:
                nola_jobs = [
                    j for j in dray_jobs
                    if j.get("container") and j.get("efj") and
                    any(kw in (j["row_data"][6] if len(j["row_data"]) > 6 else "").lower()
                        for kw in ("new orleans", "napoleon"))
                ]
                if nola_jobs:
                    try:
                        nola_cnums = [j["container"] for j in nola_jobs]
                        print(f"\n  Terminal check (NOLA): {len(nola_cnums)} container(s)...")
                        terminal_results = _check_nola(nola_cnums)
                        for j in nola_jobs:
                            cnum = j["container"]
                            t = terminal_results.get(cnum)
                            if not t:
                                print(f"    {cnum}: not in terminal API response")
                                continue
                            # Update bot_notes with terminal status
                            tn = t["bot_notes"]
                            pg_update_shipment(j["efj"], bot_notes=tn)
                            # Write pickup date if terminal confirms available and no rep date set
                            if t["ready"] and t["pickup_date"] and not j["existing_pickup"]:
                                pg_update_shipment(j["efj"], pickup_date=t["pickup_date"])
                                sheet_update_import(j["efj"], tab_name, pickup=t["pickup_date"])
                                print(f"    {cnum}: AVAILABLE — pickup {t['pickup_date']}")
                            else:
                                print(f"    {cnum}: {tn[:90]}")
                            # Write bot_notes directly to sheet Col N via csl_sheet_writer helper
                            try:
                                import gspread
                                from csl_sheet_writer import _get_gc, _find_row_by_efj, _tab_cols
                                gc = _get_gc()
                                if gc:
                                    sh = gc.open_by_key(os.environ.get("SHEET_ID", ""))
                                    ws = sh.worksheet(tab_name)
                                    srow = _find_row_by_efj(ws, j["efj"])
                                    if srow:
                                        botnotes_col, _ = _tab_cols(tab_name)
                                        ws.update(f"{botnotes_col}{srow}", [[tn]], value_input_option="RAW")
                            except Exception as _se:
                                pass  # sheet write is best-effort
                    except Exception as _te:
                        print(f"  WARNING: Terminal check error: {_te}")

            # ── Archive completed loads (Postgres only) ──────────────────────
            if archive_jobs and not args.dry_run:
                print(f"\n  Archiving {len(archive_jobs)} completed load(s)...")
                for aj in archive_jobs:
                    rep_info = _get_rep_for_account(sh, tab_name)
                    if not rep_info:
                        print(f"  WARNING: archive skipped — no rep mapping for '{tab_name}', efj={aj['efj']}. Load remains active.")
                        print(f"  WARN: Skipping archive {aj['efj']} — no rep mapping for '{tab_name}'")
                        continue
                    pg_archive_shipment(aj["efj"])
                    sheet_archive_row(aj["efj"], tab_name, rep=rep_info["rep"])
                    print(f"  Archived {aj['efj']} (Returned to Port)")

                    # Remove from new_check
                    archived_key = f"{tab_name}:{aj['container']}"
                    new_check.pop(archived_key, None)

                    # Send archive email
                    rep_info = _get_rep_for_account(sh, tab_name) or {}
                    rep_email = rep_info.get("email", "")
                    rep_name  = rep_info.get("rep", "")
                    if rep_email:
                        timestamp = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
                        subject = f"CSL Archived | {aj['efj']} | {aj['container']} | Returned to Port"
                        _td = 'style="padding:4px 10px;font-size:13px;"'
                        _tl = 'style="padding:4px 10px;color:#555;font-size:13px;"'
                        body = (
                            f'<div style="font-family:Arial,sans-serif;max-width:700px;">'
                            f'<div style="background:#1b5e20;color:white;padding:10px 14px;border-radius:6px 6px 0 0;font-size:15px;">'
                            f'<b>Container Archived &mdash; Returned to Port</b></div>'
                            f'<div style="border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;padding:12px;">'
                            f'<p style="margin:0 0 8px 0;font-size:12px;color:#888;">Archived: {timestamp}</p>'
                            f'<table style="border-collapse:collapse;">'
                            f'<tr><td {_tl}>EFJ#</td><td {_td}><b>{aj["efj"]}</b></td></tr>'
                            f'<tr><td {_tl}>Container</td><td {_td}><b>{aj["container"]}</b></td></tr>'
                            f'<tr><td {_tl}>Account</td><td {_td}>{tab_name}</td></tr>'
                            f'<tr><td {_tl}>Rep</td><td {_td}>{rep_name}</td></tr>'
                            f'<tr><td {_tl}>ETA</td><td {_td}>{aj["eta"] or "—"}</td></tr>'
                            f'<tr><td {_tl}>Pickup</td><td {_td}>{aj["pickup"] or "—"}</td></tr>'
                            f'<tr><td {_tl}>Returned</td><td {_td}>{aj["return_date"] or "—"}</td></tr>'
                            f'<tr><td {_tl}>Status</td><td {_td}>{aj["status"]}</td></tr>'
                            f'</table></div></div>'
                        )
                        _send_email(rep_email, EMAIL_CC, subject, body)

            if tab_changes:
                print(f"\n  {len(tab_changes)} change(s) detected — sending email...")
                send_account_notification(tab_name, ACCOUNT_REPS, tab_changes)
            else:
                print(f"\n  No changes in '{tab_name}'.")

        browser.close()

    save_last_check(new_check)
    print("\nRun complete.")


def main():
    parser = argparse.ArgumentParser(description="CSL Dray Import Bot")
    parser.add_argument("--tab", help="Process only this tab")
    parser.add_argument("--dry-run", action="store_true",
                        help="Scrape only, skip writes and emails")
    parser.add_argument("--once", action="store_true",
                        help="Run once and exit (legacy cron mode)")
    args = parser.parse_args()

    if args.once:
        run_once(args)
        return

    print(f"Dray Import Monitor started — polling every {POLL_INTERVAL // 3600} hours.")
    while True:
        try:
            run_once(args)
        except Exception as exc:
            print(f"ERROR in run_once: {exc.__class__.__name__}: {exc}")
        print(f"\n  Sleeping {POLL_INTERVAL // 3600} hours...")
        _time.sleep(POLL_INTERVAL)


if __name__ == "__main__":
    main()
