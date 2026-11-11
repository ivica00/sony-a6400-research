#pragma once

#ifndef A6400_HOST_COMPILE
#error "compile-only host stub included without -DA6400_HOST_COMPILE"
#endif

// COMPILE-ONLY HOST STUB -- NOT AN ANDROID HEADER.
// The shipping pipeline does not use Bitmap; this stub is present because the
// task asked for the complete minimal host-header set.

#include <jni.h>

#include <cstdint>

typedef struct AndroidBitmapInfo {
    uint32_t width;
    uint32_t height;
    uint32_t stride;
    int32_t format;
    uint32_t flags;
} AndroidBitmapInfo;

enum {
    ANDROID_BITMAP_FORMAT_NONE = 0,
    ANDROID_BITMAP_FORMAT_RGBA_8888 = 1
};

static inline int AndroidBitmap_getInfo(JNIEnv*, jobject, AndroidBitmapInfo*)
{
    return -1;
}