#!/usr/bin/env python3
"""Build and run the a6400 daemon host unit tests.

No hardware is touched: only ``test/host_test.c``, ``src/frame_hook.c`` and
``src/control_bridge.c`` are compiled and executed on the host.

Compiler selection, in order:

1. ``$CC`` if set (used verbatim).
2. An x86 host compiler inside the WSL Ubuntu distribution (``gcc``/``cc``/
   ``clang``), which is the documented path:
   ``wsl -d Ubuntu -- bash -lc "..."``.
3. A host compiler on Windows (``gcc`` on PATH, ``C:\\mingw64\\bin\\gcc.exe``,
   ``clang``) when WSL has no x86 Linux compiler.
4. When the runner itself is executed *inside* WSL and WSL has no x86 Linux
   compiler, the Windows MinGW gcc is invoked through WSL interop. The test
   binary is therefore a Windows executable; that is printed explicitly.

This environment has only the ARM cross compiler inside WSL, so the interop or
Windows path is what actually runs here. The chosen compiler is always printed
so the receipt is never ambiguous.

Exit status is non-zero on a build failure, a non-zero test exit, any reported
failure, or fewer than the required number of assertions.
"""

from __future__ import annotations

import os
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
BUILD = ROOT / "build"
SOURCES = ["test/host_test.c", "src/frame_hook.c", "src/control_bridge.c",
           "src/sd_policy.c"]
CFLAGS = ["-std=gnu11", "-Wall", "-Wextra", "-Werror", "-Iinclude"]
MIN_ASSERTIONS = 40
WSL_DISTRO = os.environ.get("A6400_WSL_DISTRO", "Ubuntu")


def _run(cmd: list[str], **kwargs) -> subprocess.CompletedProcess:
    return subprocess.run(cmd, cwd=str(ROOT), text=True,
                          stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
                          **kwargs)


def _which_local(names: list[str]) -> str | None:
    for name in names:
        if os.name == "nt":
            found = shutil.which(name)
            if found:
                return found
            candidate = Path("C:/mingw64/bin") / f"{name}.exe"
            if candidate.is_file():
                return str(candidate)
        else:
            found = shutil.which(name)
            if found:
                return found
    return None


def _wsl_compiler() -> str | None:
    if os.name != "nt" or not shutil.which("wsl"):
        return None
    script = "command -v gcc || command -v cc || command -v clang || true"
    probe = _run(["wsl", "-d", WSL_DISTRO, "--", "bash", "-lc", script])
    if probe.returncode != 0:
        return None
    name = probe.stdout.strip().splitlines()
    return name[0] if name else None


def _wsl_path(path: Path) -> str:
    probe = _run(["wsl", "-d", WSL_DISTRO, "--", "wslpath", "-a", str(path)])
    if probe.returncode != 0:
        raise RuntimeError(f"wslpath failed for {path}: {probe.stdout}")
    return probe.stdout.strip()


def build_and_run_wsl(compiler: str) -> int:
    root = _wsl_path(ROOT)
    quoted = "'" + root.replace("'", "'\\''") + "'"
    script = (
        f"cd {quoted} && mkdir -p build && "
        f"{compiler} {' '.join(CFLAGS)} -o build/host_test {' '.join(SOURCES)} && "
        f"./build/host_test build"
    )
    print(f"compiler: {compiler} (WSL {WSL_DISTRO})")
    print(f"command : wsl -d {WSL_DISTRO} -- bash -lc \"{script}\"")
    proc = _run(["wsl", "-d", WSL_DISTRO, "--", "bash", "-lc", script])
    return _report(proc, "build/host_test")


def build_and_run_local(compiler: str, windows_binary: bool | None = None) -> int:
    BUILD.mkdir(parents=True, exist_ok=True)
    if windows_binary is None:
        windows_binary = os.name == "nt"
    exe = BUILD / ("host_test.exe" if windows_binary else "host_test")
    interop = windows_binary and os.name != "nt"
    if interop:
        # The Windows linker cannot open a /mnt/c path, so build and run with
        # paths relative to the (translated) working directory.
        exe_arg = "./build/host_test.exe"
    else:
        exe_arg = str(exe)
    cmd = [compiler, *CFLAGS, "-o", exe_arg, *SOURCES]
    kind = "host" if os.name == "nt" else "Windows host compiler via WSL interop"
    print(f"compiler: {compiler} ({kind})")
    print("command : " + " ".join(cmd))
    build = _run(cmd)
    if build.returncode != 0:
        print(build.stdout)
        print("RESULT: BUILD FAILED")
        return 1
    if build.stdout.strip():
        print(build.stdout.strip())
    # A Windows executable launched through interop cannot open a /mnt/c path
    # argument; "build" is relative to the translated working directory.
    work_arg = "build" if interop else str(BUILD)
    run = _run([exe_arg, work_arg])
    return _report(run, exe_arg)


def _report(proc: subprocess.CompletedProcess, binary: str) -> int:
    output = proc.stdout or ""
    print(output, end="" if output.endswith("\n") else "\n")

    checks = None
    failures = None
    for line in output.splitlines():
        if line.startswith("checks:"):
            try:
                checks = int(line.split(":", 1)[1].strip())
            except ValueError:
                checks = None
        elif line.startswith("failures:"):
            try:
                failures = int(line.split(":", 1)[1].strip())
            except ValueError:
                failures = None

    problems: list[str] = []
    if proc.returncode != 0:
        problems.append(f"non-zero test exit ({proc.returncode})")
    if failures is None:
        problems.append("no 'failures:' line in the test output")
    elif failures != 0:
        problems.append(f"{failures} assertion(s) failed")
    if checks is None:
        problems.append("no 'checks:' line in the test output")
    elif checks < MIN_ASSERTIONS:
        problems.append(f"only {checks} assertions, need >= {MIN_ASSERTIONS}")

    print(f"binary  : {binary}")
    print(f"checks  : {checks if checks is not None else 'missing'}")
    print(f"failures: {failures if failures is not None else 'missing'}")
    if problems:
        for problem in problems:
            print(f"PROBLEM : {problem}")
        print("RESULT: FAIL")
        return 1
    print("RESULT: PASS")
    return 0


def _windows_compiler_for_interop() -> str | None:
    """A Windows gcc reachable from WSL, used only when WSL has no x86 cc."""
    if os.name == "nt":
        return None
    override = os.environ.get("A6400_WIN_GCC")
    candidates = [override] if override else []
    candidates.append("/mnt/c/mingw64/bin/gcc.exe")
    for candidate in candidates:
        if candidate and Path(candidate).is_file():
            return candidate
    return None


def main() -> int:
    explicit = os.environ.get("CC")
    if explicit:
        return build_and_run_local(explicit)

    if os.name == "nt":
        wsl_cc = _wsl_compiler()
        if wsl_cc:
            return build_and_run_wsl(wsl_cc)
        print("note: no x86 compiler inside WSL; using a Windows host compiler")
        local_cc = _which_local(["gcc", "cc", "clang"])
        if local_cc:
            return build_and_run_local(local_cc)
    else:
        # Running inside a POSIX host, possibly WSL.
        local_cc = _which_local(["gcc", "cc", "clang", "x86_64-linux-gnu-gcc"])
        if local_cc:
            return build_and_run_local(local_cc)
        win_cc = _windows_compiler_for_interop()
        if win_cc:
            print("note: no x86 Linux compiler here; using the Windows compiler through WSL interop")
            return build_and_run_local(win_cc, windows_binary=True)

    print("no host compiler found (tried $CC, WSL/Linux gcc/cc/clang, "
          "Windows gcc/cc/clang, WSL-interop /mnt/c/mingw64/bin/gcc.exe)")
    print("RESULT: BLOCKED")
    return 1


if __name__ == "__main__":
    sys.exit(main())
