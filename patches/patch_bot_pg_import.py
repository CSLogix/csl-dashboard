#!/usr/bin/env python3
"""
Patch csl_bot.py to dual-write to Postgres alongside Google Sheets.
Adds pg_update_shipment() after each scrape result and pg_archive_shipment()
in the archive function.
"""
import shutil, datetime, sys

TARGET = "/root/csl-bot/csl_bot.py"
BAK = TARGET + f".bak_pg_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"

shutil.copy2(TARGET, BAK)
print(f"Backup: {BAK}")

with open(TARGET, "r") as f:
    src = f.read()

changes = 0

# ── 1. Add import after load_dotenv() ────────────────────────────────────────
anchor1 = "load_dotenv()\n\nSHEET_ID"
if anchor1 in src:
    src = src.replace(
        anchor1,
        "load_dotenv()\n\n"
        "from csl_pg_writer import pg_update_shipment, pg_archive_shipment\n\n"
        "SHEET_ID",
        1
    )
    changes += 1
    print("[1/3] Added pg_writer import")
else:
    print("[1/3] SKIP: Could not find import anchor")

# ── 2. Dual-write in per-job loop after new_check assignment ──────────────────
anchor2 = '                new_check[container_key] = current\n\n                prev           = last_check.get(container_key, {})'
if anchor2 in src:
    injection = (
        '                new_check[container_key] = current\n'
        '\n'
        '                # ── PG dual-write ──\n'
        '                _efj = (job["row_data"][0].strip() if job.get("row_data") else "")\n'
        '                if _efj and not args.dry_run:\n'
        '                    pg_update_shipment(\n'
        '                        _efj,\n'
        '                        eta=current["eta"] or None,\n'
        '                        pickup_date=current["lfd"] or None,\n'
        '                        return_date=current["return_date"] or None,\n'
        '                        status=current["status"] or None,\n'
        '                        account=tab_name,\n'
        '                        move_type="Dray Import",\n'
        '                    )\n'
        '\n'
        '                prev           = last_check.get(container_key, {})'
    )
    src = src.replace(anchor2, injection, 1)
    changes += 1
    print("[2/3] Added PG dual-write in per-job loop")
else:
    print("[2/3] SKIP: Could not find per-job anchor")

# ── 3. Archive dual-write after dest_ws.append_row ───────────────────────────
anchor3 = '        dest_ws.append_row(row, value_input_option="USER_ENTERED")\n        print(f"  Archived row {sheet_row}'
if anchor3 in src:
    injection3 = (
        '        dest_ws.append_row(row, value_input_option="USER_ENTERED")\n'
        '        pg_archive_shipment(efj_num)\n'
        '        print(f"  Archived row {sheet_row}'
    )
    src = src.replace(anchor3, injection3, 1)
    changes += 1
    print("[3/3] Added PG archive in archive_completed_row()")
else:
    print("[3/3] SKIP: Could not find archive anchor")

with open(TARGET, "w") as f:
    f.write(src)

print(f"\nDone — {changes}/3 patches applied to {TARGET}")
if changes < 3:
    print("WARNING: Not all patches applied. Check anchors manually.")
    sys.exit(1)
