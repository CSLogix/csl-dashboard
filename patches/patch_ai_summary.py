"""Patch: Add POST /api/load/{efj}/summary endpoint for AI-powered load summaries."""

ENDPOINT_CODE = '''

@app.post("/api/load/{efj}/summary")
async def api_load_summary(efj: str, request: Request):
    """Generate an AI-powered operational summary for a load using Claude."""
    if not config.ANTHROPIC_API_KEY:
        raise HTTPException(422, "ANTHROPIC_API_KEY not configured")

    body = await request.json()
    shipment = body.get("shipment", {})
    emails = body.get("emails", [])
    documents = body.get("documents", [])
    driver = body.get("driver", {})
    tracking = body.get("tracking")
    today = datetime.now().strftime("%Y-%m-%d")

    lines = [
        f"Load: {shipment.get('efj', efj)}",
        f"Move Type: {shipment.get('moveType', 'Unknown')}",
        f"Account: {shipment.get('account', 'Unknown')}",
        f"Status: {shipment.get('rawStatus', shipment.get('status', 'Unknown'))}",
        f"Container/Load#: {shipment.get('container', 'N/A')}",
        f"Carrier: {shipment.get('carrier', 'N/A')}",
        f"Origin: {shipment.get('origin', 'N/A')} -> Destination: {shipment.get('destination', 'N/A')}",
        f"ETA: {shipment.get('eta', 'N/A')}",
        f"LFD/Cutoff: {shipment.get('lfd', 'N/A')}",
        f"Pickup: {shipment.get('pickupDate', 'N/A')}",
        f"Delivery: {shipment.get('deliveryDate', 'N/A')}",
        f"BOL: {shipment.get('bol', 'N/A')}",
        f"SSL/Vessel: {shipment.get('ssl', 'N/A')}",
        f"Return Port: {shipment.get('returnPort', 'N/A')}",
        f"Notes: {shipment.get('notes', 'None')}",
        f"Bot Alert: {shipment.get('botAlert', 'None')}",
        f"Rep: {shipment.get('rep', 'N/A')}",
    ]
    if shipment.get('hub'):
        lines.append(f"Hub: {shipment['hub']}")
    if shipment.get('project'):
        lines.append(f"Project: {shipment['project']}")

    if any(driver.get(k) for k in ("driverName", "driverPhone", "driverEmail", "trailerNumber")):
        lines.append("")
        lines.append("--- Driver/Carrier Contact ---")
        if driver.get("driverName"):
            lines.append(f"Driver: {driver['driverName']}")
        if driver.get("driverPhone"):
            lines.append(f"Phone: {driver['driverPhone']}")
        if driver.get("driverEmail"):
            lines.append(f"Email: {driver['driverEmail']}")
        if driver.get("carrierEmail"):
            lines.append(f"Carrier Email: {driver['carrierEmail']}")
        if driver.get("trailerNumber"):
            lines.append(f"Trailer: {driver['trailerNumber']}")

    if tracking:
        lines.append("")
        lines.append("--- Tracking Status ---")
        lines.append(f"Tracking Status: {tracking.get('trackingStatus', 'N/A')}")
        if tracking.get('eta'):
            lines.append(f"Tracking ETA: {tracking['eta']}")
        if tracking.get('behindSchedule'):
            lines.append("WARNING: Behind Schedule")
        if tracking.get('cantMakeIt'):
            lines.append(f"CRITICAL: {tracking['cantMakeIt']}")

    lines.append("")
    lines.append("--- Documents on File ---")
    if documents:
        doc_types = {}
        for d in documents:
            dt = d.get("doc_type", "other")
            doc_types.setdefault(dt, []).append(d.get("original_name", "unknown"))
        for dt, names in doc_types.items():
            lines.append(f"  {dt}: {len(names)} file(s) - {', '.join(names[:3])}")
    else:
        lines.append("  No documents uploaded")

    doc_type_set = {d.get("doc_type") for d in documents}
    missing_docs = []
    if "bol" not in doc_type_set:
        missing_docs.append("BOL")
    if "pod" not in doc_type_set:
        missing_docs.append("POD")
    if "customer_rate" not in doc_type_set:
        missing_docs.append("Customer Rate Con")
    if "carrier_rate" not in doc_type_set:
        missing_docs.append("Carrier Rate Con")
    if missing_docs:
        lines.append(f"  MISSING: {', '.join(missing_docs)}")

    lines.append("")
    lines.append("--- Recent Email Activity ---")
    if emails:
        lines.append(f"Total emails: {len(emails)}")
        for e in emails[:5]:
            sent = e.get('sent_at', '')[:10] if e.get('sent_at') else 'N/A'
            lines.append(f"  [{sent}] From: {e.get('sender', 'Unknown')}")
            lines.append(f"    Subject: {e.get('subject', 'No subject')}")
            if e.get('body_preview'):
                lines.append(f"    Preview: {e['body_preview'][:120]}")
    else:
        lines.append("  No emails indexed for this load")

    context_str = "\\n".join(lines)

    system_prompt = (
        "You are a logistics operations assistant for Evans Delivery (EFJ Operations). "
        "You produce concise, actionable load summaries for dispatchers.\\n\\n"
        "Rules:\\n"
        "- Output exactly 3-5 bullet points using the bullet character\\n"
        "- Each bullet should be one sentence, max 20 words\\n"
        "- First bullet: Current status and location context\\n"
        "- Flag any issues: behind schedule, missing documents, approaching LFD, no driver, no tracking\\n"
        "- Note document completeness (what is present vs missing)\\n"
        "- Summarize recent email activity if any\\n"
        "- If everything looks good, say so\\n"
        "- Today is: " + today + "\\n"
        "- Use plain text only, no markdown, no bold, no headers\\n"
        "- Be direct and operational for experienced dispatchers"
    )

    try:
        import anthropic
        client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
        message = client.messages.create(
            model="claude-haiku-4-5-20251001",
            max_tokens=300,
            system=system_prompt,
            messages=[{"role": "user", "content": f"Generate an operational summary for this load:\\n\\n{context_str}"}],
        )
        summary_text = message.content[0].text.strip()
        return JSONResponse({"summary": summary_text})
    except Exception as e:
        log.error("AI summary generation failed for %s: %s", efj, e)
        raise HTTPException(500, f"Summary generation failed: {str(e)}")

'''

# ─── Apply Patch ───
APP_PATH = "/root/csl-bot/csl-doc-tracker/app.py"

with open(APP_PATH, "r") as f:
    content = f.read()

if "api_load_summary" in content:
    print("Already patched - ai summary endpoint exists")
else:
    marker = '@app.get("/api/unmatched-emails")'
    if marker in content:
        content = content.replace(marker, ENDPOINT_CODE + "\n" + marker)
        with open(APP_PATH, "w") as f:
            f.write(content)
        print("SUCCESS: AI summary endpoint added before unmatched-emails")
    else:
        print("ERROR: Could not find insertion marker")
