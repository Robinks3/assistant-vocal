package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Sortie du son de l'écran Musique (0.17.0) : groupe, cases, commandes et sécurité de nuit. */
class SortieSonTest {

    private val salon = "media_player.salon"
    private val cuisine = "media_player.chambre"
    private val bureau = "media_player.bureau"

    private fun e(id: String, etat: String, membres: Set<String> = emptySet(), regroupable: Boolean = true) =
        SortieSon.Enceinte(id, id, etat, 0.3, membres, regroupable)

    @Test
    fun meneurEtCasesCochees() {
        val l = listOf(e(salon, "playing", setOf(salon, cuisine)), e(cuisine, "playing", setOf(salon, cuisine)), e(bureau, "idle"))
        assertEquals(salon, SortieSon.meneur(l)?.id)
        assertEquals(setOf(salon, cuisine), SortieSon.cochees(l))
        // Rien ne joue : aucune case.
        assertEquals(emptySet<String>(), SortieSon.cochees(listOf(e(salon, "idle"), e(cuisine, "off"))))
        // Une enceinte en pause garde son groupe.
        assertEquals(setOf(cuisine), SortieSon.cochees(listOf(e(salon, "idle"), e(cuisine, "paused"))))
    }

    @Test
    fun cocherAjouteAuGroupeDuMeneur() {
        val l = listOf(e(salon, "playing"), e(cuisine, "idle"), e(bureau, "idle"))
        val d = SortieSon.basculer(l, cuisine, true)
        assertEquals(SortieSon.Commande("join", salon, listOf(cuisine)), d.commande)
        assertEquals(salon, d.commande!!.corps().getString("entity_id"))
        assertEquals(cuisine, d.commande!!.corps().getJSONArray("group_members").getString(0))
        // La sécurité voit les deux enceintes.
        assertEquals(2, d.commande!!.verification().getJSONArray("entity_id").length())
    }

    @Test
    fun sansMusiqueOuSansRegroupementUnMessage() {
        assertNotNull(SortieSon.basculer(listOf(e(salon, "idle"), e(cuisine, "idle")), cuisine, true).message)
        val d = SortieSon.basculer(listOf(e(salon, "playing"), e(bureau, "idle", regroupable = false)), bureau, true)
        assertNull(d.commande)
        assertTrue(d.message!!.startsWith("Bureau"))
    }

    @Test
    fun decocher() {
        val groupe = setOf(salon, cuisine)
        val l = listOf(e(salon, "playing", groupe), e(cuisine, "playing", groupe))
        assertEquals(SortieSon.Commande("unjoin", cuisine), SortieSon.basculer(l, cuisine, false).commande)
        // Le meneur avec d'autres enceintes : refus expliqué.
        val d = SortieSon.basculer(l, salon, false)
        assertNull(d.commande)
        assertNotNull(d.message)
        // Le meneur seul : pause.
        assertEquals(SortieSon.Commande("media_pause", salon), SortieSon.basculer(listOf(e(salon, "playing")), salon, false).commande)
    }

    @Test
    fun pasDeSonAuSalonLaNuit() {
        org.junit.Assume.assumeTrue("règle levée le 22/10/2026", Securite.HEURE_CALME_ACTIVE)
        val ajout = SortieSon.Commande("join", bureau, listOf(salon))
        assertNotNull(SortieSon.refus(ajout, heure = 2))
        assertTrue(SortieSon.refus(ajout, heure = 2)!!.contains("salon"))
        assertNull(SortieSon.refus(ajout, heure = 22))
        // La pause reste permise la nuit.
        assertNull(SortieSon.refus(SortieSon.Commande("media_pause", salon), heure = 2))
        // Le Bureau seul, la nuit : permis.
        assertNull(SortieSon.refus(SortieSon.Commande("join", bureau, listOf(bureau)), heure = 2))
    }

    @Test
    fun regroupementLuDansLesFonctions() {
        // Valeurs lues le 22/10/2026 : Salon et Cuisine 8322623, Bureau 7796287.
        assertTrue(SortieSon.regroupable(8322623))
        assertTrue(!SortieSon.regroupable(7796287))
    }

    @Test
    fun enceinteHorsLigneNeSeCochePas() {
        // 25/10/2026 : la cuisine débranchée, un join vers elle échouait sans rien dire.
        val l = listOf(e(salon, "playing"), e(cuisine, "unavailable"))
        assertTrue(l[1].horsLigne)
        val d = SortieSon.basculer(l, cuisine, true)
        assertNull(d.commande)
        assertTrue(d.message!!.contains("hors ligne"))
        assertEquals(SortieSon.horsLigne(cuisine), d.message)
    }
}
