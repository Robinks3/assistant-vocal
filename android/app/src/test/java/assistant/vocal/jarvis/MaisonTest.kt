package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Test

/** Lecteurs qui jouent le même morceau : une seule ligne dans « Maison » (0.16.1). */
class MaisonTest {

    @Test
    fun groupeQuiContientLesAutres() {
        val l = Maison.regrouperLecteurs(listOf(
            Maison.Lecteur("media_player.enceintes_maison", "Enceintes maison", "Titre", "Artiste",
                setOf("media_player.enceintes_maison", "media_player.enceinte_cuisine")),
            Maison.Lecteur("media_player.enceinte_cuisine", "Cuisine", "Titre", "Artiste"),
        ))
        assertEquals(listOf("Titre, Artiste sur Enceintes maison"), l)
    }

    @Test
    fun memeMorceauSansGroupe() {
        val l = Maison.regrouperLecteurs(listOf(
            Maison.Lecteur("media_player.a", "Enceintes maison", "Titre", "Artiste"),
            Maison.Lecteur("media_player.b", "Cuisine", "titre", "artiste"),
            Maison.Lecteur("media_player.c", "Chambre", "Autre", ""),
        ))
        assertEquals(listOf("Titre, Artiste sur Enceintes maison et Cuisine", "Autre sur Chambre"), l)
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
            action("light.turn_on", "light.salon_plafond"),
            action("light.turn_off", "light.cuisine_suspensions"),
            action("light.turn_on", "light.salon_lampe_tele", mapOf("brightness_pct" to "40")),
            action("light.toggle", "light.couloir_plafond"),
            action("light.turn_on", "light.chambre_sacha_plafond", mapOf("transition" to "2")),
            action("media_player.media_pause", "media_player.barre_son_salon"),
        ))
        assertEquals(mapOf(
            "light.salon_plafond" to "allumer", "light.cuisine_suspensions" to "eteindre", "light.salon_lampe_tele" to "regler",
            "light.couloir_plafond" to "basculer", "light.chambre_sacha_plafond" to "allumer",
        ), e)
    }

    @Test
    fun effetsParAssist() {
        val e = Maison.effetsLumieres(listOf(
            action("assist.HassTurnOff", "light.salon_plafond"),
            action("assist.HassTurnOn", "switch.prise"),
        ))
        assertEquals(mapOf("light.salon_plafond" to "eteindre"), e)
    }
}
