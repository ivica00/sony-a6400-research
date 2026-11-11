#pragma once

// One logging seam for Android and for the offline host compile.  The host
// branch intentionally writes to stderr; it is not a shipped logging path.
#ifdef A6400_HOST_COMPILE
#include <cstdio>
#define A6400_LOGE(...) do { std::fprintf(stderr, "E/a6400lived: " __VA_ARGS__); std::fputc('\n', stderr); } while (0)
#define A6400_LOGW(...) do { std::fprintf(stderr, "W/a6400lived: " __VA_ARGS__); std::fputc('\n', stderr); } while (0)
#define A6400_LOGI(...) do { std::fprintf(stderr, "I/a6400lived: " __VA_ARGS__); std::fputc('\n', stderr); } while (0)
#else
#include <android/log.h>
#define A6400_LOGE(...) __android_log_print(ANDROID_LOG_ERROR, "a6400lived", __VA_ARGS__)
#define A6400_LOGW(...) __android_log_print(ANDROID_LOG_WARN,  "a6400lived", __VA_ARGS__)
#define A6400_LOGI(...) __android_log_print(ANDROID_LOG_INFO,  "a6400lived", __VA_ARGS__)
#endif
