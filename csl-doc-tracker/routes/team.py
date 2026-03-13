import logging
import mimetypes
import os
import uuid as _uuid

from fastapi import APIRouter, UploadFile, File
from fastapi.responses import JSONResponse, FileResponse

import database as db

log = logging.getLogger(__name__)
router = APIRouter()


@router.get("/api/team/profiles")
async def get_team_profiles():
    """Return all team profile data (avatars + subtitles)."""
    with db.get_cursor() as cur:
        cur.execute("SELECT rep_name, avatar_filename, subtitle FROM team_profiles")
        rows = cur.fetchall()
    profiles = {}
    for row in rows:
        profiles[row["rep_name"]] = {
            "avatar_url": f"/api/team/avatar/{row['rep_name']}" if row.get("avatar_filename") else None,
            "subtitle": row.get("subtitle"),
        }
    return {"profiles": profiles}


@router.post("/api/team/{rep_name}/avatar")
async def upload_avatar(rep_name: str, file: UploadFile = File(...)):
    """Upload a profile picture for a team rep."""
    allowed = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed:
        return JSONResponse(status_code=400, content={"error": f"Invalid file type. Allowed: {', '.join(allowed)}"})

    os.makedirs(os.path.join("uploads", "avatars"), exist_ok=True)

    # If PDF, convert first page to PNG
    if ext == ".pdf":
        import tempfile
        from pdf2image import convert_from_bytes
        pdf_bytes = await file.read()
        try:
            images = convert_from_bytes(pdf_bytes, first_page=1, last_page=1, dpi=150)
            ext = ".png"
            unique_name = f"{_uuid.uuid4().hex[:8]}_{rep_name}{ext}"
            save_path = os.path.join("uploads", "avatars", unique_name)
            images[0].save(save_path, "PNG")
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": f"Could not convert PDF: {str(e)}"})
    else:
        unique_name = f"{_uuid.uuid4().hex[:8]}_{rep_name}{ext}"
        save_path = os.path.join("uploads", "avatars", unique_name)

    # Remove old avatar if exists
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("SELECT avatar_filename FROM team_profiles WHERE rep_name = %s", (rep_name,))
            old = cur.fetchone()
            if old and old.get("avatar_filename"):
                old_path = os.path.join("uploads", "avatars", old["avatar_filename"])
                if os.path.exists(old_path):
                    os.remove(old_path)

            if not os.path.exists(save_path):
                content = await file.read()
                with open(save_path, "wb") as f:
                    f.write(content)

            # Auto-resize + compress avatar to 200x200
            try:
                from PIL import Image as PILImage
                img = PILImage.open(save_path)
                img = img.convert("RGB")
                # Center crop to square
                w, h = img.size
                side = min(w, h)
                left = (w - side) // 2
                top = (h - side) // 2
                img = img.crop((left, top, left + side, top + side))
                img = img.resize((200, 200), PILImage.LANCZOS)
                # Save as JPEG for smaller file size
                compressed_name = os.path.splitext(unique_name)[0] + ".jpg"
                compressed_path = os.path.join("uploads", "avatars", compressed_name)
                img.save(compressed_path, "JPEG", quality=85, optimize=True)
                # Remove original if different
                if compressed_path != save_path and os.path.exists(save_path):
                    os.remove(save_path)
                unique_name = compressed_name
                save_path = compressed_path
            except Exception as resize_err:
                import traceback; traceback.print_exc()
                pass  # keep original if resize fails

            cur.execute("""
                INSERT INTO team_profiles (rep_name, avatar_filename, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (rep_name)
                DO UPDATE SET avatar_filename = EXCLUDED.avatar_filename, updated_at = NOW()
            """, (rep_name, unique_name))

    return {"ok": True, "avatar_url": f"/api/team/avatar/{rep_name}"}


@router.delete("/api/team/{rep_name}/avatar")
async def delete_avatar(rep_name: str):
    """Remove a rep's profile picture."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("SELECT avatar_filename FROM team_profiles WHERE rep_name = %s", (rep_name,))
            row = cur.fetchone()
            if row and row.get("avatar_filename"):
                path = os.path.join("uploads", "avatars", row["avatar_filename"])
                if os.path.exists(path):
                    os.remove(path)
                cur.execute("UPDATE team_profiles SET avatar_filename = NULL, updated_at = NOW() WHERE rep_name = %s", (rep_name,))
    return {"ok": True}


@router.get("/api/team/avatar/{rep_name}")
async def serve_avatar(rep_name: str):
    """Serve a rep's profile picture."""
    with db.get_cursor() as cur:
        cur.execute("SELECT avatar_filename FROM team_profiles WHERE rep_name = %s", (rep_name,))
        row = cur.fetchone()
    if not row or not row.get("avatar_filename"):
        return JSONResponse(status_code=404, content={"error": "No avatar found"})
    path = os.path.join("uploads", "avatars", row["avatar_filename"])
    if not os.path.exists(path):
        return JSONResponse(status_code=404, content={"error": "File not found"})
    mime = mimetypes.guess_type(path)[0] or "image/png"
    return FileResponse(path, media_type=mime, headers={"Cache-Control": "public, max-age=3600"})
