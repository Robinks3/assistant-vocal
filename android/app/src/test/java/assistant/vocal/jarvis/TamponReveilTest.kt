package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class TamponReveilTest {

    private fun bloc(valeur: Int, taille: Int = 4) = ShortArray(taille) { valeur.toShort() }

    @Test
    fun garde_les_blocs_dans_l_ordre_avant_de_deborder() {
        val t = TamponReveil(capacite = 3, taille = 4)
        t.ajouter(bloc(1), -40f)
        t.ajouter(bloc(2), -30f)
        val i = t.instantane()
        assertEquals(2, i.blocs)
        assertEquals(8, i.pcm.size)
        assertEquals(1.toShort(), i.pcm[0])
        assertEquals(2.toShort(), i.pcm[7])
        assertEquals(-40f, i.db[0])
    }

    @Test
    fun ecrase_le_plus_ancien_quand_il_est_plein() {
        val t = TamponReveil(capacite = 3, taille = 4)
        for (k in 1..5) t.ajouter(bloc(k), k.toFloat())
        val i = t.instantane()
        assertEquals(3, i.blocs)
        assertEquals(listOf<Short>(3, 4, 5), (0 until 3).map { i.pcm[it * 4] })
        assertEquals(listOf(3f, 4f, 5f), i.db.toList())
    }

    @Test
    fun noter_annote_le_dernier_bloc_seulement() {
        val t = TamponReveil(capacite = 3, taille = 4)
        t.ajouter(bloc(1), 0f)
        t.ajouter(bloc(2), 0f)
        t.noter(0.7f, 0.9f, TamponReveil.PHASE_REPOS)
        val i = t.instantane()
        assertTrue(i.scores[0].isNaN())
        assertEquals(0.7f, i.scores[1])
        assertEquals(0.9f, i.vad[1])
        assertEquals("?R", i.phases)
    }

    @Test
    fun noter_puis_renoter_garde_la_derniere_valeur() {
        val t = TamponReveil(capacite = 2, taille = 4)
        t.ajouter(bloc(1), 0f)
        t.noter(Float.NaN, Float.NaN, TamponReveil.PHASE_REPOS)
        t.noter(0.4f, 0.2f, TamponReveil.PHASE_REPOS)
        assertEquals(0.4f, t.instantane().scores[0])
    }

    @Test
    fun noter_sans_bloc_ne_fait_rien_et_vider_remet_a_zero() {
        val t = TamponReveil(capacite = 2, taille = 4)
        t.noter(0.5f, 0.5f, TamponReveil.PHASE_REPOS)
        assertEquals(0, t.instantane().blocs)
        t.ajouter(bloc(9), 0f)
        t.vider()
        assertEquals(0, t.blocs)
        t.ajouter(bloc(3), 0f)
        assertEquals(3.toShort(), t.instantane().pcm[0])
    }

    @Test
    fun trente_secondes_par_defaut() {
        val t = TamponReveil()
        assertEquals(30.0, t.capacite * t.taille / 16000.0, 1e-9)
    }
}
