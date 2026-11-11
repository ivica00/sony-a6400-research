#!/usr/bin/env bash
# Offline host compile + assertion harness for the portable a6400lived sources.
#
# This is NOT an Android build.  It compiles the JNI handle/lifecycle logic,
# the JPEG validation/decoder seam, the AHardwareBuffer fallback, the renderer
# glue and the UVC parser against tests/host_stub.  GL and turbojpeg are
# compile-only fakes; no frame is rendered and no GPU is touched.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT="$(cd "${HERE}/.." && pwd)"
CPP="${ROOT}/app/src/main/cpp"
STUB="${HERE}/host_stub"
BUILD="${TMPDIR:-/tmp}/a6400-host-tests-$$"
mkdir -p "${BUILD}"
trap 'rm -rf "${BUILD}"' EXIT

CXX="${CXX:-g++}"
HOST_EXE="${BUILD}/host_main.exe"

# -Wall -Wextra -Werror: the portable half is required to be warning-free.
# The include order puts the host stubs first so <jni.h>, <android/...>,
# <EGL/egl.h>, <GLES3/gl32.h> and <turbojpeg.h> resolve to the fakes.
"${CXX}" -std=c++17 -Wall -Wextra -Werror \
    -DA6400_HOST_COMPILE \
    -I"${STUB}" \
    -I"${STUB}/generated" \
    -I"${CPP}" \
    "${CPP}/jni_bridge.cpp" \
    "${CPP}/pipeline.cpp" \
    "${CPP}/jpeg_decoder.cpp" \
    "${CPP}/ahardware_buffer_pool.cpp" \
    "${CPP}/gl_renderer.cpp" \
    "${CPP}/uvc_frame_parser.cpp" \
    "${STUB}/turbojpeg_stub.cpp" \
    "${HERE}/host_main.cpp" \
    -o "${HOST_EXE}"

"${HOST_EXE}"
