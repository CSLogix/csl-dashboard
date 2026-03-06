"""Fix: Update quote_settings DB with correct default accessorial values"""
import json
import subprocess

accessorials = [
    {"charge": "Storage", "rate": "45.00", "frequency": "per day", "checked": False, "amount": "45.00"},
    {"charge": "Pre-Pull", "rate": "150.00", "frequency": "flat", "checked": False, "amount": "150.00"},
    {"charge": "Chassis (2 days)", "rate": "45.00", "frequency": "per day", "checked": False, "amount": "45.00"},
    {"charge": "Overweight", "rate": "150.00", "frequency": "flat", "checked": False, "amount": "150.00"},
    {"charge": "Detention", "rate": "85.00", "frequency": "per hour", "checked": False, "amount": "85.00"},
]

json_str = json.dumps(accessorials)
sql = f"UPDATE quote_settings SET default_accessorials = '{json_str}' WHERE id = 1;"
result = subprocess.run(
    ["sudo", "-u", "postgres", "psql", "-d", "csl_doc_tracker", "-c", sql],
    capture_output=True, text=True
)
print(result.stdout or result.stderr)
