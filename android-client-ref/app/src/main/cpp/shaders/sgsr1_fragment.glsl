#version 320 es
//
// a6400lived spatial upscaler, "SGSR-1.0-class" (single pass, spatial only).
//
// This is NOT Qualcomm's proprietary Snapdragon Game Super Resolution 2.0 and
// it is not the temporal SGSR algorithm.  It is an independent, single-pass
// spatial design in the same class as FSR 1.0 EASU+RCAS:
//   * a 12-tap directional edge estimate (EASU-like), then
//   * a 5-tap contrast-adaptive sharpen with a lobe-ratio clamp (RCAS-like).
//
// Algorithmic inspiration and attribution:
//   AMD FidelityFX Super Resolution 1.0 (FSR 1.0), Copyright (c) 2022 Advanced
//   Micro Devices, Inc., MIT License.  No AMD source code is copied here; the
//   EASU/RCAS *structure* is reimplemented from the public algorithm
//   description for this project.  See cpp/README.md for the full notice.
//
// Adreno 750 / GMEM notes:
//   * all reads are source-texture reads in one pass; there is no dependent
//     texture feedback across passes and no render-target readback;
//   * no discard, no derivative-based branching, no branching on sampled data;
//   * total texture fetches: 12 (edge estimate) + 5 (sharpen) = 17, fixed.
//
// Two compile-time variants are produced by gl_renderer.cpp:
//   A6400_EXTERNAL_TEXTURE : AHardwareBuffer EGLImage -> samplerExternalOES
//   PEAKING                : focus-peaking tint (uPeakingIntensity)
//   A6400_BILINEAR         : plain bilinear fallback used by mode 0
//
#ifdef A6400_EXTERNAL_TEXTURE
#extension GL_OES_EGL_image_external_essl3 : require
#endif

precision mediump float;

#ifdef A6400_EXTERNAL_TEXTURE
uniform mediump samplerExternalOES uSrcTexture;
#else
uniform mediump sampler2D uSrcTexture;
#endif

// uSrcSize is the active JPEG size (1024x680 or 1280x720).  uSrcTextureSize is
// the allocated texture / AHardwareBuffer size (1280x720); keeping them
// separate lets a smaller JPEG occupy the top-left of a max-sized allocation
// without reallocating textures on every camera mode change.
uniform highp vec2 uSrcSize;
uniform highp vec2 uSrcTextureSize;
uniform highp vec2 uDstSize;
uniform mediump float uSharpness;        // 0.0 .. 1.0
uniform mediump float uExposure;         // optional, normally 1.0
uniform mediump float uPeakingIntensity; // 0.0 .. 1.0, PEAKING variant only

in highp vec2 vUv;
out mediump vec4 fragColor;

#ifndef A6400_BILINEAR

mediump float luma(mediump vec3 c)
{
    return dot(c, vec3(0.2126, 0.7152, 0.0722));
}

// 4-tap cubic windowed-sinc approximation with support 2 (Catmull-Rom
// kernel).  It has the same pass-band/negative-lobe character as Lanczos2 but
// needs no sin() calls: on Adreno 750 the trig form costs 24 transcendentals
// per pixel, which is not acceptable at 2670x1200.  This is evaluated on a
// computed coordinate, never on a texture lookup.
mediump float lanczosLike(mediump float x)
{
    x = abs(x);
    if (x >= 2.0) {
        return 0.0;
    }
    if (x < 1.0) {
        return ((1.5 * x - 2.5) * x) * x + 1.0;
    }
    return (((-0.5 * x + 2.5) * x) - 4.0) * x + 2.0;
}

void main()
{
    highp vec2 srcSize = max(uSrcSize, vec2(1.0));
    highp vec2 texSize = max(uSrcTextureSize, vec2(1.0));
    highp vec2 dstSize = max(uDstSize, vec2(1.0));
    highp vec2 uvScale = srcSize / texSize;
    highp vec2 texel = 1.0 / texSize;

    // Continuous source-pixel coordinate.  baseUv is the centre of the source
    // texel containing the output sample; f is the sub-texel phase.
    highp vec2 p = vUv * srcSize - 0.5;
    highp vec2 base = floor(p);
    highp vec2 f = p - base;
    highp vec2 baseUv = (base + 0.5) * texel;

    // ---------------------------------------------------------------------
    // 12-tap directional edge estimate (EASU-like).
    //
    // The twelve fetches form a directional cross: four horizontal samples,
    // four vertical samples sharing the centre, four down-right samples
    // sharing the centre, and two anti-diagonal samples.  Every fetched value
    // participates in at least one gradient or in the edge clamp.
    // ---------------------------------------------------------------------
    mediump vec3 c  = texture(uSrcTexture, baseUv).rgb;
    mediump vec3 h0 = texture(uSrcTexture, baseUv + vec2(-texel.x, 0.0)).rgb;
    mediump vec3 h1 = texture(uSrcTexture, baseUv + vec2( texel.x, 0.0)).rgb;
    mediump vec3 h2 = texture(uSrcTexture, baseUv + vec2( 2.0 * texel.x, 0.0)).rgb;
    mediump vec3 v0 = texture(uSrcTexture, baseUv + vec2(0.0, -texel.y)).rgb;
    mediump vec3 v1 = texture(uSrcTexture, baseUv + vec2(0.0,  texel.y)).rgb;
    mediump vec3 v2 = texture(uSrcTexture, baseUv + vec2(0.0,  2.0 * texel.y)).rgb;
    mediump vec3 d0 = texture(uSrcTexture, baseUv + vec2(-texel.x, -texel.y)).rgb;
    mediump vec3 d1 = texture(uSrcTexture, baseUv + vec2( texel.x,  texel.y)).rgb;
    mediump vec3 d2 = texture(uSrcTexture, baseUv + vec2( 2.0 * texel.x, 2.0 * texel.y)).rgb;
    mediump vec3 a0 = texture(uSrcTexture, baseUv + vec2( texel.x, -texel.y)).rgb;
    mediump vec3 a1 = texture(uSrcTexture, baseUv + vec2(-texel.x,  texel.y)).rgb;

    mediump float lc  = luma(c);
    mediump float lh0 = luma(h0);
    mediump float lh1 = luma(h1);
    mediump float lh2 = luma(h2);
    mediump float lv0 = luma(v0);
    mediump float lv1 = luma(v1);
    mediump float lv2 = luma(v2);
    mediump float ld0 = luma(d0);
    mediump float ld1 = luma(d1);
    mediump float ld2 = luma(d2);
    mediump float la0 = luma(a0);
    mediump float la1 = luma(a1);

    // First differences along the four candidate directions.  Small values
    // mean the signal varies slowly along that direction (the edge tangent).
    mediump float gx = abs(lh0 - lc) + abs(lc - lh1) + abs(lh1 - lh2);
    mediump float gy = abs(lv0 - lc) + abs(lc - lv1) + abs(lv1 - lv2);
    mediump float gd = abs(ld0 - lc) + abs(lc - ld1) + abs(ld1 - ld2);
    mediump float ga = abs(la0 - lc) + abs(lc - la1) + abs(la0 - la1);

    // Inverse-gradient mixing.  A high gradient across a direction suppresses
    // interpolation across the edge; the tangent direction wins.
    mediump float wx = 1.0 / (gx + 0.015);
    mediump float wy = 1.0 / (gy + 0.015);
    mediump float wd = 1.0 / (gd + 0.015);
    mediump float wsum = wx + wy + wd;
    mediump vec3 mixw = vec3(wx, wy, wd) / wsum;

    // The anti-diagonal has no fourth output tap, so it cannot be a direction
    // on its own.  When it dominates, split the down-right weight between the
    // horizontal and vertical results instead of losing energy.
    mediump float anti = clamp((ga - max(gx, gy)) / (ga + max(gx, gy) + 0.02),
                               0.0, 1.0);
    mixw.x += anti * mixw.z * 0.5;
    mixw.y += anti * mixw.z * 0.5;
    mixw.z *= (1.0 - anti);
    mixw /= max(mixw.x + mixw.y + mixw.z, 1.0e-4);

    // Four-tap Lanczos-like weights over {-1, 0, +1, +2} source texels.
    mediump float wh0 = lanczosLike(f.x + 1.0);
    mediump float wh1 = lanczosLike(f.x);
    mediump float wh2 = lanczosLike(1.0 - f.x);
    mediump float wh3 = lanczosLike(2.0 - f.x);
    mediump float whn = wh0 + wh1 + wh2 + wh3;
    mediump vec3 hres = (h0 * wh0 + c * wh1 + h1 * wh2 + h2 * wh3) / whn;

    mediump float wv0 = lanczosLike(f.y + 1.0);
    mediump float wv1 = lanczosLike(f.y);
    mediump float wv2 = lanczosLike(1.0 - f.y);
    mediump float wv3 = lanczosLike(2.0 - f.y);
    mediump float wvn = wv0 + wv1 + wv2 + wv3;
    mediump vec3 vres = (v0 * wv0 + c * wv1 + v1 * wv2 + v2 * wv3) / wvn;

    mediump float fd = clamp((f.x + f.y) * 0.5, 0.0, 1.0);
    mediump float wd0 = lanczosLike(fd + 1.0);
    mediump float wd1 = lanczosLike(fd);
    mediump float wd2 = lanczosLike(1.0 - fd);
    mediump float wd3 = lanczosLike(2.0 - fd);
    mediump float wdn = wd0 + wd1 + wd2 + wd3;
    mediump vec3 dres = (d0 * wd0 + c * wd1 + d1 * wd2 + d2 * wd3) / wdn;

    mediump vec3 up = hres * mixw.x + vres * mixw.y + dres * mixw.z;

    // Keep the first stage inside the local colour range.  RCAS below also
    // clamps, but this prevents EASU overshoot before the sharpen.
    mediump vec3 lo12 = min(min(min(h0, h1), min(v0, v1)), min(d0, d1));
    mediump vec3 hi12 = max(max(max(h0, h1), max(v0, v1)), max(d0, d1));
    up = clamp(up, lo12, hi12);

    // ---------------------------------------------------------------------
    // 5-tap RTX-style contrast-adaptive sharpen (RCAS-like).
    //
    // The four neighbours are sampled in *output* pixel steps, not source
    // pixel steps, so the sharpening aperture grows with the upscale factor.
    // The 5-tap min/max is the ringing guard; the lobe ratio further limits
    // overshoot when the local contrast is small.
    // ---------------------------------------------------------------------
    highp vec2 duv = uvScale / dstSize;
    mediump vec3 rc = texture(uSrcTexture, vUv * uvScale).rgb;
    mediump vec3 rl = texture(uSrcTexture, vUv * uvScale - vec2(duv.x, 0.0)).rgb;
    mediump vec3 rr = texture(uSrcTexture, vUv * uvScale + vec2(duv.x, 0.0)).rgb;
    mediump vec3 ru = texture(uSrcTexture, vUv * uvScale + vec2(0.0, duv.y)).rgb;
    mediump vec3 rd = texture(uSrcTexture, vUv * uvScale - vec2(0.0, duv.y)).rgb;

    // centre is the EASU result; rc is the nearest source sample and is used
    // only for the local range / contrast estimate.
    mediump vec3 lo5 = min(min(min(rc, rl), min(rr, ru)), min(rd, up));
    mediump vec3 hi5 = max(max(max(rc, rl), max(rr, ru)), max(rd, up));

    mediump float lLo = luma(lo5);
    mediump float lHi = luma(hi5);
    mediump float contrast = max(lHi - lLo, 0.002);
    mediump vec3 blur = (rl + rr + ru + rd) * 0.25;
    mediump vec3 detail = up - blur;

    mediump float detailL = luma(detail);
    mediump float lobe = abs(detailL) / contrast;
    mediump float lobeScale = min(1.0, 0.60 / (lobe + 1.0e-4));

    mediump float contrastGain = 0.35 + 0.65 * clamp(contrast * 4.0, 0.0, 1.0);
    mediump vec3 sharpened = up + detail * (uSharpness * contrastGain * 1.25 * lobeScale);
    sharpened = clamp(sharpened, lo5, hi5);

    mediump vec3 outColor = sharpened * uExposure;

#ifdef PEAKING
    // Focus peaking uses the same five taps: no extra texture fetch, no
    // discard, and the tint is blended rather than replacing the luma.
    mediump float edge = abs(luma(rr) - luma(rl)) + abs(luma(ru) - luma(rd));
    mediump float peak = smoothstep(0.06, 0.30, edge) * clamp(uPeakingIntensity, 0.0, 1.0);
    outColor = mix(outColor, vec3(1.0, 0.12, 0.02), peak);
#endif

    fragColor = vec4(outColor, 1.0);
}

#else // A6400_BILINEAR

void main()
{
    highp vec2 uvScale = max(uSrcSize, vec2(1.0)) / max(uSrcTextureSize, vec2(1.0));
    highp vec2 uv = clamp(vUv, 0.0, 1.0) * uvScale;
    fragColor = vec4(texture(uSrcTexture, uv).rgb * uExposure, 1.0);
}

#endif
