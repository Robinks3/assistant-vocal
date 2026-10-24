package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

/** Historique de santé (0.22.0, protocole du serveur 0.20) : lecture, calculs et textes, valeurs inventées seulement. */
class SanteHistoTest {

    private val jour = LocalDate.of(2026, 10, 22)

    private fun entete(o: JSONObject) = o.put("aujourdhui", "2026-10-22").put("premier_jour", "2025-03-12")
        .put("genere_le", "2026-10-22T09:41:00").put("lu_a", "2026-10-22T09:40:00").put("perime", false)

    private fun reponse(type: String, d: JSONObject) = JSONObject().put("etat", type).put("id", 3).put("donnees", entete(d))

    // ------------------------------------------------------------ période

    private fun periode30(avant: Any?) = reponse("sante_periode", JSONObject("""{
        "jours": 7, "du": "2026-10-16", "au": "2026-10-22", "granularite": "jour",
        "serie": {"dates": ["2026-10-16","2026-10-17","2026-10-18","2026-10-19","2026-10-20","2026-10-21","2026-10-22"],
          "en_cours": [false,false,false,false,false,false,true],
          "sommeil_minutes": [452,null,516,414,444,418,432], "au_lit_minutes": [470,null,540,430,460,440,450],
          "profond_minutes": [90,null,101,77,88,80,98], "pas": [10412,null,6390,10310,8720,12080,4210],
          "fc_moyenne": [70.4,null,69,72,71,73,71], "fc_min": [48,null,47,49,48,50,46],
          "seance": [true,false,false,false,true,false,false], "sommeil_estime": [false,null,false,true,false,false,false]},
        "courbes": {"granularite": "jour", "dates": ["2026-10-16"], "en_cours": [false], "sommeil_minutes": [452]},
        "bilan": {"du": "2026-10-16", "au": "2026-10-22", "jours": 6, "couverture": 5, "jours_disponibles": 7,
          "partielle": false, "jours_sommeil_estime": 1, "sommeil_minutes": 449, "au_lit_minutes": 468,
          "profond_minutes": 87, "pas": 9582, "distance_m": 7100, "fc_repos": 48.4, "fc_moyenne": 71.1, "spo2_min": 89,
          "sport": {"minutes": 150, "seances": 2, "trimp": 231.5, "sans_fc": 0, "minutes_par_semaine": 150,
            "seances_par_semaine": 2.0, "trimp_par_semaine": 232,
            "par_sport": {"course": {"nom": "course", "minutes": 150, "seances": 2, "trimp": 231.5, "sans_fc": 0}}}},
        "avant": null,
        "sport": {"granularite": "jour", "groupes": [{"debut": "2026-10-16", "jours": 1, "en_cours": false, "minutes": 80,
          "seances": 1, "trimp": 120, "sans_fc": 0, "par_sport": {}}], "par_mois": null},
        "hors_charge": ["ski", "snowboard"]}""").also { if (avant != null) it.put("avant", avant) })

    @Test
    fun periode_lit_les_series_paralleles_et_le_bilan() {
        val p = SanteHisto.periode(periode30(null))!!
        assertEquals(7, p.jours)
        assertEquals(7, p.serie.size)
        val trou = p.serie[1]
        assertNull(trou.pas)
        assertNull(trou.sommeil)
        assertEquals(0, trou.seances)
        assertEquals(1, p.serie[0].seances)
        assertEquals(70, p.serie[0].fcMoyenne)
        assertTrue(p.serie[3].sommeilEstime)
        assertTrue(p.serie[6].enCours)
        assertEquals(449, p.bilan!!.sommeil)
        assertEquals(48, p.bilan!!.fcRepos)
        assertEquals(2.0, p.bilan!!.sport!!.seancesParSemaine!!, 0.0)
        assertEquals(232, p.bilan!!.sport!!.trimpParSemaine)
        assertEquals("course", p.bilan!!.sport!!.parSport.getValue("course").nom)
        assertNull(p.avant)
        assertEquals("jour", p.sportGranularite)
        assertEquals(listOf("ski", "snowboard"), p.horsCharge)
        assertEquals(LocalDate.of(2025, 3, 12), p.entete.premierJour)
    }

    @Test
    fun periode_avant_partielle_garde_ses_jours_disponibles() {
        val avant = JSONObject("""{"du": "2025-03-12", "au": "2025-10-22", "jours": 225, "couverture": 200,
            "jours_disponibles": 225, "partielle": true, "pas": 8000, "sport": {"minutes_par_semaine": 210}}""")
        val p = SanteHisto.periode(periode30(avant))!!
        assertTrue(p.avant!!.partielle)
        assertEquals(225, p.avant!!.joursDisponibles)
        assertEquals(210, p.avant!!.sport!!.minutesParSemaine)
        assertEquals("7 mois seulement", SanteHisto.partielle(p.avant!!.joursDisponibles!!))
    }

    @Test
    fun periode_d_un_an_montre_les_mois_de_par_mois() {
        val r = periode30(null)
        r.getJSONObject("donnees").getJSONObject("sport").put("granularite", "semaine")
            .put("par_mois", JSONArray().put(JSONObject().put("debut", "2026-10-01").put("jours", 22).put("en_cours", true).put("trimp", 900)))
        val p = SanteHisto.periode(r)!!
        assertEquals("mois", p.sportGranularite)
        assertEquals(1, p.groupes.size)
        assertEquals(LocalDate.of(2026, 10, 1), p.groupes[0].debut)
    }

    @Test
    fun periode_par_semaine_lit_jours_seance_et_jours_renseignes() {
        val r = reponse("sante_periode", JSONObject("""{"jours": 90, "granularite": "semaine",
            "courbes": {"granularite": "semaine", "dates": ["2026-07-20", "2026-07-27"], "en_cours": [false, false],
              "jours_renseignes": [6, 7], "sommeil_minutes": [440, 450], "pas": [9000, null], "jours_seance": [3, 2],
              "jours_sommeil_estime": [0, 1]}}"""))
        val p = SanteHisto.periode(r)!!
        assertEquals(2, p.courbes.size)
        assertEquals(3, p.courbes[0].seances)
        assertEquals(6, p.courbes[0].joursRenseignes)
        assertNull(p.courbes[1].pas)
    }

    @Test
    fun reponse_d_erreur_ne_donne_rien() {
        val e = JSONObject().put("etat", "sante_periode").put("id", 3).put("erreur", "santé indisponible")
        assertNull(SanteHisto.periode(e))
        assertNull(SanteHisto.seances(e))
        assertNull(SanteHisto.seance(e))
        assertNull(SanteHisto.records(e))
        assertNull(SanteHisto.jour(e))
    }

    // ------------------------------------------------------------ séances

    private fun ligne(id: String, date: String, sport: String, minutes: Int, trimp: Any?, avecFc: Boolean = true) = JSONObject()
        .put("seance_id", id).put("date", date).put("debut_local", date + "T20:30:00").put("minutes", minutes).put("sport", sport)
        .put("nom", if (sport == "course") "Course à pied" else if (sport == "ski") "Ski" else "course")
        .put("distance_m", if (sport == "course") 8400 else JSONObject.NULL).put("allure_s_par_km", if (sport == "course") 302 else JSONObject.NULL)
        .put("fc_moyenne", if (avecFc) 148 else JSONObject.NULL).put("fc_max", if (avecFc) 182 else JSONObject.NULL)
        .put("trimp", trimp ?: JSONObject.NULL).put("avec_fc", avecFc)

    private fun liste(du: String, tronque: Boolean, vararg l: JSONObject) = reponse("sante_seances", JSONObject()
        .put("jours", 90).put("sport", "tous").put("du", du).put("au", "2026-10-22")
        .put("total", JSONObject().put("seances", l.size).put("minutes", 0).put("distance_m", 0))
        .put("par_sport", JSONObject()).put("tronque", tronque).put("seances", JSONArray(l.toList())))

    private val seancesInventees = arrayOf(
        ligne("a", "2026-10-20", "course", 80, 140),
        ligne("b", "2026-10-18", "course", 45, 90.4),
        ligne("c", "2026-10-17", "ski", 120, 200),
        ligne("d", "2026-10-16", "course", 70, null, avecFc = false),
        ligne("e", "2026-10-14", "course", 75, 100),
        ligne("f", "2026-10-01", "course", 80, 120),
        ligne("g", "2026-09-20", "course", 85, 180),
        ligne("h", "2026-09-17", "course", 90, 500),
    )

    @Test
    fun liste_des_seances_lue_ligne_par_ligne() {
        val l = SanteHisto.seances(liste("2026-07-25", false, *seancesInventees))!!
        assertEquals(8, l.seances.size)
        val c = l.seances[1]
        assertEquals("b", c.id)
        assertEquals("course", c.sport)
        assertEquals("Course à pied", c.nom)
        assertEquals(302, c.allure)
        assertEquals(90, c.trimp)
        assertFalse(l.seances[3].avecFc)
        assertEquals(20, l.seances[0].debut!!.hour)
    }

    @Test
    fun sport_de_7_jours_et_4_semaines_d_avant() {
        val l = SanteHisto.seances(liste("2026-07-25", false, *seancesInventees))!!
        val w = SanteHisto.semaine(l, jour)!!
        assertEquals(LocalDate.of(2026, 10, 16), w.du)
        assertEquals(jour, w.au)
        assertEquals(4, w.seances)
        assertEquals(80 + 45 + 120 + 70, w.minutes)
        // Ski hors de la charge, séance sans cœur sans charge.
        assertEquals(140 + 90, w.charge)
        assertEquals(1, w.sansFc)
        assertEquals(4, w.avantSemaines)
        assertEquals(2, w.avecCharge)
        // Du 18 septembre au 15 octobre : 100 + 120 + 180, le 17 septembre est hors des 4 semaines.
        assertEquals(100, w.avantMoyenne)
    }

    @Test
    fun semaines_d_avant_absentes_si_la_liste_ne_remonte_pas_assez() {
        val courte = SanteHisto.seances(liste("2026-09-23", false, *seancesInventees))!!
        assertNull(SanteHisto.semaine(courte, jour)!!.avantMoyenne)
        // Tronquée : couverte seulement si sa plus vieille séance est d'avant les 4 semaines.
        assertEquals(100, SanteHisto.semaine(SanteHisto.seances(liste("2026-07-25", true, *seancesInventees))!!, jour)!!.avantMoyenne)
        val sansLaPlusVieille = seancesInventees.dropLast(1).toTypedArray()
        assertNull(SanteHisto.semaine(SanteHisto.seances(liste("2026-07-25", true, *sansLaPlusVieille))!!, jour)!!.avantMoyenne)
    }

    @Test
    fun sport_d_un_jour_passe() {
        val l = SanteHisto.seances(liste("2026-07-25", false, *seancesInventees))!!
        val w = SanteHisto.semaine(l, LocalDate.of(2026, 10, 14))!!
        assertEquals(LocalDate.of(2026, 10, 8), w.du)
        assertEquals(1, w.seances)
        assertEquals(100, w.charge)
    }

    @Test
    fun liste_tronquee_au_milieu_des_7_jours_ne_donne_pas_de_bloc_sport() {
        // Coupée aux séances les plus récentes : la plus vieille gardée est le 18, il peut en manquer le 16 et le 17.
        val coupee = SanteHisto.seances(liste("2025-10-23", true, *seancesInventees.take(2).toTypedArray()))!!
        assertNull(SanteHisto.semaine(coupee, jour))
        // Une liste qui ne remonte pas jusqu'au premier des 7 jours, ou qui finit avant le jour demandé, non plus.
        assertNull(SanteHisto.semaine(SanteHisto.seances(liste("2026-10-18", false, *seancesInventees))!!, jour))
        assertNull(SanteHisto.semaine(SanteHisto.seances(liste("2026-07-25", false, *seancesInventees))!!, jour.plusDays(1)))
    }

    @Test
    fun pas_de_charge_quand_seul_le_ski_a_du_coeur() {
        val l = SanteHisto.seances(liste("2026-07-25", false, ligne("c", "2026-10-17", "ski", 120, 200), ligne("d", "2026-10-16", "course", 70, null, avecFc = false)))!!
        val w = SanteHisto.semaine(l, jour)!!
        assertEquals(2, w.seances)
        assertEquals(0, w.avecCharge)
    }

    @Test
    fun periode_couvrant() {
        assertEquals(30, SanteHisto.periodeCouvrant(LocalDate.of(2026, 10, 16), jour))
        assertEquals(90, SanteHisto.periodeCouvrant(LocalDate.of(2026, 9, 18), jour))
        assertEquals(365, SanteHisto.periodeCouvrant(jour.minusDays(364), jour))
        assertNull(SanteHisto.periodeCouvrant(jour.minusDays(365), jour))
        assertEquals(7, SanteHisto.periodeTenant(7))
        assertEquals(30, SanteHisto.periodeTenant(12))
        assertNull(SanteHisto.periodeTenant(400))
    }

    @Test
    fun bornes_des_zones_comme_le_serveur() {
        assertEquals("moins de 114", SanteHisto.texteBorne(SanteHisto.Borne("récupération", 0, 113)))
        assertEquals("114 à 132", SanteHisto.texteBorne(SanteHisto.Borne("endurance", 114, 132)))
        assertEquals("171 et plus", SanteHisto.texteBorne(SanteHisto.Borne("anaérobie", 171, null)))
        assertEquals("", SanteHisto.texteBorne(SanteHisto.Borne("Zone 1", null, null)))
    }

    @Test
    fun nuit_du_changement_d_heure() {
        // Nuit du 24 au 25 octobre 2026 : à 3 h il est 2 h, une nuit de 500 min commencée à 23 h 40 finit à 7 h.
        val debut = java.time.LocalDateTime.of(2026, 10, 24, 23, 40)
        assertEquals(java.time.LocalDateTime.of(2026, 10, 25, 7, 0), SanteHisto.apres(debut, 500))
        assertEquals(listOf(140L to "2 h", 320L to "4 h", 440L to "6 h"), SanteHisto.heuresNuit(debut, 500))
        // Une nuit ordinaire : 23 h 40 plus 500 min, 8 h.
        val ordinaire = java.time.LocalDateTime.of(2026, 10, 21, 23, 40)
        assertEquals(java.time.LocalDateTime.of(2026, 10, 22, 8, 0), SanteHisto.apres(ordinaire, 500))
        assertEquals(listOf(140L to "2 h", 260L to "4 h", 380L to "6 h"), SanteHisto.heuresNuit(ordinaire, 500))
        assertEquals("23 h 40", SanteHisto.heure(debut))
    }

    @Test
    fun seance_complete_avec_et_sans_bornes() {
        val o = ligne("a", "2026-10-20", "course", 80, 140).put("fin_local", "2026-10-20T21:50:00").put("kcal", 820)
            .put("fc_min", 92).put("dans_la_charge", true)
            .put("zones_minutes", JSONObject().put("z1", 6).put("z2", 33).put("z3", 18).put("z4", 13).put("z5", 4))
            .put("fc_max_reference", 190)
            .put("zones_bornes", JSONObject().put("z1", JSONObject().put("nom", "récupération").put("min_bpm", 0).put("max_bpm", 113))
                .put("z2", JSONObject().put("nom", "endurance").put("min_bpm", 114).put("max_bpm", 132))
                .put("z3", JSONObject().put("nom", "tempo").put("min_bpm", 133).put("max_bpm", 151))
                .put("z4", JSONObject().put("nom", "seuil").put("min_bpm", 152).put("max_bpm", 170))
                .put("z5", JSONObject().put("nom", "anaérobie").put("min_bpm", 171).put("max_bpm", JSONObject.NULL)))
            .put("fc_courbe", JSONArray("[[0, 95], [1.5, 120], [3, null], [4, 400], [5, 150]]"))
            .put("analyse", JSONObject().put("texte", "Analyse inventée.").put("modele", "essai").put("genere", "2026-10-20T22:00:00"))
        val s = SanteHisto.seance(reponse("sante_seance", o))!!
        assertEquals("a", s.item.id)
        assertEquals(listOf(6, 33, 18, 13, 4), s.zones)
        assertEquals(190, s.fcMaxReference)
        assertEquals("anaérobie", s.bornes!![4].nom)
        assertNull(s.bornes!![4].max)
        // Points nuls ou hors de 20 à 250 bpm écartés.
        assertEquals(listOf(0.0 to 95, 1.5 to 120, 5.0 to 150), s.courbe)
        assertEquals("Analyse inventée.", s.analyse!!.texte)
        assertTrue(s.dansLaCharge)

        val sans = ligne("b", "2026-10-18", "ski", 120, 200).put("dans_la_charge", false).put("zones_minutes", JSONObject.NULL)
            .put("fc_max_reference", JSONObject.NULL).put("zones_bornes", JSONObject.NULL).put("fc_courbe", JSONObject.NULL).put("analyse", JSONObject.NULL)
        val t = SanteHisto.seance(reponse("sante_seance", sans))!!
        assertNull(t.bornes)
        assertNull(t.fcMaxReference)
        assertTrue(t.zones.isEmpty())
        assertTrue(t.courbe.isEmpty())
        assertNull(t.analyse)
        assertFalse(t.dansLaCharge)
    }

    // ------------------------------------------------------------ records et jour

    @Test
    fun records_lus_selon_leur_forme() {
        val r = reponse("sante_records", JSONObject("""{"depuis": "2025-03-12", "seuils": {"pas": 10000, "nuit_minutes": 420},
            "records": {
              "serie_pas": {"valeur": 12, "unite": "jours", "du": "2026-09-12", "au": "2026-09-23", "battu_le": null},
              "journee_la_plus_active": {"valeur": 24310, "unite": "pas", "date": "2026-08-17", "battu_le": null},
              "meilleure_semaine_pas": {"valeur": 102400, "unite": "pas", "lundi": "2026-08-10", "battu_le": null},
              "seance_la_plus_chargee": {"valeur": 156.5, "unite": "trimp", "date": "2026-10-20", "seance_id": "a", "sport": "course", "battu_le": "2026-10-20"},
              "meilleure_allure_5km": {"valeur": 302, "unite": "s/km", "date": "2026-06-29", "seance_id": "b", "sport": "course", "distance_m": 6100, "battu_le": null},
              "fc_la_plus_basse": null}}"""))
        val rec = SanteHisto.records(r)!!
        assertEquals(10000, rec.seuilPas)
        assertEquals(420, rec.seuilNuit)
        assertFalse(rec.records.containsKey("fc_la_plus_basse"))
        assertEquals(6100, rec.records.getValue("meilleure_allure_5km").distanceM)
        assertNull(rec.records.getValue("serie_pas").distanceM)
        assertEquals(LocalDate.of(2026, 9, 12), rec.records.getValue("serie_pas").du)
        assertEquals(LocalDate.of(2026, 8, 10), rec.records.getValue("meilleure_semaine_pas").lundi)
        val s = rec.records.getValue("seance_la_plus_chargee")
        assertEquals("a", s.seanceId)
        assertEquals(LocalDate.of(2026, 10, 20), s.battuLe)
        assertEquals(156.5, s.valeur, 0.0)
    }

    @Test
    fun jour_passe_avec_nuit_et_codes_de_stades() {
        val r = reponse("sante_jour", JSONObject("""{"date": "2025-08-16", "en_cours": false, "renseigne": true,
            "sommeil_minutes": 432, "au_lit_minutes": 470, "profond_minutes": 98, "pas": 24310, "distance_m": 17900,
            "kcal": null, "fc_moyenne": 74, "fc_min": 47, "fc_max": 171, "spo2_min": 90, "seance": true, "sommeil_estime": false,
            "nuit": {"debut_local": "2025-08-15T23:40:00", "au_lit_minutes": 470, "sommeil_minutes": 432, "profond_minutes": 98,
              "stades": {"leger": 230, "profond": 98, "paradoxal": 104, "eveille": 20, "eveille_au_lit": 18},
              "seq": [[0, 30, 4], [30, 40, 5], [70, 10, 7], [80, 20, 6]]},
            "codes_stades": {"0": "inconnu", "1": "eveille", "4": "leger", "5": "profond", "6": "paradoxal", "7": "eveille_au_lit"},
            "seances": []}"""))
        val j = SanteHisto.jour(r)!!
        assertEquals(LocalDate.of(2025, 8, 16), j.date)
        assertEquals(24310, j.pas)
        assertEquals(listOf("leger", "profond", "eveille", "paradoxal"), j.nuit!!.seq.map { it.third })
        assertEquals(23, j.nuit!!.debut!!.hour)
        // L'éveil au lit compté avec l'éveil.
        assertEquals(38, j.nuit!!.stades.first { it.first == "eveille" }.second)
    }

    // ------------------------------------------------------------ textes

    @Test
    fun ligne_de_contexte_sur_l_heure_du_calcul() {
        // genere_le (heure du calcul, en UTC ici) passe avant lu_a, à l'heure de Paris.
        val e = SanteHisto.entete(entete(JSONObject()).put("genere_le", "2026-10-22T06:15:00.000Z"))
        assertEquals("Jeudi 22 octobre, données de 8 h 15", SanteHisto.contexte(e, jour))
        val sans = SanteHisto.entete(entete(JSONObject()).put("genere_le", JSONObject.NULL))
        assertEquals("Jeudi 22 octobre, données de 9 h 40", SanteHisto.contexte(sans, jour))
    }

    @Test
    fun ligne_de_contexte_et_dates() {
        val e = SanteHisto.entete(entete(JSONObject()).put("genere_le", JSONObject.NULL))
        assertEquals("Jeudi 22 octobre, données de 9 h 40", SanteHisto.contexte(e, jour))
        assertEquals("Jeudi 22 octobre, données de 9 h 40, pas encore à jour", SanteHisto.contexte(e.copy(perime = true), jour))
        assertEquals("Samedi 16 août 2025", SanteHisto.dateLongue(LocalDate.of(2025, 8, 16), jour))
        assertEquals("du 23 septembre au 22 octobre", SanteHisto.plage(LocalDate.of(2026, 9, 23), jour, jour))
        assertEquals("du 16 au 22 octobre", SanteHisto.plage(LocalDate.of(2026, 10, 16), jour, jour))
        assertEquals("du 28 décembre 2025 au 3 janvier", SanteHisto.plage(LocalDate.of(2025, 12, 28), LocalDate.of(2026, 1, 3), jour))
        assertEquals("23 sept.", SanteHisto.court(LocalDate.of(2026, 9, 23)))
        assertEquals("1er oct.", SanteHisto.court(LocalDate.of(2026, 10, 1)))
        assertEquals("Mar. 20", SanteHisto.abrege(LocalDate.of(2026, 10, 20)))
        assertEquals("ve 16", SanteHisto.initialeNumero(LocalDate.of(2026, 10, 16)))
        assertEquals("Ven. 16 octobre, 7 h 32", SanteHisto.lecture(LocalDate.of(2026, 10, 16), "7 h 32", jour))
    }

    @Test
    fun dates_sous_les_graphes_comme_la_maquette() {
        // 30 jours : 23 sept., 30 sept., 7 oct., 14 oct., puis le dernier jour à la place du 21.
        assertEquals(listOf(0, 7, 14, 21, 29), indicesDates(30, 7))
        assertEquals((0 until 7).toList(), indicesDates(7, 1))
        assertEquals(listOf(0, 4, 8, 12), indicesDates(13, 4))
        assertEquals(listOf(0, 4, 8, 12, 14), indicesDates(15, 4))
        assertEquals(emptyList<Int>(), indicesDates(0, 7))
    }

    @Test
    fun allure_et_periodes_d_avant() {
        assertEquals("5:02 min/km", SanteHisto.allure(302))
        assertEquals("3 semaines seulement", SanteHisto.partielle(21))
        assertEquals("5 jours seulement", SanteHisto.partielle(5))
        assertEquals("Les 7 jours d'avant", SanteHisto.avant(7))
        assertEquals("Les 3 mois d'avant", SanteHisto.avant(90))
        assertEquals("L'année d'avant", SanteHisto.avant(365))
    }

    // ------------------------------------------------------------ essai sans valeur

    @Test
    fun presence_ne_dit_que_les_champs_manquants() {
        val r = periode30(null)
        r.getJSONObject("donnees").getJSONObject("bilan").remove("jours_sommeil_estime")
        val t = SanteHisto.presence("sante_periode", r)
        assertTrue(t, t.contains("bilan.jours_sommeil_estime"))
        // Aucune valeur : ni les pas, ni les minutes, ni une date.
        for (v in listOf("10412", "452", "9582", "2026")) assertFalse(t, t.contains(v))
        assertEquals("sante_jour : aucune réponse", SanteHisto.presence("sante_jour", null))
        assertEquals("sante_jour : erreur du serveur", SanteHisto.presence("sante_jour", JSONObject().put("etat", "sante_jour").put("erreur", "x")))
    }

    @Test
    fun la_demonstration_suit_le_protocole_du_serveur() {
        fun corps(type: String) = JSONObject().put("type", type)
        val demandes = listOf(
            corps("sante_periode").put("jours", 7), corps("sante_periode").put("jours", 30),
            corps("sante_periode").put("jours", 90), corps("sante_periode").put("jours", 365),
            corps("sante_seances").put("jours", 30).put("sport", "tous"), corps("sante_records"),
            corps("sante_jour").put("date", jour.minusDays(3).toString()),
        )
        for (c in demandes) {
            val t = SanteHisto.presence(c.getString("type"), SanteDemo.reponse(c, jour))
            assertTrue(t, t.endsWith("aucun champ attendu ne manque"))
        }
        val id = SanteHisto.seances(SanteDemo.reponse(corps("sante_seances").put("jours", 30).put("sport", "tous"), jour))!!.seances.first().id
        val t = SanteHisto.presence("sante_seance", SanteDemo.reponse(corps("sante_seance").put("seance_id", id), jour))
        assertTrue(t, t.endsWith("aucun champ attendu ne manque"))
        // Fenêtre passée comme le serveur 0.20.2 : finie le jour demandé, sans jour en cours, avec la période d'avant.
        val au = SanteDemo.reponse(corps("sante_periode").put("jours", 7).put("au", "2026-08-01"), jour)
        val p = SanteHisto.periode(au)!!
        assertEquals(LocalDate.of(2026, 8, 1), p.au)
        assertFalse(p.serie.any { it.enCours })
        assertEquals("finie le jour demandé, aucun jour en cours, avec période d'avant", SanteHisto.presenceAu(au, "2026-08-01"))
        val l = SanteDemo.reponse(corps("sante_seances").put("jours", 90).put("sport", "tous").put("au", "2026-04-05"), jour)
        assertEquals(LocalDate.of(2026, 4, 5), SanteHisto.seances(l)!!.au)
        assertTrue(SanteHisto.presenceAu(l, "2026-04-05").startsWith("finie le jour demandé"))
        // 35 jours refusés comme par le serveur (7, 30, 90 ou 365 seulement).
        assertTrue(SanteDemo.reponse(corps("sante_seances").put("jours", 35).put("au", "2026-04-05"), jour).has("erreur"))
        assertNotNull(SanteHisto.records(SanteDemo.reponse(corps("sante_records"), jour)))
    }

    @Test
    fun records_de_la_demonstration_s_ouvrent_sur_une_vraie_seance() {
        val rec = SanteHisto.records(SanteDemo.reponse(JSONObject().put("type", "sante_records"), jour))!!
        for (r in rec.records.values) {
            val id = r.seanceId ?: continue
            val s = SanteHisto.seance(SanteDemo.reponse(JSONObject().put("type", "sante_seance").put("seance_id", id), jour))!!
            assertEquals(id, s.item.id)
            assertEquals(r.date, s.item.date)
        }
    }

    @Test
    fun sportsPrincipauxTiresDesSeances() {
        // 0.30.1 : filtres et totaux de Séances tirés des séances reçues, aucun sport écrit dans le code.
        val par = linkedMapOf(
            "velo" to SanteHisto.Sport("Vélo", 300, 4, null, null),
            "natation" to SanteHisto.Sport("Natation", 200, 6, null, null),
            "course" to SanteHisto.Sport("Course à pied", 400, 4, null, null),
            "yoga" to SanteHisto.Sport("Yoga", 50, 0, null, null),
        )
        // Minutes d'abord, comme le serveur : course (400), vélo (300), puis natation (200) dans « Autres ».
        assertEquals(listOf("course" to "Course à pied", "velo" to "Vélo"), SanteHisto.sportsPrincipaux(par))
        assertEquals(listOf("course"), SanteHisto.sportsPrincipaux(par, 1).map { it.first })
        // À minutes égales, le plus de séances.
        val egal = mapOf("a" to SanteHisto.Sport("A", 100, 2, null, null), "b" to SanteHisto.Sport("B", 100, 5, null, null))
        assertEquals("b", SanteHisto.sportsPrincipaux(egal, 1).single().first)
        assertTrue(SanteHisto.sportsPrincipaux(emptyMap()).isEmpty())
        // Sans nom, la clé.
        assertEquals("ski" to "ski", SanteHisto.sportsPrincipaux(mapOf("ski" to SanteHisto.Sport("", 30, 1, null, null))).single())
    }

    @Test
    fun demonstrationSansCourse() {
        val r = SanteDemo.reponse(JSONObject().put("type", "sante_seances").put("jours", 365).put("sport", "tous"), LocalDate.of(2026, 10, 24))
        val sports = r.getJSONObject("donnees").getJSONObject("par_sport").keys().asSequence().toSet()
        assertEquals(setOf("natation", "velo", "course"), sports)
    }
}
