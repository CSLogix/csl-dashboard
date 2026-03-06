"""Fix: Use correct cache invalidation attribute (_last not last_refresh)."""

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP, "r") as f:
    code = f.read()

old = "        sheet_cache.last_refresh = 0"
new = "        sheet_cache._last = 0"

if old not in code:
    print("Already fixed or not found")
    exit(0)

code = code.replace(old, new, 1)

with open(APP, "w") as f:
    f.write(code)

print("OK — cache invalidation fixed")
