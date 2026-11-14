"""Local and CI guardrail runner (stdlib-only).

Runs fast structural, security/binary-hygiene, markdown-link, and status-sync
checks using only the Python standard library so contributors get immediate
parity with the GitHub Actions ``guardrails`` job.
"""
from __future__ import annotations

import argparse
import io
import os
import py_compile
import re
import struct
import subprocess
import sys
import unittest
from dataclasses import dataclass
from pathlib import Path

from project_paths import PROJECT_ROOT

FORBIDDEN_EXTENSION_RE = re.compile(
    r"\.(so|ko|elf|bin|img|raw|dat|tar|ckpt|dmp|etl)$", re.IGNORECASE
)
MAX_TRACKED_FILE_BYTES = 2 * 1024 * 1024  # 2 MiB
ELF_MAGIC = b"\x7fELF"

GUARDRAIL_TEST_MODULES = (
    "tests.test_repository_layout",
    "tests.test_target_profiles",
    "tests.test_research_status_sync",
    "tests.test_research_status_dashboard",
    "tests.test_agents_md_archive_integrity",
)

MARKDOWN_LINK_RE = re.compile(r"!?\[[^\]]*\]\(([^)\s]+)(?:\s+\"[^\"]*\")?\)")
FENCE_RE = re.compile(r"^\s*```")


@dataclass
class CheckResult:
    name: str
    passed: bool
    detail: str


FIRST_PARTY_DIRS = ("src", "tests", "tools", "probes", "legacy")
FALLBACK_IGNORED_PARTS = {
    ".git",
    "venv",
    "__pycache__",
    ".android-tools",
    "artifacts",
    "assets",
    "build",
    "devcrashday_a6400",
    "dist",
    "firmware",
    "backups",
    "android",
    "fwtool.py",
    "Sony-PMCA-RE",
}


def _read_git_index_paths(index_path: Path) -> list[Path] | None:
    """Parse git index v2/v3 entries in pure Python when git CLI cannot spawn."""
    try:
        data = index_path.read_bytes()
    except OSError:
        return None
    if len(data) < 12 or data[:4] != b"DIRC":
        return None
    version, count = struct.unpack(">II", data[4:12])
    if version not in (2, 3):
        return None
    pos = 12
    paths: list[Path] = []
    for _ in range(count):
        entry_start = pos
        if pos + 62 > len(data):
            return None
        flags = struct.unpack(">H", data[pos + 60 : pos + 62])[0]
        pos += 62
        if version == 3 and (flags & 0x4000):
            if pos + 2 > len(data):
                return None
            pos += 2
        nul = data.find(b"\x00", pos)
        if nul < 0:
            return None
        paths.append(Path(data[pos:nul].decode("utf-8", errors="replace")))
        # Git index entries are padded to 8-byte boundaries with at least 1 NUL byte.
        entry_len = (nul - entry_start) + 1
        pad = (8 - (entry_len % 8)) % 8
        pos = nul + 1 + pad
    return sorted(paths)


def tracked_files(root: Path) -> list[Path]:
    """Return tracked repository paths relative to ``root``."""
    proc = subprocess.run(
        ["git", "-C", str(root), "ls-files", "-z"],
        capture_output=True,
        check=False,
    )
    if proc.returncode == 0:
        raw_items = proc.stdout.split(b"\x00")
        return [Path(item.decode("utf-8")) for item in raw_items if item]

    index_paths = _read_git_index_paths(root / ".git" / "index")
    if index_paths is not None:
        return index_paths

    results: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file():
            continue
        rel = path.relative_to(root)
        if any(part in FALLBACK_IGNORED_PARTS for part in rel.parts):
            continue
        results.append(rel)
    return sorted(results)


def _is_first_party_py(rel: Path) -> bool:
    if rel.suffix != ".py":
        return False
    if len(rel.parts) == 1:
        return True
    return rel.parts[0] in FIRST_PARTY_DIRS


def check_py_compile(root: Path, files: list[Path] | None = None) -> CheckResult:
    """Compile first-party Python files to catch syntax errors."""
    rel_files = files if files is not None else tracked_files(root)
    py_files = [rel for rel in rel_files if _is_first_party_py(rel) and (root / rel).is_file()]
    errors: list[str] = []
    for rel in py_files:
        try:
            py_compile.compile(str(root / rel), doraise=True)
        except py_compile.PyCompileError as exc:
            errors.append(f"{rel.as_posix()}: {exc.msg}")
    if errors:
        return CheckResult("py_compile", False, "; ".join(errors[:5]))
    return CheckResult("py_compile", True, f"Compiled {len(py_files)} Python files")


def check_forbidden_files(root: Path, files: list[Path] | None = None) -> CheckResult:
    """Reject large tracked files, forbidden binary extensions, and ELF binaries."""
    rel_files = files if files is not None else tracked_files(root)
    violations: list[str] = []
    checked = 0
    for rel in rel_files:
        full = root / rel
        if not full.is_file():
            continue
        checked += 1
        posix = rel.as_posix()
        if FORBIDDEN_EXTENSION_RE.search(posix):
            violations.append(f"forbidden extension: {posix}")
            continue
        size = full.stat().st_size
        if size > MAX_TRACKED_FILE_BYTES:
            violations.append(f"exceeds 2 MiB ({size} bytes): {posix}")
            continue
        try:
            with full.open("rb") as fh:
                head = fh.read(4)
            if head == ELF_MAGIC:
                violations.append(f"ELF magic detected: {posix}")
        except OSError as exc:
            violations.append(f"unreadable {posix}: {exc}")

    if violations:
        return CheckResult("binary_and_size_guard", False, "; ".join(violations[:5]))
    return CheckResult(
        "binary_and_size_guard", True, f"Verified {checked} tracked files (<=2 MiB, no firmware/ELF)"
    )


def _strip_inline_code(line: str) -> str:
    return re.sub(r"`[^`]*`", "", line)


def iter_relative_markdown_links(markdown_text: str) -> list[str]:
    """Extract relative link targets outside fenced code blocks and inline code."""
    targets: list[str] = []
    in_fence = False
    for line in markdown_text.splitlines():
        if FENCE_RE.match(line):
            in_fence = not in_fence
            continue
        if in_fence:
            continue
        cleaned = _strip_inline_code(line)
        for match in MARKDOWN_LINK_RE.finditer(cleaned):
            target = match.group(1).strip()
            if target.startswith("<") and target.endswith(">"):
                target = target[1:-1]
            lower = target.lower()
            if lower.startswith(
                ("http://", "https://", "mailto:", "file://", "conversation://", "#")
            ):
                continue
            targets.append(target)
    return targets


def _is_first_party_doc(rel: Path) -> bool:
    if rel.suffix.lower() != ".md":
        return False
    if len(rel.parts) == 1:
        return True
    return rel.parts[0] == "docs" and "archives" not in rel.parts and "evidence" not in rel.parts


def check_markdown_links(root: Path, files: list[Path] | None = None) -> CheckResult:
    """Verify that relative links in first-party Markdown docs resolve on disk."""
    rel_files = files if files is not None else tracked_files(root)
    md_files = [
        rel
        for rel in rel_files
        if _is_first_party_doc(rel) and (root / rel).is_file()
    ]
    broken: list[str] = []
    link_count = 0
    for rel in md_files:
        full = root / rel
        text = full.read_text(encoding="utf-8", errors="replace")
        for target in iter_relative_markdown_links(text):
            link_count += 1
            path_part = target.split("#", 1)[0].split("?", 1)[0]
            if not path_part:
                continue
            resolved = (full.parent / path_part).resolve()
            if not resolved.exists():
                broken.append(f"{rel.as_posix()} -> {target}")
    if broken:
        return CheckResult("markdown_links", False, "; ".join(broken[:5]))
    return CheckResult(
        "markdown_links", True, f"Checked {link_count} relative links across {len(md_files)} docs"
    )


def check_guardrail_tests(root: Path, include_self: bool = True) -> CheckResult:
    """Run stdlib-only structural, profile, archive, and status-sync tests."""
    modules = list(GUARDRAIL_TEST_MODULES)
    if include_self:
        modules.append("tests.test_ci_check")

    loader = unittest.TestLoader()
    suite = unittest.TestSuite()
    for mod in modules:
        suite.addTests(loader.loadTestsFromName(mod))

    stream = io.StringIO()
    runner = unittest.TextTestRunner(stream=stream, verbosity=1)
    result = runner.run(suite)
    if not result.wasSuccessful():
        tail = stream.getvalue().strip().splitlines()[-10:]
        return CheckResult(
            "guardrail_tests",
            False,
            f"ran={result.testsRun}, failures={len(result.failures)}, errors={len(result.errors)} | "
            + " / ".join(tail[-3:]),
        )
    return CheckResult("guardrail_tests", True, f"Passed {result.testsRun} guardrail tests")


def check_status_svg_sync(root: Path) -> CheckResult:
    """Verify docs/images/status_a6400.svg matches STATUS_SNAPSHOT."""
    proc = subprocess.run(
        [sys.executable, "-m", "tools.research.render_research_status", "--check"],
        cwd=str(root),
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        msg = (proc.stderr or proc.stdout).strip().splitlines()
        return CheckResult("status_svg_sync", False, msg[-1] if msg else "render_research_status --check failed")
    return CheckResult("status_svg_sync", True, "docs/images/status_a6400.svg matches STATUS_SNAPSHOT")


def format_markdown_summary(results: list[CheckResult]) -> str:
    """Render check results as a GitHub-flavored Markdown summary."""
    lines = [
        "## CI Guardrails Summary",
        "",
        "| Check | Status | Details |",
        "| :--- | :---: | :--- |",
    ]
    for item in results:
        badge = "PASS" if item.passed else "FAIL"
        detail = " ".join(item.detail.splitlines())
        lines.append(f"| `{item.name}` | {badge} | {detail} |")
    all_ok = all(item.passed for item in results)
    lines.append("")
    lines.append(f"**Overall:** {'PASS' if all_ok else 'FAIL'} ({sum(1 for r in results if r.passed)}/{len(results)} checks passed)")
    return "\n".join(lines) + "\n"


def run_all_checks(root: Path = PROJECT_ROOT, include_self: bool = True) -> list[CheckResult]:
    files = tracked_files(root)
    return [
        check_py_compile(root, files),
        check_forbidden_files(root, files),
        check_markdown_links(root, files),
        check_status_svg_sync(root),
        check_guardrail_tests(root, include_self=include_self),
    ]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Run stdlib-only local/CI guardrails.")
    parser.add_argument(
        "--summary",
        action="store_true",
        help="Print a Markdown summary table (and append to $GITHUB_STEP_SUMMARY if set).",
    )
    parser.add_argument(
        "--skip-self-test",
        action="store_true",
        help="Skip running tests.test_ci_check inside guardrail_tests.",
    )
    args = parser.parse_args(argv)

    results = run_all_checks(PROJECT_ROOT, include_self=not args.skip_self_test)
    for item in results:
        tag = "PASS" if item.passed else "FAIL"
        print(f"[{tag}] {item.name}: {item.detail}")

    if args.summary:
        md = format_markdown_summary(results)
        print()
        print(md, end="")
        summary_path = os.environ.get("GITHUB_STEP_SUMMARY")
        if summary_path:
            with open(summary_path, "a", encoding="utf-8") as fh:
                fh.write(md)

    return 0 if all(item.passed for item in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
