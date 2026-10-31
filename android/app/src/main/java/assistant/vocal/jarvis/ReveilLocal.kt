package assistant.vocal.jarvis

import ai.onnxruntime.OnnxTensor
import ai.onnxruntime.OrtEnvironment
import ai.onnxruntime.OrtSession
import android.content.Context
import java.nio.FloatBuffer
import kotlin.random.Random

/**
 * Mot de réveil calculé sur le téléphone, avec les trois modèles ONNX d'openWakeWord
 * (assets/reveil). Depuis la 0.15.0, le dernier modèle est au choix : « Hey Jarvis » (anglais,
 * openWakeWord) ou le mot de la configuration ([PERSO], section reveil de maison.json, modèle et
 * licence rangés dans assets/reveil/ à la compilation). Les deux prennent 16 plongements de 96 valeurs. Reprise fidèle de openwakeword.Model.predict pour des
 * blocs de 1280 échantillons (80 ms à 16 kHz) : les scores sont identiques à ceux du
 * serveur (0,998 et 0,001 au même bloc sur les deux WAV de android/test-reveil, PC et tablette).
 *
 * Chaîne par bloc : spectrogramme mel des 1760 derniers échantillons (8 trames de 32
 * bandes, transformées en x/10 + 2), plongement des 76 dernières trames (96 valeurs),
 * puis modèle hey_jarvis sur les 16 derniers plongements (1,28 s de son).
 *
 * Coût mesuré sur la tablette le 12/10/2026, par bloc de 80 ms : 35 ms sur un
 * fil sans XNNPACK, 25 ms sur un fil avec (réglage retenu, un seul cœur occupé), 16 ms sur deux
 * fils avec. Le plongement pèse les deux tiers du temps.
 */
class ReveilLocal(
    contexte: Context,
    fils: Int = 1,
    xnnpack: Boolean = true,
    /** [HEY_JARVIS] ou [PERSO]. */
    val mot: String = HEY_JARVIS,
) : AutoCloseable {

    private val env = OrtEnvironment.getEnvironment()
    private val options = OrtSession.SessionOptions().apply {
        setInterOpNumThreads(1)
        if (xnnpack) {
            // XNNPACK gère lui-même ses fils, ONNX Runtime doit alors rester sur un seul.
            setIntraOpNumThreads(1)
            addXnnpack(mapOf("intra_op_num_threads" to fils.toString()))
        } else {
            setIntraOpNumThreads(fils)
        }
    }
    private val mel = session(contexte, "melspectrogram.onnx")
    private val plongement = session(contexte, "embedding_model.onnx")
    private val modele = session(contexte, fichier(mot))

    private val brut = FloatArray(BRUT_MAX)
    private var nBrut = 0
    private val mels = ArrayDeque<FloatArray>()
    private val traits = ArrayDeque<FloatArray>()
    private var nPredictions = 0
    /** Temps cumulés (ns) du spectrogramme, du plongement et du modèle, pour le banc. */
    val chrono = LongArray(3)

    init {
        reinitialiser()
    }

    private fun session(contexte: Context, nom: String): OrtSession {
        val octets = contexte.assets.open("reveil/$nom").use { it.readBytes() }
        return env.createSession(octets, options)
    }

    /** Remet les tampons dans l'état d'un modèle neuf, comme openwakeword.Model.reset(). */
    fun reinitialiser() {
        nBrut = 0
        mels.clear()
        repeat(76) { mels.addLast(FloatArray(32) { 1f }) }
        // openWakeWord amorce ses plongements avec 4 s de bruit aléatoire.
        traits.clear()
        val bruit = FloatArray(64000) { (Random.nextInt(-1000, 1000)).toFloat() }
        val m = spectrogramme(bruit, bruit.size)
        var i = 0
        while (i + 76 <= m.size) {
            traits.addLast(plonger(m.subList(i, i + 76)))
            i += 8
        }
        while (traits.size > TRAITS_MAX) traits.removeFirst()
        nPredictions = 0
    }

    /** Score de 0 à 1 pour un bloc de 1280 échantillons PCM 16 bits. */
    fun bloc(echantillons: ShortArray): Float {
        require(echantillons.size == BLOC)
        // Tampon brut : on garde les 1760 derniers échantillons (480 de recouvrement).
        val n = echantillons.size
        if (nBrut + n > BRUT_MAX) {
            val garder = BRUT_MAX - n
            System.arraycopy(brut, nBrut - garder, brut, 0, garder)
            nBrut = garder
        }
        for (k in 0 until n) brut[nBrut + k] = echantillons[k].toFloat()
        nBrut += n

        var t0 = System.nanoTime()
        for (trame in spectrogramme(brut, nBrut)) mels.addLast(trame)
        chrono[0] += System.nanoTime() - t0
        t0 = System.nanoTime()
        while (mels.size > MELS_MAX) mels.removeFirst()

        traits.addLast(plonger(mels.subList(mels.size - 76, mels.size)))
        while (traits.size > TRAITS_MAX) traits.removeFirst()
        chrono[1] += System.nanoTime() - t0
        t0 = System.nanoTime()

        val entree = FloatBuffer.allocate(16 * 96)
        for (t in traits.subList(traits.size - 16, traits.size)) entree.put(t)
        entree.rewind()
        val score = OnnxTensor.createTensor(env, entree, longArrayOf(1, 16, 96)).use { x ->
            modele.run(mapOf(modele.inputNames.first() to x)).use { r ->
                @Suppress("UNCHECKED_CAST")
                (r[0].value as Array<FloatArray>)[0][0]
            }
        }
        chrono[2] += System.nanoTime() - t0
        nPredictions++
        // Comme openWakeWord : les 5 premières prédictions sont forcées à zéro.
        return if (nPredictions <= 5) 0f else score
    }

    private fun spectrogramme(x: FloatArray, longueur: Int): List<FloatArray> {
        val entree = FloatBuffer.wrap(x, 0, longueur).slice()
        return OnnxTensor.createTensor(env, entree, longArrayOf(1, longueur.toLong())).use { t ->
            mel.run(mapOf("input" to t)).use { r ->
                // Sortie [trames, 1, n, 32] : on aplatit vers une liste de trames de 32 bandes.
                @Suppress("UNCHECKED_CAST")
                val brute = r[0].value as Array<Array<Array<FloatArray>>>
                val sortie = ArrayList<FloatArray>()
                for (a in brute) for (b in a) for (trame in b) {
                    sortie.add(FloatArray(32) { trame[it] / 10f + 2f })
                }
                sortie
            }
        }
    }

    private fun plonger(fenetre: List<FloatArray>): FloatArray {
        val entree = FloatBuffer.allocate(76 * 32)
        for (trame in fenetre) entree.put(trame)
        entree.rewind()
        return OnnxTensor.createTensor(env, entree, longArrayOf(1, 76, 32, 1)).use { t ->
            plongement.run(mapOf("input_1" to t)).use { r ->
                @Suppress("UNCHECKED_CAST")
                (r[0].value as Array<Array<Array<FloatArray>>>)[0][0][0].copyOf()
            }
        }
    }

    override fun close() {
        mel.close()
        plongement.close()
        modele.close()
        options.close()
    }

    companion object {
        const val HEY_JARVIS = "hey_jarvis"
        /** Mot de réveil de la configuration (section reveil de maison.json, modèle reveil/<mot>.onnx rangé dans les
         *  assets par build.gradle.kts). Une valeur enregistrée
         *  par une version précédente, autre que HEY_JARVIS, est lue comme PERSO (SatelliteService.motReveilChoisi). */
        const val PERSO = "perso"
        const val BLOC = 1280

        private val REVEIL = ConfigMaison.section("reveil")
        private val MOT_PERSO: String = REVEIL.optString("mot").trim().lowercase()
        /** Vrai quand la configuration fournit son mot de réveil : sinon seul Hey Jarvis existe. */
        val PERSO_DISPONIBLE: Boolean = MOT_PERSO.isNotEmpty()
        /** Langue et licence du mot de réveil de la configuration, affichées dans les réglages. */
        val LANGUE_PERSO: String = REVEIL.optString("langue")
        val LICENCE_PERSO: String = REVEIL.optString("licence")

        fun fichier(mot: String): String = if (mot == PERSO && PERSO_DISPONIBLE) "$MOT_PERSO.onnx" else "hey_jarvis_v0.1.onnx"

        /** Nom affiché du mot de réveil. */
        fun nom(mot: String): String =
            if (mot == PERSO && PERSO_DISPONIBLE) REVEIL.optString("nom").ifEmpty { MOT_PERSO.replaceFirstChar { it.uppercase() } }
            else "Hey Jarvis"
        private const val BRUT_MAX = BLOC + 160 * 3
        private const val MELS_MAX = 10 * 97
        private const val TRAITS_MAX = 120
    }
}
