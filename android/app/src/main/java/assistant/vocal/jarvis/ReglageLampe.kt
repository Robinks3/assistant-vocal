package assistant.vocal.jarvis

import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * Réglages fins d'une lampe (0.34.0) : blancs nommés, couleurs nommées, bornes de la piste de chaleur, mot de
 * chaleur et conformité de la lecture (kelvins à 100 K près, teinte à 8 degrés près, bouclage autour de 0°).
 * Rien d'Android ici, pour que les tests tournent sur la machine.
 */
internal object ReglageLampe {
    class Blanc(val nom: String, val kelvin: Int, val rgb: Int)
    class Teinte(val nom: String, val degres: Int)

    const val KELVIN_CHAUD = 2700
    const val KELVIN_FROID = 6500
    const val TOLERANCE_KELVIN = 100
    const val TOLERANCE_TEINTE = 8f

    /** Les quatre blancs du volet. Bougie vaut 2202 K sur une lampe qui ne descend pas plus bas, et s'affiche tel quel. */
    val BLANCS = listOf(
        Blanc("Bougie", 2200, 0xFFF6A25A.toInt()),
        Blanc("Chaud", 2700, 0xFFF7B97A.toInt()),
        Blanc("Neutre", 4000, 0xFFF7E3C8.toInt()),
        Blanc("Froid", 6000, 0xFFCFE0F7.toInt()),
    )

    /** Les huit couleurs nommées, envoyées en hs_color (teinte, saturation 100) pour rester neutres vis-à-vis de la luminosité. */
    val TEINTES = listOf(
        Teinte("Rouge", 0), Teinte("Orange", 30), Teinte("Jaune", 55), Teinte("Vert", 120),
        Teinte("Cyan", 180), Teinte("Bleu", 220), Teinte("Violet", 275), Teinte("Rose", 330),
    )

    private val MODES_COULEUR = setOf("hs", "xy", "rgb", "rgbw", "rgbww")

    fun modeCouleur(mode: String) = mode in MODES_COULEUR

    /** Bornes de la piste : celles de la lampe, sinon 2700 à 6500 K. */
    fun bornes(a: Appareils.Appareil): Pair<Int, Int> {
        val k0 = if (a.kelvinMin > 0) a.kelvinMin else KELVIN_CHAUD
        val k1 = if (a.kelvinMax > k0) a.kelvinMax else maxOf(KELVIN_FROID, k0 + 1)
        return k0 to k1
    }

    fun kelvinDe(a: Appareils.Appareil, fraction: Float): Int {
        val (k0, k1) = bornes(a)
        return (k0 + (k1 - k0) * fraction.coerceIn(0f, 1f)).roundToInt()
    }

    fun fractionDe(a: Appareils.Appareil, kelvin: Int): Float {
        val (k0, k1) = bornes(a)
        return ((kelvin - k0).toFloat() / (k1 - k0)).coerceIn(0f, 1f)
    }

    fun mot(kelvin: Int): String = when {
        kelvin < 2450 -> "bougie"
        kelvin < 3300 -> "chaud"
        kelvin < 4800 -> "neutre"
        else -> "froid"
    }

    /** Sous le nom d'une lampe en blanc : « 2700 K chaud ». Null en couleur, éteinte ou sans lecture. */
    fun blancAffiche(a: Appareils.Appareil): String? {
        if (!a.allume || modeCouleur(a.mode)) return null
        val k = a.kelvin ?: return null
        return "$k K ${mot(k)}"
    }

    /** Une lampe allumée en couleur (sa pastille prend sa teinte). */
    fun enCouleur(a: Appareils.Appareil) = a.allume && modeCouleur(a.mode)

    /** Ce que fait un toucher sur la ligne (hors rond et piste) : déplier le volet si la lampe se règle, sinon bascule. */
    enum class Geste { DEPLIER, BASCULER }

    fun gesteLigne(a: Appareils.Appareil?, horsLigne: Boolean): Geste =
        if (!horsLigne && a != null && (a.couleur || a.blanc)) Geste.DEPLIER else Geste.BASCULER

    /**
     * Onglet montré à l'ouverture du volet : true pour Couleur. Une lampe qui ne fait que l'un des deux n'a pas le choix,
     * sinon le choix fait au doigt, sinon le mode de la lampe (Couleur si elle est allumée en couleur, Blanc sinon).
     */
    fun surCouleur(a: Appareils.Appareil, choix: Boolean?): Boolean = when {
        !a.blanc -> true
        !a.couleur -> false
        else -> choix ?: enCouleur(a)
    }

    /**
     * Valeur montrée en tête du volet : « 2700 K chaud » en Blanc, le nom de la couleur en Couleur. Une lampe éteinte
     * garde la dernière valeur connue, sans quoi le volet dit « éteinte » plutôt que de rester vide.
     */
    fun valeurVolet(a: Appareils.Appareil, surCouleur: Boolean): String {
        val v = if (surCouleur) a.teinte?.let { nomTeinte(it) } else a.kelvin?.let { "$it K ${mot(it)}" }
        return v ?: if (a.allume) "" else "éteinte"
    }

    /** Nom de la couleur nommée la plus proche d'une teinte, pour la valeur affichée dans l'onglet Couleur. */
    fun nomTeinte(degres: Float): String = TEINTES.minBy { ecartTeinte(it.degres.toFloat(), degres) }.nom

    /** Teinte en degrés (0 à 360) d'une couleur RVB, ou null pour un gris. */
    fun teinteDeRgb(rgb: List<Int>): Float? {
        if (rgb.size < 3) return null
        val r = rgb[0] / 255f
        val g = rgb[1] / 255f
        val b = rgb[2] / 255f
        val mx = maxOf(r, g, b)
        val d = mx - minOf(r, g, b)
        if (d < 0.02f) return null
        val h = when (mx) {
            r -> ((g - b) / d) % 6f
            g -> (b - r) / d + 2f
            else -> (r - g) / d + 4f
        } * 60f
        return if (h < 0) h + 360f else h
    }

    /** RVB (0 à 255) d'une teinte à pleine saturation et pleine valeur, pour le prévu et les pastilles. */
    fun rgbDeTeinte(degres: Float, saturation: Float = 1f): List<Int> {
        val h = ((degres % 360f) + 360f) % 360f / 60f
        val c = saturation
        val x = c * (1f - abs(h % 2f - 1f))
        val m = 1f - c
        val (r, g, b) = when (h.toInt()) {
            0 -> Triple(c, x, 0f)
            1 -> Triple(x, c, 0f)
            2 -> Triple(0f, c, x)
            3 -> Triple(0f, x, c)
            4 -> Triple(x, 0f, c)
            else -> Triple(c, 0f, x)
        }
        return listOf(r, g, b).map { ((it + m) * 255f).roundToInt().coerceIn(0, 255) }
    }

    /** Écart entre deux teintes, en degrés, par le plus court chemin (350° et 5° sont à 15°). */
    fun ecartTeinte(a: Float, b: Float): Float {
        val d = abs(a - b) % 360f
        return if (d > 180f) 360f - d else d
    }

    fun teinteConforme(prevue: Float, lue: Float) = ecartTeinte(prevue, lue) <= TOLERANCE_TEINTE

    fun kelvinConforme(prevu: Int, lu: Int) = abs(prevu - lu) <= TOLERANCE_KELVIN

    /**
     * La lecture [l] a-t-elle le réglage de couleur demandé dans [p] ? Sans mode prévu (simple marche ou luminosité),
     * oui. Une lampe qui ne dit pas son mode (anciennes lectures) n'est jugée que sur ce qu'elle donne.
     */
    fun reglageConforme(l: Appareils.Appareil, p: Appareils.Appareil): Boolean {
        if (p.mode == "color_temp" && p.kelvin != null) {
            if (l.mode.isNotEmpty() && l.mode != "color_temp") return false
            val k = l.kelvin ?: return l.mode.isEmpty()
            return kelvinConforme(p.kelvin, k)
        }
        if (modeCouleur(p.mode) && p.teinte != null) {
            if (l.mode == "color_temp") return false
            val t = l.teinte ?: return l.mode.isEmpty()
            return teinteConforme(p.teinte, t)
        }
        return true
    }
}
