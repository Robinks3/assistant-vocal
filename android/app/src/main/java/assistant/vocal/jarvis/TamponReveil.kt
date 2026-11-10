package assistant.vocal.jarvis

/**
 * Tampon circulaire du son des 30 dernières secondes (0.53.0), pour les captures du mot de réveil
 * ([CapturesReveil]). Il vit en mémoire seulement : rien n'est écrit sur disque sans un événement.
 *
 * La boucle de capture y range chaque bloc de 80 ms ([ajouter]), puis le détecteur annote ce même bloc
 * ([noter]) : score du réveil, probabilité de parole de Silero et phase de l'assistant. Une valeur absente
 * (détecteur muet pendant l'écoute, mode serveur) reste à NaN. [instantane] rend une copie dans l'ordre du
 * temps, du bloc le plus ancien au plus récent.
 *
 * Coût : 375 blocs de 1280 échantillons, 960 Ko de son, et une copie de 2,5 Ko par bloc.
 */
class TamponReveil(val capacite: Int = BLOCS, val taille: Int = BLOC) {

    class Instantane(
        val pcm: ShortArray,
        val scores: FloatArray,
        val vad: FloatArray,
        val db: FloatArray,
        /** Une lettre par bloc, voir [PHASE_REPOS] et les suivantes. */
        val phases: String,
    ) {
        val blocs: Int get() = scores.size
    }

    private val son = ShortArray(capacite * taille)
    private val scores = FloatArray(capacite)
    private val vad = FloatArray(capacite)
    private val db = FloatArray(capacite)
    private val phases = CharArray(capacite)
    /** Case du prochain bloc. */
    private var tete = 0
    private var nombre = 0

    val blocs: Int @Synchronized get() = nombre

    @Synchronized
    fun ajouter(bloc: ShortArray, niveauDb: Float) {
        require(bloc.size == taille)
        System.arraycopy(bloc, 0, son, tete * taille, taille)
        scores[tete] = Float.NaN
        vad[tete] = Float.NaN
        db[tete] = niveauDb
        phases[tete] = PHASE_INCONNUE
        tete = (tete + 1) % capacite
        if (nombre < capacite) nombre++
    }

    /** Annote le dernier bloc rangé. Sans bloc, rien. */
    @Synchronized
    fun noter(score: Float, probaVoix: Float, phase: Char) {
        if (nombre == 0) return
        val i = (tete - 1 + capacite) % capacite
        scores[i] = score
        vad[i] = probaVoix
        phases[i] = phase
    }

    @Synchronized
    fun instantane(): Instantane {
        val debut = (tete - nombre + capacite) % capacite
        val pcm = ShortArray(nombre * taille)
        val s = FloatArray(nombre)
        val v = FloatArray(nombre)
        val d = FloatArray(nombre)
        val p = CharArray(nombre)
        for (k in 0 until nombre) {
            val i = (debut + k) % capacite
            System.arraycopy(son, i * taille, pcm, k * taille, taille)
            s[k] = scores[i]
            v[k] = vad[i]
            d[k] = db[i]
            p[k] = phases[i]
        }
        return Instantane(pcm, s, v, d, String(p))
    }

    @Synchronized
    fun vider() {
        son.fill(0)
        tete = 0
        nombre = 0
    }

    companion object {
        const val BLOC = 1280
        /** 375 blocs de 80 ms : 30 s. */
        const val BLOCS = 375
        const val PHASE_REPOS = 'R'
        const val PHASE_ECOUTE = 'E'
        const val PHASE_TRAITEMENT = 'T'
        const val PHASE_REPONSE = 'P'
        /** Mode serveur : le téléphone ne sait pas où en est le serveur. */
        const val PHASE_SERVEUR = 'S'
        const val PHASE_INCONNUE = '?'
    }
}
