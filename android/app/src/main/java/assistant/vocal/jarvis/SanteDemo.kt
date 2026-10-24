package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject
import java.time.DayOfWeek
import java.time.LocalDate
import java.util.Random
import kotlin.math.roundToInt
import kotlin.math.sin

/**
 * Valeurs fictives du panneau Santé pour les démonstrations de l'appli de débogage (0.22.0), une réponse par
 * message du serveur 0.20 (`sante`, `sante_periode`, `sante_seances`, `sante_seance`, `sante_records`,
 * `sante_jour`), toutes tirées d'un même calendrier inventé pour rester cohérentes entre elles. Aucune vraie
 * donnée de santé : chaque jour est tiré au hasard d'après sa seule date.
 */
internal object SanteDemo {

    private class JourFictif(val date: LocalDate, val sommeil: Int?, val auLit: Int?, val profond: Int?, val pas: Int?, val fcMoy: Int?, val fcMin: Int?, val fcMax: Int?, val seances: List<SeanceFictive>)

    private class SeanceFictive(val id: String, val date: LocalDate, val heure: Int, val minute: Int, val sport: String, val nom: String, val minutes: Int, val trimp: Int, val fcMoy: Int, val fcMax: Int, val distanceM: Int?)

    private fun jour(d: LocalDate, aujourdhui: LocalDate): JourFictif {
        val r = Random(d.toEpochDay() * 7919L)
        // Un jour sans montre de temps en temps, pour montrer les trous.
        val absent = d.toEpochDay() % 23L == 5L && d != aujourdhui
        val sommeil = if (absent) null else 400 + r.nextInt(95)
        val seances = ArrayList<SeanceFictive>()
        if (d.isBefore(aujourdhui) || d == aujourdhui) {
            // Sports de démonstration neutres (0.30.1) : natation, vélo, et une course une semaine sur deux pour les
            // records de course (course la plus longue, meilleure allure sur 5 km).
            when (d.dayOfWeek) {
                DayOfWeek.MONDAY, DayOfWeek.THURSDAY -> {
                    val m = 45 + r.nextInt(20)
                    val h = if (d.dayOfWeek == DayOfWeek.MONDAY) 12 to 20 else 19 to 5
                    seances.add(SeanceFictive("demo-${d}-n", d, h.first, h.second, "natation", "Natation", m, 90 + r.nextInt(40), 132 + r.nextInt(12), 165 + r.nextInt(10), null))
                }
                DayOfWeek.WEDNESDAY, DayOfWeek.SUNDAY -> {
                    val m = 60 + r.nextInt(40)
                    val h = if (d.dayOfWeek == DayOfWeek.WEDNESDAY) 18 to 15 else 10 to 0
                    seances.add(SeanceFictive("demo-${d}-v", d, h.first, h.second, "velo", "Vélo", m, 100 + r.nextInt(50), 135 + r.nextInt(12), 170 + r.nextInt(10), null))
                }
                DayOfWeek.SATURDAY -> if (d.toEpochDay() / 7 % 2 == 0L) {
                    val m = 35 + r.nextInt(15)
                    seances.add(SeanceFictive("demo-${d}-c", d, 9, 30, "course", "Course à pied", m, 85 + r.nextInt(20), 148 + r.nextInt(6), 170 + r.nextInt(8), 5500 + r.nextInt(2500)))
                }
                else -> {}
            }
        }
        val pas = when {
            absent -> null
            d == aujourdhui -> 4210
            d == jourActif(aujourdhui) -> 24310
            else -> 6000 + r.nextInt(7000) + if (seances.isNotEmpty()) 2500 else 0
        }
        return JourFictif(
            d, sommeil, sommeil?.let { it + 15 + r.nextInt(25) }, sommeil?.let { 70 + r.nextInt(35) }, pas,
            if (absent) null else 68 + r.nextInt(8), if (absent) null else 46 + r.nextInt(5), if (absent) null else 120 + r.nextInt(20), seances,
        )
    }

    private fun entete(o: JSONObject, aujourdhui: LocalDate): JSONObject =
        o.put("aujourdhui", aujourdhui.toString()).put("premier_jour", "2025-03-12").put("genere_le", aujourdhui.toString() + "T09:41:00")
            .put("lu_a", aujourdhui.toString() + "T09:40:00").put("perime", false)

    private fun reponse(type: String, d: JSONObject) = JSONObject().put("etat", type).put("id", 0).put("donnees", d)

    /** Analyse de démonstration, assez longue pour essayer la colonne défilante de Séances. */
    private const val ANALYSE = "Analyse de démonstration, rédigée pour essayer l'affichage. Séance régulière, avec un échauffement " +
        "progressif sur les dix premières minutes puis des montées franches à chaque effort. Le cœur redescend " +
        "vite entre les efforts, signe d'une bonne récupération. Les dernières minutes restent soutenues. Rien à corriger " +
        "pour la prochaine séance, sinon garder une hydratation régulière.\n\nSecond paragraphe de " +
        "démonstration : la charge de la séance est dans la moyenne des quatre dernières semaines, la semaine reste équilibrée " +
        "avec les autres séances. Ce texte ne vient d'aucune vraie mesure."

    /** Réponse fictive à la demande [corps], au jour [aujourdhui]. */
    fun reponse(corps: JSONObject, aujourdhui: LocalDate = SanteHisto.aujourdhui()): JSONObject {
        // Comme le serveur 0.20.2 : 7, 30, 90 ou 365 jours, fenêtre finie le jour `au` s'il est donné.
        val type = corps.optString("type")
        if ((type == "sante_periode" || type == "sante_seances") && corps.optInt("jours", 30) !in listOf(7, 30, 90, 365))
            return JSONObject().put("etat", type).put("id", 0).put("erreur", "période non prise en charge (7, 30, 90 ou 365 jours)")
        val au = if (corps.isNull("au")) null else SanteHisto.date(corps.optString("au"))
        if (au != null && au.isAfter(aujourdhui)) return JSONObject().put("etat", type).put("id", 0).put("erreur", "date hors de l'historique")
        return reponseDe(type, corps, au, aujourdhui)
    }

    private fun reponseDe(type: String, corps: JSONObject, au: LocalDate?, aujourdhui: LocalDate): JSONObject = when (type) {
        "sante_periode" -> periode(corps.optInt("jours", 30), au ?: aujourdhui, aujourdhui, au != null)
        "sante_seances" -> seances(corps.optInt("jours", 30), corps.optString("sport", "tous"), au ?: aujourdhui, aujourdhui)
        "sante_seance" -> seance(corps.optString("seance_id"), aujourdhui)
        "sante_records" -> records(aujourdhui)
        "sante_jour" -> jourComplet(LocalDate.parse(corps.optString("date")), aujourdhui)
        else -> resume(aujourdhui)
    }

    private fun seanceJson(s: SeanceFictive): JSONObject = JSONObject().put("seance_id", s.id).put("date", s.date.toString())
        .put("debut_local", s.date.toString() + "T" + s.heure.toString().padStart(2, '0') + ":" + s.minute.toString().padStart(2, '0') + ":00")
        .put("minutes", s.minutes).put("sport", s.sport).put("nom", s.nom).put("distance_m", s.distanceM ?: JSONObject.NULL)
        .put("allure_s_par_km", allureDe(s) ?: JSONObject.NULL)
        .put("fc_moyenne", s.fcMoy).put("fc_max", s.fcMax).put("trimp", s.trimp).put("avec_fc", true)

    private fun resume(aujourdhui: LocalDate): JSONObject {
        val jours = JSONArray()
        for (k in 6 downTo 0) {
            val j = jour(aujourdhui.minusDays(k.toLong()), aujourdhui)
            jours.put(JSONObject().put("date", j.date.toString()).put("renseigne", j.pas != null).put("pas", j.pas ?: JSONObject.NULL).put("sommeil_minutes", if (k == 0) 412 else j.sommeil ?: JSONObject.NULL))
        }
        val derniere = (0..10).asSequence().map { jour(aujourdhui.minusDays(it.toLong()), aujourdhui) }.flatMap { it.seances.asSequence() }.first()
        val d = entete(JSONObject(), aujourdhui).put("date", aujourdhui.toString())
            .put("nuit", JSONObject().put("date", aujourdhui.toString()).put("cette_nuit", true).put("minutes", 432)
                .put("stades", JSONObject().put("profond", 98).put("paradoxal", 84).put("leger", 230).put("eveille", 20)))
            .put("aujourdhui", JSONObject().put("date", aujourdhui.toString()).put("renseigne", true).put("pas", 4210).put("distance_m", 3100)
                .put("fc_repos", 48).put("fc_min", 46).put("fc_moyenne", 71).put("fc_max", 132).put("spo2_moyenne", 95).put("spo2_min", 89))
            .put("jours", jours)
            .put("seances", JSONArray().put(seanceJson(derniere).put("titre", derniere.nom).put("kcal", 820).put("fc_courbe", courbe(derniere))))
        return JSONObject().put("etat", "sante").put("id", 0).put("donnees", d)
    }

    private fun courbe(s: SeanceFictive): JSONArray {
        val a = JSONArray()
        val n = 60
        for (k in 0 until n) {
            val t = k / (n - 1.0)
            val montee = (95 + (s.fcMoy - 95) * minOf(1.0, t * 8)).toInt()
            val effort = if (s.sport == "course") (6 * sin(t * 12)).toInt() else (22 * maxOf(0.0, sin(t * Math.PI * 16))).toInt() - 6
            val fin = if (t > 0.94) ((t - 0.94) * 900).toInt() else 0
            a.put(JSONArray().put(s.minutes * t).put((montee + effort - fin).coerceIn(90, s.fcMax)))
        }
        a.put(JSONArray().put(s.minutes * 0.35).put(s.fcMax))
        return a
    }

    private fun periode(n: Int, au: LocalDate, aujourdhui: LocalDate, fenetre: Boolean = false): JSONObject {
        val jours = (n - 1 downTo 0).map { jour(au.minusDays(it.toLong()), aujourdhui) }
        fun serie(l: List<JourFictif>): JSONObject {
            val o = JSONObject()
            fun col(nom: String, f: (JourFictif) -> Any?) = o.put(nom, JSONArray(l.map { f(it) ?: JSONObject.NULL }))
            col("dates") { it.date.toString() }
            col("en_cours") { !fenetre && it.date == aujourdhui }
            col("sommeil_minutes") { it.sommeil }
            col("au_lit_minutes") { it.auLit }
            col("profond_minutes") { it.profond }
            col("pas") { it.pas }
            col("fc_moyenne") { it.fcMoy }
            col("fc_min") { it.fcMin }
            col("seance") { it.seances.isNotEmpty() }
            col("sommeil_estime") { false }
            return o
        }
        val parSemaine = n >= 90
        val courbes = if (!parSemaine) serie(jours) else {
            val semaines = jours.groupBy { it.date.minusDays((it.date.dayOfWeek.value - 1).toLong()) }.toSortedMap()
            val o = JSONObject()
            fun moy(l: List<JourFictif>, f: (JourFictif) -> Int?): Any = l.mapNotNull(f).takeIf { it.isNotEmpty() }?.average()?.roundToInt() ?: JSONObject.NULL
            o.put("dates", JSONArray(semaines.keys.map { it.toString() }))
            o.put("en_cours", JSONArray(semaines.values.map { l -> !fenetre && l.any { it.date == aujourdhui } }))
            o.put("jours_renseignes", JSONArray(semaines.values.map { l -> l.count { it.pas != null } }))
            o.put("sommeil_minutes", JSONArray(semaines.values.map { l -> moy(l) { it.sommeil } }))
            o.put("profond_minutes", JSONArray(semaines.values.map { l -> moy(l) { it.profond } }))
            o.put("pas", JSONArray(semaines.values.map { l -> moy(l.filter { it.date != aujourdhui }) { it.pas } }))
            o.put("fc_moyenne", JSONArray(semaines.values.map { l -> moy(l) { it.fcMoy } }))
            o.put("fc_min", JSONArray(semaines.values.map { l -> moy(l) { it.fcMin } }))
            o.put("jours_seance", JSONArray(semaines.values.map { l -> l.count { it.seances.isNotEmpty() } }))
            o.put("au_lit_minutes", JSONArray(semaines.values.map { l -> moy(l) { it.auLit } }))
            o.put("jours_sommeil_estime", JSONArray(semaines.values.map { 0 }))
            o
        }
        fun bilan(l: List<JourFictif>, du: LocalDate, a: LocalDate): JSONObject {
            val fini = l.filter { it.date != aujourdhui }
            fun moy(f: (JourFictif) -> Int?): Any = fini.mapNotNull(f).takeIf { it.isNotEmpty() }?.average()?.roundToInt() ?: JSONObject.NULL
            val sc = l.flatMap { it.seances }
            val semaines = l.size / 7.0
            val par = JSONObject()
            for ((k, g) in sc.groupBy { it.sport }) par.put(k, JSONObject().put("nom", g.first().nom).put("minutes", g.sumOf { it.minutes }).put("seances", g.size).put("trimp", g.sumOf { it.trimp }).put("sans_fc", 0))
            return JSONObject().put("du", du.toString()).put("au", a.toString()).put("jours", fini.size).put("couverture", fini.count { it.pas != null })
                .put("jours_disponibles", l.size).put("partielle", false).put("jours_sommeil_estime", 0)
                .put("sommeil_minutes", moy { it.sommeil }).put("au_lit_minutes", moy { it.auLit }).put("profond_minutes", moy { it.profond })
                .put("pas", moy { it.pas }).put("distance_m", (moy { it.pas } as? Int)?.let { (it * 0.74).roundToInt() } ?: JSONObject.NULL)
                .put("fc_repos", moy { it.fcMin }).put("fc_moyenne", moy { it.fcMoy }).put("spo2_min", 90)
                .put("sport", JSONObject().put("minutes", sc.sumOf { it.minutes }).put("seances", sc.size).put("trimp", sc.sumOf { it.trimp }).put("sans_fc", 0)
                    .put("minutes_par_semaine", (sc.sumOf { it.minutes } / semaines).roundToInt()).put("seances_par_semaine", ((sc.size / semaines) * 10).roundToInt() / 10.0)
                    .put("trimp_par_semaine", (sc.sumOf { it.trimp } / semaines).roundToInt()).put("par_sport", par))
        }
        val du = jours.first().date
        val avantJours = (n downTo 1).map { jour(du.minusDays(it.toLong()), aujourdhui) }
        // Sport comme le serveur 0.20 : par jour à 7 jours, par semaine sinon, et les mois à part à 1 an.
        fun groupes(cle: (LocalDate) -> LocalDate): JSONArray {
            val a = JSONArray()
            for ((debut, l) in jours.groupBy { cle(it.date) }.toSortedMap()) {
                val sc = l.flatMap { it.seances }
                val par = JSONObject()
                for ((k, g) in sc.groupBy { it.sport }) par.put(k, JSONObject().put("nom", g.first().nom).put("minutes", g.sumOf { it.minutes }).put("seances", g.size).put("trimp", g.sumOf { it.trimp }).put("sans_fc", 0))
                a.put(JSONObject().put("debut", debut.toString()).put("jours", l.size).put("en_cours", !fenetre && l.any { it.date == aujourdhui })
                    .put("minutes", sc.sumOf { it.minutes }).put("seances", sc.size).put("trimp", sc.sumOf { it.trimp }).put("sans_fc", 0).put("par_sport", par))
            }
            return a
        }
        val parSemaineSport: (LocalDate) -> LocalDate = { d -> d.minusDays((d.dayOfWeek.value - 1).toLong()) }
        val sport = JSONObject().put("granularite", if (n <= 7) "jour" else "semaine")
            .put("groupes", groupes(if (n <= 7) ({ d -> d }) else parSemaineSport))
            .put("par_mois", if (n >= 365) groupes { d -> d.withDayOfMonth(1) } else JSONObject.NULL)
        val d = entete(JSONObject(), aujourdhui).put("jours", n).put("du", du.toString()).put("au", au.toString()).put("granularite", if (parSemaine) "semaine" else "jour")
            .put("serie", serie(jours)).put("courbes", courbes).put("bilan", bilan(jours, du, au))
            .put("avant", if (n >= 365) bilan(avantJours.takeLast(213), du.minusDays(213), du.minusDays(1)).put("partielle", true).put("jours_disponibles", 213) else bilan(avantJours, du.minusDays(n.toLong()), du.minusDays(1)).put("partielle", false))
            .put("sport", sport).put("hors_charge", JSONArray().put("ski").put("snowboard"))
        return reponse("sante_periode", d)
    }

    private fun seancesDe(n: Int, aujourdhui: LocalDate, fin: LocalDate = aujourdhui): List<SeanceFictive> =
        (0 until n).flatMap { jour(fin.minusDays(it.toLong()), aujourdhui).seances }

    private fun seances(n: Int, sport: String, fin: LocalDate, aujourdhui: LocalDate): JSONObject {
        val l = seancesDe(n, aujourdhui, fin).filter { sport == "tous" || it.sport == sport }
        // Totaux par sport comme le serveur 0.20.2 : charge (null pour le ski), séances sans cœur.
        val par = JSONObject()
        for ((k, g) in l.groupBy { it.sport }) par.put(k, JSONObject().put("nom", g.first().nom).put("minutes", g.sumOf { it.minutes }).put("seances", g.size)
            .put("trimp", if (k in SanteHisto.HORS_CHARGE) JSONObject.NULL else g.sumOf { it.trimp })
            .put("distance_m", g.mapNotNull { it.distanceM }.sum()).put("sans_fc", 0))
        val d = entete(JSONObject(), aujourdhui).put("jours", n).put("sport", sport).put("du", fin.minusDays((n - 1).toLong()).toString()).put("au", fin.toString())
            .put("total", JSONObject().put("seances", l.size).put("minutes", l.sumOf { it.minutes }).put("distance_m", l.mapNotNull { it.distanceM }.sum())
                .put("trimp", l.filter { it.sport !in SanteHisto.HORS_CHARGE }.sumOf { it.trimp }).put("sans_fc", 0))
            .put("par_sport", par).put("tronque", l.size > 100).put("seances", JSONArray(l.take(100).map { seanceJson(it) }))
        return reponse("sante_seances", d)
    }

    private fun seance(id: String, aujourdhui: LocalDate): JSONObject {
        val date = Regex("""\d{4}-\d{2}-\d{2}""").find(id)?.value?.let { LocalDate.parse(it) } ?: aujourdhui
        val s = jour(date, aujourdhui).seances.firstOrNull { it.id == id } ?: seancesDe(10, aujourdhui).first()
        // Bornes comme le serveur pour une FC max de 190 : la zone 1 part de 0 bpm, la zone 5 sans maximum.
        val bornes = JSONObject()
        val b = listOf(0 to 113, 114 to 132, 133 to 151, 152 to 170, 171 to null)
        val noms = listOf("récupération", "endurance", "tempo", "seuil", "anaérobie")
        for (i in 0 until 5) bornes.put("z${i + 1}", JSONObject().put("nom", noms[i]).put("min_bpm", b[i].first).put("max_bpm", b[i].second ?: JSONObject.NULL))
        val fin = s.date.atTime(s.heure, s.minute).plusMinutes(s.minutes.toLong())
        val o = seanceJson(s).put("fin_local", fin.toString() + ":00").put("titre", s.nom).put("type", s.sport).put("type_code", JSONObject.NULL)
            .put("kcal", 820).put("fc_min", 92).put("fc_echantillons", 60)
            .put("vitesse_moyenne_kmh", s.distanceM?.let { (it / 1000.0) / (s.minutes / 60.0) } ?: JSONObject.NULL).put("vitesse_max_kmh", JSONObject.NULL)
            .put("dans_la_charge", true).put("zones_minutes", zones(s))
            .put("fc_max_reference", 190).put("zones_bornes", bornes).put("fc_courbe", courbe(s))
            .put("analyse", JSONObject().put("texte", ANALYSE).put("modele", "démonstration").put("genere", s.date.toString() + "T22:00:00"))
        return reponse("sante_seance", entete(o, aujourdhui))
    }

    /**
     * Jour fictif de la journée la plus active : le dimanche (jour de vélo) d'il y a deux mois environ. La
     * démonstration de la vue Jour l'ouvre comme depuis Records, à la manière de la maquette `SanteJour`.
     */
    fun jourActif(aujourdhui: LocalDate): LocalDate = aujourdhui.minusDays(60).let { it.minusDays((it.dayOfWeek.value % 7).toLong()) }

    private fun lundi(d: LocalDate): LocalDate = d.minusDays((d.dayOfWeek.value - 1).toLong())

    /** Séance fictive de [sport] le [d] ou juste avant, pour que chaque record de séance s'ouvre sur une vraie séance du calendrier. */
    private fun seanceVers(d: LocalDate, sport: String, aujourdhui: LocalDate): SeanceFictive? =
        (0..14).asSequence().map { jour(d.minusDays(it.toLong()), aujourdhui) }.flatMap { it.seances.asSequence() }.firstOrNull { it.sport == sport }

    /** Minutes par zone d'une séance fictive, d'après sa seule durée. */
    private fun zones(s: SeanceFictive): JSONObject {
        val z = listOf(0.08, 0.42, 0.24, 0.17).map { (s.minutes * it).roundToInt() }
        return JSONObject().put("z1", z[0]).put("z2", z[1]).put("z3", z[2]).put("z4", z[3]).put("z5", (s.minutes - z.sum()).coerceAtLeast(0))
    }

    private fun allureDe(s: SeanceFictive): Int? = s.distanceM?.let { (s.minutes * 60.0 / (it / 1000.0)).roundToInt() }

    private fun records(aujourdhui: LocalDate): JSONObject {
        fun rec(v: Double, unite: String, date: LocalDate? = null, du: LocalDate? = null, au: LocalDate? = null, lundi: LocalDate? = null, seance: SeanceFictive? = null, battu: LocalDate? = null) =
            JSONObject().put("valeur", v).put("unite", unite).put("date", (seance?.date ?: date)?.toString() ?: JSONObject.NULL)
                .put("du", du?.toString() ?: JSONObject.NULL).put("au", au?.toString() ?: JSONObject.NULL).put("lundi", lundi?.toString() ?: JSONObject.NULL)
                .put("seance_id", seance?.id ?: JSONObject.NULL).put("sport", seance?.sport ?: JSONObject.NULL).put("battu_le", battu?.toString() ?: JSONObject.NULL)
        // Unités du serveur 0.20 : min, pas, jours, nuits, km, s/km, trimp, bpm. Dates proches (ouvertes dans
        // Tendances) et anciennes (au-delà d'un an, ouvertes sur leur premier jour).
        val recent = seancesDe(7, aujourdhui).firstOrNull { it.sport == "natation" }
        val longue = seanceVers(aujourdhui.minusDays(53), "velo", aujourdhui)
        val course = seanceVers(aujourdhui.minusDays(45), "course", aujourdhui)
        val zone5 = seanceVers(LocalDate.of(2025, 6, 14), "natation", aujourdhui)
        val allure = seanceVers(LocalDate.of(2025, 6, 29), "course", aujourdhui)
        val r = JSONObject()
            .put("serie_pas", rec(12.0, "jours", du = aujourdhui.minusDays(40), au = aujourdhui.minusDays(29)))
            .put("journee_la_plus_active", rec(24310.0, "pas", date = jourActif(aujourdhui)))
            .put("meilleure_semaine_pas", rec(102400.0, "pas", lundi = lundi(aujourdhui.minusDays(70))))
            .put("seance_la_plus_longue", rec(longue?.minutes?.toDouble() ?: 0.0, "min", seance = longue))
            .put("course_la_plus_longue", rec((course?.distanceM ?: 0) / 1000.0, "km", seance = course))
            .put("semaine_la_plus_sportive", rec(400.0, "min", lundi = lundi(aujourdhui.minusDays(56))))
            .put("seance_la_plus_chargee", rec(recent?.trimp?.toDouble() ?: 0.0, "trimp", seance = recent, battu = recent?.date))
            .put("zone5_la_plus_longue", rec(zone5?.let { zones(it).getInt("z5").toDouble() } ?: 0.0, "min", seance = zone5))
            .put("meilleure_allure_5km", rec(allure?.let { allureDe(it) }?.toDouble() ?: 0.0, "s/km", seance = allure))
            .put("nuit_la_plus_longue", rec(602.0, "min", date = LocalDate.of(2026, 4, 12)))
            .put("serie_nuits", rec(9.0, "nuits", du = LocalDate.of(2025, 6, 2), au = LocalDate.of(2025, 6, 10)))
            .put("sommeil_profond_le_plus_long", rec(134.0, "min", date = LocalDate.of(2025, 7, 6)))
            .put("fc_la_plus_basse", rec(41.0, "bpm", date = LocalDate.of(2025, 6, 3)))
            .put("fc_la_plus_haute", rec(zone5?.fcMax?.toDouble() ?: 0.0, "bpm", seance = zone5))
        // Distance de la course du record d'allure (serveur 0.20.2).
        r.getJSONObject("meilleure_allure_5km").put("distance_m", allure?.distanceM ?: JSONObject.NULL)
        val d = entete(JSONObject(), aujourdhui).put("depuis", "2025-03-12").put("seuils", JSONObject().put("pas", 10000).put("nuit_minutes", 420)).put("records", r)
        return reponse("sante_records", d)
    }

    private fun jourComplet(date: LocalDate, aujourdhui: LocalDate): JSONObject {
        val j = jour(date, aujourdhui)
        val seq = JSONArray()
        // Codes du serveur 0.20 (STADES de sante_hist.py).
        val codes = JSONObject().put("0", "inconnu").put("1", "eveille").put("2", "endormi").put("3", "hors_du_lit").put("4", "leger")
            .put("5", "profond").put("6", "paradoxal").put("7", "eveille_au_lit")
        val r = Random(date.toEpochDay())
        var t = 0
        val auLit = j.auLit ?: 0
        val motif = listOf(4, 5, 4, 6, 4, 5, 4, 6, 7, 4, 6, 4, 5, 4, 6, 1)
        var k = 0
        while (t < auLit) {
            val d = 20 + r.nextInt(40)
            seq.put(JSONArray().put(t).put(minOf(d, auLit - t)).put(motif[k % motif.size]))
            t += d
            k++
        }
        val d = entete(JSONObject(), aujourdhui).put("date", date.toString()).put("en_cours", date == aujourdhui).put("renseigne", j.pas != null)
            .put("sommeil_minutes", j.sommeil ?: JSONObject.NULL).put("au_lit_minutes", j.auLit ?: JSONObject.NULL).put("profond_minutes", j.profond ?: JSONObject.NULL)
            .put("pas", j.pas ?: JSONObject.NULL).put("distance_m", j.pas?.let { (it * 0.74).roundToInt() } ?: JSONObject.NULL).put("kcal", JSONObject.NULL)
            .put("fc_moyenne", j.fcMoy ?: JSONObject.NULL).put("fc_min", j.fcMin ?: JSONObject.NULL).put("fc_max", j.fcMax ?: JSONObject.NULL).put("spo2_min", 90)
            .put("seance", j.seances.isNotEmpty()).put("sommeil_estime", false)
            .put("nuit", if (j.sommeil == null) JSONObject.NULL else JSONObject().put("debut_local", date.minusDays(1).toString() + "T23:40:00").put("au_lit_minutes", j.auLit).put("sommeil_minutes", j.sommeil)
                .put("profond_minutes", j.profond).put("stades", JSONObject().put("profond", j.profond).put("paradoxal", 120).put("leger", (j.sommeil - (j.profond ?: 0) - 120).coerceAtLeast(0)).put("eveille", (j.auLit ?: 0) - j.sommeil))
                .put("seq", seq))
            .put("codes_stades", codes).put("seances", JSONArray(j.seances.map { seanceJson(it) }))
        return reponse("sante_jour", d)
    }
}
