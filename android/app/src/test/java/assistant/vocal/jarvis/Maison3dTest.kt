package assistant.vocal.jarvis

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

class Maison3dTest {
    private fun lampe(etat: String, lum: Int?) = Appareils.Appareil(
        id = "light.salon_plafond", nom = "Salon", etat = etat, zone = "sejour", piece = "Séjour", luminosite = lum)

    private fun lampeCouleur(rgb: List<Int>?, kelvin: Int?, mode: String, etat: String = "on", lum: Int? = 80) = Appareils.Appareil(
        id = "light.salon_plafond", nom = "Salon", etat = etat, zone = "sejour", piece = "Séjour", luminosite = lum,
        rgb = rgb, kelvin = kelvin, mode = mode)

    private fun media(id: String, etat: String, volume: Double?) = Appareils.Appareil(
        id = id, nom = "Télé", etat = etat, zone = "sejour", piece = "Séjour", volume = volume)

    @Test
    fun lampeAllumeeAvecLuminosite() {
        val e = Maison3d.etatHa(lampe("on", 40))
        assertEquals("on", e.getString("state"))
        assertEquals(102, e.getJSONObject("attributes").getInt("brightness"))
    }

    @Test
    fun lampeEteinteSansLuminosite() {
        val e = Maison3d.etatHa(lampe("off", null))
        assertEquals("off", e.getString("state"))
        assertFalse(e.getJSONObject("attributes").has("brightness"))
    }

    @Test
    fun luminositeBornee() {
        assertEquals(255, Maison3d.etatHa(lampe("on", 140)).getJSONObject("attributes").getInt("brightness"))
    }

    @Test
    fun modeTemperatureEnvoieLesKelvins() {
        val a = Maison3d.etatHa(lampeCouleur(listOf(255, 180, 107), 2700, "color_temp")).getJSONObject("attributes")
        assertEquals(2700, a.getInt("color_temp_kelvin"))
        assertFalse(a.has("rgb_color"))
    }

    @Test
    fun modeCouleurEnvoieLeRgb() {
        val a = Maison3d.etatHa(lampeCouleur(listOf(10, 200, 30), 4000, "hs")).getJSONObject("attributes")
        assertEquals(200, a.getJSONArray("rgb_color").getInt(1))
        assertFalse(a.has("color_temp_kelvin"))
    }

    @Test
    fun sansRgbLaTemperatureSuffit() {
        val a = Maison3d.etatHa(lampeCouleur(null, 3000, "")).getJSONObject("attributes")
        assertEquals(3000, a.getInt("color_temp_kelvin"))
    }

    @Test
    fun lampeSansCouleurNEnvoieAucuneCouleur() {
        val a = Maison3d.etatHa(lampeCouleur(null, null, "brightness")).getJSONObject("attributes")
        assertFalse(a.has("rgb_color") || a.has("color_temp_kelvin"))
    }

    @Test
    fun couleursHorsBornesSontRamenees() {
        val a = Maison3d.etatHa(lampeCouleur(listOf(300, -5, 128), 90000, "rgb")).getJSONObject("attributes")
        val rgb = a.getJSONArray("rgb_color")
        assertEquals(listOf(255, 0, 128), listOf(rgb.getInt(0), rgb.getInt(1), rgb.getInt(2)))
        val k = Maison3d.etatHa(lampeCouleur(null, 90000, "color_temp")).getJSONObject("attributes")
        assertEquals(Maison3dPont.KELVIN_MAX, k.getInt("color_temp_kelvin"))
        val bas = Maison3d.etatHa(lampeCouleur(null, 10, "color_temp")).getJSONObject("attributes")
        assertEquals(Maison3dPont.KELVIN_MIN, bas.getInt("color_temp_kelvin"))
        // un rgb à deux composantes est ignoré
        assertFalse(Maison3d.etatHa(lampeCouleur(listOf(1, 2), null, "rgb")).getJSONObject("attributes").has("rgb_color"))
    }

    @Test
    fun lampeEteinteNePorteAucuneCouleur() {
        val a = Maison3d.etatHa(lampeCouleur(listOf(255, 0, 0), 2700, "rgb", etat = "off", lum = null)).getJSONObject("attributes")
        assertEquals(0, a.length())
    }

    @Test
    fun lampeIndisponibleOuInconnueEstRenvoyeeTelleQuelleSansAttributs() {
        for (etat in listOf("unavailable", "unknown")) {
            val e = Maison3d.etatHa(lampeCouleur(listOf(255, 0, 0), 2700, "rgb", etat = etat))
            assertEquals(etat, e.getString("state"))
            assertEquals(0, e.getJSONObject("attributes").length())
        }
    }

    @Test
    fun etat3dChoisitLaTraductionSelonLeDomaine() {
        assertEquals("on", Maison3d.etat3d(lampe("on", 50))!!.getString("state"))
        val tele = Maison3d.etat3d(media("media_player.tele_salon", "playing", 0.4))!!
        assertEquals("playing", tele.getString("state"))
        assertEquals(0.4, tele.getJSONObject("attributes").getDouble("volume_level"), 1e-9)
        val interrupteur = Appareils.Appareil(id = "switch.prise", nom = "Prise", etat = "on", zone = "sejour", piece = "Séjour")
        assertNull(Maison3d.etat3d(interrupteur))
    }

    @Test
    fun etatDeLaTeleSansVolume() {
        val e = Maison3d.etatMedia(media("media_player.tele_salon", "off", null))
        assertEquals("{\"state\":\"off\"}", e.toString())
    }

    @Test
    fun laCleDeDeduplicationChangeAvecLaCouleurLaChaleurEtLeVolume() {
        val chaud = Maison3d.etat3d(lampeCouleur(null, 2700, "color_temp"))!!.toString()
        val froid = Maison3d.etat3d(lampeCouleur(null, 6500, "color_temp"))!!.toString()
        val rouge = Maison3d.etat3d(lampeCouleur(listOf(255, 0, 0), null, "rgb"))!!.toString()
        val bleu = Maison3d.etat3d(lampeCouleur(listOf(0, 0, 255), null, "rgb"))!!.toString()
        assertEquals(4, setOf(chaud, froid, rouge, bleu).size)
        assertEquals(chaud, Maison3d.etat3d(lampeCouleur(null, 2700, "color_temp"))!!.toString())
        val bas = Maison3d.etat3d(media("media_player.tele_salon", "on", 0.1))!!.toString()
        val haut = Maison3d.etat3d(media("media_player.tele_salon", "on", 0.6))!!.toString()
        assertNotEquals(bas, haut)
    }

    @Test
    fun lireCorrespondancesIgnoreLeVideEtLesCommentaires() {
        val reglages = JSONObject("""{"vue3d": {"correspondances": {
            "media_player.a": "media_player.b", "_note": "texte", "": "x",
            "media_player.c": "  ", "media_player.autre": " media_player.b "}}}""")
        val m = Maison3d.lireCorrespondances(reglages)
        assertEquals(mapOf("media_player.a" to "media_player.b", "media_player.autre" to "media_player.b"), m)
        assertTrue(Maison3d.lireCorrespondances(JSONObject()).isEmpty())
        assertTrue(Maison3d.lireCorrespondances(JSONObject("""{"vue3d": {}}""")).isEmpty())
        assertTrue(Maison3d.lireCorrespondances(JSONObject("""{"vue3d": "texte"}""")).isEmpty())
    }
}
