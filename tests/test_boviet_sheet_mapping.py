"""Tests for Boviet hub-specific Google Sheet column mappings.

Validates that Piedra and Hanson tabs map to the correct sheet columns,
focusing on loads in transit or assigned status.

Uses source parsing to avoid importing heavy dependencies (FastAPI, etc.)
"""
import ast
import os
import re

import pytest

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


# ═══ Helper: extract BOVIET_TAB_CONFIGS dict from a Python source file ══════

def _extract_boviet_configs(filepath):
    """Parse BOVIET_TAB_CONFIGS from a .py file without importing it."""
    with open(filepath) as f:
        source = f.read()

    # Find the assignment
    match = re.search(
        r'BOVIET_TAB_CONFIGS\s*=\s*\{',
        source,
    )
    assert match, f"BOVIET_TAB_CONFIGS not found in {filepath}"

    # Extract the full dict literal by counting braces
    start = match.start() + len("BOVIET_TAB_CONFIGS = ")
    depth = 0
    end = start
    for i, ch in enumerate(source[start:], start):
        if ch == '{':
            depth += 1
        elif ch == '}':
            depth -= 1
            if depth == 0:
                end = i + 1
                break
    raw = source[start:end]
    return ast.literal_eval(raw)


def _extract_boviet_done_statuses(filepath):
    """Parse BOVIET_DONE_STATUSES from a .py file."""
    with open(filepath) as f:
        source = f.read()
    match = re.search(r'BOVIET_DONE_STATUSES\s*=\s*(\{[^}]+\})', source)
    if not match:
        return None
    return ast.literal_eval(match.group(1))


# ═══ Boviet Sheet Column Layout (ground truth from actual sheets) ════════════
#
# Piedra sheet layout:
#   A=EFJ, B=Rate, C=Load ID, D=BV#, E=PU Location, F=DEL Location,
#   G=Pickup Date/Time, H=Delivery Date/Time, I=Status, J=Truck Type,
#   K=Carrier Email, L=Driver Phone#, M=Trailer#, N=Driver Name, O=NOTE
#
# Hanson sheet layout:
#   A=EFJ, B=Rate, C=Load ID/Container No., D=BV#, E=PU Location, F=Del Location,
#   G=Pick Up Date/Time, H=Del Date/Time, I=Status, J=Truck Type,
#   K=Carrier Email, L=Driver Phone#, M=Driver Name, N=Trailer#


PIEDRA_EXPECTED = {
    "efj_col": 0,            # A: EFJ Pro #
    "load_id_col": 2,        # C: Load ID
    "status_col": 8,         # I: Status
    "pickup_col": 6,         # G: Pickup Date/Time
    "delivery_col": 7,       # H: Delivery Date/Time
    "phone_col": 11,         # L: Driver Phone#
    "trailer_col": 12,       # M: Trailer#
    "carrier_email_col": 10, # K: Carrier Email
    "driver_name_col": 13,   # N: Driver Name
}

HANSON_EXPECTED = {
    "efj_col": 0,            # A: EFJ Pro #
    "load_id_col": 2,        # C: Load ID / Container No.
    "status_col": 8,         # I: Status
    "pickup_col": 6,         # G: Pick Up Date/Time
    "delivery_col": 7,       # H: Del Date/Time
    "phone_col": 11,         # L: Driver Phone#
    "trailer_col": 13,       # N: Trailer#  (swapped vs Piedra!)
    "carrier_email_col": 10, # K: Carrier Email
    "driver_name_col": 12,   # M: Driver Name (swapped vs Piedra!)
}


# ═══ Config file locations ══════════════════════════════════════════════════

CONFIG_FILES = {
    "shared.py": os.path.join(ROOT, "csl-doc-tracker", "shared.py"),
    "csl-doc-tracker/csl_sheet_sync.py": os.path.join(ROOT, "csl-doc-tracker", "csl_sheet_sync.py"),
    "csl_sheet_sync.py (root)": os.path.join(ROOT, "csl_sheet_sync.py"),
    "daily_summary.py": os.path.join(ROOT, "daily_summary.py"),
    "patch_postgres_migration.py": os.path.join(ROOT, "patch_postgres_migration.py"),
}


# ═══ Test: shared.py config ═════════════════════════════════════════════════

class TestSharedPyConfig:
    @pytest.fixture(autouse=True)
    def load_config(self):
        self.configs = _extract_boviet_configs(CONFIG_FILES["shared.py"])

    def test_piedra_column_mapping(self):
        cfg = self.configs["Piedra"]
        for key, expected_val in PIEDRA_EXPECTED.items():
            assert cfg[key] == expected_val, \
                f"Piedra.{key}: expected {expected_val}, got {cfg.get(key)}"

    def test_hanson_column_mapping(self):
        cfg = self.configs["Hanson"]
        for key, expected_val in HANSON_EXPECTED.items():
            assert cfg[key] == expected_val, \
                f"Hanson.{key}: expected {expected_val}, got {cfg.get(key)}"

    def test_hanson_has_default_origin(self):
        cfg = self.configs["Hanson"]
        assert cfg.get("default_origin"), "Hanson should have default_origin"
        assert cfg.get("default_dest"), "Hanson should have default_dest"

    def test_piedra_has_default_origin(self):
        cfg = self.configs["Piedra"]
        assert cfg["default_origin"] == "Greenville, NC"
        assert cfg["default_dest"] == "Mexia, TX"

    def test_hanson_driver_name_trailer_swapped_vs_piedra(self):
        """Hanson has Driver Name at M (12) and Trailer# at N (13),
        while Piedra has Trailer# at M (12) and Driver Name at N (13)."""
        piedra = self.configs["Piedra"]
        hanson = self.configs["Hanson"]
        assert piedra["trailer_col"] == 12
        assert piedra["driver_name_col"] == 13
        assert hanson["driver_name_col"] == 12
        assert hanson["trailer_col"] == 13

    def test_hanson_has_carrier_email_col(self):
        cfg = self.configs["Hanson"]
        assert "carrier_email_col" in cfg
        assert cfg["carrier_email_col"] == 10  # Column K

    def test_hanson_has_driver_name_col(self):
        cfg = self.configs["Hanson"]
        assert "driver_name_col" in cfg
        assert cfg["driver_name_col"] == 12  # Column M


# ═══ Test: All config files have correct Hanson mapping ═════════════════════

class TestAllConfigFilesConsistent:
    """Every file that defines BOVIET_TAB_CONFIGS must have the correct Hanson mapping."""

    @pytest.mark.parametrize("name,path", list(CONFIG_FILES.items()))
    def test_hanson_load_id_not_rate_column(self, name, path):
        """load_id_col must be 2 (C=Container), NOT 1 (B=Rate)."""
        configs = _extract_boviet_configs(path)
        cfg = configs["Hanson"]
        assert cfg["load_id_col"] == 2, \
            f"{name}: Hanson load_id_col is {cfg['load_id_col']} (B=Rate!), should be 2 (C=Container)"

    @pytest.mark.parametrize("name,path", list(CONFIG_FILES.items()))
    def test_hanson_status_col_is_i(self, name, path):
        """status_col must be 8 (I=Status), NOT 6 (G=Pickup Date)."""
        configs = _extract_boviet_configs(path)
        cfg = configs["Hanson"]
        assert cfg["status_col"] == 8, \
            f"{name}: Hanson status_col is {cfg['status_col']} (G=Pickup!), should be 8 (I=Status)"

    @pytest.mark.parametrize("name,path", list(CONFIG_FILES.items()))
    def test_hanson_pickup_col_is_g(self, name, path):
        """pickup_col must be 6 (G=Pickup Date), NOT 4 (E=PU Location)."""
        configs = _extract_boviet_configs(path)
        cfg = configs["Hanson"]
        assert cfg["pickup_col"] == 6, \
            f"{name}: Hanson pickup_col is {cfg['pickup_col']} (E=Location!), should be 6 (G=Pickup)"


# ═══ Test: Simulated Row Parsing ════════════════════════════════════════════

class TestHansonRowParsing:
    """Simulate reading a Hanson sheet row to verify correct field extraction."""

    def _build_hanson_row(self):
        return [
            "EFJ107541",                    # 0  A: EFJ Pro #
            "",                              # 1  B: Rate
            "BEAU4692326",                   # 2  C: Load ID / Container No.
            "BV-250418A",                    # 3  D: BV #
            "Houston, TX",                   # 4  E: PU Location
            "Valera TX",                     # 5  F: Del Location
            "3/16 13:00",                    # 6  G: Pick Up Date/Time
            "3/17 10:00",                    # 7  H: Del Date/Time
            "In Transit",                    # 8  I: Status
            "53' Van",                       # 9  J: Truck Type
            "Candy Santos <candy@mail.com>", # 10 K: Carrier Email
            "281) 415-5329",                 # 11 L: Driver Phone #
            "Felix",                         # 12 M: Driver Name
            "86144",                         # 13 N: Trailer #
        ]

    def test_extract_fields_with_correct_config(self):
        row = self._build_hanson_row()
        cfg = HANSON_EXPECTED

        assert row[cfg["efj_col"]] == "EFJ107541"
        assert row[cfg["load_id_col"]] == "BEAU4692326"
        assert row[cfg["status_col"]] == "In Transit"
        assert row[cfg["pickup_col"]] == "3/16 13:00"
        assert row[cfg["delivery_col"]] == "3/17 10:00"
        assert row[cfg["phone_col"]] == "281) 415-5329"
        assert row[cfg["trailer_col"]] == "86144"
        assert "candy" in row[cfg["carrier_email_col"]].lower()
        assert row[cfg["driver_name_col"]] == "Felix"

    def test_old_wrong_config_would_mismap(self):
        """The OLD config would produce garbage data."""
        row = self._build_hanson_row()
        OLD_WRONG = {
            "load_id_col": 1, "status_col": 6, "pickup_col": 4,
            "delivery_col": 5, "phone_col": 8, "trailer_col": 10,
        }
        assert row[OLD_WRONG["load_id_col"]] == ""         # B=Rate, not a load ID
        assert row[OLD_WRONG["status_col"]] == "3/16 13:00" # G=Pickup, not Status!
        assert row[OLD_WRONG["pickup_col"]] == "Houston, TX" # E=Location, not date!


class TestPiedraRowParsing:
    def _build_piedra_row(self):
        return [
            "EFJ107535",                    # 0  A: EFJ Pro #
            "$2,900.00",                     # 1  B: Rate
            "TT-P-0316-EV-6",               # 2  C: Load ID
            "BSTT-030326P",                  # 3  D: BV #
            "Greenville, NC",                # 4  E: PU Location
            "Mexia, TX",                     # 5  F: DEL Location
            "3/16 16:45",                    # 6  G: Pickup Date/Time
            "3/18 13:30",                    # 7  H: Delivery Date/Time
            "In Transit",                    # 8  I: Status
            "53' Van",                       # 9  J: Truck Type
            "goytomb45@gmail.com",           # 10 K: Carrier Email
            "",                              # 11 L: Driver Phone #
            "",                              # 12 M: Trailer #
            "Goitom Berhane",                # 13 N: Driver Name
            "",                              # 14 O: NOTE
        ]

    def test_extract_fields_with_correct_config(self):
        row = self._build_piedra_row()
        cfg = PIEDRA_EXPECTED
        assert row[cfg["efj_col"]] == "EFJ107535"
        assert row[cfg["load_id_col"]] == "TT-P-0316-EV-6"
        assert row[cfg["status_col"]] == "In Transit"
        assert row[cfg["pickup_col"]] == "3/16 16:45"
        assert row[cfg["delivery_col"]] == "3/18 13:30"
        assert row[cfg["carrier_email_col"]] == "goytomb45@gmail.com"
        assert row[cfg["driver_name_col"]] == "Goitom Berhane"


# ═══ Test: In Transit / Assigned not skipped ════════════════════════════════

class TestStatusFiltering:
    """Verify that in_transit and assigned loads are NOT skipped by sync."""

    @pytest.fixture(autouse=True)
    def load_done_statuses(self):
        self.done = _extract_boviet_done_statuses(CONFIG_FILES["shared.py"])

    def test_in_transit_not_in_done_statuses(self):
        assert "in transit" not in self.done
        assert "In Transit" not in self.done

    def test_assigned_not_in_done_statuses(self):
        assert "assigned" not in self.done

    def test_picking_up_not_in_done_statuses(self):
        assert "picking up" not in self.done

    def test_delivered_is_in_done_statuses(self):
        assert "delivered" in self.done
