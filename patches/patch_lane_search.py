"""
Patch: Add GET /api/rate-iq/search-lane endpoint.
Searches rate_quotes + carriers table for matching origin/destination combos.
Returns carrier rates ranked by price for QuoteBuilder rate intelligence.
"""

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP, "r") as f:
    code = f.read()

target = '''@app.get("/api/customer-reply-alerts")
async def api_customer_reply_alerts():
    """Get active customer reply alerts (unreplied for 15+ min)."""'''

new_endpoint = '''@app.get("/api/rate-iq/search-lane")
async def api_search_lane(origin: str = Query(""), destination: str = Query("")):
    """
    Search for carrier rates matching an origin/destination lane.
    Used by QuoteBuilder to show rate intelligence when building a quote.
    Returns matching carrier quotes ranked by rate, plus carrier directory info.
    """
    if not origin and not destination:
        return {"matches": [], "carriers": [], "stats": {}}

    origin_q = origin.strip().lower()
    dest_q = destination.strip().lower()

    with db.get_cursor() as cur:
        # Search rate_quotes for matching lanes (fuzzy match on origin/destination)
        conditions = []
        params = []
        if origin_q:
            conditions.append("(LOWER(rq.origin) LIKE %s OR LOWER(rq.lane) LIKE %s)")
            params.extend([f"%{origin_q}%", f"%{origin_q}%"])
        if dest_q:
            conditions.append("(LOWER(rq.destination) LIKE %s OR LOWER(rq.lane) LIKE %s)")
            params.extend([f"%{dest_q}%", f"%{dest_q}%"])

        where = " AND ".join(conditions) if conditions else "TRUE"
        cur.execute(f"""
            SELECT rq.id, rq.lane, rq.origin, rq.destination, rq.miles,
                   rq.carrier_name, rq.carrier_email, rq.rate_amount,
                   rq.rate_unit, rq.quote_date, rq.status, rq.move_type
            FROM rate_quotes rq
            WHERE {where}
            ORDER BY rq.rate_amount ASC NULLS LAST, rq.quote_date DESC NULLS LAST
            LIMIT 50
        """, params)
        rate_matches = cur.fetchall()

        # Search carriers directory for matching pickup/destination areas
        carrier_conditions = []
        carrier_params = []
        if origin_q:
            carrier_conditions.append("LOWER(c.pickup_area) LIKE %s")
            carrier_params.append(f"%{origin_q}%")
        if dest_q:
            carrier_conditions.append("LOWER(c.destination_area) LIKE %s")
            carrier_params.append(f"%{dest_q}%")

        carrier_where = " OR ".join(carrier_conditions) if carrier_conditions else "FALSE"
        try:
            cur.execute(f"""
                SELECT c.id, c.name, c.mc_number, c.email, c.phone,
                       c.pickup_area, c.destination_area, c.regions, c.equipment,
                       c.can_dray, c.hazmat, c.overweight, c.date_quoted
                FROM carriers c
                WHERE {carrier_where}
                ORDER BY c.date_quoted DESC NULLS LAST
                LIMIT 20
            """, carrier_params)
            matching_carriers = cur.fetchall()
        except Exception:
            matching_carriers = []

    # Build response
    matches = []
    for rq in rate_matches:
        matches.append({
            "id": rq["id"],
            "lane": rq["lane"],
            "origin": rq["origin"],
            "destination": rq["destination"],
            "miles": rq["miles"],
            "carrier": rq["carrier_name"] or "Unknown",
            "carrier_email": rq["carrier_email"],
            "rate": float(rq["rate_amount"]) if rq["rate_amount"] else None,
            "rate_unit": rq["rate_unit"],
            "date": rq["quote_date"].isoformat() if rq["quote_date"] else None,
            "status": rq["status"],
            "move_type": rq["move_type"],
        })

    carriers = []
    for c in matching_carriers:
        carriers.append({
            "id": c["id"],
            "name": c["name"],
            "mc": c["mc_number"],
            "email": c["email"],
            "phone": c["phone"],
            "pickup": c["pickup_area"],
            "destination": c["destination_area"],
            "can_dray": c["can_dray"],
            "hazmat": c["hazmat"],
            "overweight": c["overweight"],
            "date_quoted": c["date_quoted"].isoformat() if c["date_quoted"] else None,
        })

    # Stats
    rates = [m["rate"] for m in matches if m["rate"]]
    stats = {}
    if rates:
        stats = {
            "floor": min(rates),
            "ceiling": max(rates),
            "avg": round(sum(rates) / len(rates), 2),
            "count": len(rates),
            "total_carriers": len(set(m["carrier"] for m in matches)),
        }

    return {"matches": matches, "carriers": carriers, "stats": stats}


''' + target

if target not in code:
    print("ERROR: target not found")
    exit(1)

code = code.replace(target, new_endpoint, 1)

with open(APP, "w") as f:
    f.write(code)

print("OK — /api/rate-iq/search-lane endpoint added")
