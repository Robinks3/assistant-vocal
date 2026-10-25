package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject
import java.io.File

/**
 * Configuration de la maison (0.28.2) : maison.json du dossier de configuration (modèle config-exemple/, voir
 * poc/maison.py), copié dans BuildConfig.MAISON_JSON par build.gradle.kts. Les tests unitaires lisent le
 * dossier désigné par la propriété système maison.dossier (config-exemple/, valeurs fictives). Rien de propre à la
 * maison n'est écrit dans le code : listes de sécurité (Securite), enceintes (SortieSon), noms courts
 * (MaisonEnGrand), consigne et exemples du LLM de l'appareil (CerveauAppareil).
 */
object ConfigMaison {
    private val dossierTests: String? = System.getProperty("maison.dossier")

    val json: JSONObject = JSONObject(
        dossierTests?.let { File(it, "maison.json").readText(Charsets.UTF_8) } ?: BuildConfig.MAISON_JSON,
    )

    /** Vrai quand la configuration lue est l'exemple fictif (tests unitaires). */
    val EST_EXEMPLE: Boolean = dossierTests?.let { File(it).name == "config-exemple" } == true

    /** Propriétaire de la maison (section proprietaire) : prénom affiché et clé de son jeton. */
    val NOM_PROPRIETAIRE: String = section("proprietaire").optString("nom").trim().ifEmpty { "Moi" }
    val CLE_PROPRIETAIRE: String = section("proprietaire").optString("cle").ifEmpty { NOM_PROPRIETAIRE }.trim().lowercase()

    /** Nom affiché de l'assistant (section assistant), « Assistant » sans elle. */
    val NOM_ASSISTANT: String = nomAssistant(json)

    /** Règle du nom de l'assistant : chaîne non vide de assistant.nom, sinon « Assistant » (section absente,
     *  vide ou mal formée). Même règle que poc/maison.py et build.gradle.kts. */
    fun nomAssistant(racine: JSONObject): String =
        ((racine.opt("assistant") as? JSONObject)?.opt("nom") as? String)?.trim()?.ifEmpty { null } ?: "Assistant"

    /** Section [cle] de maison.json, vide si absente. */
    fun section(cle: String): JSONObject = json.optJSONObject(cle) ?: JSONObject()

    /** Liste de chaînes [cle] de [o], vide si absente. */
    fun chaines(o: JSONObject, cle: String): List<String> = o.optJSONArray(cle)?.chaines() ?: emptyList()

    fun JSONArray.chaines(): List<String> = (0 until length()).map { getString(it) }
}
