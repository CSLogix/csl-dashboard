import mimetypes
from datetime import datetime, timedelta
from pathlib import Path

from fastapi import APIRouter, Query, Form, Request, HTTPException
from fastapi.responses import HTMLResponse, RedirectResponse, FileResponse, Response

import auth
import config
import database as db
from crypto import decrypt_data
from shared import (
    sheet_cache, log,
    _sidebar, _topbar, _page,
    _build_stats_html, _build_alerts_html, _build_accounts_html,
    _build_bots_html, _build_actions_html, _build_team_html,
    _generate_alerts, _get_bot_status_detailed, _get_recent_actions,
    REP_STYLES, COL,
)

router = APIRouter()


@router.get("/rep/{rep_name}", response_class=HTMLResponse)
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
    var fields = [['Container/Load', d.container_url ? '<a href="' + d.container_url + '" target="_blank" style="color:#06b6d4">' + d.container + ' &#x2197;</a>' : d.container], ['BOL/Booking', d.bol], ['SSL/Vessel', d.ssl], ['Carrier', d.carrier], ['Origin', d.origin], ['Destination', d.destination], ['Status', d.status || 'Unknown'], ['Rep', d.rep || 'Unassigned']];
    if (d.container_url) { fields.push(['Macropoint', '<a href="' + d.container_url + '" target="_blank" style="color:#06b6d4">Track Shipment &#x2197;</a>']); }
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


@router.get("/legacy", response_class=HTMLResponse)
def dashboard():
    sheet_cache.refresh_if_needed()

    stats = sheet_cache.stats
    accounts = sheet_cache.accounts
    alerts = _generate_alerts(sheet_cache.shipments, limit=10)
    bots = _get_bot_status_detailed()
    actions = _get_recent_actions(8)
    team = sheet_cache.team

    panel_html = """
<div class="detail-overlay" id="detail-overlay" onclick="closePanel()"></div>
<div class="detail-panel" id="detail-panel">
  <button class="panel-close" onclick="closePanel()">&times;</button>
  <div id="panel-content"><div class="panel-loading">Select a shipment to view details</div></div>
</div>"""

    body = f"""{_sidebar("dashboard")}
<div class="main">
  {_topbar()}
  <div class="content">
    {_build_stats_html(stats)}
    <div class="two-col">
      {_build_alerts_html(alerts)}
      {_build_accounts_html(accounts)}
    </div>
    <div class="three-col">
      {_build_bots_html(bots)}
      {_build_actions_html(actions)}
      {_build_team_html(team)}
    </div>
  </div>
</div>
{panel_html}"""

    interactive_js = r"""
// --- Slide-out Panel ---
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
    if (!res.ok) throw new Error('Not found');
    var data = await res.json();
    renderPanel(data);
  } catch(e) {
    pc.innerHTML = '<div class="panel-loading" style="color:var(--accent-red)">Could not load details for ' + efj + '</div>';
  }
}

function renderPanel(d) {
  var pc = document.getElementById('panel-content');
  var statusColor = 'var(--text-primary)';
  var sl = (d.status || '').toLowerCase();
  if (sl.includes('delivered') || sl.includes('completed')) statusColor = 'var(--accent-green)';
  else if (sl.includes('risk') || sl.includes('hold')) statusColor = 'var(--accent-red)';

  var h = '<div class="panel-head">';
  h += '<div class="panel-head-title">' + (d.efj || 'Unknown') + '</div>';
  h += '<div class="panel-head-sub">' + (d.account || '') + ' \u00B7 ' + (d.move_type || '') + '</div>';
  h += '</div>';

  // Shipment info
  h += '<div class="panel-section"><div class="panel-section-title">Shipment Details</div>';
  var fields = [
    ['Container / Load', d.container], ['BOL / Booking', d.bol],
    ['SSL / Vessel', d.ssl], ['Carrier', d.carrier],
    ['Origin', d.origin], ['Destination', d.destination],
    ['Status', '<span style="color:' + statusColor + ';font-weight:700">' + (d.status || 'Unknown') + '</span>'],
    ['Rep', d.rep || 'Unassigned']
  ];
  for (var i = 0; i < fields.length; i++) {
    h += '<div class="panel-field"><span class="panel-field-label">' + fields[i][0] + '</span><span class="panel-field-value">' + (fields[i][1] || '-') + '</span></div>';
  }
  h += '</div>';

  // Timeline
  h += '<div class="panel-section"><div class="panel-section-title">Timeline</div>';
  var dates = [['ETA / ERD', d.eta], ['LFD / Cutoff', d.lfd], ['Pickup', d.pickup], ['Delivery', d.delivery], ['Return to Port', d.return_port]];
  for (var i = 0; i < dates.length; i++) {
    var val = dates[i][1] || '-';
    var style = '';
    if (dates[i][0].includes('LFD') && val !== '-') {
      var today = new Date().toISOString().slice(0,10);
      if (val.slice(0,10) <= today) style = ' style="color:var(--accent-red);font-weight:700"';
    }
    h += '<div class="panel-field"><span class="panel-field-label">' + dates[i][0] + '</span><span class="panel-field-value"' + style + '>' + val + '</span></div>';
  }
  h += '</div>';

  // Bot notes
  if (d.notes || d.bot_alert) {
    h += '<div class="panel-section"><div class="panel-section-title">Notes</div>';
    if (d.notes) h += '<div style="font-size:12px;color:var(--text-secondary);line-height:1.6;margin-bottom:8px">' + d.notes + '</div>';
    if (d.bot_alert) h += '<div style="font-size:11px;color:var(--accent-cyan);font-family:JetBrains Mono,monospace">' + d.bot_alert + '</div>';
    h += '</div>';
  }

  // Document checklist
  h += '<div class="panel-section"><div class="panel-section-title">Document Checklist</div>';
  var docTypes = ['BOL', 'POD', 'Invoice'];
  for (var i = 0; i < docTypes.length; i++) {
    var dt = docTypes[i];
    var doc = null;
    if (d.documents) {
      for (var j = 0; j < d.documents.length; j++) {
        if (d.documents[j].doc_type === dt) { doc = d.documents[j]; break; }
      }
    }
    if (doc && doc.filename) {
      h += '<div class="doc-item received"><div class="doc-status">\u2713</div>';
      h += '<div class="doc-info"><div class="doc-type">' + dt + '</div><div class="doc-filename">' + doc.filename + '</div></div>';
      h += '<div class="doc-action"><a href="/docs/' + doc.file_path + '" target="_blank">Download</a></div></div>';
    } else {
      h += '<div class="doc-item missing"><div class="doc-status">\u2717</div>';
      h += '<div class="doc-info"><div class="doc-type">' + dt + '</div><div class="doc-filename">Not received</div></div>';
      h += '<div class="doc-action"><input type="file" id="upload-' + dt + '-' + d.efj + '" accept=".pdf,.png,.jpg,.jpeg,.xlsx,.xls,.doc,.docx" onchange="uploadDoc(\'' + d.efj + '\',\'' + dt + '\',this)">';
      h += '<label for="upload-' + dt + '-' + d.efj + '">Upload</label></div></div>';
    }
  }
  h += '</div>';

  pc.innerHTML = h;
}

async function uploadDoc(efj, docType, input) {
  if (!input.files.length) return;
  var file = input.files[0];
  var allowed = ['.pdf','.png','.jpg','.jpeg','.xlsx','.xls','.doc','.docx'];
  var ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
  if (allowed.indexOf(ext) === -1) {
    alert('File type not allowed. Allowed: ' + allowed.join(', '));
    input.value = '';
    return;
  }
  if (file.size > 25 * 1024 * 1024) {
    alert('File too large. Maximum size is 25 MB.');
    input.value = '';
    return;
  }
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
    if (res.ok) {
      label.textContent = 'Done!';
      label.style.color = '#16a34a';
      setTimeout(function() { loadPanel(efj); }, 500);
    } else {
      var err = await res.json().catch(function() { return {detail:'Upload failed'}; });
      alert(err.detail || 'Upload failed');
      label.textContent = origText;
      label.style.opacity = '1';
      input.disabled = false;
    }
  } catch(e) {
    alert('Upload error: ' + e.message);
    label.textContent = origText;
    label.style.opacity = '1';
    input.disabled = false;
  }
}

// --- Filter Tabs (Alerts) ---
document.querySelectorAll('.filter-tabs').forEach(function(group) {
  // Only handle the alert filter tabs (first filter-tabs group in two-col)
  if (!group.closest('.panel-header') || !group.closest('.two-col')) return;
  group.querySelectorAll('.filter-tab').forEach(function(tab) {
    tab.addEventListener('click', function() {
      group.querySelectorAll('.filter-tab').forEach(function(t){ t.classList.remove('active'); });
      this.classList.add('active');
      var filter = this.textContent.trim().toLowerCase();
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
      });
    });
  });
});

// --- Stat Card Clicks ---
document.querySelectorAll('.stat-card').forEach(function(card) {
  card.addEventListener('click', function() {
    var label = this.querySelector('.stat-label').textContent.toLowerCase();
    if (label.includes('active')) {
      var el = document.querySelector('.account-list');
      if (el) { el.scrollIntoView({behavior:'smooth'}); el.classList.add('highlight-flash'); setTimeout(function(){el.classList.remove('highlight-flash');},1500); }
    } else if (label.includes('at risk')) {
      // Filter alerts to show urgent/warning only
      document.querySelectorAll('.alert-item').forEach(function(item) {
        var icon = item.querySelector('.alert-icon');
        item.style.display = (icon && (icon.classList.contains('urgent') || icon.classList.contains('warning'))) ? '' : 'none';
      });
      var al = document.querySelector('.alert-list');
      if (al) { al.scrollIntoView({behavior:'smooth'}); al.classList.add('highlight-flash'); setTimeout(function(){al.classList.remove('highlight-flash');},1500); }
    } else if (label.includes('eta')) {
      // Show info alerts (bot updates)
      document.querySelectorAll('.alert-item').forEach(function(item) {
        var icon = item.querySelector('.alert-icon');
        item.style.display = (icon && icon.classList.contains('info')) ? '' : 'none';
      });
      var al = document.querySelector('.alert-list');
      if (al) al.scrollIntoView({behavior:'smooth'});
    } else if (label.includes('on schedule') || label.includes('completed')) {
      var el = document.querySelector('.three-col');
      if (el) el.scrollIntoView({behavior:'smooth'});
    }
  });
});

// --- Search ---
var searchInput = document.querySelector('.search-box input');
if (searchInput) {
  searchInput.addEventListener('input', function() {
    var q = this.value.toLowerCase().trim();
    // Filter alert items
    document.querySelectorAll('.alert-item').forEach(function(item) {
      if (!q) { item.style.display = ''; return; }
      item.style.display = item.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
    // Filter account rows
    document.querySelectorAll('.account-row:not(.header)').forEach(function(row) {
      if (!q) { row.style.display = ''; return; }
      row.style.display = row.textContent.toLowerCase().includes(q) ? '' : 'none';
    });
  });
}

// Auto-refresh (pause when panel is open)
setTimeout(function(){ if (!document.getElementById('detail-panel').classList.contains('open')) location.reload(); }, 60000);
"""
    return HTMLResponse(_page("CSL AI Dispatch", body, interactive_js))


@router.get("/shipments", response_class=HTMLResponse)
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
    var fields = [['Container/Load', d.container_url ? '<a href="' + d.container_url + '" target="_blank" style="color:#06b6d4">' + d.container + ' &#x2197;</a>' : d.container], ['BOL/Booking', d.bol], ['Status', d.status || 'Unknown'], ['Rep', d.rep || 'Unassigned']];
    if (d.container_url) { fields.push(['Macropoint', '<a href="' + d.container_url + '" target="_blank" style="color:#06b6d4">Track Shipment &#x2197;</a>']); }
    for (var i=0;i<fields.length;i++) { h += '<div class="panel-field"><span class="panel-field-label">' + fields[i][0] + '</span><span class="panel-field-value">' + (fields[i][1]||'-') + '</span></div>'; }
    h += '</div>';
    pc.innerHTML = h;
  } catch(e) { pc.innerHTML = '<div class="panel-loading">Error loading details</div>'; }
}
"""

    return HTMLResponse(_page("CSL Shipments", body, script=dd_js))


@router.get("/unmatched", response_class=HTMLResponse)
def unmatched_page():
    emails = db.get_unmatched_emails()
    if not emails:
        table = '<div style="padding:48px;text-align:center;color:var(--text-dim);">No unmatched emails</div>'
    else:
        rows = ""
        for em in emails[:50]:
            date_str = em["received_date"].strftime("%Y-%m-%d %H:%M") if em.get("received_date") else "-"
            rows += f"""<tr>
<td>{em.get('subject') or '-'}</td><td>{em.get('sender') or '-'}</td><td>{date_str}</td><td>{em.get('attachment_names') or '-'}</td>
<td><form class="match-form" method="POST" action="/unmatched/{em['id']}/match"><input type="text" name="load_number" placeholder="EFJ#" required><button type="submit">Match</button></form>
<form class="match-form" method="POST" action="/unmatched/{em['id']}/ignore" style="margin-top:4px;"><button type="submit" class="btn-ignore">Ignore</button></form></td>
</tr>"""
        table = f'<table><thead><tr><th>Subject</th><th>From</th><th>Date</th><th>Attachments</th><th>Action</th></tr></thead><tbody>{rows}</tbody></table>'

    body = f"""{_sidebar("unmatched")}
<div class="main">
  {_topbar("Unmatched", "Emails", search=False)}
  <div class="content">
    <div style="margin-bottom:16px;"><h2 style="font-size:18px;">Unmatched Emails ({len(emails)})</h2></div>
    <div class="panel"><div class="table-wrap">{table}</div></div>
  </div>
</div>"""
    return HTMLResponse(_page("CSL Unmatched Emails", body))


@router.get("/docs/{file_path:path}")
def serve_document(file_path: str, request: Request):
    """Serve a document, decrypting it on the fly."""
    # Defense-in-depth auth check
    token = request.cookies.get("csl_session")
    if not auth.verify_session_token(token):
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Path traversal protection
    full_path = config.DOCUMENT_STORAGE_PATH / file_path
    try:
        full_path.resolve().relative_to(config.DOCUMENT_STORAGE_PATH.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Document not found")

    # Decrypt file contents
    encrypted_data = full_path.read_bytes()
    try:
        decrypted_data = decrypt_data(encrypted_data)
    except Exception:
        # Fallback: file might be unencrypted (pre-migration)
        log.warning("Failed to decrypt %s, serving as-is", file_path)
        decrypted_data = encrypted_data

    # Determine content type from extension
    content_type, _ = mimetypes.guess_type(file_path)
    if not content_type:
        content_type = "application/octet-stream"

    return Response(
        content=decrypted_data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'inline; filename="{Path(file_path).name}"',
            "Cache-Control": "no-store",
        }
    )


@router.post("/unmatched/{unmatched_id}/match")
def match_unmatched(unmatched_id: int, load_number: str = Form(...)):
    load = db.get_load_by_number(load_number.strip())
    if not load:
        raise HTTPException(status_code=404, detail=f"Load '{load_number}' not found")
    db.resolve_unmatched_email(unmatched_id, load["id"])
    return RedirectResponse(url="/unmatched", status_code=303)


@router.post("/unmatched/{unmatched_id}/ignore")
def ignore_unmatched(unmatched_id: int):
    db.ignore_unmatched_email(unmatched_id)
    return RedirectResponse(url="/unmatched", status_code=303)
