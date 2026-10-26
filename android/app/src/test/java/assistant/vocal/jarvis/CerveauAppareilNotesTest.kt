package assistant.vocal.jarvis

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Notes du LLM (llm.notes de commandes.yaml) : exportées dans dictionnaire.json, lues ici et ajoutées en bout de
 * ligne de l'appareil dans la consigne, comme le LLM du serveur (poc/assistant.py, « nom [note] »).
 */
class CerveauAppareilNotesTest {

    private val tele = CerveauAppareil.Appareil("media_player.tele_salon", "Télévision du séjour", "off", "Salon")
    private val lampe = CerveauAppareil.Appareil("light.salon_lampe_tele", "Lampe TV", "off", "Salon")
    private val gabarit = "Lumières :\n{lumieres}\nMédias :\n{medias}\nAutres :\n{autres}"

    private fun dictionnaireExemple(): JSONObject {
        val dossier = System.getProperty("maison.dossier") ?: error("propriété système maison.dossier absente (voir build.gradle.kts)")
        return JSONObject(File(dossier, "genere/android/dictionnaire.json").readText(Charsets.UTF_8))
    }

    @Test
    fun notesLuesDansLeDictionnaireExporte() {
        val notes = CerveauAppareil.lireNotes(dictionnaireExemple().getJSONObject("llm"))
        val note = notes["media_player.tele_salon"] ?: error("note de la télé absente de l'export d'exemple")
        assertTrue("select_source" in note)
        // Les guillemets et accolades de la note arrivent intacts, ils servent d'exemple au modèle.
        assertTrue("""{"source": ...}""" in note)
    }

    @Test
    fun sansNotesLaLigneEstInchangee() {
        assertTrue(CerveauAppareil.lireNotes(JSONObject()).isEmpty())
        assertTrue(CerveauAppareil.lireNotes(JSONObject("""{"renommer": {}}""")).isEmpty())
        assertEquals("- Télévision du séjour (Salon) : media_player.tele_salon", CerveauAppareil.ligneAppareil(tele, emptyMap()))
    }

    @Test
    fun noteEnCrochetsApresLeNom() {
        val notes = mapOf("media_player.tele_salon" to "entrées via select_source")
        assertEquals(
            "- Télévision du séjour [entrées via select_source] (Salon) : media_player.tele_salon",
            CerveauAppareil.ligneAppareil(tele, notes),
        )
        // Un appareil sans note garde sa ligne d'avant.
        assertEquals("- Lampe TV (Salon) : light.salon_lampe_tele", CerveauAppareil.ligneAppareil(lampe, notes))
    }

    @Test
    fun valeursInvalidesIgnorees() {
        val llm = JSONObject("""{"notes": {"a.b": "  ", "c.d": 3, "e.f": " utile "}}""")
        assertEquals(mapOf("e.f" to "utile"), CerveauAppareil.lireNotes(llm))
        // notes qui n'est pas un objet : ignoré, pas d'exception.
        assertTrue(CerveauAppareil.lireNotes(JSONObject("""{"notes": ["x"]}""")).isEmpty())
    }

    @Test
    fun noteDansLaConsigneSystemeSeulementPourSonAppareil() {
        val notes = mapOf("media_player.tele_salon" to "entrées via select_source")
        val avec = CerveauAppareil.construireSysteme(gabarit, listOf(lampe, tele), notes)
        assertTrue("- Télévision du séjour [entrées via select_source] (Salon) : media_player.tele_salon" in avec)
        assertTrue("- Lampe TV (Salon) : light.salon_lampe_tele" in avec)
        val sans = CerveauAppareil.construireSysteme(gabarit, listOf(lampe, tele), emptyMap())
        assertFalse("select_source" in sans)
        assertTrue("- Télévision du séjour (Salon) : media_player.tele_salon" in sans)
        assertEquals("Lumières :\n- (aucun)\nMédias :\n- (aucun)\nAutres :\n- (aucun)", CerveauAppareil.construireSysteme(gabarit, emptyList(), notes))
    }
}
