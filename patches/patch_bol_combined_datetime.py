"""
Patch: BOL Combined Date/Time Support
Allows CSV uploads with combined "Pickup Date/Time" and "Delivery Date/Time" columns.
Auto-splits "3/6 8:15" into pickup_date="3/6" + pickup_time="8:15" for the template.
Also accepts the original separate column format.
"""

APP_PY = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP_PY, "r") as f:
    src = f.read()

# 1. Update BOL_ACCOUNTS to add combined columns as alternates
old_csv_columns = '''        "csv_columns": {
            "EFJ Pro #": "efj_pro",
            "BV #": "box_one",
            "Boviet  Load#": "piedra_box",
            "Pallet Count": "pallet_count",
            "Piece Count": "piece_count",
            "Watt": "wattage",
            "Pickup Appt Date": "pickup_date",
            "PU Appt Time": "pickup_time",
            "Delivery Apt Date": "delivery_date",
            "Delivery Appt Time": "delivery_time",
        },
        "filename_pattern": "{piedra_box} {efj_pro}",
        "required_columns": ["EFJ Pro #", "BV #", "Boviet  Load#", "Pickup Appt Date"],'''

new_csv_columns = '''        "csv_columns": {
            "EFJ Pro #": "efj_pro",
            "BV #": "box_one",
            "Boviet  Load#": "piedra_box",
            "Pallet Count": "pallet_count",
            "Piece Count": "piece_count",
            "Watt": "wattage",
            "Pickup Appt Date": "pickup_date",
            "PU Appt Time": "pickup_time",
            "Delivery Apt Date": "delivery_date",
            "Delivery Appt Time": "delivery_time",
            "Pickup Date/Time": "_pickup_combined",
            "Delivery Date/Time": "_delivery_combined",
        },
        "combined_datetime_fields": {
            "_pickup_combined": ("pickup_date", "pickup_time"),
            "_delivery_combined": ("delivery_date", "delivery_time"),
        },
        "filename_pattern": "{piedra_box} {efj_pro}",
        "required_columns": ["EFJ Pro #", "BV #", "Boviet  Load#"],'''

if old_csv_columns not in src:
    print("ERROR: Could not find BOL_ACCOUNTS csv_columns block to patch")
else:
    src = src.replace(old_csv_columns, new_csv_columns)
    print("OK: Updated BOL_ACCOUNTS with combined date/time columns")

# 2. Add combined-field splitting logic after context is built, before template render
old_render = '''            tpl = _DocxTemplate(str(template_path))
            tpl.render(context)'''

new_render = '''            # Split combined date/time fields (e.g. "3/6 8:15" -> date="3/6", time="8:15")
            for combo_key, (date_var, time_var) in cfg.get("combined_datetime_fields", {}).items():
                if combo_key in context and context[combo_key]:
                    parts = context[combo_key].strip().split(None, 1)
                    if not context.get(date_var):
                        context[date_var] = parts[0] if len(parts) >= 1 else context[combo_key]
                    if not context.get(time_var):
                        context[time_var] = parts[1] if len(parts) >= 2 else ""
                    del context[combo_key]

            tpl = _DocxTemplate(str(template_path))
            tpl.render(context)'''

if old_render not in src:
    print("ERROR: Could not find template render block to patch")
else:
    src = src.replace(old_render, new_render)
    print("OK: Added combined date/time splitting logic")

# 3. Update the /api/bol/accounts endpoint to include combined_datetime info
old_accounts_endpoint = '''    for key, cfg in BOL_ACCOUNTS.items():
        accounts.append({
            "key": key,
            "label": cfg["label"],
            "columns": list(cfg["csv_columns"].keys()),
            "required_columns": cfg.get("required_columns", []),
        })'''

new_accounts_endpoint = '''    for key, cfg in BOL_ACCOUNTS.items():
        # Filter out internal combined-field markers from displayed columns
        display_cols = [c for c, v in cfg["csv_columns"].items() if not v.startswith("_")]
        combined_cols = [c for c, v in cfg["csv_columns"].items() if v.startswith("_")]
        accounts.append({
            "key": key,
            "label": cfg["label"],
            "columns": display_cols,
            "combined_columns": combined_cols,
            "required_columns": cfg.get("required_columns", []),
        })'''

if old_accounts_endpoint not in src:
    print("ERROR: Could not find accounts endpoint to patch")
else:
    src = src.replace(old_accounts_endpoint, new_accounts_endpoint)
    print("OK: Updated accounts endpoint to show combined columns")

with open(APP_PY, "w") as f:
    f.write(src)
print("DONE: Patch applied successfully")
