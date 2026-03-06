"""Fix SPA catch-all to serve static files (logo.svg, astrobot.png) from dist/."""
import re

APP_PY = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP_PY, "r") as f:
    content = f.read()

old = '''@app.get("/app")
@app.get("/app/{path:path}")
async def react_spa(path: str = ""):
    """Serve React SPA for all /app/* routes."""
    if _react_index.exists():
        return FileResponse(str(_react_index), media_type="text/html")
    return RedirectResponse("/legacy", status_code=302)'''

new = '''@app.get("/app")
@app.get("/app/{path:path}")
async def react_spa(path: str = ""):
    """Serve React SPA for all /app/* routes."""
    # Serve actual static files from dist/ if they exist (images, etc.)
    if path:
        import mimetypes as _mt
        static_file = _react_dist / path
        if static_file.is_file():
            mime, _ = _mt.guess_type(str(static_file))
            return FileResponse(str(static_file), media_type=mime or "application/octet-stream")
    if _react_index.exists():
        return FileResponse(str(_react_index), media_type="text/html")
    return RedirectResponse("/legacy", status_code=302)'''

if old in content:
    content = content.replace(old, new)
    with open(APP_PY, "w") as f:
        f.write(content)
    print("PATCHED OK — SPA now serves static files from dist/")
else:
    print("ERROR: Old block not found. Checking current state...")
    # Show what's around the SPA route
    lines = content.split("\n")
    for i, line in enumerate(lines):
        if "react_spa" in line:
            start = max(0, i - 2)
            end = min(len(lines), i + 12)
            print(f"\nLines {start+1}-{end+1}:")
            for j in range(start, end):
                print(f"  {j+1}: {lines[j]}")
