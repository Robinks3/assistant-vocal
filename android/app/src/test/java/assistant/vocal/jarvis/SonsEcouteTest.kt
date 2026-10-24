package assistant.vocal.jarvis

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import kotlin.math.pow
import kotlin.math.sqrt

/** Sons d'écoute (0.23.0) : les 16 fichiers de res/raw, leur format, leur fin audible et la version de nuit. */
class SonsEcouteTest {

    private class Wav(val taux: Int, val canaux: Int, val bits: Int, val echantillons: ShortArray) {
        val rms get() = sqrt(echantillons.sumOf { it.toDouble() * it } / echantillons.size)

        /** Fin de la dernière fenêtre de 10 ms au-dessus de [seuilDb] dBFS. */
        fun finAudibleMs(seuilDb: Double): Long {
            val n = taux / 100
            val limite = 32768.0 * 10.0.pow(seuilDb / 20)
            var fin = 0L
            for (k in 0 until echantillons.size / n) {
                var somme = 0.0
                for (i in k * n until (k + 1) * n) somme += echantillons[i].toDouble() * echantillons[i]
                if (sqrt(somme / n) > limite) fin = (k + 1) * 10L
            }
            return fin
        }
    }

    /** Dossier cherché en remontant depuis le dossier de travail (module app en général). */
    private val raw: File by lazy {
        var dossier: File? = File(System.getProperty("user.dir") ?: ".").absoluteFile
        while (dossier != null) {
            for (chemin in listOf("src/main/res/raw", "app/src/main/res/raw")) {
                val f = File(dossier, chemin)
                if (f.isDirectory) return@lazy f
            }
            dossier = dossier.parentFile
        }
        error("res/raw introuvable depuis ${System.getProperty("user.dir")}")
    }

    /** RIFF lu bloc par bloc : la série 2.0.0 range un bloc LIST INFO après les données. */
    private fun lire(nom: String): Wav {
        val f = File(raw, "$nom.wav")
        assertTrue("$nom absent", f.isFile)
        val b = ByteBuffer.wrap(f.readBytes()).order(ByteOrder.LITTLE_ENDIAN)
        assertEquals("RIFF", String(ByteArray(4).also { b.get(it) }))
        b.getInt()
        assertEquals("WAVE", String(ByteArray(4).also { b.get(it) }))
        var format = 0
        var canaux = 0
        var taux = 0
        var bits = 0
        var donnees: ShortArray? = null
        while (b.remaining() >= 8) {
            val id = String(ByteArray(4).also { b.get(it) })
            val taille = b.getInt()
            val debut = b.position()
            when (id) {
                "fmt " -> {
                    format = b.getShort().toInt()
                    canaux = b.getShort().toInt()
                    taux = b.getInt()
                    b.getInt()
                    b.getShort()
                    bits = b.getShort().toInt()
                }
                "data" -> donnees = ShortArray(taille / 2).also { b.asShortBuffer().get(it) }
            }
            b.position(debut + taille + (taille and 1))
        }
        assertEquals("$nom : PCM", 1, format)
        return Wav(taux, canaux, bits, donnees ?: error("$nom sans données"))
    }

    @Test
    fun seizeFichiersAuBonFormat() {
        val attendus = mutableSetOf<String>()
        for (p in SonsEcoute.PAIRES) for (son in SonsEcoute.Son.values()) for (nuit in listOf(false, true)) {
            val nom = SonsEcoute.fichier(p.nom, son, nuit)
            attendus += nom
            val w = lire(nom)
            // 48 kHz mono 16 bits : le format natif de la sortie, SoundPool n'a rien à convertir.
            assertEquals(nom, 48_000, w.taux)
            assertEquals(nom, 1, w.canaux)
            assertEquals(nom, 16, w.bits)
            assertTrue(nom, w.echantillons.isNotEmpty())
        }
        // Une paire oubliée dans la table des ressources resterait muette.
        assertEquals(attendus, SonsEcoute.RESSOURCES.keys)
        assertTrue(SonsEcoute.PAIRES.any { it.nom == SonsEcoute.PAIRE_DEFAUT })
    }

    @Test
    fun finAudibleDuDebutConnue() {
        // La fenêtre sourde de chaque paire en dépend (SonsEcoute.dureeSourdeMs) : la valeur écrite dans le
        // code doit couvrir le fichier, sans le surestimer de plus de 30 ms.
        assertEquals(SonsEcoute.PAIRES.map { it.nom }.toSet(), SonsEcoute.FIN_AUDIBLE_DEBUT_MS.keys)
        for (p in SonsEcoute.PAIRES) {
            val mesure = lire(SonsEcoute.fichier(p.nom, SonsEcoute.Son.DEBUT, false)).finAudibleMs(-50.0)
            val ecrit = SonsEcoute.FIN_AUDIBLE_DEBUT_MS.getValue(p.nom)
            assertTrue("${p.nom} : $ecrit ms écrits, $mesure ms mesurés", mesure <= ecrit && ecrit - mesure <= 30)
        }
    }

    @Test
    fun nuitSixDecibelsPlusBas() {
        for (p in SonsEcoute.PAIRES) for (son in SonsEcoute.Son.values()) {
            val jour = lire(SonsEcoute.fichier(p.nom, son, false))
            val nuit = lire(SonsEcoute.fichier(p.nom, son, true))
            assertEquals(jour.echantillons.size, nuit.echantillons.size)
            // -6 dB : la moitié de l'amplitude, à l'arrondi près.
            val rapport = nuit.rms / jour.rms
            assertTrue("${p.nom} $son : rapport $rapport", rapport in 0.47..0.53)
        }
    }
}
