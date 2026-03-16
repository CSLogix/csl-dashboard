from collections import defaultdict
from urllib.parse import unquote

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

import database as db
from shared import log

router = APIRouter()


@router.get("/api/rate-iq")
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
        # Only add if not already represented by a rate_quote
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


@router.get("/api/rate-iq/lane/{lane}")
async def api_rate_iq_lane(lane: str):
    """Get all quotes for a specific lane."""
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


@router.patch("/api/rate-iq/{quote_id}")
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
    # When accepting, reject competing pending quotes for same EFJ
    if new_status == "accepted" and row.get("efj"):
        with db.get_conn() as conn2:
            with db.get_cursor(conn2) as cur2:
                cur2.execute(
                    "UPDATE rate_quotes SET status = 'rejected' WHERE efj = %s AND id != %s AND status = 'pending'",
                    (row["efj"], quote_id),
                )
                if cur2.rowcount:
                    log.info("Rate IQ: rejected %d competing quotes for %s", cur2.rowcount, row["efj"])
    return {"ok": True, "id": row["id"], "status": new_status,
            "carrier": row["carrier_name"], "rate": float(row["rate_amount"]) if row["rate_amount"] else None}


@router.get("/api/rate-iq/outbound-quotes")
async def api_outbound_quotes(
    customer: str = Query(""),
    origin:   str = Query(""),
    dest:     str = Query(""),
    limit:    int = Query(50),
):
    """
    Quote archive — Evans outbound customer rate quotes indexed from sent mail.
    Searchable by customer name, origin, destination.
    """
    conditions = ["rq.quote_direction = 'outbound'", "rq.total_estimate IS NOT NULL"]
    params: list = []
    if customer.strip():
        conditions.append("(LOWER(rq.customer_name) LIKE %s OR LOWER(rq.carrier_email) LIKE %s)")
        params += [f"%{customer.strip().lower()}%", f"%{customer.strip().lower()}%"]
    if origin.strip():
        conditions.append("(LOWER(rq.origin) LIKE %s OR LOWER(rq.lane) LIKE %s)")
        params += [f"%{origin.strip().lower()}%", f"%{origin.strip().lower()}%"]
    if dest.strip():
        conditions.append("(LOWER(rq.destination) LIKE %s OR LOWER(rq.lane) LIKE %s)")
        params += [f"%{dest.strip().lower()}%", f"%{dest.strip().lower()}%"]
    where = " AND ".join(conditions)
    params.append(limit)
    with db.get_cursor() as cur:
        cur.execute(f"""
            SELECT rq.id, rq.efj, rq.lane, rq.origin, rq.destination,
                   rq.customer_name, rq.carrier_email AS customer_email,
                   rq.move_type, rq.linehaul, rq.chassis_per_day,
                   rq.accessorials, rq.total_estimate,
                   rq.quote_date, rq.indexed_at
            FROM rate_quotes rq
            WHERE {where}
            ORDER BY rq.quote_date DESC NULLS LAST
            LIMIT %s
        """, params)
        rows = cur.fetchall()
    return {
        "quotes": [
            {
                "id":            r["id"],
                "efj":           r["efj"],
                "lane":          r["lane"],
                "origin":        r["origin"],
                "destination":   r["destination"],
                "customer":      r["customer_name"],
                "customer_email":r["customer_email"],
                "move_type":     r["move_type"],
                "linehaul":      float(r["linehaul"]) if r["linehaul"] else None,
                "chassis_per_day": float(r["chassis_per_day"]) if r["chassis_per_day"] else None,
                "accessorials":  r["accessorials"],
                "total":         float(r["total_estimate"]) if r["total_estimate"] else None,
                "quote_date":    r["quote_date"].isoformat() if r["quote_date"] else None,
                "indexed_at":    r["indexed_at"].isoformat() if r["indexed_at"] else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.get("/api/rate-iq/search-lane")
async def api_search_lane(origin: str = Query(""), destination: str = Query("")):
    """
    Unified lane rate search: rate_quotes + lane_rates + won quotes.
    Groups results by normalized lane. Returns lane_groups[] with
    floor/avg/ceiling per lane, plus flat matches[] for backwards compat.
    """
    if not origin and not destination:
        return {"matches": [], "lane_groups": [], "carriers": [], "stats": {}}

    origin_q = origin.strip().lower()
    dest_q = destination.strip().lower()

    # Build WHERE conditions for each source
    def _build_conditions(o_col, d_col, lane_col=None):
        conds, params = [], []
        if origin_q:
            if lane_col:
                conds.append(f"(LOWER({o_col}) LIKE %s OR LOWER({lane_col}) LIKE %s)")
                params.extend([f"%{origin_q}%", f"%{origin_q}%"])
            else:
                conds.append(f"LOWER({o_col}) LIKE %s")
                params.append(f"%{origin_q}%")
        if dest_q:
            if lane_col:
                conds.append(f"(LOWER({d_col}) LIKE %s OR LOWER({lane_col}) LIKE %s)")
                params.extend([f"%{dest_q}%", f"%{dest_q}%"])
            else:
                conds.append(f"LOWER({d_col}) LIKE %s")
                params.append(f"%{dest_q}%")
        return (" AND ".join(conds) if conds else "TRUE"), params

    rq_where, rq_params = _build_conditions("rq.origin", "rq.destination", "rq.lane")
    lr_where, lr_params = _build_conditions("lr.port", "lr.destination")
    # won quotes use pod/final_delivery
    wq_where, wq_params = _build_conditions("q.pod", "q.final_delivery")

    with db.get_cursor() as cur:
        # ── Unified UNION: rate_quotes + lane_rates + won quotes ──
        cur.execute(f"""
            SELECT origin, destination,
                   COALESCE(NULLIF(TRIM(origin),'') || ' \u2192 ' || NULLIF(TRIM(destination),''), lane, '') AS norm_lane,
                   carrier_name, carrier_email, rate_amount, rate_unit,
                   quote_date, source, move_type, id, miles, status
            FROM (
                -- Email-extracted carrier rates
                SELECT rq.origin, rq.destination, rq.lane,
                       rq.carrier_name, rq.carrier_email, rq.rate_amount, rq.rate_unit,
                       rq.quote_date, 'email' AS source, rq.move_type, rq.id, rq.miles, rq.status
                FROM rate_quotes rq
                WHERE {rq_where} AND rq.rate_amount IS NOT NULL

                UNION ALL

                -- Excel-imported lane rates
                SELECT lr.port AS origin, lr.destination,
                       lr.port || ' \u2192 ' || lr.destination AS lane,
                       lr.carrier_name, NULL AS carrier_email,
                       lr.dray_rate AS rate_amount, 'flat' AS rate_unit,
                       lr.created_at AS quote_date, 'import' AS source,
                       lr.move_type, lr.id, NULL AS miles, 'import' AS status
                FROM lane_rates lr
                WHERE {lr_where} AND lr.dray_rate IS NOT NULL

                UNION ALL

                -- Won/accepted customer quotes (carrier cost only)
                SELECT q.pod AS origin, q.final_delivery AS destination,
                       q.pod || ' \u2192 ' || q.final_delivery AS lane,
                       q.carrier_name, NULL AS carrier_email,
                       q.carrier_total AS rate_amount, 'flat' AS rate_unit,
                       q.created_at AS quote_date, 'quote' AS source,
                       q.shipment_type AS move_type, q.id, NULL AS miles, 'accepted' AS status
                FROM quotes q
                WHERE {wq_where} AND q.status = 'accepted' AND q.carrier_total > 0
            ) combined
            ORDER BY rate_amount ASC NULLS LAST, quote_date DESC NULLS LAST
            LIMIT 100
        """, rq_params + lr_params + wq_params + rq_params)
        all_rows = cur.fetchall()

        # ── Directory carriers ──
        c_conds, c_params = [], []
        if origin_q:
            c_conds.append("LOWER(c.pickup_area) LIKE %s")
            c_params.append(f"%{origin_q}%")
        if dest_q:
            c_conds.append("LOWER(c.destination_area) LIKE %s")
            c_params.append(f"%{dest_q}%")
        c_where = " OR ".join(c_conds) if c_conds else "FALSE"
        try:
            cur.execute(f"""
                SELECT c.id, c.name, c.mc_number, c.email, c.phone,
                       c.pickup_area, c.destination_area,
                       c.can_dray, c.hazmat, c.overweight, c.date_quoted
                FROM carriers c WHERE {c_where}
                ORDER BY c.date_quoted DESC NULLS LAST LIMIT 20
            """, c_params)
            matching_carriers = cur.fetchall()
        except Exception:
            matching_carriers = []

    # ── Build flat matches (backwards compat) ──
    matches = []
    for r in all_rows:
        matches.append({
            "id": r["id"],
            "lane": r["norm_lane"],
            "origin": r["origin"],
            "destination": r["destination"],
            "miles": r["miles"],
            "carrier": r["carrier_name"] or "Unknown",
            "carrier_email": r["carrier_email"],
            "rate": float(r["rate_amount"]) if r["rate_amount"] else None,
            "rate_unit": r["rate_unit"],
            "date": r["quote_date"].isoformat() if r["quote_date"] else None,
            "status": r["status"],
            "source": r["source"],
            "move_type": r["move_type"],
        })

    # ── Group by normalized lane ──
    lane_map = defaultdict(list)
    for m in matches:
        key = (
            (m["origin"] or "").strip().lower(),
            (m["destination"] or "").strip().lower(),
        )
        lane_map[key].append(m)

    lane_groups = []
    for (orig_key, dest_key), group in sorted(
        lane_map.items(),
        key=lambda kv: min((q["rate"] or 9e9) for q in kv[1])
    ):
        rates = [q["rate"] for q in group if q["rate"]]
        source_counts = {}
        for q in group:
            source_counts[q["source"]] = source_counts.get(q["source"], 0) + 1
        last_date = max((q["date"] or "") for q in group) or None
        lane_groups.append({
            "lane": group[0]["lane"],
            "origin": group[0]["origin"],
            "destination": group[0]["destination"],
            "count": len(group),
            "rated_count": len(rates),
            "floor": min(rates) if rates else None,
            "avg": round(sum(rates) / len(rates), 2) if rates else None,
            "ceiling": max(rates) if rates else None,
            "carriers": len(set(q["carrier"] for q in group)),
            "last_quoted": last_date,
            "sources": source_counts,  # {"email": 3, "import": 2}
            "quotes": sorted(group, key=lambda q: q["rate"] or 9e9),
        })

    # Sort lane_groups: most quotes first
    lane_groups.sort(key=lambda g: g["rated_count"], reverse=True)

    # ── Global stats ──
    all_rates = [m["rate"] for m in matches if m["rate"]]
    stats = {}
    if all_rates:
        stats = {
            "floor": min(all_rates),
            "ceiling": max(all_rates),
            "avg": round(sum(all_rates) / len(all_rates), 2),
            "count": len(all_rates),
            "total_carriers": len(set(m["carrier"] for m in matches)),
            "total_lanes": len(lane_groups),
            "sources": {
                "email": sum(1 for m in matches if m["source"] == "email"),
                "import": sum(1 for m in matches if m["source"] == "import"),
                "quote": sum(1 for m in matches if m["source"] == "quote"),
            },
        }

    carriers = [
        {
            "id": c["id"], "name": c["name"], "mc": c["mc_number"],
            "email": c["email"], "phone": c["phone"],
            "pickup": c["pickup_area"], "destination": c["destination_area"],
            "can_dray": c["can_dray"], "hazmat": c["hazmat"],
            "overweight": c["overweight"],
            "date_quoted": c["date_quoted"].isoformat() if c["date_quoted"] else None,
        }
        for c in matching_carriers
    ]

    return {"matches": matches, "lane_groups": lane_groups, "carriers": carriers, "stats": stats}


@router.get("/api/lane-stats")
async def api_lane_stats():
    """Top freight corridors by load volume. Future-proof for avg carrier_pay once rate fields exist."""
    with db.get_cursor() as cur:
        cur.execute("""
            SELECT
                TRIM(SPLIT_PART(origin, ',', 1))                           AS origin_city,
                TRIM(SPLIT_PART(TRIM(SPLIT_PART(origin, ',', 2)), ' ', 1)) AS origin_state,
                TRIM(SPLIT_PART(destination, ',', 1))                      AS dest_city,
                TRIM(SPLIT_PART(TRIM(SPLIT_PART(destination, ',', 2)), ' ', 1)) AS dest_state,
                COUNT(*)                                                     AS load_count,
                AVG(customer_rate)                     AS avg_customer_rate
            FROM shipments
            WHERE archived = false
              AND origin    IS NOT NULL AND origin    != ''
              AND destination IS NOT NULL AND destination != ''
              AND origin    LIKE '%,%'
              AND destination LIKE '%,%'
            GROUP BY 1, 2, 3, 4
            ORDER BY load_count DESC
            LIMIT 20
        """)
        rows = cur.fetchall()
    lanes = []
    for r in rows:
        lanes.append({
            "origin_city":  r["origin_city"],
            "origin_state": r["origin_state"],
            "dest_city":    r["dest_city"],
            "dest_state":   r["dest_state"],
            "load_count":   r["load_count"],
            "avg_customer_rate": float(r["avg_customer_rate"]) if r["avg_customer_rate"] else None,
        })
    return {"lanes": lanes}


# ── Market Rates (LoadMatch / benchmark data — no carrier) ──────────

@router.post("/api/rate-iq/market-rates")
async def post_market_rates(request: Request):
    """Parse pasted tab-separated LoadMatch data and store as market benchmark rates."""
    import re
    from datetime import datetime as _dt
    from decimal import Decimal, InvalidOperation

    body = await request.json()
    origin = (body.get("origin") or "").strip()
    destination = (body.get("destination") or "").strip()
    move_type = (body.get("move_type") or "dray").strip().lower()
    text = (body.get("text") or "").strip()

    if not origin or not destination:
        return JSONResponse(status_code=400, content={"error": "origin and destination are required"})
    if not text:
        return JSONResponse(status_code=400, content={"error": "text is required"})

    DATE_FORMATS = ["%Y-%b-%d", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b %d, %Y"]
    HEADER_WORDS = {"date", "terminal", "base", "fsc", "total", "linehaul", "rate"}

    def parse_money(s):
        """Strip $, commas, whitespace and return Decimal or None."""
        s = s.strip().replace("$", "").replace(",", "")
        if not s or s == "—" or s == "-":
            return None
        return Decimal(s)

    def parse_pct(s):
        """Parse a percentage string like '29%' to Decimal."""
        s = s.strip().replace("%", "")
        if not s or s == "—" or s == "-":
            return Decimal("0")
        return Decimal(s)

    def parse_date(s):
        """Try multiple date formats and return a date or None."""
        s = s.strip()
        for f in DATE_FORMATS:
            try:
                return _dt.strptime(s, f).date()
            except ValueError:
                continue
        return None

    rows_inserted = 0
    rows_skipped = 0
    errors = []
    insert_params = []

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for i, line in enumerate(lines):
        # Split by tab or 2+ spaces
        parts = [p.strip() for p in line.split("\t") if p.strip()]
        if len(parts) < 3:
            # Try splitting by 2+ whitespace
            parts = [p.strip() for p in re.split(r"\s{2,}", line) if p.strip()]

        # Skip header rows
        if parts and any(w in parts[0].lower() for w in HEADER_WORDS):
            continue

        # Expect: date, terminal, base, fsc%, total  (5 cols)
        # Or: date, terminal, base, total  (4 cols, no fsc)
        # Or: terminal, base, fsc%, total  (4 cols, no date)
        try:
            rate_date = None
            terminal = None
            base_rate = None
            fsc = Decimal("0")
            total = None

            if len(parts) >= 5:
                rate_date = parse_date(parts[0])
                terminal = parts[1]
                base_rate = parse_money(parts[2])
                fsc = parse_pct(parts[3])
                total = parse_money(parts[4])
            elif len(parts) == 4:
                # Try date first
                d = parse_date(parts[0])
                if d:
                    rate_date = d
                    terminal = parts[1]
                    base_rate = parse_money(parts[2])
                    total = parse_money(parts[3])
                else:
                    terminal = parts[0]
                    base_rate = parse_money(parts[1])
                    fsc = parse_pct(parts[2])
                    total = parse_money(parts[3])
            elif len(parts) == 3:
                terminal = parts[0]
                base_rate = parse_money(parts[1])
                total = parse_money(parts[2])
            else:
                rows_skipped += 1
                continue

            if total is None and base_rate is None:
                rows_skipped += 1
                errors.append(f"Line {i + 1}: no rate found")
                continue

            if total is None and base_rate is not None:
                total = base_rate * (1 + fsc / 100) if fsc else base_rate

            insert_params.append((rate_date, terminal, origin, destination, base_rate, fsc, total, move_type))
            rows_inserted += 1

        except (InvalidOperation, ValueError) as e:
            rows_skipped += 1
            errors.append(f"Line {i + 1}: {e}")

    if rows_inserted == 0:
        return JSONResponse(status_code=400, content={"error": "No valid rows parsed", "skipped": rows_skipped, "errors": errors[:10]})

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            for p in insert_params:
                cur.execute("""
                    INSERT INTO market_rates (rate_date, terminal, origin, destination, base_rate, fsc_pct, total, source, move_type)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'loadmatch', %s)
                """, p)

    return {"ok": True, "inserted": rows_inserted, "skipped": rows_skipped, "errors": errors[:10]}


@router.get("/api/rate-iq/market-rates")
async def get_market_rates(
    origin: str = Query(default=""),
    destination: str = Query(default=""),
    move_type: str = Query(default=""),
):
    """Retrieve market benchmark rates for a lane with aggregate stats."""
    origin = origin.strip()
    destination = destination.strip()

    if not origin and not destination:
        return JSONResponse(status_code=400, content={"error": "origin or destination required"})

    conditions = []
    params = []
    if origin:
        conditions.append("LOWER(origin) LIKE %s")
        params.append(f"%{origin.lower()}%")
    if destination:
        conditions.append("LOWER(destination) LIKE %s")
        params.append(f"%{destination.lower()}%")
    if move_type:
        conditions.append("LOWER(move_type) = %s")
        params.append(move_type.lower())

    where = " AND ".join(conditions)

    with db.get_cursor() as cur:
        cur.execute(f"""
            SELECT id, rate_date, terminal, origin, destination,
                   base_rate, fsc_pct, total, source, move_type, created_at
            FROM market_rates
            WHERE {where}
            ORDER BY rate_date DESC NULLS LAST
            LIMIT 100
        """, params)
        rows = cur.fetchall()

    rates = []
    totals = []
    for r in rows:
        t = float(r["total"]) if r["total"] else None
        if t:
            totals.append(t)
        rates.append({
            "id": r["id"],
            "date": r["rate_date"].isoformat() if r["rate_date"] else None,
            "terminal": r["terminal"],
            "origin": r["origin"],
            "destination": r["destination"],
            "base": float(r["base_rate"]) if r["base_rate"] else None,
            "fsc_pct": float(r["fsc_pct"]) if r["fsc_pct"] else None,
            "total": t,
            "source": r["source"],
            "move_type": r["move_type"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        })

    stats = None
    if totals:
        mid = len(totals) // 2
        recent = totals[:mid] if mid > 0 else totals
        older = totals[mid:] if mid > 0 else []
        recent_avg = sum(recent) / len(recent) if recent else None
        older_avg = sum(older) / len(older) if older else None
        trend_pct = round(((recent_avg - older_avg) / older_avg) * 100, 1) if recent_avg and older_avg and older_avg > 0 else None

        stats = {
            "avg": round(sum(totals) / len(totals), 2),
            "min": min(totals),
            "max": max(totals),
            "count": len(totals),
            "latest_date": rates[0]["date"] if rates else None,
            "oldest_date": rates[-1]["date"] if rates else None,
            "trend_pct": trend_pct,
        }

    return {"rates": rates, "stats": stats}
