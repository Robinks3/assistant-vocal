package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

/** Seconde passe de l'accueil (0.24.0) : zones du plan, intensité, arrêt de la musique, volume visé, textes courts. */
class AccueilDispositionTest {

    @Test
    fun zonesDeLaMaquette() {
        assertEquals(Disposition.A, Disposition.zone(musique = false, ecoute = false, decale = false))
        assertEquals(Disposition.B, Disposition.zone(musique = true, ecoute = false, decale = false))
        assertEquals(Disposition.ECOUTE_A, Disposition.zone(musique = false, ecoute = true, decale = false))
        assertEquals(Disposition.ECOUTE_B, Disposition.zone(musique = true, ecoute = true, decale = false))
        // Un jour sur deux, la moitié droite se décale de 24 px de maquette (0,019 de la largeur).
        assertEquals(0.5f + 24f / 1280f, Disposition.zone(musique = false, ecoute = false, decale = true).x, 1e-6f)
        // L'écoute resserre la zone autour du même centre : l'orbe naît là où était le plan.
        assertEquals(Disposition.A.centreX, Disposition.ECOUTE_A.centreX, 1f)
        assertEquals(Disposition.A.centreY, Disposition.ECOUTE_A.centreY, 1f)
        assertEquals(Disposition.B.centreY, Disposition.ECOUTE_B.centreY, 1f)
        // Toutes les zones tiennent dans la fenêtre, décalées comprises.
        for (m in listOf(true, false)) for (e in listOf(true, false)) {
            val z = Disposition.zone(m, e, decale = true)
            assertTrue(z.x + z.largeur <= 1f && z.y + z.hauteur <= 1f)
        }
    }

    @Test
    fun intensiteEtOrbe() {
        assertEquals(1f, Disposition.intensite(jour = true, nuit = false))
        assertEquals(0.2f, Disposition.intensite(jour = false, nuit = false))
        assertEquals(0.15f, Disposition.intensite(jour = false, nuit = true))
        assertEquals(200f, Disposition.diametreOrbe(musique = false, soir = false))
        assertEquals(170f, Disposition.diametreOrbe(musique = true, soir = false))
        assertEquals(170f, Disposition.diametreOrbe(musique = false, soir = true))
    }

    @Test
    fun arretDeLaMusique() {
        val s = SuiviMusique()
        assertEquals(SuiviMusique.Phase.ABSENT, s.avancer(joue = false, connu = false, maintenant = 0L))
        assertEquals(SuiviMusique.Phase.JOUE, s.avancer(joue = true, connu = true, maintenant = 1_000L))
        // Arrêt, même si le lecteur disparaît de la liste : 30 s sans rien changer, puis 10 min en pause.
        assertEquals(SuiviMusique.Phase.GRACE, s.avancer(joue = false, connu = false, maintenant = 2_000L))
        assertEquals(SuiviMusique.Phase.GRACE, s.avancer(joue = false, connu = false, maintenant = 31_999L))
        assertEquals(SuiviMusique.Phase.PAUSE, s.avancer(joue = false, connu = false, maintenant = 32_000L))
        // Reprise dans les 10 min : le bloc se rallume.
        assertEquals(SuiviMusique.Phase.JOUE, s.avancer(joue = true, connu = true, maintenant = 300_000L))
        s.avancer(joue = false, connu = true, maintenant = 400_000L)
        assertEquals(SuiviMusique.Phase.PAUSE, s.avancer(joue = false, connu = true, maintenant = 400_000L + 30_000L + 599_999L))
        assertEquals(SuiviMusique.Phase.ABSENT, s.avancer(joue = false, connu = true, maintenant = 400_000L + 30_000L + 600_000L))
        // Une fois parti, un lecteur en pause qui reste dans la liste ne fait pas revenir le bloc...
        assertEquals(SuiviMusique.Phase.ABSENT, s.avancer(joue = false, connu = true, maintenant = 2_000_000L))
        assertFalse(s.montre(SuiviMusique.Phase.ABSENT))
        assertTrue(s.montre(SuiviMusique.Phase.PAUSE))
    }

    @Test
    fun volumeViseParPasDeCinq() {
        val v = VolumeVise()
        // Trois touchers rapides sur plus : de 30 à 45 %, cumulés sur la valeur affichée.
        assertEquals(0.35, v.pas(0.30, +1, 0L)!!, 1e-9)
        assertEquals(0.40, v.pas(0.30, +1, 100L)!!, 1e-9)
        assertEquals(0.45, v.pas(0.30, +1, 200L)!!, 1e-9)
        assertEquals(0.45, v.affiche(0.30, 1_000L), 1e-9)
        // Home Assistant confirme : la valeur lue reprend la main.
        v.lu(0.45)
        assertEquals(0.44, v.affiche(0.44, 1_100L), 1e-9)
        // Sans confirmation, la visée s'efface au bout de 3 s.
        v.pas(0.30, -1, 2_000L)
        assertEquals(0.25, v.affiche(0.30, 4_999L), 1e-9)
        assertEquals(0.30, v.affiche(0.30, 5_000L), 1e-9)
    }

    @Test
    fun volumeJamaisAuDelaDuMaximum() {
        // config-exemple règle plafond_volume à 100, comme la configuration du propriétaire : la piste va jusqu'à 100 %.
        assertEquals(1.0, Securite.VOLUME_MAX, 1e-9)
        assertEquals(1.0, VolumeVise.MAX, 1e-9)
        val v = VolumeVise()
        assertNull(v.pas(1.0, +1, 0L))
        assertEquals(1.0, v.pas(0.98, +1, 0L)!!, 1e-9)
        assertNull(VolumeVise().pas(0.0, -1, 0L))
        // Plus de plafond de 50 % : une enceinte à 70 % monte encore.
        assertEquals(0.75, VolumeVise().pas(0.70, +1, 0L)!!, 1e-9)
        assertEquals(0.65, VolumeVise().pas(0.70, -1, 0L)!!, 1e-9)
        assertEquals(0.9, VolumeVise().glisser(0.9, 0L), 1e-9)
        assertEquals(1.0, VolumeVise().glisser(1.2, 0L), 1e-9)
    }

    @Test
    fun volumeSousUnPlafondConfigure() {
        // Plafond de 50 % : plus s'arrête au plafond, la piste aussi.
        val v = VolumeVise(max = 0.5)
        assertNull(v.pas(0.5, +1, 0L))
        assertEquals(0.5, VolumeVise(max = 0.5).pas(0.48, +1, 0L)!!, 1e-9)
        assertEquals(0.5, VolumeVise(max = 0.5).glisser(0.9, 0L), 1e-9)
        assertEquals(0.4, VolumeVise(max = 0.5).pas(0.45, -1, 0L)!!, 1e-9)
        // Plafond de 72,5 % : borné après l'arrondi, jamais 0,73.
        assertEquals(0.725, VolumeVise(max = 0.725).pas(0.70, +1, 0L)!!, 1e-9)
        assertEquals(0.725, VolumeVise(max = 0.725).glisser(0.8, 0L), 1e-9)
        assertNull(VolumeVise(max = 0.725).pas(0.725, +1, 0L))
        // Plafond de 0 % : le son reste coupé.
        assertNull(VolumeVise(max = 0.0).pas(0.0, +1, 0L))
        assertEquals(0.0, VolumeVise(max = 0.0).glisser(0.6, 0L), 1e-9)
        // Groupe d'enceintes sous un plafond de 72,5 %.
        val g = VolumeVise.groupe(mapOf("salon" to 0.70, "cuisine" to 0.60), avant = 0.70, apres = 0.80, max = 0.725)
        assertEquals(0.725, g.getValue("salon"), 1e-9)
        assertEquals(0.70, g.getValue("cuisine"), 1e-9)
    }

    @Test
    fun fractionSousUnPlafondConfigure() {
        assertEquals(0.6, VolumeVise.fraction(0.3, 0.5), 1e-9)
        assertEquals(1.0, VolumeVise.fraction(0.5, 0.5), 1e-9)
        assertEquals(1.0, VolumeVise.fraction(0.9, 0.5), 1e-9)
        assertEquals(1.0, VolumeVise.fraction(0.725, 0.725), 1e-9)
        assertEquals(0.0, VolumeVise.fraction(0.4, 0.0), 1e-9)
    }

    @Test
    fun fractionDeLaPiste() {
        // Sans plafond, la piste couvre tout le volume.
        assertEquals(0.3, VolumeVise.fraction(0.3), 1e-9)
        assertEquals(1.0, VolumeVise.fraction(1.4), 1e-9)
        assertEquals(0.0, VolumeVise.fraction(-0.1), 1e-9)
        assertEquals(0.0, VolumeVise.fraction(Double.NaN), 1e-9)
    }

    @Test
    fun volumeDUnGroupeParDecalage() {
        val r = VolumeVise.groupe(mapOf("salon" to 0.30, "cuisine" to 0.20), avant = 0.30, apres = 0.40)
        assertEquals(0.40, r["salon"]!!, 1e-9)
        assertEquals(0.30, r["cuisine"]!!, 1e-9)
        // Chaque enceinte est bornée pour elle-même au volume permis (100 % sans plafond).
        val p = VolumeVise.groupe(mapOf("salon" to 0.95, "cuisine" to 0.98), avant = 0.98, apres = 1.0)
        assertEquals(0.97, p["salon"]!!, 1e-9)
        assertEquals(1.0, p["cuisine"]!!, 1e-9)
    }

    @Test
    fun textesCourts() {
        assertEquals("Jeu. 22 oct.", TextesCourts.date(LocalDate.of(2026, 10, 22)))
        assertEquals("Dim. 1er mars", TextesCourts.date(LocalDate.of(2026, 3, 1)))
        assertEquals("21°", TextesCourts.temperature(Etat.Meteo("20,6 °C", "Éclaircies")))
        assertEquals("-3°", TextesCourts.temperature(Etat.Meteo("-3.2", "Neige")))
        assertEquals("", TextesCourts.temperature(null))
        assertEquals("pluie 17 h", TextesCourts.pluie("Pluie vers 17 h."))
        assertEquals("neige 6 h", TextesCourts.pluie("Neige vers 6 h."))
        assertEquals("pluie en ce moment", TextesCourts.pluie("Pluie en ce moment."))
        assertEquals("", TextesCourts.pluie(""))
        assertEquals("7 h 05", TextesCourts.sommeil(425))
        assertEquals("5 320", TextesCourts.pas(5320))
        assertEquals("Maison hors ligne depuis 10 h 02", TextesCourts.panne("Home Assistant ne répond plus", 10, 2))
        assertEquals("Caméra indisponible", TextesCourts.panne("Caméra indisponible", null, null))
        assertEquals("30 %", TextesCourts.pourcent(0.3))
    }

    @Test
    fun libelleDuVolume() {
        fun l(id: String, membres: Set<String> = emptySet()) = Etat.Lecteur(id, "Enceintes", "playing", "", "", "", 0.0, 0.0, 0L, 0.3, membres)
        assertEquals("Volume du salon", TextesCourts.volume(l("media_player.barre_son_salon")))
        assertEquals("Volume du salon et de la cuisine", TextesCourts.volume(l("media_player.barre_son_salon", setOf("media_player.enceinte_cuisine"))))
        assertEquals("Volume", TextesCourts.volume(l("media_player.autre")))
    }
}
