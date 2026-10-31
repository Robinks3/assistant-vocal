package assistant.vocal.jarvis

import android.content.Context
import android.os.SystemClock
import android.util.Log
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder

/**
 * Banc de Canary sur le téléphone, sans micro : charge le modèle déposé par adb dans
 * /sdcard/Android/data/<application_id>/files/canary/ et transcrit des WAV (16 kHz, mono, 16 bits)
 * du dossier files/. Résultats dans logcat, étiquette JarvisCanary :
 *   adb shell am start -n <application_id>/assistant.vocal.jarvis.MainActivity --es test_canary a.wav,b.wav
 */
object TestCanary {
    private const val TAG = "JarvisCanary"

    fun lancer(contexte: Context, fichiers: String, fils: Int) {
        Thread({
            try {
                val t0 = SystemClock.elapsedRealtime()
                CanaryLocal(CanaryLocal.dossierModele(contexte), fils).use { c ->
                    Log.i(TAG, "modèle chargé en ${SystemClock.elapsedRealtime() - t0} ms, $fils fils (${c.chargements.joinToString(", ")})")
                    for (nom in fichiers.split(",").map { it.trim() }.filter { it.isNotEmpty() }) {
                        val octets = File(contexte.getExternalFilesDir(null), nom).readBytes()
                        val sb = ByteBuffer.wrap(octets, 44, octets.size - 44).order(ByteOrder.LITTLE_ENDIAN).asShortBuffer()
                        val pcm = ShortArray(sb.remaining()).also { sb.get(it) }
                        val r = c.transcrire(pcm)
                        Log.i(TAG, "$nom (%.1f s) : « %s » en %d ms (préparation %d, encodeur %d, décodeur %d pour %d jetons)".format(
                            pcm.size / 16000.0, r.texte, r.msPreparation + r.msEncodeur + r.msDecodeur,
                            r.msPreparation, r.msEncodeur, r.msDecodeur, r.jetons))
                    }
                }
            } catch (e: Throwable) {
                Log.e(TAG, "Banc impossible", e)
            }
        }, "jarvis-test-canary").start()
    }
}
