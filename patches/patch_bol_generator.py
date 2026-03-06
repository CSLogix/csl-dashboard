"""
Patch: BOL Generator API
Adds GET /api/bol/accounts and POST /api/bol/generate to app.py
Generates PDFs from Word templates via docxtpl + LibreOffice headless.
"""
import re

APP_PY = "/root/csl-bot/csl-doc-tracker/app.py"

BOL_BLOCK = '''

# ═══════════════════════════════════════════════════════════════
# BOL GENERATOR API
# ═══════════════════════════════════════════════════════════════
import uuid as _uuid
import zipfile as _zipfile
from io import BytesIO as _BytesIO
from docxtpl import DocxTemplate as _DocxTemplate
import pandas as _pd

_BOL_TEMPLATE_DIR = Path("/root/csl-bot/csl-doc-tracker/bol_templates")
_BOL_TEMP_DIR = Path("/root/csl-bot/csl-doc-tracker/bol_temp")

BOL_ACCOUNTS = {
    "piedra_solar": {
        "label": "Piedra Solar",
        "template": "piedra_solar.docx",
        "csv_columns": {
            "EFJ Pro #": "efj_pro",
            "BV #": "box_one",
            "Boviet  Load#": "piedra_box",
            "Pallet Count": "pallet_count",
            "Piece Count": "piece_count",
            "Watt": "wattage",
            "Pickup Appt Date": "pickup_date",
            "PU Appt Time": "pickup_time",
            "Delivery Apt Date": "delivery_date",
            "Delivery Appt Time": "delivery_time",
        },
        "filename_pattern": "{piedra_box} {efj_pro}",
        "required_columns": ["EFJ Pro #", "BV #", "Boviet  Load#", "Pickup Appt Date"],
    },
}


def _cleanup_bol_temp(max_age_seconds=3600):
    """Remove job directories older than max_age_seconds."""
    if not _BOL_TEMP_DIR.exists():
        return
    now = _time.time()
    for d in _BOL_TEMP_DIR.iterdir():
        if d.is_dir() and (now - d.stat().st_mtime) > max_age_seconds:
            shutil.rmtree(d, ignore_errors=True)


def _fuzzy_match_columns(df_columns, mapping):
    """Fuzzy-match CSV column names: strip whitespace, case-insensitive, collapse multiple spaces."""
    norm = lambda s: re.sub(r"\\s+", " ", str(s).strip().lower())
    df_norm = {norm(c): c for c in df_columns}
    matched = {}
    missing = []
    for csv_col, tpl_var in mapping.items():
        key = norm(csv_col)
        if key in df_norm:
            matched[df_norm[key]] = tpl_var
        else:
            missing.append(csv_col)
    return matched, missing


@app.get("/api/bol/accounts")
def bol_accounts():
    accounts = []
    for key, cfg in BOL_ACCOUNTS.items():
        accounts.append({
            "key": key,
            "label": cfg["label"],
            "columns": list(cfg["csv_columns"].keys()),
            "required_columns": cfg.get("required_columns", []),
        })
    return {"accounts": accounts}


@app.post("/api/bol/generate")
async def bol_generate(account: str = Form(...), file: UploadFile = File(...)):
    # Cleanup old temp dirs
    _cleanup_bol_temp()

    if account not in BOL_ACCOUNTS:
        raise HTTPException(400, f"Unknown account: {account}")

    cfg = BOL_ACCOUNTS[account]
    template_path = _BOL_TEMPLATE_DIR / cfg["template"]
    if not template_path.exists():
        raise HTTPException(500, f"Template not found: {cfg['template']}")

    # Create job directory
    job_id = str(_uuid.uuid4())[:8]
    job_dir = _BOL_TEMP_DIR / job_id
    job_dir.mkdir(parents=True, exist_ok=True)

    try:
        # Save uploaded file
        content = await file.read()
        fname = file.filename or "data.csv"
        upload_path = job_dir / fname
        upload_path.write_bytes(content)

        # Parse CSV or Excel
        try:
            if fname.lower().endswith((".xls", ".xlsx")):
                df = _pd.read_excel(upload_path)
            else:
                df = _pd.read_csv(upload_path)
        except Exception as e:
            raise HTTPException(400, f"Failed to parse file: {e}")

        if len(df) == 0:
            raise HTTPException(400, "File contains no data rows")
        if len(df) > 100:
            raise HTTPException(400, f"Too many rows ({len(df)}). Max 100 per batch.")

        # Match columns
        matched, missing = _fuzzy_match_columns(df.columns, cfg["csv_columns"])
        req_missing = [c for c in cfg.get("required_columns", []) if c not in matched and c.lower() not in [m.lower() for m in matched]]
        if req_missing:
            raise HTTPException(400, f"Missing required columns: {', '.join(req_missing)}. Found: {', '.join(df.columns.tolist())}")

        # Generate .docx files
        docx_files = []
        for i, row in df.iterrows():
            context = {}
            for csv_col, tpl_var in matched.items():
                val = row.get(csv_col, "")
                context[tpl_var] = str(val) if _pd.notna(val) else ""

            tpl = _DocxTemplate(str(template_path))
            tpl.render(context)

            # Build filename from pattern
            try:
                name = cfg["filename_pattern"].format(**context)
            except KeyError:
                name = f"BOL_{i+1}"
            safe_name = re.sub(r'[<>:"/\\\\|?*]', '_', name)
            docx_path = job_dir / f"{safe_name}.docx"
            tpl.save(str(docx_path))
            docx_files.append(docx_path)

        # Batch convert to PDF with LibreOffice
        result = subprocess.run(
            ["libreoffice", "--headless", "--convert-to", "pdf", "--outdir", str(job_dir)]
            + [str(f) for f in docx_files],
            capture_output=True, text=True, timeout=120,
        )
        if result.returncode != 0:
            logging.error(f"LibreOffice error: {result.stderr}")
            raise HTTPException(500, "PDF conversion failed")

        # Collect PDFs into ZIP
        pdf_files = sorted(job_dir.glob("*.pdf"))
        if not pdf_files:
            raise HTTPException(500, "No PDFs generated")

        zip_buf = _BytesIO()
        with _zipfile.ZipFile(zip_buf, "w", _zipfile.ZIP_DEFLATED) as zf:
            for pdf in pdf_files:
                zf.write(pdf, pdf.name)
        zip_buf.seek(0)

        # Return ZIP
        zip_name = f"BOLs_{account}_{job_id}.zip"
        return Response(
            content=zip_buf.getvalue(),
            media_type="application/zip",
            headers={"Content-Disposition": f'attachment; filename="{zip_name}"'},
        )

    finally:
        # Cleanup job dir
        shutil.rmtree(job_dir, ignore_errors=True)

'''

# ── Apply patch ──
with open(APP_PY, "r") as f:
    src = f.read()

if "/api/bol/generate" in src:
    print("SKIP: BOL generator endpoints already present in app.py")
else:
    # Insert before the health check endpoint
    marker = '@app.get("/health")'
    if marker not in src:
        print("ERROR: Could not find health endpoint marker")
    else:
        src = src.replace(marker, BOL_BLOCK + "\n" + marker)
        with open(APP_PY, "w") as f:
            f.write(src)
        print("OK: BOL generator endpoints added to app.py")

    # Add /api/bol/ to public paths in auth middleware if needed
    if "bol" not in src.split("PUBLIC_API_PREFIXES")[0] if "PUBLIC_API_PREFIXES" in src else True:
        # Check if there's a public path list
        if "PUBLIC_API_PREFIXES" in src:
            print("NOTE: Check that /api/bol/ paths are accessible through auth middleware")
        else:
            print("NOTE: Auth middleware should allow /api/bol/ paths (they require session cookie)")
