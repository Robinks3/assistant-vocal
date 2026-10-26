package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File

/**
 * Actions dynamiques de commandes.yaml (S-L4, appli 0.41.0) : mêmes cas que poc/tests/test_commandes_dynamiques.py
 * (poc/tests/cas_dynamique.json). Valeurs comparées en texte, comme côté Python.
 */
class CommandesDynamiquesTest {

    private fun fichier(chemin: String): File {
        var dossier: File? = File(System.getProperty("user.dir") ?: ".").absoluteFile
        while (dossier != null) {
            val f = File(dossier, chemin)
            if (f.isFile) return f
            dossier = dossier.parentFile
        }
        error("$chemin introuvable depuis ${System.getProperty("user.dir")}")
    }

    private fun texte(v: Any?): String = when (v) {
        null, JSONObject.NULL -> "None"
        is Boolean -> if (v) "true" else "false"
        is JSONObject -> "{" + v.keys().asSequence().sorted().joinToString(",") { "$it=${texte(v.opt(it))}" } + "}"
        is JSONArray -> "[" + (0 until v.length()).joinToString(",") { texte(v.get(it)) } + "]"
        else -> v.toString()
    }

    private fun etatsDe(o: JSONObject): Map<String, JSONObject?> =
        o.keys().asSequence().associateWith { o.optJSONObject(it) }

    @Test
    fun casCommunsAvecLeServeur() {
        val cas = JSONObject(fichier("poc/tests/cas_dynamique.json").readText(Charsets.UTF_8)).getJSONArray("cas")
        assertTrue("aucun cas lu", cas.length() > 0)
        val echecs = ArrayList<String>()
        for (i in 0 until cas.length()) {
            val c = cas.getJSONObject(i)
            val note = c.getString("note")
            val r = CommandesDynamiques.resoudreToutes(listOf(c.getJSONObject("action")), etatsDe(c.getJSONObject("etats")))
            val voulues = c.getJSONArray("actions")
            val obtenues = r.actions.map { texte(it) }
            val attendues = (0 until voulues.length()).map { texte(voulues.get(it)) }
            if (obtenues != attendues) echecs.add("$note : $obtenues au lieu de $attendues")
            val vide = if (c.isNull("vide")) null else c.getString("vide")
            if (r.vide != vide) echecs.add("$note : réponse vide ${r.vide} au lieu de $vide")
        }
        assertEquals("cas en écart avec commandes_dynamiques.py :\n" + echecs.joinToString("\n"), 0, echecs.size)
    }

    @Test
    fun uneActionOrdinairePasseTelleQuelle() {
        val ordinaire = JSONObject().put("service", "light.turn_on").put("entity_id", "light.a")
        val r = CommandesDynamiques.resoudreToutes(listOf(ordinaire), emptyMap())
        assertEquals(listOf(ordinaire), r.actions)
        assertNull(r.vide)
    }

    @Test
    fun entitesLuesSansDoublonEtDansLOrdre() {
        val liste = listOf(
            JSONObject("""{"dynamique":"kelvin_pas","entity_id":["light.b","light.a"],"pas":500}"""),
            JSONObject("""{"dynamique":"selon_etat","entite":"light.a"}"""),
            JSONObject("""{"dynamique":"selon_etat","entite":"media_player.tele_salon"}"""),
            JSONObject("""{"service":"light.turn_on","entity_id":"light.z"}"""),
        )
        assertEquals(listOf("light.b", "light.a", "media_player.tele_salon"), CommandesDynamiques.entitesLues(liste))
    }

    @Test
    fun uneActionDynamiqueInconnueNeFaitRien() {
        val r = CommandesDynamiques.resoudreToutes(listOf(JSONObject("""{"dynamique":"inventee"}""")), emptyMap())
        assertTrue(r.actions.isEmpty())
        assertEquals(CommandesDynamiques.REPONSE_VIDE_DEFAUT, r.vide)
    }

    @Test
    fun onNonCiteDansUnYamlVautLEtatOn() {
        // YAML 1.1 lit `on` comme un booléen : la liste des états permis doit quand même reconnaître l'état "on".
        val action = JSONObject("""{"dynamique":"selon_etat","entite":"media_player.tele_salon","etats":[true,"playing"],
            "alors":{"service":"media_player.volume_up","entity_id":"media_player.tele_salon"},
            "sinon":{"service":"light.turn_on","entity_id":"light.a"}}""")
        val etats = mapOf<String, JSONObject?>("media_player.tele_salon" to JSONObject("""{"state":"on"}"""))
        val r = CommandesDynamiques.resoudreToutes(listOf(action), etats)
        assertEquals(listOf("media_player.volume_up"), r.actions.map { it.getString("service") })
    }

    @Test
    fun laResolutionNeModifiePasLActionDuDictionnaire() {
        val alors = JSONObject("""{"service":"media_player.volume_up","entity_id":"media_player.tele_salon"}""")
        val action = JSONObject().put("dynamique", "selon_etat").put("entite", "media_player.tele_salon")
            .put("etats", JSONArray().put("on")).put("alors", alors)
        val etats = mapOf<String, JSONObject?>("media_player.tele_salon" to JSONObject("""{"state":"on"}"""))
        val r = CommandesDynamiques.resoudreToutes(listOf(action), etats)
        r.actions[0].put("entity_id", "autre")
        assertEquals("media_player.tele_salon", alors.getString("entity_id"))
    }

    @Test
    fun laSecuriteVoitLesActionsResolues() {
        // Une action résolue passe par Securite.verifier comme n'importe quelle action écrite à la main.
        val action = JSONObject("""{"dynamique":"selon_etat","entite":"media_player.tele_salon","etats":["on"],
            "alors":{"service":"media_player.volume_up","entity_id":"media_player.tele_salon"}}""")
        val etats = mapOf<String, JSONObject?>("media_player.tele_salon" to JSONObject("""{"state":"on"}"""))
        val r = CommandesDynamiques.resoudreToutes(listOf(action), etats)
        assertEquals(1, r.actions.size)
        assertEquals(Securite.verifier(JSONObject().put("service", "media_player.volume_up")
            .put("entity_id", "media_player.tele_salon")), Securite.verifier(r.actions[0]))
    }
}
