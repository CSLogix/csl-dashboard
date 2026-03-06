"""Add PDF support to avatar upload — auto-converts PDF to PNG using pdf2image."""

APP = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP, "r") as f:
    code = f.read()

# Replace the allowed extensions set and add PDF conversion logic
old = '''    allowed = {".png", ".jpg", ".jpeg", ".gif", ".webp"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed:
        return JSONResponse(status_code=400, content={"error": f"Invalid file type. Allowed: {', '.join(allowed)}"})

    unique_name = f"{_uuid.uuid4().hex[:8]}_{rep_name}{ext}"
    save_path = os.path.join("uploads", "avatars", unique_name)
    os.makedirs(os.path.dirname(save_path), exist_ok=True)'''

new = '''    allowed = {".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"}
    ext = os.path.splitext(file.filename)[1].lower()
    if ext not in allowed:
        return JSONResponse(status_code=400, content={"error": f"Invalid file type. Allowed: {', '.join(allowed)}"})

    os.makedirs(os.path.join("uploads", "avatars"), exist_ok=True)

    # If PDF, convert first page to PNG
    if ext == ".pdf":
        import tempfile
        from pdf2image import convert_from_bytes
        pdf_bytes = await file.read()
        try:
            images = convert_from_bytes(pdf_bytes, first_page=1, last_page=1, dpi=150)
            ext = ".png"
            unique_name = f"{_uuid.uuid4().hex[:8]}_{rep_name}{ext}"
            save_path = os.path.join("uploads", "avatars", unique_name)
            images[0].save(save_path, "PNG")
        except Exception as e:
            return JSONResponse(status_code=400, content={"error": f"Could not convert PDF: {str(e)}"})
    else:
        unique_name = f"{_uuid.uuid4().hex[:8]}_{rep_name}{ext}"
        save_path = os.path.join("uploads", "avatars", unique_name)'''

if old in code:
    code = code.replace(old, new, 1)
    print("PDF avatar support added")
else:
    print("ERROR: Could not find target code block")
    exit(1)

# Also need to move the file.read() + write for non-PDF path
# The original code reads file content after the old block — adjust it
old2 = '''            content = await file.read()
            with open(save_path, "wb") as f:
                f.write(content)'''

new2 = '''            if ext != ".pdf":  # PDF already saved above
                content = await file.read()
                with open(save_path, "wb") as f:
                    f.write(content)'''

# Wait — the ext might have been changed to .png for PDFs already.
# Actually the file write happens AFTER the conversion block, and for PDFs
# the file is already saved by images[0].save(). For non-PDFs we still need
# to read and write. But `ext` was already overwritten to .png for PDFs.
# Let me think about this differently...
#
# Actually the read/write block is inside the "with db..." section.
# For PDFs, file.read() was already called above. So we need a flag or
# just check if the file was already written.

# Simpler approach: just skip the content write if save_path already exists
new2b = '''            if not os.path.exists(save_path):
                content = await file.read()
                with open(save_path, "wb") as f:
                    f.write(content)'''

if old2 in code:
    code = code.replace(old2, new2b, 1)
    print("File write guard added")
else:
    print("WARNING: Could not find file write block")

with open(APP, "w") as f:
    f.write(code)

print("Done. Restart csl-dashboard.")
