#!/usr/bin/env bash
# claude-approve.sh — Staging branch + approval gateway workflow
#
# Usage:
#   claude-approve.sh prepare [branch-name]   Create staging branch
#   claude-approve.sh submit  [description]   Diff → submit → poll → merge/reject
#   claude-approve.sh status  [review-id]     Check review status
#   claude-approve.sh poll    [review-id]     Resume polling (after Ctrl+C)
#
# Env vars (or source .env):
#   GATEWAY_URL          Public URL for SMS links (default: http://localhost:5004)
#   GATEWAY_INTERNAL     URL for curl calls (default: http://localhost:5004)
#   APPROVAL_API_TOKEN   Bearer token (optional, must match server)
#   BASE_BRANCH          Branch to diff against (default: master)

set -euo pipefail

GATEWAY_URL="${GATEWAY_URL:-http://localhost:5004}"
GATEWAY_INTERNAL="${GATEWAY_INTERNAL:-http://localhost:5004}"
API_TOKEN="${APPROVAL_API_TOKEN:-}"
BASE_BRANCH="${BASE_BRANCH:-master}"
STATE_DIR="${STATE_DIR:-.claude-approve}"

_auth_header() {
    if [ -n "$API_TOKEN" ]; then
        echo "Authorization: Bearer $API_TOKEN"
    else
        echo "X-Noop: 1"
    fi
}

cmd_prepare() {
    local name="${1:-claude-staging-$(date +%Y%m%d-%H%M%S)}"

    # Ensure clean working tree
    if ! git diff --quiet HEAD 2>/dev/null; then
        echo "WARNING: You have uncommitted changes."
        read -rp "Continue anyway? [y/N] " yn
        [[ "$yn" =~ ^[Yy] ]] || exit 1
    fi

    git checkout -b "$name" "$BASE_BRANCH"
    mkdir -p "$STATE_DIR"
    echo "$name" > "$STATE_DIR/branch"
    echo ""
    echo "Staging branch created: $name"
    echo "Make your changes, commit, then run: claude-approve.sh submit"
}

cmd_submit() {
    local desc="${1:-Claude Code changes}"
    local branch
    branch=$(git branch --show-current)

    if [ "$branch" = "$BASE_BRANCH" ]; then
        echo "ERROR: You're on $BASE_BRANCH. Run 'prepare' first to create a staging branch."
        exit 1
    fi

    # Check there are actual changes
    local diff_text
    diff_text=$(git diff "$BASE_BRANCH"..."$branch" 2>/dev/null || git diff "$BASE_BRANCH".."$branch")
    if [ -z "$diff_text" ]; then
        echo "No changes between $branch and $BASE_BRANCH"
        exit 1
    fi

    # Gather stats
    local files_json additions deletions
    files_json=$(git diff --name-only "$BASE_BRANCH"..."$branch" 2>/dev/null | jq -R . | jq -s .)
    additions=$(git diff --stat "$BASE_BRANCH"..."$branch" 2>/dev/null | tail -1 | grep -oP '\d+(?= insertion)' || echo 0)
    deletions=$(git diff --stat "$BASE_BRANCH"..."$branch" 2>/dev/null | tail -1 | grep -oP '\d+(?= deletion)' || echo 0)

    # Write diff to temp file (handles all special chars safely)
    local diff_file
    diff_file=$(mktemp)
    echo "$diff_text" > "$diff_file"

    echo "Submitting ${additions}+ / ${deletions}- across $(echo "$files_json" | jq length) files..."

    # POST to server
    local response
    response=$(curl -sf -X POST "${GATEWAY_INTERNAL}/api/submit" \
        -H "Content-Type: application/json" \
        -H "$(_auth_header)" \
        -d "$(jq -n \
            --rawfile diff "$diff_file" \
            --arg desc "$desc" \
            --arg branch "$branch" \
            --argjson files "$files_json" \
            --argjson add "${additions:-0}" \
            --argjson del "${deletions:-0}" \
            '{diff: $diff, description: $desc, branch: $branch, files_changed: $files, additions: $add, deletions: $del}'
        )")

    rm -f "$diff_file"

    local review_id review_url
    review_id=$(echo "$response" | jq -r '.review_id')
    review_url=$(echo "$response" | jq -r '.url')

    mkdir -p "$STATE_DIR"
    echo "$review_id" > "$STATE_DIR/review_id"
    echo "$branch" > "$STATE_DIR/branch"

    echo ""
    echo "Review submitted: $review_id"
    echo "URL: $review_url"
    echo "SMS notification sent (if configured)"
    echo ""

    # Start polling
    _poll "$review_id" "$branch" "$desc"
}

cmd_poll() {
    local review_id="${1:-}"
    if [ -z "$review_id" ] && [ -f "$STATE_DIR/review_id" ]; then
        review_id=$(cat "$STATE_DIR/review_id")
    fi
    if [ -z "$review_id" ]; then
        echo "ERROR: No review ID. Provide one or run 'submit' first."
        exit 1
    fi

    local branch
    branch=$(cat "$STATE_DIR/branch" 2>/dev/null || git branch --show-current)

    _poll "$review_id" "$branch" ""
}

_poll() {
    local review_id="$1"
    local branch="$2"
    local desc="$3"
    local interval=5
    local max_interval=15

    echo "Waiting for approval... (Ctrl+C to detach, resume with: claude-approve.sh poll)"

    while true; do
        local result
        result=$(curl -sf "${GATEWAY_INTERNAL}/api/review/${review_id}/status" 2>/dev/null || echo '{"status":"error"}')
        local status
        status=$(echo "$result" | jq -r '.status')

        case "$status" in
            approved)
                echo ""
                echo "APPROVED"
                echo ""
                echo "Merging $branch into $BASE_BRANCH..."
                git checkout "$BASE_BRANCH"
                git merge "$branch" --no-ff -m "Approved: ${desc:-merge $branch}"
                git branch -d "$branch"
                rm -rf "$STATE_DIR"
                echo "Done. $branch merged into $BASE_BRANCH."
                exit 0
                ;;
            rejected)
                local comment
                comment=$(echo "$result" | jq -r '.reject_comment // empty')
                echo ""
                echo "REJECTED"
                [ -n "$comment" ] && echo "Comment: $comment"
                echo ""
                echo "You're still on branch: $branch"
                echo "Make fixes, commit, and run 'submit' again."
                rm -f "$STATE_DIR/review_id"
                exit 1
                ;;
            pending)
                printf "."
                sleep "$interval"
                # Back off: 5 → 7 → 10 → 12 → 15
                [ "$interval" -lt "$max_interval" ] && interval=$((interval + 2))
                ;;
            error)
                printf "x"
                sleep "$interval"
                ;;
            *)
                echo ""
                echo "Unexpected status: $status"
                exit 2
                ;;
        esac
    done
}

cmd_status() {
    local review_id="${1:-}"
    if [ -z "$review_id" ] && [ -f "$STATE_DIR/review_id" ]; then
        review_id=$(cat "$STATE_DIR/review_id")
    fi
    if [ -z "$review_id" ]; then
        echo "No review ID found."
        exit 1
    fi

    curl -sf "${GATEWAY_INTERNAL}/api/review/${review_id}/status" | jq .
}

# --- Main ---
case "${1:-help}" in
    prepare) shift; cmd_prepare "$@" ;;
    submit)  shift; cmd_submit "$@" ;;
    poll)    shift; cmd_poll "$@" ;;
    status)  shift; cmd_status "$@" ;;
    help|*)
        echo "claude-approve.sh — Staging branch + approval gateway"
        echo ""
        echo "  prepare [name]    Create a staging branch"
        echo "  submit  [desc]    Submit diff for review, poll for result"
        echo "  poll    [id]      Resume polling for a pending review"
        echo "  status  [id]      One-shot status check"
        ;;
esac
