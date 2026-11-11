// a6400 low-latency live-view reference client (transport A: PTP, transport B: UVC).
//
// Two repositories only. No AndroidX, no third-party libraries: the app is
// plain android.* + the Kotlin stdlib, and the renderer is a local CMake target.
pluginManagement {
    repositories {
        google()
        mavenCentral()
        gradlePluginPortal()
    }
}

dependencyResolutionManagement {
    repositoriesMode.set(RepositoriesMode.FAIL_ON_PROJECT_REPOS)
    repositories {
        google()
        mavenCentral()
    }
}

rootProject.name = "a6400-lived"

include(":app")
