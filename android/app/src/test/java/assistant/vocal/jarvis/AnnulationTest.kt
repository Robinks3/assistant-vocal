package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import assistant.vocal.jarvis.Annulation.Geste as g
import assistant.vocal.jarvis.Annulation.Moment as m

/** Annuler la réflexion d'un appui (0.52.0) : gestes par moment, commande annulée, rappel de ce qui est fait. */
class AnnulationTest {

    @Test
    fun `l'heure veut dire je reparle, l'ecran veut dire stop`() {
        assertEquals(g.ECOUTER, Annulation.geste(m.REPOS, surHeure = true))
        assertEquals(g.RIEN, Annulation.geste(m.REPOS, surHeure = false))
        assertEquals(g.ANNULER_REFLEXION, Annulation.geste(m.REFLEXION, surHeure = true))
        assertEquals(g.ANNULER_REFLEXION, Annulation.geste(m.REFLEXION, surHeure = false))
        assertEquals(g.COUPER_ET_REECOUTER, Annulation.geste(m.REPONSE, surHeure = true))
        assertEquals(g.COUPER, Annulation.geste(m.REPONSE, surHeure = false))
        assertEquals(g.RIEN, Annulation.geste(m.AUTRE, surHeure = true))
    }

    @Test
    fun `pendant l'ecoute un toucher garde son sens, arreter`() {
        assertEquals(Annulation.Geste.ARRETER_ECOUTE, Annulation.geste(Annulation.Moment.ECOUTE, surHeure = true))
        assertEquals(Annulation.Geste.ARRETER_ECOUTE, Annulation.geste(Annulation.Moment.ECOUTE, surHeure = false))
    }

    @Test
    fun `l'ecran capte tout appui sauf au repos`() {
        assertFalse(Annulation.capte("Repos"))
        assertTrue(Annulation.capte("Je t'écoute"))
        assertTrue(Annulation.capte("Je réfléchis"))
        assertTrue(Annulation.capte("Je réponds"))
        assertFalse(Annulation.capte(""))
        assertEquals(Annulation.Moment.REFLEXION, Annulation.moment("Je réfléchis"))
    }

    @Test
    fun `une commande est annulee quand son numero n'est plus le courant`() {
        assertFalse(Annulation.annulee(commandeDuFil = 4, numeroCommande = 4))
        assertTrue(Annulation.annulee(commandeDuFil = 4, numeroCommande = 5))
    }

    @Test
    fun `seules les actions vraiment parties sont rappelees`() {
        val fait = listOf(
            "light.turn_on light.essai",
            "light.turn_off light.autre" + Annulation.SUFFIXE,
            "lock.unlock lock.porte (refusé : sécurité)",
            "light.turn_on light.essai (non exécuté, essai)",
            "media_player.turn_on media_player.tele (écartée)",
            "rien fait (personne non reconnue)",
        )
        assertEquals(listOf("light.turn_on light.essai"), Annulation.faites(fait))
    }

    @Test
    fun `message sous l'heure`() {
        assertNull(Annulation.message(emptyList()))
        assertNull(Annulation.message(listOf("")))
        assertEquals("Annulé, déjà fait : allumer la lampe", Annulation.message(listOf("allumer la lampe")))
        assertEquals("Annulé, déjà fait : A, B", Annulation.message(listOf("A", "B")))
        assertEquals("annulé par un appui", Annulation.detail(""))
        assertEquals("Assist, annulé par un appui", Annulation.detail("Assist"))
    }
}
