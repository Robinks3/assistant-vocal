package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneId
import java.time.ZonedDateTime

/** Lecture des prévisions météo (0.18.0) : types demandés, réponse de weather.get_forecasts, météo du moment. */
class PrevisionsTest {

    private val paris = ZoneId.of("Europe/Paris")

    /** Réponse REST de `POST /api/services/weather/get_forecasts?return_response`, comme HA la rend. */
    private val reponse = """
        {"changed_states": [], "service_response": {"weather.forecast_maison": {"forecast": [
          {"condition": "sunny", "datetime": "2026-10-22T10:00:00+00:00", "temperature": 20.4, "precipitation_probability": 0, "precipitation": 0.0, "wind_speed": 11.2, "wind_bearing": 225, "wind_gust_speed": 24.1, "humidity": 64},
          {"condition": "partlycloudy", "datetime": "2026-10-22T09:00:00+00:00", "temperature": 19.0, "precipitation_probability": 10},
          {"condition": "rainy", "datetime": "2026-10-22T11:00:00Z", "temperature": 18, "precipitation_probability": 70, "wind_bearing": "NE"},
          {"condition": "cloudy", "datetime": "pas une date", "temperature": 17}
        ]}}}
    """.trimIndent()

    @Test
    fun typesSelonLesFonctionsDeLEntite() {
        // WeatherEntityFeature : 1 par jour, 2 horaire, 4 deux par jour. Rien d'annoncé : on essaie quand même.
        assertTrue(Previsions.horaire(3))
        assertFalse(Previsions.horaire(1))
        assertTrue(Previsions.horaire(0))
        assertEquals(Previsions.PAR_JOUR, Previsions.typeJours(3))
        assertEquals(Previsions.DEUX_PAR_JOUR, Previsions.typeJours(6))
        assertNull(Previsions.typeJours(2))
        assertEquals(Previsions.PAR_JOUR, Previsions.typeJours(0))
        val c = Previsions.corps("weather.forecast_maison", Previsions.HORAIRE)
        assertEquals("weather.forecast_maison", c.getString("entity_id"))
        assertEquals("hourly", c.getString("type"))
        assertTrue(Previsions.CHEMIN.endsWith("?return_response"))
    }

    @Test
    fun lectureDeLaReponseDuService() {
        val l = Previsions.lire(reponse, "weather.forecast_maison")
        // L'élément sans date est écarté, le reste trié dans le temps.
        assertEquals(3, l.size)
        assertEquals(listOf("partlycloudy", "sunny", "rainy"), l.map { it.condition })
        val midi = l[1]
        assertEquals(20.4, midi.temperature!!, 0.001)
        assertEquals(ZonedDateTime.of(2026, 10, 22, 12, 0, 0, 0, paris).toInstant().toEpochMilli(), midi.instant)
        assertEquals(11.2, midi.vent!!, 0.001)
        assertEquals(225.0, midi.direction!!, 0.001)
        assertEquals(24.1, midi.rafales!!, 0.001)
        assertEquals(64, midi.humidite)
        assertEquals(70, l[2].pluie)
        // Direction donnée en point cardinal par certaines intégrations.
        assertEquals(45.0, l[2].direction!!, 0.001)
        assertNull(l[0].vent)
        // Réponse du service seule, sans enveloppe, ou d'une autre entité : lue quand même.
        val seule = """{"weather.autre": {"forecast": [{"condition": "fog", "datetime": "2026-10-22T09:00:00+00:00", "temperature": 9}]}}"""
        assertEquals("fog", Previsions.lire(seule, "weather.forecast_maison").single().condition)
        // Liste brute.
        assertEquals(1, Previsions.lire("""[{"condition": "snowy", "datetime": "2026-10-22T09:00:00+00:00"}]""", "x").size)
        // Refus de la passerelle, réponse vide ou illisible : aucune prévision, sans planter.
        assertTrue(Previsions.lire("refusé : chemin non permis", "weather.forecast_maison").isEmpty())
        assertTrue(Previsions.lire("", "weather.forecast_maison").isEmpty())
        assertTrue(Previsions.lire("{}", "weather.forecast_maison").isEmpty())
    }

    @Test
    fun previsionsParJourEtDeuxFoisParJour() {
        val jours = """{"service_response": {"weather.m": {"forecast": [
            {"condition": "rainy", "datetime": "2026-10-23T10:00:00+00:00", "temperature": 18, "templow": 11, "precipitation_probability": 70},
            {"condition": "clear-night", "datetime": "2026-10-23T22:00:00+00:00", "temperature": 12, "is_daytime": false}
        ]}}}"""
        val l = Previsions.lire(jours, "weather.m")
        assertEquals(11.0, l[0].basse!!, 0.001)
        assertNull(l[0].deJour)
        assertEquals(false, l[1].deJour)
    }

    @Test
    fun meteoDuMomentEtSoleil() {
        val etat = """{"entity_id": "weather.forecast_maison", "state": "partlycloudy", "attributes": {"temperature": 19.6,
            "apparent_temperature": 18.7, "humidity": 64, "pressure": 1016.2, "wind_speed": 11, "wind_bearing": 210.0,
            "wind_gust_speed": 24, "uv_index": 3.1, "dew_point": 12.4, "visibility": 16, "cloud_coverage": 40,
            "wind_speed_unit": "km/h", "pressure_unit": "hPa", "visibility_unit": "km",
            "forecast": [{"condition": "sunny", "datetime": "2026-10-22T10:00:00+00:00", "temperature": 20}]}}"""
        val a = Previsions.lireActuel(etat)!!
        assertEquals("partlycloudy", a.condition)
        assertEquals(18.7, a.ressenti!!, 0.001)
        assertEquals(64, a.humidite)
        assertEquals(210.0, a.direction!!, 0.001)
        assertEquals(40, a.nuages)
        assertEquals("hPa", a.unitePression)
        // Une entité qui ne donne que la température : le reste est absent, pas inventé.
        val maigre = Previsions.lireActuel("""{"state": "sunny", "attributes": {"temperature": 21}}""")!!
        assertNull(maigre.humidite)
        assertNull(maigre.ressenti)
        assertNull(Previsions.lireActuel("pas du JSON"))
        // Ancien attribut forecast, pour les intégrations qui le gardent.
        assertEquals(1, Previsions.lireAttribut(etat).size)
        val soleil = Previsions.lireSoleil("""{"state": "above_horizon", "attributes": {"next_rising": "2026-10-23T05:12:03.000+00:00", "next_setting": "2026-10-22T16:21:40+00:00"}}""")!!
        assertEquals(ZonedDateTime.of(2026, 10, 23, 7, 12, 3, 0, paris).toInstant().toEpochMilli(), soleil.lever)
        assertNull(Previsions.lireSoleil("""{"attributes": {}}"""))
    }

    @Test
    fun directionDuVent() {
        assertEquals(0.0, Previsions.direction(360)!!, 0.001)
        assertEquals(350.0, Previsions.direction(-10.0)!!, 0.001)
        assertEquals(202.5, Previsions.direction("SSW")!!, 0.001)
        assertEquals(270.0, Previsions.direction("O")!!, 0.001)
        assertEquals(90.0, Previsions.direction("90")!!, 0.001)
        assertNull(Previsions.direction("vers le large"))
        assertNull(Previsions.direction(null))
    }
}
