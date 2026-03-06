#!/usr/bin/env python3
"""
Patch: Rate IQ API endpoints + enhanced tracking/doc summary
Adds:
  - /api/rate-iq (lane grouping + carrier scorecard)
  - /api/rate-iq/lane/{lane}
  - PATCH /api/rate-iq/{quote_id} (accept/reject)
  - /api/customer-reply-alerts + dismiss
  - /api/unclassified-documents
  - Stop timestamps in tracking-summary
  - Latest doc IDs in document-summary
  - "rate" + "unclassified" valid doc types
"""
import shutil, os, sys, re
from datetime import datetime

APP_PATH = "/root/csl-bot/csl-doc-tracker/app.py"

def backup(path):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{path}.bak_{ts}"
    shutil.copy2(path, bak)
    print(f"Backup: {bak}")
    return bak

def patch():
    if not os.path.exists(APP_PATH):
        print(f"ERROR: {APP_PATH} not found"); sys.exit(1)

    backup(APP_PATH)
    code = open(APP_PATH).read()

    # ── 1. Add stop timestamps to tracking-summary ──
    old_tracking = '''            "lastScraped": entry.get("last_scraped", ""),
        }
    return {"tracking": result}'''
    new_tracking = '''            "lastScraped": entry.get("last_scraped", ""),
            # Stop timestamps for slide view display
            "stop1Arrived": stop_times.get("stop1_arrived"),
            "stop1Departed": stop_times.get("stop1_departed"),
            "stop2Arrived": stop_times.get("stop2_arrived"),
            "stop2Departed": stop_times.get("stop2_departed"),
            "stop1Eta": stop_times.get("stop1_eta"),
            "stop2Eta": stop_times.get("stop2_eta"),
        }
    return {"tracking": result}'''

    if old_tracking in code:
        code = code.replace(old_tracking, new_tracking)
        print("✓ Added stop timestamps to tracking-summary")
    elif "stop1Arrived" in code:
        print("⊘ Stop timestamps already present")
    else:
        print("⚠ Could not find tracking-summary anchor — skipping")

    # ── 2. Enhance document-summary with latest_id ──
    old_docsummary = '''    with db.get_cursor() as cur:
        cur.execute("""
            SELECT efj, doc_type, COUNT(*) as cnt
            FROM load_documents
            GROUP BY efj, doc_type
            ORDER BY efj
        """)
        rows = cur.fetchall()
    result = {}
    for r in rows:
        efj_val = r["efj"] if isinstance(r, dict) else r[0]
        doc_type = r["doc_type"] if isinstance(r, dict) else r[1]
        cnt = r["cnt"] if isinstance(r, dict) else r[2]
        if efj_val not in result:
            result[efj_val] = {}
        result[efj_val][doc_type] = cnt
    return {"documents": result}'''
    new_docsummary = '''    with db.get_cursor() as cur:
        cur.execute("""
            SELECT efj, doc_type, COUNT(*) as cnt, MAX(id) as latest_id
            FROM load_documents
            GROUP BY efj, doc_type
            ORDER BY efj
        """)
        rows = cur.fetchall()
    result = {}
    doc_ids = {}
    for r in rows:
        efj_val = r["efj"] if isinstance(r, dict) else r[0]
        doc_type = r["doc_type"] if isinstance(r, dict) else r[1]
        cnt = r["cnt"] if isinstance(r, dict) else r[2]
        latest_id = r["latest_id"] if isinstance(r, dict) else r[3]
        if efj_val not in result:
            result[efj_val] = {}
            doc_ids[efj_val] = {}
        result[efj_val][doc_type] = cnt
        doc_ids[efj_val][doc_type] = latest_id
    return {"documents": result, "doc_ids": doc_ids}'''

    if old_docsummary in code:
        code = code.replace(old_docsummary, new_docsummary)
        print("✓ Enhanced document-summary with latest_id")
    elif "doc_ids" in code and "latest_id" in code:
        print("⊘ Document-summary already enhanced")
    else:
        print("⚠ Could not find document-summary anchor — skipping")

    # ── 3. Add "rate" and "unclassified" to valid doc types ──
    old_valid = '''    valid_types = [
        "customer_rate", "carrier_rate", "pod", "bol",
        "carrier_invoice", "screenshot", "email", "other",
    ]'''
    new_valid = '''    valid_types = [
        "customer_rate", "carrier_rate", "rate", "unclassified",
        "pod", "bol", "carrier_invoice", "screenshot", "email", "other",
    ]'''
    if old_valid in code:
        code = code.replace(old_valid, new_valid)
        print("✓ Added 'rate' + 'unclassified' to valid doc types")
    elif '"unclassified"' in code and '"rate"' in code:
        print("⊘ Valid doc types already updated")
    else:
        print("⚠ Could not find valid_types anchor — skipping")

    # ── 4. Add Rate IQ + alert endpoints ──
    RATE_IQ_BLOCK = '''

# ═══════════════════════════════════════════════════════════════
# RATE IQ + CUSTOMER REPLY ALERTS
# ═══════════════════════════════════════════════════════════════

@app.get("/api/unclassified-documents")
async def api_unclassified_documents():
    """Return documents with unclassified doc_type for manual review."""
    with db.get_cursor() as cur:
        cur.execute("""
            SELECT ld.id, ld.efj, ld.doc_type, ld.original_name,
                   ld.uploaded_at, ld.uploaded_by
            FROM load_documents ld
            WHERE ld.doc_type = 'unclassified'
            ORDER BY ld.uploaded_at DESC
            LIMIT 50
        """)
        rows = cur.fetchall()
    docs = []
    for r in rows:
        docs.append({
            "id": r["id"],
            "efj": r["efj"],
            "doc_type": r["doc_type"],
            "original_name": r["original_name"],
            "uploaded_at": r["uploaded_at"].isoformat() if r["uploaded_at"] else None,
            "uploaded_by": r["uploaded_by"],
        })
    return {"documents": docs, "count": len(docs)}


@app.get("/api/rate-iq")
async def api_rate_iq():
    """
    Rate IQ — return carrier rate history grouped by lane for scorecard comparison.
    Each lane shows all carrier quotes received, sorted by rate.
    """
    with db.get_cursor() as cur:
        # Get parsed rate quotes from rate_quotes table
        cur.execute("""
            SELECT rq.id, rq.email_thread_id, rq.efj, rq.lane, rq.origin,
                   rq.destination, rq.miles, rq.move_type, rq.carrier_name,
                   rq.carrier_email, rq.rate_amount, rq.rate_unit,
                   rq.quote_date, rq.indexed_at, rq.status
            FROM rate_quotes rq
            ORDER BY rq.quote_date DESC NULLS LAST
            LIMIT 500
        """)
        rate_quotes = cur.fetchall()
        # Get carrier rate emails with lane info
        cur.execute("""
            SELECT et.id, et.efj, et.sender, et.subject, et.body_preview,
                   et.lane, et.email_type, et.sent_at, et.indexed_at
            FROM email_threads et
            WHERE et.email_type = 'carrier_rate'
            ORDER BY et.sent_at DESC
            LIMIT 200
        """)
        carrier_emails = cur.fetchall()
        # Get carrier rate documents
        cur.execute("""
            SELECT ld.id, ld.efj, ld.doc_type, ld.original_name,
                   ld.uploaded_at, ld.uploaded_by
            FROM load_documents ld
            WHERE ld.doc_type = 'carrier_rate'
            ORDER BY ld.uploaded_at DESC
            LIMIT 200
        """)
        carrier_docs = cur.fetchall()
        # Get customer rate requests
        cur.execute("""
            SELECT et.id, et.efj, et.sender, et.subject, et.body_preview,
                   et.lane, et.email_type, et.sent_at
            FROM email_threads et
            WHERE et.email_type = 'customer_rate'
            ORDER BY et.sent_at DESC
            LIMIT 100
        """)
        customer_emails = cur.fetchall()

    # Group rate quotes by lane (parsed data with actual $$ amounts)
    lanes = {}
    for rq in rate_quotes:
        lane_key = rq["lane"] or "Unknown Lane"
        if lane_key not in lanes:
            lanes[lane_key] = {
                "lane": lane_key, "miles": None, "move_type": None,
                "carrier_quotes": [], "customer_requests": [],
                "cheapest": None, "avg_rate": None,
            }
        entry = lanes[lane_key]
        if rq["miles"] and not entry["miles"]:
            entry["miles"] = rq["miles"]
        if rq["move_type"] and not entry["move_type"]:
            entry["move_type"] = rq["move_type"]
        entry["carrier_quotes"].append({
            "id": rq["id"],
            "efj": rq["efj"],
            "carrier": rq["carrier_name"] or rq["carrier_email"] or "Unknown",
            "carrier_email": rq["carrier_email"],
            "rate": float(rq["rate_amount"]) if rq["rate_amount"] else None,
            "rate_unit": rq["rate_unit"],
            "date": rq["quote_date"].isoformat() if rq["quote_date"] else None,
            "status": rq["status"],
            "move_type": rq["move_type"],
        })

    # Also add carrier emails that might not have parsed rates
    for e in carrier_emails:
        lane_key = e["lane"] or "Unknown Lane"
        if lane_key not in lanes:
            lanes[lane_key] = {
                "lane": lane_key, "miles": None, "move_type": None,
                "carrier_quotes": [], "customer_requests": [],
                "cheapest": None, "avg_rate": None,
            }
        existing_ids = {q.get("efj") for q in lanes[lane_key]["carrier_quotes"]}
        if e["efj"] not in existing_ids:
            lanes[lane_key]["carrier_quotes"].append({
                "id": e["id"],
                "efj": e["efj"],
                "carrier": e["sender"],
                "carrier_email": e["sender"],
                "rate": None,
                "rate_unit": None,
                "date": e["sent_at"].isoformat() if e["sent_at"] else None,
                "status": "pending",
                "move_type": None,
                "source": "email",
            })

    # Add customer requests to their lanes
    for e in customer_emails:
        lane_key = e["lane"] or "Unknown Lane"
        if lane_key not in lanes:
            lanes[lane_key] = {
                "lane": lane_key, "miles": None, "move_type": None,
                "carrier_quotes": [], "customer_requests": [],
                "cheapest": None, "avg_rate": None,
            }
        lanes[lane_key]["customer_requests"].append({
            "id": e["id"],
            "efj": e["efj"],
            "sender": e["sender"],
            "subject": e["subject"],
            "sent_at": e["sent_at"].isoformat() if e["sent_at"] else None,
        })

    # Compute cheapest + avg per lane
    for lane_data in lanes.values():
        rates = [q["rate"] for q in lane_data["carrier_quotes"] if q.get("rate")]
        if rates:
            min_rate = min(rates)
            cheapest_q = next(q for q in lane_data["carrier_quotes"] if q.get("rate") == min_rate)
            lane_data["cheapest"] = {"carrier": cheapest_q["carrier"], "rate": min_rate}
            lane_data["avg_rate"] = round(sum(rates) / len(rates), 2)

    # Carrier scorecard — frequency, win rate, avg rate
    carrier_scores = {}
    for rq in rate_quotes:
        carrier_key = rq["carrier_email"] or rq["carrier_name"] or "Unknown"
        if carrier_key not in carrier_scores:
            carrier_scores[carrier_key] = {
                "carrier": rq["carrier_name"] or carrier_key,
                "quote_count": 0, "win_count": 0,
                "total_rate": 0, "rated_count": 0,
                "lanes_covered": set(),
            }
        cs = carrier_scores[carrier_key]
        cs["quote_count"] += 1
        if rq["status"] == "accepted":
            cs["win_count"] += 1
        if rq["rate_amount"]:
            cs["total_rate"] += float(rq["rate_amount"])
            cs["rated_count"] += 1
        if rq["lane"]:
            cs["lanes_covered"].add(rq["lane"])

    # Fallback: also count carrier emails not in rate_quotes
    for e in carrier_emails:
        sender = e["sender"] or "Unknown"
        sender_key = sender.split("<")[-1].replace(">", "").strip() if "<" in sender else sender
        if sender_key not in carrier_scores:
            carrier_scores[sender_key] = {
                "carrier": sender,
                "quote_count": 0, "win_count": 0,
                "total_rate": 0, "rated_count": 0,
                "lanes_covered": set(),
            }
            carrier_scores[sender_key]["quote_count"] += 1
            if e["lane"]:
                carrier_scores[sender_key]["lanes_covered"].add(e["lane"])

    scorecard = []
    for key, data in carrier_scores.items():
        scorecard.append({
            "carrier": data["carrier"],
            "quote_count": data["quote_count"],
            "win_count": data["win_count"],
            "avg_rate": round(data["total_rate"] / data["rated_count"], 2) if data["rated_count"] else None,
            "lanes_covered": len(data["lanes_covered"]),
            "lane_list": list(data["lanes_covered"]),
        })
    scorecard.sort(key=lambda x: x["quote_count"], reverse=True)

    return {
        "lanes": list(lanes.values()),
        "scorecard": scorecard,
        "carrier_docs": [
            {
                "id": d["id"], "efj": d["efj"], "doc_type": d["doc_type"],
                "original_name": d["original_name"],
                "uploaded_at": d["uploaded_at"].isoformat() if d["uploaded_at"] else None,
            }
            for d in carrier_docs
        ],
        "total_carrier_quotes": len(carrier_emails),
        "total_customer_requests": len(customer_emails),
        "total_rate_quotes": len(rate_quotes),
    }


@app.get("/api/rate-iq/lane/{lane}")
async def api_rate_iq_lane(lane: str):
    """Get all quotes for a specific lane."""
    from urllib.parse import unquote
    lane = unquote(lane)
    with db.get_cursor() as cur:
        cur.execute("""
            SELECT et.id, et.efj, et.sender, et.subject, et.body_preview,
                   et.lane, et.email_type, et.sent_at
            FROM email_threads et
            WHERE et.lane = %s
            ORDER BY et.sent_at DESC
        """, (lane,))
        emails = cur.fetchall()
    results = []
    for e in emails:
        results.append({
            "id": e["id"],
            "efj": e["efj"],
            "sender": e["sender"],
            "subject": e["subject"],
            "body_preview": e["body_preview"],
            "lane": e["lane"],
            "email_type": e["email_type"],
            "sent_at": e["sent_at"].isoformat() if e["sent_at"] else None,
        })
    return {"lane": lane, "emails": results}


@app.patch("/api/rate-iq/{quote_id}")
async def update_rate_quote(quote_id: int, request: Request):
    """Accept or reject a rate quote."""
    body = await request.json()
    new_status = body.get("status", "").strip()
    if new_status not in ("accepted", "rejected", "pending"):
        return JSONResponse(status_code=400, content={"error": "status must be accepted, rejected, or pending"})
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "UPDATE rate_quotes SET status = %s WHERE id = %s RETURNING id, lane, carrier_name, rate_amount",
                (new_status, quote_id),
            )
            row = cur.fetchone()
    if not row:
        return JSONResponse(status_code=404, content={"error": "quote not found"})
    return {"ok": True, "id": row["id"], "status": new_status,
            "carrier": row["carrier_name"], "rate": float(row["rate_amount"]) if row["rate_amount"] else None}


@app.get("/api/customer-reply-alerts")
async def api_customer_reply_alerts():
    """Get active customer reply alerts (unreplied for 15+ min)."""
    with db.get_cursor() as cur:
        cur.execute("""
            SELECT cra.id, cra.email_thread_id, cra.efj, cra.sender,
                   cra.subject, cra.alerted_at, cra.dismissed
            FROM customer_reply_alerts cra
            WHERE cra.dismissed = FALSE
            ORDER BY cra.alerted_at DESC
            LIMIT 50
        """)
        alerts = cur.fetchall()
    return [
        {
            "id": a["id"], "email_thread_id": a["email_thread_id"],
            "efj": a["efj"], "sender": a["sender"], "subject": a["subject"],
            "alerted_at": a["alerted_at"].isoformat() if a["alerted_at"] else None,
        }
        for a in alerts
    ]


@app.post("/api/customer-reply-alerts/{alert_id}/dismiss")
async def dismiss_customer_reply_alert(alert_id: int):
    """Dismiss a customer reply alert."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "UPDATE customer_reply_alerts SET dismissed = TRUE WHERE id = %s RETURNING id",
                (alert_id,),
            )
            row = cur.fetchone()
    if not row:
        return JSONResponse(status_code=404, content={"error": "alert not found"})
    return {"ok": True}
'''

    if "api_rate_iq" in code:
        print("⊘ Rate IQ endpoints already present")
    else:
        # Insert before the document hub section or at end
        markers = [
            "# ═══════════════════════════════════════════════════════════════\n# DOCUMENT HUB",
            "# ═══════════════════════════════════════════════════════════════\n# BOL",
            "# ═══════════════════════════════════════════════════════════════\n# CARRIER",
        ]
        inserted = False
        for marker in markers:
            if marker in code:
                code = code.replace(marker, RATE_IQ_BLOCK + "\n" + marker)
                inserted = True
                break
        if not inserted:
            # Append before the final lines
            code += RATE_IQ_BLOCK
        print("✓ Added Rate IQ + customer-reply-alerts endpoints")

    open(APP_PATH, "w").write(code)
    print(f"\nDone. Restart: systemctl restart csl-dashboard")

if __name__ == "__main__":
    patch()
