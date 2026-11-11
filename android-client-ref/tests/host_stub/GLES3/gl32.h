#pragma once

#ifndef A6400_HOST_COMPILE
#error "compile-only host stub included without -DA6400_HOST_COMPILE"
#endif

// COMPILE-ONLY HOST STUB -- NOT AN ANDROID HEADER.
// These are no-op/failing shims sufficient to link the portable pipeline.  The
// host test never reaches a successful GL initialisation.

#include <cstddef>
#include <cstdint>

typedef unsigned int GLenum;
typedef unsigned char GLboolean;
typedef unsigned int GLbitfield;
typedef int GLint;
typedef int GLsizei;
typedef unsigned int GLuint;
typedef unsigned char GLubyte;
typedef char GLchar;
typedef std::ptrdiff_t GLintptr;
typedef std::ptrdiff_t GLsizeiptr;
typedef struct __GLsync* GLsync;

enum {
    GL_FALSE = 0,
    GL_TRUE = 1,
    GL_NO_ERROR = 0,
    GL_TRIANGLES = 0x0004,
    GL_DEPTH_TEST = 0x0B71,
    GL_CULL_FACE = 0x0B44,
    GL_BLEND = 0x0BE2,
    GL_DITHER = 0x0BD0,
    GL_SCISSOR_TEST = 0x0C11,
    GL_TEXTURE_2D = 0x0DE1,
    GL_UNSIGNED_BYTE = 0x1401,
    GL_RGBA = 0x1908,
    GL_VERSION = 0x1F02,
    GL_RENDERER = 0x1F01,
    GL_LINEAR = 0x2601,
    GL_TEXTURE_MAG_FILTER = 0x2800,
    GL_TEXTURE_MIN_FILTER = 0x2801,
    GL_TEXTURE_WRAP_S = 0x2802,
    GL_TEXTURE_WRAP_T = 0x2803,
    GL_COLOR_BUFFER_BIT = 0x00004000,
    GL_RGBA8 = 0x8058,
    GL_CLAMP_TO_EDGE = 0x812F,
    GL_TEXTURE0 = 0x84C0,
    GL_ARRAY_BUFFER = 0x8892,
    GL_ELEMENT_ARRAY_BUFFER = 0x8893,
    GL_FRAGMENT_SHADER = 0x8B30,
    GL_VERTEX_SHADER = 0x8B31,
    GL_COMPILE_STATUS = 0x8B81,
    GL_LINK_STATUS = 0x8B82,
    GL_INFO_LOG_LENGTH = 0x8B84,
    GL_UNPACK_ALIGNMENT = 0x0CF5,
    GL_UNPACK_ROW_LENGTH = 0x0CF2,
    GL_TEXTURE_EXTERNAL_OES = 0x8D65,
    GL_SYNC_GPU_COMMANDS_COMPLETE = 0x9117,
    GL_SYNC_FLUSH_COMMANDS_BIT = 0x00000001,
    GL_ALREADY_SIGNALED = 0x911A,
    GL_TIMEOUT_EXPIRED = 0x911B,
    GL_CONDITION_SATISFIED = 0x911C,
    GL_WAIT_FAILED = 0x911D
};

static inline GLenum glGetError(void) { return GL_NO_ERROR; }
static inline const GLubyte* glGetString(GLenum) { return nullptr; }
static inline void glViewport(GLint, GLint, GLsizei, GLsizei) {}
static inline void glClearColor(float, float, float, float) {}
static inline void glClear(GLbitfield) {}
static inline void glDisable(GLenum) {}
static inline void glEnable(GLenum) {}
static inline void glPixelStorei(GLenum, GLint) {}
static inline void glActiveTexture(GLenum) {}
static inline void glBindTexture(GLenum, GLuint) {}
static inline void glGenTextures(GLsizei n, GLuint* textures)
{
    for (GLsizei i = 0; i < n; ++i) {
        textures[i] = 0;
    }
}
static inline void glDeleteTextures(GLsizei, const GLuint*) {}
static inline void glTexParameteri(GLenum, GLenum, GLint) {}
static inline void glTexImage2D(GLenum, GLint, GLint, GLsizei, GLsizei, GLint,
                                GLenum, GLenum, const void*) {}
static inline void glTexSubImage2D(GLenum, GLint, GLint, GLint, GLsizei, GLsizei,
                                   GLenum, GLenum, const void*) {}
static inline GLuint glCreateShader(GLenum) { return 1; }
static inline void glShaderSource(GLuint, GLsizei, const GLchar* const*, const GLint*) {}
static inline void glCompileShader(GLuint) {}
static inline void glGetShaderiv(GLuint, GLenum, GLint* value) { *value = 0; }
static inline void glGetShaderInfoLog(GLuint, GLsizei, GLsizei*, GLchar*) {}
static inline void glDeleteShader(GLuint) {}
static inline GLuint glCreateProgram(void) { return 2; }
static inline void glAttachShader(GLuint, GLuint) {}
static inline void glDetachShader(GLuint, GLuint) {}
static inline void glLinkProgram(GLuint) {}
static inline void glGetProgramiv(GLuint, GLenum, GLint* value) { *value = 0; }
static inline void glGetProgramInfoLog(GLuint, GLsizei, GLsizei*, GLchar*) {}
static inline void glDeleteProgram(GLuint) {}
static inline void glUseProgram(GLuint) {}
static inline GLint glGetUniformLocation(GLuint, const GLchar*) { return -1; }
static inline void glUniform1i(GLint, GLint) {}
static inline void glUniform1f(GLint, float) {}
static inline void glUniform2f(GLint, float, float) {}
static inline void glGenVertexArrays(GLsizei n, GLuint* arrays)
{
    for (GLsizei i = 0; i < n; ++i) {
        arrays[i] = 0;
    }
}
static inline void glBindVertexArray(GLuint) {}
static inline void glDeleteVertexArrays(GLsizei, const GLuint*) {}
static inline void glDrawArrays(GLenum, GLint, GLsizei) {}
static inline GLsync glFenceSync(GLenum, GLbitfield) { return nullptr; }
static inline GLenum glClientWaitSync(GLsync, GLbitfield, uint64_t) { return GL_TIMEOUT_EXPIRED; }
static inline void glDeleteSync(GLsync) {}
static inline void glFinish(void) {}
