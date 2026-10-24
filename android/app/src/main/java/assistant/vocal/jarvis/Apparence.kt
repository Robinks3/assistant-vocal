package assistant.vocal.jarvis

import android.content.Context

/**
 * Choix de la palette (0.19.0) : retenu dans les préférences de l'appli, et compris à la voix sans le LLM ni
 * le dictionnaire du serveur, avant lui, par le moteur de la tablette (MoteurLocal) : « mets la palette
 * Méditerranée », « palette veillée » choisissent un jeu, « palette selon l'heure » le mode automatique,
 * « palette suivante » ou « change de palette » passent au choix suivant (Palette.CHOIX).
 */
internal object Apparence {

    private const val PREFS = "apparence"
    private const val CLE_PALETTE = "palette"

    /** Applique la palette retenue (Sobre par défaut). À appeler avant de construire une interface. */
    fun charger(ctx: Context) {
        val nom = ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).getString(CLE_PALETTE, null) ?: return
        Palette.choisir(nom)
    }

    /** Choisit et retient [nom] (un jeu ou le mode Selon l'heure). Rend faux s'il n'existe pas. */
    fun enregistrer(ctx: Context, nom: String): Boolean {
        if (!Palette.choisir(nom)) return false
        ctx.getSharedPreferences(PREFS, Context.MODE_PRIVATE).edit().putString(CLE_PALETTE, Palette.choix).apply()
        return true
    }

    /** Demande comprise : un choix nommé (un jeu ou Palette.AUTO), ou le suivant ([nom] nul). */
    data class Demande(val nom: String?)

    private val CHANGER = setOf("change", "changer", "changes", "suivante", "autre", "prochaine", "nouvelle")
    /** Au-delà, la phrase dit autre chose qu'un choix de palette. */
    private const val MOTS_MAX = 8

    private fun proche(mot: String, cible: String, seuil: Double = 0.8): Boolean =
        mot == cible || (mot.length >= 4 && DictionnaireLocal.ratio(mot, cible) >= seuil)

    /**
     * La phrase [entendu] demande-t-elle une palette ? Il faut le mot « palette » (à une faute près) et soit le
     * nom d'un jeu (à une faute près, « pastel » pour Pastels), soit un mot de changement. Sinon null, et la
     * phrase suit son chemin habituel.
     */
    fun commande(entendu: String): Demande? {
        val mots = DictionnaireLocal.normaliser(DictionnaireLocal.epurer(entendu)).split(" ").filter { it.isNotEmpty() }
        if (mots.isEmpty() || mots.size > MOTS_MAX) return null
        if (mots.none { proche(it, "palette") || it == "palettes" }) return null
        val phrase = mots.joinToString(" ")
        if ("selon l heure" in phrase || "automatique" in mots || "auto" in mots) return Demande(Palette.AUTO)
        val noms = Palette.JEUX.map { it to DictionnaireLocal.normaliser(it.nom) }
        for (m in mots) {
            if (proche(m, "palette")) continue
            noms.firstOrNull { (_, n) -> proche(m, n) }?.let { return Demande(it.first.nom) }
        }
        if (mots.any { it in CHANGER }) return Demande(null)
        return null
    }

    /**
     * Le soleil est-il levé à [maintenant] (millisecondes depuis 1970) ? D'après la dernière lecture de sun.sun
     * ([soleil]) et les lever et coucher passés depuis. Sans lecture ou lecture de plus de 24 h, de 7 h à 19 h
     * ([heure] locale).
     */
    fun jour(soleil: Etat.Soleil?, maintenant: Long, heure: Int): Boolean {
        // Sans lecture, ou lecture de plus de 24 h (0.21.1) : de 7 h à 19 h.
        if (soleil == null || (soleil.luLe != null && maintenant - soleil.luLe > 24 * 3_600_000L)) return heure in 7 until 19
        var leve = soleil.leve
        val passes = listOfNotNull(soleil.lever?.let { it to true }, soleil.coucher?.let { it to false })
            .filter { it.first <= maintenant }
            .sortedBy { it.first }
        for ((_, v) in passes) leve = v
        return leve
    }

    /** Réponse dite après le choix. */
    fun reponse(nom: String): String = if (nom == Palette.AUTO) "Palette selon l'heure." else "Palette $nom."
}
