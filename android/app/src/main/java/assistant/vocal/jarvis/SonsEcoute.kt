package assistant.vocal.jarvis

import android.content.Context
import android.media.AudioAttributes
import android.media.SoundPool
import android.os.Handler
import android.os.Looper
import android.util.Log
import java.util.Calendar
import java.util.concurrent.ConcurrentHashMap

/**
 * Sons de début et de fin d'écoute (0.23.0), à la place des tonalités de ToneGenerator
 * (TONE_PROP_BEEP et TONE_PROP_ACK, jugées désagréables le 22/10/2026).
 *
 * Quatre paires synthétisées (`android/outils/sons-ecoute/fabriquer_sons.py`, série 2.0.0), au choix
 * dans la carte Sons d'écoute des réglages : bronze, corde, déclic, halo. Chacune a sa version de nuit,
 * 6 dB plus bas, jouée du coucher au lever du soleil comme la palette Veillée.
 *
 * SoundPool partagé par le service et l'écran (même processus) : les 16 fichiers de res/raw sont
 * décodés une fois en mémoire, la lecture part en quelques dizaines de millisecondes. Flux des médias
 * comme les anciens bips, donc réglé par le volume des médias, et sans focus audio : une musique qui
 * joue sur l'appareil n'est ni coupée ni baissée.
 *
 * Le micro ignore le début de l'écoute, 600 ms au moins (MoteurLocal, serveur du PC) : le son de début ne
 * doit pas entrer dans la phrase. Halo et Bronze sonnent plus longtemps que ne le permet ce budget (bloc de
 * 80 ms, sortie jusqu'à 150 ms), d'où [dureeSourdeMs], qui allonge la fenêtre selon la paire choisie.
 */
object SonsEcoute {
    private const val TAG = "JarvisSons"
    const val CLE = "sons_ecoute"

    enum class Son { DEBUT, FIN }

    /** [nom] enregistré dans les préférences et dans le nom des fichiers, [libelle] du sélecteur. */
    class Paire(val nom: String, val libelle: String, val description: String)

    val PAIRES = listOf(
        Paire("bronze", "Bronze", "Un petit bol de bronze frappé puis retenu par la main. À la fin, un bol plus grand répond, aussitôt étouffé."),
        Paire("corde", "Corde", "Deux cordes de nylon pincées qui montent d'une quinte. À la fin, la première seule, étouffée sous la paume."),
        Paire("declic", "Déclic", "Deux crans d'un bouton usiné qui montent. À la fin, un seul cran plus grave. Le plus court et le plus discret."),
        Paire("halo", "Halo", "Un accord en quintes qui s'allume de bas en haut. À la fin, le même un ton plus bas, qui se referme."),
    )
    const val PAIRE_DEFAUT = "bronze"

    /**
     * Fin audible du son de début de chaque paire (dernière fenêtre de 10 ms au-dessus de -50 dBFS),
     * mesurée sur les fichiers et vérifiée par SonsEcouteTest.
     */
    internal val FIN_AUDIBLE_DEBUT_MS = mapOf("bronze" to 380L, "corde" to 360L, "declic" to 300L, "halo" to 410L)

    /** Bloc de 80 ms jugé à son traitement et non à son enregistrement, sortie de SoundPool jusqu'à 150 ms, entrée. */
    private const val MARGE_SORTIE_MS = 260L

    /** Les 16 fichiers de res/raw, nommés comme [fichier] les nomme. */
    internal val RESSOURCES = mapOf(
        "ecoute_bronze_debut" to R.raw.ecoute_bronze_debut,
        "ecoute_bronze_debut_nuit" to R.raw.ecoute_bronze_debut_nuit,
        "ecoute_bronze_fin" to R.raw.ecoute_bronze_fin,
        "ecoute_bronze_fin_nuit" to R.raw.ecoute_bronze_fin_nuit,
        "ecoute_corde_debut" to R.raw.ecoute_corde_debut,
        "ecoute_corde_debut_nuit" to R.raw.ecoute_corde_debut_nuit,
        "ecoute_corde_fin" to R.raw.ecoute_corde_fin,
        "ecoute_corde_fin_nuit" to R.raw.ecoute_corde_fin_nuit,
        "ecoute_declic_debut" to R.raw.ecoute_declic_debut,
        "ecoute_declic_debut_nuit" to R.raw.ecoute_declic_debut_nuit,
        "ecoute_declic_fin" to R.raw.ecoute_declic_fin,
        "ecoute_declic_fin_nuit" to R.raw.ecoute_declic_fin_nuit,
        "ecoute_halo_debut" to R.raw.ecoute_halo_debut,
        "ecoute_halo_debut_nuit" to R.raw.ecoute_halo_debut_nuit,
        "ecoute_halo_fin" to R.raw.ecoute_halo_fin,
        "ecoute_halo_fin_nuit" to R.raw.ecoute_halo_fin_nuit,
    )

    /** Écart entre le début et la fin quand on essaie une paire dans les réglages. */
    private const val ESSAI_ECART_MS = 1_400L

    private var pool: SoundPool? = null
    private val ids = HashMap<String, Int>()
    /** Identifiants chargés sans erreur : un son pas encore prêt n'est pas joué plutôt que joué en retard. */
    private val prets = ConcurrentHashMap.newKeySet<Int>()
    private val principal by lazy { Handler(Looper.getMainLooper()) }
    private var finEssai: Runnable? = null

    fun choisie(ctx: Context): String {
        val p = SatelliteService.preferences(ctx).getString(CLE, PAIRE_DEFAUT)
        return PAIRES.firstOrNull { it.nom == p }?.nom ?: PAIRE_DEFAUT
    }

    fun choisir(ctx: Context, paire: String) {
        if (PAIRES.none { it.nom == paire }) return
        SatelliteService.preferences(ctx).edit().putString(CLE, paire).apply()
    }

    /** Version douce du coucher au lever du soleil, comme la palette Veillée. */
    fun nuit(): Boolean =
        !Apparence.jour(Etat.courant.soleil, System.currentTimeMillis(), Calendar.getInstance().get(Calendar.HOUR_OF_DAY))

    /** Temps, compté depuis son lancement, pendant lequel le micro doit ignorer le son de début choisi. */
    fun dureeSourdeMs(ctx: Context): Long = (FIN_AUDIBLE_DEBUT_MS[choisie(ctx)] ?: 450L) + MARGE_SORTIE_MS

    /** Nom du fichier de res/raw, sans extension. */
    fun fichier(paire: String, son: Son, nuit: Boolean): String =
        "ecoute_${paire}_" + (if (son == Son.DEBUT) "debut" else "fin") + if (nuit) "_nuit" else ""

    /**
     * Décode les 16 sons, une seule fois par processus. Appelé au démarrage du service et des réglages, sur
     * le fil principal : SoundPool annonce la fin des chargements sur le Looper du fil qui l'a créé.
     */
    @Synchronized
    fun charger(ctx: Context) {
        if (pool != null) return
        val app = ctx.applicationContext
        prets.clear()
        ids.clear()
        val p = SoundPool.Builder()
            .setMaxStreams(2)
            .setAudioAttributes(
                AudioAttributes.Builder()
                    .setUsage(AudioAttributes.USAGE_MEDIA)
                    .setContentType(AudioAttributes.CONTENT_TYPE_SONIFICATION)
                    .build(),
            )
            .build()
        p.setOnLoadCompleteListener { _, id, statut ->
            if (statut == 0) prets.add(id) else Log.w(TAG, "Son $id illisible ($statut)")
        }
        try {
            for ((nom, res) in RESSOURCES) ids[nom] = p.load(app, res, 1)
        } catch (e: Exception) {
            // Rien de gardé d'un chargement à moitié fait : les identifiants repartent de 1 au suivant.
            Log.w(TAG, "Sons d'écoute illisibles", e)
            p.release()
            ids.clear()
            prets.clear()
            return
        }
        pool = p
    }

    /** Son de la paire choisie, version de nuit selon l'heure. */
    fun jouer(ctx: Context, son: Son) = jouer(choisie(ctx), son, nuit())

    @Synchronized
    private fun jouer(paire: String, son: Son, nuit: Boolean) {
        val p = pool ?: return
        val id = ids[fichier(paire, son, nuit)] ?: return
        if (id !in prets) return
        try {
            p.play(id, 1f, 1f, 1, 0, 1f)
        } catch (e: Exception) {
            Log.w(TAG, "Son impossible", e)
        }
    }

    /** Réglages : le début puis la fin de [paire], pour l'entendre avant de la garder. */
    fun essayer(ctx: Context, paire: String, nuit: Boolean = nuit()) {
        charger(ctx)
        finEssai?.let { principal.removeCallbacks(it) }
        jouer(paire, Son.DEBUT, nuit)
        finEssai = Runnable { jouer(paire, Son.FIN, nuit) }.also { principal.postDelayed(it, ESSAI_ECART_MS) }
    }
}
