package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Palette à la voix et soleil du mode Selon l'heure (0.19.0). */
class ApparenceTest {

    @Test
    fun paletteNommeeALaVoix() {
        assertEquals("Méditerranée", Apparence.commande("Mets la palette Méditerranée")?.nom)
        assertEquals("Méditerranée", Apparence.commande("mets la palette mediterranee s'il te plaît")?.nom)
        assertEquals("Veillée", Apparence.commande("palette veillée")?.nom)
        assertEquals("Pastels", Apparence.commande("Palette pastel")?.nom)
        assertEquals("Sobre", Apparence.commande("Mets la palette sobre")?.nom)
        assertEquals(Palette.AUTO, Apparence.commande("Mets la palette selon l'heure")?.nom)
        assertEquals(Palette.AUTO, Apparence.commande("palette automatique")?.nom)
    }

    @Test
    fun paletteSuivante() {
        val d = Apparence.commande("Palette suivante")
        assertTrue(d != null && d.nom == null)
        val c = Apparence.commande("Change de palette")
        assertTrue(c != null && c.nom == null)
    }

    @Test
    fun autresPhrasesNonPrises() {
        assertNull(Apparence.commande("Allume la lumière du salon"))
        assertNull(Apparence.commande("Palette"))
        assertNull(Apparence.commande("Mets la palette aurore"))
        assertNull(Apparence.commande("Est-ce que tu sais d'où vient le mot palette en peinture à l'huile ancienne"))
        assertEquals("Palette Méditerranée.", Apparence.reponse("Méditerranée"))
        assertEquals("Palette selon l'heure.", Apparence.reponse(Palette.AUTO))
    }

    @Test
    fun soleilLeveOuCouche() {
        val h = 3_600_000L
        // Lu levé à 10 h, coucher à 18 h, lever le lendemain à 7 h.
        val s = Etat.Soleil(true, lever = 31 * h, coucher = 18 * h)
        assertTrue(Apparence.jour(s, 12 * h, 12))
        assertFalse(Apparence.jour(s, 19 * h, 19))
        assertTrue(Apparence.jour(s, 32 * h, 8))
        // Lu couché la nuit : levé une fois le lever passé.
        val n = Etat.Soleil(false, lever = 7 * h, coucher = 18 * h)
        assertFalse(Apparence.jour(n, 6 * h, 6))
        assertTrue(Apparence.jour(n, 8 * h, 8))
        // Sans sun.sun : de 7 h à 19 h.
        assertTrue(Apparence.jour(null, 0L, 7))
        assertFalse(Apparence.jour(null, 0L, 19))
    }

    @Test
    fun lectureDuSoleilTropVieille() {
        val h = 3_600_000L
        val s = Etat.Soleil(false, lever = 7 * h, coucher = 18 * h, luLe = 0L)
        // Lu il y a plus de 24 h : repli sur 7 h à 19 h, quoi que dise la lecture.
        assertTrue(Apparence.jour(s, 30 * h, 12))
        assertFalse(Apparence.jour(s, 30 * h, 21))
    }
}
