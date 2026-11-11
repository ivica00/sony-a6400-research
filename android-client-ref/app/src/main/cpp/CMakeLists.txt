# a6400lived -- native half of the ILCE-6400 low-latency live-view client.
#
# This library deliberately has no third-party dependency except libjpeg-turbo
# (turbojpeg API).  EGL, GLESv3, AHardwareBuffer, log, jnigraphics and JNI are
# platform libraries supplied by the NDK / Android.
#
# libjpeg-turbo is NOT vendored in this repository.  Build it for arm64-v8a and
# install it under:
#
#   android-client-ref/third_party/libjpeg-turbo/
#       include/turbojpeg.h
#       lib/libturbojpeg.a          (or libturbojpeg.so)
#
# A CMake build of libjpeg-turbo with -DWITH_TURBOJPEG=ON -DCMAKE_TOOLCHAIN_FILE=
# $NDK/build/cmake/android.toolchain.cmake -DANDROID_ABI=arm64-v8a is enough.
# The fatal error below repeats the instruction so a missing vendor tree is not
# mistaken for an NDK problem.

cmake_minimum_required(VERSION 3.22)
project(a6400lived LANGUAGES CXX)

set(CMAKE_CXX_STANDARD 17)
set(CMAKE_CXX_STANDARD_REQUIRED ON)
set(CMAKE_CXX_EXTENSIONS OFF)

# The consumer (app/build.gradle.kts) already restricts abiFilters to arm64-v8a.
# Keep a second, explicit guard here so a host-side or desktop CMake invocation
# cannot quietly produce a 32-bit library with different JNI/NEON behaviour.
if(ANDROID_ABI AND NOT ANDROID_ABI STREQUAL "arm64-v8a")
    message(FATAL_ERROR
        "a6400lived supports arm64-v8a only; ANDROID_ABI=${ANDROID_ABI} was requested.")
endif()
if(NOT ANDROID_ABI)
    set(ANDROID_ABI "arm64-v8a" CACHE STRING "Target Android ABI" FORCE)
endif()

if(TURBOJPEG_ROOT)
    set(A6400_TURBOJPEG_ROOT "${TURBOJPEG_ROOT}")
else()
    set(A6400_TURBOJPEG_ROOT
        "${CMAKE_CURRENT_SOURCE_DIR}/../../../../third_party/libjpeg-turbo")
endif()

find_library(turbojpeg-lib
    NAMES turbojpeg
    HINTS
        "${A6400_TURBOJPEG_ROOT}/lib"
        "${A6400_TURBOJPEG_ROOT}"
        "${CMAKE_CURRENT_SOURCE_DIR}/../../../../third_party/libjpeg-turbo/lib"
)

if(NOT turbojpeg-lib)
    message(FATAL_ERROR
        "libjpeg-turbo (turbojpeg) was not found.\n"
        "Vendor it under android-client-ref/third_party/libjpeg-turbo/ with\n"
        "  include/turbojpeg.h\n"
        "  lib/libturbojpeg.a  (or libturbojpeg.so)\n"
        "and rebuild.  This project does not download or embed libjpeg-turbo.\n"
        "If your tree lives elsewhere, pass -DTURBOJPEG_ROOT=<path> (the finder\n"
        "above remains the canonical location).")
endif()

find_path(turbojpeg-include
    NAMES turbojpeg.h
    HINTS
        "${A6400_TURBOJPEG_ROOT}/include"
        "${A6400_TURBOJPEG_ROOT}"
)
if(NOT turbojpeg-include)
    message(FATAL_ERROR
        "turbojpeg.h was not found next to the libjpeg-turbo library.\n"
        "Expected android-client-ref/third_party/libjpeg-turbo/include/turbojpeg.h.")
endif()

# Embed the two GLSL files at configure time.  Keeping the shipping shader in a
# real .glsl file makes the static validator and code review honest; the raw
# string literal avoids an asset manager and keeps the .so self-contained.
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/shaders/sgsr1_fragment.glsl" SGSR1_FRAGMENT)
file(READ "${CMAKE_CURRENT_SOURCE_DIR}/shaders/passthrough_vertex.glsl" PASSTHROUGH_VERTEX)
set(A6400_GENERATED_DIR "${CMAKE_CURRENT_BINARY_DIR}/generated")
file(MAKE_DIRECTORY "${A6400_GENERATED_DIR}")
configure_file(
    "${CMAKE_CURRENT_SOURCE_DIR}/shaders_embed.h.in"
    "${A6400_GENERATED_DIR}/shaders_embed.h"
    @ONLY)

add_library(a6400lived SHARED
    jni_bridge.cpp
    pipeline.cpp
    jpeg_decoder.cpp
    ahardware_buffer_pool.cpp
    gl_renderer.cpp
    uvc_frame_parser.cpp
    shaders/sgsr1_fragment.glsl
    shaders/passthrough_vertex.glsl
)

target_include_directories(a6400lived PRIVATE
    "${CMAKE_CURRENT_SOURCE_DIR}"
    "${A6400_GENERATED_DIR}"
    "${turbojpeg-include}"
)

# -O2 and -ffast-math are acceptable here because the decoder output is
# validated by libjpeg-turbo and the shader is compiled by the GPU driver, not
# by this translation unit.  No LTO assumption is made.
target_compile_options(a6400lived PRIVATE
    -O2
    -ffast-math
    -Wall
    -Wextra
)

# The app's externalNativeBuild already passes -fno-exceptions -fno-rtti.  Do not
# override that here: this library contains no C++ throw/catch and no RTTI use.
target_link_libraries(a6400lived PRIVATE
    ${turbojpeg-lib}
    jnigraphics
    log
    android
    EGL
    GLESv3
    m
)
