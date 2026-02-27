"""
Google Sheets sync for CSL Document Tracker.
Periodically reads the master Google Sheet to sync load references into the database.
"""

import logging
import sys
import time

import gspread
from google.oauth2.service_account import Credentials

import config
import database as db
import load_matcher

log = logging.getLogger(__name__)

SCOPES = [
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]


def _get_sheets_client() -> gspread.Client:
    creds = Credentials.from_service_account_file(
        config.GOOGLE_SHEETS_CREDENTIALS_PATH, scopes=SCOPES
    )
    return gspread.authorize(creds)


def _determine_account(tab_name: str) -> str:
    """Map a tab name to an account category."""
    name_lower = tab_name.lower()
    if "boviet" in name_lower:
        return "Boviet"
    if "tolead" in name_lower:
        return "Tolead"
    return "EFJ-Operations"


def _read_tab_with_retry(ws, max_retries=3):
    """Read a worksheet tab with retry on quota (429) errors."""
    for attempt in range(max_retries):
        try:
            return ws.get_all_values()
        except gspread.exceptions.APIError as e:
            if e.response.status_code == 429 and attempt < max_retries - 1:
                wait = 60 * (attempt + 1)  # 60s, 120s, 180s
                log.warning("Quota exceeded reading tab '%s' — waiting %ds", ws.title, wait)
                time.sleep(wait)
            else:
                raise


def sync_once():
    """
    Read all non-skipped tabs from the Google Sheet.
    For each row, upsert the load and all its references into the database.
    """
    try:
        client = _get_sheets_client()
        spreadsheet = client.open_by_key(config.GOOGLE_SHEETS_ID)
    except Exception:
        log.exception("Failed to connect to Google Sheets — will retry next cycle")
        return

    worksheets = spreadsheet.worksheets()
    column_mapping = config.SHEET_COLUMN_MAPPING

    total_loads = 0
    total_refs = 0

    for ws in worksheets:
        if ws.title in config.SHEET_SKIP_TABS:
            continue

        # Throttle between tab reads to avoid Sheets API quota (60 reads/min)
        time.sleep(5)

        try:
            rows = _read_tab_with_retry(ws)
        except Exception:
            log.warning("Failed to read tab '%s' — skipping", ws.title, exc_info=True)
            continue

        if not rows:
            continue

        header = rows[0]
        # Build column index mapping: header_name → column_index
        header_index = {h.strip(): i for i, h in enumerate(header)}

        # Find the columns that map to reference types
        ref_columns = {}  # ref_type → col_index
        for header_name, ref_type in column_mapping.items():
            if header_name in header_index:
                ref_columns[ref_type] = header_index[header_name]

        if "efj" not in ref_columns:
            # Can't process rows without an EFJ column
            log.debug("Tab '%s' has no EFJ column — skipping", ws.title)
            continue

        efj_col = ref_columns["efj"]
        account = _determine_account(ws.title)

        # Optional metadata columns
        cust_ref_col = header_index.get(config.SHEET_CUSTOMER_REF_COLUMN)
        cust_name_col = header_index.get(config.SHEET_CUSTOMER_NAME_COLUMN)

        for row in rows[1:]:
            if efj_col >= len(row):
                continue
            efj_num = row[efj_col].strip()
            if not efj_num:
                continue

            customer_ref = row[cust_ref_col].strip() if cust_ref_col and cust_ref_col < len(row) else None
            customer_name = row[cust_name_col].strip() if cust_name_col and cust_name_col < len(row) else ws.title

            load_id = db.upsert_load(
                load_number=efj_num,
                customer_ref=customer_ref,
                customer_name=customer_name or ws.title,
                account=account,
            )
            db.ensure_checklist(load_id)
            total_loads += 1

            # Upsert all references for this row
            for ref_type, col_idx in ref_columns.items():
                if col_idx < len(row):
                    val = row[col_idx].strip()
                    if val:
                        db.upsert_reference(load_id, ref_type, val)
                        total_refs += 1

    # Rebuild the in-memory lookup table after sync
    load_matcher.rebuild_lookup()
    log.info(
        "Sheets sync complete: %d loads, %d references synced. Lookup has %d entries.",
        total_loads, total_refs, load_matcher.get_lookup_size(),
    )


def run_loop():
    """Run sync in a loop forever."""
    interval = config.SHEET_SYNC_INTERVAL_MINUTES * 60
    log.info("Sheets sync loop starting (interval=%d min)", config.SHEET_SYNC_INTERVAL_MINUTES)

    while True:
        try:
            sync_once()
        except Exception:
            log.exception("Unhandled error in sheets sync cycle")
        time.sleep(interval)


def main():
    logging.basicConfig(
        level=getattr(logging, config.LOG_LEVEL),
        format="%(asctime)s [%(name)s] %(levelname)s: %(message)s",
        handlers=[
            logging.StreamHandler(sys.stdout),
            logging.FileHandler(config.LOG_FILE),
        ],
    )
    db.init_pool()
    try:
        run_loop()
    except KeyboardInterrupt:
        log.info("Sheets sync stopped by user")
    finally:
        db.close_pool()


if __name__ == "__main__":
    main()
