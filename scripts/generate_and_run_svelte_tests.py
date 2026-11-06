"""
generate_and_run_svelte_tests.py

Reads a PR diff, asks Claude to generate Vitest + Svelte Testing Library tests
for changed .svelte / .ts / .js frontend files, writes them to a TEMP directory
(never to the repo), runs vitest, captures output, then deletes the temp files.

Only the test RESULTS are surfaced — the generated test code is discarded.
"""

import argparse
import json
import re
import shutil
import subprocess
import tempfile
from pathlib import Path

# ── Helpers ───────────────────────────────────────────────────────────────────

FRONTEND_EXTENSIONS = {".svelte", ".ts", ".js", ".tsx", ".jsx"}

# Patterns that suggest a file is already a test file — skip these
TEST_FILE_PATTERNS = re.compile(r"\.(test|spec)\.(ts|js|svelte)$")


def extract_frontend_changes(diff_text: str) -> dict[str, str]:
    """
    Parse unified diff and return {filename: diff_chunk} for frontend files.
    Skips deleted files and existing test/spec files.
    """
    changes: dict[str, str] = {}
    current_file: str | None = None
    current_lines: list[str] = []

    for line in diff_text.splitlines():
        if line.startswith("diff --git"):
            if current_file and current_lines:
                changes[current_file] = "\n".join(current_lines)
            current_file = None
            current_lines = []
        elif line.startswith("+++ b/"):
            candidate = line[6:]
            ext = Path(candidate).suffix
            if ext in FRONTEND_EXTENSIONS and not TEST_FILE_PATTERNS.search(candidate):
                current_file = candidate
                current_lines = []
            else:
                current_file = None
        elif line.startswith("--- ") or line.startswith("diff "):
            continue
        elif current_file:
            current_lines.append(line)

    if current_file and current_lines:
        changes[current_file] = "\n".join(current_lines)

    # Keep only files with added lines
    return {
        f: chunk
        for f, chunk in changes.items()
        if any(ln.startswith("+") for ln in chunk.splitlines())
    }


def read_source_file(filepath: str) -> str:
    try:
        return Path(filepath).read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError):
        return ""


def detect_vitest_config() -> str:
    """Return the vitest config flag to use, if a config file exists."""
    for cfg in ["vitest.config.ts", "vitest.config.js", "vite.config.ts", "vite.config.js"]:
        if Path(cfg).exists():
            return f"--config {cfg}"
    return ""


# ── Claude call ───────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a senior Svelte/TypeScript engineer writing Vitest test suites.

Rules:
- Use Vitest (import from 'vitest') and @testing-library/svelte for component tests.
- For pure TypeScript utilities, use only vitest (describe/it/expect).
- Write ONLY valid TypeScript/JavaScript. No markdown fences, no prose.
- Import the module under test using the EXACT relative path from where the
  test file will live (you will be told this path).
- Cover the new or changed behaviour shown in the diff.
- Mock fetch/API calls with vi.mock or vi.fn().
- Do NOT modify source files.
- Output only the test file content, starting with imports."""


def generate_tests_for_file(
    source_path: str,
    diff_chunk: str,
    source_content: str,
    test_file_path: str,
) -> str:
    """Call Claude Code CLI to generate tests for a single changed frontend file."""
    is_svelte = source_path.endswith(".svelte")
    test_type = "Svelte component" if is_svelte else "TypeScript module"

    user_message = f"""Generate a Vitest test suite for the following changed {test_type}.

SOURCE FILE: {source_path}
TEST FILE WILL BE AT: {test_file_path}
(Adjust relative import paths accordingly.)

--- CURRENT SOURCE ---
{source_content or "(not readable — use diff context only)"}

--- DIFF (what changed in this PR) ---
{diff_chunk}

Write tests covering the changed/added logic."""

    result = subprocess.run(
        ["claude", "-p", f"{SYSTEM_PROMPT}\n\n{user_message}"],
        capture_output=True,
        text=True,
        check=True,
        timeout=120,
    )
    return result.stdout.strip()


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--diff", required=True)
    parser.add_argument("--output", required=True)
    args = parser.parse_args()

    diff_text = Path(args.diff).read_text(encoding="utf-8")
    frontend_changes = extract_frontend_changes(diff_text)

    results = {
        "language": "svelte_typescript",
        "files_tested": [],
        "test_output": "",
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "summary": "",
        "note": "Test files are ephemeral and were not committed to the repository.",
    }

    if not frontend_changes:
        results["summary"] = "No frontend (.svelte/.ts/.js) files changed in this PR."
        Path(args.output).write_text(json.dumps(results, indent=2))
        print(results["summary"])
        return

    # Write generated tests to a temp directory INSIDE the project so that
    # relative imports resolve correctly against node_modules.
    temp_dir = Path(tempfile.mkdtemp(prefix=".claude_pr_tests_", dir="."))
    generated_paths: list[str] = []

    try:
        for source_path, diff_chunk in frontend_changes.items():
            print(f"  Generating tests for {source_path} ...")
            source_content = read_source_file(source_path)

            # Mirror the source structure inside temp dir
            test_filename = Path(source_path).stem + ".test.ts"
            test_path = temp_dir / test_filename

            try:
                test_code = generate_tests_for_file(
                    source_path,
                    diff_chunk,
                    source_content,
                    str(test_path),
                )
            except Exception as exc:
                print(f"  ⚠ Claude error for {source_path}: {exc}")
                continue

            test_path.write_text(test_code, encoding="utf-8")
            generated_paths.append(str(test_path))
            print(f"  ✓ Ephemeral test written: {test_path}")

        results["files_tested"] = [
            # Report source filenames, not temp test paths
            k for k in frontend_changes
        ]

        if not generated_paths:
            results["summary"] = "Claude could not generate frontend tests for any changed files."
            Path(args.output).write_text(json.dumps(results, indent=2))
            return

        # Run vitest in run mode (no watch) targeting only our temp files
        config_flag = detect_vitest_config()
        vitest_cmd = ["npx", "vitest", "run", *generated_paths]
        if config_flag:
            vitest_cmd += config_flag.split()

        print(f"\nRunning: {' '.join(vitest_cmd)}")
        proc = subprocess.run(vitest_cmd, capture_output=True, text=True)
        output = proc.stdout + proc.stderr
        results["test_output"] = output

        # Parse vitest summary line
        for line in reversed(output.splitlines()):
            line_lower = line.lower()
            if any(kw in line_lower for kw in ("passed", "failed", "tests")):
                results["summary"] = line.strip()
                m = re.search(r"(\d+)\s+passed", line_lower)
                if m:
                    results["passed"] = int(m.group(1))
                m = re.search(r"(\d+)\s+failed", line_lower)
                if m:
                    results["failed"] = int(m.group(1))
                break

        if not results["summary"]:
            results["summary"] = "Vitest completed (see full output above)."

    finally:
        # Always clean up — test files never persist
        shutil.rmtree(temp_dir, ignore_errors=True)
        print(f"\nEphemeral test directory removed: {temp_dir}")

    Path(args.output).write_text(json.dumps(results, indent=2))
    print(f"Results saved to {args.output}")
    print(f"Summary: {results['summary']}")


if __name__ == "__main__":
    main()
