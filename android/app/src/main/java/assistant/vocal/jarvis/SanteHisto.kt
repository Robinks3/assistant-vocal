package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.TextStyle
import java.util.Locale
import kotlin.math.roundToInt

/**
 * Historique de la santé pour les onglets Tendances, Séances, Records et la vue d'un jour passé (0.22.0,
 * maquettes relues et `docs/maquettes/revue-sante-onglets.md`), en logique pure testée sur la machine
 * (SanteHistoTest, données inventées).
 *
 * Protocole du serveur 0.20 (capacité `sante_historique`) : `sante_periode` (7, 30, 90 ou 365 jours),
 * `sante_seances`, `sante_seance`, `sante_records`, `sante_jour`. Chaque réponse est `{"etat", "id",
 * "donnees"}` ou `{"etat", "id", "erreur"}`, `donnees` portant toujours `aujourdhui`, `premier_jour`,
 * `genere_le`, `lu_a` et `perime`. Lecture défensive : tout champ peut manquer ou être nul, une valeur
 * absente ne s'affiche pas. Rien de ceci n'est gardé ailleurs qu'en mémoire du panneau ouvert.
 */
internal object SanteHisto {

    /** Fuseau des données (le serveur compte les jours à l'heure de Paris), jamais celui de l'appareil. */
    val PARIS: ZoneId = ZoneId.of("Europe/Paris")

    /** Aujourd'hui à Paris. */
    fun aujourdhui(): LocalDate = LocalDate.now(PARIS)

    // ------------------------------------------------------------ lecture de base

    fun donnees(r: JSONObject?): JSONObject? {
        if (r == null || r.has("erreur")) return null
        return if (r.has("donnees")) r.optJSONObject("donnees") else r
    }

    fun entier(o: JSONObject?, cle: String, max: Int = 10_000_000): Int? = Sante.entier(o, cle)?.takeIf { it in 0..max }
    fun texte(o: JSONObject?, cle: String): String? = Sante.texte(o, cle)
    fun date(s: String?): LocalDate? = try {
        if (s == null) null else LocalDate.parse(s.take(10))
    } catch (_: Exception) {
        null
    }
    fun date(o: JSONObject?, cle: String): LocalDate? = date(texte(o, cle))

    fun moment(s: String?, zone: ZoneId = PARIS): LocalDateTime? {
        if (s == null) return null
        return try {
            OffsetDateTime.parse(s).atZoneSameInstant(zone).toLocalDateTime()
        } catch (_: Exception) {
            try {
                LocalDateTime.parse(s)
            } catch (_: Exception) {
                null
            }
        }
    }

    private fun vrai(o: JSONObject?, cle: String): Boolean = o != null && o.has(cle) && !o.isNull(cle) && o.optBoolean(cle, false)

    /** Liste parallèle [cle] de [o] : valeur i, ou null (absente, nulle, illisible). */
    private class Liste(o: JSONObject?, cle: String) {
        private val a: JSONArray? = o?.optJSONArray(cle)
        val taille: Int get() = a?.length() ?: 0
        fun entier(i: Int, max: Int = 10_000_000): Int? {
            val x = a ?: return null
            if (i >= x.length() || x.isNull(i)) return null
            val v = x.opt(i)
            val d = (v as? Number)?.toDouble() ?: (v as? Boolean)?.let { if (it) 1.0 else 0.0 } ?: return null
            if (d.isNaN()) return null
            return d.roundToInt().takeIf { it in 0..max }
        }
        fun vrai(i: Int): Boolean {
            val x = a ?: return false
            if (i >= x.length() || x.isNull(i)) return false
            return when (val v = x.opt(i)) {
                is Boolean -> v
                is Number -> v.toInt() != 0
                else -> false
            }
        }
        fun texte(i: Int): String? {
            val x = a ?: return null
            if (i >= x.length() || x.isNull(i)) return null
            return x.optString(i).ifEmpty { null }
        }
    }

    // ------------------------------------------------------------ en-tête commun

    data class Entete(val aujourdhui: LocalDate?, val premierJour: LocalDate?, val luA: LocalDateTime?, val perime: Boolean, val genereLe: LocalDateTime? = null)

    fun entete(d: JSONObject?): Entete = Entete(
        date(d, "aujourdhui") ?: date(d, "date"), date(d, "premier_jour"), moment(texte(d, "lu_a")), vrai(d, "perime"), moment(texte(d, "genere_le")),
    )

    // ------------------------------------------------------------ période (Tendances)

    /** Un jour (ou une semaine) des séries : null là où rien n'est enregistré. */
    data class Point(
        val date: LocalDate,
        val enCours: Boolean,
        val sommeil: Int?,
        val auLit: Int?,
        val profond: Int?,
        val pas: Int?,
        val fcMoyenne: Int?,
        val fcMin: Int?,
        /** Séances ce jour-là (ou jours avec séance dans la semaine). */
        val seances: Int,
        val sommeilEstime: Boolean,
        val joursRenseignes: Int? = null,
    )

    data class Sport(val nom: String, val minutes: Int?, val seances: Int?, val trimp: Int?, val sansFc: Int?)

    data class SportStat(
        val minutes: Int?,
        val seances: Int?,
        val trimp: Int?,
        val sansFc: Int?,
        val minutesParSemaine: Int?,
        val seancesParSemaine: Double?,
        val trimpParSemaine: Int?,
        val parSport: Map<String, Sport>,
    )

    data class Bilan(
        val du: LocalDate?,
        val au: LocalDate?,
        val jours: Int?,
        val couverture: Double?,
        val joursDisponibles: Int?,
        val sommeil: Int?,
        val auLit: Int?,
        val profond: Int?,
        val pas: Int?,
        val distanceM: Int?,
        val fcRepos: Int?,
        val fcMoyenne: Int?,
        val spo2Min: Int?,
        val sport: SportStat?,
        val partielle: Boolean = false,
    )

    data class Groupe(val debut: LocalDate, val jours: Int?, val enCours: Boolean, val minutes: Int?, val seances: Int?, val trimp: Int?, val sansFc: Int?, val parSport: Map<String, Sport>)

    data class Periode(
        val entete: Entete,
        val jours: Int,
        val du: LocalDate?,
        val au: LocalDate?,
        val granularite: String,
        val serie: List<Point>,
        val courbes: List<Point>,
        val bilan: Bilan?,
        val avant: Bilan?,
        val sportGranularite: String,
        val groupes: List<Groupe>,
        val horsCharge: List<String>,
    )

    /**
     * Sports principaux d'une période (0.30.1), pour les filtres et les totaux de Séances : les plus pratiqués d'abord
     * (minutes, comme l'ordre de `par_sport` du serveur, puis séances), [n] au plus, avec leur nom. Aucun sport propre à
     * quelqu'un n'est écrit dans le code : chacun voit les siens.
     */
    fun sportsPrincipaux(parSport: Map<String, Sport>, n: Int = 2): List<Pair<String, String>> =
        parSport.entries.filter { (it.value.seances ?: 0) > 0 }
            .sortedWith(compareByDescending<Map.Entry<String, Sport>> { it.value.minutes ?: 0 }.thenByDescending { it.value.seances ?: 0 })
            .take(n).map { it.key to it.value.nom.ifBlank { it.key } }

    private fun parSport(o: JSONObject?): Map<String, Sport> {
        if (o == null) return emptyMap()
        val m = LinkedHashMap<String, Sport>()
        for (k in o.keys()) {
            val s = o.optJSONObject(k) ?: continue
            m[k] = Sport(texte(s, "nom") ?: SanteDetail.libelleSeance(null, k), entier(s, "minutes"), entier(s, "seances"), entier(s, "trimp"), entier(s, "sans_fc"))
        }
        return m
    }

    private fun sportStat(o: JSONObject?): SportStat? {
        if (o == null) return null
        val sps = o.optDouble("seances_par_semaine").takeIf { !o.isNull("seances_par_semaine") && !it.isNaN() }
        return SportStat(entier(o, "minutes"), entier(o, "seances"), entier(o, "trimp"), entier(o, "sans_fc"), entier(o, "minutes_par_semaine"), sps, entier(o, "trimp_par_semaine"), parSport(o.optJSONObject("par_sport")))
    }

    private fun bilan(o: JSONObject?): Bilan? {
        if (o == null) return null
        val cv = o.optDouble("couverture").takeIf { !o.isNull("couverture") && !it.isNaN() }
        return Bilan(
            date(o, "du"), date(o, "au"), entier(o, "jours"), cv, entier(o, "jours_disponibles"),
            entier(o, "sommeil_minutes", 1440), entier(o, "au_lit_minutes", 1440), entier(o, "profond_minutes", 1440),
            entier(o, "pas", 500_000), entier(o, "distance_m"), entier(o, "fc_repos", 250), entier(o, "fc_moyenne", 250),
            entier(o, "spo2_min", 100), sportStat(o.optJSONObject("sport")), vrai(o, "partielle"),
        )
    }

    private fun points(o: JSONObject?): List<Point> {
        if (o == null) return emptyList()
        val dates = Liste(o, "dates")
        val enCours = Liste(o, "en_cours")
        val sommeil = Liste(o, "sommeil_minutes")
        val auLit = Liste(o, "au_lit_minutes")
        val profond = Liste(o, "profond_minutes")
        val pas = Liste(o, "pas")
        val fcMoy = Liste(o, "fc_moyenne")
        val fcMin = Liste(o, "fc_min")
        val seance = Liste(o, if (o.has("seance")) "seance" else "jours_seance")
        val estime = Liste(o, "sommeil_estime")
        val renseignes = Liste(o, "jours_renseignes")
        return (0 until dates.taille).mapNotNull { i ->
            val d = date(dates.texte(i)) ?: return@mapNotNull null
            Point(
                d, enCours.vrai(i), sommeil.entier(i, 1440), auLit.entier(i, 1440), profond.entier(i, 1440), pas.entier(i, 500_000),
                fcMoy.entier(i, 250), fcMin.entier(i, 250), seance.entier(i, 100) ?: 0, estime.vrai(i), renseignes.entier(i, 7),
            )
        }
    }

    fun periode(r: JSONObject?): Periode? {
        val d = donnees(r) ?: return null
        val sport = d.optJSONObject("sport")
        // À 1 an, le serveur donne les semaines dans `groupes` et les mois dans `par_mois` : le graphe montre les mois.
        val parMois = sport?.optJSONArray("par_mois")?.takeIf { it.length() > 0 }
        val granularite = if (parMois != null) "mois" else texte(sport, "granularite") ?: "semaine"
        val groupes = (parMois ?: sport?.optJSONArray("groupes") ?: JSONArray()).let { a ->
            (0 until a.length()).mapNotNull { i ->
                val g = a.optJSONObject(i) ?: return@mapNotNull null
                val debut = date(g, "debut") ?: return@mapNotNull null
                Groupe(debut, entier(g, "jours", 400), vrai(g, "en_cours"), entier(g, "minutes"), entier(g, "seances"), entier(g, "trimp"), entier(g, "sans_fc"), parSport(g.optJSONObject("par_sport")))
            }
        }
        val avantO = d.optJSONObject("avant")
        val horsCharge = d.optJSONArray("hors_charge")?.let { a -> (0 until a.length()).mapNotNull { a.optString(it).ifEmpty { null } } } ?: emptyList()
        return Periode(
            entete(d), entier(d, "jours", 400) ?: 0, date(d, "du"), date(d, "au"), texte(d, "granularite") ?: "jour",
            points(d.optJSONObject("serie")), points(d.optJSONObject("courbes")), bilan(d.optJSONObject("bilan")),
            bilan(avantO)?.copy(partielle = vrai(avantO, "partielle"), joursDisponibles = entier(avantO, "jours_disponibles") ?: bilan(avantO)?.joursDisponibles),
            granularite, groupes, horsCharge,
        )
    }

    // ------------------------------------------------------------ séances

    data class SeanceItem(
        val id: String,
        val date: LocalDate?,
        val debut: LocalDateTime?,
        val minutes: Int?,
        val sport: String,
        val nom: String,
        val distanceM: Int?,
        val allure: Int?,
        val fcMoyenne: Int?,
        val fcMax: Int?,
        val trimp: Int?,
        val avecFc: Boolean,
    )

    data class Borne(val nom: String, val min: Int?, val max: Int?)

    data class Analyse(val texte: String, val modele: String?, val genere: LocalDateTime?)

    data class SeanceComplete(
        val item: SeanceItem,
        val fin: LocalDateTime?,
        val kcal: Int?,
        val fcMin: Int?,
        val dansLaCharge: Boolean,
        val zones: List<Int?>,
        val fcMaxReference: Int?,
        val bornes: List<Borne>?,
        val courbe: List<Pair<Double, Int>>,
        val analyse: Analyse?,
    )

    data class ListeSeances(
        val entete: Entete,
        val jours: Int,
        val sport: String,
        val du: LocalDate?,
        val au: LocalDate?,
        val total: Triple<Int?, Int?, Int?>,
        val parSport: Map<String, Sport>,
        val distances: Map<String, Int?>,
        val tronque: Boolean,
        val seances: List<SeanceItem>,
    )

    fun seanceItem(o: JSONObject?): SeanceItem? {
        if (o == null) return null
        val id = texte(o, "seance_id") ?: o.opt("seance_id")?.toString() ?: return null
        val sport = texte(o, "sport") ?: texte(o, "type") ?: ""
        val nom = SanteDetail.libelleSeance(texte(o, "nom") ?: texte(o, "titre"), sport)
        return SeanceItem(
            id, date(o, "date"), moment(texte(o, "debut_local") ?: texte(o, "debut")), entier(o, "minutes", 1440), sport, nom,
            entier(o, "distance_m"), entier(o, "allure_s_par_km", 3600), entier(o, "fc_moyenne", 250), entier(o, "fc_max", 250),
            entier(o, "trimp", 5000), if (o.has("avec_fc")) vrai(o, "avec_fc") else entier(o, "fc_moyenne", 250) != null,
        )
    }

    fun seances(r: JSONObject?): ListeSeances? {
        val d = donnees(r) ?: return null
        val t = d.optJSONObject("total")
        val ps = d.optJSONObject("par_sport")
        val distances = LinkedHashMap<String, Int?>()
        if (ps != null) for (k in ps.keys()) distances[k] = entier(ps.optJSONObject(k), "distance_m")
        val l = (d.optJSONArray("seances") ?: JSONArray()).let { a -> (0 until a.length()).mapNotNull { seanceItem(a.optJSONObject(it)) } }
        return ListeSeances(
            entete(d), entier(d, "jours", 400) ?: 0, texte(d, "sport") ?: "tous", date(d, "du"), date(d, "au"),
            Triple(entier(t, "seances"), entier(t, "minutes"), entier(t, "distance_m")), parSport(ps), distances, vrai(d, "tronque"), l,
        )
    }

    fun seance(r: JSONObject?): SeanceComplete? {
        val d = donnees(r) ?: return null
        val o = d.optJSONObject("seance") ?: d
        val item = seanceItem(o) ?: return null
        val z = o.optJSONObject("zones_minutes")
        val zb = o.optJSONObject("zones_bornes")
        val bornes = zb?.let { b -> (1..5).map { i -> val x = b.optJSONObject("z$i"); Borne(texte(x, "nom") ?: "Zone $i", entier(x, "min_bpm", 250), entier(x, "max_bpm", 250)) } }
        val courbe = o.optJSONArray("fc_courbe")?.let { c ->
            (0 until c.length()).mapNotNull { k ->
                val p = c.optJSONArray(k) ?: return@mapNotNull null
                if (p.length() < 2 || p.isNull(0) || p.isNull(1)) return@mapNotNull null
                val m = p.optDouble(0)
                val b = p.optDouble(1)
                if (m.isNaN() || b.isNaN() || b < 20 || b > 250) null else m to b.roundToInt()
            }
        } ?: emptyList()
        val an = o.optJSONObject("analyse")?.let { a -> texte(a, "texte")?.let { Analyse(it, texte(a, "modele"), moment(texte(a, "genere"))) } }
        return SeanceComplete(
            item, moment(texte(o, "fin_local")), entier(o, "kcal", 20_000), entier(o, "fc_min", 250),
            if (o.has("dans_la_charge")) vrai(o, "dans_la_charge") else true,
            if (z == null) emptyList() else (1..5).map { entier(z, "z$it", 1440) }, entier(o, "fc_max_reference", 250), bornes, courbe, an,
        )
    }

    // ------------------------------------------------------------ records

    data class Record(
        val cle: String,
        val valeur: Double,
        val unite: String,
        val date: LocalDate?,
        val du: LocalDate?,
        val au: LocalDate?,
        val lundi: LocalDate?,
        val seanceId: String?,
        val sport: String?,
        val battuLe: LocalDate?,
        /** Distance de la séance du record d'allure (serveur 0.20.2). */
        val distanceM: Int? = null,
    )

    data class Records(val entete: Entete, val depuis: LocalDate?, val seuilPas: Int?, val seuilNuit: Int?, val records: Map<String, Record>)

    val CLES_RECORDS = listOf(
        "serie_pas", "journee_la_plus_active", "meilleure_semaine_pas", "seance_la_plus_longue", "course_la_plus_longue",
        "semaine_la_plus_sportive", "seance_la_plus_chargee", "zone5_la_plus_longue", "meilleure_allure_5km",
        "nuit_la_plus_longue", "serie_nuits", "sommeil_profond_le_plus_long", "fc_la_plus_basse", "fc_la_plus_haute",
    )

    fun records(r: JSONObject?): Records? {
        val d = donnees(r) ?: return null
        val rec = d.optJSONObject("records")
        val m = LinkedHashMap<String, Record>()
        if (rec != null) for (k in CLES_RECORDS) {
            val o = rec.optJSONObject(k) ?: continue
            if (o.isNull("valeur")) continue
            val v = o.optDouble("valeur")
            if (v.isNaN() || v < 0) continue
            m[k] = Record(
                k, v, texte(o, "unite") ?: "", date(o, "date"), date(o, "du"), date(o, "au"), date(o, "lundi"),
                texte(o, "seance_id") ?: o.opt("seance_id")?.takeIf { !o.isNull("seance_id") }?.toString(), texte(o, "sport"), date(o, "battu_le"),
                entier(o, "distance_m"),
            )
        }
        val s = d.optJSONObject("seuils")
        return Records(entete(d), date(d, "depuis"), entier(s, "pas"), entier(s, "nuit_minutes", 1440), m)
    }

    // ------------------------------------------------------------ jour passé

    data class Nuit(val debut: LocalDateTime?, val auLit: Int?, val sommeil: Int?, val profond: Int?, val stades: List<Pair<String, Int>>, val seq: List<Triple<Int, Int, String>>)

    data class Jour(
        val entete: Entete,
        val date: LocalDate,
        val enCours: Boolean,
        val renseigne: Boolean,
        val sommeil: Int?,
        val auLit: Int?,
        val profond: Int?,
        val pas: Int?,
        val distanceM: Int?,
        val fcMoyenne: Int?,
        val fcMin: Int?,
        val fcMax: Int?,
        val spo2Min: Int?,
        val sommeilEstime: Boolean,
        val nuit: Nuit?,
        val seances: List<SeanceItem>,
    )

    fun jour(r: JSONObject?): Jour? {
        val d = donnees(r) ?: return null
        val date = date(d, "date") ?: return null
        val codes = d.optJSONObject("codes_stades")
        val n = d.optJSONObject("nuit")?.let { o ->
            val seq = o.optJSONArray("seq")?.let { a ->
                (0 until a.length()).mapNotNull { i ->
                    val p = a.optJSONArray(i) ?: return@mapNotNull null
                    if (p.length() < 3 || p.isNull(0) || p.isNull(1)) return@mapNotNull null
                    val code = p.opt(2)?.toString() ?: return@mapNotNull null
                    // « eveille_au_lit » du serveur dessiné comme l'éveil, comme dans les stades (SanteDetail.stades).
                    val nom = DictionnaireLocal.normaliser(codes?.optString(code)?.ifEmpty { null } ?: code).let { if (it == "eveille au lit") "eveille" else it }
                    Triple(p.optInt(0), p.optInt(1), nom)
                }
            } ?: emptyList()
            Nuit(moment(texte(o, "debut_local")), entier(o, "au_lit_minutes", 1440), entier(o, "sommeil_minutes", 1440), entier(o, "profond_minutes", 1440), SanteDetail.stades(o.optJSONObject("stades")), seq)
        }
        val l = (d.optJSONArray("seances") ?: JSONArray()).let { a -> (0 until a.length()).mapNotNull { seanceItem(a.optJSONObject(it)) } }
        return Jour(
            entete(d), date, vrai(d, "en_cours"), if (d.has("renseigne")) vrai(d, "renseigne") else true,
            entier(d, "sommeil_minutes", 1440), entier(d, "au_lit_minutes", 1440), entier(d, "profond_minutes", 1440),
            entier(d, "pas", 500_000), entier(d, "distance_m"), entier(d, "fc_moyenne", 250), entier(d, "fc_min", 250),
            entier(d, "fc_max", 250), entier(d, "spo2_min", 100), vrai(d, "sommeil_estime"), n, l,
        )
    }

    // ------------------------------------------------------------ textes communs

    private val FR = Locale.FRANCE

    fun majuscule(s: String) = s.replaceFirstChar { it.titlecase(FR) }

    fun jourSemaine(d: LocalDate): String = d.dayOfWeek.getDisplayName(TextStyle.FULL, FR)
    fun mois(d: LocalDate): String = d.month.getDisplayName(TextStyle.FULL, FR)

    /** « 1er » ou le numéro du jour. */
    fun numero(d: LocalDate): String = if (d.dayOfMonth == 1) "1er" else d.dayOfMonth.toString()

    /** « 22 octobre », avec l'année dès qu'elle n'est pas [annee]. */
    fun jourMois(d: LocalDate, annee: Int): String = numero(d) + " " + mois(d) + if (d.year != annee) " ${d.year}" else ""

    /**
     * « Jeudi 22 octobre, données de 9 h 40 » : la ligne de contexte des quatre onglets, à l'heure du calcul
     * des données (`genere_le`), à défaut de leur lecture (`lu_a`, résumé `sante` d'Aujourd'hui).
     */
    fun contexte(e: Entete, aujourdhui: LocalDate): String {
        val j = e.aujourdhui ?: aujourdhui
        val base = majuscule(jourSemaine(j)) + " " + jourMois(j, aujourdhui.year)
        val l = e.genereLe ?: e.luA ?: return base
        val h = "${l.hour} h " + l.minute.toString().padStart(2, '0')
        return base + ", données de " + h + if (e.perime) ", pas encore à jour" else ""
    }

    /** « Samedi 16 août 2025 » : la date de la vue d'un jour passé (année écrite si elle n'est pas l'année en cours). */
    fun dateLongue(d: LocalDate, aujourdhui: LocalDate): String = majuscule(jourSemaine(d)) + " " + jourMois(d, aujourdhui.year)

    /** « du 23 septembre au 22 octobre ». */
    fun plage(du: LocalDate, au: LocalDate, aujourdhui: LocalDate): String {
        val debut = when {
            du.year == au.year && du.month == au.month -> numero(du)
            du.year == au.year -> numero(du) + " " + mois(du)
            else -> numero(du) + " " + mois(du) + " " + du.year
        }
        return "du $debut au ${jourMois(au, aujourdhui.year)}"
    }

    /** « 23 sept. », « 7 oct. », « 22 oct. » : étiquettes des graphes. */
    fun court(d: LocalDate): String {
        val m = when (d.monthValue) {
            1 -> "janv."; 2 -> "févr."; 3 -> "mars"; 4 -> "avr."; 5 -> "mai"; 6 -> "juin"
            7 -> "juil."; 8 -> "août"; 9 -> "sept."; 10 -> "oct."; 11 -> "nov."; else -> "déc."
        }
        return numero(d) + " " + m
    }

    /** « Mar. 20 », « Dim. 18 » : dates abrégées de la liste des séances. */
    fun abrege(d: LocalDate): String {
        val j = when (d.dayOfWeek.value) {
            1 -> "Lun."; 2 -> "Mar."; 3 -> "Mer."; 4 -> "Jeu."; 5 -> "Ven."; 6 -> "Sam."; else -> "Dim."
        }
        return "$j ${d.dayOfMonth}"
    }

    /** « ve 16 » : étiquettes des graphes de sept jours. */
    fun initialeNumero(d: LocalDate): String = jourSemaine(d).take(2) + " " + d.dayOfMonth

    /** « Ven. 16 octobre, 11 420 pas » : lecture d'une barre au doigt. */
    fun lecture(d: LocalDate, valeur: String, aujourdhui: LocalDate): String = abrege(d).substringBefore(" ") + " " + jourMois(d, aujourdhui.year) + ", " + valeur

    fun duree(m: Int): String = Sante.duree(m)
    fun milliers(n: Int): String = Sante.milliers(n)
    fun km(m: Int): String = String.format(FR, "%.1f km", m / 1000.0)

    /** « 5:02 min/km ». */
    fun allure(s: Int): String = "${s / 60}:" + (s % 60).toString().padStart(2, '0') + " min/km"

    /** « 7 mois seulement », « 3 semaines seulement » : période d'avant partielle. */
    fun partielle(jours: Int): String = when {
        jours >= 60 -> "${(jours / 30.4).roundToInt()} mois seulement"
        jours >= 14 -> "${jours / 7} semaines seulement"
        else -> "$jours jours seulement"
    }

    /** Libellé d'une période : « Les 30 jours d'avant », « Les 3 mois d'avant », « L'année d'avant ». */
    fun avant(jours: Int): String = when (jours) {
        7 -> "Les 7 jours d'avant"
        30 -> "Les 30 jours d'avant"
        90 -> "Les 3 mois d'avant"
        365 -> "L'année d'avant"
        else -> "Les $jours jours d'avant"
    }

    // ------------------------------------------------------------ sport de 7 jours (Aujourd'hui, vue Jour)

    /**
     * Sport de 7 jours : [avecCharge] séances comptées dans la charge (avec fréquence cardiaque, hors ski et
     * snowboard). Sans elles, pas de ligne de charge (jamais « 0 de charge »).
     */
    data class Semaine(
        val du: LocalDate, val au: LocalDate, val seances: Int, val minutes: Int, val charge: Int, val sansFc: Int,
        val avantSemaines: Int, val avantMoyenne: Int?, val avecCharge: Int = 0,
    )

    /** Sports hors de la charge d'entraînement, comme `hors_charge` du serveur 0.20. */
    val HORS_CHARGE = setOf("ski", "snowboard")

    /** Semaines d'avant comparées dans le bloc Sport (maquettes `Sante` et `SanteJour`). */
    const val SEMAINES_AVANT = 4

    /** Période la plus courte du serveur (30, 90 ou 365 jours, finie aujourd'hui) qui contient [du], ou null au-delà d'un an. */
    fun periodeCouvrant(du: LocalDate, aujourdhui: LocalDate): Int? {
        val ecart = java.time.temporal.ChronoUnit.DAYS.between(du, aujourdhui)
        return listOf(30, 90, 365).firstOrNull { ecart < it }
    }

    /** Période la plus courte du serveur (7, 30, 90 ou 365 jours) qui tient [jours] jours, ou null au-delà d'un an. */
    fun periodeTenant(jours: Long): Int? = listOf(7, 30, 90, 365).firstOrNull { jours <= it }

    /**
     * Bloc Sport : les 7 jours glissants finis le jour [fin] compris, et la charge moyenne par semaine des
     * [semainesAvant] semaines glissantes d'avant, tout calculé sur une liste `sante_seances` (seule source qui
     * donne chaque séance avec sa date et sa charge) qui doit remonter jusque-là. Une séance sans fréquence
     * cardiaque compte dans les séances et les minutes, pas dans la charge, et le ski ou le snowboard pas dans
     * la charge non plus (comme le bilan du serveur).
     *
     * Liste tronquée (100 séances au plus, les plus récentes) : null si sa plus vieille séance n'est pas d'avant
     * le premier des 7 jours, car il peut en manquer dans ces 7 jours (revue de code 0.22.0). Les semaines
     * d'avant ne sont comptées que si la liste remonte jusqu'à elles.
     */
    fun semaine(l: ListeSeances, fin: LocalDate, semainesAvant: Int = SEMAINES_AVANT): Semaine? {
        val du = fin.minusDays(6)
        fun jourDe(s: SeanceItem) = s.date ?: s.debut?.toLocalDate()
        val plusVieille = l.seances.mapNotNull { jourDe(it) }.minOrNull()
        if (l.tronque && (plusVieille == null || !plusVieille.isBefore(du))) return null
        if (!l.tronque && l.du != null && l.du.isAfter(du)) return null
        if (l.au != null && l.au.isBefore(fin)) return null
        fun entre(a: LocalDate, b: LocalDate) = l.seances.filter { s -> jourDe(s)?.let { !it.isBefore(a) && !it.isAfter(b) } == true }
        fun chargees(x: List<SeanceItem>) = x.filter { it.sport !in HORS_CHARGE && it.trimp != null }
        val sept = entre(du, fin)
        val avantDu = du.minusDays(7L * semainesAvant)
        val avant = entre(avantDu, du.minusDays(1))
        val couvert = if (l.tronque) plusVieille != null && plusVieille.isBefore(avantDu) else l.du == null || !l.du.isAfter(avantDu)
        return Semaine(
            du, fin, sept.size, sept.sumOf { it.minutes ?: 0 }, chargees(sept).sumOf { it.trimp ?: 0 }, sept.count { !it.avecFc },
            semainesAvant, if (couvert && semainesAvant > 0) (chargees(avant).sumOf { it.trimp ?: 0 } / semainesAvant.toDouble()).roundToInt() else null,
            chargees(sept).size,
        )
    }

    // ------------------------------------------------------------ zones et nuit

    /**
     * Bornes d'une zone en texte : « moins de 114 » pour la zone 1 (elle part de 0 bpm, tout ce qui est sous le
     * seuil de la zone 2), « 114 à 132 », « 171 et plus » pour la zone 5, vide sans bornes.
     */
    fun texteBorne(b: Borne): String = when {
        b.min != null && b.min <= 0 && b.max != null -> "moins de ${b.max + 1}"
        b.min != null && b.max != null -> "${b.min} à ${b.max}"
        b.min != null -> "${b.min} et plus"
        else -> ""
    }

    /** Heure de Paris [minutes] après [debut] (heure de Paris), changement d'heure compris (25 octobre 2026). */
    fun apres(debut: LocalDateTime, minutes: Long): LocalDateTime =
        debut.atZone(PARIS).plusMinutes(minutes).withZoneSameInstant(PARIS).toLocalDateTime()

    fun heure(t: LocalDateTime): String = "${t.hour} h " + t.minute.toString().padStart(2, '0')

    /**
     * Heures écrites sous l'hypnogramme d'une nuit de [minutes] commencée à [debut] : chaque heure paire pleine
     * à 50 min au moins du début et de la fin, avec son décalage en minutes depuis le début. Calculé sur les
     * instants : la nuit du changement d'heure a une heure de plus, et 2 h n'est écrit qu'une fois.
     */
    fun heuresNuit(debut: LocalDateTime, minutes: Long): List<Pair<Long, String>> {
        val z0 = debut.atZone(PARIS)
        val l = ArrayList<Pair<Long, String>>()
        var h = z0.plusHours(1).withMinute(0).withSecond(0).withNano(0)
        var dernier = -1
        while (true) {
            val m = java.time.Duration.between(z0, h).toMinutes()
            if (m > minutes - 50) break
            if (m >= 50 && h.hour % 2 == 0 && h.hour != dernier) {
                l.add(m to "${h.hour} h")
                dernier = h.hour
            }
            h = h.plusHours(1)
        }
        return l
    }

    /**
     * Ce qui est présent dans une réponse d'historique, sans aucune valeur (essai par adb, journal) : le type,
     * puis les champs attendus du protocole 0.20 qui manquent, ou l'erreur. Jamais une valeur, une date ni un
     * nombre de séances.
     */
    fun presence(type: String, r: JSONObject?): String {
        if (r == null) return "$type : aucune réponse"
        if (r.has("erreur")) return "$type : erreur du serveur"
        if (r.optString("etat") != type) return "$type : réponse d'un autre type"
        val d = donnees(r) ?: return "$type : réponse sans données"
        val manque = ArrayList<String>()
        fun champs(o: JSONObject?, prefixe: String, cles: List<String>) {
            if (o == null) {
                manque.add(prefixe.trimEnd('.'))
                return
            }
            for (k in cles) if (!o.has(k)) manque.add(prefixe + k)
        }
        champs(d, "", listOf("aujourdhui", "premier_jour", "genere_le", "lu_a", "perime"))
        val jour = listOf("dates", "en_cours", "sommeil_minutes", "au_lit_minutes", "profond_minutes", "pas", "fc_moyenne", "fc_min", "sommeil_estime")
        val bilanCles = listOf("du", "au", "jours", "couverture", "jours_disponibles", "jours_sommeil_estime", "sommeil_minutes", "au_lit_minutes", "profond_minutes", "pas", "distance_m", "fc_repos", "fc_moyenne", "spo2_min", "sport")
        val sportCles = listOf("minutes", "seances", "trimp", "sans_fc", "minutes_par_semaine", "seances_par_semaine", "trimp_par_semaine", "par_sport")
        val ligne = listOf("seance_id", "date", "debut_local", "minutes", "sport", "nom", "distance_m", "allure_s_par_km", "fc_moyenne", "fc_max", "trimp", "avec_fc")
        var listes = true
        fun memeLongueur(o: JSONObject?) {
            if (o == null) return
            val n = o.optJSONArray("dates")?.length() ?: return
            for (k in o.keys()) o.optJSONArray(k)?.let { if (it.length() != n) listes = false }
        }
        when (type) {
            "sante_periode" -> {
                champs(d, "", listOf("jours", "du", "au", "granularite", "serie", "courbes", "bilan", "avant", "sport", "hors_charge"))
                champs(d.optJSONObject("serie"), "serie.", jour + "seance")
                val c = d.optJSONObject("courbes")
                if (d.optInt("jours") >= 90) champs(c, "courbes.", listOf("dates", "en_cours", "jours_renseignes", "jours_sommeil_estime", "jours_seance"))
                else champs(c, "courbes.", jour)
                memeLongueur(d.optJSONObject("serie"))
                memeLongueur(c)
                champs(d.optJSONObject("bilan"), "bilan.", bilanCles)
                champs(d.optJSONObject("bilan")?.optJSONObject("sport"), "bilan.sport.", sportCles)
                d.optJSONObject("avant")?.let { a -> champs(a, "avant.", bilanCles + "partielle") }
                champs(d.optJSONObject("sport"), "sport.", listOf("granularite", "groupes"))
            }
            "sante_seances" -> {
                champs(d, "", listOf("jours", "sport", "du", "au", "total", "par_sport", "tronque", "seances"))
                champs(d.optJSONObject("total"), "total.", listOf("seances", "minutes", "distance_m"))
                d.optJSONArray("seances")?.optJSONObject(0)?.let { champs(it, "seances[0].", ligne) }
            }
            "sante_seance" -> champs(d.optJSONObject("seance") ?: d, "", ligne + listOf(
                "fin_local", "titre", "type", "type_code", "kcal", "fc_min", "fc_echantillons", "vitesse_moyenne_kmh", "vitesse_max_kmh",
                "dans_la_charge", "zones_minutes", "fc_max_reference", "zones_bornes", "fc_courbe", "analyse",
            ))
            "sante_records" -> {
                champs(d, "", listOf("depuis", "seuils", "records"))
                champs(d.optJSONObject("seuils"), "seuils.", listOf("pas", "nuit_minutes"))
                champs(d.optJSONObject("records"), "records.", CLES_RECORDS)
            }
            "sante_jour" -> {
                champs(d, "", listOf("date", "en_cours", "renseigne", "sommeil_minutes", "au_lit_minutes", "profond_minutes", "pas", "distance_m", "kcal", "fc_moyenne", "fc_min", "fc_max", "spo2_min", "seance", "sommeil_estime", "nuit", "codes_stades", "seances"))
                d.optJSONObject("nuit")?.let { n -> champs(n, "nuit.", listOf("debut_local", "au_lit_minutes", "sommeil_minutes", "profond_minutes", "stades", "seq")) }
            }
        }
        return "$type : réponse lue, " + (if (manque.isEmpty()) "aucun champ attendu ne manque" else "manquent " + manque.joinToString(", ")) +
            if (listes) "" else ", listes parallèles de longueurs différentes"
    }

    /**
     * Forme d'une réponse à une fenêtre passée (`au`, serveur 0.20.2), sans valeur ni date : finie le jour
     * demandé ou non, jour en cours, liste tronquée, période d'avant.
     */
    fun presenceAu(r: JSONObject?, au: String): String {
        val d = donnees(r) ?: return "sans réponse lisible"
        val enCours = listOf("serie", "courbes").any { k ->
            d.optJSONObject(k)?.optJSONArray("en_cours")?.let { a -> (0 until a.length()).any { a.optBoolean(it) } } == true
        }
        return listOfNotNull(
            if (texte(d, "au") == au) "finie le jour demandé" else "pas finie le jour demandé",
            if (d.has("serie")) (if (enCours) "un jour en cours" else "aucun jour en cours") else null,
            if (d.has("tronque")) (if (vrai(d, "tronque")) "tronquée" else "non tronquée") else null,
            if (d.has("avant")) (if (d.isNull("avant")) "sans période d'avant" else "avec période d'avant") else null,
        ).joinToString(", ")
    }
}
