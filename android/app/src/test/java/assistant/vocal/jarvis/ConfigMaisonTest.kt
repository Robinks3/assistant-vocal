package assistant.vocal.jarvis

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Test

/** Nom affiché de l'assistant, lu dans la section assistant de config-exemple/maison.json. */
class ConfigMaisonTest {
    @Test
    fun nomAssistantLuDansLaConfiguration() {
        assertEquals("Iris", ConfigMaison.NOM_ASSISTANT)
    }

    @Test
    fun nomAssistantParDefautSiSectionAbsenteOuMalFormee() {
        for (json in listOf("{}", """{"assistant":{}}""", """{"assistant":{"nom":"  "}}""", """{"assistant":"Iris"}""",
                """{"assistant":{"nom":42}}""", """{"assistant":{"nom":null}}""", """{"assistant":["Iris"]}""")) {
            assertEquals(json, "Assistant", ConfigMaison.nomAssistant(JSONObject(json)))
        }
        assertEquals("Jeeves", ConfigMaison.nomAssistant(JSONObject("""{"assistant":{"nom":" Jeeves "}}""")))
    }

    @Test
    fun leNomDeLAssistantNePassePasPourHomeAssistant() {
        assertEquals("jarvis", Maison.voie("Assistant", "palette", "C'est fait.", "Assistant"))
        assertEquals("claude", Maison.voie("Claude Haiku", "appli Assistant sur la tablette", "C'est fait.", "Assistant"))
        assertEquals("jarvis", Maison.voie("Hal", "", "C'est fait.", "Hal"))
        assertEquals("dictionnaire", Maison.voie("Iris", "dictionnaire", "C'est fait.", "Iris"))
        // Home Assistant reste reconnu même quand l'assistant s'appelle « Assistant ».
        assertEquals("ha", Maison.voie("Home Assistant", "", "C'est fait.", "Assistant"))
        assertEquals("ha", Maison.voie("HA", "conversation", "C'est fait.", "Iris"))
    }
}
