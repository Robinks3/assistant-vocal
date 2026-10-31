package assistant.vocal.jarvis

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate
import java.time.ZoneId

/** Panneau Santé (0.21.0) : lecture défensive de toute la réponse et textes, valeurs fictives seulement. */
class SanteDetailTest {

    private val zone = ZoneId.of("Europe/Paris")
    private val jour = LocalDate.of(2026, 10, 22)

    private val reponse = JSONObject(
        """{"etat": "sante", "id": 4, "donnees": {"date": "2026-10-22", "lu_a": null,
        "aujourdhui": {"date": "2026-10-22", "renseigne": true, "pas": 4210, "distance_m": 3100, "kcal_totales": 1980,
          "kcal_actives": null, "fc_repos": null, "fc_min": 48, "fc_max": 132, "fc_moyenne": 71, "spo2_moyenne": 95, "spo2_min": 89},
        "nuit": {"date": "2026-10-22", "cette_nuit": true, "minutes": 432, "stades": {"leger": 230, "eveille": 20, "profond": 98, "paradoxal": 84}},
        "jours": [
          {"date": "2026-10-16", "renseigne": true, "pas": 10412, "sommeil_minutes": 452},
          {"date": "2026-10-17", "renseigne": false, "pas": null, "sommeil_minutes": null},
          {"date": "2026-10-18", "renseigne": true, "pas": 6390, "sommeil_minutes": 516},
          {"date": "2026-10-19", "renseigne": true, "pas": 10310, "sommeil_minutes": 414},
          {"date": "2026-10-20", "renseigne": true, "pas": 8720, "sommeil_minutes": 444},
          {"date": "2026-10-21", "renseigne": true, "pas": 12080, "sommeil_minutes": 418},
          {"date": "2026-10-22", "renseigne": true, "pas": 4210, "sommeil_minutes": 432}],
        "seances": [
          {"date": "2026-10-21", "debut": "2026-10-21T18:30:00+00:00", "fin": null, "type": "natation", "titre": "Natation", "type_code": 1,
           "minutes": 75, "kcal": 820, "distance_m": null, "trimp": null, "fc_moyenne": 148, "fc_max": 186, "fc_min": 90,
           "vitesse_moyenne_kmh": null, "vitesse_max_kmh": null, "zones_minutes": {"z1": 6, "z2": 14, "z3": 22, "z4": 24, "z5": 9},
           "fc_courbe": [[0, 95], [10, 150], [20, 186], [30, 120]]},
          {"date": "2026-10-18", "titre": null, "type": "Course à pied", "minutes": 42, "kcal": 410, "distance_m": 6800, "zones_minutes": null, "fc_courbe": null}]
        }}""",
    )

    @Test
    fun lectureComplete() {
        val d = SanteDetail.lire(reponse, zone)!!
        assertEquals(jour, d.date)
        val n = d.nuit!!
        assertTrue(n.cetteNuit)
        assertEquals(432, n.minutes)
        // Stades dans l'ordre profond, paradoxal, léger, éveillé.
        assertEquals(listOf("profond", "paradoxal", "leger", "eveille"), n.stades.map { it.first })
        assertEquals(20, n.eveille)
        assertEquals(4210, d.aujourdhui!!.pas)
        assertEquals(7, d.jours.size)
        assertEquals(2, d.seances.size)
        val s = d.seances[0]
        assertEquals("Natation", s.titre)
        assertEquals(20, s.debut!!.hour)
        assertEquals(listOf(6, 14, 22, 24, 9), s.zones)
        assertEquals(4, s.courbe.size)
        assertEquals("Course à pied", d.seances[1].titre)
        assertTrue(d.seances[1].courbe.isEmpty())
    }

    @Test
    fun erreurEtChampsNuls() {
        assertNull(SanteDetail.lire(JSONObject("""{"etat": "sante", "id": 1, "erreur": "refusé"}""")))
        assertNull(SanteDetail.lire(null))
        val d = SanteDetail.lire(JSONObject("""{"donnees": {"date": "2026-10-22", "nuit": {"date": "2026-10-21", "cette_nuit": false, "minutes": null}, "aujourdhui": {"pas": null}, "jours": null, "seances": [{"minutes": -3}]}}"""))!!
        assertNull(d.nuit!!.minutes)
        assertNull(d.aujourdhui!!.pas)
        assertTrue(d.jours.isEmpty())
        assertNull(d.seances[0].minutes)
        assertEquals("Séance", d.seances[0].titre)
    }

    @Test
    fun textesDuPanneau() {
        val d = SanteDetail.lire(reponse, zone)!!
        assertEquals("Sommeil cette nuit", SanteDetail.titreNuit(d.nuit!!))
        assertEquals("Dernière nuit, mercredi 21 octobre", SanteDetail.titreNuit(SanteDetail.Nuit(LocalDate.of(2026, 10, 21), false, 400, emptyList())))
        assertEquals("3,1 km d'activités, 1 980 kcal dépensées", SanteDetail.lignePas(d.aujourdhui!!))
        assertEquals("71 en moyenne, 132 au plus haut", SanteDetail.ligneCoeur(d.aujourdhui!!))
        assertEquals("Oxygène dans le sang, 95 % en moyenne, 89 % au plus bas", SanteDetail.ligneOxygene(d.aujourdhui!!))
        assertEquals("Hier, 1 h 15, 820 kcal", SanteDetail.ligneSeance(d.seances[0], jour))
        assertEquals("Dimanche, 42 min, 6,8 km", SanteDetail.ligneSeance(d.seances[1], jour))
        assertEquals("Hier à 20 h 30, pendant 1 h 15", SanteDetail.quandSeance(d.seances[0], jour))
        assertEquals("820 kcal, cœur à 148 en moyenne, 186 au plus haut", SanteDetail.chiffresSeance(d.seances[0]))
        assertEquals("je", SanteDetail.initiale(jour))
        assertEquals("10,4", SanteDetail.milliersDePas(10412))
        assertEquals("léger", SanteDetail.nomStade("leger"))
    }

    @Test
    fun septJoursSansAujourdhuiPourLesPas() {
        val d = SanteDetail.lire(reponse, zone)!!
        val pas = SanteDetail.pasTermines(d, jour)
        assertEquals(6, pas.size)
        assertFalse(pas.any { it.first == jour })
        // Un jour non renseigné reste vide.
        assertNull(pas[1].second)
        val nuits = SanteDetail.nuits(d, jour)
        assertEquals(7, nuits.size)
        assertEquals(jour to 432, nuits.last())
    }

    @Test
    fun presenceSansAucuneValeur() {
        val p = SanteDetail.presence(reponse)
        assertEquals("réponse lue, nuit (minutes, cette nuit, stades), aujourd'hui (pas, distance, kcal, cœur, oxygène), 7 jours, 2 séances", p)
        assertFalse(p.any { it.isDigit() && p.contains("4210") })
        assertEquals("erreur du serveur", SanteDetail.presence(JSONObject("""{"erreur": "x"}""")))
    }

    @Test
    fun titresDesSeancesEnFrancais() {
        assertEquals("Natation", SanteDetail.libelleSeance(null, "natation"))
        assertEquals("Course nature", SanteDetail.libelleSeance(null, "course_nature"))
        assertEquals("Course à pied", SanteDetail.libelleSeance(null, "course"))
        assertEquals("Vélo d'appartement", SanteDetail.libelleSeance("", "velo_appartement"))
        assertEquals("Séance", SanteDetail.libelleSeance(null, "type_42"))
        assertEquals("Séance", SanteDetail.libelleSeance(null, null))
        assertEquals("Sortie du dimanche", SanteDetail.libelleSeance("Sortie du dimanche", "course"))
    }

    @Test
    fun stadesDeSommeilRanges() {
        val s = SanteDetail.stades(JSONObject("""{"leger": 200, "eveille": 10, "eveille_au_lit": 12, "hors_du_lit": 5, "endormi": 30, "inconnu": 4, "bizarre": 3, "profond": 90}"""))
        assertEquals(listOf("profond", "leger", "endormi", "eveille", "hors du lit", "inconnu"), s.map { it.first })
        // Éveillé au lit compté avec l'éveil, clé inconnue avec « inconnu ».
        assertEquals(22, s.first { it.first == "eveille" }.second)
        assertEquals(7, s.first { it.first == "inconnu" }.second)
        assertTrue(SanteDetail.dort("endormi"))
        assertFalse(SanteDetail.dort("hors du lit"))
        assertEquals("hors du lit", SanteDetail.nomStade("hors du lit"))
        assertEquals("inconnu", SanteDetail.nomStade("inconnu"))
    }
}
