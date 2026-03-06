#!/usr/bin/env python3
"""
Macropoint Screenshotter v3 — captures the GPS ping map from the authenticated portal.

Uses mp_cookies.json for portal login and searches by load ID to get the map with
breadcrumb pings (not the public visibility "Track Now" page).

Falls back to public visibility URL if cookies are expired or unavailable.

Saves screenshots to: /root/csl-bot/csl-doc-tracker/uploads/mp_screenshots/{efj}.png
Saves metadata to:    /root/csl-bot/csl-doc-tracker/uploads/mp_screenshots/{efj}.json

Crontab entry:
*/30 7-19 * * 1-5 cd /root/csl-bot && python3 macropoint_screenshotter.py >> /var/log/mp-screenshots.log 2>&1
"""

import os, json, time, traceback
from datetime import datetime, timezone

SCREENSHOT_DIR = "/root/csl-bot/csl-doc-tracker/uploads/mp_screenshots"
TRACKING_CACHE = "/root/csl-bot/ftl_tracking_cache.json"
MP_COOKIES_FILE = "/root/csl-bot/mp_cookies.json"
MP_PORTAL_URL = "https://visibility.macropoint.com"

os.makedirs(SCREENSHOT_DIR, exist_ok=True)


def load_tracking_cache():
    if not os.path.exists(TRACKING_CACHE):
        print("Error: No tracking cache file")
        return {}
    with open(TRACKING_CACHE) as f:
        return json.load(f)


def load_mp_cookies():
    try:
        with open(MP_COOKIES_FILE) as f:
            cookies = json.load(f)
        for c in cookies:
            exp = c.get("expires", -1)
            if isinstance(exp, (int, float)) and exp > 1e12:
                c["expires"] = int(exp / 1e6)
            elif exp == 0 or exp is None:
                c["expires"] = -1
        return cookies
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def capture_portal_screenshot(page, efj, load_id, mp_cookies):
    """Screenshot the authenticated portal map page with GPS pings."""
    screenshot_path = os.path.join(SCREENSHOT_DIR, f"{efj}.png")
    meta_path = os.path.join(SCREENSHOT_DIR, f"{efj}.json")

    try:
        ctx = page.context
        ctx.add_cookies(mp_cookies)

        search_url = f"{MP_PORTAL_URL}/shipments?search={load_id}"
        page.goto(search_url, wait_until="domcontentloaded", timeout=25000)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        time.sleep(2)

        # Check if session expired
        if "auth.gln.com" in page.url or "login" in page.url.lower():
            print(f"  Session expired — falling back to public URL for {efj}")
            return "expired"

        # Try clicking into the shipment detail to get the map view
        try:
            selectors = [
                f'a:has-text("{load_id}")',
                f'tr:has-text("{load_id}")',
                f'div:has-text("{load_id}")',
            ]
            for sel in selectors:
                try:
                    row = page.locator(sel).first
                    if row.is_visible(timeout=2000):
                        row.click(timeout=5000)
                        try:
                            page.wait_for_load_state("networkidle", timeout=12000)
                        except Exception:
                            pass
                        time.sleep(3)
                        break
                except Exception:
                    continue
        except Exception:
            pass

        # Wait for map tiles to load
        map_selectors = [
            ".leaflet-tile-loaded",
            ".mapboxgl-map",
            "canvas",
            "[class*='map']",
            ".gm-style",
        ]
        map_found = False
        for sel in map_selectors:
            try:
                page.wait_for_selector(sel, timeout=5000)
                map_found = True
                time.sleep(2)  # Extra time for map tiles
                break
            except Exception:
                continue

        if not map_found:
            time.sleep(3)  # Generic wait if no map selector found

        page.screenshot(path=screenshot_path, full_page=False)
        print(f"  Captured (portal): {efj}")

        meta = {
            "captured_at": datetime.now(timezone.utc).isoformat(),
            "efj": efj,
            "source": "portal",
            "load_id": load_id,
        }
        with open(meta_path, "w") as f:
            json.dump(meta, f)
        return "ok"

    except Exception as e:
        print(f"  Portal failed {efj}: {e}")
        return "error"


def capture_public_screenshot(page, efj, url):
    """Fallback: screenshot the public visibility URL."""
    screenshot_path = os.path.join(SCREENSHOT_DIR, f"{efj}.png")
    meta_path = os.path.join(SCREENSHOT_DIR, f"{efj}.json")

    try:
        page.goto(url, wait_until="networkidle", timeout=30000)
        time.sleep(4)
        page.screenshot(path=screenshot_path, full_page=False)
        print(f"  Captured (public): {efj}")

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
        return False


def main():
    now_str = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    print(f"\n{'='*60}")
    print(f"Macropoint Screenshotter v3 — {now_str}")
    print(f"{'='*60}")

    cache = load_tracking_cache()
    loads = {k: v for k, v in cache.items() if v.get("macropoint_url", "").startswith("http")}
    print(f"Found {len(loads)} loads with Macropoint URLs")

    if not loads:
        print("Nothing to screenshot.")
        return

    mp_cookies = load_mp_cookies()
    have_cookies = mp_cookies is not None
    cookie_status = "available" if have_cookies else "NOT FOUND — using public URLs only"
    print(f"Portal cookies: {cookie_status}")

    from playwright.sync_api import sync_playwright

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        context = browser.new_context(viewport={"width": 1280, "height": 900})
        page = context.new_page()

        captured = failed = 0
        portal_expired = False

        for efj, data in loads.items():
            url = data["macropoint_url"]
            load_id = data.get("mp_load_id") or data.get("load_id") or efj
            print(f"\nProcessing: {efj} (load_id={load_id})")

            success = False

            # Try authenticated portal first (has GPS ping map)
            if have_cookies and not portal_expired:
                result = capture_portal_screenshot(page, efj, load_id, mp_cookies)
                if result == "ok":
                    success = True
                elif result == "expired":
                    portal_expired = True
                    print("  Portal session expired — switching to public URLs for remaining loads")

            # Fallback to public visibility URL
            if not success:
                success = capture_public_screenshot(page, efj, url)

            if success:
                captured += 1
            else:
                failed += 1
            time.sleep(1)

        browser.close()

    print(f"\nDone! Captured: {captured}, Failed: {failed}")


if __name__ == "__main__":
    main()
