"""Add auto-resize + compression to avatar uploads.
Resizes to 200x200 circle-friendly square, compresses to JPEG/PNG."""

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP, "r") as f:
    code = f.read()

# Find the non-PDF save path and add resize logic after it
old = '''    else:
        unique_name = f"{_uuid.uuid4().hex[:8]}_{rep_name}{ext}"
        save_path = os.path.join("uploads", "avatars", unique_name)

    # Remove old avatar if exists
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:'''

new = '''    else:
        unique_name = f"{_uuid.uuid4().hex[:8]}_{rep_name}{ext}"
        save_path = os.path.join("uploads", "avatars", unique_name)

    # Remove old avatar if exists
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:'''

# That's the same — I need a different approach. Let me add resize after the file is saved.
# Find the spot right before the DB insert where the file has been written

old_block = '''            if not os.path.exists(save_path):
                content = await file.read()
                with open(save_path, "wb") as f:
                    f.write(content)

            cur.execute("""
                INSERT INTO team_profiles (rep_name, avatar_filename, updated_at)
                VALUES (%s, %s, NOW())
                ON CONFLICT (rep_name)
                DO UPDATE SET avatar_filename = EXCLUDED.avatar_filename, updated_at = NOW()
            """, (rep_name, unique_name))'''

new_block = '''            if not os.path.exists(save_path):
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
            """, (rep_name, unique_name))'''

if old_block in code:
    code = code.replace(old_block, new_block, 1)
    print("Avatar auto-resize (200x200 + JPEG compress) added")
else:
    print("ERROR: Could not find target block")
    exit(1)

with open(APP, "w") as f:
    f.write(code)

print("Done. Restart csl-dashboard.")
