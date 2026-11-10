package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject
import java.io.File
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale

/**
 * Dossier des captures du mot de réveil (0.53.0), sans rien d'Android : testé hors appareil.
 *
 * Une capture = `capture-AAAAMMJJ-HHMMSS-mmm.wav` (16 kHz, mono, 16 bits) et le `.json` du même nom : les
 * métadonnées passées par l'appelant, plus les tableaux par bloc du tampon (score, Silero, dB, phase).
 * Le nom ne porte pas l'étiquette : elle peut changer après coup ([reetiqueter]).
 *
 * Rétention : au plus [maxCaptures] captures et [maxAgeMs] d'ancienneté, les plus anciennes partent à
 * chaque écriture ([purger]).
 */
class ArchiveCaptures(
    val dossier: File,
    val maxCaptures: Int = MAX_CAPTURES,
    val maxAgeMs: Long = MAX_AGE_MS,
) {

    /** Écrit le son puis le JSON (le JSON en dernier : une capture sans JSON est incomplète). */
    fun ecrire(nom: String, inst: TamponReveil.Instantane, meta: JSONObject, maintenant: Long = System.currentTimeMillis()) {
        dossier.mkdirs()
        ecrireAtomique(File(dossier, "$nom.wav"), wav(inst.pcm, TAUX))
        val j = JSONObject(meta.toString())
            .put("taux", TAUX)
            .put("bloc", inst.pcm.size / maxOf(1, inst.blocs))
            .put("blocs", inst.blocs)
            .put("scores", tableau(inst.scores))
            .put("vad", tableau(inst.vad))
            .put("db", tableau(inst.db))
            .put("phases", inst.phases)
        ecrireAtomique(File(dossier, "$nom.json"), j.toString().toByteArray(Charsets.UTF_8))
        purger(maintenant)
    }

    /** Change l'étiquette et ajoute des champs à une capture déjà écrite. Faux si elle n'existe plus. */
    fun reetiqueter(nom: String, champs: Map<String, Any?>): Boolean {
        val f = File(dossier, "$nom.json")
        if (!f.exists()) return false
        val j = JSONObject(f.readText(Charsets.UTF_8))
        for ((k, v) in champs) j.put(k, v ?: JSONObject.NULL)
        ecrireAtomique(f, j.toString().toByteArray(Charsets.UTF_8))
        return true
    }

    fun lire(nom: String): JSONObject? {
        val f = File(dossier, "$nom.json")
        return if (f.exists()) JSONObject(f.readText(Charsets.UTF_8)) else null
    }

    /** Noms des captures (sans extension), du plus ancien au plus récent. */
    fun noms(): List<String> =
        (dossier.listFiles() ?: emptyArray())
            .mapNotNull { f -> f.name.takeIf { it.startsWith(PREFIXE) }?.substringBeforeLast('.') }
            .distinct()
            .sorted()

    /** Supprime ce qui dépasse la rétention. Rend le nombre de captures supprimées. */
    fun purger(maintenant: Long = System.currentTimeMillis()): Int {
        val partir = aPurger(noms(), maintenant, maxCaptures, maxAgeMs)
        for (n in partir) supprimer(n)
        return partir.size
    }

    /** Efface toutes les captures. Rend leur nombre. */
    fun effacer(): Int {
        val tout = noms()
        for (n in tout) supprimer(n)
        (dossier.listFiles() ?: emptyArray()).filter { it.name.endsWith(".tmp") }.forEach { it.delete() }
        return tout.size
    }

    /** Nombre de captures et place prise en octets. */
    fun bilan(): Pair<Int, Long> {
        val fichiers = (dossier.listFiles() ?: emptyArray()).filter { it.name.startsWith(PREFIXE) }
        return fichiers.map { it.name.substringBeforeLast('.') }.distinct().size to fichiers.sumOf { it.length() }
    }

    private fun supprimer(nom: String) {
        for (ext in listOf("json", "wav")) File(dossier, "$nom.$ext").delete()
    }

    private fun ecrireAtomique(f: File, octets: ByteArray) {
        val tmp = File(f.parentFile, f.name + ".tmp")
        tmp.writeBytes(octets)
        if (!tmp.renameTo(f)) {
            f.delete()
            if (!tmp.renameTo(f)) {
                tmp.delete()
                throw java.io.IOException("écriture impossible : ${f.name}")
            }
        }
    }

    companion object {
        const val TAUX = 16000
        const val PREFIXE = "capture-"
        const val MAX_CAPTURES = 200
        const val MAX_AGE_MS = 14L * 24 * 3600 * 1000
        private const val MOTIF = "yyyyMMdd-HHmmss-SSS"

        fun nom(instant: Long): String = PREFIXE + SimpleDateFormat(MOTIF, Locale.ROOT).format(Date(instant))

        /** Instant d'une capture d'après son nom, ou null pour un nom illisible. */
        fun instant(nom: String): Long? = try {
            SimpleDateFormat(MOTIF, Locale.ROOT).apply { isLenient = false }.parse(nom.removePrefix(PREFIXE))?.time
        } catch (_: Exception) {
            null
        }

        /** Captures à supprimer : trop vieilles, puis les plus anciennes au-delà de [max]. Noms illisibles gardés. */
        fun aPurger(noms: List<String>, maintenant: Long, max: Int, maxAgeMs: Long): List<String> {
            val tries = noms.sorted()
            val vieilles = tries.filter { n -> instant(n)?.let { maintenant - it > maxAgeMs } == true }
            val restent = tries - vieilles.toSet()
            val enTrop = if (restent.size > max) restent.take(restent.size - max) else emptyList()
            return vieilles + enTrop
        }

        /** Fichier WAV PCM 16 bits mono. */
        fun wav(pcm: ShortArray, taux: Int): ByteArray {
            val donnees = pcm.size * 2
            val b = ByteBuffer.allocate(44 + donnees).order(ByteOrder.LITTLE_ENDIAN)
            b.put("RIFF".toByteArray(Charsets.US_ASCII)).putInt(36 + donnees)
            b.put("WAVE".toByteArray(Charsets.US_ASCII))
            b.put("fmt ".toByteArray(Charsets.US_ASCII)).putInt(16)
            b.putShort(1).putShort(1).putInt(taux).putInt(taux * 2).putShort(2).putShort(16)
            b.put("data".toByteArray(Charsets.US_ASCII)).putInt(donnees)
            for (s in pcm) b.putShort(s)
            return b.array()
        }

        /** NaN devient null (JSON n'a pas de NaN), le reste est arrondi au millième. */
        fun tableau(valeurs: FloatArray): JSONArray {
            val a = JSONArray()
            for (v in valeurs) {
                if (v.isNaN() || v.isInfinite()) a.put(JSONObject.NULL)
                else a.put(Math.round(v * 1000.0) / 1000.0)
            }
            return a
        }
    }
}
