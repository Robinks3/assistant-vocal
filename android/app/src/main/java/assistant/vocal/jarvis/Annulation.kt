package assistant.vocal.jarvis

/**
 * Annuler la réflexion d'un appui sur l'écran (0.52.0, demande du 10/11/2026), logique pure testée sur la machine
 * (AnnulationTest), commune au mode « Cet appareil » ([MoteurLocal]) et au mode serveur ([SatelliteService]).
 *
 * Deux gestes : l'heure veut toujours dire « je reparle », le reste de l'écran « stop ».
 * - Repos : l'heure lance l'écoute, le reste de l'écran garde ses fonctions (non capté).
 * - Écoute : tout appui arrête l'écoute, rien n'est transcrit (geste d'avant, inchangé).
 * - Réflexion : l'heure annule et relance l'écoute avec son son de début, ailleurs annule et revient au repos en
 *   silence. L'appui ailleurs est avalé : il n'ouvre ni le plan, ni la météo, ni la santé.
 * - Réponse : l'heure coupe la voix et relance l'écoute, ailleurs coupe la voix et revient au repos.
 * Aucun son d'annulation : « Annulé » s'affiche sous l'heure. Une action déjà partie vers Home Assistant n'est pas
 * défaite (pas d'inverse fiable) : « Annulé, déjà fait : ... » la rappelle, et l'historique garde la ligne.
 */
object Annulation {

    /** Ce que fait l'assistant au moment de l'appui. */
    enum class Moment { REPOS, ECOUTE, REFLEXION, REPONSE, AUTRE }

    enum class Geste { ECOUTER, ARRETER_ECOUTE, ANNULER_REFLEXION, COUPER_ET_REECOUTER, COUPER, RIEN }

    /** Message bref sous l'heure. */
    const val MESSAGE = "Annulé"
    /** Marque d'une action non envoyée parce que la commande a été annulée (même mot que le serveur). */
    const val SUFFIXE = " (annulé)"
    /** Réponse gardée dans l'historique pour une commande annulée. */
    const val REPONSE = "(annulée par un appui, rien n'a été dit)"

    /** Geste pour un appui à ce [moment], sur l'heure ([surHeure]) ou ailleurs. */
    fun geste(moment: Moment, surHeure: Boolean): Geste = when (moment) {
        Moment.REPOS -> if (surHeure) Geste.ECOUTER else Geste.RIEN
        Moment.ECOUTE -> Geste.ARRETER_ECOUTE
        Moment.REFLEXION -> Geste.ANNULER_REFLEXION
        Moment.REPONSE -> if (surHeure) Geste.COUPER_ET_REECOUTER else Geste.COUPER
        Moment.AUTRE -> Geste.RIEN
    }

    /** Moment d'après le texte d'état de l'écran ([Etat.Instantane.assistant]). */
    fun moment(assistant: String): Moment = when (assistant) {
        "Repos" -> Moment.REPOS
        "Je t'écoute" -> Moment.ECOUTE
        "Je réfléchis" -> Moment.REFLEXION
        "Je réponds" -> Moment.REPONSE
        else -> Moment.AUTRE
    }

    /** L'écran prend tout appui (avant les panneaux) pendant l'écoute, la réflexion et la réponse. */
    fun capte(assistant: String): Boolean = moment(assistant) in setOf(Moment.ECOUTE, Moment.REFLEXION, Moment.REPONSE)

    /** La commande traitée par le fil de travail n'est plus la commande en cours : elle a été annulée. */
    fun annulee(commandeDuFil: Int, numeroCommande: Int): Boolean = commandeDuFil != numeroCommande

    /** Détail de la voie dans l'historique pour une commande annulée. */
    fun detail(detail: String): String = if (detail.isBlank()) "annulé par un appui" else "$detail, annulé par un appui"

    private val NON_FAIT = Regex("""\((refusé|annulé|non exécuté|écartée|non joué|essai)[^)]*\)\s*$""")

    /** Lignes « Fait » d'actions vraiment parties : ni refusées, ni annulées, ni en essai, ni écartées. */
    fun faites(fait: List<String>): List<String> =
        fait.filter { it.isNotBlank() && !it.startsWith("rien fait") && !NON_FAIT.containsMatchIn(it) }

    /** « Annulé, déjà fait : ... » pour des actions déjà lisibles, ou null s'il n'y en a aucune. */
    fun message(lisibles: List<String>): String? =
        lisibles.filter { it.isNotBlank() }.takeIf { it.isNotEmpty() }?.let { "$MESSAGE, déjà fait : " + it.joinToString(", ") }
}
