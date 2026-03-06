#!/usr/bin/env python3
"""Fix: header detection needs 'order#' not just 'order'."""

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP, "r") as f:
    code = f.read()

# Fix XLS: "order" -> "order#" for header detection
old = '''            if any("order" in v for v in vals):'''
new = '''            if any("order#" in v for v in vals):'''
if old in code:
    code = code.replace(old, new)
    print("[1/2] Fixed XLS header detection (order -> order#).")
else:
    print("[1/2] WARN: XLS pattern not found.")

# Fix XLSX: same
old2 = '''            if any("order" in str(v).lower() for v in r if v):'''
new2 = '''            if any("order#" in str(v).lower() for v in r if v):'''
if old2 in code:
    code = code.replace(old2, new2)
    print("[2/2] Fixed XLSX header detection.")
else:
    print("[2/2] WARN: XLSX pattern not found.")

with open(APP, "w") as f:
    f.write(code)

# Clear data
import psycopg2, sys
sys.path.insert(0, "/root/csl-bot/csl-doc-tracker")
import config
conn = psycopg2.connect(
    host=config.DB_HOST, port=config.DB_PORT,
    dbname=config.DB_NAME, user=config.DB_USER, password=config.DB_PASSWORD
)
cur = conn.cursor()
cur.execute("DELETE FROM unbilled_orders")
conn.commit()
cur.close()
conn.close()
print("Cleared data. Restart + re-upload needed.")
