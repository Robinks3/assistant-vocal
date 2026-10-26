package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** S-D5 (I11) : les extras `test_*` de MainActivity ne sont lus que dans un build de débogage. */
class LectureExtrasTest {

    private val extras = mapOf(
        "test_reveil" to "hey", "test_llm" to "bonjour", "modele" to "gemma", "test_canary" to "oui",
    )

    /** Compte les lectures, pour prouver qu'un build de publication ne touche pas à l'intention. */
    private class Intention(val valeurs: Map<String, String>, val fils: Int = 8) {
        var lectures = 0
        fun texte(cle: String): String? { lectures++; return valeurs[cle] }
        fun entier(cle: String, defaut: Int): Int { lectures++; return if (cle == "fils") fils else defaut }
    }

    @Test
    fun debugVraiLesExtrasSontLus() {
        val i = Intention(extras)
        val d = ExtrasTest.lisibles(true, i::texte, i::entier)
        assertEquals("hey", d.reveil)
        assertEquals("bonjour", d.llm)
        assertEquals("gemma", d.modele)
        assertEquals("oui", d.canary)
        assertEquals(8, d.fils)
        assertFalse(d.vide)
    }

    @Test
    fun debugFauxLesExtrasSontIgnores() {
        val i = Intention(extras)
        val d = ExtrasTest.lisibles(false, i::texte, i::entier)
        assertNull(d.reveil)
        assertNull(d.llm)
        assertNull(d.modele)
        assertNull(d.canary)
        assertEquals(ExtrasTest.FILS_PAR_DEFAUT, d.fils)
        assertTrue(d.vide)
        assertEquals("l'intention n'est pas même lue", 0, i.lectures)
    }

    @Test
    fun debugVraiSansExtraRienNEstDemande() {
        val i = Intention(emptyMap())
        val d = ExtrasTest.lisibles(true, i::texte, i::entier)
        assertTrue(d.vide)
        assertEquals(8, d.fils)
    }

    @Test
    fun lesNomsDesExtrasSontCeuxDeAdb() {
        assertEquals("test_reveil", ExtrasTest.REVEIL)
        assertEquals("test_llm", ExtrasTest.LLM)
        assertEquals("test_canary", ExtrasTest.CANARY)
        assertEquals("modele", ExtrasTest.MODELE)
        assertEquals("fils", ExtrasTest.FILS)
    }
}
