#!/usr/bin/env python3
"""
One-time OAuth flow for john.feltz@commonsenselogistics.com
Reuses the existing CSL Doc Tracker OAuth client (credentials.json).
Saves token to csl_gmail_token.json for the inbox scanner.

Usage:
    python3 csl_gmail_auth.py

It will print a URL — open it in your browser, sign in as
john.feltz@commonsenselogistics.com, click Allow.
"""

import os
import json
from google_auth_oauthlib.flow import InstalledAppFlow
from google.oauth2.credentials import Credentials

CREDENTIALS_PATH = os.path.join(
    os.path.dirname(__file__), "csl-doc-tracker", "credentials.json"
)
TOKEN_PATH = os.path.join(os.path.dirname(__file__), "csl_gmail_token.json")
SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]


def main():
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)
        if creds and creds.valid:
            print(f"Token already exists and is valid: {TOKEN_PATH}")
            print("Delete it first if you want to re-authorize.")
            return
        if creds and creds.expired and creds.refresh_token:
            from google.auth.transport.requests import Request
            creds.refresh(Request())
            with open(TOKEN_PATH, "w") as f:
                f.write(creds.to_json())
            print(f"Token refreshed successfully: {TOKEN_PATH}")
            return

    if not os.path.exists(CREDENTIALS_PATH):
        print(f"ERROR: OAuth client not found at {CREDENTIALS_PATH}")
        return

    flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)

    print()
    print("=" * 60)
    print("  CSL Gmail Authorization")
    print("=" * 60)
    print()
    print("Starting local server on port 8091...")
    print("Open the URL below in your browser:")
    print("Sign in as: john.feltz@commonsenselogistics.com")
    print("Click 'Allow' to grant access.")
    print()

    creds = flow.run_local_server(
        port=8091,
        open_browser=False,
        prompt="consent",
        login_hint="john.feltz@commonsenselogistics.com",
    )

    with open(TOKEN_PATH, "w") as f:
        f.write(creds.to_json())

    os.chmod(TOKEN_PATH, 0o600)
    print()
    print(f"Token saved to: {TOKEN_PATH}")
    print("The inbox scanner can now read john.feltz@ emails.")


if __name__ == "__main__":
    main()
