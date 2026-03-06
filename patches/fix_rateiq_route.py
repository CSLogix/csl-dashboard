"""Fix: Add /rateiq-bot.png route properly to app.py"""

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP) as f:
    lines = f.readlines()

# Remove the broken merged line
clean = []
for line in lines:
    if "rateiq-bot.png" in line and "async def" in line:
        continue
    clean.append(line)

# Insert proper route before @app.get("/app")
route = '''@app.get("/rateiq-bot.png")
async def serve_rateiq_bot():
    _f = Path(__file__).parent / "static" / "dist" / "rateiq-bot.png"
    if _f.exists():
        return FileResponse(str(_f), media_type="image/png")
    return JSONResponse({"error": "not found"}, 404)

'''

final = []
for line in clean:
    if line.strip() == '@app.get("/app")':
        final.append(route)
    final.append(line)

with open(APP, "w") as f:
    f.writelines(final)

print("Fixed rateiq-bot route!")
