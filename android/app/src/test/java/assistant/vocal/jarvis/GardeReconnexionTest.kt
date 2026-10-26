package assistant.vocal.jarvis

import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Chien de garde de la passerelle Home Assistant (0.38.2). */
class GardeReconnexionTest {

    private val socketA = Any()
    private val socketB = Any()

    @Test
    fun pasDeSocketRienAFaire() {
        val g = GardeReconnexion(30_000)
        assertFalse(g.doitRelancer(null, false, 0))
        assertFalse(g.doitRelancer(null, false, 120_000))
    }

    @Test
    fun socketIndisponibleRelanceeApresLeDelai() {
        val g = GardeReconnexion(30_000)
        assertFalse(g.doitRelancer(socketA, false, 1_000))
        assertFalse(g.doitRelancer(socketA, false, 20_000))
        assertFalse(g.doitRelancer(socketA, false, 30_999))
        assertTrue(g.doitRelancer(socketA, false, 31_000))
    }

    @Test
    fun passerelleDisponibleNeDeclenchePas() {
        val g = GardeReconnexion(30_000)
        assertFalse(g.doitRelancer(socketA, false, 0))
        assertFalse(g.doitRelancer(socketA, true, 10_000))
        assertFalse(g.doitRelancer(socketA, true, 200_000))
    }

    @Test
    fun uneCoupureApresDisponibiliteRepartDeZero() {
        val g = GardeReconnexion(30_000)
        assertFalse(g.doitRelancer(socketA, true, 0))
        // Devenue indisponible : le délai compte à partir de la première observation, pas de l'ouverture.
        assertFalse(g.doitRelancer(socketA, false, 100_000))
        assertFalse(g.doitRelancer(socketA, false, 120_000))
        assertTrue(g.doitRelancer(socketA, false, 130_000))
    }

    @Test
    fun uneNouvelleSocketRelanceLeChronometre() {
        val g = GardeReconnexion(30_000)
        assertFalse(g.doitRelancer(socketA, false, 0))
        assertFalse(g.doitRelancer(socketB, false, 25_000))
        assertFalse(g.doitRelancer(socketB, false, 50_000))
        assertTrue(g.doitRelancer(socketB, false, 55_000))
    }

    @Test
    fun apresUneRelanceLeChronometreRepart() {
        val g = GardeReconnexion(30_000)
        assertFalse(g.doitRelancer(socketA, false, 0))
        assertTrue(g.doitRelancer(socketA, false, 30_000))
        // Même objet revu sans avoir été remplacé : nouveau délai complet.
        assertFalse(g.doitRelancer(socketA, false, 31_000))
        assertFalse(g.doitRelancer(socketA, false, 60_000))
        assertTrue(g.doitRelancer(socketA, false, 61_000))
    }
}
