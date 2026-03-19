"""
FTL Quote Calculator — backend route.

Replicates the Excel-based quoting workflow:
  1. User enters SONAR + DAT market inputs for a lane.
  2. Server calculates deltas, averages, and final customer quote.
  3. Returns lane comp history from completed FTL shipments + lane_rates.
"""

import logging
from datetime import datetime, timedelta
from typing import Optional

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import database as db
from shared import log

router = APIRouter()

# ── Pydantic models ────────────────────────────────────────────

class FTLQuoteRequest(BaseModel):
    origin: str = ""
    destination: str = ""
    mileage: float = 0

    # SONAR (TRAC) inputs
    trac_spot_current: float = 0     # TRAC Spot current flat rate
    trac_spot_low: float = 0         # TRAC Spot low
    trac_spot_high: float = 0        # TRAC Spot high
    trac_contract: float = 0         # TRAC Contract flat rate

    # DAT inputs
    dat_spot_low: float = 0          # DAT RateView spot low
    dat_spot_high: float = 0         # DAT RateView spot high
    dat_7day: float = 0              # DAT 7-day avg
    dat_15day: float = 0             # DAT 15-day avg
    dat_90day: float = 0             # DAT 90-day avg

    # Deadhead comps (from DAT loadboard — nearby lane rates)
    dh_origin_rate: float = 0        # Best comp: deadhead-to-origin filtered rate
    dh_dest_rate: float = 0          # Best comp: deadhead-to-destination filtered rate

    # Margin
    margin_usd: float = 300.00
    margin_source: str = "fixed"     # "fixed" or "pct"
    margin_pct: float = 15.0         # Used when margin_source == "pct"


# ── Calculation endpoint ───────────────────────────────────────

@router.post("/api/ftl-quote/calculate")
async def ftl_quote_calculate(data: FTLQuoteRequest):
    """Calculate FTL quote from SONAR + DAT market inputs."""
    mileage = data.mileage if data.mileage > 0 else 1  # avoid div/0

    # ── Deltas ──
    sonar_spot_delta = data.trac_spot_high - data.trac_spot_current
    dat_spot_delta = data.dat_spot_high - data.dat_spot_low
    sonar_vs_dat_high = data.dat_spot_high - data.trac_spot_high

    # ── Averages ──
    # Collect all non-zero rate inputs for averaging
    rate_inputs = []
    labels = []
    if data.trac_spot_current > 0:
        rate_inputs.append(data.trac_spot_current); labels.append("SONAR Spot")
    if data.trac_spot_high > 0:
        rate_inputs.append(data.trac_spot_high); labels.append("SONAR High")
    if data.trac_contract > 0:
        rate_inputs.append(data.trac_contract); labels.append("SONAR Contract")
    if data.dat_7day > 0:
        rate_inputs.append(data.dat_7day); labels.append("DAT 7d")
    if data.dat_15day > 0:
        rate_inputs.append(data.dat_15day); labels.append("DAT 15d")
    if data.dat_90day > 0:
        rate_inputs.append(data.dat_90day); labels.append("DAT 90d")
    if data.dh_origin_rate > 0:
        rate_inputs.append(data.dh_origin_rate); labels.append("DH-O Comp")
    if data.dh_dest_rate > 0:
        rate_inputs.append(data.dh_dest_rate); labels.append("DH-D Comp")

    avg_all = round(sum(rate_inputs) / len(rate_inputs), 2) if rate_inputs else 0

    # ── Margin ──
    if data.margin_source == "pct" and data.margin_pct > 0:
        margin_usd = round(avg_all * (data.margin_pct / 100), 2)
    else:
        margin_usd = data.margin_usd

    # ── Final pricing ──
    quote_customer = round(avg_all + margin_usd, 2)
    quoted_rpm = round(quote_customer / mileage, 2) if mileage > 0 else 0
    carrier_target = avg_all
    carrier_rpm = round(carrier_target / mileage, 2) if mileage > 0 else 0
    margin_pct_actual = round((margin_usd / quote_customer) * 100, 2) if quote_customer > 0 else 0

    # ── RPM breakdown ──
    sonar_rpm = round(data.trac_spot_current / mileage, 2) if data.trac_spot_current > 0 else 0
    dat_rpm = round(data.dat_7day / mileage, 2) if data.dat_7day > 0 else 0

    return JSONResponse({
        "mileage": data.mileage,
        # Deltas
        "sonar_spot_delta": round(sonar_spot_delta, 2),
        "dat_spot_delta": round(dat_spot_delta, 2),
        "sonar_vs_dat_high": round(sonar_vs_dat_high, 2),
        # Averages
        "avg_all": avg_all,
        "avg_inputs_used": labels,
        "avg_inputs_count": len(rate_inputs),
        # RPMs
        "sonar_rpm": sonar_rpm,
        "dat_rpm": dat_rpm,
        "carrier_rpm": carrier_rpm,
        "quoted_rpm": quoted_rpm,
        # Pricing
        "carrier_target": carrier_target,
        "margin_usd": round(margin_usd, 2),
        "margin_pct": margin_pct_actual,
        "quote_customer": quote_customer,
    })


# ── Lane comp history (carrier pay from completed FTL loads) ───

@router.get("/api/ftl-quote/lane-comps")
async def ftl_quote_lane_comps(
    origin: str = Query("", description="Origin city/state"),
    destination: str = Query("", description="Destination city/state"),
    days: int = Query(90, description="Lookback days"),
):
    """
    Pull carrier pay comps from completed FTL shipments.
    Fuzzy matches on origin/destination city names.
    Also includes Boviet + Tolead lane data if matching.
    """
    comps = []
    cutoff = (datetime.utcnow() - timedelta(days=days)).isoformat()

    try:
        with db.get_cursor() as cur:
            # Completed FTL shipments with carrier_pay set
            conditions = [
                "LOWER(move_type) IN ('ftl', 'otr', 'full truckload')",
                "carrier_pay IS NOT NULL",
                "carrier_pay > 0",
                f"created_at >= '{cutoff}'",
            ]
            if origin:
                conditions.append(f"LOWER(origin) LIKE '%{origin.lower().replace(chr(39), '')}%'")
            if destination:
                conditions.append(f"LOWER(destination) LIKE '%{destination.lower().replace(chr(39), '')}%'")

            where = " AND ".join(conditions)
            cur.execute(f"""
                SELECT efj, origin, destination, carrier, carrier_pay, customer_rate,
                       pickup_date, delivery_date, account, equipment_type
                FROM shipments
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT 50
            """)
            for row in cur.fetchall():
                cp = float(row["carrier_pay"]) if row.get("carrier_pay") else 0
                cr = float(row["customer_rate"]) if row.get("customer_rate") else 0
                comps.append({
                    "efj": row.get("efj", ""),
                    "origin": row.get("origin", ""),
                    "destination": row.get("destination", ""),
                    "carrier": row.get("carrier", ""),
                    "carrier_pay": cp,
                    "customer_rate": cr,
                    "margin": round(cr - cp, 2) if cr and cp else None,
                    "pickup_date": row.get("pickup_date", ""),
                    "delivery_date": row.get("delivery_date", ""),
                    "account": row.get("account", ""),
                    "equipment": row.get("equipment_type", ""),
                    "source": "shipment",
                })

            # Also pull from lane_rates table (FTL entries)
            lr_conditions = ["LOWER(move_type) IN ('ftl', 'otr')"]
            if origin:
                lr_conditions.append(f"LOWER(port) LIKE '%{origin.lower().replace(chr(39), '')}%'")
            if destination:
                lr_conditions.append(f"LOWER(destination) LIKE '%{destination.lower().replace(chr(39), '')}%'")

            lr_where = " AND ".join(lr_conditions)
            cur.execute(f"""
                SELECT port as origin, destination, carrier_name as carrier,
                       total as carrier_pay, equipment_type as equipment,
                       notes, source, created_at
                FROM lane_rates
                WHERE {lr_where}
                ORDER BY created_at DESC
                LIMIT 30
            """)
            for row in cur.fetchall():
                cp = float(row["carrier_pay"]) if row.get("carrier_pay") else 0
                comps.append({
                    "origin": row.get("origin", ""),
                    "destination": row.get("destination", ""),
                    "carrier": row.get("carrier", ""),
                    "carrier_pay": cp,
                    "equipment": row.get("equipment", ""),
                    "notes": row.get("notes", ""),
                    "source": row.get("source", "lane_rate"),
                    "date": row["created_at"].strftime("%Y-%m-%d") if row.get("created_at") else "",
                })

    except Exception as e:
        log.warning("ftl-quote lane-comps error: %s", e)

    return JSONResponse({
        "comps": comps,
        "count": len(comps),
        "origin_filter": origin,
        "destination_filter": destination,
        "lookback_days": days,
    })


# ── Save a quote for reference ─────────────────────────────────

class FTLQuoteSave(BaseModel):
    origin: str
    destination: str
    mileage: float
    carrier_target: float
    quote_customer: float
    margin_usd: float
    margin_pct: float
    quoted_rpm: float
    inputs_json: dict = {}
    notes: str = ""


@router.post("/api/ftl-quote/save")
async def ftl_quote_save(data: FTLQuoteSave, request: Request):
    """Persist an FTL quote to the quotes table for history tracking."""
    import json as _json
    try:
        user = getattr(request.state, "user", {})
        username = user.get("username", "unknown")

        # Generate next quote number
        with db.get_cursor() as cur:
            cur.execute("SELECT MAX(id) as max_id FROM quotes")
            row = cur.fetchone()
            next_num = (row["max_id"] or 0) + 1
            quote_number = f"CSL-FTL-{next_num:04d}"

            # Store lane + inputs in route_json
            route_data = {
                "origin": data.origin,
                "destination": data.destination,
                "mileage": data.mileage,
                "quoted_rpm": data.quoted_rpm,
                "inputs": data.inputs_json,
            }

            # Store margin info in linehaul_json
            linehaul_data = {
                "carrier_target": data.carrier_target,
                "margin_usd": data.margin_usd,
                "notes": data.notes,
                "created_by": username,
            }

            cur.execute("""
                INSERT INTO quotes (
                    quote_number, shipment_type, pod, final_delivery,
                    one_way_miles, carrier_total, margin_pct,
                    estimated_total, linehaul_json, route_json,
                    created_at, updated_at
                ) VALUES (
                    %s, 'FTL', %s, %s, %s, %s, %s, %s, %s, %s, NOW(), NOW()
                )
                RETURNING id
            """, (
                quote_number, data.origin, data.destination,
                str(data.mileage), data.carrier_target, data.margin_pct,
                data.quote_customer,
                _json.dumps(linehaul_data), _json.dumps(route_data),
            ))
            row = cur.fetchone()
            quote_id = row["id"] if row else None

        return JSONResponse({"ok": True, "quote_id": quote_id, "quote_number": quote_number})
    except Exception as e:
        log.warning("ftl-quote save error: %s", e)
        return JSONResponse({"ok": False, "error": str(e)}, status_code=500)


# ── Saved FTL quote history ────────────────────────────────────

@router.get("/api/ftl-quote/history")
async def ftl_quote_history(
    limit: int = Query(20),
    origin: str = Query(""),
    destination: str = Query(""),
):
    """Retrieve saved FTL quotes."""
    import json as _json
    results = []
    try:
        with db.get_cursor() as cur:
            conditions = ["shipment_type = 'FTL'"]
            if origin:
                conditions.append(
                    f"(LOWER(pod) LIKE '%{origin.lower().replace(chr(39), '')}%'"
                    f" OR LOWER(COALESCE(route_json->>'origin','')) LIKE '%{origin.lower().replace(chr(39), '')}%')"
                )
            if destination:
                conditions.append(
                    f"(LOWER(final_delivery) LIKE '%{destination.lower().replace(chr(39), '')}%'"
                    f" OR LOWER(COALESCE(route_json->>'destination','')) LIKE '%{destination.lower().replace(chr(39), '')}%')"
                )
            where = " AND ".join(conditions)
            cur.execute(f"""
                SELECT id, quote_number, pod, final_delivery, one_way_miles,
                       carrier_total, estimated_total, margin_pct,
                       linehaul_json, route_json, created_at
                FROM quotes
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT %s
            """, (limit,))
            for row in cur.fetchall():
                route = row.get("route_json") or {}
                if isinstance(route, str):
                    try: route = _json.loads(route)
                    except: route = {}
                linehaul = row.get("linehaul_json") or {}
                if isinstance(linehaul, str):
                    try: linehaul = _json.loads(linehaul)
                    except: linehaul = {}
                results.append({
                    "id": row["id"],
                    "quote_number": row.get("quote_number", ""),
                    "origin": route.get("origin", row.get("pod", "")),
                    "destination": route.get("destination", row.get("final_delivery", "")),
                    "mileage": float(row["one_way_miles"]) if row.get("one_way_miles") and row["one_way_miles"].replace('.','',1).isdigit() else route.get("mileage", 0),
                    "carrier_total": float(row["carrier_total"]) if row.get("carrier_total") else 0,
                    "customer_total": float(row["estimated_total"]) if row.get("estimated_total") else 0,
                    "margin_pct": float(row["margin_pct"]) if row.get("margin_pct") else 0,
                    "notes": linehaul.get("notes", ""),
                    "created_by": linehaul.get("created_by", ""),
                    "created_at": row["created_at"].strftime("%Y-%m-%d %H:%M") if row.get("created_at") else "",
                })
    except Exception as e:
        log.warning("ftl-quote history error: %s", e)

    return JSONResponse({"quotes": results, "count": len(results)})
