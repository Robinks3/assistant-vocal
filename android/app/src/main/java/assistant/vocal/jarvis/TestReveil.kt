package assistant.vocal.jarvis

import android.content.Context
import android.os.SystemClock
import android.util.Log
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Banc du mot de réveil local, sans micro : passe des WAV (16 kHz, mono, 16 bits) dans
 * ReveilLocal et écrit dans logcat (étiquette JarvisReveil) le score maximal, le bloc où il
 * tombe et le temps de calcul par bloc. Les WAV sont déposés par adb dans
 * /sdcard/Android/data/assistant.vocal.jarvis/files/, puis :
 *   adb shell am start -n assistant.vocal.jarvis/.MainActivity --es test_reveil positif.wav,negatif.wav
 */
object TestReveil {
    private const val TAG = "JarvisReveil"

    fun lancer(contexte: Context, fichiers: String) {
        Thread({
            try {
                for ((fils, xnn) in listOf(1 to true)) ReveilLocal(contexte, fils, xnn).use { r ->
                    Log.i(TAG, "réglage : $fils fil(s), XNNPACK $xnn")
                    for (nom in fichiers.split(",").map { it.trim() }.filter { it.isNotEmpty() }) {
                        val f = File(contexte.getExternalFilesDir(null), nom)
                        val octets = f.readBytes()
                        val pcm = ByteBuffer.wrap(octets, 44, octets.size - 44).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
                        r.reinitialiser()
                        r.chrono.fill(0)
                        var max = 0f
                        var ouMax = -1
                        var n = 0
                        val bloc = ShortArray(ReveilLocal.BLOC)
                        val debut = SystemClock.elapsedRealtimeNanos()
                        while (pcm.remaining() >= ReveilLocal.BLOC) {
                            pcm.get(bloc)
                            val s = r.bloc(bloc)
                            if (s > max) {
                                max = s
                                ouMax = n
                            }
                            n++
                        }
                        val ms = (SystemClock.elapsedRealtimeNanos() - debut) / 1e6 / maxOf(n, 1)
                        val c = r.chrono.map { it / 1e6 / maxOf(n, 1) }
                        Log.i(TAG, "$nom : score max %.3f au bloc %d sur %d, %.1f ms par bloc de 80 ms (mel %.1f, plongement %.1f, modèle %.1f)"
                            .format(max, ouMax, n, ms, c[0], c[1], c[2]))
                    }
                }
            } catch (e: Exception) {
                Log.e(TAG, "Banc impossible", e)
            }
        }, "jarvis-test-reveil").start()
    }
}
