package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Test

/** Lecteurs qui jouent le même morceau : une seule ligne dans « Maison » (0.16.1). */
class MaisonTest {

    @Test
    fun groupeQuiContientLesAutres() {
        val l = Maison.regrouperLecteurs(listOf(
            Maison.Lecteur("media_player.exemple22", "Enceintes Maison", "Titre", "Artiste",
                setOf("media_player.exemple22", "media_player.cuisine")),
            Maison.Lecteur("media_player.cuisine", "Cuisine", "Titre", "Artiste"),
        ))
        assertEquals(listOf("Titre, Artiste sur Enceintes Maison"), l)
    }

    @Test
    fun memeMorceauSansGroupe() {
        val l = Maison.regrouperLecteurs(listOf(
            Maison.Lecteur("media_player.a", "Enceintes Maison", "Titre", "Artiste"),
            Maison.Lecteur("media_player.b", "Cuisine", "titre", "artiste"),
            Maison.Lecteur("media_player.c", "Chambre", "Autre", ""),
        ))
        assertEquals(listOf("Titre, Artiste sur Enceintes Maison et Cuisine", "Autre sur Chambre"), l)
    }

    @Test
    fun sansTitreChacunSaLigne() {
        val l = Maison.regrouperLecteurs(listOf(
            Maison.Lecteur("media_player.a", "Salon", "", ""),
            Maison.Lecteur("media_player.b", "Cuisine", "", ""),
        ))
        assertEquals(listOf("lecture en cours sur Salon", "lecture en cours sur Cuisine"), l)
    }

    private fun action(service: String, entite: String, donnees: Map<String, String> = emptyMap()) =
        Maison.ActionLue(service, listOf(entite), donnees, essai = false, refusee = false, ecartee = false)

    @Test
    fun effetsDesLumieres() {
        val e = Maison.effetsLumieres(listOf(
            action("light.turn_on", "light.exemple6"),
            action("light.turn_off", "light.cuisine"),
            action("light.turn_on", "light.exemple7", mapOf("brightness_pct" to "40")),
            action("light.toggle", "light.exemple17"),
            action("light.turn_on", "light.exemple14", mapOf("transition" to "2")),
            action("media_player.media_pause", "media_player.salon"),
        ))
        assertEquals(mapOf(
            "light.exemple6" to "allumer", "light.cuisine" to "eteindre", "light.exemple7" to "regler",
            "light.exemple17" to "basculer", "light.exemple14" to "allumer",
        ), e)
    }

    @Test
    fun effetsParAssist() {
        val e = Maison.effetsLumieres(listOf(
            action("assist.HassTurnOff", "light.exemple6"),
            action("assist.HassTurnOn", "switch.prise"),
        ))
        assertEquals(mapOf("light.exemple6" to "eteindre"), e)
    }
}
