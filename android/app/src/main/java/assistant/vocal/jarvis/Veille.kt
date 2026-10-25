package assistant.vocal.jarvis

/**
 * Protection de l'écran OLED de la tablette (0.17.0), logique pure testée sur la machine (VeilleTest).
 * La tablette a un écran Super AMOLED allumé en permanence en station : un pixel noir est éteint et ne
 * s'use pas, un motif immobile et clair marque l'écran. Trois régimes nets, selon la présence :
 *
 * - VIVANT : quelqu'un est vu par la caméra, ou un toucher, un mot de réveil ou une commande date de
 *   moins de 2 min (ce qui tient lieu de présence quand la vision est désactivée), ou l'assistant écoute,
 *   réfléchit ou répond. Couleurs, bulles et orbe à leur taille, luminosité plafonnée à 40 % (10 % la
 *   nuit). La reprise prend 0,8 s ([DUREE_REPRISE_MS]).
 * - AOD (0.17.2, écran toujours allumé) : personne depuis 2 min, de jour. Luminosité de la fenêtre au
 *   plancher ([LUMINOSITE_MIN]), orbe réduit à un point de quelques pixels gris bleuté très foncé, et
 *   un seul petit bloc gris sombre en trait fin : l'heure, la météo, le nombre de lumières allumées.
 *   Ni bulle, ni contour, ni fond, ni texte d'état. Le bloc change de zone toutes les 3 min ([zoneAod],
 *   [placeAodX], [placeAodY]) avec un fondu lent ([opaciteAod]), en plus du décalage global. Il remplace
 *   la protection et la veille profonde de la 0.17.0. Fondu de 2 s.
 * - ETEINT : la nuit, personne depuis 2 min. Tout est noir (pixels éteints), le micro écoute toujours :
 *   présence, mot de réveil ou toucher rallument l'écran.
 *
 * 0.24.0 (demande du propriétaire : « quand elle voit mon visage, elle reprend vie, quand je lui parle, elle reprend
 * vie ») : le régime vivant a deux allures, lissées par [eclat]. Vivant plein (1) tant qu'un visage est vu, qu'on
 * touche ou qu'on parle, et [DELAI_RETRAIT_MS] après. En retrait (0) ensuite : couleurs moins saturées, fond noir
 * pur, luminosité à 75 % de son plafond. Retrait en 6 s ([DUREE_RETRAIT_MS]), retour en 0,8 s. Quand une musique
 * joue, l'AOD attend 10 min au lieu de 2 ([DELAI_PROTECTION_MUSIQUE_MS]) : quelqu'un écoute sans regarder.
 *
 * Toujours : décalage global de toute l'interface d'un pixel par minute, borné à ±12 px ([decalage]),
 * textes d'état visibles seulement au toucher ou 10 s après une commande ([textesVisibles]), places
 * des bulles échangées de gauche à droite un jour sur deux ([miroir]).
 * Horloge monotone en millisecondes (SystemClock.elapsedRealtime) : les instants sont donnés par l'appelant.
 */
class Veille {

    enum class Regime { VIVANT, AOD, ETEINT }

    var regime = Regime.VIVANT
        private set
    /** 1 : écran vivant, 0 : AOD. Lissé : 0,8 s pour reprendre vie, 2 s pour s'éteindre. */
    var vie = 1f
        private set
    /** 1 : vivant plein (visage, toucher, voix depuis moins de 30 s), 0 : en retrait. Lissé : 0,8 s pour revenir, 6 s pour partir. */
    var eclat = 1f
        private set
    /** Cible d'[eclat] : vivant plein (vrai) ou en retrait (faux), sans lissage. */
    var actif = true
        private set
    /** 1 : tout est noir (nuit, personne). Lissé sur 2 s. */
    var noir = 0f
        private set
    /** Instant du dernier passage au régime vivant, pour rallumer les bulles l'une après l'autre. */
    var repriseLe = 0L
        private set
    /** Dernier instant de vie : présence vue, activité, commande en cours. */
    var derniereVieLe = 0L
        private set
    /** Dernier instant où une commande était en cours (écoute, réflexion, réponse). */
    var derniereCommandeLe = 0L
        private set

    private var dernierPas = -1L

    /**
     * Avance jusqu'à [maintenant]. [presence] : quelqu'un est vu par la caméra (faux sans vision).
     * [activiteLe] : dernier toucher, mot de réveil ou commande (0 : jamais). [occupe] : l'assistant
     * écoute, réfléchit ou répond. [musique] : une musique joue (AOD au bout de 10 min au lieu de 2). Rend vrai
     * tant qu'une transition est en cours (images à suivre).
     */
    fun avancer(maintenant: Long, presence: Boolean, activiteLe: Long, occupe: Boolean, nuit: Boolean, musique: Boolean = false): Boolean {
        if (dernierPas < 0L) {
            // Premier appel : l'écran s'ouvre vivant, comme après un toucher.
            derniereVieLe = maintenant
            dernierPas = maintenant
        }
        if (presence || occupe) derniereVieLe = maintenant
        if (activiteLe > derniereVieLe) derniereVieLe = minOf(activiteLe, maintenant)
        if (occupe) derniereCommandeLe = maintenant
        val calme = maintenant - derniereVieLe
        val nouveau = when {
            presence || occupe || calme < (if (musique) DELAI_PROTECTION_MUSIQUE_MS else DELAI_PROTECTION_MS) -> Regime.VIVANT
            nuit -> Regime.ETEINT
            else -> Regime.AOD
        }
        if (nouveau == Regime.VIVANT && regime != Regime.VIVANT) repriseLe = maintenant
        regime = nouveau

        val dt = (maintenant - dernierPas).coerceIn(0L, 1000L).toFloat()
        dernierPas = maintenant
        vie = if (regime == Regime.VIVANT) minOf(1f, vie + dt / DUREE_REPRISE_MS) else maxOf(0f, vie - dt / DUREE_FONDU_MS)
        noir = if (regime == Regime.ETEINT) minOf(1f, noir + dt / DUREE_FONDU_MS) else maxOf(0f, noir - dt / DUREE_REPRISE_MS)
        actif = regime == Regime.VIVANT && (presence || occupe || calme < DELAI_RETRAIT_MS)
        eclat = if (actif) minOf(1f, eclat + dt / DUREE_REPRISE_MS) else maxOf(0f, eclat - dt / DUREE_RETRAIT_MS)
        return (vie > 0f && vie < 1f) || (noir > 0f && noir < 1f) || (eclat > 0f && eclat < 1f)
    }

    /**
     * Luminosité de la fenêtre : plafond en régime vivant (40 %, 10 % la nuit), 75 % de ce plafond en retrait
     * (40 à 30 %, 0.24.0), plancher en AOD et éteint.
     */
    fun luminosite(nuit: Boolean): Float = luminositeAvec(if (nuit) LUMINOSITE_NUIT else LUMINOSITE_PLAFOND)

    /**
     * Même chose avec le plafond du vivant plein donné par l'appelant (0.28.0 : la lumière de la pièce,
     * LumiereAmbiante). Retrait, AOD et écran éteint inchangés.
     */
    fun luminositeAvec(plafondVivant: Float): Float {
        val plafond = plafondVivant * (RETRAIT_LUMINOSITE + (1f - RETRAIT_LUMINOSITE) * eclat)
        val plancher = LUMINOSITE_MIN * (1f - noir)
        return plancher + (plafond - plancher) * vie
    }

    /** Textes d'état et version : visibles au toucher ou pendant 10 s après une commande. */
    fun textesVisibles(maintenant: Long, toucherLe: Long): Boolean =
        regime == Regime.VIVANT && maintenant - maxOf(toucherLe, derniereCommandeLe) < DUREE_TEXTES_MS

    companion object {
        const val DELAI_PROTECTION_MS = 2 * 60_000L
        /** Une musique joue : l'AOD attend 10 min (choix du propriétaire, 0.24.0). */
        const val DELAI_PROTECTION_MUSIQUE_MS = 10 * 60_000L
        /** Vivant plein 30 s après le dernier visage, toucher ou mot, puis en retrait (0.24.0). */
        const val DELAI_RETRAIT_MS = 30_000L
        /** Retrait lent, pour qu'on ne le remarque pas. */
        const val DUREE_RETRAIT_MS = 6000f
        /** En retrait, la luminosité tombe à 75 % de son plafond. */
        const val RETRAIT_LUMINOSITE = 0.75f
        const val DUREE_REPRISE_MS = 800f
        const val DUREE_FONDU_MS = 2000f
        const val DUREE_TEXTES_MS = 10_000L
        /** Les bulles se rallument l'une après l'autre, à cet écart. */
        const val ECART_BULLES_MS = 120L
        const val LUMINOSITE_PLAFOND = 0.40f
        const val LUMINOSITE_NUIT = 0.10f
        /**
         * Plancher de la fenêtre (0.17.2) : 0, soit WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_OFF
         * (PowerManager.BRIGHTNESS_MIN), la valeur la plus basse que la fenêtre accepte. Les sources du
         * SDK 36.1 la décrivent comme « la plus basse », pas comme écran éteint : Android la ramène au
         * minimum de la dalle. Tout nombre négatif annulerait la consigne et rendrait la luminosité
         * choisie dans les paramètres. La 0.17.0 s'arrêtait à 1 %.
         */
        const val LUMINOSITE_MIN = 0f
        /** Décalage global : ±24 px depuis la 0.18.1 (revue de design, ±12 avant), 49 positions par axe. */
        const val BORNE_PX = 24
        private const val COTE = 2 * BORNE_PX + 1
        private const val CASES = COTE * COTE
        /** Aller puis retour sur le même chemin : 4 800 minutes, 80 h. */
        const val PERIODE_MIN = 2 * CASES - 2

        /**
         * Décalage global (x, y) en pixels pour la minute [minute] (minutes depuis 1970) : un pixel par
         * minute, en serpentin dans le carré de ±24 px (une rangée de gauche à droite, la suivante de
         * droite à gauche), puis retour par le même chemin. Deux minutes voisines diffèrent d'un pixel.
         */
        fun decalage(minute: Long): Pair<Int, Int> {
            val p = Math.floorMod(minute, PERIODE_MIN.toLong()).toInt()
            val q = if (p < CASES) p else PERIODE_MIN - p
            val rangee = q / COTE
            val colonne = q % COTE
            val x = if (rangee % 2 == 0) colonne else COTE - 1 - colonne
            return (x - BORNE_PX) to (rangee - BORNE_PX)
        }

        /**
         * Un jour sur deux, la disposition change ([jour] : jours depuis 1970). Depuis la 0.18.1, plus de
         * miroir : la colonne de gauche de l'accueil passe de x 72 à x 120 (pixels de maquette) et le plan
         * 3D se décale de 60 px, pour répartir l'usure.
         */
        fun miroir(jour: Long): Boolean = Math.floorMod(jour, 2L) == 1L

        /** Dérive propre au bloc de l'heure (0.18.1) : ±42 px sur x en 50 min, ±24 px sur y en 43 min. */
        const val DERIVE_HEURE_X_PX = 42f
        const val DERIVE_HEURE_Y_PX = 24f
        const val PERIODE_DERIVE_X_MS = 50 * 60_000L
        const val PERIODE_DERIVE_Y_MS = 43 * 60_000L

        /**
         * Dérive de l'heure (x, y) en pixels réels à l'instant [instant] (millisecondes depuis 1970), en plus
         * du décalage global : le décalage d'un pixel par minute ne suffit pas à protéger les fûts des
         * chiffres, qui restent allumés au même endroit. Deux sinusoïdes de périodes premières entre elles,
         * lentes (au plus 5,3 px par minute) : le bloc ne revient au même point qu'au bout de 36 h environ.
         */
        fun deriveHeure(instant: Long): Pair<Float, Float> {
            val ax = 2.0 * Math.PI * Math.floorMod(instant, PERIODE_DERIVE_X_MS) / PERIODE_DERIVE_X_MS
            val ay = 2.0 * Math.PI * Math.floorMod(instant, PERIODE_DERIVE_Y_MS) / PERIODE_DERIVE_Y_MS
            return (DERIVE_HEURE_X_PX * kotlin.math.sin(ax)).toFloat() to (DERIVE_HEURE_Y_PX * kotlin.math.sin(ay + 1.0)).toFloat()
        }

        /** Allumage d'une bulle de rang [rang] au moment [depuisReprise] (ms) après la reprise, de 0 à 1 sur 600 ms. */
        fun allumage(rang: Int, depuisReprise: Long): Float =
            ((depuisReprise - rang * ECART_BULLES_MS) / 600f).coerceIn(0f, 1f)

        // ------------------------------------------------------------ écran AOD (0.17.2)

        /** Le bloc AOD change de zone toutes les 3 min, fondu lent de 2,5 s à la sortie et à l'entrée. */
        const val PERIODE_AOD_MS = 3 * 60_000L
        const val FONDU_AOD_MS = 2_500L
        /**
         * Zones du bloc : grille de 3 sur 3, numérotée de gauche à droite et de haut en bas, sans la case
         * du centre où reste le point de l'orbe.
         */
        val ZONES_AOD = intArrayOf(0, 1, 2, 3, 5, 6, 7, 8)
        /** Marge du bloc AOD au bord de sa vue, en dp. */
        const val MARGE_AOD_DP = 28f

        /** Gris de l'AOD : peu saturés et sombres (VeilleTest : rien de coloré, aucun aplat clair). */
        val GRIS_AOD_HEURE: Int get() = Palette.aodHeure
        val GRIS_AOD_TEXTE: Int get() = Palette.aodTexte
        /** Point de l'orbe en AOD : gris bleuté très foncé, quelques pixels, sans halo. */
        val GRIS_AOD_POINT: Int = Palette.aodPoint
        val COULEURS_AOD: IntArray get() = intArrayOf(GRIS_AOD_HEURE, GRIS_AOD_TEXTE, GRIS_AOD_POINT)
        /** Rayon du point de l'orbe en AOD, en dp (environ 3 px sur la tablette). */
        const val RAYON_POINT_AOD_DP = 1.5f

        /** Période AOD de l'instant [instant] (millisecondes depuis 1970). */
        fun periodeAod(instant: Long): Long = Math.floorDiv(instant, PERIODE_AOD_MS)

        /**
         * Zone (0 à 8, jamais 4) du bloc pour la période [periode]. Les huit zones sont toutes visitées
         * en 24 min, chaque tour commence trois zones plus loin que le précédent, et deux périodes
         * voisines ne tombent jamais dans la même zone (même au passage d'un tour au suivant).
         */
        fun zoneAod(periode: Long): Int {
            val n = ZONES_AOD.size.toLong()
            val tour = Math.floorDiv(periode, n)
            val rang = Math.floorMod(Math.floorMod(periode, n) + 3L * Math.floorMod(tour, n), n).toInt()
            return ZONES_AOD[rang]
        }

        /** Fraction pseudo-aléatoire stable (0,15 à 0,85) pour la période [periode], tirée par [sel]. */
        private fun fraction(periode: Long, sel: Int): Float {
            var h = periode * 0x9E3779B97F4A7C15uL.toLong() + sel * 0x632BE59BD9B4E019L
            h = h xor (h ushr 31)
            h *= 0x5851F42D4C957F2DL
            h = h xor (h ushr 29)
            val u = (h ushr 40).toFloat() / (1L shl 24).toFloat()
            return 0.15f + 0.7f * u
        }

        /**
         * Abscisse du coin gauche du bloc AOD ([taille] de large) dans une vue de [etendue], pendant la
         * période [periode] : dans le tiers de sa zone, à une place tirée au sort, toujours à [marge] au
         * moins des bords. Un bloc plus large que la place disponible est centré.
         */
        fun placeAodX(periode: Long, etendue: Float, taille: Float, marge: Float): Float =
            place(zoneAod(periode) % 3, fraction(periode, 1), etendue, taille, marge)

        /** Ordonnée du haut du bloc AOD, comme [placeAodX] sur l'autre axe. */
        fun placeAodY(periode: Long, etendue: Float, taille: Float, marge: Float): Float =
            place(zoneAod(periode) / 3, fraction(periode, 2), etendue, taille, marge)

        private fun place(tiers: Int, f: Float, etendue: Float, taille: Float, marge: Float): Float {
            val libre = etendue - 2f * marge - taille
            if (libre <= 0f) return ((etendue - taille) / 2f).coerceAtLeast(0f)
            return marge + libre * (tiers + f) / 3f
        }

        /** Opacité du bloc AOD à l'instant [instant] : fondu de sortie avant chaque changement de zone, d'entrée après. */
        fun opaciteAod(instant: Long): Float {
            val t = Math.floorMod(instant, PERIODE_AOD_MS)
            val bord = minOf(t, PERIODE_AOD_MS - t).toFloat()
            return (bord / FONDU_AOD_MS).coerceIn(0f, 1f)
        }

        /** Attente (ms) avant la prochaine image utile du bloc AOD : pendant un fondu, 15 images par seconde. */
        fun attenteAod(instant: Long): Long {
            val t = Math.floorMod(instant, PERIODE_AOD_MS)
            return if (t < FONDU_AOD_MS || t > PERIODE_AOD_MS - FONDU_AOD_MS) 66L
            else (PERIODE_AOD_MS - FONDU_AOD_MS - t).coerceAtLeast(1L)
        }

        /** Saturation et luminosité (0 à 1, au sens TSL) d'une couleur ARGB, pour vérifier les gris de l'AOD. */
        fun saturationLuminosite(c: Int): Pair<Float, Float> {
            val r = ((c shr 16) and 0xff) / 255f
            val g = ((c shr 8) and 0xff) / 255f
            val b = (c and 0xff) / 255f
            val max = maxOf(r, g, b)
            val min = minOf(r, g, b)
            val l = (max + min) / 2f
            val d = max - min
            val s = if (d == 0f) 0f else d / (1f - kotlin.math.abs(2f * l - 1f))
            return s to l
        }
    }
}
