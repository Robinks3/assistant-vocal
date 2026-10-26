package assistant.vocal.jarvis

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
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

    /** Plafond du volume d'un cas (0 à 1), comme securite.plafond_volume dans la configuration : absent, aucun. */
    private fun volumeMax(c: JSONObject): Double = Securite.plafondConfigure(c.opt("plafond_volume")) / 100

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
            val refus = Securite.verifier(action, c.getInt("heure"), c.optString("personne"), volumeMax(c))
            if ((refus != null) != c.getBoolean("refus")) {
                echecs.add("${c.getString("note")} : attendu refus=${c.getBoolean("refus")}, obtenu « $refus »")
            }
        }
        assertEquals("cas en écart avec securite.py :\n" + echecs.joinToString("\n"), 0, echecs.size)
    }

    @Test
    fun heuresCalmesPassantMinuit() {
        // 26/10/2026 (S-D1) : plage de 22 h à 7 h. La règle reste coupée dans la configuration, le test la force.
        val nuit = cas.getJSONObject("heures_calmes_nuit")
        val plage = nuit.getJSONObject("plage_nuit")
        val forcee = Pair(plage.getInt("debut"), plage.getInt("fin"))
        val liste = nuit.getJSONArray("cas")
        assertTrue("aucun cas d'heures calmes lu", liste.length() > 0)
        val echecs = ArrayList<String>()
        for (i in 0 until liste.length()) {
            val c = liste.getJSONObject(i)
            val action = JSONObject(c.getJSONObject("donnees").toString()).put("service", c.getString("service"))
            val refus = Securite.verifier(action, c.getInt("heure"), plageCalme = forcee)
            if ((refus != null) != c.getBoolean("refus")) {
                echecs.add("${c.getString("note")} : attendu refus=${c.getBoolean("refus")}, obtenu « $refus »")
            }
        }
        assertEquals("cas en écart avec securite.py :\n" + echecs.joinToString("\n"), 0, echecs.size)
    }

    @Test
    fun enHeureCalme() {
        val liste = cas.getJSONObject("heures_calmes_nuit").getJSONArray("en_heure_calme")
        assertTrue("aucun cas de plage calme lu", liste.length() > 0)
        for (i in 0 until liste.length()) {
            val c = liste.getJSONObject(i)
            assertEquals(c.getString("note"), c.getBoolean("attendu"),
                Securite.enHeureCalme(c.getInt("heure"), c.getInt("debut"), c.getInt("fin")))
        }
    }

    @Test
    fun heuresCalmesRestentCoupees() {
        // La règle 2 est levée par le propriétaire : seul le calcul a changé, pas le niveau de protection.
        assertFalse(Securite.HEURE_CALME_ACTIVE)
        val son = JSONObject().put("service", "media_player.media_play").put("entity_id", "media_player.enceintes_maison")
        assertNull(Securite.verifier(son, 3))
        assertNotNull(Securite.verifier(son, 3, plageCalme = Pair(22, 7)))
    }

    @Test
    fun servicesDeLaListeBlanche() {
        // Décision D6 (26/10/2026, S-F1) : mêmes cas que test_services_permis.py, contre le services_permis
        // du dictionnaire exporté pour l'appli (poc/tests/cas_securite.json, bloc « services »).
        val dossier = System.getProperty("maison.dossier") ?: error("propriété système maison.dossier absente (voir build.gradle.kts)")
        val permis = JSONObject(File(dossier, "genere/android/dictionnaire.json").readText(Charsets.UTF_8))
            .getJSONObject("services_permis")
        val liste = cas.getJSONArray("services")
        assertTrue("aucun cas de service lu", liste.length() > 0)
        for (i in 0 until liste.length()) {
            val c = liste.getJSONObject(i)
            val domaine = c.getString("domaine")
            val service = c.getString("service")
            var present = false
            val services = permis.optJSONArray(domaine)
            if (services != null) {
                for (j in 0 until services.length()) if (services.getString(j) == service) present = true
            }
            assertEquals(c.getString("note"), c.getBoolean("permis"), present)
        }
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
        // 25/10/2026 : plus de plafond de 50 % par défaut. config-exemple règle plafond_volume à 100, comme la
        // configuration du propriétaire : aucun plafond.
        assertEquals(1.0, Securite.VOLUME_MAX, 1e-9)
        assertFalse(Securite.PLAFOND_ACTIF)
        assertEquals(0.8, Securite.plafonnerVolume(0.8), 1e-9)
        assertEquals(1.0, Securite.plafonnerVolume(1.5), 1e-9)
        assertEquals(0.0, Securite.plafonnerVolume(-1.0), 1e-9)
        assertEquals(0.0, Securite.plafonnerVolume(Double.NaN), 1e-9)
        // Avec un plafond de 50 % réglé dans la configuration.
        assertEquals(0.5, Securite.plafonnerVolume(0.8, 0.5), 1e-9)
        assertEquals(0.25, Securite.plafonnerVolume(0.25, 0.5), 1e-9)
        assertEquals(0.5, Securite.plafonnerVolume(0.5, 0.5), 1e-9)
        assertEquals(0.0, Securite.plafonnerVolume(-1.0, 0.5), 1e-9)
        assertEquals(0.0, Securite.plafonnerVolume(Double.NaN, 0.5), 1e-9)
    }

    @Test
    fun plafondsConfigures() {
        // Mêmes cas que test_plafond_configure de securite.py.
        val liste = cas.getJSONArray("plafonds_configures")
        assertTrue("aucun cas de plafond configuré lu", liste.length() > 0)
        for (i in 0 until liste.length()) {
            val c = liste.getJSONObject(i)
            assertEquals(c.getString("note"), c.getDouble("attendu"), Securite.plafondConfigure(c.opt("valeur")), 1e-9)
        }
        // Absent du fichier commun (JSON n'a pas de NaN) : illisible, plafond prudent.
        assertEquals(Securite.PLAFOND_SI_ILLISIBLE, Securite.plafondConfigure(Double.NaN), 1e-9)
    }

    @Test
    fun pourcentages() {
        val liste = cas.getJSONArray("pourcentages")
        assertTrue("aucun cas de pourcentage lu", liste.length() > 0)
        for (i in 0 until liste.length()) {
            val c = liste.getJSONObject(i)
            assertEquals(c.getString("attendu"), Securite.pourcentage(c.getDouble("niveau")))
        }
    }

    @Test
    fun volumeSetPlafonne() {
        // Mêmes cas que test_plafond_volume de securite.py : données avant et après le plafond.
        val liste = cas.getJSONArray("plafonds")
        assertTrue("aucun cas de plafond lu", liste.length() > 0)
        for (i in 0 until liste.length()) {
            val c = liste.getJSONObject(i)
            val note = c.getString("note")
            val max = volumeMax(c)
            val avant = c.getJSONObject("donnees")
            val brut = avant.toString()
            val apres = Securite.plafonner(c.getString("service"), avant, max)
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
            assertNull(note, Securite.verifier(JSONObject(apres.toString()).put("service", c.getString("service")), 14, volumeMax = max))
        }
    }

    @Test
    fun securiteActive() {
        assertTrue("la sécurité en dur ne se lève qu'à la demande explicite du propriétaire", Securite.SECURITE_ACTIVE)
    }

    @Test
    fun monterLeSonSansDepasserLePlafond() {
        // 0.24.0 : avec un plafond, volume_up passerait au-dessus par pas, il devient un volume_set plafonné ou il
        // est refusé. Depuis le 25/10/2026 le plafond est réglable (aucun par défaut) : sans plafond, volume_up passe.
        val avant = Securite.volumeLu
        try {
            Securite.volumeLu = { id -> if (id == "media_player.barre_son_salon") 0.48 else null }
            val salon = JSONObject().put("entity_id", "media_player.barre_son_salon")
            val inconnu = JSONObject().put("entity_id", "media_player.inconnu")
            // Plafond de 50 % réglé dans la configuration.
            val (s, d) = Securite.monterSansDepasser("media_player.volume_up", salon, 0.5)
            assertEquals("media_player.volume_set", s)
            assertEquals(0.5, d.getDouble("volume_level"), 1e-9)
            val (s2, _) = Securite.monterSansDepasser("media_player.volume_up", inconnu, 0.5)
            assertEquals("media_player.volume_up", s2)
            val refus = Securite.verifier(JSONObject(inconnu.toString()).put("service", "media_player.volume_up"), volumeMax = 0.5)
            assertEquals(Securite.refusVolumeUp(0.5), refus)
            assertTrue(refus!!.contains("plafonné à 50 %"))
            assertTrue(Securite.refusVolumeUp(0.725).contains("plafonné à 72,5 %"))
            // Sans plafond (la configuration d'exemple, comme celle du propriétaire) : 5 points de plus, jusqu'au maximum.
            val (s3, d3) = Securite.monterSansDepasser("media_player.volume_up", salon)
            assertEquals("media_player.volume_set", s3)
            assertEquals(0.53, d3.getDouble("volume_level"), 1e-9)
            Securite.volumeLu = { 0.98 }
            assertEquals(1.0, Securite.monterSansDepasser("media_player.volume_up", salon).second.getDouble("volume_level"), 1e-9)
            assertNull(Securite.verifier(JSONObject(inconnu.toString()).put("service", "media_player.volume_up")))
            // Les autres sécurités restent : un appareil visé par son identifiant brut est toujours refusé.
            assertNotNull(Securite.verifier(JSONObject().put("service", "media_player.volume_up").put("device_id", "abc")))
        } finally {
            Securite.volumeLu = avant
        }
    }
}
