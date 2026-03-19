#!/usr/bin/env python3
"""
Macropoint login script v2 — handles current auth flow (auth.gln.com).
Run interactively: python3 mp_login_save.py

Takes screenshots at each step so you can see what's happening:
  /tmp/mp_login_1_start.png
  /tmp/mp_login_2_username.png
  /tmp/mp_login_3_password.png
  /tmp/mp_login_4_otp_page.png
  /tmp/mp_login_5_done.png
"""
import sys, json, time, os
from playwright.sync_api import sync_playwright
from dotenv import load_dotenv

load_dotenv("/root/csl-bot/.env", override=False)

COOKIES_FILE   = "/root/csl-bot/mp_cookies.json"
MACROPOINT_URL = "https://visibility.macropoint.com/"
MP_USER        = os.environ["MACROPOINT_USER"]
MP_PASS        = os.environ["MACROPOINT_PASSWORD"]


def save_cookies():
    with sync_playwright() as p:
        browser = p.chromium.launch(headless=True)
        ctx     = browser.new_context(viewport={"width": 1280, "height": 900})
        page    = ctx.new_page()

        # Step 1: Navigate to Macropoint
        print("[1/5] Navigating to Macropoint...")
        page.goto(MACROPOINT_URL, timeout=30000)
        try:
            page.wait_for_load_state("networkidle", timeout=20000)
        except Exception:
            pass
        time.sleep(2)
        page.screenshot(path="/tmp/mp_login_1_start.png")
        print(f"  URL: {page.url}")
        print(f"  Screenshot: /tmp/mp_login_1_start.png")

        # Step 2: Enter username
        print("\n[2/5] Entering username...")
        # Try different username field selectors (old MP vs auth.gln.com)
        username_filled = False
        for selector in ['input[name="UserName"]', 'input[name="username"]',
                         'input[type="email"]', 'input[name="loginfmt"]',
                         'input[id="username"]', '#username', '#UserName']:
            try:
                el = page.locator(selector)
                if el.is_visible(timeout=2000):
                    el.fill(MP_USER)
                    username_filled = True
                    print(f"  Filled username via: {selector}")
                    break
            except Exception:
                continue

        if not username_filled:
            print("  WARNING: Could not find username field!")
            print(f"  Page text: {page.inner_text('body')[:500]}")
            page.screenshot(path="/tmp/mp_login_2_username.png")
            browser.close()
            return

        # Click next/submit for username
        for selector in ['input[id="UsernameNext"]', 'button[type="submit"]',
                         'input[type="submit"]', '#next', '.btn-primary',
                         'button:has-text("Next")', 'button:has-text("Continue")']:
            try:
                el = page.locator(selector)
                if el.is_visible(timeout=1500):
                    el.click()
                    print(f"  Clicked: {selector}")
                    break
            except Exception:
                continue

        time.sleep(3)
        try:
            page.wait_for_load_state("networkidle", timeout=10000)
        except Exception:
            pass
        page.screenshot(path="/tmp/mp_login_2_username.png")
        print(f"  URL: {page.url}")
        print(f"  Screenshot: /tmp/mp_login_2_username.png")

        # Step 3: Enter password
        print("\n[3/5] Entering password...")
        password_filled = False
        for selector in ['input[name="Password"]', 'input[name="password"]',
                         'input[type="password"]', '#Password', '#password']:
            try:
                el = page.locator(selector)
                if el.is_visible(timeout=3000):
                    el.fill(MP_PASS)
                    password_filled = True
                    print(f"  Filled password via: {selector}")
                    break
            except Exception:
                continue

        if not password_filled:
            print("  WARNING: Could not find password field!")
            print(f"  Page text: {page.inner_text('body')[:500]}")
            page.screenshot(path="/tmp/mp_login_3_password.png")
            browser.close()
            return

        # Click login/submit
        for selector in ['input[id="Login"]', 'button[type="submit"]',
                         'input[type="submit"]', '#Login', '.btn-primary',
                         'button:has-text("Sign in")', 'button:has-text("Login")',
                         'button:has-text("Log in")']:
            try:
                el = page.locator(selector)
                if el.is_visible(timeout=1500):
                    el.click()
                    print(f"  Clicked: {selector}")
                    break
            except Exception:
                continue

        time.sleep(4)
        try:
            page.wait_for_load_state("networkidle", timeout=15000)
        except Exception:
            pass
        page.screenshot(path="/tmp/mp_login_3_password.png")
        print(f"  URL: {page.url}")
        print(f"  Screenshot: /tmp/mp_login_3_password.png")

        # Step 4: Check if we need OTP
        current_url = page.url.lower()
        page_text = page.inner_text("body")

        needs_otp = any([
            "otp" in current_url,
            "twofactor" in current_url,
            "mfa" in current_url,
            "verify" in current_url,
            "code" in current_url and "verification" in current_url,
            "One-time" in page_text,
            "verification code" in page_text.lower(),
            "enter the code" in page_text.lower(),
            "enter code" in page_text.lower(),
        ])

        if needs_otp:
            page.screenshot(path="/tmp/mp_login_4_otp_page.png")
            print(f"\n[4/5] OTP page detected!")
            print(f"  URL: {page.url}")
            print(f"  Screenshot: /tmp/mp_login_4_otp_page.png")
            print(f"  Page text snippet: {page_text[:300]}")
            print()

            otp = input("  Enter OTP code: ").strip()
            if not otp:
                print("  No OTP entered — aborting.")
                browser.close()
                return

            # Fill OTP
            otp_filled = False
            for selector in ['input[name="Otp"]', 'input[name="otp"]',
                             'input[name="code"]', 'input[name="verificationCode"]',
                             'input[type="tel"]', 'input[type="number"]',
                             '#Otp', '#otp', '#code']:
                try:
                    el = page.locator(selector)
                    if el.is_visible(timeout=2000):
                        el.fill(otp)
                        otp_filled = True
                        print(f"  Filled OTP via: {selector}")
                        break
                except Exception:
                    continue

            if not otp_filled:
                # Try any visible input field
                try:
                    inputs = page.locator('input:visible')
                    count = inputs.count()
                    for i in range(count):
                        inp = inputs.nth(i)
                        inp_type = inp.get_attribute("type") or ""
                        if inp_type not in ["hidden", "submit", "button"]:
                            inp.fill(otp)
                            otp_filled = True
                            print(f"  Filled OTP in input #{i}")
                            break
                except Exception:
                    pass

            if not otp_filled:
                print("  WARNING: Could not find OTP input field!")
                browser.close()
                return

            # Click verify/submit
            for selector in ['button[id="Verify"]', 'button[type="submit"]',
                             'input[type="submit"]', '#Verify',
                             'button:has-text("Verify")', 'button:has-text("Submit")',
                             'button:has-text("Continue")']:
                try:
                    el = page.locator(selector)
                    if el.is_visible(timeout=1500):
                        el.click()
                        print(f"  Clicked: {selector}")
                        break
                except Exception:
                    continue

            time.sleep(4)
            try:
                page.wait_for_load_state("networkidle", timeout=15000)
            except Exception:
                pass

        elif "shipments" in current_url or "dashboard" in current_url:
            print("\n[4/5] No OTP needed — already logged in!")
        else:
            page.screenshot(path="/tmp/mp_login_4_otp_page.png")
            print(f"\n[4/5] Unexpected page after login:")
            print(f"  URL: {page.url}")
            print(f"  Screenshot: /tmp/mp_login_4_otp_page.png")
            print(f"  Page text: {page_text[:500]}")

            # Check if there's a "send code" button we need to click first
            for selector in ['button:has-text("Send")', 'button:has-text("send code")',
                             'a:has-text("Send")', 'button:has-text("Email")',
                             'button:has-text("Text")', 'button:has-text("SMS")']:
                try:
                    el = page.locator(selector)
                    if el.is_visible(timeout=2000):
                        print(f"\n  Found send button: {selector}")
                        resp = input(f"  Click '{selector}' to send OTP? (y/n): ").strip().lower()
                        if resp == 'y':
                            el.click()
                            time.sleep(4)
                            try:
                                page.wait_for_load_state("networkidle", timeout=10000)
                            except Exception:
                                pass
                            page.screenshot(path="/tmp/mp_login_4b_after_send.png")
                            print(f"  Screenshot: /tmp/mp_login_4b_after_send.png")

                            otp = input("  Enter OTP code: ").strip()
                            if otp:
                                # Try to fill and submit
                                for sel2 in ['input[name="Otp"]', 'input[name="otp"]',
                                             'input[name="code"]', 'input[type="tel"]']:
                                    try:
                                        el2 = page.locator(sel2)
                                        if el2.is_visible(timeout=2000):
                                            el2.fill(otp)
                                            break
                                    except Exception:
                                        continue
                                for sel2 in ['button[type="submit"]', 'button:has-text("Verify")',
                                             'button:has-text("Submit")']:
                                    try:
                                        el2 = page.locator(sel2)
                                        if el2.is_visible(timeout=1500):
                                            el2.click()
                                            break
                                    except Exception:
                                        continue
                                time.sleep(4)
                                try:
                                    page.wait_for_load_state("networkidle", timeout=15000)
                                except Exception:
                                    pass
                        break
                except Exception:
                    continue

        # Step 5: Save cookies
        print(f"\n[5/5] Saving cookies...")
        page.screenshot(path="/tmp/mp_login_5_done.png")
        print(f"  Final URL: {page.url}")
        print(f"  Screenshot: /tmp/mp_login_5_done.png")

        cookies = ctx.cookies()
        with open(COOKIES_FILE, 'w') as f:
            json.dump(cookies, f)
        print(f"  Saved {len(cookies)} cookies to {COOKIES_FILE}")

        # Verify we're actually logged in
        if "shipments" in page.url or "dashboard" in page.url or "visibility.macropoint" in page.url:
            if "login" not in page.url.lower() and "auth" not in page.url.lower():
                print("\n  SUCCESS — logged into Macropoint portal!")
            else:
                print("\n  WARNING — may not be fully logged in, check screenshots")
        else:
            print(f"\n  WARNING — unexpected final URL, check /tmp/mp_login_5_done.png")

        browser.close()


if __name__ == '__main__':
    save_cookies()
