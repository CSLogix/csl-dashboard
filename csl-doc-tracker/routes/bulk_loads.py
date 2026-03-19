import csv
import io
import logging
import sys
from datetime import datetime
from io import BytesIO

import xlrd
from fastapi import APIRouter, Request
from fastapi.responses import JSONResponse

import database as db
from shared import log

router = APIRouter()

# ─── Keyword-to-field mapping for auto-detection ───
FIELD_KEYWORDS = {
    "efj": ["efj", "efj#", "efj #", "pro_number", "pro number", "pro#", "pro", "order", "order#", "order #", "load", "load#"],
    "move_type": ["move_type", "move type", "movetype", "mode", "service"],
    "container": ["container", "container#", "cntr", "equipment_number", "unit"],
    "bol": ["bol", "booking", "mbl", "bl#", "booking#", "mbl#", "ref_3"],
    "vessel": ["vessel", "ship", "ssl", "steamship"],
    "carrier": ["carrier", "trucker", "drayage", "scac", "motor carrier", "tractor_name"],
    "origin": ["origin", "from_city", "pickup city", "from city", "shipper", "port of loading", "pol"],
    "destination": ["destination", "to_city", "delivery city", "to city", "consignee", "port of discharge"],
    "eta": ["eta", "arrival", "estimated arrival", "erd"],
    "lfd": ["lfd", "last free", "cutoff", "free time", "demurrage"],
    "pickup_date": ["pu_appt_date", "pickup_date", "pickup date", "pickup", "pick up", "p/u", "p/u date", "pu_appt"],
    "delivery_date": ["dlv_appt_date", "delivery_date", "delivery date", "del date", "dliv", "dlv_appt"],
    "status": ["status"],
    "notes": ["notes", "remarks", "comments", "instructions", "special"],
    "carrier_pay": ["driverpay_total", "driverpay", "carrier_pay", "carrier pay", "carrier cost", "carrier rate", "buy"],
    "driver": ["driver_name", "driver name", "driver"],
    "account": ["account", "bill_to_name", "bill_to", "bill to", "billto", "customer", "client"],
    "customer_rate": ["total_billed", "customer rate", "customer_rate", "revenue", "cx rate", "sell", "line haul"],
    "hub": ["hub", "project", "facility", "terminal"],
}

# Short keywords that should only match as whole words/tokens, not substrings
_SHORT_KEYWORDS = {"pro", "from", "to", "buy", "ship", "mode", "cost", "sell"}

ACCOUNT_REPS = {
    "Allround": "Radka", "Boviet": "Radka", "Cadi": "Radka",
    "DHL": "Janice", "DSV": "Janice", "EShipping": "Janice",
    "IWS": "Janice", "Kripke": "Janice", "MAO": "Janice",
    "MGF": "John F", "Rose": "Radka", "USHA": "Radka",
    "Tolead": "Radka", "Prolog": "Radka", "Talatrans": "Radka",
    "LS Cargo": "Radka", "GW-World": "John F",
}

_SHARED_ACCOUNTS = {"Boviet", "Tolead"}


def _safe_date(val):
    """Parse various date formats to YYYY-MM-DD string."""
    if not val:
        return ""
    s = str(val).strip()
    if not s or s.lower() in ("none", "nan", "nat"):
        return ""
    # Already YYYY-MM-DD
    if len(s) >= 10 and s[4] == "-" and s[7] == "-":
        return s[:10]
    for fmt in ("%m/%d/%Y", "%m/%d/%y", "%Y-%m-%d", "%m-%d-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).strftime("%Y-%m-%d")
        except ValueError:
            continue
    # Excel float date
    try:
        fv = float(s)
        if 30000 < fv < 60000:
            from datetime import timedelta
            epoch = datetime(1899, 12, 30)
            return (epoch + timedelta(days=fv)).strftime("%Y-%m-%d")
    except (ValueError, TypeError):
        pass
    return s  # Return as-is if unparseable


def _safe_float(val):
    """Parse numeric value, return None if not a number."""
    if val is None:
        return None
    s = str(val).strip().replace("$", "").replace(",", "")
    if not s or s.lower() in ("none", "nan", ""):
        return None
    try:
        return float(s)
    except (ValueError, TypeError):
        return None


def _detect_header_row(rows: list, max_scan: int = 5) -> int:
    """Find the header row by looking for shipment-related keywords."""
    keywords = {"efj", "order", "container", "carrier", "origin", "destination",
                "bol", "booking", "pickup", "delivery", "status", "move", "account"}
    best_row, best_score = 0, 0
    for idx, row in enumerate(rows[:max_scan]):
        score = 0
        for cell in row:
            cell_lower = str(cell).strip().lower() if cell else ""
            for kw in keywords:
                if kw in cell_lower:
                    score += 1
                    break
        if score > best_score:
            best_score = score
            best_row = idx
    return best_row


def _auto_map_columns(headers: list) -> dict:
    """Map column indices to shipment fields using fuzzy keyword matching."""
    import re
    mappings = {}
    used_fields = set()

    for col_idx, header in enumerate(headers):
        h = str(header).strip().lower()
        if not h or h.startswith("col"):
            continue

        best_field = None
        best_match_len = -1  # Prefer longer keyword matches

        for field, keywords in FIELD_KEYWORDS.items():
            if field in used_fields:
                continue
            for kw in keywords:
                kw_lower = kw.lower()
                # Exact match (case-insensitive) — always wins
                if h == kw_lower:
                    best_field = field
                    best_match_len = 9999
                    break
                # Substring match — prefer longest matching keyword
                if kw_lower in h and len(kw_lower) > best_match_len:
                    if kw_lower in _SHORT_KEYWORDS:
                        tokens = re.split(r'[_\s]+', h)
                        if kw_lower not in tokens:
                            continue
                    best_field = field
                    best_match_len = len(kw_lower)
            if best_match_len == 9999:
                break  # Exact match found, stop searching

        if best_field:
            mappings[str(col_idx)] = best_field
            used_fields.add(best_field)

    return mappings


def _parse_file(file_bytes: bytes, filename: str) -> tuple:
    """Parse CSV/XLS/XLSX file. Returns (headers, data_rows) where data_rows are lists of strings."""
    fname = filename.lower()

    if fname.endswith(".csv") or fname.endswith(".tsv"):
        text = file_bytes.decode("utf-8-sig", errors="replace")
        try:
            dialect = csv.Sniffer().sniff(text[:4096])
        except csv.Error:
            dialect = csv.excel
        reader = csv.reader(io.StringIO(text), dialect)
        all_rows = [row for row in reader if any(c.strip() for c in row)]

    elif fname.endswith(".xls"):
        wb = xlrd.open_workbook(file_contents=file_bytes)
        ws = wb.sheet_by_index(0)
        all_rows = []
        for r in range(ws.nrows):
            row = []
            for c in range(ws.ncols):
                val = ws.cell_value(r, c)
                if ws.cell_type(r, c) == xlrd.XL_CELL_DATE:
                    try:
                        dt = xlrd.xldate_as_datetime(val, wb.datemode)
                        val = dt.strftime("%Y-%m-%d")
                    except Exception:
                        val = str(val)
                row.append(str(val) if val is not None else "")
            all_rows.append(row)

    elif fname.endswith(".xlsx") or fname.endswith(".xlsm"):
        import openpyxl
        wb = openpyxl.load_workbook(BytesIO(file_bytes), read_only=True, data_only=True)
        ws = wb.active
        all_rows = []
        for row in ws.iter_rows(values_only=True):
            processed = []
            for v in row:
                if hasattr(v, "strftime"):
                    processed.append(v.strftime("%Y-%m-%d"))
                elif v is not None:
                    processed.append(str(v))
                else:
                    processed.append("")
            all_rows.append(processed)
        wb.close()
    else:
        raise ValueError(f"Unsupported file type: {filename}")

    if not all_rows:
        return [], []

    header_idx = _detect_header_row(all_rows)
    headers = [str(h).strip() if h else f"col{i}" for i, h in enumerate(all_rows[header_idx])]
    data_rows = all_rows[header_idx + 1:]

    # Filter out completely empty rows
    data_rows = [r for r in data_rows if any(str(c).strip() for c in r)]

    return headers, data_rows


# ─── Endpoints ───

@router.post("/api/loads/bulk-upload/preview")
async def bulk_upload_preview(request: Request):
    """Parse uploaded file and return headers, auto-mapped columns, and all rows."""
    form = await request.form()
    file = form.get("file")
    if not file:
        return JSONResponse({"error": "No file provided"}, status_code=400)

    filename = file.filename
    file_bytes = await file.read()

    try:
        headers, data_rows = _parse_file(file_bytes, filename)
    except Exception as e:
        log.error("bulk_upload_preview parse error: %s", e)
        return JSONResponse({"error": f"Failed to parse file: {e}"}, status_code=400)

    if not headers:
        return JSONResponse({"error": "No data found in file"}, status_code=400)

    mappings = _auto_map_columns(headers)

    # Convert data rows to list of dicts keyed by string column index
    rows = []
    for row in data_rows:
        row_dict = {}
        for i, h in enumerate(headers):
            val = row[i] if i < len(row) else ""
            row_dict[str(i)] = str(val).strip() if val else ""
        rows.append(row_dict)

    return JSONResponse({
        "headers": headers,
        "mappings": mappings,
        "rows": rows,
        "total_rows": len(rows),
    })


@router.post("/api/loads/bulk-upload/create")
async def bulk_upload_create(request: Request):
    """Create shipments from mapped rows."""
    body = await request.json()
    loads = body.get("loads", [])
    defaults = body.get("defaults", {})

    if not loads:
        return JSONResponse({"error": "No loads provided"}, status_code=400)

    created = []
    skipped = []
    errors = []

    for load in loads:
        # Merge defaults where field is empty
        for key, val in defaults.items():
            if val and not load.get(key):
                load[key] = val

        efj = (load.get("efj") or "").strip()
        # Auto-prefix EFJ if the value is numeric-only (TMS Pro_Number format)
        if efj and efj.isdigit():
            efj = f"EFJ{efj}"
            load["efj"] = efj
        elif efj and not efj.upper().startswith("EFJ"):
            efj = f"EFJ{efj}"
            load["efj"] = efj
        account = (load.get("account") or "").strip()
        if not efj or not account:
            errors.append({"efj": efj or "(blank)", "reason": "Missing EFJ or account"})
            continue

        rep = load.get("rep") or ACCOUNT_REPS.get(account, "Unassigned")

        # Parse dates
        eta = _safe_date(load.get("eta"))
        lfd = _safe_date(load.get("lfd"))
        pickup = _safe_date(load.get("pickup_date"))
        delivery = _safe_date(load.get("delivery_date"))

        # Parse rates
        cust_rate = _safe_float(load.get("customer_rate"))
        carr_pay = _safe_float(load.get("carrier_pay"))

        try:
            with db.get_conn() as conn:
                with db.get_cursor(conn) as cur:
                    cur.execute("""
                        INSERT INTO shipments (
                            efj, move_type, container, bol, vessel, carrier,
                            origin, destination, eta, lfd, pickup_date, delivery_date,
                            status, notes, driver, bot_notes, return_date,
                            account, hub, rep, source, customer_rate, carrier_pay
                        ) VALUES (
                            %(efj)s, %(move_type)s, %(container)s, %(bol)s, %(vessel)s, %(carrier)s,
                            %(origin)s, %(destination)s, %(eta)s, %(lfd)s, %(pickup_date)s, %(delivery_date)s,
                            %(status)s, %(notes)s, %(driver)s, %(bot_notes)s, %(return_date)s,
                            %(account)s, %(hub)s, %(rep)s, 'bulk_upload', %(customer_rate)s, %(carrier_pay)s
                        )
                        ON CONFLICT (efj) DO NOTHING
                        RETURNING efj
                    """, {
                        "efj": efj,
                        "move_type": load.get("move_type", ""),
                        "container": load.get("container", ""),
                        "bol": load.get("bol", ""),
                        "vessel": load.get("vessel", ""),
                        "carrier": load.get("carrier", ""),
                        "origin": load.get("origin", ""),
                        "destination": load.get("destination", ""),
                        "eta": eta or None,
                        "lfd": lfd or None,
                        "pickup_date": pickup or None,
                        "delivery_date": delivery or None,
                        "status": load.get("status", "pending"),
                        "notes": load.get("notes", ""),
                        "driver": load.get("driver", ""),
                        "bot_notes": f"Bulk upload on {datetime.now().strftime('%m/%d %H:%M')}",
                        "return_date": load.get("return_date") or None,
                        "account": account,
                        "hub": load.get("hub", ""),
                        "rep": rep,
                        "customer_rate": cust_rate,
                        "carrier_pay": carr_pay,
                    })
                    row = cur.fetchone()
                    if row:
                        created.append(efj)
                    else:
                        skipped.append({"efj": efj, "reason": "Already exists"})
        except Exception as e:
            log.error("bulk_upload_create error for %s: %s", efj, e)
            errors.append({"efj": efj, "reason": str(e)})

    # Fire-and-forget sheet writes
    if created:
        try:
            if "/root/csl-bot" in sys.path or "/root/csl-bot/csl-doc-tracker" in sys.path:
                from csl_sheet_writer import sheet_add_row
                for load in loads:
                    efj = (load.get("efj") or "").strip()
                    account = (load.get("account") or "").strip()
                    if efj in created and account not in _SHARED_ACCOUNTS:
                        try:
                            sheet_add_row(efj, account, load)
                        except Exception as e:
                            log.warning("Sheet write failed for %s: %s", efj, e)
        except ImportError:
            log.warning("csl_sheet_writer not available, skipping sheet writes")

    summary = f"Created {len(created)} loads"
    if skipped:
        summary += f", skipped {len(skipped)}"
    if errors:
        summary += f", {len(errors)} errors"

    return JSONResponse({
        "created": created,
        "skipped": skipped,
        "errors": errors,
        "summary": summary,
    })
