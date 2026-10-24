package assistant.vocal.jarvis

import org.json.JSONObject
import kotlin.math.pow

/**
 * Palette unique de l'appli (0.18.1, demande du propriétaire) : toutes les couleurs de l'accueil de la tablette, de
 * la page 3D, des écrans Maison, Musique et Réglages et de l'AOD sont ici, par rôle, et nulle part ailleurs.
 *
 * 0.19.0 (revue design des palettes) : quatre jeux de couleurs ([JEUX]), Sobre, Pastels, Méditerranée et
 * Veillée, et un mode « Selon l'heure » ([AUTO] : Pastels le jour, Veillée du coucher au lever du soleil).
 * Chaque famille garde sa teinte dans tous les jeux (assistant bleu, lumières ambre, météo bleu ciel, pluie
 * bleu plus sombre, musique rose, santé vert) : un jeu ne change que les neutres, la luminance et la
 * saturation. Rôles, dans l'ordre de la revue : texte, texte2, texte3, heure, surface, filet, barre,
 * assistant, lumiere, meteo, pluie, musique, sante, soleil, et colonne (0.22.0, gris des barres de données). Les couleurs des autres écrans en découlent :
 * avec Sobre, ce sont celles de la 0.18.1, avec un autre jeu, elles prennent ses teintes. Le choix
 * ([choix]) se change par [choisir] (Réglages, Apparence, ou la voix), l'appli reconstruit alors son
 * interface.
 *
 * Règles qui tiennent quel que soit le jeu : fond noir pur (écran OLED), l'heure à la teinte `heure` du
 * jeu (luminance basse) et jamais plus claire, l'AOD plafonné à la luminance de ses gris d'aujourd'hui en
 * gardant seulement la teinte du jeu (PaletteTest). Depuis la palette contrastée du 22/10/2026 : l'heure
 * jamais plus claire que texte2, les accents des phrases au moins aussi clairs que texte2, le texte à
 * 18:1 au plus et jamais blanc pur, les surfaces à 1,35:1 au plus (PaletteTest aussi).
 */
internal object Palette {

    // Lecture des couleurs sans android.graphics.Color : la palette sert aussi aux tests sur la machine.
    fun c(hex: String): Int = (0xFF000000L or hex.removePrefix("#").toLong(16)).toInt()
    private fun argb(a: Int, r: Int, g: Int, b: Int): Int = (a shl 24) or (r shl 16) or (g shl 8) or b

    /** Un jeu de couleurs : un rôle par couleur, dans l'ordre de la revue design des palettes. */
    class Jeu(
        val nom: String,
        /** Ce que le jeu veut dire, sous son nom dans Réglages. */
        val esprit: String,
        val texte1: Int,
        val texte2: Int,
        val texte3: Int,
        val heure: Int,
        val surface: Int,
        val filet: Int,
        val barre: Int,
        val assistant: Int,
        val lumiere: Int,
        val meteo: Int,
        val pluie: Int,
        val musique: Int,
        val sante: Int,
        val soleil: Int,
        /** Gris des barres de données des graphes (0.22.0, 3,4 à 3,8:1 sur noir depuis le 22/10), plus clair
         *  que barre, et gris éteint des commandes de musique ([texteEteint]). */
        val colonne: Int,
    )

    private fun jeu(nom: String, esprit: String, vararg t: String): Jeu {
        require(t.size == 15)
        val v = t.map { c(it) }
        return Jeu(nom, esprit, v[0], v[1], v[2], v[3], v[4], v[5], v[6], v[7], v[8], v[9], v[10], v[11], v[12], v[13], v[14])
    }

    // Palette plus contrastée validée le 22/10/2026 (docs/maquettes/palettes.py, PALETTES, et
    // revue-accueil-musique.md, section Contraste) : mêmes teintes, seule la clarté monte. Jour : texte 17 à
    // 18:1, texte2 10:1, heure 9,8:1, colonne 3,8:1. Veillée : texte 14:1, texte2 7,6:1, colonne 3,4:1.
    val SOBRE = jeu("Sobre", "Gris et deux accents",
        "#E4E8ED", "#ADB4BD", "#8D949E", "#ABB2BB", "#1F2124", "#393D42", "#494E54",
        "#7FB2FF", "#F0B46A", "#E4E8ED", "#A4B9CE", "#E4E8ED", "#E4E8ED", "#E4E8ED", "#636A72")
    val PASTELS = jeu("Pastels", "Une teinte par famille, le jour",
        "#EEEAE2", "#BAB2A6", "#989288", "#B7B1A6", "#23211D", "#3F3C37", "#504E48",
        "#8CB1F4", "#F7B56A", "#80CBE0", "#82C0D5", "#F89DAD", "#98D9B2", "#EDD198", "#6D6861")
    val MEDITERRANEE = jeu("Méditerranée", "Plus solaire, lin et citron",
        "#F3EDE3", "#B9B3A4", "#989288", "#B8B1A3", "#23211C", "#3F3C35", "#514E46",
        "#8CB1F4", "#F7C066", "#79C3E0", "#82C0D5", "#F99EA0", "#91CEA6", "#F2D48E", "#6D695D")
    val VEILLEE = jeu("Veillée", "Atténuée, pour le soir",
        "#DCD2C5", "#A49A91", "#8A837B", "#A09990", "#1E1B18", "#36322F", "#46423D",
        "#8096D1", "#D89C67", "#78A6BE", "#82A5BB", "#D58D8B", "#7EB396", "#CDB68A", "#686058")
    /** Les quatre jeux, dans l'ordre de Réglages. */
    val JEUX = listOf(SOBRE, PASTELS, MEDITERRANEE, VEILLEE)

    /** Mode « Selon l'heure » : [PASTELS] le jour, [VEILLEE] du coucher au lever du soleil. */
    const val AUTO = "Selon l'heure"
    /** Choix possibles, dans l'ordre de « palette suivante » : les quatre jeux puis le mode Selon l'heure. */
    val CHOIX: List<String> get() = JEUX.map { it.nom } + AUTO

    /** Choix du propriétaire : le nom d'un jeu ou [AUTO]. Sobre tant que rien n'est choisi. */
    @Volatile var choix: String = SOBRE.nom
        private set
    /** Le soleil est levé (mode Selon l'heure), posé par l'écran principal. */
    @Volatile var jour: Boolean = true
        private set
    /** Jeu en vigueur : celui choisi, ou celui de l'heure en mode Selon l'heure. */
    @Volatile var jeu: Jeu = SOBRE
        private set
    private val sobre: Boolean get() = jeu === SOBRE

    /** Jeu nommé [nom] (casse et accents indifférents), ou null. */
    fun jeu(nom: String): Jeu? {
        val n = DictionnaireLocal.normaliser(nom)
        return JEUX.firstOrNull { DictionnaireLocal.normaliser(it.nom) == n }
    }

    /** Choix nommé [nom] (un jeu ou le mode Selon l'heure), écrit comme dans [CHOIX], ou null. */
    fun choixNomme(nom: String): String? {
        val n = DictionnaireLocal.normaliser(nom)
        return CHOIX.firstOrNull { DictionnaireLocal.normaliser(it) == n }
    }

    private fun enVigueur(): Jeu = if (choix == AUTO) (if (jour) PASTELS else VEILLEE) else (jeu(choix) ?: SOBRE)

    /** Choisit [nom] (un jeu ou [AUTO]). Rend vrai s'il existe (même s'il était déjà choisi). */
    fun choisir(nom: String): Boolean {
        val c = choixNomme(nom) ?: return false
        choix = c
        jeu = enVigueur()
        return true
    }

    /** Lever ou coucher du soleil : rend vrai si le jeu en vigueur change (mode Selon l'heure). */
    fun reglerJour(oui: Boolean): Boolean {
        jour = oui
        val j = enVigueur()
        if (j === jeu) return false
        jeu = j
        return true
    }

    /** Choix qui suit [nom] dans [CHOIX], en revenant au premier après le dernier. */
    fun suivant(nom: String): String {
        val l = CHOIX
        val i = l.indexOf(choixNomme(nom) ?: nom)
        return l[(i + 1).mod(l.size)]
    }

    // ------------------------------------------------ outils de couleur (sans Android)

    private fun canal(v: Int): Double { val s = v / 255.0; return if (s <= 0.04045) s / 12.92 else ((s + 0.055) / 1.055).pow(2.4) }
    private fun octet(l: Double): Int {
        val s = if (l <= 0.0031308) l * 12.92 else 1.055 * l.pow(1 / 2.4) - 0.055
        return (s * 255.0).coerceIn(0.0, 255.0).let { Math.round(it).toInt() }
    }

    /** Luminance relative (WCAG) d'une couleur opaque, de 0 (noir) à 1 (blanc). */
    fun luminance(couleur: Int): Double =
        0.2126 * canal((couleur shr 16) and 0xFF) + 0.7152 * canal((couleur shr 8) and 0xFF) + 0.0722 * canal(couleur and 0xFF)

    /** [couleur] assombrie, teinte gardée, jusqu'à la luminance [plafond] si elle la dépasse. */
    fun plafonner(couleur: Int, plafond: Double): Int {
        val l = luminance(couleur)
        if (l <= plafond || l <= 0.0) return couleur
        var k = plafond / l
        // L'arrondi à l'octet peut dépasser le plafond d'un rien : on resserre jusqu'à tenir dessous.
        while (true) {
            fun f(v: Int) = octet(canal(v) * k)
            val r = argb(0xFF, f((couleur shr 16) and 0xFF), f((couleur shr 8) and 0xFF), f(couleur and 0xFF))
            if (luminance(r) <= plafond || k <= 0.0) return r
            k *= 0.995
        }
    }

    /** Mélange de [a] vers [b], de 0 ([a]) à 1 ([b]), canal par canal. */
    fun melange(a: Int, b: Int, t: Float): Int {
        fun m(s: Int) = Math.round(((a shr s) and 0xFF) * (1 - t) + ((b shr s) and 0xFF) * t)
        return argb(0xFF, m(16), m(8), m(0))
    }

    /** Couleur d'un blanc de [kelvins] (approximation de Tanner Helland, de 1 000 à 40 000 K). */
    fun kelvin(kelvins: Int): Int {
        val t = kelvins.coerceIn(1000, 40000) / 100.0
        val r = if (t <= 66) 255.0 else 329.698727446 * (t - 60).pow(-0.1332047592)
        val g = if (t <= 66) 99.4708025861 * kotlin.math.ln(t) - 161.1195681661 else 288.1221695283 * (t - 60).pow(-0.0755148492)
        val b = when {
            t >= 66 -> 255.0
            t <= 19 -> 0.0
            else -> 138.5177312231 * kotlin.math.ln(t - 10) - 305.0447927307
        }
        fun o(v: Double) = Math.round(v.coerceIn(0.0, 255.0)).toInt()
        return argb(0xFF, o(r), o(g), o(b))
    }

    /** « #RRGGBB » d'une couleur. */
    fun hex(couleur: Int): String = "#%06X".format(couleur and 0xFFFFFF)

    private val AOD_HEURE_SOBRE = c("#5E6878")
    private val AOD_TEXTE_SOBRE = c("#4A5362")

    // ------------------------------------------------ accueil de la tablette
    /** Fond de tous les écrans de la tablette : noir pur, pixel éteint. */
    val fond = c("#000000")
    /** Texte principal (date, réponse, transcription). */
    val texte1: Int get() = jeu.texte1
    /** Texte secondaire (météo, phrases de la maison, transcription en réflexion). */
    val texte2: Int get() = jeu.texte2
    /** Texte tertiaire (écho de la commande, consignes, version). */
    val texte3: Int get() = jeu.texte3
    /** Commandes de musique au repos depuis 30 s : le gris `colonne` du jeu (3,4 à 3,8:1 sur noir, revue du 22/10). */
    val texteEteint: Int get() = jeu.colonne
    /**
     * Chiffres de l'heure et points au repos : la teinte `heure` du jeu, de luminance basse, jamais plus
     * claire (usure OLED de leurs fûts, toujours au même endroit).
     */
    val heure: Int get() = jeu.heure
    /** Filets fins (points d'état éteints, rail de la progression de la musique). */
    val filet: Int get() = jeu.filet
    /** Barres des graphes (panneaux Santé et Météo). */
    val barre: Int get() = jeu.barre
    /** Lever et coucher du soleil (futur panneau Météo). */
    val soleil: Int get() = jeu.soleil
    /** Barres de données des graphes de la santé (0.22.0). */
    val colonne: Int get() = jeu.colonne
    /** Présence de l'assistant : les deux points de l'heure à l'écoute, « Je t'écoute ». */
    val accentAssistant: Int get() = jeu.assistant
    /** Ce qui est allumé dans la maison, et la ligne de panne. */
    val accentLumiere: Int get() = jeu.lumiere
    /** La pluie, seulement. */
    val accentPluie: Int get() = jeu.pluie
    /** Valeur de la météo (« 20 degrés »), dans la phrase en texte secondaire, sauf quand la pluie est annoncée. */
    val meteo: Int get() = jeu.meteo
    /** Filet de progression de la musique sous le titre. */
    val musique: Int get() = jeu.musique
    /** Valeurs de santé du propriétaire (durée du sommeil, nombre de pas). */
    val sante: Int get() = jeu.sante
    /** Surface la plus sombre permise en dehors du noir pur (tuiles, fonds de blocs). */
    val surface: Int get() = jeu.surface
    /** Ligne choisie dans Réglages, Apparence. */
    val selection = c("#17181B")

    // ------------------------------------------------ plan 3D (page assets/maison3d)
    /**
     * Teintes de la page 3D, envoyées par assistant.teintes au chargement. Tout ce qui est éteint reste neutre
     * quel que soit le jeu, la lumière, les poussières, le flux d'une action et la pluie suivent le jeu
     * ([plan3dPalette], aussi envoyé par assistant.palette).
     */
    val plan3d: Map<String, String>
        get() = linkedMapOf(
            "fond" to "#000000",
            "murDessus" to "#2B2D31",
            "murFace" to "#1B1C1F",
            "sol" to "#141518",
            "meubleSombre" to "#222428",
            "meubleClair" to "#2E3034",
            "support" to "#26282C",
            "ampoule" to "#3A3A3A",
            "braise" to "#FF6B1F",
        ) + plan3dPalette

    /** Teintes de la page 3D qui suivent le jeu : lumière chaude (lampe sans couleur HA), poussières, flux, pluie. */
    val plan3dPalette: Map<String, String>
        get() = linkedMapOf(
            // lumière chaude d'une lampe dont Home Assistant ne donne pas la couleur (2 700 K avec Sobre)
            "lumiere" to if (sobre) "#FFA757" else hex(jeu.lumiere),
            "poussiere" to hex(jeu.lumiere),
            // flux de particules d'une action : la couleur de l'assistant qui part vers la lampe
            "flux" to if (sobre) "#6B9EFF" else hex(jeu.assistant),
            "pluie" to hex(jeu.pluie),
        )

    fun plan3dJson(): JSONObject = JSONObject().apply { for ((k, v) in plan3d) put(k, v) }
    fun plan3dPaletteJson(): JSONObject = JSONObject().apply { for ((k, v) in plan3dPalette) put(k, v) }

    // ------------------------------------------------ écran toujours allumé (AOD)
    /** Heure de l'AOD : la teinte du jeu, à moitié grise, plafonnée à la luminance du gris d'aujourd'hui. */
    val aodHeure: Int get() = if (sobre) AOD_HEURE_SOBRE else plafonner(melange(AOD_HEURE_SOBRE, jeu.heure, 0.5f), luminance(AOD_HEURE_SOBRE))
    val aodTexte: Int get() = if (sobre) AOD_TEXTE_SOBRE else plafonner(melange(AOD_TEXTE_SOBRE, jeu.texte2, 0.5f), luminance(AOD_TEXTE_SOBRE))
    val aodPoint = c("#1A2029")

    // ------------------------------------------------ écrans Maison, Musique, Réglages (et téléphone)
    val ecran = c("#121417")
    val ecranHaut = c("#171B22")
    val ecranBas = c("#0C0E11")
    /** Panneaux plein écran de la tablette (Maison, Musique, Réglages) : noir pur (revue du 22/10). */
    val panneau = c("#000000")
    val carte = c("#1E2228")
    val carteHaut = c("#242931")
    val carteBas = c("#1A1E24")
    val carteBord = c("#2E343D")
    val champ = c("#2A2F37")
    val champHaut = c("#2D333C")
    val champBas = c("#252A31")
    val champBord = c("#363D47")
    val creuxHaut = c("#111317")
    val creuxBas = c("#181B20")
    val creuxBord = c("#262A31")
    val texteReglages: Int get() = if (sobre) c("#E8EAED") else jeu.texte1
    val texteReglages2: Int get() = if (sobre) c("#9AA0A6") else jeu.texte2
    /** Accent des réglages : la couleur d'un projet d'inspiration, plafonnée pour qu'un texte blanc s'y lise toujours. */
    val accentReglages: Int get() = if (sobre) c("#4C8DFF") else plafonner(jeu.assistant, luminance(c("#4C8DFF")))
    val accentReglagesClair: Int get() = if (sobre) c("#7DB0FF") else jeu.assistant
    val bleuNuitHaut = c("#0F1B30")
    val bleuNuit = c("#0A1222")
    val bleuNuitBas = c("#060A14")
    val vert = c("#3CCB7F")
    val orange = c("#F5A623")
    val rouge = c("#E5534B")
    val gris: Int get() = if (sobre) c("#6B7280") else plafonner(jeu.texte3, luminance(c("#6B7280")))
    val grisSombre = c("#2E3A50")
    val essai = c("#F2A33A")
    val trait = c("#353B45")
    /** Ambre de l'écran Maison (tuiles allumées, filtre choisi) : la lumière du jeu. */
    val ambreMaison: Int get() = if (sobre) c("#FFC857") else jeu.lumiere
    /** Or de l'écran Musique : la musique du jeu. */
    val or: Int get() = if (sobre) c("#E6C88C") else jeu.musique
    /** Texte sur un bouton plein, et blanc des icônes de musique. */
    val texteSurAccent = c("#FFFFFF")
    /** Texte foncé posé sur un aplat clair (filtre choisi, bouton or). */
    val texteSurClair = c("#1A1408")
    val voieLlm = c("#A98BFF")
    /** Carte de réponse en verre (téléphone). */
    val carteReponse = argb(238, 9, 14, 24)
    /** Verre bleu nuit (carte de verre), du haut vers le bas. */
    val verreHaut = argb(238, 16, 26, 46)
    val verreBas = argb(238, 9, 15, 28)
    /** Ondulation au toucher des boutons, et des boutons discrets. */
    val ondulation = argb(60, 255, 255, 255)
    val ondulationDiscrete = argb(45, 255, 255, 255)
    /** Ombres portées des cartes en relief. */
    val ombre = c("#000000")
    /** Liseré d'une pastille de couleur (réglage fin d'une lampe). */
    val pastilleBord = argb(90, 255, 255, 255)

    // écran Maison connectée
    val maisonCadre3d = c("#282E3A")
    val maisonFiltre = c("#161A22")
    val maisonSousNiveau: Int get() = if (sobre) c("#161616") else jeu.surface
    val maisonSousNiveauBord = c("#1E2430")
    val tuileEteinte: Int get() = if (sobre) c("#161616") else jeu.surface
    val tuileAllumee: Int get() = if (sobre) c("#241C0E") else melange(fond, jeu.lumiere, 0.14f)
    val tuileBord = c("#222834")
    val tuileNom: Int get() = if (sobre) c("#C4CAD6") else melange(jeu.texte1, jeu.texte2, 0.3f)
    val tuileNomAllume: Int get() = if (sobre) c("#F0E2C4") else melange(jeu.texte1, jeu.lumiere, 0.3f)
    val tuileFleche: Int get() = if (sobre) c("#969EAE") else jeu.texte2
    val tuileBarre = c("#242832")

    // écran Musique
    val musiquePochette: Int get() = if (sobre) c("#161616") else jeu.surface
    val musiqueTitre: Int get() = if (sobre) c("#D6DCE8") else jeu.texte1
    val musiqueTexte: Int get() = if (sobre) c("#C8CEDA") else melange(jeu.texte1, jeu.texte2, 0.3f)
    val musiqueRail = c("#3C404A")
    val musiqueLecteur = c("#181C24")
    /** Rail de la barre de progression : blanc à 27 %. */
    val progressionRail = argb(70, 255, 255, 255)
    /** Fond des petits boutons de musique : bleu ardoise à 43 %. */
    val boutonMusique = argb(110, 40, 56, 90)
}
