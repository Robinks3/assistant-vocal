package assistant.vocal.jarvis

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
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

    /** Export à part des phrases apprises (0.32.2) : fusionné après commandes.yaml, sans jamais le remplacer. */
    @Test
    fun phrasesApprisesFusionneesSansRemplacerLaConfiguration() {
        val dossier = System.getProperty("maison.dossier") ?: error("propriété système maison.dossier absente")
        // L'export d'exemple n'a pas de jeton : celui d'un vrai export, commun aux deux fichiers.
        val config = JSONObject(File(dossier, "genere/android/dictionnaire.json").readText(Charsets.UTF_8))
            .put("export", "jeton")
        val cleConfig = config.getJSONArray("formes").getJSONArray(0).getString(0)
        fun appris(export: String) = JSONObject("""{"version":"test","genere_le":"","export":"$export","modeles":[
            {"actions":[{"service":"light.turn_on","entity_id":"light.essai"}],"reponse":"Appris.","source":"commandes_apprises.yaml","appris":true,"ligne":1,"motif":"x"},
            {"actions":[{"service":"light.turn_off","entity_id":"light.essai"}],"reponse":"Écrasé.","source":"commandes_apprises.yaml","appris":true,"ligne":2,"motif":"y"}],
            "formes":[["phrase apprise de test",0],["$cleConfig",1]]}""")
        val sans = DictionnaireLocal(config)
        val avec = DictionnaireLocal(config, appris("jeton"))
        assertEquals(sans.taille + 1, avec.taille)
        assertEquals("phrases apprises : 1", avec.etatAppris)
        val t = avec.chercher("phrase apprise de test")
        assertTrue(t != null && t.forme.appris && t.forme.reponse == "Appris.")
        // Une phrase apprise n'est reconnue que mot pour mot, même à une lettre près.
        assertNull(avec.chercher("phrase apprise de tests"))
        val c = avec.chercher(cleConfig)
        assertTrue(c != null && !c.forme.appris && c.forme.reponse != "Écrasé.")
    }

    /** Phrases apprises d'un autre export (fichier périmé, autre maison) ou abîmées : ignorées, le reste marche. */
    @Test
    fun phrasesApprisesEtrangeresOuAbimeesIgnorees() {
        val dossier = System.getProperty("maison.dossier") ?: error("propriété système maison.dossier absente")
        val config = JSONObject(File(dossier, "genere/android/dictionnaire.json").readText(Charsets.UTF_8))
            .put("export", "jeton")
        val taille = DictionnaireLocal(config).taille
        val apprisVide = """"modeles":[{"actions":[],"reponse":"","source":"","ligne":1,"motif":"x"}]"""
        val autre = DictionnaireLocal(config, JSONObject("""{"export":"autre",$apprisVide,"formes":[["phrase etrangere",0]]}"""))
        assertEquals(taille, autre.taille)
        assertNull(autre.chercher("phrase etrangere"))
        assertTrue(autre.etatAppris.startsWith("phrases apprises ignorées"))
        // Indice de modèle hors limites à la deuxième forme : rien n'est ajouté, pas même la première.
        val abime = DictionnaireLocal(config,
            JSONObject("""{"export":"jeton",$apprisVide,"formes":[["phrase valide",0],["phrase cassee",7]]}"""))
        assertEquals(taille, abime.taille)
        assertNull(abime.chercher("phrase valide"))
        assertTrue(abime.etatAppris.startsWith("phrases apprises illisibles"))
        // Sans jeton des deux côtés (export d'avant la 0.32.2), les phrases apprises ne sont pas prises.
        val ancien = DictionnaireLocal(config.put("export", ""),
            JSONObject("""{$apprisVide,"formes":[["phrase ancienne",0]]}"""))
        assertNull(ancien.chercher("phrase ancienne"))
    }
}
