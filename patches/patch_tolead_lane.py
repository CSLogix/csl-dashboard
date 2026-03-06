#!/usr/bin/env python3
"""
patch_tolead_lane.py — Adds Origin → Destination "Lane" column to the
Tolead daily summary email table.

Changes:
1. Add TOLEAD_COL_ORIGIN = 6 config
2. Read origin in scan_tolead()
3. Pass origin through scrape_and_summarize()
4. Add Lane column to summary table when origin/dest data exists
"""
import re

FILE = "/root/csl-bot/daily_summary.py"

with open(FILE, "r") as f:
    code = f.read()

# Backup
with open(FILE + ".bak", "w") as f:
    f.write(code)
print("Backup saved")

# ── 1. Add TOLEAD_COL_ORIGIN ────────────────────────────────────────────────
code = code.replace(
    'TOLEAD_COL_DEST   = 7\n',
    'TOLEAD_COL_ORIGIN = 6\nTOLEAD_COL_DEST   = 7\n',
)
print("1. Added TOLEAD_COL_ORIGIN = 6")

# ── 2. Read origin in scan_tolead() ─────────────────────────────────────────
code = code.replace(
    '''        entries.append({
            "efj": _safe_get(row, TOLEAD_COL_EFJ),
            "load_id": _safe_get(row, TOLEAD_COL_ORD),
            "mp_url": mp_url,
            "pickup": _safe_get(row, TOLEAD_COL_DATE),
            "delivery": "",
            "dest": _safe_get(row, TOLEAD_COL_DEST),
            "sheet_status": status,
        })''',
    '''        entries.append({
            "efj": _safe_get(row, TOLEAD_COL_EFJ),
            "load_id": _safe_get(row, TOLEAD_COL_ORD),
            "mp_url": mp_url,
            "pickup": _safe_get(row, TOLEAD_COL_DATE),
            "delivery": "",
            "origin": _safe_get(row, TOLEAD_COL_ORIGIN),
            "dest": _safe_get(row, TOLEAD_COL_DEST),
            "sheet_status": status,
        })''',
)
print("2. Added origin to scan_tolead() entries")

# ── 3. Pass origin through scrape_and_summarize() ───────────────────────────
code = code.replace(
    '''            "dest": item.get("dest", ""),''',
    '''            "origin": item.get("origin", ""),
            "dest": item.get("dest", ""),''',
)
print("3. Added origin to scrape_and_summarize() summaries")

# ── 4. Update build_summary_body to detect lane data and pass flag ───────────
code = code.replace(
    '''    hdrs = ["EFJ #", "Load ID", "Status", "Stop 1 (Pickup)", "Stop 2 (Delivery)"]

    sections = ""
    sections += _section(_G, "On Time", len(on_time), hdrs, _build_rows(on_time, "on_time"))
    sections += _section(_R, "Behind Schedule / Can't Make It", len(behind), hdrs, _build_rows(behind, "behind"))
    sections += _section(_P, "Tracking Issues", len(tracking), hdrs, _build_rows(tracking, "tracking"))''',
    '''    has_lane = any(s.get("origin") or s.get("dest") for s in summaries)
    hdrs = ["EFJ #", "Load ID"]
    if has_lane:
        hdrs.append("Lane")
    hdrs += ["Status", "Stop 1 (Pickup)", "Stop 2 (Delivery)"]

    sections = ""
    sections += _section(_G, "On Time", len(on_time), hdrs, _build_rows(on_time, "on_time", has_lane=has_lane))
    sections += _section(_R, "Behind Schedule / Can't Make It", len(behind), hdrs, _build_rows(behind, "behind", has_lane=has_lane))
    sections += _section(_P, "Tracking Issues", len(tracking), hdrs, _build_rows(tracking, "tracking", has_lane=has_lane))''',
)
print("4. Updated build_summary_body with lane detection")

# ── 5. Update _build_rows to accept has_lane and render lane column ──────────
code = code.replace(
    '''def _build_rows(loads, category):
    rows = ""
    for i, s in enumerate(loads):
        alt = i % 2 == 1
        efj = s["efj"]
        load_ref = s.get("mp_load_id") or s["load_id"]
        status = s["mp_status"]
        otp = s.get("otp") or "&mdash;"
        otd = s.get("otd") or "&mdash;"

        if category == "behind":
            otp_st = _TD_R if "BEHIND" in (s.get("otp") or "").upper() else _TD
            otd_st = _TD_R if "BEHIND" in (s.get("otd") or "").upper() else _TD
            rows += _tr([_cb(efj), _c(load_ref), _c(status), _c(otp, otp_st), _c(otd, otd_st)], alt=alt)
        elif category == "tracking":
            rows += _tr([_cb(efj), _c(load_ref), _c(status, _TD_P), _c(otp, _TD_P), _c(otd, _TD_P)], alt=alt)
        else:
            rows += _tr([_cb(efj), _c(load_ref), _c(status), _c(otp), _c(otd)], alt=alt)
    return rows''',
    '''def _build_rows(loads, category, has_lane=False):
    rows = ""
    for i, s in enumerate(loads):
        alt = i % 2 == 1
        efj = s["efj"]
        load_ref = s.get("mp_load_id") or s["load_id"]
        status = s["mp_status"]
        otp = s.get("otp") or "&mdash;"
        otd = s.get("otd") or "&mdash;"

        lane_cell = []
        if has_lane:
            origin = s.get("origin", "")
            dest = s.get("dest", "")
            if origin and dest:
                lane = f"{origin} &#8594; {dest}"
            else:
                lane = origin or dest or "&mdash;"
            lane_cell = [_c(lane)]

        if category == "behind":
            otp_st = _TD_R if "BEHIND" in (s.get("otp") or "").upper() else _TD
            otd_st = _TD_R if "BEHIND" in (s.get("otd") or "").upper() else _TD
            rows += _tr([_cb(efj), _c(load_ref)] + lane_cell + [_c(status), _c(otp, otp_st), _c(otd, otd_st)], alt=alt)
        elif category == "tracking":
            rows += _tr([_cb(efj), _c(load_ref)] + lane_cell + [_c(status, _TD_P), _c(otp, _TD_P), _c(otd, _TD_P)], alt=alt)
        else:
            rows += _tr([_cb(efj), _c(load_ref)] + lane_cell + [_c(status), _c(otp), _c(otd)], alt=alt)
    return rows''',
)
print("5. Updated _build_rows with lane column support")

# ── Write ────────────────────────────────────────────────────────────────────
with open(FILE, "w") as f:
    f.write(code)
print("\nPatch applied successfully!")
print("Lane column will appear in Tolead daily summaries (Origin → Destination)")
print("FTL and Boviet summaries are unaffected (no origin/dest data).")
