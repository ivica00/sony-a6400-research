#version 460 core
#include <flutter/runtime_effect.glsl>
// SGSR1 reconstruction adapted from Qualcomm BSD-3-Clause reference.
// Copyright (c) 2025 Qualcomm Innovation Center, Inc. All rights reserved.
// See third_party/sgsr1/LICENSE. Gather emulated at texel centers for Flutter.
uniform vec2 uSize;
uniform vec2 uSource;
uniform float uSharpness;
uniform float uPeaking;
uniform float uSgsr;
uniform float uZebra;
uniform float uZebraLevel;
uniform float uLut;
uniform float uLutSize;
uniform float uLutStrength;
uniform vec3 uDomainMin;
uniform vec3 uDomainMax;
uniform sampler2D uImage;
uniform sampler2D uMeter;
uniform sampler2D uLutAtlas;
out vec4 fragColor;
vec4 source(vec2 uv) {return texture(uImage,clamp(uv,vec2(0),vec2(1)));}
vec4 gatherGreen(vec2 uv) {
  vec2 base=floor(uv*uSource-0.5);
  vec2 p=(base+0.5)/uSource,px=1.0/uSource;
  return vec4(source(p+vec2(0,px.y)).g,source(p+px).g,source(p+vec2(px.x,0)).g,source(p).g);
}
float fastLanczos2(float x)
{
	float wA = x-4.0;
	float wB = x*wA-wA;
	wA *= wA;
	return wB*wA;
}
vec2 weightY(float dx, float dy,float c, float std)
{
	float x = ((dx*dx)+(dy* dy))* 0.55 + clamp(abs(c)*std, 0.0, 1.0);
	float w = fastLanczos2(x);
	return vec2(w, w * c);	
}


vec3 sgsr(vec2 uv) {
	int mode = 1;
	float edgeThreshold = 8.0/255.0;
	float edgeSharpness = 1.0+uSharpness;

	vec4 color;
	if(mode == 1)
		color.xyz = source(uv).xyz;
	else
		color.xyzw = source(uv).xyzw;

	float xCenter;
	xCenter = abs(uv.x+-0.5);
	float yCenter;
	yCenter = abs(uv.y+-0.5);

	//todo: config the SR region based on needs
	//if ( mode!=4 && xCenter*xCenter+yCenter*yCenter<=0.4 * 0.4)
	if ( mode!=4)
	{
		vec2 imgCoord = ((uv*uSource)+vec2(-0.5,0.5));
		vec2 imgCoordPixel = floor(imgCoord);
		vec2 coord = (imgCoordPixel*(1.0/uSource));
		vec2 pl = (imgCoord+(-imgCoordPixel));
		vec4  left = gatherGreen(coord);

		float edgeVote = abs(left.z - left.y) + abs(color.g - left.y)  + abs(color.g - left.z) ;
		if(edgeVote > edgeThreshold)
		{
			coord.x += (1.0/uSource.x);

			vec4 right = gatherGreen(coord + vec2((1.0/uSource.x), 0.0));
			vec4 upDown;
			upDown.xy = gatherGreen(coord + vec2(0.0, -(1.0/uSource.y))).wz;
			upDown.zw  = gatherGreen(coord+ vec2(0.0, (1.0/uSource.y))).yx;

			float mean = (left.y+left.z+right.x+right.w)*0.25;
			left = left - vec4(mean);
			right = right - vec4(mean);
			upDown = upDown - vec4(mean);
			color.w =color.g - mean;

			float sum = (((((abs(left.x)+abs(left.y))+abs(left.z))+abs(left.w))+(((abs(right.x)+abs(right.y))+abs(right.z))+abs(right.w)))+(((abs(upDown.x)+abs(upDown.y))+abs(upDown.z))+abs(upDown.w)));				
			float std = 2.181818/max(sum,0.000001);
			
			vec2 aWY = weightY(pl.x, pl.y+1.0, upDown.x,std);				
			aWY += weightY(pl.x-1.0, pl.y+1.0, upDown.y,std);
			aWY += weightY(pl.x-1.0, pl.y-2.0, upDown.z,std);
			aWY += weightY(pl.x, pl.y-2.0, upDown.w,std);			
			aWY += weightY(pl.x+1.0, pl.y-1.0, left.x,std);
			aWY += weightY(pl.x, pl.y-1.0, left.y,std);
			aWY += weightY(pl.x, pl.y, left.z,std);
			aWY += weightY(pl.x+1.0, pl.y, left.w,std);
			aWY += weightY(pl.x-1.0, pl.y-1.0, right.x,std);
			aWY += weightY(pl.x-2.0, pl.y-1.0, right.y,std);
			aWY += weightY(pl.x-2.0, pl.y, right.z,std);
			aWY += weightY(pl.x-1.0, pl.y, right.w,std);

			float finalY = aWY.y/max(abs(aWY.x),0.000001)*sign(aWY.x);

			float maxY = max(max(left.y,left.z),max(right.x,right.w));
			float minY = min(min(left.y,left.z),min(right.x,right.w));
			finalY = clamp(edgeSharpness*finalY, minY, maxY);
					
			float deltaY = finalY -color.w;	
			
			//smooth high contrast input
			deltaY = clamp(deltaY, -23.0 / 255.0, 23.0 / 255.0);

			color.x = clamp((color.x+deltaY),0.0,1.0);
			color.y = clamp((color.y+deltaY),0.0,1.0);
			color.z = clamp((color.z+deltaY),0.0,1.0);
		}
	}

return color.rgb;
}

vec3 lutTexel(vec3 p) {
  vec2 uv=vec2((p.b*uLutSize+p.r+0.5)/(uLutSize*uLutSize),(p.g+0.5)/uLutSize);
  return texture(uLutAtlas,uv).rgb;
}
vec3 applyLut(vec3 rgb) {
  vec3 v=clamp((rgb-uDomainMin)/(uDomainMax-uDomainMin),0.0,1.0)*(uLutSize-1.0);
  vec3 a=floor(v),b=min(a+1.0,vec3(uLutSize-1.0)),f=fract(v);
  vec3 low=mix(mix(lutTexel(a),lutTexel(vec3(b.r,a.g,a.b)),f.r),mix(lutTexel(vec3(a.r,b.g,a.b)),lutTexel(vec3(b.r,b.g,a.b)),f.r),f.g);
  vec3 high=mix(mix(lutTexel(vec3(a.r,a.g,b.b)),lutTexel(vec3(b.r,a.g,b.b)),f.r),mix(lutTexel(vec3(a.r,b.g,b.b)),lutTexel(b),f.r),f.g);
  return mix(rgb,mix(low,high,f.b),uLutStrength);
}
void main() {
  vec2 uv=FlutterFragCoord().xy/uSize;
  vec3 c=uSgsr>0.5?sgsr(uv):source(uv).rgb;
  if(uLut>0.5)c=applyLut(c);
  // Zebras meter the original incoming display signal BEFORE LUT/709.
  float luma=dot(texture(uMeter,uv).rgb,vec3(0.2126,0.7152,0.0722));
  if(uZebra>0.5&&luma>=uZebraLevel) {
    float stripe=step(0.5,fract((FlutterFragCoord().x+FlutterFragCoord().y)/12.0));
    c=mix(c,mix(vec3(0.03),vec3(1.0),stripe),0.8);
  }
  if(uPeaking>0.5) {
    vec2 px=1.0/uSource;
    vec3 e=texture(uImage,clamp(uv+vec2(px.x,0),0.0,1.0)).rgb;
    vec3 w=texture(uImage,clamp(uv-vec2(px.x,0),0.0,1.0)).rgb;
    vec3 n=texture(uImage,clamp(uv+vec2(0,px.y),0.0,1.0)).rgb;
    vec3 s=texture(uImage,clamp(uv-vec2(0,px.y),0.0,1.0)).rgb;
    if(length(e-w)+length(n-s)>0.32)c=mix(c,vec3(0.95,0.16,0.1),0.85);
  }
  fragColor=vec4(clamp(c,0.0,1.0),1.0);
}
