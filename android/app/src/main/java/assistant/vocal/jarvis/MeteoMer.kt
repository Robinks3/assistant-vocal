package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.LocalTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.temporal.ChronoUnit
import java.util.Locale
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.roundToInt
import kotlin.math.sin

/**
 * Page Mer du panneau Météo (0.23.0, maquettes `MeteoMer*` relues le 22/10) : conditions de navigation du jour
 * dans la rade de Marseille, servies par le serveur de l'assistant (message `meteo_mer`, serveur 0.21.0). Logique pure,
 * testée sur la machine (MeteoMerTest). Les vues (EcranMer) ne font que dessiner ce qui est calculé ici.
 *
 * Trois points en mer, constantes du serveur : Prado, devant le Pharo, milieu de rade. Vent ARPEGE et
 * AROME par Open-Meteo, vagues régionales (WaveWatch III) ou MFWAM, station à terre du Vieux-Port.
 * Règles de la synthèse (relecture marine) : la brise est établie à la première de deux heures de suite à 4 nœuds
 * ou plus, retombée après deux heures sous 4 nœuds. « Calme » sous 1 nœud. Bascule citée dès 30 degrés. Sous
 * 3 nœuds, la direction est « variable ».
 */
internal object MeteoMer {

    /** Plan d'eau : section « mer » de maison.json (points, mots qui les désignent, station à terre, libellés). */
    private val CONF: JSONObject = ConfigMaison.section("mer")
    /** Faux sans sections « mer » et « vent » actives (les deux pages se suivent dans le panneau) : pages Mer et
     *  Vent masquées, aucune question classée « mer ». Le cadre de la carte doit compter quatre nombres. */
    val ACTIF: Boolean = CONF.optBoolean("actif", false) && ConfigMaison.section("vent").let { v ->
        v.optBoolean("actif", false) && (v.optJSONArray("cadre")?.length() ?: 0) >= 4
    }
    private val PTS: List<JSONObject> = CONF.optJSONArray("points")?.let { a -> (0 until a.length()).mapNotNull { a.optJSONObject(it) } } ?: emptyList()
    val POINTS: List<String> = PTS.map { it.optString("id") }
    /** Point par défaut (« defaut » vrai, sinon le premier). */
    val DEFAUT: String = PTS.firstOrNull { it.optBoolean("defaut") }?.optString("id") ?: POINTS.firstOrNull() ?: ""
    val NOMS: Map<String, String> = PTS.associate { it.optString("id") to it.optString("nom") }
    private val TITRES: Map<String, String> = PTS.associate { it.optString("id") to it.optString("titre") }
    /** Stations de chaque point, la plus représentative d'abord (page du vent mesuré). */
    val STATIONS: Map<String, List<String>> = PTS.associate { it.optString("id") to ConfigMaison.chaines(it, "stations") }
    /** Points sans station à eux : la réponse ne dit pas que leur balise n'émet pas. */
    val SANS_STATION: Set<String> = PTS.filter { it.optBoolean("sans_station") }.map { it.optString("id") }.toSet()
    /** Mots qui désignent un point (« frioul » pour le Pharo), dans l'ordre où ils sont cherchés. */
    val ALIAS: List<Pair<String, String>> = CONF.optJSONArray("alias")?.let { a ->
        (0 until a.length()).mapNotNull { i -> a.optJSONArray(i)?.takeIf { it.length() >= 2 }?.let { it.getString(0) to it.getString(1) } }
    } ?: emptyList()
    /** Autres noms de lieu du plan d'eau permis après « à » dans une question (la ville). */
    val MOTS_LIEU: List<String> = ConfigMaison.chaines(CONF, "mots_lieu")
    private val TITRE_DEFAUT: String = CONF.optString("titre").ifEmpty { CONF.optString("nom") }.ifEmpty { "Mer" }
    /** Libellé de la page Terre vu depuis les pages de la mer (« Météo à ... »). */
    val LIBELLE_TERRE: String = CONF.optString("libelle_terre").ifEmpty { "Météo" }
    private val ATTRIBUTION: String = CONF.optString("attribution")
    /** Noms des deux modèles de prévision du vent, affichés dans les lignes et les légendes. */
    val NOM_PRINCIPAL: String = CONF.optJSONObject("modele_principal")?.optString("nom")?.ifEmpty { null } ?: "prévision"
    val NOM_SECOND: String = CONF.optJSONObject("modele_second")?.optString("nom")?.ifEmpty { null } ?: "second modèle"
    /** Point dont la station à terre donne la mesure du bloc du moment. */
    private val POINT_STATION: String = CONF.optJSONObject("station")?.optString("point") ?: ""

    /** Journée de navigation : de 7 h à 20 h (fin exclue), choix du 22/10. */
    const val DEBUT_JOURNEE = 7
    const val FIN_JOURNEE = 20

    /** Seuils de la synthèse, en nœuds. */
    const val ETABLIE = 4.0
    const val CALME = 1.0
    const val VARIABLE = 3.0
    const val DESACCORD = 3.0

    /** Mesure de la station gardée 15 min. */
    const val FRAICHEUR_STATION_MS = 15 * 60_000L

    val ZONE: ZoneId = runCatching { ZoneId.of(CONF.optString("fuseau").ifEmpty { "UTC" }) }.getOrDefault(ZoneId.of("UTC"))

    data class Heure(
        val t: LocalDateTime,
        val vent: Double?, val rafales: Double?, val dir: Int?,
        val vent2: Double? = null, val dir2: Int? = null,
        val air: Double? = null, val pluie: Double? = null, val cape: Int? = null, val foudre: Double? = null, val code: Int? = null,
        val visi: Int? = null,
        val vagues: Double? = null, val periode: Double? = null, val dirVagues: Int? = null,
    )

    data class Point(val id: String, val nom: String, val sourceVagues: String, val heures: List<Heure>)

    data class Station(val nom: String, val vent: Double?, val dir: Int?, val le: ZonedDateTime?)

    data class Soleil(val jour: LocalDate, val lever: LocalTime?, val coucher: LocalTime?)

    data class Donnees(
        val luA: ZonedDateTime?,
        val points: List<Point>,
        val eau: Double?,
        val soleil: List<Soleil>,
        val station: Station?,
        val erreurs: List<String>,
    ) {
        fun point(id: String): Point? = points.firstOrNull { it.id == id } ?: points.firstOrNull()
    }

    // ------------------------------------------------------------ lecture

    /**
     * Données de la réponse du serveur (`{"etat":"meteo_mer","id","donnees"}`, ou les seules `donnees`), ou null
     * avec le message lisible de l'échec.
     */
    fun lire(reponse: JSONObject?): Pair<Donnees?, String> {
        if (reponse == null) return null to "le serveur ne répond pas"
        reponse.optString("erreur").takeIf { it.isNotBlank() }?.let { return null to it }
        val d = reponse.optJSONObject("donnees") ?: reponse.takeIf { it.has("points") } ?: return null to "réponse sans données"
        return try {
            val points = ArrayList<Point>()
            val a = d.optJSONArray("points") ?: JSONArray()
            for (i in 0 until a.length()) {
                val p = a.optJSONObject(i) ?: continue
                val id = p.optString("id")
                if (id.isEmpty()) continue
                val hs = ArrayList<Heure>()
                val ha = p.optJSONArray("heures") ?: JSONArray()
                for (k in 0 until ha.length()) {
                    val h = ha.optJSONObject(k) ?: continue
                    val t = try { LocalDateTime.parse(h.optString("t")) } catch (_: Exception) { continue }
                    hs.add(
                        Heure(
                            t, nombre(h, "vent"), nombre(h, "rafales"), entier(h, "dir"), nombre(h, "vent2"), entier(h, "dir2"),
                            nombre(h, "air"), nombre(h, "pluie"), entier(h, "cape"), nombre(h, "foudre"), entier(h, "code"),
                            entier(h, "visi"), nombre(h, "vagues"), nombre(h, "periode"), entier(h, "dir_vagues"),
                        )
                    )
                }
                points.add(Point(id, p.optString("nom").ifBlank { NOMS[id] ?: id }, p.optString("vagues_source"), hs.sortedBy { it.t }))
            }
            if (points.isEmpty()) return null to "aucun point en mer"
            val soleil = ArrayList<Soleil>()
            d.optJSONArray("soleil")?.let { s ->
                for (i in 0 until s.length()) {
                    val o = s.optJSONObject(i) ?: continue
                    val jour = try { LocalDate.parse(o.optString("jour")) } catch (_: Exception) { continue }
                    soleil.add(Soleil(jour, heure(o.optString("lever")), heure(o.optString("coucher"))))
                }
            }
            val station = d.optJSONObject("station")?.let { o ->
                Station(o.optString("nom"), nombre(o, "vent"), entier(o, "dir"), instant(o.optString("le")))
            }
            val erreurs = d.optJSONArray("erreurs")?.let { e -> (0 until e.length()).map { e.optString(it) }.filter { it.isNotBlank() } } ?: emptyList()
            Donnees(instant(d.optString("lu_a")), points, nombre(d, "eau"), soleil, station, erreurs) to ""
        } catch (e: Exception) {
            null to "réponse illisible (${e.javaClass.simpleName})"
        }
    }

    private fun nombre(o: JSONObject, cle: String): Double? =
        if (!o.has(cle) || o.isNull(cle)) null else o.optDouble(cle).takeIf { !it.isNaN() }

    private fun entier(o: JSONObject, cle: String): Int? = nombre(o, cle)?.roundToInt()

    private fun heure(s: String): LocalTime? = try { LocalTime.parse(s) } catch (_: Exception) { null }

    private fun instant(s: String): ZonedDateTime? = if (s.isBlank()) null else try {
        OffsetDateTime.parse(s).atZoneSameInstant(ZONE)
    } catch (_: Exception) {
        null
    }

    // ------------------------------------------------------------ frise et journée

    /** Une colonne de la frise : l'heure, et si elle ouvre un nouveau jour (la nuit est sautée). */
    data class Colonne(val h: Heure, val saut: Boolean)

    /**
     * Colonnes de la frise : de l'heure en cours jusqu'à 20 h, puis les journées suivantes de 7 h à 20 h, la nuit
     * sautée. Chaque premier instant d'un nouveau jour porte [Colonne.saut].
     */
    fun colonnes(p: Point, maintenant: ZonedDateTime): List<Colonne> {
        val debut = maintenant.withZoneSameInstant(ZONE).toLocalDateTime().truncatedTo(ChronoUnit.HOURS)
        val l = p.heures.filter { !it.t.isBefore(debut) && it.t.hour in DEBUT_JOURNEE..FIN_JOURNEE }
        return l.mapIndexed { i, h -> Colonne(h, i > 0 && h.t.toLocalDate() != l[i - 1].t.toLocalDate()) }
    }

    /**
     * Heures de la journée de navigation : aujourd'hui de l'heure en cours (7 h au plus tôt) à 20 h, ou demain
     * passé 20 h. [jour] et [debut] / [fin] imposent une autre plage (question à la voix).
     */
    fun journee(p: Point, maintenant: ZonedDateTime, jour: Int? = null, debut: Int = DEBUT_JOURNEE, fin: Int = FIN_JOURNEE): List<Heure> {
        val m = maintenant.withZoneSameInstant(ZONE)
        val j = jour ?: if (m.hour >= FIN_JOURNEE) 1 else 0
        val date = m.toLocalDate().plusDays(j.toLong())
        val de = if (j == 0) maxOf(debut, m.hour) else debut
        return p.heures.filter { it.t.toLocalDate() == date && it.t.hour >= de && it.t.hour < fin && it.vent != null }
    }

    // ------------------------------------------------------------ synthèse

    /**
     * Synthèse d'une plage : les lignes écrites, la phrase dite (sans le lieu ni le jour), et ce qui sert ailleurs
     * (aperçu de la page Terre, ligne de détail).
     */
    data class Synthese(
        val lignes: List<String>,
        val parle: String,
        val apercu: String,
        val detail: String,
        val orage: Heure? = null,
    )

    fun synthese(w: List<Heure>, quand: String): Synthese {
        if (w.isEmpty()) return Synthese(listOf("Pas de prévision de vent."), "Je n'ai pas de prévision de vent.", "pas de prévision", "pas de prévision")
        val v = w.map { it.vent ?: 0.0 }
        val n = w.size
        val lignes = ArrayList<String>()
        val dit = ArrayList<String>()
        val details = ArrayList<String>()
        val orage = w.firstOrNull { (it.cape ?: 0) >= 1000 || (it.foudre ?: 0.0) > 0.0 }
        orage?.let {
            lignes.add("Risque d'orage vers ${it.t.hour} h.")
            dit.add("Risque d'orage vers ${it.t.hour} heures.")
        }
        val e = (0 until n - 1).firstOrNull { v[it] >= ETABLIE && v[it + 1] >= ETABLIE }
        var apercu: String
        if (e == null) {
            val calme = v.max() < CALME
            val texte = if (calme) "Calme" else "Moins de 4 nœuds"
            val fin = w.last().t.hour + 1
            val suite = if (w.first().t.hour <= DEBUT_JOURNEE && fin >= FIN_JOURNEE) "toute la journée" else "jusqu'à $fin h"
            lignes.add("$texte $suite.")
            dit.add("$texte ${suite.replace(" h", " heures")}.")
            details.add("${texte.lowercase(Locale.FRANCE)} $suite")
            apercu = if (calme) "calme $quand" else "moins de 4 nœuds $quand"
        } else {
            if (e > 0) {
                val calme = w.subList(0, e).all { (it.vent ?: 0.0) < CALME }
                val avant = (if (calme) "Calme" else "Moins de 4 nœuds") + " avant ${w[e].t.hour} h"
                lignes.add("$avant.")
                dit.add(avant.replace(" h", " heures"))
                details.add(avant.lowercase(Locale.FRANCE).replaceFirstChar { it })
            }
            val t = (e + 1 until n).firstOrNull { j -> v[j] < ETABLIE && (j == n - 1 || v[j + 1] < ETABLIE) }
            val etab = w.subList(e, t ?: n)
            val mn = etab.mapNotNull { it.vent }.min().roundToInt()
            val mx = etab.mapNotNull { it.vent }.max().roundToInt()
            val ecart = if (mn == mx) "$mx" else "$mn à $mx"
            val d0 = moyenne(etab.take(2))
            val s0 = MeteoQuestion.secteur(d0)
            val tete = if (e > 0) "Puis " + (s0?.let { "$it, " } ?: "") else (s0?.let { MeteoQuestion.majuscule(it) + ", " } ?: "")
            lignes.add("$tete$ecart nœuds.")
            dit.add((if (e > 0) "puis " else "") + (s0?.let { "$it, " } ?: "") + "$ecart nœuds")
            details.add((if (e > 0) "puis " else "") + (s0?.let { "$it " } ?: "") + "$ecart nœuds")
            val bascule = if (d0 == null) null else etab.drop(2).firstOrNull { h ->
                h.dir != null && angle(h.dir.toDouble(), d0) >= 30.0 && MeteoQuestion.secteur(h.dir.toDouble()) != s0
            }
            val sb = bascule?.let { MeteoQuestion.secteur(it.dir!!.toDouble()) }
            val ht = t?.let { w[it].t.hour }
            when {
                bascule != null && ht != null -> {
                    lignes.add("${MeteoQuestion.majuscule(sb!!)} vers ${bascule.t.hour} h, retombe à $ht h.")
                    dit[dit.size - 1] = dit.last() + ", passant ${aLa(sb)} vers ${bascule.t.hour} heures, puis retombe à $ht heures."
                    details.add("$sb vers ${bascule.t.hour} h, retombe à $ht h")
                }
                bascule != null -> {
                    lignes.add("${MeteoQuestion.majuscule(sb!!)} vers ${bascule.t.hour} h.")
                    dit[dit.size - 1] = dit.last() + ", passant ${aLa(sb)} vers ${bascule.t.hour} heures."
                    details.add("$sb vers ${bascule.t.hour} h")
                }
                ht != null -> {
                    lignes.add("Retombe à $ht h.")
                    dit[dit.size - 1] = dit.last() + ", puis retombe à $ht heures."
                    details.add("retombe à $ht h")
                }
                else -> dit[dit.size - 1] = dit.last() + "."
            }
            if (e > 0 && dit.size >= 2 && orage == null) {
                // « Moins de 4 nœuds avant 14 heures, puis sud-ouest... » : une seule phrase.
                dit[0] = dit[0] + ", " + dit.removeAt(1)
            } else if (e > 0 && orage != null && dit.size >= 3) {
                dit[1] = dit[1] + ", " + dit.removeAt(2)
            }
            apercu = (s0?.let { "$it " } ?: "") + "$ecart nœuds " + (if (w[e].t.hour >= 12 && quand == "aujourd'hui") "cet après-midi" else quand)
        }
        // Désaccord des modèles sur deux heures de suite : dit quand il reste de la place.
        val desaccord = (0 until n - 1).firstOrNull { k ->
            val a = w[k].vent2?.let { abs(it - (w[k].vent ?: it)) } ?: 0.0
            val b = w[k + 1].vent2?.let { abs(it - (w[k + 1].vent ?: it)) } ?: 0.0
            a >= DESACCORD && b >= DESACCORD
        }
        if (desaccord != null && lignes.size < 4) {
            lignes.add("Modèles en désaccord vers ${w[desaccord].t.hour} h.")
            dit.add("Les modèles ne sont pas d'accord vers ${w[desaccord].t.hour} heures.")
        }
        val g = w.mapNotNull { it.rafales }.maxOrNull()?.roundToInt()
        val vg = w.mapNotNull { it.vagues }
        val vagues = if (vg.isEmpty()) null else {
            val a = vg.min()
            val b = vg.max()
            if (dixieme(a) == dixieme(b)) "vagues ${dixieme(b)} m" else "vagues ${dixieme(a)} à ${dixieme(b)} m"
        }
        val fin = listOfNotNull(g?.let { "Rafales $it" }, vagues).joinToString(", ")
        if (fin.isNotEmpty()) lignes.add("$fin.")
        val finDite = listOfNotNull(
            g?.let { "Rafales à $it nœuds" },
            vagues?.let { x -> x.replace("vagues ", "vagues de ").replace(" m", " " + if (vg.max() >= 2.0) "mètres" else "mètre") },
            if (orage == null) "pas d'orage" else null,
        ).joinToString(", ")
        if (finDite.isNotEmpty()) dit.add(MeteoQuestion.majuscule(finDite) + ".")
        if (orage != null) apercu = "risque d'orage $quand"
        details.addAll(listOfNotNull(g?.let { "rafales jusqu'à $it" }, vagues))
        val pluie = w.mapNotNull { it.pluie }.sum()
        details.add(if (pluie >= 0.1) "pluie ${MeteoTexte.mm(pluie)} mm" else "sec")
        if (orage != null) details.add("risque d'orage vers ${orage.t.hour} h")
        return Synthese(lignes.take(5), dit.joinToString(" ").replace("  ", " ").trim(), apercu, details.joinToString(", "), orage)
    }

    /** « à l'ouest », « au sud-ouest », « au nord ». */
    private fun aLa(secteur: String): String = if (secteur.first() in "aeiou") "à l'$secteur" else "au $secteur"

    private fun dixieme(v: Double): String = String.format(Locale.FRANCE, "%.1f", v)

    /** Direction moyenne des heures (pondérée par la force du vent), ou null. */
    fun moyenne(l: List<Heure>): Double? {
        var x = 0.0
        var y = 0.0
        for (h in l) {
            val d = h.dir ?: continue
            val v = h.vent ?: 1.0
            x += v * cos(Math.toRadians(d.toDouble()))
            y += v * sin(Math.toRadians(d.toDouble()))
        }
        if (abs(x) < 1e-9 && abs(y) < 1e-9) return null
        return (Math.toDegrees(atan2(y, x)) + 360.0) % 360.0
    }

    /** Écart d'angle entre deux directions, de 0 à 180 degrés. */
    fun angle(a: Double, b: Double): Double {
        val d = abs(((a - b) % 360.0 + 360.0) % 360.0)
        return if (d > 180.0) 360.0 - d else d
    }

    // ------------------------------------------------------------ écrans

    fun titre(point: String): String = TITRES[point]?.ifEmpty { null } ?: TITRE_DEFAUT

    /** Direction affichée : « Variable » sous 3 nœuds, sinon « D'ouest, 272° ». */
    fun direction(vent: Double?, dir: Int?): String = when {
        vent == null || dir == null || vent < VARIABLE -> "Variable"
        else -> MeteoQuestion.majuscule(MeteoQuestion.de(MeteoQuestion.secteur(dir.toDouble())!!)) + ", $dir°"
    }

    /** L'heure en cours d'un point, ou la première à venir. */
    fun maintenant(p: Point, maintenant: ZonedDateTime): Heure? {
        val h = maintenant.withZoneSameInstant(ZONE).toLocalDateTime().truncatedTo(ChronoUnit.HOURS)
        return p.heures.firstOrNull { it.t == h } ?: p.heures.firstOrNull { it.t.isAfter(h) }
    }

    /** Deuxième ligne du bloc du moment : rafales et second modèle. */
    fun ligneRafales(h: Heure?): String = listOfNotNull(
        h?.rafales?.let { "Rafales ${noeuds(it)}" },
        h?.vent2?.let { "$NOM_SECOND ${noeuds(it)}" },
    ).joinToString(", ")

    /** « 1 nœud », « 3 nœuds ». */
    fun noeuds(v: Double): String = v.roundToInt().let { "$it nœud" + if (it > 1) "s" else "" }

    /**
     * Troisième ligne du bloc du moment : la station à terre de son point si sa mesure a moins de 15 min, sinon les
     * vagues et l'eau.
     */
    fun ligneMesure(point: String, d: Donnees, h: Heure?, maintenant: ZonedDateTime): String {
        val s = d.station
        if (point == POINT_STATION && s?.vent != null && s.le != null) {
            val age = java.time.Duration.between(s.le, maintenant).toMillis()
            if (age in -60_000L..FRAICHEUR_STATION_MS) {
                val sec = if (s.vent < VARIABLE || s.dir == null) "" else " " + MeteoQuestion.de(MeteoQuestion.secteur(s.dir.toDouble())!!)
                return "Station à terre, ${s.le.hour} h ${s.le.minute.toString().padStart(2, '0')} : ${s.vent.roundToInt()} nœud${if (s.vent.roundToInt() > 1) "s" else ""}$sec"
            }
        }
        return listOfNotNull(
            h?.vagues?.let { "Vagues ${dixieme(it)} m" + (h.periode?.let { p -> " en ${p.roundToInt()} s" } ?: "") },
            d.eau?.let { "eau ${it.roundToInt()}°" },
        ).joinToString(", ")
    }

    /** Ligne de détail d'une heure touchée. */
    fun detail(h: Heure): Pair<String, String> {
        val parties = ArrayList<String>()
        h.vent?.let { v ->
            val r = v.roundToInt()
            parties.add("$r nœud${if (r > 1) "s" else ""}" + if (h.dir != null && v >= VARIABLE) " ${MeteoQuestion.de(MeteoQuestion.secteur(h.dir.toDouble())!!)} (${h.dir}°)" else ", variable")
        }
        h.rafales?.let { parties.add("rafales ${it.roundToInt()}") }
        h.vent2?.let { parties.add("$NOM_SECOND ${it.roundToInt()}") }
        h.vagues?.let { parties.add("vagues ${dixieme(it)} m" + (h.periode?.let { p -> " en ${p.roundToInt()} s" } ?: "")) }
        h.air?.let { parties.add("air ${it.roundToInt()}°") }
        parties.add(if ((h.pluie ?: 0.0) >= 0.1) "pluie ${MeteoTexte.mm(h.pluie!!)} mm" else "sec")
        if ((h.cape ?: 0) >= 1000 || (h.foudre ?: 0.0) > 0.0) parties.add("risque d'orage")
        h.visi?.takeIf { it < 5000 }?.let { parties.add("visibilité ${dixieme(it / 1000.0)} km") }
        return "${h.t.hour} h" to " : " + parties.joinToString(", ")
    }

    /** Une case du bas de la page : nom, valeur en grand, deux lignes. */
    data class Case(val nom: String, val valeur: String, val ligne1: String, val ligne2: String, val chiffres: Boolean)

    /**
     * Cases de droite : écart des modèles sur la journée, orages, eau et air à l'heure choisie [h], soleil.
     */
    fun cases(d: Donnees, w: List<Heure>, h: Heure?, maintenant: ZonedDateTime): List<Case> {
        val m = maintenant.withZoneSameInstant(ZONE)
        val ecart = w.filter { it.vent != null && it.vent2 != null }.maxByOrNull { abs(it.vent!! - it.vent2!!) }
        val modeles = if (ecart == null) Case("Modèles", "", "un seul modèle", "", false) else {
            val e = abs(ecart.vent!! - ecart.vent2!!).roundToInt()
            Case("Modèles", "$e nœud${if (e > 1) "s" else ""}", "d'écart au plus", "à ${ecart.t.hour} h", true)
        }
        val orage = w.firstOrNull { (it.cape ?: 0) >= 1000 || (it.foudre ?: 0.0) > 0.0 }
        val finW = w.lastOrNull()?.t
        val jusque = if (finW == null) "" else "jusqu'à " + (if (finW.toLocalDate() != m.toLocalDate()) "demain " else "") + "${finW.hour + 1} h"
        val orages = if (orage == null) Case("Orages", "Aucun", jusque, "", false) else Case("Orages", "Risque", "vers ${orage.t.hour} h", "", false)
        val eau = Case("Eau", d.eau?.let { "${it.roundToInt()}°" } ?: "", h?.air?.let { "air ${it.roundToInt()}°" } ?: "", "", true)
        val aujourd = d.soleil.firstOrNull { it.jour == m.toLocalDate() }
        val demain = d.soleil.firstOrNull { it.jour == m.toLocalDate().plusDays(1) }
        fun hm(t: LocalTime) = "${t.hour} h ${t.minute.toString().padStart(2, '0')}"
        val soleil = when {
            aujourd?.coucher != null && m.toLocalTime().isBefore(aujourd.coucher) ->
                Case("Soleil", hm(aujourd.coucher), "coucher", (demain?.lever ?: aujourd.lever)?.let { "lever ${hm(it)}" } ?: "", true)
            demain?.lever != null -> Case("Soleil", hm(demain.lever), "lever", demain.coucher?.let { "coucher ${hm(it)}" } ?: "", true)
            else -> Case("Soleil", "", "", "", true)
        }
        return listOf(modeles, orages, eau, soleil)
    }

    /** Ligne des sources, avec l'heure de lecture et les sources en panne. */
    fun sources(d: Donnees): String {
        val lu = d.luA?.let { " Lu à ${it.hour} h ${it.minute.toString().padStart(2, '0')}." } ?: ""
        val pannes = if (d.erreurs.isEmpty()) "" else " " + MeteoQuestion.majuscule(d.erreurs.joinToString(", ")) + "."
        return "$ATTRIBUTION$lu$pannes".trim()
    }

    /** Aperçu de la page Terre : « sud-ouest 5 à 6 nœuds cet après-midi » au point par défaut, ou null sans donnée. */
    fun apercu(d: Donnees, maintenant: ZonedDateTime): String? {
        val p = d.point(DEFAUT) ?: return null
        val w = journee(p, maintenant)
        if (w.isEmpty()) return null
        val quand = if (w.first().t.toLocalDate() == maintenant.withZoneSameInstant(ZONE).toLocalDate()) "aujourd'hui" else "demain"
        return synthese(w, quand).apercu
    }

    // ------------------------------------------------------------ réponse à la voix

    /** Réponse à une question sur la mer (« quelles conditions en mer au Prado »), d'après [d]. */
    fun reponse(q: MeteoQuestion.Question, d: Donnees?, maintenant: ZonedDateTime, erreur: String = ""): MeteoQuestion.Reponse {
        val p = q.plage
        val date = maintenant.withZoneSameInstant(ZONE).toLocalDate().plusDays(p.jour.toLong())
        val nomPoint = NOMS[q.point] ?: NOMS[DEFAUT] ?: ""
        val entete = "Conditions de navigation ${p.nom}"
        val base = MeteoQuestion.Reponse(MeteoQuestion.Page.MER, entete, emptyList(), "", date, MeteoQuestion.Sujet.MER, point = q.point)
        val point = d?.points?.firstOrNull { it.id == q.point }
        if (d == null || point == null) {
            val pourquoi = erreur.ifBlank { "pas de donnée" }
            return base.copy(lignes = listOf("Mer indisponible.", MeteoQuestion.majuscule(pourquoi) + "."), parle = "Je n'ai pas la météo de la mer : $pourquoi.")
        }
        val w = journee(point, maintenant, p.jour, p.debut, p.fin)
        if (w.isEmpty()) {
            return base.copy(lignes = listOf("Pas de prévision ${p.nom}."), parle = "Je n'ai pas de prévision en mer pour ${p.nom}.")
        }
        val s = synthese(w, p.nom)
        val debut = w.first().t.atZone(ZONE).toInstant().toEpochMilli()
        val fin = w.last().t.plusHours(1).atZone(ZONE).toInstant().toEpochMilli()
        val choisi = (s.orage ?: w.maxByOrNull { it.vent ?: 0.0 })?.t?.atZone(ZONE)?.toInstant()?.toEpochMilli()
        val tete = "De ${w.first().t.hour} h à ${w.last().t.hour + 1} h"
        return base.copy(
            lignes = s.lignes,
            parle = "À $nomPoint ${p.nom}, " + s.parle.replaceFirstChar { it.lowercase(Locale.FRANCE) },
            bandeDebut = debut, bandeFin = fin, choisi = choisi,
            detail = tete to " : " + s.detail,
        )
    }
}
