#!/usr/bin/env python3
"""
Macropoint Screenshotter v5 — captures tracking detail panel from public visibility URLs.

No authentication needed. Crops to the tracking details panel (progress tracker,
tripsheet, stop details, timestamps) which renders reliably in headless Chrome.

Saves screenshots using BOTH the cache key AND the load_num (EFJ number) so the
dashboard API can find them regardless of how the tracking cache is keyed.

Saves to: /root/csl-bot/csl-doc-tracker/uploads/mp_screenshots/{key}.png
Metadata: /root/csl-bot/csl-doc-tracker/uploads/mp_screenshots/{key}.json

Crontab entry:
*/30 7-19 * * 1-5 cd /root/csl-bot && python3 macropoint_screenshotter.py >> /var/log/mp-screenshots.log 2>&1
"""

import os, json, time, shutil, traceback
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


def capture_screenshot(page, key, load_num, url):
    """Navigate to public visibility URL and screenshot the tracking detail panel.

    Saves by cache key, then copies to load_num filename if different (so both
    container-number and EFJ-number lookups work).
    """
    screenshot_path = os.path.join(SCREENSHOT_DIR, f"{key}.png")
    meta_path = os.path.join(SCREENSHOT_DIR, f"{key}.json")

    try:
        page.goto(url, wait_until="networkidle", timeout=45000)
        time.sleep(5)

        # Crop to the bottom detail panel (progress tracker + tripsheet)
        # The map is top ~470px, details below
        page.screenshot(
            path=screenshot_path,
            clip={"x": 0, "y": 470, "width": 1280, "height": 430}
        )

        meta = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "key": key,
            "load_num": load_num,
            "source": "public",
            "url": url,
        }
        with open(meta_path, "w") as f:
            json.dump(meta, f)

        # Also save under load_num if it differs from key
        # e.g. key=CSNU8670992 → also save as EFJ107093.png
        # e.g. key=107230 → also save as EFJ107230.png (adds prefix)
        aliases = set()
        if load_num and load_num != key:
            # Sanitize: replace chars that break filenames
            safe_ln = load_num.replace("/", "_").replace("\\", "_")
            aliases.add(safe_ln)
        # Handle bare numbers: if key is "107230", also save as "EFJ107230"
        if key.isdigit():
            aliases.add(f"EFJ{key}")

        for alias in aliases:
            alias_png = os.path.join(SCREENSHOT_DIR, f"{alias}.png")
            alias_json = os.path.join(SCREENSHOT_DIR, f"{alias}.json")
            shutil.copy2(screenshot_path, alias_png)
            shutil.copy2(meta_path, alias_json)

        names = [key] + list(aliases)
        print(f"  Captured: {' + '.join(names)}")
        return True

    except Exception as e:
        print(f"  Failed {key}: {e}")
        traceback.print_exc()
        return False


def main():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"Macropoint Screenshotter v5 — {now_str}")
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

        for key, data in loads.items():
            url = data["macropoint_url"]
            load_num = data.get("load_num", "")
            print(f"\nProcessing: {key} (load_num={load_num})")

            if capture_screenshot(page, key, load_num, url):
                captured += 1
            else:
                failed += 1
            time.sleep(1)

        browser.close()

    print(f"\nDone! Captured: {captured}, Failed: {failed}")


if __name__ == "__main__":
    main()
