#pragma once

// EGL/GLES entry points.  On Android these come from the NDK platform headers;
// on the host they come from tests/host_stub (compile-only fakes).  The
// prototypes for the KHR/EXT functions used here need the *PROTOTYPES macros.
#ifndef EGL_EGLEXT_PROTOTYPES
#define EGL_EGLEXT_PROTOTYPES 1
#endif
#ifndef GL_GLEXT_PROTOTYPES
#define GL_GLEXT_PROTOTYPES 1
#endif

#ifdef A6400_HOST_COMPILE
// Host-only stubs live under tests/host_stub and are found via -I.  Shipping
// builds never see that directory.
#include <EGL/egl.h>
#include <GLES3/gl32.h>
#include <GLES2/gl2ext.h>
#else
#include <EGL/egl.h>
#include <EGL/eglext.h>
#include <GLES3/gl32.h>
#include <GLES2/gl2ext.h>
#endif
