"""
Fix the .msg handler in app.py to use extract-msg library.
Replaces the broken one-liner + any corrupted multi-line version.
"""
import re

app_path = "/root/csl-bot/csl-doc-tracker/app.py"

with open(app_path, "r") as f:
    lines = f.readlines()

# Find the start of the .msg block
start_idx = None
for i, line in enumerate(lines):
    if "# .msg (Outlook)" in line and ("ext in" in line or "extract-msg" in line):
        start_idx = i
        break

if start_idx is None:
    print("ERROR: Could not find .msg handler block")
    exit(1)

# Find the end: look for the line with 'raise HTTPException(400, f"Unsupported file type'
end_idx = None
for i in range(start_idx, min(start_idx + 120, len(lines))):
    if 'Unsupported file type' in lines[i]:
        end_idx = i
        break

if end_idx is None:
    print("ERROR: Could not find end of .msg block")
    exit(1)

print(f"Replacing lines {start_idx+1} to {end_idx+1}")

NL = chr(10)
I4 = "    "
I8 = "        "
I12 = "            "
I16 = "                "
I20 = "                    "
I24 = "                        "

new_lines = [
    f"{I4}# .msg (Outlook) - use extract-msg for proper parsing{NL}",
    f"{I4}if ext in ('msg',):{NL}",
    f"{I8}try:{NL}",
    f"{I12}import extract_msg, io as _io{NL}",
    f"{I12}msg = extract_msg.openMsg(_io.BytesIO(file_bytes)){NL}",
    f"{I12}parts = []{NL}",
    f"{I12}if msg.subject:{NL}",
    f"{I16}parts.append('Subject: ' + str(msg.subject)){NL}",
    f"{I12}if msg.sender:{NL}",
    f"{I16}parts.append('From: ' + str(msg.sender)){NL}",
    f"{I12}if msg.date:{NL}",
    f"{I16}parts.append('Date: ' + str(msg.date)){NL}",
    f"{I12}if msg.body:{NL}",
    f"{I16}parts.append(msg.body){NL}",
    f"{I12}text_content = chr(10).join(parts){NL}",
    f"{I12}# Extract image attachments for Claude Vision{NL}",
    f"{I12}attachment_images = []{NL}",
    f"{I12}for att in (msg.attachments or []):{NL}",
    f"{I16}att_name = (att.longFilename or att.shortFilename or '').lower(){NL}",
    f"{I16}if att_name.endswith(('.png', '.jpg', '.jpeg', '.gif', '.webp')):{NL}",
    f"{I20}att_data = att.data{NL}",
    f"{I20}if att_data:{NL}",
    f"{I24}import base64 as _b64{NL}",
    f"{I24}ext2 = att_name.rsplit('.', 1)[-1]{NL}",
    f"{I24}mt = dict(png='image/png', jpg='image/jpeg', jpeg='image/jpeg', gif='image/gif', webp='image/webp').get(ext2, 'image/png'){NL}",
    f"{I24}attachment_images.append(dict(type='image', source=dict(type='base64', media_type=mt, data=_b64.b64encode(att_data).decode()))){NL}",
    f"{I16}elif att_name.endswith('.pdf') and att.data:{NL}",
    f"{I20}try:{NL}",
    f"{I24}import fitz{NL}",
    f"{I24}pdf_doc = fitz.open(stream=att.data, filetype='pdf'){NL}",
    f"{I24}pdf_text = chr(10).join(page.get_text() for page in pdf_doc){NL}",
    f"{I24}if pdf_text.strip():{NL}",
    f"{I24}    text_content += chr(10)*2 + '--- Attached PDF: ' + att_name + ' ---' + chr(10) + pdf_text[:4000]{NL}",
    f"{I20}except Exception:{NL}",
    f"{I24}pass{NL}",
    f"{I12}if not text_content.strip():{NL}",
    f"{I16}raise HTTPException(400, 'Could not extract readable text from .msg file'){NL}",
    f"{I12}if has_claude:{NL}",
    f"{I16}try:{NL}",
    f"{I20}content_msg = [dict(type='text', text=_EXTRACT_PROMPT + chr(10)*2 + text_content[:8000])]{NL}",
    f"{I20}content_msg = attachment_images + content_msg{NL}",
    f"{I20}result = _extract_with_claude(content_msg){NL}",
    f"{I20}return JSONResponse(result){NL}",
    f"{I16}except Exception as e:{NL}",
    f"{I20}log.warning('Claude .msg extraction failed: %s', e){NL}",
    f"{I12}result = _parse_rate_text(text_content){NL}",
    f"{I12}if not result:{NL}",
    f"{I16}raise HTTPException(400, 'Could not extract rate info from .msg file'){NL}",
    f"{I12}return JSONResponse(result){NL}",
    f"{I8}except HTTPException:{NL}",
    f"{I12}raise{NL}",
    f"{I8}except Exception as e:{NL}",
    f"{I12}log.error('.msg extraction failed: %s', e){NL}",
    f"{I12}# Fallback: brute-force ASCII extraction{NL}",
    f"{I12}try:{NL}",
    f"{I16}raw = file_bytes.decode('latin-1', errors='replace'){NL}",
    f"{I16}blocks = re.findall(r'[ -~]{{20,}}', raw){NL}",
    f"{I16}fallback_text = chr(10).join(blocks){NL}",
    f"{I16}if fallback_text.strip() and has_claude:{NL}",
    f"{I20}content_msg = [dict(type='text', text=_EXTRACT_PROMPT + chr(10)*2 + fallback_text[:8000])]{NL}",
    f"{I20}result = _extract_with_claude(content_msg){NL}",
    f"{I20}return JSONResponse(result){NL}",
    f"{I12}except Exception:{NL}",
    f"{I16}pass{NL}",
    f"{I12}raise HTTPException(500, f'Failed to process .msg file: {{e}}'){NL}",
    f"{NL}",
    f"{I4}# .htm/.html files{NL}",
    f"{I4}if ext in ('htm', 'html'):{NL}",
    f"{I8}try:{NL}",
    f"{I12}raw = file_bytes.decode('utf-8', errors='replace'){NL}",
    f"{I12}text_content = re.sub(r'<[^>]+>', ' ', raw){NL}",
    f"{I12}text_content = re.sub(chr(92) + 's+', ' ', text_content).strip(){NL}",
    f"{I12}if not text_content:{NL}",
    f"{I16}raise HTTPException(400, 'Could not extract text from HTML file'){NL}",
    f"{I12}if has_claude:{NL}",
    f"{I16}try:{NL}",
    f"{I20}content_msg = [dict(type='text', text=_EXTRACT_PROMPT + chr(10)*2 + text_content[:8000])]{NL}",
    f"{I20}result = _extract_with_claude(content_msg){NL}",
    f"{I20}return JSONResponse(result){NL}",
    f"{I16}except Exception as e:{NL}",
    f"{I20}log.warning('Claude HTML extraction failed: %s', e){NL}",
    f"{I12}result = _parse_rate_text(text_content){NL}",
    f"{I12}if not result:{NL}",
    f"{I16}raise HTTPException(400, 'Could not extract rate info from HTML'){NL}",
    f"{I12}return JSONResponse(result){NL}",
    f"{I8}except HTTPException:{NL}",
    f"{I12}raise{NL}",
    f"{I8}except Exception as e:{NL}",
    f"{I12}log.error('HTML extraction failed: %s', e){NL}",
    f"{I12}raise HTTPException(500, f'Failed to process HTML file: {{e}}'){NL}",
    f"{NL}",
]

# Replace
lines[start_idx:end_idx] = new_lines

with open(app_path, "w") as f:
    f.writelines(lines)

print("OK: .msg handler replaced with extract-msg version")
