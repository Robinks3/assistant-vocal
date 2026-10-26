// Fichier racine. La configuration réelle est dans app/build.gradle.kts.
plugins {
    // AGP 9 embarque son propre support Kotlin : ne pas appliquer
    // org.jetbrains.kotlin.android en plus (« extension already registered »).
    id("com.android.application") version "9.2.1" apply false
}

// Sous Windows, le projet est sous Documents, scanné par Defender et indexé par Windows Search :
// le dossier `build` est donc écrit hors de Documents (C:/Dev/assistant-vocal-build) pour éviter les
// AccessDeniedException quand Gradle supprime ses fichiers. Ailleurs (Linux, macOS), ce détour n'a
// pas lieu d'être : le dossier `build/` standard de chaque module est gardé (ignoré par git).
// `-PdossierBuild=...` choisit un autre dossier, sur tous les systèmes (deux arbres compilés en même temps).
val dossierBuild: String? = (findProperty("dossierBuild") as String?)?.takeIf { it.isNotBlank() }
    ?: "C:/Dev/assistant-vocal-build".takeIf { System.getProperty("os.name").lowercase().contains("windows") }
allprojects {
    if (dossierBuild != null) {
        layout.buildDirectory.set(file("$dossierBuild/${rootProject.name}-${project.name}"))
    }
}
