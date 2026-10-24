package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Test

/** Mot de réveil de la configuration (0.30.0) : config-exemple/ n'en fournit pas, seul Hey Jarvis existe. */
class ReveilConfigTest {
    @Test
    fun sansSectionReveilSeulHeyJarvis() {
        assertFalse(ReveilLocal.PERSO_DISPONIBLE)
        assertEquals("hey_jarvis_v0.1.onnx", ReveilLocal.fichier(ReveilLocal.PERSO))
        assertEquals("Hey Jarvis", ReveilLocal.nom(ReveilLocal.PERSO))
        assertEquals("hey_jarvis_v0.1.onnx", ReveilLocal.fichier(ReveilLocal.HEY_JARVIS))
    }
}
