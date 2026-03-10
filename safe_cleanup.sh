#!/bin/bash
# Soft-delete sensitive probe/patch files from /tmp instead of permanent rm
trash-put /tmp/probe_*.py 2>/dev/null
trash-put /tmp/terminal_creds_upload.json 2>/dev/null
echo 'Done. Use trash-list to see them, trash-restore to recover, trash-empty 30 to purge >30 days old.'
