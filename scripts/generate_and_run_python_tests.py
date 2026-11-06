"""
generate_and_run_python_tests.py

Reads a PR diff, asks Claude to generate Pytest tests for changed Python files,
writes them into the repo's existing tests/ or test/ folder, runs pytest,
and saves a structured JSON result.

Tests ARE committed to the repo (written to the detected test folder).
The action will commit them if you add a commit step — or leave them for
the developer to review and commit manually.
"""

import argparse
import json
import subprocess
import sys
import tempfile
from pathlib import Path

# ── Helpers ──────────────────────────────────────────────────────────────────

def find_test_dir() -> Path | None:
    """Auto-detect tests/ or test/ folder in the repo root."""
    for candidate in ["tests", "test"]:
        p = Path(candidate)
        if p.is_dir():
            return p
    return None


def extract_python_changes(diff_text: str) -> dict[str, str]:
    """
    Parse unified diff and return {filename: changed_chunk} for .py files.
    Only includes files that were modified or added (not deleted).
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
        elif line.startswith("+++ b/") and line.endswith(".py"):
            current_file = line[6:]  # strip '+++ b/'
            current_lines = []
        elif line.startswith("--- ") or line.startswith("diff "):
            continue
        elif current_file:
            current_lines.append(line)

    if current_file and current_lines:
        changes[current_file] = "\n".join(current_lines)

    # Remove deleted files (only have - lines, no + lines)
    return {
        f: chunk
        for f, chunk in changes.items()
        if any(ln.startswith("+") for ln in chunk.splitlines())
    }


def read_source_file(filepath: str) -> str:
    """Read a source file for additional context, return empty string if missing."""
    try:
        return Path(filepath).read_text(encoding="utf-8")
    except (FileNotFoundError, PermissionError):
        return ""


# ── Claude call ───────────────────────────────────────────────────────────────

SYSTEM_PROMPT = """You are a senior Python engineer writing Pytest test suites.

Rules:
- Write ONLY valid Python/Pytest code. No markdown, no explanation outside comments.
- Cover the new or changed behaviour shown in the diff.
- Use descriptive test function names (test_<what>_<expected_outcome>).
- Prefer parametrize for data-driven cases.
- Mock external I/O (DB, HTTP, filesystem) with pytest-mock or unittest.mock.
- Do NOT alter the source files under test.
- Output only the test file content, starting with imports."""


def generate_tests_for_file(
    source_path: str,
    diff_chunk: str,
    source_content: str,
) -> str:
    """Call Claude Code CLI to generate tests for a single changed Python file."""
    user_message = f"""Generate a Pytest test suite for the following changed Python file.

FILE: {source_path}

--- CURRENT SOURCE ---
{source_content or "(file not readable — use diff context only)"}

--- DIFF (what changed) ---
{diff_chunk}

Write tests that cover the changed/added logic. Import from the module path implied by the file path."""

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
    parser.add_argument("--diff", required=True, help="Path to the PR diff file")
    parser.add_argument("--output", required=True, help="Path to write JSON results")
    args = parser.parse_args()

    diff_text = Path(args.diff).read_text(encoding="utf-8")
    python_changes = extract_python_changes(diff_text)

    results = {
        "language": "python",
        "files_tested": [],
        "test_output": "",
        "passed": 0,
        "failed": 0,
        "errors": 0,
        "summary": "",
        "generated_test_paths": [],
    }

    if not python_changes:
        results["summary"] = "No Python files changed in this PR."
        Path(args.output).write_text(json.dumps(results, indent=2))
        print(results["summary"])
        return

    test_dir = find_test_dir()
    if test_dir is None:
        # Create a tests/ folder if none exists
        test_dir = Path("tests")
        test_dir.mkdir(exist_ok=True)
        (test_dir / "__init__.py").touch()
        print("Created tests/ directory (none detected).")
    else:
        print(f"Detected test directory: {test_dir}/")

    generated_paths: list[str] = []

    for source_path, diff_chunk in python_changes.items():
        print(f"  Generating tests for {source_path} ...")
        source_content = read_source_file(source_path)

        try:
            test_code = generate_tests_for_file(
                source_path, diff_chunk, source_content
            )
        except Exception as exc:
            print(f"  ⚠ Claude error for {source_path}: {exc}")
            continue

        # Derive test filename: src/foo/bar.py → tests/test_foo_bar.py
        safe_name = source_path.replace("/", "_").replace(".py", "")
        test_filename = f"test_{safe_name}.py"
        test_path = test_dir / test_filename
        test_path.write_text(test_code, encoding="utf-8")
        generated_paths.append(str(test_path))
        print(f"  ✓ Written: {test_path}")

    results["generated_test_paths"] = generated_paths

    if not generated_paths:
        results["summary"] = "Claude could not generate tests for any changed files."
        Path(args.output).write_text(json.dumps(results, indent=2))
        return

    # Run only the generated tests
    print("\nRunning generated tests with pytest...")
    proc = subprocess.run(
        ["pytest", *generated_paths, "--tb=short", "-q"],
        capture_output=True,
        text=True,
    )

    output = proc.stdout + proc.stderr
    results["test_output"] = output
    results["files_tested"] = generated_paths

    # Parse summary line e.g. "3 passed, 1 failed, 0 errors"
    for line in reversed(output.splitlines()):
        line_lower = line.lower()
        if "passed" in line_lower or "failed" in line_lower or "error" in line_lower:
            results["summary"] = line.strip()
            if "passed" in line_lower:
                import re
                m = re.search(r"(\d+) passed", line_lower)
                if m:
                    results["passed"] = int(m.group(1))
            if "failed" in line_lower:
                import re
                m = re.search(r"(\d+) failed", line_lower)
                if m:
                    results["failed"] = int(m.group(1))
            if "error" in line_lower:
                import re
                m = re.search(r"(\d+) error", line_lower)
                if m:
                    results["errors"] = int(m.group(1))
            break

    Path(args.output).write_text(json.dumps(results, indent=2))
    print(f"\nResults saved to {args.output}")
    print(f"Summary: {results['summary']}")


if __name__ == "__main__":
    main()
