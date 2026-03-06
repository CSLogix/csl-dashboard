#!/usr/bin/env python3
"""Local Macropoint login — saves cookies then SCPs to server."""
import json, time, sys
from playwright.sync_api import sync_playwright

MP_USER = "john.feltz@evansdelivery.com"
MP_PASS = "MFdoom1131@1"
COOKIES_FILE = "mp_cookies.json"

with sync_playwright() as p:
    browser = p.chromium.launch(headless=False)  # visible browser
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    page = ctx.new_page()

    print("[1] Navigating to Macropoint...")
    page.goto("https://visibility.macropoint.com/", timeout=30000)
    try: page.wait_for_load_state("networkidle", timeout=15000)
    except: pass
    time.sleep(2)

    print("[2] Entering username...")
    page.locator('input[name="UserName"]').fill(MP_USER)
    page.locator('input[id="UsernameNext"]').click()
    time.sleep(3)
    try: page.wait_for_load_state("networkidle", timeout=10000)
    except: pass

    print("[3] Entering password...")
    page.locator('input[name="Password"]').fill(MP_PASS)
    page.locator('input[id="Login"]').click()
    time.sleep(5)
    try: page.wait_for_load_state("networkidle", timeout=15000)
    except: pass
    print(f"  URL: {page.url}")

    # OTP prompt
    otp = input("\nEnter OTP from your phone: ").strip()
    otp_field = page.locator('input[name="Otp"]')
    otp_field.fill(otp)
    time.sleep(1)
    otp_field.press("Enter")

    time.sleep(8)
    try: page.wait_for_load_state("networkidle", timeout=15000)
    except: pass

    print(f"\nFinal URL: {page.url}")
    cookies = ctx.cookies()
    with open(COOKIES_FILE, "w") as f:
        json.dump(cookies, f)
    print(f"Saved {len(cookies)} cookies to {COOKIES_FILE}")

    if "login" not in page.url.lower() and "auth" not in page.url.lower():
        print("\nSUCCESS! Now run:")
        print(f'  scp {COOKIES_FILE} root@187.77.217.61:/root/csl-bot/mp_cookies.json')
    else:
        print("\nLogin may have failed — check the browser window")
        input("Press Enter to close...")

    browser.close()
