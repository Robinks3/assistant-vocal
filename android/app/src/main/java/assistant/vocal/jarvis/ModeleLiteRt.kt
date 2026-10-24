package assistant.vocal.jarvis

import android.content.Context
import android.util.Log
import com.google.ai.edge.litertlm.Backend
import com.google.ai.edge.litertlm.Content
import com.google.ai.edge.litertlm.Contents
import com.google.ai.edge.litertlm.Message
import com.google.ai.edge.litertlm.ConversationConfig
import com.google.ai.edge.litertlm.Engine
import com.google.ai.edge.litertlm.EngineConfig
import com.google.ai.edge.litertlm.ResponseFormat
import com.google.ai.edge.litertlm.SamplerConfig
import com.google.ai.edge.litertlm.ThinkingConfig
import java.io.File

/**
 * Petit LLM sur l'appareil avec LiteRT-LM (Google), modèles .litertlm de Hugging Face
 * litert-community (Apache 2.0) copiés par adb dans Android/data/assistant.vocal.jarvis/files/llm/.
 * Recherche du 13/10/2026 : Gemini Nano (ML Kit Prompt API) n'est pas ouvert aux applis sur le
 * téléphone, et Samsung n'expose aucun LLM. Sortie contrainte au schéma JSON des actions.
 */
class ModeleLiteRt(private val fichier: File, private val gpu: Boolean, cache: File) : ModeleTexte {

    override val nom: String = fichier.nameWithoutExtension + if (gpu) " (GPU)" else " (CPU)"

    private val moteur = Engine(
        EngineConfig(fichier.path, if (gpu) Backend.GPU() else Backend.CPU(4, null), null, null, 4096, null, cache.path)
    ).also { it.initialize() }

    private var formatAccepte = contrainteParDefaut

    override fun generer(systeme: String, exemples: List<Pair<String, String>>, phrase: String): String {
        if (formatAccepte) {
            try {
                return envoyer(systeme, exemples, phrase, true)
            } catch (e: Exception) {
                // Certains modèles n'acceptent pas la sortie contrainte : on garde le JSON demandé dans le prompt.
                Log.w(TAG, "Sortie contrainte refusée par $nom, essai sans", e)
                formatAccepte = false
            }
        }
        return envoyer(systeme, exemples, phrase, false)
    }

    private fun envoyer(systeme: String, exemples: List<Pair<String, String>>, phrase: String, contraint: Boolean): String {
        val config = ConversationConfig(
            Contents.of(systeme),
            exemples.flatMap { (q, r) -> listOf(Message.user(q), Message.model(r)) },
            emptyList(),
            SamplerConfig(1, 1.0, 0.0, 0), // glouton : la même phrase donne la même décision
            false, emptyList(), emptyMap(), null, false, 300, ThinkingConfig(false, 0), contraint,
        )
        moteur.createConversation(config).use { c ->
            val reponse = c.sendMessage(
                phrase, emptyMap(), null, null, null, 300, ThinkingConfig(false, 0),
                if (contraint) ResponseFormat.json(SCHEMA) else null,
            )
            return reponse.contents.contents.filterIsInstance<Content.Text>().joinToString("") { it.text }
        }
    }

    override fun close() = moteur.close()

    companion object {
        private const val TAG = "JarvisLlm"

        /** Sortie contrainte au schéma JSON : réglable par le banc pour mesurer son coût. */
        // Coupée par défaut : avec Gemma 4 sur le téléphone elle cassait le JSON (« {"{"actions"... », 13/10/2026).
        @Volatile var contrainteParDefaut = false

        private const val SCHEMA = """{"type":"object","properties":{"actions":{"type":"array","maxItems":3,"items":{"type":"object","properties":{"service":{"type":"string"},"entity_id":{"type":"string"},"donnees":{"type":"object"}},"required":["service","entity_id"]}},"reponse":{"type":"string"}},"required":["actions","reponse"]}"""

        fun dossier(contexte: Context): File = File(contexte.getExternalFilesDir(null), "llm")

        /** Modèles reconnus, du préféré au plus léger, et s'ils tournent sur le GPU. */
        private val PREFERENCES = listOf(
            "gemma-4-E2B-it-gpu.litertlm" to true,
            "gemma-4-E2B-it.litertlm" to false,
            "Qwen2.5-1.5B-Instruct_multi-prefill-seq_q8_ekv4096.litertlm" to false,
            "qwen3_0.6b_nothink_q4_block32_ekv1280.litertlm" to false,
        )

        /** Premier modèle présent sur l'appareil, ou celui demandé par son nom de fichier. */
        fun choisir(contexte: Context, demande: String? = null): Pair<File, Boolean>? {
            val d = dossier(contexte)
            if (demande != null) {
                val f = File(d, demande)
                return if (f.length() > 0) f to demande.contains("-gpu") else null
            }
            return PREFERENCES.map { (n, g) -> File(d, n) to g }.firstOrNull { it.first.length() > 0 }
        }

        fun charger(contexte: Context, demande: String? = null): ModeleLiteRt? {
            val (f, g) = choisir(contexte, demande) ?: return null
            val cache = File(contexte.cacheDir, "litertlm").apply { mkdirs() }
            return ModeleLiteRt(f, g, cache)
        }
    }
}
