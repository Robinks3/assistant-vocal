package assistant.vocal.jarvis

import org.junit.After
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Jeux de couleurs (0.19.0, revue design des palettes) : valeurs, règles OLED, choix et mode Selon l'heure. */
class PaletteTest {

    @After
    fun remettreSobre() {
        Palette.choisir("Sobre")
        Palette.reglerJour(true)
    }

    @Test
    fun quatreJeuxAuxValeursDeLaRevue() {
        assertEquals(listOf("Sobre", "Pastels", "Méditerranée", "Veillée"), Palette.JEUX.map { it.nom })
        assertEquals(listOf("Sobre", "Pastels", "Méditerranée", "Veillée", "Selon l'heure"), Palette.CHOIX)
        // Palette plus contrastée du 22/10/2026 (PALETTES de docs/maquettes/palettes.py).
        val p = Palette.PASTELS
        assertEquals(
            listOf("#EEEAE2", "#BAB2A6", "#989288", "#B7B1A6", "#23211D", "#3F3C37", "#504E48",
                "#8CB1F4", "#F7B56A", "#80CBE0", "#82C0D5", "#F89DAD", "#98D9B2", "#EDD198", "#6D6861"),
            listOf(p.texte1, p.texte2, p.texte3, p.heure, p.surface, p.filet, p.barre,
                p.assistant, p.lumiere, p.meteo, p.pluie, p.musique, p.sante, p.soleil, p.colonne).map { Palette.hex(it) },
        )
        assertEquals("#ABB2BB", Palette.hex(Palette.SOBRE.heure))
        assertEquals("#D89C67", Palette.hex(Palette.VEILLEE.lumiere))
        assertEquals("#F7C066", Palette.hex(Palette.MEDITERRANEE.lumiere))
    }

    /** Rapport de contraste WCAG sur le noir pur (fond OLED), comme rapport() de docs/maquettes/palettes.py. */
    private fun rapport(couleur: Int): Double = (Palette.luminance(couleur) + 0.05) / 0.05

    @Test
    fun contrasteDesPhrasesEtPlafondsOled() {
        for (j in Palette.JEUX) {
            // L'heure n'est jamais plus claire que texte2 (graisse fine, toujours au même endroit).
            assertTrue(j.nom, rapport(j.heure) <= rapport(j.texte2))
            // Les accents des phrases se lisent au moins aussi bien que le texte secondaire qui les porte.
            val accents = mapOf("meteo" to j.meteo, "pluie" to j.pluie, "musique" to j.musique, "sante" to j.sante, "lumiere" to j.lumiere)
            for ((role, v) in accents) assertTrue("${j.nom}, $role", rapport(v) >= rapport(j.texte2))
            // Texte à 18:1 au plus, au dixième près comme dans la revue (Méditerranée à 18,03:1), jamais blanc pur.
            assertTrue(j.nom, rapport(j.texte1) < 18.05)
            assertTrue(j.nom, Palette.hex(j.texte1) != "#FFFFFF")
            // Surfaces à 1,35:1 au plus.
            assertTrue(j.nom, rapport(j.surface) <= 1.35)
        }
    }

    @Test
    fun commandesEteintesAuGrisColonne() {
        for (j in Palette.JEUX) {
            Palette.choisir(j.nom)
            assertEquals(j.nom, j.colonne, Palette.texteEteint)
            // Encore lisible (3:1 au moins), mais nettement sous le tertiaire.
            assertTrue(j.nom, rapport(Palette.texteEteint) >= 3.0)
            assertTrue(j.nom, rapport(Palette.texteEteint) < rapport(j.texte3))
        }
    }

    @Test
    fun sobreParDefautEtValeursDeLaVersionPrecedenteAilleurs() {
        assertEquals("Sobre", Palette.jeu.nom)
        // Écrans Maison, Musique et Réglages : Sobre garde exactement les couleurs de la 0.18.1.
        assertEquals("#E8EAED", Palette.hex(Palette.texteReglages))
        assertEquals("#4C8DFF", Palette.hex(Palette.accentReglages))
        assertEquals("#FFC857", Palette.hex(Palette.ambreMaison))
        assertEquals("#161616", Palette.hex(Palette.tuileEteinte))
        assertEquals("#5E6878", Palette.hex(Palette.aodHeure))
        assertEquals("#FFA757", Palette.plan3d["lumiere"])
    }

    @Test
    fun lHeureNeDepassePasSaTeinteEtLAodResteSombre() {
        for (j in Palette.JEUX) {
            Palette.choisir(j.nom)
            // L'heure reste à la teinte heure du jeu, de luminance basse : sous celle du texte principal.
            assertEquals(j.heure, Palette.heure)
            assertTrue(j.nom, Palette.luminance(Palette.heure) < Palette.luminance(j.texte1))
            // AOD : jamais plus lumineux que les gris d'aujourd'hui.
            assertTrue(j.nom, Palette.luminance(Palette.aodHeure) <= Palette.luminance(Palette.c("#5E6878")) + 1e-9)
            assertTrue(j.nom, Palette.luminance(Palette.aodTexte) <= Palette.luminance(Palette.c("#4A5362")) + 1e-9)
            // Un texte blanc se lit toujours sur l'accent des réglages.
            assertTrue(j.nom, Palette.luminance(Palette.accentReglages) <= Palette.luminance(Palette.c("#4C8DFF")) + 1e-9)
        }
    }

    @Test
    fun choixParNomEtSuivant() {
        assertTrue(Palette.choisir("mediterranee"))
        assertEquals("Méditerranée", Palette.jeu.nom)
        assertFalse(Palette.choisir("Aurore"))
        assertEquals("Méditerranée", Palette.choix)
        assertNull(Palette.jeu("Crépuscule"))
        assertEquals("Veillée", Palette.suivant("Méditerranée"))
        assertEquals("Selon l'heure", Palette.suivant("Veillée"))
        assertEquals("Sobre", Palette.suivant("Selon l'heure"))
    }

    @Test
    fun selonLHeurePastelsLeJourVeilleeLaNuit() {
        Palette.reglerJour(true)
        assertTrue(Palette.choisir("Selon l'heure"))
        assertEquals("Pastels", Palette.jeu.nom)
        assertTrue(Palette.reglerJour(false))
        assertEquals("Veillée", Palette.jeu.nom)
        assertFalse(Palette.reglerJour(false))
        // Hors du mode automatique, le soleil ne change rien.
        Palette.choisir("Sobre")
        assertFalse(Palette.reglerJour(true))
        assertEquals("Sobre", Palette.jeu.nom)
    }

    @Test
    fun outilsDeCouleur() {
        assertEquals("#FFFFFF", Palette.hex(Palette.melange(Palette.c("#000000"), Palette.c("#FFFFFF"), 1f)))
        val p = Palette.plafonner(Palette.c("#FFFFFF"), 0.2)
        assertEquals(0.2, Palette.luminance(p), 0.01)
        // Un blanc chaud de 2 700 K tire vers l'ambre, 6 500 K vers le blanc.
        val chaud = Palette.kelvin(2700)
        assertTrue(((chaud shr 16) and 0xFF) > (chaud and 0xFF) + 80)
        val froid = Palette.kelvin(6500)
        assertTrue((froid and 0xFF) > 230)
    }
}
