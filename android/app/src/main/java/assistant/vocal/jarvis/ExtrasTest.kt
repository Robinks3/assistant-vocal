package assistant.vocal.jarvis

/**
 * Extras d'intention `test_*` de MainActivity (S-D5, I11) : ils lancent le banc du mot de réveil, du LLM de
 * l'appareil et de Canary depuis `adb shell am start`. MainActivity est exportée, donc n'importe quelle appli du
 * téléphone pourrait les envoyer : ils ne sont lus que dans un build de débogage. La décision est ici, pure,
 * pour que les tests unitaires l'éprouvent sans Android.
 */
object ExtrasTest {
    const val REVEIL = "test_reveil"
    const val LLM = "test_llm"
    const val MODELE = "modele"
    const val CANARY = "test_canary"
    const val FILS = "fils"
    const val FILS_PAR_DEFAUT = 4

    /** Ce que l'intention demande de lancer. Chaque champ vaut null quand l'extra manque ou n'est pas lisible. */
    data class Demande(val reveil: String?, val llm: String?, val modele: String?, val canary: String?, val fils: Int) {
        val vide: Boolean get() = reveil == null && llm == null && canary == null
    }

    private val SANS_DEMANDE = Demande(null, null, null, null, FILS_PAR_DEFAUT)

    /**
     * Extras à honorer. [debug] vaut BuildConfig.DEBUG : faux (build de publication), rien n'est lu, pas même par
     * [texte] ou [entier]. [texte] et [entier] lisent un extra de l'intention (nom, valeur par défaut pour l'entier).
     */
    fun lisibles(debug: Boolean, texte: (String) -> String?, entier: (String, Int) -> Int): Demande {
        if (!debug) return SANS_DEMANDE
        return Demande(texte(REVEIL), texte(LLM), texte(MODELE), texte(CANARY), entier(FILS, FILS_PAR_DEFAUT))
    }
}
