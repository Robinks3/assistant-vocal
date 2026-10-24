package assistant.vocal.jarvis

import org.json.JSONObject
import kotlin.math.roundToInt

/** Traduction d'un appareil lu dans Home Assistant vers l'état que lit la vue 3D (0.17.4). */
internal object Maison3d {
    /** `{"state": "on", "attributes": {"brightness": 0..255, "rgb_color" ou "color_temp_kelvin"}}` : ce que lit la page. */
    fun etatHa(a: Appareils.Appareil): JSONObject {
        val attributs = JSONObject()
        val lum = a.luminosite
        if (a.allume && lum != null) attributs.put("brightness", (lum.coerceIn(0, 100) * 5.55).roundToInt())
        // Couleur réelle de la lampe (0.18.1) : la page n'utilise sa lumière chaude par défaut qu'à défaut.
        if (a.allume) a.rgb?.let { attributs.put("rgb_color", org.json.JSONArray(it)) }
        if (a.allume && a.rgb == null) a.kelvin?.let { attributs.put("color_temp_kelvin", it) }
        return JSONObject().put("state", if (a.allume) "on" else "off").put("attributes", attributs)
    }
}
