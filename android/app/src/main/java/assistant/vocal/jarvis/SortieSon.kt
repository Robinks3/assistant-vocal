package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject

/**
 * Sortie du son de l'écran Musique (0.17.0), logique pure testée sur la machine (SortieSonTest).
 *
 * Trois enceintes de Music Assistant, vérifiées par la passerelle (/api/states, 22/10/2026) : le Salon
 * et ses voisines (liste appareils.sortie_son de la configuration de la maison, par exemple le Salon, la
 * Cuisine et le Bureau). Une seule musique synchronisée : l'enceinte qui joue mène le groupe
 * (attribut group_members), cocher une autre enceinte l'y ajoute (media_player.join), la décocher l'en
 * retire (media_player.unjoin). Le regroupement n'est proposé que si l'enceinte l'annonce (fonction
 * GROUPING de supported_features) : le 22/10, le Bureau ne l'annonçait pas.
 *
 * Toute commande est vérifiée par Securite.verifier avant l'envoi, avec le meneur et l'enceinte visée
 * comme cibles : pas de son au salon de minuit à 9 h (la Cuisine fait partie des enceintes du salon).
 */
object SortieSon {

    /** Enceinte lue dans Home Assistant : état, volume (0 à 1), membres du groupe, regroupement possible. */
    data class Enceinte(
        val id: String,
        val nom: String,
        val etat: String,
        val volume: Double,
        val membres: Set<String>,
        val regroupable: Boolean,
    ) {
        val active: Boolean get() = etat == "playing" || etat == "paused" || etat == "buffering"
        /** Enceinte injoignable (débranchée, hors Wi-Fi) : un join vers elle échoue sans rien dire (25/10/2026). */
        val horsLigne: Boolean get() = etat == "unavailable" || etat == "unknown"
    }

    /** Service media_player à appeler : [entite] et, pour join, les enceintes à ajouter. */
    data class Commande(val service: String, val entite: String, val membres: List<String> = emptyList()) {
        /** Corps envoyé à /api/services/media_player/... */
        fun corps(): JSONObject = JSONObject().put("entity_id", entite).apply {
            if (membres.isNotEmpty()) put("group_members", JSONArray(membres))
        }

        /** Ce que vérifie la sécurité : toutes les enceintes touchées sont des cibles. */
        fun verification(): JSONObject =
            JSONObject().put("service", "media_player.$service").put("entity_id", JSONArray(listOf(entite) + membres))
    }

    /** Décision après un toucher sur une case : une commande, ou un message pour l'utilisateur, ou rien. */
    data class Decision(val commande: Commande?, val message: String?)

    /** Les enceintes, dans l'ordre de l'écran, et leur nom court (appareils.sortie_son de maison.json). */
    val ENCEINTES: List<Pair<String, String>> = ConfigMaison.section("appareils").optJSONArray("sortie_son")?.let { a ->
        (0 until a.length()).mapNotNull { i -> a.optJSONObject(i)?.let { it.optString("entite") to it.optString("nom") } }
    } ?: emptyList()

    /** MediaPlayerEntityFeature.GROUPING de Home Assistant. */
    const val FONCTION_GROUPE = 524288

    fun regroupable(fonctions: Long): Boolean = fonctions and FONCTION_GROUPE.toLong() != 0L

    fun nomCourt(id: String): String = ENCEINTES.firstOrNull { it.first == id }?.second ?: id

    /**
     * Enceinte qui mène la musique : celle qui joue avec le plus grand groupe, sinon celle en pause.
     * Null si aucune des trois ne joue.
     */
    fun meneur(e: List<Enceinte>): Enceinte? {
        fun taille(x: Enceinte) = x.membres.count { m -> m != x.id && e.any { it.id == m } }
        return e.filter { it.etat == "playing" || it.etat == "buffering" }.maxByOrNull(::taille)
            ?: e.filter { it.etat == "paused" }.maxByOrNull(::taille)
    }

    /** Enceintes qui font entendre la musique : le meneur et les membres de son groupe. */
    fun cochees(e: List<Enceinte>): Set<String> {
        val m = meneur(e) ?: return emptySet()
        val ids = e.map { it.id }.toSet()
        return setOf(m.id) + m.membres.filter { it in ids }
    }

    /** On coche ([cocher] vrai) ou décoche l'enceinte [id]. */
    fun basculer(e: List<Enceinte>, id: String, cocher: Boolean): Decision {
        val cible = e.firstOrNull { it.id == id } ?: return Decision(null, "Enceinte introuvable dans Home Assistant.")
        val actuelles = cochees(e)
        val m = meneur(e)
        if (cocher) {
            if (id in actuelles) return Decision(null, null)
            if (cible.horsLigne) return Decision(null, horsLigne(id))
            if (m == null) return Decision(null, "Aucune musique sur ces enceintes : lance d'abord une musique.")
            if (!m.regroupable) return Decision(null, "${nomCourt(m.id)} ne se regroupe pas avec les autres enceintes.")
            if (!cible.regroupable) return Decision(null, "${nomCourt(id)} ne se regroupe pas avec les autres enceintes.")
            return Decision(Commande("join", m.id, listOf(id)), null)
        }
        if (id !in actuelles || m == null) return Decision(null, null)
        if (id == m.id) {
            // Retirer le meneur dissoudrait le groupe d'une façon qu'on ne maîtrise pas (Music Assistant).
            if (actuelles.size > 1) {
                return Decision(null, "${nomCourt(id)} mène la musique : décoche d'abord les autres enceintes, ou mets en pause.")
            }
            return Decision(Commande("media_pause", id), null)
        }
        return Decision(Commande("unjoin", id), null)
    }

    /** Message d'une enceinte hors ligne, au féminin comme « enceinte ». */
    fun horsLigne(id: String): String = "${nomCourt(id)} est hors ligne : vérifie qu'elle est branchée et sur le Wi-Fi."

    /** Raison du refus de la sécurité, ou null : à appeler avant tout envoi. */
    fun refus(c: Commande, heure: Int = Securite.heureMaison(), personne: String = ""): String? =
        Securite.verifier(c.verification(), heure, personne)
}
