#!/usr/bin/env python3
"""
patch_mp_driver_phone.py
Patches ftl_monitor.py to scrape the driver's tracking phone from
the authenticated Macropoint portal and write it to the tracking cache.

Flow:
1. After the normal public-page scrape, if we got a mp_load_id,
   try to open the shipment detail page in the authenticated portal.
2. Parse the "Tracking Phone" / phone number from the detail page.
3. Write it to ftl_tracking_cache.json under the "driver_phone" key.
4. The dashboard API already reads from the cache and the frontend
   already shows it — no further changes needed.

If the MP session is expired, it silently skips (no crash).

Run: python3 /tmp/patch_mp_driver_phone.py
"""
import re

FILE = "/root/csl-bot/ftl_monitor.py"

with open(FILE) as f:
    code = f.read()

changes = 0

# ══════════════════════════════════════════════════════════════════════════
# 1) Add MP cookies constant near other config
# ══════════════════════════════════════════════════════════════════════════
if "MP_COOKIES_FILE" in code:
    print("[1] MP_COOKIES_FILE already defined — skipping")
else:
    anchor = 'TRACKING_CACHE_FILE = "/root/csl-bot/ftl_tracking_cache.json"'
    if anchor not in code:
        print("ERROR: TRACKING_CACHE_FILE not found. Run patch_ftl_tracking_cache.py first.")
        exit(1)
    code = code.replace(
        anchor,
        anchor + '\nMP_COOKIES_FILE    = "/root/csl-bot/mp_cookies.json"'
               + '\nMP_PORTAL_URL      = "https://visibility.macropoint.com"',
    )
    changes += 1
    print("[1] Added MP_COOKIES_FILE and MP_PORTAL_URL constants")

# ══════════════════════════════════════════════════════════════════════════
# 2) Add function to scrape driver phone from authenticated portal
# ══════════════════════════════════════════════════════════════════════════
if "def scrape_driver_phone" in code:
    print("[2] scrape_driver_phone already defined — skipping")
else:
    # Insert before the scrape_macropoint function
    anchor = "def scrape_macropoint("
    idx = code.index(anchor)

    driver_phone_func = '''
def _load_mp_cookies():
    """Load Macropoint portal session cookies, or None if unavailable."""
    try:
        with open(MP_COOKIES_FILE) as f:
            cookies = json.load(f)
        # Fix expires: Playwright rejects large microsecond timestamps
        for c in cookies:
            exp = c.get("expires", -1)
            if isinstance(exp, (int, float)) and exp > 1e12:
                c["expires"] = int(exp / 1e6)
            elif exp == 0 or exp is None:
                c["expires"] = -1
        return cookies
    except (FileNotFoundError, json.JSONDecodeError):
        return None


def scrape_driver_phone(browser, mp_load_id: str, load_ref: str, mp_cookies: list = None) -> str | None:
    """
    Open the Macropoint portal shipment detail page and extract
    the driver's tracking phone number.
    Returns the phone string or None.
    """
    if not mp_cookies or not mp_load_id:
        return None

    page = browser.new_page()
    try:
        ctx = page.context
        ctx.add_cookies(mp_cookies)

        # Try the shipment search/detail page
        # Macropoint portal shipment URLs: /shipments or search by load number
        search_url = f"{MP_PORTAL_URL}/shipments?search={load_ref}"
        page.goto(search_url, wait_until="domcontentloaded", timeout=20_000)
        try:
            page.wait_for_load_state("networkidle", timeout=12_000)
        except PlaywrightTimeout:
            pass
        page.wait_for_timeout(2000)

        # Check if session expired (redirected to login)
        if "auth.gln.com" in page.url or "login" in page.url.lower():
            print("    MP portal session expired — skipping driver phone lookup")
            return None

        text = page.inner_text("body")

        # Try to find phone number patterns in the shipment detail
        # Macropoint shows tracking phone near "Phone" or "Tracking Phone" labels
        phone_patterns = [
            # "Tracking Phone\n(443) 555-1234" or "Phone\n+14435551234"
            r"(?:Tracking\s+)?Phone[:\s]*\n?\s*(\+?1?[\s.-]?\(?\d{3}\)?[\s.-]?\d{3}[\s.-]?\d{4})",
            # Generic US phone in the page
            r"(\(\d{3}\)\s*\d{3}[-.]?\d{4})",
            r"(\d{3}[-.]?\d{3}[-.]?\d{4})",
        ]

        # First try clicking into the shipment detail if we're on a list page
        try:
            # Click the first shipment row/link that matches our load
            link = page.locator(f'a:has-text("{load_ref}"), tr:has-text("{load_ref}")').first
            if link.is_visible(timeout=3000):
                link.click(timeout=5000)
                page.wait_for_load_state("networkidle", timeout=10_000)
                page.wait_for_timeout(2000)
                text = page.inner_text("body")
        except Exception:
            pass  # Already on detail page or couldn't click — use current text

        # Extract phone numbers from the page
        found_phones = []
        for pattern in phone_patterns:
            matches = re.findall(pattern, text, re.I)
            found_phones.extend(matches)

        if not found_phones:
            return None

        # Filter out the Evans dispatch phone (we don't want that)
        dispatch_digits = "4437614954"
        for phone in found_phones:
            digits = re.sub(r"\D", "", phone)
            if digits.startswith("1") and len(digits) == 11:
                digits = digits[1:]
            if digits != dispatch_digits and len(digits) == 10:
                # Format nicely
                formatted = f"({digits[:3]}) {digits[3:6]}-{digits[6:]}"
                print(f"    Driver phone found: {formatted}")
                return formatted

        return None

    except PlaywrightTimeout:
        print("    MP portal timeout — skipping driver phone")
        return None
    except Exception as exc:
        print(f"    MP portal error: {exc}")
        return None
    finally:
        page.close()


'''
    code = code[:idx] + driver_phone_func + code[idx:]
    changes += 1
    print("[2] Added _load_mp_cookies and scrape_driver_phone functions")

# ══════════════════════════════════════════════════════════════════════════
# 3) Load MP cookies once at the start of each poll cycle
# ══════════════════════════════════════════════════════════════════════════
if "mp_cookies = _load_mp_cookies()" in code:
    print("[3] MP cookies load already present — skipping")
else:
    anchor = "    tracking_cache = load_tracking_cache()"
    if anchor not in code:
        print("ERROR: tracking_cache load not found. Run patch_ftl_tracking_cache.py first.")
        exit(1)
    code = code.replace(
        anchor,
        anchor + "\n    mp_cookies = _load_mp_cookies()",
    )
    changes += 1
    print("[3] Added mp_cookies = _load_mp_cookies() at poll start")

# ══════════════════════════════════════════════════════════════════════════
# 4) After scraping each load, try to get driver phone and add to cache
# ══════════════════════════════════════════════════════════════════════════
if "scrape_driver_phone(browser" in code:
    print("[4] scrape_driver_phone call already present — skipping")
else:
    # Find the update_tracking_cache call and add driver phone scraping before it
    anchor = '                update_tracking_cache(\n                    row["efj"], row["load_num"], status,'
    if anchor not in code:
        # Try alternate format
        anchor = 'update_tracking_cache(\n                    row["efj"], row["load_num"], status,'
    if anchor not in code:
        print("ERROR: Cannot find update_tracking_cache call")
        exit(1)

    idx = code.index(anchor)

    driver_phone_call = '''                # Try to get driver's tracking phone from authenticated MP portal
                driver_phone = None
                if mp_load_id and mp_cookies:
                    driver_phone = scrape_driver_phone(
                        browser, mp_load_id, row["load_num"], mp_cookies
                    )

'''
    code = code[:idx] + driver_phone_call + code[idx:]
    changes += 1
    print("[4] Added scrape_driver_phone call before update_tracking_cache")

# ══════════════════════════════════════════════════════════════════════════
# 5) Add driver_phone to update_tracking_cache signature and data
# ══════════════════════════════════════════════════════════════════════════
# Update the function signature to accept driver_phone
old_sig = 'def update_tracking_cache(efj: str, load_num: str, status, mp_load_id,\n                          cant_make_it, stop_times: dict, url: str, cache: dict):'
new_sig = 'def update_tracking_cache(efj: str, load_num: str, status, mp_load_id,\n                          cant_make_it, stop_times: dict, url: str, cache: dict,\n                          driver_phone: str = None):'

if new_sig in code:
    print("[5a] update_tracking_cache signature already updated — skipping")
elif old_sig in code:
    code = code.replace(old_sig, new_sig)
    changes += 1
    print("[5a] Updated update_tracking_cache signature with driver_phone param")
else:
    print("WARNING: Could not find update_tracking_cache signature to update")

# Add driver_phone to the cache dict
old_cache_dict = '        "macropoint_url": url,\n        "last_scraped": now,\n    }'
new_cache_dict = '        "macropoint_url": url,\n        "last_scraped": now,\n        "driver_phone": driver_phone or cache.get(efj, {}).get("driver_phone"),\n    }'

if 'driver_phone' in code.split('"macropoint_url": url')[1].split('}')[0] if '"macropoint_url": url' in code else '':
    print("[5b] driver_phone already in cache dict — skipping")
elif old_cache_dict in code:
    code = code.replace(old_cache_dict, new_cache_dict)
    changes += 1
    print("[5b] Added driver_phone to tracking cache dict")
else:
    print("WARNING: Could not find cache dict to add driver_phone")

# Update the call site to pass driver_phone
old_call = '''                update_tracking_cache(
                    row["efj"], row["load_num"], status,
                    mp_load_id, cant_make_it, stop_times,
                    row["url"], tracking_cache,
                )'''
new_call = '''                update_tracking_cache(
                    row["efj"], row["load_num"], status,
                    mp_load_id, cant_make_it, stop_times,
                    row["url"], tracking_cache,
                    driver_phone=driver_phone,
                )'''

if 'driver_phone=driver_phone' in code:
    print("[5c] update_tracking_cache call already passes driver_phone — skipping")
elif old_call in code:
    code = code.replace(old_call, new_call)
    changes += 1
    print("[5c] Updated update_tracking_cache call to pass driver_phone")
else:
    print("WARNING: Could not find update_tracking_cache call to update")


with open(FILE, "w") as f:
    f.write(code)

print(f"\n✅ ftl_monitor.py patched ({changes} changes)")
print("   Driver phone will be scraped from MP portal when session is active")
print("   Restart: systemctl restart csl-ftl")
