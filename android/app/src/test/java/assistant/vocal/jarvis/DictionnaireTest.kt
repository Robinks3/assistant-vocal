package assistant.vocal.jarvis

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * « Ma chambre » selon la personne qui parle : mêmes cas que poc/tests/test_personnes.py
 * (poc/tests/cas_personnes.json), sur le dictionnaire exporté de config-exemple/ (genere/android/dictionnaire.json).
 * Chaque action rendue passe aussi par la sécurité en dur avec la même personne.
 */
class DictionnaireTest {

    /** Fichier cherché en remontant depuis le dossier de travail (module app en général). */
    private fun fichier(chemin: String): File {
        var dossier: File? = File(System.getProperty("user.dir") ?: ".").absoluteFile
        while (dossier != null) {
            val f = File(dossier, chemin)
            if (f.isFile) return f
            dossier = dossier.parentFile
        }
        error("$chemin introuvable depuis ${System.getProperty("user.dir")}")
    }

    /** Dictionnaire exporté de la configuration des tests (config-exemple/, propriété système maison.dossier). */
    private val dico by lazy {
        val dossier = System.getProperty("maison.dossier") ?: error("propriété système maison.dossier absente (voir build.gradle.kts)")
        DictionnaireLocal(JSONObject(File(dossier, "genere/android/dictionnaire.json").readText(Charsets.UTF_8)))
    }

    @Test
    fun prenomMalEntenduCorrige() {
        // proprietaire.variantes de config-exemple/maison.json, comme test_prenom_mal_entendu_corrige en Python.
        val regles = ArrayList<String>()
        assertEquals("allume la chambre de Sacha", DictionnaireLocal.epurer("allume la chambre de sasha", regles))
        assertTrue(regles.any { "Sacha" in it })
        assertEquals("allume la chambre de Sacha", DictionnaireLocal.epurer("allume la chambre de sachat"))
    }

    @Test
    fun maChambreSelonLaPersonne() {
        val cas = JSONObject(fichier("poc/tests/cas_personnes.json").readText(Charsets.UTF_8)).getJSONArray("cas")
        assertTrue("aucun cas lu", cas.length() > 0)
        val echecs = ArrayList<String>()
        for (i in 0 until cas.length()) {
            val c = cas.getJSONObject(i)
            val note = c.getString("note")
            val personne = c.optString("personne")
            val t = dico.chercher(c.getString("phrase"))
            if (t == null) {
                echecs.add("$note : phrase absente du dictionnaire")
                continue
            }
            val f = t.forme
            val actions = (0 until f.actions.length()).map { f.actions.getJSONObject(it) }
            val r = dico.personnes.appliquer(actions, f.cle, personne)
            if (c.optBoolean("refus")) {
                if (r.refus == null || r.actions.isNotEmpty()) echecs.add("$note : refus attendu")
                continue
            }
            if (r.refus != null) {
                echecs.add("$note : refus inattendu « ${r.refus} »")
                continue
            }
            val attendues = c.getJSONArray("cibles")
            val obtenues = r.actions.map { a ->
                when (val v = a.opt("entity_id")) {
                    is org.json.JSONArray -> (0 until v.length()).map { v.getString(it) }
                    else -> v?.toString().orEmpty().split(",")
                }
            }
            val voulues = (0 until attendues.length()).map { k ->
                val l = attendues.getJSONArray(k)
                (0 until l.length()).map { l.getString(it) }
            }
            if (obtenues != voulues) echecs.add("$note : cibles $obtenues au lieu de $voulues")
            if (c.has("service") && r.actions.firstOrNull()?.optString("service") != c.getString("service")) {
                echecs.add("$note : service ${r.actions.firstOrNull()?.optString("service")}")
            }
            val refusSecu = r.actions.mapNotNull { Securite.verifier(it, 21, personne) }
            if (refusSecu.isNotEmpty() != c.getBoolean("securite_refus")) echecs.add("$note : sécurité $refusSecu")
        }
        assertEquals("cas en écart avec dictionnaire.py :\n" + echecs.joinToString("\n"), 0, echecs.size)
    }

    @Test
    fun sachaNePiloteToujoursPasChezCamille() {
        org.junit.Assume.assumeTrue("règle levée le 22/10/2026", Securite.PROTEGER_OCCUPANT)
        val f = dico.chercher("allume les lumières de ma chambre")!!.forme
        val actions = (0 until f.actions.length()).map { f.actions.getJSONObject(it) }
        val pourCamille = dico.personnes.appliquer(actions, f.cle, "Camille").actions
        assertTrue(pourCamille.all { Securite.verifier(it, 21, "Sacha") != null })
        assertTrue(pourCamille.all { Securite.verifier(it, 21, "") != null })
        assertTrue(pourCamille.all { Securite.verifier(it, 21, DictionnaireLocal.INCONNU) != null })
    }
}
