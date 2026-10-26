package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject
import java.text.Normalizer
import java.util.Calendar
import java.util.TimeZone

/**
 * Sécurité écrite en dur, demandée le 13/10/2026. À ne lever qu'à la demande explicite du propriétaire.
 * Copie exacte des règles et des listes de poc/securite.py (côté serveur) :
 * Les noms et les listes propres à la maison (occupant protégé, zones, entités, lecteurs de son, fuseau)
 * viennent de la configuration de la maison : maison.json du dossier de configuration (modèle config-exemple/),
 * copiée dans BuildConfig.MAISON_JSON par build.gradle.kts. Les tests unitaires lisent le dossier désigné
 * par la propriété système maison.dossier (config-exemple/, valeurs fictives). « L'occupant » est la personne nommée par
 * nom_occupant.
 * 1. ne JAMAIS toucher à ce qui appartient à l'occupant (chambre, salle de bain, lumières, réveils,
 *    automatisations, scripts, téléphone), ni viser « all », une zone de l'occupant ou un appareil ;
 * 2. aucun son dans le salon pendant les heures calmes (heures_calmes, de minuit à 9 h par défaut,
 *    heure du fuseau de la maison) ;
 * 3. exception décidée le 21/10/2026 : l'occupant reconnu par la tablette, seul devant elle et
 *    avec assurance, peut allumer, éteindre et régler ses lumières à lui (PERMIS_PERSONNE), et rien
 *    d'autre de ce qui lui appartient. Quelqu'un d'autre, ou personne de sûr : la règle 1 reste entière.
 * Assist de Home Assistant est sauté tant que SECURITE_ACTIVE est vrai : on ne voit pas sa cible avant.
 *
 * Levée le 22/10/2026 à la demande explicite du propriétaire : règles 1 et 2 coupées (PROTEGER_OCCUPANT et
 * HEURE_CALME_ACTIVE à false), comme dans poc/securite.py. Reste le refus d'un appareil visé par son
 * identifiant brut. Remettre une règle : son drapeau à true ici ET dans securite.py.
 *
 * Plafond du volume (VOLUME_MAX) : fixe du 22/10/2026, réglable depuis le 25/10/2026 à la demande du
 * propriétaire par securite.plafond_volume (pourcentage, 100 par défaut : aucun plafond). Quand un plafond est
 * réglé, jamais de media_player.volume_set au-dessus. Ici, les données sont plafonnées là où elles sont
 * construites ([plafonner], appelé par Maison.commandeMedia, Maison.commande, Appareils.regler,
 * CerveauAppareil et MoteurLocal), côté serveur verifier() de securite.py plafonne aussi tout ce qui passe
 * par la passerelle.
 */
object Securite {
    const val SECURITE_ACTIVE = true
    const val PROTEGER_OCCUPANT = false
    const val HEURE_CALME_ACTIVE = false

    /** Configuration de la maison (ConfigMaison : maison.json). */
    private val maison: JSONObject = ConfigMaison.json
    private val conf: JSONObject = maison.optJSONObject("securite") ?: JSONObject()

    /**
     * Plafond gardé quand securite.plafond_volume est illisible (texte, vrai ou faux) : une faute de frappe ne
     * lève pas un plafond voulu. Même valeur que PLAFOND_SI_ILLISIBLE de poc/securite.py.
     */
    const val PLAFOND_SI_ILLISIBLE = 50.0

    /**
     * Plafond du volume en pourcentage (0 à 100) d'après la valeur de securite.plafond_volume, comme
     * plafond_configure de securite.py (cas communs « plafonds_configures ») : absente ou null, 100 (aucun
     * plafond), un nombre borné entre 0 et 100, autre chose [PLAFOND_SI_ILLISIBLE].
     */
    fun plafondConfigure(valeur: Any?): Double {
        if (valeur == null || valeur == JSONObject.NULL) return 100.0
        // Un booléen n'est pas un Number sur la JVM : vrai et faux sont illisibles, comme dans securite.py.
        val n = (valeur as? Number)?.toDouble() ?: return PLAFOND_SI_ILLISIBLE
        return if (n.isNaN()) PLAFOND_SI_ILLISIBLE else n.coerceIn(0.0, 100.0)
    }

    /** Volume le plus fort permis, de 0 à 1 (même calcul que VOLUME_MAX de poc/securite.py). 1 : aucun plafond. */
    val VOLUME_MAX: Double = plafondConfigure(conf.opt("plafond_volume")) / 100

    /** Vrai quand la configuration règle un plafond (moins de 100 %) : trait au bout des pistes, refus du volume_up. */
    val PLAFOND_ACTIF: Boolean get() = VOLUME_MAX < 1.0

    /** 0.5 donne « 50 », 0.725 donne « 72,5 » : un volume de 0 à 1 dit en pourcentage, comme securite.pourcentage. */
    fun pourcentage(niveau: Double): String {
        val p = Math.round(niveau * 1000) / 10.0
        return if (p == Math.floor(p)) p.toLong().toString() else p.toString().replace(".", ",")
    }
    private fun liste(cle: String): List<String> =
        conf.optJSONArray(cle)?.let { a -> (0 until a.length()).map { a.getString(it) } } ?: emptyList()

    /** Nom de l'occupant protégé, tel qu'il s'affiche dans les refus. */
    val NOM_OCCUPANT: String = conf.optString("nom_occupant").ifEmpty { "l'occupant" }
    private val MOTS_PROTEGES = liste("mots_proteges").map { it.lowercase() }
    private val MOTS_PIECES = liste("mots_pieces").map { it.lowercase() }.ifEmpty { MOTS_PROTEGES }
    private val ZONES_PROTEGEES = liste("zones_protegees").map { it.lowercase() }.toSet()
    private val ENTITES_PROTEGEES = liste("entites_protegees").map { it.lowercase() }.toSet()
    private val SON_SALON = liste("son_salon").toSet()
    private val SERVICES_SILENCIEUX = setOf(
        "media_player.turn_off", "media_player.media_pause", "media_player.media_stop",
        "media_player.volume_down", "media_player.volume_mute", "script.turn_off",
    )
    private val HEURE_CALME_DEBUT = conf.optJSONObject("heures_calmes")?.optInt("debut", 0) ?: 0
    private val HEURE_CALME_FIN = conf.optJSONObject("heures_calmes")?.optInt("fin", 9) ?: 9
    /** Plage dite dans le refus et l'écran Musique, tirée de heures_calmes (0.32.3, figée auparavant). */
    val PLAGE_CALME: String = listOf(HEURE_CALME_DEBUT, HEURE_CALME_FIN)
        .map { if (it % 24 == 0) "minuit" else "$it h" }.let { (de, a) -> "entre $de et $a" }
    private val FUSEAU: String = maison.optString("fuseau").ifEmpty { "UTC" }

    /** Règle 3 : ce que la personne reconnue peut piloter chez elle, et rien de plus. */
    private class Droits(val entites: Set<String>, val services: Set<String>)
    private val PERMIS_PERSONNE: Map<String, Droits> = conf.optJSONObject("permis_personne")?.let { o ->
        o.keys().asSequence().associate { cle ->
            val d = o.getJSONObject(cle)
            fun l(k: String) = d.optJSONArray(k)?.let { a -> (0 until a.length()).map { a.getString(it) } }?.toSet() ?: emptySet()
            cle.lowercase() to Droits(entites = l("entites"), services = l("services"))
        }
    } ?: emptyMap()

    /** « Camille », « camille », « Camille  » donnent « camille ». Vide si on ne sait pas qui parle. */
    fun personneNormalisee(personne: String?): String =
        Normalizer.normalize(personne ?: "", Normalizer.Form.NFKD).replace(Regex("[^\\p{ASCII}]"), "").trim().lowercase()

    /** Vrai si cette personne reconnue a le droit d'agir sur cette entité à elle (règle 3). */
    fun permisPour(personne: String?, service: String, entite: String): Boolean {
        val d = PERMIS_PERSONNE[personneNormalisee(personne)] ?: return false
        return service in d.services && entite in d.entites
    }

    /** Entités de l'occupant que cette personne reconnue peut piloter (règle 3), vide sinon. */
    fun entitesPermises(personne: String?): Set<String> = PERMIS_PERSONNE[personneNormalisee(personne)]?.entites ?: emptySet()

    private fun cibles(v: Any?): List<String> = when (v) {
        null -> emptyList()
        is JSONArray -> (0 until v.length()).map { v.optString(it).trim() }.filter { it.isNotEmpty() }
        else -> v.toString().split(",").map { it.trim() }.filter { it.isNotEmpty() }
    }

    /** Vrai pour ce qui appartient à l'occupant (entité, nom ou service). Public depuis la 0.16.0 :
     *  l'écran ambiant s'en sert pour ne rien afficher de lui, la règle elle-même ne change pas. */
    fun protege(e: String): Boolean {
        if (!PROTEGER_OCCUPANT) return false
        val m = e.lowercase()
        return m in ENTITES_PROTEGEES || MOTS_PROTEGES.any { it in m }
    }

    /** Pièce de l'occupant (identifiant ou nom de zone), pour l'écran ambiant (0.16.0). */
    fun zoneProtegee(z: String): Boolean = PROTEGER_OCCUPANT && (z.lowercase() in ZONES_PROTEGEES || protege(z))

    /** Nom de pièce lu dans HA qui appartient à l'occupant, tant que la règle 1 est active. */
    fun pieceProtegee(piece: String): Boolean = PROTEGER_OCCUPANT && MOTS_PIECES.any { it in piece.lowercase() }

    /**
     * Vrai si [heure] (0 à 23) tombe dans la plage calme [debut], [fin] exclue. Une plage qui passe minuit (début
     * après la fin, par exemple 22 h à 7 h) couvre la soirée et le début de matinée (26/10/2026, S-D1). Début égal
     * à la fin : plage vide. Même calcul que en_heure_calme de securite.py (cas communs « heures_calmes_nuit »).
     */
    fun enHeureCalme(heure: Int, debut: Int, fin: Int): Boolean =
        if (debut <= fin) heure in debut until fin else heure >= debut || heure < fin

    /**
     * Raison du refus, ou null si l'action est permise. [action] : {"service", "entity_id", ...}.
     * [personne] : qui parle d'après la reconnaissance de la tablette (règle 3), vide si on ne sait pas.
     * [volumeMax] : plafond du volume, celui de la configuration sauf dans les tests.
     * [plageCalme] : (début, fin) qui force la règle 2 sur cette plage, pour les tests seulement. Absent, la règle
     * suit HEURE_CALME_ACTIVE et heures_calmes de la configuration.
     */
    fun verifier(
        action: JSONObject, heure: Int = heureMaison(), personne: String = "", volumeMax: Double = VOLUME_MAX,
        plageCalme: Pair<Int, Int>? = null,
    ): String? {
        if (!SECURITE_ACTIVE) return null
        val service = action.optString("service")
        val entites = cibles(action.opt("entity_id"))
        val zones = cibles(action.opt("area_id"))
        if (action.has("device_id")) return "viser un appareil par son identifiant est interdit (sécurité)"
        // Un étage ou une étiquette désigne un groupe d'entités que la liste blanche par appareil ne voit pas (25/10/2026).
        if (action.has("floor_id") || action.has("label_id")) return "viser un étage ou une étiquette est interdit (sécurité)"
        // Avec un plafond, monter le son par pas passerait au-dessus : seul un volume précis (volume_set plafonné) passe.
        if (service == "media_player.volume_up" && volumeMax < 1.0) return refusVolumeUp(volumeMax)
        if (PROTEGER_OCCUPANT && entites.any { it.equals("all", true) }) return "viser toute la maison est interdit, cela toucherait la chambre de $NOM_OCCUPANT (sécurité)"
        if (PROTEGER_OCCUPANT && zones.any { it.lowercase() in ZONES_PROTEGEES || protege(it) }) return "je ne touche jamais aux pièces de $NOM_OCCUPANT (sécurité)"
        if (protege(service) || entites.any { protege(it) && !permisPour(personne, service, it) }) return "je ne touche jamais à ce qui appartient à $NOM_OCCUPANT (sécurité)"
        val calme = plageCalme ?: if (HEURE_CALME_ACTIVE) Pair(HEURE_CALME_DEBUT, HEURE_CALME_FIN) else null
        if (calme != null && enHeureCalme(heure, calme.first, calme.second)) {
            var silencieux = service in SERVICES_SILENCIEUX
            if (service == "media_player.volume_mute" && action.has("is_volume_muted") && !action.optBoolean("is_volume_muted")) silencieux = false
            if (!silencieux && (service in SON_SALON || entites.any { it in SON_SALON })) {
                return "pas de son dans le salon $PLAGE_CALME (sécurité)"
            }
        }
        return null
    }

    /** Refus d'un volume_up quand un plafond est réglé et qu'il n'a pas pu devenir un volume précis, comme refus_volume_up. */
    fun refusVolumeUp(volumeMax: Double = VOLUME_MAX): String =
        "le volume est plafonné à ${pourcentage(volumeMax)} %, je le règle seulement à une valeur précise (sécurité)"

    /** Niveau de volume (0 à 1) borné entre 0 et [volumeMax] (1 sans plafond). Un niveau illisible (NaN) donne 0. */
    fun plafonnerVolume(niveau: Double, volumeMax: Double = VOLUME_MAX): Double =
        if (niveau.isNaN()) 0.0 else niveau.coerceIn(0.0, volumeMax)

    /**
     * [donnees] d'un appel à [service] (« domaine.service »), volume plafonné : pour media_player.volume_set,
     * une copie dont volume_level est passé par [plafonnerVolume], sinon les mêmes données. Le plafond tient
     * quels que soient les drapeaux ci-dessus, comme dans securite.py.
     */
    fun plafonner(service: String, donnees: JSONObject, volumeMax: Double = VOLUME_MAX): JSONObject {
        if (service != "media_player.volume_set" || !donnees.has("volume_level")) return donnees
        return JSONObject(donnees.toString()).put("volume_level", plafonnerVolume(donnees.optDouble("volume_level", 0.0), volumeMax))
    }

    /**
     * Volume lu dans Home Assistant pour une enceinte (0.24.0), posé par Maison : sert à changer un
     * volume_up en volume_set borné par le plafond. Null quand il est inconnu.
     */
    @Volatile var volumeLu: (String) -> Double? = { null }

    /**
     * volume_up monterait par pas au-delà d'un plafond (revue de code de la 0.24.0) : il devient un
     * volume_set 5 points au-dessus du volume lu, borné par [volumeMax]. Volume inconnu : l'action reste un
     * volume_up, que [verifier] refuse quand un plafond est réglé et laisse passer sinon. Rend le service et les
     * données à envoyer.
     */
    fun monterSansDepasser(service: String, donnees: JSONObject, volumeMax: Double = VOLUME_MAX): Pair<String, JSONObject> {
        if (service != "media_player.volume_up") return service to donnees
        val id = donnees.opt("entity_id") as? String ?: return service to donnees
        val lu = volumeLu(id) ?: return service to donnees
        return "media_player.volume_set" to JSONObject(donnees.toString()).put("volume_level", plafonnerVolume(lu + 0.05, volumeMax))
    }

    /** Phrase qui parle de l'occupant : refusée avant tout LLM (banc du 13/10/2026 : Gemma allumait
     *  d'autres lumières à « allume la chambre de <occupant> »), comme securite.phrase_protegee.
     *  L'occupant reconnu peut parler de ses affaires : chaque action reste vérifiée par verifier(). */
    fun phraseProtegee(texte: String, personne: String = ""): String? {
        if (!SECURITE_ACTIVE) return null
        if (!PROTEGER_OCCUPANT || personneNormalisee(personne) in PERMIS_PERSONNE) return null
        val t = texte.lowercase()
        return if (MOTS_PROTEGES.any { it in t }) "je ne touche jamais à ce qui appartient à $NOM_OCCUPANT (sécurité)" else null
    }

    /** Heure de la maison, dans le fuseau de la configuration. */
    fun heureMaison(): Int = Calendar.getInstance(TimeZone.getTimeZone(FUSEAU)).get(Calendar.HOUR_OF_DAY)
}
