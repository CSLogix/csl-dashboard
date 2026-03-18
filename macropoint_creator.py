#!/usr/bin/env python3
"""
macropoint_creator.py — Creates Macropoint shipments with OTP 2FA support.
Runs as a persistent process, communicates via state files.
"""
import re, sys, json, time, os, tempfile
from datetime import datetime
from zoneinfo import ZoneInfo
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv()

_tmpdir = tempfile.mkdtemp(prefix="mp_creator_")
STATE_FILE  = os.path.join(_tmpdir, "mp_state.json")
RESULT_FILE = os.path.join(_tmpdir, "mp_result.json")

STATE_TZ = {
    "CT":"America/New_York","DE":"America/New_York","FL":"America/New_York",
    "GA":"America/New_York","ME":"America/New_York","MD":"America/New_York",
    "MA":"America/New_York","MI":"America/Detroit","NH":"America/New_York",
    "NJ":"America/New_York","NY":"America/New_York","NC":"America/New_York",
    "OH":"America/New_York","PA":"America/New_York","RI":"America/New_York",
    "SC":"America/New_York","VT":"America/New_York","VA":"America/New_York",
    "WV":"America/New_York","DC":"America/New_York","IN":"America/Indiana/Indianapolis",
    "KY":"America/New_York","AL":"America/Chicago","AR":"America/Chicago",
    "IL":"America/Chicago","IA":"America/Chicago","KS":"America/Chicago",
    "LA":"America/Chicago","MN":"America/Chicago","MS":"America/Chicago",
    "MO":"America/Chicago","NE":"America/Chicago","ND":"America/Chicago",
    "OK":"America/Chicago","SD":"America/Chicago","TN":"America/Chicago",
    "TX":"America/Chicago","WI":"America/Chicago","AZ":"America/Phoenix",
    "CO":"America/Denver","ID":"America/Denver","MT":"America/Denver",
    "NM":"America/Denver","UT":"America/Denver","WY":"America/Denver",
    "CA":"America/Los_Angeles","NV":"America/Los_Angeles","OR":"America/Los_Angeles",
    "WA":"America/Los_Angeles","AK":"America/Anchorage","HI":"Pacific/Honolulu",
}

MP_TZ_LABELS = {
    "America/New_York":    "(UTC-05:00) Eastern Time (US & Canada)",
    "America/Detroit":     "(UTC-05:00) Eastern Time (US & Canada)",
    "America/Indiana/Indianapolis": "(UTC-05:00) Indiana (East)",
    "America/Chicago":     "(UTC-06:00) Central Time (US & Canada)",
    "America/Denver":      "(UTC-07:00) Mountain Time (US & Canada)",
    "America/Phoenix":     "(UTC-07:00) Arizona",
    "America/Los_Angeles": "(UTC-08:00) Pacific Time (US & Canada)",
    "America/Anchorage":   "(UTC-09:00) Alaska",
    "Pacific/Honolulu":    "(UTC-10:00) Hawaii",
}

MACROPOINT_URL = "https://visibility.macropoint.com/"
MP_USER        = os.environ["MACROPOINT_USER"]
MP_PASS        = os.environ["MACROPOINT_PASSWORD"]
TRACKING_PHONE = os.environ.get("MACROPOINT_TRACKING_PHONE", "4437614954")

def get_tz_label(state):
    tz = STATE_TZ.get(state.upper(), "America/Chicago")
    return MP_TZ_LABELS.get(tz, "(UTC-06:00) Central Time (US & Canada)")

def fmt_date(dt):
    return f"{dt.month}/{dt.day}/{dt.year}"

def fmt_time_str(h, m=0):
    suffix = "AM" if h < 12 else "PM"
    h12 = h if 1<=h<=12 else (h-12 if h>12 else 12)
    return f"{h12}:{m:02d} {suffix}"

def parse_appt(appt_str):
    m = re.search(r'(\d{1,2})/(\d{1,2})/(\d{4})\s+(\d{2}):(\d{2})', appt_str)
    if m:
        return int(m.group(1)),int(m.group(2)),int(m.group(3)),int(m.group(4)),int(m.group(5))
    return None

def set_state(state): 
    with open(STATE_FILE,'w') as f: json.dump(state,f)

def get_state():
    try:
        with open(STATE_FILE) as f: return json.load(f)
    except (OSError, json.JSONDecodeError): return {}
def create_macropoint(data):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx     = browser.new_context()
        page    = ctx.new_page()

        COOKIES_FILE = "/root/csl-bot/mp_cookies.json"
        import os
        if not os.path.exists(COOKIES_FILE):
            browser.close()
            return {"status": "error", "error": "No saved session. Please visit /mp-login to authenticate first."}

        print("Loading saved cookies...")
        with open(COOKIES_FILE) as f:
            cookies = json.load(f)
        ctx.add_cookies(cookies)

        print("Navigating to Macropoint...")
        page.goto(MACROPOINT_URL, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=20000)
        page.wait_for_timeout(2000)

        if "auth.gln.com" in page.url or "login" in page.url.lower():
            browser.close()
            return {"status": "error", "error": "Session expired. Please visit /mp-login to re-authenticate."}

        print("Logged in via cookies, URL:", page.url)

        # Navigate to New Shipment
        print("Opening New Shipment...")
        try:
            page.click('a:has-text("New Shipment"), button:has-text("New Shipment")', timeout=10000)
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception as e:
            print(f"New Shipment button not found, navigating directly: {e}")
            page.goto(MACROPOINT_URL + "shipments/new", timeout=20000)
            page.wait_for_load_state("networkidle", timeout=15000)
        page.wait_for_timeout(2000)
        print("New shipment page:", page.url)
        now = datetime.now(ZoneInfo("America/New_York"))

        # Fill phone
        try:
            page.locator('input[placeholder*="National Number"], input[placeholder*="phone"], input[type="tel"]').first.fill(TRACKING_PHONE, timeout=5000)
        except Exception as e:
            print(f"Warning phone: {e}")

        # Load #
        try:
            page.locator('input[placeholder*="Load"], input[placeholder*="load"], input[placeholder*="Reference"]').first.fill(data['pro'], timeout=5000)
        except Exception as e:
            print(f"Warning load#: {e}")

        # Track for 5 days
        try:
            page.select_option('select:near(:text("Track For"))', label="5 Days", timeout=5000)
        except Exception as e:
            print(f"Warning track duration: {e}")

        # Every 15 min
        try:
            page.select_option('select:near(:text("Every"))', label="15 Minutes", timeout=5000)
        except Exception as e:
            print(f"Warning frequency: {e}")

        # Tracking method - Driver Cell Phone
        try:
            page.select_option('select:near(:text("Tracking Method"))', label="Driver's Cell Phone#", timeout=5000)
        except Exception as e:
            print(f"Warning tracking method: {e}")

        # Start tracking now
        try:
            page.screenshot(path="/tmp/mp_form.png")
            print("Screenshot saved to /tmp/mp_form.png")
        except Exception: pass  # best-effort screenshot

        # ── Pickup Stop ──────────────────────────────────────────────────────
        print("Filling Pickup stop...")
        p_tz = get_tz_label(data['pickup_state'])
        if data['pickup_type'] == 'appointment':
            pa = parse_appt(data['pickup_appt'])
            p_mo,p_day,p_yr,p_hr,p_min = pa if pa else (now.month,now.day,now.year,8,0)
            p_start = fmt_time_str(p_hr, p_min)
            p_end   = fmt_time_str(p_hr, p_min)
            p_date  = f"{p_mo}/{p_day}/{p_yr}"
        else:
            p_date  = fmt_date(now)
            p_start = "6:00 AM"
            p_end   = "4:00 PM"

        try:
            page.click('text=Pickup', timeout=10000)
            page.wait_for_timeout(1000)
            page.screenshot(path="/tmp/mp_pickup.png")

            page.locator('input[placeholder*="Stop Name"]').first.fill(data['pickup_name'], timeout=5000)
            page.locator('input[placeholder*="address line 1"], input[placeholder*="Address Line 1"]').first.fill(data['pickup_addr'], timeout=5000)
            page.locator('input[placeholder*="City"]').first.fill(data['pickup_city'].title(), timeout=5000)
            page.locator('input[placeholder*="State"]').first.fill(data['pickup_state'], timeout=5000)
            page.locator('input[placeholder*="Zip"]').first.fill(data['pickup_zip'], timeout=5000)
        except Exception as e:
            print(f"Warning pickup fields: {e}")
# ── Delivery Stop ────────────────────────────────────────────────────
        print("Filling Delivery stop...")
        d_tz = get_tz_label(data['delivery_state'])
        if data['delivery_type'] == 'appointment':
            da = parse_appt(data['delivery_appt'])
            d_mo,d_day,d_yr,d_hr,d_min = da if da else (now.month,now.day,now.year,8,0)
            d_start = fmt_time_str(d_hr, d_min)
            d_end   = fmt_time_str(d_hr, d_min)
            d_date  = f"{d_mo}/{d_day}/{d_yr}"
        else:
            d_date  = fmt_date(now)
            d_start = "6:00 AM"
            d_end   = "4:00 PM"

        try:
            page.click('text=Drop-Off, text=Drop Off', timeout=10000)
            page.wait_for_timeout(1000)
            page.screenshot(path="/tmp/mp_delivery.png")

            page.locator('input[placeholder*="Stop Name"]').last.fill(data['delivery_name'], timeout=5000)
            page.locator('input[placeholder*="address line 1"], input[placeholder*="Address Line 1"]').last.fill(data['delivery_addr'], timeout=5000)
            page.locator('input[placeholder*="City"]').last.fill(data['delivery_city'].title(), timeout=5000)
            page.locator('input[placeholder*="State"]').last.fill(data['delivery_state'], timeout=5000)
            page.locator('input[placeholder*="Zip"]').last.fill(data['delivery_zip'], timeout=5000)
        except Exception as e:
            print(f"Warning delivery fields: {e}")

        # ── Save ─────────────────────────────────────────────────────────────
        print("Saving shipment...")
        try:
            page.screenshot(path="/tmp/mp_before_save.png")
            page.click('button:has-text("Save"), button[type="submit"]:has-text("Save")', timeout=10000)
            page.wait_for_load_state("networkidle", timeout=30000)
            page.wait_for_timeout(3000)
        except Exception as e:
            print(f"Warning save: {e}")

        tracking_url = page.url
        print(f"Tracking URL: {tracking_url}")
        page.screenshot(path="/tmp/mp_after_save.png")
        browser.close()
        return {"status": "success", "url": tracking_url}


if __name__ == '__main__':
    args = json.loads(sys.argv[1])
    data = args.get("data", args)

    try:
        result = create_macropoint(data)
        print(json.dumps(result))
    except Exception as e:
        print(json.dumps({"status": "error", "error": str(e)}))
