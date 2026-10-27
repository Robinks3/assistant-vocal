package assistant.vocal.jarvis

import assistant.vocal.jarvis.AirHistorique.Duree
import assistant.vocal.jarvis.AirHistorique.Grandeur
import assistant.vocal.jarvis.AirHistorique.Groupe
import assistant.vocal.jarvis.AirHistorique.Point
import assistant.vocal.jarvis.AirHistorique.Resultat
import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneId
import java.time.ZonedDateTime

/** Historique de l'air d'une pièce (S-L8, appli 0.47.0) : lecture de la réponse, échelle, bandes, trous, axe du temps. */
class AirHistoriqueTest {

    private val paris = ZoneId.of("Europe/Paris")

    private fun reponse(series: JSONObject, heures: Int = 24, pas: Double = 300.0, fin: Double = 1_790_000_000.0): JSONObject =
        JSONObject().put("etat", "air_historique").put("id", 1).put(
            "donnees", JSONObject().put("piece", "salon").put("heures", heures).put("debut", fin - heures * 3600.0)
                .put("fin", fin).put("pas", pas).put("series", series),
        )

    private fun points(vararg p: Pair<Double, Double>): JSONArray =
        JSONArray().apply { for ((t, v) in p) put(JSONArray().put(t).put(v)) }

    private fun pts(vararg p: Pair<Double, Double>): List<Point> = p.map { Point(it.first, it.second) }

    // ------------------------------------------------------------ lecture

    @Test fun reponseNulleEstUneErreurReseau() {
        val r = AirHistorique.lire(null)
        assertTrue(r is Resultat.Erreur)
        assertEquals(AirHistorique.ERREUR_RESEAU, (r as Resultat.Erreur).message)
    }

    @Test fun erreurDuServeurPasseTelle() {
        val r = AirHistorique.lire(JSONObject().put("etat", "air_historique").put("erreur", "pièce protégée"))
        assertEquals("pièce protégée", (r as Resultat.Erreur).message)
        assertEquals("Pièce protégée", AirHistorique.messageErreur("pièce protégée"))
    }

    @Test fun donneesAbsentesEstUneErreur() {
        assertTrue(AirHistorique.lire(JSONObject().put("etat", "air_historique")) is Resultat.Erreur)
    }

    @Test fun lecturesDesSeriesEtDesPoints() {
        val s = JSONObject().put("co2", points(1000.0 to 600.0, 1300.0 to 640.5)).put("pm25", points(1000.0 to 4.2))
        val r = AirHistorique.lire(reponse(s))
        assertTrue(r is Resultat.Charge)
        val d = (r as Resultat.Charge).donnees
        assertEquals("salon", d.piece)
        assertEquals(24, d.heures)
        assertEquals(2, d.points(Grandeur.CO2).size)
        assertEquals(640.5, d.points(Grandeur.CO2)[1].v, 0.0)
        assertTrue(d.points(Grandeur.TEMPERATURE).isEmpty())
        assertTrue(d.aDesPoints(Groupe.AIR))
        assertFalse(d.aDesPoints(Groupe.CLIMAT))
    }

    @Test fun aucuneMesureDonneVide() {
        val r = AirHistorique.lire(reponse(JSONObject()))
        assertTrue(r is Resultat.Vide)
        val s = JSONObject().put("co2", JSONArray()).put("pm25", JSONArray())
        assertTrue(AirHistorique.lire(reponse(s)) is Resultat.Vide)
    }

    @Test fun pointsIllisiblesSontIgnoresEtLesAutresTries() {
        val a = JSONArray().put(JSONArray().put(2000.0).put(700.0)).put(JSONArray().put(1000.0).put(JSONObject.NULL))
            .put(JSONArray().put(1500.0)).put("x").put(JSONArray().put(1000.0).put(650.0))
        val d = (AirHistorique.lire(reponse(JSONObject().put("co2", a))) as Resultat.Charge).donnees
        assertEquals(listOf(1000.0, 2000.0), d.points(Grandeur.CO2).map { it.t })
        assertEquals(listOf(650.0, 700.0), d.points(Grandeur.CO2).map { it.v })
    }

    @Test fun fuseauInconnuOuVideTombeEnUtc() {
        assertEquals(ZoneId.of("UTC"), AirHistorique.fuseau(null))
        assertEquals(ZoneId.of("UTC"), AirHistorique.fuseau(""))
        assertEquals(ZoneId.of("UTC"), AirHistorique.fuseau("Nulle/Part"))
        assertEquals(paris, AirHistorique.fuseau("Europe/Paris"))
    }

    // ------------------------------------------------------------ échelle

    @Test fun pasNice() {
        assertEquals(200.0, AirHistorique.pasNice(800.0, 4), 1e-9)
        assertEquals(5.0, AirHistorique.pasNice(20.0, 4), 1e-9)
        assertEquals(2.0, AirHistorique.pasNice(7.0, 4), 1e-9)
        assertEquals(1.0, AirHistorique.pasNice(0.0, 4), 1e-9)
        assertEquals(0.5, AirHistorique.pasNice(2.0, 4), 1e-9)
    }

    @Test fun echelleCo2PartDe400EtMonteAuMoins1200() {
        val e = AirHistorique.echelle(Grandeur.CO2, pts(0.0 to 520.0, 1.0 to 700.0))
        assertEquals(400.0, e.bas, 0.0)
        assertTrue(e.haut >= 1200.0)
        val g = e.graduations()
        assertEquals(400.0, g.first(), 1e-9)
        assertEquals(e.haut, g.last(), 1e-9)
    }

    @Test fun echelleCo2QuandLaMesureDepasseLeHaut() {
        val e = AirHistorique.echelle(Grandeur.CO2, pts(0.0 to 520.0, 1.0 to 2600.0))
        assertTrue(e.haut >= 2600.0)
    }

    @Test fun echelleCo2SousLes400DescendJusqueLa() {
        val e = AirHistorique.echelle(Grandeur.CO2, pts(0.0 to 330.0, 1.0 to 700.0))
        assertTrue(e.bas <= 330.0)
    }

    @Test fun echellePm25PartDeZero() {
        val e = AirHistorique.echelle(Grandeur.PM25, pts(0.0 to 3.0))
        assertEquals(0.0, e.bas, 0.0)
        assertTrue(e.haut >= 15.0)
    }

    @Test fun echelleTemperatureEtHumiditeContiennentLesDonnees() {
        val t = AirHistorique.echelle(Grandeur.TEMPERATURE, pts(0.0 to 19.2, 1.0 to 21.7))
        assertTrue(t.bas <= 19.2 && t.haut >= 21.7)
        assertTrue(t.haut - t.bas >= 6.0)
        val h = AirHistorique.echelle(Grandeur.HUMIDITE, pts(0.0 to 38.0, 1.0 to 97.0))
        assertTrue(h.bas >= 0.0 && h.haut <= 100.0)
        assertTrue(h.bas <= 38.0 && h.haut >= 97.0)
    }

    @Test fun echelleSansPointReste() {
        for (g in Grandeur.values()) {
            val e = AirHistorique.echelle(g, emptyList())
            assertTrue(g.name, e.haut > e.bas)
            assertTrue(g.name, e.graduations().size >= 2)
        }
    }

    @Test fun fractionEstBorneeEntre0Et1() {
        val e = AirHistorique.Echelle(400.0, 1200.0, 200.0)
        assertEquals(0.0, e.fraction(400.0), 0.0)
        assertEquals(1.0, e.fraction(1200.0), 0.0)
        assertEquals(0.5, e.fraction(800.0), 1e-9)
        assertEquals(1.0, e.fraction(5000.0), 0.0)
        assertEquals(0.0, e.fraction(0.0), 0.0)
    }

    // ------------------------------------------------------------ bandes de seuil

    @Test fun bandesCo2ReprennentLesSeuilsDeMesures() {
        val e = AirHistorique.Echelle(400.0, 2000.0, 400.0)
        val b = AirHistorique.bandes(Grandeur.CO2, e)
        assertEquals(4, b.size)
        assertEquals(listOf(0, 1, 2, 3), b.map { it.rang })
        assertEquals(400.0, b[0].de, 0.0)
        assertEquals(Mesures.SEUILS_CO2[0], b[0].a, 0.0)
        assertEquals(Mesures.SEUILS_CO2[1], b[1].a, 0.0)
        assertEquals(Mesures.SEUILS_CO2[2], b[2].a, 0.0)
        assertEquals(2000.0, b[3].a, 0.0)
    }

    @Test fun bandesSontCoupeesALEchelle() {
        val e = AirHistorique.Echelle(400.0, 1200.0, 200.0)
        val b = AirHistorique.bandes(Grandeur.CO2, e)
        assertEquals(listOf(0, 1, 2), b.map { it.rang })
        assertEquals(1200.0, b.last().a, 0.0)
        val petite = AirHistorique.bandes(Grandeur.PM25, AirHistorique.Echelle(0.0, 15.0, 5.0))
        assertEquals(listOf(0, 1), petite.map { it.rang })
        assertEquals(15.0, petite.last().a, 0.0)
    }

    @Test fun pasDeBandePourLaTemperatureEtLHumidite() {
        assertTrue(AirHistorique.bandes(Grandeur.TEMPERATURE, AirHistorique.Echelle(16.0, 26.0, 2.0)).isEmpty())
        assertTrue(AirHistorique.bandes(Grandeur.HUMIDITE, AirHistorique.Echelle(0.0, 100.0, 25.0)).isEmpty())
        assertNull(AirHistorique.seuils(Grandeur.HUMIDITE))
    }

    @Test fun couleursEtMotsSuiventLesSeuils() {
        assertEquals(Mesures.COULEURS_AIR[0], AirHistorique.couleurAir(Grandeur.CO2, 799.0))
        assertEquals(Mesures.COULEURS_AIR[1], AirHistorique.couleurAir(Grandeur.CO2, 800.0))
        assertEquals(Mesures.COULEURS_AIR[3], AirHistorique.couleurAir(Grandeur.PM25, 56.0))
        assertNull(AirHistorique.couleurAir(Grandeur.TEMPERATURE, 20.0))
        assertEquals("médiocre", AirHistorique.mot(Grandeur.CO2, 1240.0))
        assertEquals("", AirHistorique.mot(Grandeur.HUMIDITE, 50.0))
    }

    // ------------------------------------------------------------ trous

    @Test fun uneCourbeSansTrouFaitUnSeulSegment() {
        val p = pts(0.0 to 1.0, 300.0 to 2.0, 600.0 to 3.0)
        assertEquals(1, AirHistorique.segments(p, 300.0).size)
    }

    @Test fun unTrouCoupeLaCourbe() {
        val p = pts(0.0 to 1.0, 300.0 to 2.0, 1500.0 to 3.0, 1800.0 to 4.0)
        val s = AirHistorique.segments(p, 300.0)
        assertEquals(2, s.size)
        assertEquals(2, s[0].size)
        assertEquals(2, s[1].size)
    }

    @Test fun unEcartDUnPasEtDemiNeCoupePas() {
        val p = pts(0.0 to 1.0, 450.0 to 2.0)
        assertEquals(1, AirHistorique.segments(p, 300.0).size)
        assertEquals(2, AirHistorique.segments(pts(0.0 to 1.0, 451.0 to 2.0), 300.0).size)
    }

    @Test fun segmentsSansPointOuSansPas() {
        assertTrue(AirHistorique.segments(emptyList(), 300.0).isEmpty())
        assertEquals(1, AirHistorique.segments(pts(0.0 to 1.0, 99999.0 to 2.0), 0.0).size)
    }

    // ------------------------------------------------------------ axe du temps

    private fun epoch(an: Int, mois: Int, jour: Int, h: Int, mn: Int = 0): Double =
        ZonedDateTime.of(an, mois, jour, h, mn, 0, 0, paris).toEpochSecond().toDouble()

    @Test fun reperesDeSixHeuresSontHoraires() {
        val fin = epoch(2026, 10, 27, 14, 5)
        val r = AirHistorique.reperesTemps(fin - 6 * 3600.0, fin, paris)
        assertEquals(listOf("9 h", "10 h", "11 h", "12 h", "13 h", "14 h"), r.map { it.libelle })
        assertEquals(epoch(2026, 10, 27, 9), r[0].t, 0.0)
    }

    @Test fun reperesDeVingtQuatreHeuresToutesLesQuatreHeuresLocales() {
        val fin = epoch(2026, 10, 27, 14, 5)
        val r = AirHistorique.reperesTemps(fin - 24 * 3600.0, fin, paris)
        assertEquals(listOf("16 h", "20 h", "0 h", "4 h", "8 h", "12 h"), r.map { it.libelle })
    }

    @Test fun reperesDeSeptJoursALMinuitLocale() {
        val fin = epoch(2026, 10, 27, 14, 5)
        val r = AirHistorique.reperesTemps(fin - 168 * 3600.0, fin, paris)
        assertEquals(7, r.size)
        assertEquals("mer. 21", r.first().libelle)
        assertEquals("mar. 27", r.last().libelle)
        assertEquals(epoch(2026, 10, 27, 0), r.last().t, 0.0)
    }

    @Test fun lAxeSuitLeFuseauDeLaConfig() {
        val fin = epoch(2026, 10, 27, 14, 5)
        val utc = AirHistorique.reperesTemps(fin - 6 * 3600.0, fin, ZoneId.of("UTC"))
        assertEquals("13 h", utc.last().libelle)
        val local = AirHistorique.reperesTemps(fin - 6 * 3600.0, fin, paris)
        assertEquals("14 h", local.last().libelle)
    }

    @Test fun plageVideSansRepere() {
        assertTrue(AirHistorique.reperesTemps(10.0, 10.0, paris).isEmpty())
        assertTrue(AirHistorique.reperesTemps(20.0, 10.0, paris).isEmpty())
    }

    // ------------------------------------------------------------ phrases

    @Test fun formatFrancais() {
        assertEquals("1240", AirHistorique.formater(1240.4, 0))
        assertEquals("21,5", AirHistorique.formater(21.46, 1))
        assertEquals("4,0", AirHistorique.formater(4.0, 1))
        assertEquals("612 ppm", AirHistorique.valeur(Grandeur.CO2, 611.6))
        assertEquals("12,3 µg/m3", AirHistorique.valeur(Grandeur.PM25, 12.34))
    }

    @Test fun lectureAuDoigt() {
        val p = Point(epoch(2026, 10, 27, 14, 5), 1240.0)
        assertEquals("mardi 14 h 05, 1240 ppm, médiocre", AirHistorique.lecture(Grandeur.CO2, p, paris))
        assertEquals("mardi 14 h 05, 52 %", AirHistorique.lecture(Grandeur.HUMIDITE, Point(p.t, 52.0), paris))
    }

    @Test fun resumeEtPlusProche() {
        val p = pts(0.0 to 500.0, 300.0 to 900.0, 600.0 to 700.0)
        val r = AirHistorique.resume(p)!!
        assertEquals(500.0, r.min, 0.0)
        assertEquals(900.0, r.max, 0.0)
        assertEquals(700.0, r.moyenne, 1e-9)
        assertEquals(700.0, r.derniere, 0.0)
        assertEquals("de 500 à 900 ppm, moyenne 700 ppm", AirHistorique.phraseResume(Grandeur.CO2, r))
        assertNull(AirHistorique.resume(emptyList()))
        assertEquals(900.0, AirHistorique.plusProche(p, 340.0)!!.v, 0.0)
        assertNull(AirHistorique.plusProche(emptyList(), 1.0))
    }

    @Test fun titresEtDurees() {
        assertEquals("Salon, 24 dernières heures", AirHistorique.titre("Salon", Duree.H24))
        assertEquals("Salon, 7 derniers jours", AirHistorique.titre("Salon", Duree.J7))
        assertEquals(Duree.H24, Duree.PAR_DEFAUT)
        assertEquals(Duree.J7, AirHistorique.dureeDe(168))
        assertEquals(Duree.H24, AirHistorique.dureeDe(99))
        assertEquals(listOf(6, 24, 168), Duree.values().map { it.heures })
    }

    // ------------------------------------------------------------ pièce de l'accueil

    private fun air(rang: Int) = Mesures.AirPiece(rang, Mesures.MOTS_AIR[rang], Mesures.COULEURS_AIR[rang], rang >= 2)

    private fun piece(statut: Mesures.Statut, rang: Int? = null) =
        Mesures.PieceMesures(statut, "x", Mesures.COULEUR_GRIS, air = rang?.let { air(it) })

    @Test fun pieceAccueilEstLaPireSiAAerer() {
        val m = linkedMapOf(
            "salon" to piece(Mesures.Statut.OK, 0), "chambre" to piece(Mesures.Statut.OK, 2),
            "bureau" to piece(Mesures.Statut.OK, 3),
        )
        assertEquals("bureau", Mesures.pieceAccueil(m)!!.key)
    }

    @Test fun pieceAccueilSinonLaPremiereQuiParle() {
        val m = linkedMapOf(
            "cave" to piece(Mesures.Statut.AUCUN), "garage" to piece(Mesures.Statut.PROTEGEE),
            "salon" to piece(Mesures.Statut.SANS_AIR), "chambre" to piece(Mesures.Statut.OK, 1),
        )
        assertEquals("salon", Mesures.pieceAccueil(m)!!.key)
    }

    @Test fun pieceAccueilNulleQuandPersonneNeParle() {
        assertNull(Mesures.pieceAccueil(emptyMap()))
        assertNull(Mesures.pieceAccueil(mapOf("cave" to piece(Mesures.Statut.AUCUN))))
        assertNotNull(Mesures.pieceAccueil(mapOf("salon" to piece(Mesures.Statut.OK, 0))))
    }
}
