package assistant.vocal.jarvis

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Santé de Sacha sur l'accueil (0.19.0) : lecture défensive, phrases, qui la voit, mémoire de 10 min. */
class SanteTest {

    private fun reponse(donnees: String) = JSONObject("""{"etat": "sante", "id": 3, "donnees": $donnees}""")

    @Test
    fun lectureDeLaReponseDuServeur() {
        val r = Sante.lire(reponse("""{"date": "2026-10-22", "nuit": {"date": "2026-10-22", "minutes": 432, "cette_nuit": true},
            "aujourdhui": {"date": "2026-10-22", "renseigne": true, "pas": 4210}}"""))
        assertEquals(Sante.Resume(432, 4210), r)
    }

    @Test
    fun champsAbsentsOuNulsSansLigne() {
        assertNull(Sante.lire(null))
        assertNull(Sante.lire(JSONObject("""{"etat": "sante", "id": 3, "erreur": "service indisponible"}""")))
        assertNull(Sante.lire(reponse("""{"date": "2026-10-22", "nuit": {"minutes": null}, "aujourdhui": {"pas": null}}""")))
        assertEquals(Sante.Resume(null, 980), Sante.lire(reponse("""{"date": "2026-10-22", "aujourdhui": {"pas": 980}}""")))
        // La nuit du matin pas encore arrivée : jamais la nuit d'avant à sa place.
        assertEquals(Sante.Resume(null, 12), Sante.lire(reponse("""{"date": "2026-10-22", "nuit": {"date": "2026-10-21", "minutes": 400}, "aujourdhui": {"pas": 12}}""")))
        assertEquals(Sante.Resume(null, 12), Sante.lire(reponse("""{"date": "2026-10-22", "nuit": {"date": "2026-10-22", "minutes": 400, "cette_nuit": false}, "aujourdhui": {"pas": 12}}""")))
        // cette_nuit absent : traité comme faux, pas de ligne de sommeil.
        assertEquals(Sante.Resume(null, 12), Sante.lire(reponse("""{"date": "2026-10-22", "nuit": {"date": "2026-10-22", "minutes": 400}, "aujourdhui": {"pas": 12}}""")))
        assertNull(Sante.lire(reponse("""{"nuit": {"minutes": "beaucoup"}, "aujourdhui": {"pas": -4}}""")))
    }

    @Test
    fun phrasesDeLAccueil() {
        assertEquals("Tu as dormi 7 h 12.", Sante.phraseSommeil(432)?.texte)
        assertEquals("7 h 12", Sante.phraseSommeil(432)?.let { it.texte.substring(it.ambre!!.first, it.ambre!!.last + 1) })
        assertEquals("Tu as dormi 7 h 05.", Sante.phraseSommeil(425)?.texte)
        assertEquals("Tu as dormi 8 h.", Sante.phraseSommeil(480)?.texte)
        assertEquals("Tu as dormi 45 min.", Sante.phraseSommeil(45)?.texte)
        assertEquals("4 210 pas aujourd'hui.", Sante.phrasePas(4210)?.texte)
        assertEquals("12 345 pas aujourd'hui.", Sante.phrasePas(12345)?.texte)
        assertEquals("980 pas", Sante.phrasePas(980)?.let { it.texte.substring(it.ambre!!.first, it.ambre!!.last + 1) })
        assertNull(Sante.phraseSommeil(null))
        assertNull(Sante.phrasePas(null))
    }

    @Test
    fun seulementSachaSeulEtReconnuSurLImageCourante() {
        val sacha = PersonneVue(1, "p1", "Sacha", true, sur = true)
        val sachaDeMemoire = PersonneVue(1, "p1", "Sacha", true, sur = false)
        val lou = PersonneVue(2, "p2", "Lou", true, sur = true)
        val inconnu = PersonneVue(3, null, null, true, inconnu = true)
        assertTrue(Sante.proprietaireSeulSur(listOf(sacha)))
        assertTrue(Sante.proprietaireSeulSur(listOf(PersonneVue(1, "p1", " SÂCHA ", true, sur = true))))
        // Identité seulement gardée de mémoire (tête tournée, ou quelqu'un d'autre à sa place) : non.
        assertFalse(Sante.proprietaireSeulSur(listOf(sachaDeMemoire)))
        assertFalse(Sante.proprietaireSeulSur(listOf(sacha, lou)))
        assertFalse(Sante.proprietaireSeulSur(listOf(sacha, inconnu)))
        assertFalse(Sante.proprietaireSeulSur(listOf(lou)))
        assertFalse(Sante.proprietaireSeulSur(listOf(inconnu)))
        assertFalse(Sante.proprietaireSeulSur(emptyList()))
    }

    @Test
    fun gardeSurUneImageDeMoinsDUneSeconde() {
        val sacha = listOf(PersonneVue(1, "p1", "Sacha", true, sur = true))
        val g = Sante.Garde()
        assertTrue(g.voir(sacha, 10_000L, 10_100L))
        // Analyse en panne ou caméra muette : la même liste ne vaut plus au-delà d'1 s.
        assertTrue(g.voir(sacha, 10_000L, 11_000L))
        assertFalse(g.voir(sacha, 10_000L, 11_001L))
        // Une image vide est tolérée 500 ms, pas plus.
        val g2 = Sante.Garde()
        assertTrue(g2.voir(sacha, 20_000L, 20_000L))
        assertTrue(g2.voir(emptyList(), 20_200L, 20_200L))
        assertTrue(g2.voir(emptyList(), 20_500L, 20_500L))
        assertFalse(g2.voir(emptyList(), 20_700L, 20_700L))
        // Jamais une image où quelqu'un d'autre apparaît, et plus de tolérance ensuite.
        val g3 = Sante.Garde()
        assertTrue(g3.voir(sacha, 30_000L, 30_000L))
        assertFalse(g3.voir(listOf(PersonneVue(2, null, null, true)), 30_200L, 30_200L))
        assertFalse(g3.voir(emptyList(), 30_400L, 30_400L))
        // Pas d'image du tout.
        assertFalse(Sante.Garde().voir(sacha, 0L, 100L))
    }

    @Test
    fun resumeJeteAuChangementDeJour() {
        val m = Sante.Memoire()
        assertTrue(m.avancer(true, 0L, 100L))
        m.recu(Sante.Resume(432, 4210), 1_000L, 100L)
        assertEquals(Sante.Resume(432, 4210), m.montre(true))
        m.avancer(true, 2_000L, 101L)
        assertNull(m.resume)
    }

    @Test
    fun memoireDeDixMinutes() {
        val m = Sante.Memoire()
        val r = Sante.Resume(432, 4210)
        // Sacha seul : une demande, pas deux tant qu'elle court.
        assertTrue(m.avancer(true, 1_000L))
        assertFalse(m.avancer(true, 2_000L))
        m.recu(r, 3_000L)
        assertEquals(r, m.montre(true))
        // Caché sur-le-champ quand il n'est plus seul, gardé en mémoire.
        assertNull(m.montre(false))
        assertFalse(m.avancer(false, 60_000L))
        assertEquals(r, m.resume)
        // Effacé après 10 min sans Sacha seul.
        assertFalse(m.avancer(false, 2_000L + 10 * 60_000L))
        assertNull(m.resume)
        // Redemandé une minute avant la fin des 10 min, effacé à 10 min.
        val m2 = Sante.Memoire()
        assertTrue(m2.avancer(true, 0L))
        m2.recu(r, 0L)
        assertFalse(m2.avancer(true, 8 * 60_000L))
        assertTrue(m2.avancer(true, 9 * 60_000L))
        assertEquals(r, m2.resume)
        assertFalse(m2.avancer(true, 10 * 60_000L))
        assertNull(m2.resume)
    }
}
