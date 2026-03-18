#!/usr/bin/env python3
"""Test JsonCargo Container Endpoint (GET /containers/{tracking_number}).

Calls the endpoint and prints the raw JSON response to verify
whether it returns an events/moves array or flat fields only.

Usage:
    python3 tests/test_container_endpoint.py <CONTAINER_NUM> <SHIPPING_LINE>
    python3 tests/test_container_endpoint.py MEDU9091004 MAERSK
    python3 tests/test_container_endpoint.py              # uses defaults
"""
import json
import os
import sys

import requests
from dotenv import load_dotenv

# Try loading .env from /root/csl-bot first, then project root
for env_path in ["/root/csl-bot/.env", os.path.join(os.path.dirname(__file__), "..", ".env")]:
    if os.path.exists(env_path):
        load_dotenv(env_path)
        break

JSONCARGO_API_KEY = os.environ.get("JSONCARGO_API_KEY", "")
JSONCARGO_BASE = "https://api.jsoncargo.com/api/v1"

DEFAULT_CONTAINER = "MEDU9091004"
DEFAULT_SHIPPING_LINE = "MAERSK"


def test_container_endpoint(container_num, shipping_line):
    if not JSONCARGO_API_KEY:
        print("ERROR: JSONCARGO_API_KEY not found in environment or .env file")
        sys.exit(1)

    url = f"{JSONCARGO_BASE}/containers/{container_num}/"
    headers = {"x-api-key": JSONCARGO_API_KEY}
    params = {"shipping_line": shipping_line}

    print(f"GET {url}")
    print(f"  shipping_line={shipping_line}")
    print(f"  x-api-key={JSONCARGO_API_KEY[:8]}...{JSONCARGO_API_KEY[-4:]}")
    print()

    resp = requests.get(url, headers=headers, params=params, timeout=30)
    print(f"HTTP {resp.status_code}")
    print()

    try:
        data = resp.json()
    except Exception as e:
        print(f"Failed to parse JSON: {e}")
        print(f"Raw response: {resp.text[:500]}")
        return

    # Pretty-print full response
    print("=== FULL RESPONSE ===")
    print(json.dumps(data, indent=2, default=str))
    print()

    # Analyze response structure
    print("=== STRUCTURE ANALYSIS ===")

    if "error" in data:
        print(f"ERROR response: {data['error']}")
        return

    inner = data.get("data", {})
    if not inner:
        print("No 'data' key in response")
        return

    # Check for events/moves arrays
    events = inner.get("events", None)
    moves = inner.get("moves", None)
    has_events = events is not None and len(events) > 0
    has_moves = moves is not None and len(moves) > 0

    print(f"  data.events present: {events is not None} (count: {len(events) if events else 0})")
    print(f"  data.moves present:  {moves is not None} (count: {len(moves) if moves else 0})")

    # Check for flat fields
    flat_fields = [
        "container_id", "container_type", "container_status",
        "shipping_line_name", "eta_final_destination",
        "shipped_from", "shipped_to", "last_location",
        "last_vessel_name", "current_vessel_name",
        "atd_origin", "customs_clearance", "bill_of_lading",
        "discharging_port", "loading_port", "last_updated",
    ]
    present_flat = {f: inner[f] for f in flat_fields if inner.get(f) is not None}
    print(f"  Flat fields present: {len(present_flat)} / {len(flat_fields)}")
    for field, value in present_flat.items():
        print(f"    {field}: {value}")

    print()
    if has_events or has_moves:
        print("RESULT: Response includes events/moves array — current parsing code is compatible.")
    elif present_flat:
        print("RESULT: Response is FLAT ONLY (no events/moves) — code updates needed!")
        print("  csl_bot.py has partial flat fallback, export_monitor.py does NOT.")
    else:
        print("RESULT: Unexpected response structure — manual review needed.")


if __name__ == "__main__":
    container = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_CONTAINER
    shipping_line = sys.argv[2] if len(sys.argv) > 2 else DEFAULT_SHIPPING_LINE
    test_container_endpoint(container, shipping_line)
