#!/usr/bin/env python3
"""Static structure verification for the a6400 reference Android client.

No Android SDK, Gradle or Kotlin compiler is available in this environment, so
this script is the *only* mechanical proof that the source tree is complete and
self-consistent. It is deliberately strict: every check that fails is reported
with the file and the reason, and any failure makes the process exit non-zero.

Checks
------
 1. Every required file exists (and is non-empty).
 2. `NativePipeline.kt` declares exactly the nine fixed JNI entry points, in
    order, with the exact signatures the native workstream implements.
 3. `System.loadLibrary("a6400lived")` is present.
 4. The PTP opcodes, response codes, the 0xFFFFC002 liveview handle and every
    property code the client depends on are present in the transport sources.
 5. The manifest declares USB host support, the device-attached intent filter
    and the device XML filter, and does NOT request CAMERA.
 6. `res/xml/usb_device_filter.xml` filters VID 0x054C with both PIDs.
 7. `app/build.gradle.kts` points at `src/main/cpp/CMakeLists.txt`, pins
    compileSdk 34 / minSdk 26 / targetSdk 34 / jvmTarget 17 / arm64-v8a and a
    literal NDK version, and pulls in no AndroidX dependency.
 8. No TODO/FIXME/XXX/HACK/"stub"/"not implemented" marker survives in shipping
    Kotlin.
 9. Braces balance in every Kotlin file, using a comment- and string-aware
    scanner (a naive count would be fooled by string templates).
10. The documentation states the things this project must not quietly drop:
    the verified/unverified split, the 0x9205 ineffectiveness warning, the
    vendor-libs note for libjpeg-turbo and the honest "not compiled" record.

Usage:
    python android-client-ref/tools/verify_structure.py [-v]
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
APP = ROOT / "app"
MAIN = APP / "src" / "main"
KT_ROOT = MAIN / "java" / "com" / "a6400" / "lived"

VERBOSE = "-v" in sys.argv[1:] or "--verbose" in sys.argv[1:]

failures: list[str] = []
checks = 0


def ok(message: str) -> None:
    global checks
    checks += 1
    if VERBOSE:
        print(f"  ok   {message}")


def fail(message: str) -> None:
    global checks
    checks += 1
    failures.append(message)
    print(f"  FAIL {message}")


def check(condition: bool, success: str, failure: str) -> None:
    if condition:
        ok(success)
    else:
        fail(failure)


REQUIRED_FILES = [
    "settings.gradle.kts",
    "build.gradle.kts",
    "gradle.properties",
    "README.md",
    "app/build.gradle.kts",
    "app/proguard-rules.pro",
    "app/src/main/AndroidManifest.xml",
    "app/src/main/res/xml/usb_device_filter.xml",
    "app/src/main/res/values/strings.xml",
    "docs/PROTOCOL.md",
    "docs/VERIFICATION.md",
    "tools/verify_structure.py",
    "app/src/main/java/com/a6400/lived/MainActivity.kt",
    "app/src/main/java/com/a6400/lived/NativePipeline.kt",
    "app/src/main/java/com/a6400/lived/usb/TransportContracts.kt",
    "app/src/main/java/com/a6400/lived/usb/UsbHost.kt",
    "app/src/main/java/com/a6400/lived/usb/PtpContainer.kt",
    "app/src/main/java/com/a6400/lived/usb/PtpTransport.kt",
    "app/src/main/java/com/a6400/lived/usb/PtpSony.kt",
    "app/src/main/java/com/a6400/lived/usb/UvcTransport.kt",
    "app/src/main/java/com/a6400/lived/gl/SgsrSurfaceView.kt",
    "app/src/main/java/com/a6400/lived/media/LatencyTracker.kt",
]

# Files owned by the native-pipeline workstream. They are NOT required here and
# must not be created by this verification (or by the Kotlin client author):
#   app/src/main/cpp/**      (CMakeLists.txt, JNI implementation, libjpeg-turbo)
#   tests/**                 (native/host test harness)
FOREIGN_OWNED = [
    "app/src/main/cpp/CMakeLists.txt",
    "tests",
]

EXPECTED_JNI = [
    "external fun nativeCreate(): Long",
    "external fun nativeDestroy(handle: Long)",
    "external fun nativePushJpeg(handle: Long, data: ByteArray, length: Int, seq: Long, captureNs: Long): Int",
    "external fun nativeConfigure(handle: Long, viewportW: Int, viewportH: Int, frameW: Int, frameH: Int)",
    "external fun nativeRender(handle: Long): Long",
    "external fun nativeSetSharpness(handle: Long, value: Float)",
    "external fun nativeSetUpscaleMode(handle: Long, mode: Int)",
    "external fun nativeSetFocusPeaking(handle: Long, enabled: Int, intensity: Float)",
    "external fun nativeGetStats(handle: Long, out: LongArray)",
]

# opcode / constant -> human description
REQUIRED_PTP_TOKENS = {
    0x1002: "OpenSession",
    0x1003: "CloseSession",
    0x1009: "GetObject (liveview)",
    0x9201: "Sony SDIOConnect",
    0x9202: "Sony GetSDIOExtDeviceInfo",
    0x9205: "Sony absolute property write",
    0x9207: "Sony signed notch write",
    0x9209: "Sony property descriptor read",
    0x2001: "PTP response OK",
    0x201E: "PTP response SessionAlreadyOpen",
    0x5007: "property aperture",
    0xD20D: "property shutter",
    0xD21E: "property ISO",
    0x5010: "property exposure compensation",
    0x500A: "property focus mode",
    0x5001: "property battery (absent on a6400)",
    0x00C8: "0x9202 argument",
}

FORBIDDEN_MARKERS = re.compile(
    r"(\bTODO\b|\bFIXME\b|\bXXX\b|\bHACK\b|\bstub\b|\bnot implemented\b|\bunimplemented\b)",
    re.IGNORECASE,
)


# --------------------------------------------------------------------------- 9


def strip_kotlin(source: str) -> str:
    """Removes comments, strings and char literals so braces can be counted."""
    out: list[str] = []
    i = 0
    n = len(source)
    while i < n:
        c = source[i]
        nxt = source[i + 1] if i + 1 < n else ""
        if c == "/" and nxt == "/":
            j = source.find("\n", i)
            if j < 0:
                break
            out.append("\n")
            i = j + 1
            continue
        if c == "/" and nxt == "*":
            depth = 1
            i += 2
            while i < n and depth > 0:
                if source.startswith("/*", i):
                    depth += 1
                    i += 2
                elif source.startswith("*/", i):
                    depth -= 1
                    i += 2
                else:
                    if source[i] == "\n":
                        out.append("\n")
                    i += 1
            continue
        if source.startswith('"""', i):
            j = source.find('"""', i + 3)
            i = n if j < 0 else j + 3
            out.append('""')
            continue
        if c == '"':
            i += 1
            while i < n:
                if source[i] == "\\":
                    i += 2
                    continue
                if source[i] == '"':
                    i += 1
                    break
                if source[i] == "\n":
                    out.append("\n")
                i += 1
            out.append('""')
            continue
        if c == "'":
            i += 1
            while i < n:
                if source[i] == "\\":
                    i += 2
                    continue
                if source[i] == "'":
                    i += 1
                    break
                i += 1
            out.append("'x'")
            continue
        out.append(c)
        i += 1
    return "".join(out)


def brace_balance(path: Path) -> tuple[int, int]:
    """Returns (final_depth, line_of_first_underflow)."""
    source = path.read_text(encoding="utf-8")
    stripped = strip_kotlin(source)
    depth = 0
    line = 1
    underflow_line = 0
    for ch in stripped:
        if ch == "\n":
            line += 1
        elif ch == "{":
            depth += 1
        elif ch == "}":
            depth -= 1
            if depth < 0 and underflow_line == 0:
                underflow_line = line
    return depth, underflow_line


# --------------------------------------------------------------------------- 1


def check_required_files() -> None:
    print("[1] required files")
    for relative in REQUIRED_FILES:
        path = ROOT / relative
        if not path.is_file():
            fail(f"missing file: {relative}")
        elif path.stat().st_size == 0:
            fail(f"empty file: {relative}")
        else:
            ok(relative)
    for foreign in FOREIGN_OWNED:
        path = ROOT / foreign
        state = "present" if path.exists() else "absent (other owner)"
        ok(f"{foreign}: {state}")


# --------------------------------------------------------------------------- 2


def normalize(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def check_jni() -> None:
    print("[2] fixed JNI contract")
    path = KT_ROOT / "NativePipeline.kt"
    if not path.is_file():
        fail("NativePipeline.kt missing; cannot verify the JNI contract")
        return
    source = path.read_text(encoding="utf-8")
    declared = [
        normalize(match.group(0))
        for match in re.finditer(r"external\s+fun\s+[^\n]+", source)
    ]
    check(
        len(declared) == len(EXPECTED_JNI),
        f"{len(declared)} external fun declarations",
        f"expected {len(EXPECTED_JNI)} external fun declarations, found {len(declared)}",
    )
    for index, expected in enumerate(EXPECTED_JNI):
        if index >= len(declared):
            fail(f"missing JNI declaration #{index + 1}: {expected}")
            continue
        if declared[index] != expected:
            fail(f"JNI declaration #{index + 1} differs:\n        expected: {expected}\n        found:    {declared[index]}")
        else:
            ok(f"JNI #{index + 1} {expected.split('(')[0]}")
    check(
        re.search(r'System\.loadLibrary\("a6400lived"\)', source) is not None,
        'System.loadLibrary("a6400lived") present',
        'System.loadLibrary("a6400lived") missing from NativePipeline.kt',
    )


# --------------------------------------------------------------------------- 3


def usb_sources() -> str:
    parts = []
    for path in sorted((KT_ROOT / "usb").glob("*.kt")):
        parts.append(path.read_text(encoding="utf-8"))
    return "\n".join(parts)


def check_ptp_tokens() -> None:
    print("[3] PTP opcodes, responses and property codes")
    sources = usb_sources()
    if not sources:
        fail("no sources under java/com/a6400/lived/usb/")
        return
    for value, description in REQUIRED_PTP_TOKENS.items():
        pattern = re.compile(rf"(?i)0x0*{value:x}(?:L)?\b")
        check(
            pattern.search(sources) is not None,
            f"0x{value:04X} ({description})",
            f"0x{value:04X} ({description}) is not referenced anywhere in usb/*.kt",
        )
    handle = re.search(r"(?i)0x0*ffffc002(?:L)?", sources)
    check(
        handle is not None,
        "liveview handle 0xFFFFC002",
        "liveview handle 0xFFFFC002 is not referenced in usb/*.kt",
    )
    check(
        "0X9207" in sources.upper() and "stepNotch" in sources,
        "notch path stepNotch() implemented",
        "stepNotch() (0x9207 notch write) not found in usb/*.kt",
    )
    check(
        "0X9205" in sources.upper() and "setAbsolute" in sources,
        "absolute-write path setAbsolute() present but unused by the UI",
        "setAbsolute() (0x9205) not found in usb/*.kt",
    )


# --------------------------------------------------------------------------- 5/6


def check_manifest() -> None:
    print("[4] AndroidManifest.xml")
    path = MAIN / "AndroidManifest.xml"
    if not path.is_file():
        fail("AndroidManifest.xml missing")
        return
    text = path.read_text(encoding="utf-8")
    check(
        "android.hardware.usb.host" in text,
        "uses-feature android.hardware.usb.host",
        "manifest does not declare uses-feature android.hardware.usb.host",
    )
    check(
        re.search(r'android\.hardware\.usb\.host"[^>]*android:required="true"', text, re.S) is not None,
        "usb.host required=true",
        "android.hardware.usb.host is not marked android:required=\"true\"",
    )
    check(
        text.count("android.hardware.usb.action.USB_DEVICE_ATTACHED") >= 2,
        "attach intent filter + meta-data present",
        "manifest needs both the USB_DEVICE_ATTACHED intent filter and the meta-data name",
    )
    check(
        "usb_device_filter" in text,
        "meta-data resource @xml/usb_device_filter",
        "manifest does not point at @xml/usb_device_filter",
    )
    camera_permission = re.search(
        r'<uses-permission[^>]*android:name\s*=\s*"android\.permission\.(CAMERA|CAMERA_[A-Z_]+)"',
        text,
    )
    check(
        camera_permission is None,
        "no CAMERA uses-permission element (not needed)",
        "manifest declares a uses-permission for android.permission.CAMERA, which this client does not use",
    )
    check(
        "android:configChanges" in text and "orientation" in text,
        "configChanges covers orientation (GL surface survives)",
        "manifest activity lacks configChanges with orientation",
    )
    check(
        "MainActivity" in text,
        "MainActivity declared",
        "manifest does not declare MainActivity",
    )


def check_device_filter() -> None:
    print("[5] res/xml/usb_device_filter.xml")
    path = MAIN / "res" / "xml" / "usb_device_filter.xml"
    if not path.is_file():
        fail("usb_device_filter.xml missing")
        return
    text = path.read_text(encoding="utf-8")
    check(
        re.search(r'vendor-id\s*=\s*"1356"', text) is not None,
        "vendor-id 1356 (0x054C)",
        'vendor-id="1356" (0x054C) not found in the device filter',
    )
    for pid, label in ((3242, "0x0CAA"), (802, "0x0322")):
        check(
            re.search(rf'product-id\s*=\s*"{pid}"', text) is not None,
            f"product-id {pid} ({label})",
            f'product-id="{pid}" ({label}) not found in the device filter',
        )


# --------------------------------------------------------------------------- 7


def check_gradle() -> None:
    print("[6] Gradle configuration")
    app_gradle = APP / "build.gradle.kts"
    root_gradle = ROOT / "build.gradle.kts"
    settings = ROOT / "settings.gradle.kts"
    if not app_gradle.is_file() or not root_gradle.is_file() or not settings.is_file():
        fail("gradle files missing")
        return
    text = app_gradle.read_text(encoding="utf-8")
    check(
        'path = file("src/main/cpp/CMakeLists.txt")' in text,
        "externalNativeBuild points at src/main/cpp/CMakeLists.txt",
        'app/build.gradle.kts does not contain: path = file("src/main/cpp/CMakeLists.txt")',
    )
    for pattern, description in (
        (r"compileSdk\s*=\s*34", "compileSdk 34"),
        (r"minSdk\s*=\s*26", "minSdk 26"),
        (r"targetSdk\s*=\s*34", "targetSdk 34"),
        (r"jvmTarget\s*=\s*org\.jetbrains\.kotlin\.gradle\.dsl\.JvmTarget\.JVM_17", "kotlin jvmTarget 17"),
        (r'sourceCompatibility\s*=\s*JavaVersion\.VERSION_17', "java sourceCompatibility 17"),
        (r'targetCompatibility\s*=\s*JavaVersion\.VERSION_17', "java targetCompatibility 17"),
        (r'abiFilters\s*\+=\s*"arm64-v8a"', 'abiFilters += "arm64-v8a"'),
        (r"ndkVersion\s*=\s*pinnedNdkVersion", "ndkVersion = pinnedNdkVersion"),
        (r'"26\.3\.11579264"', 'NDK version string "26.3.11579264"'),
        (r"externalNativeBuild\s*\{", "externalNativeBuild block"),
    ):
        check(
            re.search(pattern, text) is not None,
            description,
            f"app/build.gradle.kts is missing: {description}",
        )
    dependency_lines = [
        line for line in app_gradle.read_text(encoding="utf-8").splitlines()
        if re.search(r"\b(implementation|api|compileOnly|runtimeOnly|kapt|ksp)\s*\(", line)
    ]
    check(
        all("androidx" not in line.lower() for line in dependency_lines),
        "no AndroidX dependency coordinate",
        "an AndroidX dependency coordinate was added to app/build.gradle.kts: "
        + repr(dependency_lines),
    )
    check(
        "android.useAndroidX=false" in (ROOT / "gradle.properties").read_text(encoding="utf-8"),
        "gradle.properties pins android.useAndroidX=false",
        "gradle.properties must keep android.useAndroidX=false so AndroidX cannot creep in",
    )
    check(
        'include(":app")' in settings.read_text(encoding="utf-8"),
        "settings.gradle.kts includes :app",
        'settings.gradle.kts does not contain include(":app")',
    )
    check(
        '"a6400-lived"' in settings.read_text(encoding="utf-8"),
        "rootProject.name set",
        "settings.gradle.kts does not set rootProject.name",
    )


# --------------------------------------------------------------------------- 8


def kotlin_files() -> list[Path]:
    return sorted(KT_ROOT.rglob("*.kt"))


def check_markers() -> None:
    print("[7] no TODO/FIXME/stub markers in shipping Kotlin")
    files = kotlin_files()
    if not files:
        fail("no Kotlin sources found")
        return
    for path in files:
        text = path.read_text(encoding="utf-8")
        matches = FORBIDDEN_MARKERS.findall(text)
        if matches:
            sample = ", ".join(sorted({m.group(0) for m in FORBIDDEN_MARKERS.finditer(text)}))
            fail(f"{path.relative_to(ROOT)} contains a placeholder marker: {sample}")
        else:
            ok(f"{path.relative_to(ROOT)} marker-free")
    check(
        all("import androidx" not in p.read_text(encoding="utf-8") for p in files),
        "no androidx imports in Kotlin",
        "an AndroidX import was found in the Kotlin sources",
    )


# --------------------------------------------------------------------------- 9


def check_braces() -> None:
    print("[8] brace balance per Kotlin file")
    files = kotlin_files()
    if not files:
        fail("no Kotlin sources found")
        return
    for path in files:
        depth, underflow = brace_balance(path)
        relative = path.relative_to(ROOT)
        if underflow:
            fail(f"{relative}: closing brace without an opener around line {underflow}")
        elif depth != 0:
            fail(f"{relative}: {depth} unclosed '{{' at end of file")
        else:
            ok(f"{relative}: balanced")


# -------------------------------------------------------------------------- 10


def check_docs() -> None:
    print("[9] documentation invariants")
    readme = (ROOT / "README.md").read_text(encoding="utf-8")
    protocol = (ROOT / "docs" / "PROTOCOL.md").read_text(encoding="utf-8")
    verification = (ROOT / "docs" / "VERIFICATION.md").read_text(encoding="utf-8")
    documents = (
        (readme, "README.md"),
        (protocol, "docs/PROTOCOL.md"),
        (verification, "docs/VERIFICATION.md"),
    )
    for text, name in documents:
        check(
            "UNVERIFIED" in text.upper(),
            f"{name}: verified/unverified split stated",
            f"{name} never mentions UNVERIFIED",
        )
    check(
        "0x9205" in protocol and re.search(r"not effective|NOT effective|ineffective", protocol) is not None,
        "PROTOCOL.md states that 0x9205 absolute writes are not effective",
        "PROTOCOL.md must warn that 0x9205 absolute writes are acknowledged but not effective",
    )
    check(
        re.search(r"not\s+compiled", verification, re.IGNORECASE) is not None,
        "VERIFICATION.md records that the Kotlin was not compiled",
        "VERIFICATION.md must state that no Kotlin was compiled (no SDK in this environment)",
    )
    check(
        re.search(r"1181", verification) is not None,
        "VERIFICATION.md records the 1181-test baseline",
        "VERIFICATION.md must record the 1181-test repository baseline",
    )
    check(
        "libjpeg-turbo" in readme,
        "README.md documents how to vendor libjpeg-turbo",
        "README.md must document vendoring libjpeg-turbo under app/src/main/cpp/third_party",
    )
    check(
        "third_party/libjpeg-turbo" in readme,
        "README.md names the exact libjpeg-turbo path",
        "README.md must name app/src/main/cpp/third_party/libjpeg-turbo",
    )
    check(
        "0x9207" in protocol and "0x9209" in protocol and "1730" in protocol,
        "PROTOCOL.md documents 0x9207, 0x9209 and the 1730-byte blob",
        "PROTOCOL.md must document the notch opcode, the property read and the 1730-byte blob",
    )
    check(
        "0x81" in protocol and "0x83" in protocol and "0x84" in protocol,
        "PROTOCOL.md documents the bulk/interrupt endpoints",
        "PROTOCOL.md must document endpoints 0x81/0x83/0x84",
    )
    check(
        "SET_CUR" in protocol and "PROBE" in protocol.upper() and "COMMIT" in protocol.upper(),
        "PROTOCOL.md documents the UVC PROBE/COMMIT sequence",
        "PROTOCOL.md must document the UVC SET_CUR/GET_CUR PROBE and COMMIT sequence",
    )


def main() -> int:
    print(f"verify_structure: {ROOT}")
    print()
    check_required_files()
    check_jni()
    check_ptp_tokens()
    check_manifest()
    check_device_filter()
    check_gradle()
    check_markers()
    check_braces()
    check_docs()
    print()
    if failures:
        print(f"FAILED: {len(failures)} of {checks} checks")
        for message in failures:
            print(f"  - {message}")
        return 1
    print(f"PASS: all {checks} checks")
    return 0


if __name__ == "__main__":
    sys.exit(main())
