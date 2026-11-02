package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Confirmation du mot de réveil (0.51.0) : deux blocs de suite au-dessus du seuil et de la parole récente. */
class ConfirmationReveilTest {
    private val seuil = 0.5f

    @Test
    fun unSeulBlocAuDessusDuSeuilNeReveillePas() {
        val c = ConfirmationReveil()
        assertFalse(c.bloc(0.1f, seuil, true))
        assertFalse(c.bloc(0.9f, seuil, true))
        assertEquals("un seul bloc au-dessus du seuil", c.refus)
        assertFalse(c.bloc(0.2f, seuil, false))
        assertFalse(c.bloc(0.9f, seuil, false))
    }

    @Test
    fun deuxBlocsDeSuiteAvecParoleReveillent() {
        val c = ConfirmationReveil()
        assertFalse(c.bloc(0.1f, seuil, true))
        assertFalse(c.bloc(0.6f, seuil, true))
        assertTrue(c.bloc(0.7f, seuil, false))
        // L'état repart de zéro après un réveil.
        assertFalse(c.bloc(0.7f, seuil, false))
    }

    @Test
    fun sansParoleRecenteLeScoreNeSuffitPas() {
        val c = ConfirmationReveil()
        repeat(5) { assertFalse(c.bloc(0.9f, seuil, false)) }
        assertEquals("pas de parole vue par Silero", c.refus)
    }

    @Test
    fun laParoleSOublieAuBoutDeLaMemoire() {
        val c = ConfirmationReveil()
        c.bloc(0.0f, seuil, true)
        repeat(ConfirmationReveil.MEMOIRE_VOIX - 1) { c.bloc(0.0f, seuil, false) }
        assertFalse(c.bloc(0.9f, seuil, false))
        assertFalse(c.bloc(0.9f, seuil, false))
    }

    @Test
    fun sansSileroSeuleLaSuiteDeBlocsCompte() {
        val c = ConfirmationReveil()
        assertFalse(c.bloc(0.9f, seuil, null))
        assertTrue(c.bloc(0.9f, seuil, null))
    }
}
