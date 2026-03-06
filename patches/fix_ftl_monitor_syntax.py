#!/usr/bin/env python3
"""Fix syntax error in ftl_monitor.py where mp_status parameter was appended incorrectly."""

FILE = "/root/csl-bot/ftl_monitor.py"

with open(FILE) as f:
    code = f.read()

changes = 0

# Fix 1: The mp_status parameter was added incorrectly
old = '''                    driver_phone=driver_phone,
                , mp_status=mp_load_status)'''

new = '''                    driver_phone=driver_phone,
                    mp_status=mp_load_status)'''

if old in code:
    code = code.replace(old, new, 1)
    changes += 1
    print("Fixed mp_status parameter placement")
else:
    # Try alternate pattern
    old2 = 'driver_phone=driver_phone,\n                , mp_status=mp_load_status)'
    if old2 in code:
        code = code.replace(old2, 'driver_phone=driver_phone,\n                    mp_status=mp_load_status)', 1)
        changes += 1
        print("Fixed mp_status parameter (alt pattern)")
    else:
        print("WARNING: Could not find broken mp_status pattern")
        # Show context
        if ", mp_status=mp_load_status)" in code:
            idx = code.index(", mp_status=mp_load_status)")
            context = code[max(0, idx-100):idx+50]
            print(f"Found at context: ...{repr(context)}...")

with open(FILE, "w") as f:
    f.write(code)

print(f"\nApplied {changes} fixes to ftl_monitor.py")
