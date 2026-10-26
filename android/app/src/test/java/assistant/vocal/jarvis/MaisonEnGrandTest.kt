package assistant.vocal.jarvis

import org.json.JSONArray
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** La maison en grand (0.27.0) : contenu des pièces, étiquettes, pastilles, attentes, cadence d'envoi. */
class MaisonEnGrandTest {

    /** Ce que rend maison3d.contenu() pour la page 0.8.0 (pièces de l'appartement d'origine). */
    private val contenu = """
        [{"id":"sejour_cuisine","nom":"Séjour et cuisine","lampes":[{"entite":"light.cuisine_suspensions","nom":""},{"entite":"light.salon_plafond","nom":"Salon"},{"entite":"light.salon_lampe_tele","nom":"Lampe TV"}],
          "medias":[{"entite":"media_player.tele_salon","nom":"Télévision","type":"tele","alias":[]},{"entite":"media_player.barre_son_salon","nom":"Barre de son du salon","type":"enceinte","alias":["media_player.barre_son_salon_enceintes"]},{"entite":"media_player.enceinte_cuisine","nom":"Enceinte de la cuisine","type":"enceinte","alias":[]}]},
         {"id":"entree_couloir","nom":"Entrée et couloir","lampes":[{"entite":"light.couloir_plafond","nom":"Entrée"}],"medias":[]},
         {"id":"salle_de_bain","nom":"Salle de bain","lampes":[],"medias":[]},
         {"id":"chambre_sacha","nom":"Chambre de Sacha","lampes":[{"entite":"light.chambre_sacha_chevets","nom":""},{"entite":"light.chambre_sacha_plafond","nom":"Plafond Sacha"}],"medias":[]},
         {"id":"chambre_camille","nom":"Chambre de Camille","lampes":[{"entite":"light.chambre_camille_plafonds","nom":""},{"entite":"light.chambre_camille_chevet","nom":"Chevet Camille"}],"medias":[]}]
    """.trimIndent()

    private fun lampe(id: String, etat: String, lum: Int? = null, modes: List<String> = listOf("brightness")) =
        Appareils.Appareil(id, id, etat, "", "", luminosite = lum, modes = modes)

    private fun media(id: String, etat: String, volume: Double? = null) =
        Appareils.Appareil(id, id, etat, "", "", volume = volume)

    private val pieces = MaisonEnGrand.lireContenu(contenu)
    private val sejour = pieces.first { it.id == "sejour_cuisine" }

    private val lus = MaisonEnGrand.index(
        listOf(
            lampe("light.salon_plafond", "on", 80), lampe("light.salon_lampe_tele", "on", 60),
            lampe("light.cuisine_suspensions", "on", modes = listOf("onoff")), lampe("light.couloir_plafond", "off"),
            lampe("light.chambre_sacha_plafond", "off"), lampe("light.chambre_sacha_chevets", "off"),
            lampe("light.chambre_camille_plafonds", "off"), lampe("light.chambre_camille_chevet", "off"),
        ),
        listOf(media("media_player.tele_salon", "on"), media("media_player.barre_son_salon", "playing", 0.3), media("media_player.enceinte_cuisine", "unavailable")),
    )

    @Test
    fun contenuLuLampesPuisTelePuisEnceintes() {
        assertEquals(5, pieces.size)
        assertEquals(listOf("light.cuisine_suspensions", "light.salon_plafond", "light.salon_lampe_tele", "media_player.tele_salon", "media_player.barre_son_salon", "media_player.enceinte_cuisine"), sejour.objets.map { it.entite })
        assertEquals(MaisonEnGrand.Genre.TELE, sejour.tele?.genre)
        assertEquals(listOf("media_player.barre_son_salon_enceintes"), sejour.enceintes.first().alias)
        assertTrue(MaisonEnGrand.lireContenu("pas du json").isEmpty())
        assertTrue(MaisonEnGrand.lireContenu(null).isEmpty())
    }

    @Test
    fun chaquePieceQuiARegler_portesSonNom_chambreDeCamilleComprise() {
        val e = MaisonEnGrand.etiquettes(pieces, lus, "Sacha", injoignable = false)
        val ids = (0 until e.length()).map { e.getJSONObject(it).getString("piece") }
        // La salle de bain n'a rien à régler : pas de nom au sol. La chambre de Camille (groupe et chevet) en a un.
        assertEquals(listOf("sejour_cuisine", "entree_couloir", "chambre_sacha", "chambre_camille"), ids)
        val s = e.getJSONObject(0)
        assertEquals("3 allumées, télé allumée, musique", s.getString("etat"))
        assertEquals("éteinte", e.getJSONObject(1).getString("etat"))
    }

    @Test
    fun pieceProtegee_resteNommeeAvecUnCadenas_sansRienDireDeSesLampes() {
        val e = MaisonEnGrand.etiquettes(pieces, lus, "Sacha", injoignable = false, estProtegee = { it.id == "chambre_camille" })
        val t = (0 until e.length()).map { e.getJSONObject(it) }.first { it.getString("piece") == "chambre_camille" }
        assertTrue(t.getBoolean("verrou"))
        assertEquals("", t.getString("etat"))
        assertEquals("Chambre de Camille", t.getString("nom"))
    }

    @Test
    fun drapeauDeLOccupantLeve_aucunePieceProtegee() {
        // Securite.PROTEGER_OCCUPANT est à false depuis le 22/10/2026 (demande du propriétaire).
        assertFalse(pieces.any { MaisonEnGrand.protegee(it, lus, "") })
    }

    @Test
    fun pastillesPartout_lampesGroupesTeleEtEnceintes() {
        val p = MaisonEnGrand.pastilles(sejour, lus, emptyMap(), "light.salon_lampe_tele", injoignable = false)
        assertEquals(6, p.length())
        val par = (0 until p.length()).associate { p.getJSONObject(it).getString("entite") to p.getJSONObject(it) }
        assertEquals(0.8, par.getValue("light.salon_plafond").getDouble("fraction"), 1e-9)
        assertEquals("tele", par.getValue("media_player.tele_salon").getString("genre"))
        assertTrue(par.getValue("media_player.tele_salon").getBoolean("allume"))
        // Volume de 30 %, sans plafond (config-exemple) : 0,3 de l'arc.
        assertEquals(0.3, par.getValue("media_player.barre_son_salon").getDouble("fraction"), 1e-9)
        assertEquals("hors", par.getValue("media_player.enceinte_cuisine").getString("etat"))
        assertTrue(par.getValue("light.salon_lampe_tele").getBoolean("surligne"))
        // La chambre de Sacha a les siennes, plafond et chevets.
        val c = MaisonEnGrand.pastilles(pieces.first { it.id == "chambre_sacha" }, lus, emptyMap(), null, false)
        assertEquals(setOf("light.chambre_sacha_chevets", "light.chambre_sacha_plafond"), (0 until c.length()).map { c.getJSONObject(it).getString("entite") }.toSet())
        // Maison injoignable : tout est hors ligne.
        val h = MaisonEnGrand.pastilles(sejour, lus, emptyMap(), null, injoignable = true)
        assertTrue((0 until h.length()).all { h.getJSONObject(it).getString("etat") == "hors" })
    }

    @Test
    fun nomsCourtsEtAccords() {
        assertEquals("Suspension", MaisonEnGrand.nom(sejour.objets[1], null))
        assertEquals("allumée, 80 %", MaisonEnGrand.etatLampe("Suspension", lus["light.salon_plafond"]))
        assertEquals("allumée", MaisonEnGrand.etatLampe("Cuisine", lus["light.cuisine_suspensions"]))
        assertEquals("éteints", MaisonEnGrand.etatLampe("Chevets", lus["light.chambre_sacha_chevets"]))
        assertEquals("éteint", MaisonEnGrand.etatLampe("Plafond", lus["light.chambre_sacha_plafond"]))
        assertEquals("hors ligne", MaisonEnGrand.etatLampe("Suspension", null))
        assertEquals("3 lampes allumées", MaisonEnGrand.resume(sejour, lus))
        assertEquals("Lampes éteintes", MaisonEnGrand.resume(pieces.first { it.id == "chambre_sacha" }, lus))
        assertEquals("La lampe de la télé n'a pas répondu.", MaisonEnGrand.phraseEchec(listOf("Lampe de la télé")))
        assertEquals("La suspension et le plafond n'ont pas répondu.", MaisonEnGrand.phraseEchec(listOf("Suspension", "Plafond")))
        assertEquals("L'entrée n'a pas répondu.", MaisonEnGrand.phraseEchec(listOf("Entrée")))
    }

    @Test
    fun aliasRepondQuandLEntiteEstHorsLigne() {
        val o = sejour.enceintes.first()
        val l = mapOf(
            "media_player.barre_son_salon" to media("media_player.barre_son_salon", "unavailable"),
            "media_player.barre_son_salon_enceintes" to media("media_player.barre_son_salon_enceintes", "playing", 0.2),
        )
        assertEquals("media_player.barre_son_salon_enceintes", MaisonEnGrand.trouver(o, l)?.id)
    }

    @Test
    fun attente_confirmee_ou_echec_apres_5s_garde_8s() {
        val a = Attentes()
        val avant = lampe("light.salon_lampe_tele", "on", 60)
        a.poser(MaisonEnGrand.prevuIntensite(avant, 30), 0L)
        // Tout de suite : l'état prévu est montré.
        assertEquals(30, a.vus(mapOf(avant.id to avant)).getValue(avant.id).luminosite)
        assertTrue(a.enAttente)
        // 5 s sans confirmation : échec, fantôme à 30 %, l'état lu revient.
        assertTrue(a.avancer(mapOf(avant.id to avant), 5_000L))
        assertEquals(30, a.fantome(avant.id)?.luminosite)
        assertEquals(60, a.vus(mapOf(avant.id to avant)).getValue(avant.id).luminosite)
        assertEquals(listOf(avant.id), a.echecs)
        // 8 s plus tard l'échec est oublié.
        a.avancer(mapOf(avant.id to avant), 13_000L)
        assertNull(a.fantome(avant.id))
        // Une lecture conforme (à 2 points près) confirme.
        a.poser(MaisonEnGrand.prevuIntensite(avant, 30), 20_000L)
        a.avancer(mapOf(avant.id to avant.copy(luminosite = 31)), 21_000L)
        assertFalse(a.enAttente)
        assertTrue(a.echecs.isEmpty())
    }

    @Test
    fun attente_volume_comparee_au_volume_seul() {
        val e = media("media_player.barre_son_salon", "playing", 0.3)
        assertTrue(Attentes.conforme(e.copy(volume = 0.39), e.copy(volume = 0.4), volume = true))
        assertFalse(Attentes.conforme(e.copy(volume = 0.3), e.copy(volume = 0.4), volume = true))
        val tele = media("media_player.tele_salon", "on", 0.2)
        // Télé éteinte : HA ne dit plus son volume, la demande d'arrêt est pourtant confirmée.
        assertTrue(Attentes.conforme(tele.copy(etat = "off", volume = null), tele.copy(etat = "off")))
    }

    @Test
    fun cadence_auPlusToutesLes300ms_etLaDerniereValeurALaFin() {
        val c = Cadence()
        val envoyes = mutableListOf<Int>()
        // Un glissé de 40 à 80 %, un point toutes les 16 ms : quelques valeurs, jamais une par pixel.
        var t = 0L
        for (v in 40..80) {
            c.bouge(v, t)?.let { envoyes += it }
            t += 16
        }
        c.fin(80, t)?.let { envoyes += it }
        assertEquals(80, envoyes.last())
        assertTrue("trop d'envois : $envoyes", envoyes.size <= 1 + (41 * 16 / 300) + 1)
        // Une valeur qui ne change pas ne repart pas.
        val d = Cadence()
        assertEquals(50, d.bouge(50, 0L))
        assertNull(d.bouge(50, 400L))
        assertNull(d.fin(50, 500L))
    }

    @Test
    fun volumePlafonneDansLAppli_avantMemeSecurite() {
        val e = media("media_player.barre_son_salon", "playing", 0.3)
        // La piste va jusqu'au volume permis : sans plafond (config-exemple, comme celle du propriétaire), la
        // fraction 1 vaut 100 %.
        val c = Appareils.regler(e, (1f * VolumeVise.MAX).toFloat())!!
        assertEquals(1.0, c.corps.getDouble("volume_level"), 1e-9)
        assertEquals(0.9, Appareils.regler(e, 0.9f)!!.corps.getDouble("volume_level"), 1e-9)
        assertEquals(0.8, VolumeVise().glisser(0.8, 0L), 1e-9)
        assertEquals(0.8, Securite.plafonnerVolume(0.8), 1e-9)
        // Avec un plafond de 50 % réglé dans la configuration, le volume y est ramené.
        assertEquals(0.5, Securite.plafonnerVolume(0.8, 0.5), 1e-9)
        assertEquals(0.5, Securite.plafonner("media_player.volume_set", org.json.JSONObject().put("volume_level", 0.9), 0.5).getDouble("volume_level"), 1e-9)
    }

    @Test
    fun etiquettesVidesQuandRienARegler() {
        assertEquals(0, MaisonEnGrand.etiquettes(listOf(MaisonEnGrand.Piece("x", "X", emptyList())), lus, "", false).length())
        assertEquals(JSONArray().toString(), MaisonEnGrand.pastilles(MaisonEnGrand.Piece("x", "X", emptyList()), lus, emptyMap(), null, false).toString())
    }
}
