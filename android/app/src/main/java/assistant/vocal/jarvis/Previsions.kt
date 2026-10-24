package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.OffsetDateTime
import kotlin.math.roundToInt

/**
 * Lecture des prévisions météo (0.18.0), logique pure testée sur la machine (PrevisionsTest), pour le panneau
 * Météo de la tablette (0.20.0, EcranMeteo) et la phrase de pluie de l'accueil.
 *
 * Depuis Home Assistant 2023.9, les prévisions ne sont plus dans les attributs de l'entité weather : on les
 * demande au service `weather.get_forecasts` (`type` hourly, puis daily ou twice_daily selon ce que l'entité
 * annonce dans `supported_features`), réponse `{"service_response": {entité: {"forecast": [...]}}}`. La
 * météo du moment vient des attributs de l'entité (`/api/states/weather...`), le soleil de `sun.sun`.
 */
object Previsions {

    data class Prevision(
        /** Instant de la prévision, en millisecondes depuis 1970. */
        val instant: Long,
        val condition: String,
        val temperature: Double?,
        /** Probabilité de pluie en %, si l'intégration la donne. */
        val pluie: Int? = null,
        /** Hauteur de pluie prévue en mm. */
        val millimetres: Double? = null,
        /** Minimale du jour (prévisions par jour). */
        val basse: Double? = null,
        /** Demi-journée de jour ou de nuit (prévisions deux fois par jour). */
        val deJour: Boolean? = null,
        val vent: Double? = null,
        /** Direction d'où vient le vent, en degrés (0 : du nord). */
        val direction: Double? = null,
        val rafales: Double? = null,
        val humidite: Int? = null,
    )

    /** Météo du moment, d'après les attributs de l'entité weather, avec les unités qu'elle annonce. */
    data class Actuel(
        val condition: String,
        val temperature: Double?,
        val ressenti: Double? = null,
        val humidite: Int? = null,
        val pression: Double? = null,
        val vent: Double? = null,
        val direction: Double? = null,
        val rafales: Double? = null,
        val uv: Double? = null,
        val rosee: Double? = null,
        val visibilite: Double? = null,
        val nuages: Int? = null,
        val uniteVent: String = "km/h",
        val unitePression: String = "hPa",
        val uniteVisibilite: String = "km",
        /** Nom de l'entité (friendly_name), pour le titre du panneau (0.20.0). */
        val nom: String = "",
    )

    /** Prochain lever et prochain coucher du soleil (sun.sun), en millisecondes depuis 1970. */
    data class Soleil(val lever: Long?, val coucher: Long?)

    /**
     * Résultat d'une lecture. En cas d'échec d'un service, [erreur] (message lisible) avec le code et la
     * réponse exacte de la passerelle, les données lues par ailleurs restant montrées.
     */
    data class Lecture(
        val horaire: List<Prevision> = emptyList(),
        val journalier: List<Prevision> = emptyList(),
        /** Type des prévisions de jours : daily, ou twice_daily en repli. */
        val typeJours: String = PAR_JOUR,
        val actuel: Actuel? = null,
        val soleil: Soleil? = null,
        val erreur: String = "",
        val code: Int = 200,
        val reponse: String = "",
    )

    const val HORAIRE = "hourly"
    const val DEUX_PAR_JOUR = "twice_daily"
    const val PAR_JOUR = "daily"

    /** Fonctions annoncées par l'entité (WeatherEntityFeature : 1 par jour, 2 horaire, 4 deux par jour). */
    fun horaire(fonctions: Long): Boolean = fonctions and 2L != 0L || fonctions == 0L

    /** Type des jours à demander : par jour, sinon deux par jour, sinon rien. */
    fun typeJours(fonctions: Long): String? = when {
        fonctions == 0L || fonctions and 1L != 0L -> PAR_JOUR
        fonctions and 4L != 0L -> DEUX_PAR_JOUR
        else -> null
    }

    /** Chemin REST du service avec sa réponse, et son corps. */
    const val CHEMIN = "/api/services/weather/get_forecasts?return_response"

    fun corps(entite: String, type: String): JSONObject = JSONObject().put("entity_id", entite).put("type", type)

    /**
     * Prévisions de [entite] dans la réponse du service. Accepte la réponse REST complète
     * (`service_response`), la seule réponse du service, ou une liste brute (ancien attribut `forecast`).
     * Les éléments sans date lisible sont écartés, le reste est trié dans le temps.
     */
    fun lire(corps: String, entite: String): List<Prevision> {
        val t = corps.trim()
        if (t.isEmpty()) return emptyList()
        return try {
            if (t.startsWith("[")) return lireListe(JSONArray(t))
            val o = JSONObject(t)
            val reponse = o.optJSONObject("service_response") ?: o
            val bloc = reponse.optJSONObject(entite) ?: reponse.keys().asSequence().mapNotNull { reponse.optJSONObject(it) }
                .firstOrNull { it.has("forecast") } ?: reponse
            lireListe(bloc.optJSONArray("forecast") ?: JSONArray())
        } catch (_: Exception) {
            emptyList()
        }
    }

    fun lireListe(a: JSONArray): List<Prevision> {
        val sortie = ArrayList<Prevision>()
        for (i in 0 until a.length()) {
            val o = a.optJSONObject(i) ?: continue
            val instant = instant(o.optString("datetime")) ?: continue
            sortie.add(
                Prevision(
                    instant, o.optString("condition"), nombre(o, "temperature"),
                    nombre(o, "precipitation_probability")?.roundToInt(), nombre(o, "precipitation"),
                    nombre(o, "templow"), if (o.has("is_daytime") && !o.isNull("is_daytime")) o.optBoolean("is_daytime") else null,
                    nombre(o, "wind_speed"), direction(o.opt("wind_bearing")), nombre(o, "wind_gust_speed"),
                    nombre(o, "humidity")?.roundToInt(),
                )
            )
        }
        return sortie.sortedBy { it.instant }
    }

    /** Météo du moment d'après l'état de l'entité weather (`/api/states/...`), ou null si illisible. */
    fun lireActuel(corps: String): Actuel? = try {
        val o = JSONObject(corps)
        val a = o.optJSONObject("attributes") ?: JSONObject()
        Actuel(
            o.optString("state"), nombre(a, "temperature"), nombre(a, "apparent_temperature"),
            nombre(a, "humidity")?.roundToInt(), nombre(a, "pressure"), nombre(a, "wind_speed"),
            direction(a.opt("wind_bearing")), nombre(a, "wind_gust_speed"), nombre(a, "uv_index"),
            nombre(a, "dew_point"), nombre(a, "visibility"), nombre(a, "cloud_coverage")?.roundToInt(),
            a.optString("wind_speed_unit").ifBlank { "km/h" }, a.optString("pressure_unit").ifBlank { "hPa" },
            a.optString("visibility_unit").ifBlank { "km" }, a.optString("friendly_name"),
        )
    } catch (_: Exception) {
        null
    }

    /** Ancien attribut `forecast` de l'entité, pour les intégrations qui le gardent. */
    fun lireAttribut(corps: String): List<Prevision> = try {
        JSONObject(corps).optJSONObject("attributes")?.optJSONArray("forecast")?.let { lireListe(it) } ?: emptyList()
    } catch (_: Exception) {
        emptyList()
    }

    /** Soleil d'un état sun.sun déjà lu (0.19.0, mode Selon l'heure de la palette), ou null. */
    fun soleilEtat(etat: String, attributs: JSONObject): Etat.Soleil? {
        if (etat != "above_horizon" && etat != "below_horizon") return null
        return Etat.Soleil(etat == "above_horizon", instant(attributs.optString("next_rising")), instant(attributs.optString("next_setting")), System.currentTimeMillis())
    }

    fun lireSoleil(corps: String): Soleil? = try {
        val a = JSONObject(corps).optJSONObject("attributes") ?: JSONObject()
        Soleil(instant(a.optString("next_rising")), instant(a.optString("next_setting"))).takeIf { it.lever != null || it.coucher != null }
    } catch (_: Exception) {
        null
    }

    private fun nombre(o: JSONObject, cle: String): Double? =
        if (!o.has(cle) || o.isNull(cle)) null else o.optDouble(cle).takeIf { !it.isNaN() }

    private val POINTS = listOf("N" to 0.0, "NNE" to 22.5, "NE" to 45.0, "ENE" to 67.5, "E" to 90.0, "ESE" to 112.5, "SE" to 135.0,
        "SSE" to 157.5, "S" to 180.0, "SSO" to 202.5, "SSW" to 202.5, "SO" to 225.0, "SW" to 225.0, "OSO" to 247.5, "WSW" to 247.5,
        "O" to 270.0, "W" to 270.0, "ONO" to 292.5, "WNW" to 292.5, "NO" to 315.0, "NW" to 315.0, "NNO" to 337.5, "NNW" to 337.5)

    /** Direction en degrés, donnée en nombre ou en point cardinal (« NE ») selon l'intégration. */
    fun direction(v: Any?): Double? = when (v) {
        is Number -> v.toDouble().takeIf { !it.isNaN() }?.let { ((it % 360.0) + 360.0) % 360.0 }
        is String -> v.trim().toDoubleOrNull()?.let { direction(it) } ?: POINTS.firstOrNull { it.first.equals(v.trim(), true) }?.second
        else -> null
    }

    private fun instant(s: String): Long? {
        if (s.isBlank()) return null
        return try {
            OffsetDateTime.parse(s).toInstant().toEpochMilli()
        } catch (_: Exception) {
            try {
                Instant.parse(s).toEpochMilli()
            } catch (_: Exception) {
                null
            }
        }
    }
}
