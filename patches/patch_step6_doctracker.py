"""Step 6: Document Tracker redesign - new columns + drag-drop PODs."""

APP_FILE = '/root/csl-bot/csl-doc-tracker/app.py'

with open(APP_FILE, 'r') as f:
    code = f.read()

# Find and replace the shipments route
OLD_SHIPMENTS = '''@app.get("/shipments", response_class=HTMLResponse)
def shipments(account: str = Query(default=None)):
    account_filter = account if account else None
    stats = db.get_dashboard_stats(account_filter)
    loads = db.get_dashboard_loads(account_filter)

    if not loads:
        table = '<div style="padding:48px;text-align:center;color:var(--text-dim);">No loads found</div>'
    else:
        rows = ""
        now = datetime.utcnow()
        for load in loads:
            age = (now - load["created_at"]).days if load["created_at"] else 0
            bol = '<span class="doc-yes">&#10004; BOL</span>' if load["bol_received"] else '<span class="doc-no">&#10008;</span>'
            pod = '<span class="doc-yes">&#10004; POD</span>' if load["pod_received"] else '<span class="doc-no">&#10008;</span>'
            rows += f"<tr><td><strong>{load['load_number']}</strong></td><td>{load['customer_ref'] or '-'}</td><td>{load['customer_name'] or '-'}</td><td>{load['account'] or '-'}</td><td>{bol}</td><td>{pod}</td><td>{age}d</td></tr>"
        table = f'<table><thead><tr><th>Load #</th><th>Customer Ref</th><th>Customer</th><th>Account</th><th>BOL</th><th>POD</th><th>Age</th></tr></thead><tbody>{rows}</tbody></table>'

    accts = [("All", None), ("EFJ-Operations", "EFJ-Operations"), ("Boviet", "Boviet"), ("Tolead", "Tolead")]
    filt = ""
    for label, val in accts:
        active = "active" if val == account_filter else ""
        href = "/shipments" if val is None else f"/shipments?account={val}"
        filt += f\'<a href="{href}" style="padding:6px 14px;border-radius:8px;border:1px solid var(--border);font-size:12px;color:{"var(--accent-blue)" if active else "var(--text-secondary)"};background:{"var(--glow-blue)" if active else "var(--bg-card)"};margin-right:6px;">{label}</a>\'

    body = f"""{_sidebar("shipments")}
<div class="main">
  {_topbar("Document", "Tracker", search=False)}
  <div class="content">
    <div style="margin-bottom:16px;display:flex;gap:16px;align-items:center;">
      <h2 style="font-size:18px;">Shipments ({stats[\'total_loads\']})</h2>
      <span style="color:var(--accent-amber);font-size:12px;">Missing BOL: {stats[\'missing_bol\']}</span>
      <span style="color:var(--accent-red);font-size:12px;">Missing POD: {stats[\'missing_pod\']}</span>
    </div>
    <div style="margin-bottom:16px;">{filt}</div>
    <div class="panel"><div class="table-wrap">{table}</div></div>
  </div>
</div>"""
    return HTMLResponse(_page("CSL Shipments", body))'''

# Because the f-string quoting in the original is complex, let's use line-based replacement
lines = code.split('\n')
start_idx = None
end_idx = None

for i, line in enumerate(lines):
    if '@app.get("/shipments"' in line:
        start_idx = i
    if start_idx is not None and i > start_idx and line.strip().startswith('return HTMLResponse(_page("CSL Shipments"'):
        end_idx = i + 1
        break

if start_idx is None or end_idx is None:
    print(f"ERROR: Could not find shipments route (start={start_idx}, end={end_idx})")
    exit(1)

print(f"Found shipments route: lines {start_idx+1} to {end_idx}")

NEW_SHIPMENTS = r'''@app.get("/shipments", response_class=HTMLResponse)
def shipments(account: str = Query(default=None)):
    """Document Tracker - shows all shipments with drag-drop POD upload."""
    sheet_cache.refresh_if_needed()
    account_filter = account if account else None

    # Get doc status from DB
    all_loads_db = db.get_dashboard_loads(None)
    doc_map = {}
    for ld in all_loads_db:
        doc_map[ld["load_number"]] = {
            "bol": ld.get("bol_received", False),
            "pod": ld.get("pod_received", False),
            "status": ld.get("status", "active"),
        }

    # Build list from sheet cache
    all_shipments = sheet_cache.shipments
    if account_filter:
        all_shipments = [s for s in all_shipments if s.get("account") == account_filter]

    # Filter out delivered/completed
    active = []
    ready_to_invoice = []
    for s in all_shipments:
        sl = s["status"].lower() if s.get("status") else ""
        if any(w in sl for w in ("delivered", "completed", "empty return")):
            continue
        efj = s["efj"]
        docs = doc_map.get(efj, {})
        s["_bol"] = docs.get("bol", False)
        s["_pod"] = docs.get("pod", False)
        s["_db_status"] = docs.get("status", "active")
        if s["_pod"] and s["_db_status"] == "ready_to_invoice":
            ready_to_invoice.append(s)
        else:
            active.append(s)

    # Stats
    total = len(active) + len(ready_to_invoice)
    missing_bol = sum(1 for s in active if not s["_bol"])
    missing_pod = sum(1 for s in active if not s["_pod"])

    # Build rows
    def build_rows(shipment_list, show_dismiss=False):
        rows = ""
        for s in shipment_list:
            bol = '<span class="doc-yes">&#10004;</span>' if s["_bol"] else '<span class="doc-no">&#10008;</span>'
            pod = '<span class="doc-yes">&#10004;</span>' if s["_pod"] else '<span class="doc-no drop-target">&#10008; Drop POD</span>'

            ctr = s["container"] or "-"
            if s.get("container_url"):
                ctr = f'<a href="{s["container_url"]}" target="_blank" style="color:var(--accent-cyan);">{ctr}</a>'

            status_sl = (s["status"] or "").lower()
            sc = "var(--text-secondary)"
            if "at port" in status_sl or "available" in status_sl:
                sc = "var(--accent-amber)"
            elif "in transit" in status_sl or "on vessel" in status_sl:
                sc = "var(--accent-blue)"
            elif "out for" in status_sl or "picked up" in status_sl:
                sc = "var(--accent-cyan)"

            dismiss_btn = ""
            if show_dismiss:
                dismiss_btn = f'<td><button class="btn-dismiss" onclick="dismissLoad(\'{s["efj"]}\')">&#10004; Done</button></td>'

            rows += f"""<tr class="drop-row" data-efj="{s['efj']}" ondragover="handleDragOver(event)" ondragleave="handleDragLeave(event)" ondrop="handleDrop(event, '{s['efj']}')">
  <td><strong><a href="javascript:void(0)" onclick="openPanel('{s['efj']}')" style="color:var(--accent-blue);cursor:pointer;">{s['efj']}</a></strong></td>
  <td style="font-family:JetBrains Mono,monospace;font-size:12px;">{ctr}</td>
  <td>{s['account'] or '-'}</td>
  <td>{bol}</td>
  <td class="pod-cell">{pod}</td>
  <td><span style="color:{sc}">{s['status'] or '-'}</span></td>
  {dismiss_btn}
</tr>"""
        return rows

    active_rows = build_rows(active)
    rti_rows = build_rows(ready_to_invoice, show_dismiss=True)

    rti_section = ""
    if ready_to_invoice:
        rti_section = f"""<div class="panel" style="margin-bottom:16px;border:1px solid var(--accent-amber);">
  <div class="panel-header" style="background:rgba(245,158,11,0.1);">
    <div class="panel-title" style="color:var(--accent-amber);">Ready to Invoice ({len(ready_to_invoice)})</div>
  </div>
  <div class="table-wrap">
    <table>
      <thead><tr><th>EFJ #</th><th>Container/Load ID</th><th>Account</th><th>BOL</th><th>POD</th><th>Status</th><th></th></tr></thead>
      <tbody>{rti_rows}</tbody>
    </table>
  </div>
</div>"""

    accts = [("All", None), ("EFJ-Operations", "EFJ-Operations"), ("Boviet", "Boviet"), ("Tolead", "Tolead")]
    filt = ""
    for label, val in accts:
        is_active = val == account_filter or (val is None and account_filter is None)
        href = "/shipments" if val is None else f"/shipments?account={val}"
        filt += f'<a href="{href}" style="padding:6px 14px;border-radius:8px;border:1px solid var(--border);font-size:12px;color:{"var(--accent-blue)" if is_active else "var(--text-secondary)"};background:{"var(--glow-blue)" if is_active else "var(--bg-card)"};margin-right:6px;">{label}</a>'

    body = f"""{_sidebar("shipments")}
<div class="main">
  {_topbar("Document", "Tracker", search=False)}
  <div class="content">
    <div style="margin-bottom:16px;display:flex;gap:16px;align-items:center;flex-wrap:wrap;">
      <h2 style="font-size:18px;">Shipments ({total})</h2>
      <span style="color:var(--accent-amber);font-size:12px;">Missing BOL: {missing_bol}</span>
      <span style="color:var(--accent-red);font-size:12px;">Missing POD: {missing_pod}</span>
    </div>
    <div style="margin-bottom:16px;">{filt}</div>
    {rti_section}
    <div class="panel">
      <div class="table-wrap">
        <table>
          <thead><tr><th>EFJ #</th><th>Container/Load ID</th><th>Account</th><th>BOL</th><th>POD</th><th>Status</th></tr></thead>
          <tbody>{active_rows}</tbody>
        </table>
      </div>
    </div>
    <div style="margin-top:12px;font-size:11px;color:var(--text-dim);text-align:center;">Drag &amp; drop POD files onto any row to upload</div>
  </div>
</div>
<div class="detail-overlay" id="detail-overlay" onclick="closePanel()"></div>
<div class="detail-panel" id="detail-panel">
  <button class="panel-close" onclick="closePanel()">&times;</button>
  <div id="panel-content"><div class="panel-loading">Select a shipment</div></div>
</div>"""

    dd_js = r"""
function handleDragOver(e) {
  e.preventDefault();
  e.stopPropagation();
  e.currentTarget.style.outline = '2px dashed var(--accent-blue)';
  e.currentTarget.style.background = 'rgba(59,130,246,0.05)';
}
function handleDragLeave(e) {
  e.currentTarget.style.outline = '';
  e.currentTarget.style.background = '';
}
async function handleDrop(e, efj) {
  e.preventDefault();
  e.stopPropagation();
  var row = e.currentTarget;
  row.style.outline = '';
  row.style.background = '';

  var files = e.dataTransfer.files;
  if (!files.length) return;
  var file = files[0];
  var allowed = ['.pdf','.png','.jpg','.jpeg'];
  var ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
  if (allowed.indexOf(ext) === -1) { alert('Only PDF/image files accepted for POD.'); return; }
  if (file.size > 25*1024*1024) { alert('File too large. Max 25 MB.'); return; }

  var podCell = row.querySelector('.pod-cell');
  podCell.innerHTML = '<span style="color:var(--accent-amber);">Uploading...</span>';
  row.style.background = 'rgba(245,158,11,0.05)';

  var fd = new FormData();
  fd.append('file', file);
  fd.append('doc_type', 'POD');
  try {
    var res = await fetch('/api/load/' + encodeURIComponent(efj) + '/upload', {method:'POST', body:fd});
    if (res.ok) {
      podCell.innerHTML = '<span class="doc-yes">&#10004;</span>';
      row.style.background = 'rgba(34,197,94,0.06)';
      row.style.transition = 'background 0.5s';
      // Mark as ready to invoice
      await fetch('/api/load/' + encodeURIComponent(efj) + '/ready-to-invoice', {method:'POST'});
      setTimeout(function() { window.location.reload(); }, 1500);
    } else {
      podCell.innerHTML = '<span class="doc-no">&#10008; Failed</span>';
      row.style.background = '';
    }
  } catch(err) {
    podCell.innerHTML = '<span class="doc-no">&#10008; Error</span>';
    row.style.background = '';
  }
}

async function dismissLoad(efj) {
  if (!confirm('Mark ' + efj + ' as invoiced/complete?')) return;
  try {
    var res = await fetch('/api/load/' + encodeURIComponent(efj) + '/dismiss', {method:'POST'});
    if (res.ok) { window.location.reload(); }
    else { alert('Failed to dismiss load.'); }
  } catch(e) { alert('Error: ' + e.message); }
}

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
    var h = '<div class="panel-head"><div class="panel-head-title">' + d.efj + '</div>';
    h += '<div class="panel-head-sub">' + (d.account||'') + ' \u00B7 ' + (d.move_type||'') + '</div></div>';
    h += '<div class="panel-section"><div class="panel-section-title">Details</div>';
    var fields = [['Container/Load', d.container], ['BOL/Booking', d.bol], ['Status', d.status || 'Unknown'], ['Rep', d.rep || 'Unassigned']];
    for (var i=0;i<fields.length;i++) { h += '<div class="panel-field"><span class="panel-field-label">' + fields[i][0] + '</span><span class="panel-field-value">' + (fields[i][1]||'-') + '</span></div>'; }
    h += '</div>';
    pc.innerHTML = h;
  } catch(e) { pc.innerHTML = '<div class="panel-loading">Error loading details</div>'; }
}
"""

    return HTMLResponse(_page("CSL Shipments", body, script=dd_js))'''

# Replace
new_lines = lines[:start_idx] + [NEW_SHIPMENTS + '\n'] + lines[end_idx:]
code = '\n'.join(new_lines)

# Also add the two new API endpoints for ready-to-invoice and dismiss
# Insert before @app.get("/health")
RTI_ENDPOINTS = '''
@app.post("/api/load/{efj}/ready-to-invoice")
async def api_ready_to_invoice(efj: str):
    """Mark a load as ready to invoice after POD is uploaded."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "UPDATE loads SET status = 'ready_to_invoice', updated_at = NOW() WHERE load_number = %s",
                (efj,)
            )
    return {"status": "ok"}


@app.post("/api/load/{efj}/dismiss")
async def api_dismiss_load(efj: str):
    """Dismiss a load from the ready-to-invoice list (mark as invoiced/complete)."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "UPDATE loads SET status = 'invoiced', invoiced = TRUE, updated_at = NOW() WHERE load_number = %s",
                (efj,)
            )
    return {"status": "ok"}

'''

code = code.replace(
    '@app.get("/health")',
    RTI_ENDPOINTS + '@app.get("/health")'
)

with open(APP_FILE, 'w') as f:
    f.write(code)

print(f"Step 6: Document Tracker redesigned (lines {start_idx+1}-{end_idx} replaced)")
print("Step 6: Added /api/load/{efj}/ready-to-invoice and /api/load/{efj}/dismiss endpoints")
