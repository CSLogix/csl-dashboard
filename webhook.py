import hmac
import json
import os
from datetime import datetime
from zoneinfo import ZoneInfo
from flask import Flask, request, jsonify

app = Flask(__name__)

BASIC_AUTH_USERNAME = "cslbot"
BASIC_AUTH_PASSWORD = "AcGG1Mc51MhCdPd5784zr2mETZuZR8oyqceEUNiDlWw"
LOG_FILE = "/root/csl-bot/webhook_payloads.log"


def auth_valid() -> bool:
    creds = request.authorization
    if not creds:
        return False
    user_ok = hmac.compare_digest(creds.username, BASIC_AUTH_USERNAME)
    pass_ok = hmac.compare_digest(creds.password, BASIC_AUTH_PASSWORD)
    return user_ok and pass_ok


@app.before_request
def check_auth():
    if not auth_valid():
        return jsonify({"error": "Unauthorized"}), 401, {"WWW-Authenticate": 'Basic realm="csl-bot"'}


@app.route("/macropoint-webhook", methods=["POST"])
def webhook():
    payload = request.get_json(silent=True) or {}
    now = datetime.now(ZoneInfo("America/New_York")).strftime("%Y-%m-%d %H:%M:%S ET")
    
    # Log every payload so we can see the structure
    log_entry = f"\n{'='*60}\n[{now}]\n{json.dumps(payload, indent=2)}\n"
    try:
        with open(LOG_FILE, "a") as f:
            f.write(log_entry)
    except Exception:
        pass
    
    print(f"[{now}] Webhook received: {json.dumps(payload)[:200]}")
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
