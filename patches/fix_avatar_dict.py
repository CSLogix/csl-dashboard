"""Fix avatar endpoints: RealDictCursor returns dicts, not tuples.
All row[0]/row[1]/row[2] must become row["column_name"]."""

import sys

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP, "r") as f:
    code = f.read()

fixes = [
    # Fix 1: get_team_profiles
    (
        '    for row in rows:\n        profiles[row[0]] = {\n            "avatar_url": f"/api/team/avatar/{row[0]}" if row[1] else None,\n            "subtitle": row[2],\n        }',
        '    for row in rows:\n        profiles[row["rep_name"]] = {\n            "avatar_url": f"/api/team/avatar/{row[\'rep_name\']}" if row.get("avatar_filename") else None,\n            "subtitle": row.get("subtitle"),\n        }',
    ),
    # Fix 2: upload_avatar - old file check
    (
        '            if old and old[0]:\n                old_path = os.path.join("uploads", "avatars", old[0])',
        '            if old and old.get("avatar_filename"):\n                old_path = os.path.join("uploads", "avatars", old["avatar_filename"])',
    ),
    # Fix 3: delete_avatar
    (
        '            if row and row[0]:\n                path = os.path.join("uploads", "avatars", row[0])',
        '            if row and row.get("avatar_filename"):\n                path = os.path.join("uploads", "avatars", row["avatar_filename"])',
    ),
    # Fix 4: serve_avatar
    (
        '    if not row or not row[0]:\n        return JSONResponse(status_code=404, content={"error": "No avatar found"})\n    path = os.path.join("uploads", "avatars", row[0])',
        '    if not row or not row.get("avatar_filename"):\n        return JSONResponse(status_code=404, content={"error": "No avatar found"})\n    path = os.path.join("uploads", "avatars", row["avatar_filename"])',
    ),
]

for i, (old, new) in enumerate(fixes, 1):
    if old in code:
        code = code.replace(old, new, 1)
        print(f"Fix {i}: applied")
    else:
        print(f"Fix {i}: NOT FOUND — may already be fixed")

with open(APP, "w") as f:
    f.write(code)

print("Done. Restart csl-dashboard.")
