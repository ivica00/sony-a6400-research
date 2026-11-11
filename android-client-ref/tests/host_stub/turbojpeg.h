#pragma once

#ifndef A6400_HOST_COMPILE
#error "compile-only host stub included without -DA6400_HOST_COMPILE"
#endif

// COMPILE-ONLY HOST STUB -- NOT libjpeg-turbo.
// The implementation in turbojpeg_stub.cpp parses only SOF dimensions and
// fills a deterministic RGBA pattern; it does not decode entropy data.  The
// real shipping build links the vendored libjpeg-turbo instead.

#include <cstddef>

typedef void* tjhandle;

#define TJPF_RGBA 3
#define TJFLAG_FASTDCT 2048

#ifdef __cplusplus
extern "C" {
#endif

tjhandle tjInitDecompress(void);
int tjDestroy(tjhandle handle);
int tjDecompressHeader3(tjhandle handle, const unsigned char* jpegBuf,
                        unsigned long jpegSize, int* width, int* height,
                        int* jpegSubsamp, int* jpegColorspace);
int tjDecompress2(tjhandle handle, const unsigned char* jpegBuf,
                  unsigned long jpegSize, unsigned char* dstBuf,
                  int width, int pitch, int height, int pixelFormat, int flags);
char* tjGetErrorStr2(tjhandle handle);
int tjGetErrorCode(tjhandle handle);

#ifdef __cplusplus
}
#endif
