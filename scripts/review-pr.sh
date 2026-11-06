#!/usr/bin/env bash
# review-pr.sh — Local PR review using Claude Code CLI
#
# Usage:
#   ./scripts/review-pr.sh <org/repo> <pr_number> [stack]
#
# stack options:
#   python  — generate + run Python (pytest) tests before review
#   svelte  — generate + run Svelte/TS (vitest) tests before review
#   skip    — skip test generation, just do peer review (default)
#
# Requirements:
#   - gh CLI authenticated (gh auth login)
#   - claude CLI installed and authenticated (claude --version)
#   - python3 in PATH (for test generation steps)

set -euo pipefail

REPO="${1:?Error: repo required.  Usage: review-pr.sh <org/repo> <pr_number> [python|svelte|skip]}"
PR_NUMBER="${2:?Error: PR number required.  Usage: review-pr.sh <org/repo> <pr_number> [python|svelte|skip]}"
STACK="${3:-skip}"

DIFF_FILE="/tmp/pr_${PR_NUMBER}.diff"
PYTHON_RESULTS="/tmp/python_results_${PR_NUMBER}.json"
SVELTE_RESULTS="/tmp/svelte_results_${PR_NUMBER}.json"
COMMENT_FILE="/tmp/review_comment_${PR_NUMBER}.md"

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

EMPTY_RESULTS='{"summary":"Skipped.","passed":0,"failed":0,"test_output":""}'

echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"
echo "  Claude PR Review"
echo "  Repo:  ${REPO}"
echo "  PR:    #${PR_NUMBER}"
echo "  Stack: ${STACK}"
echo "━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━"

# ── 1. Fetch diff ─────────────────────────────────────────────────────────────
echo ""
echo "▶ Fetching PR diff..."
if ! gh pr diff "$PR_NUMBER" --repo "$REPO" > "$DIFF_FILE"; then
  echo "  ✗ Could not fetch diff. Check 'gh auth status' and the repo/PR number."
  exit 1
fi
DIFF_LINES=$(wc -l < "$DIFF_FILE" | tr -d ' ')
echo "  ✓ ${DIFF_LINES} lines"

# ── 2. Test generation (optional) ─────────────────────────────────────────────
if [ "$STACK" = "python" ]; then
  echo ""
  echo "▶ Generating and running Python tests..."
  python3 "$SCRIPT_DIR/generate_and_run_python_tests.py" \
    --diff "$DIFF_FILE" \
    --output "$PYTHON_RESULTS" || true
  echo "$EMPTY_RESULTS" > "$SVELTE_RESULTS"

elif [ "$STACK" = "svelte" ]; then
  echo ""
  echo "▶ Generating and running Svelte/TS tests..."
  python3 "$SCRIPT_DIR/generate_and_run_svelte_tests.py" \
    --diff "$DIFF_FILE" \
    --output "$SVELTE_RESULTS" || true
  echo "$EMPTY_RESULTS" > "$PYTHON_RESULTS"

else
  echo ""
  echo "  (Skipping test generation — pass 'python' or 'svelte' as 3rd arg to enable)"
  echo "$EMPTY_RESULTS" > "$PYTHON_RESULTS"
  echo "$EMPTY_RESULTS" > "$SVELTE_RESULTS"
fi

# ── 3. Peer review ────────────────────────────────────────────────────────────
echo ""
echo "▶ Running peer review with Claude..."
python3 "$SCRIPT_DIR/peer_review.py" \
  --diff "$DIFF_FILE" \
  --python-results "$PYTHON_RESULTS" \
  --svelte-results "$SVELTE_RESULTS" \
  --output "$COMMENT_FILE"

# ── 4. Post comment ───────────────────────────────────────────────────────────
echo ""
echo "▶ Posting review comment to PR #${PR_NUMBER}..."
gh pr comment "$PR_NUMBER" --repo "$REPO" --body-file "$COMMENT_FILE"

echo ""
echo "✓ Done — https://github.com/${REPO}/pull/${PR_NUMBER}"
