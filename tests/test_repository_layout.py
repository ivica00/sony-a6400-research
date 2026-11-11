"""Repository-layout contract checks.

The repository root is a contributor-facing surface, not a scratch directory. These
offline checks fail when a forwarding shim or launcher returns to the root, when a moved
document/asset is duplicated, or when a first-party module imports a module by the bare
root name that no longer exists there.

Standard-library only so it can run in CI without the emulation dependencies.
"""
import re
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

REMOVED_ROOT_SHIMS = (
    "analyze_hardware_drivers.py",
    "backup_camera.py",
    "check_camera.py",
    "cxd90045_gui_runner.py",
    "cxd90045_hle_emulator.py",
    "firmware_analyzer.py",
    "sony_gui_simulator.py",
    "test_authentic_screens.py",
    "unpack_firmware.py",
)

MOVED_LAUNCHERS = {
    "launch_cinema_mpv.bat": ("scripts", "%~dp0..\\artifacts"),
    "launch_cinemahud_android.ps1": ("scripts", "Split-Path -Parent $PSScriptRoot"),
    "launch_cinemahud_ptp.bat": ("scripts", 'cd /d "%~dp0.."'),
    "start_camera_shell.bat": ("scripts", '%~dp0..\\tools\\cam_live_terminal.py'),
}

MOVED_ASSETS = (
    "docs/images/status.png",
    "docs/images/status_a6400.png",
    "docs/UVC_HANDOVER_PLAN.md",
)

SCANNED_DIRECTORIES = ("src", "tools", "tests", "legacy")


def _read(path):
    return path.read_text(encoding="utf-8").replace("\r\n", "\n")


class TestRootDirectory(unittest.TestCase):
    def test_forwarding_shims_are_gone(self):
        for name in REMOVED_ROOT_SHIMS:
            self.assertFalse(
                (ROOT / name).exists(),
                f"{name} is a removed forwarding shim; launch the implementation as a module instead",
            )

    def test_project_paths_stays_at_root(self):
        self.assertTrue((ROOT / "project_paths.py").is_file())

    def test_standard_project_files_exist(self):
        for name in ("README.md", "LICENSE", "CONTRIBUTING.MD", "AGENTS.MD", "pyproject.toml",
                     "requirements.txt", ".gitignore"):
            self.assertTrue((ROOT / name).is_file(), f"missing standard root file: {name}")

    def test_core_directories_exist(self):
        for name in ("src", "tools", "tests", "docs", "scripts", "legacy", "probes",
                     ".github"):
            self.assertTrue((ROOT / name).is_dir(), f"missing core directory: {name}")


class TestLaunchers(unittest.TestCase):
    def test_launchers_live_in_scripts(self):
        for name in MOVED_LAUNCHERS:
            self.assertFalse((ROOT / name).exists(), f"{name} must not sit in the repository root")
            self.assertTrue((ROOT / "scripts" / name).is_file(), f"missing scripts/{name}")

    def test_launchers_resolve_the_repository_root(self):
        for name, (_directory, marker) in MOVED_LAUNCHERS.items():
            text = _read(ROOT / "scripts" / name)
            self.assertIn(marker, text, f"{name} does not resolve paths from its own location")

    def test_no_launcher_depends_on_the_callers_cwd(self):
        for name in MOVED_LAUNCHERS:
            text = _read(ROOT / "scripts" / name)
            self.assertNotIn('"%~dp0venv', text, name)
            self.assertNotIn('"%~dp0artifacts', text, name)


class TestMovedAssets(unittest.TestCase):
    def test_assets_live_under_docs(self):
        for relative in MOVED_ASSETS:
            self.assertTrue((ROOT / relative).is_file(), f"missing moved asset: {relative}")
            name = Path(relative).name
            self.assertFalse((ROOT / name).exists(), f"{name} must not be duplicated at the root")

    def test_status_png_writer_targets_docs_images(self):
        text = _read(ROOT / "tools" / "research" / "generate_status_image.py")
        self.assertIn('"docs" / "images" / "status_a6400.png"', text)
        self.assertNotIn('ROOT / "status_a6400.png"', text)


class TestNoBareShimImports(unittest.TestCase):
    """A first-party module must never import a removed shim by its bare root name."""

    def test_no_bare_shim_imports(self):
        modules = "|".join(re.escape(Path(name).stem) for name in REMOVED_ROOT_SHIMS)
        pattern = re.compile(rf"^\s*(?:from|import)\s+(?:{modules})\b")
        offenders = []
        for directory in SCANNED_DIRECTORIES:
            for path in sorted((ROOT / directory).rglob("*.py")):
                if "__pycache__" in path.parts:
                    continue
                for number, line in enumerate(_read(path).splitlines(), start=1):
                    if pattern.match(line):
                        offenders.append(f"{path.relative_to(ROOT)}:{number}: {line.strip()}")
        self.assertEqual(offenders, [], "bare import of a removed root shim:\n" + "\n".join(offenders))


class TestDocumentationEntryPoints(unittest.TestCase):
    def test_contributor_guides_exist(self):
        for relative in (
            "docs/ADDING_A_BIONZX_CAMERA.md",
            "docs/CONTRIBUTING_UVC_PTP.md",
            "docs/UVC_PTP_STATUS.md",
            "docs/REPOSITORY.md",
            "docs/images/research-status.svg",
        ):
            self.assertTrue((ROOT / relative).is_file(), f"missing contributor document: {relative}")

    def test_readme_links_the_multi_device_guide(self):
        readme = _read(ROOT / "README.md")
        self.assertIn("docs/ADDING_A_BIONZX_CAMERA.md", readme)
        self.assertIn("docs/CONTRIBUTING_UVC_PTP.md", readme)
        self.assertIn("docs/images/research-status.svg", readme)

    def test_ci_workflow_runs_the_structural_checks(self):
        workflow = _read(ROOT / ".github" / "workflows" / "ci.yml")
        for test_module in (
            "tests.test_repository_layout",
            "tests.test_target_profiles",
            "tests.test_research_status_sync",
            "tests.test_research_status_dashboard",
        ):
            self.assertIn(test_module, workflow)


if __name__ == "__main__":
    unittest.main()
