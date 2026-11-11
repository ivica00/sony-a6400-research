#version 460 core
#include <flutter/runtime_effect.glsl>
uniform vec2 uFlowSize;
uniform vec2 uSource;
uniform sampler2D uPrevious;
uniform sampler2D uCurrent;
out vec4 fragColor;
float gray(vec3 c) { return dot(c,vec3(0.2126,0.7152,0.0722)); }
float matchCost(vec2 uv,vec2 d) {
  float cost=0.0;
  for(int k=0;k<5;k++) {
    vec2 p=vec2(0.0);
    if(k==1)p=vec2(-3,0);if(k==2)p=vec2(3,0);
    if(k==3)p=vec2(0,-3);if(k==4)p=vec2(0,3);
    vec2 at=clamp(uv+p/uSource,vec2(0.0),vec2(1.0));
    float a=gray(texture(uPrevious,clamp(at-d/uSource,vec2(0.0),vec2(1.0))).rgb);
    float b=gray(texture(uCurrent,at).rgb);
    cost+=abs(a-b);
  }
  return cost*0.2;
}
void main() {
  vec2 uv=FlutterFragCoord().xy/uFlowSize;
  vec2 flow=vec2(0.0);
  float best=matchCost(uv,flow);
  // Coarse-to-fine local block flow: ±15 source pixels. No synthetic vectors
  // from the camera or proprietary Adreno Frame Motion Engine are assumed.
  for(int level=0;level<4;level++) {
    float stepSize=level==0?8.0:level==1?4.0:level==2?2.0:1.0;
    vec2 origin=flow,selected=flow;
    float score=best+dot(flow,flow)*0.000002;
    for(int y=-1;y<=1;y++){for(int x=-1;x<=1;x++){
      vec2 candidate=origin+vec2(float(x),float(y))*stepSize;
      float cost=matchCost(uv,candidate);
      float next=cost+dot(candidate,candidate)*0.000002;
      if(next<score){score=next;best=cost;selected=candidate;}
    }}
    flow=selected;
  }
  float confidence=1.0-smoothstep(0.025,0.12,best);
  fragColor=vec4(flow/32.0+0.5,confidence,1.0);
}
