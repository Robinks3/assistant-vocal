package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneId
import java.time.ZonedDateTime

/** Panneau Météo (0.20.0) : pictos, nuit, frise, jours, synthèse, détail, voix. */
class MeteoTexteTest {

    private val zone = ZoneId.of("Europe/Paris")
    private val maintenant = ZonedDateTime.of(2026, 10, 22, 13, 37, 0, 0, zone)
    private fun h(heure: Int, jour: Int = 22) = ZonedDateTime.of(2026, 10, jour, heure, 0, 0, 0, zone).toInstant().toEpochMilli()
    private fun p(heure: Int, condition: String = "partlycloudy", t: Double = 20.0, mm: Double? = 0.0, jour: Int = 22) =
        Previsions.Prevision(h(heure, jour), condition, t, millimetres = mm, vent = 12.0, direction = 270.0, humidite = 64)

    @Test
    fun pictosDeJourEtDeNuit() {
        assertEquals(MeteoTexte.Picto.ECLAIRCIES, MeteoTexte.picto("partlycloudy", false))
        assertEquals(MeteoTexte.Picto.NUIT_NUAGE, MeteoTexte.picto("partlycloudy", true))
        assertEquals(MeteoTexte.Picto.NUIT, MeteoTexte.picto("clear-night", false))
        assertEquals(MeteoTexte.Picto.SOLEIL, MeteoTexte.picto("sunny", false))
        assertEquals(MeteoTexte.Picto.PLUIE, MeteoTexte.picto("pouring", false))
        assertEquals(MeteoTexte.Picto.NEIGE, MeteoTexte.picto("snowy", true))
        assertEquals(MeteoTexte.Picto.NUAGE, MeteoTexte.picto("fog", false))
    }

    @Test
    fun nuitEntreCoucherEtLever() {
        val coucher = h(18) + 12 * 60_000L
        val lever = h(7, 23) + 5 * 60_000L
        assertFalse(MeteoTexte.nuit(h(18), lever, coucher))
        assertTrue(MeteoTexte.nuit(h(19), lever, coucher))
        assertTrue(MeteoTexte.nuit(h(3, 23), lever, coucher))
        assertFalse(MeteoTexte.nuit(h(8, 23), lever, coucher))
        // Le lendemain soir, mêmes heures à 24 h près.
        assertTrue(MeteoTexte.nuit(h(20, 23), lever, coucher))
        assertFalse(MeteoTexte.nuit(h(12), null, coucher))
    }

    @Test
    fun colonnesDepuisLHeureEnCours() {
        val l = (12..23).map { p(it) } + (0..2).map { p(it, jour = 23) }
        val c = MeteoTexte.colonnes(l, maintenant, h(7, 23), h(18) + 12 * 60_000L)
        assertEquals(13, c.first().heure)
        assertTrue(c.first { it.heure == 0 }.minuit)
        assertFalse(c.first().minuit)
        // Pictos de nuit atténués, sauf la première heure de nuit.
        val o = MeteoTexte.opacites(c)
        val i19 = c.indexOfFirst { it.heure == 19 }
        assertEquals(1f, o[i19])
        assertEquals(0.5f, o[i19 + 1])
        assertEquals(1f, o[0])
    }

    @Test
    fun pluieEnBarresEtEnMillimetres() {
        assertEquals(0f, MeteoTexte.barre(0.0))
        assertEquals(3f, MeteoTexte.barre(0.05))
        assertEquals(27f, MeteoTexte.barre(0.9))
        assertEquals(60f, MeteoTexte.barre(2.0))
        assertEquals(60f, MeteoTexte.barre(4.5))
        val c = MeteoTexte.colonnes(listOf(p(13, mm = 0.2), p(14, mm = 1.2), p(15, mm = 1.8), p(16, mm = 0.6)), maintenant, null, null)
        assertEquals(listOf("", "1,2 mm", "1,8", "0,6"), MeteoTexte.textesMm(c))
        assertTrue(MeteoTexte.rafaleMontree(38.0))
        assertFalse(MeteoTexte.rafaleMontree(30.0))
    }

    @Test
    fun detailDUneHeure() {
        val c = MeteoTexte.colonnes(listOf(Previsions.Prevision(h(18), "rainy", 18.0, 70, 1.8, vent = 22.0, rafales = 38.0, humidite = 84)), maintenant.withHour(18), null, null).first()
        assertEquals("18 h" to " : 18°, pluie 70 %, 1,8 mm, vent 22 km/h, rafales à 38 km/h, humidité 84 %", MeteoTexte.detail(c))
        val sec = MeteoTexte.colonnes(listOf(Previsions.Prevision(h(13), "sunny", null)), maintenant, null, null).first()
        assertEquals("13 h" to "", MeteoTexte.detail(sec))
        assertEquals("indice UV 3 (modéré)", MeteoTexte.uv(3.4))
        assertEquals("18 h 05", MeteoTexte.heureMinute(h(18) + 5 * 60_000L, zone))
    }

    @Test
    fun syntheseSansRienInventer() {
        val jours = MeteoTexte.jours(listOf(
            Previsions.Prevision(h(12), "partlycloudy", 22.0, basse = 14.0),
            Previsions.Prevision(h(12, 23), "partlycloudy", 21.0, basse = 13.0),
        ), maintenant.toLocalDate(), zone)
        val journalier = listOf(Previsions.Prevision(h(12), "partlycloudy", 22.0, basse = 14.0), Previsions.Prevision(h(12, 23), "partlycloudy", 21.0, basse = 13.0))
        // Sec puis pluie de 17 h à 19 h.
        val heures = (13..23).map { p(it, if (it in 17..18) "rainy" else "cloudy", mm = if (it in 17..18) 1.0 else 0.0) }
        assertEquals(listOf("Sec jusqu'à 17 h.", "Puis pluie jusqu'à 19 h.", "Demain, éclaircies et 21°."), MeteoTexte.synthese(heures, jours, journalier, maintenant))
        // Sec partout.
        assertEquals("Sec pour 12 heures.", MeteoTexte.synthese((13..23).map { p(it) }, jours, journalier, maintenant).first())
        // Pluie en ce moment qui cesse.
        val pluie = (13..23).map { p(it, if (it < 15) "rainy" else "cloudy") }
        assertEquals(listOf("Pluie jusqu'à 15 h.", "Puis sec."), MeteoTexte.synthese(pluie, emptyList(), emptyList(), maintenant))
        assertEquals(emptyList<String>(), MeteoTexte.synthese(emptyList(), emptyList(), emptyList(), maintenant))
    }

    @Test
    fun joursEtEchelleCommune() {
        val j = MeteoTexte.jours((22..29).map { Previsions.Prevision(h(12, it), "sunny", 20.0 + it - 22, basse = 12.0, pluie = if (it == 23) 60 else null) }, LocalDate.of(2026, 10, 22), zone)
        assertEquals(7, j.size)
        assertEquals("Aujourd'hui", j[0].nom)
        assertEquals("Vendredi", j[1].nom)
        assertEquals(60, j[1].probabilite)
        val (haut, hauteur) = MeteoTexte.echelleJour(j[0], j)!!
        assertTrue(haut > 0f)
        assertTrue(hauteur >= 4f && haut + hauteur <= 44f)
    }

    @Test
    fun titreEtVoix() {
        assertEquals("Météo à la maison", MeteoTexte.titre("Forecast Maison"))
        assertEquals("Météo à Lille", MeteoTexte.titre("Forecast Lille"))
        assertEquals("Météo à la maison", MeteoTexte.titre(""))
    }


    @Test
    fun uniteDuVentEtNegatifsALaVoix() {
        assertTrue(MeteoTexte.rafaleMontree(38.0, "km/h"))
        assertFalse(MeteoTexte.rafaleMontree(20.0, "km/h"))
        // 9 m/s font 32 km/h, 8 m/s 29 km/h.
        assertTrue(MeteoTexte.rafaleMontree(9.0, "m/s"))
        assertFalse(MeteoTexte.rafaleMontree(8.0, "m/s"))
        assertEquals("moins 2", MeteoTexte.parle(-2.0))
        assertEquals("13", MeteoTexte.parle(13.0))
    }
}
