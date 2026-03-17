"""Tests for csl_sheet_writer.py — verifying loads are written to the correct
Google Sheet tab with proper column mapping."""
import sys
import os
from unittest.mock import patch, MagicMock, call

import pytest

# Import the module under test
from csl_sheet_writer import (
    sheet_add_row, sheet_delete_row, sheet_update_field,
    sheet_update_import, sheet_update_ftl, sheet_update_export,
    _fmt_status, _fmt_eta, _find_row_by_efj, _tab_cols,
    PG_TO_SHEET_COL, PG_STATUS_TO_SHEET, TAB_COL_OVERRIDES,
    MASTER_SHEET_ID,
)


# ═══ Unit Tests: Status Formatting ══════════════════════════════════════════

class TestFormatStatus:
    def test_maps_snake_case_to_display(self):
        assert _fmt_status("at_port") == "At Port"
        assert _fmt_status("delivered") == "Delivered"
        assert _fmt_status("empty_return") == "Empty Return"
        assert _fmt_status("in_transit") == "In Transit"

    def test_maps_ftl_statuses(self):
        assert _fmt_status("picking_up") == "Picking Up"
        assert _fmt_status("at_delivery") == "At Delivery"
        assert _fmt_status("need_pod") == "Need POD"

    def test_maps_billing_statuses(self):
        assert _fmt_status("billed_closed") == "Billed & Closed"
        assert _fmt_status("ready_to_close") == "Ready to Close"

    def test_passthrough_already_formatted(self):
        assert _fmt_status("Vessel Arrived") == "Vessel Arrived"
        assert _fmt_status("Discharged") == "Discharged"
        assert _fmt_status("Released") == "Released"

    def test_none_and_empty(self):
        assert _fmt_status(None) is None
        assert _fmt_status("") == ""

    def test_unknown_passes_through(self):
        assert _fmt_status("some_unknown_status") == "some_unknown_status"


# ═══ Unit Tests: ETA Formatting ═════════════════════════════════════════════

class TestFormatEta:
    def test_iso_date(self):
        assert _fmt_eta("2026-03-10") == "03/10"

    def test_iso_datetime(self):
        assert _fmt_eta("2026-03-10 06:00") == "03/10"

    def test_already_formatted(self):
        assert _fmt_eta("03/10") == "03/10"

    def test_none_and_empty(self):
        assert _fmt_eta(None) is None
        assert _fmt_eta("") == ""


# ═══ Unit Tests: Tab Column Overrides ════════════════════════════════════════

class TestTabCols:
    def test_default_columns(self):
        botnotes, return_col = _tab_cols("DHL")
        assert botnotes == "O"
        assert return_col == "P"

    def test_override_columns(self):
        botnotes, return_col = _tab_cols("GW-World")
        assert botnotes == "N"
        assert return_col == "O"

    def test_mamata_override(self):
        botnotes, return_col = _tab_cols("Mamata")
        assert botnotes == "N"
        assert return_col == "O"


# ═══ Unit Tests: Column Mapping Completeness ═════════════════════════════════

class TestColumnMapping:
    """Verify that the PG→Sheet column map covers all 16 master columns."""

    def test_all_fields_mapped(self):
        expected_fields = {
            "move_type", "container", "bol", "vessel", "carrier",
            "origin", "destination", "eta", "lfd", "pickup_date",
            "delivery_date", "status", "driver", "bot_notes", "return_date",
        }
        assert expected_fields.issubset(set(PG_TO_SHEET_COL.keys()))

    def test_column_letters_unique(self):
        values = list(PG_TO_SHEET_COL.values())
        assert len(values) == len(set(values)), "Duplicate column letters in PG_TO_SHEET_COL"

    def test_column_letters_in_range(self):
        for field, col in PG_TO_SHEET_COL.items():
            assert col in "ABCDEFGHIJKLMNOP", f"Column {col} for {field} is outside A-P range"


# ═══ Integration Tests: sheet_add_row ════════════════════════════════════════

class TestSheetAddRow:
    @patch("csl_sheet_writer._get_gc")
    def test_adds_row_to_correct_tab(self, mock_gc):
        mock_ws = MagicMock()
        mock_sh = MagicMock()
        mock_sh.worksheet.return_value = mock_ws
        mock_gc.return_value.open_by_key.return_value = mock_sh

        # EFJ not already in sheet
        mock_ws.col_values.return_value = ["EFJ100001", "EFJ100002"]

        data = {
            "move_type": "Dray Import",
            "container": "MAEU1234567",
            "bol": "BOL999",
            "vessel": "MSC ANNA",
            "carrier": "Universal Carrier",
            "origin": "Port Newark, NJ",
            "destination": "Columbus, OH",
            "eta": "2026-03-15",
            "lfd": "2026-03-18",
            "pickup_date": "",
            "delivery_date": "",
            "status": "at_port",
            "driver": "",
            "bot_notes": "",
            "return_date": "",
        }

        sheet_add_row("EFJ107500", "DHL", data)

        # Verify opened correct sheet
        mock_gc.return_value.open_by_key.assert_called_once_with(MASTER_SHEET_ID)
        # Verify correct tab
        mock_sh.worksheet.assert_called_once_with("DHL")
        # Verify append_row was called
        mock_ws.append_row.assert_called_once()

        row = mock_ws.append_row.call_args[0][0]
        assert len(row) == 16, f"Row should have 16 columns (A-P), got {len(row)}"
        assert row[0] == "EFJ107500"       # Col A: EFJ
        assert row[1] == "Dray Import"     # Col B: Move Type
        assert row[2] == "MAEU1234567"     # Col C: Container
        assert row[3] == "BOL999"          # Col D: BOL
        assert row[4] == "MSC ANNA"        # Col E: Vessel
        assert row[5] == "Universal Carrier"  # Col F: Carrier
        assert row[6] == "Port Newark, NJ"   # Col G: Origin
        assert row[7] == "Columbus, OH"       # Col H: Destination
        assert row[8] == "2026-03-15"         # Col I: ETA
        assert row[9] == "2026-03-18"         # Col J: LFD
        assert row[12] == "At Port"           # Col M: Status (formatted)

    @patch("csl_sheet_writer._get_gc")
    def test_skips_duplicate_efj(self, mock_gc):
        mock_ws = MagicMock()
        mock_sh = MagicMock()
        mock_sh.worksheet.return_value = mock_ws
        mock_gc.return_value.open_by_key.return_value = mock_sh

        # EFJ already exists in sheet
        mock_ws.col_values.return_value = ["EFJ107500", "EFJ100002"]

        sheet_add_row("EFJ107500", "DHL", {"move_type": "FTL"})

        # Should NOT call append_row since EFJ already exists
        mock_ws.append_row.assert_not_called()

    @patch("csl_sheet_writer._get_gc")
    def test_status_formatted_for_sheet(self, mock_gc):
        mock_ws = MagicMock()
        mock_sh = MagicMock()
        mock_sh.worksheet.return_value = mock_ws
        mock_gc.return_value.open_by_key.return_value = mock_sh
        mock_ws.col_values.return_value = []  # No existing rows

        sheet_add_row("EFJ999", "Allround", {"status": "in_transit"})

        row = mock_ws.append_row.call_args[0][0]
        assert row[12] == "In Transit", "Status should be formatted for sheet dropdown"


# ═══ Integration Tests: sheet_delete_row ═════════════════════════════════════

class TestSheetDeleteRow:
    @patch("csl_sheet_writer._get_gc")
    def test_deletes_correct_row(self, mock_gc):
        mock_ws = MagicMock()
        mock_sh = MagicMock()
        mock_sh.worksheet.return_value = mock_ws
        mock_gc.return_value.open_by_key.return_value = mock_sh

        # EFJ at row 3 (1-indexed)
        mock_ws.col_values.return_value = ["Header", "EFJ100001", "EFJ107500", "EFJ100002"]

        sheet_delete_row("EFJ107500", "DHL")

        mock_sh.worksheet.assert_called_once_with("DHL")
        mock_ws.delete_rows.assert_called_once_with(3)  # Row 3 (1-indexed)

    @patch("csl_sheet_writer._get_gc")
    def test_noop_when_efj_not_found(self, mock_gc):
        mock_ws = MagicMock()
        mock_sh = MagicMock()
        mock_sh.worksheet.return_value = mock_ws
        mock_gc.return_value.open_by_key.return_value = mock_sh

        mock_ws.col_values.return_value = ["Header", "EFJ100001"]

        sheet_delete_row("EFJ999999", "DHL")

        mock_ws.delete_rows.assert_not_called()

    @patch("csl_sheet_writer._get_gc")
    def test_handles_missing_tab(self, mock_gc):
        mock_sh = MagicMock()
        mock_sh.worksheet.side_effect = Exception("Worksheet not found")
        mock_gc.return_value.open_by_key.return_value = mock_sh

        # Should not raise — fire-and-forget
        sheet_delete_row("EFJ107500", "NonExistentTab")


# ═══ Integration Tests: sheet_update_field ═══════════════════════════════════

class TestSheetUpdateField:
    @patch("csl_sheet_writer._get_gc")
    def test_writes_correct_columns(self, mock_gc):
        mock_ws = MagicMock()
        mock_sh = MagicMock()
        mock_sh.worksheet.return_value = mock_ws
        mock_gc.return_value.open_by_key.return_value = mock_sh
        mock_ws.col_values.return_value = ["Header", "EFJ107500"]

        sheet_update_field("EFJ107500", "DHL", {
            "carrier": "New Carrier",
            "origin": "Chicago, IL",
        })

        # Should batch_update with RAW for non-status fields
        calls = mock_ws.batch_update.call_args_list
        assert len(calls) == 1
        updates = calls[0][0][0]
        ranges = {u["range"] for u in updates}
        assert "F2" in ranges  # Carrier is col F, row 2
        assert "G2" in ranges  # Origin is col G, row 2

    @patch("csl_sheet_writer._get_gc")
    def test_status_uses_user_entered(self, mock_gc):
        mock_ws = MagicMock()
        mock_sh = MagicMock()
        mock_sh.worksheet.return_value = mock_ws
        mock_gc.return_value.open_by_key.return_value = mock_sh
        mock_ws.col_values.return_value = ["Header", "EFJ107500"]

        sheet_update_field("EFJ107500", "DHL", {"status": "delivered"})

        calls = mock_ws.batch_update.call_args_list
        # Status should be USER_ENTERED (for dropdown validation)
        status_call = [c for c in calls if c[1].get("value_input_option") == "USER_ENTERED"]
        assert len(status_call) == 1
        assert status_call[0][0][0][0]["values"] == [["Delivered"]]


# ═══ Integration Tests: sheet_update_import ══════════════════════════════════

class TestSheetUpdateImport:
    @patch("csl_sheet_writer._get_gc")
    def test_writes_eta_pickup_return_status(self, mock_gc):
        mock_ws = MagicMock()
        mock_sh = MagicMock()
        mock_sh.worksheet.return_value = mock_ws
        mock_gc.return_value.open_by_key.return_value = mock_sh
        mock_ws.col_values.return_value = ["Header", "EFJ107500"]

        sheet_update_import("EFJ107500", "DHL",
                            eta="2026-03-15", pickup="03/20",
                            return_date="03/25", status="delivered")

        # Should have both RAW and USER_ENTERED batch_update calls
        calls = mock_ws.batch_update.call_args_list
        assert len(calls) == 2  # RAW updates + status

        raw_updates = calls[0][0][0]
        raw_ranges = {u["range"] for u in raw_updates}
        assert "I2" in raw_ranges   # ETA col I
        assert "K2" in raw_ranges   # Pickup col K
        assert "P2" in raw_ranges   # Return col P
        assert "O2" in raw_ranges   # Bot notes col O


# ═══ Find Row Tests ═════════════════════════════════════════════════════════

class TestFindRowByEfj:
    def test_finds_exact_match(self):
        mock_ws = MagicMock()
        mock_ws.col_values.return_value = ["Header", "EFJ100", "EFJ200", "EFJ300"]
        assert _find_row_by_efj(mock_ws, "EFJ200") == 3  # 1-indexed

    def test_strips_whitespace(self):
        mock_ws = MagicMock()
        mock_ws.col_values.return_value = ["Header", "EFJ100 ", " EFJ200"]
        assert _find_row_by_efj(mock_ws, "EFJ200") == 3

    def test_returns_none_when_not_found(self):
        mock_ws = MagicMock()
        mock_ws.col_values.return_value = ["Header", "EFJ100"]
        assert _find_row_by_efj(mock_ws, "EFJ999") is None
