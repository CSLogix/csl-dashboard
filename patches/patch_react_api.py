"""
Patch: Add JSON API endpoints for React Dashboard
Adds: /api/shipments, /api/alerts, /api/accounts, /api/team, CORS middleware
Target: /root/csl-bot/csl-doc-tracker/app.py
"""
import re, shutil, sys, os

APP = "/root/csl-bot/csl-doc-tracker/app.py"
shutil.copy2(APP, APP + ".bak_react_api")
code = open(APP).read()

# ────────────────────────────────────────────
# 1. Add CORS middleware (after existing middleware)
# ────────────────────────────────────────────
cors_code = '''
# ── CORS middleware for React dev ──
from starlette.middleware.cors import CORSMiddleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
'''

# Insert after the AuthMiddleware line
if "CORSMiddleware" not in code:
    # Find the last add_middleware call
    match = re.search(r'(app\.add_middleware\(AuthMiddleware.*?\))', code, re.DOTALL)
    if match:
        insert_pos = match.end()
        code = code[:insert_pos] + "\n" + cors_code + code[insert_pos:]
        print("[+] Added CORS middleware")
    else:
        # Fallback: insert after app = FastAPI()
        match = re.search(r'(app\s*=\s*FastAPI\([^)]*\))', code)
        if match:
            insert_pos = match.end()
            code = code[:insert_pos] + "\n" + cors_code + code[insert_pos:]
            print("[+] Added CORS middleware (after FastAPI init)")
        else:
            print("[!] Could not find insertion point for CORS")
else:
    print("[=] CORS middleware already present")

# ────────────────────────────────────────────
# 2. Add /api/shipments endpoint
# ────────────────────────────────────────────
shipments_api = '''
# ── React Dashboard: Shipments API ──
@app.get("/api/shipments")
async def api_shipments(request: Request, account: str = None, status: str = None):
    """Return all shipments as JSON, optionally filtered by account and/or status."""
    cache.maybe_refresh()
    data = cache.shipments
    if account:
        data = [s for s in data if s.get("account", "").lower() == account.lower()]
    if status:
        data = [s for s in data if s.get("status", "").lower() == status.lower()]
    return {"shipments": data, "total": len(data)}
'''

if '"/api/shipments"' not in code:
    # Insert before the health endpoint or at end of routes
    match = re.search(r'(@app\.(get|post)\("/health")', code)
    if match:
        code = code[:match.start()] + shipments_api + "\n" + code[match.start():]
    else:
        code += shipments_api
    print("[+] Added /api/shipments endpoint")
else:
    print("[=] /api/shipments already exists")

# ────────────────────────────────────────────
# 3. Add /api/alerts endpoint
# ────────────────────────────────────────────
alerts_api = '''
# ── React Dashboard: Alerts API ──
@app.get("/api/alerts")
async def api_alerts(request: Request):
    """Return current alerts for the dashboard."""
    cache.maybe_refresh()
    alerts = cache._generate_alerts() if hasattr(cache, '_generate_alerts') else []
    return {"alerts": alerts, "total": len(alerts)}
'''

if '"/api/alerts"' not in code:
    match = re.search(r'(@app\.(get|post)\("/health")', code)
    if match:
        code = code[:match.start()] + alerts_api + "\n" + code[match.start():]
    else:
        code += alerts_api
    print("[+] Added /api/alerts endpoint")
else:
    print("[=] /api/alerts already exists")

# ────────────────────────────────────────────
# 4. Add /api/accounts endpoint
# ────────────────────────────────────────────
accounts_api = '''
# ── React Dashboard: Accounts API ──
@app.get("/api/accounts")
async def api_accounts(request: Request):
    """Return account summaries for the dashboard."""
    cache.maybe_refresh()
    return {"accounts": cache.accounts}
'''

if '"/api/accounts"' not in code:
    match = re.search(r'(@app\.(get|post)\("/health")', code)
    if match:
        code = code[:match.start()] + accounts_api + "\n" + code[match.start():]
    else:
        code += accounts_api
    print("[+] Added /api/accounts endpoint")
else:
    print("[=] /api/accounts already exists")

# ────────────────────────────────────────────
# 5. Add /api/team endpoint
# ────────────────────────────────────────────
team_api = '''
# ── React Dashboard: Team API ──
@app.get("/api/team")
async def api_team(request: Request):
    """Return team member summaries for the dashboard."""
    cache.maybe_refresh()
    return {"team": cache.team}
'''

if '"/api/team"' not in code:
    match = re.search(r'(@app\.(get|post)\("/health")', code)
    if match:
        code = code[:match.start()] + team_api + "\n" + code[match.start():]
    else:
        code += team_api
    print("[+] Added /api/team endpoint")
else:
    print("[=] /api/team already exists")

# ────────────────────────────────────────────
# Write
# ────────────────────────────────────────────
with open(APP, "w") as f:
    f.write(code)
print("\n[✓] Patch applied. Restart csl-dashboard service to activate.")
print("    systemctl restart csl-dashboard")
