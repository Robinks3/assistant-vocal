package assistant.vocal.jarvis

import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.TextStyle
import java.util.Locale
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * Panneau Météo de la tablette (0.20.0, maquette `Meteo2` relue) : tout ce qui s'y écrit, en logique pure
 * testée sur la machine (MeteoTexteTest). Les vues (EcranMeteo) ne font que dessiner ce qui est calculé ici.
 *
 * Rien n'est inventé : une valeur absente des prévisions n'est pas écrite, la phrase de synthèse ne dit que
 * ce que disent les heures et les jours lus dans Home Assistant (weather.get_forecasts).
 */
internal object MeteoTexte {

    /** Pictos des maquettes, plus la neige. */
    enum class Picto { SOLEIL, ECLAIRCIES, NUAGE, PLUIE, NEIGE, NUIT_NUAGE, NUIT }

    /** Une colonne de la frise : l'heure, ce qu'on y dessine, et si c'est la nuit. */
    data class Colonne(
        val instant: Long,
        val heure: Int,
        val temperature: Double?,
        val picto: Picto,
        val millimetres: Double?,
        val probabilite: Int?,
        val vent: Double?,
        val direction: Double?,
        val rafales: Double?,
        val humidite: Int?,
        val nuit: Boolean,
        /** Minuit (premier instant d'un nouveau jour) : repère « Demain » ou nom du jour. */
        val minuit: Boolean,
    )

    /** Un jour de la rangée du bas. */
    data class Jour(val date: LocalDate, val nom: String, val picto: Picto, val probabilite: Int?, val millimetres: Double?, val max: Double?, val min: Double?)

    private val PLUIE = setOf("rainy", "pouring", "lightning-rainy", "lightning", "hail")
    private val NEIGE = setOf("snowy", "snowy-rainy")

    /** Picto d'une condition Home Assistant, de jour ou de nuit. */
    fun picto(condition: String, nuit: Boolean): Picto = when {
        condition in PLUIE -> Picto.PLUIE
        condition in NEIGE -> Picto.NEIGE
        condition == "clear-night" -> Picto.NUIT
        condition == "sunny" -> if (nuit) Picto.NUIT else Picto.SOLEIL
        condition == "partlycloudy" -> if (nuit) Picto.NUIT_NUAGE else Picto.ECLAIRCIES
        else -> Picto.NUAGE
    }

    /** Une heure où il pleut : probabilité d'au moins 50 %, condition de pluie, de neige ou d'orage, ou 0,2 mm et plus. */
    fun pluvieuse(p: Previsions.Prevision): Boolean =
        (p.pluie ?: -1) >= 50 || p.condition in PLUIE || p.condition in NEIGE || (p.millimetres ?: 0.0) >= 0.2

    /**
     * Nuit à l'instant [t] : entre un coucher et le lever suivant. [lever] et [coucher] sont les prochains lus
     * dans sun.sun ; les jours suivants, les mêmes heures à 24 h près (l'écart de quelques minutes d'un jour à
     * l'autre ne change pas l'heure de la colonne).
     */
    fun nuit(t: Long, lever: Long?, coucher: Long?): Boolean {
        if (lever == null || coucher == null) return false
        val jour = 24 * 3_600_000L
        // Ramène les deux repères autour de t.
        fun proche(r: Long): Long {
            var x = r
            while (x - t > jour / 2) x -= jour
            while (t - x > jour / 2) x += jour
            return x
        }
        val l = proche(lever)
        val c = proche(coucher)
        return if (c < l) t >= c && t < l else t < l || t >= c
    }

    /** Colonnes de la frise : les heures à partir de celle en cours, avec leur picto de jour ou de nuit. */
    fun colonnes(horaire: List<Previsions.Prevision>, maintenant: ZonedDateTime, lever: Long?, coucher: Long?): List<Colonne> {
        val debut = maintenant.withMinute(0).withSecond(0).withNano(0).toInstant().toEpochMilli()
        val zone = maintenant.zone
        return horaire.filter { it.instant >= debut }.mapIndexed { i, p ->
            val h = Instant.ofEpochMilli(p.instant).atZone(zone)
            val n = nuit(p.instant, lever, coucher)
            Colonne(p.instant, h.hour, p.temperature, picto(p.condition, n), p.millimetres, p.pluie, p.vent, p.direction, p.rafales, p.humidite, n, i > 0 && h.hour == 0)
        }
    }

    /** Opacité des pictos : les pictos de nuit à moitié, sauf la première heure de nuit (maquette). */
    fun opacites(c: List<Colonne>): List<Float> {
        var premiere = true
        return c.map {
            if (!it.nuit) {
                1f
            } else if (premiere) {
                premiere = false
                1f
            } else 0.5f
        }
    }

    /** « 1,8 », « 0,6 » : millimètres à une décimale, virgule française. */
    fun mm(v: Double): String = String.format(Locale.FRANCE, "%.1f", v)

    /** Hauteur de la barre de pluie en pixels de maquette : proportionnelle aux mm, pleine à 2 mm, 3 px au moins. */
    fun barre(mm: Double?, pleine: Float = 60f): Float {
        val m = mm ?: 0.0
        if (m <= 0.0) return 0f
        return maxOf(3f, (minOf(m, 2.0) / 2.0 * pleine).toFloat())
    }

    /** Texte des millimètres au-dessus de la barre, dès 0,5 mm, « mm » une seule fois (la première). */
    fun textesMm(c: List<Colonne>): List<String> {
        var premier = true
        return c.map {
            val m = it.millimetres ?: 0.0
            if (m < 0.5) "" else {
                val t = mm(m) + if (premier) " mm" else ""
                premier = false
                t
            }
        }
    }

    fun degres(v: Double?): String = if (v == null) "" else "${v.roundToInt()}°"

    /** 30 km/h dans l'unité du vent de l'entité (0.21.1) : km/h, m/s, mph, nœuds, pieds par seconde. */
    fun seuilRafales(unite: String): Double = when (unite.trim().lowercase(Locale.ROOT)) {
        "m/s" -> 30.0 / 3.6
        "mph" -> 30.0 / 1.609344
        "kn", "kt", "nœuds", "noeuds" -> 30.0 / 1.852
        "ft/s" -> 30.0 / 1.09728
        else -> 30.0
    }

    /** Rafales montrées au-dessus de 30 km/h, dans l'unité [unite] du vent. */
    fun rafaleMontree(r: Double?, unite: String = "km/h"): Boolean = r != null && r > seuilRafales(unite)

    /** Ligne de détail d'une heure touchée : seulement ce que dit la prévision. */
    fun detail(c: Colonne, uniteVent: String = "km/h"): Pair<String, String> {
        val parties = ArrayList<String>()
        c.temperature?.let { parties.add(degres(it)) }
        c.probabilite?.let { parties.add("pluie $it %") }
        c.millimetres?.takeIf { it >= 0.1 }?.let { parties.add(mm(it) + " mm") }
        c.vent?.let { parties.add("vent ${it.roundToInt()} $uniteVent") }
        c.rafales?.takeIf { rafaleMontree(it, uniteVent) }?.let { parties.add("rafales à ${it.roundToInt()} $uniteVent") }
        c.humidite?.let { parties.add("humidité $it %") }
        return "${c.heure} h" to (if (parties.isEmpty()) "" else " : " + parties.joinToString(", "))
    }

    /** Catégorie de l'indice UV (OMS). */
    fun uv(v: Double): String {
        val n = v.roundToInt()
        val c = when {
            n <= 2 -> "faible"
            n <= 5 -> "modéré"
            n <= 7 -> "élevé"
            n <= 10 -> "très élevé"
            else -> "extrême"
        }
        return "indice UV $n ($c)"
    }

    /** « 18 h 24 », « 7 h 05 ». */
    fun heureMinute(t: Long, zone: ZoneId): String {
        val h = Instant.ofEpochMilli(t).atZone(zone)
        return "${h.hour} h " + h.minute.toString().padStart(2, '0')
    }

    /** Jours de la rangée du bas, sept au plus, à partir d'aujourd'hui. Deux par jour : regroupés par date. */
    fun jours(journalier: List<Previsions.Prevision>, aujourdhui: LocalDate, zone: ZoneId): List<Jour> {
        val parDate = journalier.groupBy { Instant.ofEpochMilli(it.instant).atZone(zone).toLocalDate() }
        return parDate.keys.filter { !it.isBefore(aujourdhui) }.sorted().take(7).map { d ->
            val l = parDate.getValue(d)
            val jour = l.firstOrNull { it.deJour != false } ?: l.first()
            val temps = l.mapNotNull { it.temperature }
            val bas = l.mapNotNull { it.basse } + l.filter { it.deJour == false }.mapNotNull { it.temperature }
            val probas = l.mapNotNull { it.pluie }
            val mm = l.mapNotNull { it.millimetres }
            Jour(
                d, nomJour(d, aujourdhui), picto(jour.condition, false), probas.maxOrNull(), if (mm.isEmpty()) null else mm.sum(),
                temps.maxOrNull(), bas.minOrNull() ?: if (l.size > 1) temps.minOrNull() else null,
            )
        }
    }

    /** « Aujourd'hui », « Demain » n'est pas utilisé (la maquette nomme les jours), puis « Vendredi »... */
    fun nomJour(d: LocalDate, aujourdhui: LocalDate): String =
        if (d == aujourdhui) "Aujourd'hui" else d.dayOfWeek.getDisplayName(TextStyle.FULL, Locale.FRANCE).replaceFirstChar { it.titlecase(Locale.FRANCE) }

    /**
     * Phrase de synthèse du haut à droite, trois lignes au plus : la pluie des 12 prochaines heures (« Sec
     * jusqu'à 17 h. », « Puis pluie jusqu'à 19 h. »), puis demain (« Demain, éclaircies et 21°. »).
     */
    fun synthese(horaire: List<Previsions.Prevision>, jours: List<Jour>, journalier: List<Previsions.Prevision>, maintenant: ZonedDateTime): List<String> {
        val zone = maintenant.zone
        val debut = maintenant.withMinute(0).withSecond(0).withNano(0).toInstant().toEpochMilli()
        val h = horaire.filter { it.instant >= debut }
        val lignes = ArrayList<String>()
        if (h.isNotEmpty()) {
            val horizon = h.take(13)
            fun heure(p: Previsions.Prevision) = Instant.ofEpochMilli(p.instant).atZone(zone).hour
            val pleut = pluvieuse(horizon[0])
            val i = horizon.indexOfFirst { pluvieuse(it) != pleut }
            if (!pleut) {
                if (i < 0) lignes.add("Sec pour 12 heures.")
                else {
                    lignes.add("Sec jusqu'à ${heure(horizon[i])} h.")
                    val fin = h.drop(i).indexOfFirst { !pluvieuse(it) }
                    lignes.add(if (fin < 0) "Puis pluie." else "Puis pluie jusqu'à ${heure(h[i + fin])} h.")
                }
            } else {
                if (i < 0) lignes.add("Pluie pour 12 heures.")
                else {
                    lignes.add("Pluie jusqu'à ${heure(horizon[i])} h.")
                    lignes.add("Puis sec.")
                }
            }
        }
        val demain = maintenant.toLocalDate().plusDays(1)
        jours.firstOrNull { it.date == demain }?.let { j ->
            val cond = journalier.firstOrNull { Instant.ofEpochMilli(it.instant).atZone(zone).toLocalDate() == demain && it.deJour != false }?.condition
            val ciel = cond?.let { Maison.meteoEnFrancais(it) }
            val parties = listOfNotNull(ciel, j.max?.let { degres(it) })
            if (parties.isNotEmpty()) lignes.add("Demain, " + parties.joinToString(" et ") + ".")
        }
        return lignes
    }

    /** Nombre dit à voix haute : « moins 2 », « 13 ». */
    fun parle(v: Double): String {
        val n = v.roundToInt()
        return if (n < 0) "moins ${abs(n)}" else "$n"
    }

    /** Lieu de l'entité météo (« Forecast Lille » donne « Lille »), ou null pour la maison. */
    fun lieu(nom: String): String? {
        val l = nom.trim().removePrefix("Forecast ").removePrefix("Prévisions ").removePrefix("Météo ").trim()
        return l.takeIf { it.isNotEmpty() && it.lowercase(Locale.FRANCE) !in setOf("maison", "home", "domicile", "forecast") }
    }

    /** Titre du panneau. */
    fun titre(nom: String): String = lieu(nom)?.let { "Météo à $it" } ?: "Météo à la maison"

    /** Échelle commune des barres des jours : haut et hauteur (pixels de maquette) de l'écart d'un jour. */
    fun echelleJour(j: Jour, tous: List<Jour>, hauteur: Float = 44f): Pair<Float, Float>? {
        val max = j.max ?: return null
        val min = j.min ?: max
        val hauts = tous.mapNotNull { it.max }
        val bas = tous.mapNotNull { it.min ?: it.max }
        val gmax = hauts.maxOrNull() ?: return null
        val gmin = bas.minOrNull() ?: return null
        val e = maxOf(1.0, gmax - gmin)
        val haut = ((gmax - max) / e * hauteur).toFloat()
        val h = maxOf(4f, (abs(max - min) / e * hauteur).toFloat())
        return haut to minOf(h, hauteur - haut)
    }
}
