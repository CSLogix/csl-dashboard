"""
Patch v2: Add /api/quotes/distance to quote_routes.py (before /{quote_id})
and remove the duplicate from app.py.
"""
import re

# ── 1. Add to quote_routes.py before the /{quote_id} route ──
ROUTES_PATH = "/root/csl-bot/csl-doc-tracker/quote_routes.py"

DISTANCE_ENDPOINT = '''
# ── Distance / Mileage Calculator ──

@router.get("/distance")
async def get_distance(origin: str = "", destination: str = ""):
    """Return driving distance and transit time between origin and destination."""
    import httpx, os
    if not origin or not destination:
        return JSONResponse({"error": "origin and destination required"}, status_code=400)
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return JSONResponse({"error": "Google Maps API key not configured"}, status_code=500)
    try:
        url = "https://maps.googleapis.com/maps/api/distancematrix/json"
        params = {
            "origins": origin,
            "destinations": destination,
            "units": "imperial",
            "key": api_key,
        }
        async with httpx.AsyncClient(timeout=10) as client:
            resp = await client.get(url, params=params)
            data = resp.json()
        if data.get("status") != "OK":
            return JSONResponse({"error": f"API error: {data.get('status')}"}, status_code=502)
        element = data["rows"][0]["elements"][0]
        if element.get("status") != "OK":
            return JSONResponse({"error": f"Route error: {element.get('status')}"}, status_code=404)
        meters = element["distance"]["value"]
        one_way = round(meters / 1609.344)
        seconds = element["duration"]["value"]
        hours = seconds / 3600
        if one_way <= 250:
            transit = "1 day"
        elif one_way <= 600:
            transit = "1-2 days"
        elif one_way <= 1200:
            transit = "2-3 days"
        elif one_way <= 2000:
            transit = "3-4 days"
        else:
            transit = "4-5 days"
        return {
            "one_way_miles": one_way,
            "round_trip_miles": one_way * 2,
            "transit_time": transit,
            "duration_hours": round(hours, 1),
        }
    except Exception as e:
        return JSONResponse({"error": str(e)}, status_code=500)


'''

with open(ROUTES_PATH, "r") as f:
    content = f.read()

if "/distance" in content:
    print("Distance route already in quote_routes.py, skipping.")
else:
    # Insert before # ── CRUD ── section
    marker = "# ── CRUD ──"
    if marker in content:
        content = content.replace(marker, DISTANCE_ENDPOINT + marker)
        with open(ROUTES_PATH, "w") as f:
            f.write(content)
        print("Added distance endpoint to quote_routes.py before CRUD section")
    else:
        print("ERROR: Could not find CRUD marker in quote_routes.py")

# ── 2. Remove duplicate from app.py ──
APP_PATH = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP_PATH, "r") as f:
    app_content = f.read()

# Remove the distance endpoint block we added in v1
pattern = r'\n# ── Distance API for Rate IQ ──.*?return JSONResponse\(\{"error": str\(e\)\}, 500\)\n'
cleaned = re.sub(pattern, '\n', app_content, flags=re.DOTALL)
if cleaned != app_content:
    with open(APP_PATH, "w") as f:
        f.write(cleaned)
    print("Removed duplicate distance endpoint from app.py")
else:
    print("No duplicate found in app.py (already clean)")

print("Done!")
