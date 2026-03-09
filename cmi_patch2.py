"""Patch ftl_monitor.py + tolead_monitor.py — add ETA extraction for CAN'T MAKE IT alerts."""

# ═══════════════════════════════════════════════════════════════════════════
# PATCH ftl_monitor.py
# ═══════════════════════════════════════════════════════════════════════════
path = "/root/csl-bot/ftl_monitor.py"
with open(path) as f:
    code = f.read()
with open(path + ".pre-cmi2", "w") as f:
    f.write(code)

# 1) Add _extract_stop_eta helper before _parse_macropoint
code = code.replace(
    "\n\ndef _parse_macropoint(",
    '''


def _extract_stop_eta(section: str) -> str | None:
    """Extract ETA + behind/ahead info from a stop section.
    Returns e.g. 'ETA: 2/25/2026 11:11 PM CT — 20.7 Hours BEHIND' or None."""
    parts = []
    # Look for "X.X Hours BEHIND" or "X.X Hours AHEAD"
    m_behind = re.search(
        r"(\d+\.?\d*)\s+Hours?\s+(BEHIND|AHEAD)",
        section, re.I,
    )
    if m_behind:
        parts.append(f"{m_behind.group(1)} Hours {m_behind.group(2).upper()}")
    # Look for "ETA: M/D/YYYY H:MM AM/PM TZ"
    m_eta = re.search(
        r"ETA:\s*(\d{1,2}/\d{1,2}/\d{4}\s+\d{1,2}:\d{2}\s*[AP]M\s*[A-Z]{1,3})",
        section, re.I,
    )
    if m_eta:
        parts.append(f"ETA: {m_eta.group(1).strip()}")
    return " — ".join(parts) if parts else None


def _parse_macropoint(''',
)

# 2) Replace the CAN'T MAKE IT detection block to also extract ETA
code = code.replace(
    """    # Detect "CAN'T MAKE IT" in stop sections
    _cmi_stops = []
    if stop1_text and re.search(r"CAN['\\u2019]?T\\s+MAKE\\s+IT", stop1_text, re.I):
        _cmi_stops.append("Stop 1 (Pickup)")
    if stop2_text and re.search(r"CAN['\\u2019]?T\\s+MAKE\\s+IT", stop2_text, re.I):
        _cmi_stops.append("Stop 2 (Delivery)")
    cant_make_it = " & ".join(_cmi_stops) if _cmi_stops else None""",
    r"""    # Detect "CAN'T MAKE IT" in stop sections + extract ETA
    _cmi_parts = []
    if stop1_text and re.search(r"CAN['\u2019]?T\s+MAKE\s+IT", stop1_text, re.I):
        eta1 = _extract_stop_eta(stop1_text)
        _cmi_parts.append(f"Stop 1 (Pickup)" + (f" [{eta1}]" if eta1 else ""))
    if stop2_text and re.search(r"CAN['\u2019]?T\s+MAKE\s+IT", stop2_text, re.I):
        eta2 = _extract_stop_eta(stop2_text)
        _cmi_parts.append(f"Stop 2 (Delivery)" + (f" [{eta2}]" if eta2 else ""))
    cant_make_it = " & ".join(_cmi_parts) if _cmi_parts else None""",
)

with open(path, "w") as f:
    f.write(code)
print(f"Patched {path}")

# ═══════════════════════════════════════════════════════════════════════════
# PATCH tolead_monitor.py — no changes needed, it already uses cant_make_it
# from ftl_monitor's scrape_macropoint which now includes ETA info
# ═══════════════════════════════════════════════════════════════════════════
print("tolead_monitor.py — no changes needed (uses ftl_monitor.scrape_macropoint)")
print("Done.")
