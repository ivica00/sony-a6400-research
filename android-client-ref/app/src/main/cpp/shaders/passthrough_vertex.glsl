#version 320 es
//
// Full-screen triangle with no VBO and no vertex-buffer churn.  GLES 3.2
// requires a bound VAO for a draw, but the VAO may be empty: gl_VertexID is
// enough.  The triangle is oversized so its visible region exactly covers the
// viewport; the rasteriser clips the rest.
//
// Uniforms are intentionally absent.  Letterboxing is done with glViewport by
// gl_renderer.cpp, not by a vertex scale uniform.
precision highp float;

out highp vec2 vUv;

void main()
{
    vec2 p = vec2(
        (gl_VertexID == 1) ? 3.0 : -1.0,
        (gl_VertexID == 2) ? 3.0 : -1.0);
    vUv = p * 0.5 + 0.5;
    gl_Position = vec4(p, 0.0, 1.0);
}
