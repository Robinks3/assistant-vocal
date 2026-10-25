package assistant.vocal.jarvis

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Écran Maison connectée et bulle Maison (0.17.0) : Camille, décompte des lampes, commandes. */
class AppareilsTest {

    private fun lumiere(id: String, etat: String, zone: String, piece: String, membres: List<String> = emptyList(), nom: String = id) =
        Appareils.Appareil(id, nom, etat, zone, piece, if (etat == "on") 60 else null, null, listOf("color_temp", "xy"), membres)

    /** Les lumières de l'appartement lues le 22/10/2026, toutes allumées, avec celles de Camille. */
    private val maison = listOf(
        lumiere("light.exemple11", "on", "chambre_sacha", "Chambre Sacha",
            listOf("light.exemple12", "light.exemple13")),
        lumiere("light.exemple12", "on", "chambre_sacha", "Chambre Sacha"),
        lumiere("light.exemple13", "on", "chambre_sacha", "Chambre Sacha"),
        lumiere("light.exemple14", "on", "chambre_sacha", "Chambre Sacha"),
        lumiere("light.cuisine", "on", "cuisine", "Séjour", listOf("light.exemple15", "light.exemple16")),
        lumiere("light.exemple15", "on", "salle_a_manger", "Salle à manger"),
        lumiere("light.exemple16", "on", "salle_a_manger", "Salle à manger"),
        lumiere("light.exemple7", "on", "cuisine", "Séjour"),
        lumiere("light.exemple6", "on", "cuisine", "Séjour"),
        lumiere("light.exemple17", "on", "entree", "Entrée"),
        lumiere("light.chambre_camille", "on", "chambre_camille", "Chambre Camille"),
        lumiere("light.exemple18", "on", "chambre_camille", "Chambre Camille"),
        // Une lampe de Camille dont ni le nom ni l'identifiant ne le disent : écartée par sa pièce.
        lumiere("light.exemple19", "on", "chambre_camille", "Chambre Camille", nom = "Lampe bureau"),
    )

    @Test
    fun lesGroupesNeSontPasComptesDeuxFois() {
        org.junit.Assume.assumeTrue("règle levée le 22/10/2026", Securite.PROTEGER_OCCUPANT)
        // 10 entrées sans Camille, mais 8 lampes : les deux groupes ne comptent pas.
        val allumees = Appareils.lumieresAllumees(maison, "")
        assertEquals(8, allumees.size)
        assertFalse(allumees.any { it.id == "light.exemple11" || it.id == "light.cuisine" })
        assertEquals(listOf("Séjour", "Salle à manger", "Entrée", "Chambre Sacha"), Appareils.piecesAllumees(allumees))
    }

    @Test
    fun rienDeCamilleSaufSesLumieresPourLui() {
        org.junit.Assume.assumeTrue("règle levée le 22/10/2026", Securite.PROTEGER_OCCUPANT)
        val pourSacha = Appareils.montres(maison, "Sacha")
        assertFalse(pourSacha.any { it.zone == "chambre_camille" })
        assertEquals(8, Appareils.lumieresAllumees(maison, "").size)
        // Camille reconnu : ses deux lumières permises apparaissent, pas la lampe de sa pièce hors de la liste.
        val pourCamille = Appareils.montres(maison, "Camille")
        assertTrue(pourCamille.any { it.id == "light.chambre_camille" })
        assertTrue(pourCamille.any { it.id == "light.exemple18" })
        assertFalse(pourCamille.any { it.id == "light.exemple19" })
        assertEquals(10, Appareils.lumieresAllumees(maison, "Camille").size)
        // Personne d'inconnu : rien de Camille.
        assertFalse(Appareils.montres(maison, "inconnu").any { it.zone == "chambre_camille" })
    }

    @Test
    fun unGroupeQuiContientUneLampeDeCamilleEstCache() {
        org.junit.Assume.assumeTrue("règle levée le 22/10/2026", Securite.PROTEGER_OCCUPANT)
        val g = lumiere("light.tout", "on", "", "", listOf("light.exemple6", "light.chambre_camille"))
        assertFalse(Appareils.visible(g, "Sacha"))
    }

    @Test
    fun filtresParPieceEtMedias() {
        org.junit.Assume.assumeTrue("règle levée le 22/10/2026", Securite.PROTEGER_OCCUPANT)
        val tele = Appareils.Appareil("media_player.exemple20", "TV", "off", "cuisine", "Séjour", classe = "tv")
        val doublon = Appareils.Appareil("media_player.tv", "TV", "idle", "", "", classe = "speaker")
        val salon = Appareils.Appareil("media_player.salon", "Salon", "playing", "", "", volume = 0.3)
        val aspirateur = Appareils.Appareil("vacuum.robot", "Aspirateur robot", "docked", "cuisine", "Séjour")
        val montres = Appareils.montres(maison + listOf(tele, doublon, salon, aspirateur), "")
        assertFalse(montres.any { it.id == "media_player.tv" })
        val f = Appareils.filtres(montres).map { it.second }
        assertEquals(listOf("Toutes", "Séjour", "Salle à manger", "Entrée", "Chambre Sacha", "Musique et télé", "Aspirateur"), f)
        assertEquals(setOf("media_player.exemple20", "media_player.salon"),
            Appareils.filtrer(montres, Appareils.FILTRE_MEDIAS).map { it.id }.toSet())
        assertTrue(Appareils.filtrer(montres, "cuisine").all { it.domaine == "light" })
    }

    @Test
    fun commandesDesTuiles() {
        val salon = maison.first { it.id == "light.exemple6" }
        assertEquals("light.turn_off", Appareils.basculer(salon)!!.service)
        assertEquals("light.turn_on", Appareils.basculer(salon.copy(etat = "off"))!!.service)
        val c = Appareils.regler(salon, 0.4f)!!
        assertEquals(40, c.corps.getInt("brightness_pct"))
        assertEquals("light.turn_off", Appareils.regler(salon, 0f)!!.service)
        val enceinte = Appareils.Appareil("media_player.chambre", "Cuisine", "playing", "", "", volume = 0.3)
        assertEquals("media_player.media_pause", Appareils.basculer(enceinte)!!.service)
        assertEquals(0.45, Appareils.regler(enceinte, 0.45f)!!.corps.getDouble("volume_level"), 1e-9)
        // Sans plafond (config-exemple comme celle du propriétaire, 25/10/2026) : toute la tuile, jusqu'à 100 %.
        assertEquals(0.55, Appareils.regler(enceinte, 0.55f)!!.corps.getDouble("volume_level"), 1e-9)
        assertEquals(1.0, Appareils.regler(enceinte, 1f)!!.corps.getDouble("volume_level"), 1e-9)
        val tele = Appareils.Appareil("media_player.exemple20", "TV", "on", "", "", classe = "tv")
        assertEquals("media_player.turn_off", Appareils.basculer(tele)!!.service)
        assertEquals("vacuum.start", Appareils.basculer(Appareils.Appareil("vacuum.r", "A", "docked", "", ""))!!.service)
        // Blanc borné à ce que la lampe accepte.
        val lampe = salon.copy(kelvinMin = 2202, kelvinMax = 6535)
        assertEquals(6535, Appareils.blanc(lampe, 9000).corps.getInt("color_temp_kelvin"))
    }

    @Test
    fun toutEteindreLesPiecesCommunes() {
        val c = Appareils.toutEteindre(Appareils.montres(maison, ""))!!
        val ids = (0 until c.corps.getJSONArray("entity_id").length()).map { c.corps.getJSONArray("entity_id").getString(it) }
        assertTrue("light.exemple6" in ids && "light.exemple17" in ids && "light.exemple15" in ids)
        assertFalse(ids.any { it.contains("sacha") || it.contains("camille") })
        assertNull(Appareils.toutEteindre(emptyList()))
        // La sécurité laisse passer : rien de Camille, pas de son.
        assertNull(Securite.verifier(c.verification(), heure = 2))
    }

    @Test
    fun laSecuriteRefuseCamillePourSacha() {
        org.junit.Assume.assumeTrue("règle levée le 22/10/2026", Securite.PROTEGER_OCCUPANT)
        val t = maison.first { it.id == "light.chambre_camille" }
        val c = Appareils.basculer(t)!!
        assertTrue(Securite.verifier(c.verification(), heure = 12, personne = "Sacha") != null)
        assertNull(Securite.verifier(c.verification(), heure = 12, personne = "Camille"))
    }

    @Test
    fun lectureDuModele() {
        val o = JSONObject("""{"id":"light.exemple6","nom":"Salon","etat":"on","zone":"cuisine","piece":"Séjour","lum":102,
            "modes":["color_temp","xy"],"membres":[],"volume":null,"sources":[],"source":"","classe":"","kmin":2202,"kmax":6535}""")
        val a = Appareils.lire(o)!!
        assertEquals(40, a.luminosite)
        assertNull(a.volume)
        assertTrue(a.couleur && a.blanc && a.reglable)
        assertEquals("allumée à 40 %", Appareils.etatLisible(a))
        assertEquals("1 lumière allumée : Séjour", Appareils.resume(listOf(a)))
    }

    @Test
    fun unGroupeUneSeuleTuileSesLampesEnSousNiveau() {
        // 0.17.2 : plus de tuile à part pour les lampes d'un groupe montré.
        val montres = Appareils.montres(maison, "Sacha")
        val tuiles = Appareils.regrouper(Appareils.filtrer(montres, Appareils.FILTRE_TOUTES))
        val ids = tuiles.map { it.appareil.id }
        assertTrue("light.exemple11" in ids && "light.cuisine" in ids)
        for (lampe in listOf("light.exemple12", "light.exemple13",
            "light.exemple15", "light.exemple16")) {
            assertFalse("$lampe a encore sa tuile", lampe in ids)
        }
        val chevets = tuiles.first { it.appareil.id == "light.exemple11" }
        assertTrue(chevets.groupe)
        assertEquals(setOf("light.exemple12", "light.exemple13"), chevets.lampes.map { it.id }.toSet())
        assertEquals("2 lampes", Appareils.nombreLampes(chevets.lampes.size))
        assertEquals("1 lampe", Appareils.nombreLampes(1))
        // Une lampe seule garde sa tuile, sans sous-niveau.
        val plafond = tuiles.first { it.appareil.id == "light.exemple14" }
        assertFalse(plafond.groupe)
        assertTrue(plafond.lampes.isEmpty())
        // Filtre Salle à manger : le groupe Cuisine est au Séjour, ses lampes gardent donc leur tuile.
        val salle = Appareils.regrouper(Appareils.filtrer(montres, "salle_a_manger")).map { it.appareil.id }
        assertEquals(listOf("light.exemple15", "light.exemple16"), salle)
        // Le décompte de la bulle ne change pas : les lampes réelles, sans les groupes.
        val allumees = Appareils.lumieresAllumees(maison, "Sacha").map { it.id }
        assertFalse("light.exemple11" in allumees || "light.cuisine" in allumees)
        assertTrue("light.exemple15" in allumees)
    }

    @Test
    fun `le code d'appairage a 6 chiffres (invitation) ou 8 (amorcage)`() {
        assertTrue(Appareils.codeAmorcageValide("123456"))
        assertTrue(Appareils.codeAmorcageValide("12345678"))
        assertFalse(Appareils.codeAmorcageValide("1234567"))
        assertFalse(Appareils.codeAmorcageValide("12345"))
        assertFalse(Appareils.codeAmorcageValide(""))
    }
}
