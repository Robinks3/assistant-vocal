package assistant.vocal.jarvis

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Sécurité en dur : mêmes cas que poc/tests/test_securite.py (poc/tests/cas_securite.json).
 * Un cas ajouté au fichier commun est vérifié des deux côtés, pour que les deux copies des
 * règles (securite.py et Securite.kt) ne divergent pas.
 */
class SecuriteTest {

    /** Le fichier commun, cherché en remontant depuis le dossier de travail (module app en général). */
    private val cas: JSONObject by lazy {
        var dossier: File? = File(System.getProperty("user.dir") ?: ".").absoluteFile
        var trouve: File? = null
        while (dossier != null && trouve == null) {
            val f = File(dossier, "poc/tests/cas_securite.json")
            if (f.isFile) trouve = f
            dossier = dossier.parentFile
        }
        val f = trouve ?: error("poc/tests/cas_securite.json introuvable depuis ${System.getProperty("user.dir")}")
        JSONObject(f.readText(Charsets.UTF_8))
    }

    @Test
    fun actions() {
        val liste = cas.getJSONArray("actions")
        assertTrue("aucun cas d'action lu", liste.length() > 0)
        val echecs = ArrayList<String>()
        for (i in 0 until liste.length()) {
            val c = liste.getJSONObject(i)
            // Comme le serveur : l'action est le service plus les données envoyées à HA.
            val action = JSONObject(c.getJSONObject("donnees").toString()).put("service", c.getString("service"))
            // Règle 3 : qui parle, d'après la reconnaissance de la tablette (absent = on ne sait pas).
            val refus = Securite.verifier(action, c.getInt("heure"), c.optString("personne"))
            if ((refus != null) != c.getBoolean("refus")) {
                echecs.add("${c.getString("note")} : attendu refus=${c.getBoolean("refus")}, obtenu « $refus »")
            }
        }
        assertEquals("cas en écart avec securite.py :\n" + echecs.joinToString("\n"), 0, echecs.size)
    }

    @Test
    fun phrases() {
        val liste = cas.getJSONArray("phrases")
        assertTrue("aucun cas de phrase lu", liste.length() > 0)
        for (i in 0 until liste.length()) {
            val c = liste.getJSONObject(i)
            val refus = Securite.phraseProtegee(c.getString("phrase"), c.optString("personne"))
            assertEquals(c.getString("phrase") + " (" + c.optString("personne", "inconnu") + ")", c.getBoolean("refus"), refus != null)
        }
    }

    @Test
    fun plafondDuVolume() {
        assertEquals(0.5, Securite.VOLUME_MAX, 1e-9)
        assertEquals(0.5, Securite.plafonnerVolume(0.8), 1e-9)
        assertEquals(0.25, Securite.plafonnerVolume(0.25), 1e-9)
        assertEquals(0.5, Securite.plafonnerVolume(0.5), 1e-9)
        assertEquals(0.0, Securite.plafonnerVolume(-1.0), 1e-9)
        assertEquals(0.0, Securite.plafonnerVolume(Double.NaN), 1e-9)
    }

    @Test
    fun volumeSetPlafonne() {
        // Mêmes cas que test_plafond_volume de securite.py : données avant et après le plafond.
        val liste = cas.getJSONArray("plafonds")
        assertTrue("aucun cas de plafond lu", liste.length() > 0)
        for (i in 0 until liste.length()) {
            val c = liste.getJSONObject(i)
            val note = c.getString("note")
            val avant = c.getJSONObject("donnees")
            val brut = avant.toString()
            val apres = Securite.plafonner(c.getString("service"), avant)
            // Les données reçues ne changent pas, seule la copie envoyée est plafonnée.
            assertEquals(note, brut, avant.toString())
            val attendu = c.getJSONObject("attendu")
            assertEquals(note, attendu.keys().asSequence().toSet(), apres.keys().asSequence().toSet())
            for (k in attendu.keys()) {
                val v = attendu.get(k)
                if (v is Number) assertEquals("$note, $k", v.toDouble(), apres.getDouble(k), 1e-9)
                else assertEquals("$note, $k", v.toString(), apres.getString(k))
            }
            // Le plafond ne fait jamais refuser l'action.
            assertNull(note, Securite.verifier(JSONObject(apres.toString()).put("service", c.getString("service")), 14))
        }
    }

    @Test
    fun securiteActive() {
        assertTrue("la sécurité en dur ne se lève qu'à la demande explicite du propriétaire", Securite.SECURITE_ACTIVE)
    }

    @Test
    fun monterLeSonSansDepasserLePlafond() {
        // 0.24.0 : volume_up passerait au-dessus de 50 % par pas, il devient un volume_set plafonné ou il est refusé.
        val avant = Securite.volumeLu
        try {
            Securite.volumeLu = { id -> if (id == "media_player.salon") 0.48 else null }
            val (s, d) = Securite.monterSansDepasser("media_player.volume_up", JSONObject().put("entity_id", "media_player.salon"))
            assertEquals("media_player.volume_set", s)
            assertEquals(0.5, d.getDouble("volume_level"), 1e-9)
            val (s2, _) = Securite.monterSansDepasser("media_player.volume_up", JSONObject().put("entity_id", "media_player.inconnu"))
            assertEquals("media_player.volume_up", s2)
            assertEquals(Securite.VOLUME_UP_REFUSE, Securite.verifier(JSONObject().put("service", "media_player.volume_up").put("entity_id", "media_player.inconnu")))
        } finally {
            Securite.volumeLu = avant
        }
    }
}
