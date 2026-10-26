package assistant.vocal.jarvis

import org.json.JSONObject
import java.text.Normalizer
import kotlin.math.roundToInt

/**
 * Volet de réglage de la télévision (0.39.0, lot S-L3) : tuiles de sources, un seul curseur de volume, texte d'état.
 * Les tuiles viennent de la configuration (reglages.tele.sources de maison.json : nom affiché et nom de la source dans
 * Home Assistant), jamais du code. Toute commande part par [Appareils.source] ou par le volume de la maison en grand,
 * donc par les contrôles de Securite comme les autres. Rien d'Android ici, pour que les tests tournent sur la machine.
 */
internal object ReglageTele {

    /** Une tuile du volet : le nom affiché et le nom exact de la source dans la liste de la télé. */
    class Tuile(val nom: String, val source: String)

    /** Libellé de la dernière tuile, qui déplie toutes les sources de la télé. */
    const val TOUTES = "Toutes"

    /** Tuiles par rangée du volet. */
    const val PAR_RANGEE = 4

    /** Tuiles lues dans la configuration de la maison. */
    val TUILES: List<Tuile> by lazy { lireTuiles(ConfigMaison.section("reglages")) }

    /**
     * Tuiles décrites par reglages.tele.sources : une liste d'objets {nom, source}. Une entrée sans nom ou sans
     * source, ou mal formée, est ignorée. Sans section, aucune tuile (le volet n'offre alors que le volume).
     */
    fun lireTuiles(reglages: JSONObject): List<Tuile> {
        val liste = reglages.optJSONObject("tele")?.optJSONArray("sources") ?: return emptyList()
        val tuiles = ArrayList<Tuile>()
        for (i in 0 until liste.length()) {
            val e = liste.optJSONObject(i) ?: continue
            val nom = e.optString("nom").trim()
            val source = e.optString("source").trim()
            if (nom.isNotEmpty() && source.isNotEmpty() && nom != TOUTES) tuiles.add(Tuile(nom, source))
        }
        return tuiles
    }

    /** Forme comparable d'un nom de source : minuscules, sans accent ni espace (« HDMI 1 » et « HDMI1 » se valent). */
    fun forme(s: String): String =
        Normalizer.normalize(s.lowercase(), Normalizer.Form.NFD).filter { it.isLetterOrDigit() || it == '+' }

    fun memeSource(a: String, b: String) = a.isNotBlank() && b.isNotBlank() && forme(a) == forme(b)

    /**
     * Tuiles que la télé offre vraiment. Si HA ne donne pas sa liste de sources, toutes les tuiles restent (le choix
     * est alors celui de la configuration), sinon seules celles dont la source figure dans la liste.
     */
    fun tuilesOffertes(tuiles: List<Tuile>, a: Appareils.Appareil?): List<Tuile> {
        if (a == null || a.sources.isEmpty()) return tuiles
        return tuiles.filter { t -> a.sources.any { memeSource(it, t.source) } }
    }

    /** Nom de la source tel que la télé le donne, ou la source configurée si la liste ne la contient pas. */
    fun sourceExacte(a: Appareils.Appareil?, t: Tuile): String = a?.sources?.firstOrNull { memeSource(it, t.source) } ?: t.source

    /** Tuile qui correspond à une source, ou null. */
    fun tuileDe(tuiles: List<Tuile>, source: String): Tuile? = tuiles.firstOrNull { memeSource(it.source, source) }

    /**
     * Source à croire en cours : celle que lit HA si elle est connue, sinon la dernière choisie ici. Null si la télé
     * est éteinte ou ne dit rien. La lecture de la source est peu fiable sur cette télé (application active parfois
     * absente), le résultat ne s'affiche donc qu'au conditionnel, voir [texteEtat].
     */
    fun sourceProbable(a: Appareils.Appareil?, choisie: String?): String? {
        if (a == null || !MaisonEnGrand.teleAllumee(a)) return null
        if (a.source.isNotBlank()) return a.source
        return choisie?.takeIf { it.isNotBlank() }
    }

    /** Tuile mise en avant : celle de la source probable, ou null. */
    fun tuileActive(tuiles: List<Tuile>, a: Appareils.Appareil?, choisie: String?): Tuile? =
        sourceProbable(a, choisie)?.let { tuileDe(tuiles, it) }

    /**
     * Texte sous le nom : « éteinte », « hors ligne », « allumée » ou « allumée, sans doute Netflix ». Le conditionnel
     * vient de ce que la source lue n'est pas toujours juste.
     */
    fun texteEtat(a: Appareils.Appareil?, horsLigne: Boolean, tuiles: List<Tuile>, choisie: String?): String {
        if (horsLigne) return "hors ligne"
        if (!MaisonEnGrand.teleAllumee(a)) return "éteinte"
        val source = sourceProbable(a, choisie) ?: return "allumée"
        val nom = tuileDe(tuiles, source)?.nom ?: source
        return "allumée, sans doute $nom"
    }

    /** Ce que fait un toucher sur la ligne (hors rond) : déplier le volet si la télé est allumée, sinon l'allumer. */
    enum class Geste { DEPLIER, BASCULER }

    fun gesteLigne(a: Appareils.Appareil?, horsLigne: Boolean): Geste =
        if (!horsLigne && MaisonEnGrand.teleAllumee(a)) Geste.DEPLIER else Geste.BASCULER

    /** Le volet peut être ouvert : télé en ligne et allumée. */
    fun volet(a: Appareils.Appareil?, horsLigne: Boolean) = !horsLigne && MaisonEnGrand.teleAllumee(a)

    /** Les sources que la télé annonce, pour la tuile Toutes, sans doublon (à la forme près). */
    fun toutesLesSources(a: Appareils.Appareil?): List<String> {
        val vues = HashSet<String>()
        return a?.sources.orEmpty().filter { it.isNotBlank() && vues.add(forme(it)) }
    }

    /** Commande de choix d'une source, par select_source. */
    fun commande(a: Appareils.Appareil, source: String): Appareils.Commande = Appareils.source(a, source)

    /** Les tuiles par rangées de [PAR_RANGEE], pour la mise en page. */
    fun rangees(n: Int): List<IntRange> = (0 until n step PAR_RANGEE).map { it until minOf(it + PAR_RANGEE, n) }

    // ------------------------------------------------------------ volume

    /** Volume le plus fort permis (plafond réglé de la sécurité en dur), de 0 à 1. */
    val volumeMax: Double get() = Securite.VOLUME_MAX

    /** Position du curseur (0 à 1 de la piste, qui s'arrête au plafond) pour un volume lu. Sans volume lu, 0. */
    fun fractionPiste(a: Appareils.Appareil?): Float =
        a?.volume?.let { VolumeVise.fraction(it).toFloat() } ?: 0f

    /** Volume (0 à 1, arrondi au centième, jamais au-dessus du plafond) pour une position du curseur. */
    fun volumeDePiste(fraction: Float): Double =
        Securite.plafonnerVolume(((fraction.coerceIn(0f, 1f) * volumeMax * 100).roundToInt()) / 100.0)

    /** Le curseur peut régler le volume : la télé a un volume lu. */
    fun volumeReglable(a: Appareils.Appareil?, horsLigne: Boolean) = !horsLigne && a?.volume != null

    /** Texte du volume à côté du curseur : « 35 % », ou « sans mesure » quand HA ne le dit pas. */
    fun texteVolume(a: Appareils.Appareil?): String = a?.volume?.let { TextesCourts.pourcent(it) } ?: "sans mesure"

    /** Phrase pour TalkBack sur le curseur. */
    fun descriptionVolume(a: Appareils.Appareil?): String = "Volume de la télé, ${texteVolume(a)}"
}
