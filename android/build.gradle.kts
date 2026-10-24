// Fichier racine. La configuration réelle est dans app/build.gradle.kts.
plugins {
    // AGP 9 embarque son propre support Kotlin : ne pas appliquer
    // org.jetbrains.kotlin.android en plus (« extension already registered »).
    id("com.android.application") version "9.2.1" apply false
}

// Le projet est sous Documents, scanné par Defender et indexé par Windows Search :
// le dossier `build` est donc écrit hors de Documents pour éviter les
// AccessDeniedException quand Gradle supprime ses fichiers.
// `-PdossierBuild=...` choisit un autre dossier (deux arbres compilés en même temps).
val dossierBuild = (findProperty("dossierBuild") as String?) ?: "C:/Dev/assistant-vocal-build"
allprojects {
    layout.buildDirectory.set(file("$dossierBuild/${rootProject.name}-${project.name}"))
}
