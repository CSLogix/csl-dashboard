"""
Patch: Add React SPA serving to app.py

Adds:
1. StaticFiles mount for /assets (Vite build output)
2. /app catch-all route serving React index.html
3. Redirect / to /app (old HTML dashboard moves to /legacy)
"""

import re

APP_PY = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP_PY) as f:
    code = f.read()

# --- Backup ---
with open(APP_PY + ".bak_react_deploy", "w") as f:
    f.write(code)

# 1. Add StaticFiles import if not present
if "StaticFiles" not in code:
    code = code.replace(
        "from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, JSONResponse, Response",
        "from fastapi.responses import HTMLResponse, FileResponse, RedirectResponse, JSONResponse, Response\nfrom fastapi.staticfiles import StaticFiles",
    )

# 2. Mount /assets to serve Vite build JS/CSS — insert right after CORS middleware block
cors_block_end = 'allow_methods=["*"],\n    allow_headers=["*"],\n)'
if cors_block_end in code:
    static_mount = '''

# ── Serve React production build assets ──
_react_dist = Path(__file__).parent / "static" / "dist"
if _react_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(_react_dist / "assets")), name="react-assets")
'''
    code = code.replace(cors_block_end, cors_block_end + static_mount)

# 3. Change GET / to redirect to /app instead of serving old HTML
# The old HTML dashboard at / becomes /legacy
code = code.replace(
    '@app.get("/", response_class=HTMLResponse)',
    '@app.get("/legacy", response_class=HTMLResponse)',
    1  # only first occurrence
)

# 4. Add React SPA routes — right before the health endpoint
health_marker = '@app.get("/health")'
react_routes = '''# ── React SPA ──
_react_index = Path(__file__).parent / "static" / "dist" / "index.html"

@app.get("/")
async def react_root():
    """Redirect root to React app."""
    return RedirectResponse("/app", status_code=302)

@app.get("/app")
@app.get("/app/{path:path}")
async def react_spa(path: str = ""):
    """Serve React SPA for all /app/* routes."""
    if _react_index.exists():
        return FileResponse(str(_react_index), media_type="text/html")
    return RedirectResponse("/legacy", status_code=302)

'''
code = code.replace(health_marker, react_routes + health_marker)

# 5. Add /app to PUBLIC_PATHS so auth middleware doesn't block it
code = code.replace(
    'PUBLIC_PATHS = {"/login", "/setup", "/health", "/logo.svg"}',
    'PUBLIC_PATHS = {"/login", "/setup", "/health", "/logo.svg", "/app", "/assets"}',
)

# 6. Update auth middleware to allow /app/* paths
code = code.replace(
    'if path in PUBLIC_PATHS or path.startswith("/static") or path.startswith("/api/"):',
    'if path in PUBLIC_PATHS or path.startswith("/static") or path.startswith("/api/") or path.startswith("/app") or path.startswith("/assets"):',
)

with open(APP_PY, "w") as f:
    f.write(code)

print("Patch applied successfully!")
print("  - /assets → serves Vite build JS/CSS")
print("  - / → redirects to /app")
print("  - /app → React SPA")
print("  - /legacy → old server-rendered dashboard")
print("  - Auth middleware updated for /app and /assets paths")
