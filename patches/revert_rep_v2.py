"""Full revert of rep v2 patch — restore original rep dashboard, remove invoiced column."""

APP_FILE = '/root/csl-bot/csl-doc-tracker/app.py'

with open(APP_FILE, 'r') as f:
    code = f.read()

# 1. Remove "invoiced" from COL mapping
code = code.replace(
    '"status": 12, "notes": 13, "bot_alert": 14, "return_port": 15, "invoiced": 16,',
    '"status": 12, "notes": 13, "bot_alert": 14, "return_port": 15,'
)

# 2. Remove "invoiced" from shipment dict
code = code.replace(
    '"bot_alert": cell("bot_alert"), "return_port": cell("return_port"), "invoiced": cell("invoiced"),',
    '"bot_alert": cell("bot_alert"), "return_port": cell("return_port"),'
)

# 3. Remove "invoiced" from api_load_detail
code = code.replace(
    '"return_port": shipment["return_port"],\n        "rep": shipment["rep"],\n        "invoiced": shipment.get("invoiced", ""),',
    '"return_port": shipment["return_port"],\n        "rep": shipment["rep"],'
)

# 4. Remove the CSS addition
css_addition = """
.acct-body { transition: max-height 0.3s ease; overflow: hidden; }
.acct-body.collapsed { max-height: 0 !important; overflow: hidden; }
"""
code = code.replace(css_addition, '')

# 5. Replace the v2 rep dashboard with the original
# Find the v2 rep dashboard
v2_start_marker = '# ---------------------------------------------------------------------------\n# Rep Dashboard \xe2\x80\x94 broken down by account\n# ---------------------------------------------------------------------------'
v2_end_marker = '\n\n@app.on_event("startup")'

start_idx = code.index(v2_start_marker)
end_idx = code.index(v2_end_marker, start_idx)

original_rep = r'''# ---------------------------------------------------------------------------
# Rep Dashboard
# ---------------------------------------------------------------------------
@app.get("/rep/{rep_name}", response_class=HTMLResponse)
def rep_dashboard(rep_name: str):
    """Dedicated dashboard for a specific rep."""
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

    # Compute rep-specific stats
    now = datetime.now()
    today = now.strftime("%Y-%m-%d")
    tomorrow = (now + timedelta(days=1)).strftime("%Y-%m-%d")
    active = at_risk = on_sched = eta_chg = 0
    imports = exports = ftl = 0
    accounts = set()

    for s in rep_shipments:
        sl = s["status"].lower()
        is_done = any(w in sl for w in ("delivered", "completed", "empty return"))
        if is_done:
            continue

        active += 1
        mt = s.get("move_type", "").lower()
        if "import" in mt:
            imports += 1
        elif "export" in mt:
            exports += 1
        elif "ftl" in mt or "truckload" in mt:
            ftl += 1

        accounts.add(s["account"])

        risk = False
        if s["lfd"] and s["lfd"][:10] <= tomorrow:
            risk = True
        if not s["eta"] and not s["status"]:
            risk = True
        if risk:
            at_risk += 1
        else:
            on_sched += 1

        if s["bot_alert"] and today in s["bot_alert"]:
            eta_chg += 1

    info = REP_STYLES.get(rep_name, {"color": "var(--accent-blue)", "bg": "linear-gradient(135deg,#3b82f6,#2563eb)", "initials": "??"})

    # Stats cards
    stats_html = f"""<div class="stats-grid">
  <div class="stat-card"><div class="stat-value">{active}</div><div class="stat-label">Active Loads</div></div>
  <div class="stat-card"><div class="stat-value" style="color:var(--accent-red)">{at_risk}</div><div class="stat-label">At Risk</div></div>
  <div class="stat-card"><div class="stat-value" style="color:var(--accent-green)">{on_sched}</div><div class="stat-label">On Schedule</div></div>
  <div class="stat-card"><div class="stat-value" style="color:var(--accent-amber)">{eta_chg}</div><div class="stat-label">ETA Changed</div></div>
</div>"""

    # Move type breakdown
    breakdown_html = f"""<div class="panel" style="margin-bottom:20px;">
  <div class="panel-header"><div class="panel-title">Load Breakdown</div></div>
  <div style="display:flex;gap:24px;padding:16px;">
    <div style="text-align:center;flex:1;"><div style="font-size:28px;font-weight:700;color:var(--accent-blue)">{imports}</div><div style="font-size:12px;color:var(--text-secondary)">Imports</div></div>
    <div style="text-align:center;flex:1;"><div style="font-size:28px;font-weight:700;color:var(--accent-cyan)">{exports}</div><div style="font-size:12px;color:var(--text-secondary)">Exports</div></div>
    <div style="text-align:center;flex:1;"><div style="font-size:28px;font-weight:700;color:var(--accent-purple)">{ftl}</div><div style="font-size:12px;color:var(--text-secondary)">FTL</div></div>
    <div style="text-align:center;flex:1;"><div style="font-size:12px;color:var(--text-secondary);margin-top:4px;">Accounts: {', '.join(sorted(accounts))}</div></div>
  </div>
</div>"""

    # Alerts for this rep
    rep_alerts = _generate_alerts(rep_shipments, limit=10)
    alerts_html = _build_alerts_html(rep_alerts)

    # Load table
    rows = ""
    for s in rep_shipments:
        sl = s["status"].lower()
        is_done = any(w in sl for w in ("delivered", "completed", "empty return"))
        if is_done:
            continue

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

        efj_link = f'<a href="javascript:void(0)" onclick="openPanel(\'{s["efj"]}\')" style="color:var(--accent-blue);cursor:pointer;">{s["efj"]}</a>'

        rows += f"""<tr>
  <td>{efj_link}</td>
  <td>{s['account']}</td>
  <td style="font-family:JetBrains Mono,monospace;font-size:12px">{s['container']}</td>
  <td><span style="color:{status_color}">{s['status'] or '-'}</span></td>
  <td>{s['eta'] or '-'}</td>
  <td{lfd_style}>{s['lfd'] or '-'}</td>
  <td>{s['move_type'] or '-'}</td>
</tr>"""

    table_html = f"""<div class="panel">
  <div class="panel-header"><div class="panel-title">Active Loads</div></div>
  <div class="table-wrap">
    <table>
      <thead><tr><th>EFJ #</th><th>Account</th><th>Container</th><th>Status</th><th>ETA</th><th>LFD</th><th>Type</th></tr></thead>
      <tbody>{rows}</tbody>
    </table>
  </div>
</div>"""

    # Panel HTML for clickable loads
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
        <div style="font-size:13px;color:var(--text-secondary);">{', '.join(sorted(accounts))}</div>
      </div>
      <a href="/" style="margin-left:auto;font-size:12px;color:var(--text-secondary);border:1px solid var(--border);padding:6px 14px;border-radius:8px;">&larr; Back to Overview</a>
    </div>
    {stats_html}
    {breakdown_html}
    {alerts_html}
    {table_html}
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

code = code[:start_idx] + original_rep + code[end_idx:]

with open(APP_FILE, 'w') as f:
    f.write(code)

print('FULLY REVERTED: rep dashboard restored to original, invoiced column removed')
