#!/usr/bin/env python3
"""
One-time Macropoint login script. Run interactively to save session cookies.
Usage: python3 mp_login_save.py <OTP>
"""
import sys, json
from playwright.sync_api import sync_playwright

COOKIES_FILE   = "/root/csl-bot/mp_cookies.json"
MACROPOINT_URL = "https://visibility.macropoint.com/"
MP_USER        = "john.feltz@evansdelivery.com"
MP_PASS        = "MFdoom1131@1"

def save_cookies(otp):
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx     = browser.new_context()
        page    = ctx.new_page()

        print("Navigating...")
        page.goto(MACROPOINT_URL, timeout=30000)
        page.wait_for_load_state("networkidle", timeout=20000)

        print("Logging in...")
        page.fill('input[name="UserName"]', MP_USER)
        page.click('input[id="UsernameNext"]')
        page.wait_for_timeout(2000)
        page.fill('input[name="Password"]', MP_PASS)
        page.click('input[id="Login"]')
        page.wait_for_load_state("networkidle", timeout=20000)
        page.wait_for_timeout(2000)

        if "Otp" in page.url or "TwoFactor" in page.url:
            print(f"Entering OTP: {otp}")
            page.fill('input[name="Otp"]', str(otp))
            page.click('button[id="Verify"]')
            page.wait_for_load_state("networkidle", timeout=20000)
            page.wait_for_timeout(3000)

        print("Final URL:", page.url)
        cookies = ctx.cookies()
        with open(COOKIES_FILE, 'w') as f:
            json.dump(cookies, f)
        print(f"Saved {len(cookies)} cookies to {COOKIES_FILE}")
        browser.close()

if __name__ == '__main__':
    otp = sys.argv[1] if len(sys.argv) > 1 else input("Enter OTP: ")
    save_cookies(otp)
