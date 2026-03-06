#!/usr/bin/env python3
"""Patch: Add _invoiced field to sheet_cache shipments so /api/shipments includes it."""

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP) as f:
    code = f.read()

# Insert invoiced enrichment between "self.shipments = all_shipments" and "self._compute_stats()"
old = """        self.shipments = all_shipments
        self._compute_stats()"""

new = """        self.shipments = all_shipments

        # Enrich shipments with invoiced status from DB
        try:
            invoiced_map = db.get_invoiced_map()
        except Exception:
            invoiced_map = {}
        for s in self.shipments:
            s["_invoiced"] = invoiced_map.get(s["efj"], False)

        self._compute_stats()"""

if "invoiced_map" in code.split("_do_refresh")[1].split("_compute_stats")[0]:
    print("SKIP: _invoiced already present in _do_refresh before _compute_stats")
else:
    code = code.replace(old, new, 1)
    print("PATCHED: Added _invoiced enrichment to _do_refresh")

with open(APP, "w") as f:
    f.write(code)

print("Done. Restart csl-dashboard to apply.")
