#!/usr/bin/env python3
"""
Patch: Carrier Performance Scorecard
- Adds GET /api/carriers/scorecard endpoint
- Aggregates delivery performance from completed loads (Google Sheet tabs)
- Returns per-carrier: total_loads, on_time_pct, avg_transit_days, top_lanes, last_used
"""

APP = "/root/csl-bot/csl-doc-tracker/app.py"

print("[1/1] Adding carrier scorecard endpoint to app.py...")

with open(APP, "r") as f:
    code = f.read()

if "/api/carriers/scorecard" in code:
    print("   Already patched — skipping.")
    exit(0)

# Insert after the completed loads endpoint block
ANCHOR = '''@app.get("/api/completed")'''

SCORECARD_ENDPOINT = '''

# -- Carrier Performance Scorecard ─────────────────────────────────────

@app.get("/api/carriers/scorecard")
async def api_carrier_scorecard():
    """Aggregate carrier delivery performance from completed loads."""
    from datetime import datetime as _dt
    from collections import defaultdict

    _refresh_completed_cache()
    loads = _completed_cache.get("data", [])

    carriers = defaultdict(lambda: {
        "loads": 0, "on_time": 0, "total_transit": 0, "transit_count": 0,
        "lanes": defaultdict(int), "last_delivery": None, "move_types": defaultdict(int),
    })

    def _parse_date(s):
        if not s:
            return None
        for fmt in ("%m/%d/%Y", "%Y-%m-%d", "%m/%d/%y", "%m-%d-%Y", "%m-%d-%y"):
            try:
                return _dt.strptime(s.strip(), fmt)
            except ValueError:
                continue
        return None

    for load in loads:
        carrier = (load.get("carrier") or "").strip()
        if not carrier or carrier.lower() in ("", "tbd", "tba", "n/a", "none"):
            continue

        carriers[carrier]["loads"] += 1
        move = load.get("move_type", "").strip()
        if move:
            carriers[carrier]["move_types"][move] += 1

        origin = load.get("origin", "").strip()
        dest = load.get("destination", "").strip()
        if origin and dest:
            lane = f"{origin} → {dest}"
            carriers[carrier]["lanes"][lane] += 1

        pickup_dt = _parse_date(load.get("pickup"))
        delivery_dt = _parse_date(load.get("delivery"))
        lfd_dt = _parse_date(load.get("lfd"))

        # Transit time
        if pickup_dt and delivery_dt and delivery_dt > pickup_dt:
            delta = (delivery_dt - pickup_dt).days
            if 0 < delta < 60:
                carriers[carrier]["total_transit"] += delta
                carriers[carrier]["transit_count"] += 1

        # On-time: delivery <= LFD (for dray) or delivery exists (for FTL)
        if delivery_dt:
            if lfd_dt:
                if delivery_dt <= lfd_dt:
                    carriers[carrier]["on_time"] += 1
            else:
                carriers[carrier]["on_time"] += 1

        # Track most recent delivery
        if delivery_dt:
            if not carriers[carrier]["last_delivery"] or delivery_dt > carriers[carrier]["last_delivery"]:
                carriers[carrier]["last_delivery"] = delivery_dt

    # Build response
    results = []
    for name, data in carriers.items():
        total = data["loads"]
        on_time_pct = round(data["on_time"] / total * 100) if total > 0 else 0
        avg_transit = round(data["total_transit"] / data["transit_count"], 1) if data["transit_count"] > 0 else None
        top_lanes = sorted(data["lanes"].items(), key=lambda x: -x[1])[:5]
        primary_move = max(data["move_types"].items(), key=lambda x: x[1])[0] if data["move_types"] else None

        results.append({
            "carrier": name,
            "total_loads": total,
            "on_time_pct": on_time_pct,
            "avg_transit_days": avg_transit,
            "lanes_served": len(data["lanes"]),
            "top_lanes": [{"lane": l, "count": c} for l, c in top_lanes],
            "primary_move_type": primary_move,
            "last_delivery": data["last_delivery"].strftime("%Y-%m-%d") if data["last_delivery"] else None,
        })

    results.sort(key=lambda x: -x["total_loads"])
    return JSONResponse({"carriers": results, "total": len(results)})


''' + ANCHOR

if ANCHOR in code:
    code = code.replace(ANCHOR, SCORECARD_ENDPOINT)
    print("   Added /api/carriers/scorecard endpoint.")
else:
    print("   ERROR: Could not find anchor — GET /api/completed")
    exit(1)

with open(APP, "w") as f:
    f.write(code)

print("   Done! Carrier scorecard patch applied.")
print("   Restart: systemctl restart csl-dashboard")
