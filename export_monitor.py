#!/usr/bin/env python3
import json,os,smtplib,time,re,requests,gspread
from datetime import datetime
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from zoneinfo import ZoneInfo
from google.auth.transport.requests import Request as GoogleRequest
from google.oauth2.service_account import Credentials

SHEET_ID="19MB5HmmWwsVXY_nADCYYLJL-zWXYt8yWrfeRBSfB2S0"
CREDENTIALS_FILE="/root/csl-credentials.json"
STATE_FILE="/root/csl-bot/export_state.json"
POLL_INTERVAL=3600
SMTP_HOST="smtp.gmail.com"
SMTP_PORT=587
SMTP_USER="jfeltzjr@gmail.com"
SMTP_PASSWORD="birxmwdoafjxhfdh"
EMAIL_CC="efj-operations@evansdelivery.com"
EMAIL_FALLBACK="efj-operations@evansdelivery.com"
ACCOUNT_LOOKUP_TAB="Account Rep"
SKIP_TABS={"Sheet 4","DTCELNJW","Account Rep","Completed Eli","Completed Radka"}
COL_EFJ=0;COL_MOVE_TYPE=1;COL_CONTAINER=2;COL_BOOKING=3;COL_VESSEL=4
COL_CARRIER=5;COL_ORIGIN=6;COL_DEST=7;COL_ERD=8;COL_CUTOFF=9;COL_NOTES=14
SCOPES=["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
RAIL_KEYWORDS=["rail","ramp","intermodal","train","bnsf","union pacific","csx"]
GATE_IN_STATUSES=["full load on rail for export","gate in full","full in","received for export transfer","loaded on vessel","vessel departure"]
JSONCARGO_API_KEY="wiD6ZZoQLstkmQl4nRsGTYwe93cr_cpHboDTu15VLRQ"
JSONCARGO_BASE="https://api.jsoncargo.com/api/v1"
SSL_LINE_MAP={"cma":{"name":"CMA_CGM"},"cgm":{"name":"CMA_CGM"},"maersk":{"name":"MAERSK"},"hapag":{"name":"HAPAG_LLOYD"},"msc":{"name":"MSC"},"evergreen":{"name":"EVERGREEN"},"one":{"name":"ONE"},"cosco":{"name":"COSCO"},"zim":{"name":"ZIM"},"yang ming":{"name":"YANG_MING"},"hmm":{"name":"HMM"}}

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
        with open(STATE_FILE,"w") as f: json.dump(data,f,indent=2)
    except Exception as e: print(f"  WARNING: {e}")

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

def detect_ssl_line(vessel,carrier):
    combined=f"{vessel} {carrier}".lower()
    for key,val in SSL_LINE_MAP.items():
        if key in combined: return val["name"]
    return None
def jsoncargo_bol_lookup(booking_num, ssl_line):
    try:
        url=f"{JSONCARGO_BASE}/containers/bol/{booking_num}/"
        resp=requests.get(url,headers={"x-api-key":JSONCARGO_API_KEY},
                         params={"shipping_line":ssl_line},timeout=20)
        data=resp.json()
        if "data" in data:
            containers=data["data"].get("associated_container_numbers",[])
            if containers:
                print(f"    BOL lookup: found containers {containers}")
                return containers[0]
        print(f"    BOL lookup: {data.get('error',{}).get('title','no result')}")
        return None
    except Exception as e:
        print(f"    BOL lookup error: {e}"); return None

def jsoncargo_container_track(container_num, ssl_line):
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
        return {"events":events,"gate_in":gate_in}
    except Exception as e:
        print(f"    Container track error: {e}"); return None

def _send_email(to,cc,subject,body):
    msg=MIMEMultipart("alternative")
    msg["Subject"]=subject;msg["From"]=SMTP_USER;msg["To"]=to
    if cc and cc!=to: msg["Cc"]=cc
    msg.attach(MIMEText(body,"plain"))
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
    lines=[f"CSL Dray Export Update - {tab_name}",f"Generated: {now}"]
    if rep_name: lines.append(f"Rep: {rep_name}")
    lines.append("")
    for a in alerts:
        lines+=[f"EFJ#:      {a['efj']}",f"Container: {a['container']}",
                f"Vessel:    {a['vessel']}",f"Booking:   {a['booking']}",
                f"ERD:       {a.get('erd') or '-'}",f"Cutoff:    {a.get('cutoff') or '-'}"]
        if a.get("alert_reason"): lines.append(f"Alert:     {a['alert_reason']}")
        if a.get("changed"): lines.append(f"Changed:   {', '.join(a['changed'])}")
        lines.append("")
    _send_email(rep,cc,subj,"\n".join(lines).strip())

def send_container_assigned_email(tab_name,lookup,efj,booking,container_num):
    info=lookup.get(tab_name,{})
    rep=info.get("email","") or EMAIL_FALLBACK
    rep_name=info.get("rep","")
    cc=EMAIL_CC if rep!=EMAIL_FALLBACK else None
    now=datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    subj=f"CSL Export - Container # Assigned | {efj} | {container_num}"
    lines=[f"Container Number Assigned",f"Updated: {now}","",
           f"EFJ#:      {efj}",
           f"Booking#:  {booking}",
           f"Container: {container_num}"]
    if rep_name: lines.insert(2,f"Rep: {rep_name}")
    _send_email(rep,cc,subj,"\n".join(lines).strip())

def send_archive_email(tab_name,lookup,job):
    info=lookup.get(tab_name,{})
    rep=info.get("email","") or EMAIL_FALLBACK
    rep_name=info.get("rep","")
    cc=EMAIL_CC if rep!=EMAIL_FALLBACK else None
    now=datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M ET")
    subj=f"CSL Export Archived | {job['efj']} | {job['container']} | Gate In"
    lines=["CSL Dray Export - Gate In Confirmed",f"Archived: {now}","",
           f"EFJ#:      {job['efj']}",f"Container: {job['container']}",
           f"Booking:   {job['booking']}",f"Vessel:    {job['vessel']}",
           f"Origin:    {job['origin']}",f"Dest:      {job['dest']}",
           f"ERD:       {job.get('erd') or '-'}",f"Cutoff:    {job.get('cutoff') or '-'}",
           f"Gate In:   {job['gate_in_status']}"]
    if rep_name: lines.insert(2,f"Rep: {rep_name}")
    _send_email(rep,cc,subj,"\n".join(lines).strip())

def archive_export_row(sheet,tab_name,sheet_row,row_data,job,lookup):
    try:
        info=lookup.get(tab_name,{})
        rep_name=info.get("rep","").lower()
        dest_tab="Completed Radka" if "radka" in rep_name else "Completed Eli"
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
def run_once(account_lookup):
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
            current={"erd":erd,"cutoff":cutoff}
            changed=[f.upper() for f in ("erd","cutoff") if current[f]!=prev.get(f,"")]
            new_state[key]=current
            alert_reason=_cutoff_alert(cutoff) if cutoff else None
            if changed or alert_reason:
                reason=alert_reason or f"Date change: {', '.join(changed)}"
                print(f"    ALERT: {reason}")
                tab_alerts.append({"efj":efj,"container":container,"vessel":vessel,
                    "booking":booking,"erd":erd,"cutoff":cutoff,
                    "alert_reason":alert_reason,"changed":changed})
                today=datetime.now(ZoneInfo("America/New_York")).strftime("%m-%d %H:%M")
                note_updates.append((sheet_row,f"{reason} - {today}"))

            ssl_line=detect_ssl_line(vessel,carrier)
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
    while True:
        run_once(account_lookup)
        print("  Sleeping 60 min...")
        time.sleep(POLL_INTERVAL)

if __name__=="__main__":
    main()
