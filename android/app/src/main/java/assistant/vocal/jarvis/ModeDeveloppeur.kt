package assistant.vocal.jarvis

import android.content.Context

/**
 * Mode développeur (0.48.0) : montre ou cache tout ce qui sert au débogage dans l'appli (numéro de version et date de
 * compilation, durées en ms, compteurs, états de connexion détaillés, identifiants techniques, déroulé des étapes).
 *
 * Une seule clé, dans les préférences de l'interface, lue ici et nulle part ailleurs. Par défaut le mode est actif,
 * y compris sur une installation qui n'a jamais enregistré la clé : rien ne change tant que personne ne le coupe.
 * Couper le mode ne touche à rien d'autre. La sécurité en dur (Securite.kt) n'en dépend pas.
 */
internal object ModeDeveloppeur {
    /** Mêmes préférences que le reste de l'interface (MainActivity.PREFS_INTERFACE). */
    const val PREFS = "interface"
    const val CLE = "mode_developpeur"
    const val DEFAUT = true

    /** Valeur effective d'une clé lue dans les préférences, null quand elle n'a jamais été enregistrée. */
    fun valeur(enregistre: Boolean?): Boolean = enregistre ?: DEFAUT

    fun actif(ctx: Context): Boolean {
        val p = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE)
        return valeur(if (p.contains(CLE)) p.getBoolean(CLE, DEFAUT) else null)
    }

    fun enregistrer(ctx: Context, actif: Boolean) {
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putBoolean(CLE, actif).apply()
    }

    /** Version et date de compilation : vides quand le mode est coupé. */
    fun libelleVersion(actif: Boolean, libelle: String): String = if (actif) libelle else ""

    /**
     * Texte de la caméra. Mode coupé : les cadences et les ms par image disparaissent, il reste « Caméra active ».
     * Une erreur garde son message, c'est une information utile.
     */
    fun visionEtat(actif: Boolean, etat: String, niveau: String): String = when {
        actif -> etat
        niveau == "ok" || niveau == "attente" -> "Caméra active"
        else -> etat
    }

    /** Durée d'une réponse (« Répondu en 1,20 s ») : absente quand le mode est coupé. */
    fun dureeReponse(actif: Boolean, texte: String): String = if (actif) texte else ""

    /** Seuil de réveil : le nombre n'est montré qu'en mode développeur. */
    fun seuilReveil(actif: Boolean, nombre: String): String = if (actif) "Seuil de réveil : $nombre" else "Sensibilité du réveil"

    /**
     * Ligne d'état du serveur. Mode coupé : « Connecté » ou « Non connecté », sans version, passerelle ni détail de
     * liaison. [detaille] est la ligne complète du mode développeur.
     */
    fun serveurEtat(actif: Boolean, connecte: Boolean, detaille: String): String = when {
        actif -> detaille
        connecte -> "Connecté"
        else -> "Non connecté"
    }

    /** Détail de la connexion (message technique du satellite) : vide quand le mode est coupé. */
    fun detailConnexion(actif: Boolean, detail: String): String = if (actif) detail else ""
}
