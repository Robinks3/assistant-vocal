package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

/** Historique lisible et sans doublon (0.17.0). */
class HistoriqueLisibleTest {

    private val noms = mapOf(
        "light.exemple6" to "Salon",
        "light.cuisine" to "Cuisine",
        "light.exemple7" to "Lampe TV",
        "media_player.chambre" to "Cuisine",
    )

    @Test
    fun nomsDesAppareilsEtVerbe() {
        // La ligne vue sur la tablette le 21/10 à 23:27:38.
        assertEquals("Salon et Cuisine : éteintes", HistoriqueLisible.ligne("light.turn_off light.exemple6 light.cuisine", noms))
        assertEquals("Lampe TV : luminosité 40 %", HistoriqueLisible.ligne("light.turn_on light.exemple7 (brightness_pct=40)", noms))
        assertEquals("Cuisine : pause", HistoriqueLisible.ligne("media_player.media_pause media_player.chambre", noms))
        // Nom inconnu : tiré de l'identifiant.
        assertEquals("Entree entree : allumée", HistoriqueLisible.ligne("light.turn_on light.exemple17", noms))
    }

    @Test
    fun mentionsGardees() {
        assertEquals("Salon : allumée (essai, rien n'a été envoyé)",
            HistoriqueLisible.ligne("light.turn_on light.exemple6 (non exécuté, essai)", noms))
        assertEquals("Salon : allumée (refusé : pas de son)",
            HistoriqueLisible.ligne("light.turn_on light.exemple6 (refusé : pas de son)", noms))
        assertEquals("Salon : allumée (écartée)", HistoriqueLisible.ligne("light.turn_on light.exemple6 (écartée)", noms))
    }

    @Test
    fun rienDeCamilleEnClair() {
        org.junit.Assume.assumeTrue("règle levée le 22/10/2026", Securite.PROTEGER_OCCUPANT)
        val l = HistoriqueLisible.ligne("light.turn_on light.chambre_camille (refusé : je ne touche jamais à ce qui appartient à Camille (sécurité))", noms)
        assertFalse(l.lowercase().contains("chambre camille"))
        assertEquals("Appareil protégé : allumée (refusé : je ne touche jamais à ce qui appartient à Camille (sécurité))", l)
    }

    @Test
    fun refusAvecParenthesesImbriquees() {
        // Raison écrite par MoteurLocal, qui finit par « (sécurité) ».
        assertEquals("Salon : allumée (refusé : pas de son dans le salon entre minuit et 9 h (sécurité))",
            HistoriqueLisible.ligne("light.turn_on light.exemple6 (refusé : pas de son dans le salon entre minuit et 9 h (sécurité))", noms))
        assertEquals("Salon : allumée (refusé)", HistoriqueLisible.ligne("light.turn_on light.exemple6 (refusé)", noms))
    }

    @Test
    fun ligneInconnueGardee() {
        assertEquals("rien fait (personne non reconnue)", HistoriqueLisible.ligne("rien fait (personne non reconnue)", noms))
    }

    @Test
    fun doublonsRetires() {
        fun e(heure: String, entendu: String, id: String = "") =
            Etat.EntreeHistorique("2026-10-21", heure, false, entendu, "dictionnaire", "", emptyList(), false, "C'est fait.", "0,4 s", id)
        val l = listOf(e("23:27:38", "Éteins le salon"), e("23:27:38", "éteins le salon ", "1"), e("23:20:00", "Éteins le salon"))
        val s = HistoriqueLisible.sansDoublons(l)
        assertEquals(2, s.size)
        assertEquals("23:27:38", s[0].heure)
        assertEquals("23:20:00", s[1].heure)
    }
}
