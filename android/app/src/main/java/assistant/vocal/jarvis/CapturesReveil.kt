package assistant.vocal.jarvis

import android.content.Context
import android.os.Build
import android.os.SystemClock
import android.util.Log
import org.json.JSONObject
import java.io.File
import java.security.MessageDigest
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.TimeZone
import java.util.concurrent.Executors

/**
 * Captures du mot de réveil (0.53.0), pour comprendre et corriger sa détection.
 *
 * Fonction active ([actif], réglage « Captures du réveil », désactivé par défaut), les 30 dernières secondes de
 * son restent en mémoire dans un [TamponReveil]. Rien n'est écrit sur disque sans un événement, et la fonction
 * coupée vide le tampon. Trois événements gardent les 30 s d'avant :
 * - [MANQUE] : l'orbe touché au repos (le réveil n'a pas entendu). Le regard ne compte pas.
 * - [REVEIL] : le réveil se déclenche. L'issue de l'écoute est ajoutée ensuite ([issue]) : rien entendu en 8 s
 *   ou transcription vide la changent en [FAUX_PROBABLE].
 * - [FAUX_SIGNALE] : bouton « C'était un faux réveil », dans les deux minutes qui suivent un réveil.
 *
 * Les captures vont dans le dossier privé de l'appli, `files/captures-reveil/` ([ArchiveCaptures]), 200 au plus
 * et 14 jours au plus. Ni texte transcrit ni prénom n'y sont écrits. Récupération sur le PC et analyse :
 * `poc/outils/analyser_captures.py`.
 */
object CapturesReveil {

    const val CLE = "captures_reveil"
    const val DOSSIER = "captures-reveil"

    const val MANQUE = "manque"
    const val REVEIL = "reveil"
    const val FAUX_PROBABLE = "faux_probable"
    const val FAUX_SIGNALE = "faux_signale"

    const val ISSUE_COMMANDE = "commande"
    const val ISSUE_RIEN_ENTENDU = "rien_entendu"
    const val ISSUE_TRANSCRIPTION_VIDE = "transcription_vide"

    /** Le bouton « C'était un faux réveil » vise le dernier réveil de moins de deux minutes. */
    const val FENETRE_SIGNALEMENT_MS = 120_000L
    /** L'issue de l'écoute n'est rattachée qu'à une capture de moins d'une minute. */
    private const val FENETRE_ISSUE_MS = 60_000L
    private const val SCHEMA = 1
    private const val TAG = "JarvisCaptures"

    /** Réglages en vigueur au moment de l'événement, fournis par le service. */
    class Reglages(
        val seuil: Float,
        val mot: String,
        /** "appareil" (mode « Cet appareil ») ou "serveur". */
        val mode: String,
        /** Où le mot de réveil est guetté : "appareil" ou "serveur". */
        val lieuReveil: String,
        /** Vrai quand la confirmation sur deux blocs et Silero s'applique (mode « Cet appareil »). */
        val confirmation: Boolean,
        val micro: String,
    )

    private class Derniere(val nom: String, val etiquette: String, val le: Long, @Volatile var issueFaite: Boolean = false)

    @Volatile var actif = false
        private set
    /** Nombre et taille des captures, tenus à jour après chaque écriture ou effacement. */
    @Volatile var nombre = 0
        private set
    @Volatile var octets = 0L
        private set

    /** Fourni par SatelliteService au démarrage. */
    @Volatile var reglages: (() -> Reglages)? = null

    private val tampon = TamponReveil()
    private val fil = Executors.newSingleThreadExecutor()
    @Volatile private var archive: ArchiveCaptures? = null
    @Volatile private var appli: Context? = null
    @Volatile private var dernierReveil: Derniere? = null
    @Volatile private var derniere: Derniere? = null
    private val empreintes = HashMap<String, String>()

    fun initialiser(contexte: Context) {
        val c = contexte.applicationContext
        appli = c
        if (archive == null) archive = ArchiveCaptures(File(c.filesDir, DOSSIER))
        actif = SatelliteService.preferences(c).getBoolean(CLE, false)
        if (!actif) tampon.vider()
        fil.execute { majBilan() }
    }

    fun activer(contexte: Context, oui: Boolean) {
        SatelliteService.preferences(contexte).edit().putBoolean(CLE, oui).apply()
        if (archive == null) initialiser(contexte)
        actif = oui
        if (!oui) {
            tampon.vider()
            dernierReveil = null
            derniere = null
        }
    }

    /** Fil de capture : chaque bloc de 80 ms, avant tout traitement. */
    fun ajouter(bloc: ShortArray, niveauDb: Float) {
        if (actif) tampon.ajouter(bloc, niveauDb)
    }

    /** Fil de capture : score, probabilité de parole (NaN si absents) et phase du dernier bloc. */
    fun noter(score: Float, probaVoix: Float, phase: Char) {
        if (actif) tampon.noter(score, probaVoix, phase)
    }

    /** Garde les 30 dernières secondes. Copie du tampon sur le fil appelant, écriture sur un fil à part. */
    fun evenement(etiquette: String, cause: String) {
        if (!actif) return
        val a = archive ?: return
        val inst = tampon.instantane()
        if (inst.blocs == 0) return
        val maintenant = System.currentTimeMillis()
        val nom = ArchiveCaptures.nom(maintenant)
        val r = try {
            reglages?.invoke()
        } catch (e: Exception) {
            null
        }
        val d = Derniere(nom, etiquette, SystemClock.elapsedRealtime())
        derniere = d
        if (etiquette == REVEIL) dernierReveil = d
        try {
            fil.execute {
                try {
                    a.ecrire(nom, inst, meta(nom, etiquette, cause, maintenant, inst.blocs, r))
                    Log.i(TAG, "Capture $nom ($etiquette, $cause)")
                } catch (e: Exception) {
                    Log.e(TAG, "Capture $nom impossible", e)
                }
                majBilan()
            }
        } catch (e: Exception) {
            Log.e(TAG, "Capture refusée", e)
        }
    }

    /** Issue de l'écoute qui suit la dernière capture, une seule fois et dans la minute. */
    fun issue(issue: String) {
        val d = derniere ?: return
        if (d.issueFaite || SystemClock.elapsedRealtime() - d.le > FENETRE_ISSUE_MS) return
        d.issueFaite = true
        val faux = d.etiquette == REVEIL && (issue == ISSUE_RIEN_ENTENDU || issue == ISSUE_TRANSCRIPTION_VIDE)
        val champs = mutableMapOf<String, Any?>("issue" to issue)
        if (faux) champs["etiquette"] = FAUX_PROBABLE
        fil.execute {
            try {
                archive?.reetiqueter(d.nom, champs)
            } catch (e: Exception) {
                Log.w(TAG, "Issue de ${d.nom} non écrite", e)
            }
        }
    }

    /** Un faux réveil peut être signalé : dernier réveil de moins de deux minutes, pas encore signalé. */
    fun signalable(): Boolean {
        val d = dernierReveil ?: return false
        return actif && SystemClock.elapsedRealtime() - d.le <= FENETRE_SIGNALEMENT_MS
    }

    /** Bouton « C'était un faux réveil ». Vrai si le dernier réveil a été marqué. */
    fun signalerFaux(): Boolean {
        if (!signalable()) return false
        val d = dernierReveil ?: return false
        dernierReveil = null
        val signaleLe = horodatage(System.currentTimeMillis())
        fil.execute {
            try {
                archive?.reetiqueter(d.nom, mapOf("etiquette" to FAUX_SIGNALE, "signale_le" to signaleLe))
            } catch (e: Exception) {
                Log.w(TAG, "Signalement de ${d.nom} non écrit", e)
            }
        }
        return true
    }

    /** Efface toutes les captures, puis rappelle [fini] avec leur nombre (sur le fil des captures). */
    fun effacer(fini: (Int) -> Unit = {}) {
        dernierReveil = null
        derniere = null
        fil.execute {
            val n = try {
                archive?.effacer() ?: 0
            } catch (e: Exception) {
                Log.e(TAG, "Effacement impossible", e)
                0
            }
            majBilan()
            fini(n)
        }
    }

    private fun majBilan() {
        val (n, o) = archive?.bilan() ?: (0 to 0L)
        nombre = n
        octets = o
    }

    private fun meta(nom: String, etiquette: String, cause: String, instant: Long, blocs: Int, r: Reglages?): JSONObject {
        val utc = SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSS'Z'", Locale.ROOT).apply { timeZone = TimeZone.getTimeZone("UTC") }
        val j = JSONObject()
            .put("schema", SCHEMA)
            .put("id", nom)
            .put("etiquette", etiquette)
            .put("etiquette_initiale", etiquette)
            .put("cause", cause)
            .put("issue", JSONObject.NULL)
            .put("horodatage", horodatage(instant))
            .put("horodatage_utc", utc.format(Date(instant)))
            .put("index_evenement", blocs - 1)
            .put("appareil", JSONObject()
                .put("fabricant", Build.MANUFACTURER)
                .put("modele", Build.MODEL)
                .put("android", Build.VERSION.RELEASE))
            .put("appli", JSONObject()
                .put("version", BuildConfig.VERSION_BASE)
                .put("code", BuildConfig.VERSION_CODE)
                .put("variante", BuildConfig.UTILISATEUR)
                .put("compilation", BuildConfig.HORODATAGE_COMPILATION))
        if (r != null) {
            val fichier = ReveilLocal.fichier(r.mot)
            j.put("modele", JSONObject()
                .put("mot", r.mot)
                .put("nom", ReveilLocal.nom(r.mot))
                .put("fichier", fichier)
                .put("sha256", empreinte(fichier) ?: JSONObject.NULL))
                .put("seuil", Math.round(r.seuil * 1000.0) / 1000.0)
                .put("mode", r.mode)
                .put("lieu_reveil", r.lieuReveil)
                .put("micro", r.micro)
                .put("confirmation", if (r.confirmation) JSONObject()
                    .put("blocs_score", ConfirmationReveil.BLOCS_SCORE)
                    .put("memoire_voix", ConfirmationReveil.MEMOIRE_VOIX)
                    .put("seuil_voix", VadSilero.SEUIL_DEBUT.toDouble())
                else JSONObject.NULL)
        }
        return j
    }

    private fun horodatage(instant: Long): String =
        SimpleDateFormat("yyyy-MM-dd'T'HH:mm:ss.SSSXXX", Locale.ROOT).format(Date(instant))

    /** Empreinte sha256 du modèle de réveil embarqué, calculée une fois par fichier. */
    private fun empreinte(fichier: String): String? = synchronized(empreintes) {
        empreintes[fichier] ?: try {
            val c = appli ?: return null
            val md = MessageDigest.getInstance("SHA-256")
            c.assets.open("reveil/$fichier").use { md.update(it.readBytes()) }
            md.digest().joinToString("") { "%02x".format(it) }.also { empreintes[fichier] = it }
        } catch (e: Exception) {
            null
        }
    }
}
