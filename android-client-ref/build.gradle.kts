// Root build file. Plugin versions are pinned once here so `app/build.gradle.kts`
// stays free of version literals.
//
// Toolchain this project is written against (see README.md "Build"):
//   * Gradle 8.7+        (the wrapper is not vendored; use `gradle wrapper` once offline)
//   * Android Gradle Plugin 8.5.2
//   * Kotlin 1.9.24
//
// No repositories are declared for dependencies other than the two standard ones
// in settings.gradle.kts, and no dependency is ever added to :app.
plugins {
    id("com.android.application") version "8.5.2" apply false
    id("org.jetbrains.kotlin.android") version "1.9.24" apply false
}
