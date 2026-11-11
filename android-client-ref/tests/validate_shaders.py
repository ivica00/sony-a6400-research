#!/usr/bin/env python3
"""Static checks for the a6400lived GLSL shipping shaders.

Standard library only.  This is not a GLSL compiler: it checks the properties
that can be checked without a driver (version line, required uniforms, braces,
no discard, tap-count comments, PEAKING and external-texture switches).
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CPP = ROOT / "app" / "src" / "main" / "cpp"
FRAGMENT = CPP / "shaders" / "sgsr1_fragment.glsl"
VERTEX = CPP / "shaders" / "passthrough_vertex.glsl"

REQUIRED_UNIFORMS = (
    "uSrcTexture",
    "uSrcSize",
    "uSrcTextureSize",
    "uDstSize",
    "uSharpness",
    "uExposure",
    "uPeakingIntensity",
)


def strip_comments(source: str) -> str:
    source = re.sub(r"/\*.*?\*/", "", source, flags=re.DOTALL)
    source = re.sub(r"//[^\n]*", "", source)
    return source


def check_version(source: str, path: Path, failures: list[str]) -> None:
    lines = [line.strip() for line in source.splitlines() if line.strip()]
    if not lines or lines[0] != "#version 320 es":
        failures.append(f"{path.name}: first non-empty line must be '#version 320 es'")
    versions = re.findall(r"^#version\b.*$", source, flags=re.MULTILINE)
    if len(versions) != 1:
        failures.append(f"{path.name}: expected exactly one #version directive, got {versions!r}")


def check_balanced(source: str, path: Path, failures: list[str]) -> None:
    for opener, closer, name in (("{", "}", "braces"), ("(", ")", "parentheses"),
                                 ("[", "]", "brackets")):
        if source.count(opener) != source.count(closer):
            failures.append(
                f"{path.name}: unbalanced {name}: {source.count(opener)} {opener} vs "
                f"{source.count(closer)} {closer}"
            )


def check_fragment(source: str, failures: list[str]) -> None:
    stripped = strip_comments(source)
    for uniform in REQUIRED_UNIFORMS:
        pattern = rf"\buniform\b[^;]*\b{re.escape(uniform)}\b\s*;"
        if re.search(pattern, stripped) is None:
            failures.append(f"{FRAGMENT.name}: required uniform missing: {uniform}")
    if "sampler2D" not in stripped and "samplerExternalOES" not in stripped:
        failures.append(f"{FRAGMENT.name}: uSrcTexture has no sampler declaration")
    if "PEAKING" not in stripped:
        failures.append(f"{FRAGMENT.name}: no PEAKING compile switch")
    if "A6400_EXTERNAL_TEXTURE" not in stripped:
        failures.append(f"{FRAGMENT.name}: no A6400_EXTERNAL_TEXTURE compile switch")
    if re.search(r"\bdiscard\b", stripped):
        failures.append(f"{FRAGMENT.name}: discard is forbidden")
    comments = "\n".join(
        line for line in source.splitlines() if line.strip().startswith("//")
    )
    for needle in ("12-tap", "5-tap"):
        if needle not in comments:
            failures.append(f"{FRAGMENT.name}: tap-count comment '{needle}' missing")
    if "12" not in comments or "5" not in comments:
        failures.append(f"{FRAGMENT.name}: tap-count numeric comments missing")
    # Every texture() call is intentional; count the 12 + 5 structure in the
    # SGSR body, excluding the separate bilinear variant.
    bilinear_marker = "#else // A6400_BILINEAR"
    sgsr_source = source.split(bilinear_marker, 1)[0]
    texture_calls = len(re.findall(r"\btexture\s*\(", strip_comments(sgsr_source)))
    if texture_calls != 17:
        failures.append(
            f"{FRAGMENT.name}: expected exactly 17 texture() calls in the SGSR body "
            f"(12-tap + 5-tap), found {texture_calls}"
        )
    if "mediump" not in source:
        failures.append(f"{FRAGMENT.name}: expected explicit mediump precision")


def check_vertex(source: str, failures: list[str]) -> None:
    stripped = strip_comments(source)
    if "gl_VertexID" not in stripped:
        failures.append(f"{VERTEX.name}: full-screen triangle must use gl_VertexID")
    if "gl_Position" not in stripped:
        failures.append(f"{VERTEX.name}: no gl_Position write")
    if "layout" in stripped or "in vec" in stripped:
        failures.append(f"{VERTEX.name}: vertex attributes/VBOs are not expected")


def main() -> int:
    failures: list[str] = []
    for path in (FRAGMENT, VERTEX):
        if not path.is_file():
            failures.append(f"missing shader: {path}")
    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        return 1

    fragment = FRAGMENT.read_text(encoding="utf-8")
    vertex = VERTEX.read_text(encoding="utf-8")

    for path, source in ((FRAGMENT, fragment), (VERTEX, vertex)):
        check_version(source, path, failures)
        check_balanced(strip_comments(source), path, failures)
    check_fragment(fragment, failures)
    check_vertex(vertex, failures)

    if failures:
        for failure in failures:
            print(f"FAIL: {failure}")
        print(f"SHADER VALIDATION: FAIL ({len(failures)} issue(s))")
        return 1

    print("SHADER VALIDATION: PASS")
    print("  version: #version 320 es (fragment + vertex)")
    print("  uniforms: uSrcTexture uSrcSize uSrcTextureSize uDstSize uSharpness "
          "uExposure uPeakingIntensity")
    print("  compile switches: PEAKING, A6400_EXTERNAL_TEXTURE")
    print("  discard: absent")
    print("  taps: 12-tap edge estimate + 5-tap sharpen comments present")
    sgsr_calls = len(re.findall(
        r"\btexture\s*\(",
        strip_comments(fragment.split("#else // A6400_BILINEAR", 1)[0]),
    ))
    total_calls = len(re.findall(r"\btexture\s*\(", strip_comments(fragment)))
    print(f"  texture() calls: {sgsr_calls} SGSR (12+5) + "
          f"{total_calls - sgsr_calls} bilinear")
    return 0


if __name__ == "__main__":
    sys.exit(main())
