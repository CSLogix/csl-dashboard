"""Patch app.py: Add Invoiced column + redesign rep dashboard with account breakdown."""

APP_FILE = '/root/csl-bot/csl-doc-tracker/app.py'

with open(APP_FILE, 'r') as f:
    code = f.read()

# 1. Add "invoiced" to COL mapping (column Q = index 16)
code = code.replace(
    '"status": 12, "notes": 13, "bot_alert": 14, "return_port": 15,',
    '"status": 12, "notes": 13, "bot_alert": 14, "return_port": 15, "invoiced": 16,'
)

# 2. Add "invoiced" to shipment dict in _do_refresh
code = code.replace(
    '"bot_alert": cell("bot_alert"), "return_port": cell("return_port"),',
    '"bot_alert": cell("bot_alert"), "return_port": cell("return_port"), "invoiced": cell("invoiced"),'
)

# 3. Add "invoiced" to the api_load_detail response
code = code.replace(
    '"return_port": shipment["return_port"],\n        "rep": shipment["rep"],',
    '"return_port": shipment["return_port"],\n        "rep": shipment["rep"],\n        "invoiced": shipment.get("invoiced", ""),',
)

# 4. Replace the entire rep_dashboard function
old_rep_route = '''# ---------------------------------------------------------------------------
# Rep Dashboard
# ---------------------------------------------------------------------------
@app.get("/rep/{rep_name}", response_class=HTMLResponse)
def rep_dashboard(rep_name: str):'''

# Find the end of the rep_dashboard function (ends before @app.on_event("startup"))
old_end = '\n\n@app.on_event("startup")'

# Extract the old rep_dashboard function
start_idx = code.index(old_rep_route)
end_idx = code.index(old_end, start_idx)
old_rep_function = code[start_idx:end_idx]

new_rep_function = r'''# ---------------------------------------------------------------------------
# Rep Dashboard — broken down by account
# ---------------------------------------------------------------------------
@app.get("/rep/{rep_name}", response_class=HTMLResponse)
def rep_dashboard(rep_name: str):
    """Dedicated dashboard for a specific rep, broken down by account."""
    sheet_cache.refresh_if_needed()

    # Filter shipments for this rep
    rep_shipments = [s for s in sheet_cache.shipments if s.get("rep", "Unassigned") == rep_name]
    if not rep_shipments:
        body = f"""{_sidebar("dashboard")}
<div class="main">
  {_topbar(rep_name, "Dashboard", search=False)}
  <div class="content">
    <div style="padding:48px;text-align:center;color:var(--text-dim);">No loads found for {rep_name}</div>
  </div>
</div>"""
        return HTMLResponse(_page(f"{rep_name} - CSL Dispatch", body))

    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")

    # --- Compute overall rep stats ---
    total_active = total_risk = total_sched = total_unbilled = 0
    account_data = {}  # account -> {active, at_risk, on_sched, unbilled, shipments}

    for s in rep_shipments:
        sl = s["status"].lower()
        is_done = any(w in sl for w in ("delivered", "completed", "empty return"))
        if is_done:
            continue

        acct = s["account"]
        if acct not in account_data:
            account_data[acct] = {"active": 0, "at_risk": 0, "on_sched": 0, "unbilled": 0, "shipments": []}

        account_data[acct]["active"] += 1
        account_data[acct]["shipments"].append(s)
        total_active += 1

        risk = False
        if s["lfd"] and s["lfd"][:10] <= tomorrow:
            risk = True
        if not s["eta"] and not s["status"]:
            risk = True
        if risk:
            account_data[acct]["at_risk"] += 1
            total_risk += 1
        else:
            account_data[acct]["on_sched"] += 1
            total_sched += 1

        inv = s.get("invoiced", "").strip().lower()
        if inv not in ("yes", "y", "invoiced", "billed"):
            account_data[acct]["unbilled"] += 1
            total_unbilled += 1

    info = REP_STYLES.get(rep_name, {"color": "var(--accent-blue)", "bg": "linear-gradient(135deg,#3b82f6,#2563eb)", "initials": "??"})

    # --- Stats toolbar ---
    stats_html = f"""<div class="stats-grid" style="grid-template-columns:repeat(4,1fr);">
  <div class="stat-card blue"><div class="stat-label">Active Loads</div><div class="stat-value">{total_active}</div><div class="stat-sub">Across {len(account_data)} accounts</div></div>
  <div class="stat-card red"><div class="stat-label">At Risk</div><div class="stat-value">{total_risk}</div><div class="stat-sub">LFD soon or no data</div></div>
  <div class="stat-card green"><div class="stat-label">On Schedule</div><div class="stat-value">{total_sched}</div><div class="stat-sub">{round(total_sched / total_active * 100) if total_active else 0}% of active</div></div>
  <div class="stat-card amber"><div class="stat-label">Unbilled</div><div class="stat-value">{total_unbilled}</div><div class="stat-sub">Not yet invoiced</div></div>
</div>"""

    # --- Account sections ---
    accounts_html = ""
    for acct_name in sorted(account_data.keys(), key=lambda a: account_data[a]["active"], reverse=True):
        ad = account_data[acct_name]

        # Account header with mini stats
        accounts_html += f"""<div class="panel" style="margin-bottom:20px;">
  <div class="panel-header" style="cursor:pointer;" onclick="this.parentElement.querySelector('.acct-body').classList.toggle('collapsed')">
    <div class="panel-title">
      <a href="/shipments?account={acct_name}" style="color:var(--text-primary);text-decoration:none;">{acct_name}</a>
      <span style="font-family:'JetBrains Mono',monospace;font-size:11px;font-weight:400;color:var(--text-dim);margin-left:8px;">{ad['active']} loads</span>
    </div>
    <div style="display:flex;gap:16px;font-family:'JetBrains Mono',monospace;font-size:11px;">
      <span style="color:var(--accent-red);">{ad['at_risk']} risk</span>
      <span style="color:var(--accent-green);">{ad['on_sched']} on sched</span>
      <span style="color:var(--accent-amber);">{ad['unbilled']} unbilled</span>
    </div>
  </div>
  <div class="acct-body">
    <div class="table-wrap">
      <table>
        <thead><tr><th>EFJ #</th><th>Container</th><th>Status</th><th>ETA</th><th>LFD</th><th>Type</th><th>Invoiced</th></tr></thead>
        <tbody>"""

        for s in ad["shipments"]:
            sl = s["status"].lower()
            lfd_style = ""
            if s["lfd"] and s["lfd"][:10] <= tomorrow:
                lfd_style = ' style="color:var(--accent-red);font-weight:600"'

            status_color = "var(--accent-green)"
            if "at port" in sl or "available" in sl:
                status_color = "var(--accent-amber)"
            elif "in transit" in sl or "on vessel" in sl:
                status_color = "var(--accent-blue)"
            elif "out for" in sl or "picked up" in sl:
                status_color = "var(--accent-cyan)"

            inv_val = s.get("invoiced", "").strip()
            inv_display = f'<span style="color:var(--accent-green);font-weight:600;">Yes</span>' if inv_val.lower() in ("yes", "y", "invoiced", "billed") else '<span style="color:var(--accent-amber);">No</span>'

            efj_link = f'<a href="javascript:void(0)" onclick="openPanel(\'{s["efj"]}\')" style="color:var(--accent-blue);cursor:pointer;">{s["efj"]}</a>'

            accounts_html += f"""<tr>
  <td>{efj_link}</td>
  <td style="font-family:JetBrains Mono,monospace;font-size:12px">{s['container']}</td>
  <td><span style="color:{status_color}">{s['status'] or '-'}</span></td>
  <td>{s['eta'] or '-'}</td>
  <td{lfd_style}>{s['lfd'] or '-'}</td>
  <td>{s['move_type'] or '-'}</td>
  <td>{inv_display}</td>
</tr>"""

        accounts_html += """</tbody>
      </table>
    </div>
  </div>
</div>"""

    # --- Alerts ---
    rep_alerts = _generate_alerts(rep_shipments, limit=10)
    alerts_html = _build_alerts_html(rep_alerts)

    # --- Panel HTML ---
    panel_html = """
<div class="detail-overlay" id="detail-overlay" onclick="closePanel()"></div>
<div class="detail-panel" id="detail-panel">
  <button class="panel-close" onclick="closePanel()">&times;</button>
  <div id="panel-content"><div class="panel-loading">Select a shipment to view details</div></div>
</div>"""

    body = f"""{_sidebar("dashboard")}
<div class="main">
  {_topbar(rep_name, "Dashboard", search=False)}
  <div class="content">
    <div style="display:flex;align-items:center;gap:16px;margin-bottom:24px;">
      <div style="width:48px;height:48px;border-radius:14px;background:{info['bg']};display:flex;align-items:center;justify-content:center;font-weight:700;font-size:18px;color:#fff;">{info['initials']}</div>
      <div>
        <h2 style="font-size:22px;font-weight:700;">{rep_name}</h2>
        <div style="font-size:13px;color:var(--text-secondary);">{', '.join(sorted(account_data.keys()))}</div>
      </div>
      <a href="/" style="margin-left:auto;font-size:12px;color:var(--text-secondary);border:1px solid var(--border);padding:6px 14px;border-radius:8px;">&larr; Back to Overview</a>
    </div>
    {stats_html}
    {alerts_html}
    <div style="margin-top:20px;">
      <h3 style="font-size:16px;font-weight:700;margin-bottom:16px;">Loads by Account</h3>
      {accounts_html}
    </div>
  </div>
</div>
{panel_html}"""

    interactive_js = r"""
function openPanel(efj) {
  if (!efj) return;
  document.getElementById('detail-panel').classList.add('open');
  document.getElementById('detail-overlay').classList.add('open');
  loadPanel(efj);
}
function closePanel() {
  document.getElementById('detail-panel').classList.remove('open');
  document.getElementById('detail-overlay').classList.remove('open');
}
document.addEventListener('keydown', function(e) { if (e.key === 'Escape') closePanel(); });

async function loadPanel(efj) {
  var pc = document.getElementById('panel-content');
  pc.innerHTML = '<div class="panel-loading">Loading ' + efj + '...</div>';
  try {
    var res = await fetch('/api/load/' + encodeURIComponent(efj));
    if (!res.ok) { pc.innerHTML = '<div class="panel-loading">Load not found</div>'; return; }
    var d = await res.json();
    var h = '<div class="panel-section">';
    h += '<h3 style="font-size:18px;margin-bottom:16px;">' + d.efj + '</h3>';
    h += '<div class="panel-grid">';
    h += '<div class="panel-field"><div class="panel-label">Account</div><div class="panel-value">' + (d.account||'-') + '</div></div>';
    h += '<div class="panel-field"><div class="panel-label">Move Type</div><div class="panel-value">' + (d.move_type||'-') + '</div></div>';
    h += '<div class="panel-field"><div class="panel-label">Container</div><div class="panel-value" style="font-family:JetBrains Mono,monospace">' + (d.container||'-') + '</div></div>';
    h += '<div class="panel-field"><div class="panel-label">BOL</div><div class="panel-value">' + (d.bol||'-') + '</div></div>';
    h += '<div class="panel-field"><div class="panel-label">Carrier</div><div class="panel-value">' + (d.carrier||'-') + '</div></div>';
    h += '<div class="panel-field"><div class="panel-label">SSL</div><div class="panel-value">' + (d.ssl||'-') + '</div></div>';
    h += '<div class="panel-field"><div class="panel-label">Origin</div><div class="panel-value">' + (d.origin||'-') + '</div></div>';
    h += '<div class="panel-field"><div class="panel-label">Destination</div><div class="panel-value">' + (d.destination||'-') + '</div></div>';
    h += '<div class="panel-field"><div class="panel-label">Status</div><div class="panel-value">' + (d.status||'-') + '</div></div>';
    h += '<div class="panel-field"><div class="panel-label">Rep</div><div class="panel-value">' + (d.rep||'-') + '</div></div>';
    h += '<div class="panel-field"><div class="panel-label">Invoiced</div><div class="panel-value">' + (d.invoiced || 'No') + '</div></div>';
    h += '</div></div>';
    h += '<div class="panel-section"><h4>Timeline</h4><div class="panel-grid">';
    var lfdStyle = '';
    if (d.lfd) { var lfdDate = new Date(d.lfd); var now = new Date(); if (lfdDate <= now) lfdStyle = 'color:var(--accent-red);font-weight:600'; }
    h += '<div class="panel-field"><div class="panel-label">ETA</div><div class="panel-value">' + (d.eta||'-') + '</div></div>';
    h += '<div class="panel-field"><div class="panel-label">LFD</div><div class="panel-value" style="' + lfdStyle + '">' + (d.lfd||'-') + '</div></div>';
    h += '<div class="panel-field"><div class="panel-label">Pickup</div><div class="panel-value">' + (d.pickup||'-') + '</div></div>';
    h += '<div class="panel-field"><div class="panel-label">Delivery</div><div class="panel-value">' + (d.delivery||'-') + '</div></div>';
    h += '</div></div>';
    if (d.bot_alert) { h += '<div class="panel-section"><h4>Bot Notes</h4><div style="font-size:13px;color:var(--text-secondary);white-space:pre-wrap;">' + d.bot_alert + '</div></div>'; }
    h += '<div class="panel-section"><h4>Document Checklist</h4><div class="doc-checklist">';
    var docTypes = ['BOL','POD','Invoice'];
    for (var i=0;i<docTypes.length;i++) {
      var dt = docTypes[i];
      var doc = null;
      if (d.documents) { for (var j=0;j<d.documents.length;j++) { if (d.documents[j].doc_type === dt) { doc = d.documents[j]; break; } } }
      if (doc && doc.filename) {
        h += '<div class="doc-item received"><div class="doc-status">&#10004;</div>';
        h += '<div class="doc-info"><div class="doc-type">' + dt + '</div><div class="doc-filename">' + doc.filename + '</div></div>';
        h += '<div class="doc-action"><a href="/docs/' + doc.file_path + '" target="_blank">View</a></div></div>';
      } else {
        h += '<div class="doc-item missing"><div class="doc-status">&#10008;</div>';
        h += '<div class="doc-info"><div class="doc-type">' + dt + '</div><div class="doc-filename">Not received</div></div>';
        h += '<div class="doc-action"><input type="file" id="upload-' + dt + '-' + d.efj + '" accept=".pdf,.png,.jpg,.jpeg,.xlsx,.xls,.doc,.docx" onchange="uploadDoc(\'' + d.efj + '\',\'' + dt + '\',this)">';
        h += '<label for="upload-' + dt + '-' + d.efj + '">Upload</label></div></div>';
      }
    }
    h += '</div></div>';
    pc.innerHTML = h;
  } catch(e) { pc.innerHTML = '<div class="panel-loading">Error loading details</div>'; }
}

async function uploadDoc(efj, docType, input) {
  if (!input.files.length) return;
  var file = input.files[0];
  var allowed = ['.pdf','.png','.jpg','.jpeg','.xlsx','.xls','.doc','.docx'];
  var ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
  if (allowed.indexOf(ext) === -1) { alert('File type not allowed.'); input.value = ''; return; }
  if (file.size > 25 * 1024 * 1024) { alert('File too large. Max 25 MB.'); input.value = ''; return; }
  var label = input.nextElementSibling;
  var origText = label.textContent;
  label.textContent = 'Uploading...';
  label.style.opacity = '0.6';
  input.disabled = true;
  var fd = new FormData();
  fd.append('file', file);
  fd.append('doc_type', docType);
  try {
    var res = await fetch('/api/load/' + encodeURIComponent(efj) + '/upload', {method:'POST', body:fd});
    if (res.ok) { label.textContent = 'Done!'; label.style.color = '#16a34a'; setTimeout(function(){ loadPanel(efj); }, 500); }
    else { var err = await res.json().catch(function(){return {detail:'Upload failed'};}); alert(err.detail||'Upload failed'); label.textContent=origText; label.style.opacity='1'; input.disabled=false; }
  } catch(e) { alert('Upload error: '+e.message); label.textContent=origText; label.style.opacity='1'; input.disabled=false; }
}
"""

    return HTMLResponse(_page(f"{rep_name} - CSL Dispatch", body, script=interactive_js))

'''

code = code[:start_idx] + new_rep_function + code[end_idx:]

# 5. Add CSS for collapsible account sections
css_addition = """
.acct-body { transition: max-height 0.3s ease; overflow: hidden; }
.acct-body.collapsed { max-height: 0 !important; overflow: hidden; }
"""

code = code.replace(
    '@keyframes highlightFlash',
    css_addition + '@keyframes highlightFlash'
)

with open(APP_FILE, 'w') as f:
    f.write(code)

print('app.py patched: rep dashboard v2 with account breakdown + invoiced column')
