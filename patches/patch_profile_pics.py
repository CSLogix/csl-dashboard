#!/usr/bin/env python3
"""Patch: Add profile picture upload/serve endpoints for team reps.

Adds:
  - team_profiles table (rep_name, avatar_filename, subtitle)
  - POST /api/team/{rep_name}/avatar  — upload avatar
  - GET  /api/team/avatar/{rep_name}  — serve avatar image
  - DELETE /api/team/{rep_name}/avatar — remove avatar
  - GET  /api/team/profiles           — list all profiles
"""

APP_FILE = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP_FILE, "r") as f:
    code = f.read()

# ─── 1. Ensure uploads/avatars directory is created ───
if "uploads/avatars" not in code:
    # Find the uploads dir makedirs and add avatars subdir after it
    import re
    makedirs_match = re.search(r'os\.makedirs\("uploads"[^)]*\)', code)
    if makedirs_match:
        insert_after = makedirs_match.end()
        code = code[:insert_after] + '\n    os.makedirs("uploads/avatars", exist_ok=True)' + code[insert_after:]
    else:
        print("WARNING: No uploads makedirs found, will create dir in startup")

# ─── 2. Create team_profiles table in startup ───
if "team_profiles" not in code:
    # Insert after the driver_contacts table creation block
    marker = 'log.info("driver_contacts table ready")'
    if marker in code:
        insert_pos = code.index(marker) + len(marker)
        table_block = '''

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
        log.warning("Could not create team_profiles table: %s", e)'''
        code = code[:insert_pos] + table_block + code[insert_pos:]
    else:
        print("WARNING: Could not find driver_contacts marker")

# ─── 3. Add avatar endpoints before the React catch-all ───
if "/api/team/profiles" not in code:
    # Insert before the React index catch-all route
    marker = '_react_index = Path(__file__).parent / "static" / "dist" / "index.html"'
    if marker in code:
        insert_pos = code.index(marker)
    else:
        # Fallback: before last 200 chars
        insert_pos = len(code) - 200

    endpoints = '''
# ═══════════════════════════════════════════════════════════════
# TEAM PROFILE ENDPOINTS (avatars + subtitles)
# ═══════════════════════════════════════════════════════════════

@app.get("/api/team/profiles")
async def get_team_profiles():
    """Return all team profile data (avatars + subtitles)."""
    with db.get_cursor() as cur:
        cur.execute("SELECT rep_name, avatar_filename, subtitle FROM team_profiles")
        rows = cur.fetchall()
    profiles = {}
    for row in rows:
        profiles[row[0]] = {
            "avatar_url": f"/api/team/avatar/{row[0]}" if row[1] else None,
            "subtitle": row[2],
        }
    return {"profiles": profiles}


@app.post("/api/team/{rep_name}/avatar")
async def upload_avatar(rep_name: str, file: UploadFile = File(...)):
    """Upload a profile picture for a team rep."""
    import uuid as _uuid
    allowed = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed:
        return JSONResponse(status_code=400, content={"error": f"Invalid file type. Allowed: {', '.join(allowed)}"})

    unique_name = f"{_uuid.uuid4().hex[:8]}_{rep_name}{ext}"
    save_path = os.path.join("uploads", "avatars", unique_name)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)

    # Remove old avatar if exists
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("SELECT avatar_filename FROM team_profiles WHERE rep_name = %s", (rep_name,))
            old = cur.fetchone()
            if old and old[0]:
                old_path = os.path.join("uploads", "avatars", old[0])
                if os.path.exists(old_path):
                    os.remove(old_path)

            content = await file.read()
            with open(save_path, "wb") as f:
                f.write(content)

            cur.execute("""
                INSERT INTO team_profiles (rep_name, avatar_filename, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (rep_name)
                DO UPDATE SET avatar_filename = EXCLUDED.avatar_filename, updated_at = NOW()
            """, (rep_name, unique_name))

    return {"ok": True, "avatar_url": f"/api/team/avatar/{rep_name}"}


@app.delete("/api/team/{rep_name}/avatar")
async def delete_avatar(rep_name: str):
    """Remove a rep's profile picture."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("SELECT avatar_filename FROM team_profiles WHERE rep_name = %s", (rep_name,))
            row = cur.fetchone()
            if row and row[0]:
                path = os.path.join("uploads", "avatars", row[0])
                if os.path.exists(path):
                    os.remove(path)
                cur.execute("UPDATE team_profiles SET avatar_filename = NULL, updated_at = NOW() WHERE rep_name = %s", (rep_name,))
    return {"ok": True}


@app.get("/api/team/avatar/{rep_name}")
async def serve_avatar(rep_name: str):
    """Serve a rep's profile picture."""
    with db.get_cursor() as cur:
        cur.execute("SELECT avatar_filename FROM team_profiles WHERE rep_name = %s", (rep_name,))
        row = cur.fetchone()
    if not row or not row[0]:
        return JSONResponse(status_code=404, content={"error": "No avatar found"})
    path = os.path.join("uploads", "avatars", row[0])
    if not os.path.exists(path):
        return JSONResponse(status_code=404, content={"error": "File not found"})
    import mimetypes
    mime = mimetypes.guess_type(path)[0] or "image/png"
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "public, max-age=3600"})


'''
    code = code[:insert_pos] + endpoints + code[insert_pos:]

with open(APP_FILE, "w") as f:
    f.write(code)

# Create the avatars directory
os.makedirs("uploads/avatars", exist_ok=True)

print("=" * 60)
print("  Profile Picture Endpoints Patched Successfully!")
print("=" * 60)
print("  POST   /api/team/{rep_name}/avatar  — upload")
print("  GET    /api/team/avatar/{rep_name}  — serve image")
print("  DELETE /api/team/{rep_name}/avatar  — remove")
print("  GET    /api/team/profiles           — list all")
print()
print("  DB table: team_profiles")
print("  Storage:  uploads/avatars/")
print()
print("  Restart csl-dashboard to apply.")
