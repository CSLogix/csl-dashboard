#!/usr/bin/env python3
"""Fix broken multi-line f-string in csl_bot.py (line 1905)."""
path = "/root/csl-bot/csl_bot.py"

with open(path, "rb") as f:
    data = f.read()

# The broken pattern: print(f" followed by literal 0x0a then [{now_str}]
# We want to replace the 0x0a byte with the two bytes 0x5c 0x6e (\n escape)
target = b'print(f"\x0a[{now_str}] Dray Import cycle...")'
replacement = b'print(f"\\n[{now_str}] Dray Import cycle...")'

count = data.count(target)
print(f"Found {count} occurrences of broken f-string")
print(f"Target bytes: {target[7:12].hex()}")
print(f"Replacement bytes: {replacement[7:13].hex()}")

if count > 0:
    data = data.replace(target, replacement)
    with open(path, "wb") as f:
        f.write(data)
    print("Fixed!")

    # Verify
    with open(path, "rb") as f:
        verify = f.read()
    remaining = verify.count(target)
    has_fix = verify.count(replacement)
    print(f"Remaining broken: {remaining}, Fixed present: {has_fix}")
else:
    idx = data.find(b"Dray Import cycle")
    if idx >= 0:
        print(f"Context: {data[idx-20:idx+40]!r}")
