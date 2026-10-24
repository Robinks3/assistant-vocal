package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test
import kotlin.math.abs

/** Protection de l'écran OLED (0.17.0) : régimes, minuteries, transitions, décalage global, écran AOD (0.17.2). */
class VeilleTest {

    private val minute = 60_000L

    /** Avance pas à pas de 100 ms jusqu'à [jusqua], comme le ferait l'écran. */
    private fun Veille.aller(depuis: Long, jusqua: Long, presence: Boolean = false, activite: Long = 0L,
                             occupe: Boolean = false, nuit: Boolean = false, musique: Boolean = false) {
        var t = depuis
        while (t <= jusqua) {
            avancer(t, presence, activite, occupe, nuit, musique)
            t += 100
        }
    }

    @Test
    fun personneDepuisDeuxMinutesAod() {
        val v = Veille()
        v.aller(0, 2 * minute - 100)
        assertEquals(Veille.Regime.VIVANT, v.regime)
        assertEquals(1f, v.vie, 0f)
        v.aller(2 * minute, 2 * minute + 1000)
        assertEquals(Veille.Regime.AOD, v.regime)
        // Fondu de 2 s : à mi-chemin après 1 s.
        assertTrue(v.vie > 0.4f && v.vie < 0.6f)
        v.aller(2 * minute + 1100, 2 * minute + 2500)
        assertEquals(0f, v.vie, 0f)
    }

    @Test
    fun aodTientSansLimiteDeJour() {
        // 0.17.2 : plus de veille profonde à 10 min, l'AOD reste le même toute la journée.
        val v = Veille()
        v.aller(0, 30 * minute)
        assertEquals(Veille.Regime.AOD, v.regime)
        assertEquals(0f, v.noir, 0f)
    }

    @Test
    fun presenceRallumeEnMoinsDUneSeconde() {
        val v = Veille()
        v.aller(0, 5 * minute)
        assertEquals(0f, v.vie, 0f)
        val t0 = 5 * minute + 100
        v.avancer(t0, true, 0L, false, false)
        assertEquals(Veille.Regime.VIVANT, v.regime)
        assertEquals(t0, v.repriseLe)
        v.aller(t0 + 100, t0 + 500, presence = true)
        assertTrue(v.vie > 0.4f && v.vie < 0.8f)
        v.aller(t0 + 600, t0 + 900, presence = true)
        assertEquals(1f, v.vie, 0f)
    }

    @Test
    fun laPieceSeVideRetourApresDeuxMinutes() {
        val v = Veille()
        v.aller(0, 3 * minute, presence = true)
        assertEquals(Veille.Regime.VIVANT, v.regime)
        // Plus personne à 3 min : encore vivant à 4 min 59, protection à 5 min.
        v.aller(3 * minute + 100, 5 * minute - 100)
        assertEquals(Veille.Regime.VIVANT, v.regime)
        v.aller(5 * minute + 100, 5 * minute + 100)
        assertEquals(Veille.Regime.AOD, v.regime)
    }

    @Test
    fun sansVisionLeToucherTientLieuDePresence() {
        val v = Veille()
        v.aller(0, 4 * minute)
        assertEquals(Veille.Regime.AOD, v.regime)
        val toucher = 4 * minute + 50
        v.aller(4 * minute + 100, 4 * minute + 100, activite = toucher)
        assertEquals(Veille.Regime.VIVANT, v.regime)
        v.aller(4 * minute + 200, toucher + 2 * minute - 100, activite = toucher)
        assertEquals(Veille.Regime.VIVANT, v.regime)
        v.aller(toucher + 2 * minute + 50, toucher + 2 * minute + 50, activite = toucher)
        assertEquals(Veille.Regime.AOD, v.regime)
    }

    @Test
    fun uneCommandeEnCoursGardeVivant() {
        val v = Veille()
        v.aller(0, 20 * minute, occupe = true)
        assertEquals(Veille.Regime.VIVANT, v.regime)
        assertTrue(v.textesVisibles(20 * minute, 0L))
        // Textes encore visibles 9 s après la commande, plus après 10 s.
        v.aller(20 * minute + 100, 20 * minute + 9000)
        assertTrue(v.textesVisibles(20 * minute + 9000, 0L))
        v.aller(20 * minute + 9100, 20 * minute + 10_100)
        assertFalse(v.textesVisibles(20 * minute + 10_100, 0L))
    }

    @Test
    fun laNuitSansPersonneEcranNoir() {
        val v = Veille()
        v.aller(0, 2 * minute + 2500, nuit = true)
        assertEquals(Veille.Regime.ETEINT, v.regime)
        assertEquals(1f, v.noir, 0f)
        assertEquals(0f, v.luminosite(true), 0f)
        // Le mot de réveil (activité) rallume.
        val reveil = 2 * minute + 2600
        v.aller(reveil, reveil + 900, activite = reveil, nuit = true)
        assertEquals(Veille.Regime.VIVANT, v.regime)
        assertEquals(0f, v.noir, 0f)
        assertEquals(Veille.LUMINOSITE_NUIT, v.luminosite(true), 1e-6f)
    }

    @Test
    fun luminositeBornee() {
        val v = Veille()
        v.aller(0, 1000, presence = true)
        assertEquals(Veille.LUMINOSITE_PLAFOND, v.luminosite(false), 1e-6f)
        v.aller(1100, 3 * minute + 1100)
        assertEquals(Veille.LUMINOSITE_MIN, v.luminosite(false), 1e-6f)
    }

    @Test
    fun deriveDeLHeureLenteEtBornee() {
        // 0.18.1 : ±42 px sur x, ±24 px sur y, au plus quelques pixels par minute, et toute l'amplitude parcourue.
        var avant = Veille.deriveHeure(0L)
        var xMin = 0f; var xMax = 0f; var yMin = 0f; var yMax = 0f
        for (m in 1L..(6 * 60L)) {
            val d = Veille.deriveHeure(m * minute)
            assertTrue(abs(d.first) <= 42f && abs(d.second) <= 24f)
            assertTrue("trop rapide à $m", abs(d.first - avant.first) <= 5.5f && abs(d.second - avant.second) <= 3.6f)
            xMin = minOf(xMin, d.first); xMax = maxOf(xMax, d.first); yMin = minOf(yMin, d.second); yMax = maxOf(yMax, d.second)
            avant = d
        }
        assertTrue(xMax > 41f && xMin < -41f && yMax > 23f && yMin < -23f)
        // Périodes différentes : le bloc ne repasse pas au même point au bout d'un seul cycle.
        assertTrue(Veille.deriveHeure(50 * minute) != Veille.deriveHeure(0L))
    }

    @Test
    fun decalageUnPixelParMinuteDansLeCarre() {
        var avant = Veille.decalage(0)
        assertEquals(-24 to -24, avant)
        val vus = HashSet<Pair<Int, Int>>()
        for (m in 1L..(2L * Veille.PERIODE_MIN + 5)) {
            val d = Veille.decalage(m)
            assertTrue("x hors borne à $m", abs(d.first) <= Veille.BORNE_PX)
            assertTrue("y hors borne à $m", abs(d.second) <= Veille.BORNE_PX)
            assertEquals("pas d'un pixel à $m", 1, abs(d.first - avant.first) + abs(d.second - avant.second))
            vus.add(d)
            avant = d
        }
        // Toutes les positions du carré sont visitées, et le chemin revient au départ.
        assertEquals(49 * 49, vus.size)
        assertEquals(Veille.decalage(0), Veille.decalage(Veille.PERIODE_MIN.toLong()))
        // Minutes négatives (horloge mal réglée) : toujours dans le carré.
        val n = Veille.decalage(-7)
        assertTrue(abs(n.first) <= 24 && abs(n.second) <= 24)
    }

    @Test
    fun miroirUnJourSurDeux() {
        assertFalse(Veille.miroir(20_000))
        assertTrue(Veille.miroir(20_001))
        assertFalse(Veille.miroir(20_002))
        assertTrue(Veille.miroir(-1))
    }

    @Test
    fun bullesRallumeesLUneApresLAutre() {
        assertEquals(0f, Veille.allumage(1, 100), 0f)
        assertTrue(Veille.allumage(0, 300) > Veille.allumage(1, 300))
        assertTrue(Veille.allumage(1, 300) > Veille.allumage(2, 300))
        assertEquals(1f, Veille.allumage(3, 3 * 120L + 600), 0f)
    }

    @Test
    fun aodLuminositeAuPlancher() {
        // Le plancher est la plus basse valeur que la fenêtre accepte (BRIGHTNESS_OVERRIDE_OFF), jamais négative.
        assertEquals(0f, Veille.LUMINOSITE_MIN, 0f)
        val v = Veille()
        v.aller(0, 2 * minute + 2500)
        assertEquals(Veille.Regime.AOD, v.regime)
        assertEquals(0f, v.vie, 0f)
        assertEquals(0f, v.luminosite(false), 0f)
        assertTrue(v.luminosite(false) >= 0f)
        // Pendant le fondu, la luminosité descend sans jamais passer sous le plancher.
        val w = Veille()
        w.aller(0, 2 * minute + 1000)
        val l = w.luminosite(false)
        assertTrue(l > 0f && l < Veille.LUMINOSITE_PLAFOND)
        // Pas de texte d'état en AOD.
        assertFalse(v.textesVisibles(2 * minute + 2500, 2 * minute + 2400))
    }

    @Test
    fun aodZonesQuiTournent() {
        val vues = HashSet<Int>()
        var avant = Veille.zoneAod(-1)
        for (p in 0L until 8 * 30) {
            val z = Veille.zoneAod(p)
            assertTrue("zone $z hors de la grille", z in 0..8)
            assertTrue("zone du centre à $p", z != 4)
            assertTrue("même zone deux fois de suite à $p", z != avant)
            vues.add(z)
            avant = z
        }
        assertEquals(8, vues.size)
        // Chaque tour de 24 min passe par les huit zones, en commençant ailleurs que le précédent.
        for (tour in 0L until 10) {
            val dansTour = (0 until 8).map { Veille.zoneAod(tour * 8 + it) }.toSet()
            assertEquals(8, dansTour.size)
        }
        assertTrue(Veille.zoneAod(0) != Veille.zoneAod(8))
        // Horloge mal réglée (avant 1970) : toujours une zone permise.
        assertTrue(Veille.zoneAod(-12_345) in Veille.ZONES_AOD)
        // Toutes les 3 min : même période pendant 3 min, la suivante ensuite.
        assertEquals(Veille.periodeAod(0), Veille.periodeAod(Veille.PERIODE_AOD_MS - 1))
        assertEquals(Veille.periodeAod(0) + 1, Veille.periodeAod(Veille.PERIODE_AOD_MS))
    }

    @Test
    fun aodBlocDansLEcranHorsDesBords() {
        val marge = 56f
        for ((largeur, hauteur) in listOf(2560f to 1500f, 1280f to 720f, 900f to 500f)) {
            val bw = 420f
            val bh = 260f
            val places = HashSet<Pair<Int, Int>>()
            for (p in -20L until 500L) {
                val x = Veille.placeAodX(p, largeur, bw, marge)
                val y = Veille.placeAodY(p, hauteur, bh, marge)
                assertTrue("x trop à gauche à $p", x >= marge)
                assertTrue("x trop à droite à $p", x + bw <= largeur - marge)
                assertTrue("y trop haut à $p", y >= marge)
                assertTrue("y trop bas à $p", y + bh <= hauteur - marge)
                // Le centre du bloc tombe dans le tiers de sa zone.
                val z = Veille.zoneAod(p)
                val libreX = largeur - 2 * marge - bw
                val tiers = ((x - marge) / libreX * 3f).toInt().coerceIn(0, 2)
                assertEquals("colonne de la zone à $p", z % 3, tiers)
                places.add(x.toInt() to y.toInt())
            }
            // Les places varient aussi dans une même zone.
            assertTrue(places.size > 100)
        }
        // Bloc plus grand que l'écran : centré, jamais hors de l'écran à gauche ou en haut.
        val x = Veille.placeAodX(3, 300f, 400f, 20f)
        assertEquals(0f, x, 0f)
        assertEquals(50f, Veille.placeAodX(3, 500f, 400f, 60f), 0f)
    }

    @Test
    fun aodFonduLentAuChangementDeZone() {
        val p = Veille.PERIODE_AOD_MS
        assertEquals(0f, Veille.opaciteAod(0), 0f)
        assertEquals(1f, Veille.opaciteAod(p / 2), 0f)
        assertEquals(1f, Veille.opaciteAod(Veille.FONDU_AOD_MS), 0f)
        val mi = Veille.opaciteAod(Veille.FONDU_AOD_MS / 2)
        assertTrue(mi > 0.4f && mi < 0.6f)
        // Le bloc s'efface avant de changer de zone.
        assertTrue(Veille.opaciteAod(p - 200) < 0.1f)
        for (t in 0L until p step 997) {
            val o = Veille.opaciteAod(t)
            assertTrue(o in 0f..1f)
        }
        // Images : 15 par seconde pendant un fondu, sinon rien jusqu'au prochain fondu.
        assertEquals(66L, Veille.attenteAod(100))
        assertEquals(p - Veille.FONDU_AOD_MS - p / 2, Veille.attenteAod(p / 2))
        assertTrue(Veille.attenteAod(-5) >= 1L)
    }

    @Test
    fun aodRienDeColore() {
        for (c in Veille.COULEURS_AOD) {
            assertEquals("opaque", 0xff, (c ushr 24) and 0xff)
            val (s, l) = Veille.saturationLuminosite(c)
            assertTrue("couleur saturée : ${Integer.toHexString(c)}", s <= 0.3f)
            assertTrue("gris trop clair : ${Integer.toHexString(c)}", l <= 0.45f)
        }
        // Le point de l'orbe est très foncé, l'heure reste la plus lisible.
        assertTrue(Veille.saturationLuminosite(Veille.GRIS_AOD_POINT).second <= 0.15f)
        assertTrue(Veille.saturationLuminosite(Veille.GRIS_AOD_HEURE).second > Veille.saturationLuminosite(Veille.GRIS_AOD_TEXTE).second)
        // Contrôle du calcul : un bleu vif est saturé, un gris ne l'est pas.
        assertTrue(Veille.saturationLuminosite(0xFF4C8DFF.toInt()).first > 0.9f)
        assertEquals(0f, Veille.saturationLuminosite(0xFF505050.toInt()).first, 0f)
    }

    @Test
    fun enRetraitTrenteSecondesApresLeDernierRegard() {
        // 0.24.0 : vivant plein tant qu'un visage est vu, puis 30 s, puis retrait en 6 s, toujours en régime vivant.
        val v = Veille()
        v.aller(0, minute, presence = true)
        assertEquals(1f, v.eclat, 0f)
        v.aller(minute + 100, minute + 29_900)
        assertEquals(1f, v.eclat, 0f)
        v.aller(minute + 30_000, minute + 33_000)
        assertTrue(v.eclat > 0.4f && v.eclat < 0.6f)
        v.aller(minute + 33_100, minute + 37_000)
        assertEquals(0f, v.eclat, 0f)
        assertEquals(Veille.Regime.VIVANT, v.regime)
        // Luminosité à 75 % de son plafond en retrait.
        assertEquals(Veille.LUMINOSITE_PLAFOND * Veille.RETRAIT_LUMINOSITE, v.luminosite(false), 1e-6f)
        // Un toucher ramène le vivant plein en 0,8 s.
        val t = minute + 40_000
        v.aller(t, t + 900, activite = t)
        assertEquals(1f, v.eclat, 0f)
    }

    @Test
    fun ecouteEtVoixGardentLeVivantPlein() {
        val v = Veille()
        v.aller(0, 5 * minute, occupe = true)
        assertEquals(1f, v.eclat, 0f)
    }

    @Test
    fun avecMusiqueAodApresDixMinutes() {
        val v = Veille()
        v.aller(0, 9 * minute, musique = true)
        assertEquals(Veille.Regime.VIVANT, v.regime)
        assertEquals(0f, v.eclat, 0f)
        v.aller(9 * minute + 100, 10 * minute + 100, musique = true)
        assertEquals(Veille.Regime.AOD, v.regime)
        // Sans musique, toujours 2 min.
        val w = Veille()
        w.aller(0, 2 * minute + 100)
        assertEquals(Veille.Regime.AOD, w.regime)
    }
}
