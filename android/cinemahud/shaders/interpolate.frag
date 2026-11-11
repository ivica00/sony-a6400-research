#version 460 core
#include <flutter/runtime_effect.glsl>
uniform vec2 uSource;
uniform sampler2D uPrevious;
uniform sampler2D uCurrent;
uniform sampler2D uFlow;
out vec4 fragColor;
void main(){
  vec2 uv=FlutterFragCoord().xy/uSource;
  vec3 flow=texture(uFlow,uv).rgb;
  vec2 delta=(flow.rg-0.5)*32.0/uSource;
  vec4 a=texture(uPrevious,clamp(uv-0.5*delta,vec2(0),vec2(1)));
  vec4 b=texture(uCurrent,clamp(uv+0.5*delta,vec2(0),vec2(1)));
  // Cut/occlusion fallback is the current real frame, never a ghosted blend.
  if(flow.b<0.35||length(a.rgb-b.rgb)>0.24){fragColor=texture(uCurrent,uv);return;}
  fragColor=mix(a,b,0.5);
}
