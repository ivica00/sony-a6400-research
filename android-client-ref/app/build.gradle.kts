plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

// NDK version pin.
//
// The renderer is plain C++/JNI plus a vendored libjpeg-turbo (see
// app/src/main/cpp/CMakeLists.txt, owned by the native pipeline workstream).
// The NDK is pinned to a *string constant* so the value is reviewable in one
// place and reproducible across machines:
//   26.3.11579264 == NDK r26d, the last r26 LTS that ships the r26 libc++
//                    headers libjpeg-turbo's CMake build expects.
// Change this constant and README.md together, never in one place only.
val pinnedNdkVersion = "26.3.11579264"

// CMake binary version pinned to what NDK r26d bundles.
val pinnedCmakeVersion = "3.22.1"

android {
    namespace = "com.a6400.lived"
    compileSdk = 34
    ndkVersion = pinnedNdkVersion

    defaultConfig {
        applicationId = "com.a6400.lived"
        minSdk = 26
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"

        // One ABI only: every physically verified host so far is arm64-v8a and a
        // 32-bit build would silently change the JNI/NEON code paths.
        ndk {
            abiFilters += "arm64-v8a"
        }

        externalNativeBuild {
            cmake {
                // Static libc++ keeps the .so self-contained (no libc++_shared.so
                // to ship) and avoids an RPATH surprise on first launch.
                arguments += listOf("-DANDROID_STL=c++_static")
                cppFlags += listOf("-std=c++17", "-fno-exceptions", "-fno-rtti")
            }
        }
    }

    externalNativeBuild {
        cmake {
            path = file("src/main/cpp/CMakeLists.txt")
            version = pinnedCmakeVersion
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    buildTypes {
        debug {
            isMinifyEnabled = false
        }
        release {
            isMinifyEnabled = false
            // No signing config is committed: sign the release APK out of band.
            proguardFiles(
                getDefaultProguardFile("proguard-android-optimize.txt"),
                "proguard-rules.pro"
            )
        }
    }

    // The whole app is one source set and one ABI; no resource shrinking and no
    // buildConfig class are needed, so leave both off explicitly.
    buildFeatures {
        buildConfig = false
        resValues = false
    }
}

kotlin {
    compilerOptions {
        jvmTarget = org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17
    }
}

// Intentionally empty: this client depends on android.* and the Kotlin stdlib
// only. Adding AndroidX (or anything else) is a design change, not a build fix.
dependencies {
}
