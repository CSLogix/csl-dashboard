#!/usr/bin/env python3
from flask import Flask,request,render_template_string
import gspread,os,io,csv,openpyxl,re
from datetime import datetime
from google.oauth2.service_account import Credentials
from google.auth.transport.requests import Request as GoogleRequest

SHEET_ID="19MB5HmmWwsVXY_nADCYYLJL-zWXYt8yWrfeRBSfB2S0"
CREDENTIALS_FILE="/root/csl-credentials.json"
SCOPES=["https://www.googleapis.com/auth/spreadsheets","https://www.googleapis.com/auth/drive"]
SKIP_TABS={"Sheet 4","Account Rep","Completed Eli","Completed Radka"}
app=Flask(__name__)

def _parse_pickup(s):
    if not s: return ''
    m=re.match(r'(\d{1,2})/(\d{1,2})\s+(\d{1,2})',s)
    if m:
        mo,dy,hr=m.group(1),m.group(2),int(m.group(3))
        suffix="AM" if hr<12 else "PM"
        hr12=hr if 1<=hr<=12 else (hr-12 if hr>12 else 12)
        return f"{int(mo):02d}-{int(dy):02d} {hr12:02d}:00 {suffix}"
    m2=re.match(r'(\d{1,2})-(\d{1,2})',s)
    if m2: return f"{int(m2.group(1)):02d}-{int(m2.group(2)):02d}"
    return s

def _load_creds():
    creds=Credentials.from_service_account_file(CREDENTIALS_FILE,scopes=SCOPES)
    creds.refresh(GoogleRequest())
    return creds
HTML_TOP="""<!DOCTYPE html>
<html><head><title>CSL Report Upload</title>
<style>
body{font-family:Arial,sans-serif;max-width:900px;margin:40px auto;padding:20px;background:#f5f5f5;}
h1{color:#2c3e50;}
.box{background:white;padding:30px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.1);margin-bottom:20px;}
.btn{background:#2c3e50;color:white;padding:12px 24px;border:none;border-radius:4px;cursor:pointer;font-size:16px;}
.btn:hover{background:#34495e;}
input[type=file]{margin:15px 0;padding:8px;width:100%;border:2px dashed #ccc;border-radius:4px;}
.success{background:#d4edda;border:1px solid #c3e6cb;color:#155724;padding:12px;border-radius:4px;margin-top:15px;}
.error{background:#f8d7da;border:1px solid #f5c6cb;color:#721c24;padding:12px;border-radius:4px;margin-top:15px;}
table{width:100%;border-collapse:collapse;margin-top:10px;}
th{background:#2c3e50;color:white;padding:8px;text-align:left;}
td{padding:8px;border-bottom:1px solid #ddd;}
.tag{display:inline-block;padding:2px 8px;border-radius:3px;font-size:12px;margin:1px;}
.tc{background:#d4edda;color:#155724;}
.td{background:#cce5ff;color:#004085;}
.te{background:#fff3cd;color:#856404;}
.tj{background:#f8d7da;color:#721c24;}
.tk{background:#e2d9f3;color:#432874;}
</style></head><body>
<div class="box">
<h1>CSL Report Upload</h1>
<p>Upload Excel (.xlsx) or CSV to auto-update Google Sheet by EFJ#.</p>
<p>
<span class="tag tc">C: Container#</span>
<span class="tag td">D: MBL#</span>
<span class="tag te">E: Vessel</span>
<span class="tag tj">J: LFD</span>
<span class="tag tk">K: Pickup</span>
&nbsp;&mdash; <em>Only empty cells updated</em>
</p>
<form method="POST" enctype="multipart/form-data" action="/upload">
<input type="file" name="report" accept=".xlsx,.csv" required>
<br><button class="btn" type="submit">Upload &amp; Update Sheet</button>
</form>
{% if message %}<div class="{{ msg_class }}">{{ message }}</div>{% endif %}
</div>"""

HTML_RESULTS="""{% if results %}
<div class="box"><h2>Results</h2>
<table><tr><th>EFJ#</th><th>Tab</th><th>Row</th><th>Updates</th></tr>
{% for r in results %}<tr>
<td>{{ r.efj }}</td><td>{{ r.tab }}</td><td>{{ r.row }}</td>
<td>{% for u in r.updates %}<span class="tag t{{ u.c }}">{{ u.col }}: {{ u.val }}</span>{% endfor %}
{% if not r.updates %}<em>no empty cells</em>{% endif %}</td>
</tr>{% endfor %}
</table></div>{% endif %}
{% if not_found %}
<div class="box"><h2>Not Found in Sheet</h2>
<ul>{% for e in not_found %}<li>{{ e }}</li>{% endfor %}</ul>
</div>{% endif %}
</body></html>"""

HTML=HTML_TOP+HTML_RESULTS

def parse_report(file_bytes,filename):
    report={}
    if filename.endswith('.xlsx'):
        wb=openpyxl.load_workbook(io.BytesIO(file_bytes))
        ws=wb.active
        rows=list(ws.iter_rows(values_only=True))
        start=0
        for i,row in enumerate(rows):
            if row and any(str(c or '').strip().upper() in ('REF#','EFJ#','EFJ') for c in row):
                start=i+1; break
        for row in rows[start:]:
            if not row or not row[0]: continue
            efj=str(row[0]).strip()
            if not efj.startswith('EFJ'): continue
            container=str(row[1]).strip() if row[1] else ''
            lfd=row[2]; pickup=row[3]
            mbl=str(row[12]).strip() if len(row)>12 and row[12] else ''
            vessel=str(row[13]).strip() if len(row)>13 and row[13] else ''
            if hasattr(lfd,'strftime'): lfd=lfd.strftime('%m-%d')
            elif lfd: lfd=str(lfd).strip()
            else: lfd=''
            if hasattr(pickup,'strftime'): pickup=pickup.strftime('%m-%d')
            elif pickup: pickup=_parse_pickup(str(pickup).strip())
            else: pickup=''
            report[efj]={'container':container,'lfd':lfd,'pickup':pickup,'mbl':mbl,'vessel':vessel}
    elif filename.endswith('.csv'):
        text=file_bytes.decode('utf-8-sig')
        reader=csv.reader(io.StringIO(text))
        rows=list(reader)
        start=0
        for i,row in enumerate(rows):
            if any(c.strip().upper() in ('REF#','EFJ#','EFJ') for c in row):
                start=i+1; break
        for row in rows[start:]:
            if not row or not row[0].strip().startswith('EFJ'): continue
            efj=row[0].strip()
            container=row[1].strip() if len(row)>1 else ''
            lfd=row[2].strip() if len(row)>2 else ''
            pickup=_parse_pickup(row[3].strip()) if len(row)>3 else ''
            mbl=row[12].strip() if len(row)>12 else ''
            vessel=row[13].strip() if len(row)>13 else ''
            report[efj]={'container':container,'lfd':lfd,'pickup':pickup,'mbl':mbl,'vessel':vessel}
    return report

@app.route('/',methods=['GET'])
def index():
    return render_template_string(HTML)

@app.route('/upload',methods=['POST'])
def upload():
    f=request.files.get('report')
    if not f or not f.filename:
        return render_template_string(HTML,message="No file selected.",msg_class="error")
    filename=f.filename.lower()
    if not (filename.endswith('.xlsx') or filename.endswith('.csv')):
        return render_template_string(HTML,message="Only .xlsx and .csv supported.",msg_class="error")
    try:
        file_bytes=f.read()
        report=parse_report(file_bytes,filename)
    except Exception as e:
        return render_template_string(HTML,message=f"Parse error: {e}",msg_class="error")
    if not report:
        return render_template_string(HTML,message="No EFJ# rows found.",msg_class="error")
    try:
        creds=_load_creds()
        gc=gspread.authorize(creds)
        sheet=gc.open_by_key(SHEET_ID)
    except Exception as e:
        return render_template_string(HTML,message=f"Sheets error: {e}",msg_class="error")
    results=[];found_efjs=set();total_updates=0
    for ws_tab in sheet.worksheets():
        if ws_tab.title in SKIP_TABS: continue
        try: rows=ws_tab.get_all_values()
        except: continue
        batch=[]
        for i,row in enumerate(rows):
            if not row: continue
            efj=row[0].strip()
            if efj not in report: continue
            r=report[efj];sheet_row=i+1;found_efjs.add(efj);row_updates=[]
            def chk(col,idx,val,c,b=batch,rw=row,sr=sheet_row,ru=row_updates):
                if val and (len(rw)<=idx or not rw[idx].strip()):
                    b.append({'range':f'{col}{sr}','values':[[val]]})
                    ru.append({'col':col,'val':val,'c':c})
            chk('C',2,r['container'],'c')
            chk('D',3,r['mbl'],'d')
            chk('E',4,r['vessel'],'e')
            chk('J',9,r['lfd'],'j')
            chk('K',10,r['pickup'],'k')
            results.append({'efj':efj,'tab':ws_tab.title,'row':sheet_row,'updates':row_updates})
            total_updates+=len(row_updates)
        if batch:
            try: ws_tab.batch_update(batch,value_input_option='RAW')
            except Exception as e:
                return render_template_string(HTML,message=f"Write error: {e}",msg_class="error")
    not_found=[e for e in report if e not in found_efjs]
    now=datetime.now().strftime("%Y-%m-%d %H:%M")
    msg=f"Done {now} - matched {len(found_efjs)} EFJ rows, updated {total_updates} cells."
    return render_template_string(HTML,message=msg,msg_class="success",
        results=results,not_found=not_found,total_updates=total_updates)


@app.route('/upload-pdf-test', methods=['GET','POST'])
def upload_pdf_test():
    if request.method=='POST':
        f=request.files.get('pdf')
        if f:
            f.save('/tmp/test_pod.pdf')
            import subprocess
            result=subprocess.run(['python3','/tmp/test_pdf_parse.py'],capture_output=True,text=True)
            return f'<pre>{result.stdout}\n{result.stderr}</pre>'
        return 'No file'
    return '''<form method="POST" enctype="multipart/form-data">
    <input type="file" name="pdf">
    <button type="submit">Upload & Parse</button>
    </form>'''


@app.route('/macropoint', methods=['GET','POST'])
def macropoint_page():
    import pdfplumber, re, json, subprocess
    from google.oauth2.service_account import Credentials
    from google.auth.transport.requests import Request as GoogleRequest

    parsed = None
    error  = None
    print(f'DEBUG macropoint: method={request.method} form_keys={list(request.form.keys())} files={list(request.files.keys())}')

    if request.method == 'POST' and 'create' not in request.form and 'pdf' in request.files:
        f = request.files['pdf']
        pdf_bytes = f.read()
        try:
            import io
            with pdfplumber.open(io.BytesIO(pdf_bytes)) as pdf:
                text = "\n".join(p.extract_text() for p in pdf.pages if p.extract_text())

            def _get(pattern, txt, flags=0, grp=1):
                m = re.search(pattern, txt, flags)
                return m.group(grp).strip() if m else ""

            efj       = _get(r"Order\s+(EFJ\d+)", text)
            pro       = _get(r"PRO\s*#\s*(\d+)", text, re.I)
            tab       = _get(r"Reference\s*#4.+?Reference\s*#5.+?Reference\s*#6\s*\n(.+?)(?:\n|$)", text, re.I|re.S)
            p_name    = _get(r"^(\S+)\s+\S+\s*$", text, re.M)
            m2        = re.search(r"^(\S+)\s+(\S+)\s*$", text, re.M)
            p_name    = m2.group(1) if m2 else ""
            d_name    = m2.group(2) if m2 else ""
            p_appt    = _get(r"Appointment:\s*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})", text)
            d_appt    = _get(r"Delivery Appointment:\s*(\d{2}/\d{2}/\d{4}\s+\d{2}:\d{2})", text)

            addr_m = re.search(r"(\d+\s+\w.+?)\s+(\d+\s+\w.+?)\s+Weight:\s*\d+", text)
            city_m = re.search(r"([A-Z][A-Z ]+,\s*[A-Z]{2}\s*\d{5})\s+([A-Z][A-Z ]+,\s*[A-Z]{2}\s*\d{5})", text)

            p_addr = addr_m.group(1).strip().split("\n")[-1].strip() if addr_m else ""
            d_addr = addr_m.group(2).strip().split("\n")[-1].strip() if addr_m else ""

            def parse_city(s):
                m = re.match(r"(.+),\s*([A-Z]{2})\s*(\d{5})", s.strip())
                return (m.group(1), m.group(2), m.group(3)) if m else (s, "", "")

            p_city, p_state, p_zip = parse_city(city_m.group(1)) if city_m else ("","","")
            d_city, d_state, d_zip = parse_city(city_m.group(2)) if city_m else ("","","")

            parsed = {
                "efj": efj, "pro": pro, "tab": tab,
                "pickup_name": p_name, "pickup_addr": p_addr,
                "pickup_city": p_city, "pickup_state": p_state, "pickup_zip": p_zip,
                "pickup_appt": p_appt,
                "delivery_name": d_name, "delivery_addr": d_addr,
                "delivery_city": d_city, "delivery_state": d_state, "delivery_zip": d_zip,
                "delivery_appt": d_appt,
            }
        except Exception as e:
            error = str(e)

    if request.method == 'POST' and 'create' in request.form:
        import json, subprocess, gspread
        data = {
            "efj":           request.form.get("efj"),
            "pro":           request.form.get("pro"),
            "tab":           request.form.get("tab"),
            "pickup_name":   request.form.get("pickup_name"),
            "pickup_addr":   request.form.get("pickup_addr"),
            "pickup_city":   request.form.get("pickup_city"),
            "pickup_state":  request.form.get("pickup_state"),
            "pickup_zip":    request.form.get("pickup_zip"),
            "pickup_appt":   request.form.get("pickup_appt"),
            "pickup_type":   request.form.get("pickup_type"),
            "delivery_name": request.form.get("delivery_name"),
            "delivery_addr": request.form.get("delivery_addr"),
            "delivery_city": request.form.get("delivery_city"),
            "delivery_state":request.form.get("delivery_state"),
            "delivery_zip":  request.form.get("delivery_zip"),
            "delivery_appt": request.form.get("delivery_appt"),
            "delivery_type": request.form.get("delivery_type"),
        }
        args = json.dumps({"data": data})
        result = subprocess.run(
            ["python3", "/root/csl-bot/macropoint_creator.py", args],
            capture_output=True, text=True, timeout=180
        )
        print("MP stdout:", result.stdout[-500:])
        print("MP stderr:", result.stderr[-200:])
        try:
            out = json.loads(result.stdout.strip().split("\n")[-1])
        except:
            out = {"status": "error", "error": result.stdout[-300:] + result.stderr[-200:]}

        if out.get("status") == "success":
            tracking_url = out["url"]
            try:
                creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
                creds.refresh(GoogleRequest())
                gc  = gspread.authorize(creds)
                sh  = gc.open_by_key(SHEET_ID)
                tab_name = data["tab"]
                efj = data["efj"]
                pro = data["pro"]
                ws  = sh.worksheet(tab_name)
                rows = ws.get_all_values()
                for i, row in enumerate(rows):
                    if row and row[0].strip() == efj:
                        ws.update_cell(i+1, 3, f'=HYPERLINK("{tracking_url}","{pro}")')
                        break
            except Exception as e:
                return render_template_string(MP_HTML, parsed=None, error=f"Sheet update failed: {e}", success=None, otp_required=False, form_data=None)
            return render_template_string(MP_HTML, parsed=None, error=None, success=tracking_url, otp_required=False, form_data=None)
        else:
            return render_template_string(MP_HTML, parsed=None, error=out.get("error","Unknown error"), success=None, otp_required=False, form_data=None)

    return render_template_string(MP_HTML, parsed=parsed, error=error, success=None, otp_required=False, form_data=None)

MP_HTML = """<!DOCTYPE html>
<html><head><title>Create Macropoint</title>
<style>
body{font-family:Arial,sans-serif;max-width:900px;margin:40px auto;padding:20px;background:#f5f5f5;}
h1{color:#2c3e50;}
.box{background:white;padding:30px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.1);margin-bottom:20px;}
.btn{background:#2c3e50;color:white;padding:12px 24px;border:none;border-radius:4px;cursor:pointer;font-size:16px;margin-top:10px;}
.btn:hover{background:#34495e;}
.btn-green{background:#27ae60;} .btn-green:hover{background:#219a52;}
input[type=file]{margin:15px 0;padding:8px;width:100%;border:2px dashed #ccc;border-radius:4px;}
input[type=text]{width:100%;padding:8px;margin:4px 0 12px;border:1px solid #ccc;border-radius:4px;box-sizing:border-box;}
select{width:100%;padding:8px;margin:4px 0 12px;border:1px solid #ccc;border-radius:4px;}
.row{display:grid;grid-template-columns:1fr 1fr;gap:20px;}
.success{background:#d4edda;border:1px solid #c3e6cb;color:#155724;padding:12px;border-radius:4px;}
.error{background:#f8d7da;border:1px solid #f5c6cb;color:#721c24;padding:12px;border-radius:4px;}
label{font-weight:bold;font-size:13px;color:#555;}
h3{color:#2c3e50;border-bottom:2px solid #eee;padding-bottom:8px;}
</style></head><body>
<div class="box">
<h1>🚛 Create Macropoint</h1>
<p>Upload a BOL/POD PDF to auto-fill and create a Macropoint shipment.</p>
{% if success %}
<div class="success">✅ Macropoint created! Tracking URL written to sheet.<br><a href="{{ success }}" target="_blank">{{ success }}</a></div>
{% endif %}
{% if error %}<div class="error">❌ {{ error }}</div>{% endif %}
{% if otp_required %}
<div class="success" style="background:#fff3cd;border-color:#ffc107;color:#856404;">
📱 Macropoint sent a one-time password to your phone. Enter it below:
</div>
<form method="POST">
{% for k,v in form_data.items() %}
<input type="hidden" name="{{ k }}" value="{{ v }}">
{% endfor %}
<input type="hidden" name="create" value="1">
<div style="margin:15px 0;">
<label style="font-weight:bold;">One-Time Password (OTP)</label>
<input type="text" name="otp" placeholder="Enter OTP from your phone" style="width:300px;padding:10px;font-size:18px;letter-spacing:4px;margin-top:8px;border:2px solid #ffc107;border-radius:4px;">
</div>
<button class="btn btn-green" type="submit">✅ Submit OTP & Create Shipment</button>
</form>
{% endif %}
{% if not parsed and not otp_required %}
<form method="POST" enctype="multipart/form-data">
<input type="file" name="pdf">
<button class="btn" type="submit">Parse PDF</button>
</form>
{% endif %}
</div>

{% if parsed %}
<form method="POST">
<div class="box">
<h3>Parsed Data — Review & Confirm</h3>
<div class="row">
<div><label>EFJ#</label><input type="text" name="efj" value="{{ parsed.efj }}"></div>
<div><label>PRO# (Load ID)</label><input type="text" name="pro" value="{{ parsed.pro }}"></div>
</div>
<div><label>Sheet Tab (from Ref#5)</label><input type="text" name="tab" value="{{ parsed.tab }}"></div>
</div>

<div class="box">
<h3>📍 Pickup Stop</h3>
<div class="row">
<div><label>Stop Name</label><input type="text" name="pickup_name" value="{{ parsed.pickup_name }}"></div>
<div><label>Stop Type</label><select name="pickup_type">
<option value="appointment">Appointment</option>
<option value="fcfs">FCFS</option>
</select></div>
</div>
<div><label>Address</label><input type="text" name="pickup_addr" value="{{ parsed.pickup_addr }}"></div>
<div class="row">
<div><label>City</label><input type="text" name="pickup_city" value="{{ parsed.pickup_city }}"></div>
<div><label>State</label><input type="text" name="pickup_state" value="{{ parsed.pickup_state }}"></div>
</div>
<div class="row">
<div><label>Zip</label><input type="text" name="pickup_zip" value="{{ parsed.pickup_zip }}"></div>
<div><label>Appointment Date/Time</label><input type="text" name="pickup_appt" value="{{ parsed.pickup_appt }}"></div>
</div>
</div>

<div class="box">
<h3>📍 Delivery Stop</h3>
<div class="row">
<div><label>Stop Name</label><input type="text" name="delivery_name" value="{{ parsed.delivery_name }}"></div>
<div><label>Stop Type</label><select name="delivery_type">
<option value="appointment">Appointment</option>
<option value="fcfs">FCFS</option>
</select></div>
</div>
<div><label>Address</label><input type="text" name="delivery_addr" value="{{ parsed.delivery_addr }}"></div>
<div class="row">
<div><label>City</label><input type="text" name="delivery_city" value="{{ parsed.delivery_city }}"></div>
<div><label>State</label><input type="text" name="delivery_state" value="{{ parsed.delivery_state }}"></div>
</div>
<div class="row">
<div><label>Zip</label><input type="text" name="delivery_zip" value="{{ parsed.delivery_zip }}"></div>
<div><label>Appointment Date/Time</label><input type="text" name="delivery_appt" value="{{ parsed.delivery_appt }}"></div>
</div>
</div>

<div class="box">
<button class="btn btn-green" type="submit" name="create" value="1">🚛 Create Macropoint & Update Sheet</button>
</div>
</form>
{% endif %}
</body></html>"""


@app.route('/mp-login', methods=['GET','POST'])
def mp_login():
    message = None
    error = None
    if request.method == 'POST':
        import subprocess
        otp = request.form.get('otp','').strip()
        if otp:
            result = subprocess.run(
                ['python3', '/root/csl-bot/mp_login_save.py', otp],
                capture_output=True, text=True, timeout=60
            )
            if 'Saved' in result.stdout:
                message = '✅ Session saved successfully! You can now create Macropoint shipments.'
            else:
                error = result.stdout + result.stderr
        else:
            # Step 1: trigger login to get OTP sent
            result = subprocess.run(
                ['python3', '-c', """
import sys
sys.path.insert(0,'/root/csl-bot')
from playwright.sync_api import sync_playwright
with sync_playwright() as p:
    browser = p.chromium.launch(headless=True)
    page = browser.new_page()
    page.goto('https://visibility.macropoint.com/', timeout=30000)
    page.wait_for_load_state('networkidle', timeout=20000)
    page.fill('input[name="UserName"]', 'john.feltz@evansdelivery.com')
    page.click('input[id="UsernameNext"]')
    page.wait_for_timeout(2000)
    page.fill('input[name="Password"]', 'MFdoom1131@1')
    page.click('input[id="Login"]')
    page.wait_for_load_state('networkidle', timeout=20000)
    print('OTP_SENT' if 'Otp' in page.url or 'TwoFactor' in page.url else 'NO_OTP')
    browser.close()
"""],
                capture_output=True, text=True, timeout=60
            )
            if 'OTP_SENT' in result.stdout:
                message = 'otp_sent'
            else:
                error = 'Login failed: ' + result.stdout + result.stderr

    return render_template_string("""<!DOCTYPE html>
<html><head><title>MP Login</title>
<style>
body{font-family:Arial,sans-serif;max-width:500px;margin:80px auto;padding:20px;background:#f5f5f5;}
.box{background:white;padding:30px;border-radius:8px;box-shadow:0 2px 8px rgba(0,0,0,0.1);}
.btn{background:#27ae60;color:white;padding:12px 24px;border:none;border-radius:4px;cursor:pointer;font-size:16px;width:100%;margin-top:10px;}
input[type=text]{width:100%;padding:10px;margin:10px 0;border:1px solid #ccc;border-radius:4px;box-sizing:border-box;font-size:18px;letter-spacing:4px;}
.success{background:#d4edda;border:1px solid #c3e6cb;color:#155724;padding:12px;border-radius:4px;margin:10px 0;}
.error{background:#f8d7da;border:1px solid #f5c6cb;color:#721c24;padding:12px;border-radius:4px;margin:10px 0;}
.info{background:#d1ecf1;border:1px solid #bee5eb;color:#0c5460;padding:12px;border-radius:4px;margin:10px 0;}
</style></head><body>
<div class="box">
<h2>🔐 Macropoint Login</h2>
{% if message %}
<div class="success">{{ message }}</div>
<a href="/macropoint">← Back to Create Macropoint</a>
{% elif error %}
<div class="error">❌ {{ error }}</div>
<form method="POST">
<div class="info">📱 Enter the OTP sent to your phone:</div>
<input type="text" name="otp" placeholder="Enter OTP" autofocus>
<button class="btn" type="submit">✅ Verify & Save Session</button>
</form>
{% else %}
<div class="info">📱 Click below — Macropoint will send an OTP to your phone. Then enter it here.</div>
<form method="POST">
<input type="text" name="otp" placeholder="Enter OTP from phone" autofocus>
<button class="btn" type="submit">✅ Login & Save Session</button>
</form>
{% endif %}
</div>
</body></html>""", message=message, error=error)

if __name__=='__main__':
    app.run(host='0.0.0.0',port=5001,debug=False)


@app.route('/upload-pdf-test', methods=['GET','POST'])
def upload_pdf_test():
    if request.method=='POST':
        f=request.files.get('pdf')
        if f:
            f.save('/tmp/test_pod.pdf')
            import subprocess
            result=subprocess.run(['python3','/tmp/test_pdf_parse.py'],capture_output=True,text=True)
            return f'<pre>{result.stdout}\n{result.stderr}</pre>'
        return 'No file'
    return '''<form method="POST" enctype="multipart/form-data">
    <input type="file" name="pdf" >
    <button type="submit">Upload & Parse</button>
    </form>'''
