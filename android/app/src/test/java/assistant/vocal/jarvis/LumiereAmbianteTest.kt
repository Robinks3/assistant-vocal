package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Luminosité de l'écran selon la lumière de la pièce (0.28.0) : courbe, médiane, hystérésis, lissage, repli. */
class LumiereAmbianteTest {

    @Test
    fun courbe_passeParLesPointsMesures_etMonteToujours() {
        assertEquals(0.06f, LumiereAmbiante.courbe(0f), 1e-6f)
        assertEquals(0.35f, LumiereAmbiante.courbe(14f), 1e-6f)
        assertEquals(0.55f, LumiereAmbiante.courbe(200f), 1e-6f)
        assertEquals(0.70f, LumiereAmbiante.courbe(50_000f), 1e-6f)
        var avant = -1f
        for (lux in listOf(0f, 0.5f, 1f, 2f, 3f, 8f, 14f, 30f, 60f, 120f, 200f, 500f, 1_000f, 5_000f)) {
            val v = LumiereAmbiante.courbe(lux)
            assertTrue("$lux lux : $v après $avant", v > avant || v == 0.70f)
            assertTrue(v in LumiereAmbiante.PLANCHER..LumiereAmbiante.MAXI)
            avant = v
        }
        // Séjour tout allumé le soir : bien plus que les 10 % de la règle de l'heure, grand jour plus que 40 %.
        assertTrue(LumiereAmbiante.courbe(14f) > Veille.LUMINOSITE_NUIT * 3)
        assertTrue(LumiereAmbiante.courbe(200f) > Veille.LUMINOSITE_PLAFOND)
    }

    @Test
    fun sansCapteur_laRegleDeLHeure() {
        val l = LumiereAmbiante()
        assertFalse(l.disponible)
        assertEquals(Veille.LUMINOSITE_NUIT, l.plafond(0L, nuit = true), 0f)
        assertEquals(Veille.LUMINOSITE_PLAFOND, l.plafond(0L, nuit = false), 0f)
        assertNull(l.sombre())
    }

    @Test
    fun reveil_lEstimationTient_puisLaPremiereMesureSansHysteresis() {
        val l = LumiereAmbiante()
        l.mesure(14f, 0L)
        assertEquals(0.35f, l.plafond(0L, nuit = true), 1e-6f)
        // Activité arrêtée puis reprise : pas de creux vers les 10 % de la nuit en attendant la première mesure.
        l.oublier()
        l.attendre(60_000L)
        assertEquals(0.35f, l.plafond(60_300L, nuit = true), 1e-6f)
        // Première mesure : pièce noire, retenue tout de suite, la consigne descend lentement.
        l.mesure(0f, 60_400L)
        val v = l.plafond(61_400L, nuit = true)
        assertEquals(0.35f - LumiereAmbiante.DESCENTE_PAR_S * 1.1f, v, 1e-4f)
        assertEquals(0f, l.luxRetenu!!, 0f)
        assertTrue(l.enTransition)
        // Capteur muet après le réveil : au-delà de l'attente, la règle de l'heure.
        val m = LumiereAmbiante()
        m.mesure(14f, 0L)
        m.plafond(0L, true)
        m.oublier()
        m.attendre(10_000L)
        assertEquals(Veille.LUMINOSITE_NUIT, m.plafond(12_000L, nuit = true), 0f)
    }

    @Test
    fun ombrePuisLampe_aucuneNaTenu4s_rienNEstRetenu() {
        val l = LumiereAmbiante()
        l.mesure(14f, 0L)
        val avant = l.plafond(0L, false)
        // 3 s d'ombre (2 lux) puis 3 s de lampe de téléphone (200 lux), puis retour à 14 lux.
        l.mesure(2f, 10_000L)
        for (t in 10_000L..13_000L step 250L) l.plafond(t, false)
        l.mesure(200f, 13_000L)
        for (t in 13_000L..16_000L step 250L) l.plafond(t, false)
        l.mesure(14f, 16_000L)
        for (t in 16_000L..40_000L step 250L) l.plafond(t, false)
        assertEquals(14f, l.luxRetenu!!, 0f)
        assertEquals(avant, l.plafond(40_000L, false), 1e-6f)
    }

    @Test
    fun premiereMesure_appliqueeTelleQuelle_puisSuitLentement() {
        val l = LumiereAmbiante()
        l.mesure(0f, 0L)
        assertEquals(0.06f, l.plafond(0L, nuit = true), 1e-6f)
        assertEquals(true, l.sombre())
        // On allume le séjour : 14 lux. Rien ne change avant 4 s, puis la consigne monte de 3 points par seconde au plus.
        l.mesure(14f, 1_000L)
        var t = 1_000L
        var v = 0f
        val vues = mutableListOf<Float>()
        while (t <= 30_000L) {
            v = l.plafond(t, nuit = true)
            vues += v
            t += 1_000L
        }
        assertEquals(0.06f, vues[1], 1e-6f)
        for (i in 1 until vues.size) assertTrue("saut de ${vues[i] - vues[i - 1]}", vues[i] - vues[i - 1] <= LumiereAmbiante.MONTEE_PAR_S + 1e-4f)
        assertEquals(0.35f, v, 1e-6f)
        assertEquals(false, l.sombre())
    }

    @Test
    fun lampeDeTelephonePasseeDevant_neChangeRien() {
        val l = LumiereAmbiante()
        l.mesure(14f, 0L)
        l.plafond(0L, false)
        // Un éclair de 1 s à 2 000 lux : la médiane des 4 s ne bouge pas, puis la mesure revient à 14.
        l.mesure(2_000f, 5_000L)
        val pendant = l.plafond(5_500L, false)
        l.mesure(14f, 6_000L)
        for (t in 6_000L..20_000L step 500L) assertEquals(pendant, l.plafond(t, false), 1e-6f)
        assertEquals(14f, l.luxRetenu!!, 0f)
    }

    @Test
    fun quelquunSePenche_moinsDe3s_neChangeRien() {
        val l = LumiereAmbiante()
        l.mesure(14f, 0L)
        val avant = l.plafond(0L, false)
        // Ombre de 2,5 s : 3 lux, puis retour.
        for (t in 10_000L..12_500L step 250L) l.mesure(3f, t)
        for (t in 10_000L..12_500L step 500L) l.plafond(t, false)
        l.mesure(14f, 12_600L)
        for (t in 12_600L..30_000L step 500L) assertEquals(avant, l.plafond(t, false), 1e-6f)
    }

    @Test
    fun petiteVariation_sousLeSeuil_neChangeRien() {
        val l = LumiereAmbiante()
        l.mesure(14f, 0L)
        val avant = l.plafond(0L, false)
        // 14 vers 18 lux : 0,1 décade, sous le seuil de 0,15. Aucun pompage.
        l.mesure(18f, 1_000L)
        for (t in 1_000L..60_000L step 1_000L) assertEquals(avant, l.plafond(t, false), 1e-6f)
    }

    @Test
    fun descente_plusLenteQueLaMontee() {
        val l = LumiereAmbiante()
        l.mesure(200f, 0L)
        assertEquals(0.55f, l.plafond(0L, false), 1e-6f)
        l.mesure(0f, 1_000L)
        val vues = (1_000L..60_000L step 1_000L).map { l.plafond(it, false) }
        for (i in 1 until vues.size) assertTrue(vues[i - 1] - vues[i] <= LumiereAmbiante.DESCENTE_PAR_S + 1e-4f)
        assertEquals(0.06f, vues.last(), 1e-6f)
    }

    @Test
    fun capteurATChangement_laDerniereMesureResteValable() {
        val l = LumiereAmbiante()
        l.mesure(14f, 0L)
        // Une heure sans nouvel événement : la pièce n'a pas changé, la consigne reste celle de 14 lux.
        assertEquals(0.35f, l.plafond(3_600_000L, nuit = true), 1e-6f)
        assertTrue(l.disponible)
    }

    @Test
    fun retraitEtAod_inchanges() {
        val v = Veille()
        v.avancer(0L, presence = true, activiteLe = 0L, occupe = false, nuit = false)
        assertEquals(0.35f, v.luminositeAvec(0.35f), 1e-6f)
        assertEquals(v.luminosite(false), v.luminositeAvec(Veille.LUMINOSITE_PLAFOND), 1e-6f)
        assertEquals(v.luminosite(true), v.luminositeAvec(Veille.LUMINOSITE_NUIT), 1e-6f)
    }
}
