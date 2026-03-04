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
SKIP_TABS={"Sheet 4","DTCELNJW","Account Rep","SSL Links","Completed Eli","Completed Radka","Completed John F"}
COL_EFJ=0;COL_MOVE_TYPE=1;COL_CONTAINER=2;COL_BOOKING=3;COL_VESSEL=4
COL_CARRIER=5;COL_ORIGIN=6;COL_DEST=7;COL_ERD=8;COL_CUTOFF=9;COL_NOTES=14
SCOPES=["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
RAIL_KEYWORDS=["rail","ramp","intermodal","train","bnsf","union pacific","csx"]
GATE_IN_STATUSES=["full load on rail for export","gate in full","full in","received for export transfer","loaded on vessel","vessel departure"]
JSONCARGO_API_KEY=os.environ["JSONCARGO_API_KEY"]
JSONCARGO_BASE="https://api.jsoncargo.com/api/v1"

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
    creds=Credentials.from_service_account_file(CREDENTIALS_FILE,scopes=SCOPES)
    creds.refresh(GoogleRequest())
    return creds

def load_state():
    if os.path.exists(STATE_FILE):
        try:
            with open(STATE_FILE) as f: return json.load(f)
        except: pass
    return {}

def save_state(data):
    try:
        import shutil
        if os.path.exists(STATE_FILE):
            shutil.copy2(STATE_FILE, STATE_FILE + '.bak')
        tmp = STATE_FILE + '.tmp'
        with open(tmp, 'w') as f:
            json.dump(data, f, indent=2)
        os.replace(tmp, STATE_FILE)
    except Exception as e: print(f'  WARNING: {e}')

def load_account_lookup(creds):
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
        except: continue
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

def archive_export_row(sheet,tab_name,sheet_row,row_data,job,lookup):
    try:
        info=lookup.get(tab_name,{})
        rep_name=info.get("rep","").lower()
        # Route to rep's completed tab
        if "radka" in rep_name:
            dest_tab="Completed Radka"
        elif "john" in rep_name:
            dest_tab="Completed John F"
        elif "eli" in rep_name:
            dest_tab="Completed Eli"
        else:
            # Fallback: try "Completed {First Name}"
            first_name = info.get("rep","").split()[0] if info.get("rep","") else ""
            dest_tab = f"Completed {first_name}" if first_name else None
            if not dest_tab:
                print(f"    WARNING: No completed tab for rep '{info.get('rep','')}' — skipping archive")
                return False
        dest_ws=sheet.worksheet(dest_tab)
        existing=dest_ws.col_values(1)
        if job["efj"] in existing:
            print(f"    SKIP: {job['efj']} already in {dest_tab}"); return False
        dest_ws.append_row(row_data,value_input_option="RAW")
        print(f"    Archived to {dest_tab}")
        send_archive_email(tab_name,lookup,job)
        src_ws=sheet.worksheet(tab_name)
        src_ws.delete_rows(sheet_row)
        print(f"    Deleted row {sheet_row} from {tab_name}")
        return True
    except Exception as e:
        print(f"    WARNING: Archive failed: {e}"); return False
def run_once(account_lookup,ssl_links):
    now_str=datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    print(f"\n[{now_str}] Export poll cycle...")
    creds=_load_credentials()
    gc=gspread.authorize(creds)
    sheet=gc.open_by_key(SHEET_ID)
    account_tabs=get_account_tabs(sheet,account_lookup)
    if not account_tabs: print("  No account tabs found."); return
    print(f"  Tabs: {account_tabs}")
    state=load_state(); new_state=dict(state)

    for tab_name in account_tabs:
        print(f"\n  Checking {tab_name}...")
        try:
            ws=gc.open_by_key(SHEET_ID).worksheet(tab_name)
            rows=ws.get_all_values()
        except Exception as e: print(f"  ERROR: {e}"); continue
        exp=[(i+1,r) for i,r in enumerate(rows) if len(r)>COL_MOVE_TYPE and r[COL_MOVE_TYPE].strip().lower()=="dray export"]
        print(f"  Found {len(exp)} export row(s)")
        tab_alerts=[];note_updates=[];sheet_updates=[];archive_jobs=[]

        for sheet_row,row in exp:
            def g(col,r=row): return r[col].strip() if len(r)>col else ""
            efj=g(COL_EFJ);container=g(COL_CONTAINER);booking=g(COL_BOOKING)
            vessel=g(COL_VESSEL);carrier=g(COL_CARRIER);origin=g(COL_ORIGIN)
            dest=g(COL_DEST);erd=g(COL_ERD);cutoff=g(COL_CUTOFF);notes=g(COL_NOTES)
            key=f"{tab_name}:{efj}:{container}"
            print(f"\n  -> {efj}|{container} booking={booking} ERD={erd!r} Cutoff={cutoff!r}")
            prev=state.get(key,{})
            current={"erd":erd,"cutoff":cutoff,"cutoff_alerted":prev.get("cutoff_alerted","")}
            changed=[f.upper() for f in ("erd","cutoff") if current[f]!=prev.get(f,"")]
            if "CUTOFF" in changed:
                current["cutoff_alerted"]=""
            new_state[key]=current
            alert_reason=_cutoff_alert(cutoff) if cutoff else None
            if alert_reason and current["cutoff_alerted"]==cutoff:
                print(f"    Cutoff alert already sent for {cutoff} - skipping")
                alert_reason=None
            if changed or alert_reason:
                if alert_reason:
                    current["cutoff_alerted"]=cutoff
                    new_state[key]=current
                reason=alert_reason or f"Date change: {', '.join(changed)}"
                tab_alerts.append({"efj":efj,"container":container,"vessel":vessel,
                    "booking":booking,"erd":erd,"cutoff":cutoff,
                    "alert_reason":alert_reason,"changed":changed})
                today=datetime.now(ZoneInfo("America/New_York")).strftime("%m-%d %H:%M")
                note_updates.append((sheet_row,f"{reason} - {today}"))

            ssl_line=detect_ssl_line(vessel,carrier,ssl_links)
            if not ssl_line:
                print(f"    SSL line not detected for {vessel}/{carrier} - skipping API")
                continue

            if not _is_container_num(container):
                print(f"    Col C is booking# - calling BOL lookup...")
                found_container=jsoncargo_bol_lookup(booking,ssl_line)
                if found_container:
                    print(f"    Container# found: {found_container} - updating Col C")
                    sheet_updates.append({"range":f"C{sheet_row}","values":[[found_container]]})
                    send_container_assigned_email(tab_name,account_lookup,efj,booking,found_container)
                    today=datetime.now(ZoneInfo("America/New_York")).strftime("%m-%d %H:%M")
                    note_updates.append((sheet_row,f"Container# assigned: {found_container} - {today}"))
                    container=found_container
                else:
                    print(f"    No container# yet for {efj}")
                    continue

            print(f"    Tracking container# {container}...")
            track=jsoncargo_container_track(container,ssl_line)
            if not track:
                print(f"    No tracking data for {container}")
                continue
            if track["gate_in"]:
                print(f"    GATE IN: {track['gate_in']} - queuing archive")
                archive_jobs.append({"sheet_row":sheet_row,"row_data":row,
                    "efj":efj,"container":container,"booking":booking,
                    "vessel":vessel,"origin":origin,"dest":dest,
                    "erd":erd,"cutoff":cutoff,"gate_in_status":track["gate_in"]})
            else:
                print(f"    No gate-in yet for {container}")

        if sheet_updates:
            try: ws.batch_update(sheet_updates,value_input_option="RAW"); print(f"  Updated {len(sheet_updates)} Col C value(s)")
            except Exception as e: print(f"  WARNING: {e}")
        if note_updates:
            try: ws.batch_update([{"range":f"O{sr}","values":[[n]]} for sr,n in note_updates],value_input_option="RAW"); print(f"  Wrote {len(note_updates)} note(s)")
            except Exception as e: print(f"  WARNING: {e}")
        if archive_jobs:
            print(f"\n  Archiving {len(archive_jobs)} gate-in row(s)...")
            for job in sorted(archive_jobs,key=lambda j:j["sheet_row"],reverse=True):
                ok=archive_export_row(sheet,tab_name,job["sheet_row"],job["row_data"],job,account_lookup)
                if ok: new_state.pop(f"{tab_name}:{job['efj']}:{job['container']}",None)
        if tab_alerts:
            print(f"\n  Sending alert for {len(tab_alerts)} row(s)...")
            send_export_alert(tab_name,account_lookup,tab_alerts)
        else: print(f"  No alerts for {tab_name}")

    save_state(new_state)
    print("Export poll complete.")

def main():
    print("Export Monitor v2 started.")
    creds=_load_credentials()
    account_lookup=load_account_lookup(creds)
    ssl_links=load_ssl_links(creds)
    while True:
        run_once(account_lookup,ssl_links)
        print("  Sleeping 60 min...")
        time.sleep(POLL_INTERVAL)

if __name__=="__main__":
    import sys
    if "--once" in sys.argv:
        print("Export Monitor v2 — single run")
        creds = _load_credentials()
        account_lookup = load_account_lookup(creds)
        ssl_links = load_ssl_links(creds)
        run_once(account_lookup, ssl_links)
        print("Run complete.")
    else:
        main()
