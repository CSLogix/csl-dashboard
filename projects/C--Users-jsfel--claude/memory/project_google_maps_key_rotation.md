---
name: Google Maps API key rotation
description: Distance Matrix API key rotated 2026-03-18 after GitHub secret scanning leak — new key is IP + API restricted in CSL Doc Tracker GCP project
type: project
---

Google Maps Distance Matrix API key was rotated on 2026-03-18 after GitHub secret scanning flagged a public leak in `patches/patch_distance_api.py`.

**Why:** Old key `AIzaSyAZskerz...` was committed to the CSLogix/csl-dashboard repo in patch files. GitHub flagged it as a public leak (alert #1). Alert closed as "revoked".

**New key details:**
- GCP project: **CSL Doc Tracker** (`csl-doc-tracker`) under john.feltz@commonsense account
- Application restriction: IP address — `187.77.217.61` only
- API restriction: Distance Matrix API only
- Key stored in: `/root/csl-bot/.env` (`GOOGLE_MAPS_API_KEY`) and `/etc/systemd/system/csl-dashboard.service` (`Environment=`)

**IPv6 gap (2026-03-19):** Server uses IPv6 (`2a02:4780:4:2fa2::1`) for outbound requests by default, but API key only allows IPv4 `187.77.217.61`. Workaround: force IPv4 via `urllib3.util.connection.allowed_gai_family = lambda: socket.AF_INET` in Python. Proper fix: add the IPv6 to GCP API key IP restrictions.

**How to apply:** Never hardcode API keys in patch files or committed code. Always use env vars. If key needs rotation again, create new key in CSL Doc Tracker GCP project Credentials page.
