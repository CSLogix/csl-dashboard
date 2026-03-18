#!/usr/bin/env python3
import json,os,smtplib,time,re,requests,gspread
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.service_account import Credentials
from dotenv import load_dotenv

load_dotenv()

from csl_pg_writer import (pg_update_shipment, pg_archive_shipment,
                          pg_load_all_export_state, pg_set_export_state,
                          pg_delete_export_state, pg_jc_cache_get,
                          pg_jc_cache_set, pg_ensure_tracking_tables)
from csl_sheet_writer import sheet_update_export, sheet_archive_row

SHEET_ID=os.environ["SHEET_ID"]
CREDENTIALS_FILE=os.environ.get("GOOGLE_CREDENTIALS_FILE","/root/csl-credentials.json")
STATE_FILE="/root/csl-bot/export_state.json"
POLL_INTERVAL=3600
SMTP_HOST="smtp.gmail.com"
SMTP_PORT=587
SMTP_USER=os.environ["SMTP_USER"]
SMTP_PASSWORD=os.environ["SMTP_PASSWORD"]
EMAIL_CC=os.environ.get("EMAIL_CC","efj-operations@evansdelivery.com")
EMAIL_FALLBACK=os.environ.get("EMAIL_CC","efj-operations@evansdelivery.com")
ACCOUNT_LOOKUP_TAB="Account Rep"
SKIP_TABS={"Sheet 4","Sheet14","DTCELNJW","Account Rep","SSL Links","Completed Eli","Completed Radka","Completed John F"}
COL_EFJ=0;COL_MOVE_TYPE=1;COL_CONTAINER=2;COL_BOOKING=3;COL_VESSEL=4
COL_CARRIER=5;COL_ORIGIN=6;COL_DEST=7;COL_ERD=8;COL_CUTOFF=9;COL_NOTES=14
SCOPES=["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
RAIL_KEYWORDS=["rail","ramp","intermodal","train","bnsf","union pacific","csx"]
GATE_IN_STATUSES=["full load on rail for export","gate in full","full in","received for export transfer","loaded on vessel","vessel departure"]
JSONCARGO_API_KEY=os.environ["JSONCARGO_API_KEY"]
JSONCARGO_BASE="https://api.jsoncargo.com/api/v1"

# -- JsonCargo API response cache (Postgres-backed) --
import json as _json
import time as _time_mod

_JSONCARGO_CACHE_TTL = 6 * 3600

# ── Postgres migration: hardcoded lookups ────────────────────────────────
import psycopg2
import psycopg2.extras
from dotenv import load_dotenv as _pg_load_dotenv
_pg_load_dotenv("/root/csl-bot/csl-doc-tracker/.env")

def _pg_connect():
    return psycopg2.connect(
        host=os.getenv("DB_HOST", "localhost"),
        port=int(os.getenv("DB_PORT", "5432")),
        dbname=os.getenv("DB_NAME", "csl_dispatch"),
        user=os.getenv("DB_USER", "csl_user"),
        password=os.getenv("DB_PASSWORD", ""),
    )

SSL_LINKS_PG = {
    "maersk":      "MAERSK",
    "hapag":       "HAPAG_LLOYD",
    "hapag-lloyd": "HAPAG_LLOYD",
    "one line":    "ONE",
    "ocean network": "ONE",
    "evergreen":   "EVERGREEN",
    "hmm":         "HMM",
    "cma cgm":     "CMA_CGM",
    "cma":         "CMA_CGM",
    "apl":         "CMA_CGM",
    "msc":         "MSC",
    "cosco":       "COSCO",
    "zim":         "ZIM",
    "yang ming":   "YANG_MING",
    "acl":         "CMA_CGM",
    "sm line":     "SM_LINE",
    "sml":         "SM_LINE",
    "matson":      "MATSON",
}

ACCOUNT_REPS_PG = {
    "Allround":        {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Boviet":          {"rep": "",      "email": "Boviet-efj@evansdelivery.com"},
    "Cadi":            {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "CNL":             {"rep": "Janice","email": "Janice.Cortes@evansdelivery.com"},
    "DHL":             {"rep": "John F","email": "John.Feltz@evansdelivery.com"},
    "DSV":             {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "EShipping":       {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "GW-World":        {"rep": "John F","email": "John.Feltz@evansdelivery.com"},
    "IWS":             {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Kischo":          {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "Kripke":          {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "LS Cargo":        {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "MAO":             {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "Mamata":          {"rep": "John F","email": "John.Feltz@evansdelivery.com"},
    "MD Metal":        {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Meiko":           {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "MGF":             {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Mitchells Trans": {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Rose":            {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "SEI Acquistion":  {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Sutton":          {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Talatrans":       {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Tanera":          {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "TCR":             {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
    "Texas":           {"rep": "Eli",   "email": "Eli.Luchuk@evansdelivery.com"},
    "USHA":            {"rep": "Radka", "email": "Radka.White@evansdelivery.com"},
}


# BOL/booking prefix (first 4 chars) -> SSL code
BOL_PREFIX_TO_SSL = {
    "MAEU": "MAERSK", "SEAU": "MAERSK", "SGLU": "MAERSK",
    "SUDU": "MAERSK", "MCPU": "MAERSK", "ALIU": "MAERSK", "CNIU": "MAERSK",
    "CMDU": "CMA_CGM", "APLU": "CMA_CGM", "ACLU": "CMA_CGM",
    "ANLC": "CMA_CGM", "CSFU": "CMA_CGM", "MCAW": "CMA_CGM",
    "HLCU": "HAPAG_LLOYD", "UACU": "HAPAG_LLOYD",
    "MOLU": "ONE", "KLNE": "ONE",
    "EVRG": "EVERGREEN",
    "HDMU": "HMM",
    "MSCU": "MSC",
    "COSU": "COSCO", "CHNJ": "COSCO",
    "ZIMU": "ZIM",
    "YMLU": "YANG_MING",
    "SMLM": "SM_LINE",
    "MATS": "MATSON",
    "MWHL": "WAN_HAI", "WHLC": "WAN_HAI", "CNCX": "WAN_HAI",
}


def _ssl_from_bol_prefix(bol):
    """
    Determine an SSL code from a bill-of-lading or booking identifier by inspecting its first four characters.
    
    Parameters:
        bol (str): Bill-of-lading or booking identifier; may include surrounding whitespace.
    
    Returns:
        str or None: SSL code corresponding to the identifier's 4-character prefix, or None if the identifier is missing, too short, or has no matching SSL.
    """
    if not bol or len(bol.strip()) < 5:
        return None
    prefix = bol.strip()[:4].upper()
    return BOL_PREFIX_TO_SSL.get(prefix)


def _resolve_ssl_export(vessel, carrier, bol=""):
    """
    Determine the shipping line (SSL) code from vessel or carrier text, falling back to a BOL prefix when provided.
    
    Checks vessel and carrier strings against the SSL_LINKS_PG mappings (exact match, substring, and word-start heuristics). If no match is found and a BOL/booking string is supplied, attempts to derive the SSL from the BOL prefix.
    
    Parameters:
        vessel (str): Vessel name or description to inspect.
        carrier (str): Carrier name or description to inspect.
        bol (str): Bill-of-lading or booking identifier used as a fallback source for SSL detection.
    
    Returns:
        ssl_code (str | None): The detected SSL code from SSL_LINKS_PG, or `None` if no match is found.
    """
    for text in (vessel or "", carrier or ""):
        val = text.strip().lower()
        if not val:
            continue
        if val in SSL_LINKS_PG:
            return SSL_LINKS_PG[val]
        for key, code in SSL_LINKS_PG.items():
            if key in val:
                return code
        for key, code in SSL_LINKS_PG.items():
            if any(w.startswith(key) for w in val.split()):
                return code
    # Fallback: detect from BOL prefix (e.g. MAEU2814354 -> MAERSK)
    if bol:
        detected = _ssl_from_bol_prefix(bol)
        if detected:
            print(f"    Auto-detected SSL from BOL prefix: {bol[:4]} -> {detected}")
            return detected
    return None


def _jc_cache_get(container_num):
    """
    Get JsonCargo cache entry for a container from the Postgres-backed cache using the module's TTL.
    
    Parameters:
        container_num (str): Container number to look up.
    
    Returns:
        The cached JsonCargo response for `container_num` if present and not expired, otherwise `None`.
    """
    return pg_jc_cache_get(container_num, _JSONCARGO_CACHE_TTL)

def _jc_cache_set(container_num, data):
    """
    Store JsonCargo lookup results in the Postgres-backed JsonCargo cache for a container.
    
    Parameters:
        container_num (str): Container number used as the cache key.
        data (Any): JSON-serializable lookup result or tracking payload to persist.
    """
    pg_jc_cache_set(container_num, data)

SSL_LINKS_TAB="SSL Links"

def load_ssl_links(creds):
    """Read SSL Links tab -> dict mapping lowercase ssl name -> {url, code}."""
    try:
        gc2=gspread.authorize(creds)
        ws=gc2.open_by_key(SHEET_ID).worksheet(SSL_LINKS_TAB)
        rows=ws.get_all_values()
        lookup={}
        for row in rows[1:]:
            if len(row)>=3 and row[0].strip():
                ssl_name=row[0].strip()
                url=row[1].strip()
                ssl_code=row[2].strip()
                if ssl_name and (url or ssl_code):
                    lookup[ssl_name.lower()]={"url":url,"code":ssl_code}
        print(f"  Loaded {len(lookup)} SSL link(s) from '{SSL_LINKS_TAB}'")
        return lookup
    except Exception as e:
        print(f"  WARNING: Could not load SSL Links: {e}")
        return {}

def _load_credentials():
    """
    Load Google service account credentials from the configured service account file and ensure the access token is fresh.
    
    Returns:
        creds (google.oauth2.service_account.Credentials): Service account credentials initialized with SCOPES and refreshed for immediate use.
    """
    creds=Credentials.from_service_account_file(CREDENTIALS_FILE,scopes=SCOPES)
    creds.refresh(GoogleRequest())
    return creds

def load_state():
    """
    Load persisted export tracking state, preferring the Postgres-backed store and falling back to a legacy local JSON file if Postgres has no data.
    
    Returns:
        state (dict): Mapping of per-export keys to their persisted state; empty dict if no persisted state is found.
    """
    state = pg_load_all_export_state()
    if state:
        return state
    # Fallback: try legacy JSON file if PG returned empty (first run after migration)
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f: return json.load(f)
        except (OSError, json.JSONDecodeError): pass
    return {}

def load_account_lookup(creds):
    """
    Load account representative lookup mapping from the Account Rep sheet.
    
    Parameters:
        creds: Google service account credentials used to access the spreadsheet.
    
    Returns:
        dict: Mapping from account identifier (str) to a dict with keys "rep" (representative name) and "email" (representative email). Returns an empty dict if the sheet cannot be read or no valid rows are found.
    """
    try:
        gc=gspread.authorize(creds)
        ws=gc.open_by_key(SHEET_ID).worksheet(ACCOUNT_LOOKUP_TAB)
        lookup={}
        for row in ws.get_all_values():
            if len(row)>=3 and row[0].strip():
                a,r,e=row[0].strip(),row[1].strip(),row[2].strip()
                if a and e: lookup[a]={"rep":r,"email":e}
        print(f"  Loaded {len(lookup)} account(s)")
        return lookup
    except Exception as e:
        print(f"  WARNING: {e}"); return {}

def get_account_tabs(sheet,lookup):
    return [ws.title for ws in sheet.worksheets() if ws.title not in SKIP_TABS and ws.title in lookup]

def get_sheet_hyperlinks(creds,sheet_id,tab_name):
    try:
        creds.refresh(GoogleRequest())
        url=(f"https://sheets.googleapis.com/v4/spreadsheets/{sheet_id}"
             f"?ranges={tab_name}&fields=sheets.data.rowData.values.hyperlink&includeGridData=true")
        resp=requests.get(url,headers={"Authorization":f"Bearer {creds.token}"},timeout=20)
        rows=resp.json()["sheets"][0]["data"][0].get("rowData",[])
        return [[cell.get("hyperlink") for cell in row.get("values",[])] for row in rows]
    except Exception as e:
        print(f"  WARNING: hyperlink fetch failed: {e}"); return []

def _parse_date(s):
    s=s.strip()
    if not s: return None
    yr=datetime.now().year
    for fmt in ["%d-%b","%m-%d","%m/%d","%m/%d/%Y","%Y-%m-%d","%d-%b-%Y","%b %d","%B %d","%d-%b-%y"]:
        try:
            dt=datetime.strptime(s,fmt)
            if dt.year==1900: dt=dt.replace(year=yr)
            return dt
        except (ValueError, TypeError): continue
    return None

def _cutoff_alert(s):
    dt=_parse_date(s)
    if not dt: return None
    now=datetime.now(ZoneInfo("America/New_York")).replace(tzinfo=None)
    diff=dt-now
    if diff.total_seconds()<0: return None
    if diff.total_seconds()<=48*3600: return f"CUTOFF IN {int(diff.total_seconds()/3600)}hrs"
    return None

def _is_rail(vessel,origin,carrier):
    return any(kw in f"{vessel} {origin} {carrier}".lower() for kw in RAIL_KEYWORDS)

def _is_container_num(s):
    return bool(re.match(r'^[A-Z]{4}\d{7}$',s.strip().upper()))

def detect_ssl_line(vessel, carrier, ssl_links):
    """Match vessel/carrier text to SSL Links lookup."""
    combined = f"{vessel} {carrier}".lower()
    for key, info in ssl_links.items():
        if key in combined or combined in key:
            return info["code"]
    for key, info in ssl_links.items():
        key_words = key.replace("-", " ").split()
        for word in key_words:
            if len(word) >= 3 and word in combined:
                return info["code"]
    return None
def jsoncargo_bol_lookup(booking_num, ssl_line):
    cached = _jc_cache_get(f"bol:{booking_num}")
    if cached is not None:
        print(f"    BOL lookup: cache hit for {booking_num}")
        return cached
    try:
        url=f"{JSONCARGO_BASE}/containers/bol/{booking_num}/"
        resp=requests.get(url,headers={"x-api-key":JSONCARGO_API_KEY},
                         params={"shipping_line":ssl_line},timeout=20)
        data=resp.json()
        if "data" in data:
            containers=data["data"].get("associated_container_numbers",[])
            if containers:
                print(f"    BOL lookup: found containers {containers}")
                _jc_cache_set(f"bol:{booking_num}", containers[0])
                return containers[0]
        print(f"    BOL lookup: {data.get('error',{}).get('title','no result')}")
        return None
    except Exception as e:
        print(f"    BOL lookup error: {e}"); return None

def jsoncargo_container_track(container_num, ssl_line):
    cached = _jc_cache_get(container_num)
    if cached is not None:
        print(f"    Container track: cache hit for {container_num}")
        return cached
    try:
        url=f"{JSONCARGO_BASE}/containers/{container_num}/"
        resp=requests.get(url,headers={"x-api-key":JSONCARGO_API_KEY},
                         params={"shipping_line":ssl_line},timeout=20)
        data=resp.json()
        if "error" in data:
            print(f"    Container track: {data['error'].get('title','error')}")
            return None
        events=[]
        raw_events=data.get("data",{}).get("events",[]) or data.get("data",{}).get("moves",[]) or []
        for ev in raw_events:
            desc=(ev.get("description") or ev.get("move") or ev.get("status") or "").lower()
            if desc: events.append(desc)
        print(f"    Container track: {len(events)} events found")
        gate_in=None
        all_text=" ".join(events)
        for status in GATE_IN_STATUSES:
            if status in all_text:
                gate_in=status.title(); break
        result = {"events":events,"gate_in":gate_in}
        _jc_cache_set(container_num, result)
        return result
    except Exception as e:
        print(f"    Container track error: {e}"); return None

def _send_email(to,cc,subject,body):
    msg=MIMEMultipart("alternative")
    msg["Subject"]=subject;msg["From"]=SMTP_USER;msg["To"]=to
    if cc and cc!=to: msg["Cc"]=cc
    msg.attach(MIMEText(body,"html"))
    rcpt=[to]+([cc] if cc and cc!=to else [])
    try:
        with smtplib.SMTP(SMTP_HOST,SMTP_PORT) as s:
            s.ehlo();s.starttls();s.login(SMTP_USER,SMTP_PASSWORD)
            s.sendmail(SMTP_USER,rcpt,msg.as_string())
        print(f"    Email sent to {to}")
    except Exception as e: print(f"    WARNING: Email failed: {e}")

def send_export_alert(tab_name,lookup,alerts):
    if not alerts: return
    info=lookup.get(tab_name,{})
    rep=info.get("email","") or EMAIL_FALLBACK
    rep_name=info.get("rep","")
    cc=EMAIL_CC if rep!=EMAIL_FALLBACK else None
    now=datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    subj=f"CSL Export Alert - {tab_name} - {now}"
    th='style="padding:6px 10px;text-align:left;border-bottom:1px solid #ddd;color:white;font-size:13px;"'
    td='style="padding:6px 10px;border-bottom:1px solid #eee;font-size:13px;"'
    hdr_color="#e65100"
    hdrs=["EFJ #","Container","Vessel","Booking","ERD","Cutoff","Alert"]
    hdr_cells="".join(f'<th {th}>{h}</th>' for h in hdrs)
    rows=""
    for i,a in enumerate(alerts):
        alt=' style="background:#f9f9f9;"' if i%2==1 else ''
        alert_text=a.get("alert_reason") or ", ".join(a.get("changed",[])) or ""
        rows+=(f'<tr{alt}>'
               f'<td {td}><b>{a["efj"]}</b></td>'
               f'<td {td}>{a["container"]}</td>'
               f'<td {td}>{a["vessel"]}</td>'
               f'<td {td}>{a["booking"]}</td>'
               f'<td {td}>{a.get("erd") or "\u2014"}</td>'
               f'<td {td}>{a.get("cutoff") or "\u2014"}</td>'
               f'<td {td}><b>{alert_text}</b></td>'
               f'</tr>')
    rep_line=f' &mdash; Rep: {rep_name}' if rep_name else ''
    body=(f'<div style="font-family:Arial,sans-serif;max-width:900px;">'
          f'<h2 style="margin:0 0 4px 0;color:#333;">CSL Dray Export Alert &mdash; {tab_name}</h2>'
          f'<p style="color:#888;font-size:12px;margin:0 0 4px 0;">{now} &mdash; {len(alerts)} Alert(s){rep_line}</p>'
          f'<div style="background:{hdr_color};color:white;padding:8px 14px;'
          f'border-radius:6px 6px 0 0;font-size:15px;margin-top:12px;">'
          f'<b>Export Alerts ({len(alerts)})</b></div>'
          f'<table style="border-collapse:collapse;width:100%;border:1px solid #ddd;border-top:none;">'
          f'<tr style="background:{hdr_color};">{hdr_cells}</tr>'
          f'{rows}</table></div>')
    _send_email(rep,cc,subj,body)

def send_container_assigned_email(tab_name,lookup,efj,booking,container_num):
    info=lookup.get(tab_name,{})
    rep=info.get("email","") or EMAIL_FALLBACK
    rep_name=info.get("rep","")
    cc=EMAIL_CC if rep!=EMAIL_FALLBACK else None
    now=datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    subj=f"CSL Export - Container # Assigned | {efj} | {container_num}"
    td='style="padding:4px 10px;font-size:13px;"'
    tl='style="padding:4px 10px;color:#555;font-size:13px;"'
    rep_row=f'<tr><td {tl}>Rep</td><td {td}>{rep_name}</td></tr>' if rep_name else ''
    body=(f'<div style="font-family:Arial,sans-serif;max-width:700px;">'
          f'<div style="background:#1b5e20;color:white;padding:10px 14px;border-radius:6px 6px 0 0;font-size:15px;">'
          f'<b>Container Number Assigned</b></div>'
          f'<div style="border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;padding:12px;">'
          f'<p style="margin:0 0 8px 0;font-size:12px;color:#888;">Updated: {now}</p>'
          f'<table style="border-collapse:collapse;">{rep_row}'
          f'<tr><td {tl}>EFJ#</td><td {td}><b>{efj}</b></td></tr>'
          f'<tr><td {tl}>Booking#</td><td {td}>{booking}</td></tr>'
          f'<tr><td {tl}>Container</td><td {td}><b>{container_num}</b></td></tr>'
          f'</table></div></div>')
    _send_email(rep,cc,subj,body)

def send_archive_email(tab_name,lookup,job):
    info=lookup.get(tab_name,{})
    rep=info.get("email","") or EMAIL_FALLBACK
    rep_name=info.get("rep","")
    cc=EMAIL_CC if rep!=EMAIL_FALLBACK else None
    now=datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    subj=f"CSL Export Archived | {job['efj']} | {job['container']} | Gate In"
    td='style="padding:4px 10px;font-size:13px;"'
    tl='style="padding:4px 10px;color:#555;font-size:13px;"'
    rep_row=f'<tr><td {tl}>Rep</td><td {td}>{rep_name}</td></tr>' if rep_name else ''
    body=(f'<div style="font-family:Arial,sans-serif;max-width:700px;">'
          f'<div style="background:#1b5e20;color:white;padding:10px 14px;border-radius:6px 6px 0 0;font-size:15px;">'
          f'<b>Gate In Confirmed &mdash; Archived</b></div>'
          f'<div style="border:1px solid #ddd;border-top:none;border-radius:0 0 6px 6px;padding:12px;">'
          f'<p style="margin:0 0 8px 0;font-size:12px;color:#888;">Archived: {now}</p>'
          f'<table style="border-collapse:collapse;">{rep_row}'
          f'<tr><td {tl}>EFJ#</td><td {td}><b>{job["efj"]}</b></td></tr>'
          f'<tr><td {tl}>Container</td><td {td}><b>{job["container"]}</b></td></tr>'
          f'<tr><td {tl}>Booking</td><td {td}>{job["booking"]}</td></tr>'
          f'<tr><td {tl}>Vessel</td><td {td}>{job["vessel"]}</td></tr>'
          f'<tr><td {tl}>Origin</td><td {td}>{job["origin"]}</td></tr>'
          f'<tr><td {tl}>Destination</td><td {td}>{job["dest"]}</td></tr>'
          f'<tr><td {tl}>ERD</td><td {td}>{job.get("erd") or "\u2014"}</td></tr>'
          f'<tr><td {tl}>Cutoff</td><td {td}>{job.get("cutoff") or "\u2014"}</td></tr>'
          f'<tr><td {tl}>Gate In</td><td {td}><b>{job["gate_in_status"]}</b></td></tr>'
          f'</table></div></div>')
    _send_email(rep,cc,subj,body)

def archive_export_row_pg(job, tab_name):
    """Archive export row — Postgres only (no sheet writes)."""
    try:
        pg_archive_shipment(job["efj"])
        sheet_archive_row(job['efj'], tab_name,
                          rep=ACCOUNT_REPS_PG.get(tab_name, {}).get('rep'))
        print(f"    Archived {job['efj']} (Gate In)")
        send_archive_email(tab_name, ACCOUNT_REPS_PG, job)
        return True
    except Exception as e:
        print(f"    WARNING: Archive failed: {e}")
        return False


def run_once():
    """
    Perform a single poll cycle to process active Dray Export shipments from Postgres.
    
    Reads active "Dray Export" shipments, ensures required tracking tables exist, and processes each row:
    - Detects ERD and cutoff changes and persists per-row state to Postgres.
    - Generates cutoff alerts and collects per-account alert batches.
    - Resolves steamship line (SSL) for lookups (including BOL-prefix fallback) and, when needed,
      looks up container numbers via JsonCargo and writes assignments to Postgres and the Master Sheet.
    - Tracks container status via JsonCargo; when a gate-in is observed, archives the export row,
      removes persisted state, and notifies recipients.
    - Sends email notifications for cutoff/container alerts, container assignments, and archive events.
    
    Side effects:
    - Reads and updates Postgres shipment and tracking state tables.
    - May update the Master Sheet and send HTML emails.
    - May call external JsonCargo APIs for lookups and tracking.
    """
    now_str = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    print(f"\n[{now_str}] Export poll cycle (Postgres mode)...")

    # Ensure tracking state tables exist
    pg_ensure_tracking_tables()

    # ── Read active dray export loads from Postgres ──────────────────────────
    conn = None
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
                WHERE move_type = 'Dray Export' AND archived = FALSE
                ORDER BY account, efj
            """)
            all_loads = cur.fetchall()
    except Exception as exc:
        print(f"FATAL: Could not read from Postgres: {exc}")
        return
    finally:
        if conn is not None:
            conn.close()

    # Group by account
    from collections import defaultdict
    by_account = defaultdict(list)
    for row in all_loads:
        acct = row["account"] or "Unknown"
        by_account[acct].append(row)

    account_tabs = sorted(by_account.keys())
    print(f"  Loaded {len(all_loads)} active Dray Export load(s) across {len(account_tabs)} account(s)")
    if not account_tabs:
        print("  No active export loads found.")
        return

    state = load_state()

    for tab_name in account_tabs:
        loads = by_account[tab_name]
        print(f"\n  Checking {tab_name}... ({len(loads)} export row(s))")
        tab_alerts = []

        for row in loads:
            efj = (row["efj"] or "").strip()
            container = (row["container"] or "").strip()
            booking = (row["bol"] or "").strip()
            vessel = (row["vessel"] or "").strip()
            carrier = (row["carrier"] or "").strip()
            origin = (row["origin"] or "").strip()
            dest = (row["destination"] or "").strip()
            # Use lfd as cutoff for exports, eta as ERD
            erd = (row["eta"] or "").strip()
            cutoff = (row["lfd"] or "").strip()

            if not efj:
                continue

            key = f"{tab_name}:{efj}:{container}"
            print(f"\n  -> {efj}|{container} booking={booking} ERD={erd!r} Cutoff={cutoff!r}")

            prev = state.get(key, {})
            current = {"erd": erd, "cutoff": cutoff, "cutoff_alerted": prev.get("cutoff_alerted", "")}
            changed = [f.upper() for f in ("erd", "cutoff") if current[f] != prev.get(f, "")]
            if "CUTOFF" in changed:
                current["cutoff_alerted"] = ""
            pg_set_export_state(key, **current)

            alert_reason = _cutoff_alert(cutoff) if cutoff else None
            if alert_reason and current["cutoff_alerted"] == cutoff:
                print(f"    Cutoff alert already sent for {cutoff} - skipping")
                alert_reason = None

            if changed or alert_reason:
                if alert_reason:
                    current["cutoff_alerted"] = cutoff
                    pg_set_export_state(key, **current)
                tab_alerts.append({
                    "efj": efj, "container": container, "vessel": vessel,
                    "booking": booking, "erd": erd, "cutoff": cutoff,
                    "alert_reason": alert_reason, "changed": changed,
                })
                today = datetime.now(ZoneInfo("America/New_York")).strftime("%m-%d %H:%M")
                reason = alert_reason or f"Date change: {', '.join(changed)}"
                pg_update_shipment(efj, bot_notes=f"{reason} - {today}",
                                   account=tab_name, move_type="Dray Export")

            # Resolve SSL line
            ssl_line = _resolve_ssl_export(vessel, carrier, booking)
            if not ssl_line:
                print(f"    SSL line not detected for {vessel}/{carrier}/{booking} - skipping API")
                continue

            # Check if container column has booking# instead of container#
            if not _is_container_num(container):
                print(f"    Col C is booking# - calling BOL lookup...")
                found_container = jsoncargo_bol_lookup(booking, ssl_line)
                if found_container:
                    print(f"    Container# found: {found_container}")
                    # Update container in Postgres
                    pg_update_shipment(efj, container=found_container,
                                       account=tab_name, move_type="Dray Export")
                    # Dual-write: update container in Master Sheet
                    sheet_update_export(efj, tab_name, container=found_container)
                    send_container_assigned_email(tab_name, ACCOUNT_REPS_PG, efj, booking, found_container)
                    today = datetime.now(ZoneInfo("America/New_York")).strftime("%m-%d %H:%M")
                    pg_update_shipment(efj, bot_notes=f"Container# assigned: {found_container} - {today}")
                    container = found_container
                else:
                    print(f"    No container# yet for {efj}")
                    continue

            print(f"    Tracking container# {container}...")
            track = jsoncargo_container_track(container, ssl_line)
            if not track:
                print(f"    No tracking data for {container}")
                continue
            if track["gate_in"]:
                print(f"    GATE IN: {track['gate_in']} - archiving")
                job = {
                    "efj": efj, "container": container, "booking": booking,
                    "vessel": vessel, "origin": origin, "dest": dest,
                    "erd": erd, "cutoff": cutoff, "gate_in_status": track["gate_in"],
                }
                ok = archive_export_row_pg(job, tab_name)
                if ok:
                    pg_delete_export_state(key)
            else:
                print(f"    No gate-in yet for {container}")

        if tab_alerts:
            print(f"\n  Sending alert for {len(tab_alerts)} row(s)...")
            send_export_alert(tab_name, ACCOUNT_REPS_PG, tab_alerts)
        else:
            print(f"  No alerts for {tab_name}")

    # State already persisted per-row to Postgres via pg_set_export_state()
    print("Export poll complete.")


def main():
    print("Export Monitor v3 (Postgres mode) started.")
    while True:
        run_once()
        print("  Sleeping 60 min...")
        time.sleep(POLL_INTERVAL)

if __name__ == "__main__":
    import sys
    if "--once" in sys.argv:
        print("Export Monitor v3 — single run (Postgres)")
        run_once()
        print("Run complete.")
    else:
        main()
