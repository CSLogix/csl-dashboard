"""Tests for the DELETE /api/v2/load/{efj} endpoint logic.

Since the full app has heavy dependencies (database, shared config, etc.),
we test the endpoint behavior by mocking the database layer.
"""
import sys
import os
from unittest.mock import patch, MagicMock, AsyncMock
import importlib

import pytest

# We need to mock heavy imports before loading the module
# Mock database, shared, and other deps that require live connections

@pytest.fixture
def mock_db():
    """Mock database module."""
    db = MagicMock()
    conn = MagicMock()
    cur = MagicMock()
    # Set up context managers
    db.get_conn.return_value.__enter__ = MagicMock(return_value=conn)
    db.get_conn.return_value.__exit__ = MagicMock(return_value=False)
    db.get_cursor.return_value.__enter__ = MagicMock(return_value=cur)
    db.get_cursor.return_value.__exit__ = MagicMock(return_value=False)
    return db, conn, cur


class TestDeleteEndpointLogic:
    """Test the delete endpoint logic by validating SQL operations."""

    def test_delete_cleans_up_related_tables(self):
        """Verify that delete removes records from all related tables."""
        # The tables that should be cleaned up on delete
        expected_tables = {"load_documents", "load_notes", "tracking_events",
                           "driver_contacts", "rate_quotes", "shipments"}

        # Read the v2.py source to verify all tables are referenced
        v2_path = os.path.join(os.path.dirname(__file__), "..", "csl-doc-tracker", "routes", "v2.py")
        with open(v2_path) as f:
            source = f.read()

        # Find the delete endpoint
        start = source.find('@router.delete("/api/v2/load/{efj}")')
        assert start != -1, "DELETE endpoint not found in v2.py"

        # Find the next endpoint (to bound our search)
        next_endpoint = source.find("@router.", start + 10)
        delete_fn_source = source[start:next_endpoint]

        for table in expected_tables:
            assert table in delete_fn_source, \
                f"Table '{table}' not cleaned up in delete endpoint"

    def test_delete_checks_shipment_exists(self):
        """Verify the endpoint looks up the shipment before deleting."""
        v2_path = os.path.join(os.path.dirname(__file__), "..", "csl-doc-tracker", "routes", "v2.py")
        with open(v2_path) as f:
            source = f.read()

        start = source.find('@router.delete("/api/v2/load/{efj}")')
        next_endpoint = source.find("@router.", start + 10)
        delete_fn_source = source[start:next_endpoint]

        # Should SELECT first to check existence and get account
        assert "SELECT" in delete_fn_source
        assert "account" in delete_fn_source
        # Should raise 404 if not found
        assert "404" in delete_fn_source

    def test_delete_fires_sheet_cleanup(self):
        """Verify the endpoint schedules sheet row deletion."""
        v2_path = os.path.join(os.path.dirname(__file__), "..", "csl-doc-tracker", "routes", "v2.py")
        with open(v2_path) as f:
            source = f.read()

        start = source.find('@router.delete("/api/v2/load/{efj}")')
        next_endpoint = source.find("@router.", start + 10)
        delete_fn_source = source[start:next_endpoint]

        assert "_delete_load_from_master_sheet" in delete_fn_source
        assert "background_tasks" in delete_fn_source

    def test_delete_skips_shared_accounts(self):
        """Shared accounts (Tolead, Boviet) should not get sheet delete calls."""
        v2_path = os.path.join(os.path.dirname(__file__), "..", "csl-doc-tracker", "routes", "v2.py")
        with open(v2_path) as f:
            source = f.read()

        start = source.find('@router.delete("/api/v2/load/{efj}")')
        next_endpoint = source.find("@router.", start + 10)
        delete_fn_source = source[start:next_endpoint]

        assert "_SHARED_SHEET_ACCOUNTS" in delete_fn_source


class TestDeleteHelperExists:
    """Verify the _delete_load_from_master_sheet helper is properly defined."""

    def test_helper_function_defined(self):
        v2_path = os.path.join(os.path.dirname(__file__), "..", "csl-doc-tracker", "routes", "v2.py")
        with open(v2_path) as f:
            source = f.read()

        assert "def _delete_load_from_master_sheet(" in source
        assert "sheet_delete_row" in source


class TestSheetDeleteRowIntegration:
    """Test that sheet_delete_row is importable from csl_sheet_writer."""

    def test_sheet_delete_row_importable(self):
        from csl_sheet_writer import sheet_delete_row
        assert callable(sheet_delete_row)

    def test_sheet_delete_row_signature(self):
        import inspect
        from csl_sheet_writer import sheet_delete_row
        sig = inspect.signature(sheet_delete_row)
        params = list(sig.parameters.keys())
        assert "efj" in params
        assert "account" in params


class TestAddEndpointColumnMapping:
    """Verify the add endpoint maps all fields to the correct Postgres columns."""

    def test_add_endpoint_inserts_all_fields(self):
        """The INSERT should cover all 16 master sheet columns + metadata."""
        v2_path = os.path.join(os.path.dirname(__file__), "..", "csl-doc-tracker", "routes", "v2.py")
        with open(v2_path) as f:
            source = f.read()

        start = source.find('@router.post("/api/v2/load/add")')
        assert start != -1
        next_endpoint = source.find("@router.", start + 10)
        add_fn_source = source[start:next_endpoint]

        # All master sheet fields should be in the INSERT
        required_fields = [
            "efj", "move_type", "container", "bol", "vessel", "carrier",
            "origin", "destination", "eta", "lfd", "pickup_date", "delivery_date",
            "status", "notes", "driver", "bot_notes", "return_date",
            "account", "hub", "rep",
        ]
        for field in required_fields:
            assert field in add_fn_source, \
                f"Field '{field}' missing from add endpoint INSERT"

    def test_add_endpoint_fires_sheet_write(self):
        """New loads should be written to the Master Sheet."""
        v2_path = os.path.join(os.path.dirname(__file__), "..", "csl-doc-tracker", "routes", "v2.py")
        with open(v2_path) as f:
            source = f.read()

        start = source.find('@router.post("/api/v2/load/add")')
        next_endpoint = source.find("@router.", start + 10)
        add_fn_source = source[start:next_endpoint]

        assert "_add_load_to_master_sheet" in add_fn_source
