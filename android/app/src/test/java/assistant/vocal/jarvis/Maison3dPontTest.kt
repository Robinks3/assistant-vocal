package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

/** Vue 3D de l'appartement : file d'attente avant `pret()` et traduction des états HA. */
class Maison3dPontTest {

    @Test
    fun attendLaPagePuisVideLaFileDansLOrdre() {
        val faits = mutableListOf<String>()
        val pont = Maison3dPont { faits += it }
        pont.appeler("a()")
        pont.appeler("b()")
        assertTrue(faits.isEmpty())
        assertFalse(pont.prete)
        pont.surPret()
        assertEquals(listOf("a()", "b()"), faits)
        pont.appeler("c()")
        assertEquals(listOf("a()", "b()", "c()"), faits)
    }

    @Test
    fun fileBorneeEtOublieeAuRechargement() {
        val faits = mutableListOf<String>()
        val pont = Maison3dPont { faits += it }
        repeat(Maison3dPont.ATTENTE_MAX + 10) { pont.appeler("x($it)") }
        pont.surPret()
        assertEquals(Maison3dPont.ATTENTE_MAX, faits.size)
        assertEquals("x(10)", faits.first())
        pont.reinitialiser()
        pont.appeler("y()")
        assertEquals(Maison3dPont.ATTENTE_MAX, faits.size)
    }

    @Test
    fun etatsNeGardeQueLesLumieresEtLesAttributsUtiles() {
        val brut = JSONArray()
            .put(JSONObject().put("entity_id", "light.cuisine").put("state", "on")
                .put("attributes", JSONObject().put("brightness", 128).put("friendly_name", "Cuisine")
                    .put("rgb_color", JSONArray(listOf(255, 200, 100))).put("color_temp_kelvin", JSONObject.NULL)))
            .put(JSONObject().put("entity_id", "switch.prise").put("state", "on"))
            .put(JSONObject().put("entity_id", "light.exemple17").put("state", "off"))
        val script = Maison3dPont.scriptEtats(brut)
        assertTrue(script.startsWith("maison3d.etats(") && script.endsWith(")"))
        val l = JSONArray(script.removePrefix("maison3d.etats(").removeSuffix(")"))
        assertEquals(2, l.length())
        val cuisine = l.getJSONObject(0)
        assertEquals("light.cuisine", cuisine.getString("entity_id"))
        assertEquals("on", cuisine.getString("state"))
        val a = cuisine.getJSONObject("attributes")
        assertEquals(128, a.getInt("brightness"))
        assertEquals(255, a.getJSONArray("rgb_color").getInt(0))
        assertFalse(a.has("friendly_name"))
        assertFalse(a.has("color_temp_kelvin"))
        assertEquals("off", l.getJSONObject(1).getString("state"))
    }

    @Test
    fun entiteEchappeeDansLeScript() {
        val s = Maison3dPont.scriptEtat("light.a\"b", JSONObject().put("state", "on"))
        assertEquals("maison3d.etat(\"light.a\\\"b\", {\"state\":\"on\"})", s)
        assertEquals("maison3d.montrer([\"light.cuisine\",\"chambre_sacha\"])",
            Maison3dPont.scriptMontrer(listOf("light.cuisine", "chambre_sacha")))
    }

    @Test
    fun actionGardeLEffetEtLEtatReduit() {
        val effets = JSONObject()
            .put("light.exemple6", JSONObject().put("effet", "allumer").put("state", "on")
                .put("attributes", JSONObject().put("brightness", 102).put("friendly_name", "Salon")))
            .put("light.cuisine", JSONObject().put("effet", "eteindre"))
        val s = Maison3dPont.scriptAction(effets)
        assertTrue(s.startsWith("maison3d.action("))
        val o = JSONObject(s.removePrefix("maison3d.action(").removeSuffix(")"))
        val salon = o.getJSONObject("light.exemple6")
        assertEquals("allumer", salon.getString("effet"))
        assertEquals("on", salon.getString("state"))
        assertEquals(102, salon.getJSONObject("attributes").getInt("brightness"))
        assertFalse(salon.getJSONObject("attributes").has("friendly_name"))
        assertEquals("eteindre", o.getJSONObject("light.cuisine").getString("effet"))
        assertFalse(o.getJSONObject("light.cuisine").has("state"))
    }

    @Test
    fun effetInconnuDevientUnReglage() {
        val s = Maison3dPont.scriptAction(JSONObject().put("light.a", "basculer").put("light.b", JSONObject().put("effet", "alert(1)")))
        val o = JSONObject(s.removePrefix("maison3d.action(").removeSuffix(")"))
        assertEquals("regler", o.getJSONObject("light.a").getString("effet"))
        assertEquals("regler", o.getJSONObject("light.b").getString("effet"))
    }

    @Test
    fun poserReduitChaqueEtat() {
        val s = Maison3dPont.scriptPoser(JSONObject().put("light.a",
            JSONObject().put("state", "on").put("attributes", JSONObject().put("brightness", 40).put("icon", "x"))))
        val o = JSONObject(s.removePrefix("maison3d.poser(").removeSuffix(")"))
        assertEquals("on", o.getJSONObject("light.a").getString("state"))
        assertFalse(o.getJSONObject("light.a").getJSONObject("attributes").has("icon"))
    }

    @Test
    fun scriptsDeLAccueil() {
        // Nombres en notation JavaScript, quelle que soit la langue de la tablette.
        assertEquals("maison3d.fondu(true, 0.08)", Maison3dPont.scriptFondu(0.08f))
        assertEquals("maison3d.rotation(600, 10, 1)", Maison3dPont.scriptRotation(600, 10, 1f))
        assertEquals("maison3d.rotation(0, 30, 1.12)", Maison3dPont.scriptRotation(-5, 99, 1.12f))
        assertEquals("maison3d.attenuer(0.28, 450)", Maison3dPont.scriptAttenuer(0.28f, 450))
        assertEquals("maison3d.attenuer(1, 0)", Maison3dPont.scriptAttenuer(3f, -1))
        assertEquals("maison3d.ensemble(1600)", Maison3dPont.scriptEnsemble(1600))
        assertEquals("maison3d.fondu(true, 0)", Maison3dPont.scriptFondu(Float.NaN))
        // 0.18.1 : palette, cadence, pause, poussières, maison en panne, toucher sur le plan.
        assertEquals("maison3d.teintes({\"sol\":\"#141518\"})", Maison3dPont.scriptTeintes(JSONObject().put("sol", "#141518")))
        // 0.19.0 : teintes du jeu de couleurs choisi.
        assertEquals("maison3d.palette({\"flux\":\"#7EF0C9\"})", Maison3dPont.scriptPalette(JSONObject().put("flux", "#7EF0C9")))
        assertEquals("maison3d.cadence(12, 30)", Maison3dPont.scriptCadence(12))
        assertEquals("maison3d.cadence(12, 12)", Maison3dPont.scriptCadence(12, 12))
        assertEquals("maison3d.cadence(30, 30)", Maison3dPont.scriptCadence(120))
        assertEquals("maison3d.pause(true)", Maison3dPont.scriptPause(true))
        assertEquals("maison3d.poussieres(false)", Maison3dPont.scriptPoussieres(false))
        assertEquals("maison3d.desaturer(true)", Maison3dPont.scriptDesaturer(true))
        assertEquals("maison3d.dansLePlan(412.5, 300)", Maison3dPont.scriptDansLePlan(412.5f, 300f))
    }

    @Test
    fun etatsLaissentPasserLaTeleEtLesEnceintesAvecLeurVolume() {
        val brut = JSONArray()
            .put(JSONObject().put("entity_id", "media_player.exemple20").put("state", "on")
                .put("attributes", JSONObject().put("friendly_name", "Télé")))
            .put(JSONObject().put("entity_id", "media_player.salon").put("state", "playing")
                .put("attributes", JSONObject().put("volume_level", 0.3).put("media_title", "Titre")))
        val l = JSONArray(Maison3dPont.scriptEtats(brut).removePrefix("maison3d.etats(").removeSuffix(")"))
        assertEquals(2, l.length())
        assertEquals("on", l.getJSONObject(0).getString("state"))
        val a = l.getJSONObject(1).getJSONObject("attributes")
        assertEquals(0.3, a.getDouble("volume_level"), 1e-9)
        assertFalse(a.has("media_title"))
    }

    @Test
    fun scriptsDeLaSecondePasse() {
        assertEquals("maison3d.rotation(600, 10, 1, 25, 75)", Maison3dPont.scriptRotation(600, 10, 1f, 25f, 75f))
        val d = Maison3dPont.scriptDisposition(Disposition.A, 600)
        val o = JSONObject(d.removePrefix("maison3d.disposition(").removeSuffix(")"))
        assertEquals(0.5, o.getDouble("x"), 1e-6)
        assertEquals(0.444, o.getDouble("largeur"), 1e-6)
        assertEquals(600, o.getInt("duree_ms"))
        assertFalse(JSONObject(Maison3dPont.scriptDisposition(Disposition.B, 0).removePrefix("maison3d.disposition(").removeSuffix(")")).has("duree_ms"))
        assertEquals("maison3d.teintes({\"jeu\": \"couleur\", \"intensite\": 0.2})", Maison3dPont.scriptJeuCouleur(0.2f))
        assertEquals("maison3d.teintes({\"intensite\": 0.15})", Maison3dPont.scriptIntensite(0.15f))
        assertEquals("if (typeof maison3d.regime === \"function\") maison3d.regime(1, 800)", Maison3dPont.scriptRegime(1f, 800))
    }

    @Test
    fun scriptsDeLaMaisonEnGrand() {
        assertEquals("if (typeof maison3d.grand === \"function\") maison3d.grand(true, 56, 20)", Maison3dPont.scriptGrand(true, 56f, 20f))
        assertEquals("if (typeof maison3d.choisir === \"function\") maison3d.choisir(\"sejour_cuisine\", 600)", Maison3dPont.scriptChoisir("sejour_cuisine", 600))
        assertEquals("if (typeof maison3d.choisir === \"function\") maison3d.choisir(null, 600)", Maison3dPont.scriptChoisir(null, 600))
        // Un identifiant ne sort jamais de sa chaîne.
        assertTrue(Maison3dPont.scriptChoisir("a\"); alert(1); (\"", 0).contains("\"a\\\"); alert(1); (\\\"\""))
        assertEquals("if (typeof maison3d.voile === \"function\") maison3d.voile(0.65)", Maison3dPont.scriptVoile(0.65f))
        assertEquals("if (typeof maison3d.voile === \"function\") maison3d.voile(0.9)", Maison3dPont.scriptVoile(3f))
        val e = JSONArray().put(JSONObject().put("piece", "entree_couloir").put("nom", "Entrée").put("etat", "éteinte").put("verrou", false))
        assertEquals("if (typeof maison3d.etiquettes === \"function\") maison3d.etiquettes($e)", Maison3dPont.scriptEtiquettes(e))
        assertTrue(Maison3dPont.scriptDesigner(10.5f, 20f).contains("maison3d.designer(10.5, 20)"))
    }

    @Test
    fun texteRenduParLaWebView() {
        // evaluateJavascript encode le texte rendu par la page en JSON.
        assertEquals("{\"genre\":\"piece\",\"id\":\"sejour_cuisine\"}", Maison3dPont.texteRendu("\"{\\\"genre\\\":\\\"piece\\\",\\\"id\\\":\\\"sejour_cuisine\\\"}\""))
        assertEquals(null, Maison3dPont.texteRendu("null"))
        assertEquals(null, Maison3dPont.texteRendu(null))
        assertEquals(null, Maison3dPont.texteRendu("12"))
        assertEquals(null, Maison3dPont.texteRendu("\"\""))
    }
}
