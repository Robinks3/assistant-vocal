package assistant.vocal.jarvis

import java.time.LocalDate
import java.time.format.DateTimeFormatter
import java.util.Locale
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * Textes et états de l'écran d'accueil de la tablette (0.18.0, piste « la maison »), logique pure testée
 * sur la machine (AccueilTest). L'écran lui-même est dans EcranAmbiant : ici, ce qu'il écrit et quand.
 */
internal object Accueil {

    /** Ce que montre l'accueil : le repos (plan, heure, musique), l'écoute, la réflexion, la réponse. */
    enum class Mode { ARRETE, REPOS, ECOUTE, REFLEXION, REPONSE }

    /** La réponse reste écrite 6 s après la fin de la voix, comme sous l'orbe du téléphone. */
    const val DUREE_REPONSE_MS = 6_000L

    /** Une panne ne s'affiche que si elle dure : le démarrage et une reconnexion brève ne disent rien. */
    const val DELAI_PANNE_MS = 20_000L

    fun mode(enMarche: Boolean, assistant: String, parole: String, paroleFinLe: Long, maintenant: Long): Mode = when {
        !enMarche -> Mode.ARRETE
        assistant == "Je t'écoute" -> Mode.ECOUTE
        assistant == "Je réfléchis" -> Mode.REFLEXION
        assistant == "Je réponds" -> Mode.REPONSE
        parole.isNotBlank() && (paroleFinLe == 0L || maintenant - paroleFinLe < DUREE_REPONSE_MS) -> Mode.REPONSE
        else -> Mode.REPOS
    }

    /** L'assistant travaille : l'écran entier sert à couper (écoute ou réponse). */
    fun occupe(m: Mode): Boolean = m == Mode.ECOUTE || m == Mode.REFLEXION || m == Mode.REPONSE

    /**
     * Ligne du haut à droite, en ambre : une panne, vide quand tout va bien. Les états du serveur, de la
     * passerelle et de la vision ne sont plus affichés en permanence.
     */
    fun panne(
        enMarche: Boolean, connecte: Boolean, serveurLocal: Boolean, passerelleDispo: Boolean, maisonLue: Boolean,
        visionNiveau: String, alerteCle: String, alerteJeton: String = "",
    ): String = when {
        alerteCle.isNotBlank() -> "Clé du serveur refusée, voir l'écran Appareils"
        alerteJeton.isNotBlank() -> "Appareil refusé par le serveur, voir l'écran Appareils"
        !enMarche -> ""
        !connecte -> "Serveur injoignable"
        !(passerelleDispo || (!serveurLocal && maisonLue)) -> "Home Assistant ne répond plus"
        visionNiveau == "erreur" -> "Caméra indisponible"
        else -> ""
    }

    /**
     * Retenue d'un texte qui doit durer [delaiMs] avant d'être montré (ligne de panne). Un texte qui en
     * remplace un autre déjà montré attend aussi son délai, l'ancien restant affiché d'ici là.
     */
    class Retenue(private val delaiMs: Long) {
        private var attendu = ""
        private var depuis = 0L
        var montre = ""
            private set

        fun avancer(texte: String, maintenant: Long, immediat: Boolean = false): String {
            if (texte != attendu) {
                attendu = texte
                depuis = maintenant
            }
            montre = when {
                texte.isEmpty() -> ""
                immediat || maintenant - depuis >= delaiMs -> texte
                else -> montre
            }
            return montre
        }
    }


    private val JOUR = DateTimeFormatter.ofPattern("EEEE", Locale.FRANCE)
    private val MOIS = DateTimeFormatter.ofPattern("MMMM", Locale.FRANCE)

    /** « Jeudi 22 octobre », « Dimanche 1er novembre ». */
    fun date(jour: LocalDate): String {
        val j = jour.dayOfMonth
        return JOUR.format(jour).replaceFirstChar { it.titlecase(Locale.FRANCE) } + " " +
            (if (j == 1) "1er" else j.toString()) + " " + MOIS.format(jour)
    }

    /** La météo en mots : « Éclaircies, 20 degrés ». Vide tant que Home Assistant n'a rien dit. */
    fun meteo(m: Etat.Meteo?): String {
        if (m == null) return ""
        val ciel = m.etat.trim().replaceFirstChar { it.titlecase(Locale.FRANCE) }
        return listOf(ciel, degres(m.temperature)).filter { it.isNotBlank() }.joinToString(", ")
    }

    /** Place de « 20 degrés » (ou « moins 3 degrés ») dans la phrase de la météo, pour sa teinte (0.19.0). */
    fun valeurMeteo(phrase: String): IntRange? =
        Regex("(?:moins )?\\d+ degrés?").find(phrase)?.range

    /** Place de « 17 h » (ou « en ce moment ») dans la phrase de la pluie, pour sa teinte (0.19.0). */
    fun valeurPluie(phrase: String): IntRange? =
        Regex("\\d+ h|en ce moment").find(phrase)?.range

    /**
     * Couleur réelle des lampes allumées pour « allumée » (0.19.0) : celle de la plus lumineuse, lue dans Home
     * Assistant (`rgb_color`, sinon sa température de blanc), sinon [defaut]. Une couleur trop sombre pour se
     * lire sur le noir est éclaircie vers le blanc, teinte gardée.
     */
    fun couleurLampes(lampes: List<Appareils.Appareil>, defaut: Int): Int {
        val l = lampes.filter { it.etat == "on" }.maxByOrNull { it.luminosite ?: 100 } ?: return defaut
        val rgb = l.rgb?.takeIf { it.size >= 3 }
        val brute = when {
            rgb != null -> (0xFF shl 24) or (rgb[0].coerceIn(0, 255) shl 16) or (rgb[1].coerceIn(0, 255) shl 8) or rgb[2].coerceIn(0, 255)
            l.kelvin != null && l.kelvin > 0 -> Palette.kelvin(l.kelvin)
            else -> return defaut
        }
        var c = brute
        var t = 0f
        while (Palette.luminance(c) < LUMINANCE_LISIBLE && t < 1f) {
            t += 0.1f
            c = Palette.melange(brute, 0xFFFFFFFF.toInt(), t)
        }
        return c
    }

    /** Luminance au-dessous de laquelle une couleur de lampe ne se lit plus sur le noir. */
    const val LUMINANCE_LISIBLE = 0.2

    /** « 20 degrés », « 1 degré », « moins 3 degrés », d'après « 20 °C » (signe moins typographique compris). */
    fun degres(temperature: String): String {
        val brut = Regex("[-\\u2212]?\\d+(?:[.,]\\d+)?").find(temperature)?.value ?: return ""
        val v = brut.replace(MOINS, '-').replace(',', '.').toDoubleOrNull() ?: return ""
        return degres(v)
    }

    /** Signe moins typographique (U+2212) de certaines locales Java, lu comme un tiret. */
    private val MOINS = 0x2212.toChar()

    fun degres(v: Double): String {
        val n = v.roundToInt()
        val a = abs(n)
        val unite = if (a >= 2) "degrés" else "degré"
        return if (n < 0) "moins $a $unite" else "$a $unite"
    }

    /** « 1 lumière », « 2 lumières ». */
    fun lumieres(n: Int): String = if (n <= 1) "$n lumière" else "$n lumières"

    /** « Dans le salon », « Dans le salon et la cuisine » (revue du 22/10), « Sur l'enceinte du bureau » hors de la sortie du son. */
    fun lieuMusique(l: Etat.Lecteur): String {
        val noms = (listOf(l.id) + l.membres).distinct()
            .mapNotNull { id -> SortieSon.ENCEINTES.firstOrNull { it.first == id }?.second }
            .distinct()
        return if (noms.isEmpty()) "Sur " + l.nom.ifBlank { "l'enceinte" } else "Dans " + enumerer(noms.map { article(it) })
    }

    /** « le salon », « la cuisine », « l'entrée », « la chambre Sacha », « les chevets Sacha ». */
    fun article(nom: String): String {
        val t = nom.trim()
        if (t.isEmpty()) return t
        // Seule la première lettre passe en minuscule : « Chambre Sacha » garde son prénom.
        val n = t.replaceFirstChar { it.lowercase(Locale.FRANCE) }
        return when {
            Accord.pluriel(n) -> "les $n"
            n.first() in "aeéèêiîoôuyh" -> "l'$n"
            Accord.feminin(n) -> "la $n"
            else -> "le $n"
        }
    }

    // ------------------------------------------------ phrases de la zone de texte (revue du 22/10)

    /** Une phrase de la zone de texte, et la partie à écrire en ambre (le seul mot « allumé »), ou null. */
    data class Phrase(val texte: String, val ambre: IntRange? = null)

    private val NOMBRES = listOf("Zéro", "Une", "Deux", "Trois", "Quatre", "Cinq", "Six", "Sept", "Huit", "Neuf", "Dix")

    /**
     * Pièces allumées en une phrase : « Le séjour est allumé. », « La salle à manger est allumée. »,
     * « Le séjour et la salle à manger sont allumés. », à partir de trois « Trois pièces allumées. ». Rien
     * d'allumé : null. [pieces] : noms des pièces de Home Assistant (zones), dans l'ordre de la maison.
     */
    fun phraseLumieres(pieces: List<String>): Phrase? {
        val p = pieces.map { it.trim() }.filter { it.isNotEmpty() }.distinct()
        if (p.isEmpty()) return null
        if (p.size >= 3) {
            val debut = (NOMBRES.getOrNull(p.size) ?: p.size.toString()) + " pièces "
            return Phrase("${debut}allumées.", debut.length until debut.length + "allumées".length)
        }
        val sujet = enumerer(p.map { article(it) }).replaceFirstChar { it.titlecase(Locale.FRANCE) }
        val verbe = if (p.size > 1 || Accord.pluriel(p[0])) " sont " else " est "
        val mot = Accord.participe(p, "allumer")
        val debut = sujet + verbe
        return Phrase("$debut$mot.", debut.length until debut.length + mot.length)
    }

    /**
     * Échec d'une action sur des lumières (carte « sans réponse ») : « Je n'ai pas pu allumer le salon, la
     * maison ne répond pas. ». [noms] : noms des lumières visées, [effet] : allumer, eteindre ou regler.
     */
    fun echec(noms: List<String>, effet: String): String {
        val verbe = when (effet) {
            "allumer" -> "allumer"
            "eteindre" -> "éteindre"
            else -> "régler"
        }
        val quoi = if (noms.isEmpty()) "les lumières" else enumerer(noms.map { article(it) })
        return "Je n'ai pas pu $verbe $quoi, la maison ne répond pas."
    }

    /** « La maison ne répond plus depuis 10 h 02. », [heure] et [minute] du début de la panne. */
    fun phrasePanne(heure: Int, minute: Int): String = String.format(Locale.FRANCE, "La maison ne répond plus depuis %d h %02d.", heure, minute)

    /**
     * Pluie dans les douze heures, d'après les prévisions horaires : « Pluie vers 17 h. », « Pluie en ce
     * moment. », « Neige vers 6 h. ». Vide sans pluie annoncée ou sans prévision horaire.
     */
    fun pluie(liste: List<Previsions.Prevision>, maintenant: java.time.ZonedDateTime): String {
        val debut = maintenant.truncatedTo(java.time.temporal.ChronoUnit.HOURS)
        val fin = debut.plusHours(12)
        val p = liste.firstOrNull {
            val h = java.time.Instant.ofEpochMilli(it.instant).atZone(maintenant.zone)
            !h.isBefore(debut) && h.isBefore(fin) && pluvieuse(it)
        } ?: return ""
        val h = java.time.Instant.ofEpochMilli(p.instant).atZone(maintenant.zone)
        val mot = if (p.condition == "snowy" || p.condition == "snowy-rainy") "Neige" else "Pluie"
        return if (h.hour == maintenant.hour && h.toLocalDate() == maintenant.toLocalDate()) "$mot en ce moment." else "$mot vers ${h.hour} h."
    }

    /** Une heure pluvieuse : probabilité d'au moins 50 %, ou condition de pluie, de neige, d'orage ou de grêle. */
    fun pluvieuse(p: Previsions.Prevision): Boolean =
        (p.pluie ?: -1) >= 50 || p.condition in setOf("rainy", "pouring", "lightning-rainy", "snowy", "snowy-rainy", "hail")

    // ------------------------------------------------ couche de service et accueil de la personne

    /** Point d'état de la couche de service : tout va bien, panne, ou rien à surveiller (désactivé, démarrage). */
    enum class Point { OK, PANNE, ETEINT }

    /** Serveur, maison (passerelle HA) et caméra, dans cet ordre. */
    fun points(
        enMarche: Boolean, connecte: Boolean, serveurLocal: Boolean, passerelleDispo: Boolean, maisonLue: Boolean, visionNiveau: String,
    ): List<Point> {
        if (!enMarche) return listOf(Point.ETEINT, Point.ETEINT, Point.ETEINT)
        val serveur = if (connecte) Point.OK else Point.PANNE
        val maison = if (passerelleDispo || (!serveurLocal && maisonLue)) Point.OK else Point.PANNE
        val camera = when (visionNiveau) {
            "ok" -> Point.OK
            "erreur" -> Point.PANNE
            else -> Point.ETEINT
        }
        return listOf(serveur, maison, camera)
    }

    /** « Bonjour Sacha », « Bonsoir Sacha » à partir de 18 h (et la nuit), rien pour un inconnu. */
    fun salutation(nom: String?, heure: Int): String {
        val n = nom?.trim()?.takeIf { it.isNotEmpty() } ?: return ""
        return (if (heure >= 18 || heure < 5) "Bonsoir " else "Bonjour ") + n
    }

    /**
     * Fenêtre de l'accueil de la personne : « Bonjour Sacha » pendant [dureeMs] après une reconnaissance,
     * puis plus rien. Une même personne n'est saluée de nouveau qu'après [absenceMs] sans être vue (la
     * reconnaissance peut clignoter), une autre personne l'est tout de suite.
     */
    class Salut(private val dureeMs: Long = 10_000L, private val absenceMs: Long = 60_000L) {
        private var nom: String? = null
        private var vuLe = Long.MIN_VALUE / 2
        private var depuis = Long.MIN_VALUE / 2

        /** [vu] : prénom d'une personne seule reconnue, ou null. Rend le prénom à saluer maintenant, ou null. */
        fun avancer(vu: String?, maintenant: Long): String? {
            if (vu != null) {
                if (vu != nom || maintenant - vuLe > absenceMs) depuis = maintenant
                nom = vu
                vuLe = maintenant
            }
            return if (vu != null && maintenant - depuis < dureeMs) vu else null
        }
    }

    /** « A », « A et B », « A, B et C ». */
    fun enumerer(l: List<String>): String =
        if (l.size <= 1) l.joinToString("") else l.dropLast(1).joinToString(", ") + " et " + l.last()
}

/** Accord en genre et en nombre des noms d'appareils et de pièces (0.18.0), heuristique sur le premier mot. */
internal object Accord {
    private val FEMININS = setOf(
        "lampe", "lumière", "suspension", "applique", "ampoule", "guirlande", "cuisine", "entrée", "chambre", "salle",
        "veilleuse", "lanterne", "led", "bande", "barre", "liseuse", "enceinte", "télé", "télévision", "lampes",
        "lumières", "suspensions", "appliques", "ampoules", "guirlandes", "leds", "bandes", "chambres", "salles",
    )

    private fun premier(nom: String): String = nom.trim().lowercase(Locale.FRANCE).substringBefore(' ')

    fun feminin(nom: String): Boolean = premier(nom) in FEMININS

    /** « Chevets Sacha », « Lampes du salon », « Salon et Lampe TV » sont des pluriels. */
    fun pluriel(nom: String): Boolean {
        val p = premier(nom)
        return " et " in nom || ", " in nom || (p.length > 3 && (p.endsWith("s") || p.endsWith("x")))
    }

    /** Participe accordé avec les noms : allumé, éteinte, réglés... [effet] : allumer, eteindre ou regler. */
    fun participe(noms: List<String>, effet: String): String {
        val base = when (effet) {
            "allumer" -> "allumé"
            "eteindre" -> "éteint"
            else -> "réglé"
        }
        val f = noms.isNotEmpty() && noms.all { feminin(it) }
        val p = noms.size > 1 || noms.any { pluriel(it) }
        return base + (if (f) "e" else "") + (if (p) "s" else "")
    }
}
