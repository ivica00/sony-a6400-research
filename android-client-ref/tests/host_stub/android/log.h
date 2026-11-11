#pragma once

#ifndef A6400_HOST_COMPILE
#error "compile-only host stub included without -DA6400_HOST_COMPILE"
#endif

// COMPILE-ONLY HOST STUB -- NOT AN ANDROID HEADER.
// The host build routes logging through cpp/log.h to stderr; this header only
// exists so a translation unit that includes <android/log.h> can still compile.

enum android_LogPriority {
    ANDROID_LOG_UNKNOWN = 0,
    ANDROID_LOG_DEFAULT = 1,
    ANDROID_LOG_VERBOSE = 2,
    ANDROID_LOG_DEBUG = 3,
    ANDROID_LOG_INFO = 4,
    ANDROID_LOG_WARN = 5,
    ANDROID_LOG_ERROR = 6,
    ANDROID_LOG_FATAL = 7,
    ANDROID_LOG_SILENT = 8
};

static inline int __android_log_print(int, const char*, const char*, ...)
{
    return 0;
}
