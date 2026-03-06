#!/usr/bin/env python3
"""
Patch: Skip junk email attachments (signature icons, tracking pixels, social logos).
Adds is_junk_attachment() filter to csl_inbox_scanner.py.

Run on server:
    python3 /tmp/patch_attachment_filter.py
"""

import shutil, os, sys
from datetime import datetime

SCANNER_PATH = "/root/csl-bot/csl_inbox_scanner.py"

def backup(path):
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    bak = f"{path}.bak_{ts}"
    shutil.copy2(path, bak)
    print(f"Backup: {bak}")

JUNK_FILTER_FUNC = '''
# ── Junk attachment filter (signature icons, tracking pixels, social logos) ──

JUNK_FILENAME_PATTERNS = re.compile(
    r"^image\\d{3}\\.(png|jpg|jpeg|gif)$"       # Outlook signature images: image001.png
    r"|^(icon|logo|banner|spacer|pixel|beacon)"  # Generic junk prefixes
    r"|facebook|linkedin|twitter|instagram|youtube|tiktok"  # Social media icons
    r"|(^|\\.)(gif)$"                             # Almost all .gif attachments are tracking pixels
    r"|^outlook_\\w+\\.(png|jpg)"                  # Outlook-generated images
    r"|^~\\$"                                      # Office temp files
    , re.IGNORECASE
)

JUNK_MAX_SIZE_BYTES = 15_000  # 15KB — real docs are larger

def is_junk_attachment(filename, size_bytes=None):
    """Return True if attachment looks like a signature icon or tracking pixel."""
    if not filename:
        return True
    # Known junk filename patterns
    if JUNK_FILENAME_PATTERNS.search(filename):
        return True
    # Tiny image files are almost always icons/signatures
    if size_bytes is not None and size_bytes < JUNK_MAX_SIZE_BYTES:
        ext = filename.rsplit(".", 1)[-1].lower() if "." in filename else ""
        if ext in ("png", "jpg", "jpeg", "gif", "bmp", "ico"):
            return True
    return False

'''

def patch():
    if not os.path.exists(SCANNER_PATH):
        print(f"ERROR: {SCANNER_PATH} not found"); sys.exit(1)

    backup(SCANNER_PATH)
    code = open(SCANNER_PATH).read()
    changes = 0

    # ── 1. Add is_junk_attachment function ──
    if "def is_junk_attachment" in code:
        print("= is_junk_attachment already exists")
    else:
        # Insert before the EFJ_PATTERN line
        marker = "# EFJ# pattern:"
        if marker in code:
            idx = code.find(marker)
            code = code[:idx] + JUNK_FILTER_FUNC + code[idx:]
            print("+ Added is_junk_attachment() function")
            changes += 1
        else:
            print("WARNING: Could not find EFJ_PATTERN marker")

    # ── 2. Add junk filter to attachment processing ──
    # Find the valid_attachments filter and add junk check
    old_filter = """    valid_attachments = [
        a for a in attachments
        if Path(a["filename"]).suffix.lower() in ALLOWED_EXTENSIONS
    ]"""

    new_filter = """    valid_attachments = [
        a for a in attachments
        if Path(a["filename"]).suffix.lower() in ALLOWED_EXTENSIONS
        and not is_junk_attachment(a["filename"], a.get("size"))
    ]"""

    if "is_junk_attachment" not in code.split("valid_attachments")[1] if "valid_attachments" in code else True:
        if old_filter in code:
            code = code.replace(old_filter, new_filter)
            print("+ Added junk filter to valid_attachments check")
            changes += 1
        else:
            print("WARNING: Could not find valid_attachments filter block")
    else:
        print("= junk filter already in valid_attachments")

    # ── 3. Capture attachment size in collect_attachments ──
    # Check if size is already captured
    old_collect = '''        attachments.append({
            "filename": payload["filename"],'''

    if '"size"' not in code.split("collect_attachments")[1].split("return attachments")[0] if "collect_attachments" in code else True:
        new_collect = '''        attachments.append({
            "filename": payload["filename"],
            "size": payload.get("body", {}).get("size", 0),'''

        if old_collect in code:
            code = code.replace(old_collect, new_collect)
            print("+ Added size capture to collect_attachments()")
            changes += 1
        else:
            print("WARNING: Could not find collect_attachments append block")
    else:
        print("= size already captured in collect_attachments")

    if changes > 0:
        open(SCANNER_PATH, "w").write(code)
        print(f"\n{changes} changes applied.")
        print("Restart: systemctl restart csl-inbox")
    else:
        print("\nNo changes needed.")


if __name__ == "__main__":
    patch()
