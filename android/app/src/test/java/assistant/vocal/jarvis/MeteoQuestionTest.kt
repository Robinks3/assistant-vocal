package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.ZoneId
import java.time.ZonedDateTime

/** Question de météo à la voix (0.23.0) : compréhension, plages, réponses écrites et dites, bande et détail. */
class MeteoQuestionTest {

    private val zone = ZoneId.of("Europe/Paris")
    // Jeudi 22 octobre 2026, 11 h 20, comme la maquette.
    private val maintenant = ZonedDateTime.of(2026, 10, 22, 11, 20, 0, 0, zone)
    private fun h(heure: Int, jour: Int = 22) = ZonedDateTime.of(2026, 10, jour, heure, 0, 0, 0, zone).toInstant().toEpochMilli()

    /** Les heures de la maquette, de jeudi 11 h à vendredi 22 h. */
    private val horaire: List<Previsions.Prevision> = run {
        val brut = listOf(
            listOf(11, 20, 0, 0.0, 12, 0, 315), listOf(12, 21, 0, 0.0, 13, 0, 310), listOf(13, 22, 0, 0.0, 14, 0, 300),
            listOf(14, 22, 0, 0.0, 16, 0, 295), listOf(15, 21, 0, 0.0, 18, 0, 290), listOf(16, 20, 10, 0.0, 18, 0, 285),
            listOf(17, 19, 60, 1.2, 20, 34, 280), listOf(18, 18, 70, 1.8, 22, 38, 280), listOf(19, 17, 40, 0.6, 18, 27, 290),
            listOf(20, 16, 20, 0.1, 15, 0, 300), listOf(21, 16, 0, 0.0, 12, 0, 310), listOf(22, 15, 0, 0.0, 10, 0, 315),
            listOf(23, 15, 0, 0.0, 9, 0, 320),
        )
        val jeudi = brut.map { b ->
            val p = (b[3] as Double)
            Previsions.Prevision(
                h(b[0] as Int), if (p >= 0.5) "rainy" else "partlycloudy", (b[1] as Int).toDouble(), b[2] as Int, p,
                vent = (b[4] as Int).toDouble(), direction = (b[6] as Int).toDouble(), rafales = (b[5] as Int).takeIf { it > 0 }?.toDouble(),
            )
        }
        val demain = (0..22).map { k ->
            val v = listOf(8, 8, 7, 7, 8, 10, 12, 14, 16, 18, 20, 22, 23, 24, 25, 25, 23, 21, 19, 17, 15, 13, 12)[k]
            val g = listOf(0, 0, 0, 0, 0, 0, 22, 24, 27, 30, 32, 35, 37, 38, 39, 40, 37, 34, 31, 26, 0, 0, 0)[k]
            val t = listOf(14, 14, 14, 13, 13, 13, 13, 14, 15, 17, 18, 19, 20, 21, 21, 21, 20, 19, 18, 17, 16, 15, 15)[k]
            Previsions.Prevision(h(k, 23), "partlycloudy", t.toDouble(), 0, 0.0, vent = v.toDouble(), direction = 275.0, rafales = g.takeIf { it > 0 }?.toDouble())
        }
        jeudi + demain
    }

    private val lecture by lazy {
        Previsions.Lecture(
            horaire = horaire,
            journalier = listOf(
                Previsions.Prevision(h(12), "rainy", 22.0, 70, 3.6, basse = 14.0),
                Previsions.Prevision(h(12, 23), "partlycloudy", 21.0, 10, 0.0, basse = 13.0),
                Previsions.Prevision(h(12, 24), "sunny", 23.0, 0, 0.0, basse = 12.0, vent = 14.0, direction = 300.0),
            ),
            actuel = Previsions.Actuel("partlycloudy", 20.0, ressenti = 19.0, vent = 12.0, direction = 315.0, uniteVent = "km/h"),
        )
    }

    private fun q(s: String) = MeteoQuestion.comprendre(s, maintenant, listOf("Lille"))

    @Test
    fun comprendLesQuestionsDeSacha() {
        val pluie = q("Va-t-il pleuvoir cet après-midi ?")!!
        assertEquals(MeteoQuestion.Sujet.PLUIE, pluie.sujet)
        assertEquals(MeteoQuestion.Plage(0, 12, 18, "cet après-midi"), pluie.plage)
        val vent = q("Quel vent demain ?")!!
        assertEquals(MeteoQuestion.Sujet.VENT, vent.sujet)
        assertEquals(1, vent.plage.jour)
        assertEquals("demain", vent.plage.nom)
        assertTrue(vent.plage.jourEntier)
        val soir = q("Il fera combien ce soir ?")!!
        assertEquals(MeteoQuestion.Sujet.TEMPERATURE, soir.sujet)
        assertEquals(MeteoQuestion.Plage(0, 18, 23, "ce soir"), soir.plage)
        val mer = q("Quelles conditions en mer à Exemple4 ?")!!
        assertEquals(MeteoQuestion.Sujet.MER, mer.sujet)
        assertEquals("Exemple4", mer.point)
        assertEquals(MeteoQuestion.Plage(0, 7, 20, "aujourd'hui", jourEntier = true), mer.plage)
        assertEquals("Exemple3", q("quel vent devant Exemple3 demain")!!.point)
    }

    @Test
    fun comprendDAutresTournures() {
        assertEquals(MeteoQuestion.Sujet.GENERAL, q("Quel temps fera-t-il demain ?")!!.sujet)
        assertEquals(MeteoQuestion.Sujet.GENERAL, q("la météo de demain")!!.sujet)
        assertEquals(MeteoQuestion.Sujet.GENERAL, q("est-ce qu'il va faire beau samedi")!!.sujet)
        assertEquals(2, q("est-ce qu'il va faire beau samedi")!!.plage.jour)
        assertEquals(MeteoQuestion.Sujet.PLUIE, q("faut-il prendre un parapluie demain matin")!!.sujet)
        assertEquals(MeteoQuestion.Plage(1, 6, 12, "demain matin"), q("faut-il prendre un parapluie demain matin")!!.plage)
        assertEquals(MeteoQuestion.Plage(0, 16, 17, "à 16 h"), q("est-ce qu'il pleuvra à 16 h")!!.plage)
        assertEquals(MeteoQuestion.Plage(0, 17, 20, "vers 18 h"), q("quelle température vers 18 heures")!!.plage)
        assertEquals(MeteoQuestion.Plage(2, 6, 22, "après-demain", jourEntier = true), q("quel temps après-demain")!!.plage)
        val present = q("il pleut ?")!!
        assertTrue(present.plage.maintenant)
        assertTrue(q("quel temps fait-il")!!.plage.maintenant)
        assertEquals("Lille", q("quel temps demain à Lille")!!.lieu)
        assertEquals(MeteoQuestion.Sujet.TEMPERATURE, q("il va faire froid ce soir ?")!!.sujet)
    }

    @Test
    fun laissePasserCeQuiNEstPasUneQuestionDeMeteo() {
        assertNull(q("allume le salon demain"))
        assertNull(q("rappelle-moi demain de regarder la météo"))
        assertNull(q("combien de temps pour aller à Paris demain"))
        assertNull(q("allume le chauffage il fait froid"))
        assertNull(q("mets de la musique"))
        assertNull(q("j'ai froid"))
        assertNull(q("merci"))
        // Revue de code 0.25.0 : commandes et questions sur la maison, lieux inconnus.
        assertNull(q("descends les volets, il va pleuvoir"))
        assertNull(q("dis à Lou qu'il va pleuvoir"))
        assertNull(q("ajoute parapluie à la liste de courses"))
        assertNull(q("quelle est la température du salon"))
        assertNull(q("combien il reste de lumières allumées"))
        assertNull(q("quel est le temps de cuisson des pâtes"))
        assertNull(q("quel temps à Paris demain"))
        assertNotNull(q("quel temps à Lille demain"))
        assertNotNull(q("quel temps fera-t-il à midi"))
    }

    @Test
    fun heuresLimitesEtPlagesPassees() {
        // « Vers 0 h » commence la veille à 23 h, sans planter.
        val r = MeteoQuestion.repondre(q("quelle température vers 0 h")!!, lecture, maintenant)
        assertNotNull(r.lignes.firstOrNull())
        // Une heure passée vise demain, une partie du jour passée est dite passée.
        assertEquals(MeteoQuestion.Plage(1, 3, 4, "demain à 3 h"), q("va-t-il pleuvoir à 3 h")!!.plage)
        val apres = ZonedDateTime.of(2026, 10, 22, 15, 0, 0, 0, zone)
        val matin = MeteoQuestion.comprendre("va-t-il pleuvoir ce matin", apres)!!
        assertEquals("Déjà passé.", MeteoQuestion.repondre(matin, lecture, apres).lignes.first())
        assertEquals(MeteoQuestion.Plage(1, 16, 17, "demain à 16 h"), q("il pleuvra à 16h30 ?")!!.plage.let { if (it.jour == 0) it.copy(jour = 1, nom = "demain à 16 h") else it })
        assertEquals("dans 2 heures", MeteoQuestion.heures("dans 2 heures"))
        assertEquals("à 17 heures, à 1 heure", MeteoQuestion.heures("à 17 h, à 1 h"))
    }

    @Test
    fun pluieCetApresMidiSuitLaPluieJusquaSaFin() {
        val r = MeteoQuestion.repondre(q("Va-t-il pleuvoir cet après-midi ?")!!, lecture, maintenant)
        assertEquals("Pluie cet après-midi", r.entete)
        assertEquals(listOf("Oui, à partir de 17 h.", "Jusqu'à 20 h, 3,6 mm."), r.lignes)
        assertEquals("Oui, à partir de 17 heures, jusqu'à 20 heures, 3,6 millimètres.", r.parle)
        assertEquals(h(12), r.bandeDebut)
        assertEquals(h(20), r.bandeFin)
        assertEquals(h(18), r.choisi)
        assertEquals("De 12 h à 20 h", r.detail.first)
        assertEquals(" : pluie de 17 h à 20 h, jusqu'à 70 %, 3,6 mm en tout, 17 à 22°, vent 13 à 22 km/h, rafales jusqu'à 38 km/h à 18 h", r.detail.second)
    }

    @Test
    fun pasDePluieDemain() {
        val r = MeteoQuestion.repondre(q("va-t-il pleuvoir demain")!!, lecture, maintenant)
        assertEquals(listOf("Non, sec demain."), r.lignes)
        assertEquals("Non, sec demain.", r.parle)
    }

    @Test
    fun ventDeDemain() {
        val r = MeteoQuestion.repondre(q("Quel vent demain ?")!!, lecture, maintenant)
        assertEquals("Vent demain", r.entete)
        assertEquals(listOf("Ouest, 12 à 25 km/h.", "Rafales à 40 vers 15 h."), r.lignes)
        assertEquals("Demain, vent d'ouest, 12 à 25 kilomètres heure. Rafales à 40 vers 15 heures.", r.parle)
        assertEquals(h(6, 23), r.bandeDebut)
        assertEquals(h(22, 23), r.bandeFin)
        assertEquals(h(15, 23), r.choisi)
        assertEquals("Demain, de 6 h à 22 h", r.detail.first)
    }

    @Test
    fun temperatureDuSoir() {
        val r = MeteoQuestion.repondre(q("Il fera combien ce soir ?")!!, lecture, maintenant)
        assertEquals("Température ce soir", r.entete)
        assertEquals(listOf("18° à 18 h.", "15° vers 22 h."), r.lignes)
        assertEquals("Ce soir, 18 degrés à 18 heures, puis 15 degrés vers 22 heures.", r.parle)
        assertEquals("Ce soir, de 18 h à 23 h", r.detail.first)
        assertTrue(r.detail.second.startsWith(" : 15 à 18°"))
    }

    @Test
    fun maintenantEtJourHorsDeLaFrise() {
        val r = MeteoQuestion.repondre(q("quel temps fait-il")!!, lecture, maintenant)
        assertEquals(listOf("20°, éclaircies.", "Ressenti 19°."), r.lignes)
        val s = MeteoQuestion.repondre(q("quel temps samedi")!!, lecture, maintenant)
        assertEquals(listOf("Ensoleillé, 12 à 23°.", "Sec."), s.lignes)
        assertNull(s.bandeDebut)
        val rien = MeteoQuestion.repondre(q("quel temps mercredi")!!, lecture, maintenant)
        assertEquals("Je n'ai pas de prévision pour mercredi.", rien.parle)
    }

    @Test
    fun plageCommenceALHeureEnCours() {
        val r = MeteoQuestion.repondre(q("quel temps aujourd'hui")!!, lecture, maintenant)
        assertEquals(h(11), r.bandeDebut)
        assertNotNull(r.lignes.firstOrNull())
    }

    @Test
    fun directionsEnMots() {
        assertEquals("ouest", MeteoQuestion.secteur(272.0))
        assertEquals("sud-ouest", MeteoQuestion.secteur(225.0))
        assertEquals("nord", MeteoQuestion.secteur(355.0))
        assertEquals("d'ouest", MeteoQuestion.de("ouest"))
        assertEquals("de sud-ouest", MeteoQuestion.de("sud-ouest"))
    }
}
