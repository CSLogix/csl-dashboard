"""
FTL Quote Calculator — backend route.

Replicates the Excel-based quoting workflow:
  1. User enters SONAR + DAT market inputs for a lane.
  2. Server calculates deltas, averages, and final customer quote.
  3. Returns lane comp history from completed FTL shipments + lane_rates.
"""

import logging
import threading
from datetime import datetime, timedelta
from typing import Optional

import requests as _req
from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse
from pydantic import BaseModel

import config
import database as db
from shared import log

router = APIRouter()

# ── EIA Diesel Price Cache ────────────────────────────────────
# Cache the weekly diesel price so we don't hit EIA on every page load.
# Refreshes at most once per 6 hours.
_diesel_cache = {"price": None, "date": None, "fetched_at": None}
_diesel_lock = threading.Lock()
_DIESEL_CACHE_TTL = timedelta(hours=6)

# EIA API v2 — Weekly U.S. No 2 Diesel Retail Prices
_EIA_DIESEL_URL = "https://api.eia.gov/v2/petroleum/pri/gnd/data"


def _fetch_eia_diesel() -> dict:
    """Fetch latest weekly US diesel price from EIA API."""
    api_key = config.EIA_API_KEY
    if not api_key:
        return {"price": None, "date": None, "error": "EIA_API_KEY not configured"}

    try:
        resp = _req.get(_EIA_DIESEL_URL, params={
            "api_key": api_key,
            "frequency": "weekly",
            "data[0]": "value",
            "facets[product][]": "EPD2D",   # No 2 Diesel
            "facets[duoarea][]": "NUS",      # U.S. National
            "sort[0][column]": "period",
            "sort[0][direction]": "desc",
            "length": 1,
        }, timeout=10)
        resp.raise_for_status()
        data = resp.json()
        records = data.get("response", {}).get("data", [])
        if records:
            rec = records[0]
            return {
                "price": float(rec["value"]),
                "date": rec.get("period", ""),
                "error": None,
            }
        return {"price": None, "date": None, "error": "No data returned from EIA"}
    except Exception as e:
        log.warning("EIA diesel fetch error: %s", e)
        return {"price": None, "date": None, "error": str(e)}


def _get_diesel_price() -> dict:
    """Get diesel price from cache or fetch if stale."""
    with _diesel_lock:
        now = datetime.utcnow()
        if (
            _diesel_cache["price"] is not None
            and _diesel_cache["fetched_at"]
            and (now - _diesel_cache["fetched_at"]) < _DIESEL_CACHE_TTL
        ):
            return {
                "price": _diesel_cache["price"],
                "date": _diesel_cache["date"],
                "cached": True,
            }

    # Fetch fresh (outside lock to avoid blocking)
    result = _fetch_eia_diesel()
    if result["price"] is not None:
        with _diesel_lock:
            _diesel_cache["price"] = result["price"]
            _diesel_cache["date"] = result["date"]
            _diesel_cache["fetched_at"] = datetime.utcnow()
    return result


@router.get("/api/ftl-quote/diesel-price")
async def ftl_diesel_price():
    """Return current US national average diesel price from EIA."""
    result = _get_diesel_price()
    return JSONResponse({
        "price": result.get("price"),
        "date": result.get("date", ""),
        "cached": result.get("cached", False),
        "error": result.get("error"),
        "source": "EIA Weekly U.S. No 2 Diesel Retail Prices",
    })

# ── Pydantic models ────────────────────────────────────────────

class FTLQuoteRequest(BaseModel):
    origin: str = ""
    destination: str = ""
    mileage: float = 0

    # SONAR TRAC Spot (3 values from Rate Intelligence)
    trac_flat_low: float = 0         # TRAC Spot low
    trac_flat_current: float = 0     # TRAC Spot current
    trac_flat_high: float = 0        # TRAC Spot high

    # SONAR Contract (3 values from Rate Intelligence)
    contract_flat_low: float = 0     # Contract low
    contract_flat_current: float = 0 # Contract current
    contract_flat_high: float = 0    # Contract high

    # DAT Spot (from DAT RateView)
    dat_spot_low: float = 0          # DAT Spot low
    dat_spot_high: float = 0         # DAT Spot high

    # DAT Contract (from DAT RateView)
    dat_contract_low: float = 0      # DAT Contract low
    dat_contract_high: float = 0     # DAT Contract high

    # Capacity / market indicators
    capacity_conditions: str = ""    # Neutral / Difficult / Most Difficult
    otri: float = 0                  # Outbound Tender Rejection Index

    # Deadhead comps (from DAT loadboard — nearby lane rates)
    dh_origin_rate: float = 0        # Best comp: deadhead-to-origin filtered rate
    dh_dest_rate: float = 0          # Best comp: deadhead-to-destination filtered rate

    # Margin
    margin_usd: float = 300.00
    margin_source: str = "fixed"     # "fixed" or "pct"
    margin_pct: float = 15.0         # Used when margin_source == "pct"


# ── Dynamic margin matrix (OTRI × mileage) ───────────────────
#
# OTRI (Outbound Tender Rejection Index) measures market tightness:
#   <5%   = loose (carriers accepting most freight, price-competitive)
#   5-8%  = balanced (normal operating conditions)
#   8-12% = tight (carriers rejecting loads, rates climbing)
#   >12%  = very tight (capacity crunch, premium pricing)
#
# Mileage brackets reflect fixed-cost dilution:
#   Short haul (<300 mi):   Fixed costs dominate → higher margin %
#   Medium (300-800 mi):    Standard operating range
#   Long haul (800-1500 mi): Fixed costs spread → slightly lower %
#   Very long (>1500 mi):   Competitive long-haul → lowest %
#
# Matrix values are margin % of avg_all (carrier target).
_MARGIN_MATRIX = {
    # (otri_band, mileage_band) → margin_pct
    ("loose",      "short"):  12.0,
    ("loose",      "medium"): 10.0,
    ("loose",      "long"):    8.0,
    ("loose",      "xlong"):   7.0,
    ("balanced",   "short"):  15.0,
    ("balanced",   "medium"): 13.0,
    ("balanced",   "long"):   11.0,
    ("balanced",   "xlong"):   9.0,
    ("tight",      "short"):  18.0,
    ("tight",      "medium"): 16.0,
    ("tight",      "long"):   14.0,
    ("tight",      "xlong"):  12.0,
    ("very_tight", "short"):  22.0,
    ("very_tight", "medium"): 20.0,
    ("very_tight", "long"):   17.0,
    ("very_tight", "xlong"):  15.0,
}


def _otri_band(otri: float) -> str:
    if otri < 5:
        return "loose"
    elif otri < 8:
        return "balanced"
    elif otri < 12:
        return "tight"
    return "very_tight"


def _mileage_band(miles: float) -> str:
    if miles < 300:
        return "short"
    elif miles < 800:
        return "medium"
    elif miles < 1500:
        return "long"
    return "xlong"


def _auto_margin_pct(otri: float, mileage: float) -> float:
    """Compute dynamic margin % from OTRI × mileage matrix."""
    ob = _otri_band(otri)
    mb = _mileage_band(mileage)
    return _MARGIN_MATRIX.get((ob, mb), 13.0)  # 13% fallback


# ── Calculation endpoint ───────────────────────────────────────

@router.post("/api/ftl-quote/calculate")
async def ftl_quote_calculate(data: FTLQuoteRequest):
    """Calculate FTL quote from SONAR + DAT market inputs.

    Avg All formula (matches Excel):
      AVERAGE(trac_flat_current, trac_flat_high,
              contract_flat_current, contract_flat_high,
              dat_spot_high, dat_contract_high)
    """
    mileage = data.mileage if data.mileage > 0 else 1  # avoid div/0

    # ── Deltas (match Excel columns) ──
    sonar_spot_delta = data.trac_flat_high - data.trac_flat_current
    dat_spot_delta = data.dat_spot_high - data.dat_spot_low
    dat_high_delta = data.dat_spot_high - data.trac_flat_high  # DAT vs SONAR high comparison

    # ── Avg All: exact Excel formula ──
    # Average of: trac_flat_current, trac_flat_high,
    #             contract_flat_current, contract_flat_high,
    #             dat_spot_high, dat_contract_high
    avg_inputs = []
    avg_labels = []
    for val, label in [
        (data.trac_flat_current, "TRAC Current"),
        (data.trac_flat_high, "TRAC High"),
        (data.contract_flat_current, "Contract Current"),
        (data.contract_flat_high, "Contract High"),
        (data.dat_spot_high, "DAT Spot High"),
        (data.dat_contract_high, "DAT Contract High"),
    ]:
        if val > 0:
            avg_inputs.append(val)
            avg_labels.append(label)

    avg_all = round(sum(avg_inputs) / len(avg_inputs), 2) if avg_inputs else 0

    # ── Sonar Analysis ──
    # "Spot Lower" if TRAC current < Avg All, else "Spot Higher"
    if data.trac_flat_current > 0 and avg_all > 0:
        sonar_analysis = "Spot Lower" if data.trac_flat_current < avg_all else "Spot Higher"
    else:
        sonar_analysis = ""

    # ── Avg vs Spot = Avg All - DAT Spot High ──
    avg_vs_spot = round(avg_all - data.dat_spot_high, 2) if data.dat_spot_high > 0 else 0

    # ── Margin ──
    if data.margin_source == "auto":
        auto_pct = _auto_margin_pct(data.otri, data.mileage)
        margin_usd = round(avg_all * (auto_pct / 100), 2)
    elif data.margin_source == "pct" and data.margin_pct > 0:
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
    spot_rpm = round(data.trac_flat_current / mileage, 2) if data.trac_flat_current > 0 else 0
    contract_rpm = round(data.contract_flat_current / mileage, 2) if data.contract_flat_current > 0 else 0

    return JSONResponse({
        "mileage": data.mileage,
        # Deltas (match Excel columns V, W, U)
        "sonar_spot_delta": round(sonar_spot_delta, 2),
        "dat_spot_delta": round(dat_spot_delta, 2),
        "dat_high_delta": round(dat_high_delta, 2),
        # Avg All (Excel column R)
        "avg_all": avg_all,
        "avg_inputs_used": avg_labels,
        "avg_inputs_count": len(avg_inputs),
        # Sonar Analysis (Excel column S)
        "sonar_analysis": sonar_analysis,
        # Avg vs Spot (Excel column T)
        "avg_vs_spot": avg_vs_spot,
        # RPMs
        "spot_rpm": spot_rpm,
        "contract_rpm": contract_rpm,
        "carrier_rpm": carrier_rpm,
        "quoted_rpm": quoted_rpm,
        # Pricing
        "carrier_target": carrier_target,
        "margin_usd": round(margin_usd, 2),
        "margin_pct": margin_pct_actual,
        "quote_customer": quote_customer,
        # Market context
        "capacity_conditions": data.capacity_conditions,
        "otri": data.otri,
        # Auto margin metadata (always included so frontend can show recommendation)
        "auto_margin": {
            "pct": _auto_margin_pct(data.otri, data.mileage),
            "otri_band": _otri_band(data.otri),
            "mileage_band": _mileage_band(data.mileage),
            "active": data.margin_source == "auto",
        },
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
    cutoff = datetime.utcnow() - timedelta(days=days)

    try:
        with db.get_cursor() as cur:
            # ── Completed FTL shipments (parameterized) ──
            ship_where = [
                "LOWER(move_type) IN ('ftl', 'otr', 'full truckload')",
                "carrier_pay IS NOT NULL",
                "carrier_pay > 0",
                "created_at >= %s",
            ]
            ship_params = [cutoff]
            if origin:
                ship_where.append("LOWER(origin) LIKE %s")
                ship_params.append(f"%{origin.lower()}%")
            if destination:
                ship_where.append("LOWER(destination) LIKE %s")
                ship_params.append(f"%{destination.lower()}%")

            cur.execute(f"""
                SELECT efj, origin, destination, carrier, carrier_pay, customer_rate,
                       pickup_date, delivery_date, account, equipment_type, mileage
                FROM shipments
                WHERE {" AND ".join(ship_where)}
                ORDER BY created_at DESC
                LIMIT 50
            """, ship_params)
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
                    "pickup_date": str(row["pickup_date"]) if row.get("pickup_date") else "",
                    "delivery_date": str(row["delivery_date"]) if row.get("delivery_date") else "",
                    "account": row.get("account", ""),
                    "equipment": row.get("equipment_type", ""),
                    "mileage": float(row["mileage"]) if row.get("mileage") else None,
                    "source": "shipment",
                })

            # ── Lane rates table (FTL entries, parameterized) ──
            lr_where = ["LOWER(move_type) IN ('ftl', 'otr')"]
            lr_params = []
            if origin:
                lr_where.append("LOWER(port) LIKE %s")
                lr_params.append(f"%{origin.lower()}%")
            if destination:
                lr_where.append("LOWER(destination) LIKE %s")
                lr_params.append(f"%{destination.lower()}%")

            cur.execute(f"""
                SELECT port as origin, destination, carrier_name as carrier,
                       total as carrier_pay, equipment_type as equipment,
                       notes, source, created_at
                FROM lane_rates
                WHERE {" AND ".join(lr_where)}
                ORDER BY created_at DESC
                LIMIT 30
            """, lr_params)
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
            params = []
            if origin:
                conditions.append(
                    "(LOWER(pod) LIKE %s"
                    " OR LOWER(COALESCE(route_json->>'origin','')) LIKE %s)"
                )
                params.extend([f"%{origin.lower()}%", f"%{origin.lower()}%"])
            if destination:
                conditions.append(
                    "(LOWER(final_delivery) LIKE %s"
                    " OR LOWER(COALESCE(route_json->>'destination','')) LIKE %s)"
                )
                params.extend([f"%{destination.lower()}%", f"%{destination.lower()}%"])
            where = " AND ".join(conditions)
            params.append(limit)
            cur.execute(f"""
                SELECT id, quote_number, pod, final_delivery, one_way_miles,
                       carrier_total, estimated_total, margin_pct,
                       linehaul_json, route_json, created_at
                FROM quotes
                WHERE {where}
                ORDER BY created_at DESC
                LIMIT %s
            """, params)
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
