"""
Patch: BOL Screenshot OCR Extraction
Adds POST /api/bol/extract — accepts an image, returns extracted table data via Tesseract OCR.
"""
import re

APP_PY = "/root/csl-bot/csl-doc-tracker/app.py"

EXTRACT_BLOCK = '''

# ── BOL Screenshot OCR Extraction ──
import pytesseract
from PIL import Image as _PILImage

@app.post("/api/bol/extract")
async def bol_extract(file: UploadFile = File(...)):
    """Extract table data from a screenshot using Tesseract OCR."""
    _cleanup_bol_temp()

    job_id = str(_uuid.uuid4())[:8]
    job_dir = _BOL_TEMP_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    try:
        content = await file.read()
        img_path = job_dir / (file.filename or "screenshot.png")
        img_path.write_bytes(content)

        # Open image and run OCR
        img = _PILImage.open(str(img_path))
        # Use TSV output for structured data
        tsv_text = pytesseract.image_to_data(img, output_type=pytesseract.Output.STRING)

        # Also get plain text as fallback
        plain_text = pytesseract.image_to_string(img)

        # Parse TSV output into rows grouped by block/line
        lines_by_block = {}
        for line in tsv_text.strip().split("\\n")[1:]:  # skip header
            parts = line.split("\\t")
            if len(parts) >= 12:
                block_num = parts[1]
                line_num = parts[4]
                text = parts[11].strip()
                if text and int(parts[10]) > 30:  # confidence > 30%
                    key = f"{block_num}_{line_num}"
                    if key not in lines_by_block:
                        lines_by_block[key] = []
                    lines_by_block[key].append(text)

        # Build structured lines
        structured_lines = []
        for key in sorted(lines_by_block.keys(), key=lambda k: (int(k.split("_")[0]), int(k.split("_")[1]))):
            line_text = " ".join(lines_by_block[key])
            if line_text.strip():
                structured_lines.append(line_text)

        # Try to detect tabular data — look for lines with consistent delimiters
        # Strategy: find lines that look like they have multiple columns (dates, EFJ numbers, etc.)
        efj_pattern = re.compile(r"EFJ\\d{5,}")
        date_pattern = re.compile(r"\\d{1,2}/\\d{1,2}/\\d{2,4}")
        time_pattern = re.compile(r"\\d{1,2}:\\d{2}\\s*[AaPp][Mm]")

        # Return both raw text and structured lines for the frontend to work with
        return {
            "raw_text": plain_text,
            "lines": structured_lines,
            "line_count": len(structured_lines),
        }

    except Exception as e:
        logging.error(f"OCR extraction error: {e}")
        raise HTTPException(500, f"OCR extraction failed: {str(e)}")
    finally:
        shutil.rmtree(job_dir, ignore_errors=True)

'''

# ── Apply patch ──
with open(APP_PY, "r") as f:
    src = f.read()

if "/api/bol/extract" in src:
    print("SKIP: BOL extract endpoint already present")
else:
    marker = '@app.get("/health")'
    if marker not in src:
        print("ERROR: Could not find health endpoint marker")
    else:
        src = src.replace(marker, EXTRACT_BLOCK + "\n" + marker)
        with open(APP_PY, "w") as f:
            f.write(src)
        print("OK: BOL extract endpoint added to app.py")
