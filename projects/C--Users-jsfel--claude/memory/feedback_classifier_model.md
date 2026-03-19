---
name: Email classifier must use Claude Haiku, not Gemini Flash
description: csl_email_classifier.py AI calls must use claude-haiku-4-5-20251001 — Gemini Flash produced 45% failure rate from malformed JSON
type: feedback
---

Email classifier (csl_email_classifier.py) must stay on Claude Haiku (`claude-haiku-4-5-20251001`), not Gemini Flash.

**Why:** Gemini 2.5 Flash was tested in production Mar 17 2026 and dropped success rate from 86% (Haiku) to 45%. Failure mode was consistently `Unterminated string starting at...` — Flash couldn't reliably produce valid JSON for structured classification output. 619 failures in ~11 hours vs ~71 failures/day on Haiku.

**How to apply:** If considering model swaps for the inbox scanner's AI classification or rate extraction, do not use Gemini Flash. Haiku is proven reliable for this structured JSON output task. Both `ai_classify_email` and `_ai_extract_rate` use `ANTHROPIC_API_KEY` from `.env`.
