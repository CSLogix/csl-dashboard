"""
Patch: Fix 4 gaps in MacroPoint webhook → dashboard data flow
=============================================================
Gap A: behindSchedule in tracking-summary ignores schedule_alert text
Gap B: cant_make_it never set from ScheduleAlertCode=3
Gap C: Suffixed load refs (LAX1260308015-1) don't match cache (LAX1260308015)
Gap D: Loads with active pings but empty status show blank on dashboard

Targets: /root/csl-bot/csl-doc-tracker/app.py
"""
import re

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP, "r") as f:
    code = f.read()

# ─────────────────────────────────────────────────────────────
# GAP A: Fix behindSchedule in tracking-summary endpoint
# The existing code only checks stop_times ETAs for "BEHIND".
# Add check for schedule_alert text field too.
# ─────────────────────────────────────────────────────────────
old_behind = '''        stop_times = entry.get("stop_times") or {}
        behind = False
        for k in ("stop1_eta", "stop2_eta"):
            val = stop_times.get(k) or ""
            if "BEHIND" in val.upper():
                behind = True'''

new_behind = '''        stop_times = entry.get("stop_times") or {}
        behind = False
        for k in ("stop1_eta", "stop2_eta"):
            val = stop_times.get(k) or ""
            if "BEHIND" in val.upper():
                behind = True
        # Also check schedule_alert text from native MP protocol
        _sa_text = (entry.get("schedule_alert") or "").upper()
        if "BEHIND" in _sa_text or "PAST APPOINTMENT" in _sa_text:
            behind = True'''

assert old_behind in code, "Gap A: could not find behindSchedule block"
code = code.replace(old_behind, new_behind, 1)
print("Gap A patched: behindSchedule now checks schedule_alert text")

# ─────────────────────────────────────────────────────────────
# GAP B: Set cant_make_it when ScheduleAlertCode=3
# The schedule alert handler stores the code but never flips
# the cant_make_it flag.
# ─────────────────────────────────────────────────────────────
old_sa_store = '''                    if schedule_alert != _old_alert:
                        _sa_entry["schedule_alert"] = schedule_alert
                        _sa_entry["schedule_alert_code"] = params.get("ScheduleAlertCode", "")
                        _sa_entry["distance_to_stop"] = distance_str
                        _sa_entry["eta_to_stop"] = params.get("EtaToStop", "")
                        _sa_entry["schedule_stop_type"] = stop_type'''

new_sa_store = '''                    if schedule_alert != _old_alert:
                        _sa_entry["schedule_alert"] = schedule_alert
                        _sa_entry["schedule_alert_code"] = params.get("ScheduleAlertCode", "")
                        _sa_entry["distance_to_stop"] = distance_str
                        _sa_entry["eta_to_stop"] = params.get("EtaToStop", "")
                        _sa_entry["schedule_stop_type"] = stop_type
                        # Gap B: Set cant_make_it from ScheduleAlertCode=3
                        _alert_code = str(params.get("ScheduleAlertCode", "")).strip()
                        if _alert_code == "3":
                            _sa_entry["cant_make_it"] = True
                            log.info(f"Webhook: cant_make_it=True for {_sa_key} (code=3)")
                        elif _alert_code in ("1", "2") and _sa_entry.get("cant_make_it"):
                            # Clear cant_make_it if driver recovered (now ahead/on-time)
                            _sa_entry["cant_make_it"] = None
                            log.info(f"Webhook: cant_make_it cleared for {_sa_key} (code={_alert_code})")'''

assert old_sa_store in code, "Gap B: could not find schedule alert store block"
code = code.replace(old_sa_store, new_sa_store, 1)
print("Gap B patched: cant_make_it now set from ScheduleAlertCode=3")

# ─────────────────────────────────────────────────────────────
# GAP C: Suffix-stripped matching for load refs like LAX1260308015-1
# Need to patch all 3 lookup sites:
#   1. Ping handler cache lookup
#   2. Schedule alert proximity detector (_sc_cache lookup)
#   3. Schedule alert storage (_sa_cache lookup)
# ─────────────────────────────────────────────────────────────

# C.1: Ping handler (lines ~8685-8695)
old_ping_lookup = '''        # Find matching cache entry by load_ref (could be ORD1260305010 format)
        matched_key = None
        for key, entry in cache.items():
            efj = entry.get("efj", "")
            load_num = entry.get("load_num", "")
            mp_load_id = entry.get("mp_load_id", "")
            if (load_ref == efj or load_ref == load_num or
                    load_ref == mp_load_id or load_ref == key):
                matched_key = key
                break'''

new_ping_lookup = '''        # Find matching cache entry by load_ref (could be ORD1260305010 format)
        matched_key = None
        for key, entry in cache.items():
            efj = entry.get("efj", "")
            load_num = entry.get("load_num", "")
            mp_load_id = entry.get("mp_load_id", "")
            if (load_ref == efj or load_ref == load_num or
                    load_ref == mp_load_id or load_ref == key):
                matched_key = key
                break
        # Gap C: suffix-stripped fallback (LAX1260308015-1 -> LAX1260308015)
        if not matched_key and "-" in load_ref:
            _base_ref = load_ref.rsplit("-", 1)[0]
            for key, entry in cache.items():
                if _base_ref in (entry.get("efj", ""), entry.get("load_num", ""),
                                 entry.get("mp_load_id", ""), key):
                    matched_key = key
                    break'''

assert old_ping_lookup in code, "Gap C.1: could not find ping lookup block"
code = code.replace(old_ping_lookup, new_ping_lookup, 1)
print("Gap C.1 patched: ping handler suffix-stripped fallback")

# C.2: Schedule alert proximity detector (_sc_cache lookup)
old_sc_lookup = '''            _sc_matched = None
            for _sk, _sv in _sc_cache.items():
                _efj = _sv.get("efj", "")
                _ln = _sv.get("load_num", "")
                _ml = _sv.get("mp_load_id", "")
                if load_ref in (_efj, _ln, _ml, _sk):
                    _sc_matched = _sk
                    break'''

new_sc_lookup = '''            _sc_matched = None
            for _sk, _sv in _sc_cache.items():
                _efj = _sv.get("efj", "")
                _ln = _sv.get("load_num", "")
                _ml = _sv.get("mp_load_id", "")
                if load_ref in (_efj, _ln, _ml, _sk):
                    _sc_matched = _sk
                    break
            # Gap C: suffix-stripped fallback
            if not _sc_matched and "-" in load_ref:
                _base_ref = load_ref.rsplit("-", 1)[0]
                for _sk, _sv in _sc_cache.items():
                    if _base_ref in (_sv.get("efj", ""), _sv.get("load_num", ""),
                                     _sv.get("mp_load_id", ""), _sk):
                        _sc_matched = _sk
                        break'''

assert old_sc_lookup in code, "Gap C.2: could not find _sc_cache lookup block"
code = code.replace(old_sc_lookup, new_sc_lookup, 1)
print("Gap C.2 patched: proximity detector suffix-stripped fallback")

# C.3: Schedule alert storage (_sa_cache lookup)
old_sa_lookup = '''                _sa_key = None
                for _sak, _sav in _sa_cache.items():
                    if load_ref in (_sav.get("efj", ""), _sav.get("load_num", ""),
                                    _sav.get("mp_load_id", ""), _sak):
                        _sa_key = _sak
                        break'''

new_sa_lookup = '''                _sa_key = None
                for _sak, _sav in _sa_cache.items():
                    if load_ref in (_sav.get("efj", ""), _sav.get("load_num", ""),
                                    _sav.get("mp_load_id", ""), _sak):
                        _sa_key = _sak
                        break
                # Gap C: suffix-stripped fallback
                if not _sa_key and "-" in load_ref:
                    _base_ref = load_ref.rsplit("-", 1)[0]
                    for _sak, _sav in _sa_cache.items():
                        if _base_ref in (_sav.get("efj", ""), _sav.get("load_num", ""),
                                         _sav.get("mp_load_id", ""), _sak):
                            _sa_key = _sak
                            break'''

assert old_sa_lookup in code, "Gap C.3: could not find _sa_cache lookup block"
code = code.replace(old_sa_lookup, new_sa_lookup, 1)
print("Gap C.3 patched: schedule alert storage suffix-stripped fallback")

# ─────────────────────────────────────────────────────────────
# GAP D: Set "Tracking Started" when ping arrives for empty-status load
# This goes inside the ping handler, right after updating last_location
# but before the cache write.
# ─────────────────────────────────────────────────────────────
old_ping_save = '''        if matched_key:
            entry = cache[matched_key]
            entry["last_location"] = {
                "lat": lat, "lon": lon,
                "city": city, "state": state, "street": street,
                "timestamp": timestamp,
            }
            entry["last_scraped"] = now
            entry["last_ping_at"] = now
            if not entry.get("last_event_at"):
                entry["last_event_at"] = now'''

new_ping_save = '''        if matched_key:
            entry = cache[matched_key]
            entry["last_location"] = {
                "lat": lat, "lon": lon,
                "city": city, "state": state, "street": street,
                "timestamp": timestamp,
            }
            entry["last_scraped"] = now
            entry["last_ping_at"] = now
            if not entry.get("last_event_at"):
                entry["last_event_at"] = now
            # Gap D: Initialize status if blank — pings prove tracking is active
            if not (entry.get("status") or "").strip():
                entry["status"] = "Tracking Started"
                log.info(f"Webhook: auto-set Tracking Started for {matched_key} (ping received)")'''

assert old_ping_save in code, "Gap D: could not find ping save block"
code = code.replace(old_ping_save, new_ping_save, 1)
print("Gap D patched: empty status -> Tracking Started on ping")

# ─────────────────────────────────────────────────────────────
# Also add suffix fallback to _update_tracking_cache_webhook
# so POST-format webhooks also benefit from Gap C fix
# ─────────────────────────────────────────────────────────────
old_utcw_fallback = '''    if not matched_key:
        try:
            with db.get_cursor() as cur:'''

# Check if there's a unique match — need to be careful
count = code.count(old_utcw_fallback)
if count == 1:
    new_utcw_fallback = '''    # Gap C: suffix-stripped fallback for _update_tracking_cache_webhook
    if not matched_key and "-" in load_ref:
        _base_ref = load_ref.rsplit("-", 1)[0]
        for key, entry in cache.items():
            if _base_ref in (entry.get("efj", ""), entry.get("load_num", "") or "",
                             entry.get("mp_load_id", "") or "", key):
                matched_key = key
                break

    if not matched_key:
        try:
            with db.get_cursor() as cur:'''
    code = code.replace(old_utcw_fallback, new_utcw_fallback, 1)
    print("Gap C.4 patched: _update_tracking_cache_webhook suffix fallback")
else:
    print(f"Gap C.4 skipped: found {count} matches for PG fallback block (expected 1)")

# ─────────────────────────────────────────────────────────────
# Write patched file
# ─────────────────────────────────────────────────────────────
with open(APP, "w") as f:
    f.write(code)

print("\nAll gaps patched successfully. Restart csl-dashboard to apply.")
