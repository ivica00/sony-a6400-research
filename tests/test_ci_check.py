"""Unit tests for the stdlib-only local/CI guardrail runner."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from tools.research.ci_check import (
    CheckResult,
    check_forbidden_files,
    check_markdown_links,
    check_py_compile,
    format_markdown_summary,
    iter_relative_markdown_links,
)


class TestCiCheck(unittest.TestCase):
    def test_py_compile_accepts_valid_python_and_rejects_syntax_error(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            ok_file = root / "ok.py"
            ok_file.write_text("x = 1 + 2\n", encoding="utf-8")
            res_ok = check_py_compile(root, [Path("ok.py")])
            self.assertTrue(res_ok.passed, res_ok.detail)

            bad_file = root / "bad.py"
            bad_file.write_text("def broken(:\n    pass\n", encoding="utf-8")
            res_bad = check_py_compile(root, [Path("bad.py")])
            self.assertFalse(res_bad.passed)
            self.assertIn("bad.py", res_bad.detail)

    def test_forbidden_files_rejects_binary_extensions_elf_magic_and_large_files(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "good.txt").write_text("hello\n", encoding="utf-8")
            self.assertTrue(check_forbidden_files(root, [Path("good.txt")]).passed)

            (root / "dump.bin").write_bytes(b"data")
            res_ext = check_forbidden_files(root, [Path("dump.bin")])
            self.assertFalse(res_ext.passed)
            self.assertIn("forbidden extension", res_ext.detail)

            (root / "mystery").write_bytes(b"\x7fELF\x01\x01\x01\x00")
            res_elf = check_forbidden_files(root, [Path("mystery")])
            self.assertFalse(res_elf.passed)
            self.assertIn("ELF magic detected", res_elf.detail)

            (root / "huge.json").write_bytes(b"a" * (2 * 1024 * 1024 + 1))
            res_size = check_forbidden_files(root, [Path("huge.json")])
            self.assertFalse(res_size.passed)
            self.assertIn("exceeds 2 MiB", res_size.detail)

    def test_markdown_links_ignores_code_and_catches_broken_relative_targets(self) -> None:
        sample = "\n".join(
            [
                "See [good](docs/guide.md#section) and [web](https://example.com).",
                "Inline `[ignored](missing.md)` should not count.",
                "```markdown",
                "[fenced](also_missing.md)",
                "```",
            ]
        )
        self.assertEqual(iter_relative_markdown_links(sample), ["docs/guide.md#section"])

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "docs").mkdir()
            (root / "docs/guide.md").write_text("# Guide\n", encoding="utf-8")
            (root / "README.md").write_text("[Guide](docs/guide.md#top)\n", encoding="utf-8")
            self.assertTrue(check_markdown_links(root, [Path("README.md")]).passed)

            (root / "BROKEN.md").write_text("[Missing](docs/nope.md)\n", encoding="utf-8")
            res_broken = check_markdown_links(root, [Path("BROKEN.md")])
            self.assertFalse(res_broken.passed)
            self.assertIn("docs/nope.md", res_broken.detail)

    def test_format_markdown_summary_renders_table_and_overall_status(self) -> None:
        summary = format_markdown_summary(
            [
                CheckResult("py_compile", True, "Compiled 10 files"),
                CheckResult("markdown_links", False, "1 broken link"),
            ]
        )
        self.assertIn("| `py_compile` | PASS | Compiled 10 files |", summary)
        self.assertIn("| `markdown_links` | FAIL | 1 broken link |", summary)
        self.assertIn("**Overall:** FAIL (1/2 checks passed)", summary)


if __name__ == "__main__":
    unittest.main()
