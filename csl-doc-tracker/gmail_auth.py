"""Standalone Gmail OAuth authorization script.
Run this once to generate token.json without needing the database."""

import os
from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.readonly",
    "https://www.googleapis.com/auth/gmail.modify",
]
CREDENTIALS_PATH = os.getenv("GMAIL_CREDENTIALS_PATH", "credentials.json")
TOKEN_PATH = os.getenv("GMAIL_TOKEN_PATH", "token.json")

def main():
    creds = None
    if os.path.exists(TOKEN_PATH):
        creds = Credentials.from_authorized_user_file(TOKEN_PATH, SCOPES)

    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            flow = InstalledAppFlow.from_client_secrets_file(CREDENTIALS_PATH, SCOPES)
            print("\n=== Gmail OAuth Authorization ===")
            print("A URL will be shown below. Open it in your browser,")
            print("sign in with john.feltz@commonsenselogistics.com,")
            print("and authorize access.\n")
            creds = flow.run_local_server(
                host="localhost",
                port=8090,
                bind_addr="0.0.0.0",
                open_browser=False,
                success_message="Authorization complete! You can close this tab.",
            )
        with open(TOKEN_PATH, "w") as f:
            f.write(creds.to_json())
        print(f"\ntoken.json saved successfully!")
    else:
        print("token.json already exists and is valid.")

if __name__ == "__main__":
    main()
