"""
Load matcher for CSL Document Tracker.
Builds an in-memory lookup table of all known reference numbers and matches
email subjects against them to find the associated load.
"""

import logging
import re

import database as db

log = logging.getLogger(__name__)

# In-memory mapping: normalized reference → load_id
_lookup: dict[str, int] = {}


def rebuild_lookup():
    """Rebuild the in-memory lookup table from the database."""
    global _lookup
    refs = db.get_all_references()
    new_lookup = {}
    for row in refs:
        key = row["reference_value"].strip().upper()
        if key:
            new_lookup[key] = row["load_id"]
    _lookup = new_lookup
    log.info("Reference lookup table rebuilt: %d entries", len(_lookup))


def match_subject(subject: str) -> int | None:
    """
    Scan an email subject line for any known reference number.
    Returns the load_id if found, else None.

    Strategy:
    1. Tokenize the subject into words/segments.
    2. Also try regex patterns for common reference formats.
    3. Check each candidate against the lookup table.
    """
    if not subject:
        return None

    # Extract candidates from the subject
    candidates = set()

    # Split on common delimiters
    tokens = re.split(r"[\s,;:|/\-–—\(\)\[\]{}]+", subject)
    for token in tokens:
        clean = token.strip().strip("#").strip(".")
        if len(clean) >= 3:
            candidates.add(clean.upper())

    # Regex for EFJ numbers (e.g., EFJ12345, EFJ 12345)
    efj_matches = re.findall(r"EFJ\s*\d+", subject, re.IGNORECASE)
    for m in efj_matches:
        candidates.add(re.sub(r"\s+", "", m).upper())

    # Regex for container numbers (4 letters + 7 digits, e.g., MSCU1234567)
    container_matches = re.findall(r"[A-Z]{4}\d{7}", subject, re.IGNORECASE)
    for m in container_matches:
        candidates.add(m.upper())

    # Check each candidate against the lookup
    for candidate in candidates:
        if candidate in _lookup:
            load_id = _lookup[candidate]
            log.info("Matched reference '%s' → load_id %d", candidate, load_id)
            return load_id

    # Fallback: substring search for longer reference values
    subject_upper = subject.upper()
    for ref_value, load_id in _lookup.items():
        if len(ref_value) >= 6 and ref_value in subject_upper:
            log.info("Matched reference '%s' (substring) → load_id %d", ref_value, load_id)
            return load_id

    return None


def match_text(text: str) -> int | None:
    """Like match_subject but for arbitrary text (e.g., attachment filenames)."""
    return match_subject(text)


def get_lookup_size() -> int:
    return len(_lookup)
