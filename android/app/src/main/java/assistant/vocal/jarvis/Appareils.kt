package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale

/**
 * Appareils de l'écran Maison connectée et de la bulle Maison (0.17.0), logique pure testée sur la
 * machine (AppareilsTest) : ce qu'on montre, ce qu'on compte, ce que fait un toucher ou un glissé.
 *
 * Rien de ce qui appartient à l'occupant protégé n'est montré ni compté (Securite.protege et zoneProtegee), sauf
 * ses lumières quand c'est lui que la tablette reconnaît (règle 3, Securite.entitesPermises). Les
 * lumières allumées se comptent en lampes : un groupe (attribut entity_id, comme « Chevets » ou
 * « Cuisine ») n'est pas compté quand ses lampes le sont déjà. C'était la cause des 10 lumières
 * annoncées un soir pour 8 lampes.
 */
object Appareils {

    data class Appareil(
        val id: String,
        val nom: String,
        val etat: String,
        /** Pièce : identifiant de zone HA (area_id) et nom affiché (area_name). */
        val zone: String,
        val piece: String,
        /** Luminosité de 0 à 100 quand la lumière est allumée, null sinon. */
        val luminosite: Int? = null,
        /** Volume de 0 à 1 pour un lecteur, null sinon. */
        val volume: Double? = null,
        val modes: List<String> = emptyList(),
        /** Lampes d'un groupe de lumières (attribut entity_id), vide sinon. */
        val membres: List<String> = emptyList(),
        val sources: List<String> = emptyList(),
        val source: String = "",
        val classe: String = "",
        val kelvinMin: Int = 0,
        val kelvinMax: Int = 0,
        /** Couleur d'une lumière allumée (rgb_color) et sa température en kelvins, pour le plan 3D (0.18.1). */
        val rgb: List<Int>? = null,
        val kelvin: Int? = null,
        /** Teinte en degrés et mode de couleur lus (color_mode), pour juger un réglage fin (0.34.0). */
        val teinte: Float? = null,
        val mode: String = "",
    ) {
        val domaine: String get() = id.substringBefore('.')
        val allume: Boolean get() = etat !in ETATS_ETEINTS
        val couleur: Boolean get() = modes.any { it in setOf("hs", "xy", "rgb", "rgbw", "rgbww") }
        val blanc: Boolean get() = "color_temp" in modes
        val reglable: Boolean get() = when (domaine) {
            "light" -> modes.any { it != "onoff" }
            "media_player" -> volume != null
            else -> false
        }
    }

    private val ETATS_ETEINTS = setOf("off", "idle", "standby", "unavailable", "unknown", "docked", "paused", "closed", "")

    /** Lecteurs montrés dans « Musique et télé » : la télé et les trois enceintes de la sortie du son. */
    val ENCEINTES: Set<String> = SortieSon.ENCEINTES.map { it.first }.toSet()

    const val FILTRE_TOUTES = "toutes"
    const val FILTRE_MEDIAS = "medias"
    const val FILTRE_ASPIRATEUR = "aspirateur"

    /** Règle 3 comprise : visible si rien de l'occupant protégé, ou si c'est une de ses lumières et lui qui est reconnu. */
    fun visible(a: Appareil, personne: String): Boolean {
        if (a.id in Securite.entitesPermises(personne)) return true
        if (Securite.protege(a.id) || Securite.protege(a.nom)) return false
        if (Securite.zoneProtegee(a.zone) || Securite.zoneProtegee(a.piece)) return false
        // Un groupe qui contient une lampe de l'occupant protégé trahirait son état.
        return a.membres.none { Securite.protege(it) }
    }

    /** Ce que l'écran Maison montre : visible, et pour les lecteurs, seulement la télé et les enceintes. */
    fun montres(tous: List<Appareil>, personne: String): List<Appareil> = tous.filter { a ->
        visible(a, personne) && a.etat != "unavailable" &&
            (a.domaine != "media_player" || a.id in ENCEINTES || a.classe == "tv")
    }

    /**
     * Lumières allumées comptées en lampes : un groupe n'est pas compté si une de ses lampes est dans la
     * liste (elle est comptée elle-même). [tous] : toutes les lumières lues, avant le filtre de l'occupant protégé.
     */
    fun lumieresAllumees(tous: List<Appareil>, personne: String): List<Appareil> {
        val ids = tous.map { it.id }.toSet()
        return tous.filter { a ->
            a.domaine == "light" && a.etat == "on" && visible(a, personne) && a.membres.none { it in ids }
        }
    }

    /** Pièces où des lampes sont allumées, dans l'ordre de la maison, sans doublon. */
    fun piecesAllumees(allumees: List<Appareil>): List<String> =
        allumees.map { it.piece }.filter { it.isNotBlank() }.distinct().sortedBy { ordrePiece(it) }

    /** Ordre des pièces de la maison, noms en minuscules (appareils.ordre_pieces de maison.json). */
    private val ORDRE_PIECES: List<String> = ConfigMaison.chaines(ConfigMaison.section("appareils"), "ordre_pieces").map { it.lowercase(Locale.FRANCE) }

    private fun ordrePiece(p: String): Int = ORDRE_PIECES.indexOf(p.lowercase(Locale.FRANCE)).let { if (it < 0) ORDRE_PIECES.size else it }

    /** Filtres de l'écran : Toutes, les pièces qui ont des appareils, Musique et télé, Aspirateur. */
    fun filtres(montres: List<Appareil>): List<Pair<String, String>> {
        val sortie = mutableListOf(FILTRE_TOUTES to "Toutes")
        val pieces = montres.filter { it.domaine != "media_player" && it.domaine != "vacuum" && it.piece.isNotBlank() }
            .map { it.zone to it.piece }.distinct().sortedBy { ordrePiece(it.second) }
        sortie.addAll(pieces)
        if (montres.any { it.domaine == "media_player" }) sortie.add(FILTRE_MEDIAS to "Musique et télé")
        if (montres.any { it.domaine == "vacuum" }) sortie.add(FILTRE_ASPIRATEUR to "Aspirateur")
        return sortie
    }

    fun filtrer(montres: List<Appareil>, filtre: String): List<Appareil> = when (filtre) {
        FILTRE_TOUTES -> montres
        FILTRE_MEDIAS -> montres.filter { it.domaine == "media_player" }
        FILTRE_ASPIRATEUR -> montres.filter { it.domaine == "vacuum" }
        else -> montres.filter { it.zone == filtre && it.domaine != "media_player" && it.domaine != "vacuum" }
    }.sortedWith(compareBy({ ordreDomaine(it.domaine) }, { ordrePiece(it.piece) }, { it.membres.isEmpty() }, { it.nom.lowercase(Locale.FRANCE) }))

    private fun ordreDomaine(d: String) = listOf("light", "fan", "cover", "climate", "media_player", "vacuum").indexOf(d).let { if (it < 0) 9 else it }

    /** Tuile de l'écran Maison (0.17.2) : un appareil, et pour un groupe de lampes, ses lampes du sous-niveau. */
    data class Tuile(val appareil: Appareil, val lampes: List<Appareil> = emptyList()) {
        val groupe: Boolean get() = appareil.domaine == "light" && appareil.membres.isNotEmpty()
    }

    /**
     * Groupes de lampes (0.17.2) : un groupe de la liste devient une seule tuile qui pilote tout le groupe,
     * ses lampes passent dans son sous-niveau au lieu d'avoir chacune leur tuile (« Cuisine » avec
     * Cuisine 1 et 2, « Chevets » avec les deux chevets). Une lampe dont aucun groupe n'est dans la
     * liste (autre pièce filtrée, groupe caché) garde sa tuile. L'ordre de [liste] est gardé. Le décompte
     * de la bulle n'en dépend pas (lumieresAllumees).
     */
    fun regrouper(liste: List<Appareil>): List<Tuile> {
        val groupes = liste.filter { it.domaine == "light" && it.membres.isNotEmpty() }
        val dansUnGroupe = groupes.flatMap { g -> g.membres.filter { it != g.id } }.toSet()
        return liste.filter { it.id !in dansUnGroupe || it in groupes }.map { a ->
            if (a in groupes) Tuile(a, liste.filter { it.id != a.id && it.id in a.membres }) else Tuile(a)
        }
    }

    /** Libellé du nombre de lampes d'un groupe : « 1 lampe », « 2 lampes ». */
    fun nombreLampes(n: Int): String = if (n <= 1) "$n lampe" else "$n lampes"

    /** Commande à envoyer : service « domaine.service » et corps de l'appel. */
    data class Commande(val service: String, val corps: JSONObject) {
        /** Ce que vérifie Securite.kt : le corps et le service. */
        fun verification(): JSONObject = JSONObject(corps.toString()).put("service", service)
    }

    /** Toucher une tuile : allumer ou éteindre (lecture ou pause pour une enceinte, départ ou retour pour l'aspirateur). */
    fun basculer(a: Appareil): Commande? {
        val corps = JSONObject().put("entity_id", a.id)
        return when (a.domaine) {
            "light", "fan", "switch" -> Commande("${a.domaine}.${if (a.etat == "on") "turn_off" else "turn_on"}", corps)
            "cover" -> Commande("cover.${if (a.etat == "open" || a.etat == "opening") "close_cover" else "open_cover"}", corps)
            "media_player" -> when {
                a.id in ENCEINTES -> Commande("media_player.${if (a.etat == "playing") "media_pause" else "media_play"}", corps)
                // Télé : allumée dans tout état autre qu'éteinte ou en veille.
                else -> Commande("media_player.${if (a.etat == "off" || a.etat == "standby") "turn_on" else "turn_off"}", corps)
            }
            "vacuum" -> Commande("vacuum.${if (a.etat == "cleaning") "return_to_base" else "start"}", corps)
            else -> null
        }
    }

    /** Glisser sur la tuile : luminosité ou volume, [fraction] de 0 à 1. */
    fun regler(a: Appareil, fraction: Float): Commande? {
        val f = fraction.coerceIn(0f, 1f)
        val corps = JSONObject().put("entity_id", a.id)
        return when {
            a.domaine == "light" && a.reglable -> {
                val pct = Math.round(f * 100)
                if (pct <= 0) Commande("light.turn_off", corps) else Commande("light.turn_on", corps.put("brightness_pct", pct))
            }
            // Volume borné par le plafond réglé (Securite.VOLUME_MAX, aucun par défaut) : au-delà, il reste au plafond.
            a.domaine == "media_player" && a.volume != null ->
                Commande("media_player.volume_set", corps.put("volume_level", Securite.plafonnerVolume(Math.round(f * 100) / 100.0)))
            else -> null
        }
    }

    /** Appui long, lumière en couleur : une couleur [r], [g], [b]. */
    fun couleur(a: Appareil, r: Int, g: Int, b: Int): Commande =
        Commande("light.turn_on", JSONObject().put("entity_id", a.id).put("rgb_color", JSONArray(listOf(r, g, b))))

    /** Couleur nommée du volet : teinte en degrés à pleine saturation, la luminosité reste celle de la lampe. */
    fun teinte(a: Appareil, degres: Int): Commande =
        Commande("light.turn_on", JSONObject().put("entity_id", a.id).put("hs_color", JSONArray(listOf(degres, 100))))

    /** Appui long, lumière blanche : température en kelvins, bornée à ce que la lampe accepte. */
    fun blanc(a: Appareil, kelvin: Int): Commande {
        val k = if (a.kelvinMin > 0 && a.kelvinMax >= a.kelvinMin) kelvin.coerceIn(a.kelvinMin, a.kelvinMax) else kelvin
        return Commande("light.turn_on", JSONObject().put("entity_id", a.id).put("color_temp_kelvin", k))
    }

    /** Appui long, télé : une source. */
    fun source(a: Appareil, source: String): Commande =
        Commande("media_player.select_source", JSONObject().put("entity_id", a.id).put("source", source))

    /** Pièces communes : tout sauf les chambres et les salles de bain. */
    fun commune(zone: String): Boolean = zone.isNotBlank() && !zone.startsWith("chambre") && !zone.startsWith("salle_de_bain")

    /** « Tout éteindre (pièces communes) » : les lumières allumées des pièces communes, en un seul appel. */
    fun toutEteindre(montres: List<Appareil>): Commande? {
        val ids = montres.filter { it.domaine == "light" && it.etat == "on" && commune(it.zone) }.map { it.id }
        if (ids.isEmpty()) return null
        return Commande("light.turn_off", JSONObject().put("entity_id", JSONArray(ids)))
    }

    /** État lisible d'une tuile : « allumée à 40 % », « éteinte », « volume 30 % », « en lecture »... */
    fun etatLisible(a: Appareil): String {
        val f = a.domaine == "light" || a.domaine == "climate"
        return when (a.domaine) {
            "light" -> if (a.etat == "on") (a.luminosite?.let { "allumée à $it %" } ?: "allumée") else "éteinte"
            "media_player" -> when (a.etat) {
                "playing" -> "en lecture" + (a.volume?.let { ", volume ${Math.round(it * 100)} %" } ?: "")
                "paused" -> "en pause"
                "off", "standby" -> "éteinte".takeIf { a.classe == "tv" } ?: "éteint"
                "idle", "on" -> if (a.classe == "tv") "allumée" else "en attente"
                else -> a.etat
            }
            "vacuum" -> when (a.etat) {
                "cleaning" -> "en train de nettoyer"
                "docked" -> "sur sa base"
                "returning" -> "retourne à sa base"
                "error" -> "en erreur"
                "idle" -> "à l'arrêt"
                "paused" -> "en pause"
                else -> a.etat
            }
            "cover" -> when (a.etat) { "open" -> "ouvert"; "closed" -> "fermé"; else -> a.etat }
            else -> if (a.etat == "on") (if (f) "allumée" else "allumé") else if (a.etat == "off") (if (f) "éteinte" else "éteint") else a.etat
        }
    }

    /** Résumé en tête de l'écran : lampes allumées et leurs pièces. */
    fun resume(allumees: List<Appareil>): String {
        val n = allumees.size
        if (n == 0) return "Toutes les lumières sont éteintes"
        val pieces = piecesAllumees(allumees)
        val debut = if (n == 1) "1 lumière allumée" else "$n lumières allumées"
        return if (pieces.isEmpty()) debut else "$debut : " + pieces.joinToString(", ")
    }

    /** Lecture d'un appareil rendu par le modèle de Maison.lireAppareils. */
    fun lire(o: JSONObject): Appareil? {
        val id = o.optString("id")
        if (id.isEmpty()) return null
        fun liste(nom: String) = o.optJSONArray(nom)?.let { a -> (0 until a.length()).map { a.optString(it) }.filter { it.isNotEmpty() } } ?: emptyList()
        val lum = if (o.isNull("lum") || !o.has("lum")) null else Math.round(o.optDouble("lum", 0.0) / 5.55).toInt().coerceIn(0, 100)
        val volume = if (o.isNull("volume") || !o.has("volume")) null else o.optDouble("volume", 0.0)
        // Les enceintes gardent leur nom court (Salon, Cuisine, Bureau), comme dans l'écran Musique.
        val nom = if (id in ENCEINTES) SortieSon.nomCourt(id) else o.optString("nom").ifBlank { Maison.nomBrut(id) }
        val rgb = o.optJSONArray("rgb")?.let { a -> (0 until a.length()).map { a.optInt(it) } }?.takeIf { it.size == 3 }
        val kelvin = if (o.isNull("kelvin") || !o.has("kelvin")) null else o.optInt("kelvin").takeIf { it > 0 }
        val hs = o.optJSONArray("hs")?.takeIf { it.length() >= 1 && !it.isNull(0) }?.optDouble(0)?.toFloat()
        val teinte = hs ?: rgb?.let { ReglageLampe.teinteDeRgb(it) }
        return Appareil(
            id, nom, o.optString("etat"), o.optString("zone"), o.optString("piece"),
            lum, volume, liste("modes"), liste("membres"), liste("sources"), o.optString("source"), o.optString("classe"),
            o.optInt("kmin", 0), o.optInt("kmax", 0), rgb, kelvin, teinte, if (o.isNull("mode")) "" else o.optString("mode"),
        )
    }
}
