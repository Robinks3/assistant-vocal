package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Mode développeur : actif par défaut, bascule, et ce que chaque texte devient quand il est coupé. */
class ModeDeveloppeurTest {

    @Test
    fun actifParDefautQuandLaCleNAJamaisEteEnregistree() {
        assertTrue(ModeDeveloppeur.DEFAUT)
        assertTrue(ModeDeveloppeur.valeur(null))
    }

    @Test
    fun uneValeurEnregistreeEstRespectee() {
        assertFalse(ModeDeveloppeur.valeur(false))
        assertTrue(ModeDeveloppeur.valeur(true))
    }

    @Test
    fun uneSeuleCleDansLesPreferencesDeLInterface() {
        assertEquals("mode_developpeur", ModeDeveloppeur.CLE)
        assertEquals("interface", ModeDeveloppeur.PREFS)
    }

    @Test
    fun laVersionDisparaitQuandOnCoupe() {
        assertEquals("Version 0.48.0", ModeDeveloppeur.libelleVersion(true, "Version 0.48.0"))
        assertEquals("", ModeDeveloppeur.libelleVersion(false, "Version 0.48.0"))
    }

    @Test
    fun laCameraNeDitPlusLesMillisecondesMaisGardeSesErreurs() {
        val detail = "Vision sur le PC, 42 ms par image, 12 images/s"
        assertEquals(detail, ModeDeveloppeur.visionEtat(true, detail, "ok"))
        assertEquals("Caméra active", ModeDeveloppeur.visionEtat(false, detail, "ok"))
        assertEquals("Caméra active", ModeDeveloppeur.visionEtat(false, detail, "attente"))
        assertEquals("Caméra injoignable", ModeDeveloppeur.visionEtat(false, "Caméra injoignable", "erreur"))
    }

    @Test
    fun laDureeDeLaReponseDisparait() {
        assertEquals("Répondu en 1,2 s", ModeDeveloppeur.dureeReponse(true, "Répondu en 1,2 s"))
        assertEquals("", ModeDeveloppeur.dureeReponse(false, "Répondu en 1,2 s"))
    }

    @Test
    fun leSeuilDuReveilNEstChiffreQuEnModeDeveloppeur() {
        assertEquals("Seuil de réveil : 0,45", ModeDeveloppeur.seuilReveil(true, "0,45"))
        assertEquals("Sensibilité du réveil", ModeDeveloppeur.seuilReveil(false, "0,45"))
    }

    @Test
    fun leServeurSeResumeEnConnecteOuNonConnecte() {
        val detail = "Serveur 0.48.0 via la passerelle, 12 ms"
        assertEquals(detail, ModeDeveloppeur.serveurEtat(true, true, detail))
        assertEquals("Connecté", ModeDeveloppeur.serveurEtat(false, true, detail))
        assertEquals("Non connecté", ModeDeveloppeur.serveurEtat(false, false, detail))
    }

    @Test
    fun leDetailDeConnexionDisparait() {
        assertEquals("ws://x : fermée (1006)", ModeDeveloppeur.detailConnexion(true, "ws://x : fermée (1006)"))
        assertEquals("", ModeDeveloppeur.detailConnexion(false, "ws://x : fermée (1006)"))
    }
}
