package assistant.vocal.jarvis

/**
 * Confirmation du mot de réveil au repos (0.51.0, faux réveils signalés le 02/11/2026). Un seul bloc de 80 ms
 * au-dessus du seuil lançait l'écoute : un mot de la télé ou d'une conversation qui ressemblait au mot suffisait.
 * Il faut désormais [blocsScore] blocs de suite au-dessus du seuil, et de la parole vue par Silero VAD dans les
 * [memoireVoix] derniers blocs (le score culmine à la fin du mot, la parole est donc juste avant).
 * Sans Silero (voix à null), seule la suite de blocs compte.
 */
class ConfirmationReveil(
    private val blocsScore: Int = BLOCS_SCORE,
    private val memoireVoix: Int = MEMOIRE_VOIX,
) {
    private var suite = 0
    private var depuisVoix = JAMAIS

    /** Raison du dernier refus, pour le journal : null tant qu'aucun bloc n'a passé le seuil. */
    var refus: String? = null
        private set

    /** Un bloc : vrai quand le réveil est confirmé, et l'état repart alors de zéro. */
    fun bloc(score: Float, seuil: Float, voix: Boolean?): Boolean {
        depuisVoix = when {
            voix == true -> 0
            depuisVoix == JAMAIS -> JAMAIS
            else -> depuisVoix + 1
        }
        if (score < seuil) {
            suite = 0
            return false
        }
        suite++
        if (voix != null && depuisVoix >= memoireVoix) {
            refus = "pas de parole vue par Silero"
            return false
        }
        if (suite < blocsScore) {
            refus = "un seul bloc au-dessus du seuil"
            return false
        }
        reinitialiser()
        return true
    }

    fun reinitialiser() {
        suite = 0
        depuisVoix = JAMAIS
        refus = null
    }

    companion object {
        const val BLOCS_SCORE = 2
        /** 15 blocs de 80 ms, 1,2 s : la durée du mot entendu par le modèle (1,28 s). */
        const val MEMOIRE_VOIX = 15
        private const val JAMAIS = Int.MAX_VALUE
    }
}
