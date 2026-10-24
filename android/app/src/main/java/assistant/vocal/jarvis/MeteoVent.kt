package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.OffsetDateTime
import java.time.ZonedDateTime
import java.util.Locale
import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * Page « Vent mesuré sur le plan d'eau » du panneau Météo (0.29.0, maquettes `MeteoBalises*` relues le 24/10) :
 * mesures réelles des balises, des stations officielles et de la station
 * à terre du Vieux-Port, servies par le serveur (message `vent_mesure`, serveur 0.24.0). Logique pure,
 * testée sur la machine (MeteoVentTest). Les vues (EcranVent) ne font que dessiner ce qui est calculé ici.
 *
 * Le serveur garde les mesures avec leur vrai horodatage : c'est ici qu'on juge la fraîcheur (seuil de chaque
 * source, 45 min les balises, 75 min les stations officielles, 30 min la station à terre). Les mesures viennent avant les prévisions.
 */
internal object MeteoVent {

    data class Mesure(val t: Long, val vent: Double, val dir: Int?, val rafale: Double?)

    data class Station(
        val id: String, val nom: String, val genre: String, val type: String, val source: String,
        val lat: Double, val lon: Double, val point: String, val seuilMin: Int, val mesures: List<Mesure>,
    ) {
        val enMer: Boolean get() = type == "mer" || type == "abritee"
    }

    data class Donnees(val luA: ZonedDateTime?, val stations: List<Station>, val erreurs: List<String>) {
        fun station(id: String?): Station? = stations.firstOrNull { it.id == id }
    }

    /** Fenêtre de la courbe et du curseur, en secondes. */
    const val FENETRE_S = 3 * 3600L

    /** Section « vent » de maison.json : cadre et dessin de la carte, stations préférées. */
    private val CONF: JSONObject = ConfigMaison.section("vent")
    private val CARTE: JSONObject = CONF.optJSONObject("carte") ?: JSONObject()
    /** Cadre de la carte (latitude min et max, longitude min et max), le même que le trait de côte des assets. */
    private val CADRE: List<Double> = CONF.optJSONArray("cadre")?.let { a -> (0 until a.length()).map { a.optDouble(it, 0.0) } }
        ?.takeIf { it.size >= 4 } ?: listOf(0.0, 0.0, 0.0, 0.0)
    val LAT0: Double = CADRE[0]
    val LAT1: Double = CADRE[1]
    val LON0: Double = CADRE[2]
    val LON1: Double = CADRE[3]
    /** Taille de la carte en pixels de maquette. */
    val LARGEUR: Float = CARTE.optDouble("largeur", 640.0).toFloat()
    val HAUTEUR: Float = CARTE.optDouble("hauteur", 423.0).toFloat()
    /** Stations essayées d'abord pour la station par défaut (celles des jours de régate en tête). */
    private val PREFEREES: List<String> = ConfigMaison.chaines(CONF, "preferees")

    // ------------------------------------------------------------ lecture

    /** Données de la réponse du serveur, ou null avec le message lisible de l'échec. */
    fun lire(reponse: JSONObject?): Pair<Donnees?, String> {
        if (reponse == null) return null to "le serveur ne répond pas"
        reponse.optString("erreur").takeIf { it.isNotBlank() }?.let { return null to it }
        val d = reponse.optJSONObject("donnees") ?: reponse.takeIf { it.has("stations") } ?: return null to "réponse sans données"
        return try {
            val stations = ArrayList<Station>()
            val a = d.optJSONArray("stations") ?: JSONArray()
            for (i in 0 until a.length()) {
                val s = a.optJSONObject(i) ?: continue
                val id = s.optString("id")
                val lat = nombre(s, "lat")
                val lon = nombre(s, "lon")
                if (id.isEmpty() || lat == null || lon == null) continue
                val m = ArrayList<Mesure>()
                val ma = s.optJSONArray("mesures") ?: JSONArray()
                for (k in 0 until ma.length()) {
                    val o = ma.optJSONObject(k) ?: continue
                    val t = o.optLong("t", -1L).takeIf { it > 0 } ?: continue
                    val v = nombre(o, "vent") ?: continue
                    m.add(Mesure(t, v, nombre(o, "dir")?.roundToInt(), nombre(o, "rafale")?.takeIf { it > 0.0 }))
                }
                if (m.isEmpty()) continue
                stations.add(
                    Station(
                        id, s.optString("nom").ifBlank { id }, s.optString("genre"), s.optString("type").ifBlank { "terre" },
                        s.optString("source"), lat, lon, s.optString("point").ifBlank { MeteoMer.DEFAUT },
                        s.optInt("seuil_min", 45).coerceIn(5, 600), m.sortedBy { it.t }.distinctBy { it.t },
                    )
                )
            }
            val erreurs = d.optJSONArray("erreurs")?.let { e -> (0 until e.length()).map { e.optString(it) }.filter { it.isNotBlank() } } ?: emptyList()
            if (stations.isEmpty()) return null to (erreurs.firstOrNull() ?: "aucune mesure sur le plan d'eau")
            Donnees(instant(d.optString("lu_a")), stations, erreurs) to ""
        } catch (e: Exception) {
            null to "réponse illisible (${e.javaClass.simpleName})"
        }
    }

    private fun nombre(o: JSONObject, cle: String): Double? =
        if (!o.has(cle) || o.isNull(cle)) null else o.optDouble(cle).takeIf { !it.isNaN() }

    private fun instant(s: String): ZonedDateTime? = if (s.isBlank()) null else try {
        OffsetDateTime.parse(s).atZoneSameInstant(MeteoMer.ZONE)
    } catch (_: Exception) {
        null
    }

    // ------------------------------------------------------------ fraîcheur et valeurs

    /** La dernière mesure à l'instant [refS] (secondes), ou null. */
    fun mesure(s: Station, refS: Long): Mesure? = s.mesures.lastOrNull { it.t <= refS }

    /** Âge en minutes de la mesure [m] à l'instant [refS]. */
    fun age(m: Mesure, refS: Long): Int = max(0L, (refS - m.t) / 60L).toInt()

    /** Mesure assez récente pour être montrée comme actuelle (seuil de la source). */
    fun fraiche(s: Station, m: Mesure?, refS: Long): Boolean = m != null && refS - m.t <= s.seuilMin * 60L

    /** Moyenne du vent et rafale maximale sur les 15 min avant [refS] (rafale : à défaut le vent maximal). */
    fun quinze(s: Station, refS: Long): Pair<Double, Double>? {
        val l = s.mesures.filter { it.t in (refS - 15 * 60L)..refS }
        if (l.isEmpty()) return null
        val moy = l.map { it.vent }.average()
        val raf = l.mapNotNull { it.rafale }.maxOrNull() ?: l.maxOf { it.vent }
        return moy to raf
    }

    /** « il y a 1 min », « il y a 12 min », « il y a 1 h 05 ». */
    fun ilYa(minutes: Int): String = when {
        minutes <= 1 -> "il y a 1 min"
        minutes < 60 -> "il y a $minutes min"
        else -> "il y a ${minutes / 60} h " + (minutes % 60).toString().padStart(2, '0')
    }

    /** « 13 h 12 » d'un instant en secondes, à l'heure du plan d'eau (mer.fuseau). */
    fun heure(t: Long): String {
        val z = Instant.ofEpochSecond(t).atZone(MeteoMer.ZONE)
        return "${z.hour} h " + z.minute.toString().padStart(2, '0')
    }

    /**
     * Station choisie par défaut : la première des stations préférées (vent.preferees) qui émet, sinon la première
     * station en mer fraîche, sinon la première de la liste.
     */
    fun parDefaut(d: Donnees, refS: Long): Station? {
        fun ok(id: String) = d.station(id)?.takeIf { fraiche(it, mesure(it, refS), refS) }
        return PREFEREES.firstNotNullOfOrNull { ok(it) } ?: d.stations.firstOrNull { it.enMer && fraiche(it, mesure(it, refS), refS) } ?: d.stations.firstOrNull()
    }

    /** Stations de chaque point de prévision, par ordre de préférence (la plus représentative d'abord), celles du
     *  point par défaut pour un point inconnu. */
    fun stationsDuPoint(point: String): List<String> =
        MeteoMer.STATIONS[point]?.takeIf { it.isNotEmpty() } ?: MeteoMer.STATIONS[MeteoMer.DEFAUT] ?: emptyList()

    /**
     * La station du point qui répond : d'abord la première à moins de 15 min (une mesure récente d'une station moins
     * représentative vaut mieux qu'une vieille de la meilleure), puis la première dans le seuil de sa source, ou null.
     */
    fun pourPoint(d: Donnees, point: String, refS: Long, enMer: Boolean = false): Station? {
        val l = stationsDuPoint(point).mapNotNull { d.station(it) }.filter { !enMer || it.enMer }
        // En mer seulement (la voix) : la plus représentative du point dans le seuil de sa source.
        if (enMer) return l.firstOrNull { fraiche(it, mesure(it, refS), refS) }
        return l.firstOrNull { s -> mesure(s, refS)?.let { refS - it.t <= 15 * 60L } == true }
            ?: l.firstOrNull { fraiche(it, mesure(it, refS), refS) }
    }

    /** « d'ouest », « de sud-ouest », ou null sans direction ou sous 3 nœuds (variable). */
    fun direction(m: Mesure): String? =
        if (m.dir == null || m.vent < MeteoMer.VARIABLE) null else MeteoQuestion.de(MeteoQuestion.secteur(m.dir.toDouble())!!)

    fun noeuds(v: Double): String = v.roundToInt().let { "$it nœud" + if (it > 1) "s" else "" }

    /** Aperçu de la page Terre : « 13 nœuds de sud-ouest au Frioul, il y a 1 min », ou null sans mesure fraîche. */
    fun apercu(d: Donnees, maintenantS: Long): String? {
        val s = parDefaut(d, maintenantS) ?: return null
        val m = mesure(s, maintenantS)?.takeIf { fraiche(s, it, maintenantS) } ?: return null
        return noeuds(m.vent) + (direction(m)?.let { " " + it.replaceFirstChar { c -> c.lowercase(Locale.FRANCE) } } ?: "") + " à ${s.nom}, " + ilYa(age(m, maintenantS))
    }

    /** Ligne de mesure du bloc du moment de la page des prévisions : « Mesuré au Frioul il y a 2 min : 13 nœuds de sud-ouest ». */
    fun ligneMesure(d: Donnees?, point: String, maintenantS: Long): String? {
        val s = d?.let { pourPoint(it, point, maintenantS) } ?: return null
        val m = mesure(s, maintenantS) ?: return null
        return "Mesuré à ${s.nom} ${ilYa(age(m, maintenantS))} : " + noeuds(m.vent) +
            (direction(m)?.let { " " + it.replaceFirstChar { c -> c.lowercase(Locale.FRANCE) } } ?: "")
    }

    /** Prévision ARPEGE à l'heure de [refS] au point de la station, ou null. */
    fun prevu(s: Station, mer: MeteoMer.Donnees?, refS: Long): Pair<Int, Double>? {
        val p = mer?.points?.firstOrNull { it.id == s.point } ?: return null
        val h = Instant.ofEpochSecond(refS).atZone(MeteoMer.ZONE).toLocalDateTime().withMinute(0).withSecond(0).withNano(0)
        val x = p.heures.firstOrNull { it.t == h }?.vent ?: return null
        return h.hour to x
    }

    // ------------------------------------------------------------ carte

    /** Position d'une station sur la carte, en pixels de maquette, ou null hors du cadre. */
    fun carte(lat: Double, lon: Double): Pair<Float, Float>? {
        if (lat < LAT0 || lat > LAT1 || lon < LON0 || lon > LON1) return null
        return ((lon - LON0) / (LON1 - LON0) * LARGEUR).toFloat() to ((LAT1 - lat) / (LAT1 - LAT0) * HAUTEUR).toFloat()
    }

    /** Décalage du bloc de chaque station vers la mer (vent.carte.decalages), le reste par défaut vers le sud. */
    private val DECALAGE: Map<String, Pair<Float, Float>> = CARTE.optJSONObject("decalages")?.let { o ->
        o.keys().asSequence().mapNotNull { k -> o.optJSONArray(k)?.takeIf { it.length() >= 2 }?.let { k to (it.getDouble(0).toFloat() to it.getDouble(1).toFloat()) } }.toMap()
    } ?: emptyMap()

    /** Un bloc de la carte : la station, son point, le centre de son bloc. */
    data class Bloc(val station: Station, val x: Float, val y: Float, val bx: Float, val by: Float)

    /**
     * Blocs des stations du cadre. Évitement simple : un bloc qui en touche un autre déjà placé descend de 40 px, au
     * plus trois fois, en restant dans la carte.
     */
    fun blocs(d: Donnees): List<Bloc> {
        val sortie = ArrayList<Bloc>()
        for (s in d.stations) {
            val (x, y) = carte(s.lat, s.lon) ?: continue
            val (dx, dy) = DECALAGE[s.id] ?: (0f to 90f)
            var bx = (x + dx).coerceIn(40f, LARGEUR - 40f)
            var by = (y + dy).coerceIn(48f, HAUTEUR - 52f)
            var essais = 0
            while (essais < 3 && sortie.any { abs(it.bx - bx) < 70f && abs(it.by - by) < 80f }) {
                by = (by + 40f).coerceAtMost(HAUTEUR - 52f)
                bx = (bx + 24f).coerceAtMost(LARGEUR - 40f)
                essais++
            }
            sortie.add(Bloc(s, x, y, bx, by))
        }
        return sortie
    }

    /** Station touchée sur la carte en ([x], [y]) pixels de maquette : le bloc ou le point le plus proche à 48 px près. */
    fun touchee(blocs: List<Bloc>, x: Float, y: Float): Station? =
        blocs.map { b -> b to minOf(hypot(b.bx - x, b.by - 10f - y), hypot(b.x - x, b.y - y)) }
            .filter { it.second < 48f }.minByOrNull { it.second }?.first?.station

    // ------------------------------------------------------------ voix

    /**
     * Réponse à une question sur le vent en mer maintenant (« quel vent au Prado ») par la mesure de la station du
     * point, ou de la plus représentative si elle n'émet pas, puis la prévision. Null sans aucune mesure fraîche en
     * mer : la réponse par les prévisions prend le relais.
     */
    fun reponse(q: MeteoQuestion.Question, d: Donnees?, mer: MeteoMer.Donnees?, maintenant: ZonedDateTime): MeteoQuestion.Reponse? {
        if (d == null) return null
        val refS = maintenant.toEpochSecond()
        // À la voix, une station en mer d'abord : la question porte sur le plan d'eau.
        val s = pourPoint(d, q.point, refS, enMer = true) ?: d.stations.firstOrNull { it.enMer && fraiche(it, mesure(it, refS), refS) } ?: return null
        val m = mesure(s, refS) ?: return null
        val a = age(m, refS)
        val dir = direction(m)?.replaceFirstChar { it.lowercase(Locale.FRANCE) }
        val prev = prevu(s, mer, refS)
        val nomVoulu = MeteoMer.NOMS[q.point] ?: MeteoMer.NOMS[MeteoMer.DEFAUT] ?: ""
        // La balise du point n'émet pas : on le dit avant de donner celle qui répond.
        val absente = q.pointDit && stationsDuPoint(q.point).firstOrNull() != s.id && q.point !in MeteoMer.SANS_STATION
        val lignes = ArrayList<String>()
        lignes.add(noeuds(m.vent).replaceFirstChar { it.uppercase(Locale.FRANCE) } + (dir?.let { " $it" } ?: ", vent variable") + ".")
        lignes.add(MeteoQuestion.majuscule(ilYa(a)) + (m.rafale?.let { ", rafales ${it.roundToInt()}" } ?: "") + ".")
        prev?.let { lignes.add("Prévu à ${it.first} h : ${noeuds(it.second)}.") }
        val minutes = if (a <= 1) "1 minute" else "$a minutes"
        val parle = (if (absente) "La balise de $nomVoulu n'émet pas en ce moment. " else "") +
            "${s.nom} mesure ${noeuds(m.vent)}" + (dir?.let { " $it" } ?: "") + " il y a $minutes" +
            (m.rafale?.let { ", rafales à ${it.roundToInt()}" } ?: "") + "." +
            (prev?.let { " La prévision en donnait ${it.second.roundToInt()}." } ?: "")
        return MeteoQuestion.Reponse(
            MeteoQuestion.Page.VENT, "Vent mesuré à ${s.nom}", lignes, parle,
            maintenant.withZoneSameInstant(MeteoMer.ZONE).toLocalDate(), MeteoQuestion.Sujet.MER,
            detail = "" to "", point = q.point, station = s.id,
        )
    }
}
