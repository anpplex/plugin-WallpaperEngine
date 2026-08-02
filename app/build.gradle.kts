plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
    id("org.jetbrains.kotlin.plugin.compose")
}

android {
    namespace = "com.motif.wallpaperengine"
    compileSdk = 35

    defaultConfig {
        applicationId = "com.motif.wallpaperengine"
        minSdk = 31
        targetSdk = 35
        versionCode = 1
        versionName = "0.1.0-car"
        // WP-09: inject Mineradio APK signing cert SHA-256 (not a secret).
        // Shared parse rule with verify-wallpaper-plugin: 64 hex lowercase; debug zero-digest fallback.
        val certProp = (project.findProperty("mineradioCallerCertSha256") as String?)
            ?: System.getenv("MINERADIO_CALLER_CERT_SHA256")
        val certTrim = certProp?.trim()?.lowercase()
        require(certTrim == null || certTrim.isEmpty() || certTrim.matches(Regex("^[0-9a-f]{64}$"))) {
            "mineradioCallerCertSha256 must be empty (dev) or 64 hex"
        }
        val certSha = if (certTrim != null && certTrim.matches(Regex("^[0-9a-f]{64}$"))) {
            certTrim
        } else {
            "0".repeat(64)
        }
        buildConfigField("String", "MINERADIO_CALLER_CERT_SHA256", "\"$certSha\"")
        manifestPlaceholders["mineradioCallerCertSha256"] = certSha
        buildConfigField("String", "WE_OFFICIAL_PKG", "\"io.wallpaperengine.weclient\"")
        buildConfigField(
            "String",
            "WE_WALLPAPER_SERVICE",
            "\"io.wallpaperengine.weclient.WEWallpaperService\"",
        )
    }

    buildFeatures {
        compose = true
        buildConfig = true
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
    kotlinOptions { jvmTarget = "17" }

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }

    testOptions {
        unitTests.isIncludeAndroidResources = true
        unitTests.isReturnDefaultValues = true
    }
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-compose:1.9.3")
    implementation("androidx.lifecycle:lifecycle-runtime-ktx:2.8.7")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("org.jetbrains.kotlinx:kotlinx-coroutines-android:1.9.0")
    implementation(platform("androidx.compose:compose-bom:2024.12.01"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.foundation:foundation")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.compose.ui:ui-tooling-preview")
    debugImplementation("androidx.compose.ui:ui-tooling")

    // WP-01 RED: pure unit tests for PluginContract (Robolectric for Bundle)
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.robolectric:robolectric:4.14.1")
}
