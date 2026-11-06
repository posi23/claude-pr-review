# Claude PR Review — Local Setup

Your review tool runs entirely on your machine using the **Claude Code CLI** —
no Anthropic API key or credits required.

---

## How it works

```
./scripts/review-pr.sh <org/repo> <pr_number> [stack]
  │
  ├─ gh pr diff        → fetches the PR diff from GitHub
  ├─ claude -p         → Claude Code CLI runs the peer review
  └─ gh pr comment     → posts the review comment on the PR
```

The `stack` argument is optional:
- `python` — also generates and runs Pytest tests before the review
- `svelte` — also generates and runs Vitest tests before the review
- _(omit or `skip`)_ — peer review only (fastest)

---

## One-Time Setup

### Step 1 — Authenticate the GitHub CLI

```bash
gh auth login
```

Make sure the token has `repo` scope so it can read diffs and post comments
on your target repos.

### Step 2 — Confirm Claude Code is installed

```bash
claude --version
```

If not installed, see: https://github.com/anthropics/claude-code

### Step 3 — Clone this repo

```bash
git clone https://github.com/posi23/claude-pr-review.git
cd claude-pr-review
```

That's it — no secrets, no API keys, no GitHub Actions needed.

---

## Running a review

```bash
# Peer review only (fastest)
./scripts/review-pr.sh your-org/your-repo 42

# With Python test generation
./scripts/review-pr.sh your-org/your-repo 42 python

# With Svelte/TS test generation
./scripts/review-pr.sh your-org/your-repo 42 svelte
```

Claude will post a comment directly on the PR when done.

---

## Troubleshooting

| Problem | Fix |
|---|---|
| `gh: pull request not found` | Check repo format (`org/repo`) and PR number |
| `gh: HTTP 403` | Run `gh auth login` — token may need `repo` scope |
| `claude: command not found` | Install Claude Code: https://github.com/anthropics/claude-code |
| Comment posts but review is empty | Run the script again; Claude CLI timed out (180s limit in peer_review.py) |
| Svelte tests fail to run | The target repo's `package.json` may not have Vitest — check the output |
