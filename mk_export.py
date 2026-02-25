import textwrap, os
code = textwrap.dedent("""
    #!/usr/bin/env python3
    import json, os, smtplib, time, gspread
    from datetime import datetime
    from email.mime.multipart import MIMEMultipart
    from email.mime.text import MIMEText
    from zoneinfo import ZoneInfo
    from google.auth.transport.requests import Request as GoogleRequest
    from google.oauth2.service_account import Credentials
    SHEET_ID='19MB5HmmWwsVXY_nADCYYLJL-zWXYt8yWrfeRBSfB2S0'
    CREDENTIALS_FILE='/root/csl-credentials.json'
    STATE_FILE='/root/csl-bot/export_state.json'
    POLL_INTERVAL=3600
    SMTP_HOST='smtp.gmail.com'
    SMTP_PORT=587
    SMTP_USER='jfeltzjr@gmail.com'
    SMTP_PASSWORD='birxmwdoafjxhfdh'
    EMAIL_CC='efj-operations@evansdelivery.com'
    EMAIL_FALLBACK='efj-operations@evansdelivery.com'
    ACCOUNT_LOOKUP_TAB='Account Rep'
    SKIP_TABS={'Sheet 4','DTCELNJW','Account Rep','Completed Eli','Completed Radka'}
    COL_EFJ=0;COL_MOVE_TYPE=1;COL_CONTAINER=2;COL_BOOKING=3;COL_VESSEL=4
    COL_CARRIER=5;COL_ORIGIN=6;COL_ERD=8;COL_CUTOFF=9;COL_NOTES=14
    SCOPES=['https://www.googleapis.com/auth/spreadsheets','https://www.googleapis.com/auth/drive']
    RAIL_KEYWORDS=['rail','ramp','intermodal','train','bnsf','union pacific','csx']
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
            with open(STATE_FILE,'w') as f: json.dump(data,f,indent=2)
        except Exception as e: print(f'  WARNING: {e}')
    def load_account_lookup(creds):
        try:
            gc=gspread.authorize(creds)
            ws=gc.open_by_key(SHEET_ID).worksheet(ACCOUNT_LOOKUP_TAB)
            lookup={}
            for row in ws.get_all_values():
                if len(row)>=3 and row[0].strip():
                    a,r,e=row[0].strip(),row[1].strip(),row[2].strip()
                    if a and e: lookup[a]={'rep':r,'email':e}
            print(f'  Loaded {len(lookup)} account(s)')
            return lookup
        except Exception as e:
            print(f'  WARNING: {e}'); return {}
    def get_account_tabs(sheet,lookup):
        return [ws.title for ws in sheet.worksheets() if ws.title not in SKIP_TABS and ws.title in lookup]
    def _is_rail(vessel,origin,carrier):
        return any(kw in f'{vessel} {origin} {carrier}'.lower() for kw in RAIL_KEYWORDS)
    def _parse_date(s):
        s=s.strip()
        if not s: return None
        yr=datetime.now().year
        for fmt in ['%d-%b','%m-%d','%m/%d','%m/%d/%Y','%Y-%m-%d','%d-%b-%Y','%b %d','%B %d']:
            try:
                dt=datetime.strptime(s,fmt)
                if dt.year==1900: dt=dt.replace(year=yr)
                return dt
            except: continue
        return None
    def _cutoff_alert(s):
        dt=_parse_date(s)
        if not dt: return None
        now=datetime.now(ZoneInfo('America/New_York')).replace(tzinfo=None)
        diff=dt-now
        if diff.total_seconds()<0: return 'PAST CUTOFF'
        if diff.total_seconds()<=48*3600: return f'CUTOFF IN {int(diff.total_seconds()/3600)}hrs'
        return None
    def _send_email(to,cc,subject,body):
        from email.mime.multipart import MIMEMultipart
        from email.mime.text import MIMEText
        msg=MIMEMultipart('alternative')
        msg['Subject']=subject; msg['From']=SMTP_USER; msg['To']=to
        if cc and cc!=to: msg['Cc']=cc
        msg.attach(MIMEText(body,'plain'))
        rcpt=[to]+([cc] if cc and cc!=to else [])
        try:
            with smtplib.SMTP(SMTP_HOST,SMTP_PORT) as s:
                s.ehlo(); s.starttls(); s.login(SMTP_USER,SMTP_PASSWORD)
                s.sendmail(SMTP_USER,rcpt,msg.as_string())
            print(f'    Email sent to {to}')
        except Exception as e: print(f'    WARNING: Email failed: {e}')
    def send_alert(tab,lookup,alerts):
        if not alerts: return
        info=lookup.get(tab,{})
        rep=info.get('email','') or EMAIL_FALLBACK
        rep_name=info.get('rep','')
        cc=EMAIL_CC if rep!=EMAIL_FALLBACK else None
        now=datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %H:%M ET')
        subj=f'CSL Export Alert - {tab} - {now}'
        lines=[f'CSL Dray Export Update - {tab}',f'Generated: {now}']
        if rep_name: lines.append(f'Rep: {rep_name}')
        lines.append('')
        for a in alerts:
            lines+=[f"EFJ#:      {a['efj']}",f"Container: {a['container']}",
                    f"Vessel:    {a['vessel']}",f"Booking:   {a['booking']}",
                    f"ERD:       {a['erd'] or '-'}",f"Cutoff:    {a['cutoff'] or '-'}"]
            if a.get('alert_reason'): lines.append(f"Alert:     {a['alert_reason']}")
            if a.get('changed'): lines.append(f"Changed:   {', '.join(a['changed'])}")
            lines.append('')
        _send_email(rep,cc,subj,'\\n'.join(lines).strip())
    def run_once(lookup):
        now=datetime.now(ZoneInfo('America/New_York')).strftime('%Y-%m-%d %H:%M ET')
        print(f'\\n[{now}] Export poll cycle...')
        creds=_load_credentials()
        gc=gspread.authorize(creds)
        sheet=gc.open_by_key(SHEET_ID)
        tabs=get_account_tabs(sheet,lookup)
        if not tabs: print('  No tabs.'); return
        print(f'  Tabs: {tabs}')
        state=load_state(); new_state=dict(state)
        for tab in tabs:
            print(f'\\n  Checking {tab}...')
            try:
                ws=gc.open_by_key(SHEET_ID).worksheet(tab)
                rows=ws.get_all_values()
            except Exception as e: print(f'  ERROR: {e}'); continue
            exp=[(i+1,r) for i,r in enumerate(rows) if len(r)>COL_MOVE_TYPE and r[COL_MOVE_TYPE].strip().lower()=='dray export']
            print(f'  Found {len(exp)} export row(s)')
            alerts=[]; notes=[]
            for sr,row in exp:
                def g(c,r=row): return r[c].strip() if len(r)>c else ''
                efj=g(COL_EFJ); cont=g(COL_CONTAINER); book=g(COL_BOOKING)
                ves=g(COL_VESSEL); car=g(COL_CARRIER); org=g(COL_ORIGIN)
                erd=g(COL_ERD); cut=g(COL_CUTOFF); nts=g(COL_NOTES)
                key=f'{tab}:{efj}:{cont}'
                print(f'  -> {efj}|{cont} ERD={erd!r} Cutoff={cut!r}')
                if _is_rail(ves,org,car):
                    td=datetime.now(ZoneInfo('America/New_York')).strftime('%m-%d')
                    rn=f'Rail container - manual cutoff check needed ({td})'
                    if rn not in nts: notes.append((sr,rn)); print('    Flagged rail')
                    continue
                prev=state.get(key,{})
                cur={'erd':erd,'cutoff':cut}
                changed=[f.upper() for f in ('erd','cutoff') if cur[f]!=prev.get(f,'')]
                new_state[key]=cur
                ar=_cutoff_alert(cut) if cut else None
                if changed or ar:
                    reason=ar or f"Date change: {', '.join(changed)}"
                    print(f'    ALERT: {reason}')
                    alerts.append({'efj':efj,'container':cont,'vessel':ves,'booking':book,
                                   'erd':erd,'cutoff':cut,'alert_reason':ar,'changed':changed})
                    td=datetime.now(ZoneInfo('America/New_York')).strftime('%m-%d %H:%M')
                    notes.append((sr,f'{reason} - {td}'))
                else: print('    No changes')
            if notes:
                try:
                    ws.batch_update([{'range':f'O{sr}','values':[[n]]} for sr,n in notes],value_input_option='RAW')
                    print(f'  Wrote {len(notes)} note(s)')
                except Exception as e: print(f'  WARNING: {e}')
            if alerts: send_alert(tab,lookup,alerts)
            else: print(f'  No alerts for {tab}')
        save_state(new_state)
        print('Export poll complete.')
    def main():
        print('Export Monitor started.')
        creds=_load_credentials()
        lookup=load_account_lookup(creds)
        while True:
            run_once(lookup)
            print('  Sleeping 60 min...')
            time.sleep(POLL_INTERVAL)
    if __name__=='__main__':
        main()
""").lstrip()
with open('/root/csl-bot/export_monitor.py','w') as f:
    f.write(code)
print('Done -',len(code),'bytes')
