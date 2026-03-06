"""Patch app.py to add file encryption, validation, and fix upload bugs."""

APP_FILE = '/root/csl-bot/csl-doc-tracker/app.py'

with open(APP_FILE, 'r') as f:
    code = f.read()

# 1. Add crypto import after 'import auth'
code = code.replace(
    'import auth\nimport config',
    'import auth\nimport config\nfrom crypto import encrypt_data, decrypt_data'
)

# 2. Add mimetypes import
code = code.replace(
    'import json\nimport logging',
    'import json\nimport logging\nimport mimetypes'
)

# 3. Add file validation constants after the REP_STYLES block
old_rep_end = '''    "Janice": {"color": "var(--accent-cyan)", "bg": "linear-gradient(135deg,#06b6d4,#0891b2)", "initials": "JC"},
}'''

new_rep_end = '''    "Janice": {"color": "var(--accent-cyan)", "bg": "linear-gradient(135deg,#06b6d4,#0891b2)", "initials": "JC"},
}

# ---------------------------------------------------------------------------
# File upload validation
# ---------------------------------------------------------------------------
ALLOWED_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".xlsx", ".xls", ".doc", ".docx"}
MAX_UPLOAD_SIZE = 25 * 1024 * 1024  # 25 MB


def _sanitize_filename(filename: str) -> str:
    """Strip path components and dangerous characters from a filename."""
    name = Path(filename).name
    name = re.sub(r'[^\\w\\-.]', '_', name)
    name = re.sub(r'_{2,}', '_', name)
    name = re.sub(r'\\.{2,}', '.', name)
    if not name or name.startswith('.'):
        name = f"upload_{int(_time.time())}"
    return name'''

code = code.replace(old_rep_end, new_rep_end)

# 4. Replace the serve_document endpoint
old_serve = '''@app.get("/docs/{file_path:path}")
def serve_document(file_path: str):
    full_path = config.DOCUMENT_STORAGE_PATH / file_path
    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Document not found")
    try:
        full_path.resolve().relative_to(config.DOCUMENT_STORAGE_PATH.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")
    return FileResponse(str(full_path))'''

new_serve = '''@app.get("/docs/{file_path:path}")
def serve_document(file_path: str, request: Request):
    """Serve a document, decrypting it on the fly."""
    # Defense-in-depth auth check
    token = request.cookies.get("csl_session")
    if not auth.verify_session_token(token):
        raise HTTPException(status_code=401, detail="Not authenticated")

    # Path traversal protection
    full_path = config.DOCUMENT_STORAGE_PATH / file_path
    try:
        full_path.resolve().relative_to(config.DOCUMENT_STORAGE_PATH.resolve())
    except ValueError:
        raise HTTPException(status_code=403, detail="Access denied")

    if not full_path.exists():
        raise HTTPException(status_code=404, detail="Document not found")

    # Decrypt file contents
    encrypted_data = full_path.read_bytes()
    try:
        decrypted_data = decrypt_data(encrypted_data)
    except Exception:
        # Fallback: file might be unencrypted (pre-migration)
        log.warning("Failed to decrypt %s, serving as-is", file_path)
        decrypted_data = encrypted_data

    # Determine content type from extension
    content_type, _ = mimetypes.guess_type(file_path)
    if not content_type:
        content_type = "application/octet-stream"

    return Response(
        content=decrypted_data,
        media_type=content_type,
        headers={
            "Content-Disposition": f'inline; filename="{Path(file_path).name}"',
            "Cache-Control": "no-store",
        }
    )'''

code = code.replace(old_serve, new_serve)

# 5. Replace the upload endpoint
old_upload = '''@app.post("/api/load/{efj}/upload")
async def api_load_upload(efj: str, file: UploadFile = File(...), doc_type: str = Form(...)):
    """Upload a document for a load."""
    if doc_type not in ("BOL", "POD", "Invoice", "Other"):
        raise HTTPException(status_code=400, detail="Invalid document type")

    # Create storage directory
    store_dir = config.DOCUMENT_STORAGE_PATH / efj / doc_type
    os.makedirs(store_dir, exist_ok=True)

    # Save file
    dest = store_dir / file.filename
    with open(dest, "wb") as f:
        shutil.copyfileobj(file.file, f)

    # Insert into database
    rel_path = f"{efj}/{doc_type}/{file.filename}"
    try:
        db.insert_document(efj, doc_type, file.filename, rel_path)
    except Exception as e:
        log.warning("DB insert for doc %s/%s failed: %s", efj, doc_type, e)

    return {"status": "ok", "filename": file.filename, "path": rel_path}'''

new_upload = '''@app.post("/api/load/{efj}/upload")
async def api_load_upload(efj: str, file: UploadFile = File(...), doc_type: str = Form(...)):
    """Upload a document for a load — validates, encrypts, and stores securely."""
    if doc_type not in ("BOL", "POD", "Invoice", "Other"):
        raise HTTPException(status_code=400, detail="Invalid document type")

    # Validate file extension
    original_name = file.filename or "unknown"
    ext = Path(original_name).suffix.lower()
    if ext not in ALLOWED_EXTENSIONS:
        raise HTTPException(
            status_code=400,
            detail=f"File type '{ext}' not allowed. Allowed: {', '.join(sorted(ALLOWED_EXTENSIONS))}"
        )

    # Read file with size check
    contents = await file.read()
    if len(contents) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File too large. Maximum size is {MAX_UPLOAD_SIZE // (1024*1024)} MB"
        )

    # Sanitize filename
    safe_name = _sanitize_filename(original_name)

    # Create storage directory with restricted permissions
    store_dir = config.DOCUMENT_STORAGE_PATH / efj / doc_type
    os.makedirs(store_dir, mode=0o700, exist_ok=True)

    # Handle duplicates
    stem = Path(safe_name).stem
    suffix = Path(safe_name).suffix
    dest = store_dir / safe_name
    counter = 1
    while dest.exists():
        dest = store_dir / f"{stem}_{counter}{suffix}"
        counter += 1
    final_name = dest.name

    # Encrypt and save
    encrypted_data = encrypt_data(contents)
    dest.write_bytes(encrypted_data)
    os.chmod(str(dest), 0o600)

    # Insert into database (with correct parameter order)
    rel_path = f"{efj}/{doc_type}/{final_name}"
    try:
        load_id = db.find_load_id_by_reference(efj)
        if load_id is None:
            log.warning("No load found for reference %s, skipping DB insert", efj)
        else:
            db.insert_document(load_id, doc_type, rel_path, original_name)
    except Exception as e:
        log.warning("DB insert for doc %s/%s failed: %s", efj, doc_type, e)

    return {"status": "ok", "filename": original_name, "path": rel_path}'''

code = code.replace(old_upload, new_upload)

# 6. Replace frontend upload JS — the file input and uploadDoc function
old_input = """h += '<div class="doc-action"><input type="file" id="upload-' + dt + '-' + d.efj + '" onchange="uploadDoc(\\'' + d.efj + '\\',\\'' + dt + '\\',this)">';"""

new_input = """h += '<div class="doc-action"><input type="file" id="upload-' + dt + '-' + d.efj + '" accept=".pdf,.png,.jpg,.jpeg,.xlsx,.xls,.doc,.docx" onchange="uploadDoc(\\'' + d.efj + '\\',\\'' + dt + '\\',this)">';"""

code = code.replace(old_input, new_input)

old_upload_js = """async function uploadDoc(efj, docType, input) {
  if (!input.files.length) return;
  var fd = new FormData();
  fd.append('file', input.files[0]);
  fd.append('doc_type', docType);
  try {
    var res = await fetch('/api/load/' + encodeURIComponent(efj) + '/upload', {method:'POST', body:fd});
    if (res.ok) { loadPanel(efj); }
    else { alert('Upload failed'); }
  } catch(e) { alert('Upload error: ' + e.message); }
}"""

new_upload_js = """async function uploadDoc(efj, docType, input) {
  if (!input.files.length) return;
  var file = input.files[0];
  var allowed = ['.pdf','.png','.jpg','.jpeg','.xlsx','.xls','.doc','.docx'];
  var ext = file.name.substring(file.name.lastIndexOf('.')).toLowerCase();
  if (allowed.indexOf(ext) === -1) {
    alert('File type not allowed. Allowed: ' + allowed.join(', '));
    input.value = '';
    return;
  }
  if (file.size > 25 * 1024 * 1024) {
    alert('File too large. Maximum size is 25 MB.');
    input.value = '';
    return;
  }
  var label = input.nextElementSibling;
  var origText = label.textContent;
  label.textContent = 'Uploading...';
  label.style.opacity = '0.6';
  input.disabled = true;
  var fd = new FormData();
  fd.append('file', file);
  fd.append('doc_type', docType);
  try {
    var res = await fetch('/api/load/' + encodeURIComponent(efj) + '/upload', {method:'POST', body:fd});
    if (res.ok) {
      label.textContent = 'Done!';
      label.style.color = '#16a34a';
      setTimeout(function() { loadPanel(efj); }, 500);
    } else {
      var err = await res.json().catch(function() { return {detail:'Upload failed'}; });
      alert(err.detail || 'Upload failed');
      label.textContent = origText;
      label.style.opacity = '1';
      input.disabled = false;
    }
  } catch(e) {
    alert('Upload error: ' + e.message);
    label.textContent = origText;
    label.style.opacity = '1';
    input.disabled = false;
  }
}"""

code = code.replace(old_upload_js, new_upload_js)

with open(APP_FILE, 'w') as f:
    f.write(code)

print('app.py patched successfully')
