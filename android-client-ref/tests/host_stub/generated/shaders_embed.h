#pragma once

#ifndef A6400_HOST_COMPILE
#error "compile-only host stub included without -DA6400_HOST_COMPILE"
#endif

// COMPILE-ONLY HOST STUB -- NOT THE GENERATED SHADER HEADER.
// gl_renderer.cpp needs these symbols to link on the host.  They are never
// compiled by a driver because the host has no EGL context.

static const char kA6400PassthroughVertex[] =
    "#version 320 es\nprecision highp float;\nout highp vec2 vUv;\n"
    "void main(){ vec2 p=vec2((gl_VertexID==1)?3.0:-1.0,(gl_VertexID==2)?3.0:-1.0);"
    "vUv=p*0.5+0.5; gl_Position=vec4(p,0.0,1.0); }\n";

static const char kA6400Sgsr1Fragment[] =
    "#version 320 es\nprecision mediump float;\n"
    "uniform mediump sampler2D uSrcTexture;\nuniform highp vec2 uSrcSize;\n"
    "uniform highp vec2 uSrcTextureSize;\nuniform highp vec2 uDstSize;\n"
    "uniform mediump float uSharpness;\nuniform mediump float uExposure;\n"
    "uniform mediump float uPeakingIntensity;\nin highp vec2 vUv;\n"
    "out mediump vec4 fragColor;\n"
    "void main(){ fragColor=texture(uSrcTexture,vUv); }\n";
