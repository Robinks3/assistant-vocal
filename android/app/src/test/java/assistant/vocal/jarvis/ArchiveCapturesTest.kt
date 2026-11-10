package assistant.vocal.jarvis

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Rule
import org.junit.Test
import org.junit.rules.TemporaryFolder
import java.nio.ByteBuffer
import java.nio.ByteOrder

class ArchiveCapturesTest {

    @get:Rule
    val dossier = TemporaryFolder()

    private val jour = 24L * 3600 * 1000

    private fun instantane(blocs: Int = 3, taille: Int = 4): TamponReveil.Instantane {
        val t = TamponReveil(capacite = blocs, taille = taille)
        for (k in 1..blocs) {
            t.ajouter(ShortArray(taille) { (k * 100 + it).toShort() }, -20f - k)
            if (k == blocs) t.noter(0.8123f, 0.6f, TamponReveil.PHASE_REPOS)
        }
        return t.instantane()
    }

    @Test
    fun ecrit_un_wav_lisible_et_son_json() {
        val a = ArchiveCaptures(dossier.root)
        val nom = ArchiveCaptures.nom(1_700_000_000_000L)
        a.ecrire(nom, instantane(), JSONObject().put("etiquette", "reveil"), maintenant = 1_700_000_000_000L)
        val wav = java.io.File(dossier.root, "$nom.wav").readBytes()
        val b = ByteBuffer.wrap(wav).order(ByteOrder.LITTLE_ENDIAN)
        assertEquals("RIFF", String(wav, 0, 4, Charsets.US_ASCII))
        assertEquals(16000, b.getInt(24))
        assertEquals(1.toShort(), b.getShort(22))
        assertEquals(24, b.getInt(40))
        assertEquals(44 + 24, wav.size)
        assertEquals(100.toShort(), b.getShort(44))

        val j = a.lire(nom)!!
        assertEquals("reveil", j.getString("etiquette"))
        assertEquals(3, j.getInt("blocs"))
        assertEquals(4, j.getInt("bloc"))
        assertTrue(j.getJSONArray("scores").isNull(0))
        assertEquals(0.812, j.getJSONArray("scores").getDouble(2), 1e-9)
        assertEquals("??R", j.getString("phases"))
        assertEquals(1 to (44 + 24 + java.io.File(dossier.root, "$nom.json").length()), a.bilan())
    }

    @Test
    fun reetiqueter_change_l_etiquette_et_ajoute_des_champs() {
        val a = ArchiveCaptures(dossier.root)
        val nom = ArchiveCaptures.nom(1_700_000_000_000L)
        a.ecrire(nom, instantane(), JSONObject().put("etiquette", "reveil"), maintenant = 1_700_000_000_000L)
        assertTrue(a.reetiqueter(nom, mapOf("etiquette" to "faux_probable", "issue" to "rien_entendu")))
        val j = a.lire(nom)!!
        assertEquals("faux_probable", j.getString("etiquette"))
        assertEquals("rien_entendu", j.getString("issue"))
        assertEquals(3, j.getInt("blocs"))
        assertFalse(a.reetiqueter("capture-inexistante", mapOf("etiquette" to "x")))
    }

    @Test
    fun le_nom_se_relit_en_instant() {
        val t = 1_700_000_123_456L
        assertEquals(t, ArchiveCaptures.instant(ArchiveCaptures.nom(t)))
        assertEquals(null, ArchiveCaptures.instant("capture-n-importe-quoi"))
    }

    @Test
    fun purge_les_trop_vieilles_puis_les_plus_anciennes_au_dela_du_plafond() {
        val maintenant = 1_700_000_000_000L
        val noms = listOf(20L, 10L, 3L, 2L, 1L).map { ArchiveCaptures.nom(maintenant - it * jour) }
        val partir = ArchiveCaptures.aPurger(noms, maintenant, max = 2, maxAgeMs = 14 * jour)
        // 20 j hors rétention, puis parmi 10, 3, 2, 1 j on garde les deux plus récentes.
        assertEquals(
            listOf(20L, 10L, 3L).map { ArchiveCaptures.nom(maintenant - it * jour) },
            partir,
        )
        assertEquals(emptyList<String>(), ArchiveCaptures.aPurger(listOf("capture-illisible"), maintenant, 1, jour))
    }

    @Test
    fun ecrire_purge_et_effacer_vide_tout() {
        val a = ArchiveCaptures(dossier.root, maxCaptures = 2)
        val t0 = 1_700_000_000_000L
        for (k in 0 until 4) a.ecrire(ArchiveCaptures.nom(t0 + k * 1000), instantane(), JSONObject(), maintenant = t0 + 4000)
        assertEquals(listOf(2, 3).map { ArchiveCaptures.nom(t0 + it * 1000) }, a.noms())
        java.io.File(dossier.root, "autre.txt").writeText("x")
        assertEquals(2, a.effacer())
        assertEquals(0, a.bilan().first)
        assertTrue(java.io.File(dossier.root, "autre.txt").exists())
    }
}
