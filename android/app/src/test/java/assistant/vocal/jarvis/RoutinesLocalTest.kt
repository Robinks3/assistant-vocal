package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.text.Normalizer

/**
 * Routines reçues du serveur (0.40.0, lot S-R3). Logique pure : la liste reçue, la portée par personne, la
 * décision locale, la confirmation d'un brouillon et le motif de création. Sans Android ni dictionnaire : la
 * forme comparée est calculée par une fonction simple (minuscules, sans accent ni ponctuation), comme le fait
 * `forme()` du serveur.
 */
class RoutinesLocalTest {

    private fun forme(t: String): String =
        Normalizer.normalize(t.lowercase(), Normalizer.Form.NFD).replace(Regex("\\p{Mn}+"), "")
            .replace(Regex("[^a-z0-9 ]"), " ").replace(Regex("\\s+"), " ").trim()

    private fun routines() = RoutinesLocal(::forme)

    private fun resume(
        id: String, nom: String, auteur: String? = "Sacha", pour: String = "auteur", actif: Boolean = true,
        phrases: List<String> = emptyList(), variantes: List<String> = emptyList(),
    ): JSONObject = JSONObject()
        .put("id", id).put("nom", nom).put("auteur", auteur ?: JSONObject.NULL).put("pour", pour).put("actif", actif)
        .put("phrases", JSONArray(phrases)).put("variantes", JSONArray(variantes)).put("etapes", 2)

    private fun reponse(version: Int, vararg r: JSONObject): JSONObject =
        JSONObject().put("etat", "routines").put("version", version).put("routines", JSONArray(r.toList()))

    private fun garni(): RoutinesLocal {
        val r = routines()
        r.serveurSait = true
        val liste = reponse(
            3,
            resume("r1", "bonne nuit", "Sacha", "auteur", phrases = listOf("Bonne nuit"), variantes = listOf("je vais dormir")),
            resume("r2", "cinéma", "Camille", "tous", phrases = listOf("C'est l'heure du cinéma")),
            resume("r3", "secret de Camille", "Camille", "auteur", phrases = listOf("mode secret")),
            resume("r4", "coupée", "Sacha", "tous", actif = false, phrases = listOf("ancienne routine du matin")),
        )
        // La même liste pour chacun : la portée se juge à la phrase dite, pas à la liste lue.
        for (p in listOf("Sacha", "Camille", "")) r.enregistrer(p, liste)
        return r
    }

    // ------------------------------------------------------------ liste reçue

    @Test
    fun lecture_phrases_et_variantes() {
        val r = routines()
        val n = r.enregistrer(
            "Sacha",
            reponse(1, resume("r1", "bonne nuit", phrases = listOf("Bonne nuit  "), variantes = listOf("je vais dormir", " "))),
        )
        assertEquals(1, n)
        val b = r.routines("Sacha").single()
        assertEquals(listOf("Bonne nuit", "je vais dormir"), b.phrases)
        assertEquals(setOf("bonne nuit", "je vais dormir"), b.formes)
        assertEquals(1, r.version("Sacha"))
    }

    @Test
    fun lecture_ignore_les_entrees_sans_identifiant_et_les_reponses_vides() {
        val r = routines()
        assertEquals(0, r.enregistrer("", JSONObject().put("etat", "routines")))
        assertEquals(1, r.enregistrer("", reponse(2, resume("", "sans id"), resume("ok", "valide", phrases = listOf("salut")))))
        assertEquals("ok", r.routines("").single().id)
    }

    @Test
    fun auteur_nul_est_une_chaine_vide() {
        val r = routines()
        r.enregistrer("", reponse(1, resume("r1", "libre", auteur = null, pour = "tous", phrases = listOf("salut"))))
        assertEquals("", r.routines("").single().auteur)
    }

    @Test
    fun liste_gardee_par_personne_avec_repli_sur_la_liste_sans_personne() {
        val r = routines()
        r.enregistrer("", reponse(1, resume("t", "pour tous", pour = "tous", phrases = listOf("bonjour la maison"))))
        r.enregistrer("Sacha", reponse(2, resume("s", "à Sacha", phrases = listOf("mon rituel"))))
        assertEquals("s", r.routines("sacha").single().id)
        assertEquals("s", r.routines("Sacha").single().id)
        // Camille n'a pas de liste propre : celle sans personne, les routines « tous », sert de repli.
        assertEquals("t", r.routines("Camille").single().id)
        assertEquals("t", r.routines("inconnu").single().id)
    }

    @Test
    fun peremption_et_rafraichissement() {
        val r = garni()
        assertTrue(r.aJour("Sacha"))
        assertFalse(r.aJour("Louise"))
        r.perimer()
        assertFalse(r.aJour("Sacha"))
        assertEquals(setOf("sacha", "camille", ""), r.personnes().toSet())
        r.enregistrer("Sacha", reponse(4))
        assertTrue(r.aJour("Sacha"))
        assertFalse(r.aJour("Camille"))
        assertEquals(4, r.version("Sacha"))
        assertEquals(-1, r.version("Louise"))
    }

    // ------------------------------------------------------------ portée

    @Test
    fun portee_auteur_et_tous() {
        val bonneNuit = garni().routines("Sacha").first { it.id == "r1" }
        assertTrue(bonneNuit.lancablePar("Sacha"))
        assertTrue(bonneNuit.lancablePar("sacha"))
        assertFalse(bonneNuit.lancablePar("Camille"))
        // Sans personne reconnue, une routine d'auteur ne part pas.
        assertFalse(bonneNuit.lancablePar(""))
        assertFalse(bonneNuit.lancablePar("inconnu"))
        val cinema = garni().routines("Sacha").first { it.id == "r2" }
        assertTrue(cinema.lancablePar(""))
        assertTrue(cinema.lancablePar("Camille"))
    }

    @Test
    fun cle_sans_accent_en_minuscules() {
        assertEquals("sacha", RoutinesLocal.cle(" Sacha "))
        assertEquals("rene", RoutinesLocal.cle("René"))
        assertEquals("", RoutinesLocal.cle("inconnu"))
        assertEquals("", RoutinesLocal.cle(""))
    }

    // ------------------------------------------------------------ décision

    @Test
    fun sans_serveur_ni_liste_rien_ne_change() {
        val r = routines()
        assertTrue(r.decider("bonne nuit", "Sacha") === RoutinesLocal.Decision.Aucune)
        assertTrue(r.decider("crée une routine", "Sacha") === RoutinesLocal.Decision.Aucune)
        assertTrue(r.vide)
    }

    @Test
    fun phrase_de_routine_lance() {
        val r = garni()
        for (phrase in listOf("Bonne nuit", "bonne nuit !", "BONNE NUIT", "je vais dormir")) {
            val d = r.decider(phrase, "Sacha")
            assertTrue(phrase, d is RoutinesLocal.Decision.Lancer)
            assertEquals("r1", (d as RoutinesLocal.Decision.Lancer).routine.id)
        }
        val tous = r.decider("c'est l'heure du cinéma", "Camille")
        assertEquals("r2", (tous as RoutinesLocal.Decision.Lancer).routine.id)
    }

    @Test
    fun routine_reservee_part_au_serveur() {
        val r = garni()
        val d = r.decider("bonne nuit", "Camille")
        assertTrue(d is RoutinesLocal.Decision.Serveur)
        assertTrue((d as RoutinesLocal.Decision.Serveur).raison.contains("bonne nuit"))
        // Personne non reconnue : même chose, le serveur dit pourquoi.
        assertTrue(r.decider("bonne nuit", "") is RoutinesLocal.Decision.Serveur)
        assertTrue(r.decider("bonne nuit", "inconnu") is RoutinesLocal.Decision.Serveur)
    }

    @Test
    fun routine_coupee_est_ignoree() {
        val r = garni()
        assertTrue(r.decider("ancienne routine du matin", "Sacha") is RoutinesLocal.Decision.Serveur)
        // Sans le mot « routine » dans la phrase, une routine coupée ne répond pas.
        val coupee = routines()
        coupee.serveurSait = true
        coupee.enregistrer("", reponse(1, resume("c", "coupée", pour = "tous", actif = false, phrases = listOf("salut la maison"))))
        assertTrue(coupee.decider("salut la maison", "Sacha") === RoutinesLocal.Decision.Aucune)
    }

    @Test
    fun phrase_ordinaire_continue_la_chaine() {
        val r = garni()
        for (phrase in listOf("allume le salon", "quelle heure est-il", "mets la musique", "fais une pause", "ajoute du lait à la liste", "")) {
            assertTrue(phrase, r.decider(phrase, "Sacha") === RoutinesLocal.Decision.Aucune)
        }
    }

    @Test
    fun mot_routine_part_au_serveur() {
        val r = garni()
        for (phrase in listOf("quelles sont mes routines", "supprime la routine du soir", "active la routine bonne nuit", "liste mes routines")) {
            assertTrue(phrase, r.decider(phrase, "Sacha") is RoutinesLocal.Decision.Serveur)
        }
    }

    @Test
    fun creation_part_au_serveur_meme_sans_le_mot_routine() {
        val r = garni()
        for (phrase in listOf("quand je te dis cinéma tu baisses la lumière", "dorénavant bonne nuit éteint tout", "à partir de maintenant ça veut dire dormir")) {
            val d = r.decider(phrase, "Sacha")
            assertTrue(phrase, d is RoutinesLocal.Decision.Serveur)
            assertEquals(phrase, "création d'une routine", (d as RoutinesLocal.Decision.Serveur).raison)
        }
    }

    @Test
    fun serveur_sait_mais_liste_absente_cree_et_gere_quand_meme() {
        val r = routines()
        r.serveurSait = true
        assertTrue(r.decider("crée une routine pour le matin", "Sacha") is RoutinesLocal.Decision.Serveur)
        assertTrue(r.decider("allume le salon", "Sacha") === RoutinesLocal.Decision.Aucune)
    }

    // ------------------------------------------------------------ confirmation d'un brouillon

    @Test
    fun confirmation_dans_le_delai() {
        val r = routines()
        assertFalse(r.confirmationEnAttente(0))
        r.attendreConfirmation(30, 10_000)
        assertTrue(r.confirmationEnAttente(10_000))
        assertTrue(r.confirmationEnAttente(39_999))
        assertFalse(r.confirmationEnAttente(40_000))
        assertFalse(r.confirmationEnAttente(90_000))
    }

    @Test
    fun confirmation_terminee_ou_sans_delai() {
        val r = routines()
        r.attendreConfirmation(30, 0)
        r.finirConfirmation()
        assertFalse(r.confirmationEnAttente(1))
        r.attendreConfirmation(30, 0)
        r.attendreConfirmation(0, 100)
        assertFalse(r.confirmationEnAttente(101))
    }

    @Test
    fun marge_de_confirmation_positive() {
        assertTrue(RoutinesLocal.MARGE_CONFIRMATION_S > 0)
    }

    // ------------------------------------------------------------ motif de création

    private fun intention(phrase: String) = RoutinesLocal.INTENTION_ROUTINE.containsMatchIn(phrase)

    private fun cas(): JSONObject {
        var dossier: File? = File(System.getProperty("user.dir") ?: ".").absoluteFile
        while (dossier != null) {
            val f = File(dossier, "poc/tests/cas_routines.json")
            if (f.isFile) return JSONObject(f.readText(Charsets.UTF_8))
            dossier = dossier.parentFile
        }
        error("poc/tests/cas_routines.json introuvable depuis ${System.getProperty("user.dir")}")
    }

    @Test
    fun intention_cas_communs_avec_le_serveur() {
        val bloc = cas().getJSONObject("intention")
        val oui = bloc.getJSONArray("oui")
        val non = bloc.getJSONArray("non")
        assertTrue(oui.length() > 0 && non.length() > 0)
        for (i in 0 until oui.length()) assertTrue(oui.getString(i), intention(oui.getString(i)))
        for (i in 0 until non.length()) assertFalse(non.getString(i), intention(non.getString(i)))
    }

    @Test
    fun intention_formes_a_verbe_avec_le_mot_routine() {
        val oui = listOf(
            "crée-moi une routine", "Crée moi une routine pour le soir", "fais-moi une routine du matin", "fais une routine",
            "fais une routine pour le soir", "ajoute une routine du matin", "ajoute-moi une routine", "programme une routine",
            "programme-moi une routine du dimanche", "mets en place une routine", "mets en place une routine pour la nuit",
            "enregistre une routine", "enregistre-moi une routine de nuit", "configure une routine", "configure-moi une routine",
            "prépare une routine", "prépare-moi une routine du matin", "prepare une routine",
            "peux-tu me créer une routine", "Peux tu me faire une routine du soir", "peux-tu m'ajouter une routine",
            "pourriez-vous me programmer une routine", "peux-tu me mettre en place une routine",
            "je voudrais une routine", "je voudrais créer une routine", "je veux une routine pour la nuit",
            "je veux créer une routine", "j'aimerais une routine du matin", "j'aimerais créer une routine",
            "j'aimerais avoir une routine", "j’aimerais une routine", "je voudrais faire une nouvelle routine",
        )
        for (p in oui) assertTrue(p, intention(p))
    }

    @Test
    fun intention_sans_faux_positif_sans_le_mot_routine() {
        val non = listOf(
            "fais une pause", "fais-moi un café", "mets la musique", "mets en place la table", "mets en pause", "ajoute du lait à la liste",
            "ajoute une alarme", "programme le réveil à sept heures", "enregistre une note", "configure la lampe", "prépare le salon",
            "peux-tu me faire un café", "peux-tu me dire l'heure", "peux-tu m'allumer le salon", "je voudrais un café",
            "je veux de la musique", "j'aimerais de la lumière", "crée un rappel pour demain", "allume la cuisine",
            "quelle est la routine du matin", "ma routine sportive est longue",
        )
        for (p in non) assertFalse(p, intention(p))
    }

    @Test
    fun intention_cree_une_routine_est_aussi_un_signal_de_creation() {
        val r = garni()
        for (p in listOf("fais-moi une routine du soir", "j'aimerais créer une routine", "peux-tu me créer une routine")) {
            val d = r.decider(p, "Sacha")
            assertTrue(p, d is RoutinesLocal.Decision.Serveur)
        }
    }
}
