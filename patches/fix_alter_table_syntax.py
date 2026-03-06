#!/usr/bin/env python3
"""Fix the ALTER TABLE syntax error caused by patch_ftl_enhancements.py inserting
the ALTER TABLE block inside the original try/except block."""

FILE = "/root/csl-bot/csl-doc-tracker/app.py"

with open(FILE) as f:
    code = f.read()

# The broken pattern: ALTER TABLE block was inserted INSIDE the original try block,
# before log.info("driver_contacts table ready"), breaking the try/except structure.
# Fix: remove the ALTER block from inside, close the original try/except properly,
# then add the ALTER block as a separate try/except after.

old = '''
        # Add new FTL columns if missing
        try:
            with db.get_conn() as conn:
                with db.get_cursor(conn) as cur:
                    cur.execute("""
                        ALTER TABLE driver_contacts
                            ADD COLUMN IF NOT EXISTS carrier_email VARCHAR(200),
                            ADD COLUMN IF NOT EXISTS trailer_number VARCHAR(50),
                            ADD COLUMN IF NOT EXISTS macropoint_url TEXT
                    """)
            log.info("driver_contacts FTL columns ready")
        except Exception as e:
            log.warning("Could not add FTL columns to driver_contacts: %s", e)

    log.info("driver_contacts table ready")
    except Exception as e:
        log.warning("Could not create driver_contacts table: %s", e)'''

new = '''
        log.info("driver_contacts table ready")
    except Exception as e:
        log.warning("Could not create driver_contacts table: %s", e)

    # Add new FTL columns if missing
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute("""
                    ALTER TABLE driver_contacts
                        ADD COLUMN IF NOT EXISTS carrier_email VARCHAR(200),
                        ADD COLUMN IF NOT EXISTS trailer_number VARCHAR(50),
                        ADD COLUMN IF NOT EXISTS macropoint_url TEXT
                """)
        log.info("driver_contacts FTL columns ready")
    except Exception as e:
        log.warning("Could not add FTL columns to driver_contacts: %s", e)'''

if old in code:
    code = code.replace(old, new, 1)
    with open(FILE, "w") as f:
        f.write(code)
    print("FIXED: Moved ALTER TABLE block after original try/except")
else:
    print("ERROR: Could not find the broken pattern")
    # Debug: show what's around line 1700
    lines = code.split('\n')
    for i in range(max(0, 1698), min(len(lines), 1720)):
        print(f"  {i+1}: {lines[i]}")
