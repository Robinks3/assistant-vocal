package assistant.vocal.jarvis

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Test
import java.util.Base64

/** Où transcrire (0.17.0) : choix du moteur selon les capacités, repli sur la tablette, message envoyé. */
class TranscriptionTest {

    /** Capacités lues le 22/10/2026 : le PC (serveur 0.18.4) et l'appli HA, sans service en ligne. */
    private val pc = listOf("pc", "ha_stp", "ha_whisper")
    private val ha = listOf("ha_stp", "ha_whisper")

    @Test
    fun voieSelonLeLieu() {
        assertEquals(OuTranscrire.Voie("pc", "pc"), OuTranscrire.voie(OuTranscrire.PC, pc, ha))
        assertEquals(OuTranscrire.Voie("ha", "ha_stp"), OuTranscrire.voie(OuTranscrire.HA, pc, ha))
        assertNull(OuTranscrire.voie(OuTranscrire.TABLETTE, pc, ha))
        // Rien d'annoncé, ou PC injoignable : pas de voie, donc la tablette.
        assertNull(OuTranscrire.voie(OuTranscrire.PC, null, ha))
        assertNull(OuTranscrire.voie(OuTranscrire.HA, pc, null))
    }

    @Test
    fun enLigneSeulementSiAnnonce() {
        assertNull(OuTranscrire.voie(OuTranscrire.EN_LIGNE, pc, ha))
        assertEquals(OuTranscrire.Voie("ha", "api"), OuTranscrire.voie(OuTranscrire.EN_LIGNE, pc, ha + "api"))
        assertEquals(OuTranscrire.Voie("pc", "api"), OuTranscrire.voie(OuTranscrire.EN_LIGNE, pc + "api", ha))
    }

    @Test
    fun lieuxProposes() {
        assertEquals(listOf("tablette", "pc", "ha"), OuTranscrire.disponibles(pc, ha))
        assertEquals(listOf("tablette"), OuTranscrire.disponibles(null, null))
        assertEquals(listOf("tablette", "ha", "api"), OuTranscrire.disponibles(null, ha + "api"))
    }

    @Test
    fun repliSurLaTablette() {
        assertEquals("pas de réponse en 8 s", OuTranscrire.issue(null).repli)
        assertEquals("erreur du serveur : moteur pc indisponible ici",
            OuTranscrire.issue(JSONObject().put("etat", "transcrit").put("texte", "").put("erreur", "moteur pc indisponible ici")).repli)
        assertEquals("rien reconnu", OuTranscrire.issue(JSONObject().put("etat", "transcrit").put("texte", "  ")).repli)
        val i = OuTranscrire.issue(JSONObject().put("etat", "transcrit").put("texte", "Allume le salon").put("moteur", "ha_stp").put("ms", 1380))
        assertEquals("Allume le salon", i.texte)
        assertNull(i.repli)
        assertEquals("ha_stp", i.moteur)
        assertEquals(1380L, i.msServeur)
    }

    @Test
    fun messageEnvoye() {
        val pcm = shortArrayOf(1, -2, 0x1234)
        val m = OuTranscrire.message(7, pcm, "pc") { Base64.getEncoder().encodeToString(it) }
        assertEquals("transcrire", m.getString("type"))
        assertEquals(7, m.getInt("id"))
        assertEquals("pc", m.getString("moteur"))
        // PCM 16 bits petit-boutiste : 01 00, FE FF, 34 12.
        val octets = Base64.getDecoder().decode(m.getString("pcm"))
        assertEquals(listOf(1, 0, 0xFE, 0xFF, 0x34, 0x12), octets.map { it.toInt() and 0xFF })
    }
}
