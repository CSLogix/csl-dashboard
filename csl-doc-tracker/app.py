"""
FastAPI dashboard for CSL Document Tracker.
Server-rendered HTML with dark theme, mobile-friendly, auto-refresh.
"""

import logging
import sys
from datetime import datetime
from pathlib import Path

from fastapi import FastAPI, HTTPException, Query, Form, Request
from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse
import uvicorn

import config
import database as db

log = logging.getLogger(__name__)

app = FastAPI(title="CSL Document Tracker")

# ---------------------------------------------------------------------------
# HTML Templates (inline to avoid extra template engine dependency)
# ---------------------------------------------------------------------------

CSS = """
:root {
    --bg-primary: #0f1117;
    --bg-secondary: #1a1d27;
    --bg-card: #222633;
    --bg-hover: #2a2e3d;
    --text-primary: #e4e6ed;
    --text-secondary: #9399a8;
    --accent: #4f8cff;
    --accent-hover: #6ba0ff;
    --green: #34d399;
    --red: #f87171;
    --yellow: #fbbf24;
    --border: #2d3348;
    --shadow: 0 2px 8px rgba(0,0,0,0.3);
}
* { box-sizing: border-box; margin: 0; padding: 0; }
body {
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Oxygen, sans-serif;
    background: var(--bg-primary);
    color: var(--text-primary);
    min-height: 100vh;
    line-height: 1.5;
}
a { color: var(--accent); text-decoration: none; }
a:hover { color: var(--accent-hover); text-decoration: underline; }

/* Header */
.header {
    background: var(--bg-secondary);
    border-bottom: 1px solid var(--border);
    padding: 16px 24px;
    display: flex;
    align-items: center;
    justify-content: space-between;
    flex-wrap: wrap;
    gap: 12px;
}
.header h1 {
    font-size: 1.25rem;
    font-weight: 600;
    letter-spacing: -0.01em;
}
.header .subtitle {
    color: var(--text-secondary);
    font-size: 0.85rem;
}

/* Stats bar */
.stats-bar {
    display: flex;
    gap: 16px;
    padding: 16px 24px;
    flex-wrap: wrap;
}
.stat-card {
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 10px;
    padding: 14px 20px;
    min-width: 140px;
    box-shadow: var(--shadow);
}
.stat-card .label {
    font-size: 0.75rem;
    color: var(--text-secondary);
    text-transform: uppercase;
    letter-spacing: 0.05em;
    margin-bottom: 4px;
}
.stat-card .value {
    font-size: 1.5rem;
    font-weight: 700;
}
.stat-card .value.warn { color: var(--yellow); }
.stat-card .value.danger { color: var(--red); }

/* Filters */
.filters {
    display: flex;
    gap: 8px;
    padding: 0 24px 16px;
    flex-wrap: wrap;
}
.filter-btn {
    padding: 8px 16px;
    border-radius: 8px;
    border: 1px solid var(--border);
    background: var(--bg-card);
    color: var(--text-secondary);
    cursor: pointer;
    font-size: 0.85rem;
    transition: all 0.15s;
}
.filter-btn:hover { background: var(--bg-hover); color: var(--text-primary); }
.filter-btn.active {
    background: var(--accent);
    color: #fff;
    border-color: var(--accent);
}

/* Tabs */
.tabs {
    display: flex;
    gap: 0;
    padding: 0 24px;
    border-bottom: 1px solid var(--border);
}
.tab {
    padding: 10px 20px;
    cursor: pointer;
    font-size: 0.9rem;
    color: var(--text-secondary);
    border-bottom: 2px solid transparent;
    transition: all 0.15s;
}
.tab:hover { color: var(--text-primary); }
.tab.active {
    color: var(--accent);
    border-bottom-color: var(--accent);
}
.tab .badge {
    background: var(--red);
    color: #fff;
    font-size: 0.7rem;
    padding: 1px 7px;
    border-radius: 10px;
    margin-left: 6px;
    font-weight: 600;
}

/* Table */
.table-wrap {
    padding: 16px 24px;
    overflow-x: auto;
    -webkit-overflow-scrolling: touch;
}
table {
    width: 100%;
    border-collapse: collapse;
    font-size: 0.875rem;
}
thead th {
    background: var(--bg-secondary);
    color: var(--text-secondary);
    font-weight: 600;
    text-transform: uppercase;
    font-size: 0.7rem;
    letter-spacing: 0.06em;
    padding: 10px 14px;
    text-align: left;
    border-bottom: 1px solid var(--border);
    white-space: nowrap;
}
tbody tr {
    border-bottom: 1px solid var(--border);
    transition: background 0.1s;
}
tbody tr:hover { background: var(--bg-hover); }
tbody td {
    padding: 10px 14px;
    white-space: nowrap;
}
.doc-status {
    display: inline-flex;
    align-items: center;
    gap: 4px;
    font-size: 0.85rem;
}
.doc-yes { color: var(--green); }
.doc-no { color: var(--red); }

/* Unmatched table */
.unmatched-section { padding: 16px 24px; }
.unmatched-section h3 { margin-bottom: 12px; font-size: 1rem; }
.match-form {
    display: inline-flex;
    gap: 6px;
    align-items: center;
}
.match-form input {
    background: var(--bg-secondary);
    border: 1px solid var(--border);
    border-radius: 6px;
    color: var(--text-primary);
    padding: 5px 10px;
    font-size: 0.8rem;
    width: 120px;
}
.match-form button {
    background: var(--accent);
    color: #fff;
    border: none;
    border-radius: 6px;
    padding: 5px 12px;
    font-size: 0.8rem;
    cursor: pointer;
}
.match-form button:hover { background: var(--accent-hover); }
.btn-ignore {
    background: var(--bg-hover) !important;
    color: var(--text-secondary) !important;
}
.btn-ignore:hover { background: #3a3e4d !important; }

/* Mobile */
@media (max-width: 768px) {
    .header { padding: 12px 16px; }
    .stats-bar { padding: 12px 16px; gap: 10px; }
    .stat-card { min-width: 100px; padding: 10px 14px; }
    .stat-card .value { font-size: 1.2rem; }
    .filters { padding: 0 16px 12px; }
    .tabs { padding: 0 16px; }
    .table-wrap { padding: 12px 16px; }
    .unmatched-section { padding: 12px 16px; }
    table { font-size: 0.8rem; }
    thead th, tbody td { padding: 8px 10px; }
}
@media (max-width: 480px) {
    .stat-card { min-width: 80px; padding: 8px 10px; }
    .stat-card .label { font-size: 0.65rem; }
    .stat-card .value { font-size: 1rem; }
    .filter-btn { padding: 6px 12px; font-size: 0.8rem; }
}

/* Refresh indicator */
.refresh-indicator {
    position: fixed;
    bottom: 16px;
    right: 16px;
    background: var(--bg-card);
    border: 1px solid var(--border);
    border-radius: 8px;
    padding: 6px 12px;
    font-size: 0.75rem;
    color: var(--text-secondary);
    box-shadow: var(--shadow);
}

/* Empty state */
.empty-state {
    text-align: center;
    padding: 48px 24px;
    color: var(--text-secondary);
}
.empty-state .icon { font-size: 2rem; margin-bottom: 12px; }
"""

SCRIPT = """
// Auto-refresh every 60 seconds
let countdown = 60;
const indicator = document.getElementById('refresh-countdown');
setInterval(() => {
    countdown--;
    if (indicator) indicator.textContent = 'Refresh in ' + countdown + 's';
    if (countdown <= 0) {
        location.reload();
    }
}, 1000);

// Tab switching
function switchTab(tab) {
    document.querySelectorAll('.tab-content').forEach(el => el.style.display = 'none');
    document.querySelectorAll('.tab').forEach(el => el.classList.remove('active'));
    document.getElementById('tab-' + tab).style.display = 'block';
    document.querySelector('[data-tab="' + tab + '"]').classList.add('active');
}
"""


def _base_page(title: str, body: str) -> str:
    return f"""<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="UTF-8">
    <meta name="viewport" content="width=device-width, initial-scale=1.0">
    <title>{title}</title>
    <style>{CSS}</style>
</head>
<body>
{body}
<div class="refresh-indicator" id="refresh-countdown">Refresh in 60s</div>
<script>{SCRIPT}</script>
</body>
</html>"""


def _render_loads_table(loads: list) -> str:
    if not loads:
        return '<div class="empty-state"><div class="icon">&#128230;</div><p>No loads found</p></div>'

    now = datetime.utcnow()
    rows_html = ""
    for load in loads:
        age_days = (now - load["created_at"]).days if load["created_at"] else 0

        if load["bol_received"]:
            bol_cell = f'<span class="doc-status doc-yes"><a href="/docs/{load["bol_file_path"]}" target="_blank">&#10004; BOL</a></span>'
        else:
            bol_cell = '<span class="doc-status doc-no">&#10008;</span>'

        if load["pod_received"]:
            pod_cell = f'<span class="doc-status doc-yes"><a href="/docs/{load["pod_file_path"]}" target="_blank">&#10004; POD</a></span>'
        else:
            pod_cell = '<span class="doc-status doc-no">&#10008;</span>'

        rows_html += f"""<tr>
            <td><strong>{load['load_number']}</strong></td>
            <td>{load['customer_ref'] or '-'}</td>
            <td>{load['customer_name'] or '-'}</td>
            <td>{load['account'] or '-'}</td>
            <td>{bol_cell}</td>
            <td>{pod_cell}</td>
            <td>{age_days}d</td>
        </tr>"""

    return f"""<table>
        <thead><tr>
            <th>Load #</th><th>Customer Ref</th><th>Customer</th>
            <th>Account</th><th>BOL</th><th>POD</th><th>Age</th>
        </tr></thead>
        <tbody>{rows_html}</tbody>
    </table>"""


def _render_unmatched_table(emails: list) -> str:
    if not emails:
        return '<div class="empty-state"><p>No unmatched emails</p></div>'

    rows = ""
    for em in emails:
        date_str = em["received_date"].strftime("%Y-%m-%d %H:%M") if em["received_date"] else "-"
        rows += f"""<tr>
            <td>{em['subject'] or '-'}</td>
            <td>{em['sender'] or '-'}</td>
            <td>{date_str}</td>
            <td>{em['attachment_names'] or '-'}</td>
            <td>
                <form class="match-form" method="POST" action="/unmatched/{em['id']}/match">
                    <input type="text" name="load_number" placeholder="EFJ#" required>
                    <button type="submit">Match</button>
                </form>
                <form class="match-form" method="POST" action="/unmatched/{em['id']}/ignore" style="margin-top:4px;">
                    <button type="submit" class="btn-ignore">Ignore</button>
                </form>
            </td>
        </tr>"""

    return f"""<table>
        <thead><tr>
            <th>Subject</th><th>From</th><th>Date</th><th>Attachments</th><th>Action</th>
        </tr></thead>
        <tbody>{rows}</tbody>
    </table>"""


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

@app.on_event("startup")
def startup():
    db.init_pool()
    log.info("Dashboard started")


@app.on_event("shutdown")
def shutdown():
    db.close_pool()


@app.get("/", response_class=HTMLResponse)
def dashboard(account: str = Query(default=None)):
    account_filter = account if account in ("EFJ-Operations", "Boviet", "Tolead") else None
    stats = db.get_dashboard_stats(account_filter)
    loads = db.get_dashboard_loads(account_filter)
    unmatched = db.get_unmatched_emails()

    # Build filter buttons
    accounts = [("All Accounts", None), ("EFJ-Operations", "EFJ-Operations"),
                ("Boviet", "Boviet"), ("Tolead", "Tolead")]
    filter_html = ""
    for label, val in accounts:
        active = "active" if val == account_filter else ""
        href = "/" if val is None else f"/?account={val}"
        filter_html += f'<a class="filter-btn {active}" href="{href}">{label}</a>'

    # Stats bar
    stats_html = f"""
    <div class="stat-card"><div class="label">Total Loads</div><div class="value">{stats['total_loads']}</div></div>
    <div class="stat-card"><div class="label">Missing BOL</div><div class="value warn">{stats['missing_bol']}</div></div>
    <div class="stat-card"><div class="label">Missing POD</div><div class="value warn">{stats['missing_pod']}</div></div>
    <div class="stat-card"><div class="label">Unmatched</div><div class="value danger">{stats['unmatched_emails']}</div></div>
    """

    # Tabs
    unmatched_badge = f'<span class="badge">{stats["unmatched_emails"]}</span>' if stats["unmatched_emails"] > 0 else ""
    tabs_html = f"""
    <div class="tab active" data-tab="loads" onclick="switchTab('loads')">Loads</div>
    <div class="tab" data-tab="unmatched" onclick="switchTab('unmatched')">Unmatched{unmatched_badge}</div>
    """

    loads_table = _render_loads_table(loads)
    unmatched_table = _render_unmatched_table(unmatched)

    body = f"""
    <div class="header">
        <div>
            <h1>CSL Document Tracker</h1>
            <div class="subtitle">Evans Delivery / EFJ Operations</div>
        </div>
    </div>
    <div class="stats-bar">{stats_html}</div>
    <div class="filters">{filter_html}</div>
    <div class="tabs">{tabs_html}</div>
    <div id="tab-loads" class="tab-content" style="display:block;">
        <div class="table-wrap">{loads_table}</div>
    </div>
    <div id="tab-unmatched" class="tab-content" style="display:none;">
        <div class="unmatched-section">
            <h3>Unmatched Emails</h3>
            {unmatched_table}
        </div>
    </div>
    """

    return HTMLResponse(_base_page("CSL Document Tracker", body))


@app.get("/docs/{file_path:path}")
def serve_document(file_path: str):
    """Serve a document file from storage."""
    full_path = config.DOCUMENT_STORAGE_PATH / file_path
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Document not found")
    # Security: ensure the resolved path is within storage
    try:
        full_path.resolve().relative_to(config.DOCUMENT_STORAGE_PATH.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")
    return FileResponse(str(full_path))


@app.post("/unmatched/{unmatched_id}/match")
def match_unmatched(unmatched_id: int, load_number: str = Form(...)):
    """Manually match an unmatched email to a load by EFJ number."""
    load = db.get_load_by_number(load_number.strip())
    if not load:
        raise HTTPException(status_code=404, detail=f"Load '{load_number}' not found")
    db.resolve_unmatched_email(unmatched_id, load["id"])
    log.info("Manually matched unmatched email %d to load %s", unmatched_id, load_number)
    return RedirectResponse(url="/?account=", status_code=303)


@app.post("/unmatched/{unmatched_id}/ignore")
def ignore_unmatched(unmatched_id: int):
    """Mark an unmatched email as ignored."""
    db.ignore_unmatched_email(unmatched_id)
    return RedirectResponse(url="/?account=", status_code=303)


@app.get("/health")
def health():
    return {"status": "ok"}


def main():
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.LOG_FILE),
        ],
    )
    uvicorn.run(
        "app:app",
        host=config.DASHBOARD_HOST,
        port=config.DASHBOARD_PORT,
        log_level=config.LOG_LEVEL.lower(),
    )


if __name__ == "__main__":
    main()
