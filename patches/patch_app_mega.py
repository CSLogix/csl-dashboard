"""
Mega patch for app.py: Steps 0,2,3,4,5,7,8 from the plan.
- Step 0: SheetCache reads Boviet + Tolead sheets
- Step 2: Invoiced toggle API endpoint
- Step 3: Undo broken v2 patch artifacts
- Step 4: New rep dashboard with account cards
- Step 5: FTL clickable Macropoint links (hyperlink fetching)
- Step 7: Live Alerts Boviet/Tolead filter tabs
- Step 8: Team panel Boviet/Tolead/Janice rows
"""

APP_FILE = '/root/csl-bot/csl-doc-tracker/app.py'

with open(APP_FILE, 'r') as f:
    code = f.read()

# =====================================================================
# STEP 3: Undo broken v2 patch artifacts
# =====================================================================
code = code.replace(
    '"status": 12, "notes": 13, "bot_alert": 14, "return_port": 15, "invoiced": 16,',
    '"status": 12, "notes": 13, "bot_alert": 14, "return_port": 15,'
)
code = code.replace(
    '"bot_alert": cell("bot_alert"), "return_port": cell("return_port"), "invoiced": cell("invoiced"),',
    '"bot_alert": cell("bot_alert"), "return_port": cell("return_port"),'
)
code = code.replace(
    '"return_port": shipment["return_port"],\n        "rep": shipment["rep"],\n        "invoiced": shipment.get("invoiced", ""),',
    '"return_port": shipment["return_port"],\n        "rep": shipment["rep"],'
)
css_rm = """
.acct-body { transition: max-height 0.3s ease; overflow: hidden; }
.acct-body.collapsed { max-height: 0 !important; overflow: hidden; }
"""
code = code.replace(css_rm, '')

print("Step 3: v2 artifacts removed")

# =====================================================================
# STEP 8: Add REP_STYLES for Boviet, Tolead
# =====================================================================
code = code.replace(
    '"Janice": {"color": "var(--accent-cyan)", "bg": "linear-gradient(135deg,#06b6d4,#0891b2)", "initials": "JC"},',
    '"Janice": {"color": "var(--accent-cyan)", "bg": "linear-gradient(135deg,#06b6d4,#0891b2)", "initials": "JC"},\n    "Boviet": {"color": "var(--accent-amber)", "bg": "linear-gradient(135deg,#f59e0b,#d97706)", "initials": "BV"},\n    "Tolead": {"color": "var(--accent-red)", "bg": "linear-gradient(135deg,#ef4444,#dc2626)", "initials": "TL"},'
)
print("Step 8: REP_STYLES updated")

# =====================================================================
# STEP 0: Add Boviet/Tolead sheet reading to SheetCache
# =====================================================================

# Add constants after CACHE_TTL
boviet_tolead_consts = '''
# Boviet + Tolead separate sheets
BOVIET_SHEET_ID = "1OP-ZDaMCOsPxcxezHSPfN5ftUXlUcOjFgsfCQgDp3wI"
BOVIET_SKIP_TABS = {"POCs", "Boviet Master"}
BOVIET_TAB_CONFIGS = {
    "DTE Fresh/Stock":  {"efj_col": 0, "load_id_col": 1, "status_col": 5},
    "Sundance":         {"efj_col": 0, "load_id_col": 1, "status_col": 6},
    "Renewable Energy": {"efj_col": 0, "load_id_col": 1, "status_col": 5},
    "Radiance Solar":   {"efj_col": 0, "load_id_col": 1, "status_col": 5},
    "Piedra":           {"efj_col": 0, "load_id_col": 2, "status_col": 7},
    "Hanson":           {"efj_col": 0, "load_id_col": 1, "status_col": 6},
}
BOVIET_DONE_STATUSES = {"Delivered", "Completed", "Canceled", "Cancelled", "Ready to Close"}

TOLEAD_SHEET_ID = "1-zl7CCFdy2bWRTm1FsGDDjU-KVwqPiThQuvJc2ZU2ac"
TOLEAD_TAB = "Schedule"
TOLEAD_COL_EFJ = 15     # P
TOLEAD_COL_ORD = 1      # B
TOLEAD_COL_STATUS = 9   # J
TOLEAD_COL_ORIGIN = 6   # G
TOLEAD_COL_DEST = 7     # H
TOLEAD_COL_DATE = 4     # E
TOLEAD_SKIP_STATUSES = {"Delivered", "Canceled"}

'''
code = code.replace(
    'CACHE_TTL = 300  # 5 minutes',
    'CACHE_TTL = 300  # 5 minutes' + boviet_tolead_consts
)

# Add Boviet/Tolead reading in _do_refresh(), right before self.shipments = all_shipments
boviet_tolead_read = '''
        # --- Read Boviet sheet ---
        try:
            bov_sh = gc.open_by_key(BOVIET_SHEET_ID)
            bov_tabs = [ws.title for ws in bov_sh.worksheets()
                        if ws.title not in BOVIET_SKIP_TABS and ws.title in BOVIET_TAB_CONFIGS]
            for tab_name in bov_tabs:
                try:
                    cfg = BOVIET_TAB_CONFIGS[tab_name]
                    ws = bov_sh.worksheet(tab_name)
                    rows = ws.get_all_values()
                    for row in rows[1:]:  # skip header
                        efj = row[cfg["efj_col"]].strip() if len(row) > cfg["efj_col"] else ""
                        load_id = row[cfg["load_id_col"]].strip() if len(row) > cfg["load_id_col"] else ""
                        status = row[cfg["status_col"]].strip() if len(row) > cfg["status_col"] else ""
                        if not efj or status in BOVIET_DONE_STATUSES:
                            continue
                        all_shipments.append({
                            "account": "Boviet", "efj": efj, "move_type": "FTL",
                            "container": load_id, "bol": "", "ssl": "",
                            "carrier": "", "origin": "", "destination": "",
                            "eta": "", "lfd": "", "pickup": "", "delivery": "",
                            "status": status, "notes": "", "bot_alert": "",
                            "return_port": "", "rep": "Boviet",
                            "container_url": "",
                        })
                    _time.sleep(1)
                except Exception as e:
                    log.warning("Boviet tab %s: %s", tab_name, e)
        except Exception as e:
            log.warning("Boviet sheet read failed: %s", e)

        # --- Read Tolead sheet ---
        try:
            tol_sh = gc.open_by_key(TOLEAD_SHEET_ID)
            ws = tol_sh.worksheet(TOLEAD_TAB)
            rows = ws.get_all_values()
            for row in rows[1:]:
                def tol_cell(idx):
                    return row[idx].strip() if len(row) > idx else ""
                efj = tol_cell(TOLEAD_COL_EFJ)
                ord_num = tol_cell(TOLEAD_COL_ORD)
                status = tol_cell(TOLEAD_COL_STATUS)
                if not efj and not ord_num:
                    continue
                if status in TOLEAD_SKIP_STATUSES:
                    continue
                all_shipments.append({
                    "account": "Tolead", "efj": efj or ord_num,
                    "move_type": "FTL", "container": ord_num, "bol": "",
                    "ssl": "", "carrier": "",
                    "origin": tol_cell(TOLEAD_COL_ORIGIN),
                    "destination": tol_cell(TOLEAD_COL_DEST),
                    "eta": tol_cell(TOLEAD_COL_DATE), "lfd": "",
                    "pickup": "", "delivery": "",
                    "status": status, "notes": "", "bot_alert": "",
                    "return_port": "", "rep": "Tolead",
                    "container_url": "",
                })
        except Exception as e:
            log.warning("Tolead sheet read failed: %s", e)

'''

code = code.replace(
    '        self.shipments = all_shipments\n        self._compute_stats()',
    boviet_tolead_read + '        self.shipments = all_shipments\n        self._compute_stats()'
)
print("Step 0: Boviet/Tolead sheet reading added")

# =====================================================================
# STEP 5: Add container_url field to master tracker shipments
# =====================================================================
# Add container_url to the shipment dict in the master tracker loop
code = code.replace(
    '"bot_alert": cell("bot_alert"), "return_port": cell("return_port"),',
    '"bot_alert": cell("bot_alert"), "return_port": cell("return_port"),\n                        "container_url": "",'
)
print("Step 5: container_url field added to shipments")

# =====================================================================
# STEP 7: Add Boviet + Tolead filter tabs to Live Alerts
# =====================================================================
code = code.replace(
    "'<div class=\"filter-tabs\"><button class=\"filter-tab active\">All</button><button class=\"filter-tab\">Imports</button><button class=\"filter-tab\">Exports</button><button class=\"filter-tab\">FTL</button></div>'",
    "'<div class=\"filter-tabs\"><button class=\"filter-tab active\">All</button><button class=\"filter-tab\">Imports</button><button class=\"filter-tab\">Exports</button><button class=\"filter-tab\">FTL</button><button class=\"filter-tab\">Boviet</button><button class=\"filter-tab\">Tolead</button></div>'"
)

# Add data-account attribute to alert items
code = code.replace(
    'efj_attr = f\' data-efj="{a["efj"]}"\' if a.get("efj") else ""',
    'efj_attr = f\' data-efj="{a["efj"]}"\' if a.get("efj") else ""\n            acct_attr = f\' data-account="{a.get("account", "")}"\''
)
code = code.replace(
    'items += f"""<div class="alert-item"{efj_attr}{move_attr}',
    'items += f"""<div class="alert-item"{efj_attr}{move_attr}{acct_attr}'
)

# Add account to alert data
code = code.replace(
    '"move": s["move_type"], "rep": s["rep"], "efj": s["efj"],\n            }',
    '"move": s["move_type"], "rep": s["rep"], "efj": s["efj"], "account": s["account"],\n            }'
)
# Fix for the other 3 alert types too
import re
code = re.sub(
    r'"move": s\["move_type"\], "rep": s\["rep"\], "efj": s\["efj"\],\n(\s+)\}',
    '"move": s["move_type"], "rep": s["rep"], "efj": s["efj"], "account": s["account"],\n\\1}',
    code
)

# Update the JS filter logic to handle Boviet/Tolead
old_filter_js = """var filter = this.textContent.trim().toLowerCase();
      document.querySelectorAll('.alert-item').forEach(function(item) {
        if (filter === 'all') { item.style.display = ''; return; }
        var move = (item.dataset.move || '').toLowerCase();
        if (filter === 'imports' && move.includes('import')) item.style.display = '';
        else if (filter === 'exports' && move.includes('export')) item.style.display = '';
        else if (filter === 'ftl' && move.includes('ftl')) item.style.display = '';
        else item.style.display = 'none';
      });"""

new_filter_js = """var filter = this.textContent.trim().toLowerCase();
      document.querySelectorAll('.alert-item').forEach(function(item) {
        if (filter === 'all') { item.style.display = ''; return; }
        var move = (item.dataset.move || '').toLowerCase();
        var acct = (item.dataset.account || '').toLowerCase();
        if (filter === 'imports' && move.includes('import')) item.style.display = '';
        else if (filter === 'exports' && move.includes('export')) item.style.display = '';
        else if (filter === 'ftl' && move.includes('ftl')) item.style.display = '';
        else if (filter === 'boviet' && acct === 'boviet') item.style.display = '';
        else if (filter === 'tolead' && acct === 'tolead') item.style.display = '';
        else item.style.display = 'none';
      });"""

code = code.replace(old_filter_js, new_filter_js)
print("Step 7: Boviet/Tolead filter tabs added")

# =====================================================================
# STEP 2: Add invoiced toggle API endpoint (before /health)
# =====================================================================
invoiced_api = '''

@app.post("/api/load/{efj}/invoiced")
async def api_set_invoiced(efj: str, request: Request):
    """Toggle invoiced status for a load."""
    body = await request.json()
    invoiced = bool(body.get("invoiced", False))
    db.set_load_invoiced(efj, invoiced)
    return {"status": "ok", "invoiced": invoiced}

'''
code = code.replace(
    '@app.get("/health")',
    invoiced_api + '@app.get("/health")'
)
print("Step 2: Invoiced API endpoint added")

# =====================================================================
# STEP 4: Replace rep_dashboard with account cards layout
# =====================================================================

# Find and replace the entire rep_dashboard function
# The v2 version starts with "# Rep Dashboard — broken down by account"
# or the original starts with "# Rep Dashboard"
# It ends before "@app.on_event("startup")"

# Try v2 marker first
v2_marker = '# ---------------------------------------------------------------------------\n# Rep Dashboard \xe2\x80\x94 broken down by account\n# ---------------------------------------------------------------------------'
v1_marker = '# ---------------------------------------------------------------------------\n# Rep Dashboard\n# ---------------------------------------------------------------------------'

if v2_marker in code:
    start_marker = v2_marker
elif v1_marker in code:
    start_marker = v1_marker
else:
    print("WARNING: Could not find rep dashboard marker!")
    start_marker = None

if start_marker:
    end_marker = '\n\n@app.on_event("startup")'
    start_idx = code.index(start_marker)
    end_idx = code.index(end_marker, start_idx)

    new_rep_dashboard = r'''# ---------------------------------------------------------------------------
# Rep Dashboard — Account Cards with Drill-Down
# ---------------------------------------------------------------------------
@app.get("/rep/{rep_name}", response_class=HTMLResponse)
def rep_dashboard(rep_name: str):
    """Dedicated dashboard: account cards with per-account stats, click to expand load tables."""
    sheet_cache.refresh_if_needed()

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

    # Get invoiced map from DB
    try:
        invoiced_map = db.get_invoiced_map()
    except Exception:
        invoiced_map = {}

    # Build per-account data
    account_data = {}
    for s in rep_shipments:
        sl = s["status"].lower()
        is_done = any(w in sl for w in ("delivered", "completed", "empty return"))
        if is_done:
            continue

        acct = s["account"]
        if acct not in account_data:
            account_data[acct] = {"active": 0, "at_risk": 0, "on_sched": 0, "unbilled": 0, "shipments": []}

        inv = invoiced_map.get(s["efj"], False)
        s["_invoiced"] = inv

        account_data[acct]["active"] += 1
        account_data[acct]["shipments"].append(s)

        risk = False
        if s["lfd"] and s["lfd"][:10] <= tomorrow:
            risk = True
        if not s["eta"] and not s["status"]:
            risk = True
        if risk:
            account_data[acct]["at_risk"] += 1
        else:
            account_data[acct]["on_sched"] += 1

        if not inv:
            account_data[acct]["unbilled"] += 1

    info = REP_STYLES.get(rep_name, {"color": "var(--accent-blue)", "bg": "linear-gradient(135deg,#3b82f6,#2563eb)", "initials": "??"})
    num_accts = len(account_data)
    min_w = "180px" if num_accts > 6 else "240px"

    # --- Account cards ---
    cards_html = ""
    for acct_name in sorted(account_data.keys(), key=lambda a: account_data[a]["active"], reverse=True):
        ad = account_data[acct_name]
        risk_color = "var(--accent-red)" if ad["at_risk"] > 0 else "var(--text-dim)"
        unbill_color = "var(--accent-amber)" if ad["unbilled"] > 0 else "var(--text-dim)"

        # Build load table rows for this account
        load_rows = ""
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

            inv_val = s.get("_invoiced", False)
            inv_sel_yes = " selected" if inv_val else ""
            inv_sel_no = "" if inv_val else " selected"
            row_bg = "background:rgba(34,197,94,0.06);" if inv_val else ""

            ctr_display = s["container"]
            if s.get("container_url"):
                ctr_display = f'<a href="{s["container_url"]}" target="_blank" style="color:var(--accent-cyan);">{s["container"]}</a>'

            efj_link = f'<a href="javascript:void(0)" onclick="openPanel(\'{s["efj"]}\')" style="color:var(--accent-blue);cursor:pointer;">{s["efj"]}</a>'

            load_rows += f"""<tr style="{row_bg}" data-efj="{s['efj']}">
  <td>{efj_link}</td>
  <td style="font-family:JetBrains Mono,monospace;font-size:12px">{ctr_display}</td>
  <td><span style="color:{status_color}">{s['status'] or '-'}</span></td>
  <td>{s['eta'] or '-'}</td>
  <td{lfd_style}>{s['lfd'] or '-'}</td>
  <td>{s['move_type'] or '-'}</td>
  <td><select class="inv-select" data-efj="{s['efj']}" onchange="toggleInvoiced(this)" style="background:var(--bg-surface);border:1px solid var(--border);border-radius:6px;color:var(--text-primary);padding:3px 6px;font-size:11px;cursor:pointer;">
    <option value="false"{inv_sel_no}>Unbilled</option>
    <option value="true"{inv_sel_yes}>Invoiced</option>
  </select></td>
</tr>"""

        safe_id = acct_name.replace(" ", "_").replace("/", "_")
        cards_html += f"""<div class="stat-card" style="cursor:pointer;padding:16px;" onclick="toggleAcct('{safe_id}')">
  <div style="font-weight:700;font-size:14px;margin-bottom:10px;">{acct_name}</div>
  <div style="display:grid;grid-template-columns:1fr 1fr;gap:4px;font-size:12px;">
    <div><span style="color:var(--text-dim);">Active</span> <span style="font-weight:700;color:var(--accent-blue);">{ad['active']}</span></div>
    <div><span style="color:var(--text-dim);">On Sched</span> <span style="font-weight:700;color:var(--accent-green);">{ad['on_sched']}</span></div>
    <div><span style="color:var(--text-dim);">At Risk</span> <span style="font-weight:700;color:{risk_color};">{ad['at_risk']}</span></div>
    <div><span style="color:var(--text-dim);">Unbilled</span> <span style="font-weight:700;color:{unbill_color};">{ad['unbilled']}</span></div>
  </div>
</div>
<div id="acct-{safe_id}" class="acct-expand" style="display:none;grid-column:1/-1;">
  <div class="panel" style="margin-bottom:12px;">
    <div class="panel-header"><div class="panel-title">{acct_name} &mdash; {ad['active']} Active Loads</div></div>
    <div class="table-wrap">
      <table>
        <thead><tr><th>EFJ #</th><th>Container/ID</th><th>Status</th><th>ETA</th><th>LFD</th><th>Type</th><th>Invoiced</th></tr></thead>
        <tbody>{load_rows}</tbody>
      </table>
    </div>
  </div>
</div>"""

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
        <div style="font-size:13px;color:var(--text-secondary);">{num_accts} accounts &middot; {sum(d['active'] for d in account_data.values())} active loads</div>
      </div>
      <a href="/" style="margin-left:auto;font-size:12px;color:var(--text-secondary);border:1px solid var(--border);padding:6px 14px;border-radius:8px;">&larr; Back to Overview</a>
    </div>
    <div style="display:grid;grid-template-columns:repeat(auto-fill,minmax({min_w},1fr));gap:12px;margin-bottom:24px;">
      {cards_html}
    </div>
  </div>
</div>
{panel_html}"""

    interactive_js = r"""
function toggleAcct(id) {
  var el = document.getElementById('acct-' + id);
  if (!el) return;
  if (el.style.display === 'none') {
    // Close all others first
    document.querySelectorAll('.acct-expand').forEach(function(e) { e.style.display = 'none'; });
    el.style.display = 'block';
    el.scrollIntoView({behavior: 'smooth', block: 'nearest'});
  } else {
    el.style.display = 'none';
  }
}

async function toggleInvoiced(sel) {
  var efj = sel.dataset.efj;
  var val = sel.value === 'true';
  try {
    var res = await fetch('/api/load/' + encodeURIComponent(efj) + '/invoiced', {
      method: 'POST', headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({invoiced: val})
    });
    if (res.ok) {
      var row = sel.closest('tr');
      row.style.background = val ? 'rgba(34,197,94,0.06)' : '';
      row.style.transition = 'background 0.3s';
    }
  } catch(e) { console.error('Invoiced toggle failed:', e); }
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
    h += '<div class="panel-section"><div class="panel-section-title">Shipment Details</div>';
    var fields = [['Container/Load', d.container], ['BOL/Booking', d.bol], ['SSL/Vessel', d.ssl], ['Carrier', d.carrier], ['Origin', d.origin], ['Destination', d.destination], ['Status', d.status || 'Unknown'], ['Rep', d.rep || 'Unassigned']];
    for (var i=0;i<fields.length;i++) { h += '<div class="panel-field"><span class="panel-field-label">' + fields[i][0] + '</span><span class="panel-field-value">' + (fields[i][1]||'-') + '</span></div>'; }
    h += '</div>';
    h += '<div class="panel-section"><div class="panel-section-title">Timeline</div>';
    var dates = [['ETA/ERD', d.eta], ['LFD/Cutoff', d.lfd], ['Pickup', d.pickup], ['Delivery', d.delivery]];
    for (var i=0;i<dates.length;i++) { h += '<div class="panel-field"><span class="panel-field-label">' + dates[i][0] + '</span><span class="panel-field-value">' + (dates[i][1]||'-') + '</span></div>'; }
    h += '</div>';
    if (d.bot_alert) { h += '<div class="panel-section"><div class="panel-section-title">Bot Notes</div><div style="font-size:12px;color:var(--text-secondary);white-space:pre-wrap;">' + d.bot_alert + '</div></div>'; }
    h += '<div class="panel-section"><div class="panel-section-title">Documents</div>';
    var docTypes = ['BOL','POD','Invoice'];
    for (var i=0;i<docTypes.length;i++) {
      var dt = docTypes[i]; var doc = null;
      if (d.documents) { for (var j=0;j<d.documents.length;j++) { if (d.documents[j].doc_type===dt) { doc=d.documents[j]; break; } } }
      if (doc && doc.filename) {
        h += '<div class="doc-item received"><div class="doc-status">\u2713</div><div class="doc-info"><div class="doc-type">' + dt + '</div><div class="doc-filename">' + doc.filename + '</div></div><div class="doc-action"><a href="/docs/' + doc.file_path + '" target="_blank">View</a></div></div>';
      } else {
        h += '<div class="doc-item missing"><div class="doc-status">\u2717</div><div class="doc-info"><div class="doc-type">' + dt + '</div><div class="doc-filename">Not received</div></div>';
        h += '<div class="doc-action"><input type="file" id="upload-' + dt + '-' + d.efj + '" accept=".pdf,.png,.jpg,.jpeg,.xlsx,.xls,.doc,.docx" onchange="uploadDoc(\'' + d.efj + '\',\'' + dt + '\',this)"><label for="upload-' + dt + '-' + d.efj + '">Upload</label></div></div>';
      }
    }
    h += '</div>';
    pc.innerHTML = h;
  } catch(e) { pc.innerHTML = '<div class="panel-loading">Error loading details</div>'; }
}

async function uploadDoc(efj, docType, input) {
  if (!input.files.length) return;
  var file = input.files[0];
  var allowed = ['.pdf','.png','.jpg','.jpeg','.xlsx','.xls','.doc','.docx'];
  var ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
  if (allowed.indexOf(ext)===-1) { alert('File type not allowed.'); input.value=''; return; }
  if (file.size > 25*1024*1024) { alert('File too large. Max 25 MB.'); input.value=''; return; }
  var label = input.nextElementSibling;
  var orig = label.textContent;
  label.textContent = 'Uploading...'; label.style.opacity = '0.6'; input.disabled = true;
  var fd = new FormData(); fd.append('file', file); fd.append('doc_type', docType);
  try {
    var res = await fetch('/api/load/' + encodeURIComponent(efj) + '/upload', {method:'POST', body:fd});
    if (res.ok) { label.textContent='Done!'; label.style.color='#16a34a'; setTimeout(function(){loadPanel(efj);},500); }
    else { var err = await res.json().catch(function(){return {detail:'Upload failed'};}); alert(err.detail||'Upload failed'); label.textContent=orig; label.style.opacity='1'; input.disabled=false; }
  } catch(e) { alert('Upload error: '+e.message); label.textContent=orig; label.style.opacity='1'; input.disabled=false; }
}
"""

    return HTMLResponse(_page(f"{rep_name} - CSL Dispatch", body, script=interactive_js))

'''

    code = code[:start_idx] + new_rep_dashboard + code[end_idx:]
    print("Step 4: New rep dashboard with account cards deployed")

with open(APP_FILE, 'w') as f:
    f.write(code)

print("ALL STEPS COMPLETE — app.py patched successfully")
