package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

class Maison3dTest {
    private fun lampe(etat: String, lum: Int?) = Appareils.Appareil(
        id = "light.exemple6", nom = "Salon", etat = etat, zone = "sejour", piece = "Séjour", luminosite = lum)

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
}
