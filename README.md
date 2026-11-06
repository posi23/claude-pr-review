# Claude PR Review

A first-pass code review for GitHub pull requests, run by Claude Code. It reads the diff, writes and runs tests against the changed code, then posts a review on the PR with blocking issues kept separate from suggestions. It never commits, merges or approves anything. The developer makes every change.

I built this in March 2026 while working across a Python backend and a SvelteKit frontend. I wanted every PR I opened to get a consistent review before a teammate spent time on it, and I wanted the tests to actually run rather than just be suggested.

## Two ways to run it

**1. Interactive, inside Claude Code.** Open Claude Code in `review-assistant/` and say "review my PR". [`review-assistant/CLAUDE.md`](review-assistant/CLAUDE.md) drives the whole flow through the GitHub MCP server:

```
find my open PRs ─► fetch diff, files and CI status ─► write + run tests in /tmp
       ─► post test results ─► review the diff ─► post review with inline suggestions
```

**2. Scripted, one command.** `scripts/review-pr.sh` runs Claude Code headless (`claude -p`), so it works from a terminal or another script:

```bash
./scripts/review-pr.sh your-org/your-repo 42 python
```

```
gh pr diff ─► generate_and_run_python_tests.py ─► peer_review.py ─► gh pr comment
                 (or ..._svelte_tests.py)           (claude -p)
```

Setup steps are in [SETUP.md](SETUP.md). Neither mode needs an API key; both use your Claude Code login.

## Guardrails

These are in the instructions on purpose, because an agent with GitHub write access can do real damage:

- It never commits, pushes, merges or approves. Fixes go up as GitHub `suggestion` blocks, so applying one is a click the developer makes.
- Generated tests are never committed. In interactive mode they live in `/tmp` and are thrown away; the Svelte script deletes its temp files too; the Python script leaves them in your local `tests/` folder so you can keep the useful ones.
- Failing CI is reported before anything else.
- Findings are split into blocking issues and suggestions, and every review ends with a verdict.
- Repo, PR number and stack are worked out from GitHub. It only asks when there's real ambiguity, like several open PRs.

## What I had to correct along the way

Most of the CLAUDE.md is fixes for things the agent got wrong in early runs:

- **Imports failed.** The agent's tests tried to import the real modules, which pulled in the whole app's dependencies and broke. The instructions now tell it to copy just the changed functions into a self-contained test file and mock what they call.
- **Python version mismatches.** `StrEnum` only exists from Python 3.11, so tests crashed on older interpreters. Every generated test file now starts with a shim.
- **Catch-all `except` blocks hid bugs.** Tests passed because errors were being swallowed. It's now told to pass `None` into those functions and check what actually happens.
- **A GitHub MCP bug.** Posting a comment sometimes failed with `Expected number, received string`. The workaround is to hand the comment to a subagent to post.
- **Huge diffs.** Very large PRs blew past the context window, so the scripted version truncates the diff at 20,000 characters and says so in the review, rather than pretending it saw everything.
- **The approve contradiction.** My first version said "never approve" in one section but let the review be submitted as `APPROVE` in another. It now only submits `COMMENT` or `REQUEST_CHANGES`.

The first version also ran in GitHub Actions against the Anthropic API, using repo secrets. I moved it to the local Claude Code CLI so there are no keys to store or rotate.

## Limitations

- Tests built from copied functions check the logic in isolation, not how it behaves inside the full app.
- A truncated diff means a partial review. The comment says when that happened.
- The review is a first pass. It doesn't replace a human reviewer.

## Layout

```
review-assistant/CLAUDE.md                  instructions for the interactive mode
scripts/review-pr.sh                        one-command entry point
scripts/peer_review.py                      runs the review through claude -p
scripts/generate_and_run_python_tests.py    writes and runs pytest tests for changed .py files
scripts/generate_and_run_svelte_tests.py    writes and runs Vitest tests for changed frontend files
SETUP.md                                    one-time setup
```
