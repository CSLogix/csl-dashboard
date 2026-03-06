"""
Patch: Add /api/quotes/distance endpoint
Uses Google Maps Distance Matrix API to calculate mileage and transit time
between origin and destination for Rate IQ quote builder.
"""
import re

APP_PATH = "/root/csl-bot/csl-doc-tracker/app.py"

ENDPOINT_CODE = '''

# ── Distance API for Rate IQ ──────────────────────────────────────────
@app.get("/api/quotes/distance")
async def get_distance(origin: str = "", destination: str = ""):
    """Return driving distance and transit time between origin and destination."""
    import httpx, os, math
    if not origin or not destination:
        return JSONResponse({"error": "origin and destination required"}, 400)
    api_key = os.environ.get("GOOGLE_MAPS_API_KEY", "")
    if not api_key:
        return JSONResponse({"error": "Google Maps API key not configured"}, 500)
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
            return JSONResponse({"error": f"API error: {data.get('status')}"}, 502)
        element = data["rows"][0]["elements"][0]
        if element.get("status") != "OK":
            return JSONResponse({"error": f"Route error: {element.get('status')}"}, 404)
        # Distance in miles (API returns meters)
        meters = element["distance"]["value"]
        one_way = round(meters / 1609.344)
        # Duration in hours
        seconds = element["duration"]["value"]
        hours = seconds / 3600
        # Estimate transit time as business days (assume 500 mi/day for trucking)
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
        return JSONResponse({"error": str(e)}, 500)
'''

with open(APP_PATH, "r") as f:
    content = f.read()

if "/api/quotes/distance" in content:
    print("Distance endpoint already exists, skipping.")
else:
    # Check if httpx is available, if not we'll need to install it
    try:
        import httpx
        print("httpx already installed")
    except ImportError:
        import subprocess
        subprocess.run(["pip3", "install", "httpx", "--break-system-packages"], check=True)
        print("Installed httpx")

    # Add endpoint before the last line or at the end
    # Find a good insertion point - after other /api/quotes endpoints or at end
    if "/api/quotes" in content:
        # Insert after the last quotes-related endpoint block
        # Find the last occurrence of a quotes route
        pattern = r'(@app\.(get|post|delete)\("/api/quotes(?!/distance)[^"]*"\).*?)(\n\n)'
        matches = list(re.finditer(pattern, content, re.DOTALL))
        if matches:
            last_match = matches[-1]
            insert_pos = last_match.end()
            content = content[:insert_pos] + ENDPOINT_CODE + content[insert_pos:]
            print(f"Inserted distance endpoint after last /api/quotes route")
        else:
            content += ENDPOINT_CODE
            print("Appended distance endpoint at end of file")
    else:
        content += ENDPOINT_CODE
        print("Appended distance endpoint at end of file")

    with open(APP_PATH, "w") as f:
        f.write(content)
    print("Patch applied successfully!")

# Also add GOOGLE_MAPS_API_KEY to the systemd service environment
import subprocess
service_path = "/etc/systemd/system/csl-dashboard.service"
with open(service_path, "r") as f:
    svc = f.read()

if "GOOGLE_MAPS_API_KEY" not in svc:
    # Add to the Environment line
    svc = svc.replace(
        'Environment=',
        'Environment=GOOGLE_MAPS_API_KEY=AIzaSyAZskerzHFzlUyAzjtFsyniRYg539KzS-I ',
        1  # only first occurrence
    )
    with open(service_path, "w") as f:
        f.write(svc)
    subprocess.run(["systemctl", "daemon-reload"], check=True)
    print("Added GOOGLE_MAPS_API_KEY to systemd service")
else:
    print("GOOGLE_MAPS_API_KEY already in systemd service")
