import java.text.SimpleDateFormat
import java.util.Date
import java.util.Properties
import java.util.TimeZone

plugins {
    id("com.android.application")
}

// Version unique du livrable, à garder synchronisée avec ../VERSION.md.
// L'écran principal et la notification l'affichent avec l'horodatage.
val versionApplication = "0.47.1"
val horodatageCompilation: String = SimpleDateFormat("yyyy-MM-dd HH:mm").apply {
    timeZone = TimeZone.getTimeZone("Europe/Paris")
}.format(Date())

// Une APK par personne : `gradlew assembleDebug -Putilisateur=camille`.
// Sans la propriété, c'est l'APK du propriétaire (clé SATELLITE_JETON).
// Avec, on lit SATELLITE_JETON_<UTILISATEUR> et on suffixe le versionName.
val utilisateur: String = (findProperty("utilisateur") as String?)?.trim()?.lowercase() ?: ""
if (!utilisateur.matches(Regex("[a-z0-9_]*"))) {
    throw GradleException("Propriété utilisateur invalide : lettres, chiffres et _ seulement.")
}
// Le nom affiché par défaut est celui du propriétaire (proprietaire.nom de maison.json), lu plus bas.
var nomUtilisateur = utilisateur.replaceFirstChar { it.uppercase() }
val cleJeton = if (utilisateur.isEmpty()) "SATELLITE_JETON" else "SATELLITE_JETON_${utilisateur.uppercase()}"

// Seule la ligne de la clé voulue est retenue dans poc/.env. Les autres lignes
// (autres secrets) ne sont ni conservées ni affichées.
val fichierEnv = rootProject.file("../poc/.env")
val jetonSatellite: String = if (fichierEnv.exists()) {
    fichierEnv.readLines(Charsets.UTF_8)
        .map { it.trim() }
        .firstOrNull { it.startsWith("$cleJeton=") }
        ?.substringAfter("=")
        ?.trim()
        ?.trim('"', '\'')
        ?: ""
} else ""
if (jetonSatellite.isEmpty()) {
    if (utilisateur.isNotEmpty()) throw GradleException("$cleJeton absent de poc/.env.")
    logger.warn("$cleJeton absent de poc/.env : le satellite sera refusé par le serveur.")
}
// Configuration de la maison, un seul dossier hors du code (voir poc/maison.py) : -PconfigDossier=... (ancien nom
// -PmaisonDossier), sinon la variable ASSISTANT_VOCAL_CONFIG (ancien nom MAISON_DOSSIER), sinon config/ à la racine du
// dépôt (non suivi par git), ou l'ancien maison/ tant que config/ n'existe pas. maison.json y donne les
// adresses par défaut et les listes de sécurité, recopiées dans BuildConfig.MAISON_JSON que Securite.kt
// interprète, et genere/android/ devient un dossier d'assets : dictionnaire.json (android/outils/exporter_dictionnaire.py)
// et maison3d/vue3d.html, la vue 3D de l'appartement (carte/3d/generer_3d.py).
// Sans ce dossier, seuls les tests unitaires tournent, sur config-exemple/ (valeurs fictives) : une APK est refusée.
val dossierExemple: File = rootProject.file("../config-exemple")
val dossierMaison: File = listOf(findProperty("configDossier") as String?, findProperty("maisonDossier") as String?,
    System.getenv("ASSISTANT_VOCAL_CONFIG"), System.getenv("MAISON_DOSSIER")).firstOrNull { !it.isNullOrBlank() }
    ?.let { File(it).takeIf { f -> f.isAbsolute } ?: rootProject.file("../$it") }
    ?: rootProject.file("../config").takeIf { File(it, "maison.json").exists() || !rootProject.file("../maison/maison.json").exists() }
    ?: rootProject.file("../maison").also { logger.warn("${it.path} : ancien dossier de configuration, à renommer en config/.") }
// Un chemin relatif part de la racine du dépôt, comme pour poc/maison.py lancé depuis la racine.
val fabriqueApk = gradle.startParameter.taskNames.any { t ->
    val n = t.lowercase().substringAfterLast(":")
    n == "build" || listOf("assemble", "install", "bundle", "package").any { it in n }
}
val dossierLu: File = if (File(dossierMaison, "maison.json").exists()) dossierMaison else {
    if (fabriqueApk) {
        throw GradleException("${dossierMaison.path}/maison.json absent : copier config-exemple/ en config/ et y mettre les vraies valeurs avant de compiler une APK.")
    }
    logger.warn("${dossierMaison.path}/maison.json absent : configuration fictive de config-exemple/ (réservée aux tests unitaires).")
    dossierExemple
}
// Données d'usage de cette machine (JARVIS_DONNEES du serveur, poc/ par défaut, -PdonneesDossier=... sinon) :
// genere/android/dictionnaire_appris.json y porte les phrases apprises, hors du dossier de configuration versionné.
val dossierDonnees: File = listOf(findProperty("donneesDossier") as String?, System.getenv("JARVIS_DONNEES"))
    .firstOrNull { !it.isNullOrBlank() }?.let { File(it).takeIf { f -> f.isAbsolute } ?: rootProject.file("../$it") }
    ?: rootProject.file("../poc")
if (fabriqueApk && !File(dossierLu, "genere/android/dictionnaire.json").exists()) {
    throw GradleException("${dossierLu.path}/genere/android/dictionnaire.json absent : lancer python android/outils/exporter_dictionnaire.py.")
}
if (fabriqueApk && !File(dossierLu, "genere/android/maison3d/vue3d.html").exists()) {
    throw GradleException("${dossierLu.path}/genere/android/maison3d/vue3d.html absent : lancer python carte/3d/generer_3d.py.")
}
// Page d'avant la 0.31.0 (ancien nom du pont JavaScript) : la vue 3D ne parlerait plus à l'appli.
if (fabriqueApk && "Maison3dAndroid" !in File(dossierLu, "genere/android/maison3d/vue3d.html").readText(Charsets.UTF_8)) {
    throw GradleException("${dossierLu.path}/genere/android/maison3d/vue3d.html périmée (pont d'avant la 0.31.0) : relancer python carte/3d/generer_3d.py.")
}
// Page d'avant la 0.46.0 (S-L7) : sans maison3d.mesures, les pastilles de mesures restent invisibles sans erreur.
if (fabriqueApk && "function mesures(" !in File(dossierLu, "genere/android/maison3d/vue3d.html").readText(Charsets.UTF_8)) {
    throw GradleException("${dossierLu.path}/genere/android/maison3d/vue3d.html périmée (sans les mesures de la 0.46.0) : relancer python carte/3d/generer_3d.py.")
}
val maison: Map<*, *> = try {
    groovy.json.JsonSlurper().parseText(File(dossierLu, "maison.json").readText(Charsets.UTF_8)) as Map<*, *>
} catch (e: Exception) {
    throw GradleException("Configuration de la maison illisible (${dossierLu.path}/maison.json) : ${e.message}")
}
// Mot de réveil de la configuration (section reveil) : reveil/<mot>.onnx du dossier, rangé dans assets/reveil/.
val motReveilConfig: String = ((maison["reveil"] as? Map<*, *>)?.get("mot") as? String)?.trim()?.lowercase().orEmpty()
val modeleReveilConfig: File? = motReveilConfig.takeIf { it.isNotEmpty() }?.let { File(dossierLu, "reveil/$it.onnx") }
// Noms des modèles d'openWakeWord rangés dans le dépôt : un mot de réveil du même nom les écraserait dans l'APK.
if (motReveilConfig in listOf("melspectrogram", "embedding_model", "hey_jarvis", "hey_jarvis_v0.1")) {
    throw GradleException("${dossierLu.path}/maison.json : reveil.mot ne peut pas valoir « $motReveilConfig », nom d'un modèle du dépôt.")
}
if (modeleReveilConfig != null && modeleReveilConfig.exists() && !File(modeleReveilConfig.path + ".LICENSE").exists()) {
    logger.warn("${modeleReveilConfig.path}.LICENSE absent : l'APK embarque ce mot de réveil sans sa licence.")
}
if (fabriqueApk && modeleReveilConfig != null && !modeleReveilConfig.exists()) {
    throw GradleException("${dossierLu.path}/maison.json : reveil.mot vaut « $motReveilConfig » mais ${modeleReveilConfig.path} est absent.")
}
// Carte du vent mesuré (section vent, actif) : trait de côte et terre lus dans genere/android/.
(maison["vent"] as? Map<*, *>)?.takeIf { fabriqueApk && it["actif"] == true }?.let { vent ->
    val carte = vent["carte"] as? Map<*, *>
    for (cle in listOf("cote", "terre")) {
        val chemin = carte?.get(cle) as? String
        if (chemin.isNullOrBlank() || !File(dossierLu, "genere/android/$chemin").exists()) {
            throw GradleException("${dossierLu.path}/maison.json : vent.carte.$cle (« ${chemin ?: ""} ») absent de genere/android/, la carte du vent sortirait sans côte.")
        }
    }
}
val nomProprietaire = ((maison["proprietaire"] as? Map<*, *>)?.get("nom") as? String)?.trim()?.ifEmpty { null }
if (nomProprietaire == null) {
    logger.warn("${dossierLu.path}/maison.json : section proprietaire absente, l'APK s'affiche au nom de « Moi » et la santé ne s'affiche pour personne.")
}
if (utilisateur.isEmpty()) {
    nomUtilisateur = nomProprietaire ?: "Moi"
}
// Nom affiché de l'assistant (section assistant) : nom de l'appli sous l'icône et dans les réglages.
val nomAssistant = ((maison["assistant"] as? Map<*, *>)?.get("nom") as? String)?.trim()?.ifEmpty { null } ?: "Assistant"
// Échappement d'une ressource chaîne Android : barre oblique inverse, apostrophe, guillemet, et @ ou ? en tête.
fun ressourceChaine(s: String): String =
    s.replace("\\", "\\\\").replace("'", "\\'").replace("\"", "\\\"").let { if (it.startsWith("@") || it.startsWith("?")) "\\$it" else it }
fun reseauMaison(cle: String): String = ((maison["reseau"] as? Map<*, *>)?.get(cle) as? String)?.trim().orEmpty()
// Plus de jeton Home Assistant dans l'APK depuis la 0.15.0 : le mode « Cet appareil » passe par
// la passerelle de l'app Jarvis sur HA, qui garde son propre jeton (voir PasserelleHa.kt).

// Signature de publication facultative : android/keystore.properties (ignoré par git, voir docs/INSTALLER.md).
// Le fichier n'est lu que s'il existe, et seules ses quatre clés sont retenues. Si une clé manque, la
// compilation s'arrête avec un message clair plutôt que de produire une APK mal signée.
val proprietesSignature = Properties().apply {
    val fichier = rootProject.file("keystore.properties")
    if (fichier.exists()) fichier.inputStream().use { load(it) }
}
val signatureFournie: Boolean = rootProject.file("keystore.properties").exists()
if (signatureFournie) {
    val manquantes = listOf("storeFile", "storePassword", "keyAlias", "keyPassword")
        .filter { proprietesSignature.getProperty(it).isNullOrBlank() }
    if (manquantes.isNotEmpty()) {
        throw GradleException("android/keystore.properties : clé(s) manquante(s) ${manquantes.joinToString(", ")}.")
    }
}

fun chaineJava(s: String) = "\"" + s.replace("\\", "\\\\").replace("\"", "\\\"") + "\""

android {
    namespace = "assistant.vocal.jarvis"

    compileSdk {
        version = release(37)
    }

    defaultConfig {
        applicationId = "assistant.vocal.jarvis"
        minSdk = 26
        targetSdk = 36
        versionCode = 88
        versionName = if (utilisateur.isEmpty()) versionApplication else "$versionApplication-$utilisateur"

        buildConfigField("String", "VERSION_BASE", chaineJava(versionApplication))
        buildConfigField("String", "UTILISATEUR", chaineJava(nomUtilisateur))
        buildConfigField("String", "HORODATAGE_COMPILATION", chaineJava(horodatageCompilation))
        // Port chiffré (wss, clé épinglée à la première connexion) depuis la 0.15.0.
        buildConfigField("String", "SERVEUR_PC_DEFAUT", chaineJava(reseauMaison("android_serveur_pc")))
        buildConfigField("String", "SERVEUR_HA_DEFAUT", chaineJava(reseauMaison("android_serveur_ha")))
        // Noms d'hôte de repli (virgules), essayés avant l'IP si elle a changé (0.34.0).
        buildConfigField("String", "HOTES_PC_DEFAUT", chaineJava(reseauMaison("android_hotes_pc")))
        buildConfigField("String", "HOTES_HA_DEFAUT", chaineJava(reseauMaison("android_hotes_ha")))
        // Configuration de la maison en JSON compact, ASCII (groovy échappe les accents).
        buildConfigField("String", "MAISON_JSON", chaineJava(groovy.json.JsonOutput.toJson(maison)))
        buildConfigField("String", "JETON_DEFAUT", chaineJava(jetonSatellite))
        resValue("string", "app_name", ressourceChaine(nomAssistant))

        // ONNX Runtime et OpenCV embarquent leur moteur natif par architecture : seuls les ARM
        // des téléphones (téléphone, tablette, téléphone) sont gardés pour limiter la taille de l'APK.
        ndk {
            abiFilters += listOf("arm64-v8a", "armeabi-v7a")
        }
    }

    // Signature de publication : seulement si android/keystore.properties existe (ignoré par git, jamais
    // versionné). Clés attendues : storeFile (chemin du fichier de clés), storePassword, keyAlias, keyPassword.
    // Sans ce fichier, la variante release reste non signée et debug garde la clé de débogage d'Android.
    if (signatureFournie) {
        signingConfigs {
            create("publication") {
                storeFile = rootProject.file(proprietesSignature.getProperty("storeFile"))
                storePassword = proprietesSignature.getProperty("storePassword")
                keyAlias = proprietesSignature.getProperty("keyAlias")
                keyPassword = proprietesSignature.getProperty("keyPassword")
            }
        }
    }

    buildTypes {
        release {
            isMinifyEnabled = false
            if (signatureFournie) signingConfig = signingConfigs.getByName("publication")
        }
    }

    buildFeatures {
        buildConfig = true
        resValues = true
    }

    // Fichiers produits à partir de la configuration de la maison : dictionnaire.json, maison3d/vue3d.html et
    // carte/ (trait de côte et terre de la carte du vent mesuré).
    sourceSets["main"].assets.srcDir(File(dossierLu, "genere/android"))
    // Phrases apprises (dictionnaire_appris.json), jamais avec la configuration fictive. Chemins canoniques : un
    // même dossier écrit autrement (« ./config », lien) ne doit ni passer pour un autre ni être ajouté deux fois.
    File(dossierDonnees, "genere/android").takeIf {
        it.isDirectory && dossierLu.canonicalFile != dossierExemple.canonicalFile &&
            it.canonicalFile != File(dossierLu, "genere/android").canonicalFile
    }?.let {
        logger.lifecycle("Phrases apprises prises dans ${it.path}")
        sourceSets["main"].assets.srcDir(it)
    }

    // Les tests unitaires tournent sur la configuration fictive de config-exemple/, jamais sur la vraie : propriété
    // système lue par ConfigMaison.kt et DictionnaireTest. `-PmaisonTests=reel` les lance sur le dossier de la
    // maison (les cas écrits pour config-exemple/ y échouent, c'est attendu : sert à rejouer d'anciens cas).
    testOptions {
        unitTests.all {
            val reel = (findProperty("maisonTests") as String?) == "reel"
            it.systemProperty("maison.dossier", (if (reel) dossierMaison else dossierExemple).absolutePath)
        }
    }

    compileOptions {
        sourceCompatibility = JavaVersion.VERSION_17
        targetCompatibility = JavaVersion.VERSION_17
    }

    kotlin {
        compilerOptions {
            jvmTarget.set(org.jetbrains.kotlin.gradle.dsl.JvmTarget.JVM_17)
            // LiteRT-LM 0.18 est compilé avec Kotlin 2.4, plus récent que celui d'AGP 9.2.1.
            freeCompilerArgs.add("-Xskip-metadata-version-check")
        }
    }

    packaging {
        resources.excludes += "/META-INF/{AL2.0,LGPL2.1}"
    }
}

// Copie du mot de réveil de la configuration (modèle et sa licence) dans un dossier d'assets produit.
abstract class CopierReveil : DefaultTask() {
    @get:InputFiles abstract val modeles: ConfigurableFileCollection
    @get:OutputDirectory abstract val sortie: DirectoryProperty

    @TaskAction
    fun copier() {
        val dossier = File(sortie.get().asFile, "reveil")
        sortie.get().asFile.deleteRecursively()
        dossier.mkdirs()
        modeles.files.filter { it.exists() }.forEach { it.copyTo(File(dossier, it.name), overwrite = true) }
    }
}
val copierReveil = tasks.register<CopierReveil>("copierReveil") {
    modeleReveilConfig?.let { modeles.from(it, File(it.path + ".LICENSE")) }
    sortie.set(layout.buildDirectory.dir("assetsConfig"))
}
androidComponents {
    onVariants { variante -> variante.sources.assets?.addGeneratedSourceDirectory(copierReveil, CopierReveil::sortie) }
}

dependencies {
    implementation("com.squareup.okhttp3:okhttp:4.12.0")
    // Mot de réveil openWakeWord calculé sur le téléphone (v0.9.0).
    implementation("com.microsoft.onnxruntime:onnxruntime-android:1.22.0")
    // LLM sur l'appareil (0.13.0) : LiteRT-LM de Google, modèles .litertlm (Gemma 4, Qwen) copiés par adb.
    implementation("com.google.ai.edge.litertlm:litertlm-android:0.18.0")
    // Vision de la tablette (0.16.0) : caméra par CameraX, visages par OpenCV (YuNet et SFace).
    // OpenCV 4.14.0 de Maven Central (org.opencv:opencv, Apache 2.0), dernière de la branche 4.x,
    // celle de FaceDetectorYN et FaceRecognizerSF utilisés par poc/vision.py.
    implementation("org.opencv:opencv:4.14.0")
    implementation("androidx.camera:camera-camera2:1.6.2")
    implementation("androidx.camera:camera-lifecycle:1.6.2")
    implementation("androidx.camera:camera-view:1.6.2")
    // Cycle de vie porté par le service et l'écran des visages (CameraX en a besoin).
    implementation("androidx.lifecycle:lifecycle-runtime:2.8.7")

    // Tests unitaires sur la machine (0.15.0) : sécurité en dur contre poc/tests/cas_securite.json,
    // et depuis la 0.16.0 la reconnaissance des visages (Reconnaissance.kt, logique pure).
    // org.json réel, celui d'android.jar n'est qu'une coquille vide hors appareil.
    testImplementation("junit:junit:4.13.2")
    testImplementation("org.json:json:20240303")
}
