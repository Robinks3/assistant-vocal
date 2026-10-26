package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNotNull
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Questions vocales sur les mesures d'une pièce et pastille des étiquettes de la vue maison entière (S-L6). */
class MesuresQuestionTest {

    private val pieces = mapOf("sejour_cuisine" to "Séjour et cuisine", "chambre_sacha" to "Chambre de Sacha", "chambre_camille" to "Chambre de Camille")
    private val zones = mapOf(
        "sejour_cuisine" to listOf("coin_repas", "salon", "cuisine"), "chambre_sacha" to listOf("chambre_1"),
        "chambre_camille" to listOf("chambre_camille"),
    )

    private fun q(phrase: String) = MesuresQuestion.comprendre(phrase, pieces, zones)

    private fun releve(vararg c: Mesures.Capteur) = Mesures.Releve(1790000000.0, c.toList())

    private fun capteur(id: String, classe: String, etat: String, zone: String, age: Double = 30.0) =
        Mesures.Capteur(id, classe, etat, zone, "", "", 1790000000.0 - age)

    @Test
    fun laPieceSeDevineParSonNomOuParUneDeSesZones() {
        assertEquals("sejour_cuisine", q("quelle température dans le salon")?.piece)
        assertEquals("sejour_cuisine", q("il fait combien dans la cuisine")?.piece)
        assertEquals("sejour_cuisine", q("quelle est l'humidité du séjour")?.piece)
        assertEquals("chambre_camille", q("comment est l'air dans la chambre de Camille")?.piece)
        assertEquals(MesuresQuestion.Sujet.AIR, q("comment est l'air dans le salon")?.sujet)
        assertEquals(MesuresQuestion.Sujet.HUMIDITE, q("quelle est l'humidité du salon")?.sujet)
        assertEquals(MesuresQuestion.Sujet.TEMPERATURE, q("quelle température dans le salon")?.sujet)
    }

    @Test
    fun uneChambreAmbigueOuUnOrdreNeSontPasDesQuestions() {
        assertNull("deux chambres : ambigu", q("quelle température dans la chambre"))
        assertNull("pas de pièce", q("quelle température fait-il demain"))
        assertNull("un ordre", q("mets l'air du salon plus fort"))
        assertNull("autre sujet", q("allume le salon"))
        assertNull(MesuresQuestion.comprendre("quelle température dans le salon", emptyMap()))
    }

    @Test
    fun reponseDeLaTemperatureEtDeLAir() {
        val r = Mesures.parPiece(
            releve(capteur("sensor.t", "temperature", "21,4", "salon"), capteur("sensor.c", "carbon_dioxide", "1200", "salon")),
            zones, emptyList(), noms = pieces,
        )
        val p = r.getValue("sejour_cuisine")
        assertEquals("Il fait 21° dans la pièce Séjour et cuisine, c'est agréable.", MesuresQuestion.repondre(q("quelle température dans le salon")!!, p))
        val air = MesuresQuestion.repondre(q("comment est l'air du salon")!!, p)
        assertTrue(air, air.startsWith("L'air de la pièce Séjour et cuisine est médiocre, CO2 1200 ppm."))
        assertTrue(air, air.contains("Le CO2 passe à mauvais au-dessus de 1500 ppm."))
        assertTrue(air, air.endsWith("Pense à aérer."))
        assertEquals("Il n'y a pas de capteur d'humidité dans la pièce Séjour et cuisine.", MesuresQuestion.repondre(q("humidité du salon")!!, p))
    }

    @Test
    fun uneMesureAbsenteEtUneAbsenceDeCapteur() {
        val r = Mesures.parPiece(releve(capteur("sensor.t", "temperature", "unavailable", "salon", 1800.0)), zones, emptyList(), noms = pieces)
        assertTrue(MesuresQuestion.repondre(q("quelle température dans le salon")!!, r.getValue("sejour_cuisine")).contains("absente depuis"))
        assertEquals(
            "Il n'y a pas de capteur dans la pièce Chambre de Sacha.",
            MesuresQuestion.repondre(q("quelle température dans la chambre de Sacha")!!, r.getValue("chambre_sacha")),
        )
    }

    @Test
    fun laPieceProtegeeNeLivreAucuneValeur() {
        val r = Mesures.parPiece(
            releve(capteur("sensor.t", "temperature", "19", "chambre_camille"), capteur("sensor.c", "carbon_dioxide", "1700", "chambre_camille")),
            zones, listOf("chambre_camille"), noms = pieces,
        )
        for (phrase in listOf("quelle température dans la chambre de Camille", "comment est l'air dans la chambre de Camille", "les mesures de la chambre de Camille")) {
            val reponse = MesuresQuestion.repondre(q(phrase)!!, r.getValue("chambre_camille"))
            assertEquals("Je ne donne pas les mesures de cette pièce.", reponse)
            assertFalse(reponse, reponse.contains("19") || reponse.contains("1700"))
        }
    }

    @Test
    fun lEtiquetteDePieceCarrePorteLaMesureEtLeVerrouLaCache() {
        val contenu = """[{"id":"sejour_cuisine","nom":"Séjour et cuisine","lampes":[{"entite":"light.salon_plafond","nom":"Salon"}],"medias":[]},
            {"id":"chambre_camille","nom":"Chambre de Camille","lampes":[{"entite":"light.chambre_camille_plafonds","nom":""}],"medias":[]}]"""
        val liste = MaisonEnGrand.lireContenu(contenu)
        val lus = MaisonEnGrand.index(
            listOf(
                Appareils.Appareil("light.salon_plafond", "x", "on", "", "", luminosite = 80, modes = listOf("brightness")),
                Appareils.Appareil("light.chambre_camille_plafonds", "x", "off", "", "", modes = listOf("brightness")),
            ),
            emptyList(),
        )
        val sans = Mesures.parPiece(
            releve(capteur("sensor.t", "temperature", "21", "salon"), capteur("sensor.t2", "temperature", "18", "chambre_camille")),
            zones, emptyList(), noms = pieces,
        )
        val e = MaisonEnGrand.etiquettes(liste, lus, "", false, estProtegee = { it.id == "chambre_camille" }, mesures = sans)
        val s = e.getJSONObject(0).getJSONObject("mesure")
        assertEquals("21°, pas de capteur d'air", s.getString("texte"))
        assertEquals(Mesures.COULEUR_GRIS, s.getString("couleur"))
        val c = e.getJSONObject(1)
        assertTrue(c.getBoolean("verrou"))
        val m = c.getJSONObject("mesure")
        assertEquals("pièce protégée", m.getString("texte"))
        assertEquals("protegee", m.getString("statut"))
        assertFalse(m.toString().contains("18"))
        // Sans mesures : l'étiquette garde sa forme d'avant et la maison injoignable n'en montre aucune.
        assertFalse(MaisonEnGrand.etiquettes(liste, lus, "", false).getJSONObject(0).has("mesure"))
        assertFalse(MaisonEnGrand.etiquettes(liste, lus, "", true, mesures = sans).getJSONObject(0).has("mesure"))
        assertNotNull(e)
    }
}
