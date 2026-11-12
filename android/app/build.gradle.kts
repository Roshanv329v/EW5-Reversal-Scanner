import java.util.Properties

plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

// Release signing: android/keystore.properties (not in git) points at the keystore.
val signing = Properties().apply {
    val f = rootProject.file("keystore.properties")
    if (f.exists()) f.inputStream().use { load(it) }
}

android {
    namespace = "app.ewscanner"
    compileSdk = 35

    defaultConfig {
        applicationId = "app.ewscanner"
        minSdk = 24
        targetSdk = 35
        versionCode = 2                    // raise on every release: the phone installs it as an update
        versionName = "1.1"
        ndk { abiFilters += listOf("arm64-v8a") }     // current phones and Apple-silicon emulators
    }
    signingConfigs {
        if (signing.isNotEmpty()) {
            create("release") {
                storeFile = rootProject.file(signing.getProperty("storeFile"))
                storePassword = signing.getProperty("storePassword")
                keyAlias = signing.getProperty("keyAlias")
                keyPassword = signing.getProperty("keyPassword")
            }
        }
    }
    buildTypes {
        getByName("release") {
            isMinifyEnabled = false
            if (signing.isNotEmpty()) signingConfig = signingConfigs.getByName("release")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

chaquopy {
    defaultConfig {
        version = "3.11"                   // pandas 2.1.3 / numpy 1.26.2 are prebuilt for it
        buildPython("python3.11")
        pip {
            install("numpy==1.26.2")
            install("pandas==2.1.3")
            install("pyyaml")
            install("plotly==7.1.0")       // same version as the desktop: the same charts
            install("markdown")            // User Guide
        }
    }
}

// The engine is not copied by hand: the desktop files are synced in on every build,
// so the phone always runs exactly what the Mac runs.
val engineFiles = listOf(
    "elliott_wave5_screener.py", "elliott_wave3_screener.py", "stock_data.py", "config.yaml",
    "core/__init__.py", "core/config.py", "core/data_store.py", "core/runner.py",
    "core/htf.py", "core/ta_lite.py", "core/charts.py", "core/strategies.py", "core/prefs.py",
)
val syncEngine by tasks.registering(Copy::class) {
    val project = rootDir.parentFile
    into(layout.projectDirectory.dir("src/main/python"))
    from(project) { include(engineFiles) }
    from(project.resolve("docs")) { include("*.md"); into("mobile/docs") }          // User Guide
    from(project.resolve("data")) { include("tickers.csv"); into("mobile/seed") }   // first-run ticker list
}
tasks.named("preBuild") { dependsOn(syncEngine) }
tasks.matching { it.name.endsWith("PythonSources") }.configureEach { dependsOn(syncEngine) }
