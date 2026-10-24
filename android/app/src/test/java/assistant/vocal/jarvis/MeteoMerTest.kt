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

/** Page Mer (0.23.0) : lecture du message `meteo_mer`, frise, synthèse, cases, réponse à la voix. */
class MeteoMerTest {

    private val zone = ZoneId.of("Europe/Paris")
    private val maintenant = ZonedDateTime.of(2026, 10, 23, 10, 12, 0, 0, zone)

    /** Prévision ARPEGE d'exemple du 23/10/2026 au point Prado (vent, rafales, direction, AROME), vagues régionales mr01. */
    private val prado = listOf(
        listOf(10, 1.9, 3.5, 84, 2.5, 0.4), listOf(11, 1.6, 2.5, 138, 2.3, 0.3), listOf(12, 2.7, 3.9, 177, 3.1, 0.3),
        listOf(13, 3.7, 5.1, 202, 5.2, 0.3), listOf(14, 5.2, 7.2, 220, 6.8, 0.3), listOf(15, 4.7, 7.2, 234, 7.6, 0.3),
        listOf(16, 5.2, 7.4, 219, 6.4, 0.2), listOf(17, 5.2, 7.2, 243, 6.4, 0.2), listOf(18, 5.8, 8.0, 272, 6.2, 0.2),
        listOf(19, 4.5, 8.2, 279, 5.2, 0.2), listOf(20, 4.9, 6.8, 266, 4.1, 0.2), listOf(21, 4.9, 7.2, 258, 5.4, 0.2),
    )

    /** Pharo : la brise retombe à 19 h. */
    private val pharo = listOf(
        listOf(10, 2.9, 5.6, 48, 1.6, 0.2), listOf(11, 2.1, 4.1, 88, 3.7, 0.2), listOf(12, 2.9, 4.1, 160, 4.9, 0.2),
        listOf(13, 5.1, 6.8, 190, 7.2, 0.2), listOf(14, 7.4, 9.5, 207, 8.2, 0.1), listOf(15, 7.8, 10.5, 225, 9.3, 0.1),
        listOf(16, 7.4, 10.5, 230, 7.4, 0.1), listOf(17, 6.2, 9.7, 234, 7.0, 0.1), listOf(18, 5.6, 8.4, 259, 6.6, 0.1),
        listOf(19, 3.7, 7.6, 275, 5.2, 0.1), listOf(20, 2.7, 5.2, 265, 4.5, 0.1),
    )

    private fun heures(l: List<List<Any>>, jour: Int = 23): JSONArray {
        val a = JSONArray()
        for (r in l) a.put(
            JSONObject().put("t", String.format("2026-10-%02dT%02d:00", jour, (r[0] as Number).toInt())).put("vent", r[1]).put("rafales", r[2])
                .put("dir", r[3]).put("vent2", r[4]).put("dir2", r[3]).put("air", 20.0).put("pluie", 0.0).put("cape", 40)
                .put("foudre", 0.0).put("code", 1).put("visi", 50000).put("vagues", r[5]).put("periode", 4.5).put("dir_vagues", 232)
        )
        return a
    }

    private fun reponse(): JSONObject {
        val points = JSONArray()
            .put(JSONObject().put("id", "prado").put("nom", "Prado").put("vagues_source", "regional").put("heures", heures(prado)))
            .put(JSONObject().put("id", "pharo").put("nom", "Pharo").put("vagues_source", "regional").put("heures", heures(pharo)))
            .put(JSONObject().put("id", "rade").put("nom", "Milieu de rade").put("vagues_source", "mfwam").put("heures", heures(prado)))
        val donnees = JSONObject().put("lu_a", "2026-10-23T09:50:12+02:00").put("points", points).put("eau", 22.2)
            .put("soleil", JSONArray().put(JSONObject().put("jour", "2026-10-23").put("lever", "07:23").put("coucher", "18:11"))
                .put(JSONObject().put("jour", "2026-10-24").put("lever", "07:24").put("coucher", "18:09")))
            .put("station", JSONObject().put("nom", "Vieux-Port").put("vent", 1.7).put("dir", 35).put("le", "2026-10-23T10:05:00+02:00"))
            .put("erreurs", JSONArray())
        return JSONObject().put("etat", "meteo_mer").put("id", 3).put("donnees", donnees)
    }

    private val d by lazy { MeteoMer.lire(reponse()).first!! }

    @Test
    fun litLaReponseDuServeur() {
        assertEquals(3, d.points.size)
        assertEquals("Prado", d.points[0].nom)
        assertEquals(12, d.points[0].heures.size)
        assertEquals(22.2, d.eau!!, 1e-9)
        assertEquals(9, d.luA!!.hour)
        assertNotNull(d.station)
        assertEquals("le serveur ne répond pas", MeteoMer.lire(null).second)
        assertEquals("ARPEGE indisponible", MeteoMer.lire(JSONObject().put("etat", "meteo_mer").put("erreur", "ARPEGE indisponible")).second)
        // Une valeur absente reste absente, jamais 0.
        val sans = JSONObject().put("points", JSONArray().put(JSONObject().put("id", "prado")
            .put("heures", JSONArray().put(JSONObject().put("t", "2026-10-23T10:00").put("vent", JSONObject.NULL)))))
        assertNull(MeteoMer.lire(sans).first!!.points[0].heures[0].vent)
    }

    @Test
    fun syntheseDuPradoCommeLaMaquette() {
        val w = MeteoMer.journee(d.point("prado")!!, maintenant)
        assertEquals(10, w.first().t.hour)
        assertEquals(19, w.last().t.hour)
        val s = MeteoMer.synthese(w, "aujourd'hui")
        assertEquals(listOf("Moins de 4 nœuds avant 14 h.", "Puis sud-ouest, 5 à 6 nœuds.", "Ouest vers 18 h.", "Rafales 8, vagues 0,2 à 0,4 m."), s.lignes)
        assertEquals("sud-ouest 5 à 6 nœuds cet après-midi", s.apercu)
        assertEquals(
            "Moins de 4 nœuds avant 14 heures, puis sud-ouest, 5 à 6 nœuds, passant à l'ouest vers 18 heures. " +
                "Rafales à 8 nœuds, vagues de 0,2 à 0,4 mètre, pas d'orage.",
            s.parle,
        )
    }

    @Test
    fun syntheseDuPharoQuiRetombe() {
        val s = MeteoMer.synthese(MeteoMer.journee(d.point("pharo")!!, maintenant), "aujourd'hui")
        assertEquals(listOf("Moins de 4 nœuds avant 13 h.", "Puis sud, 5 à 8 nœuds.", "Sud-ouest vers 17 h, retombe à 19 h.", "Rafales 11, vagues 0,1 à 0,2 m."), s.lignes)
    }

    @Test
    fun calmeEtOrage() {
        val calme = (7..19).map { MeteoMer.Heure(java.time.LocalDateTime.of(2026, 10, 23, it, 0), 0.5, 1.0, 90) }
        assertEquals("Calme toute la journée.", MeteoMer.synthese(calme, "aujourd'hui").lignes.first())
        val orage = (7..19).map { MeteoMer.Heure(java.time.LocalDateTime.of(2026, 10, 23, it, 0), 6.0, 9.0, 220, cape = if (it == 16) 1500 else 100) }
        val s = MeteoMer.synthese(orage, "aujourd'hui")
        assertEquals("Risque d'orage vers 16 h.", s.lignes.first())
        assertEquals("risque d'orage aujourd'hui", s.apercu)
        assertFalse(s.parle.contains("pas d'orage"))
    }

    @Test
    fun friseSauteLaNuit() {
        val p = MeteoMer.Point("prado", "Prado", "regional",
            (0..23).map { MeteoMer.Heure(java.time.LocalDateTime.of(2026, 10, 23, it, 0), 5.0, 7.0, 220) } +
                (0..23).map { MeteoMer.Heure(java.time.LocalDateTime.of(2026, 10, 24, it, 0), 5.0, 7.0, 220) })
        val c = MeteoMer.colonnes(p, maintenant)
        assertEquals(10, c.first().h.t.hour)
        assertEquals(20, c[10].h.t.hour)
        assertTrue(c[11].saut)
        assertEquals(7, c[11].h.t.hour)
        assertEquals(11 + 14, c.size)
    }

    @Test
    fun blocDuMomentEtCases() {
        val p = d.point("prado")!!
        val h = MeteoMer.maintenant(p, maintenant)!!
        assertEquals("Variable", MeteoMer.direction(h.vent, h.dir))
        assertEquals("D'ouest, 272°", MeteoMer.direction(5.8, 272))
        assertEquals("Rafales 4 nœuds, AROME 3 nœuds", MeteoMer.ligneRafales(h))
        assertEquals("Station à terre, 10 h 05 : 2 nœuds", MeteoMer.ligneMesure("prado", d, h, maintenant))
        assertEquals("Vagues 0,2 m en 5 s, eau 22°", MeteoMer.ligneMesure("pharo", d, MeteoMer.maintenant(d.point("pharo")!!, maintenant), maintenant))
        // Mesure trop vieille : les vagues à la place.
        assertTrue(MeteoMer.ligneMesure("prado", d, h, maintenant.plusMinutes(30)).startsWith("Vagues"))
        val w = MeteoMer.journee(p, maintenant)
        val cases = MeteoMer.cases(d, w, p.heures.first { it.t.hour == 15 }, maintenant)
        assertEquals(listOf("Modèles", "Orages", "Eau", "Soleil"), cases.map { it.nom })
        assertEquals("3 nœuds", cases[0].valeur)
        assertEquals("à 15 h", cases[0].ligne2)
        assertEquals("Aucun", cases[1].valeur)
        assertEquals("jusqu'à 20 h", cases[1].ligne1)
        assertEquals("22°", cases[2].valeur)
        assertEquals("18 h 11", cases[3].valeur)
        assertEquals("lever 7 h 24", cases[3].ligne2)
        assertEquals("15 h" to " : 5 nœuds de sud-ouest (234°), rafales 7, AROME 8, vagues 0,3 m en 5 s, air 20°, sec", MeteoMer.detail(p.heures.first { it.t.hour == 15 }))
    }

    @Test
    fun reponseALaVoix() {
        val q = MeteoQuestion.comprendre("Quelles conditions en mer à Prado ?", maintenant)!!
        val r = MeteoMer.reponse(q, d, maintenant)
        assertEquals(MeteoQuestion.Page.MER, r.page)
        assertEquals("Conditions de navigation aujourd'hui", r.entete)
        assertEquals(4, r.lignes.size)
        assertTrue(r.parle.startsWith("À Prado aujourd'hui, moins de 4 nœuds avant 14 heures, puis sud-ouest"))
        assertEquals("De 10 h à 20 h", r.detail.first)
        assertEquals(" : moins de 4 nœuds avant 14 h, puis sud-ouest 5 à 6 nœuds, ouest vers 18 h, rafales jusqu'à 8, vagues 0,2 à 0,4 m, sec", r.detail.second)
        val sans = MeteoMer.reponse(q, null, maintenant, "le PC ne répond pas")
        assertEquals("Je n'ai pas la météo de la mer : le PC ne répond pas.", sans.parle)
        assertEquals("sud-ouest 5 à 6 nœuds cet après-midi", MeteoMer.apercu(d, maintenant))
    }
}
