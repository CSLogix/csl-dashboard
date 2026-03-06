#!/usr/bin/env python3
"""
Patch: Add margin_type column to quotes table + PATCH status endpoint
Changes:
  1. ALTER TABLE quotes ADD COLUMN margin_type VARCHAR DEFAULT 'pct'
  2. Include margin_type in POST/PUT quote handlers
  3. Add PATCH /api/quotes/{id}/status endpoint for quick status updates
"""
import subprocess, sys

APP_PATH = "/root/csl-bot/csl-doc-tracker/app.py"

def run(cmd):
    r = subprocess.run(cmd, shell=True, capture_output=True, text=True)
    print(r.stdout.strip() if r.stdout.strip() else r.stderr.strip())
    return r.returncode == 0

def patch():
    # ── 1. Add margin_type column to quotes table ──
    print("── Adding margin_type column to quotes table ──")
    run("""python3 -c "
import psycopg2
conn = psycopg2.connect('dbname=csl_bot')
cur = conn.cursor()
cur.execute(\\\"SELECT column_name FROM information_schema.columns WHERE table_name='quotes' AND column_name='margin_type'\\\")
if cur.fetchone():
    print('= margin_type column already exists')
else:
    cur.execute(\\\"ALTER TABLE quotes ADD COLUMN margin_type VARCHAR DEFAULT 'pct'\\\")
    conn.commit()
    print('+ Added margin_type column')
conn.close()
" """)

    # ── 2. Read app.py ──
    code = open(APP_PATH).read()
    changes = 0

    # ── 3. Add margin_type to quote INSERT (POST handler) ──
    # Find the INSERT in the POST /api/quotes handler
    if "margin_type" not in code.split("INSERT INTO quotes")[1].split("VALUES")[0] if "INSERT INTO quotes" in code else "":
        # Find the INSERT statement for quotes
        old_cols = "margin_pct, sell_subtotal"
        new_cols = "margin_pct, margin_type, sell_subtotal"
        # We need to be more surgical — find the quotes INSERT
        marker = "INSERT INTO quotes"
        idx = code.find(marker)
        if idx >= 0:
            # Find margin_pct in the INSERT column list (within ~300 chars of INSERT)
            block_end = idx + 500
            block = code[idx:block_end]
            if "margin_type" not in block.split("VALUES")[0]:
                # Add margin_type after margin_pct in columns
                col_old = "margin_pct, sell_subtotal"
                col_new = "margin_pct, margin_type, sell_subtotal"
                pos = code.find(col_old, idx)
                if pos and pos < block_end:
                    code = code[:pos] + col_new + code[pos+len(col_old):]
                    print("+ Added margin_type to INSERT columns")

                    # Now add the value placeholder
                    val_section = code[idx:idx+800]
                    # Count %s to figure out where to add
                    vals_start = code.find("VALUES", idx)
                    if vals_start:
                        # Find the %s for margin_pct and add one after it
                        # We need to add qd.get("margin_type","pct") to the values tuple
                        old_val = 'qd.get("margin_pct", 0), qd.get("sell_subtotal", 0)'
                        new_val = 'qd.get("margin_pct", 0), qd.get("margin_type", "pct"), qd.get("sell_subtotal", 0)'
                        pos2 = code.find(old_val, idx)
                        if pos2:
                            code = code[:pos2] + new_val + code[pos2+len(old_val):]
                            print("+ Added margin_type to INSERT values")
                            changes += 1

                        # Also need to add a %s
                        # Find the VALUES (%s, %s, ...) line
                        vals_line_start = code.find("VALUES (", idx)
                        if vals_line_start:
                            vals_line_end = code.find(")", vals_line_start)
                            vals_block = code[vals_line_start:vals_line_end+1]
                            # Count existing %s
                            pct_count = vals_block.count("%s")
                            # We need pct_count + 1, so add one more %s
                            # Find the spot after the margin_pct %s
                            # Easier: just count from the VALUES line
                            old_vals_str = ", ".join(["%s"] * pct_count)
                            new_vals_str = ", ".join(["%s"] * (pct_count + 1))
                            old_full = f"VALUES ({old_vals_str})"
                            new_full = f"VALUES ({new_vals_str})"
                            pos3 = code.find(old_full, idx)
                            if pos3 and pos3 < idx + 800:
                                code = code[:pos3] + new_full + code[pos3+len(old_full):]
                                print("+ Added %s placeholder for margin_type")
            else:
                print("= margin_type already in INSERT")
        else:
            print("! Could not find INSERT INTO quotes")
    else:
        print("= margin_type already in quotes INSERT")

    # ── 4. Add margin_type to quote UPDATE (PUT handler) ──
    put_marker = 'UPDATE quotes SET'
    put_idx = code.find(put_marker)
    if put_idx >= 0:
        put_block = code[put_idx:put_idx+500]
        if "margin_type" not in put_block.split("WHERE")[0]:
            old_u = "margin_pct=%s, sell_subtotal"
            new_u = "margin_pct=%s, margin_type=%s, sell_subtotal"
            pos = code.find(old_u, put_idx)
            if pos and pos < put_idx + 500:
                code = code[:pos] + new_u + code[pos+len(old_u):]
                print("+ Added margin_type to UPDATE SET")

                # Add value to tuple
                old_uv = 'qd.get("margin_pct", 0), qd.get("sell_subtotal", 0)'
                new_uv = 'qd.get("margin_pct", 0), qd.get("margin_type", "pct"), qd.get("sell_subtotal", 0)'
                pos2 = code.find(old_uv, put_idx)
                if pos2 and pos2 < put_idx + 800:
                    code = code[:pos2] + new_uv + code[pos2+len(old_uv):]
                    print("+ Added margin_type to UPDATE values")
                    changes += 1
        else:
            print("= margin_type already in UPDATE")
    else:
        print("! Could not find UPDATE quotes SET")

    # ── 5. Add PATCH /api/quotes/{id}/status endpoint ──
    if "/api/quotes/{quote_id}/status" not in code:
        # Find the GET /api/quotes/{quote_id} endpoint to insert after it
        anchor = '@app.get("/api/quotes/{quote_id}")'
        idx = code.find(anchor)
        if idx < 0:
            # Try alternate format
            anchor = "@app.get('/api/quotes/{quote_id}')"
            idx = code.find(anchor)

        if idx >= 0:
            # Find the next @app route after this one
            next_route = code.find("\n@app.", idx + len(anchor))
            if next_route < 0:
                next_route = len(code)

            patch_endpoint = '''

@app.patch("/api/quotes/{quote_id}/status")
async def update_quote_status(quote_id: int, request: Request):
    """Quick status update for a quote (won/lost/expired/sent)"""
    body = await request.json()
    new_status = body.get("status")
    if new_status not in ("draft", "sent", "accepted", "lost", "expired"):
        return JSONResponse({"error": "Invalid status"}, status_code=400)
    conn = db.get_conn()
    try:
        cur = conn.cursor()
        cur.execute(
            "UPDATE quotes SET status=%s, updated_at=NOW() WHERE id=%s RETURNING id, quote_number, status",
            (new_status, quote_id)
        )
        row = cur.fetchone()
        conn.commit()
        if not row:
            return JSONResponse({"error": "Quote not found"}, status_code=404)
        return {"id": row[0], "quote_number": row[1], "status": row[2]}
    except Exception as e:
        conn.rollback()
        return JSONResponse({"error": str(e)}, status_code=500)
    finally:
        db.put_conn(conn)

'''
            code = code[:next_route] + patch_endpoint + code[next_route:]
            print("+ Added PATCH /api/quotes/{id}/status endpoint")
            changes += 1
        else:
            print("! Could not find anchor for PATCH endpoint insertion")
    else:
        print("= PATCH /api/quotes/{id}/status already exists")

    # ── 6. Add margin_type to create_quotes_table ──
    if "margin_type" not in code.split("CREATE TABLE IF NOT EXISTS quotes")[1].split(")")[0] if "CREATE TABLE IF NOT EXISTS quotes" in code else "":
        old_tbl = "margin_pct NUMERIC,"
        new_tbl = "margin_pct NUMERIC,\n            margin_type VARCHAR DEFAULT 'pct',"
        idx = code.find("CREATE TABLE IF NOT EXISTS quotes")
        if idx >= 0:
            pos = code.find(old_tbl, idx)
            if pos and pos < idx + 800:
                code = code[:pos] + new_tbl + code[pos+len(old_tbl):]
                print("+ Added margin_type to CREATE TABLE")
                changes += 1
    else:
        print("= margin_type already in CREATE TABLE")

    if changes > 0:
        open(APP_PATH, "w").write(code)
        print(f"\n{changes} changes applied. Restart: systemctl restart csl-dashboard")
    else:
        print("\nNo changes needed.")

if __name__ == "__main__":
    patch()
