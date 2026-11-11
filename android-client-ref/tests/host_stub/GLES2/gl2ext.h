#pragma once

#ifndef A6400_HOST_COMPILE
#error "compile-only host stub included without -DA6400_HOST_COMPILE"
#endif

// COMPILE-ONLY HOST STUB -- NOT AN ANDROID HEADER.
// Only the OES_EGL_image_external entry point used by AhbPool is declared.

#include <GLES3/gl32.h>

typedef void* GLeglImageOES;

#ifndef GL_TEXTURE_EXTERNAL_OES
#define GL_TEXTURE_EXTERNAL_OES 0x8D65
#endif
#ifndef GL_TEXTURE_BINDING_EXTERNAL_OES
#define GL_TEXTURE_BINDING_EXTERNAL_OES 0x8D67
#endif
#ifndef GL_REQUIRED_TEXTURE_IMAGE_UNITS_OES
#define GL_REQUIRED_TEXTURE_IMAGE_UNITS_OES 0x8D68
#endif

static inline void glEGLImageTargetTexture2DOES(GLenum, GLeglImageOES) {}
