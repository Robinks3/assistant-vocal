package assistant.vocal.jarvis

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Volet de la télévision (0.39.0) : tuiles lues de la configuration, état, commande de source, curseur de volume. */
class ReglageTeleTest {

    private val SOURCES = listOf("TV", "Netflix", "YouTube", "Prime Video", "Disney+", "CANAL+", "HDMI1", "HDMI2")

    private fun tele(
        etat: String = "on", volume: Double? = 0.35, sources: List<String> = SOURCES, source: String = "",
    ) = Appareils.Appareil("media_player.exemple74", "Télé", etat, "", "", volume = volume, sources = sources, source = source, classe = "tv")

    private val tuiles = ReglageTele.lireTuiles(
        JSONObject(
            """{"tele": {"sources": [
                {"nom": "TNT", "source": "TV"},
                {"nom": "Netflix", "source": "Netflix"},
                {"nom": "Prime Video", "source": "Prime Video"},
                {"nom": "CANAL+", "source": "CANAL+"},
                {"nom": "HDMI 1", "source": "HDMI1"}
            ]}}""",
        ),
    )

    // ------------------------------------------------------------ lecture de la configuration

    @Test fun lireTuiles_gardeLOrdreEtLesNoms() {
        assertEquals(listOf("TNT", "Netflix", "Prime Video", "CANAL+", "HDMI 1"), tuiles.map { it.nom })
        assertEquals("HDMI1", tuiles.last().source)
    }

    @Test fun lireTuiles_ignoreLesEntreesInvalidesEtToutes() {
        val t = ReglageTele.lireTuiles(
            JSONObject(
                """{"tele": {"sources": [
                    {"nom": "", "source": "TV"},
                    {"nom": "Sans source"},
                    {"nom": "Toutes", "source": "X"},
                    "texte",
                    {"nom": "  YouTube ", "source": " YouTube "}
                ]}}""",
            ),
        )
        assertEquals(1, t.size)
        assertEquals("YouTube", t[0].nom)
        assertEquals("YouTube", t[0].source)
    }

    @Test fun lireTuiles_sansSectionDonneVide() {
        assertTrue(ReglageTele.lireTuiles(JSONObject("{}")).isEmpty())
        assertTrue(ReglageTele.lireTuiles(JSONObject("""{"tele": {}}""")).isEmpty())
        assertTrue(ReglageTele.lireTuiles(JSONObject("""{"tele": {"sources": "oups"}}""")).isEmpty())
    }

    // ------------------------------------------------------------ comparaison des sources

    @Test fun memeSource_neTientPasCompteDesEspacesNiDeLaCasse() {
        assertTrue(ReglageTele.memeSource("HDMI 1", "HDMI1"))
        assertTrue(ReglageTele.memeSource("prime video", "Prime Video"))
        assertTrue(ReglageTele.memeSource("CANAL+", "canal+"))
        assertFalse(ReglageTele.memeSource("HDMI 1", "HDMI 2"))
        assertFalse(ReglageTele.memeSource("CANAL+", "CANAL"))
        assertFalse(ReglageTele.memeSource("", ""))
    }

    @Test fun memeSource_ignoreLesAccents() {
        assertTrue(ReglageTele.memeSource("Télé", "tele"))
    }

    // ------------------------------------------------------------ tuiles offertes

    @Test fun tuilesOffertes_toutesQuandLaTeleNeDonnePasSaListe() {
        assertEquals(tuiles.size, ReglageTele.tuilesOffertes(tuiles, tele(sources = emptyList())).size)
        assertEquals(tuiles.size, ReglageTele.tuilesOffertes(tuiles, null).size)
    }

    @Test fun tuilesOffertes_filtreSurLaListeDeLaTele() {
        val a = tele(sources = listOf("TV", "Netflix", "HDMI 1"))
        assertEquals(listOf("TNT", "Netflix", "HDMI 1"), ReglageTele.tuilesOffertes(tuiles, a).map { it.nom })
    }

    @Test fun sourceExacte_prendLeNomDeLaTele() {
        val a = tele(sources = listOf("HDMI 1", "Netflix"))
        val hdmi = tuiles.first { it.nom == "HDMI 1" }
        assertEquals("HDMI 1", ReglageTele.sourceExacte(a, hdmi))
        assertEquals("HDMI1", ReglageTele.sourceExacte(null, hdmi))
        assertEquals("TV", ReglageTele.sourceExacte(a, tuiles.first { it.nom == "TNT" }))
    }

    @Test fun toutesLesSources_sansDoublon() {
        val a = tele(sources = listOf("HDMI1", "HDMI 1", "Netflix", "", "netflix", "TV"))
        assertEquals(listOf("HDMI1", "Netflix", "TV"), ReglageTele.toutesLesSources(a))
        assertTrue(ReglageTele.toutesLesSources(null).isEmpty())
    }

    // ------------------------------------------------------------ état

    @Test fun texteEtat_eteinteEtHorsLigne() {
        assertEquals("éteinte", ReglageTele.texteEtat(tele(etat = "off"), false, tuiles, null))
        assertEquals("éteinte", ReglageTele.texteEtat(tele(etat = "standby"), false, tuiles, "Netflix"))
        assertEquals("hors ligne", ReglageTele.texteEtat(tele(etat = "unavailable"), true, tuiles, null))
        assertEquals("hors ligne", ReglageTele.texteEtat(null, true, tuiles, null))
    }

    @Test fun texteEtat_alluméeSansSourceConnue() {
        assertEquals("allumée", ReglageTele.texteEtat(tele(etat = "on"), false, tuiles, null))
    }

    @Test fun texteEtat_sourceAuConditionnel() {
        assertEquals("allumée, sans doute Netflix", ReglageTele.texteEtat(tele(source = "Netflix"), false, tuiles, null))
        assertEquals("allumée, sans doute HDMI 1", ReglageTele.texteEtat(tele(source = "HDMI 1"), false, tuiles, null))
    }

    @Test fun texteEtat_sourceHorsTuilesGardeLeNomDeLaTele() {
        assertEquals("allumée, sans doute YouTube", ReglageTele.texteEtat(tele(source = "YouTube"), false, tuiles, null))
    }

    @Test fun texteEtat_laSourceLueGagneSurLaChoisie() {
        assertEquals("allumée, sans doute Netflix", ReglageTele.texteEtat(tele(source = "Netflix"), false, tuiles, "TV"))
    }

    @Test fun texteEtat_laDerniereChoisieSertQuandLaLectureEstVide() {
        assertEquals("allumée, sans doute CANAL+", ReglageTele.texteEtat(tele(source = ""), false, tuiles, "CANAL+"))
    }

    @Test fun sourceProbable_nulleSiEteinte() {
        assertNull(ReglageTele.sourceProbable(tele(etat = "off", source = "Netflix"), "TV"))
        assertNull(ReglageTele.sourceProbable(null, "TV"))
        assertNull(ReglageTele.sourceProbable(tele(), " "))
    }

    @Test fun tuileActive_suitLaSourceProbable() {
        assertEquals("Netflix", ReglageTele.tuileActive(tuiles, tele(source = "Netflix"), null)?.nom)
        assertEquals("HDMI 1", ReglageTele.tuileActive(tuiles, tele(source = "HDMI 1"), null)?.nom)
        assertEquals("TNT", ReglageTele.tuileActive(tuiles, tele(source = ""), "TV")?.nom)
        assertNull(ReglageTele.tuileActive(tuiles, tele(source = "Disney+"), null))
        assertNull(ReglageTele.tuileActive(tuiles, tele(etat = "off", source = "Netflix"), null))
    }

    // ------------------------------------------------------------ gestes

    @Test fun gesteLigne_deplieQuandAllumeeEtBasculeSinon() {
        assertEquals(ReglageTele.Geste.DEPLIER, ReglageTele.gesteLigne(tele(), false))
        assertEquals(ReglageTele.Geste.BASCULER, ReglageTele.gesteLigne(tele(etat = "off"), false))
        assertEquals(ReglageTele.Geste.BASCULER, ReglageTele.gesteLigne(tele(etat = "standby"), false))
        assertEquals(ReglageTele.Geste.BASCULER, ReglageTele.gesteLigne(tele(), true))
        assertEquals(ReglageTele.Geste.BASCULER, ReglageTele.gesteLigne(null, true))
    }

    @Test fun volet_seulementEnLigneEtAllumee() {
        assertTrue(ReglageTele.volet(tele(), false))
        assertFalse(ReglageTele.volet(tele(etat = "off"), false))
        assertFalse(ReglageTele.volet(tele(), true))
        assertFalse(ReglageTele.volet(null, false))
    }

    // ------------------------------------------------------------ commande de source

    @Test fun commande_estUnSelectSource() {
        val c = ReglageTele.commande(tele(), "Netflix")
        assertEquals("media_player.select_source", c.service)
        assertEquals("media_player.exemple74", c.corps.getString("entity_id"))
        assertEquals("Netflix", c.corps.getString("source"))
    }

    @Test fun commande_aLaFormeAttendueParLaListeBlanche() {
        val c = ReglageTele.commande(tele(), "HDMI 1")
        assertEquals(setOf("entity_id", "source"), c.corps.keys().asSequence().toSet())
    }

    // ------------------------------------------------------------ mise en page

    @Test fun rangees_decoupeParQuatre() {
        assertTrue(ReglageTele.rangees(0).isEmpty())
        assertEquals(listOf(0 until 3), ReglageTele.rangees(3))
        assertEquals(listOf(0 until 4), ReglageTele.rangees(4))
        assertEquals(listOf(0 until 4, 4 until 8), ReglageTele.rangees(8))
        assertEquals(listOf(0 until 4, 4 until 8, 8 until 9), ReglageTele.rangees(9))
    }

    // ------------------------------------------------------------ volume

    @Test fun volumeDePiste_bornesEtPlafond() {
        val max = Securite.VOLUME_MAX
        assertEquals(0.0, ReglageTele.volumeDePiste(0f), 1e-9)
        assertEquals(max, ReglageTele.volumeDePiste(1f), 1e-9)
        assertEquals(0.0, ReglageTele.volumeDePiste(-3f), 1e-9)
        assertEquals(max, ReglageTele.volumeDePiste(7f), 1e-9)
        assertTrue(ReglageTele.volumeDePiste(0.5f) <= max)
    }

    @Test fun volumeDePiste_neDepasseJamaisUnPlafondReglé() {
        for (i in 0..100) {
            val v = ReglageTele.volumeDePiste(i / 100f)
            assertTrue("volume $v au-dessus du plafond ${Securite.VOLUME_MAX}", v <= Securite.VOLUME_MAX + 1e-9)
            assertTrue(v >= 0.0)
        }
    }

    @Test fun volumeDePiste_arrondiAuCentieme() {
        val v = ReglageTele.volumeDePiste(0.3333f)
        assertEquals(Math.round(v * 100) / 100.0, v, 1e-9)
    }

    @Test fun fractionPiste_inverseDeVolumeDePiste() {
        assertEquals(0f, ReglageTele.fractionPiste(tele(volume = null)), 1e-6f)
        assertEquals(0f, ReglageTele.fractionPiste(null), 1e-6f)
        assertEquals(0f, ReglageTele.fractionPiste(tele(volume = 0.0)), 1e-6f)
        assertEquals(1f, ReglageTele.fractionPiste(tele(volume = 1.0)), 1e-6f)
        val f = ReglageTele.fractionPiste(tele(volume = 0.2))
        assertTrue(f in 0f..1f)
        assertEquals(0.2, ReglageTele.volumeDePiste(f), 0.011)
    }

    @Test fun volumeReglable_ilFautUnVolumeLuEtUneTeleEnLigne() {
        assertTrue(ReglageTele.volumeReglable(tele(), false))
        assertFalse(ReglageTele.volumeReglable(tele(volume = null), false))
        assertFalse(ReglageTele.volumeReglable(tele(), true))
        assertFalse(ReglageTele.volumeReglable(null, false))
    }

    @Test fun texteVolume_pourcentOuSansMesure() {
        assertEquals("35 %", ReglageTele.texteVolume(tele(volume = 0.35)))
        assertEquals("0 %", ReglageTele.texteVolume(tele(volume = 0.0)))
        assertEquals("sans mesure", ReglageTele.texteVolume(tele(volume = null)))
        assertEquals("sans mesure", ReglageTele.texteVolume(null))
        assertEquals("Volume de la télé, 35 %", ReglageTele.descriptionVolume(tele(volume = 0.35)))
    }

    @Test fun tuilesDeLaConfigurationDExemple_sontLues() {
        // ConfigMaison lit config-exemple/ pendant les tests : la copie fictive porte les sept sources.
        val t = ReglageTele.TUILES
        assertNotNull(t)
        assertEquals(7, t.size)
        assertEquals("HDMI 1", t.last().nom)
    }
}
