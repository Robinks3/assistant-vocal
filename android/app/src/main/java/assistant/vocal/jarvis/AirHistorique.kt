package assistant.vocal.jarvis

import org.json.JSONObject
import java.time.Instant
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.temporal.ChronoUnit
import java.util.Locale
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.min
import kotlin.math.pow

/**
 * Historique de l'air d'une pièce (S-L8), logique pure du graphique : lecture de la réponse `air_historique` du serveur,
 * échelle verticale, bandes de seuil, segments sans trou, repères du temps en heure locale et lecture au doigt. Le
 * dessin (Canvas) est dans VueAirGraphique, rien ici ne touche à Android.
 *
 * Réponse du serveur : `{"etat":"air_historique","id":..,"donnees":{piece,heures,debut,fin,pas,series:{co2,pm25,temperature,
 * humidite}}}` ou `{..,"erreur":"..."}`. Un point est `[secondes Unix, valeur]`, un intervalle sans mesure est absent (un trou,
 * jamais un zéro).
 */
object AirHistorique {

    enum class Grandeur(val cle: String, val titre: String, val unite: String, val decimales: Int) {
        CO2("co2", "CO2", "ppm", 0),
        PM25("pm25", "PM2.5", "µg/m3", 1),
        TEMPERATURE("temperature", "Température", "°C", 1),
        HUMIDITE("humidite", "Humidité", "%", 0),
    }

    /** Ce que montre l'écran : l'air (CO2 et PM2.5 l'un sur l'autre), ou la température et l'humidité. */
    enum class Groupe(val titre: String, val grandeurs: List<Grandeur>) {
        AIR("Air", listOf(Grandeur.CO2, Grandeur.PM25)),
        CLIMAT("Température et humidité", listOf(Grandeur.TEMPERATURE, Grandeur.HUMIDITE)),
    }

    enum class Duree(val heures: Int, val libelle: String) {
        H6(6, "6 h"), H24(24, "24 h"), J7(168, "7 jours");

        companion object {
            val PAR_DEFAUT = H24
        }
    }

    class Point(val t: Double, val v: Double)

    class Donnees(
        val piece: String, val heures: Int, val debut: Double, val fin: Double, val pas: Double,
        val series: Map<Grandeur, List<Point>>,
    ) {
        fun points(g: Grandeur): List<Point> = series[g] ?: emptyList()
        fun aDesPoints(groupe: Groupe): Boolean = groupe.grandeurs.any { points(it).isNotEmpty() }
    }

    sealed class Resultat {
        class Charge(val donnees: Donnees) : Resultat()
        /** Réponse lue, mais aucune mesure sur la période. */
        class Vide(val donnees: Donnees) : Resultat()
        class Erreur(val message: String) : Resultat()
    }

    const val ERREUR_RESEAU = "Pas de réponse du serveur"

    // ------------------------------------------------------------ lecture de la réponse

    /** Résultat de la réponse [reponse] du serveur (null : le serveur n'a pas répondu à temps). */
    fun lire(reponse: JSONObject?): Resultat {
        if (reponse == null) return Resultat.Erreur(ERREUR_RESEAU)
        val erreur = reponse.optString("erreur")
        if (erreur.isNotEmpty()) return Resultat.Erreur(erreur)
        val d = reponse.optJSONObject("donnees") ?: return Resultat.Erreur("Réponse illisible")
        val series = LinkedHashMap<Grandeur, List<Point>>()
        val brutes = d.optJSONObject("series")
        for (g in Grandeur.values()) {
            val a = brutes?.optJSONArray(g.cle)
            val pts = ArrayList<Point>()
            if (a != null) for (i in 0 until a.length()) {
                val p = a.optJSONArray(i) ?: continue
                if (p.length() < 2 || p.isNull(0) || p.isNull(1)) continue
                val t = p.optDouble(0, Double.NaN)
                val v = p.optDouble(1, Double.NaN)
                if (t.isFinite() && v.isFinite()) pts.add(Point(t, v))
            }
            pts.sortBy { it.t }
            series[g] = pts
        }
        val fin = d.optDouble("fin", Double.NaN)
        val heures = d.optInt("heures", 24)
        val finOk = if (fin.isFinite()) fin else series.values.flatten().maxOfOrNull { it.t } ?: 0.0
        val debut = d.optDouble("debut", Double.NaN).let { if (it.isFinite()) it else finOk - heures * 3600.0 }
        val donnees = Donnees(d.optString("piece"), heures, debut, finOk, d.optDouble("pas", 0.0).let { if (it.isFinite()) it else 0.0 }, series)
        return if (series.values.all { it.isEmpty() }) Resultat.Vide(donnees) else Resultat.Charge(donnees)
    }

    /** Fuseau de la configuration (clé `fuseau`), UTC quand il manque ou qu'il est inconnu. */
    fun fuseau(nom: String?): ZoneId =
        runCatching { ZoneId.of(if (nom.isNullOrBlank()) "UTC" else nom) }.getOrDefault(ZoneId.of("UTC"))

    // ------------------------------------------------------------ échelle verticale

    class Echelle(val bas: Double, val haut: Double, val pas: Double) {
        fun fraction(v: Double): Double = if (haut <= bas) 0.0 else ((v - bas) / (haut - bas)).coerceIn(0.0, 1.0)

        /** Valeurs des repères horizontaux, de [bas] à [haut]. */
        fun graduations(): List<Double> {
            if (pas <= 0.0) return listOf(bas, haut)
            val l = ArrayList<Double>()
            var i = 0
            while (true) {
                val v = bas + i * pas
                if (v > haut + pas * 1e-6) break
                l.add(v)
                i++
                if (i > 50) break
            }
            return l
        }
    }

    /** Pas « rond » (1, 2, 5 fois une puissance de dix) pour couvrir [plage] avec environ [cibles] intervalles. */
    fun pasNice(plage: Double, cibles: Int): Double {
        if (!(plage > 0.0) || cibles <= 0) return 1.0
        val brut = plage / cibles
        val mag = 10.0.pow(floor(log10(brut)))
        val n = brut / mag
        val f = when {
            n <= 1.0 -> 1.0
            n <= 2.0 -> 2.0
            n <= 5.0 -> 5.0
            else -> 10.0
        }
        return f * mag
    }

    /**
     * Échelle d'une courbe. Le CO2 part de 400 ppm (l'air extérieur) et monte au moins jusqu'à 1 200 ppm, les particules
     * partent de zéro et montent au moins jusqu'à 15 µg/m3 : les premières bandes de seuil restent toujours visibles.
     */
    fun echelle(g: Grandeur, points: List<Point>): Echelle {
        val mn = points.minOfOrNull { it.v } ?: 0.0
        val mx = points.maxOfOrNull { it.v } ?: 0.0
        val vide = points.isEmpty()
        var bas: Double
        var haut: Double
        when (g) {
            Grandeur.CO2 -> {
                bas = if (vide) 400.0 else min(400.0, floor(mn / 100.0) * 100.0)
                haut = max(mx * 1.08, 1200.0)
            }
            Grandeur.PM25 -> {
                bas = 0.0
                haut = max(mx * 1.15, 15.0)
            }
            Grandeur.TEMPERATURE -> {
                bas = if (vide) 16.0 else floor(mn - 1.0)
                haut = if (vide) 26.0 else ceil(mx + 1.0)
                if (haut - bas < 6.0) { val m = (haut + bas) / 2.0; bas = m - 3.0; haut = m + 3.0 }
            }
            Grandeur.HUMIDITE -> {
                bas = if (vide) 30.0 else floor((mn - 5.0) / 5.0) * 5.0
                haut = if (vide) 70.0 else ceil((mx + 5.0) / 5.0) * 5.0
                if (haut - bas < 20.0) { val m = (haut + bas) / 2.0; bas = m - 10.0; haut = m + 10.0 }
            }
        }
        val pas = pasNice(haut - bas, 4)
        bas = floor(bas / pas) * pas
        haut = ceil(haut / pas) * pas
        if (g == Grandeur.HUMIDITE) { bas = max(0.0, bas); haut = min(100.0, haut) }
        if (g == Grandeur.PM25) bas = 0.0
        if (haut <= bas) haut = bas + pas
        return Echelle(bas, haut, pas)
    }

    // ------------------------------------------------------------ bandes de seuil

    /** Bande de couleur entre [de] et [a] (valeurs) pour la classe [rang] de Mesures.MOTS_AIR. */
    class Bande(val de: Double, val a: Double, val rang: Int)

    /** Seuils de [g] (CO2 ou PM2.5), null pour la température et l'humidité qui n'en ont pas. */
    fun seuils(g: Grandeur): DoubleArray? = when (g) {
        Grandeur.CO2 -> Mesures.SEUILS_CO2
        Grandeur.PM25 -> Mesures.SEUILS_PM25
        else -> null
    }

    /** Bandes bon, correct, médiocre, mauvais de [g] découpées à l'échelle [e] (aucune pour la température et l'humidité). */
    fun bandes(g: Grandeur, e: Echelle): List<Bande> {
        val s = seuils(g) ?: return emptyList()
        val bords = doubleArrayOf(e.bas, s[0], s[1], s[2], e.haut)
        val l = ArrayList<Bande>()
        for (i in 0 until 4) {
            val de = max(bords[i], e.bas)
            val a = min(bords[i + 1], e.haut)
            if (de < a) l.add(Bande(de, a, i))
        }
        return l
    }

    // ------------------------------------------------------------ courbe

    /**
     * Morceaux continus de [points] : la courbe est coupée quand l'écart entre deux points dépasse une fois et demie
     * le [pas] (un trou de mesure ne se relie jamais, il ne tombe pas à zéro).
     */
    fun segments(points: List<Point>, pas: Double): List<List<Point>> {
        if (points.isEmpty()) return emptyList()
        val limite = if (pas > 0.0) pas * 1.5 else Double.MAX_VALUE
        val sortie = ArrayList<List<Point>>()
        var courant = ArrayList<Point>()
        for (p in points) {
            if (courant.isNotEmpty() && p.t - courant.last().t > limite) {
                sortie.add(courant)
                courant = ArrayList()
            }
            courant.add(p)
        }
        sortie.add(courant)
        return sortie
    }

    // ------------------------------------------------------------ axe du temps

    class Repere(val t: Double, val libelle: String)

    private val JOURS_COURTS = listOf("lun.", "mar.", "mer.", "jeu.", "ven.", "sam.", "dim.")
    private val JOURS = listOf("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")

    private fun zdt(t: Double, fuseau: ZoneId): ZonedDateTime = Instant.ofEpochMilli(Math.floor(t * 1000).toLong()).atZone(fuseau)

    /**
     * Repères de l'axe du temps entre [debut] et [fin], en heure du [fuseau] : toutes les heures sur 6 h, toutes les 4 h
     * sur 24 h (« 8 h », « 12 h »), à minuit de chaque jour sur 7 jours (« lun. 26 »).
     */
    fun reperesTemps(debut: Double, fin: Double, fuseau: ZoneId): List<Repere> {
        if (!(fin > debut)) return emptyList()
        val heures = (fin - debut) / 3600.0
        val l = ArrayList<Repere>()
        if (heures > 36.0) {
            var d = zdt(debut, fuseau).truncatedTo(ChronoUnit.DAYS)
            while (d.toEpochSecond().toDouble() < debut) d = d.plusDays(1)
            while (d.toEpochSecond().toDouble() <= fin) {
                l.add(Repere(d.toEpochSecond().toDouble(), "${JOURS_COURTS[d.dayOfWeek.value - 1]} ${d.dayOfMonth}"))
                d = d.plusDays(1)
                if (l.size > 40) break
            }
        } else {
            val pas = if (heures <= 8.0) 1 else 4
            var d = zdt(debut, fuseau).truncatedTo(ChronoUnit.HOURS)
            while (d.toEpochSecond().toDouble() < debut || d.hour % pas != 0) d = d.plusHours(1)
            while (d.toEpochSecond().toDouble() <= fin) {
                l.add(Repere(d.toEpochSecond().toDouble(), "${d.hour} h"))
                d = d.plusHours(pas.toLong())
                if (l.size > 40) break
            }
        }
        return l
    }

    // ------------------------------------------------------------ nombres et phrases

    /** Valeur écrite avec la virgule française et le nombre de décimales de la grandeur. */
    fun formater(v: Double, decimales: Int): String =
        if (decimales <= 0) Mesures.arrondi(v).toString() else String.format(Locale.ROOT, "%.${decimales}f", v).replace('.', ',')

    fun valeur(g: Grandeur, v: Double): String = "${formater(v, g.decimales)} ${g.unite}"

    /** Mot de la valeur (bon, correct, médiocre, mauvais ; frais, agréable, chaud), vide pour l'humidité. */
    fun mot(g: Grandeur, v: Double): String = when (g) {
        Grandeur.CO2 -> Mesures.motCo2(v)
        Grandeur.PM25 -> Mesures.motPm25(v)
        Grandeur.TEMPERATURE -> Mesures.motTemperature(v)
        Grandeur.HUMIDITE -> ""
    }

    /** Couleur « #RRGGBB » du mot d'une valeur d'air, null pour la température et l'humidité. */
    fun couleurAir(g: Grandeur, v: Double): String? {
        val s = seuils(g) ?: return null
        return Mesures.COULEURS_AIR[Mesures.rangAir(v, s)]
    }

    class Resume(val min: Double, val max: Double, val moyenne: Double, val derniere: Double, val derniereT: Double)

    fun resume(points: List<Point>): Resume? {
        if (points.isEmpty()) return null
        val d = points.last()
        return Resume(points.minOf { it.v }, points.maxOf { it.v }, points.sumOf { it.v } / points.size, d.v, d.t)
    }

    /** Phrase de la période : « de 480 à 1240 ppm, moyenne 760 ppm ». */
    fun phraseResume(g: Grandeur, r: Resume): String =
        "de ${formater(r.min, g.decimales)} à ${valeur(g, r.max)}, moyenne ${valeur(g, r.moyenne)}"

    /** Point de [points] le plus proche de l'instant [t], null s'il n'y en a pas. */
    fun plusProche(points: List<Point>, t: Double): Point? = points.minByOrNull { abs(it.t - t) }

    /** « 14 h 05 » d'un instant, à l'heure du [fuseau]. */
    fun heure(t: Double, fuseau: ZoneId): String = Mesures.heureLocale(t, fuseau)

    /** Lecture au doigt : « mardi 14 h 05, 1240 ppm, médiocre ». */
    fun lecture(g: Grandeur, p: Point, fuseau: ZoneId): String {
        val d = zdt(p.t, fuseau)
        val m = mot(g, p.v)
        return "${JOURS[d.dayOfWeek.value - 1]} ${heure(p.t, fuseau)}, ${valeur(g, p.v)}" + if (m.isEmpty()) "" else ", $m"
    }

    /** Titre de la vue : « Salon, 24 dernières heures ». */
    fun titre(nomPiece: String, duree: Duree): String = when (duree) {
        Duree.H6 -> "$nomPiece, 6 dernières heures"
        Duree.H24 -> "$nomPiece, 24 dernières heures"
        Duree.J7 -> "$nomPiece, 7 derniers jours"
    }

    /** Message d'état quand le groupe choisi n'a aucune mesure sur la période. */
    fun phraseVide(groupe: Groupe): String = when (groupe) {
        Groupe.AIR -> "Pas de mesure de l'air sur cette période"
        Groupe.CLIMAT -> "Pas de mesure de température ni d'humidité sur cette période"
    }

    /**
     * Messages d'erreur du serveur les plus courants, tournés pour l'écran. Tout autre message du serveur passe tel quel
     * (il est déjà en français).
     */
    fun messageErreur(brut: String): String = when (brut) {
        ERREUR_RESEAU -> "Le serveur ne répond pas"
        else -> brut.replaceFirstChar { it.uppercaseChar() }
    }

    /** Durée choisie d'après des heures (24 si inconnue). */
    fun dureeDe(heures: Int): Duree = Duree.values().firstOrNull { it.heures == heures } ?: Duree.PAR_DEFAUT
}
