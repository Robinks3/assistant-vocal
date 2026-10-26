package assistant.vocal.jarvis

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.time.ZoneId

/**
 * Mesures par pièce (S-L6, appli 0.42.0 ou suivante) : mêmes cas que poc/tests/test_mesures.py
 * (poc/tests/cas_mesures.json), plus chaque seuil pile à la borne et juste au-dessus.
 */
class MesuresTest {

    private fun fichier(chemin: String): File {
        var dossier: File? = File(System.getProperty("user.dir") ?: ".").absoluteFile
        while (dossier != null) {
            val f = File(dossier, chemin)
            if (f.isFile) return f
            dossier = dossier.parentFile
        }
        error("$chemin introuvable depuis ${System.getProperty("user.dir")}")
    }

    private fun texteOuNull(o: JSONObject, cle: String): String? = if (o.isNull(cle)) null else o.getString(cle)

    private fun capteur(o: JSONObject) = Mesures.Capteur(
        o.getString("id"), o.getString("classe"), o.optString("etat"), o.optString("zone"),
        o.optString("zone_appareil"), o.optString("appareil"), o.optDouble("modifie", 0.0),
    )

    /** Clés comparées par les cas communs (None côté Python = absent). */
    private fun projection(p: Mesures.PieceMesures): Map<String, String?> = mapOf(
        "statut" to p.statut.name.lowercase().let { if (it == "protegee") "protegee" else it },
        "texte" to p.texte, "couleur" to p.couleur, "alerte" to p.alerte,
        "air_mot" to p.air?.mot, "temperature_mot" to p.temperature?.mot,
        "co2_mot" to p.co2?.mot, "pm25_mot" to p.pm25?.mot,
        "co2_suivant" to p.co2?.suivant, "pm25_suivant" to p.pm25?.suivant,
    )

    @Test
    fun casCommunsAvecLeServeur() {
        val cas = JSONObject(fichier("poc/tests/cas_mesures.json").readText(Charsets.UTF_8)).getJSONArray("cas")
        assertTrue("aucun cas lu", cas.length() > 0)
        val echecs = ArrayList<String>()
        for (i in 0 until cas.length()) {
            val c = cas.getJSONObject(i)
            val nom = c.getString("nom")
            val capteurs = c.getJSONArray("capteurs").let { a -> (0 until a.length()).map { capteur(a.getJSONObject(it)) } }
            val releve = Mesures.Releve(c.getDouble("maintenant"), capteurs)
            val corresp = Mesures.correspondance(JSONObject().put("correspondance_pieces", c.getJSONObject("correspondance")))
            val protegees = c.getJSONArray("protegees").let { a -> (0 until a.length()).map { a.getString(it) } }
            val noms = c.optJSONObject("noms")?.let { o -> o.keys().asSequence().associateWith { o.getString(it) } } ?: emptyMap()
            val r = Mesures.parPiece(releve, corresp, protegees, ZoneId.of(c.optString("fuseau", "UTC")), noms)
            val attendu = c.getJSONObject("attendu")
            for (piece in attendu.keys()) {
                val voulu = attendu.getJSONObject(piece)
                val obtenu = r[piece]
                if (obtenu == null) {
                    echecs.add("$nom : pièce $piece absente")
                    continue
                }
                val p = projection(obtenu)
                for (cle in voulu.keys()) {
                    val v = texteOuNull(voulu, cle)
                    if (p[cle] != v) echecs.add("$nom / $piece / $cle : ${p[cle]} au lieu de $v")
                }
            }
        }
        assertEquals("cas en écart avec mesures.py :\n" + echecs.joinToString("\n"), 0, echecs.size)
    }

    @Test
    fun motsDuCo2AuxBornes() {
        val cas = listOf(0.0 to "bon", 799.9 to "bon", 800.0 to "correct", 1000.0 to "correct", 1000.1 to "médiocre",
            1500.0 to "médiocre", 1500.1 to "mauvais", 5000.0 to "mauvais")
        for ((v, mot) in cas) assertEquals("CO2 $v", mot, Mesures.motCo2(v))
    }

    @Test
    fun motsDesParticulesAuxBornes() {
        val cas = listOf(0.0 to "bon", 8.9 to "bon", 9.0 to "correct", 35.4 to "correct", 35.5 to "médiocre",
            55.4 to "médiocre", 55.5 to "mauvais")
        for ((v, mot) in cas) assertEquals("PM2.5 $v", mot, Mesures.motPm25(v))
    }

    @Test
    fun motsDeLaTemperatureAuxBornes() {
        val cas = listOf(-5.0 to "frais", 18.9 to "frais", 19.0 to "agréable", 24.0 to "agréable", 24.1 to "chaud", 35.0 to "chaud")
        for ((v, mot) in cas) assertEquals("température $v", mot, Mesures.motTemperature(v))
    }

    @Test
    fun motsEtCouleursImposes() {
        assertEquals(listOf("bon", "correct", "médiocre", "mauvais"), Mesures.MOTS_AIR)
        assertEquals(listOf("#D4E6C8", "#EDD48A", "#EE9A45", "#D6503A"), Mesures.COULEURS_AIR)
    }

    @Test
    fun seuilSuivantEnClair() {
        assertEquals("passe à correct dès 800 ppm", Mesures.seuilSuivant("carbon_dioxide", 500.0))
        assertEquals("passe à médiocre au-dessus de 1000 ppm", Mesures.seuilSuivant("carbon_dioxide", 900.0))
        assertEquals("passe à mauvais au-dessus de 1500 ppm", Mesures.seuilSuivant("carbon_dioxide", 1200.0))
        assertEquals("", Mesures.seuilSuivant("carbon_dioxide", 1600.0))
        assertEquals("passe à médiocre au-dessus de 35,4 µg/m3", Mesures.seuilSuivant("pm25", 20.0))
        assertEquals("passe à correct dès 9 µg/m3", Mesures.seuilSuivant("pm25", 3.0))
    }

    @Test
    fun arrondiLesDemisVersLeHaut() {
        assertEquals(21L, Mesures.arrondi(20.5))
        assertEquals(20L, Mesures.arrondi(20.49))
        assertEquals(1200L, Mesures.arrondi(1199.5))
    }

    @Test
    fun gabaritEcarteLesZonesProtegeesEtGardeLesClassesConnues() {
        val g = Mesures.gabarit(listOf("Chambre_Camille", "salle_de_bain_camille"))
        assertTrue(g.contains("""set protegees = ["chambre_camille","salle_de_bain_camille"]"""))
        assertTrue(g.contains("carbon_dioxide") && g.contains("pm25") && g.contains("illuminance"))
        assertTrue(g.contains("states.sensor"))
        assertTrue(g.contains("/api/template").not())
        assertTrue(Mesures.gabarit().contains("set protegees = []"))
    }

    @Test
    fun releveIllisibleDonneNull() {
        assertNull(Mesures.lireReleve(null))
        assertNull(Mesures.lireReleve("pas du json"))
        assertNull(Mesures.lireReleve("""{"maintenant": 1}"""))
        assertNotNull(Mesures.lireReleve("""{"maintenant": 1790000000, "capteurs": []}"""))
    }

    @Test
    fun correspondanceAccepteUneZoneOuUneListeEtIgnoreLesCommentaires() {
        val c = Mesures.correspondance(
            JSONObject("""{"correspondance_pieces": {"_note": "x", "salon": ["Salon", " cuisine "], "couloir": "Couloir", "vide": []}}"""),
        )
        assertEquals(mapOf("salon" to listOf("salon", "cuisine"), "couloir" to listOf("couloir")), c)
        assertTrue(Mesures.correspondance(JSONObject()).isEmpty())
    }

    @Test
    fun laConfigurationDExempleRelieLesPieces() {
        val c = Mesures.correspondance()
        assertTrue("config-exemple sans correspondance_pieces", c.isNotEmpty())
        assertTrue(Mesures.zonesProtegees().contains("chambre_camille"))
    }

    @Test
    fun uneZoneProtegeeNeLaisseRienFuiterMemeSansLeDrapeau() {
        // PROTEGER_OCCUPANT est coupé : la protection des mesures ne dépend pas de lui.
        val releve = Mesures.Releve(
            1790000000.0,
            listOf(Mesures.Capteur("sensor.t", "temperature", "21", "chambre_camille", "", "", 1789999940.0)),
        )
        val r = Mesures.parPiece(releve, mapOf("chambre_camille" to listOf("chambre_camille")), Mesures.zonesProtegees())
        val p = r.getValue("chambre_camille")
        assertEquals(Mesures.Statut.PROTEGEE, p.statut)
        assertEquals("pièce protégée", p.texte)
        assertNull(p.temperature)
        assertNull(p.air)
        assertEquals("", p.alerte)
        assertEquals(Mesures.COULEUR_GRIS, p.couleur)
    }

    @Test
    fun uneMesurePerimeeNEstPlusColoree() {
        val maintenant = 1790000000.0
        val releve = Mesures.Releve(
            maintenant,
            listOf(
                Mesures.Capteur("sensor.co2", "carbon_dioxide", "1200", "z", "", "", maintenant - 7201),
                Mesures.Capteur("sensor.t", "temperature", "21", "z", "", "", maintenant - 60),
            ),
        )
        val p = Mesures.parPiece(releve, mapOf("p" to listOf("z")), emptyList(), ZoneId.of("Europe/Paris")).getValue("p")
        assertNull(p.co2?.valeur)
        assertNull(p.air)
        assertEquals("", p.alerte)
        assertEquals(Mesures.COULEUR_GRIS, p.couleur)
        assertTrue(p.texte, p.texte.startsWith("21°, air absent depuis "))
    }

    @Test
    fun uneMesureAJusteDeuxHeuresResteColoree() {
        val maintenant = 1790000000.0
        val releve = Mesures.Releve(maintenant, listOf(Mesures.Capteur("sensor.co2", "carbon_dioxide", "1200", "z", "", "", maintenant - 7200)))
        val p = Mesures.parPiece(releve, mapOf("p" to listOf("z")), emptyList()).getValue("p")
        assertEquals("médiocre", p.air?.mot)
        assertFalse(p.alerte.isEmpty())
    }

    @Test
    fun alerteEtLigneDAccueil() {
        val maintenant = 1790000000.0
        val releve = Mesures.Releve(
            maintenant,
            listOf(
                Mesures.Capteur("sensor.t", "temperature", "21,4", "salon", "", "", maintenant - 30),
                Mesures.Capteur("sensor.co2", "carbon_dioxide", "1200", "salon", "", "", maintenant - 30),
            ),
        )
        val r = Mesures.parPiece(releve, mapOf("salon" to listOf("salon")), emptyList(), noms = mapOf("salon" to "Salon"))
        val p = r.getValue("salon")
        assertEquals("Aère la pièce Salon, CO2 1200 ppm", p.alerte)
        assertEquals("Salon 21°, air médiocre", Mesures.ligneAccueil("Salon", p))
        assertEquals(listOf("Aère la pièce Salon, CO2 1200 ppm"), Mesures.alertes(r))
    }

    private fun capteursAir(zone: String, co2: String, maintenant: Double) = listOf(
        Mesures.Capteur("sensor.t_$zone", "temperature", "21", zone, "", "", maintenant - 30),
        Mesures.Capteur("sensor.c_$zone", "carbon_dioxide", co2, zone, "", "", maintenant - 30),
    )

    @Test
    fun nomAfficheVientDeLaCarteSinonUnRepliLisible() {
        assertEquals("Salon", Mesures.nomAffiche("salon_id", mapOf("salon_id" to "Salon")))
        assertEquals("Salon", Mesures.nomAffiche("salon_id", mapOf("salon_id" to "  Salon ")))
        // nom vide ou inconnu : l'identifiant rendu lisible, jamais le texte brut avec ses tirets bas
        assertEquals("Chambre camille", Mesures.nomAffiche("chambre_camille", mapOf("chambre_camille" to "")))
        assertEquals("Salle de bain", Mesures.nomAffiche("salle-de-bain", emptyMap()))
    }

    @Test
    fun alertePorteLeNomAfficheDeLaPieceEtPasSonIdentifiant() {
        val maintenant = 1790000000.0
        val releve = Mesures.Releve(maintenant, capteursAir("zone_salon", "1200", maintenant))
        val corresp = mapOf("piece_salon_12" to listOf("zone_salon"))
        // avec le nom de la carte
        val avec = Mesures.parPiece(releve, corresp, emptyList(), noms = mapOf("piece_salon_12" to "Salon")).getValue("piece_salon_12")
        assertEquals("Aère la pièce Salon, CO2 1200 ppm", avec.alerte)
        // sans nom connu (voix avant l'ouverture de la maison en grand) : repli lisible, pas d'identifiant technique
        val sans = Mesures.parPiece(releve, corresp, emptyList(), noms = Mesures.nomsLisibles(corresp.keys, emptyMap())).getValue("piece_salon_12")
        assertEquals("Aère la pièce Piece salon 12, CO2 1200 ppm", sans.alerte)
        assertFalse(sans.alerte.contains("_"))
    }

    private fun troisPieces(): Map<String, Mesures.PieceMesures> {
        val m = 1790000000.0
        val capteurs = capteursAir("z_salon", "500", m) + capteursAir("z_chambre", "500", m) + capteursAir("z_bureau", "500", m) +
            Mesures.Capteur("sensor.t_cam", "temperature", "20", "z_camille", "", "", m - 30)
        val corresp = linkedMapOf(
            "camille" to listOf("z_camille"), "salon" to listOf("z_salon"), "chambre" to listOf("z_chambre"),
            "bureau" to listOf("z_bureau"), "vide" to listOf("z_nulle"),
        )
        return Mesures.parPiece(Mesures.Releve(m, capteurs), corresp, listOf("camille"))
    }

    @Test
    fun ligneAccueilPrendLaPremierePieceQuiParleEtSauteLesProtegeesEtLesMuettes() {
        val r = troisPieces()
        assertEquals(Mesures.Statut.PROTEGEE, r.getValue("camille").statut)
        assertEquals(Mesures.Statut.AUCUN, r.getValue("vide").statut)
        // « camille » est protégée : c'est la suivante dans l'ordre de la configuration qui parle
        assertEquals("Le salon 21°, air bon", Mesures.ligneAccueil(r, mapOf("salon" to "Le salon")))
        assertEquals("Salon 21°, air bon", Mesures.ligneAccueil(r))
    }

    @Test
    fun ligneAccueilDonneLaParoleAPieceQuiDoitEtreAeree() {
        val m = 1790000000.0
        val capteurs = capteursAir("z_salon", "500", m) + capteursAir("z_bureau", "1200", m) + capteursAir("z_chambre", "1600", m)
        val corresp = linkedMapOf("salon" to listOf("z_salon"), "bureau" to listOf("z_bureau"), "chambre" to listOf("z_chambre"))
        val r = Mesures.parPiece(Mesures.Releve(m, capteurs), corresp, emptyList(), noms = mapOf("chambre" to "Chambre"))
        // la pire d'abord, même si le salon est la pièce principale
        assertEquals("Chambre 21°, air mauvais", Mesures.ligneAccueil(r, mapOf("chambre" to "Chambre")))
    }

    @Test
    fun ligneAccueilVideQuandPersonneNaRienADire() {
        assertEquals("", Mesures.ligneAccueil(emptyMap()))
        val m = 1790000000.0
        val r = Mesures.parPiece(Mesures.Releve(m, emptyList()), mapOf("a" to listOf("z")), listOf("b"))
        assertEquals("", Mesures.ligneAccueil(r))
        val protegee = Mesures.parPiece(Mesures.Releve(m, capteursAir("z", "500", m)), mapOf("a" to listOf("z")), listOf("z"))
        assertEquals("", Mesures.ligneAccueil(protegee))
    }
}
