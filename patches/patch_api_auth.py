"""Patch: Add API authentication + fix SameSite cookie.

Applies to /root/csl-bot/csl-doc-tracker/app.py

Changes:
1. Remove `/api/` from the public bypass in AuthMiddleware
2. Add API-specific auth that returns 401 JSON instead of redirect
3. Fix samesite="none" -> samesite="lax" on login cookie
"""
import re

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP, "r") as f:
    src = f.read()

# ── 1. Fix the auth middleware ──
old_middleware = '''class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path in PUBLIC_PATHS or path.startswith("/static") or path.startswith("/api/") or path.startswith("/app") or path.startswith("/assets"):
            return await call_next(request)
        if not auth.is_configured():
            return RedirectResponse("/setup", status_code=302)
        token = request.cookies.get("csl_session")
        user = auth.verify_session_token(token)
        if not user:
            return RedirectResponse("/login", status_code=302)
        return await call_next(request)'''

new_middleware = '''class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        # Public paths: static assets, login/setup pages, React app shell
        if path in PUBLIC_PATHS or path.startswith("/static") or path.startswith("/app") or path.startswith("/assets"):
            return await call_next(request)
        # API routes require session auth (return 401 JSON, not redirect)
        if path.startswith("/api/"):
            token = request.cookies.get("csl_session")
            user = auth.verify_session_token(token)
            if not user:
                from starlette.responses import JSONResponse
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            return await call_next(request)
        # Legacy HTML pages: redirect to login
        if not auth.is_configured():
            return RedirectResponse("/setup", status_code=302)
        token = request.cookies.get("csl_session")
        user = auth.verify_session_token(token)
        if not user:
            return RedirectResponse("/login", status_code=302)
        return await call_next(request)'''

if old_middleware not in src:
    print("ERROR: Could not find auth middleware to patch. Already patched?")
    # Check if already patched
    if 'return JSONResponse({"error": "unauthorized"}, status_code=401)' in src:
        print("Already patched — skipping middleware change.")
    else:
        raise SystemExit(1)
else:
    src = src.replace(old_middleware, new_middleware)
    print("✓ Auth middleware patched — API routes now require session cookie")

# ── 2. Fix SameSite cookie ──
old_cookie = 'samesite="none"'
new_cookie = 'samesite="lax"'

if old_cookie in src:
    src = src.replace(old_cookie, new_cookie)
    print("✓ SameSite cookie fixed: none → lax")
else:
    if new_cookie in src:
        print("SameSite already set to lax — skipping.")
    else:
        print("WARNING: Could not find samesite setting to fix.")

with open(APP, "w") as f:
    f.write(src)

print("\nPatch applied. Restart csl-dashboard to activate.")
