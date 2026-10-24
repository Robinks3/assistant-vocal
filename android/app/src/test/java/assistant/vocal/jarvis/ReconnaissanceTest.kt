package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/**
 * Reconnaissance des visages (Reconnaissance.kt) : seuil, marge, votes dans le temps, garde et oubli
 * de l'identité, suivi des pistes, présence et regard. Logique pure, sans caméra ni Android.
 */
class ReconnaissanceTest {

    /** Image toutes les 200 ms (5 images par seconde quand quelqu'un est là). */
    private fun images(identite: Identite, scores: Map<String, Float>, n: Int, depart: Long = 0L, pas: Long = 200L): String? {
        var r: String? = null
        for (i in 0 until n) r = identite.image(scores, depart + i * pas)
        return r
    }

    @Test
    fun seuil() {
        // Juste sous 0,42 : jamais reconnu, même longtemps.
        assertNull(images(Identite(), mapOf("sacha" to 0.41f, "lou" to 0.10f), 20))
        // À 0,42 avec une marge nette : reconnu.
        assertEquals("sacha", images(Identite(), mapOf("sacha" to 0.42f, "lou" to 0.10f), 4))
    }

    @Test
    fun marge() {
        // Deux profils trop proches (écart 0,04) : pas de décision.
        assertNull(images(Identite(), mapOf("sacha" to 0.60f, "lou" to 0.56f), 20))
        // Écart de 0,05 : décision.
        assertEquals("sacha", images(Identite(), mapOf("sacha" to 0.60f, "lou" to 0.55f), 4))
        // Un seul profil enregistré : la marge ne s'applique pas.
        assertEquals("sacha", images(Identite(), mapOf("sacha" to 0.50f), 4))
    }

    @Test
    fun votes() {
        val id = Identite()
        val s = mapOf("sacha" to 0.6f, "lou" to 0.2f)
        // Trois images concordantes ne suffisent pas.
        assertNull(images(id, s, 3))
        // La quatrième dans la fenêtre de 1,2 s confirme.
        assertEquals("sacha", id.image(s, 600))

        // Votes trop étalés : 4 images à 500 ms d'écart ne tiennent jamais dans 1,2 s.
        assertNull(images(Identite(), s, 10, pas = 500))

        // Un vote confiant pour quelqu'un d'autre dans la fenêtre bloque la confirmation.
        val conteste = Identite()
        conteste.image(s, 0)
        conteste.image(mapOf("sacha" to 0.2f, "lou" to 0.6f), 200)
        conteste.image(s, 400)
        conteste.image(s, 600)
        assertNull(conteste.image(s, 800))
        // Une fois le vote contraire sorti de la fenêtre, la confirmation vient.
        assertEquals("sacha", images(conteste, s, 4, depart = 1500))
    }

    @Test
    fun garde() {
        val id = Identite()
        val s = mapOf("sacha" to 0.6f, "lou" to 0.2f)
        assertEquals("sacha", images(id, s, 4))
        // Tête tournée (image inutilisable) : l'identité tient sans preuve jusqu'à 8 s.
        assertEquals("sacha", id.image(s, 7_000, utilisable = false))
        assertEquals("sacha", id.image(mapOf("sacha" to 0.30f, "lou" to 0.2f), 8_000))
        // Au-delà de 8 s sans preuve nette, elle tombe.
        assertNull(id.image(s, 17_000, utilisable = false))
        // Pas de visage du tout pour cette piste : même règle.
        val id2 = Identite()
        images(id2, s, 4)
        assertEquals("sacha", id2.absente(8_000))
        assertNull(id2.absente(8_700))
    }

    @Test
    fun oubli() {
        val s = mapOf("sacha" to 0.6f, "lou" to 0.2f)
        // Le score du profil tombe sous 0,20 : oubli immédiat, sans attendre les 8 s.
        val id = Identite()
        images(id, s, 4)
        assertNull(id.image(mapOf("sacha" to 0.19f, "lou" to 0.15f), 1_000))
        // Quelqu'un d'autre reconnu nettement : l'ancienne identité disparaît aussi.
        val id2 = Identite()
        images(id2, s, 4)
        assertNull(id2.image(mapOf("sacha" to 0.25f, "lou" to 0.62f), 1_000))
        // Entre 0,20 et le seuil : ni preuve ni oubli, l'identité tient.
        val id3 = Identite()
        images(id3, s, 4)
        assertEquals("sacha", id3.image(mapOf("sacha" to 0.25f, "lou" to 0.1f), 1_000))
    }

    private fun vecteur(vararg v: Float): FloatArray = Empreintes.normaliser(floatArrayOf(*v))

    private fun visage(empreinte: FloatArray, x: Float = 100f, regard: Boolean = true) =
        Visage(floatArrayOf(x, 60f, 80f, 80f), 0.95f, FloatArray(10), regard, 0f, empreinte)

    @Test
    fun inconnu() {
        val sacha = vecteur(1f, 0f, 0f, 0f)
        val r = Reconnaissance(listOf(Profil("1", "Sacha", sacha)))
        val autre = vecteur(0f, 0f, 1f, 0f)
        var vus = emptyList<PersonneVue>()
        // Pas encore sûr : ni nom, ni inconnu (« ma chambre » reste la chambre par défaut).
        for (i in 0 until 6) vus = r.image(listOf(visage(autre)), i * 200L)
        assertEquals(null, vus.single().nom)
        assertEquals(false, vus.single().inconnu)
        // Vu nettement 2,5 s sans ressembler à aucun profil : inconnu.
        for (i in 6..13) vus = r.image(listOf(visage(autre)), i * 200L)
        assertEquals(true, vus.single().inconnu)
        // Sacha reconnu n'est jamais inconnu, même après longtemps.
        val r2 = Reconnaissance(listOf(Profil("1", "Sacha", sacha)))
        for (i in 0 until 20) vus = r2.image(listOf(visage(sacha)), i * 200L)
        assertEquals("Sacha", vus.single().nom)
        assertEquals(false, vus.single().inconnu)
        // Sans aucun profil enregistré, personne n'est déclaré inconnu.
        val r3 = Reconnaissance()
        for (i in 0 until 20) vus = r3.image(listOf(visage(autre)), i * 200L)
        assertEquals(false, vus.single().inconnu)
    }

    @Test
    fun suiviEtNoms() {
        val sacha = vecteur(1f, 0f, 0f, 0f)
        val lou = vecteur(0f, 1f, 0f, 0f)
        val r = Reconnaissance(listOf(Profil("1", "Sacha", sacha), Profil("2", "Lou", lou)))
        var vus = emptyList<PersonneVue>()
        // Une image de Sacha un peu bruitée toutes les 200 ms : nom donné à la quatrième.
        for (i in 0 until 4) vus = r.image(listOf(visage(vecteur(0.9f, 0.1f, 0.1f, 0f))), i * 200L)
        assertEquals("Sacha", vus.single().nom)
        // Visage trop petit : inutilisable, mais l'identité de la piste tient.
        val petit = Visage(floatArrayOf(100f, 60f, 20f, 20f), 0.9f, FloatArray(10), false, 0f, vecteur(0.9f, 0.1f, 0.1f, 0f))
        assertEquals("Sacha", r.image(listOf(petit), 1_000).single().nom)
        // Deux visages : deux pistes distinctes, Lou pas encore confirmée.
        vus = r.image(listOf(visage(vecteur(0.9f, 0.1f, 0.1f, 0f)), visage(lou, x = 220f)), 1_200)
        assertEquals(2, vus.size)
        assertEquals(setOf("Sacha", null), vus.map { it.nom }.toSet())
        assertEquals(2, vus.map { it.piste }.toSet().size)
    }

    @Test
    fun regardEtPose() {
        // De face : nez au milieu des yeux et sous leur ligne.
        val face = floatArrayOf(100f, 100f, 140f, 100f, 120f, 128f, 105f, 150f, 135f, 150f)
        assertTrue(Geometrie.regard(face))
        assertEquals(0f, Geometrie.pose(face).lacet, 1e-6f)
        // Nez décalé vers un œil : de profil, ne regarde pas.
        val biais = floatArrayOf(100f, 100f, 140f, 100f, 135f, 128f, 105f, 150f, 135f, 150f)
        assertFalse(Geometrie.regard(biais))
        assertEquals(0.375f, Geometrie.pose(biais).lacet, 1e-6f)
    }

    @Test
    fun presence() {
        val p = Presence()
        assertFalse(p.image(1, 0))
        assertFalse(p.present)
        // Deux images de suite : présent.
        assertTrue(p.image(1, 200))
        assertTrue(p.present)
        // Moins de 3 s sans visage : toujours présent.
        p.image(0, 1_000)
        p.image(0, 3_100)
        assertTrue(p.present)
        // 3 s après la dernière image avec un visage : absent.
        assertTrue(p.image(0, 3_200))
        assertFalse(p.present)
    }

    @Test
    fun regardSoutenu() {
        val r = RegardSoutenu()
        assertFalse(r.image(seul = true, regarde = true, t = 0))
        assertFalse(r.image(true, true, 1_400))
        assertTrue(r.image(true, true, 1_500))
        // Une seule fois, il faut détourner le regard pour réarmer.
        assertFalse(r.image(true, true, 3_000))
        r.image(true, false, 3_200)
        assertFalse(r.image(true, true, 3_400))
        assertTrue(r.image(true, true, 4_900))
        // À deux devant la tablette, jamais.
        val deux = RegardSoutenu()
        assertFalse(deux.image(seul = false, regarde = true, t = 0))
        assertFalse(deux.image(false, true, 5_000))
    }

    @Test
    fun moyenne() {
        val m = Empreintes.moyenne(listOf(floatArrayOf(2f, 0f), floatArrayOf(0f, 1f)))
        assertEquals(1f, Empreintes.cosinus(m, m), 1e-5f)
        assertEquals(m[0], m[1], 1e-6f)
    }

    @Test
    fun identiteSureSeulementSurUneImageRecente() {
        val id = Identite()
        assertEquals("sacha", images(id, mapOf("sacha" to 0.60f, "lou" to 0.10f), 4))
        // Dernière image à 600 ms : sûre jusqu'à 1,6 s, puis gardée de mémoire seulement.
        assertTrue(id.sur(1_500L))
        assertFalse(id.sur(1_600L))
        // Image sans avis net (visage de quelqu'un d'autre rattaché par la position) : gardée, plus sûre.
        id.image(mapOf("sacha" to 0.30f, "lou" to 0.10f), 1_800L)
        assertEquals("sacha", id.profil)
        assertFalse(id.sur(1_800L))
    }
}
