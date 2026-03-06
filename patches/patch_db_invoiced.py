"""Add invoiced helper functions to database.py"""

DB_FILE = '/root/csl-bot/csl-doc-tracker/database.py'

with open(DB_FILE, 'r') as f:
    code = f.read()

NEW_FUNCS = '''

# ---------------------------------------------------------------------------
# Invoiced status
# ---------------------------------------------------------------------------

def set_load_invoiced(load_number: str, invoiced: bool):
    """Set the invoiced flag for a load by its load_number (EFJ#)."""
    with get_conn() as conn:
        with get_cursor(conn) as cur:
            cur.execute(
                "UPDATE loads SET invoiced = %s, updated_at = NOW() WHERE load_number = %s",
                (invoiced, load_number),
            )


def get_invoiced_map() -> dict:
    """Return {load_number: bool} for all loads."""
    with get_cursor() as cur:
        cur.execute("SELECT load_number, invoiced FROM loads")
        return {row["load_number"]: row["invoiced"] for row in cur.fetchall()}
'''

# Append at end of file
code = code.rstrip() + NEW_FUNCS + '\n'

with open(DB_FILE, 'w') as f:
    f.write(code)

print('database.py: added set_load_invoiced() and get_invoiced_map()')
