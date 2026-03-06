#!/usr/bin/env python3
"""
Macropoint Screenshotter — captures tracking page screenshots for active FTL loads.
Runs as a cron job: every 30 min during business hours (Mon-Fri 7am-7pm ET).

Saves screenshots to: /root/csl-bot/csl-doc-tracker/uploads/mp_screenshots/{efj}.png
Saves metadata to:    /root/csl-bot/csl-doc-tracker/uploads/mp_screenshots/{efj}.json

Crontab entry:
*/30 7-19 * * 1-5 cd /root/csl-bot && python3 macropoint_screenshotter.py >> /var/log/mp-screenshots.log 2>&1

Requires: playwright, playwright_stealth, gspread, google-auth
Uses the saved Macropoint session from mp_login_save.py
"""

import os, sys, json, time, traceback
from datetime import datetime, timezone

# Paths
SCREENSHOT_DIR = "/root/csl-bot/csl-doc-tracker/uploads/mp_screenshots"
SESSION_FILE = "/root/csl-bot/macropoint_session.json"
CREDENTIALS_FILE = os.getenv("GOOGLE_CREDENTIALS_FILE", "/root/csl-bot/credentials.json")

os.makedirs(SCREENSHOT_DIR, exist_ok=True)

def get_active_ftl_loads():
    """Get all active FTL loads with Macropoint URLs from Google Sheets."""
    import gspread
    from google.oauth2.service_account import Credentials

    SCOPES = ["https://www.googleapis.com/auth/spreadsheets.readonly"]
    creds = Credentials.from_service_account_file(CREDENTIALS_FILE, scopes=SCOPES)
    gc = gspread.authorize(creds)

    sheet_id = os.getenv("SHEET_ID", "19MB5HmmWwsVXY_nADCYYLJL-zWXYt8yWrfeRBSfB2S0")
    sh = gc.open_by_key(sheet_id)

    ftl_loads = []
    skip_tabs = {"Sheet 4", "DTCELNJW", "Account Rep", "Completed Eli", "Completed Radka"}

    for ws in sh.worksheets():
        if ws.title in skip_tabs:
            continue
        try:
            rows = ws.get_all_values()
            if len(rows) < 2:
                continue
            for row in rows[1:]:
                if len(row) < 13:
                    continue
                efj = (row[0] or "").strip()
                move_type = (row[1] or "").strip()
                status = (row[12] or "").strip().lower()
                container_or_load = (row[2] or "").strip()

                if not efj or not move_type:
                    continue
                if "ftl" not in move_type.lower():
                    continue
                if status in ("delivered", "completed", "pod received", "returned to port"):
                    continue

                # Check for hyperlink (Macropoint URL) in column C
                ftl_loads.append({
                    "efj": efj,
                    "status": status,
                    "tab": ws.title,
                })
        except Exception as e:
            print(f"  Warning: Error reading tab {ws.title}: {e}")
            continue

    return ftl_loads


def capture_screenshot(page, efj):
    """Navigate to Macropoint tracking page and capture the map screenshot."""
    try:
        # Navigate to Macropoint dashboard and search for the load
        page.goto("https://app.macropoint.com/", wait_until="networkidle", timeout=30000)
        time.sleep(2)

        # Try to search for the load by EFJ number
        search_input = page.query_selector('input[type="search"], input[placeholder*="Search"], input[placeholder*="search"]')
        if search_input:
            search_input.fill(efj.replace("EFJ ", "").replace("EFJ", "").strip())
            time.sleep(2)
            search_input.press("Enter")
            time.sleep(3)

        # Try to find and click on the load in results
        load_link = page.query_selector(f'text="{efj}"') or page.query_selector(f'td:has-text("{efj}")')
        if load_link:
            load_link.click()
            time.sleep(3)

        # Take screenshot of the map area
        map_elem = page.query_selector('.map-container, .leaflet-container, [class*="map"], #map')
        screenshot_path = os.path.join(SCREENSHOT_DIR, f"{efj}.png")

        if map_elem:
            map_elem.screenshot(path=screenshot_path)
        else:
            # Fallback: screenshot the main content area
            page.screenshot(path=screenshot_path, clip={"x": 0, "y": 0, "width": 900, "height": 400})

        # Save metadata
        meta = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "efj": efj,
        }
        meta_path = os.path.join(SCREENSHOT_DIR, f"{efj}.json")
        with open(meta_path, "w") as f:
            json.dump(meta, f)

        print(f"  Captured: {efj} -> {screenshot_path}")
        return True

    except Exception as e:
        print(f"  Failed to capture {efj}: {e}")
        return False


def main():
    print(f"\n{'='*60}")
    print(f"Macropoint Screenshotter — {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    print(f"{'='*60}")

    # Get active FTL loads
    print("\nFetching active FTL loads from Google Sheets...")
    try:
        loads = get_active_ftl_loads()
    except Exception as e:
        print(f"Error fetching loads: {e}")
        traceback.print_exc()
        return

    print(f"Found {len(loads)} active FTL loads")

    if not loads:
        print("No active FTL loads to screenshot.")
        return

    # Check for saved session
    if not os.path.exists(SESSION_FILE):
        print(f"Error: No Macropoint session file at {SESSION_FILE}")
        print("Run mp_login_save.py first to save the session.")
        return

    # Launch browser
    print("\nLaunching browser...")
    try:
        from playwright.sync_api import sync_playwright
        from playwright_stealth import stealth_sync
    except ImportError:
        print("Error: playwright/playwright_stealth not installed")
        return

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(
            storage_state=SESSION_FILE,
            viewport={"width": 1280, "height": 800},
        )
        page = context.new_page()
        stealth_sync(page)

        captured = 0
        failed = 0

        for load in loads:
            efj = load["efj"]
            print(f"\nProcessing: {efj} (tab: {load['tab']}, status: {load['status']})")
            if capture_screenshot(page, efj):
                captured += 1
            else:
                failed += 1
            time.sleep(2)  # Rate limit

        browser.close()

    print(f"\nDone! Captured: {captured}, Failed: {failed}")


if __name__ == "__main__":
    main()
