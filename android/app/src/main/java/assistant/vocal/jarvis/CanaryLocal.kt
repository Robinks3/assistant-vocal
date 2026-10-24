package assistant.vocal.jarvis

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import java.io.File
import java.nio.FloatBuffer
import java.nio.LongBuffer
import java.util.regex.Pattern

/**
 * Transcription Canary 1B v2 (int8) sur le téléphone, reprise de onnx_asr.models.nemo.NemoConformerAED
 * (recognize(signal, language="fr")) : préprocesseur nemo128 (128 bandes mel), encodeur Conformer,
 * puis décodeur appelé jeton par jeton (décodage glouton) avec les mémoires du décodeur.
 *
 * Fichiers attendus dans [dossier] (copiés par adb, 1,03 Go, trop gros pour l'APK) :
 * nemo128.onnx, encoder-model.int8.onnx, decoder-model.int8.onnx, vocab.txt.
 */
class CanaryLocal(dossier: File, private val fils: Int = 4) : AutoCloseable {

    class Resultat(val texte: String, val msPreparation: Long, val msEncodeur: Long, val msDecodeur: Long, val jetons: Int)

    private val env = OrtEnvironment.getEnvironment()
    /** Durée de chargement de chaque modèle, pour le banc. */
    val chargements = ArrayList<String>()
    private val preparation = session(dossier, "nemo128.onnx")
    private val encodeur = session(dossier, "encoder-model.int8.onnx")
    private val decodeur = session(dossier, "decoder-model.int8.onnx")

    /**
     * Le graphe est optimisé à chaque chargement (12,8 s sur la tablette, 23 s de plus quand le
     * modèle vient d'être copié). Garder la version optimisée sur disque a été essayé le
     * 12/10/2026 : relue sans optimisation, elle montait à 4,9 Go de mémoire et Android tuait l'appli.
     */
    private fun session(dossier: File, nom: String): OrtSession {
        val t0 = System.nanoTime()
        val session = OrtSession.SessionOptions().use { o ->
            o.setIntraOpNumThreads(fils)
            o.setInterOpNumThreads(1)
            o.setOptimizationLevel(OrtSession.SessionOptions.OptLevel.ALL_OPT)
            env.createSession(File(dossier, nom).path, o)
        }
        chargements.add("$nom ${(System.nanoTime() - t0) / 1_000_000} ms")
        return session
    }

    /** Identifiant vers jeton, « ▁ » remplacé par une espace comme dans onnx-asr. */
    private val vocab = HashMap<Int, String>()
    private val ids = HashMap<String, Int>()
    private val finTexte: Int
    private val amorce: LongArray

    init {
        File(dossier, "vocab.txt").forEachLine(Charsets.UTF_8) { ligne ->
            val i = ligne.lastIndexOf(' ')
            if (i > 0) {
                val jeton = ligne.substring(0, i).replace('▁', ' ')
                val id = ligne.substring(i + 1).toInt()
                vocab[id] = jeton
                ids[jeton] = id
            }
        }
        fun id(j: String) = ids[j] ?: error("jeton $j absent de vocab.txt")
        finTexte = id("<|endoftext|>")
        // Amorce de transcription en français, ponctuation et majuscules, sans horodatage.
        amorce = intArrayOf(
            id(" "), id("<|startofcontext|>"), id("<|startoftranscript|>"), id("<|emo:undefined|>"),
            id("<|fr|>"), id("<|fr|>"), id("<|pnc|>"), id("<|noitn|>"), id("<|notimestamp|>"), id("<|nodiarize|>"),
        ).map { it.toLong() }.toLongArray()
    }

    /** Signal PCM 16 bits à 16 kHz vers texte. */
    fun transcrire(pcm: ShortArray, nombre: Int = pcm.size): Resultat {
        val t0 = System.nanoTime()
        val signal = FloatArray(nombre) { pcm[it] / 32768f }
        val (traits, longueurs) = OnnxTensor.createTensor(env, FloatBuffer.wrap(signal), longArrayOf(1, nombre.toLong())).use { w ->
            OnnxTensor.createTensor(env, LongBuffer.wrap(longArrayOf(nombre.toLong())), longArrayOf(1)).use { wl ->
                preparation.run(mapOf("waveforms" to w, "waveforms_lens" to wl)).use { r ->
                    val f = r[0] as OnnxTensor
                    val forme = f.info.shape
                    val copie = FloatBuffer.allocate(f.floatBuffer.remaining()).put(f.floatBuffer)
                    copie.rewind()
                    Pair(OnnxTensor.createTensor(env, copie, forme), (r[1] as OnnxTensor).longBuffer.get(0))
                }
            }
        }
        val t1 = System.nanoTime()
        val sortieEncodeur = traits.use { x ->
            OnnxTensor.createTensor(env, LongBuffer.wrap(longArrayOf(longueurs)), longArrayOf(1)).use { l ->
                encodeur.run(mapOf("audio_signal" to x, "length" to l))
            }
        }
        val t2 = System.nanoTime()
        val jetons = ArrayList<Long>()
        sortieEncodeur.use { enc ->
            val plongements = enc.get("encoder_embeddings").get() as OnnxTensor
            val masque = enc.get("encoder_mask").get() as OnnxTensor
            var memoires: OnnxTensor = OnnxTensor.createTensor(env, FloatBuffer.allocate(0), longArrayOf(10, 1, 0, 1024))
            var resultatPrecedent: OrtSession.Result? = null
            try {
                var entree = amorce
                while (amorce.size + jetons.size < LONGUEUR_MAX) {
                    val r = OnnxTensor.createTensor(env, LongBuffer.wrap(entree), longArrayOf(1, entree.size.toLong())).use { ids ->
                        decodeur.run(
                            mapOf(
                                "input_ids" to ids,
                                "encoder_embeddings" to plongements,
                                "encoder_mask" to masque,
                                "decoder_mems" to memoires,
                            )
                        )
                    }
                    // Les mémoires de l'appel suivant sont les états cachés de celui-ci.
                    if (resultatPrecedent == null) memoires.close() else resultatPrecedent.close()
                    resultatPrecedent = r
                    memoires = r.get("decoder_hidden_states").get() as OnnxTensor
                    val logits = r.get("logits").get() as OnnxTensor
                    val forme = logits.info.shape
                    val taille = forme[2].toInt()
                    val fb = logits.floatBuffer
                    val debut = ((forme[1] - 1) * taille).toInt()
                    var meilleur = 0
                    var max = Float.NEGATIVE_INFINITY
                    for (k in 0 until taille) {
                        val v = fb.get(debut + k)
                        if (v > max) {
                            max = v
                            meilleur = k
                        }
                    }
                    if (meilleur == finTexte) break
                    jetons.add(meilleur.toLong())
                    entree = longArrayOf(meilleur.toLong())
                }
            } finally {
                resultatPrecedent?.close() ?: memoires.close()
            }
        }
        val t3 = System.nanoTime()
        val brut = jetons.map { vocab[it.toInt()] ?: "" }.filter { !it.startsWith("<|") }.joinToString("")
        val m = ESPACES.matcher(brut)
        val tampon = StringBuffer()
        while (m.find()) m.appendReplacement(tampon, if (m.group(1) != null) " " else "")
        m.appendTail(tampon)
        val texte = tampon.toString().trim()
        return Resultat(texte, (t1 - t0) / 1_000_000, (t2 - t1) / 1_000_000, (t3 - t2) / 1_000_000, jetons.size)
    }

    override fun close() {
        preparation.close()
        encodeur.close()
        decodeur.close()
    }

    companion object {
        /** Fichiers à déposer dans le dossier du modèle. */
        val FICHIERS = listOf("nemo128.onnx", "encoder-model.int8.onnx", "decoder-model.int8.onnx", "vocab.txt")
        private const val LONGUEUR_MAX = 256
        /** Même motif que onnx-asr (DECODE_SPACE_PATTERN), \b compris au sens Unicode comme en Python. */
        // Android (ICU) traite déjà \b en Unicode, comme Python, et refuse UNICODE_CHARACTER_CLASS.
        private val ESPACES = Pattern.compile("""\A\s|\s\B|(\s)\b""")

        fun dossierModele(contexte: android.content.Context): File = File(contexte.getExternalFilesDir(null), "canary")

        fun modelePresent(contexte: android.content.Context): Boolean =
            FICHIERS.all { File(dossierModele(contexte), it).length() > 0 }
    }
}
