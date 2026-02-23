import hmac
from flask import Flask, request, jsonify

app = Flask(__name__)

BASIC_AUTH_USERNAME = "cslbot"
BASIC_AUTH_PASSWORD = "AcGG1Mc51MhCdPd5784zr2mETZuZR8oyqceEUNiDlWw"


def auth_valid() -> bool:
    """Constant-time comparison to prevent timing attacks."""
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
    # TODO: handle payload
    return jsonify({"status": "ok"}), 200


if __name__ == "__main__":
    app.run(host="0.0.0.0", port=5000)
