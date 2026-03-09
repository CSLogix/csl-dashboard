"""Patch: CAN'T MAKE IT — only alert if stop not yet timestamped, use proper wording."""
path = "/root/csl-bot/ftl_monitor.py"
with open(path) as f:
    code = f.read()

old = '''    # Detect "CAN'T MAKE IT" in stop sections + extract ETA
    _cmi_parts = []
    if stop1_text and re.search(r"CAN['\u2019]?T\\s+MAKE\\s+IT", stop1_text, re.I):
        eta1 = _extract_stop_eta(stop1_text)
        _cmi_parts.append("Stop 1 (Pickup)" + (f" [{eta1}]" if eta1 else ""))
    if stop2_text and re.search(r"CAN['\u2019]?T\\s+MAKE\\s+IT", stop2_text, re.I):
        eta2 = _extract_stop_eta(stop2_text)
        _cmi_parts.append("Stop 2 (Delivery)" + (f" [{eta2}]" if eta2 else ""))
    cant_make_it = " & ".join(_cmi_parts) if _cmi_parts else None'''

new = '''    # Detect "CAN'T MAKE IT" — only alert if the stop has NOT been timestamped yet
    _cmi_parts = []
    if stop1_text and not stop1_arrived and re.search(r"CAN['\u2019]?T\\s+MAKE\\s+IT", stop1_text, re.I):
        eta1 = _extract_stop_eta(stop1_text)
        _cmi_parts.append("Driver Won't Make PU in Time" + (f" [{eta1}]" if eta1 else ""))
    if stop2_text and not stop2_arrived and re.search(r"CAN['\u2019]?T\\s+MAKE\\s+IT", stop2_text, re.I):
        eta2 = _extract_stop_eta(stop2_text)
        _cmi_parts.append("Driver Won't Make Delivery in Time" + (f" [{eta2}]" if eta2 else ""))
    cant_make_it = " & ".join(_cmi_parts) if _cmi_parts else None'''

if old in code:
    code = code.replace(old, new)
    with open(path, "w") as f:
        f.write(code)
    print("Patched ftl_monitor.py")
else:
    print("ERROR: old block not found")
