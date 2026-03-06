"""Fix: Update the driver_contacts INSERT in add-load endpoint to match actual DB schema."""

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP, "r") as f:
    code = f.read()

old = '''        # Store FTL driver info in DB if provided
        if move_type == "FTL" and (driver_phone or trailer or carrier_email or mp_url):
            try:
                with db.get_conn() as conn:
                    with db.get_cursor(conn) as cur:
                        cur.execute(
                            """INSERT INTO driver_contacts (efj, driver_phone, trailer, carrier_email, macropoint_url, updated_at)
                               VALUES (%s, %s, %s, %s, %s, NOW())
                               ON CONFLICT (efj) DO UPDATE SET
                                 driver_phone = EXCLUDED.driver_phone,
                                 trailer = EXCLUDED.trailer,
                                 carrier_email = EXCLUDED.carrier_email,
                                 macropoint_url = EXCLUDED.macropoint_url,
                                 updated_at = NOW()""",
                            (efj, driver_phone or None, trailer or None, carrier_email or None, mp_url or None),
                        )
            except Exception as db_err:
                log.warning("Driver contact save failed for %s: %s", efj, db_err)'''

new = '''        # Store FTL driver info in DB if provided
        if move_type == "FTL" and (driver_phone or carrier_email):
            try:
                # Build notes with trailer/MP URL info
                extra_notes = []
                if trailer:
                    extra_notes.append(f"Trailer: {trailer}")
                if mp_url:
                    extra_notes.append(f"MP: {mp_url}")
                notes_str = " | ".join(extra_notes) or None
                with db.get_conn() as conn:
                    with db.get_cursor(conn) as cur:
                        cur.execute(
                            """INSERT INTO driver_contacts (efj, driver_phone, driver_email, notes, updated_at)
                               VALUES (%s, %s, %s, %s, NOW())
                               ON CONFLICT (efj) DO UPDATE SET
                                 driver_phone = COALESCE(EXCLUDED.driver_phone, driver_contacts.driver_phone),
                                 driver_email = COALESCE(EXCLUDED.driver_email, driver_contacts.driver_email),
                                 notes        = COALESCE(EXCLUDED.notes, driver_contacts.notes),
                                 updated_at = NOW()""",
                            (efj, driver_phone or None, carrier_email or None, notes_str),
                        )
            except Exception as db_err:
                log.warning("Driver contact save failed for %s: %s", efj, db_err)'''

if old not in code:
    print("ERROR: target not found")
    exit(1)

code = code.replace(old, new, 1)

with open(APP, "w") as f:
    f.write(code)

print("OK — driver_contacts INSERT fixed to match schema")
