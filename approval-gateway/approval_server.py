"""
Approval Gateway — Claude Code Diff Review Server

Port 5004 | Mobile-friendly dark UI | SMS via carrier email gateway
Queues diffs for review, sends SMS link, serves review page, tracks approve/reject.

Systemd:
    [Unit]
    Description=Approval Gateway
    After=network.target
    [Service]
    ExecStart=/usr/bin/python3 -m uvicorn approval_server:app --host 127.0.0.1 --port 5004
    WorkingDirectory=/root/csl-bot/approval-gateway
    EnvironmentFile=/root/csl-bot/approval-gateway/.env
    Restart=on-failure
    [Install]
    WantedBy=multi-user.target
"""

import os
import uuid
import sqlite3
import smtplib
import threading
from email.mime.text import MIMEText
from datetime import datetime, timezone
from pathlib import Path
from contextlib import contextmanager

from fastapi import FastAPI, HTTPException, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel
from dotenv import load_dotenv

load_dotenv(Path(__file__).parent / ".env")

app = FastAPI(title="Approval Gateway", docs_url=None, redoc_url=None)

# --- Config ---
DIR = Path(__file__).parent
DB_PATH = DIR / "approvals.db"
TEMPLATE_PATH = DIR / "review.html"
GATEWAY_URL = os.getenv("GATEWAY_URL", "http://localhost:5004").rstrip("/")
SMS_EMAIL = os.getenv("SMS_EMAIL", "")
SMTP_USER = os.getenv("SMTP_USER", "")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD", "")
SMTP_HOST = os.getenv("SMTP_HOST", "smtp.gmail.com")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
API_TOKEN = os.getenv("APPROVAL_API_TOKEN", "")

REVIEW_HTML = ""


# --- Database ---
def init_db():
    with get_db() as db:
        db.execute("""
            CREATE TABLE IF NOT EXISTS reviews (
                id TEXT PRIMARY KEY,
                description TEXT,
                branch TEXT,
                diff_text TEXT,
                files_changed TEXT,
                stats TEXT,
                status TEXT DEFAULT 'pending',
                reject_comment TEXT,
                created_at TEXT,
                resolved_at TEXT
            )
        """)


@contextmanager
def get_db():
    conn = sqlite3.connect(str(DB_PATH))
    conn.row_factory = sqlite3.Row
    try:
        yield conn
        conn.commit()
    finally:
        conn.close()


# --- Models ---
class SubmitRequest(BaseModel):
    diff: str
    description: str = ""
    branch: str = ""
    files_changed: list[str] = []
    additions: int = 0
    deletions: int = 0


class RejectRequest(BaseModel):
    comment: str = ""


# --- Helpers ---
def check_token(request: Request):
    if not API_TOKEN:
        return
    auth = request.headers.get("Authorization", "")
    if auth != f"Bearer {API_TOKEN}":
        raise HTTPException(401, "Invalid API token")


def send_sms(review_id: str, description: str, stats: str):
    """Send SMS notification via carrier email gateway (runs in background thread)."""
    if not all([SMS_EMAIL, SMTP_USER, SMTP_PASSWORD]):
        print(f"[sms] Not configured, skipping for {review_id}")
        return

    def _send():
        url = f"{GATEWAY_URL}/review/{review_id}"
        body = f"Review: {description[:50]}\n{stats}\n{url}"
        msg = MIMEText(body)
        msg["From"] = SMTP_USER
        msg["To"] = SMS_EMAIL
        msg["Subject"] = ""
        try:
            with smtplib.SMTP(SMTP_HOST, SMTP_PORT) as server:
                server.starttls()
                server.login(SMTP_USER, SMTP_PASSWORD)
                server.send_message(msg)
            print(f"[sms] Sent for {review_id}")
        except Exception as e:
            print(f"[sms] Failed: {e}")

    threading.Thread(target=_send, daemon=True).start()


# --- Routes ---
@app.get("/", response_class=HTMLResponse)
async def index():
    with get_db() as db:
        rows = db.execute(
            "SELECT id, description, branch, stats, status, created_at FROM reviews ORDER BY created_at DESC LIMIT 20"
        ).fetchall()
    items = ""
    for r in rows:
        color = {"pending": "#fbbf24", "approved": "#22c55e", "rejected": "#ef4444"}.get(r["status"], "#94a3b8")
        items += f'<tr><td><a href="/review/{r["id"]}" style="color:#60a5fa">{r["id"]}</a></td>'
        items += f'<td>{r["description"] or "-"}</td><td>{r["branch"] or "-"}</td>'
        items += f'<td>{r["stats"] or "-"}</td>'
        items += f'<td style="color:{color};font-weight:600">{r["status"].upper()}</td>'
        items += f'<td style="color:#94a3b8">{r["created_at"][:16] if r["created_at"] else "-"}</td></tr>'
    return f"""<!DOCTYPE html><html><head><meta charset="UTF-8"><title>Approval Gateway</title>
<style>body{{background:#0f172a;color:#e2e8f0;font-family:system-ui;padding:24px}}
table{{width:100%;border-collapse:collapse}}th,td{{padding:8px 12px;text-align:left;border-bottom:1px solid #334155}}
th{{color:#94a3b8;font-size:12px;text-transform:uppercase}}a{{text-decoration:none}}</style></head>
<body><h2 style="margin-bottom:16px">Approval Gateway</h2>
<table><tr><th>ID</th><th>Description</th><th>Branch</th><th>Stats</th><th>Status</th><th>Created</th></tr>
{items}</table></body></html>"""


@app.post("/api/submit")
async def submit_review(req: SubmitRequest, request: Request):
    check_token(request)
    review_id = uuid.uuid4().hex[:12]
    now = datetime.now(timezone.utc).isoformat()
    stats = f"+{req.additions}/-{req.deletions}"
    with get_db() as db:
        db.execute(
            "INSERT INTO reviews (id, description, branch, diff_text, files_changed, stats, status, created_at) "
            "VALUES (?, ?, ?, ?, ?, ?, 'pending', ?)",
            (review_id, req.description, req.branch, req.diff,
             ",".join(req.files_changed), stats, now)
        )
    send_sms(review_id, req.description or "New diff", f"{len(req.files_changed)} files {stats}")
    return {"review_id": review_id, "url": f"{GATEWAY_URL}/review/{review_id}"}


@app.get("/review/{review_id}", response_class=HTMLResponse)
async def review_page(review_id: str):
    with get_db() as db:
        row = db.execute("SELECT id FROM reviews WHERE id = ?", (review_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Review not found")
    return REVIEW_HTML


@app.get("/api/review/{review_id}")
async def get_review(review_id: str):
    with get_db() as db:
        row = db.execute("SELECT * FROM reviews WHERE id = ?", (review_id,)).fetchone()
    if not row:
        raise HTTPException(404, "Review not found")
    return dict(row)


@app.post("/api/review/{review_id}/approve")
async def approve_review(review_id: str):
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as db:
        row = db.execute("SELECT status FROM reviews WHERE id = ?", (review_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Review not found")
        if row["status"] != "pending":
            raise HTTPException(409, f"Already {row['status']}")
        db.execute("UPDATE reviews SET status='approved', resolved_at=? WHERE id=?", (now, review_id))
    return {"status": "approved"}


@app.post("/api/review/{review_id}/reject")
async def reject_review(review_id: str, req: RejectRequest):
    now = datetime.now(timezone.utc).isoformat()
    with get_db() as db:
        row = db.execute("SELECT status FROM reviews WHERE id = ?", (review_id,)).fetchone()
        if not row:
            raise HTTPException(404, "Review not found")
        if row["status"] != "pending":
            raise HTTPException(409, f"Already {row['status']}")
        db.execute(
            "UPDATE reviews SET status='rejected', reject_comment=?, resolved_at=? WHERE id=?",
            (req.comment, now, review_id)
        )
    return {"status": "rejected", "comment": req.comment}


@app.get("/api/review/{review_id}/status")
async def review_status(review_id: str):
    with get_db() as db:
        row = db.execute(
            "SELECT status, reject_comment FROM reviews WHERE id = ?", (review_id,)
        ).fetchone()
    if not row:
        raise HTTPException(404, "Review not found")
    return dict(row)


@app.get("/health")
async def health():
    with get_db() as db:
        pending = db.execute("SELECT COUNT(*) as c FROM reviews WHERE status='pending'").fetchone()["c"]
    return {"status": "ok", "pending_reviews": pending}


@app.on_event("startup")
async def startup():
    global REVIEW_HTML
    init_db()
    if TEMPLATE_PATH.exists():
        REVIEW_HTML = TEMPLATE_PATH.read_text(encoding="utf-8")
    else:
        REVIEW_HTML = "<h1>review.html not found — place it next to approval_server.py</h1>"
    print(f"[gateway] Listening on {GATEWAY_URL}")
    print(f"[gateway] SMS → {SMS_EMAIL or '(not configured)'}")
