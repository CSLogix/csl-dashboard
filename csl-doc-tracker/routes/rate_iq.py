import base64
import json
import re

from collections import defaultdict
from urllib.parse import unquote

from fastapi import APIRouter, Query, Request
from fastapi.responses import JSONResponse

import config
import database as db
from shared import log


# ── Port cluster normalization for lane grouping ─────────────────────
# Maps common port name variants to a single canonical cluster name.
# Used so that "Los Angeles", "Long Beach", "LA/LB", "LBCT" etc. all
# group into one lane instead of appearing as separate results.
PORT_CLUSTERS = {
    # LA/LB
    "la/lb": "LA/LB",
    "la/lb ports": "LA/LB",
    "lalb": "LA/LB",
    "lax": "LA/LB",
    "los angeles": "LA/LB",
    "long beach": "LA/LB",
    "los angeles/long beach": "LA/LB",
    "lbct": "LA/LB",
    "apm terminals": "LA/LB",
    "apm san pedro": "LA/LB",
    "port of los angeles": "LA/LB",
    "trapac": "LA/LB",
    "everport": "LA/LB",
    "ssa marine": "LA/LB",
    "pct": "LA/LB",
    "san pedro": "LA/LB",
    "wilmington": "LA/LB",
    "carson": "LA/LB",
    # NY/NJ
    "ny/nj": "NY/NJ",
    "ny/nj ports": "NY/NJ",
    "port newark": "NY/NJ",
    "pnct": "NY/NJ",
    "elizabeth": "NY/NJ",
    "bayonne": "NY/NJ",
    "maher": "NY/NJ",
    "newark": "NY/NJ",
    "nynj": "NY/NJ",
    "nj/ny": "NY/NJ",
    "port liberty": "NY/NJ",
    "nyc port": "NY/NJ",
    "nyc": "NY/NJ",
    "new york city": "NY/NJ",
    "new york": "NY/NJ",
    "bayonne terminal": "NY/NJ",
    "apmt": "NY/NJ",
    "global terminal": "NY/NJ",
    "port liberty, ny": "NY/NJ",
    "nyc port, ny": "NY/NJ",
    "nyc, ny": "NY/NJ",
    "new york city, ny": "NY/NJ",
    "new york, ny": "NY/NJ",
    "bayonne, nj": "NY/NJ",
    "bayonne terminal, nj": "NY/NJ",
    "elizabeth, nj": "NY/NJ",
    "newark, nj": "NY/NJ",
    "port newark, nj": "NY/NJ",
    # Savannah
    "savannah": "Savannah",
    "savannah ports": "Savannah",
    "garden city": "Savannah",
    "garden city terminal": "Savannah",
    # Houston
    "houston": "Houston",
    "houston ports": "Houston",
    "barbours cut": "Houston",
    "barbour's cut": "Houston",
    "bayport": "Houston",
    "houston, tx": "Houston",
    "houston tx": "Houston",
    # Charleston
    "charleston": "Charleston",
    "wando welch": "Charleston",
    # Norfolk / Virginia
    "norfolk": "Norfolk",
    "virginia": "Norfolk",
    "portsmouth": "Norfolk",
    "nit": "Norfolk",
    # Oakland
    "oakland": "Oakland",
}

# Reverse map: cluster → all aliases (for search expansion)
_CLUSTER_ALIASES = defaultdict(set)
for _alias, _cluster in PORT_CLUSTERS.items():
    _CLUSTER_ALIASES[_cluster].add(_alias)


def _normalize_port(text: str) -> str:
    """Normalize a port/origin/destination string to its cluster name, or return as-is."""
    if not text:
        return ""
    lower = text.strip().lower()
    # Exact match
    if lower in PORT_CLUSTERS:
        return PORT_CLUSTERS[lower]
    # Try without state suffix: "houston, tx" → "houston"
    no_state = re.sub(r',\s*[a-z]{2}$', '', lower).strip()
    if no_state != lower and no_state in PORT_CLUSTERS:
        return PORT_CLUSTERS[no_state]
    # Substring match (e.g. "Long Beach Container Terminal" contains "long beach")
    for alias, cluster in sorted(PORT_CLUSTERS.items(), key=lambda x: -len(x[0])):
        if alias in lower:
            return cluster
    # Strip state suffix for general city grouping: "Dallas, TX" → "Dallas"
    if no_state != lower:
        # Title case the city name
        return no_state.title()
    return text.strip()


def _expand_search_terms(query: str) -> list[str]:
    """Given a search term like 'la' or 'long beach', return all port aliases
    that should also be matched, plus the original term."""
    if not query:
        return []
    q = query.strip().lower()
    terms = {q}
    # Check if query matches any alias → expand to all aliases in that cluster
    matched_cluster = None
    if q in PORT_CLUSTERS:
        matched_cluster = PORT_CLUSTERS[q]
    else:
        for alias, cluster in PORT_CLUSTERS.items():
            if q in alias or alias in q:
                matched_cluster = cluster
                break
    if matched_cluster:
        terms.update(_CLUSTER_ALIASES[matched_cluster])
        terms.add(matched_cluster.lower())
    return list(terms)


# ── Shared extraction helpers ────────────────────────────────────────

_CARRIER_EXTRACT_PROMPT = """Extract rate/quote information from this carrier rate confirmation or email.
Look carefully for the carrier's MC# and DOT# — these are often in the email signature block at the bottom.
Return ONLY valid JSON (no markdown, no explanation) with these fields:
{
  "carrier_name": "string or null",
  "carrier_mc": "MC number (digits only) or null",
  "origin": "city, state or full address or null",
  "destination": "city, state or full address or null",
  "shipment_type": "Dray|FTL|LTL|Transload|OTR or null",
  "rate_amount": "total all-in rate as numeric string or null",
  "linehaul_items": [{"description": "string", "rate": "numeric string"}],
  "accessorials": [{"charge": "name", "rate": "numeric string", "frequency": "flat|per day|per hour"}]
}
Only include fields you can confidently extract. For linehaul_items, list each charge line separately (linehaul, fuel surcharge, stop charges, etc). Omit null fields."""

_MARKET_EXTRACT_PROMPT = """Extract ALL rate entries from this LoadMatch / RFQ / market rate screenshot or document.
This contains multiple rate quotes for the same lane — extract every row.
Return ONLY valid JSON (no markdown, no explanation):
{
  "origin": "port or origin city/state — if visible",
  "destination": "destination city/state — if visible",
  "rates": [
    {
      "date": "YYYY-MM-DD or null",
      "terminal": "terminal or carrier name or null",
      "base_rate": "numeric string (dollars, no $ sign)",
      "fsc_pct": "numeric string (percentage, no % sign) or 0",
      "total": "numeric string (total all-in rate)"
    }
  ]
}
Extract every row of rate data you can see. If a column is missing, set it to null.
Dates should be normalized to YYYY-MM-DD format. Omit $ signs and commas from numbers."""


def _call_claude(content: list) -> dict:
    """
    Send prepared content blocks to the Claude API and return the parsed JSON response.
    
    Parameters:
        content (list): List of content blocks formatted for the Anthropic/Claude request.
    
    Returns:
        dict: Parsed JSON object from Claude's response.
    
    Raises:
        json.JSONDecodeError: If the API response cannot be parsed as JSON.
        Exception: Propagates errors raised by the Anthropics/Claude client (e.g., network or API errors).
    """
    import anthropic
    client = anthropic.Anthropic(api_key=config.ANTHROPIC_API_KEY)
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=2048,
        messages=[{"role": "user", "content": content}],
    )
    text = message.content[0].text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[-1].rsplit("```", 1)[0].strip()
    return json.loads(text)


def _file_to_content_blocks(file_bytes: bytes, filename: str, prompt: str) -> list:
    """Convert uploaded file bytes into Claude API content blocks + prompt."""
    ext = filename.lower().rsplit(".", 1)[-1] if "." in filename else ""
    blocks = []

    if ext in ("png", "jpg", "jpeg", "gif", "webp"):
        media_map = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg",
                     "gif": "image/gif", "webp": "image/webp"}
        blocks.append({
            "type": "image",
            "source": {"type": "base64", "media_type": media_map.get(ext, "image/png"),
                        "data": base64.b64encode(file_bytes).decode()},
        })
    elif ext == "pdf":
        blocks.append({
            "type": "document",
            "source": {"type": "base64", "media_type": "application/pdf",
                        "data": base64.b64encode(file_bytes).decode()},
        })
    elif ext == "msg":
        try:
            import extract_msg, io as _io
            msg = extract_msg.openMsg(_io.BytesIO(file_bytes))
            parts = []
            if msg.subject: parts.append("Subject: " + str(msg.subject))
            if msg.sender: parts.append("From: " + str(msg.sender))
            if msg.body: parts.append(msg.body)
            text_content = "\n".join(parts)
            # Also grab image attachments
            for att in (msg.attachments or []):
                att_name = (att.longFilename or att.shortFilename or "").lower()
                if att_name.endswith((".png", ".jpg", ".jpeg")) and att.data:
                    ext2 = att_name.rsplit(".", 1)[-1]
                    mt = {"png": "image/png", "jpg": "image/jpeg", "jpeg": "image/jpeg"}.get(ext2, "image/png")
                    blocks.append({"type": "image", "source": {"type": "base64", "media_type": mt,
                                                                 "data": base64.b64encode(att.data).decode()}})
            blocks.append({"type": "text", "text": text_content[:8000]})
        except Exception:
            # Brute-force ASCII extraction fallback
            raw = file_bytes.decode("latin-1", errors="replace")
            ascii_blocks = re.findall(r"[ -~]{20,}", raw)
            blocks.append({"type": "text", "text": "\n".join(ascii_blocks)[:8000]})
    elif ext in ("eml", "txt", "csv"):
        try:
            text_content = file_bytes.decode("utf-8", errors="replace")
        except Exception:
            text_content = file_bytes.decode("latin-1", errors="replace")
        blocks.append({"type": "text", "text": text_content[:8000]})
    elif ext in ("htm", "html"):
        raw = file_bytes.decode("utf-8", errors="replace")
        text_content = re.sub(r"<[^>]+>", " ", raw)
        text_content = re.sub(r"\s+", " ", text_content).strip()
        blocks.append({"type": "text", "text": text_content[:8000]})
    else:
        try:
            text_content = file_bytes.decode("utf-8", errors="replace")
        except Exception:
            text_content = file_bytes.decode("latin-1", errors="replace")
        blocks.append({"type": "text", "text": text_content[:8000]})

    blocks.append({"type": "text", "text": prompt})
    return blocks

router = APIRouter()


@router.get("/api/rate-iq")
async def api_rate_iq():
    """
    Rate IQ — return carrier rate history grouped by lane for scorecard comparison.
    Each lane shows all carrier quotes received, sorted by rate.
    """
    with db.get_cursor() as cur:
        # Get parsed rate quotes from rate_quotes table
        cur.execute("""
            SELECT rq.id, rq.email_thread_id, rq.efj, rq.lane, rq.origin,
                   rq.destination, rq.miles, rq.move_type, rq.carrier_name,
                   rq.carrier_email, rq.rate_amount, rq.rate_unit,
                   rq.quote_date, rq.indexed_at, rq.status
            FROM rate_quotes rq
            ORDER BY rq.quote_date DESC NULLS LAST
            LIMIT 500
        """)
        rate_quotes = cur.fetchall()
        # Get carrier rate emails with lane info
        cur.execute("""
            SELECT et.id, et.efj, et.sender, et.subject, et.body_preview,
                   et.lane, et.email_type, et.sent_at, et.indexed_at
            FROM email_threads et
            WHERE et.email_type = 'carrier_rate'
            ORDER BY et.sent_at DESC
            LIMIT 200
        """)
        carrier_emails = cur.fetchall()
        # Get carrier rate documents
        cur.execute("""
            SELECT ld.id, ld.efj, ld.doc_type, ld.original_name,
                   ld.uploaded_at, ld.uploaded_by
            FROM load_documents ld
            WHERE ld.doc_type = 'carrier_rate'
            ORDER BY ld.uploaded_at DESC
            LIMIT 200
        """)
        carrier_docs = cur.fetchall()
        # Get customer rate requests
        cur.execute("""
            SELECT et.id, et.efj, et.sender, et.subject, et.body_preview,
                   et.lane, et.email_type, et.sent_at
            FROM email_threads et
            WHERE et.email_type = 'customer_rate'
            ORDER BY et.sent_at DESC
            LIMIT 100
        """)
        customer_emails = cur.fetchall()

    # Group rate quotes by lane (parsed data with actual $$ amounts)
    lanes = {}
    for rq in rate_quotes:
        lane_key = rq["lane"] or "Unknown Lane"
        if lane_key not in lanes:
            lanes[lane_key] = {
                "lane": lane_key, "miles": None, "move_type": None,
                "carrier_quotes": [], "customer_requests": [],
                "cheapest": None, "avg_rate": None,
            }
        entry = lanes[lane_key]
        if rq["miles"] and not entry["miles"]:
            entry["miles"] = rq["miles"]
        if rq["move_type"] and not entry["move_type"]:
            entry["move_type"] = rq["move_type"]
        entry["carrier_quotes"].append({
            "id": rq["id"],
            "efj": rq["efj"],
            "carrier": rq["carrier_name"] or rq["carrier_email"] or "Unknown",
            "carrier_email": rq["carrier_email"],
            "rate": float(rq["rate_amount"]) if rq["rate_amount"] else None,
            "rate_unit": rq["rate_unit"],
            "date": rq["quote_date"].isoformat() if rq["quote_date"] else None,
            "status": rq["status"],
            "move_type": rq["move_type"],
        })

    # Also add carrier emails that might not have parsed rates
    for e in carrier_emails:
        lane_key = e["lane"] or "Unknown Lane"
        if lane_key not in lanes:
            lanes[lane_key] = {
                "lane": lane_key, "miles": None, "move_type": None,
                "carrier_quotes": [], "customer_requests": [],
                "cheapest": None, "avg_rate": None,
            }
        # Only add if not already represented by a rate_quote
        existing_ids = {q.get("efj") for q in lanes[lane_key]["carrier_quotes"]}
        if e["efj"] not in existing_ids:
            lanes[lane_key]["carrier_quotes"].append({
                "id": e["id"],
                "efj": e["efj"],
                "carrier": e["sender"],
                "carrier_email": e["sender"],
                "rate": None,
                "rate_unit": None,
                "date": e["sent_at"].isoformat() if e["sent_at"] else None,
                "status": "pending",
                "move_type": None,
                "source": "email",
            })

    # Add customer requests to their lanes
    for e in customer_emails:
        lane_key = e["lane"] or "Unknown Lane"
        if lane_key not in lanes:
            lanes[lane_key] = {
                "lane": lane_key, "miles": None, "move_type": None,
                "carrier_quotes": [], "customer_requests": [],
                "cheapest": None, "avg_rate": None,
            }
        lanes[lane_key]["customer_requests"].append({
            "id": e["id"],
            "efj": e["efj"],
            "sender": e["sender"],
            "subject": e["subject"],
            "sent_at": e["sent_at"].isoformat() if e["sent_at"] else None,
        })

    # Compute cheapest + avg per lane
    for lane_data in lanes.values():
        rates = [q["rate"] for q in lane_data["carrier_quotes"] if q.get("rate")]
        if rates:
            min_rate = min(rates)
            cheapest_q = next(q for q in lane_data["carrier_quotes"] if q.get("rate") == min_rate)
            lane_data["cheapest"] = {"carrier": cheapest_q["carrier"], "rate": min_rate}
            lane_data["avg_rate"] = round(sum(rates) / len(rates), 2)

    # Carrier scorecard — frequency, win rate, avg rate
    carrier_scores = {}
    for rq in rate_quotes:
        carrier_key = rq["carrier_email"] or rq["carrier_name"] or "Unknown"
        if carrier_key not in carrier_scores:
            carrier_scores[carrier_key] = {
                "carrier": rq["carrier_name"] or carrier_key,
                "quote_count": 0, "win_count": 0,
                "total_rate": 0, "rated_count": 0,
                "lanes_covered": set(),
            }
        cs = carrier_scores[carrier_key]
        cs["quote_count"] += 1
        if rq["status"] == "accepted":
            cs["win_count"] += 1
        if rq["rate_amount"]:
            cs["total_rate"] += float(rq["rate_amount"])
            cs["rated_count"] += 1
        if rq["lane"]:
            cs["lanes_covered"].add(rq["lane"])

    # Fallback: also count carrier emails not in rate_quotes
    for e in carrier_emails:
        sender = e["sender"] or "Unknown"
        sender_key = sender.split("<")[-1].replace(">", "").strip() if "<" in sender else sender
        if sender_key not in carrier_scores:
            carrier_scores[sender_key] = {
                "carrier": sender,
                "quote_count": 0, "win_count": 0,
                "total_rate": 0, "rated_count": 0,
                "lanes_covered": set(),
            }
            carrier_scores[sender_key]["quote_count"] += 1
            if e["lane"]:
                carrier_scores[sender_key]["lanes_covered"].add(e["lane"])

    scorecard = []
    for key, data in carrier_scores.items():
        scorecard.append({
            "carrier": data["carrier"],
            "quote_count": data["quote_count"],
            "win_count": data["win_count"],
            "avg_rate": round(data["total_rate"] / data["rated_count"], 2) if data["rated_count"] else None,
            "lanes_covered": len(data["lanes_covered"]),
            "lane_list": list(data["lanes_covered"]),
        })
    scorecard.sort(key=lambda x: x["quote_count"], reverse=True)

    return {
        "lanes": list(lanes.values()),
        "scorecard": scorecard,
        "carrier_docs": [
            {
                "id": d["id"], "efj": d["efj"], "doc_type": d["doc_type"],
                "original_name": d["original_name"],
                "uploaded_at": d["uploaded_at"].isoformat() if d["uploaded_at"] else None,
            }
            for d in carrier_docs
        ],
        "total_carrier_quotes": len(carrier_emails),
        "total_customer_requests": len(customer_emails),
        "total_rate_quotes": len(rate_quotes),
    }


@router.get("/api/rate-iq/lane/{lane}")
async def api_rate_iq_lane(lane: str):
    """Get all quotes for a specific lane."""
    lane = unquote(lane)
    with db.get_cursor() as cur:
        cur.execute("""
        SELECT et.id, et.efj, et.sender, et.subject, et.body_preview,
               et.lane, et.email_type, et.sent_at
        FROM email_threads et
        WHERE et.lane = %s
        ORDER BY et.sent_at DESC
        """, (lane,))
        emails = cur.fetchall()
    results = []
    for e in emails:
        results.append({
            "id": e["id"],
            "efj": e["efj"],
            "sender": e["sender"],
            "subject": e["subject"],
            "body_preview": e["body_preview"],
            "lane": e["lane"],
            "email_type": e["email_type"],
            "sent_at": e["sent_at"].isoformat() if e["sent_at"] else None,
        })
    return {"lane": lane, "emails": results}


@router.patch("/api/rate-iq/{quote_id}")
async def update_rate_quote(quote_id: int, request: Request):
    """Accept or reject a rate quote."""
    body = await request.json()
    new_status = body.get("status", "").strip()
    if new_status not in ("accepted", "rejected", "pending"):
        return JSONResponse(status_code=400, content={"error": "status must be accepted, rejected, or pending"})
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute(
                "UPDATE rate_quotes SET status = %s WHERE id = %s RETURNING id, lane, carrier_name, rate_amount",
                (new_status, quote_id),
            )
            row = cur.fetchone()
    if not row:
        return JSONResponse(status_code=404, content={"error": "quote not found"})
    # When accepting, reject competing pending quotes for same EFJ
    if new_status == "accepted" and row.get("efj"):
        with db.get_conn() as conn2:
            with db.get_cursor(conn2) as cur2:
                cur2.execute(
                    "UPDATE rate_quotes SET status = 'rejected' WHERE efj = %s AND id != %s AND status = 'pending'",
                    (row["efj"], quote_id),
                )
                if cur2.rowcount:
                    log.info("Rate IQ: rejected %d competing quotes for %s", cur2.rowcount, row["efj"])
    return {"ok": True, "id": row["id"], "status": new_status,
            "carrier": row["carrier_name"], "rate": float(row["rate_amount"]) if row["rate_amount"] else None}


@router.get("/api/rate-iq/outbound-quotes")
async def api_outbound_quotes(
    customer: str = Query(""),
    origin:   str = Query(""),
    dest:     str = Query(""),
    limit:    int = Query(50),
):
    """
    Quote archive — Evans outbound customer rate quotes indexed from sent mail.
    Searchable by customer name, origin, destination.
    """
    conditions = ["rq.quote_direction = 'outbound'", "rq.total_estimate IS NOT NULL"]
    params: list = []
    if customer.strip():
        conditions.append("(LOWER(rq.customer_name) LIKE %s OR LOWER(rq.carrier_email) LIKE %s)")
        params += [f"%{customer.strip().lower()}%", f"%{customer.strip().lower()}%"]
    if origin.strip():
        conditions.append("(LOWER(rq.origin) LIKE %s OR LOWER(rq.lane) LIKE %s)")
        params += [f"%{origin.strip().lower()}%", f"%{origin.strip().lower()}%"]
    if dest.strip():
        conditions.append("(LOWER(rq.destination) LIKE %s OR LOWER(rq.lane) LIKE %s)")
        params += [f"%{dest.strip().lower()}%", f"%{dest.strip().lower()}%"]
    where = " AND ".join(conditions)
    params.append(limit)
    with db.get_cursor() as cur:
        cur.execute(f"""
            SELECT rq.id, rq.efj, rq.lane, rq.origin, rq.destination,
                   rq.customer_name, rq.carrier_email AS customer_email,
                   rq.move_type, rq.linehaul, rq.chassis_per_day,
                   rq.accessorials, rq.total_estimate,
                   rq.quote_date, rq.indexed_at
            FROM rate_quotes rq
            WHERE {where}
            ORDER BY rq.quote_date DESC NULLS LAST
            LIMIT %s
        """, params)
        rows = cur.fetchall()
    return {
        "quotes": [
            {
                "id":            r["id"],
                "efj":           r["efj"],
                "lane":          r["lane"],
                "origin":        r["origin"],
                "destination":   r["destination"],
                "customer":      r["customer_name"],
                "customer_email":r["customer_email"],
                "move_type":     r["move_type"],
                "linehaul":      float(r["linehaul"]) if r["linehaul"] else None,
                "chassis_per_day": float(r["chassis_per_day"]) if r["chassis_per_day"] else None,
                "accessorials":  r["accessorials"],
                "total":         float(r["total_estimate"]) if r["total_estimate"] else None,
                "quote_date":    r["quote_date"].isoformat() if r["quote_date"] else None,
                "indexed_at":    r["indexed_at"].isoformat() if r["indexed_at"] else None,
            }
            for r in rows
        ],
        "count": len(rows),
    }


@router.get("/api/rate-iq/search-lane")
async def api_search_lane(origin: str = Query(""), destination: str = Query("")):
    """
    Unified lane rate search: rate_quotes + lane_rates + won quotes.
    Groups results by normalized lane. Returns lane_groups[] with
    floor/avg/ceiling per lane, plus flat matches[] for backwards compat.
    """
    if not origin and not destination:
        return {"matches": [], "lane_groups": [], "carriers": [], "stats": {}}

    origin_q = origin.strip().lower()
    dest_q = destination.strip().lower()

    # Expand search terms to include port cluster aliases
    # e.g. "la" → ["la", "la/lb", "los angeles", "long beach", "lbct", ...]
    origin_terms = _expand_search_terms(origin_q) if origin_q else []
    dest_terms = _expand_search_terms(dest_q) if dest_q else []

    # Build WHERE conditions for each source (with port alias expansion)
    def _build_conditions(o_col, d_col, lane_col=None):
        conds, params = [], []
        if origin_terms:
            o_likes = []
            for term in origin_terms:
                o_likes.append(f"LOWER({o_col}) LIKE %s")
                params.append(f"%{term}%")
                if lane_col:
                    o_likes.append(f"LOWER({lane_col}) LIKE %s")
                    params.append(f"%{term}%")
            conds.append(f"({' OR '.join(o_likes)})")
        if dest_terms:
            d_likes = []
            for term in dest_terms:
                d_likes.append(f"LOWER({d_col}) LIKE %s")
                params.append(f"%{term}%")
                if lane_col:
                    d_likes.append(f"LOWER({lane_col}) LIKE %s")
                    params.append(f"%{term}%")
            conds.append(f"({' OR '.join(d_likes)})")
        return (" AND ".join(conds) if conds else "TRUE"), params

    rq_where, rq_params = _build_conditions("rq.origin", "rq.destination", "rq.lane")
    lr_where, lr_params = _build_conditions("lr.port", "lr.destination")
    # won quotes use pod/final_delivery
    wq_where, wq_params = _build_conditions("q.pod", "q.final_delivery")
    # market rates (LoadMatch benchmarks)
    mr_where, mr_params = _build_conditions("mr.origin", "mr.destination")

    with db.get_cursor() as cur:
        # ── Unified UNION: rate_quotes + lane_rates + won quotes ──
        cur.execute(f"""
            SELECT origin, destination,
                   COALESCE(NULLIF(TRIM(origin),'') || ' \u2192 ' || NULLIF(TRIM(destination),''), lane, '') AS norm_lane,
                   carrier_name, carrier_email, rate_amount, rate_unit,
                   quote_date, source, move_type, id, miles, status
            FROM (
                -- Email-extracted carrier rates
                SELECT rq.origin, rq.destination, rq.lane,
                       rq.carrier_name, rq.carrier_email, rq.rate_amount, rq.rate_unit,
                       rq.quote_date, 'email' AS source, rq.move_type, rq.id, rq.miles, rq.status
                FROM rate_quotes rq
                WHERE {rq_where} AND rq.rate_amount IS NOT NULL

                UNION ALL

                -- Excel-imported lane rates
                SELECT lr.port AS origin, lr.destination,
                       lr.port || ' \u2192 ' || lr.destination AS lane,
                       lr.carrier_name, NULL AS carrier_email,
                       lr.dray_rate AS rate_amount, 'flat' AS rate_unit,
                       lr.created_at AS quote_date, 'import' AS source,
                       lr.move_type, lr.id, NULL AS miles, 'import' AS status
                FROM lane_rates lr
                WHERE {lr_where} AND lr.dray_rate IS NOT NULL

                UNION ALL

                -- Won/accepted customer quotes (carrier cost only)
                SELECT q.pod AS origin, q.final_delivery AS destination,
                       q.pod || ' \u2192 ' || q.final_delivery AS lane,
                       q.carrier_name, NULL AS carrier_email,
                       q.carrier_total AS rate_amount, 'flat' AS rate_unit,
                       q.created_at AS quote_date, 'quote' AS source,
                       q.shipment_type AS move_type, q.id, NULL AS miles, 'accepted' AS status
                FROM quotes q
                WHERE {wq_where} AND q.status = 'accepted' AND q.carrier_total > 0

                UNION ALL

                -- Market rates (LoadMatch benchmarks)
                SELECT mr.origin, mr.destination,
                       mr.origin || ' → ' || mr.destination AS lane,
                       COALESCE(mr.terminal, mr.source) AS carrier_name, NULL AS carrier_email,
                       mr.total AS rate_amount, 'flat' AS rate_unit,
                       mr.rate_date AS quote_date, 'market' AS source,
                       mr.move_type, mr.id, NULL AS miles, 'benchmark' AS status
                FROM market_rates mr
                WHERE {mr_where} AND mr.total IS NOT NULL
            ) combined
            ORDER BY rate_amount ASC NULLS LAST, quote_date DESC NULLS LAST
            LIMIT 100
        """, rq_params + lr_params + wq_params + mr_params)
        all_rows = cur.fetchall()

        # ── Directory carriers (with port alias expansion) ──
        c_conds, c_params = [], []
        if origin_terms:
            o_likes = []
            for term in origin_terms:
                o_likes.append("LOWER(c.pickup_area) LIKE %s")
                c_params.append(f"%{term}%")
            c_conds.append(f"({' OR '.join(o_likes)})")
        if dest_terms:
            d_likes = []
            for term in dest_terms:
                d_likes.append("LOWER(c.destination_area) LIKE %s")
                c_params.append(f"%{term}%")
            c_conds.append(f"({' OR '.join(d_likes)})")
        c_where = " OR ".join(c_conds) if c_conds else "FALSE"
        try:
            cur.execute(f"""
                SELECT c.id, c.name, c.mc_number, c.email, c.phone,
                       c.pickup_area, c.destination_area,
                       c.can_dray, c.hazmat, c.overweight, c.date_quoted
                FROM carriers c WHERE {c_where}
                ORDER BY c.date_quoted DESC NULLS LAST LIMIT 20
            """, c_params)
            matching_carriers = cur.fetchall()
        except Exception:
            matching_carriers = []

    # ── Build flat matches (backwards compat) ──
    matches = []
    for r in all_rows:
        matches.append({
            "id": r["id"],
            "lane": r["norm_lane"],
            "origin": r["origin"],
            "destination": r["destination"],
            "miles": r["miles"],
            "carrier": r["carrier_name"] or "Unknown",
            "carrier_email": r["carrier_email"],
            "rate": float(r["rate_amount"]) if r["rate_amount"] else None,
            "rate_unit": r["rate_unit"],
            "date": r["quote_date"].isoformat() if r["quote_date"] else None,
            "status": r["status"],
            "source": r["source"],
            "move_type": r["move_type"],
        })

    # ── Group by normalized lane (bidirectional, port cluster aware) ──
    # Merges A→B and B→A into a single lane group so round-trip lanes
    # aren't split into separate cards.
    lane_map = defaultdict(list)
    lane_dir_counts = defaultdict(lambda: defaultdict(int))  # biKey → {dir_string: count}
    for m in matches:
        norm_o = _normalize_port(m["origin"] or "").lower()
        norm_d = _normalize_port(m["destination"] or "").lower()
        # Bidirectional key: sort endpoints so A→B and B→A share a key
        bi_key = tuple(sorted([norm_o, norm_d]))
        lane_map[bi_key].append(m)
        dir_str = f"{norm_o}|{norm_d}"
        lane_dir_counts[bi_key][dir_str] += 1

    lane_groups = []
    for bi_key, group in sorted(
        lane_map.items(),
        key=lambda kv: min((q["rate"] or 9e9) for q in kv[1])
    ):
        rates = [q["rate"] for q in group if q["rate"]]
        source_counts = {}
        for q in group:
            source_counts[q["source"]] = source_counts.get(q["source"], 0) + 1
        last_date = max((q["date"] or "") for q in group) or None
        # Use the most common direction as primary display
        dir_counts = lane_dir_counts[bi_key]
        primary_dir = max(dir_counts, key=dir_counts.get)
        prim_o, prim_d = primary_dir.split("|")
        norm_origin = _normalize_port(prim_o) or prim_o
        norm_dest = _normalize_port(prim_d) or prim_d
        bidirectional = len(dir_counts) > 1
        arrow = " ↔ " if bidirectional else " → "
        lane_groups.append({
            "lane": f"{norm_origin}{arrow}{norm_dest}",
            "origin": norm_origin,
            "destination": norm_dest,
            "bidirectional": bidirectional,
            "count": len(group),
            "rated_count": len(rates),
            "floor": min(rates) if rates else None,
            "avg": round(sum(rates) / len(rates), 2) if rates else None,
            "ceiling": max(rates) if rates else None,
            "carriers": len(set(q["carrier"] for q in group)),
            "last_quoted": last_date,
            "sources": source_counts,  # {"email": 3, "import": 2}
            "quotes": sorted(group, key=lambda q: q["rate"] or 9e9),
        })

    # Sort lane_groups: most quotes first
    lane_groups.sort(key=lambda g: g["rated_count"], reverse=True)

    # ── Global stats ──
    all_rates = [m["rate"] for m in matches if m["rate"]]
    stats = {}
    if all_rates:
        stats = {
            "floor": min(all_rates),
            "ceiling": max(all_rates),
            "avg": round(sum(all_rates) / len(all_rates), 2),
            "count": len(all_rates),
            "total_carriers": len(set(m["carrier"] for m in matches)),
            "total_lanes": len(lane_groups),
            "sources": {
                "email": sum(1 for m in matches if m["source"] == "email"),
                "import": sum(1 for m in matches if m["source"] == "import"),
                "quote": sum(1 for m in matches if m["source"] == "quote"),
                "market": sum(1 for m in matches if m["source"] == "market"),
            },
        }

    carriers = [
        {
            "id": c["id"], "name": c["name"], "mc": c["mc_number"],
            "email": c["email"], "phone": c["phone"],
            "pickup": c["pickup_area"], "destination": c["destination_area"],
            "can_dray": c["can_dray"], "hazmat": c["hazmat"],
            "overweight": c["overweight"],
            "date_quoted": c["date_quoted"].isoformat() if c["date_quoted"] else None,
        }
        for c in matching_carriers
    ]

    return {"matches": matches, "lane_groups": lane_groups, "carriers": carriers, "stats": stats}


@router.get("/api/lane-stats")
async def api_lane_stats():
    """Top freight corridors by load volume. Future-proof for avg carrier_pay once rate fields exist."""
    with db.get_cursor() as cur:
        cur.execute("""
            SELECT
                TRIM(SPLIT_PART(origin, ',', 1))                           AS origin_city,
                TRIM(SPLIT_PART(TRIM(SPLIT_PART(origin, ',', 2)), ' ', 1)) AS origin_state,
                TRIM(SPLIT_PART(destination, ',', 1))                      AS dest_city,
                TRIM(SPLIT_PART(TRIM(SPLIT_PART(destination, ',', 2)), ' ', 1)) AS dest_state,
                COUNT(*)                                                     AS load_count,
                AVG(customer_rate)                     AS avg_customer_rate
            FROM shipments
            WHERE archived = false
              AND origin    IS NOT NULL AND origin    != ''
              AND destination IS NOT NULL AND destination != ''
              AND origin    LIKE '%,%'
              AND destination LIKE '%,%'
            GROUP BY 1, 2, 3, 4
            ORDER BY load_count DESC
            LIMIT 20
        """)
        rows = cur.fetchall()
    lanes = []
    for r in rows:
        lanes.append({
            "origin_city":  r["origin_city"],
            "origin_state": r["origin_state"],
            "dest_city":    r["dest_city"],
            "dest_state":   r["dest_state"],
            "load_count":   r["load_count"],
            "avg_customer_rate": float(r["avg_customer_rate"]) if r["avg_customer_rate"] else None,
        })
    return {"lanes": lanes}


# ── Manual Intake (carrier rate from email / file / text) ────────────

async def _parse_intake_request(request: Request):
    """
    Parse an incoming manual-intake or extract-preview request and extract text, file, move type, and any pre-extracted override.
    
    When the request is multipart/form-data, reads form fields:
    - "text" (optional)
    - "move_type" (optional, defaults to "dray")
    - "file" (optional file upload; file bytes and filename are returned)
    
    When the request has a JSON body, reads keys:
    - "text" (optional)
    - "move_type" (optional, defaults to "dray")
    - "extracted" (optional pre-reviewed extraction override)
    
    Returns:
        tuple: (text, file_bytes, filename, move_type, extracted_override)
            text (str | None): Trimmed text content if provided, otherwise None.
            file_bytes (bytes | None): Uploaded file contents if provided, otherwise None.
            filename (str): Uploaded filename or empty string.
            move_type (str): Normalized move type (lowercased), defaults to "dray".
            extracted_override (dict | None): Parsed override from JSON "extracted" key, or None.
    """
    content_type = request.headers.get("content-type", "")
    text = None
    file_bytes = None
    filename = ""
    move_type = "dray"
    extracted_override = None

    if "multipart/form-data" in content_type:
        form = await request.form()
        text = form.get("text")
        if text:
            text = str(text)
        move_type = str(form.get("move_type", "dray"))
        file_obj = form.get("file")
        if file_obj and hasattr(file_obj, "read"):
            file_bytes = await file_obj.read()
            filename = getattr(file_obj, "filename", "") or ""
    else:
        body = await request.json()
        text = (body.get("text") or "").strip()
        move_type = (body.get("move_type") or "dray").strip().lower()
        extracted_override = body.get("extracted")

    return text, file_bytes, filename, move_type, extracted_override


def _extract_rate_data(text, file_bytes, filename, move_type):
    """
    Normalize and validate extracted rate data from text or an uploaded file.
    
    Attempts AI extraction when an Anthropic API key is configured (preferring file extraction when file bytes are present, otherwise using text); if AI is not available and only text is provided, falls back to a regex-based text parser. Ensures extracted payload contains origin and destination, normalizes origin/destination/carrier/shipment_type, and computes `rate_amount` from an explicit field or by summing `linehaul_items` when necessary.
    
    Parameters:
        text (str|None): Plain-text content to extract from (may be None if a file is provided).
        file_bytes (bytes|None): Raw uploaded file bytes to send to the extractor (preferred when present).
        filename (str|None): The filename associated with `file_bytes` (used to determine handling).
        move_type (str|None): Fallback shipment type to use when extraction does not provide one.
    
    Returns:
        tuple: (extracted_dict, error_response)
            - extracted_dict (dict|None): Normalized extraction result with keys including
              `origin`, `destination`, `shipment_type`, and `rate_amount` when extraction succeeded.
            - error_response (fastapi.responses.JSONResponse|None): A JSONResponse describing the error when
              extraction or validation failed; `None` on success.
    
    Error behavior:
        - Returns a 422 error response when a file is provided but no Anthropic API key is configured.
        - Returns a 500 error response when AI extraction raises an unexpected exception.
        - Returns a 400 error response when extraction returns no data or when origin/destination cannot be determined.
    """
    has_claude = bool(config.ANTHROPIC_API_KEY)
    extracted = None

    if file_bytes and has_claude:
        try:
            blocks = _file_to_content_blocks(file_bytes, filename, _CARRIER_EXTRACT_PROMPT)
            extracted = _call_claude(blocks)
        except Exception as e:
            log.warning("Claude file extraction failed: %s", e)
            return None, JSONResponse(status_code=500, content={"error": f"AI extraction failed: {e}"})
    elif text and has_claude:
        try:
            blocks = [{"type": "text", "text": _CARRIER_EXTRACT_PROMPT + "\n\n" + text[:8000]}]
            extracted = _call_claude(blocks)
        except Exception as e:
            log.warning("Claude text extraction failed: %s", e)
            return None, JSONResponse(status_code=500, content={"error": f"AI extraction failed: {e}"})
    elif text:
        from routes.quotes import _parse_rate_text
        extracted = _parse_rate_text(text)
    else:
        return None, JSONResponse(status_code=422, content={"error": "File extraction requires ANTHROPIC_API_KEY"})

    if not extracted:
        return None, JSONResponse(status_code=400, content={"error": "Could not extract rate data"})

    # Compute total rate if not directly provided
    rate_amount = None
    if extracted.get("rate_amount"):
        try:
            rate_amount = float(str(extracted["rate_amount"]).replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            pass
    if not rate_amount and extracted.get("linehaul_items"):
        try:
            rate_amount = sum(float(str(item.get("rate", "0")).replace(",", "").replace("$", ""))
                              for item in extracted["linehaul_items"])
        except (ValueError, TypeError):
            pass

    origin = (extracted.get("origin") or "").strip()
    destination = (extracted.get("destination") or "").strip()
    carrier_name = (extracted.get("carrier_name") or "").strip()
    shipment_type = (extracted.get("shipment_type") or move_type or "dray").lower()

    if not origin or not destination:
        return None, JSONResponse(status_code=400, content={
            "error": "Could not extract origin and destination",
            "extracted": extracted,
        })

    extracted["rate_amount"] = rate_amount
    extracted["origin"] = origin
    extracted["destination"] = destination
    extracted["shipment_type"] = shipment_type

    return extracted, None


@router.post("/api/rate-iq/extract-preview")
async def post_extract_preview(request: Request):
    """
    Extract rate data from the provided file or text and return the parsed extraction for user review without persisting it.
    
    Returns:
        dict: On success, a dictionary {"ok": True, "extracted": <extracted_data>} where <extracted_data> is the normalized extraction result.
        JSONResponse: On failure, a JSONResponse with an error status and message (e.g., 400 when no input is provided or an extraction error response).
    """
    text, file_bytes, filename, move_type, _ = await _parse_intake_request(request)

    if not text and not file_bytes:
        return JSONResponse(status_code=400, content={"error": "No text or file provided"})

    extracted, error = _extract_rate_data(text, file_bytes, filename, move_type)
    if error:
        return error

    return {"ok": True, "extracted": extracted}


@router.post("/api/rate-iq/manual-intake")
async def post_manual_intake(request: Request):
    """
    Accept and ingest a carrier rate from pasted text or an uploaded file, saving it to rate_quotes and lane_rates.
    
    If an `extracted` override is provided in the request body, that pre-reviewed data is used instead of running extraction. Validates that origin and destination are present, normalizes numeric values (rates, fsc, linehaul, accessorials), and parses linehaul_items and accessorials into structured fields used for database inserts. Inserts a row into rate_quotes and attempts to insert a detailed row into lane_rates; lane_rates insertion is deduplicated by carrier + origin + destination + total, and deduplication is reported. If carrier MC number or email is present, the carriers directory is created or updated.
    
    Returns:
        dict: Result payload containing at minimum `{"ok": True, "extracted": <extracted_data>}`. If a lane_rates insert was skipped due to a duplicate, includes `duplicate_skipped: True` and `duplicate_id: <id>`.
    """
    text, file_bytes, filename, move_type, extracted_override = await _parse_intake_request(request)

    if extracted_override:
        # User already reviewed — use pre-reviewed data directly
        extracted = extracted_override
        origin = (extracted.get("origin") or "").strip()
        destination = (extracted.get("destination") or "").strip()
        if not origin or not destination:
            return JSONResponse(status_code=400, content={"error": "Origin and destination are required"})
        # Normalize rate_amount
        rate_amount = None
        if extracted.get("rate_amount"):
            try:
                rate_amount = float(str(extracted["rate_amount"]).replace(",", "").replace("$", ""))
            except (ValueError, TypeError):
                pass
        extracted["rate_amount"] = rate_amount
        extracted["origin"] = origin
        extracted["destination"] = destination
        shipment_type = (extracted.get("shipment_type") or move_type or "dray").lower()
    else:
        if not text and not file_bytes:
            return JSONResponse(status_code=400, content={"error": "No text or file provided"})

        extracted, error = _extract_rate_data(text, file_bytes, filename, move_type)
        if error:
            return error
        shipment_type = (extracted.get("shipment_type") or move_type or "dray").lower()

    origin = extracted["origin"]
    destination = extracted["destination"]
    rate_amount = extracted.get("rate_amount")
    carrier_name = (extracted.get("carrier_name") or "").strip()
    lane = f"{origin} → {destination}"

    # Parse accessorials from extracted data
    carrier_email = (extracted.get("carrier_email") or extracted.get("email") or "").strip() or None
    carrier_mc = (extracted.get("carrier_mc") or "").strip() or None
    linehaul_items = extracted.get("linehaul_items") or []
    accessorial_list = extracted.get("accessorials") or []

    # Build accessorials JSONB and extract known fields for lane_rates
    accessorials_jsonb = accessorial_list if accessorial_list else None
    linehaul_amount = None
    fsc_amount = None
    acc_fields = {}  # for lane_rates columns

    for item in linehaul_items:
        charge = (item.get("description") or "").lower()
        try:
            val = float(str(item.get("rate", "0")).replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            continue
        if "fuel" in charge or "fsc" in charge:
            fsc_amount = val
        elif "linehaul" in charge or "line haul" in charge or "base" in charge:
            linehaul_amount = val

    for acc in accessorial_list:
        charge = (acc.get("charge") or "").lower()
        try:
            val = float(str(acc.get("rate", "0")).replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            continue
        if "chassis" in charge and "split" not in charge:
            acc_fields["chassis_per_day"] = val
        elif "chassis" in charge and "split" in charge:
            acc_fields["chassis_split"] = val
        elif "prepull" in charge or "pre-pull" in charge:
            acc_fields["prepull"] = val
        elif "storage" in charge:
            acc_fields["storage_per_day"] = val
        elif "detention" in charge:
            acc_fields["detention"] = str(val)
        elif "overweight" in charge:
            acc_fields["overweight"] = val
        elif "toll" in charge:
            acc_fields["tolls"] = val
        elif "hazmat" in charge or "haz" in charge:
            acc_fields["hazmat"] = val
        elif "reefer" in charge:
            acc_fields["reefer"] = val
        elif "triaxle" in charge or "tri-axle" in charge:
            acc_fields["triaxle"] = val
        elif "bond" in charge:
            acc_fields["bond_fee"] = val
        elif "residential" in charge:
            acc_fields["residential"] = val

    # Save to rate_quotes (with accessorials)
    from datetime import date as _date
    import json as _json
    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute(
                    "INSERT INTO rate_quotes "
                    "(origin, destination, lane, carrier_name, carrier_email, rate_amount, rate_unit, "
                    " move_type, quote_date, status, source, linehaul, chassis_per_day, accessorials) "
                    "VALUES (%s,%s,%s,%s,%s,%s,'flat',%s,%s,'quoted','manual',%s,%s,%s) "
                    "ON CONFLICT DO NOTHING",
                    (origin, destination, lane, carrier_name, carrier_email, rate_amount,
                     shipment_type, _date.today(), linehaul_amount,
                     acc_fields.get("chassis_per_day"),
                     _json.dumps(accessorials_jsonb) if accessorials_jsonb else None)
                )
    except Exception as e:
        log.warning("rate_quotes insert failed: %s", e)

    # Also save to lane_rates for carrier rate table display (with full accessorial breakdown)
    # Dedup: skip if same carrier+origin+dest+total already exists
    duplicate_skipped = False
    duplicate_id = None
    if carrier_name and rate_amount:
        try:
            with db.get_conn() as conn:
                with db.get_cursor(conn) as cur:
                    cur.execute(
                        "SELECT id FROM lane_rates WHERE LOWER(carrier_name) = LOWER(%s) AND LOWER(port) = LOWER(%s) AND LOWER(destination) = LOWER(%s) AND total = %s LIMIT 1",
                        (carrier_name, origin, destination, rate_amount)
                    )
                    existing = cur.fetchone()
                    if existing:
                        duplicate_skipped = True
                        duplicate_id = existing["id"]
                    else:
                        cur.execute(
                            """INSERT INTO lane_rates
                            (port, destination, carrier_name, dray_rate, fsc, total,
                             chassis_per_day, prepull, storage_per_day, detention, chassis_split,
                             overweight, tolls, hazmat, reefer, triaxle, bond_fee, residential,
                             move_type, source)
                            VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,'email_intake')""",
                            (origin, destination, carrier_name,
                             linehaul_amount, str(fsc_amount) if fsc_amount else None, rate_amount,
                             acc_fields.get("chassis_per_day"), acc_fields.get("prepull"),
                             acc_fields.get("storage_per_day"), acc_fields.get("detention"),
                             acc_fields.get("chassis_split"), acc_fields.get("overweight"),
                             acc_fields.get("tolls"), acc_fields.get("hazmat"),
                             acc_fields.get("reefer"), acc_fields.get("triaxle"),
                             acc_fields.get("bond_fee"), acc_fields.get("residential"),
                             shipment_type)
                        )
        except Exception as e:
            log.warning("lane_rates insert failed: %s", e)

    # Update carrier directory with MC# and email if found
    if carrier_name and (carrier_mc or carrier_email):
        try:
            with db.get_conn() as conn:
                with db.get_cursor(conn) as cur:
                    cur.execute("SELECT id FROM carriers WHERE LOWER(carrier_name) = LOWER(%s)", (carrier_name,))
                    row = cur.fetchone()
                    if row:
                        updates, params = [], []
                        if carrier_mc:
                            updates.append("mc_number = COALESCE(mc_number, %s)")
                            params.append(carrier_mc)
                        if carrier_email:
                            updates.append("contact_email = COALESCE(contact_email, %s)")
                            params.append(carrier_email)
                        if updates:
                            params.append(row["id"])
                            cur.execute(f"UPDATE carriers SET {', '.join(updates)} WHERE id = %s", params)
                    else:
                        cur.execute(
                            "INSERT INTO carriers (carrier_name, mc_number, contact_email, source) VALUES (%s,%s,%s,'email_intake')",
                            (carrier_name, carrier_mc, carrier_email)
                        )
        except Exception as e:
            log.warning("carrier directory update failed: %s", e)

    result = {"ok": True, "extracted": extracted}
    if duplicate_skipped:
        result["duplicate_skipped"] = True
        result["duplicate_id"] = duplicate_id
    return result


# ── Market Rates (LoadMatch / benchmark data — no carrier) ──────────

@router.post("/api/rate-iq/market-rates")
async def post_market_rates(request: Request):
    """Parse pasted tab-separated LoadMatch data OR extract from uploaded screenshot.
    Accepts JSON body (text paste) or multipart form (file upload)."""
    from datetime import datetime as _dt
    from decimal import Decimal, InvalidOperation

    content_type = request.headers.get("content-type", "")
    has_claude = bool(config.ANTHROPIC_API_KEY)

    # Determine input: multipart file upload or JSON text paste
    origin = ""
    destination = ""
    move_type = "dray"
    text = ""
    file_bytes = None
    filename = ""

    if "multipart/form-data" in content_type:
        form = await request.form()
        origin = str(form.get("origin", "")).strip()
        destination = str(form.get("destination", "")).strip()
        move_type = str(form.get("move_type", "dray")).strip().lower()
        text = str(form.get("text", "")).strip()
        file_obj = form.get("file")
        if file_obj and hasattr(file_obj, "read"):
            file_bytes = await file_obj.read()
            filename = getattr(file_obj, "filename", "") or ""
    else:
        body = await request.json()
        origin = (body.get("origin") or "").strip()
        destination = (body.get("destination") or "").strip()
        move_type = (body.get("move_type") or "dray").strip().lower()
        text = (body.get("text") or "").strip()

    # ── File upload path: use Claude Vision to extract multiple rates ──
    if file_bytes:
        if not has_claude:
            return JSONResponse(status_code=422, content={"error": "Screenshot extraction requires ANTHROPIC_API_KEY"})
        try:
            blocks = _file_to_content_blocks(file_bytes, filename, _MARKET_EXTRACT_PROMPT)
            extracted = _call_claude(blocks)
        except Exception as e:
            log.warning("Claude market rate extraction failed: %s", e)
            return JSONResponse(status_code=500, content={"error": f"AI extraction failed: {e}"})

        # Use extracted origin/dest if user didn't provide
        if not origin:
            origin = (extracted.get("origin") or "").strip()
        if not destination:
            destination = (extracted.get("destination") or "").strip()
        if not origin or not destination:
            return JSONResponse(status_code=400, content={
                "error": "Could not determine origin/destination — please fill in the fields",
                "extracted": extracted,
            })

        rates_data = extracted.get("rates") or []
        if not rates_data:
            return JSONResponse(status_code=400, content={"error": "No rates extracted from file", "extracted": extracted})

        rows_inserted = 0
        errors = []
        insert_params = []
        for i, r in enumerate(rates_data):
            try:
                rate_date = None
                if r.get("date"):
                    try:
                        rate_date = _dt.strptime(r["date"], "%Y-%m-%d").date()
                    except ValueError:
                        pass
                terminal = r.get("terminal")
                base_str = str(r.get("base_rate") or "").replace("$", "").replace(",", "")
                total_str = str(r.get("total") or "").replace("$", "").replace(",", "")
                fsc_str = str(r.get("fsc_pct") or "0").replace("%", "")
                base_rate = Decimal(base_str) if base_str else None
                total = Decimal(total_str) if total_str else None
                fsc = Decimal(fsc_str) if fsc_str else Decimal("0")
                if total is None and base_rate is not None:
                    total = base_rate * (1 + fsc / 100) if fsc else base_rate
                if total is None and base_rate is None:
                    errors.append(f"Rate {i + 1}: no rate value")
                    continue
                insert_params.append((rate_date, terminal, origin, destination, base_rate, fsc, total, move_type))
                rows_inserted += 1
            except (InvalidOperation, ValueError) as e:
                errors.append(f"Rate {i + 1}: {e}")

        if rows_inserted == 0:
            return JSONResponse(status_code=400, content={"error": "No valid rates in extraction", "errors": errors[:10]})

        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                for p in insert_params:
                    cur.execute("""
                        INSERT INTO market_rates (rate_date, terminal, origin, destination, base_rate, fsc_pct, total, source, move_type)
                        VALUES (%s, %s, %s, %s, %s, %s, %s, 'loadmatch', %s)
                    """, p)

        return {"ok": True, "inserted": rows_inserted, "skipped": len(errors), "errors": errors[:10]}

    # ── Text paste path: parse tab-separated data ──
    if not origin or not destination:
        return JSONResponse(status_code=400, content={"error": "origin and destination are required"})
    if not text:
        return JSONResponse(status_code=400, content={"error": "text or file is required"})

    DATE_FORMATS = ["%Y-%b-%d", "%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%b %d, %Y"]
    HEADER_WORDS = {"date", "terminal", "base", "fsc", "total", "linehaul", "rate"}

    def parse_money(s):
        """Strip $, commas, whitespace and return Decimal or None."""
        s = s.strip().replace("$", "").replace(",", "")
        if not s or s == "—" or s == "-":
            return None
        return Decimal(s)

    def parse_pct(s):
        """Parse a percentage string like '29%' to Decimal."""
        s = s.strip().replace("%", "")
        if not s or s == "—" or s == "-":
            return Decimal("0")
        return Decimal(s)

    def parse_date(s):
        """Try multiple date formats and return a date or None."""
        s = s.strip()
        for f in DATE_FORMATS:
            try:
                return _dt.strptime(s, f).date()
            except ValueError:
                continue
        return None

    rows_inserted = 0
    rows_skipped = 0
    errors = []
    insert_params = []

    lines = [l.strip() for l in text.split("\n") if l.strip()]
    for i, line in enumerate(lines):
        # Split by tab or 2+ spaces
        parts = [p.strip() for p in line.split("\t") if p.strip()]
        if len(parts) < 3:
            # Try splitting by 2+ whitespace
            parts = [p.strip() for p in re.split(r"\s{2,}", line) if p.strip()]

        # Skip header rows
        if parts and any(w in parts[0].lower() for w in HEADER_WORDS):
            continue

        # Expect: date, terminal, base, fsc%, total  (5 cols)
        # Or: date, terminal, base, total  (4 cols, no fsc)
        # Or: terminal, base, fsc%, total  (4 cols, no date)
        try:
            rate_date = None
            terminal = None
            base_rate = None
            fsc = Decimal("0")
            total = None

            if len(parts) >= 5:
                rate_date = parse_date(parts[0])
                terminal = parts[1]
                base_rate = parse_money(parts[2])
                fsc = parse_pct(parts[3])
                total = parse_money(parts[4])
            elif len(parts) == 4:
                # Try date first
                d = parse_date(parts[0])
                if d:
                    rate_date = d
                    terminal = parts[1]
                    base_rate = parse_money(parts[2])
                    total = parse_money(parts[3])
                else:
                    terminal = parts[0]
                    base_rate = parse_money(parts[1])
                    fsc = parse_pct(parts[2])
                    total = parse_money(parts[3])
            elif len(parts) == 3:
                terminal = parts[0]
                base_rate = parse_money(parts[1])
                total = parse_money(parts[2])
            else:
                rows_skipped += 1
                continue

            if total is None and base_rate is None:
                rows_skipped += 1
                errors.append(f"Line {i + 1}: no rate found")
                continue

            if total is None and base_rate is not None:
                total = base_rate * (1 + fsc / 100) if fsc else base_rate

            insert_params.append((rate_date, terminal, origin, destination, base_rate, fsc, total, move_type))
            rows_inserted += 1

        except (InvalidOperation, ValueError) as e:
            rows_skipped += 1
            errors.append(f"Line {i + 1}: {e}")

    if rows_inserted == 0:
        return JSONResponse(status_code=400, content={"error": "No valid rows parsed", "skipped": rows_skipped, "errors": errors[:10]})

    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            for p in insert_params:
                cur.execute("""
                    INSERT INTO market_rates (rate_date, terminal, origin, destination, base_rate, fsc_pct, total, source, move_type)
                    VALUES (%s, %s, %s, %s, %s, %s, %s, 'loadmatch', %s)
                """, p)

    return {"ok": True, "inserted": rows_inserted, "skipped": rows_skipped, "errors": errors[:10]}


@router.get("/api/rate-iq/market-rates")
async def get_market_rates(
    origin: str = Query(default=""),
    destination: str = Query(default=""),
    move_type: str = Query(default=""),
):
    """Retrieve market benchmark rates for a lane with aggregate stats."""
    origin = origin.strip()
    destination = destination.strip()

    if not origin and not destination:
        return JSONResponse(status_code=400, content={"error": "origin or destination required"})

    conditions = []
    params = []
    if origin:
        conditions.append("LOWER(origin) LIKE %s")
        params.append(f"%{origin.lower()}%")
    if destination:
        conditions.append("LOWER(destination) LIKE %s")
        params.append(f"%{destination.lower()}%")
    if move_type:
        conditions.append("LOWER(move_type) = %s")
        params.append(move_type.lower())

    where = " AND ".join(conditions)

    with db.get_cursor() as cur:
        cur.execute(f"""
            SELECT id, rate_date, terminal, origin, destination,
                   base_rate, fsc_pct, total, source, move_type, created_at
            FROM market_rates
            WHERE {where}
            ORDER BY rate_date DESC NULLS LAST
            LIMIT 100
        """, params)
        rows = cur.fetchall()

    rates = []
    totals = []
    for r in rows:
        t = float(r["total"]) if r["total"] else None
        if t:
            totals.append(t)
        rates.append({
            "id": r["id"],
            "date": r["rate_date"].isoformat() if r["rate_date"] else None,
            "terminal": r["terminal"],
            "origin": r["origin"],
            "destination": r["destination"],
            "base": float(r["base_rate"]) if r["base_rate"] else None,
            "fsc_pct": float(r["fsc_pct"]) if r["fsc_pct"] else None,
            "total": t,
            "source": r["source"],
            "move_type": r["move_type"],
            "created_at": r["created_at"].isoformat() if r["created_at"] else None,
        })

    stats = None
    if totals:
        mid = len(totals) // 2
        recent = totals[:mid] if mid > 0 else totals
        older = totals[mid:] if mid > 0 else []
        recent_avg = sum(recent) / len(recent) if recent else None
        older_avg = sum(older) / len(older) if older else None
        trend_pct = round(((recent_avg - older_avg) / older_avg) * 100, 1) if recent_avg and older_avg and older_avg > 0 else None

        stats = {
            "avg": round(sum(totals) / len(totals), 2),
            "min": min(totals),
            "max": max(totals),
            "count": len(totals),
            "latest_date": rates[0]["date"] if rates else None,
            "oldest_date": rates[-1]["date"] if rates else None,
            "trend_pct": trend_pct,
        }

    return {"rates": rates, "stats": stats}


@router.delete("/api/rate-iq/market-rates/{rate_id}")
async def delete_market_rate(rate_id: int):
    """Delete a single market rate entry."""
    with db.get_conn() as conn:
        with db.get_cursor(conn) as cur:
            cur.execute("DELETE FROM market_rates WHERE id = %s", (rate_id,))
            if cur.rowcount == 0:
                return JSONResponse(status_code=404, content={"error": "Rate not found"})
    return {"ok": True}


# ── Rate accuracy feedback ────────────────────────────────────────────

@router.post("/api/rate-iq/feedback")
async def post_rate_feedback(request: Request):
    """Record user feedback on market rate accuracy for a lane."""
    body = await request.json()
    lane = body.get("lane", "")
    rating = body.get("rating", "")  # 'accurate' or 'inaccurate'
    avg_rate = body.get("avg_rate")
    count = body.get("count")

    if not lane or not rating:
        return JSONResponse(status_code=400, content={"error": "lane and rating required"})

    try:
        with db.get_conn() as conn:
            with db.get_cursor(conn) as cur:
                cur.execute(
                    """CREATE TABLE IF NOT EXISTS rate_feedback (
                        id SERIAL PRIMARY KEY,
                        lane TEXT NOT NULL,
                        rating TEXT NOT NULL,
                        avg_rate NUMERIC,
                        data_points INTEGER,
                        created_at TIMESTAMPTZ DEFAULT NOW()
                    )"""
                )
                cur.execute(
                    "INSERT INTO rate_feedback (lane, rating, avg_rate, data_points) VALUES (%s,%s,%s,%s)",
                    (lane, rating, avg_rate, count)
                )
    except Exception as e:
        log.warning("rate feedback insert failed: %s", e)
        return JSONResponse(status_code=500, content={"error": str(e)})

    return {"ok": True, "lane": lane, "rating": rating}
