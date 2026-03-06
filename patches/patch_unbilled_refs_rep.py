"""
Patch: Update unbilled orders parser + API to include REFERENCE-1/2/3
columns and assign rep based on bill_to → account → rep mapping.

Run: python3 /tmp/patch_unbilled_refs_rep.py
"""
import re

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP, "r") as f:
    code = f.read()

# ── 1. Add BILL_TO_REP mapping after the xlrd import ──
BILL_TO_REP_BLOCK = '''
# Mapping bill_to customer names → rep for unbilled orders
BILL_TO_REP = {
    "DHL GLOBAL FORWARDING": "John F",
    "DSV AIR": "Eli",
    "ALLROUND FORWARDING": "Radka",
    "BOVIET SOLAR": "Boviet",
    "C & L GLOBAL": "Janice",
    "CADI COMPANY": "Radka",
    "KRIPKE ENTERPRISES": "Radka",
    "MANITOULIN GLOBAL": "Radka",
    "ROSE CONTAINER": "Eli",
    "TOLEAD LOGISTICS": "Tolead",
    "USHA MARTIN": "Radka",
    "E SHIPPING": "Eli",
    "ESHIPPING": "Eli",
    "ISLAND WAY SORBET": "Radka",
    "MID AMERICA OVERSEAS": "Eli",
    "SUTTON HOME FASHIONS": "Radka",
    "MAMATA ENTERPRISES": "John F",
    "SEI ACQUISITION": "John F",
    "TEACHER CREATED": "Radka",
    "TEXAS INTERNATIONAL": "Radka",
    "COSCO SHIPPING": "Radka",
    "GEBRUDER WEISS": "Radka",
    "KIABSA TRADING": "Radka",
    "MD METAL RECYCLING": "Radka",
    "MITCHELLS TRANSPORT": "Radka",
    "SUPREME PLASTIC": "Radka",
    "TALATRANS": "Radka",
    "TRINITY LOGISTICS": "Radka",
    "WEST MOTOR FREIGHT": "Radka",
    "BETTER WAREHOUSING": "Radka",
    "KISHCO": "Eli",
    "MAO": "Eli",
    "MGF": "Radka",
    "MEIKO": "Radka",
    "TANERA": "Radka",
    "TCR": "Radka",
    "IWS": "Radka",
}

def _bill_to_rep(bill_to: str) -> str:
    """Match bill_to string to rep name using substring matching."""
    if not bill_to:
        return ""
    upper = bill_to.upper()
    for key, rep in BILL_TO_REP.items():
        if key.upper() in upper:
            return rep
    return ""

'''

# Insert after "from io import BytesIO"
anchor = "from io import BytesIO\n"
if anchor in code:
    code = code.replace(anchor, anchor + BILL_TO_REP_BLOCK, 1)
    print("[OK] Inserted BILL_TO_REP mapping")
else:
    print("[WARN] Could not find 'from io import BytesIO' anchor")

# ── 2. Update _map_unbilled_row to include ref1/ref2/ref3 ──
old_return = '''    return {
        "order_num": str(find(["Order"]) or "").strip(),
        "container": str(find(["Container"]) or "").strip(),
        "bill_to": str(find(["Bill"]) or "").strip(),
        "tractor": str(find(["Tractor"]) or "").strip(),
        "entered": safe_date(find(["Entered"])),
        "appt_date": safe_date(find(["Appt"])),
        "dliv_dt": safe_date(find(["DLIV"])),
        "act_dt": safe_date(find(["ACT"])),
    }'''

new_return = '''    bill_to = str(find(["Bill"]) or "").strip()
    return {
        "order_num": str(find(["Order"]) or "").strip(),
        "container": str(find(["Container"]) or "").strip(),
        "bill_to": bill_to,
        "ref1": str(find(["REFERENCE-1"]) or "").strip(),
        "ref2": str(find(["REFERENCE-2"]) or "").strip(),
        "ref3": str(find(["REFERENCE-3"]) or "").strip(),
        "tractor": str(find(["Tractor"]) or "").strip(),
        "entered": safe_date(find(["Entered"])),
        "appt_date": safe_date(find(["Appt"])),
        "dliv_dt": safe_date(find(["DLIV"])),
        "act_dt": safe_date(find(["ACT"])),
        "rep": _bill_to_rep(bill_to),
    }'''

if old_return in code:
    code = code.replace(old_return, new_return, 1)
    print("[OK] Updated _map_unbilled_row with ref1/ref2/ref3 and rep")
else:
    print("[WARN] Could not find old _map_unbilled_row return block")

# ── 3. Update INSERT statement to include ref1/ref2/ref3/rep ──
old_insert = '''                cur.execute(
                    """INSERT INTO unbilled_orders
                       (order_num, container, bill_to, tractor, entered, appt_date, dliv_dt, act_dt, age_days, upload_batch)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (m["order_num"], m["container"], m["bill_to"], m["tractor"],
                     m["entered"], m["appt_date"], m["dliv_dt"], m["act_dt"], age, batch_id)
                )'''

new_insert = '''                cur.execute(
                    """INSERT INTO unbilled_orders
                       (order_num, container, bill_to, ref1, ref2, ref3, tractor, entered, appt_date, dliv_dt, act_dt, age_days, rep, upload_batch)
                       VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)""",
                    (m["order_num"], m["container"], m["bill_to"], m["ref1"], m["ref2"], m["ref3"], m["tractor"],
                     m["entered"], m["appt_date"], m["dliv_dt"], m["act_dt"], age, m["rep"], batch_id)
                )'''

if old_insert in code:
    code = code.replace(old_insert, new_insert, 1)
    print("[OK] Updated INSERT statement")
else:
    print("[WARN] Could not find old INSERT statement")

# ── 4. Update SELECT in list API to include ref1/ref2/ref3/rep ──
old_select = '''        cur.execute(
            """SELECT id, order_num, container, bill_to, tractor,
                      entered::text, appt_date::text, dliv_dt::text, act_dt::text,
                      age_days, upload_batch, created_at::text
               FROM unbilled_orders
               WHERE dismissed = FALSE
               ORDER BY age_days DESC"""
        )'''

new_select = '''        cur.execute(
            """SELECT id, order_num, container, bill_to, ref1, ref2, ref3, tractor,
                      entered::text, appt_date::text, dliv_dt::text, act_dt::text,
                      age_days, rep, upload_batch, created_at::text
               FROM unbilled_orders
               WHERE dismissed = FALSE
               ORDER BY age_days DESC"""
        )'''

if old_select in code:
    code = code.replace(old_select, new_select, 1)
    print("[OK] Updated SELECT in unbilled list API")
else:
    print("[WARN] Could not find old SELECT statement")

# ── 5. Update stats API to include per-rep breakdown ──
old_stats_end = '''        by_customer = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT COALESCE(SUM(age_days), 0) as total_age FROM unbilled_orders WHERE dismissed = FALSE"'''

new_stats_end = '''        by_customer = [dict(r) for r in cur.fetchall()]
        cur.execute(
            """SELECT rep, COUNT(*) as cnt, MAX(age_days) as max_age
               FROM unbilled_orders WHERE dismissed = FALSE AND rep != ''
               GROUP BY rep ORDER BY cnt DESC"""
        )
        by_rep = [dict(r) for r in cur.fetchall()]
        cur.execute(
            "SELECT COALESCE(SUM(age_days), 0) as total_age FROM unbilled_orders WHERE dismissed = FALSE"'''

if old_stats_end in code:
    code = code.replace(old_stats_end, new_stats_end, 1)
    print("[OK] Added per-rep stats query")
else:
    print("[WARN] Could not find old stats block")

# Also update the stats return to include by_rep and oldest_age
old_stats_return = '    return JSONResponse({"count": count, "avg_age": avg_age, "by_customer": by_customer})'
new_stats_return = '''    oldest_age = max((r["max_age"] for r in by_customer), default=0) if by_customer else 0
    return JSONResponse({"count": count, "avg_age": avg_age, "oldest_age": oldest_age, "by_customer": by_customer, "by_rep": by_rep})'''

if old_stats_return in code:
    code = code.replace(old_stats_return, new_stats_return, 1)
    print("[OK] Updated stats return with by_rep and oldest_age")
else:
    print("[WARN] Could not find old stats return")


with open(APP, "w") as f:
    f.write(code)

print("\n[DONE] Patch applied. Restart csl-dashboard to take effect.")
