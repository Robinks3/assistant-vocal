package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneId
import java.time.ZonedDateTime
import kotlin.math.abs

/** Vent mesuré (0.29.0) : lecture du message `vent_mesure`, fraîcheur, 15 min, choix, carte, voix. */
class MeteoVentTest {

    private val zone = ZoneId.of("Europe/Paris")
    private val maintenant = ZonedDateTime.of(2026, 10, 24, 11, 26, 0, 0, zone)
    private val t0 = maintenant.toEpochSecond()

    private fun mesures(vals: List<Triple<Long, Double, Double?>>, dir: Int = 240): JSONArray {
        val a = JSONArray()
        for ((age, v, r) in vals) a.put(JSONObject().put("t", t0 - age * 60).put("vent", v).put("dir", dir).put("rafale", r ?: JSONObject.NULL))
        return a
    }

    private fun station(id: String, nom: String, type: String, lat: Double, lon: Double, point: String, seuil: Int, m: JSONArray, genre: String = "") =
        JSONObject().put("id", id).put("nom", nom).put("genre", genre).put("type", type).put("source", "test").put("lat", lat).put("lon", lon)
            .put("point", point).put("seuil_min", seuil).put("mesures", m)

    private fun reponse(prado: Boolean = false): JSONObject {
        val st = JSONArray()
        if (prado) st.put(station("prado", "Prado", "mer", 43.25, 5.36, "prado", 45, mesures(listOf(Triple(1L, 14.2, 17.5)), 255)))
        st.put(station("frioul", "Frioul", "mer", 43.28, 5.28, "pharo", 45,
            mesures(listOf(Triple(16L, 9.0, 12.0), Triple(10L, 12.0, 16.0), Triple(5L, 14.0, 15.0), Triple(1L, 12.8, 14.9))), "balise de régate"))
        st.put(station("callelongue", "Callelongue", "mer", 43.2105, 5.3402, "prado", 75, mesures(listOf(Triple(37L, 13.2, null)), 352)))
        st.put(station("port", "Vieux-Port", "terre", 43.3, 5.37, "prado", 30, mesures(listOf(Triple(2L, 1.7, null)), 35)))
        st.put(station("lfml", "Marignane", "terre", 43.44, 5.22, "prado", 75, mesures(listOf(Triple(37L, 9.0, null)), 250)))
        st.put(station("stn304", "Castellane", "amateur", 43.2815, 5.3794, "prado", 75, mesures(listOf(Triple(88L, 5.6, null)), 231)))
        return JSONObject().put("etat", "vent_mesure").put("id", 4).put("donnees",
            JSONObject().put("lu_a", "2026-10-24T11:26:12+02:00").put("stations", st).put("erreurs", JSONArray()))
    }

    private val d by lazy { MeteoVent.lire(reponse()).first!! }

    @Test
    fun litLaReponseDuServeur() {
        assertEquals(5, d.stations.size)
        assertEquals("Frioul", d.stations[0].nom)
        assertEquals(4, d.stations[0].mesures.size)
        assertNull(d.station("callelongue")!!.mesures[0].rafale)
        assertEquals("le serveur ne répond pas", MeteoVent.lire(null).second)
        assertEquals("Balises indisponibles", MeteoVent.lire(JSONObject().put("erreur", "Balises indisponibles")).second)
        // Station sans mesure écartée, mesure illisible écartée.
        val vide = JSONObject().put("stations", JSONArray().put(station("x", "X", "mer", 40.8, 14.2, "prado", 45, JSONArray())))
            .put("erreurs", JSONArray().put("Stations indisponibles"))
        assertEquals("Stations indisponibles", MeteoVent.lire(vide).second)
    }

    @Test
    fun fraicheurSelonLaSource() {
        val frioul = d.station("frioul")!!
        assertTrue(MeteoVent.fraiche(frioul, MeteoVent.mesure(frioul, t0), t0))
        val callelongue = d.station("callelongue")!!
        assertTrue(MeteoVent.fraiche(callelongue, MeteoVent.mesure(callelongue, t0), t0))
        // 46 min plus tard, Frioul (45 min) est périmée, Callelongue (75 min) ne l'est qu'après 75 min.
        assertFalse(MeteoVent.fraiche(frioul, MeteoVent.mesure(frioul, t0 + 46 * 60), t0 + 46 * 60))
        val amateur = d.station("stn304")!!
        assertFalse(MeteoVent.fraiche(amateur, MeteoVent.mesure(amateur, t0), t0))
        // Au curseur, la mesure est celle d'avant l'instant.
        assertEquals(12.0, MeteoVent.mesure(frioul, t0 - 8 * 60)!!.vent, 1e-9)
        assertNull(MeteoVent.mesure(frioul, t0 - 30 * 60))
    }

    @Test
    fun quinzeMinutesEtTextes() {
        val (moy, raf) = MeteoVent.quinze(d.station("frioul")!!, t0)!!
        assertEquals((12.0 + 14.0 + 12.8) / 3, moy, 1e-9)
        assertEquals(16.0, raf, 1e-9)
        assertEquals("il y a 1 min", MeteoVent.ilYa(0))
        assertEquals("il y a 37 min", MeteoVent.ilYa(37))
        assertEquals("il y a 1 h 20", MeteoVent.ilYa(80))
        assertEquals("11 h 26", MeteoVent.heure(t0))
    }

    @Test
    fun choixEtLignes() {
        assertEquals("frioul", MeteoVent.parDefaut(d, t0)!!.id)
        val regate = MeteoVent.lire(reponse(prado = true)).first!!
        assertEquals("prado", MeteoVent.parDefaut(regate, t0)!!.id)
        assertEquals("port", MeteoVent.pourPoint(d, "prado", t0)!!.id)
        assertEquals("callelongue", MeteoVent.pourPoint(d, "prado", t0, enMer = true)!!.id)
        assertEquals("frioul", MeteoVent.pourPoint(d, "pharo", t0)!!.id)
        assertEquals("13 nœuds de sud-ouest à Frioul, il y a 1 min", MeteoVent.apercu(d, t0))
        assertEquals("Mesuré à Frioul il y a 1 min : 13 nœuds de sud-ouest", MeteoVent.ligneMesure(d, "pharo", t0))
        assertNull(MeteoVent.apercu(d, t0 + 3 * 3600))
    }

    @Test
    fun carteSansChevauchement() {
        val b = MeteoVent.blocs(d)
        // Marignane est hors du cadre.
        assertNull(b.firstOrNull { it.station.id == "lfml" })
        for (x in b) {
            assertTrue(x.bx in 0f..MeteoVent.LARGEUR && x.by in 0f..MeteoVent.HAUTEUR)
            for (y in b) if (x !== y) assertFalse("${x.station.id} touche ${y.station.id}", abs(x.bx - y.bx) < 70f && abs(x.by - y.by) < 80f)
        }
        val frioul = b.first { it.station.id == "frioul" }
        assertEquals("frioul", MeteoVent.touchee(b, frioul.bx, frioul.by)!!.id)
        assertNull(MeteoVent.touchee(b, 600f, 10f))
    }

    @Test
    fun reponseALaVoixParLaMesure() {
        val q = MeteoQuestion.comprendre("quel vent à Prado", maintenant)!!
        assertTrue(q.mesure)
        val r = MeteoVent.reponse(q, d, null, maintenant)!!
        assertEquals(MeteoQuestion.Page.VENT, r.page)
        // Prado n'émet pas hors régate : Callelongue, la plus proche fraîche du point.
        assertEquals("callelongue", r.station)
        assertEquals("La balise de Prado n'émet pas en ce moment. Callelongue mesure 13 nœuds de nord il y a 37 minutes.", r.parle)
        val regate = MeteoVent.lire(reponse(prado = true)).first!!
        val r2 = MeteoVent.reponse(q, regate, null, maintenant)!!
        assertEquals("Prado mesure 14 nœuds d'ouest il y a 1 minute, rafales à 18.", r2.parle)
        assertEquals(listOf("14 nœuds d'ouest.", "Il y a 1 min, rafales 18."), r2.lignes)
        // Plus tard que tous les seuils : pas de réponse par la mesure.
        assertNull(MeteoVent.reponse(q, d, null, maintenant.plusHours(3)))
        // Une question sur la mer demain reste aux prévisions.
        assertFalse(MeteoQuestion.comprendre("quel vent à Prado demain", maintenant)!!.mesure)
        assertFalse(MeteoQuestion.comprendre("quelles conditions en mer à Prado", maintenant)!!.mesure)
        assertTrue(MeteoQuestion.comprendre("quel vent fait-il en mer", maintenant)!!.mesure)
        assertFalse(MeteoQuestion.comprendre("quel vent va-t-il faire à Prado", maintenant)!!.mesure)
        assertFalse(MeteoQuestion.comprendre("le vent soufflera-t-il en mer", maintenant)!!.mesure)
        assertFalse(MeteoQuestion.comprendre("quel vent en mer dans deux heures", maintenant)!!.mesure)
        assertEquals("pharo", MeteoQuestion.comprendre("quel vent au frioul", maintenant)!!.point)
        // Sans point nommé, pas de phrase sur la balise absente.
        val enMer = MeteoVent.reponse(MeteoQuestion.comprendre("quel vent en mer", maintenant)!!, d, null, maintenant)!!
        assertTrue(enMer.parle.startsWith("Callelongue mesure"))
    }
}
