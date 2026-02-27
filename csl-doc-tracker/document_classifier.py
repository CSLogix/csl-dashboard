"""
Document classifier for CSL Document Tracker.
Determines whether an attachment is a BOL, POD, or unclassified.
"""

import logging
import re

log = logging.getLogger(__name__)

# Patterns checked against filename (case-insensitive)
BOL_FILENAME_PATTERNS = [
    r"\bBOL\b",
    r"\bB/L\b",
    r"\bB\.L\.\b",
    r"\bbill[\s_-]*of[\s_-]*lading\b",
    r"\blading\b",
]

POD_FILENAME_PATTERNS = [
    r"\bPOD\b",
    r"\bproof[\s_-]*of[\s_-]*delivery\b",
    r"\bdelivery[\s_-]*receipt\b",
    r"\bsigned[\s_-]*delivery\b",
    r"\bdelivery[\s_-]*confirmation\b",
]

# Subject / body context clues (lower priority, used as fallback)
BOL_CONTEXT_PATTERNS = [
    r"\bBOL\b",
    r"\bB/L\b",
    r"\bbill[\s_-]*of[\s_-]*lading\b",
    r"\bbooking\b",
    r"\bshipment[\s_-]*confirm\b",
]

POD_CONTEXT_PATTERNS = [
    r"\bPOD\b",
    r"\bproof[\s_-]*of[\s_-]*delivery\b",
    r"\bdelivered\b",
    r"\bcompleted\b",
    r"\bdelivery[\s_-]*receipt\b",
    r"\bsigned[\s_-]*delivery\b",
    r"\bdelivery[\s_-]*confirmation\b",
]


def _match_any(text: str, patterns: list[str]) -> bool:
    """Return True if any regex pattern matches text (case-insensitive)."""
    for pat in patterns:
        if re.search(pat, text, re.IGNORECASE):
            return True
    return False


def classify(
    filename: str,
    email_subject: str = "",
    email_body: str = "",
) -> str:
    """
    Classify a document attachment.

    Returns:
        "BOL", "POD", or "UNCLASSIFIED"
    """
    # Step 1: Check filename
    if _match_any(filename, BOL_FILENAME_PATTERNS):
        log.debug("Classified %s as BOL (filename match)", filename)
        return "BOL"
    if _match_any(filename, POD_FILENAME_PATTERNS):
        log.debug("Classified %s as POD (filename match)", filename)
        return "POD"

    # Step 2: Check email subject + body for context clues
    context = f"{email_subject} {email_body}"

    # Check POD first — POD context words are more specific
    if _match_any(context, POD_CONTEXT_PATTERNS):
        log.debug("Classified %s as POD (context match)", filename)
        return "POD"
    if _match_any(context, BOL_CONTEXT_PATTERNS):
        log.debug("Classified %s as BOL (context match)", filename)
        return "BOL"

    log.debug("Could not classify %s — marking UNCLASSIFIED", filename)
    return "UNCLASSIFIED"


def is_relevant_attachment(filename: str) -> bool:
    """Return True if the file extension suggests a document (PDF, image, etc.)."""
    relevant_extensions = {
        ".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".bmp", ".gif",
    }
    lower = filename.lower()
    return any(lower.endswith(ext) for ext in relevant_extensions)
