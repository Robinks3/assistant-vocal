package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Test

/** Lecteur suivi par la carte de l'accueil (25/10/2026 : volume du compte Spotify montré à la place des enceinte). */
class CarteEnCoursSuiviTest {

    private fun l(id: String, etat: String, volume: Double, membres: Set<String> = emptySet()) =
        Etat.Lecteur(id, id, etat, "", "", "", 0.0, 0.0, 0L, volume, membres)

    private val salon = SortieSon.ENCEINTES[0].first
    private val cuisine = SortieSon.ENCEINTES[1].first

    @Test
    fun uneEnceinteQuiJouePasseAvantSpotify() {
        val spotify = l("media_player.spotify_sacha", "playing", 1.0)
        val lecteurs = listOf(spotify, l(cuisine, "playing", 0.3), l(salon, "playing", 0.3, setOf(salon, cuisine)))
        // Le meneur du groupe, pas le premier lecteur ni le compte Spotify à 100 %.
        assertEquals(salon, CarteEnCours.suivi(lecteurs).id)
        // Un choix fait au doigt reste respecté.
        assertEquals(spotify.id, CarteEnCours.suivi(lecteurs, spotify.id).id)
    }

    @Test
    fun memeListeDeMembresLeMeneurEnTeteGagne() {
        // HA donne la même liste group_members à chaque membre, le meneur en tête.
        val groupe = linkedSetOf(salon, cuisine)
        val lecteurs = listOf(l(cuisine, "playing", 0.5, groupe), l(salon, "buffering", 0.3, groupe))
        assertEquals(salon, CarteEnCours.suivi(lecteurs).id)
    }

    @Test
    fun sansEnceinteQuiJoueLeRestePareil() {
        val spotify = l("media_player.spotify_sacha", "playing", 1.0)
        assertEquals(spotify.id, CarteEnCours.suivi(listOf(l(salon, "idle", 0.3), spotify)).id)
        assertEquals(salon, CarteEnCours.suivi(listOf(l(cuisine, "idle", 0.3), l(salon, "paused", 0.3))).id)
    }
}
