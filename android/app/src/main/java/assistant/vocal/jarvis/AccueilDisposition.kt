package assistant.vocal.jarvis

import java.time.LocalDate
import java.util.Locale
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * Seconde passe de l'accueil de la tablette (0.24.0, maquettes du 22/10/2026 validées, canevas
 * version 24, décisions dans docs/maquettes/revue-accueil-musique.md), logique pure testée sur la machine
 * (AccueilDispositionTest) : zones du plan 3D avec et sans musique, intensité du plan, suivi de l'arrêt de la
 * musique, volume visé depuis l'accueil, et textes courts de la colonne de gauche minimaliste (piste A).
 */
internal object Disposition {

    /** Zone du plan en fractions de la fenêtre (maison3d.disposition), centre et diamètre de l'orbe en pixels de maquette. */
    data class Zone(val x: Float, val y: Float, val largeur: Float, val hauteur: Float) {
        val centreX: Float get() = (x + largeur / 2f) * CadreMaquette.LARGEUR
        val centreY: Float get() = (y + hauteur / 2f) * CadreMaquette.HAUTEUR
    }

    /** Sans musique (piste A) : le plan se centre en hauteur dans la moitié droite. */
    val A = Zone(0.5f, 0.275f, 0.444f, 0.45f)
    /** Avec musique (piste B), et pendant la pause atténuée : le plan monte et rétrécit, le bloc Musique prend le bas. */
    val B = Zone(0.519f, 0.08f, 0.406f, 0.4125f)
    /** Écoute, réflexion, réponse : la zone se resserre de 8 % autour de son centre, la scène passe à 0,28. */
    val ECOUTE_A = Zone(0.518f, 0.293f, 0.408f, 0.414f)
    val ECOUTE_B = Zone(0.535f, 0.096f, 0.373f, 0.38f)

    /** Un jour sur deux, la colonne passe à x 120 et la moitié droite se décale de 24 px de maquette. */
    const val DECALAGE_DROITE = 24f

    /** Zone voulue : avec ou sans le bloc Musique, à l'écoute ou non, le jour décalé ou non. */
    fun zone(musique: Boolean, ecoute: Boolean, decale: Boolean): Zone {
        val z = when {
            ecoute && musique -> ECOUTE_B
            ecoute -> ECOUTE_A
            musique -> B
            else -> A
        }
        return if (decale) z.copy(x = z.x + DECALAGE_DROITE / CadreMaquette.LARGEUR) else z
    }

    /** Diamètre de l'orbe en pixels de maquette : 200 sans musique, 170 avec, 85 % le soir. */
    fun diametreOrbe(musique: Boolean, soir: Boolean): Float = (if (musique) 170f else 200f) * (if (soir) 0.85f else 1f)

    /** Intensité du plan choisie par le propriétaire : 1 le jour, 0,2 le soir (Veillée), 0,15 la nuit (minuit à 7 h). */
    fun intensite(jour: Boolean, nuit: Boolean): Float = when {
        nuit -> 0.15f
        !jour -> 0.2f
        else -> 1f
    }
}

/**
 * Arrêt de la musique sur l'accueil (revue du 22/10) : pendant [graceMs] après n'importe quel arrêt (pause à
 * la voix, depuis l'appli Enceintes, fin de liste, mise en mémoire tampon) rien ne change. Ensuite le bloc reste en
 * pause, atténué, pendant [pauseMs]. Au-delà il disparaît et le plan reprend la zone A. Une reprise rallume le
 * bloc sans rien déplacer. Horloge monotone donnée par l'appelant.
 */
internal class SuiviMusique(private val graceMs: Long = 30_000L, private val pauseMs: Long = 10 * 60_000L) {

    enum class Phase { JOUE, GRACE, PAUSE, ABSENT }

    private var arretLe = -1L
    private var vu = false

    /** [joue] : le lecteur suivi joue. [connu] : un lecteur est encore à montrer (en cours ou retenu). */
    fun avancer(joue: Boolean, connu: Boolean, maintenant: Long): Phase {
        if (joue) {
            vu = true
            arretLe = -1L
            return Phase.JOUE
        }
        if (!vu && !connu) return Phase.ABSENT
        vu = true
        if (arretLe < 0L) arretLe = maintenant
        val t = maintenant - arretLe
        return when {
            t < graceMs -> Phase.GRACE
            t < graceMs + pauseMs -> Phase.PAUSE
            else -> {
                vu = false
                Phase.ABSENT
            }
        }
    }

    /** Le bloc Musique est à l'écran (et le plan dans la zone B). */
    fun montre(p: Phase): Boolean = p != Phase.ABSENT
}

/**
 * Volume réglé depuis l'accueil (revue du 22/10) : moins et plus changent la valeur visée de 5 points par
 * toucher, cumulés sur la valeur affichée. Glisser sur la piste n'envoie qu'au lâcher. La valeur visée reste
 * affichée jusqu'à la relecture de Home Assistant qui la confirme, ou [dureeMs] au plus. Jamais au-delà de
 * [max], Securite.VOLUME_MAX par défaut : le plafond réglé dans la configuration (securite.plafond_volume, 1 sans
 * plafond). Les tests passent un autre plafond.
 */
internal class VolumeVise(private val dureeMs: Long = 3_000L, private val max: Double = MAX) {

    private var vise: Double? = null
    private var viseLe = 0L

    /** Valeur à afficher (0 à 1) : la visée tant qu'elle n'est ni confirmée ni trop ancienne, sinon la valeur lue. */
    fun affiche(lu: Double, maintenant: Long): Double {
        val v = vise ?: return lu
        if (maintenant - viseLe >= dureeMs) {
            vise = null
            return lu
        }
        return v
    }

    /** Nouvelle lecture de Home Assistant : la visée confirmée s'efface. */
    fun lu(valeur: Double) {
        val v = vise ?: return
        if (abs(valeur - v) < 0.015) vise = null
    }

    /**
     * Un toucher sur moins ([sens] -1) ou plus (+1) : la nouvelle valeur visée, ou null si rien ne change
     * (plus au plafond, moins à zéro).
     */
    fun pas(lu: Double, sens: Int, maintenant: Long): Double? {
        val base = affiche(lu, maintenant)
        if (sens > 0 && base >= max - 1e-6) return null
        if (sens < 0 && base <= 1e-6) return null
        return viser(borne(base + PAS * sens, max), maintenant)
    }

    /** Doigt levé sur la piste à [valeur] (0 à 1). */
    fun glisser(valeur: Double, maintenant: Long): Double = viser(borne(valeur, max), maintenant)

    private fun viser(v: Double, maintenant: Long): Double {
        vise = v
        viseLe = maintenant
        return v
    }

    companion object {
        const val PAS = 0.05
        val MAX: Double get() = Securite.VOLUME_MAX

        /**
         * Part de la piste (0 à 1) pour un volume [v] : la piste va de 0 au volume permis ([MAX]). 0 avec un
         * plafond réglé à 0 % ou un volume illisible, au lieu d'une division par zéro.
         */
        fun fraction(v: Double, max: Double = MAX): Double =
            if (max <= 0.0 || v.isNaN()) 0.0 else (v / max).coerceIn(0.0, 1.0)

        private fun arrondi(v: Double): Double = (v * 100).roundToInt() / 100.0

        /** Arrondi au point, puis borné : un plafond de 72,5 % reste à 0,725 au lieu de remonter à 0,73. */
        private fun borne(v: Double, max: Double): Double = minOf(arrondi(v.coerceIn(0.0, max)), max)

        /**
         * Un groupe d'enceintes (salon et cuisine regroupés) : le geste fait passer la valeur affichée (celle de
         * l'enceinte la plus forte) de [avant] à [apres], et ce décalage s'applique à chaque enceinte, plafonnée
         * pour chacune. Rend le volume à envoyer à chaque enceinte (0 à 1).
         */
        fun groupe(membres: Map<String, Double>, avant: Double, apres: Double, max: Double = MAX): Map<String, Double> {
            val d = apres - avant
            return membres.mapValues { (_, v) -> borne(v + d, max) }
        }
    }
}

/** Textes courts de la colonne de gauche minimaliste (piste A, retour du 22/10 : moins textuel). */
internal object TextesCourts {

    private val JOURS = listOf("Lun.", "Mar.", "Mer.", "Jeu.", "Ven.", "Sam.", "Dim.")
    private val MOIS = listOf("janv.", "févr.", "mars", "avr.", "mai", "juin", "juil.", "août", "sept.", "oct.", "nov.", "déc.")

    /** « Jeu. 22 oct. », « Sam. 1er mars ». */
    fun date(jour: LocalDate): String {
        val j = jour.dayOfMonth
        return JOURS[jour.dayOfWeek.value - 1] + " " + (if (j == 1) "1er" else j.toString()) + " " + MOIS[jour.monthValue - 1]
    }

    /** « 21° », « -3° » d'après la température lue (« 20,6 °C »), vide si elle est inconnue. */
    fun temperature(m: Etat.Meteo?): String {
        val brut = Regex("[-\\u2212]?\\d+(?:[.,]\\d+)?").find(m?.temperature ?: "")?.value ?: return ""
        val v = brut.replace(0x2212.toChar(), '-').replace(',', '.').toDoubleOrNull() ?: return ""
        return "${v.roundToInt()}°"
    }

    /** « pluie 17 h », « neige 6 h », « pluie en ce moment », d'après la phrase de Accueil.pluie. Vide sans pluie. */
    fun pluie(phrase: String): String {
        val p = phrase.trim().trimEnd('.')
        if (p.isEmpty()) return ""
        val mot = p.substringBefore(' ').lowercase(Locale.FRANCE)
        val reste = p.substringAfter(' ', "")
        return if (reste.startsWith("vers ")) "$mot ${reste.removePrefix("vers ")}" else "$mot $reste".trim()
    }

    /** « 7 h 05 » pour le sommeil, « 5 320 » pour les pas : la valeur seule, le mot à côté en petit. */
    fun sommeil(minutes: Int?): String = minutes?.let { Sante.duree(it) } ?: ""
    fun pas(n: Int?): String = n?.let { Sante.milliers(it) } ?: ""

    /**
     * Ligne de panne en une seule ligne ambre (0.24.0) : « Maison hors ligne depuis 10 h 02 » quand Home Assistant
     * ne répond plus, « Serveur injoignable depuis 10 h 02 », les autres pannes telles quelles.
     */
    fun panne(texte: String, depuisHeure: Int?, depuisMinute: Int?): String {
        val depuis = if (depuisHeure != null && depuisMinute != null) String.format(Locale.FRANCE, " depuis %d h %02d", depuisHeure, depuisMinute) else ""
        return when (texte) {
            "Home Assistant ne répond plus" -> "Maison hors ligne$depuis"
            "Serveur injoignable" -> "Serveur injoignable$depuis"
            else -> texte
        }
    }

    /** « Volume du salon », « Volume du salon et de la cuisine », « Volume » hors de la sortie du son. */
    fun volume(l: Etat.Lecteur): String {
        val noms = (listOf(l.id) + l.membres).distinct()
            .mapNotNull { id -> SortieSon.ENCEINTES.firstOrNull { it.first == id }?.second }
            .distinct()
        if (noms.isEmpty()) return "Volume"
        return "Volume " + Accueil.enumerer(noms.map { de(Accueil.article(it)) })
    }

    /** « le salon » donne « du salon », « la cuisine » « de la cuisine », « l'entrée » « de l'entrée ». */
    private fun de(groupe: String): String = when {
        groupe.startsWith("le ") -> "du " + groupe.removePrefix("le ")
        groupe.startsWith("les ") -> "des " + groupe.removePrefix("les ")
        else -> "de $groupe"
    }

    /** « 30 % » pour 0,3. */
    fun pourcent(v: Double): String = "${max(0, (v * 100).roundToInt())} %"
}
