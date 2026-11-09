plugins {
    id("com.android.application")
    id("com.chaquo.python")
}

android {
    namespace = "fr.comap.chauffage"
    compileSdk = 35

    defaultConfig {
        applicationId = "fr.comap.chauffage"
        minSdk = 24          // minimum de Chaquopy 17
        targetSdk = 34
        versionCode = 1
        versionName = "1.0"
        ndk {
            // arm64-v8a : tous les téléphones récents ; x86_64 : émulateur Android Studio
            abiFilters += listOf("arm64-v8a", "x86_64")
        }
    }
    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }
}

chaquopy {
    defaultConfig {
        version = "3.12"     // Python 3.12 doit aussi être installé sur la machine qui compile
        pip {
            // requests, boto3, python-dateutil et pytz sont installés comme dépendances
            install("comapsmarthome-public-api")
        }
    }
}
