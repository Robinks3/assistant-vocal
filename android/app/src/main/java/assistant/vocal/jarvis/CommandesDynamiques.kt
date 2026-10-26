package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject

/**
 * Actions « dynamiques » de commandes.yaml (lot S-L4, appli 0.41.0) : le service dépend de l'état d'un appareil, lu
 * juste avant d'agir. Pendant exact de poc/commandes_dynamiques.py, avec les mêmes cas
 * (poc/tests/cas_dynamique.json, CommandesDynamiquesTest). Une action dynamique se résout en actions ordinaires, que la
 * sécurité en dur contrôle ensuite comme toutes les autres.
 *
 *  - `selon_etat` : « monte » vise le volume si la télé est allumée, la lumière sinon. Champs entite, etats, alors,
 *    sinon (facultatif), reponse_vide. L'entité dans l'un des `etats` donne `alors`, tout autre état (éteinte,
 *    indisponible, illisible) donne `sinon`.
 *  - `kelvin_pas` : « plus chaud », « plus froid ». Champs entity_id (une entité, une liste ou une chaîne séparée par des
 *    virgules), pas (kelvins, négatif pour chaud), reponse_vide. Chaque lampe allumée en blanc reçoit `light.turn_on` avec
 *    le kelvin décalé du pas, borné par ses min_color_temp_kelvin et max_color_temp_kelvin. Une lampe éteinte, en couleur
 *    ou déjà à la borne est laissée telle quelle.
 */
object CommandesDynamiques {
    const val KELVIN_MIN_DEFAUT = 2700
    const val KELVIN_MAX_DEFAUT = 6500
    const val REPONSE_VIDE_DEFAUT = "Je n'ai rien à régler pour l'instant."

    /** Actions ordinaires obtenues, et ce qu'il faut dire s'il n'en reste aucune alors qu'une action dynamique existait. */
    class Resolution(val actions: List<JSONObject>, val vide: String?)

    fun estDynamique(a: JSONObject): Boolean = a.has("dynamique")

    private fun enListe(valeur: Any?): List<Any> = when {
        valeur == null || valeur == JSONObject.NULL -> emptyList()
        valeur is JSONArray -> (0 until valeur.length()).map { valeur.get(it) }
        else -> listOf(valeur)
    }

    /** Entités visées, données en une chaîne séparée par des virgules ou en liste. */
    private fun cibles(valeur: Any?): List<String> =
        if (valeur is String) valeur.split(",").map { it.trim() }.filter { it.isNotEmpty() }
        else enListe(valeur).filterIsInstance<String>()

    /** Entités dont l'état est nécessaire pour résoudre ces actions, sans doublon et dans l'ordre. */
    fun entitesLues(actions: List<JSONObject>): List<String> {
        val lues = ArrayList<String>()
        for (a in actions) {
            if (!estDynamique(a)) continue
            val candidates = when (a.optString("dynamique")) {
                "selon_etat" -> listOf(a.opt("entite"))
                "kelvin_pas" -> cibles(a.opt("entity_id"))
                else -> emptyList()
            }
            for (e in candidates) if (e is String && e.isNotEmpty() && e !in lues) lues.add(e)
        }
        return lues
    }

    /** Un nombre lu dans les attributs de HA (nombre ou texte), ou null. */
    private fun entier(valeur: Any?): Int? = when (valeur) {
        is Boolean -> null
        is Number -> Math.round(valeur.toDouble()).toInt()
        is String -> valeur.toDoubleOrNull()?.let { Math.round(it).toInt() }
        else -> null
    }

    /** État écrit dans la liste `etats` : un booléen (YAML 1.1 lit `on` ainsi) se ramène à son nom d'état. */
    private fun nomEtat(valeur: Any?): String = when (valeur) {
        true -> "on"
        false -> "off"
        else -> valeur.toString()
    }

    private fun kelvinPas(action: JSONObject, etats: Map<String, JSONObject?>): List<JSONObject> {
        val pas = entier(action.opt("pas")) ?: 0
        val actions = ArrayList<JSONObject>()
        for (e in cibles(action.opt("entity_id"))) {
            val etat = etats[e] ?: continue
            if (etat.opt("state") != "on") continue
            val attributs = etat.optJSONObject("attributes") ?: JSONObject()
            val kelvin = entier(attributs.opt("color_temp_kelvin")) ?: continue // lampe en couleur : on ne la touche pas
            val kmin = entier(attributs.opt("min_color_temp_kelvin"))?.takeIf { it != 0 } ?: KELVIN_MIN_DEFAUT
            val kmax = entier(attributs.opt("max_color_temp_kelvin"))?.takeIf { it != 0 } ?: maxOf(KELVIN_MAX_DEFAUT, kmin + 1)
            val nouveau = maxOf(kmin, minOf(kmax, kelvin + pas))
            if (nouveau != kelvin) {
                actions.add(JSONObject().put("service", "light.turn_on").put("entity_id", e).put("color_temp_kelvin", nouveau))
            }
        }
        return actions
    }

    /** Actions ordinaires qui répondent à une action dynamique, d'après `etats` (entité vers objet d'état de HA, null si illisible). */
    private fun resoudre(action: JSONObject, etats: Map<String, JSONObject?>): List<JSONObject> =
        when (action.optString("dynamique")) {
            "selon_etat" -> {
                val courant = etats[action.optString("entite")]?.opt("state")?.toString()
                val permis = enListe(action.opt("etats")).map { nomEtat(it) }
                val choisies = if (courant != null && courant in permis) action.opt("alors") else action.opt("sinon")
                enListe(choisies).filterIsInstance<JSONObject>().map { JSONObject(it.toString()) }
            }
            "kelvin_pas" -> kelvinPas(action, etats)
            else -> emptyList()
        }

    /**
     * Remplace chaque action dynamique de la liste par ses actions ordinaires, les autres passent telles quelles.
     * `vide` : la réponse à dire si la liste est vide alors qu'elle contenait une action dynamique, sinon null.
     */
    fun resoudreToutes(actions: List<JSONObject>, etats: Map<String, JSONObject?>): Resolution {
        val sortie = ArrayList<JSONObject>()
        var vide: String? = null
        var dynamique = false
        for (a in actions) {
            if (estDynamique(a)) {
                dynamique = true
                vide = a.optString("reponse_vide").ifEmpty { REPONSE_VIDE_DEFAUT }
                sortie.addAll(resoudre(a, etats))
            } else {
                sortie.add(a)
            }
        }
        return Resolution(sortie, if (dynamique && sortie.isEmpty()) vide else null)
    }
}
