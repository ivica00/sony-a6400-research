#pragma once

#ifndef A6400_HOST_COMPILE
#error "compile-only host stub included without -DA6400_HOST_COMPILE"
#endif

// COMPILE-ONLY HOST STUB -- NOT AN ANDROID HEADER.
// Shipping sources include the real <jni.h> from the NDK.  This file exists
// only so tests/host_compile.sh can type-check the JNI adapter without a JDK
// or Android SDK.  No JVM is present and none of these functions are called by
// the host test.

#include <cstdint>

typedef int8_t jbyte;
typedef int32_t jint;
typedef int64_t jlong;
typedef float jfloat;
typedef unsigned char jboolean;
typedef int32_t jsize;

struct _jobject;
typedef _jobject* jobject;
typedef _jobject* jclass;
typedef _jobject* jarray;
typedef jarray jbyteArray;
typedef jarray jlongArray;

#define JNIEXPORT __attribute__((visibility("default")))
#define JNICALL
#define JNI_ABORT 2
#define JNI_VERSION_1_6 0x00010006

struct JNINativeMethod {
    char* name;
    char* signature;
    void* fnPtr;
};

struct JavaVM {
    jint GetEnv(void** env, jint version)
    {
        (void)env;
        (void)version;
        return -1;
    }
};

struct JNIEnv {
    jsize GetArrayLength(jarray)
    {
        return 0;
    }
    void* GetPrimitiveArrayCritical(jarray, jboolean*)
    {
        return nullptr;
    }
    void ReleasePrimitiveArrayCritical(jarray, void*, jint)
    {
    }
    void SetLongArrayRegion(jlongArray, jsize, jsize, const jlong*)
    {
    }
    jclass FindClass(const char*)
    {
        return nullptr;
    }
    jint RegisterNatives(jclass, const JNINativeMethod*, jint)
    {
        return -1;
    }
    jboolean ExceptionCheck()
    {
        return 0;
    }
    void ExceptionClear()
    {
    }
    void DeleteLocalRef(jobject)
    {
    }
};
