"""
AI Assistant module for CSL Dashboard.
Uses Claude Sonnet tool-calling to answer logistics questions
with real-time data from the CSL Postgres database.
"""

import json
import logging
import os
import re
from datetime import datetime, date
from decimal import Decimal

import anthropic

import database as db

log = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config
# ---------------------------------------------------------------------------

ANTHROPIC_API_KEY = os.getenv("ANTHROPIC_API_KEY", "")
MODEL = "claude-sonnet-4-20250514"
MAX_TOOL_ITERATIONS = 5
MAX_RESPONSE_TOKENS = 2048

client = None

def _get_client():
    global client
    if client is None:
        client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)
    return client

# ---------------------------------------------------------------------------
# JSON serializer helper
# ---------------------------------------------------------------------------

def _serialize(obj):
    """Convert DB types to JSON-safe values."""
    if obj is None:
        return None
    if isinstance(obj, (datetime, date)):
        return obj.isoformat()
    if isinstance(obj, Decimal):
        return float(obj)
    if isinstance(obj, dict):
        return {k: _serialize(v) for k, v in obj.items()}
    if isinstance(obj, (list, tuple)):
        return [_serialize(i) for i in obj]
    return obj

def _rows_to_list(rows, limit=25):
    """Convert RealDictRows to serializable list, capped."""
    return [_serialize(dict(r)) for r in rows[:limit]]

# ---------------------------------------------------------------------------
# System prompt
# ---------------------------------------------------------------------------

SYSTEM_PROMPT = """You are the CSL Bot AI assistant for Evans Delivery / EFJ Operations, a drayage and freight logistics company.

Key context:
- EFJ numbers are load identifiers (e.g. EFJ-1234)
- Move types: DRAY IMPORT, DRAY EXPORT, FTL (full truckload)
- Statuses: pending, dispatched, in_transit, at_port, picked_up, out_for_delivery, delivered, invoiced, cancelled, ready_to_close
- Accounts: Allround, Boviet, Cadi, DHL, DSV, EShipping, IWS, Kripke, MAO, MGF, Rose, USHA, Tolead
- Tolead hubs: ORD, JFK, LAX, DFW
- Rate terminology: dray_rate (linehaul), FSC (fuel surcharge), chassis_per_day, prepull, detention, storage
- Carrier tiers: 1 = preferred, 2 = standard, 3 = backup. DNU = Do Not Use
- customer_rate = what we charge the customer, carrier_pay = what we pay the carrier, margin = customer_rate - carrier_pay

Use the provided tools to look up real data before answering. You have 24 tools covering:
- Lane rates, margins, accessorial estimates, and smart dispatch suggestions
- Carrier search, compliance, and what-if comparisons
- Shipment status, full summaries, side-by-side load comparisons
- Billing checklists, document status, and account health reports
- Unit conversions (metric/imperial, CBM, weight)
- Detention/demurrage cost calculations
- Transit time estimates from historical delivery data
- Daily briefings, customer-friendly explanations, and carrier emails

Be concise, direct, and data-driven. Format monetary values with $ signs. When showing rates, include accessorials if non-zero. If a query returns no results, say so clearly."""

# ---------------------------------------------------------------------------
# Tool definitions for Claude API
# ---------------------------------------------------------------------------

TOOLS = [
    {
        "name": "query_lane_history",
        "description": "Search lane rate history for a port/origin to destination. Returns carrier options with rates and accessorial charges. Use when user asks about rates, pricing, lanes, or quotes for a route.",
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "Port or origin city/terminal (e.g. 'PNCT', 'Newark', 'APM', 'Maher')"
                },
                "destination": {
                    "type": "string",
                    "description": "Destination city or state (e.g. 'Edison NJ', 'Chicago', 'Atlanta')"
                },
                "equipment_type": {
                    "type": "string",
                    "description": "Optional: 20, 40, 40HC, 45, etc."
                }
            },
            "required": ["origin", "destination"]
        }
    },
    {
        "name": "query_carrier_db",
        "description": "Search the carrier database by name, market area, or capability. Returns carriers with contact info, tier rank, and capability badges. Use when user asks about finding carriers, carrier capabilities, or who serves a market.",
        "input_schema": {
            "type": "object",
            "properties": {
                "search_term": {
                    "type": "string",
                    "description": "Carrier name or partial name to search"
                },
                "market": {
                    "type": "string",
                    "description": "Market area to filter by (matches against markets array)"
                },
                "capability": {
                    "type": "string",
                    "enum": ["hazmat", "overweight", "reefer", "bonded", "oog", "warehousing", "transload", "dray"],
                    "description": "Required capability filter"
                },
                "exclude_dnu": {
                    "type": "boolean",
                    "description": "Exclude Do Not Use carriers (default true)"
                }
            }
        }
    },
    {
        "name": "check_efj_status",
        "description": "Look up a specific shipment by EFJ number. Returns full shipment details including status, carrier, dates, financials, and latest tracking events. Use when user asks about a specific load.",
        "input_schema": {
            "type": "object",
            "properties": {
                "efj": {
                    "type": "string",
                    "description": "EFJ load number (e.g. 'EFJ-1234' or '1234')"
                }
            },
            "required": ["efj"]
        }
    },
    {
        "name": "extract_rate_con",
        "description": "Parse rate confirmation text to extract structured data: carrier, rate, origin, destination, and accessorials. Use when user pastes rate con text and wants it parsed.",
        "input_schema": {
            "type": "object",
            "properties": {
                "text": {
                    "type": "string",
                    "description": "Raw rate confirmation text to parse"
                }
            },
            "required": ["text"]
        }
    },
    {
        "name": "draft_new_load",
        "description": "Create a structured new load entry from provided details. Returns the structured data but does NOT insert into the database. Use when user wants to draft/prepare a new shipment entry.",
        "input_schema": {
            "type": "object",
            "properties": {
                "move_type": {
                    "type": "string",
                    "enum": ["DRAY IMPORT", "DRAY EXPORT", "FTL"],
                    "description": "Type of move"
                },
                "origin": {
                    "type": "string",
                    "description": "Origin terminal or city"
                },
                "destination": {
                    "type": "string",
                    "description": "Destination city/address"
                },
                "carrier": {
                    "type": "string",
                    "description": "Carrier name"
                },
                "container": {
                    "type": "string",
                    "description": "Container number (dray) or load reference"
                },
                "customer_rate": {
                    "type": "number",
                    "description": "Customer rate in dollars"
                },
                "carrier_pay": {
                    "type": "number",
                    "description": "Carrier pay in dollars"
                },
                "account": {
                    "type": "string",
                    "description": "Customer account name"
                },
                "eta": {
                    "type": "string",
                    "description": "ETA date (YYYY-MM-DD)"
                },
                "lfd": {
                    "type": "string",
                    "description": "Last Free Day (YYYY-MM-DD)"
                }
            },
            "required": ["move_type", "origin", "destination"]
        }
    },

    {
        "name": "calculate_lane_iq_margin",
        "description": "Calculate suggested customer rate for a lane based on historical carrier pay averages plus a target margin. Use when user asks \"what should we charge\", \"quote this lane\", or \"margin on this route\".",
        "input_schema": {
            "type": "object",
            "properties": {
                "origin": {
                    "type": "string",
                    "description": "Port or origin terminal (e.g. \'PNCT\', \'Maher\', \'APM\')"
                },
                "destination": {
                    "type": "string",
                    "description": "Destination city or area"
                },
                "target_margin_pct": {
                    "type": "number",
                    "description": "Target margin percentage (default 15). Margin Guard warns below 10%."
                }
            },
            "required": ["origin", "destination"]
        }
    },
    {
        "name": "carrier_compliance_guard",
        "description": "Check carrier compliance: DNU status, tier rank, service feedback, and on-time history. Use when user asks \"is this carrier good\", \"can we use X\", \"carrier scorecard\", or before assigning a carrier to a load.",
        "input_schema": {
            "type": "object",
            "properties": {
                "carrier_name": {
                    "type": "string",
                    "description": "Carrier name to check"
                },
                "mc_number": {
                    "type": "string",
                    "description": "MC number (alternative to name)"
                }
            }
        }
    },
    {
        "name": "empty_return_scheduler",
        "description": "Find delivered dray import loads that still need empty container return. Calculates days since delivery and flags per diem risk. Use when user asks about \"empty returns\", \"containers to return\", \"per diem\", or \"free time\".",
        "input_schema": {
            "type": "object",
            "properties": {
                "account": {
                    "type": "string",
                    "description": "Optional: filter by account name"
                },
                "days_back": {
                    "type": "integer",
                    "description": "How many days back to search (default 14)"
                }
            }
        }
    },
    {
        "name": "check_document_status",
        "description": "Check document completeness for a load: which docs are on file (rate con, POD, carrier invoice, BOL) and which are missing. Use when user asks \"what docs do we have\", \"is this load ready to bill\", \"missing paperwork\".",
        "input_schema": {
            "type": "object",
            "properties": {
                "efj": {
                    "type": "string",
                    "description": "EFJ load number"
                }
            },
            "required": ["efj"]
        }
    },
    {
        "name": "draft_carrier_email",
        "description": "Draft a professional email to a carrier about a specific load. Pulls carrier contact from driver_contacts table. Use when user says \"email the carrier\", \"draft a message to\", \"reach out about this load\".",
        "input_schema": {
            "type": "object",
            "properties": {
                "efj": {
                    "type": "string",
                    "description": "EFJ load number for context"
                },
                "purpose": {
                    "type": "string",
                    "enum": ["tracking_update", "delivery_confirmation", "pod_request", "rate_confirmation", "general"],
                    "description": "Purpose of the email"
                },
                "custom_message": {
                    "type": "string",
                    "description": "Optional custom message or notes to include"
                }
            },
            "required": ["efj", "purpose"]
        }
    },
    {
        "name": "weekly_margin_report",
        "description": "Generate a margin summary across delivered loads: total revenue, total carrier pay, avg margin %, top/bottom lanes. Use when user asks \"how are margins\", \"weekly profit\", \"margin report\", \"how did we do this week\".",
        "input_schema": {
            "type": "object",
            "properties": {
                "days": {
                    "type": "integer",
                    "description": "Number of days to look back (default 7)"
                },
                "account": {
                    "type": "string",
                    "description": "Optional: filter by account"
                }
            }
        }
    },

    {
            "name": "unit_converter",
            "description": "Convert between metric and imperial units used in logistics: cm/m to ft/in, kg to lbs, CBM to cuft, miles to km, Celsius to Fahrenheit, metric tons. Use when user asks to convert measurements or weights.",
            "input_schema": {
                    "type": "object",
                    "properties": {
                            "value": {
                                    "type": "number",
                                    "description": "Numeric value to convert"
                            },
                            "from_unit": {
                                    "type": "string",
                                    "description": "Source unit (cm, m, ft, in, kg, lbs, mt, cbm, cuft, mi, km, gal, l, c, f)"
                            },
                            "to_unit": {
                                    "type": "string",
                                    "description": "Target unit (same options)"
                            }
                    },
                    "required": [
                            "value",
                            "from_unit",
                            "to_unit"
                    ]
            }
    },
    {
            "name": "shipment_summary",
            "description": "Generate a comprehensive one-pager brief for a shipment. Pulls shipment details, tracking, docs, emails, margin, carrier into one summary. Use when user asks 'summary of', 'brief me on', 'one-pager for', or 'what's going on with' a load.",
            "input_schema": {
                    "type": "object",
                    "properties": {
                            "efj": {
                                    "type": "string",
                                    "description": "EFJ load number"
                            }
                    },
                    "required": [
                            "efj"
                    ]
            }
    },
    {
            "name": "detention_calculator",
            "description": "Calculate detention/demurrage charges by terminal, arrival date, and free time. Returns when detention starts, daily cost, total accrued. Use for 'detention', 'demurrage', 'per diem', 'free time' questions.",
            "input_schema": {
                    "type": "object",
                    "properties": {
                            "terminal": {
                                    "type": "string",
                                    "description": "Terminal name (PNCT, APM, Maher, GCT Bayonne, etc.)"
                            },
                            "arrival_date": {
                                    "type": "string",
                                    "description": "Container arrival date YYYY-MM-DD"
                            },
                            "free_days": {
                                    "type": "integer",
                                    "description": "Free days (default varies by terminal)"
                            },
                            "lfd": {
                                    "type": "string",
                                    "description": "Last Free Day YYYY-MM-DD (overrides free_days calc)"
                            }
                    },
                    "required": [
                            "terminal"
                    ]
            }
    },
    {
            "name": "accessorial_estimator",
            "description": "Estimate expected accessorial charges for a lane from historical averages: chassis, prepull, tolls, overweight, detention, storage. Use for 'what extras', 'estimate accessorials', 'all-in cost'.",
            "input_schema": {
                    "type": "object",
                    "properties": {
                            "origin": {
                                    "type": "string",
                                    "description": "Port or origin terminal"
                            },
                            "destination": {
                                    "type": "string",
                                    "description": "Destination city"
                            },
                            "equipment_type": {
                                    "type": "string",
                                    "description": "Optional: 20, 40, 40HC, 45"
                            }
                    },
                    "required": [
                            "origin",
                            "destination"
                    ]
            }
    },
    {
            "name": "billing_checklist",
            "description": "Full billing readiness check: POD? Rate con? Carrier invoice? Rates entered? Status delivered? Returns pass/fail per item. Use for 'ready to bill', 'billing checklist', 'can we invoice'.",
            "input_schema": {
                    "type": "object",
                    "properties": {
                            "efj": {
                                    "type": "string",
                                    "description": "EFJ load number"
                            }
                    },
                    "required": [
                            "efj"
                    ]
            }
    },
    {
            "name": "load_comparison",
            "description": "Side-by-side comparison of two loads: rates, carriers, timeline, docs, margin. Use for 'compare', 'diff', 'difference between' two EFJ numbers.",
            "input_schema": {
                    "type": "object",
                    "properties": {
                            "efj_1": {
                                    "type": "string",
                                    "description": "First EFJ"
                            },
                            "efj_2": {
                                    "type": "string",
                                    "description": "Second EFJ"
                            }
                    },
                    "required": [
                            "efj_1",
                            "efj_2"
                    ]
            }
    },
    {
            "name": "account_health_report",
            "description": "Account-level health report: volume, margin, open issues, missing docs, unbilled, carrier mix. Use for 'how is [account] doing', 'account report', 'DSV health'.",
            "input_schema": {
                    "type": "object",
                    "properties": {
                            "account": {
                                    "type": "string",
                                    "description": "Account name (DSV, Allround, Boviet, etc.)"
                            },
                            "days": {
                                    "type": "integer",
                                    "description": "Lookback days (default 30)"
                            }
                    },
                    "required": [
                            "account"
                    ]
            }
    },
    {
            "name": "transit_time_estimator",
            "description": "Estimate transit time from actual shipment data: avg/min/max days. Better than Google Maps \u2014 uses YOUR delivery history. Use for 'how long from X to Y', 'transit time', 'delivery estimate'.",
            "input_schema": {
                    "type": "object",
                    "properties": {
                            "origin": {
                                    "type": "string",
                                    "description": "Origin terminal or city"
                            },
                            "destination": {
                                    "type": "string",
                                    "description": "Destination city"
                            }
                    },
                    "required": [
                            "origin",
                            "destination"
                    ]
            }
    },
    {
            "name": "explain_like_a_customer",
            "description": "Translate logistics jargon to plain English for customer emails. Handles LFD, demurrage, per diem, chassis split, detention, etc. Use for 'explain to customer', 'plain English', 'customer-friendly'.",
            "input_schema": {
                    "type": "object",
                    "properties": {
                            "text": {
                                    "type": "string",
                                    "description": "Internal logistics text to translate"
                            },
                            "context": {
                                    "type": "string",
                                    "description": "Optional situation context"
                            }
                    },
                    "required": [
                            "text"
                    ]
            }
    },
    {
            "name": "what_if_scenario",
            "description": "What-if analysis: compare two carriers on a lane. Checks rates, compliance, historical performance. Use for 'what if I use X instead of Y', 'compare carriers', 'should I use X or Y'.",
            "input_schema": {
                    "type": "object",
                    "properties": {
                            "carrier_a": {
                                    "type": "string",
                                    "description": "First carrier"
                            },
                            "carrier_b": {
                                    "type": "string",
                                    "description": "Second carrier"
                            },
                            "efj": {
                                    "type": "string",
                                    "description": "Optional EFJ for lane context"
                            },
                            "origin": {
                                    "type": "string",
                                    "description": "Origin if no EFJ"
                            },
                            "destination": {
                                    "type": "string",
                                    "description": "Destination if no EFJ"
                            }
                    },
                    "required": [
                            "carrier_a",
                            "carrier_b"
                    ]
            }
    },
    {
            "name": "daily_briefing",
            "description": "Morning briefing: arriving today, LFDs expiring, containers to return, missing PODs, low-margin alerts, unreplied emails. Use for 'what do I need to know', 'morning briefing', 'daily summary', 'standup'.",
            "input_schema": {
                    "type": "object",
                    "properties": {
                            "account": {
                                    "type": "string",
                                    "description": "Optional account filter"
                            },
                            "rep": {
                                    "type": "string",
                                    "description": "Optional rep filter"
                            }
                    }
            }
    },
    {
            "name": "smart_dispatch_suggest",
            "description": "Ranked carrier suggestions for a lane: rates + compliance + capabilities in one smart flow. Use for 'I need a carrier for', 'who can do', 'suggest a carrier', 'dispatch options for'.",
            "input_schema": {
                    "type": "object",
                    "properties": {
                            "origin": {
                                    "type": "string",
                                    "description": "Origin terminal/port"
                            },
                            "destination": {
                                    "type": "string",
                                    "description": "Destination city"
                            },
                            "equipment_type": {
                                    "type": "string",
                                    "description": "Optional: 20, 40, 40HC, 45"
                            },
                            "requirements": {
                                    "type": "array",
                                    "items": {
                                            "type": "string",
                                            "enum": [
                                                    "hazmat",
                                                    "overweight",
                                                    "reefer",
                                                    "bonded",
                                                    "oog"
                                            ]
                                    },
                                    "description": "Optional special requirements"
                            }
                    },
                    "required": [
                            "origin",
                            "destination"
                    ]
            }
    },

]

# ---------------------------------------------------------------------------
# Tool execution functions
# ---------------------------------------------------------------------------

def _exec_query_lane_history(origin: str, destination: str, equipment_type: str = None) -> dict:
    """Search lane_rates for origin/destination matches."""
    try:
        with db.get_cursor() as cur:
            sql = """
                SELECT port, destination, carrier_name, dray_rate, fsc, total,
                       chassis_per_day, prepull, storage_per_day, detention,
                       chassis_split, overweight, tolls, reefer, hazmat,
                       all_in_total, rank, equipment_type, move_type, triaxle,
                       bond_fee, residential, notes, source_tab, created_at
                FROM lane_rates
                WHERE (LOWER(port) LIKE %s OR LOWER(port) LIKE %s)
                  AND (LOWER(destination) LIKE %s OR LOWER(destination) LIKE %s)
            """
            o = origin.lower().strip()
            d = destination.lower().strip()
            params = [f"%{o}%", f"{o}%", f"%{d}%", f"{d}%"]

            if equipment_type:
                sql += " AND LOWER(equipment_type) = %s"
                params.append(equipment_type.lower().strip())

            sql += " ORDER BY created_at DESC NULLS LAST LIMIT 25"
            cur.execute(sql, params)
            rows = cur.fetchall()

        if not rows:
            return {"results": [], "message": f"No lane rates found for {origin} -> {destination}"}

        return {"results": _rows_to_list(rows), "count": len(rows)}
    except Exception as e:
        log.exception("query_lane_history failed")
        return {"error": str(e)}


def _exec_query_carrier_db(search_term: str = None, market: str = None,
                           capability: str = None, exclude_dnu: bool = True) -> dict:
    """Search carriers table with filters."""
    try:
        with db.get_cursor() as cur:
            conditions = []
            params = []

            if search_term:
                conditions.append("LOWER(carrier_name) LIKE %s")
                params.append(f"%{search_term.lower().strip()}%")

            if market:
                conditions.append("(markets::text ILIKE %s OR COALESCE(pickup_area,'') ILIKE %s OR COALESCE(destination_area,'') ILIKE %s)")
                m = f"%{market.strip()}%"
                params.extend([m, m, m])

            cap_map = {
                "hazmat": "can_hazmat", "overweight": "can_overweight",
                "reefer": "can_reefer", "bonded": "can_bonded",
                "oog": "can_oog", "warehousing": "can_warehousing",
                "transload": "can_transload", "dray": "can_dray",
            }
            if capability and capability in cap_map:
                conditions.append(f"{cap_map[capability]} = true")

            if exclude_dnu:
                conditions.append("(dnu IS NULL OR dnu = false)")

            where = " AND ".join(conditions) if conditions else "TRUE"
            sql = f"""
                SELECT carrier_name, mc_number, dot_number, contact_email,
                       contact_phone, contact_name, tier_rank, dnu,
                       can_dray, can_hazmat, can_overweight, can_reefer,
                       can_bonded, can_oog, can_warehousing, can_transload,
                       markets, pickup_area, destination_area, trucks,
                       service_feedback, notes
                FROM carriers
                WHERE {where}
                ORDER BY COALESCE(tier_rank, 99), carrier_name
                LIMIT 20
            """
            cur.execute(sql, params)
            rows = cur.fetchall()

        if not rows:
            return {"results": [], "message": "No carriers found matching criteria"}

        return {"results": _rows_to_list(rows), "count": len(rows)}
    except Exception as e:
        log.exception("query_carrier_db failed")
        return {"error": str(e)}


def _exec_check_efj_status(efj: str) -> dict:
    """Look up shipment by EFJ and include recent tracking events."""
    # Normalize: accept 'EFJ-1234', 'efj1234', '1234' etc.
    efj_clean = efj.strip().upper()
    if not efj_clean.startswith("EFJ"):
        efj_clean = f"EFJ-{efj_clean.lstrip('-')}"
    # Ensure dash
    if re.match(r'^EFJ\d', efj_clean):
        efj_clean = "EFJ-" + efj_clean[3:]

    try:
        with db.get_cursor() as cur:
            # Shipment lookup
            cur.execute("""
                SELECT efj, move_type, container, bol, vessel, carrier, origin,
                       destination, eta, lfd, pickup_date, delivery_date, status,
                       notes, bot_notes, return_date, driver, driver_phone,
                       account, hub, rep, customer_rate, carrier_pay,
                       created_at, updated_at
                FROM shipments
                WHERE efj = %s AND (archived IS NULL OR archived = false)
            """, (efj_clean,))
            row = cur.fetchone()

            if not row:
                # Try fuzzy match
                cur.execute("""
                    SELECT efj, status, carrier, origin, destination, account
                    FROM shipments
                    WHERE efj LIKE %s AND (archived IS NULL OR archived = false)
                    ORDER BY created_at DESC LIMIT 5
                """, (f"%{efj.strip().lstrip('EFJefj-')}%",))
                fuzzy = cur.fetchall()
                if fuzzy:
                    return {
                        "shipment": None,
                        "message": f"No exact match for {efj_clean}. Did you mean one of these?",
                        "suggestions": _rows_to_list(fuzzy)
                    }
                return {"shipment": None, "message": f"No shipment found for {efj_clean}"}

            shipment = _serialize(dict(row))

            # Get latest tracking events
            cur.execute("""
                SELECT event_type, stop_name, city, state, event_time, status_mapped
                FROM tracking_events
                WHERE efj = %s
                ORDER BY event_time DESC NULLS LAST
                LIMIT 5
            """, (efj_clean,))
            events = cur.fetchall()

            shipment["tracking_events"] = _rows_to_list(events)

            # Compute margin if both rates present
            cr = shipment.get("customer_rate")
            cp = shipment.get("carrier_pay")
            if cr and cp and cr > 0:
                shipment["margin"] = round(cr - cp, 2)
                shipment["margin_pct"] = round((cr - cp) / cr * 100, 1)

            return {"shipment": shipment}
    except Exception as e:
        log.exception("check_efj_status failed")
        return {"error": str(e)}


def _exec_extract_rate_con(text: str) -> dict:
    """Parse rate confirmation text using regex patterns."""
    result = {
        "carrier": None,
        "rate": None,
        "origin": None,
        "destination": None,
        "accessorials": {},
        "raw_text_preview": text[:300] if len(text) > 300 else text
    }

    # Carrier name patterns
    carrier_match = re.search(r'(?:carrier|company|trucking|transport)[:\s]*([A-Za-z0-9\s&.]+?)(?:\n|,|MC|DOT)', text, re.I)
    if carrier_match:
        result["carrier"] = carrier_match.group(1).strip()

    # Rate patterns
    rate_patterns = [
        r'\$\s*([\d,]+(?:\.\d{2})?)',
        r'(?:rate|total|amount|linehaul)[:\s]*\$?\s*([\d,]+(?:\.\d{2})?)',
        r'(?:pay|compensation)[:\s]*\$?\s*([\d,]+(?:\.\d{2})?)',
    ]
    rates_found = []
    for pat in rate_patterns:
        for m in re.finditer(pat, text, re.I):
            val = float(m.group(1).replace(',', ''))
            if 100 < val < 50000:
                rates_found.append(val)
    if rates_found:
        result["rate"] = max(rates_found)

    # Origin/destination
    od_match = re.search(r'(?:from|origin|pickup)[:\s]*([A-Za-z\s,]+?)(?:\n|to:|\sto\s)', text, re.I)
    if od_match:
        result["origin"] = od_match.group(1).strip()
    dest_match = re.search(r'(?:to|destination|delivery|deliver to)[:\s]*([A-Za-z\s,]+?)(?:\n|$)', text, re.I)
    if dest_match:
        result["destination"] = dest_match.group(1).strip()

    # Accessorials
    acc_patterns = {
        "fsc": r'(?:FSC|fuel)[:\s]*\$?\s*([\d,]+(?:\.\d{2})?)',
        "detention": r'(?:detention)[:\s]*\$?\s*([\d,]+(?:\.\d{2})?)',
        "chassis": r'(?:chassis)[:\s]*\$?\s*([\d,]+(?:\.\d{2})?)',
        "prepull": r'(?:prepull|pre-pull)[:\s]*\$?\s*([\d,]+(?:\.\d{2})?)',
        "tolls": r'(?:tolls?)[:\s]*\$?\s*([\d,]+(?:\.\d{2})?)',
    }
    for key, pat in acc_patterns.items():
        m = re.search(pat, text, re.I)
        if m:
            result["accessorials"][key] = float(m.group(1).replace(',', ''))

    return {"parsed": result, "message": "Parsed via regex. Review for accuracy."}


def _exec_draft_new_load(move_type: str, origin: str, destination: str,
                         carrier: str = None, container: str = None,
                         customer_rate: float = None, carrier_pay: float = None,
                         account: str = None, eta: str = None, lfd: str = None) -> dict:
    """Build structured load data without inserting."""
    draft = {
        "move_type": move_type,
        "origin": origin,
        "destination": destination,
        "carrier": carrier,
        "container": container,
        "customer_rate": customer_rate,
        "carrier_pay": carrier_pay,
        "account": account,
        "eta": eta,
        "lfd": lfd,
        "status": "pending",
        "created_at": datetime.now().isoformat(),
    }

    if customer_rate and carrier_pay:
        draft["margin"] = round(customer_rate - carrier_pay, 2)
        draft["margin_pct"] = round((customer_rate - carrier_pay) / customer_rate * 100, 1) if customer_rate > 0 else 0

    return {
        "draft": {k: v for k, v in draft.items() if v is not None},
        "message": "Draft created. This has NOT been saved to the database. Use the Add Form in the dashboard to create the load."
    }


# ---------------------------------------------------------------------------
# Tool dispatcher
# ---------------------------------------------------------------------------



def _exec_calculate_lane_iq_margin(origin: str, destination: str,
                                    target_margin_pct: float = 15.0) -> dict:
    """Calculate suggested customer rate from historical carrier pay averages."""
    try:
        with db.get_cursor() as cur:
            o = origin.lower().strip()
            d = destination.lower().strip()
            # Get historical rates for this lane
            cur.execute("""
                SELECT carrier_name, dray_rate, fsc, total, all_in_total,
                       created_at
                FROM lane_rates
                WHERE (LOWER(port) LIKE %s OR LOWER(port) LIKE %s)
                  AND (LOWER(destination) LIKE %s OR LOWER(destination) LIKE %s)
                ORDER BY created_at DESC NULLS LAST
                LIMIT 30
            """, (f"%{o}%", f"{o}%", f"%{d}%", f"{d}%"))
            rates = cur.fetchall()

            if not rates:
                return {"error": f"No historical rates found for {origin} -> {destination}"}

            rates_list = _rows_to_list(rates)

            # Calculate averages
            totals = [r.get("total") or r.get("all_in_total") or r.get("dray_rate") or 0
                      for r in rates_list if (r.get("total") or r.get("all_in_total") or r.get("dray_rate"))]

            if not totals:
                return {"error": "Found lane entries but no usable rate data"}

            avg_carrier = round(sum(totals) / len(totals), 2)
            min_carrier = round(min(totals), 2)
            max_carrier = round(max(totals), 2)
            margin_mult = 1 + (target_margin_pct / 100)
            suggested_rate = round(avg_carrier * margin_mult, 2)
            margin_10_rate = round(avg_carrier * 1.10, 2)  # Margin Guard floor

            # Get recent actual shipment margins for this lane
            cur.execute("""
                SELECT efj, customer_rate, carrier_pay, carrier, delivery_date
                FROM shipments
                WHERE (LOWER(origin) LIKE %s) AND (LOWER(destination) LIKE %s)
                  AND customer_rate IS NOT NULL AND carrier_pay IS NOT NULL
                  AND customer_rate > 0
                ORDER BY delivery_date DESC NULLS LAST
                LIMIT 10
            """, (f"%{o}%", f"%{d}%"))
            actuals = cur.fetchall()
            actual_margins = []
            for a in actuals:
                a = dict(a)
                cr = float(a.get("customer_rate") or 0)
                cp = float(a.get("carrier_pay") or 0)
                if cr > 0:
                    actual_margins.append({
                        "efj": a["efj"],
                        "customer_rate": cr,
                        "carrier_pay": cp,
                        "margin_pct": round((cr - cp) / cr * 100, 1)
                    })

        return {
            "lane": f"{origin} -> {destination}",
            "sample_size": len(totals),
            "avg_carrier_pay": avg_carrier,
            "min_carrier_pay": min_carrier,
            "max_carrier_pay": max_carrier,
            "target_margin_pct": target_margin_pct,
            "suggested_customer_rate": suggested_rate,
            "margin_guard_floor": margin_10_rate,
            "warning": "Below this rate triggers Margin Guard (< 10%)" if suggested_rate < margin_10_rate else None,
            "recent_actuals": actual_margins[:5] if actual_margins else "No recent shipments with both rates",
        }
    except Exception as e:
        log.exception("calculate_lane_iq_margin failed")
        return {"error": str(e)}


def _exec_carrier_compliance_guard(carrier_name: str = None,
                                    mc_number: str = None) -> dict:
    """Check carrier compliance, DNU status, tier, and service history."""
    try:
        with db.get_cursor() as cur:
            if mc_number:
                cur.execute("""
                    SELECT carrier_name, mc_number, dot_number, tier_rank, dnu,
                           can_dray, can_hazmat, can_overweight, can_reefer,
                           can_bonded, can_oog, can_warehousing, can_transload,
                           service_feedback, service_notes, service_record, comments,
                           insurance_info, trucks, markets, contact_email, contact_phone
                    FROM carriers WHERE mc_number = %s
                """, (mc_number.strip(),))
            elif carrier_name:
                cur.execute("""
                    SELECT carrier_name, mc_number, dot_number, tier_rank, dnu,
                           can_dray, can_hazmat, can_overweight, can_reefer,
                           can_bonded, can_oog, can_warehousing, can_transload,
                           service_feedback, service_notes, service_record, comments,
                           insurance_info, trucks, markets, contact_email, contact_phone
                    FROM carriers WHERE LOWER(carrier_name) LIKE %s
                    ORDER BY tier_rank NULLS LAST LIMIT 5
                """, (f"%{carrier_name.lower().strip()}%",))
            else:
                return {"error": "Provide carrier_name or mc_number"}

            rows = cur.fetchall()
            if not rows:
                return {"found": False, "message": "Carrier not found in database"}

            results = []
            for row in rows:
                c = _serialize(dict(row))
                # Build compliance summary
                alerts = []
                if c.get("dnu"):
                    alerts.append("DO NOT USE — carrier is flagged DNU")
                if c.get("tier_rank") and c["tier_rank"] >= 3:
                    alerts.append(f"Low tier rank ({c['tier_rank']}) — backup carrier only")
                if c.get("service_feedback") and any(w in (c["service_feedback"] or "").lower()
                                                      for w in ["poor", "late", "damage", "issue", "problem"]):
                    alerts.append(f"Service concerns noted: {c['service_feedback'][:100]}")

                # Count recent loads with this carrier
                cur.execute("""
                    SELECT COUNT(*) as total,
                           COUNT(CASE WHEN LOWER(status) = 'delivered' THEN 1 END) as delivered,
                           COUNT(CASE WHEN LOWER(status) = 'issue' THEN 1 END) as issues
                    FROM shipments
                    WHERE LOWER(carrier) LIKE %s
                      AND created_at > NOW() - INTERVAL '90 days'
                """, (f"%{(c.get('carrier_name') or '').lower()}%",))
                stats = dict(cur.fetchone())

                c["compliance_alerts"] = alerts
                c["compliance_status"] = "BLOCKED" if c.get("dnu") else ("CAUTION" if alerts else "CLEAR")
                c["recent_90d_loads"] = stats.get("total", 0)
                c["recent_90d_delivered"] = stats.get("delivered", 0)
                c["recent_90d_issues"] = stats.get("issues", 0)
                results.append(c)

        return {"carriers": results, "count": len(results)}
    except Exception as e:
        log.exception("carrier_compliance_guard failed")
        return {"error": str(e)}


def _exec_empty_return_scheduler(account: str = None, days_back: int = 14) -> dict:
    """Find delivered dray imports needing empty return, flag per diem risk."""
    try:
        with db.get_cursor() as cur:
            conditions = [
                "LOWER(move_type) LIKE '%import%'",
                "LOWER(status) IN ('delivered', 'empty_return', 'ready_to_close')",
                "delivery_date IS NOT NULL",
                "delivery_date > NOW() - INTERVAL '%s days'" % min(days_back, 60),
                "(archived IS NULL OR archived = false)",
            ]
            params = []
            if account:
                conditions.append("LOWER(account) = %s")
                params.append(account.lower().strip())

            where = " AND ".join(conditions)
            cur.execute(f"""
                SELECT efj, container, vessel, carrier, origin, destination,
                       delivery_date, return_date, lfd, status, account
                FROM shipments
                WHERE {where}
                ORDER BY delivery_date ASC
                LIMIT 30
            """, params)
            rows = cur.fetchall()

        if not rows:
            return {"loads": [], "message": "No delivered dray imports found in the time range"}

        results = []
        now = datetime.now()
        for row in rows:
            r = _serialize(dict(row))
            del_date = row["delivery_date"]
            if hasattr(del_date, 'date'):
                del_date = del_date.date() if hasattr(del_date, 'date') else del_date
            days_since = (now.date() - del_date).days if del_date else None

            r["days_since_delivery"] = days_since
            r["returned"] = r.get("status") == "empty_return" or r.get("return_date") is not None

            # Per diem risk assessment (typical free time is 4-5 days)
            if days_since is not None and not r["returned"]:
                if days_since >= 7:
                    r["per_diem_risk"] = "HIGH"
                    r["alert"] = f"Container held {days_since} days — likely accruing per diem charges"
                elif days_since >= 4:
                    r["per_diem_risk"] = "MEDIUM"
                    r["alert"] = f"Container held {days_since} days — approaching free time limit"
                else:
                    r["per_diem_risk"] = "LOW"
            else:
                r["per_diem_risk"] = "RETURNED" if r["returned"] else "UNKNOWN"

            results.append(r)

        high_risk = [r for r in results if r.get("per_diem_risk") == "HIGH"]
        med_risk = [r for r in results if r.get("per_diem_risk") == "MEDIUM"]

        return {
            "loads": results,
            "total": len(results),
            "high_risk_count": len(high_risk),
            "medium_risk_count": len(med_risk),
            "summary": f"{len(results)} delivered imports, {len(high_risk)} HIGH risk, {len(med_risk)} MEDIUM risk for per diem"
        }
    except Exception as e:
        log.exception("empty_return_scheduler failed")
        return {"error": str(e)}


def _exec_check_document_status(efj: str) -> dict:
    """Check document completeness for billing readiness."""
    efj_clean = efj.strip().upper()
    if not efj_clean.startswith("EFJ"):
        efj_clean = f"EFJ-{efj_clean.lstrip('-')}"
    if re.match(r'^EFJ\d', efj_clean):
        efj_clean = "EFJ-" + efj_clean[3:]

    try:
        with db.get_cursor() as cur:
            # Get shipment basics
            cur.execute("""
                SELECT efj, status, carrier, account, customer_rate, carrier_pay
                FROM shipments
                WHERE efj = %s AND (archived IS NULL OR archived = false)
            """, (efj_clean,))
            ship = cur.fetchone()
            if not ship:
                return {"error": f"No shipment found for {efj_clean}"}

            # Get documents
            cur.execute("""
                SELECT doc_type, filename, original_name, size_bytes, uploaded_at
                FROM load_documents
                WHERE efj = %s
                ORDER BY uploaded_at DESC
            """, (efj_clean,))
            docs = cur.fetchall()

            doc_types_found = set()
            doc_list = []
            for d in docs:
                d = dict(d)
                doc_types_found.add(d["doc_type"])
                doc_list.append({
                    "type": d["doc_type"],
                    "name": d.get("original_name") or d.get("filename"),
                    "size": d.get("size_bytes"),
                    "uploaded": _serialize(d.get("uploaded_at")),
                })

            # Required docs for billing
            required = {"carrier_rate", "pod", "bol"}
            nice_to_have = {"carrier_invoice", "customer_rate"}
            missing_required = required - doc_types_found
            missing_nice = nice_to_have - doc_types_found

            ship = _serialize(dict(ship))
            has_rates = bool(ship.get("customer_rate") and ship.get("carrier_pay"))

            billing_ready = len(missing_required) == 0 and has_rates
            blockers = []
            if missing_required:
                blockers.append(f"Missing required docs: {', '.join(missing_required)}")
            if not has_rates:
                blockers.append("Missing customer_rate or carrier_pay")

        return {
            "efj": efj_clean,
            "status": ship.get("status"),
            "documents_on_file": doc_list,
            "doc_types_found": sorted(doc_types_found),
            "missing_required": sorted(missing_required),
            "missing_nice_to_have": sorted(missing_nice),
            "has_financial_data": has_rates,
            "billing_ready": billing_ready,
            "blockers": blockers if blockers else None,
            "summary": "Ready for billing" if billing_ready else f"NOT ready — {'; '.join(blockers)}"
        }
    except Exception as e:
        log.exception("check_document_status failed")
        return {"error": str(e)}


def _exec_draft_carrier_email(efj: str, purpose: str,
                               custom_message: str = None) -> dict:
    """Draft a professional carrier email with load context."""
    efj_clean = efj.strip().upper()
    if not efj_clean.startswith("EFJ"):
        efj_clean = f"EFJ-{efj_clean.lstrip('-')}"
    if re.match(r'^EFJ\d', efj_clean):
        efj_clean = "EFJ-" + efj_clean[3:]

    try:
        with db.get_cursor() as cur:
            # Get shipment
            cur.execute("""
                SELECT efj, carrier, origin, destination, container, status,
                       pickup_date, delivery_date, driver, driver_phone
                FROM shipments
                WHERE efj = %s AND (archived IS NULL OR archived = false)
            """, (efj_clean,))
            ship = cur.fetchone()
            if not ship:
                return {"error": f"No shipment found for {efj_clean}"}
            ship = _serialize(dict(ship))

            # Get carrier contact
            cur.execute("""
                SELECT carrier_name, driver_name, driver_phone, driver_email,
                       dispatcher_name, dispatcher_phone, dispatcher_email
                FROM driver_contacts
                WHERE efj = %s
                ORDER BY updated_at DESC NULLS LAST LIMIT 1
            """, (efj_clean,))
            contact = cur.fetchone()
            contact = _serialize(dict(contact)) if contact else {}

        # Build email template
        carrier = ship.get("carrier") or contact.get("carrier_name") or "Carrier"
        to_email = contact.get("dispatcher_email") or contact.get("driver_email") or "N/A"
        to_name = contact.get("dispatcher_name") or contact.get("driver_name") or carrier

        templates = {
            "tracking_update": {
                "subject": f"Tracking Update Request — {efj_clean}",
                "body": f"Hi {to_name},\n\nCould you please provide a tracking update for load {efj_clean}?\n\nContainer: {ship.get('container', 'N/A')}\nOrigin: {ship.get('origin', 'N/A')}\nDestination: {ship.get('destination', 'N/A')}\nCurrent Status: {ship.get('status', 'N/A')}\n\nPlease confirm current location and ETA.\n\nThank you,\nEvans Delivery Operations"
            },
            "delivery_confirmation": {
                "subject": f"Delivery Confirmation Needed — {efj_clean}",
                "body": f"Hi {to_name},\n\nCan you confirm delivery for load {efj_clean}?\n\nDestination: {ship.get('destination', 'N/A')}\nScheduled Delivery: {ship.get('delivery_date', 'N/A')}\n\nPlease send POD/signed BOL at your earliest convenience.\n\nThank you,\nEvans Delivery Operations"
            },
            "pod_request": {
                "subject": f"POD Request — {efj_clean}",
                "body": f"Hi {to_name},\n\nWe need the Proof of Delivery (POD) for load {efj_clean}.\n\nDelivery Date: {ship.get('delivery_date', 'N/A')}\nDestination: {ship.get('destination', 'N/A')}\n\nPlease email the signed POD/BOL as soon as possible so we can proceed with billing.\n\nThank you,\nEvans Delivery Operations"
            },
            "rate_confirmation": {
                "subject": f"Rate Confirmation — {efj_clean}",
                "body": f"Hi {to_name},\n\nPlease find the rate confirmation for load {efj_clean}.\n\nOrigin: {ship.get('origin', 'N/A')}\nDestination: {ship.get('destination', 'N/A')}\nContainer: {ship.get('container', 'N/A')}\n\nPlease review, sign, and return at your earliest convenience.\n\nThank you,\nEvans Delivery Operations"
            },
            "general": {
                "subject": f"Re: Load {efj_clean}",
                "body": f"Hi {to_name},\n\nRegarding load {efj_clean}:\n\n{custom_message or '[Your message here]'}\n\nLoad Details:\n- Origin: {ship.get('origin', 'N/A')}\n- Destination: {ship.get('destination', 'N/A')}\n- Container: {ship.get('container', 'N/A')}\n- Status: {ship.get('status', 'N/A')}\n\nThank you,\nEvans Delivery Operations"
            },
        }

        template = templates.get(purpose, templates["general"])
        if custom_message and purpose != "general":
            template["body"] += f"\n\nAdditional note: {custom_message}"

        return {
            "draft": {
                "to": to_email,
                "to_name": to_name,
                "subject": template["subject"],
                "body": template["body"],
            },
            "carrier_contact": contact if contact else "No carrier contact on file",
            "note": "This is a draft — review and send manually via email."
        }
    except Exception as e:
        log.exception("draft_carrier_email failed")
        return {"error": str(e)}


def _exec_weekly_margin_report(days: int = 7, account: str = None) -> dict:
    """Generate margin summary across delivered loads."""
    try:
        with db.get_cursor() as cur:
            conditions = [
                "customer_rate IS NOT NULL",
                "carrier_pay IS NOT NULL",
                "customer_rate > 0",
                "carrier_pay > 0",
                f"delivery_date > NOW() - INTERVAL '{min(days, 90)} days'",
                "(archived IS NULL OR archived = false)",
            ]
            params = []
            if account:
                conditions.append("LOWER(account) = %s")
                params.append(account.lower().strip())

            where = " AND ".join(conditions)

            # Aggregate stats
            cur.execute(f"""
                SELECT
                    COUNT(*) as total_loads,
                    ROUND(SUM(customer_rate)::numeric, 2) as total_revenue,
                    ROUND(SUM(carrier_pay)::numeric, 2) as total_carrier_pay,
                    ROUND(AVG(customer_rate)::numeric, 2) as avg_rate,
                    ROUND(AVG(carrier_pay)::numeric, 2) as avg_carrier_pay,
                    ROUND(AVG((customer_rate - carrier_pay) / customer_rate * 100)::numeric, 1) as avg_margin_pct,
                    COUNT(CASE WHEN (customer_rate - carrier_pay) / customer_rate * 100 < 10 THEN 1 END) as low_margin_count
                FROM shipments
                WHERE {where}
            """, params)
            agg = _serialize(dict(cur.fetchone()))

            # Top margin lanes
            cur.execute(f"""
                SELECT origin, destination,
                       COUNT(*) as loads,
                       ROUND(AVG(customer_rate)::numeric, 2) as avg_rate,
                       ROUND(AVG(carrier_pay)::numeric, 2) as avg_pay,
                       ROUND(AVG((customer_rate - carrier_pay) / customer_rate * 100)::numeric, 1) as avg_margin_pct
                FROM shipments
                WHERE {where}
                GROUP BY origin, destination
                HAVING COUNT(*) >= 2
                ORDER BY avg_margin_pct DESC
                LIMIT 5
            """, params)
            top_lanes = _rows_to_list(cur.fetchall())

            # Bottom margin lanes
            cur.execute(f"""
                SELECT origin, destination,
                       COUNT(*) as loads,
                       ROUND(AVG(customer_rate)::numeric, 2) as avg_rate,
                       ROUND(AVG(carrier_pay)::numeric, 2) as avg_pay,
                       ROUND(AVG((customer_rate - carrier_pay) / customer_rate * 100)::numeric, 1) as avg_margin_pct
                FROM shipments
                WHERE {where}
                GROUP BY origin, destination
                HAVING COUNT(*) >= 2
                ORDER BY avg_margin_pct ASC
                LIMIT 5
            """, params)
            bottom_lanes = _rows_to_list(cur.fetchall())

            # By account breakdown
            cur.execute(f"""
                SELECT account,
                       COUNT(*) as loads,
                       ROUND(SUM(customer_rate - carrier_pay)::numeric, 2) as total_margin,
                       ROUND(AVG((customer_rate - carrier_pay) / customer_rate * 100)::numeric, 1) as avg_margin_pct
                FROM shipments
                WHERE {where}
                GROUP BY account
                ORDER BY total_margin DESC
            """, params)
            by_account = _rows_to_list(cur.fetchall())

        total_revenue = agg.get("total_revenue") or 0
        total_pay = agg.get("total_carrier_pay") or 0
        total_margin = round(total_revenue - total_pay, 2)

        return {
            "period": f"Last {days} days" + (f" ({account})" if account else ""),
            "total_loads": agg.get("total_loads", 0),
            "total_revenue": total_revenue,
            "total_carrier_pay": total_pay,
            "total_margin": total_margin,
            "avg_margin_pct": agg.get("avg_margin_pct", 0),
            "low_margin_loads": agg.get("low_margin_count", 0),
            "top_margin_lanes": top_lanes,
            "bottom_margin_lanes": bottom_lanes,
            "by_account": by_account,
        }
    except Exception as e:
        log.exception("weekly_margin_report failed")
        return {"error": str(e)}



# ---------------------------------------------------------------------------
# Tier 2 — "Stop Asking Me" Tools
# ---------------------------------------------------------------------------

def _exec_unit_converter(value: float, from_unit: str, to_unit: str) -> dict:
    """Convert between logistics-relevant units."""
    conversions = {
        ("cm", "in"): lambda v: v / 2.54,
        ("in", "cm"): lambda v: v * 2.54,
        ("m", "ft"): lambda v: v * 3.28084,
        ("ft", "m"): lambda v: v / 3.28084,
        ("cm", "ft"): lambda v: v / 30.48,
        ("ft", "cm"): lambda v: v * 30.48,
        ("m", "in"): lambda v: v * 39.3701,
        ("in", "m"): lambda v: v / 39.3701,
        ("kg", "lbs"): lambda v: v * 2.20462,
        ("lbs", "kg"): lambda v: v / 2.20462,
        ("cbm", "cuft"): lambda v: v * 35.3147,
        ("cuft", "cbm"): lambda v: v / 35.3147,
        ("mi", "km"): lambda v: v * 1.60934,
        ("km", "mi"): lambda v: v / 1.60934,
        ("gal", "l"): lambda v: v * 3.78541,
        ("l", "gal"): lambda v: v / 3.78541,
        ("c", "f"): lambda v: v * 9/5 + 32,
        ("f", "c"): lambda v: (v - 32) * 5/9,
        ("mt", "lbs"): lambda v: v * 2204.62,
        ("lbs", "mt"): lambda v: v / 2204.62,
        ("mt", "kg"): lambda v: v * 1000,
        ("kg", "mt"): lambda v: v / 1000,
    }
    f_u = from_unit.lower().strip()
    t_u = to_unit.lower().strip()
    key = (f_u, t_u)
    if key not in conversions:
        return {"error": f"Unsupported: {from_unit} -> {to_unit}. Supported: cm, m, ft, in, kg, lbs, mt, cbm, cuft, mi, km, gal, l, c, f"}
    result = round(conversions[key](value), 4)
    return {"input": f"{value} {from_unit}", "output": f"{result} {to_unit}", "value": result}


def _clean_efj(efj_raw):
    """Normalize EFJ input to EFJ-XXXX format."""
    e = efj_raw.strip().upper()
    if not e.startswith("EFJ"):
        e = f"EFJ-{e.lstrip('-')}"
    if re.match(r'^EFJ\d', e):
        e = "EFJ-" + e[3:]
    return e


def _exec_shipment_summary(efj: str) -> dict:
    """Comprehensive one-pager brief for a shipment."""
    efj_clean = _clean_efj(efj)
    try:
        with db.get_cursor() as cur:
            cur.execute("""
                SELECT efj, move_type, container, bol, vessel, carrier, origin,
                       destination, eta, lfd, pickup_date, delivery_date, status,
                       notes, bot_notes, return_date, driver, driver_phone,
                       account, hub, rep, customer_rate, carrier_pay,
                       created_at, updated_at
                FROM shipments
                WHERE efj = %s AND (archived IS NULL OR archived = false)
            """, (efj_clean,))
            ship = cur.fetchone()
            if not ship:
                return {"error": f"No shipment found for {efj_clean}"}
            ship = _serialize(dict(ship))

            # Tracking events
            cur.execute("""
                SELECT event_type, stop_name, city, state, event_time, status_mapped
                FROM tracking_events WHERE efj = %s
                ORDER BY event_time DESC NULLS LAST LIMIT 10
            """, (efj_clean,))
            ship["tracking_events"] = _rows_to_list(cur.fetchall())

            # Documents
            cur.execute("""
                SELECT doc_type, original_name, size_bytes, uploaded_at
                FROM load_documents WHERE efj = %s ORDER BY uploaded_at DESC
            """, (efj_clean,))
            ship["documents"] = _rows_to_list(cur.fetchall())

            # Email count
            cur.execute("SELECT COUNT(*) as cnt FROM email_threads WHERE efj = %s", (efj_clean,))
            ship["email_count"] = dict(cur.fetchone()).get("cnt", 0)

            # Driver contact
            cur.execute("""
                SELECT driver_name, driver_phone, dispatcher_name, dispatcher_phone, dispatcher_email
                FROM driver_contacts WHERE efj = %s
                ORDER BY updated_at DESC NULLS LAST LIMIT 1
            """, (efj_clean,))
            dc = cur.fetchone()
            ship["driver_contact"] = _serialize(dict(dc)) if dc else None

            # Margin
            cr = ship.get("customer_rate")
            cp = ship.get("carrier_pay")
            if cr and cp and float(cr) > 0:
                cr, cp = float(cr), float(cp)
                ship["margin"] = round(cr - cp, 2)
                ship["margin_pct"] = round((cr - cp) / cr * 100, 1)

            # Doc completeness
            doc_types = {d["doc_type"] for d in ship["documents"]}
            required = {"carrier_rate", "pod", "bol"}
            ship["missing_docs"] = sorted(required - doc_types)
            ship["billing_ready"] = len(required - doc_types) == 0 and bool(cr and cp)

        return {"summary": ship}
    except Exception as e:
        log.exception("shipment_summary failed")
        return {"error": str(e)}


def _exec_detention_calculator(terminal: str, arrival_date: str = None,
                                free_days: int = None, lfd: str = None) -> dict:
    """Calculate detention/demurrage based on terminal rates."""
    from datetime import timedelta
    terminal_rates = {
        "pnct": {"name": "PNCT (Port Newark)", "daily_rate": 175, "default_free": 4},
        "apm": {"name": "APM Terminals", "daily_rate": 200, "default_free": 4},
        "maher": {"name": "Maher Terminals", "daily_rate": 185, "default_free": 4},
        "gct": {"name": "GCT Bayonne", "daily_rate": 190, "default_free": 4},
        "gct bayonne": {"name": "GCT Bayonne", "daily_rate": 190, "default_free": 4},
        "red hook": {"name": "Red Hook", "daily_rate": 165, "default_free": 3},
        "nynj": {"name": "NY/NJ General", "daily_rate": 185, "default_free": 4},
        "savannah": {"name": "Savannah (GPA)", "daily_rate": 150, "default_free": 5},
        "norfolk": {"name": "Norfolk (VIT)", "daily_rate": 145, "default_free": 5},
        "charleston": {"name": "Charleston (SCPA)", "daily_rate": 155, "default_free": 5},
        "la": {"name": "Los Angeles", "daily_rate": 200, "default_free": 4},
        "long beach": {"name": "Long Beach", "daily_rate": 200, "default_free": 4},
    }
    t_key = terminal.lower().strip()
    t_info = None
    for k, v in terminal_rates.items():
        if k in t_key or t_key in k:
            t_info = v
            break
    if not t_info:
        t_info = {"name": terminal, "daily_rate": 175, "default_free": 4}

    free = free_days if free_days is not None else t_info["default_free"]
    now = datetime.now()

    if lfd:
        try:
            lfd_date = datetime.strptime(lfd, "%Y-%m-%d")
        except ValueError:
            lfd_date = now
        detention_starts = lfd_date
    elif arrival_date:
        try:
            arr = datetime.strptime(arrival_date, "%Y-%m-%d")
        except ValueError:
            arr = now
        detention_starts = arr + timedelta(days=free)
    else:
        return {
            "terminal": t_info["name"],
            "daily_rate": t_info["daily_rate"],
            "default_free_days": free,
            "message": "Provide arrival_date or lfd to calculate actual charges"
        }

    days_det = max(0, (now - detention_starts).days)
    total_cost = days_det * t_info["daily_rate"]

    return {
        "terminal": t_info["name"],
        "daily_rate": t_info["daily_rate"],
        "free_days": free,
        "detention_start_date": detention_starts.strftime("%Y-%m-%d"),
        "days_in_detention": days_det,
        "estimated_cost": total_cost,
        "status": "ACCRUING" if days_det > 0 else "WITHIN FREE TIME",
        "breakdown": f"${t_info['daily_rate']}/day x {days_det} days = ${total_cost}"
    }


def _exec_accessorial_estimator(origin: str, destination: str,
                                 equipment_type: str = None) -> dict:
    """Estimate accessorials from historical lane_rates data."""
    try:
        with db.get_cursor() as cur:
            o = origin.lower().strip()
            d = destination.lower().strip()
            sql = """
                SELECT chassis_per_day, prepull, storage_per_day, detention,
                       chassis_split, overweight, tolls, reefer, hazmat,
                       triaxle, bond_fee, residential, dray_rate, fsc, total
                FROM lane_rates
                WHERE (LOWER(port) LIKE %s OR LOWER(port) LIKE %s)
                  AND (LOWER(destination) LIKE %s OR LOWER(destination) LIKE %s)
            """
            params = [f"%{o}%", f"{o}%", f"%{d}%", f"{d}%"]
            if equipment_type:
                sql += " AND LOWER(equipment_type) = %s"
                params.append(equipment_type.lower().strip())
            sql += " LIMIT 50"
            cur.execute(sql, params)
            rows = cur.fetchall()

        if not rows:
            return {"error": f"No rate data for {origin} -> {destination}"}

        rows = [_serialize(dict(r)) for r in rows]
        acc_fields = ["chassis_per_day", "prepull", "storage_per_day", "chassis_split",
                      "overweight", "tolls", "reefer", "hazmat", "triaxle", "bond_fee", "residential"]
        averages = {}
        for field in acc_fields:
            vals = [float(r[field]) for r in rows if r.get(field) and float(r[field]) > 0]
            if vals:
                averages[field] = {
                    "avg": round(sum(vals) / len(vals), 2),
                    "min": round(min(vals), 2),
                    "max": round(max(vals), 2),
                    "count": len(vals),
                }

        dray_vals = [float(r["dray_rate"]) for r in rows if r.get("dray_rate") and float(r["dray_rate"]) > 0]
        total_vals = [float(r["total"]) for r in rows if r.get("total") and float(r["total"]) > 0]

        return {
            "lane": f"{origin} -> {destination}",
            "sample_size": len(rows),
            "avg_dray_rate": round(sum(dray_vals) / len(dray_vals), 2) if dray_vals else None,
            "avg_total": round(sum(total_vals) / len(total_vals), 2) if total_vals else None,
            "accessorials": averages,
            "common_extras": [k for k, v in averages.items() if v["count"] >= len(rows) * 0.3],
        }
    except Exception as e:
        log.exception("accessorial_estimator failed")
        return {"error": str(e)}


def _exec_billing_checklist(efj: str) -> dict:
    """Full billing readiness checklist with pass/fail per item."""
    efj_clean = _clean_efj(efj)
    try:
        with db.get_cursor() as cur:
            cur.execute("""
                SELECT efj, status, carrier, account, customer_rate, carrier_pay,
                       delivery_date, move_type
                FROM shipments WHERE efj = %s AND (archived IS NULL OR archived = false)
            """, (efj_clean,))
            ship = cur.fetchone()
            if not ship:
                return {"error": f"No shipment found for {efj_clean}"}
            ship = _serialize(dict(ship))

            cur.execute("SELECT doc_type FROM load_documents WHERE efj = %s", (efj_clean,))
            doc_types = {r["doc_type"] for r in cur.fetchall()}

            # Check unbilled
            cur.execute("""
                SELECT id, age_days FROM unbilled_orders
                WHERE UPPER(order_number) = %s AND dismissed = false
            """, (efj_clean,))
            unbilled = cur.fetchone()

        checks = {
            "pod_on_file": "pod" in doc_types,
            "rate_con_on_file": "carrier_rate" in doc_types or "customer_rate" in doc_types,
            "carrier_invoice_on_file": "carrier_invoice" in doc_types,
            "bol_on_file": "bol" in doc_types,
            "customer_rate_entered": bool(ship.get("customer_rate") and float(ship["customer_rate"]) > 0),
            "carrier_pay_entered": bool(ship.get("carrier_pay") and float(ship["carrier_pay"]) > 0),
            "status_delivered_or_later": ship.get("status") in ("delivered", "ready_to_close", "invoiced", "empty_return"),
            "has_delivery_date": bool(ship.get("delivery_date")),
        }
        blockers = [k.replace("_", " ").title() for k, v in checks.items() if not v]
        passed = all(checks.values())

        result = {
            "efj": efj_clean, "account": ship.get("account"), "status": ship.get("status"),
            "checks": checks,
            "passed": sum(1 for v in checks.values() if v),
            "total": len(checks),
            "blockers": blockers,
            "billing_ready": passed,
            "verdict": "READY TO BILL" if passed else f"NOT READY -- {len(blockers)} blocker(s): {', '.join(blockers)}",
        }
        if unbilled:
            result["unbilled_alert"] = f"Open unbilled order (age: {dict(unbilled).get('age_days', '?')} days)"
        return result
    except Exception as e:
        log.exception("billing_checklist failed")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Tier 3 — "Make Me Look Smart" Tools
# ---------------------------------------------------------------------------

def _exec_load_comparison(efj_1: str, efj_2: str) -> dict:
    """Side-by-side comparison of two loads."""
    efj1 = _clean_efj(efj_1)
    efj2 = _clean_efj(efj_2)
    try:
        with db.get_cursor() as cur:
            loads = {}
            for efj in [efj1, efj2]:
                cur.execute("""
                    SELECT efj, move_type, container, carrier, origin, destination,
                           eta, lfd, pickup_date, delivery_date, status, account,
                           customer_rate, carrier_pay, driver, return_date, vessel
                    FROM shipments WHERE efj = %s AND (archived IS NULL OR archived = false)
                """, (efj,))
                row = cur.fetchone()
                if not row:
                    return {"error": f"Shipment {efj} not found"}
                loads[efj] = _serialize(dict(row))

                cur.execute("SELECT doc_type FROM load_documents WHERE efj = %s", (efj,))
                loads[efj]["doc_types"] = sorted({r["doc_type"] for r in cur.fetchall()})

            for efj_k, s in loads.items():
                cr = s.get("customer_rate")
                cp = s.get("carrier_pay")
                if cr and cp and float(cr) > 0:
                    cr, cp = float(cr), float(cp)
                    s["margin"] = round(cr - cp, 2)
                    s["margin_pct"] = round((cr - cp) / cr * 100, 1)

            compare_fields = ["move_type", "carrier", "origin", "destination", "status",
                              "account", "customer_rate", "carrier_pay"]
            differences = {}
            for field in compare_fields:
                v1 = loads[efj1].get(field)
                v2 = loads[efj2].get(field)
                if v1 != v2:
                    differences[field] = {efj1: v1, efj2: v2}

        return {"load_1": loads[efj1], "load_2": loads[efj2],
                "differences": differences, "diff_count": len(differences)}
    except Exception as e:
        log.exception("load_comparison failed")
        return {"error": str(e)}


def _exec_account_health_report(account: str, days: int = 30) -> dict:
    """Account-level health report."""
    try:
        days = min(days, 90)
        acct = account.strip()
        with db.get_cursor() as cur:
            cur.execute("""
                SELECT COUNT(*) as total,
                       COUNT(CASE WHEN LOWER(status) NOT IN ('delivered','invoiced','cancelled','ready_to_close','archived') THEN 1 END) as active,
                       COUNT(CASE WHEN LOWER(status) = 'delivered' THEN 1 END) as delivered,
                       COUNT(CASE WHEN LOWER(status) = 'invoiced' THEN 1 END) as invoiced,
                       ROUND(AVG(CASE WHEN customer_rate > 0 AND carrier_pay > 0
                           THEN (customer_rate - carrier_pay) / customer_rate * 100 END)::numeric, 1) as avg_margin_pct,
                       ROUND(SUM(CASE WHEN customer_rate > 0 AND carrier_pay > 0
                           THEN customer_rate - carrier_pay ELSE 0 END)::numeric, 2) as total_margin,
                       ROUND(SUM(customer_rate)::numeric, 2) as total_revenue,
                       COUNT(CASE WHEN customer_rate IS NULL OR carrier_pay IS NULL OR customer_rate = 0 THEN 1 END) as missing_rates
                FROM shipments
                WHERE LOWER(account) = LOWER(%s) AND (archived IS NULL OR archived = false)
                  AND created_at > NOW() - INTERVAL '%s days'
            """ % ("%s", days), (acct,))
            stats = _serialize(dict(cur.fetchone()))

            cur.execute("""
                SELECT carrier, COUNT(*) as loads FROM shipments
                WHERE LOWER(account) = LOWER(%s) AND (archived IS NULL OR archived = false)
                  AND created_at > NOW() - INTERVAL '%s days' AND carrier IS NOT NULL
                GROUP BY carrier ORDER BY loads DESC LIMIT 5
            """ % ("%s", days), (acct,))
            top_carriers = _rows_to_list(cur.fetchall())

            cur.execute("""
                SELECT s.efj, s.status, s.delivery_date FROM shipments s
                WHERE LOWER(s.account) = LOWER(%s)
                  AND s.status IN ('delivered', 'ready_to_close')
                  AND (s.archived IS NULL OR s.archived = false)
                  AND NOT EXISTS (SELECT 1 FROM load_documents d WHERE d.efj = s.efj AND d.doc_type = 'pod')
                ORDER BY s.delivery_date ASC LIMIT 10
            """, (acct,))
            missing_pod = _rows_to_list(cur.fetchall())

            cur.execute("""
                SELECT COUNT(*) as count, ROUND(AVG(age_days)::numeric, 0) as avg_age
                FROM unbilled_orders WHERE LOWER(customer) LIKE LOWER(%s) AND dismissed = false
            """, (f"%{acct}%",))
            unbilled = _serialize(dict(cur.fetchone()))

            cur.execute("""
                SELECT efj, carrier, customer_rate, carrier_pay,
                       ROUND((customer_rate - carrier_pay) / customer_rate * 100, 1) as margin_pct
                FROM shipments
                WHERE LOWER(account) = LOWER(%s) AND (archived IS NULL OR archived = false)
                  AND customer_rate > 0 AND carrier_pay > 0
                  AND (customer_rate - carrier_pay) / customer_rate * 100 < 10
                  AND created_at > NOW() - INTERVAL '%s days'
                ORDER BY margin_pct ASC LIMIT 5
            """ % ("%s", days), (acct,))
            low_margin = _rows_to_list(cur.fetchall())

        return {
            "account": acct, "period": f"Last {days} days",
            "stats": stats, "top_carriers": top_carriers,
            "missing_pod_loads": missing_pod, "missing_pod_count": len(missing_pod),
            "unbilled": unbilled, "low_margin_loads": low_margin,
        }
    except Exception as e:
        log.exception("account_health_report failed")
        return {"error": str(e)}


def _exec_transit_time_estimator(origin: str, destination: str) -> dict:
    """Estimate transit time from actual delivery data."""
    try:
        with db.get_cursor() as cur:
            o = origin.lower().strip()
            d = destination.lower().strip()
            cur.execute("""
                SELECT efj, carrier, pickup_date, delivery_date, origin, destination
                FROM shipments
                WHERE LOWER(origin) LIKE %s AND LOWER(destination) LIKE %s
                  AND pickup_date IS NOT NULL AND delivery_date IS NOT NULL
                  AND (archived IS NULL OR archived = false)
                ORDER BY delivery_date DESC LIMIT 30
            """, (f"%{o}%", f"%{d}%"))
            rows = cur.fetchall()

        if not rows:
            return {"error": f"No historical deliveries for {origin} -> {destination}"}

        transit_days = []
        samples = []
        for r in rows:
            r = dict(r)
            try:
                p = r["pickup_date"]
                dd = r["delivery_date"]
                if isinstance(p, str):
                    p = datetime.strptime(p[:10], "%Y-%m-%d").date()
                elif hasattr(p, 'date'):
                    p = p.date()
                if isinstance(dd, str):
                    dd = datetime.strptime(dd[:10], "%Y-%m-%d").date()
                elif hasattr(dd, 'date'):
                    dd = dd.date()
                days = (dd - p).days
                if 0 <= days <= 30:
                    transit_days.append(days)
                    samples.append({"efj": r["efj"], "carrier": r.get("carrier"), "transit_days": days})
            except Exception:
                continue

        if not transit_days:
            return {"error": "Found shipments but couldn't calc transit times (date issues)"}

        return {
            "lane": f"{origin} -> {destination}",
            "sample_size": len(transit_days),
            "avg_days": round(sum(transit_days) / len(transit_days), 1),
            "min_days": min(transit_days),
            "max_days": max(transit_days),
            "median_days": sorted(transit_days)[len(transit_days) // 2],
            "recent_samples": _serialize(samples[:5]),
        }
    except Exception as e:
        log.exception("transit_time_estimator failed")
        return {"error": str(e)}


# ---------------------------------------------------------------------------
# Tier 4 — "Outside the Box" Tools
# ---------------------------------------------------------------------------

def _exec_explain_like_a_customer(text: str, context: str = None) -> dict:
    """Pass glossary to Claude for jargon translation."""
    glossary = {
        "LFD": "Last Free Day -- the deadline to pick up your container before storage fees start",
        "demurrage": "daily charges from the shipping line when a container stays at port past the free period",
        "per diem": "daily charges for keeping a container/chassis past the allowed time",
        "detention": "charges for holding a container at your facility beyond the allowed free time",
        "chassis": "the wheeled frame a shipping container sits on for road transport",
        "chassis split": "extra charge when chassis must be picked up separately from the container",
        "prepull": "moving a container out of the port to a nearby yard before delivery day",
        "SSL": "Steamship Line -- the ocean carrier (Maersk, MSC, etc.)",
        "BOL": "Bill of Lading -- the shipping receipt/contract",
        "POD": "Proof of Delivery -- signed document confirming delivery",
        "drayage": "short-distance trucking between ports and warehouses",
        "FTL": "Full Truckload -- a dedicated truck for your freight only",
        "accessorials": "additional charges beyond the base rate (tolls, fuel, special handling)",
        "FSC": "Fuel Surcharge -- adjusts with diesel prices",
        "ETA": "Estimated Time of Arrival",
        "ERD": "Earliest Return Date -- first day to return an empty container",
        "free time": "days you can keep a container without extra charges",
        "overweight": "extra charge when container exceeds standard weight limits",
        "transload": "moving cargo from one container to another",
        "bonded": "cargo held under customs bond, hasn't cleared customs yet",
    }
    return {
        "original_text": text, "glossary": glossary, "context": context,
        "instruction": "Translate the original_text into plain, customer-friendly English using the glossary. Replace jargon. Keep it professional."
    }


def _exec_what_if_scenario(carrier_a: str, carrier_b: str, efj: str = None,
                            origin: str = None, destination: str = None) -> dict:
    """What-if: compare two carriers for a lane."""
    try:
        with db.get_cursor() as cur:
            if efj:
                efj_clean = _clean_efj(efj)
                cur.execute("""
                    SELECT origin, destination, customer_rate FROM shipments
                    WHERE efj = %s AND (archived IS NULL OR archived = false)
                """, (efj_clean,))
                row = cur.fetchone()
                if row:
                    row = dict(row)
                    origin = origin or row.get("origin", "")
                    destination = destination or row.get("destination", "")

            if not origin or not destination:
                return {"error": "Provide origin + destination, or an EFJ number"}

            results = {}
            for carrier in [carrier_a, carrier_b]:
                c_lower = carrier.lower().strip()
                cur.execute("""
                    SELECT carrier_name, tier_rank, dnu, can_hazmat, can_overweight,
                           can_reefer, can_bonded, service_feedback, trucks, markets
                    FROM carriers WHERE LOWER(carrier_name) LIKE %s LIMIT 1
                """, (f"%{c_lower}%",))
                c_info = cur.fetchone()
                c_info = _serialize(dict(c_info)) if c_info else {"carrier_name": carrier, "note": "Not in carrier DB"}

                o = origin.lower().strip()
                d = destination.lower().strip()
                cur.execute("""
                    SELECT dray_rate, fsc, total, all_in_total FROM lane_rates
                    WHERE LOWER(carrier_name) LIKE %s
                      AND (LOWER(port) LIKE %s OR LOWER(port) LIKE %s)
                      AND (LOWER(destination) LIKE %s OR LOWER(destination) LIKE %s)
                    ORDER BY created_at DESC NULLS LAST LIMIT 5
                """, (f"%{c_lower}%", f"%{o}%", f"{o}%", f"%{d}%", f"{d}%"))
                rates = _rows_to_list(cur.fetchall())

                cur.execute("""
                    SELECT COUNT(*) as total_loads,
                           COUNT(CASE WHEN LOWER(status) = 'delivered' THEN 1 END) as delivered,
                           ROUND(AVG(CASE WHEN customer_rate > 0 AND carrier_pay > 0
                               THEN (customer_rate - carrier_pay) / customer_rate * 100 END)::numeric, 1) as avg_margin
                    FROM shipments
                    WHERE LOWER(carrier) LIKE %s AND LOWER(origin) LIKE %s AND LOWER(destination) LIKE %s
                      AND (archived IS NULL OR archived = false)
                """, (f"%{c_lower}%", f"%{o}%", f"%{d}%"))
                perf = _serialize(dict(cur.fetchone()))

                results[carrier] = {
                    "carrier_info": c_info, "lane_rates": rates,
                    "performance": perf,
                    "compliance": "BLOCKED" if c_info.get("dnu") else "CLEAR",
                }

        return {"lane": f"{origin} -> {destination}",
                "carrier_a": results[carrier_a], "carrier_b": results[carrier_b]}
    except Exception as e:
        log.exception("what_if_scenario failed")
        return {"error": str(e)}


def _exec_daily_briefing(account: str = None, rep: str = None) -> dict:
    """Morning briefing: what you need to know today."""
    try:
        with db.get_cursor() as cur:
            conds = ["(archived IS NULL OR archived = false)"]
            params = []
            if account:
                conds.append("LOWER(account) = LOWER(%s)")
                params.append(account)
            if rep:
                conds.append("LOWER(rep) = LOWER(%s)")
                params.append(rep)
            base = " AND ".join(conds)

            today_str = datetime.now().strftime("%Y-%m-%d")

            # Arriving today
            cur.execute(f"""
                SELECT efj, carrier, origin, destination, container, status, account
                FROM shipments WHERE {base}
                  AND (delivery_date::text LIKE %s OR eta::text LIKE %s)
                  AND LOWER(status) NOT IN ('delivered','invoiced','cancelled','ready_to_close')
                ORDER BY eta LIMIT 15
            """, params + [today_str + "%", today_str + "%"])
            arriving = _rows_to_list(cur.fetchall())

            # LFD urgent
            cur.execute(f"""
                SELECT efj, container, lfd, origin, status, account FROM shipments
                WHERE {base} AND lfd IS NOT NULL AND lfd::text <= %s
                  AND LOWER(status) NOT IN ('delivered','invoiced','cancelled','ready_to_close','picked_up')
                ORDER BY lfd LIMIT 10
            """, params + [today_str])
            lfd_urgent = _rows_to_list(cur.fetchall())

            # Containers needing return
            cur.execute(f"""
                SELECT efj, container, carrier, delivery_date, account FROM shipments
                WHERE {base} AND LOWER(move_type) LIKE '%%import%%'
                  AND LOWER(status) IN ('delivered','ready_to_close')
                  AND return_date IS NULL AND delivery_date < NOW() - INTERVAL '4 days'
                ORDER BY delivery_date ASC LIMIT 10
            """, params)
            needs_return = _rows_to_list(cur.fetchall())

            # Missing POD on delivered
            cur.execute(f"""
                SELECT s.efj, s.carrier, s.account, s.delivery_date FROM shipments s
                WHERE (s.archived IS NULL OR s.archived = false)
                  {('AND LOWER(s.account) = LOWER(%s)' if account else '')}
                  {('AND LOWER(s.rep) = LOWER(%s)' if rep else '')}
                  AND s.status IN ('delivered','ready_to_close')
                  AND NOT EXISTS (SELECT 1 FROM load_documents d WHERE d.efj = s.efj AND d.doc_type = 'pod')
                ORDER BY s.delivery_date ASC LIMIT 10
            """, ([account] if account else []) + ([rep] if rep else []))
            missing_pod = _rows_to_list(cur.fetchall())

            # Low margin
            cur.execute(f"""
                SELECT efj, carrier, customer_rate, carrier_pay, account,
                       ROUND((customer_rate - carrier_pay) / customer_rate * 100, 1) as margin_pct
                FROM shipments WHERE {base}
                  AND customer_rate > 0 AND carrier_pay > 0
                  AND (customer_rate - carrier_pay) / customer_rate * 100 < 10
                  AND LOWER(status) NOT IN ('cancelled','invoiced')
                ORDER BY margin_pct ASC LIMIT 5
            """, params)
            low_margin = _rows_to_list(cur.fetchall())

            # Unreplied emails
            try:
                cur.execute("""
                    SELECT efj, sender, subject, received_at FROM email_threads
                    WHERE direction = 'inbound' AND received_at > NOW() - INTERVAL '24 hours'
                      AND replied = false ORDER BY received_at DESC LIMIT 10
                """)
                unreplied = _rows_to_list(cur.fetchall())
            except Exception:
                unreplied = []

            # Active count
            cur.execute(f"""
                SELECT COUNT(*) as active FROM shipments WHERE {base}
                  AND LOWER(status) NOT IN ('delivered','invoiced','cancelled','ready_to_close','archived')
            """, params)
            active = dict(cur.fetchone()).get("active", 0)

        return {
            "date": datetime.now().strftime("%A, %B %d, %Y"),
            "active_loads": active,
            "arriving_today": arriving, "arriving_count": len(arriving),
            "lfd_urgent": lfd_urgent, "lfd_urgent_count": len(lfd_urgent),
            "containers_needing_return": needs_return, "return_count": len(needs_return),
            "missing_pod": missing_pod, "missing_pod_count": len(missing_pod),
            "low_margin_alerts": low_margin,
            "unreplied_emails": unreplied,
        }
    except Exception as e:
        log.exception("daily_briefing failed")
        return {"error": str(e)}


def _exec_smart_dispatch_suggest(origin: str, destination: str,
                                  equipment_type: str = None,
                                  requirements: list = None) -> dict:
    """Ranked carrier suggestions: rates + compliance + capabilities."""
    try:
        with db.get_cursor() as cur:
            o = origin.lower().strip()
            d = destination.lower().strip()
            sql = """
                SELECT lr.carrier_name, lr.dray_rate, lr.fsc, lr.total, lr.all_in_total,
                       lr.equipment_type, lr.notes,
                       c.tier_rank, c.dnu, c.can_hazmat, c.can_overweight,
                       c.can_reefer, c.can_bonded, c.can_oog,
                       c.contact_phone, c.contact_email, c.trucks,
                       c.service_feedback, c.mc_number
                FROM lane_rates lr
                LEFT JOIN carriers c ON LOWER(c.carrier_name) = LOWER(lr.carrier_name)
                WHERE (LOWER(lr.port) LIKE %s OR LOWER(lr.port) LIKE %s)
                  AND (LOWER(lr.destination) LIKE %s OR LOWER(lr.destination) LIKE %s)
            """
            params = [f"%{o}%", f"{o}%", f"%{d}%", f"{d}%"]
            if equipment_type:
                sql += " AND LOWER(lr.equipment_type) = %s"
                params.append(equipment_type.lower().strip())
            sql += " ORDER BY lr.total ASC NULLS LAST, COALESCE(c.tier_rank, 99) ASC LIMIT 20"
            cur.execute(sql, params)
            rows = cur.fetchall()

        if not rows:
            return {"error": f"No carriers for {origin} -> {destination}"}

        suggestions = []
        for r in rows:
            r = _serialize(dict(r))
            if requirements:
                cap_map = {"hazmat": "can_hazmat", "overweight": "can_overweight",
                           "reefer": "can_reefer", "bonded": "can_bonded", "oog": "can_oog"}
                missing = [req for req in requirements if not r.get(cap_map.get(req, ""))]
                r["eligible"] = len(missing) == 0
                if missing:
                    r["missing_capabilities"] = missing
            else:
                r["eligible"] = not r.get("dnu", False)

            flags = []
            if r.get("dnu"):
                flags.append("DNU")
            if r.get("tier_rank"):
                flags.append(f"T{r['tier_rank']}")
            for cap, label in [("can_hazmat","HAZ"),("can_overweight","OWT"),("can_reefer","REEF"),("can_bonded","BND")]:
                if r.get(cap):
                    flags.append(label)
            r["flags"] = flags
            r["rate"] = r.get("total") or r.get("all_in_total") or r.get("dray_rate")
            suggestions.append(r)

        suggestions.sort(key=lambda x: (not x.get("eligible", True), x.get("rate") or 99999))

        return {
            "lane": f"{origin} -> {destination}",
            "equipment": equipment_type or "any",
            "requirements": requirements or [],
            "suggestions": suggestions,
            "count": len(suggestions),
            "eligible_count": sum(1 for s in suggestions if s.get("eligible")),
        }
    except Exception as e:
        log.exception("smart_dispatch_suggest failed")
        return {"error": str(e)}


TOOL_DISPATCH = {
    "query_lane_history": lambda args: _exec_query_lane_history(**args),
    "query_carrier_db": lambda args: _exec_query_carrier_db(**args),
    "check_efj_status": lambda args: _exec_check_efj_status(**args),
    "extract_rate_con": lambda args: _exec_extract_rate_con(**args),
    "draft_new_load": lambda args: _exec_draft_new_load(**args),
    "calculate_lane_iq_margin": lambda args: _exec_calculate_lane_iq_margin(**args),
    "carrier_compliance_guard": lambda args: _exec_carrier_compliance_guard(**args),
    "empty_return_scheduler": lambda args: _exec_empty_return_scheduler(**args),
    "check_document_status": lambda args: _exec_check_document_status(**args),
    "draft_carrier_email": lambda args: _exec_draft_carrier_email(**args),
    "weekly_margin_report": lambda args: _exec_weekly_margin_report(**args),
    "unit_converter": lambda args: _exec_unit_converter(**args),
    "shipment_summary": lambda args: _exec_shipment_summary(**args),
    "detention_calculator": lambda args: _exec_detention_calculator(**args),
    "accessorial_estimator": lambda args: _exec_accessorial_estimator(**args),
    "billing_checklist": lambda args: _exec_billing_checklist(**args),
    "load_comparison": lambda args: _exec_load_comparison(**args),
    "account_health_report": lambda args: _exec_account_health_report(**args),
    "transit_time_estimator": lambda args: _exec_transit_time_estimator(**args),
    "explain_like_a_customer": lambda args: _exec_explain_like_a_customer(**args),
    "what_if_scenario": lambda args: _exec_what_if_scenario(**args),
    "daily_briefing": lambda args: _exec_daily_briefing(**args),
    "smart_dispatch_suggest": lambda args: _exec_smart_dispatch_suggest(**args),
}


def _run_tool(name: str, input_args: dict) -> str:
    """Execute a tool and return JSON string result."""
    fn = TOOL_DISPATCH.get(name)
    if not fn:
        return json.dumps({"error": f"Unknown tool: {name}"})
    try:
        result = fn(input_args)
        return json.dumps(result, default=str)
    except Exception as e:
        log.exception("Tool %s execution error", name)
        return json.dumps({"error": str(e)})


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------

async def ask_ai(question: str, context: dict = None) -> dict:
    """
    Send a question to Claude with tool access to CSL database.
    Returns { answer: str, tool_calls: list, sources: list }
    """
    if not ANTHROPIC_API_KEY:
        return {
            "answer": "AI assistant is not configured. ANTHROPIC_API_KEY is missing.",
            "tool_calls": [],
            "sources": [],
        }

    messages = [{"role": "user", "content": question}]

    # Add context to system prompt if provided
    system = SYSTEM_PROMPT
    if context:
        ctx_parts = []
        if context.get("current_efj"):
            ctx_parts.append(f"The user is currently viewing load {context['current_efj']}.")
        if context.get("current_view"):
            ctx_parts.append(f"They are on the {context['current_view']} view.")
        if context.get("account"):
            ctx_parts.append(f"Current account filter: {context['account']}.")
        if ctx_parts:
            system += "\n\nCurrent context: " + " ".join(ctx_parts)

    tool_calls_log = []
    sources = []
    api_client = _get_client()

    try:
        for iteration in range(MAX_TOOL_ITERATIONS + 1):
            response = api_client.messages.create(
                model=MODEL,
                max_tokens=MAX_RESPONSE_TOKENS,
                system=system,
                tools=TOOLS,
                messages=messages,
            )

            # Check if we got tool use blocks
            has_tool_use = any(b.type == "tool_use" for b in response.content)

            if response.stop_reason == "end_turn" or not has_tool_use:
                # Extract text answer
                answer_parts = []
                for block in response.content:
                    if block.type == "text":
                        answer_parts.append(block.text)
                return {
                    "answer": "\n".join(answer_parts) if answer_parts else "I wasn't able to generate a response.",
                    "tool_calls": tool_calls_log,
                    "sources": sources,
                }

            # Process tool calls
            assistant_content = []
            tool_results = []

            for block in response.content:
                if block.type == "text":
                    assistant_content.append({"type": "text", "text": block.text})
                elif block.type == "tool_use":
                    assistant_content.append({
                        "type": "tool_use",
                        "id": block.id,
                        "name": block.name,
                        "input": block.input,
                    })

                    # Execute tool
                    log.info("AI tool call: %s(%s)", block.name, json.dumps(block.input, default=str)[:200])
                    result_str = _run_tool(block.name, block.input)

                    tool_calls_log.append({
                        "tool": block.name,
                        "input": block.input,
                        "iteration": iteration,
                    })

                    # Track sources
                    try:
                        result_data = json.loads(result_str)
                        count = result_data.get("count", 0)
                        if count:
                            sources.append(f"{block.name}: {count} results")
                        elif result_data.get("shipment"):
                            sources.append(f"{block.name}: {result_data['shipment'].get('efj', 'found')}")
                    except Exception:
                        pass

                    tool_results.append({
                        "type": "tool_result",
                        "tool_use_id": block.id,
                        "content": result_str,
                    })

            # Add assistant message and tool results to conversation
            messages.append({"role": "assistant", "content": assistant_content})
            messages.append({"role": "user", "content": tool_results})

        # Exhausted iterations
        return {
            "answer": "I reached the maximum number of tool calls. Please try a more specific question.",
            "tool_calls": tool_calls_log,
            "sources": sources,
        }

    except anthropic.RateLimitError:
        log.warning("Anthropic rate limit hit")
        return {
            "answer": "The AI service is temporarily rate limited. Please try again in a moment.",
            "tool_calls": [],
            "sources": [],
        }
    except anthropic.APIError as e:
        log.exception("Anthropic API error")
        return {
            "answer": f"AI service error: {e.message}",
            "tool_calls": [],
            "sources": [],
        }
    except Exception as e:
        log.exception("ask_ai unexpected error")
        return {
            "answer": f"An unexpected error occurred: {str(e)}",
            "tool_calls": [],
            "sources": [],
        }
