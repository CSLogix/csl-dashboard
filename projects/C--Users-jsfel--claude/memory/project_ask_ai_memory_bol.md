# Ask AI: Memory Fix + BOL Auto-Create (2026-03-19)

## Memory Tool Fix
- Ask AI was ignoring "update memory" requests — Claude said it had no memory access
- Root cause: system prompt memory instruction too narrow (only matched "remember"/"save this")
- Fix: broadened trigger phrases + told Claude to extract details from conversation history
- Commit: `155bbcd` (Fix Ask AI not using memory tools on "update memory" requests)

## BOL → Load Creation
- Ask AI now auto-parses uploaded BOLs/PDFs and proactively asks "Want me to create this load?"
- Field mapping: container, BOL#, vessel, carrier, origin, destination, ETA, cutoff, move type
- Auto-matches account name to known accounts, infers move type from context
- Uses `bulk_create_loads` tool → Postgres + Google Sheet in one call
- Commit: `daa8b4e` (Ask AI: auto-offer load creation when BOL/document is uploaded)

## Both deployed to server (csl-dashboard restarted)
