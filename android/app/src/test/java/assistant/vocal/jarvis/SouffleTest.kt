package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Respiration de la lumière de l'assistant (0.18.0) : mots de la réponse, syllabes, micro, repos. */
class SouffleTest {

    /** Avance de [s] secondes par pas de 33 ms et rend la plus forte intensité vue. */
    private fun Souffle.pendant(s: Float): Float {
        var m = 0f
        var t = 0f
        while (t < s) {
            m = maxOf(m, avancer(0.033f))
            t += 0.033f
        }
        return m
    }

    @Test
    fun rienAuRepos() {
        val s = Souffle()
        s.mot(1f)
        assertEquals(0f, s.avancer(0.1f), 0f)
    }

    @Test
    fun chaqueMotDonneUneImpulsionQuiRetombe() {
        val s = Souffle()
        s.mode = Souffle.Mode.REPONSE
        s.avancer(0.033f)
        s.mot(1f)
        val pic = s.avancer(0.01f)
        assertTrue(pic > 0.9f)
        // Pas de mot pendant 0,4 s (sous le silence de 0,45 s) : l'impulsion retombe vers le plancher.
        var fin = 0f
        repeat(12) { fin = s.avancer(0.033f) }
        assertTrue(fin < 0.4f)
        assertTrue(fin >= 0.15f)
    }

    @Test
    fun syllabesQuandAucunMotNArrive() {
        val s = Souffle()
        s.mode = Souffle.Mode.REPONSE
        // Après le silence de 0,45 s, la lumière continue de parler au rythme des syllabes.
        s.pendant(0.5f)
        assertTrue(s.pendant(1f) >= 0.45f)
    }

    @Test
    fun suitLeMicroALEcoute() {
        val s = Souffle()
        s.mode = Souffle.Mode.ECOUTE
        s.niveau = 0f
        val calme = s.pendant(0.5f)
        s.niveau = 1f
        val fort = s.pendant(0.5f)
        assertTrue(fort > calme + 0.4f)
        assertTrue(fort <= 1f)
    }

    @Test
    fun pulsationLenteEnReflexion() {
        val s = Souffle()
        s.mode = Souffle.Mode.REFLEXION
        val vus = ArrayList<Float>()
        repeat(60) { vus.add(s.avancer(0.033f)) }
        assertTrue(vus.max() - vus.min() > 0.2f)
        assertTrue(vus.all { it in 0f..0.5f })
    }

    @Test
    fun valeursInvalidesSansEffet() {
        val s = Souffle()
        s.mode = Souffle.Mode.REPONSE
        s.mot(Float.NaN)
        val v = s.avancer(Float.NaN)
        assertTrue(!v.isNaN() && v in 0f..1f)
    }
}
