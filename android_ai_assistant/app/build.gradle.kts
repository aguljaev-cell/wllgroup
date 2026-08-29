plugins {
    id("com.android.application")
    id("org.jetbrains.kotlin.android")
}

android { namespace = "com.memoryai.assistant"; compileSdk = 35
    defaultConfig { applicationId = "com.memoryai.assistant"; minSdk = 26; targetSdk = 35; versionCode = 1; versionName = "0.1.0" }
}

dependencies {
    implementation("androidx.core:core-ktx:1.15.0")
    implementation("androidx.activity:activity-compose:1.10.1")
    implementation(platform("androidx.compose:compose-bom:2025.01.00"))
    implementation("androidx.compose.ui:ui")
    implementation("androidx.compose.material3:material3")
    implementation("androidx.lifecycle:lifecycle-runtime-compose:2.8.7")
    implementation("androidx.room:room-runtime:2.7.0")
    implementation("androidx.room:room-ktx:2.7.0")
    implementation("androidx.room:room-compiler:2.7.0")
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
}
