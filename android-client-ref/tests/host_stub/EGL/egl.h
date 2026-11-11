#pragma once

#ifndef A6400_HOST_COMPILE
#error "compile-only host stub included without -DA6400_HOST_COMPILE"
#endif

// COMPILE-ONLY HOST STUB -- NOT AN ANDROID HEADER.
// No EGL implementation exists on the host.  eglGetCurrentContext() returns
// EGL_NO_CONTEXT so the pipeline takes its documented no-GL error path.

#include <cstdint>

typedef void* EGLDisplay;
typedef void* EGLContext;
typedef void* EGLConfig;
typedef void* EGLSurface;
typedef void* EGLImageKHR;
typedef void* EGLClientBuffer;
typedef int EGLint;
typedef unsigned int EGLBoolean;
typedef unsigned int EGLenum;

#define EGL_NO_DISPLAY ((EGLDisplay)0)
#define EGL_NO_CONTEXT ((EGLContext)0)
#define EGL_NO_SURFACE ((EGLSurface)0)
#define EGL_NO_IMAGE_KHR ((EGLImageKHR)0)
#define EGL_NATIVE_BUFFER_ANDROID 0x3140

static inline EGLDisplay eglGetCurrentDisplay(void)
{
    return EGL_NO_DISPLAY;
}

static inline EGLContext eglGetCurrentContext(void)
{
    return EGL_NO_CONTEXT;
}

static inline EGLImageKHR eglCreateImageKHR(EGLDisplay, EGLContext, EGLenum,
                                            EGLClientBuffer, const EGLint*)
{
    return EGL_NO_IMAGE_KHR;
}

static inline EGLBoolean eglDestroyImageKHR(EGLDisplay, EGLImageKHR)
{
    return 0;
}
