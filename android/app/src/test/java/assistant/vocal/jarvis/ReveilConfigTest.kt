package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Mot de réveil de la configuration (0.37.3) : config-exemple/ décrit le mot « assistant » (décision D5), et
 *  « Hey Jarvis » reste le modèle de repli du dépôt. */
class ReveilConfigTest {
    @Test
    fun motDeLaConfigurationParDefaut() {
        assertTrue(ReveilLocal.PERSO_DISPONIBLE)
        assertEquals("assistant.onnx", ReveilLocal.fichier(ReveilLocal.PERSO))
        assertEquals("Assistant", ReveilLocal.nom(ReveilLocal.PERSO))
    }

    @Test
    fun heyJarvisResteLeModeleDeRepli() {
        assertEquals("hey_jarvis_v0.1.onnx", ReveilLocal.fichier(ReveilLocal.HEY_JARVIS))
        assertEquals("Hey Jarvis", ReveilLocal.nom(ReveilLocal.HEY_JARVIS))
    }
}
