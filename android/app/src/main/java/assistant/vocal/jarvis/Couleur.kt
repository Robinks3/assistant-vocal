package assistant.vocal.jarvis

/**
 * Noms historiques des couleurs des écrans (thème sombre, teintes de relief pour les dégradés). Depuis la
 * 0.18.1, ce ne sont plus que des renvois vers la palette unique ([Palette]) : aucune valeur ici. Depuis la
 * 0.19.0, des renvois lus à chaque appel, pour suivre le jeu de couleurs choisi.
 */
internal object Couleur {
    val FOND: Int get() = Palette.ecran
    /** Fond de l'écran : léger dégradé vertical, plus clair en haut. */
    val FOND_HAUT: Int get() = Palette.ecranHaut
    val FOND_BAS: Int get() = Palette.ecranBas

    val CARTE: Int get() = Palette.carte
    /** Carte en relief : haut éclairé, bas plus sombre, liseré clair. */
    val CARTE_HAUT: Int get() = Palette.carteHaut
    val CARTE_BAS: Int get() = Palette.carteBas
    val CARTE_BORD: Int get() = Palette.carteBord

    val CHAMP: Int get() = Palette.champ
    /** Sous-carte (historique, boutons secondaires). */
    val CHAMP_HAUT: Int get() = Palette.champHaut
    val CHAMP_BAS: Int get() = Palette.champBas
    val CHAMP_BORD: Int get() = Palette.champBord

    /** Rail creusé (sélecteurs, vumètre, champs) : haut plus sombre, comme une gorge. */
    val CREUX_HAUT: Int get() = Palette.creuxHaut
    val CREUX_BAS: Int get() = Palette.creuxBas
    val CREUX_BORD: Int get() = Palette.creuxBord

    val TEXTE: Int get() = Palette.texteReglages
    val TEXTE_2 = Palette.texteReglages2
    val ACCENT: Int get() = Palette.accentReglages
    val ACCENT_CLAIR: Int get() = Palette.accentReglagesClair
    val VERT: Int get() = Palette.vert
    val ORANGE: Int get() = Palette.orange
    val ROUGE: Int get() = Palette.rouge
    val GRIS: Int get() = Palette.gris
    val ESSAI: Int get() = Palette.essai
    /** Écran ambiant de la tablette (0.16.0) : fond bleu nuit de la charte Jarvis. */
    val NUIT_HAUT: Int get() = Palette.bleuNuitHaut
    val NUIT: Int get() = Palette.bleuNuit
    val NUIT_BAS: Int get() = Palette.bleuNuitBas
    /** Bleu de l'assistant, du clair au soutenu. */
    val BLEU_CLAIR: Int get() = Palette.accentAssistant
    val BLEU: Int get() = Palette.accentReglages
    /** Trait discret (rail du déroulé, séparateurs). */
    val TRAIT: Int get() = Palette.trait
    /** Écran OLED (0.17.0) : textes d'état et version en gris sombre. */
    val GRIS_SOMBRE: Int get() = Palette.grisSombre
    /** Ambre de la maison (écran Maison connectée) et or de la musique. */
    val AMBRE: Int get() = Palette.ambreMaison
    val OR: Int get() = Palette.or
    /** Fond des panneaux plein écran de la tablette : noir pur (revue de design du 22/10). */
    val PANNEAU: Int get() = Palette.panneau
}
