#!/usr/bin/env python3
"""
Macropoint Screenshotter v4 — captures tracking detail panel from public visibility URLs.

No authentication needed. Crops to the tracking details panel (progress tracker,
tripsheet, stop details, timestamps) which renders reliably in headless Chrome.

Saves screenshots to: /root/csl-bot/csl-doc-tracker/uploads/mp_screenshots/{efj}.png
Saves metadata to:    /root/csl-bot/csl-doc-tracker/uploads/mp_screenshots/{efj}.json

Crontab entry:
*/30 7-19 * * 1-5 cd /root/csl-bot && python3 macropoint_screenshotter.py >> /var/log/mp-screenshots.log 2>&1
"""

import os, json, time, traceback
from datetime import datetime, timezone

SCREENSHOT_DIR = "/root/csl-bot/csl-doc-tracker/uploads/mp_screenshots"
TRACKING_CACHE = "/root/csl-bot/ftl_tracking_cache.json"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def load_tracking_cache():
    if not os.path.exists(TRACKING_CACHE):
        print("Error: No tracking cache file")
        return {}
    with open(TRACKING_CACHE) as f:
        return json.load(f)


def capture_screenshot(page, efj, url):
    """Navigate to public visibility URL and screenshot the tracking detail panel."""
    screenshot_path = os.path.join(SCREENSHOT_DIR, f"{efj}.png")
    meta_path = os.path.join(SCREENSHOT_DIR, f"{efj}.json")

    try:
        page.goto(url, wait_until="networkidle", timeout=45000)
        time.sleep(5)

        # Crop to the bottom detail panel (progress tracker + tripsheet)
        # The map is top ~470px, details below
        page.screenshot(
            path=screenshot_path,
            clip={"x": 0, "y": 470, "width": 1280, "height": 430}
        )
        print(f"  Captured: {efj}")

        meta = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "efj": efj,
            "source": "public",
            "url": url,
        }
        with open(meta_path, "w") as f:
            json.dump(meta, f)
        return True

    except Exception as e:
        print(f"  Failed {efj}: {e}")
        traceback.print_exc()
        return False


def main():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"Macropoint Screenshotter v4 — {now_str}")
    print(f"{'='*60}")

    cache = load_tracking_cache()
    loads = {k: v for k, v in cache.items() if v.get("macropoint_url", "").startswith("http")}
    print(f"Found {len(loads)} loads with Macropoint URLs")

    if not loads:
        print("Nothing to screenshot.")
        return

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()

        captured = failed = 0

        for efj, data in loads.items():
            url = data["macropoint_url"]
            print(f"\nProcessing: {efj}")

            if capture_screenshot(page, efj, url):
                captured += 1
            else:
                failed += 1
            time.sleep(1)

        browser.close()

    print(f"\nDone! Captured: {captured}, Failed: {failed}")


if __name__ == "__main__":
    main()
