package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.roundToInt

/** Traduction d'un appareil lu dans Home Assistant vers l'état que lit la vue 3D (0.17.4). */
internal object Maison3d {

    /**
     * Entités de Home Assistant que la vue 3D appelle autrement (0.42.0), `reglages.vue3d.correspondances` de
     * maison.json : `{"media_player.tele_famille": "media_player.tele_salon"}`. Vide quand la configuration n'en dit rien.
     */
    val CORRESPONDANCES: Map<String, String> by lazy { lireCorrespondances(ConfigMaison.section("reglages")) }

    /** Lit `vue3d.correspondances` dans la section `reglages` : paires de chaînes non vides, le reste est ignoré. */
    fun lireCorrespondances(reglages: JSONObject): Map<String, String> {
        val o = reglages.optJSONObject("vue3d")?.optJSONObject("correspondances") ?: return emptyMap()
        val r = LinkedHashMap<String, String>()
        for (cle in o.keys()) {
            val valeur = o.optString(cle, "").trim()
            if (cle.isNotBlank() && valeur.isNotEmpty() && !cle.startsWith("_")) r[cle.trim()] = valeur
        }
        return r
    }

    /**
     * `{"state": "on", "attributes": {"brightness": 0..255, "rgb_color" ou "color_temp_kelvin"}}` : ce que lit la page.
     * Une lampe en mode `color_temp` envoie sa température (le rgb que HA en déduit est approché), les autres leur rgb.
     * Une lampe indisponible ou inconnue part telle quelle : la page la montre éteinte, sans couleur périmée.
     */
    fun etatHa(a: Appareils.Appareil): JSONObject {
        val etat = a.etat.trim().lowercase()
        if (etat == "unavailable" || etat == "unknown") return JSONObject().put("state", etat).put("attributes", JSONObject())
        val attributs = JSONObject()
        val lum = a.luminosite
        if (a.allume && lum != null) attributs.put("brightness", (lum.coerceIn(0, 100) * 2.55).roundToInt())
        // Couleur réelle de la lampe (0.18.1) : la page n'utilise sa lumière chaude par défaut qu'à défaut.
        if (a.allume) {
            val rgb = a.rgb?.takeIf { it.size == 3 }?.let { c -> JSONArray(c.map { it.coerceIn(0, 255) }) }
            val kelvin = a.kelvin?.takeIf { it > 0 }?.coerceIn(Maison3dPont.KELVIN_MIN, Maison3dPont.KELVIN_MAX)
            when {
                kelvin != null && (a.mode == "color_temp" || rgb == null) -> attributs.put("color_temp_kelvin", kelvin)
                rgb != null -> attributs.put("rgb_color", rgb)
            }
        }
        return JSONObject().put("state", if (a.allume) "on" else "off").put("attributes", attributs)
    }

    /** État à envoyer à la page pour cet appareil : lampe, télé ou enceinte. Null pour tout autre domaine. */
    fun etat3d(a: Appareils.Appareil): JSONObject? = when (a.domaine) {
        "light" -> etatHa(a)
        "media_player" -> etatMedia(a)
        else -> null
    }

    /** État que lit la page pour un lecteur multimédia (télé, enceinte) : `state` et `volume_level`, rien d'autre. */
    fun etatMedia(a: Appareils.Appareil): JSONObject =
        Maison3dPont.etatMedia(a.etat, a.volume)
}
