package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.TextStyle
import java.util.Locale

/**
 * Panneau Santé de la tablette (0.21.0, maquette `Sante` relue) : lecture défensive de toute la réponse du
 * serveur (`donnees`) et textes du panneau, en logique pure testée sur la machine (SanteDetailTest).
 *
 * Le modèle est découpé comme le panneau, en sections indépendantes (sommeil, pas, cœur, sept jours, séances,
 * dernière séance) que d'autres onglets (Tendances, Séances, Records, à venir d'après le tableau de bord
 * HealthStats du propriétaire) pourront reprendre. Une valeur absente ou nulle n'est jamais affichée, aucun jugement
 * (pas de moyenne comparée, pas de note).
 *
 * Données personnelles : ce modèle ne vit que le temps où le panneau est ouvert, n'est écrit nulle part et
 * ne passe jamais par Etat ni par le journal.
 */
internal object SanteDetail {

    data class Nuit(
        val date: LocalDate?,
        val cetteNuit: Boolean,
        val minutes: Int?,
        /** Minutes par stade : profond, paradoxal, léger, éveillé (dans cet ordre quand ils existent). */
        val stades: List<Pair<String, Int>>,
    ) {
        val eveille: Int? get() = stades.firstOrNull { it.first == "eveille" }?.second
    }

    data class Jour(
        val date: LocalDate?,
        val renseigne: Boolean,
        val pas: Int?,
        val distanceM: Int?,
        val kcalTotales: Int?,
        val fcRepos: Int?,
        val fcMin: Int?,
        val fcMax: Int?,
        val fcMoyenne: Int?,
        val spo2Moyenne: Int?,
        val spo2Min: Int?,
        val sommeilMinutes: Int? = null,
    )

    data class Seance(
        val date: LocalDate?,
        val debut: LocalDateTime?,
        val titre: String,
        val minutes: Int?,
        val kcal: Int?,
        val distanceM: Int?,
        val fcMoyenne: Int?,
        val fcMax: Int?,
        /** Minutes par zone de 1 à 5, vide si inconnues. */
        val zones: List<Int?>,
        /** Courbe du cœur : paires (minute, battements par minute), vide si inconnue. */
        val courbe: List<Pair<Double, Int>>,
    )

    data class Detail(
        val date: LocalDate?,
        val nuit: Nuit?,
        val aujourdhui: Jour?,
        /** Sept jours du plus ancien à aujourd'hui. */
        val jours: List<Jour>,
        /** Séances, les plus récentes d'abord. */
        val seances: List<Seance>,
    )

    private fun date(s: String?): LocalDate? = try {
        if (s == null) null else LocalDate.parse(s.take(10))
    } catch (_: Exception) {
        null
    }

    private fun moment(s: String?, zone: ZoneId): LocalDateTime? {
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

    private fun positif(v: Int?, max: Int): Int? = v?.takeIf { it in 0..max }

    private fun jour(o: JSONObject?): Jour? {
        if (o == null) return null
        return Jour(
            date(Sante.texte(o, "date")), o.optBoolean("renseigne", true),
            positif(Sante.entier(o, "pas"), 500_000), positif(Sante.entier(o, "distance_m"), 1_000_000),
            positif(Sante.entier(o, "kcal_totales"), 50_000),
            positif(Sante.entier(o, "fc_repos"), 250), positif(Sante.entier(o, "fc_min"), 250),
            positif(Sante.entier(o, "fc_max"), 250), positif(Sante.entier(o, "fc_moyenne"), 250),
            positif(Sante.entier(o, "spo2_moyenne"), 100), positif(Sante.entier(o, "spo2_min"), 100),
            positif(Sante.entier(o, "sommeil_minutes"), 24 * 60),
        )
    }

    /** Ordre des stades dans la barre : le sommeil d'abord, l'éveil ensuite, le reste en gris à la fin. */
    private val ORDRE_STADES = listOf("profond", "paradoxal", "leger", "endormi", "eveille", "hors du lit", "inconnu")

    /**
     * Stades lus dans `nuit.stades` (0.21.1) : clés normalisées, « éveillé au lit » compté avec l'éveil, toute
     * clé inconnue rangée avec « inconnu ».
     */
    fun stades(o: JSONObject?): List<Pair<String, Int>> {
        if (o == null) return emptyList()
        val somme = LinkedHashMap<String, Int>()
        for (k in o.keys()) {
            val m = positif(Sante.entier(o, k), 24 * 60) ?: continue
            if (m <= 0) continue
            val n = DictionnaireLocal.normaliser(k)
            val cle = when (n) {
                "eveille au lit", "eveille" -> "eveille"
                in ORDRE_STADES -> n
                else -> "inconnu"
            }
            somme[cle] = (somme[cle] ?: 0) + m
        }
        return somme.entries.map { it.key to it.value }.sortedBy { ORDRE_STADES.indexOf(it.first).let { i -> if (i < 0) 99 else i } }
    }

    /** Stade de sommeil proprement dit (teinte santé et libellé sous la barre). */
    fun dort(cle: String): Boolean = cle in setOf("profond", "paradoxal", "leger", "endormi")

    /**
     * Titres des séances (0.21.1) : sans titre, la clé de sante-api (« course »,
     * « velo_appartement », « type_12 ») devient un libellé français, « Séance » par défaut.
     */
    private val TITRES = mapOf(
        "course" to "Course à pied", "course a pied" to "Course à pied", "trail" to "Trail",
        "marche" to "Marche", "randonnee" to "Randonnée",
        "velo" to "Vélo", "velo appartement" to "Vélo d'appartement", "vtt" to "VTT",
        "natation" to "Natation", "musculation" to "Musculation", "yoga" to "Yoga", "etirements" to "Étirements",
        "ski" to "Ski", "ski alpin" to "Ski alpin", "ski de fond" to "Ski de fond", "plongee" to "Plongée",
        "voile" to "Voile", "kayak" to "Kayak", "aviron" to "Aviron", "rameur" to "Rameur", "elliptique" to "Elliptique",
        "football" to "Football", "basket" to "Basket", "tennis" to "Tennis", "badminton" to "Badminton",
        "danse" to "Danse", "escalade" to "Escalade", "patinage" to "Patinage", "sport" to "Sport",
    )

    /** Titres propres à la maison : section sante.sports.titres de la configuration, clé normalisée. */
    private fun titresMaison() = ConfigMaison.section("sante").optJSONObject("sports")?.optJSONObject("titres") ?: org.json.JSONObject()

    /** Libellé d'une séance : son titre s'il est lisible, sinon celui de son type, sinon « Séance ». */
    fun libelleSeance(titre: String?, type: String?): String {
        for (brut in listOf(titre, type)) {
            val t = brut?.trim().orEmpty()
            if (t.isEmpty()) continue
            val n = DictionnaireLocal.normaliser(t)
            TITRES[n]?.let { return it }
            titresMaison().optString(n).takeIf { it.isNotBlank() }?.let { return it }
            // Un vrai titre (avec majuscule, espace ou accent, sans soulignés) se montre tel quel.
            if ('_' !in t && !Regex("^type ?\\d+$").matches(n) && t != t.lowercase()) return t
        }
        return "Séance"
    }

    /** Toute la réponse du serveur, ou null pour une erreur ou une réponse illisible. */
    fun lire(reponse: JSONObject?, zone: ZoneId = ZoneId.systemDefault()): Detail? {
        if (reponse == null || reponse.has("erreur")) return null
        val d = if (reponse.has("donnees")) reponse.optJSONObject("donnees") ?: return null else reponse
        val n = d.optJSONObject("nuit")
        val nuit = n?.let {
            Nuit(date(Sante.texte(it, "date")), it.optBoolean("cette_nuit", false), positif(Sante.entier(it, "minutes"), 24 * 60), stades(it.optJSONObject("stades")))
        }
        val jours = (d.optJSONArray("jours") ?: JSONArray()).let { a -> (0 until a.length()).mapNotNull { jour(a.optJSONObject(it)) } }
        val seances = (d.optJSONArray("seances") ?: JSONArray()).let { a ->
            (0 until a.length()).mapNotNull { i ->
                val o = a.optJSONObject(i) ?: return@mapNotNull null
                val z = o.optJSONObject("zones_minutes")
                val courbe = o.optJSONArray("fc_courbe")?.let { c ->
                    (0 until c.length()).mapNotNull { k ->
                        val p = c.optJSONArray(k) ?: return@mapNotNull null
                        if (p.length() < 2 || p.isNull(0) || p.isNull(1)) return@mapNotNull null
                        val m = p.optDouble(0)
                        val b = p.optDouble(1)
                        if (m.isNaN() || b.isNaN() || b < 20 || b > 250) null else m to b.toInt()
                    }
                } ?: emptyList()
                Seance(
                    date(Sante.texte(o, "date")), moment(Sante.texte(o, "debut"), zone),
                    libelleSeance(Sante.texte(o, "titre"), Sante.texte(o, "type")),
                    positif(Sante.entier(o, "minutes"), 24 * 60), positif(Sante.entier(o, "kcal"), 20_000),
                    positif(Sante.entier(o, "distance_m"), 1_000_000),
                    positif(Sante.entier(o, "fc_moyenne"), 250), positif(Sante.entier(o, "fc_max"), 250),
                    if (z == null) emptyList() else (1..5).map { positif(Sante.entier(z, "z$it"), 24 * 60) },
                    courbe,
                )
            }
        }
        return Detail(date(Sante.texte(d, "date")), nuit, jour(d.optJSONObject("aujourdhui")), jours, seances)
    }

    /**
     * Ce qui est présent dans une réponse, sans aucune valeur (essai par adb, journal) : « réponse lue,
     * nuit (minutes, cette nuit), aujourd'hui (pas), 7 jours, 3 séances », ou l'erreur.
     */
    fun presence(r: JSONObject?): String {
        if (r == null) return "aucune réponse"
        if (r.has("erreur")) return "erreur du serveur"
        val d = lire(r) ?: return "réponse illisible"
        val n = d.nuit
        val a = d.aujourdhui
        return listOfNotNull(
            "réponse lue",
            n?.let { "nuit (" + listOfNotNull("minutes".takeIf { _ -> it.minutes != null }, "cette nuit".takeIf { _ -> it.cetteNuit }, "stades".takeIf { _ -> it.stades.isNotEmpty() }).joinToString(", ") + ")" },
            a?.let { "aujourd'hui (" + listOfNotNull("pas".takeIf { _ -> it.pas != null }, "distance".takeIf { _ -> it.distanceM != null }, "kcal".takeIf { _ -> it.kcalTotales != null }, "cœur".takeIf { _ -> it.fcMin != null }, "oxygène".takeIf { _ -> it.spo2Moyenne != null }).joinToString(", ") + ")" },
            "${d.jours.size} jours",
            "${d.seances.size} séances",
        ).joinToString(", ")
    }

    // ------------------------------------------------------------ textes

    /** « 7 h 12 », « 45 min », comme sur l'accueil. */
    fun duree(m: Int): String = Sante.duree(m)

    /** Titre du sommeil : « Sommeil cette nuit », sinon « Dernière nuit, mercredi 21 octobre ». */
    fun titreNuit(n: Nuit): String =
        if (n.cetteNuit) "Sommeil cette nuit"
        else "Dernière nuit" + (n.date?.let { ", " + dateLongue(it) } ?: "")

    fun dateLongue(d: LocalDate): String =
        d.dayOfWeek.getDisplayName(TextStyle.FULL, Locale.FRANCE) + " " + d.dayOfMonth + (if (d.dayOfMonth == 1) "er" else "") + " " +
            d.month.getDisplayName(TextStyle.FULL, Locale.FRANCE)

    /** Nom d'un stade de sommeil. */
    fun nomStade(cle: String): String = when (cle) {
        "profond" -> "profond"
        "paradoxal" -> "paradoxal"
        "leger" -> "léger"
        "endormi" -> "endormi"
        "eveille" -> "éveillé"
        "hors du lit" -> "hors du lit"
        else -> "inconnu"
    }

    /** « 3,1 km d'activités, 1 980 kcal dépensées » : distance des activités suivies et kcal totales. */
    fun lignePas(j: Jour): String = listOfNotNull(
        j.distanceM?.takeIf { it > 0 }?.let { km(it) + " d'activités" },
        j.kcalTotales?.let { Sante.milliers(it) + " kcal dépensées" },
    ).joinToString(", ")

    fun km(m: Int): String = String.format(Locale.FRANCE, "%.1f km", m / 1000.0)

    /** « 71 en moyenne, 132 au plus haut ». */
    fun ligneCoeur(j: Jour): String = listOfNotNull(j.fcMoyenne?.let { "$it en moyenne" }, j.fcMax?.let { "$it au plus haut" }).joinToString(", ")

    /** « Oxygène dans le sang, 95 % en moyenne, 89 % au plus bas ». */
    fun ligneOxygene(j: Jour): String {
        val p = listOfNotNull(j.spo2Moyenne?.let { "$it % en moyenne" }, j.spo2Min?.let { "$it % au plus bas" })
        return if (p.isEmpty()) "" else "Oxygène dans le sang, " + p.joinToString(", ")
    }

    /** Initiales des jours des graphes : « lu », « ma », « me », « je », « ve », « sa », « di ». */
    fun initiale(d: LocalDate): String = d.dayOfWeek.getDisplayName(TextStyle.FULL, Locale.FRANCE).take(2)

    /** Pas des jours terminés (sans aujourd'hui), sept au plus, du plus ancien au plus récent. */
    fun pasTermines(d: Detail, aujourdhui: LocalDate): List<Pair<LocalDate, Int?>> =
        d.jours.filter { it.date != null && it.date.isBefore(aujourdhui) }.takeLast(7).map { it.date!! to it.pas?.takeIf { _ -> it.renseigne } }

    /** Sommeil des sept nuits jusqu'à cette nuit (par jour du réveil). */
    fun nuits(d: Detail, aujourdhui: LocalDate): List<Pair<LocalDate, Int?>> =
        d.jours.filter { it.date != null && !it.date.isAfter(aujourdhui) }.takeLast(7).map { it.date!! to it.sommeilMinutes }

    /** « 10,4 » pour 10 412 pas (graphe en milliers). */
    fun milliersDePas(n: Int): String = String.format(Locale.FRANCE, "%.1f", n / 1000.0)

    /** Jour relatif d'une séance : « Aujourd'hui », « Hier », le nom du jour dans la semaine, sinon la date. */
    fun quand(d: LocalDate?, aujourdhui: LocalDate): String? {
        if (d == null) return null
        val ecart = aujourdhui.toEpochDay() - d.toEpochDay()
        return when {
            ecart == 0L -> "Aujourd'hui"
            ecart == 1L -> "Hier"
            ecart in 2..6 -> d.dayOfWeek.getDisplayName(TextStyle.FULL, Locale.FRANCE).replaceFirstChar { it.titlecase(Locale.FRANCE) }
            else -> d.dayOfMonth.toString() + " " + d.month.getDisplayName(TextStyle.FULL, Locale.FRANCE)
        }
    }

    /** « Hier, 1 h 15, 820 kcal », « Dimanche, 42 min, 6,8 km » : la distance si elle compte, sinon les kcal. */
    fun ligneSeance(s: Seance, aujourdhui: LocalDate): String = listOfNotNull(
        quand(s.date ?: s.debut?.toLocalDate(), aujourdhui),
        s.minutes?.let { duree(it) },
        s.distanceM?.takeIf { it >= 100 }?.let { km(it) } ?: s.kcal?.let { "${Sante.milliers(it)} kcal" },
    ).joinToString(", ")

    /** « Hier à 20 h 30, pendant 1 h 15 ». */
    fun quandSeance(s: Seance, aujourdhui: LocalDate): String {
        val q = quand(s.date ?: s.debut?.toLocalDate(), aujourdhui)
        val h = s.debut?.let { "à ${it.hour} h " + it.minute.toString().padStart(2, '0') }
        val debut = listOfNotNull(q, h).joinToString(" ")
        val pendant = s.minutes?.let { "pendant ${duree(it)}" }
        return listOf(debut, pendant).filter { !it.isNullOrBlank() }.joinToString(", ")
    }

    /** « 820 kcal, cœur à 148 en moyenne, 186 au plus haut ». */
    fun chiffresSeance(s: Seance): String = listOfNotNull(
        s.kcal?.let { "${Sante.milliers(it)} kcal" },
        s.fcMoyenne?.let { "cœur à $it en moyenne" },
        s.fcMax?.let { "$it au plus haut" },
    ).joinToString(", ")
}
