# Keep the JNI bridge exactly as declared: the native library exports symbols
# named after this class, so renaming or stripping it would break the link at
# runtime with UnsatisfiedLinkError.
-keep class com.a6400.lived.NativePipeline { *; }
-keepclasseswithmembernames,includedescriptorclasses class * {
    native <methods>;
}

# The GL renderer and activity are reached by name from the framework.
-keep class com.a6400.lived.MainActivity { *; }
-keep class com.a6400.lived.gl.SgsrSurfaceView { *; }
