"""
FastAPI dashboard for CSL AI Dispatch — Operations Dashboard.
Thin orchestrator: imports routers, adds middleware, handles startup/shutdown.
"""

import os
import sys
import threading
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.middleware.cors import CORSMiddleware

# Make csl_logging importable from the parent directory
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from csl_logging import get_logger

import auth
import database as db
from shared import sheet_cache, templates

# Route modules
from routes import (
    auth as auth_routes,
    legacy,
    shipments,
    rate_iq,
    emails,
    loads,
    unbilled,
    team,
    directory,
    quotes,
    health,
    v2,
    webhooks,
    spa,
    users,
    email_drafts,
    ftl_quote,
    rep_management,
)

log = get_logger(__name__)

app = FastAPI(title="CSL AI Dispatch")

# ---------------------------------------------------------------------------
# Authentication middleware
# ---------------------------------------------------------------------------
PUBLIC_PATHS = {
    "/login", "/health", "/logo.svg", "/app", "/assets",
    "/", "/macropoint-webhook", "/webhook-test", "/track",
}


class AuthMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if (
            path in PUBLIC_PATHS
            or path.startswith("/static")
            or path.startswith("/app")
            or path.startswith("/assets")
            or path.startswith("/track")
            or path.endswith((".png", ".svg", ".ico", ".jpg", ".webp"))
        ):
            return await call_next(request)
        if path.startswith("/api/"):
            dev_key = os.environ.get("CSL_DEV_KEY", "")
            dev_ips = os.environ.get("CSL_DEV_IPS", "").split(",")
            if dev_key and request.headers.get("x-dev-key") == dev_key:
                client_ip = request.headers.get("x-real-ip", "")
                if client_ip in dev_ips:
                    request.state.user = {"user_id": 1, "username": "CSLogix-EFJ", "role": "admin", "rep_name": "John F"}
                    return await call_next(request)
            token = request.cookies.get("csl_session")
            user = auth.verify_session_token(token)
            if not user:
                return JSONResponse({"error": "unauthorized"}, status_code=401)
            request.state.user = user
            return await call_next(request)
        token = request.cookies.get("csl_session")
        user = auth.verify_session_token(token)
        if not user:
            return RedirectResponse("/login", status_code=302)
        request.state.user = user
        return await call_next(request)


app.add_middleware(AuthMiddleware)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://localhost:5173", "http://localhost:5174", "http://localhost:3000"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# ---------------------------------------------------------------------------
# Static file mounts
# ---------------------------------------------------------------------------
_react_dist = Path(__file__).parent / "static" / "dist"
if _react_dist.exists():
    app.mount("/assets", StaticFiles(directory=str(_react_dist / "assets")), name="react-assets")


@app.get("/rateiq-bot.png")
async def _serve_rateiq_bot():
    f = _react_dist / "rateiq-bot.png"
    if f.exists():
        return FileResponse(str(f), media_type="image/png")
    return JSONResponse({"error": "not found"}, 404)


@app.get("/astrobot.png")
async def _serve_astrobot():
    f = _react_dist / "astrobot.png"
    if f.exists():
        return FileResponse(str(f), media_type="image/png")
    return JSONResponse({"error": "not found"}, 404)


@app.get("/logo.svg")
async def _serve_logo():
    f = _react_dist / "logo.svg"
    if f.exists():
        return FileResponse(str(f), media_type="image/svg+xml")
    return JSONResponse({"error": "not found"}, 404)

# ---------------------------------------------------------------------------
# Include all routers
# ---------------------------------------------------------------------------
app.include_router(auth_routes.router)
app.include_router(spa.router)
app.include_router(legacy.router)
app.include_router(shipments.router)
app.include_router(rate_iq.router)
app.include_router(emails.router)
app.include_router(loads.router)
app.include_router(unbilled.router)
app.include_router(team.router)
app.include_router(directory.router)
app.include_router(quotes.router)
app.include_router(health.router)
app.include_router(v2.router)
app.include_router(webhooks.router)
app.include_router(users.router)
app.include_router(email_drafts.router)
app.include_router(ftl_quote.router)
app.include_router(rep_management.router)

# ---------------------------------------------------------------------------
# Startup / Shutdown
# ---------------------------------------------------------------------------

@app.on_event("startup")
def startup():
    db.init_pool()
    auth.init()

    # Create driver_contacts table if not exists
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS driver_contacts (
                        efj VARCHAR(32) PRIMARY KEY,
                        driver_name VARCHAR(120),
                        driver_phone VARCHAR(30),
                        driver_email VARCHAR(120),
                        notes TEXT,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
        log.info("driver_contacts table ready")
    except Exception as e:
        log.warning("Could not create driver_contacts table: %s", e)

    # Create team_profiles table if not exists
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS team_profiles (
                        rep_name VARCHAR(64) PRIMARY KEY,
                        avatar_filename VARCHAR(256),
                        subtitle VARCHAR(256),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
        log.info("team_profiles table ready")
    except Exception as e:
        log.warning("Could not create team_profiles table: %s", e)

    # Create quotes table
    try:
        db.create_quotes_table()
    except Exception as e:
        log.warning("Could not create quotes table: %s", e)

    # Create carriers table
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS carriers (
                        id              SERIAL PRIMARY KEY,
                        carrier_name    VARCHAR(256) NOT NULL,
                        mc_number       VARCHAR(32),
                        dot_number      VARCHAR(32),
                        contact_email   VARCHAR(256),
                        contact_phone   VARCHAR(64),
                        contact_name    VARCHAR(256),
                        regions         TEXT,
                        ports           TEXT,
                        rail_ramps      TEXT,
                        equipment_types TEXT,
                        notes           TEXT,
                        source          VARCHAR(32) DEFAULT 'manual',
                        pickup_area     VARCHAR(256),
                        destination_area VARCHAR(256),
                        date_quoted     DATE,
                        v_code          VARCHAR(64),
                        created_at      TIMESTAMPTZ DEFAULT NOW(),
                        updated_at      TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute("CREATE UNIQUE INDEX IF NOT EXISTS idx_carriers_mc ON carriers(mc_number) WHERE mc_number IS NOT NULL AND mc_number != ''")
        log.info("carriers table ready")
    except Exception as e:
        log.warning("Could not create carriers table: %s", e)

    # Create warehouses + warehouse_rates tables
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS warehouses (
                        id              SERIAL PRIMARY KEY,
                        name            VARCHAR(256) NOT NULL,
                        mc_number       VARCHAR(32),
                        region          VARCHAR(64),
                        address         TEXT,
                        city            VARCHAR(128),
                        state           VARCHAR(4),
                        zip_code        VARCHAR(12),
                        contact_name    VARCHAR(256),
                        contact_email   VARCHAR(256),
                        contact_phone   VARCHAR(64),
                        services        TEXT,
                        notes           TEXT,
                        source          VARCHAR(32) DEFAULT 'manual',
                        pickup_area     VARCHAR(256),
                        destination_area VARCHAR(256),
                        date_quoted     DATE,
                        v_code          VARCHAR(64),
                        created_at      TIMESTAMPTZ DEFAULT NOW(),
                        updated_at      TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS warehouse_rates (
                        id              SERIAL PRIMARY KEY,
                        warehouse_id    INTEGER REFERENCES warehouses(id) ON DELETE CASCADE,
                        rate_type       VARCHAR(64) NOT NULL,
                        rate_amount     DECIMAL(10,2),
                        unit            VARCHAR(32),
                        description     TEXT,
                        effective_date  DATE,
                        notes           TEXT,
                        created_at      TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_warehouse_rates_wh ON warehouse_rates(warehouse_id)")
        log.info("warehouses + warehouse_rates tables ready")
    except Exception as e:
        log.warning("Could not create warehouse tables: %s", e)

    # Create lane_rates table
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS lane_rates (
                        id              SERIAL PRIMARY KEY,
                        port            VARCHAR(64),
                        destination     VARCHAR(256),
                        carrier_name    VARCHAR(256),
                        dray_rate       DECIMAL(10,2),
                        fsc             VARCHAR(32),
                        total           DECIMAL(10,2),
                        chassis_per_day DECIMAL(10,2),
                        prepull         DECIMAL(10,2),
                        storage_per_day DECIMAL(10,2),
                        detention       VARCHAR(64),
                        chassis_split   DECIMAL(10,2),
                        overweight      DECIMAL(10,2),
                        tolls           DECIMAL(10,2),
                        reefer          DECIMAL(10,2),
                        hazmat          DECIMAL(10,2),
                        all_in_total    DECIMAL(10,2),
                        rank            INTEGER,
                        equipment_type  VARCHAR(64),
                        move_type       VARCHAR(32) DEFAULT 'dray',
                        notes           TEXT,
                        source          VARCHAR(32) DEFAULT 'excel_import',
                        created_at      TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_lane_rates_port ON lane_rates(port)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_lane_rates_carrier ON lane_rates(carrier_name)")
        log.info("lane_rates table ready")
    except Exception as e:
        log.warning("Could not create lane_rates table: %s", e)

    # Create market_rates table (LoadMatch / benchmark data — no carrier)
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS market_rates (
                        id              SERIAL PRIMARY KEY,
                        rate_date       DATE,
                        terminal        VARCHAR(256),
                        origin          VARCHAR(256) NOT NULL,
                        destination     VARCHAR(256) NOT NULL,
                        base_rate       DECIMAL(10,2),
                        fsc_pct         DECIMAL(5,2) DEFAULT 0,
                        total           DECIMAL(10,2),
                        source          VARCHAR(64) DEFAULT 'loadmatch',
                        move_type       VARCHAR(32) DEFAULT 'dray',
                        notes           TEXT,
                        created_at      TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_market_rates_origin ON market_rates(origin)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_market_rates_dest ON market_rates(destination)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_market_rates_date ON market_rates(rate_date)")
        log.info("market_rates table ready")
    except Exception as e:
        log.warning("Could not create market_rates table: %s", e)

    # Create email_drafts table
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS email_drafts (
                        id          SERIAL PRIMARY KEY,
                        efj         VARCHAR NOT NULL,
                        account     VARCHAR,
                        milestone   VARCHAR NOT NULL,
                        to_email    VARCHAR NOT NULL,
                        cc_email    VARCHAR,
                        subject     VARCHAR NOT NULL,
                        body_html   TEXT NOT NULL,
                        status      VARCHAR DEFAULT 'draft',
                        created_at  TIMESTAMPTZ DEFAULT NOW(),
                        sent_at     TIMESTAMPTZ,
                        sent_by     VARCHAR
                    )
                """)
        log.info("email_drafts table ready")
    except Exception as e:
        log.warning("Could not create email_drafts table: %s", e)

    # Create rep_accounts table (rep -> accounts assignment)
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS rep_accounts (
                        rep_name VARCHAR(64) PRIMARY KEY,
                        accounts TEXT[] DEFAULT '{}',
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
        log.info("rep_accounts table ready")
    except Exception as e:
        log.warning("Could not create rep_accounts table: %s", e)

    # Create rep_tasks table (manual action items)
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS rep_tasks (
                        id SERIAL PRIMARY KEY,
                        rep VARCHAR(64) NOT NULL,
                        text TEXT NOT NULL,
                        efj VARCHAR(32),
                        auto_type VARCHAR(32),
                        assigned_by VARCHAR(64),
                        status VARCHAR(20) DEFAULT 'open',
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        completed_at TIMESTAMPTZ
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_rep_tasks_rep ON rep_tasks(rep)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_rep_tasks_status ON rep_tasks(status)")
                # Add assigned_by column if missing (existing tables)
                cur.execute("""
                    DO $$ BEGIN
                        ALTER TABLE rep_tasks ADD COLUMN assigned_by VARCHAR(64);
                    EXCEPTION WHEN duplicate_column THEN NULL;
                    END $$;
                """)
        log.info("rep_tasks table ready")
    except Exception as e:
        log.warning("Could not create rep_tasks table: %s", e)

    # Create ai_knowledge_base table (persistent AI memory)
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("""
                    CREATE TABLE IF NOT EXISTS ai_knowledge_base (
                        id SERIAL PRIMARY KEY,
                        category TEXT NOT NULL,
                        scope TEXT,
                        content TEXT NOT NULL,
                        source TEXT DEFAULT 'admin_entry',
                        active BOOLEAN DEFAULT TRUE,
                        created_at TIMESTAMPTZ DEFAULT NOW(),
                        updated_at TIMESTAMPTZ DEFAULT NOW()
                    )
                """)
                cur.execute("CREATE INDEX IF NOT EXISTS idx_kb_category ON ai_knowledge_base(category)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_kb_scope ON ai_knowledge_base(scope)")
                cur.execute("CREATE INDEX IF NOT EXISTS idx_kb_active ON ai_knowledge_base(active)")
        log.info("ai_knowledge_base table ready")
    except Exception as e:
        log.warning("Could not create ai_knowledge_base table: %s", e)

    # Pre-populate sheet cache in background
    threading.Thread(target=sheet_cache.refresh_if_needed, daemon=True).start()
    log.info("Dashboard started")


@app.on_event("shutdown")
def shutdown():
    db.close_pool()


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8080)
