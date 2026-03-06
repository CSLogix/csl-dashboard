#!/usr/bin/env python3
"""
Patch ftl_monitor.py to dual-write to Postgres alongside Google Sheets.
"""
import shutil, datetime, sys

TARGET = "/root/csl-bot/ftl_monitor.py"
BAK = TARGET + f".bak_pg_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"

shutil.copy2(TARGET, BAK)
print(f"Backup: {BAK}")

with open(TARGET, "r") as f:
    src = f.read()

changes = 0

# ── 1. Add import after load_dotenv() ────────────────────────────────────────
anchor1 = "load_dotenv()\n\n\ndef _retry_on_quota"
if anchor1 in src:
    src = src.replace(
        anchor1,
        "load_dotenv()\n\n"
        "from csl_pg_writer import pg_update_shipment, pg_archive_shipment\n\n\n"
        "def _retry_on_quota",
        1
    )
    changes += 1
    print("[1/3] Added pg_writer import")
else:
    print("[1/3] SKIP: Could not find import anchor")

# ── 2. PG dual-write after successful sheet batch_update ─────────────────────
anchor2 = (
    '                        ws.batch_update(sheet_updates, value_input_option="RAW")\n'
    '                        print(f"    Sheet updated — note → O{row[\'sheet_row\']}")\n'
    '                    except Exception as exc:\n'
    '                        print(f"    WARNING: sheet write failed: {exc}")'
)
if anchor2 in src:
    replacement2 = (
        '                        ws.batch_update(sheet_updates, value_input_option="RAW")\n'
        '                        print(f"    Sheet updated — note → O{row[\'sheet_row\']}")\n'
        '                        # ── PG dual-write ──\n'
        '                        if row.get("efj"):\n'
        '                            pg_update_shipment(\n'
        '                                row["efj"],\n'
        '                                pickup_date=final_pickup or None,\n'
        '                                delivery_date=final_delivery or None,\n'
        '                                status=dropdown_val or None,\n'
        '                                bot_notes=final_notes or None,\n'
        '                                account=tab_name,\n'
        '                                move_type="FTL",\n'
        '                            )\n'
        '                    except Exception as exc:\n'
        '                        print(f"    WARNING: sheet write failed: {exc}")'
    )
    src = src.replace(anchor2, replacement2, 1)
    changes += 1
    print("[2/3] Added PG dual-write after batch update")
else:
    print("[2/3] SKIP: Could not find batch update anchor")

# ── 3. Archive dual-write after dest_ws.append_row ───────────────────────────
anchor3 = (
    '        dest_ws.append_row(row, value_input_option="USER_ENTERED")\n'
    '        print(f"  Archived FTL row {sheet_row}'
)
if anchor3 in src:
    replacement3 = (
        '        dest_ws.append_row(row, value_input_option="USER_ENTERED")\n'
        '        pg_archive_shipment(efj)\n'
        '        print(f"  Archived FTL row {sheet_row}'
    )
    src = src.replace(anchor3, replacement3, 1)
    changes += 1
    print("[3/3] Added PG archive in archive_ftl_row()")
else:
    print("[3/3] SKIP: Could not find archive anchor")

with open(TARGET, "w") as f:
    f.write(src)

print(f"\nDone — {changes}/3 patches applied to {TARGET}")
if changes < 3:
    print("WARNING: Not all patches applied. Check anchors manually.")
    sys.exit(1)
