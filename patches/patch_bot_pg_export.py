#!/usr/bin/env python3
"""
Patch export_monitor.py to dual-write to Postgres alongside Google Sheets.

Three changes:
1. Import csl_pg_writer
2. Build a sheet_row→efj map + PG dual-write after sheet batch writes
3. PG archive in archive_export_row()
"""
import shutil, datetime, sys

TARGET = "/root/csl-bot/export_monitor.py"
BAK = TARGET + f".bak_pg_{datetime.datetime.now().strftime('%Y%m%d_%H%M%S')}"

shutil.copy2(TARGET, BAK)
print(f"Backup: {BAK}")

with open(TARGET, "r") as f:
    src = f.read()

changes = 0

# ── 1. Add import after load_dotenv() ────────────────────────────────────────
anchor1 = "load_dotenv()\n\nSHEET_ID="
if anchor1 in src:
    src = src.replace(
        anchor1,
        "load_dotenv()\n\n"
        "from csl_pg_writer import pg_update_shipment, pg_archive_shipment\n\n"
        "SHEET_ID=",
        1
    )
    changes += 1
    print("[1/3] Added pg_writer import")
else:
    print("[1/3] SKIP: Could not find import anchor")

# ── 2. Build row→efj map in the loop + PG write after note batch ─────────────
# 2a: Initialize _row_efj map alongside other lists
anchor2a = "        tab_alerts=[];note_updates=[];sheet_updates=[];archive_jobs=[]"
if anchor2a in src:
    src = src.replace(
        anchor2a,
        "        tab_alerts=[];note_updates=[];sheet_updates=[];archive_jobs=[];_row_efj={}",
        1
    )
    changes += 1
    print("[2a/4] Added _row_efj dict init")
else:
    print("[2a/4] SKIP: Could not find list init anchor")

# 2b: Populate _row_efj at the start of per-row loop
anchor2b = '            key=f"{tab_name}:{efj}:{container}"'
if anchor2b in src:
    src = src.replace(
        anchor2b,
        '            if efj: _row_efj[sheet_row]=efj\n'
        '            key=f"{tab_name}:{efj}:{container}"',
        1
    )
    changes += 1
    print("[2b/4] Added _row_efj population")
else:
    print("[2b/4] SKIP: Could not find key= anchor")

# 2c: PG dual-write after note batch writes, before archive_jobs check
anchor2c = (
    '        if archive_jobs:\n'
    '            print(f"\\n  Archiving {len(archive_jobs)} gate-in row(s)...")'
)
if anchor2c in src:
    replacement2c = (
    '        # ── PG dual-write for notes ──\n'
    '        for _sr, _n in note_updates:\n'
    '            _e = _row_efj.get(_sr)\n'
    '            if _e: pg_update_shipment(_e, bot_notes=_n, account=tab_name, move_type="Dray Export")\n'
    '        if archive_jobs:\n'
    '            print(f"\\n  Archiving {len(archive_jobs)} gate-in row(s)...")'
    )
    src = src.replace(anchor2c, replacement2c, 1)
    changes += 1
    print("[2c/4] Added PG dual-write after note batch")
else:
    print("[2c/4] SKIP: Could not find archive_jobs anchor")

# ── 3. Archive dual-write after dest_ws.append_row ───────────────────────────
anchor3 = (
    '        dest_ws.append_row(row_data,value_input_option="RAW")\n'
    '        print(f"    Archived to {dest_tab}")'
)
if anchor3 in src:
    replacement3 = (
    '        dest_ws.append_row(row_data,value_input_option="RAW")\n'
    '        pg_archive_shipment(job["efj"])\n'
    '        print(f"    Archived to {dest_tab}")'
    )
    src = src.replace(anchor3, replacement3, 1)
    changes += 1
    print("[3/4] Added PG archive in archive_export_row()")
else:
    print("[3/4] SKIP: Could not find archive anchor")

with open(TARGET, "w") as f:
    f.write(src)

expected = 5
print(f"\nDone — {changes}/{expected} patches applied to {TARGET}")
if changes < expected:
    print("WARNING: Not all patches applied. Check anchors manually.")
    sys.exit(1)
