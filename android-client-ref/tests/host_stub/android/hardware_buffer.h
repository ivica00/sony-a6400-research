#pragma once

#ifndef A6400_HOST_COMPILE
#error "compile-only host stub included without -DA6400_HOST_COMPILE"
#endif

// COMPILE-ONLY HOST STUB -- NOT AN ANDROID HEADER.
// AHardwareBuffer does not exist on the host.  allocate() always fails so the
// pipeline exercises its CPU-RGBA fallback during host tests.

#include <cstdint>

typedef struct AHardwareBuffer AHardwareBuffer;

typedef struct AHardwareBuffer_Desc {
    uint32_t width;
    uint32_t height;
    uint32_t layers;
    uint32_t format;
    uint64_t usage;
    uint32_t stride;
    uint32_t rfu0;
    uint64_t rfu1;
} AHardwareBuffer_Desc;

typedef struct ARect {
    int32_t left;
    int32_t top;
    int32_t right;
    int32_t bottom;
} ARect;

enum {
    AHARDWAREBUFFER_FORMAT_R8G8B8A8_UNORM = 1
};

enum {
    AHARDWAREBUFFER_USAGE_CPU_READ_OFTEN = 1ULL << 1,
    AHARDWAREBUFFER_USAGE_CPU_WRITE_OFTEN = 1ULL << 2,
    AHARDWAREBUFFER_USAGE_GPU_SAMPLED_IMAGE = 1ULL << 8
};

inline int AHardwareBuffer_allocate(const AHardwareBuffer_Desc*, AHardwareBuffer** out)
{
    if (out != nullptr) {
        *out = nullptr;
    }
    return -1;
}

inline void AHardwareBuffer_release(AHardwareBuffer*)
{
}

inline int AHardwareBuffer_lock(AHardwareBuffer*, uint64_t, int32_t, const ARect*, void** out)
{
    if (out != nullptr) {
        *out = nullptr;
    }
    return -1;
}

inline int AHardwareBuffer_unlock(AHardwareBuffer*, int32_t*)
{
    return -1;
}

inline void AHardwareBuffer_describe(const AHardwareBuffer*, AHardwareBuffer_Desc* out)
{
    if (out != nullptr) {
        *out = AHardwareBuffer_Desc{};
    }
}
