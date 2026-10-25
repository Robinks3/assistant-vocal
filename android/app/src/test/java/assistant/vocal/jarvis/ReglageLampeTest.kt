package assistant.vocal.jarvis

import org.json.JSONObject
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Réglages fins d'une lampe (0.34.0) : bornes de la piste, conformité des kelvins et des teintes, lecture, affichage. */
class ReglageLampeTest {

    private fun lampe(
        etat: String = "on", modes: List<String> = listOf("color_temp", "hs"), kmin: Int = 0, kmax: Int = 0,
        kelvin: Int? = null, teinte: Float? = null, mode: String = "", lum: Int? = 80,
    ) = Appareils.Appareil("light.x", "X", etat, "", "", luminosite = lum, modes = modes, kelvinMin = kmin, kelvinMax = kmax,
        kelvin = kelvin, teinte = teinte, mode = mode)

    private fun action(donnees: Map<String, String>) =
        Maison.ActionLue("light.turn_on", listOf("light.x"), donnees, essai = false, refusee = false, ecartee = false)

    @Test
    fun pisteBorneeAuxKelvinsDeLaLampe() {
        // Famille A (2202 à 6535), B (1801 à 6535), C (2500 à 6500) : les bouts de la piste sont ceux de la lampe.
        for ((k0, k1) in listOf(2202 to 6535, 1801 to 6535, 2500 to 6500)) {
            val a = lampe(kmin = k0, kmax = k1)
            assertEquals(k0, ReglageLampe.kelvinDe(a, 0f))
            assertEquals(k1, ReglageLampe.kelvinDe(a, 1f))
            assertEquals(k0, ReglageLampe.kelvinDe(a, -3f))
            assertEquals(k1, ReglageLampe.kelvinDe(a, 7f))
            assertEquals(0.5f, ReglageLampe.fractionDe(a, (k0 + k1) / 2), 0.001f)
        }
    }

    @Test
    fun sansBornesLaPisteVaDe2700A6500() {
        val a = lampe()
        assertEquals(2700 to 6500, ReglageLampe.bornes(a))
        assertEquals(4600, ReglageLampe.kelvinDe(a, 0.5f))
    }

    @Test
    fun blancNommeBorneParLaCommande() {
        val a = lampe(kmin = 2202, kmax = 6535)
        // Bougie (2200) est sous le plancher de la famille A : la commande part à 2202.
        assertEquals(2202, Appareils.blanc(a, 2200).corps.getInt("color_temp_kelvin"))
        assertEquals(4000, Appareils.blanc(a, 4000).corps.getInt("color_temp_kelvin"))
    }

    @Test
    fun couleurNommeeEnTeinteSaturee() {
        val c = Appareils.teinte(lampe(), 220)
        assertEquals("light.turn_on", c.service)
        assertEquals("[220,100]", c.corps.getJSONArray("hs_color").toString())
    }

    @Test
    fun kelvinsAcceptesA100KPres() {
        assertTrue(ReglageLampe.kelvinConforme(2700, 2799))
        assertTrue(ReglageLampe.kelvinConforme(2700, 2600))
        assertFalse(ReglageLampe.kelvinConforme(2700, 2801))
    }

    @Test
    fun teinteAcceptee8DegresPresAvecBouclage() {
        assertTrue(ReglageLampe.teinteConforme(0f, 8f))
        assertFalse(ReglageLampe.teinteConforme(0f, 9f))
        // Autour de 0 : 355 degrés est à 5 degrés de 0, pas à 355.
        assertTrue(ReglageLampe.teinteConforme(0f, 355f))
        assertTrue(ReglageLampe.teinteConforme(358f, 4f))
        assertFalse(ReglageLampe.teinteConforme(350f, 20f))
        assertEquals(15f, ReglageLampe.ecartTeinte(350f, 5f), 0.001f)
    }

    @Test
    fun teinteDepuisLeRgbEtInversement() {
        assertEquals(0f, ReglageLampe.teinteDeRgb(listOf(255, 0, 0))!!, 0.5f)
        assertEquals(120f, ReglageLampe.teinteDeRgb(listOf(0, 255, 0))!!, 0.5f)
        assertEquals(240f, ReglageLampe.teinteDeRgb(listOf(0, 0, 255))!!, 0.5f)
        assertNull(ReglageLampe.teinteDeRgb(listOf(200, 200, 200)))
        assertEquals(listOf(255, 0, 0), ReglageLampe.rgbDeTeinte(0f))
        assertEquals(listOf(0, 255, 0), ReglageLampe.rgbDeTeinte(120f))
        assertEquals(listOf(0, 0, 255), ReglageLampe.rgbDeTeinte(240f))
    }

    @Test
    fun attenteBlancConfirmeeA100KPres() {
        val prevu = lampe(mode = "color_temp", kelvin = 2700)
        assertTrue(Attentes.conforme(lampe(mode = "color_temp", kelvin = 2750), prevu))
        assertFalse(Attentes.conforme(lampe(mode = "color_temp", kelvin = 3200), prevu))
        // Restée en couleur : la demande de blanc n'a pas été suivie.
        assertFalse(Attentes.conforme(lampe(mode = "hs", teinte = 30f), prevu))
        // Ancienne lecture sans mode ni kelvin : ce qui n'est pas lu ne dément pas.
        assertTrue(Attentes.conforme(lampe(), prevu))
    }

    @Test
    fun attenteCouleurConfirmeeA8DegresPres() {
        val prevu = lampe(mode = "hs", teinte = 0f)
        assertTrue(Attentes.conforme(lampe(mode = "hs", teinte = 354f), prevu))
        assertFalse(Attentes.conforme(lampe(mode = "hs", teinte = 30f), prevu))
        assertFalse(Attentes.conforme(lampe(mode = "color_temp", kelvin = 2700), prevu))
    }

    @Test
    fun attenteLuminositeInchangeeParLeReglage() {
        // Un simple changement d'intensité (sans mode prévu) ne regarde pas la couleur.
        val prevu = lampe(lum = 40)
        assertTrue(Attentes.conforme(lampe(lum = 41, mode = "hs", teinte = 200f), prevu))
        assertFalse(Attentes.conforme(lampe(lum = 80, mode = "hs", teinte = 200f), prevu))
    }

    @Test
    fun actionLueBlancAvecKelvins() {
        val a = action(mapOf("color_temp_kelvin" to "2700"))
        assertTrue(Maison.conforme(a, "on", JSONObject("""{"color_mode":"color_temp","color_temp_kelvin":2790}""")))
        assertFalse(Maison.conforme(a, "on", JSONObject("""{"color_mode":"color_temp","color_temp_kelvin":3100}""")))
        assertFalse(Maison.conforme(a, "on", JSONObject("""{"color_mode":"hs","hs_color":[30,100]}""")))
        // Ancien serveur : aucune information de couleur, la demande n'est pas démentie.
        assertTrue(Maison.conforme(a, "on", JSONObject("""{"brightness":200}""")))
    }

    @Test
    fun actionLueCouleurAvecTeinteEtBouclage() {
        val a = action(mapOf("hs_color" to "[0, 100]"))
        assertTrue(Maison.conforme(a, "on", JSONObject("""{"color_mode":"hs","hs_color":[355,100]}""")))
        assertFalse(Maison.conforme(a, "on", JSONObject("""{"color_mode":"hs","hs_color":[40,100]}""")))
        assertFalse(Maison.conforme(a, "on", JSONObject("""{"color_mode":"color_temp","color_temp_kelvin":2700}""")))
        val rgb = action(mapOf("rgb_color" to "[0, 255, 0]"))
        assertTrue(Maison.conforme(rgb, "on", JSONObject("""{"color_mode":"rgb","rgb_color":[0,250,5]}""")))
        assertFalse(Maison.conforme(rgb, "on", JSONObject("""{"color_mode":"rgb","rgb_color":[255,0,0]}""")))
    }

    @Test
    fun lectureDuModeEtDeLaTeinte() {
        val o = JSONObject("""{"id":"light.x","etat":"on","lum":204,"modes":["color_temp","hs"],"kmin":1801,"kmax":6535,
            "rgb":[255,0,0],"kelvin":null,"hs":[2.5,100.0],"mode":"hs"}""")
        val a = Appareils.lire(o)!!
        assertEquals("hs", a.mode)
        assertEquals(2.5f, a.teinte!!, 0.01f)
        assertNull(a.kelvin)
        // Sans hs_color, la teinte se déduit du rgb.
        val b = Appareils.lire(JSONObject("""{"id":"light.y","etat":"on","rgb":[0,255,0],"mode":"rgb"}"""))!!
        assertEquals(120f, b.teinte!!, 0.5f)
        // Lampe en blanc : ni hs ni rgb, mode color_temp.
        val c = Appareils.lire(JSONObject("""{"id":"light.z","etat":"on","kelvin":2700,"hs":null,"mode":"color_temp"}"""))!!
        assertNull(c.teinte)
        assertEquals("color_temp", c.mode)
        assertEquals(2700, c.kelvin)
    }

    @Test
    fun etatAfficheSousLeNom() {
        assertEquals("allumée, 80 %, 2700 K chaud", MaisonEnGrand.etatLampe("Lampe", lampe(mode = "color_temp", kelvin = 2700)))
        assertEquals("allumée, 80 %, 4000 K neutre", MaisonEnGrand.etatLampe("Lampe", lampe(mode = "color_temp", kelvin = 4000)))
        assertEquals("allumée, 80 %, couleur", MaisonEnGrand.etatLampe("Lampe", lampe(mode = "hs", teinte = 120f)))
        assertEquals("allumée, 80 %", MaisonEnGrand.etatLampe("Lampe", lampe()))
        assertEquals("éteinte", MaisonEnGrand.etatLampe("Lampe", lampe(etat = "off", mode = "color_temp", kelvin = 2700)))
        assertEquals("bougie", ReglageLampe.mot(2200))
        assertEquals("froid", ReglageLampe.mot(6000))
    }

    @Test
    fun cadenceDuBlancUneValeurParIntervalle() {
        val c = Cadence(300L)
        val a = lampe(kmin = 2202, kmax = 6535)
        assertEquals(2202, c.bouge(ReglageLampe.kelvinDe(a, 0f), 1000L))
        assertNull(c.bouge(ReglageLampe.kelvinDe(a, 0.1f), 1100L))
        assertEquals(3000, c.fin(3000, 1200L))
    }
}
