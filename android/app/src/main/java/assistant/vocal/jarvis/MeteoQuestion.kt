package assistant.vocal.jarvis

import java.time.Instant
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.TextStyle
import java.util.Locale
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.cos
import kotlin.math.roundToInt
import kotlin.math.sin

/**
 * Question de météo posée à la voix (0.23.0, maquettes `MeteoQuestion*` et `MeteoMerQuestion` relues le 22/10) :
 * comprise sans LLM, puis la réponse calculée sur les prévisions lues, écrite dans le panneau Météo et dite par
 * assistant. Logique pure, testée sur la machine (MeteoQuestionTest). Note : `docs/maquettes/reflexion-meteo-question-mer.md`.
 *
 * Rien n'est inventé : une valeur absente des prévisions n'est ni écrite ni dite. La phrase écrite est la phrase
 * dite, moins le rappel de la question que porte l'en-tête du bloc, et avec les unités abrégées.
 */
object MeteoQuestion {

    enum class Sujet { PLUIE, TEMPERATURE, VENT, GENERAL, MER }

    enum class Page { TERRE, MER, VENT }

    /**
     * Plage demandée : le jour (0 aujourd'hui), l'heure de début et l'heure de fin, exclue (24 et plus : le
     * lendemain), son nom (« cet après-midi »). [maintenant] : la question porte sur l'heure en cours. [jourEntier] :
     * aucune partie du jour n'a été dite (« demain »).
     */
    data class Plage(val jour: Int, val debut: Int, val fin: Int, val nom: String, val maintenant: Boolean = false, val jourEntier: Boolean = false)

    /**
     * Question comprise. [lieu] : nom d'un autre lieu météo dit dans la phrase (« Lille »), [point] : point en mer.
     * [mesure] (0.29.0) : une question sur le vent en mer maintenant (« quel vent à Exemple4 »), à laquelle répondent
     * d'abord les mesures réelles ([MeteoVent]).
     */
    data class Question(
        val sujet: Sujet, val plage: Plage, val lieu: String? = null, val point: String = MeteoMer.DEFAUT, val mesure: Boolean = false,
        /** Le point en mer a été nommé (« à Exemple4 »), et non pris par défaut. */
        val pointDit: Boolean = false,
    )

    /**
     * Ce que montre le panneau et ce que dit assistant. [lignes] : la réponse écrite, la dernière en texte secondaire
     * quand il y en a plusieurs. Bande en instants (fin exclue), [choisi] : l'heure à choisir dans la frise.
     * [detail] : début en texte principal, reste en texte secondaire, la ligne sous la frise.
     */
    data class Reponse(
        val page: Page,
        val entete: String,
        val lignes: List<String>,
        val parle: String,
        val jour: LocalDate,
        val sujet: Sujet,
        val bandeDebut: Long? = null,
        val bandeFin: Long? = null,
        val choisi: Long? = null,
        val detail: Pair<String, String> = "" to "",
        val lieu: String? = null,
        val point: String = MeteoMer.DEFAUT,
        /** Station à choisir sur la page du vent mesuré (0.29.0), ou null. */
        val station: String? = null,
    )

    // ------------------------------------------------------------ compréhension

    private val ACTIONS = setOf(
        "allume", "allumer", "eteins", "eteindre", "mets", "mettre", "monte", "monter", "baisse", "baisser", "ouvre",
        "ouvrir", "ferme", "fermer", "lance", "lancer", "joue", "jouer", "rappelle", "rappeler", "rappel", "programme",
        "programmer", "regle", "regler", "active", "activer", "desactive", "coupe", "couper", "demarre", "arrete",
        "minuteur", "alarme", "reveil", "descends", "descendre", "augmente", "augmenter", "diminue", "diminuer",
        "chauffe", "chauffer", "ajoute", "ajouter", "envoie", "envoyer", "ecris", "ecrire", "previens", "prevenir",
        "dis", "dire", "note", "noter", "cuisson", "cuire",
    )
    /** Une pièce ou un appareil de la maison : la phrase est une commande ou une question sur la maison, pas la météo. */
    private val MAISON = setOf(
        "salon", "cuisine", "chambre", "salle", "bain", "volet", "volets", "store", "stores", "chauffage", "clim",
        "climatisation", "lumiere", "lumieres", "lampe", "lampes", "dedans", "interieur", "radiateur", "four", "frigo",
        "television", "tele", "enceinte", "enceintes", "musique", "liste", "courses", "message", "sms",
    )
    /** Mots permis après « à » ou « au » : tout autre mot est un lieu inconnu, laissé au LLM. */
    private val APRES_A = setOf(
        "midi", "minuit", "partir", "quelle", "quel", "l", "la", "le", "les", "peu", "plus", "moins", "nouveau", "peine",
        "large", "nord", "sud", "est", "ouest", "cause", "part", "cette", "ce", "maison",
        "demain", "venir", "sortir", "quai", "port", "mer",
    ) + MeteoMer.ALIAS.map { it.first } + MeteoMer.MOTS_LIEU
    private val MOTS_PLUIE = setOf(
        "pleuvoir", "pleut", "pleuvra", "pluie", "pluies", "pluvieux", "averse", "averses", "orage", "orages", "orageux",
        "parapluie", "neige", "neiger", "neigera", "grele",
    )
    private val MOTS_VENT = setOf("vent", "vents", "venteux", "rafale", "rafales", "souffle", "soufflera", "mistral")
    private val MOTS_TEMPERATURE = setOf("temperature", "temperatures", "degre", "degres")
    private val MOTS_RESSENTI = setOf("chaud", "froid", "frais", "fraiche", "doux")
    private val MOTS_CIEL = setOf("beau", "soleil", "ensoleille", "nuageux", "couvert", "gris", "brouillard")
    private val MOTS_MER = setOf("mer", "marine", "vagues", "vague", "houle", "naviguer", "navigation", "navigue", "voile", "regate", "regates")
    private val MOTS_FAIRE = setOf("fait", "fera", "faire", "ferait", "sera", "va")
    private val JOURS = listOf("lundi", "mardi", "mercredi", "jeudi", "vendredi", "samedi", "dimanche")
    private val NOMBRES = mapOf("une" to 1, "un" to 1, "deux" to 2, "trois" to 3, "quatre" to 4, "cinq" to 5, "six" to 6)

    /**
     * La question de météo de [entendu], ou null si ce n'en est pas une (la phrase continue alors vers le
     * dictionnaire et le LLM). [lieux] : noms des autres lieux météo connus (« Lille »).
     */
    fun comprendre(entendu: String, maintenant: ZonedDateTime, lieux: List<String> = emptyList()): Question? {
        val n = DictionnaireLocal.normaliser(DictionnaireLocal.epurer(entendu))
        val m = n.split(" ").filter { it.isNotEmpty() }
        if (m.isEmpty() || m.size > 18) return null
        if (m.any { it in ACTIONS } || m.any { it in MAISON } || m.first() == "a") return null
        if (Regex("""\bcombien de temps\b|\bde temps en temps\b|\ben meme temps\b|\btemps de trajet\b""").containsMatchIn(n)) return null
        val faire = m.any { it in MOTS_FAIRE }
        // Point en mer nommé : le premier mot de MeteoMer.ALIAS présent dans la phrase.
        val pointMer = MeteoMer.ALIAS.firstOrNull { (mot, _) -> mot in m }?.second
        val mer = MeteoMer.ACTIF && (pointMer != null || m.any { it in MOTS_MER } || "plan d eau" in n || "au large" in n)
        val sujet = when {
            mer -> Sujet.MER
            m.any { it in MOTS_PLUIE } -> Sujet.PLUIE
            m.any { it in MOTS_VENT } -> Sujet.VENT
            m.any { it in MOTS_TEMPERATURE } -> Sujet.TEMPERATURE
            "combien" in m && m.any { it in setOf("fait", "fera", "faire", "ferait") } -> Sujet.TEMPERATURE
            faire && m.any { it in MOTS_RESSENTI } -> Sujet.TEMPERATURE
            faire && m.any { it in MOTS_CIEL } -> Sujet.GENERAL
            Regex("""\bmeteo\b|\bquel temps\b|\btemps (qu il|prevu|fera|fait|va faire)\b""").containsMatchIn(n) -> Sujet.GENERAL
            else -> return null
        }
        val lieu = lieux.firstOrNull { l -> DictionnaireLocal.normaliser(l).let { it.isNotEmpty() && Regex("""\b${Regex.escape(it)}\b""").containsMatchIn(n) } }
        val connus = lieux.flatMap { DictionnaireLocal.normaliser(it).split(" ") }.toSet()
        if (Regex("""\b(?:a|au|aux) ([a-z]+)""").findAll(n).any { r -> r.groupValues[1].let { it !in APRES_A && it !in connus } }) return null
        val plage = if (sujet == Sujet.MER) plageMer(n, m, maintenant) else plage(n, m, maintenant)
        // Vent en mer sans jour ni partie du jour dits : la mesure d'abord (0.29.0).
        val futur = "demain" in m || JOURS.any { it in m } || "apres midi" in n || heureDite(n) != null ||
            m.any { it in setOf("aprem", "matin", "matinee", "midi", "soir", "soiree", "nuit", "fera", "sera", "va", "soufflera", "hier", "week", "weekend") } ||
            "plus tard" in n || Regex("""\bdans (\d{1,2}|une|un|deux|trois|quatre|cinq|six) (h|heure|heures)\b""").containsMatchIn(n)
        val mesure = sujet == Sujet.MER && m.any { it in MOTS_VENT } && !futur
        return Question(sujet, plage, if (sujet == Sujet.MER) null else lieu, pointMer ?: MeteoMer.DEFAUT, mesure, pointMer != null)
    }

    /** Jour dit dans la phrase : 0 aujourd'hui, 1 demain, 2 après-demain, ou le prochain jour de la semaine nommé. */
    private fun jour(n: String, m: List<String>, maintenant: ZonedDateTime): Pair<Int, String?> {
        if ("apres demain" in n) return 2 to "après-demain"
        if ("demain" in m) return 1 to "demain"
        val i = JOURS.indexOfFirst { it in m }
        if (i >= 0) {
            val d = ((i + 1) - maintenant.dayOfWeek.value + 7) % 7
            return d to if (d == 0) null else JOURS[i]
        }
        return 0 to null
    }

    /** Heure dite (« à 16 h », « vers 18 heures », « 16h »), avec le mot qui la précède, ou null. */
    private fun heureDite(n: String): Pair<String, Int>? {
        Regex("""\b(a|vers|pour|avant|apres|des|jusqu a)?\s*(\d{1,2})\s*(h|heure|heures)\b""").find(n)?.let { r ->
            val h = r.groupValues[2].toInt()
            if (h in 0..23) return r.groupValues[1] to h
        }
        Regex("""\b(a|vers|pour|avant|apres|des|jusqu a)?\s*(\d{1,2})h(?:\d{2})?\b""").find(n)?.let { r ->
            val h = r.groupValues[2].toInt()
            if (h in 0..23) return r.groupValues[1] to h
        }
        if (Regex("""\b(a|vers|pour) minuit\b""").containsMatchIn(n)) return "a" to 0
        return null
    }

    private fun plage(n: String, m: List<String>, maintenant: ZonedDateTime): Plage {
        val (j, nomJour) = jour(n, m, maintenant)
        val h0 = maintenant.hour
        fun nommer(partie: String, aujourdhui: String): String = when {
            nomJour == null -> aujourdhui
            else -> "$nomJour $partie".trim()
        }
        // « Dans deux heures » : une seule heure.
        Regex("""\bdans (\d{1,2}|une|un|deux|trois|quatre|cinq|six) (h|heure|heures)\b""").find(n)?.let { r ->
            val k = r.groupValues[1].toIntOrNull() ?: NOMBRES[r.groupValues[1]] ?: 1
            val h = h0 + k
            return Plage(0, h, h + 1, "dans $k heure" + if (k > 1) "s" else "")
        }
        heureDite(n)?.let { (mot, h0dit) ->
            // Une heure déjà passée aujourd'hui vise demain (« à 3 h » demandé à 15 h).
            val passe = j == 0 && h0dit < h0 && mot !in setOf("avant", "jusqu a")
            val j = if (passe) 1 else j
            val nomJour = if (passe) "demain" else nomJour
            fun nommer(partie: String, aujourdhui: String): String = if (nomJour == null) aujourdhui else "$nomJour $partie".trim()
            val h = h0dit
            return when (mot) {
                "vers" -> Plage(j, h - 1, h + 2, nommer("vers $h h", "vers $h h"))
                "avant", "jusqu a" -> Plage(j, if (j == 0) h0 else 6, h, nommer("avant $h h", "avant $h h"))
                "apres", "des" -> Plage(j, h, 24, nommer("après $h h", "après $h h"))
                else -> Plage(j, h, h + 1, nommer("à $h h", "à $h h"))
            }
        }
        val partie = when {
            "apres midi" in n || "aprem" in m -> Triple(12, 18, "après-midi")
            "matin" in m || "matinee" in m -> Triple(6, 12, "matin")
            "midi" in m -> Triple(12, 14, "midi")
            "soir" in m || "soiree" in m -> Triple(18, 23, "soir")
            "nuit" in m -> Triple(21, 30, "nuit")
            "journee" in m -> Triple(6, 22, "journée")
            else -> null
        }
        if (partie != null) {
            val (d, f, p) = partie
            val nom = when (p) {
                "après-midi" -> nommer("après-midi", "cet après-midi")
                "matin" -> nommer("matin", "ce matin")
                "midi" -> nommer("midi", "à midi")
                "soir" -> nommer("soir", "ce soir")
                "nuit" -> if (nomJour == null) "cette nuit" else "la nuit de $nomJour"
                else -> nommer("", "aujourd'hui")
            }
            // « Ce soir » demandé à 23 h 30 : cette nuit. « Cette nuit » demandée avant 6 h : la nuit en cours.
            if (j == 0 && f <= h0 && p == "soir") return Plage(0, h0, 30, "cette nuit")
            if (j == 0 && p == "nuit" && h0 < 6) return Plage(0, h0, 6, "cette nuit")
            return Plage(j, d, f, nom)
        }
        if (j > 0) return Plage(j, 6, 22, nomJour ?: "", jourEntier = true)
        // Sans plage : au présent, l'heure en cours (« il pleut ? », « quel temps fait-il »), sinon le reste du jour.
        val present = Regex("""\b(maintenant|actuellement|en ce moment|la tout de suite|dehors)\b""").containsMatchIn(n) ||
            (m.any { it in setOf("fait", "pleut", "souffle") } && m.none { it in setOf("fera", "va", "pleuvra", "sera", "aujourd", "journee") })
        if (present) return Plage(0, h0, h0 + 1, "en ce moment", maintenant = true)
        return if (h0 >= 21) Plage(0, h0, 30, "cette nuit") else Plage(0, h0, 22, "aujourd'hui", jourEntier = true)
    }

    /** Plage d'une question sur la mer : la journée de navigation (7 h à 20 h), ou la partie du jour dite. */
    private fun plageMer(n: String, m: List<String>, maintenant: ZonedDateTime): Plage {
        val (j0, nomJour) = jour(n, m, maintenant)
        val h0 = maintenant.hour
        val partie = when {
            "apres midi" in n || "aprem" in m -> Triple(12, 18, "après-midi")
            "matin" in m || "matinee" in m -> Triple(7, 12, "matin")
            "soir" in m || "soiree" in m -> Triple(17, 20, "soir")
            else -> null
        }
        if (partie == null) {
            // Journée de navigation : celle d'aujourd'hui jusqu'à 20 h, puis celle de demain.
            val j = if (j0 == 0 && h0 >= MeteoMer.FIN_JOURNEE) 1 else j0
            val nom = nomJour ?: if (j == 1) "demain" else "aujourd'hui"
            return Plage(j, MeteoMer.DEBUT_JOURNEE, MeteoMer.FIN_JOURNEE, nom, jourEntier = true)
        }
        val (d, f, p) = partie
        val nom = if (nomJour != null) "$nomJour $p" else when (p) {
            "après-midi" -> "cet après-midi"
            "matin" -> "ce matin"
            else -> "ce soir"
        }
        return Plage(j0, d, f, nom)
    }

    // ------------------------------------------------------------ réponse sur terre

    /** Instants de début et de fin (exclue) de la plage, le début ramené à l'heure en cours pour aujourd'hui. */
    fun bornes(p: Plage, maintenant: ZonedDateTime): Pair<Long, Long> {
        val jour = maintenant.toLocalDate().plusDays(p.jour.toLong())
        val heureEnCours = maintenant.withMinute(0).withSecond(0).withNano(0)
        fun a(h: Int): ZonedDateTime = jour.plusDays(Math.floorDiv(h, 24).toLong()).atTime(Math.floorMod(h, 24), 0).atZone(maintenant.zone)
        var debut = a(p.debut)
        if (debut.isBefore(heureEnCours)) debut = heureEnCours
        return debut.toInstant().toEpochMilli() to a(p.fin).toInstant().toEpochMilli()
    }

    /**
     * Réponse à une question sur terre, d'après la lecture [l] des prévisions (heures, jours, météo du moment).
     * [lieu] : nom du lieu dit (« Lille »), repris dans l'en-tête.
     */
    fun repondre(q: Question, l: Previsions.Lecture, maintenant: ZonedDateTime, lieu: String? = null): Reponse {
        val zone = maintenant.zone
        val p = q.plage
        val (debut, fin) = bornes(p, maintenant)
        val date = maintenant.toLocalDate().plusDays(p.jour.toLong())
        val unite = l.actuel?.uniteVent ?: "km/h"
        val heures = l.horaire.filter { it.instant in debut until fin }
        val entete = entete(q.sujet, p) + (lieu?.let { " à $it" } ?: "")
        val base = Reponse(Page.TERRE, entete, emptyList(), "", date, q.sujet, lieu = lieu)
        if (p.maintenant && l.actuel != null) return maintenantTerre(q, l, base, heures.firstOrNull(), unite)
        if (fin <= debut) {
            return base.copy(lignes = listOf("Déjà passé."), parle = "${majuscule(p.nom)}, c'est déjà passé.", detail = majuscule(p.nom) to "")
        }
        if (heures.isEmpty()) return parJour(q, l, base, date, maintenant)
        fun h(x: Previsions.Prevision) = Instant.ofEpochMilli(x.instant).atZone(zone).hour
        val nom = p.nom
        val Nom = majuscule(nom)
        val temps = heures.mapNotNull { it.temperature }
        val vents = heures.mapNotNull { it.vent }
        val rafales = heures.filter { it.rafales != null }
        val gMax = rafales.maxByOrNull { it.rafales!! }
        // Épisodes de pluie dans la plage, le dernier suivi jusqu'à sa fin même au-delà de la plage.
        val episodes = episodes(heures)
        val apres = l.horaire.filter { it.instant >= fin }
        var finPluie: Long? = null
        var mmTotal = 0.0
        var mmVu = false
        for (e in episodes) for (x in e) x.millimetres?.let { mmTotal += it; mmVu = true }
        if (episodes.isNotEmpty()) {
            val dernier = episodes.last().last()
            finPluie = if (dernier === heures.last()) {
                var k = 0
                while (k < apres.size && MeteoTexte.pluvieuse(apres[k])) {
                    apres[k].millimetres?.let { mmTotal += it; mmVu = true }
                    k++
                }
                apres.getOrNull(k)?.instant
            } else heures.getOrNull(heures.indexOf(dernier) + 1)?.instant
        }
        val probaMax = heures.mapNotNull { it.pluie }.maxOrNull()
        val unique = heures.size == 1
        val lignes = ArrayList<String>()
        var parle: String
        var choisi = heures.first().instant
        var bandeFin = fin
        when (q.sujet) {
            Sujet.PLUIE -> {
                if (episodes.isEmpty()) {
                    if (probaMax != null && probaMax >= 30) {
                        val x = heures.first { it.pluie == probaMax }
                        lignes.add("Peu probable.")
                        lignes.add("$probaMax % vers ${h(x)} h.")
                        parle = "Peu probable, $probaMax pour cent vers ${h(x)} heures."
                        choisi = x.instant
                    } else {
                        lignes.add("Non, sec $nom.")
                        probaMax?.takeIf { it > 0 }?.let { lignes.add("$it % de risque au plus.") }
                        parle = "Non, sec $nom" + (probaMax?.takeIf { it > 0 }?.let { ", $it pour cent de risque au plus." } ?: ".")
                    }
                } else {
                    val premier = episodes.first().first()
                    val toute = episodes.size == 1 && episodes[0].size == heures.size && !unique
                    val mm = if (mmVu && mmTotal >= 0.1) MeteoTexte.mm(mmTotal) else null
                    val fh = finPluie?.let { Instant.ofEpochMilli(it).atZone(zone).hour }
                    when {
                        unique -> {
                            lignes.add("Oui, $nom.")
                            mm?.let { lignes.add("$it mm.") }
                            parle = "Oui, ${heures(nom)}" + (mm?.let { ", $it ${unitePluie(mmTotal)}" } ?: "") + "."
                        }
                        toute -> {
                            lignes.add("Oui, tout $nom.")
                            mm?.let { lignes.add("$it mm en tout.") }
                            parle = "Oui, tout $nom" + (mm?.let { ", $it ${unitePluie(mmTotal)} en tout" } ?: "") + "."
                        }
                        episodes.size == 1 -> {
                            val debutTexte = if (premier.instant <= maintenant.toInstant().toEpochMilli()) "dès maintenant" else "à partir de ${h(premier)} h"
                            lignes.add("Oui, $debutTexte.")
                            val suite = listOfNotNull(fh?.let { "Jusqu'à $it h" }, mm?.let { "$it mm" })
                            if (suite.isNotEmpty()) lignes.add(suite.joinToString(", ") + ".")
                            parle = "Oui, " + heures(debutTexte) +
                                (fh?.let { ", jusqu'à $it heures" } ?: "") + (mm?.let { ", $it ${unitePluie(mmTotal)}" } ?: "") + "."
                        }
                        else -> {
                            val a = episodes[0]
                            val b = episodes[1]
                            val premiere = if (a.size == 1) "vers ${h(a.first())} h" else "de ${h(a.first())} h à ${(h(a.last()) + 1) % 24} h"
                            val seconde = if (b.size == 1) "vers ${h(b.first())} h" else "de ${h(b.first())} h à ${(h(b.last()) + 1) % 24} h"
                            lignes.add("Oui, $premiere, puis $seconde.")
                            mm?.let { lignes.add("$it mm en tout.") }
                            parle = "Oui, ${heures(premiere)}, puis ${heures(seconde)}" +
                                (mm?.let { ", $it ${unitePluie(mmTotal)} en tout" } ?: "") + "."
                        }
                    }
                    if (finPluie != null && finPluie > fin) bandeFin = finPluie
                    // L'heure la plus arrosée de la pluie annoncée, même au-delà de la plage.
                    choisi = l.horaire.filter { it.instant >= premier.instant && it.instant < (finPluie ?: bandeFin) && MeteoTexte.pluvieuse(it) }
                        .maxByOrNull { it.millimetres ?: 0.0 }?.instant ?: premier.instant
                }
            }
            Sujet.TEMPERATURE -> {
                val avecT = heures.filter { it.temperature != null }
                if (avecT.isEmpty()) {
                    lignes.add("Pas de température prévue.")
                    parle = "Je n'ai pas de température prévue $nom."
                } else {
                    val a = avecT.first()
                    val z = avecT.last()
                    val haut = avecT.maxByOrNull { it.temperature!! }!!
                    val bas = avecT.minByOrNull { it.temperature!! }!!
                    val t = { x: Previsions.Prevision -> x.temperature!!.roundToInt() }
                    when {
                        avecT.size == 1 -> {
                            lignes.add("${t(a)}° à ${h(a)} h.")
                            parle = "$Nom, ${MeteoTexte.parle(a.temperature!!)} ${degres(t(a))}."
                        }
                        p.jourEntier -> {
                            lignes.add("Jusqu'à ${t(haut)}° vers ${h(haut)} h.")
                            lignes.add("${t(bas)}° à ${h(bas)} h.")
                            parle = "$Nom, jusqu'à ${MeteoTexte.parle(haut.temperature!!)} ${degres(t(haut))} vers ${h(haut)} heures, " +
                                "${MeteoTexte.parle(bas.temperature!!)} à ${h(bas)} heures."
                            choisi = haut.instant
                        }
                        t(haut) > maxOf(t(a), t(z)) + 1 -> {
                            lignes.add("${t(a)}° à ${h(a)} h.")
                            lignes.add("Jusqu'à ${t(haut)}° vers ${h(haut)} h.")
                            lignes.add("${t(z)}° vers ${h(z)} h.")
                            parle = "$Nom, ${MeteoTexte.parle(a.temperature!!)} ${degres(t(a))} à ${h(a)} heures, jusqu'à " +
                                "${MeteoTexte.parle(haut.temperature!!)} vers ${h(haut)} heures, puis ${MeteoTexte.parle(z.temperature!!)} vers ${h(z)} heures."
                        }
                        else -> {
                            lignes.add("${t(a)}° à ${h(a)} h.")
                            lignes.add("${t(z)}° vers ${h(z)} h.")
                            parle = "$Nom, ${MeteoTexte.parle(a.temperature!!)} ${degres(t(a))} à ${h(a)} heures, puis " +
                                "${MeteoTexte.parle(z.temperature!!)} ${degres(t(z))} vers ${h(z)} heures."
                        }
                    }
                }
            }
            Sujet.VENT -> {
                if (vents.isEmpty()) {
                    lignes.add("Pas de vent prévu.")
                    parle = "Je n'ai pas de prévision de vent $nom."
                } else {
                    val mn = vents.min().roundToInt()
                    val mx = vents.max().roundToInt()
                    val sec = secteur(directionMoyenne(heures))
                    val faible = vents.max() < seuilFaible(unite)
                    val g = gMax?.rafales?.roundToInt()
                    val ecart = if (mn == mx) "$mx" else "$mn à $mx"
                    if (faible) {
                        lignes.add("Peu de vent $nom.")
                        lignes.add("$mx $unite au plus.")
                        parle = "Peu de vent $nom, $mx ${uniteParlee(unite)} au plus."
                    } else {
                        lignes.add((sec?.let { majuscule(it) + ", " } ?: "") + "$ecart $unite.")
                        if (g != null && g > mx) lignes.add("Rafales à $g vers ${h(gMax)} h.")
                        parle = "$Nom, vent" + (sec?.let { " " + de(it) } ?: "") + ", $ecart ${uniteParlee(unite)}" +
                            (if (g != null && g > mx) ". Rafales à $g vers ${h(gMax)} heures." else ".")
                        if (g != null) choisi = gMax.instant
                    }
                }
            }
            else -> {
                val ciel = cielDominant(heures)
                val mn = temps.minOrNull()?.roundToInt()
                val mx = temps.maxOrNull()?.roundToInt()
                val t = when {
                    mn == null || mx == null -> null
                    mn == mx -> "$mx°"
                    else -> "$mn à $mx°"
                }
                lignes.add(listOfNotNull(ciel?.let { majuscule(it) }, t).joinToString(", ").ifEmpty { "Prévisions $nom" } + ".")
                val pluie = phrasePluie(episodes, probaMax, ::h)
                lignes.add(pluie)
                parle = "$Nom, " + listOfNotNull(ciel, when {
                    mn == null || mx == null -> null
                    mn == mx -> "${MeteoTexte.parle(mx.toDouble())} ${degres(mx)}"
                    else -> "de ${MeteoTexte.parle(mn.toDouble())} à ${MeteoTexte.parle(mx.toDouble())} degrés"
                }).joinToString(", ") + ". " + heures(pluie).replace("%", "pour cent")
            }
        }
        // La ligne de détail couvre toute la bande, pluie suivie jusqu'à sa fin comprise.
        val bande = l.horaire.filter { it.instant in debut until bandeFin }
        val detail = detailTerre(q.sujet, p, bande, debut, bandeFin, fin, episodes, finPluie, mmTotal, mmVu, bande.mapNotNull { it.pluie }.maxOrNull(), unite, zone)
        return base.copy(lignes = lignes, parle = parle, bandeDebut = debut, bandeFin = bandeFin, choisi = choisi, detail = detail)
    }

    /** « Il pleut ? », « quel temps fait-il » : la météo du moment. */
    private fun maintenantTerre(q: Question, l: Previsions.Lecture, base: Reponse, heure: Previsions.Prevision?, unite: String): Reponse {
        val a = l.actuel!!
        val lignes = ArrayList<String>()
        val parle: String
        val ciel = a.condition.takeIf { it.isNotBlank() }?.let { Maison.meteoEnFrancais(it) }
        when (q.sujet) {
            Sujet.PLUIE -> {
                val pleut = a.condition in setOf("rainy", "pouring", "lightning-rainy", "snowy-rainy", "hail") || (heure != null && MeteoTexte.pluvieuse(heure))
                lignes.add(if (pleut) "Oui, il pleut en ce moment." else "Non, pas en ce moment.")
                parle = lignes[0]
            }
            Sujet.VENT -> {
                val v = a.vent?.roundToInt()
                val sec = a.direction?.let { secteur(it) }
                lignes.add(if (v == null) "Pas de mesure du vent." else (sec?.let { majuscule(it) + ", " } ?: "") + "$v $unite.")
                a.rafales?.roundToInt()?.takeIf { v != null && it > v }?.let { lignes.add("Rafales à $it.") }
                parle = if (v == null) "Je n'ai pas le vent du moment." else "En ce moment, vent" + (sec?.let { " " + de(it) } ?: "") +
                    ", $v ${uniteParlee(unite)}" + (a.rafales?.roundToInt()?.takeIf { it > v }?.let { ", rafales à $it" } ?: "") + "."
            }
            else -> {
                val t = a.temperature
                lignes.add(listOfNotNull(t?.let { "${it.roundToInt()}°" }, ciel).joinToString(", ").ifEmpty { "Pas de mesure" } + ".")
                a.ressenti?.let { lignes.add("Ressenti ${it.roundToInt()}°.") }
                parle = "En ce moment, " + listOfNotNull(t?.let { "${MeteoTexte.parle(it)} ${degres(it.roundToInt())}" }, ciel).joinToString(", ") +
                    (a.ressenti?.let { ", ressenti ${MeteoTexte.parle(it)}" } ?: "") + "."
            }
        }
        val debut = heure?.instant
        return base.copy(
            lignes = lignes, parle = parle, bandeDebut = debut, bandeFin = debut?.let { it + 3_600_000L }, choisi = debut,
            detail = "En ce moment" to listOfNotNull(
                a.temperature?.let { "${it.roundToInt()}°" }, a.ressenti?.let { "ressenti ${it.roundToInt()}°" },
                ciel, a.vent?.let { "vent ${it.roundToInt()} $unite" }, a.humidite?.let { "humidité $it %" },
            ).joinToString(", ").let { if (it.isEmpty()) "" else " : $it" },
        )
    }

    /** Jour hors des prévisions horaires (au-delà de 48 h) : la prévision du jour. */
    private fun parJour(q: Question, l: Previsions.Lecture, base: Reponse, date: LocalDate, maintenant: ZonedDateTime): Reponse {
        val zone = maintenant.zone
        val jours = MeteoTexte.jours(l.journalier, maintenant.toLocalDate(), zone)
        val j = jours.firstOrNull { it.date == date }
        val nom = q.plage.nom
        val Nom = majuscule(nom)
        if (j == null) {
            val d = "Je n'ai pas de prévision pour $nom."
            return base.copy(lignes = listOf("Pas de prévision pour $nom."), parle = d, detail = Nom to "")
        }
        val cond = l.journalier.firstOrNull { Instant.ofEpochMilli(it.instant).atZone(zone).toLocalDate() == date && it.deJour != false }
        val ciel = cond?.condition?.let { Maison.meteoEnFrancais(it) }
        val unite = l.actuel?.uniteVent ?: "km/h"
        val lignes = ArrayList<String>()
        val parle: String
        val t = when {
            j.max != null && j.min != null -> "${j.min.roundToInt()} à ${j.max.roundToInt()}°"
            j.max != null -> "${j.max.roundToInt()}°"
            else -> null
        }
        val tParle = when {
            j.max != null && j.min != null -> "de ${MeteoTexte.parle(j.min)} à ${MeteoTexte.parle(j.max)} degrés"
            j.max != null -> "${MeteoTexte.parle(j.max)} ${degres(j.max.roundToInt())}"
            else -> null
        }
        val p = j.probabilite
        val mm = j.millimetres?.takeIf { it >= 0.1 }?.let { MeteoTexte.mm(it) }
        when (q.sujet) {
            Sujet.PLUIE -> {
                val oui = (p ?: 0) >= 50 || (j.millimetres ?: 0.0) >= 1.0
                val peutEtre = !oui && ((p ?: 0) >= 30 || (j.millimetres ?: 0.0) >= 0.2)
                lignes.add(when { oui -> "Oui, probablement."; peutEtre -> "Peut-être."; else -> "Non, sec $nom." })
                val suite = listOfNotNull(p?.let { "pluie à $it %" }, mm?.let { "$it mm" })
                if (suite.isNotEmpty()) lignes.add(majuscule(suite.joinToString(", ")) + ".")
                parle = lignes[0].removeSuffix(".") + (if (suite.isEmpty()) "." else ", " + suite.joinToString(", ").replace("%", "pour cent").replace(" mm", " " + unitePluie(j.millimetres ?: 0.0)) + ".")
            }
            Sujet.TEMPERATURE -> {
                lignes.add(t?.let { majuscule("de $it") + "." } ?: "Pas de température prévue.")
                parle = "$Nom, " + (tParle ?: "pas de température prévue") + "."
            }
            Sujet.VENT -> {
                val v = cond?.vent?.roundToInt()
                val sec = cond?.direction?.let { secteur(it) }
                lignes.add(if (v == null) "Pas de détail du vent." else (sec?.let { majuscule(it) + ", " } ?: "") + "jusqu'à $v $unite.")
                cond?.rafales?.roundToInt()?.takeIf { v != null && it > v }?.let { lignes.add("Rafales à $it.") }
                parle = if (v == null) "Je n'ai pas le détail du vent pour $nom." else "$Nom, vent" + (sec?.let { " " + de(it) } ?: "") +
                    ", jusqu'à $v ${uniteParlee(unite)}."
            }
            else -> {
                lignes.add(listOfNotNull(ciel?.let { majuscule(it) }, t).joinToString(", ").ifEmpty { "Prévision de $nom" } + ".")
                lignes.add(p?.takeIf { it >= 10 }?.let { "Pluie à $it %." } ?: "Sec.")
                parle = "$Nom, " + listOfNotNull(ciel, tParle).joinToString(", ") + ". " + (p?.takeIf { it >= 10 }?.let { "Pluie à $it pour cent." } ?: "Sec.")
            }
        }
        val reste = listOfNotNull(ciel, t, p?.let { "pluie $it %" }, mm?.let { "$it mm" }).joinToString(", ")
        return base.copy(lignes = lignes, parle = parle, detail = Nom to (if (reste.isEmpty()) "" else " : $reste"))
    }

    /** Ligne sous la frise : la plage et ce qui justifie la réponse, le sujet de la question en premier. */
    private fun detailTerre(
        sujet: Sujet, p: Plage, heures: List<Previsions.Prevision>, debut: Long, bandeFin: Long, fin: Long,
        episodes: List<List<Previsions.Prevision>>, finPluie: Long?, mm: Double, mmVu: Boolean, probaMax: Int?, unite: String, zone: ZoneId,
    ): Pair<String, String> {
        fun h(t: Long) = Instant.ofEpochMilli(t).atZone(zone).hour
        val prolonge = bandeFin > fin
        val tete = when {
            heures.size == 1 -> "${h(debut)} h"
            prolonge -> "De ${h(debut)} h à ${h(bandeFin)} h"
            else -> "${majuscule(p.nom)}, de ${h(debut)} h à ${h(fin)} h"
        }
        val pluie = if (episodes.isEmpty()) {
            "sec" + (probaMax?.takeIf { it >= 10 }?.let { ", pluie $it % au plus" } ?: "")
        } else {
            val d = h(episodes.first().first().instant)
            val f = finPluie?.let { h(it) }
            listOfNotNull(
                if (f != null) "pluie de $d h à $f h" else "pluie dès $d h",
                probaMax?.let { "jusqu'à $it %" },
                if (mmVu && mm >= 0.1) MeteoTexte.mm(mm) + " mm en tout" else null,
            ).joinToString(", ")
        }
        val t = heures.mapNotNull { it.temperature }
        val temp = if (t.isEmpty()) null else {
            val a = t.min().roundToInt()
            val b = t.max().roundToInt()
            if (a == b) "$b°" else "$a à $b°"
        }
        val v = heures.mapNotNull { it.vent }
        val g = heures.filter { it.rafales != null }.maxByOrNull { it.rafales!! }
        val vent = if (v.isEmpty()) null else {
            val a = v.min().roundToInt()
            val b = v.max().roundToInt()
            val sec = secteur(directionMoyenne(heures))
            (if (sujet == Sujet.VENT && sec != null) "vent ${de(sec)}, " else "vent ") + (if (a == b) "$b" else "$a à $b") + " $unite" +
                (g?.rafales?.roundToInt()?.takeIf { it > b && (sujet == Sujet.VENT || MeteoTexte.rafaleMontree(g.rafales, unite)) }
                    ?.let { ", rafales jusqu'à $it $unite à ${h(g.instant)} h" } ?: "")
        }
        val parties = when (sujet) {
            Sujet.PLUIE -> listOfNotNull(pluie, temp, vent)
            Sujet.TEMPERATURE -> listOfNotNull(temp, pluie, vent)
            Sujet.VENT -> listOfNotNull(vent, pluie, temp)
            else -> listOfNotNull(temp, pluie, vent)
        }
        return tete to " : " + parties.joinToString(", ")
    }

    /** Suites d'heures pluvieuses (règle de [MeteoTexte.pluvieuse]). */
    fun episodes(heures: List<Previsions.Prevision>): List<List<Previsions.Prevision>> {
        val sortie = ArrayList<List<Previsions.Prevision>>()
        var cours = ArrayList<Previsions.Prevision>()
        for (x in heures) {
            if (MeteoTexte.pluvieuse(x)) cours.add(x)
            else if (cours.isNotEmpty()) {
                sortie.add(cours)
                cours = ArrayList()
            }
        }
        if (cours.isNotEmpty()) sortie.add(cours)
        return sortie
    }

    private fun phrasePluie(episodes: List<List<Previsions.Prevision>>, probaMax: Int?, h: (Previsions.Prevision) -> Int): String = when {
        episodes.isEmpty() -> probaMax?.takeIf { it >= 20 }?.let { "Pluie à $it % au plus." } ?: "Sec."
        episodes.size == 1 && episodes[0].size == 1 -> "Pluie vers ${h(episodes[0][0])} h."
        else -> "Pluie à partir de ${h(episodes[0][0])} h."
    }

    /** Ciel le plus fréquent de la plage, en mots, ou null. */
    private fun cielDominant(heures: List<Previsions.Prevision>): String? {
        val n = HashMap<String, Int>()
        for (h in heures) if (h.condition.isNotBlank()) n[h.condition] = (n[h.condition] ?: 0) + 1
        return n.maxByOrNull { it.value }?.key?.let { Maison.meteoEnFrancais(it) }
    }

    private fun entete(s: Sujet, p: Plage): String = when (s) {
        Sujet.PLUIE -> "Pluie ${p.nom}"
        Sujet.TEMPERATURE -> "Température ${p.nom}"
        Sujet.VENT -> "Vent ${p.nom}"
        Sujet.MER -> "Conditions de navigation ${p.nom}"
        Sujet.GENERAL -> "Météo ${p.nom}"
    }

    // ------------------------------------------------------------ outils

    private val SECTEURS = listOf("nord", "nord-est", "est", "sud-est", "sud", "sud-ouest", "ouest", "nord-ouest")

    /** Secteur d'où vient le vent, en mots (« sud-ouest »). */
    fun secteur(degres: Double?): String? = degres?.let { SECTEURS[((((it % 360.0) + 360.0) % 360.0) / 45.0).roundToInt() % 8] }

    /** « d'ouest », « de sud-ouest ». */
    fun de(secteur: String): String = if (secteur.first() in "aeiou") "d'$secteur" else "de $secteur"

    /** Direction moyenne des heures, pondérée par la force du vent, ou null. */
    fun directionMoyenne(heures: List<Previsions.Prevision>): Double? {
        var x = 0.0
        var y = 0.0
        for (h in heures) {
            val d = h.direction ?: continue
            val v = h.vent ?: 1.0
            x += v * cos(Math.toRadians(d))
            y += v * sin(Math.toRadians(d))
        }
        if (abs(x) < 1e-9 && abs(y) < 1e-9) return null
        return (Math.toDegrees(atan2(y, x)) + 360.0) % 360.0
    }

    /** 10 km/h dans l'unité du vent : en dessous, « peu de vent ». */
    private fun seuilFaible(unite: String): Double = MeteoTexte.seuilRafales(unite) / 3.0

    fun uniteParlee(unite: String): String = when (unite.trim().lowercase(Locale.ROOT)) {
        "km/h" -> "kilomètres heure"
        "m/s" -> "mètres par seconde"
        "mph" -> "miles par heure"
        "kn", "kt", "nœuds", "noeuds" -> "nœuds"
        else -> unite
    }

    private fun degres(n: Int): String = if (abs(n) >= 2) "degrés" else "degré"

    /** « 17 h » dit « 17 heures », seulement après un nombre (« dans 2 heures » reste tel quel). */
    fun heures(s: String): String = Regex("""(\d+) h\b""").replace(s) { r -> r.groupValues[1] + if (r.groupValues[1].toInt() >= 2) " heures" else " heure" }

    private fun unitePluie(mm: Double): String = if (mm >= 2.0) "millimètres" else "millimètre"

    fun majuscule(s: String): String = s.replaceFirstChar { it.titlecase(Locale.FRANCE) }

    /** Nom du jour pour l'en-tête d'un jour de la semaine (« samedi »). */
    fun nomJour(d: LocalDate): String = d.dayOfWeek.getDisplayName(TextStyle.FULL, Locale.FRANCE)
}
