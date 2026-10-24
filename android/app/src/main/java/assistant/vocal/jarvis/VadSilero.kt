package assistant.vocal.jarvis

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import java.nio.FloatBuffer
import java.nio.LongBuffer

/**
 * Détection de parole Silero VAD v5 (ONNX, licence MIT, github.com/snakers4/silero-vad v5.1.2),
 * même calcul que poc/vad.py côté serveur. Remplace le seuil d'énergie du mode « Cet appareil » :
 * la télé, un bip ou un souffle ne passent plus pour de la parole, et la fin de phrase arrive plus tôt.
 *
 * Le modèle travaille par fenêtres de 512 échantillons à 16 kHz (32 ms), précédées des 64 derniers
 * échantillons de la fenêtre d'avant, avec un état récurrent [2, 1, 128] gardé entre deux appels.
 * Deux seuils : 0,5 pour dire que la parole commence, 0,35 pour dire qu'elle s'est arrêtée.
 * Un objet par flux de micro, appelé depuis un seul fil.
 */
class VadSilero(contexte: Context) : AutoCloseable {

    private val env = OrtEnvironment.getEnvironment()
    private val options = OrtSession.SessionOptions().apply {
        setInterOpNumThreads(1)
        setIntraOpNumThreads(1)
    }
    private val session: OrtSession = env.createSession(
        contexte.assets.open("vad/silero_vad.onnx").use { it.readBytes() }, options,
    )

    private var etat = FloatArray(2 * 128)
    private val contexteAudio = FloatArray(CONTEXTE)
    private val reste = FloatArray(FENETRE)
    private var nReste = 0
    private val entree = FloatArray(CONTEXTE + FENETRE)

    /** Vrai si on est dans la parole à la fin du dernier bloc analysé. */
    var parle = false
        private set

    /** Dernière probabilité calculée, pour le déroulé. */
    var derniere = 0f
        private set

    init {
        reinitialiser()
    }

    fun reinitialiser() {
        etat.fill(0f)
        contexteAudio.fill(0f)
        nReste = 0
        parle = false
        derniere = 0f
    }

    /** Probabilité de chaque fenêtre complète de 32 ms du bloc (le reste attend le bloc suivant). */
    fun probabilites(bloc: ShortArray): List<Float> {
        val sorties = ArrayList<Float>(3)
        for (s in bloc) {
            reste[nReste++] = s / 32768f
            if (nReste == FENETRE) {
                sorties.add(fenetre())
                nReste = 0
            }
        }
        return sorties
    }

    private fun fenetre(): Float {
        System.arraycopy(contexteAudio, 0, entree, 0, CONTEXTE)
        System.arraycopy(reste, 0, entree, CONTEXTE, FENETRE)
        val p = OnnxTensor.createTensor(env, FloatBuffer.wrap(entree), longArrayOf(1, (CONTEXTE + FENETRE).toLong())).use { x ->
            OnnxTensor.createTensor(env, FloatBuffer.wrap(etat), longArrayOf(2, 1, 128)).use { h ->
                OnnxTensor.createTensor(env, LongBuffer.wrap(longArrayOf(TAUX)), LongArray(0)).use { sr ->
                    session.run(mapOf("input" to x, "state" to h, "sr" to sr)).use { r ->
                        @Suppress("UNCHECKED_CAST")
                        val sortie = (r.get("output").get().value as Array<FloatArray>)[0][0]
                        @Suppress("UNCHECKED_CAST")
                        val nouvel = r.get("stateN").get().value as Array<Array<FloatArray>>
                        var k = 0
                        for (a in nouvel) for (b in a) for (v in b) etat[k++] = v
                        sortie
                    }
                }
            }
        }
        System.arraycopy(reste, FENETRE - CONTEXTE, contexteAudio, 0, CONTEXTE)
        derniere = p
        return p
    }

    /** Vrai si on est dans la parole à la fin de ce bloc (hystérésis entre les deux seuils). */
    fun parole(bloc: ShortArray): Boolean {
        for (p in probabilites(bloc)) {
            parle = if (parle) p >= SEUIL_FIN else p >= SEUIL_DEBUT
        }
        return parle
    }

    override fun close() {
        session.close()
        options.close()
    }

    companion object {
        const val FENETRE = 512
        const val CONTEXTE = 64
        private const val TAUX = 16000L
        const val SEUIL_DEBUT = 0.5f
        const val SEUIL_FIN = 0.35f
    }
}
