package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** Lecture des chemins SVG des pictos (0.20.0). */
class CheminSvgTest {

    @Test
    fun lignesRelativesEtFermeture() {
        val p = CheminSvg.lire("M16 3v3M3 16h3M6.8 6.8l2.1 2.1")
        assertEquals(CheminSvg.Pas.Aller(16f, 3f), p[0])
        assertEquals(CheminSvg.Pas.Ligne(16f, 6f), p[1])
        assertEquals(CheminSvg.Pas.Aller(3f, 16f), p[2])
        assertEquals(CheminSvg.Pas.Ligne(6f, 16f), p[3])
        val d = p[5] as CheminSvg.Pas.Ligne
        assertEquals(8.9f, d.x, 1e-4f)
        assertEquals(8.9f, d.y, 1e-4f)
        val z = CheminSvg.lire("M8 22a8 8 0 0 1 16 0Z")
        assertTrue(z.last() === CheminSvg.Pas.Fermer)
    }

    @Test
    fun arcEnCourbesQuiFinissentAuBonPoint() {
        // Demi-cercle de rayon 8 de (8, 22) à (24, 22) : deux quarts, le sommet en (16, 14).
        val p = CheminSvg.lire("M8 22a8 8 0 0 1 16 0")
        val courbes = p.filterIsInstance<CheminSvg.Pas.Courbe>()
        assertEquals(2, courbes.size)
        assertEquals(16f, courbes[0].x, 1e-3f)
        assertEquals(14f, courbes[0].y, 1e-3f)
        assertEquals(24f, courbes[1].x, 1e-4f)
        assertEquals(22f, courbes[1].y, 1e-4f)
        // Nombres collés au signe et à la décimale (« .5-10 »), comme dans les maquettes.
        val n = CheminSvg.lire("M11 26h13a5 5 0 0 0 .5-10A7.5 7.5 0 0 0 10.2 17.5 4.3 4.3 0 0 0 11 26Z")
        val fin = n.filterIsInstance<CheminSvg.Pas.Courbe>().last()
        assertEquals(11f, fin.x, 1e-4f)
        assertEquals(26f, fin.y, 1e-4f)
    }

    @Test
    fun courbeCubiqueEtCourte() {
        val p = CheminSvg.lire("M1 3h7.5a2 2 0 1 0-2-2M1 7h10a1.8 1.8 0 1 1-1.8 1.8")
        assertEquals(CheminSvg.Pas.Ligne(8.5f, 3f), p[1])
        assertTrue(p.any { it is CheminSvg.Pas.Courbe })
    }
}
