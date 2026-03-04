"""
Quote Extractor — Uses Claude API to extract carrier rate data from images, PDFs, and emails.
"""
import base64
import json
import logging
import re
from pathlib import Path

import httpx

log = logging.getLogger(__name__)

CLAUDE_MODEL = "claude-haiku-4-5-20251001"
EXTRACTION_PROMPT = """You are a logistics rate extraction assistant. Extract carrier rate information from this document.

Return ONLY valid JSON with this exact structure:
{
  "carrier_name": "string",
  "origin": "string",
  "destination": "string",
  "shipment_type": "Dray|FTL|OTR|Transload|Dray+Transload|LTL",
  "round_trip_miles": "string or empty",
  "one_way_miles": "string or empty",
  "transit_time": "string or empty",
  "linehaul_items": [
    {"description": "string", "rate": "number as string e.g. 1250.00"}
  ],
  "accessorials": [
    {"charge": "string", "rate": "string", "frequency": "per day|per hour|flat|per mile", "amount": "string"}
  ],
  "notes": "any extra info"
}

Rules:
- Extract ALL line items with their rates
- Separate linehaul charges from accessorial charges
- Linehaul = main transportation charges (dray, OTR, transload handling, fuel surcharge if bundled)
- Accessorials = extra charges (storage, tolls, pre-pull, chassis, detention, overweight)
- Use empty string for unknown fields, never null
- Rates should be numeric strings without $ sign
"""


def _get_api_key():
    import os
    key = os.environ.get("ANTHROPIC_API_KEY", "")
    if not key:
        raise ValueError("ANTHROPIC_API_KEY not set")
    return key


def _call_claude(messages, max_tokens=2000):
    api_key = _get_api_key()
    resp = httpx.post(
        "https://api.anthropic.com/v1/messages",
        headers={
            "x-api-key": api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        },
        json={
            "model": CLAUDE_MODEL,
            "max_tokens": max_tokens,
            "messages": messages,
        },
        timeout=60.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return data["content"][0]["text"]


def _parse_json_response(text):
    # Try direct parse
    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass
    # Try extracting JSON from markdown code block
    match = re.search(r'```(?:json)?\s*(\{.*?\})\s*```', text, re.DOTALL)
    if match:
        try:
            return json.loads(match.group(1))
        except json.JSONDecodeError:
            pass
    # Try finding first { to last }
    start = text.find('{')
    end = text.rfind('}')
    if start != -1 and end != -1:
        try:
            return json.loads(text[start:end+1])
        except json.JSONDecodeError:
            pass
    raise ValueError(f"Could not parse JSON from Claude response: {text[:200]}")


def extract_from_image(file_path: str) -> dict:
    path = Path(file_path)
    suffix = path.suffix.lower()
    media_map = {
        ".png": "image/png", ".jpg": "image/jpeg", ".jpeg": "image/jpeg",
        ".gif": "image/gif", ".webp": "image/webp",
    }
    media_type = media_map.get(suffix, "image/png")

    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    messages = [{
        "role": "user",
        "content": [
            {"type": "image", "source": {"type": "base64", "media_type": media_type, "data": b64}},
            {"type": "text", "text": EXTRACTION_PROMPT},
        ]
    }]

    raw = _call_claude(messages)
    return _parse_json_response(raw)


def extract_from_pdf(file_path: str) -> dict:
    path = Path(file_path)
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()

    messages = [{
        "role": "user",
        "content": [
            {"type": "document", "source": {"type": "base64", "media_type": "application/pdf", "data": b64}},
            {"type": "text", "text": EXTRACTION_PROMPT},
        ]
    }]

    raw = _call_claude(messages)
    return _parse_json_response(raw)


def extract_from_text(text: str) -> dict:
    messages = [{
        "role": "user",
        "content": f"{EXTRACTION_PROMPT}\n\nHere is the text to extract from:\n\n{text}"
    }]
    raw = _call_claude(messages)
    return _parse_json_response(raw)


def extract_from_email(file_path: str) -> dict:
    """Extract rate data from .msg (Outlook) or .eml email files."""
    path = Path(file_path)
    suffix = path.suffix.lower()
    
    body = ""
    attachments = []
    
    if suffix == ".msg":
        import extract_msg
        msg = extract_msg.Message(str(path))
        body = f"Subject: {msg.subject or ''}\nFrom: {msg.sender or ''}\nDate: {msg.date or ''}\n\n{msg.body or ''}"
        # Check for image/PDF attachments
        for att in (msg.attachments or []):
            if hasattr(att, "filename") and att.filename:
                ext = Path(att.filename).suffix.lower()
                if ext in (".png", ".jpg", ".jpeg", ".gif", ".webp", ".pdf"):
                    att_path = Path(UPLOAD_DIR if "UPLOAD_DIR" in dir() else "/tmp") / att.filename
                    att.save(customPath=str(att_path.parent), customFilename=att_path.name)
                    attachments.append((str(att_path), ext))
        msg.close()
    elif suffix == ".eml":
        import email
        from email import policy
        with open(path, "rb") as f:
            msg = email.message_from_binary_file(f, policy=policy.default)
        body = f"Subject: {msg.get('subject', '')}\nFrom: {msg.get('from', '')}\nDate: {msg.get('date', '')}\n\n"
        if msg.get_body(preferencelist=("plain",)):
            body += msg.get_body(preferencelist=("plain",)).get_content()
        elif msg.get_body(preferencelist=("html",)):
            body += msg.get_body(preferencelist=("html",)).get_content()
    
    # If we got image/PDF attachments, try extracting from the first one
    if attachments:
        att_path, ext = attachments[0]
        try:
            if ext == ".pdf":
                return extract_from_pdf(att_path)
            else:
                return extract_from_image(att_path)
        finally:
            for p, _ in attachments:
                try:
                    import os; os.unlink(p)
                except OSError:
                    pass
    
    # Otherwise extract from the email body text
    if body.strip():
        return extract_from_text(body)
    
    raise ValueError("No extractable content found in email")
