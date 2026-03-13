from fastapi import APIRouter, Query, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
import auth

router = APIRouter()


def _auth_page_style():
    return """
    <style>
    * { margin: 0; padding: 0; box-sizing: border-box; }
    body {
        background: #0a0d12; color: #e8ecf4;
        font-family: 'Plus Jakarta Sans', -apple-system, sans-serif;
        min-height: 100vh; display: flex; align-items: center; justify-content: center;
    }
    .auth-card {
        background: #161e2c; border: 1px solid #1e2a3d; border-radius: 16px;
        padding: 48px; width: 420px; max-width: 90vw;
        box-shadow: 0 20px 60px rgba(0,0,0,0.5);
    }
    .auth-card h1 { font-size: 24px; margin-bottom: 8px; }
    .auth-card p { color: #7b8ba3; margin-bottom: 28px; font-size: 14px; }
    .auth-card label { display: block; font-size: 13px; color: #7b8ba3; margin-bottom: 6px; font-weight: 500; }
    .auth-card input {
        width: 100%; padding: 12px 16px; background: #0a0d12; border: 1px solid #1e2a3d;
        border-radius: 8px; color: #e8ecf4; font-size: 15px; margin-bottom: 18px; outline: none;
    }
    .auth-card input:focus { border-color: #3b82f6; }
    .auth-card button {
        width: 100%; padding: 14px; background: linear-gradient(135deg, #3b82f6, #2563eb);
        border: none; border-radius: 8px; color: #fff; font-size: 15px; font-weight: 600; cursor: pointer;
    }
    .auth-card button:hover { transform: translateY(-1px); box-shadow: 0 8px 24px rgba(59,130,246,0.3); }
    .error-msg {
        background: rgba(239,68,68,0.1); border: 1px solid rgba(239,68,68,0.3);
        color: #ef4444; padding: 10px 14px; border-radius: 8px; font-size: 13px; margin-bottom: 18px;
    }
    .logo-row { display: flex; align-items: center; gap: 12px; margin-bottom: 28px; }
    .logo-row img { width: 36px; height: 36px; border-radius: 8px; }
    .logo-row span { font-size: 18px; font-weight: 700; color: #3b82f6; }
    </style>
    <link href="https://fonts.googleapis.com/css2?family=Plus+Jakarta+Sans:wght@400;500;600;700&display=swap" rel="stylesheet">
    """


@router.get("/login", response_class=HTMLResponse)
def login_page(request: Request, error: str = Query(default="")):
    if not auth.is_configured():
        return RedirectResponse("/setup", status_code=302)
    token = request.cookies.get("csl_session")
    if auth.verify_session_token(token):
        return RedirectResponse("/", status_code=302)
    error_html = f'<div class="error-msg">{error}</div>' if error else ""
    return f"""<!DOCTYPE html><html><head><title>Login - CSL Dispatch</title>{_auth_page_style()}</head><body>
    <div class="auth-card">
        <div class="logo-row"><img src="/logo.svg" alt="logo"><span>CSL Dispatch</span></div>
        <h1>Sign In</h1>
        <p>Enter your credentials to access the dashboard.</p>
        {error_html}
        <form method="POST" action="/login">
            <label>Username</label>
            <input name="username" type="text" required autocomplete="username" autofocus>
            <label>Password</label>
            <input name="password" type="password" required autocomplete="current-password">
            <button type="submit">Sign In</button>
        </form>
    </div></body></html>"""


@router.post("/login")
def login_submit(request: Request, username: str = Form(...), password: str = Form(...)):
    ip = request.headers.get("x-real-ip", request.client.host)
    locked, remaining = auth.check_lockout(ip)
    if locked:
        return RedirectResponse(f"/login?error=Too+many+attempts.+Try+again+in+{remaining}+seconds.", status_code=302)
    if auth.verify_login(username, password):
        auth.clear_failed_attempts(ip)
        token = auth.create_session_token(username)
        resp = RedirectResponse("/", status_code=302)
        resp.set_cookie("csl_session", token, max_age=86400*7, httponly=True, secure=True, samesite="lax")
        return resp
    auth.record_failed_attempt(ip)
    return RedirectResponse("/login?error=Invalid+username+or+password.", status_code=302)


@router.get("/logout")
def logout():
    resp = RedirectResponse("/login", status_code=302)
    resp.delete_cookie("csl_session")
    return resp


@router.get("/setup", response_class=HTMLResponse)
def setup_page(error: str = Query(default="")):
    if auth.is_configured():
        return RedirectResponse("/login", status_code=302)
    error_html = f'<div class="error-msg">{error}</div>' if error else ""
    return f"""<!DOCTYPE html><html><head><title>Setup - CSL Dispatch</title>{_auth_page_style()}</head><body>
    <div class="auth-card">
        <div class="logo-row"><img src="/logo.svg" alt="logo"><span>CSL Dispatch</span></div>
        <h1>Create Admin Account</h1>
        <p>Set your username and password. This can only be done once.</p>
        {error_html}
        <form method="POST" action="/setup">
            <label>Username</label>
            <input name="username" type="text" required autofocus placeholder="e.g. admin">
            <label>Password</label>
            <input name="password" type="password" required minlength="8" placeholder="Min 8 characters">
            <label>Confirm Password</label>
            <input name="confirm" type="password" required minlength="8">
            <button type="submit">Create Account</button>
        </form>
    </div></body></html>"""


@router.post("/setup")
def setup_submit(username: str = Form(...), password: str = Form(...), confirm: str = Form(...)):
    if auth.is_configured():
        return RedirectResponse("/login", status_code=302)
    if len(password) < 8:
        return RedirectResponse("/setup?error=Password+must+be+at+least+8+characters.", status_code=302)
    if password != confirm:
        return RedirectResponse("/setup?error=Passwords+do+not+match.", status_code=302)
    auth.setup_password(username, password)
    return RedirectResponse("/login", status_code=302)
