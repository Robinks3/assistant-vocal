package assistant.vocal.jarvis

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

/** Santé en un coup d'œil sur l'accueil (0.26.0) : dates, 7 jours, anneau, barres, courbe, garde de confidentialité. Valeurs inventées. */
class SanteAccueilTest {

    private val jour = LocalDate.of(2026, 10, 23)

    private fun reponse(date: String, pas: Int?, nuit: Int?, cetteNuit: Boolean = true, joursJson: String = SEPT_JOURS) = JSONObject(
        """{"etat": "sante", "id": 1, "donnees": {"date": "$date", "lu_a": "${date}T07:10:00",
           "nuit": {"date": "$date", "cette_nuit": $cetteNuit, "minutes": ${nuit ?: "null"}},
           "aujourdhui": {"date": "$date", "pas": ${pas ?: "null"}}, "jours": $joursJson}}""",
    )

    @Test
    fun septJoursParDateEtHeureDeLecture() {
        val r = Sante.lire(reponse("2026-10-23", 5320, 425), jour)!!
        assertEquals(5320, r.pas)
        assertEquals(425, r.sommeilMinutes)
        assertEquals(listOf(400, 440, 350, 465, 415, 490, 425), r.nuits)
        assertEquals(listOf(56, 55, 57, 54, 55, 53, 54), r.coeur)
        assertEquals("7 h 10", r.luA)
    }

    @Test
    fun uneReponseDHierNeDonneJamaisLesPasNiLaNuitDuJour() {
        // Après minuit, le message porte encore la journée du 22 : l'anneau passe à « 0 », la nuit à « pas reçue ».
        val r = Sante.lire(reponse("2026-10-22", 9000, 470, joursJson = SEPT_JOURS_HIER), jour)!!
        assertNull(r.pas)
        assertNull(r.sommeilMinutes)
        // Les jours sont recalés sur aujourd'hui : celui du 23 manque, le 22 devient l'avant-dernier.
        assertNull(r.nuits.last())
        assertNull(r.coeur.last())
        assertEquals(425, r.nuits[5])
        // Une nuit qui n'est pas celle qui vient de finir passe en « pas reçue », même si le reste est d'aujourd'hui.
        assertNull(Sante.lire(reponse("2026-10-23", 5320, 425, cetteNuit = false), jour)!!.sommeilMinutes)
    }

    @Test
    fun anneauFermeAuDelaDeLObjectif() {
        assertEquals(0f, CoupDOeilSante.fractionPas(null))
        assertEquals(0f, CoupDOeilSante.fractionPas(0))
        assertEquals(0.5f, CoupDOeilSante.fractionPas(3000), 1e-6f)
        // Au-delà de 6 000 : anneau fermé, sans second tour.
        assertEquals(1f, CoupDOeilSante.fractionPas(14_000))
    }

    @Test
    fun barresDesNuitsEtJoursManquants() {
        val b = CoupDOeilSante.barresNuits(listOf(400, null, 350, 600, 415, null, null))
        assertEquals(CoupDOeilSante.Genre.AUTRE, b[0].genre)
        assertEquals(CoupDOeilSante.Genre.MANQUE, b[1].genre)
        // Une nuit de 10 h est écrêtée à 9 h, en haut du graphe.
        assertEquals(1f, b[3].hauteur)
        // La nuit de ce matin pas encore reçue : case pointillée, jamais une barre inventée.
        assertEquals(CoupDOeilSante.Genre.JOUR_ABSENT, b[6].genre)
        assertEquals(CoupDOeilSante.Genre.JOUR, CoupDOeilSante.barresNuits(listOf(400, 425))[1].genre)
        assertTrue(CoupDOeilSante.assez(listOf(1, null, 2, null, 3)))
        assertFalse(CoupDOeilSante.assez(listOf(1, null, null, null, 2)))
    }

    @Test
    fun courbeDuCoeurBorneeEtCoupee() {
        // Moyenne 55 : 54 et 56 restent près du milieu, une petite variation ne paraît jamais dramatique.
        val t = CoupDOeilSante.courbe(listOf(55, 54, 56, 55, 55, 55, 55))
        assertEquals(1, t.size)
        assertEquals(0.6f, t[0][1].second, 1e-6f)
        assertEquals(0.4f, t[0][2].second, 1e-6f)
        // Hors échelle (plus de 5 bpm de la moyenne) : borné au bord.
        val h = CoupDOeilSante.courbe(listOf(50, 50, 50, 50, 50, 50, 80))
        assertEquals(0f, h[0].last().second, 1e-6f)
        // Un jour manquant coupe la courbe en deux tronçons.
        assertEquals(2, CoupDOeilSante.courbe(listOf(55, 54, null, 56, 55, 55, 55)).size)
        assertTrue(CoupDOeilSante.courbe(listOf(null, null)).isEmpty())
    }

    @Test
    fun garde_leBlocNeSeMontreQuePourSachaSeulEnVivantPlein() {
        val r = Sante.Resume(425, 5320, listOf(400, 425), listOf(55, 54))
        assertTrue(Sante.montreAccueil(proprietaireSeul = true, vivant = true, actif = true, repos = true, r = r))
        // Un autre visage arrive ou l'identité est périmée : Garde rend faux, le bloc quitte l'écran aussitôt.
        assertFalse(Sante.montreAccueil(proprietaireSeul = false, vivant = true, actif = true, repos = true, r = r))
        // Jamais en retrait, en AOD ni écran éteint, ni pendant l'écoute.
        assertFalse(Sante.montreAccueil(proprietaireSeul = true, vivant = true, actif = false, repos = true, r = r))
        assertFalse(Sante.montreAccueil(proprietaireSeul = true, vivant = false, actif = true, repos = true, r = r))
        assertFalse(Sante.montreAccueil(proprietaireSeul = true, vivant = true, actif = true, repos = false, r = r))
        // Aucune donnée : rien, comme pour un invité.
        assertFalse(Sante.montreAccueil(proprietaireSeul = true, vivant = true, actif = true, repos = true, r = null))
        assertFalse(Sante.montreAccueil(proprietaireSeul = true, vivant = true, actif = true, repos = true, r = Sante.Resume(null, null, listOf(null), listOf(null))))
    }

    @Test
    fun garde_unAutreVisageAnnuleLaSanteSurLImageMeme() {
        // Garde (0.21.1) : Sacha seul et sûr, puis un inconnu sur l'image suivante : faux tout de suite.
        val g = Sante.Garde()
        val sacha = listOf(PersonneVue(1, "p1", "Sacha", true, sur = true))
        val avecInvite = listOf(PersonneVue(1, "p1", "Sacha", true, sur = true), PersonneVue(2, null, null, true, inconnu = true))
        assertTrue(g.voir(sacha, 1_000L, 1_100L))
        assertFalse(g.voir(avecInvite, 1_200L, 1_250L))
        val r = Sante.Resume(425, 5320)
        assertFalse(Sante.montreAccueil(g.voir(avecInvite, 1_200L, 1_300L), vivant = true, actif = true, repos = true, r = r))
    }

    @Test
    fun libelleSansChiffreQuandRienNEstRecu() {
        assertEquals("Ouvrir la santé : pas encore de pas, nuit pas encore reçue", VueSanteAccueil.libelle(Sante.Resume(null, 0)))
    }

    companion object {
        private const val SEPT_JOURS = """[
            {"date": "2026-10-17", "sommeil_minutes": 400, "fc_repos": 56},
            {"date": "2026-10-18", "sommeil_minutes": 440, "fc_repos": 55},
            {"date": "2026-10-19", "sommeil_minutes": 350, "fc_repos": 57},
            {"date": "2026-10-20", "sommeil_minutes": 465, "fc_repos": 54},
            {"date": "2026-10-21", "sommeil_minutes": 415, "fc_repos": 55},
            {"date": "2026-10-22", "sommeil_minutes": 490, "fc_repos": 53},
            {"date": "2026-10-23", "sommeil_minutes": 425, "fc_repos": 54}]"""
        private val SEPT_JOURS_HIER = (16..22).joinToString(",", "[", "]") { d ->
            """{"date": "2026-10-$d", "sommeil_minutes": ${if (d == 22) 425 else 400}, "fc_repos": 55}"""
        }
    }
}
