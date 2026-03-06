#!/usr/bin/env python3
"""Quick test: simulate API screenshot lookups for various EFJ numbers."""
import json, os

tc = json.load(open("/root/csl-bot/ftl_tracking_cache.json"))
mp_dir = "/root/csl-bot/csl-doc-tracker/uploads/mp_screenshots"

test_efjs = [
    "EFJ107093",  # container-keyed (CSNU8670992)
    "EFJ107230",  # bare number (107230)
    "EFJ107104",  # boviet (BSTT-022426P)
    "EFJ107030",  # tolead (TT-P-0223-EV-1)
    "EFJ106822",  # direct EFJ key
    "EFJ107090",  # slash in load_num
    "EFJ107186",  # space in load_num
]

for efj in test_efjs:
    path = os.path.join(mp_dir, f"{efj}.png")
    if os.path.exists(path):
        size = os.path.getsize(path)
        print(f"  {efj}: DIRECT match ({size:,} bytes)")
        continue

    alt_key = None
    for k, v in tc.items():
        if v.get("load_num") == efj:
            alt_key = k
            break
    if not alt_key and efj.startswith("EFJ") and efj[3:].isdigit():
        bare = efj[3:]
        if bare in tc:
            alt_key = bare

    if alt_key:
        alt_path = os.path.join(mp_dir, f"{alt_key}.png")
        if os.path.exists(alt_path):
            size = os.path.getsize(alt_path)
            print(f"  {efj}: FALLBACK via {alt_key} ({size:,} bytes)")
            continue

    print(f"  {efj}: NOT FOUND")
