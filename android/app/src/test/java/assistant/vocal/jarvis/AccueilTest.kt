package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

/** Accueil de la tablette (0.18.0, 0.18.1) : modes, panne, salutation, date, météo, musique, phrases de la zone de texte. */
class AccueilTest {

    @Test
    fun modesSelonLEtatDuService() {
        assertEquals(Accueil.Mode.ARRETE, Accueil.mode(false, "Je t'écoute", "", 0L, 0L))
        assertEquals(Accueil.Mode.REPOS, Accueil.mode(true, "Repos", "", 0L, 0L))
        assertEquals(Accueil.Mode.ECOUTE, Accueil.mode(true, "Je t'écoute", "", 0L, 0L))
        assertEquals(Accueil.Mode.REFLEXION, Accueil.mode(true, "Je réfléchis", "", 0L, 0L))
        assertEquals(Accueil.Mode.REPONSE, Accueil.mode(true, "Je réponds", "C'est fait", 0L, 0L))
        // La réponse reste écrite 6 s après la fin de la voix, puis l'accueil revient au repos.
        assertEquals(Accueil.Mode.REPONSE, Accueil.mode(true, "Repos", "C'est fait", 10_000L, 15_999L))
        assertEquals(Accueil.Mode.REPOS, Accueil.mode(true, "Repos", "C'est fait", 10_000L, 16_000L))
        assertTrue(Accueil.occupe(Accueil.Mode.ECOUTE))
        assertFalse(Accueil.occupe(Accueil.Mode.REPOS))
    }

    private fun panne(
        enMarche: Boolean = true, connecte: Boolean = true, local: Boolean = true, passerelle: Boolean = true,
        maison: Boolean = true, vision: String = "ok", cle: String = "",
    ) = Accueil.panne(enMarche, connecte, local, passerelle, maison, vision, cle)

    @Test
    fun ligneDePanneSeulementEnCasDePanne() {
        assertEquals("", panne())
        assertEquals("Serveur injoignable", panne(connecte = false))
        assertEquals("Home Assistant ne répond plus", panne(passerelle = false))
        // Serveur PC ou HA : la maison lue suffit, sans passerelle locale.
        assertEquals("", panne(local = false, passerelle = false, maison = true))
        assertEquals("Home Assistant ne répond plus", panne(local = false, passerelle = false, maison = false))
        assertEquals("Caméra indisponible", panne(vision = "erreur"))
        // Vision désactivée ou qui démarre : rien à dire.
        assertEquals("", panne(vision = ""))
        assertEquals("", panne(vision = "attente"))
        // Ordre : le serveur d'abord, puis Home Assistant, puis la caméra.
        assertEquals("Serveur injoignable", panne(connecte = false, passerelle = false, vision = "erreur"))
        // Assistant à l'arrêt : l'arrêt se lit à gauche (Démarrer), pas en panne.
        assertEquals("", panne(enMarche = false, connecte = false))
        // La clé refusée passe avant tout.
        assertEquals("Clé du serveur refusée, voir l'écran Appareils", panne(cle = "La clé a changé", connecte = false))
    }

    @Test
    fun uneBreveCoupureNeSAffichePas() {
        val r = Accueil.Retenue(20_000L)
        assertEquals("", r.avancer("Serveur injoignable", 0L))
        assertEquals("", r.avancer("Serveur injoignable", 19_999L))
        assertEquals("Serveur injoignable", r.avancer("Serveur injoignable", 20_000L))
        // Une autre panne attend son délai, l'ancienne reste affichée d'ici là.
        assertEquals("Serveur injoignable", r.avancer("Home Assistant ne répond plus", 21_000L))
        assertEquals("Home Assistant ne répond plus", r.avancer("Home Assistant ne répond plus", 41_000L))
        // Tout revient : la ligne disparaît tout de suite.
        assertEquals("", r.avancer("", 41_500L))
        // Revenue avant le délai : rien ne s'affiche.
        assertEquals("", r.avancer("Caméra indisponible", 50_000L))
        assertEquals("", r.avancer("", 55_000L))
        assertEquals("", r.avancer("Caméra indisponible", 56_000L))
        assertEquals("Clé refusée", r.avancer("Clé refusée", 56_500L, immediat = true))
    }

    @Test
    fun bonjourOuBonsoirPourUnePersonneReconnue() {
        assertEquals("Bonjour Sacha", Accueil.salutation("Sacha", 10))
        assertEquals("Bonsoir Sacha", Accueil.salutation("Sacha", 18))
        assertEquals("Bonsoir Sacha", Accueil.salutation("Sacha", 2))
        assertEquals("Bonjour Sacha", Accueil.salutation("Sacha", 5))
        assertEquals("Bonjour Camille", Accueil.salutation(" Camille ", 9))
        // Inconnu : rien.
        assertEquals("", Accueil.salutation(null, 10))
        assertEquals("", Accueil.salutation(" ", 10))
    }

    @Test
    fun bonjourPendantDixSecondesApresUneReconnaissance() {
        val s = Accueil.Salut()
        assertEquals("Sacha", s.avancer("Sacha", 0L))
        assertEquals("Sacha", s.avancer("Sacha", 9_999L))
        assertEquals(null, s.avancer("Sacha", 10_000L))
        // La reconnaissance clignote : pas de nouveau bonjour tant que Sacha n'est pas parti une minute.
        assertEquals(null, s.avancer(null, 20_000L))
        assertEquals(null, s.avancer("Sacha", 30_000L))
        assertEquals("Sacha", s.avancer("Sacha", 100_000L))
        // Une autre personne est saluée tout de suite.
        assertEquals("Lou", s.avancer("Lou", 101_000L))
        assertEquals(null, s.avancer(null, 102_000L))
    }

    @Test
    fun dateEnToutesLettres() {
        assertEquals("Jeudi 22 octobre", Accueil.date(LocalDate.of(2026, 10, 22)))
        assertEquals("Dimanche 1er novembre", Accueil.date(LocalDate.of(2026, 11, 1)))
    }

    @Test
    fun meteoEnMots() {
        assertEquals("Éclaircies, 20 degrés", Accueil.meteo(Etat.Meteo("20 °C", "éclaircies", "partlycloudy")))
        assertEquals("", Accueil.meteo(null))
        assertEquals("1 degré", Accueil.degres("1 °C"))
        assertEquals("0 degré", Accueil.degres("0 °C"))
        assertEquals("moins 3 degrés", Accueil.degres("-3 °C"))
        // Signe moins typographique de certaines locales Java.
        assertEquals("moins 3 degrés", Accueil.degres(0x2212.toChar() + "3 °C"))
        assertEquals("moins 1 degré", Accueil.degres("-1 °C"))
        assertEquals("21 degrés", Accueil.degres("20,6 °C"))
        assertEquals("", Accueil.degres("--"))
        // Sans température lisible, le ciel seul.
        assertEquals("Pluie", Accueil.meteo(Etat.Meteo("--", "pluie", "rainy")))
    }

    @Test
    fun accordDuNombreDeLumieres() {
        assertEquals("1 lumière", Accueil.lumieres(1))
        assertEquals("2 lumières", Accueil.lumieres(2))
        assertEquals("0 lumière", Accueil.lumieres(0))
    }

    private fun lecteur(id: String, etat: String = "playing", nom: String = "", membres: Set<String> = emptySet()) =
        Etat.Lecteur(id, nom, etat, "Titre", "Artiste", "", 0.0, 0.0, 0L, 0.3, membres)

    @Test
    fun lieuDeLaMusique() {
        assertEquals("Dans le salon", Accueil.lieuMusique(lecteur("media_player.salon")))
        assertEquals("Dans la cuisine", Accueil.lieuMusique(lecteur("media_player.chambre", "paused")))
        // Un groupe Enceintes qui joue sur le salon et la cuisine.
        assertEquals(
            "Dans le salon et la cuisine",
            Accueil.lieuMusique(lecteur("media_player.salon", membres = setOf("media_player.salon", "media_player.chambre"))),
        )
        // Lecteur hors de la sortie du son : son nom tel que HA le donne.
        assertEquals("Sur Enceintes Maison", Accueil.lieuMusique(lecteur("media_player.enceintes", nom = "Enceintes Maison")))
        assertEquals("l'entrée", Accueil.article("Entrée"))
        assertEquals("le bureau", Accueil.article("Bureau"))
        assertEquals("la chambre Sacha", Accueil.article("Chambre Sacha"))
        assertEquals("les chevets Sacha", Accueil.article("Chevets Sacha"))
    }

    @Test
    fun piecesAllumeesEnUnePhrase() {
        val une = Accueil.phraseLumieres(listOf("Séjour"))!!
        assertEquals("Le séjour est allumé.", une.texte)
        // Seul le mot « allumé » est en ambre.
        assertEquals("allumé", une.texte.substring(une.ambre!!))
        assertEquals("La salle à manger est allumée.", Accueil.phraseLumieres(listOf("Salle à manger"))!!.texte)
        assertEquals("L'entrée est allumée.", Accueil.phraseLumieres(listOf("Entrée"))!!.texte)
        val deux = Accueil.phraseLumieres(listOf("Séjour", "Salle à manger"))!!
        assertEquals("Le séjour et la salle à manger sont allumés.", deux.texte)
        assertEquals("allumés", deux.texte.substring(deux.ambre!!))
        assertEquals("La salle à manger et l'entrée sont allumées.", Accueil.phraseLumieres(listOf("Salle à manger", "Entrée"))!!.texte)
        val trois = Accueil.phraseLumieres(listOf("Séjour", "Salle à manger", "Entrée"))!!
        assertEquals("Trois pièces allumées.", trois.texte)
        assertEquals("allumées", trois.texte.substring(trois.ambre!!))
        assertEquals("Douze pièces allumées.".replace("Douze", "12"), Accueil.phraseLumieres((1..12).map { "Pièce $it" })!!.texte)
        // Rien d'allumé, ou des doublons : pas de phrase, ou une seule pièce.
        assertEquals(null, Accueil.phraseLumieres(emptyList()))
        assertEquals("Le séjour est allumé.", Accueil.phraseLumieres(listOf("Séjour", "Séjour", " "))!!.texte)
    }

    @Test
    fun echecEtPanneEnMots() {
        assertEquals("Je n'ai pas pu allumer le salon, la maison ne répond pas.", Accueil.echec(listOf("Salon"), "allumer"))
        assertEquals("Je n'ai pas pu éteindre la lampe TV, la maison ne répond pas.", Accueil.echec(listOf("Lampe TV"), "eteindre"))
        assertEquals("Je n'ai pas pu régler le salon et la lampe TV, la maison ne répond pas.", Accueil.echec(listOf("Salon", "Lampe TV"), "regler"))
        assertEquals("Je n'ai pas pu allumer les lumières, la maison ne répond pas.", Accueil.echec(emptyList(), "allumer"))
        assertEquals("La maison ne répond plus depuis 10 h 02.", Accueil.phrasePanne(10, 2))
        assertEquals("La maison ne répond plus depuis 0 h 45.", Accueil.phrasePanne(0, 45))
    }

    @Test
    fun pluieDansLesDouzeHeures() {
        val paris = java.time.ZoneId.of("Europe/Paris")
        val maintenant = java.time.ZonedDateTime.of(2026, 10, 22, 11, 20, 0, 0, paris)
        fun h(dh: Long, condition: String, pluie: Int? = null) =
            Previsions.Prevision(maintenant.withMinute(0).plusHours(dh).toInstant().toEpochMilli(), condition, 15.0, pluie)
        assertEquals("Pluie vers 17 h.", Accueil.pluie(listOf(h(-1, "rainy"), h(0, "sunny", 10), h(6, "cloudy", 60), h(7, "rainy")), maintenant))
        assertEquals("Pluie en ce moment.", Accueil.pluie(listOf(h(0, "pouring")), maintenant))
        assertEquals("Neige vers 13 h.", Accueil.pluie(listOf(h(2, "snowy")), maintenant))
        // Au-delà de douze heures, ou sans prévision : rien.
        assertEquals("", Accueil.pluie(listOf(h(12, "rainy")), maintenant))
        assertEquals("", Accueil.pluie(emptyList(), maintenant))
        assertEquals("", Accueil.pluie(listOf(h(3, "cloudy", 40)), maintenant))
    }

    @Test
    fun pointsDeLaCoucheDeService() {
        val P = Accueil.Point.OK
        assertEquals(listOf(P, P, P), Accueil.points(true, true, true, true, true, "ok"))
        assertEquals(listOf(P, Accueil.Point.PANNE, Accueil.Point.ETEINT), Accueil.points(true, true, true, false, false, ""))
        assertEquals(listOf(Accueil.Point.PANNE, P, Accueil.Point.PANNE), Accueil.points(true, false, false, false, true, "erreur"))
        assertEquals(List(3) { Accueil.Point.ETEINT }, Accueil.points(false, false, true, false, false, "ok"))
    }

    @Test
    fun accordDesParticipes() {
        assertEquals("allumé", Accord.participe(listOf("Salon"), "allumer"))
        assertEquals("allumée", Accord.participe(listOf("Lampe TV"), "allumer"))
        assertEquals("éteinte", Accord.participe(listOf("Cuisine"), "eteindre"))
        assertEquals("allumés", Accord.participe(listOf("Chevets Sacha"), "allumer"))
        assertEquals("allumés", Accord.participe(listOf("Salon", "Lampe TV"), "allumer"))
        assertEquals("allumées", Accord.participe(listOf("Lampe TV", "Cuisine"), "allumer"))
        assertEquals("réglé", Accord.participe(listOf("Plafond Sacha"), "regler"))
        assertEquals("éteints", Accord.participe(listOf("Plafond Sacha", "Salon"), "eteindre"))
    }

    @Test
    fun valeursEnCouleurSeulement() {
        // 0.19.0 : seules les valeurs prennent une teinte au repos.
        val m = "Éclaircies, 20 degrés"
        assertEquals("20 degrés", Accueil.valeurMeteo(m)?.let { m.substring(it.first, it.last + 1) })
        val f = "Neige, moins 3 degrés"
        assertEquals("moins 3 degrés", Accueil.valeurMeteo(f)?.let { f.substring(it.first, it.last + 1) })
        val p = "Pluie vers 17 h."
        assertEquals("17 h", Accueil.valeurPluie(p)?.let { p.substring(it.first, it.last + 1) })
        val q = "Pluie en ce moment."
        assertEquals("en ce moment", Accueil.valeurPluie(q)?.let { q.substring(it.first, it.last + 1) })
    }

    @Test
    fun couleurReelleDesLampes() {
        val defaut = Palette.c("#F0B46A")
        fun lampe(lum: Int, rgb: List<Int>? = null, k: Int? = null) =
            Appareils.Appareil("light.a$lum", "A", "on", "sejour", "Séjour", lum, rgb = rgb, kelvin = k)
        assertEquals(defaut, Accueil.couleurLampes(emptyList(), defaut))
        assertEquals(defaut, Accueil.couleurLampes(listOf(lampe(60)), defaut))
        // La plus lumineuse donne sa couleur.
        assertEquals("#FF5000", Palette.hex(Accueil.couleurLampes(listOf(lampe(20, listOf(0, 255, 0)), lampe(80, listOf(255, 80, 0))), defaut)))
        // Un bleu profond est éclairci pour se lire sur le noir.
        val bleu = Accueil.couleurLampes(listOf(lampe(60, listOf(0, 0, 255))), defaut)
        assertTrue(Palette.luminance(bleu) >= Accueil.LUMINANCE_LISIBLE)
        assertTrue((bleu and 0xFF) == 255)
        // Un blanc chaud en kelvins.
        assertEquals(Palette.kelvin(2700), Accueil.couleurLampes(listOf(lampe(60, k = 2700)), defaut))
    }
}
