package assistant.vocal.jarvis

import android.Manifest
import android.annotation.SuppressLint
import android.app.Notification
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.app.Service
import android.content.Context
import android.content.Intent
import android.content.SharedPreferences
import android.content.pm.PackageManager
import android.content.pm.ServiceInfo
import android.graphics.drawable.Icon
import android.media.AudioAttributes
import android.media.AudioFormat
import android.media.AudioRecord
import android.media.AudioTrack
import android.media.MediaRecorder
import android.media.audiofx.AcousticEchoCanceler
import android.media.audiofx.NoiseSuppressor
import android.os.Looper
import android.net.wifi.WifiManager
import android.os.Build
import android.os.Handler
import android.os.HandlerThread
import android.os.IBinder
import android.os.PowerManager
import android.os.SystemClock
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import okio.ByteString
import okio.ByteString.Companion.toByteString
import org.json.JSONException
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.ExecutorService
import java.util.concurrent.Executors
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.min
import kotlin.math.sqrt

/**
 * Service de premier plan : capte le micro en continu, l'envoie au serveur par
 * WebSocket, joue les réponses WAV et se reconnecte seul si le lien tombe.
 *
 * Depuis la 0.15.0 (serveur 0.17.0) : port chiffré wss 8766 avec clé épinglée (Confiance),
 * jeton en en-tête Authorization, appairage des nouveaux appareils, arbitre du mot de réveil.
 *
 * Depuis la 0.16.0 : mode station (tablette posée en permanence, relancée si elle est tuée, chien
 * de garde du micro, de la caméra et de la passerelle), vision par la caméra avant (Vision.kt),
 * données de l'écran ambiant (Maison.kt), et micro gardé ouvert avec l'annulation d'écho pendant
 * les réponses du mode « Cet appareil » pour pouvoir couper la parole à l'assistant.
 */
class SatelliteService : Service() {

    companion object {
        /** Réponse du PC au résumé de santé attendue 15 s au plus (0.21.1 : le serveur attend jusqu'à 11 s). */
        const val DELAI_SANTE_MS = 15_000L
        /** Météo marine (0.25.0) : la première lecture de VaguesRegional prend une vingtaine de secondes. */
        const val DELAI_METEO_MER_MS = 25_000L
        /** Vent mesuré (0.29.0) : le serveur lit ses sources en parallèle, 20 s au plus pour StationsOfficielles. */
        const val DELAI_VENT_MESURE_MS = 25_000L
        /** Historique de l'air (0.47.0) : une requête d'historique à HA, 7 jours réduits à 288 points. */
        const val DELAI_AIR_HISTORIQUE_MS = 20_000L
        const val ACTION_ARRETER = "assistant.vocal.jarvis.ARRETER"
        /** Réponse à une demande d'appairage depuis la notification (extra « id »). */
        const val ACTION_APPAIRER = "assistant.vocal.jarvis.APPAIRER"
        const val ACTION_REFUSER = "assistant.vocal.jarvis.REFUSER"
        /**
         * L'écran de l'assistant est de nouveau affiché (0.17.3) : envoyé par l'écran principal quand il
         * reprend, retrouve le focus ou quand l'écran s'allume, seulement si le service tourne déjà.
         */
        const val ACTION_REPRENDRE = "assistant.vocal.jarvis.REPRENDRE"
        /** Ancienne adresse unique (jusqu'à la 0.5.0), migrée vers CLE_URL_PC. */
        private const val CLE_URL = "url_serveur"
        const val CLE_URL_PC = "url_pc"
        const val CLE_URL_HA = "url_ha"
        const val CLE_SERVEUR = "serveur"
        const val CLE_CERVEAU = "cerveau"
        /** Où guetter le mot de réveil : "appareil" (téléphone, par défaut) ou "serveur". */
        const val CLE_REVEIL = "reveil"
        const val CLE_SEUIL_REVEIL = "seuil_reveil"
        /** 0,4 depuis la 0.10.0 (0,5 avant) : on parle doucement, loin de la tablette. */
        const val SEUIL_REVEIL_DEFAUT = 0.4f
        /** Mot de réveil guetté sur l'appareil : ReveilLocal.HEY_JARVIS (par défaut) ou ReveilLocal.PERSO. */
        const val CLE_MOT_REVEIL = "mot_reveil"
        /** Le mot de réveil de la configuration a son propre seuil, 0,5 par défaut. */
        private const val CLE_SEUIL_PERSO = "seuil_reveil_perso"
        /** Préfixe des clés de ce seuil jusqu'à la 0.30.x (un seul mot de réveil personnalisé, nommé dans la clé). */
        private const val PREFIXE_SEUIL_ANCIEN = "seuil_reveil_"
        private const val SEUIL_PERSO_DEFAUT = 0.5f
        /** Adresses ws://...:8765 converties une fois en wss://...:8766 (0.15.0). */
        private const val CLE_MIGRATION_WSS = "migration_wss"
        /** Mode « Cet appareil » : réel ou essai, et LLM de secours, choisis sur l'appareil. */
        const val CLE_MODE_LOCAL = "mode_local"
        const val CLE_CERVEAU_LOCAL = "cerveau_local"
        /** Mode station (0.16.0) : démarrage avec la tablette, écran ambiant, relance. Désactivé par défaut. */
        const val CLE_STATION = "station"
        /** Vision : "off" (par défaut), "tablette" ou "pc". */
        const val CLE_VISION = "vision"
        /** Regarder la tablette 1,5 s, seul devant, vaut le mot de réveil. Désactivé par défaut. */
        const val CLE_PARLER_REGARD = "parler_regard"
        /** Couper la parole à l'assistant par le mot de réveil pendant sa réponse (mode « Cet appareil »). */
        const val CLE_COUPER_PAROLE = "couper_parole"
        /** Transcription en direct pendant l'écoute (mode « Cet appareil »), activée par défaut. */
        const val CLE_TRANSCRIPTION_DIRECTE = "transcription_directe"
        /** Où transcrire la phrase en mode « Cet appareil » (0.17.0) : "tablette" (par défaut), "pc", "ha", "api". */
        const val CLE_LIEU_TRANSCRIPTION = "lieu_transcription"
        /** Arrêt demandé par le propriétaire : le mode station ne relance pas le service. */
        const val CLE_ARRET_VOLONTAIRE = "arret_volontaire"
        private const val CANAL = "satellite"
        private const val CANAL_APPAIRAGE = "appairage"
        private const val ID_NOTIF = 1
        private const val ID_NOTIF_APPAIRAGE = 2
        private const val TAUX = 16000
        private const val BLOC = 1280
        private const val DELAI_RECONNEXION_MS = 3000L
        private const val DELAI_JETON_REFUSE_MS = 15_000L
        private const val TAG = "JarvisSatellite"

        fun preferences(ctx: Context): SharedPreferences {
            val p = ctx.getSharedPreferences("satellite", Context.MODE_PRIVATE)
            // Migration : l'ancienne adresse unique devient celle du PC fixe.
            if (!p.contains(CLE_URL_PC) && p.contains(CLE_URL)) {
                p.edit().putString(CLE_URL_PC, p.getString(CLE_URL, null)).remove(CLE_URL).apply()
            }
            // Migration : le seuil du mot de réveil de la configuration change de clé.
            if (!p.contains(CLE_SEUIL_PERSO)) {
                val ancienne = p.all.keys.firstOrNull { it.startsWith(PREFIXE_SEUIL_ANCIEN) }
                if (ancienne != null) {
                    p.edit().putFloat(CLE_SEUIL_PERSO, p.getFloat(ancienne, SEUIL_PERSO_DEFAUT)).remove(ancienne).apply()
                }
            }
            // Migration 0.15.0 : une adresse en clair sur 8765 passe sur le port chiffré. Une seule
            // fois, pour qu'une adresse ws:// saisie exprès ensuite soit respectée.
            if (!p.getBoolean(CLE_MIGRATION_WSS, false)) {
                val e = p.edit()
                for (cle in listOf(CLE_URL_PC, CLE_URL_HA)) {
                    p.getString(cle, null)?.let { Confiance.versChiffre(it) }?.let { e.putString(cle, it) }
                }
                e.putBoolean(CLE_MIGRATION_WSS, true).apply()
            }
            return p
        }

        /** Serveur choisi : "pc" (PC fixe) ou "ha" (Home Assistant). */
        /** Serveur choisi : "pc" (PC fixe), "ha" (Home Assistant) ou "local" (tout sur cet appareil). */
        fun serveurChoisi(ctx: Context): String =
            when (preferences(ctx).getString(CLE_SERVEUR, "pc")) {
                "ha" -> "ha"
                "local" -> "local"
                else -> "pc"
            }

        fun adresse(ctx: Context, serveur: String): String {
            val p = preferences(ctx)
            return if (serveur == "ha") {
                p.getString(CLE_URL_HA, null) ?: BuildConfig.SERVEUR_HA_DEFAUT
            } else {
                p.getString(CLE_URL_PC, null) ?: BuildConfig.SERVEUR_PC_DEFAUT
            }
        }

        /** Noms d'hôte de repli du serveur (0.34.0), séparés par des virgules, issus de la configuration. */
        fun hotesDe(serveur: String): String =
            if (serveur == "ha") BuildConfig.HOTES_HA_DEFAUT else BuildConfig.HOTES_PC_DEFAUT

        fun nomServeur(serveur: String): String = when (serveur) {
            "ha" -> "Home Assistant"
            "local" -> "cet appareil"
            else -> "PC fixe"
        }

        fun reveilChoisi(ctx: Context): String =
            if (preferences(ctx).getString(CLE_REVEIL, "appareil") == "serveur") "serveur" else "appareil"

        /** Le mot de réveil de la configuration par défaut depuis la 0.17.0, Hey Jarvis reste au
         *  choix, et seul possible quand la configuration n'en fournit pas. */
        fun motReveilChoisi(ctx: Context): String =
            if (!ReveilLocal.PERSO_DISPONIBLE ||
                preferences(ctx).getString(CLE_MOT_REVEIL, ReveilLocal.PERSO) == ReveilLocal.HEY_JARVIS) ReveilLocal.HEY_JARVIS
            else ReveilLocal.PERSO

        /** Préférence du seuil du mot de réveil choisi. */
        fun cleSeuilReveil(ctx: Context): String =
            if (motReveilChoisi(ctx) == ReveilLocal.PERSO) CLE_SEUIL_PERSO else CLE_SEUIL_REVEIL

        fun seuilReveil(ctx: Context): Float =
            if (motReveilChoisi(ctx) == ReveilLocal.PERSO) preferences(ctx).getFloat(CLE_SEUIL_PERSO, SEUIL_PERSO_DEFAUT)
            else preferences(ctx).getFloat(CLE_SEUIL_REVEIL, SEUIL_REVEIL_DEFAUT)

        fun transcriptionDirecte(ctx: Context): Boolean = preferences(ctx).getBoolean(CLE_TRANSCRIPTION_DIRECTE, true)

        fun lieuTranscription(ctx: Context): String =
            preferences(ctx).getString(CLE_LIEU_TRANSCRIPTION, OuTranscrire.TABLETTE)?.takeIf { it in OuTranscrire.LIEUX } ?: OuTranscrire.TABLETTE

        fun station(ctx: Context): Boolean = preferences(ctx).getBoolean(CLE_STATION, false)

        fun visionChoisie(ctx: Context): String = when (preferences(ctx).getString(CLE_VISION, "off")) {
            "tablette" -> "tablette"
            "pc" -> "pc"
            else -> "off"
        }

        /** L'annulation d'écho d'Android existe sur cet appareil. */
        fun echoAnnulable(): Boolean = try {
            AcousticEchoCanceler.isAvailable()
        } catch (_: Throwable) {
            false
        }

        /** Couper la parole : activé par défaut si l'annulation d'écho est disponible, jamais sans elle. */
        fun couperParole(ctx: Context): Boolean =
            echoAnnulable() && preferences(ctx).getBoolean(CLE_COUPER_PAROLE, true)

        private const val MICRO_MUET_MS = 20_000L
        /** Micro vraiment mort depuis ce délai : seulement alors l'écran est remis devant (0.16.3). */
        private const val MICRO_MORT_MS = 60_000L
    }

    @Volatile private var actif = false
    @Volatile private var enLecture = false
    /** Orbe touché pendant la lecture d'une réponse du serveur : la lecture s'arrête. */
    @Volatile private var couperLecture = false
    @Volatile private var connecte = false
    @Volatile private var ws: WebSocket? = null
    /** Vrai entre « ecoute » et la fin de la phrase : seul moment où le son part au serveur
     *  quand le mot de réveil est guetté sur le téléphone. */
    @Volatile private var ecouteServeur = false
    /** Le son de début d'écoute ne part pas au serveur (0.23.0) : rien n'est envoyé avant cet instant. */
    @Volatile private var muetVersServeurJusqua = 0L
    @Volatile private var reveilChoix = "appareil"
    @Volatile private var seuil = SEUIL_REVEIL_DEFAUT
    /** Demande de remise à zéro du détecteur, faite par le thread de capture. */
    @Volatile private var reveilAReinitialiser = false
    /** Modèle illisible sur ce téléphone : retour au mot de réveil guetté par le serveur. */
    @Volatile private var reveilIndisponible = false
    /** Pas de détection avant cet instant (fin de lecture, détection qui vient d'avoir lieu). */
    @Volatile private var sourdJusqua = 0L
    /** Mode « Cet appareil » : tout tourne ici, seule la passerelle HA garde un WebSocket. */
    @Volatile private var moteurLocal: MoteurLocal? = null
    /** Mot de réveil choisi, et demande de rechargement du détecteur par le fil de capture. */
    @Volatile private var motReveil = ReveilLocal.PERSO
    @Volatile private var reveilARecharger = false
    /** Prochaine connexion sur l'ancienne adresse en clair (port chiffré muet). */
    @Volatile private var essaiRepli = false
    /** Numéro de la tentative en cours dans la liste de cibles (0.34.0), remis à zéro à chaque connexion réussie. */
    @Volatile private var essaiCible = 0
    /** Adresse de la connexion en cours, pour vérifier l'empreinte annoncée par le serveur. */
    @Volatile private var adresseCourante = ""

    private var threadCapture: Thread? = null
    private lateinit var threadReseau: HandlerThread
    private lateinit var reseau: Handler
    private lateinit var lecteur: ExecutorService
    private var client: OkHttpClient? = null
    private var verrouCpu: PowerManager.WakeLock? = null
    private var verrouWifi: WifiManager.WifiLock? = null
    private var derniereNotif = ""

    private val reconnexion = Runnable { connecter() }

    /** Fil principal : vision (CameraX), chien de garde. */
    private val principal = Handler(Looper.getMainLooper())
    @Volatile private var vision: Vision? = null
    @Volatile private var maison: Maison? = null
    /** Passerelle du mode station quand le moteur local n'en a pas (serveur PC ou HA choisi). */
    @Volatile private var passerelleStation: PasserelleHa? = null
    /** Dernier bloc lu au micro, et dernier bloc qui n'était pas entièrement nul. */
    @Volatile private var dernierBlocLe = 0L
    @Volatile private var dernierSonLe = 0L
    /** Dernier son réel, jamais remis à zéro par le chien de garde. */
    @Volatile private var dernierSonReelLe = 0L
    /** Demande du chien de garde : fermer et rouvrir le micro. */
    @Volatile private var relancerMicro = false
    /** Micro ouvert en source VOICE_COMMUNICATION avec annulation d'écho (réponse qu'on peut couper). */
    @Volatile private var microCommunication = false
    private var annuleurEcho: AcousticEchoCanceler? = null
    private var reducteurBruit: NoiseSuppressor? = null

    private val chienDeGarde = object : Runnable {
        override fun run() {
            if (!actif) return
            surveiller()
            principal.postDelayed(this, 15_000)
        }
    }

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        // Palette retenue (0.19.0) : « change de palette » part du jeu affiché, même sans écran ouvert.
        Apparence.charger(this)
        creerCanal()
        threadReseau = HandlerThread("jarvis-reseau").also { it.start() }
        reseau = Handler(threadReseau.looper)
        lecteur = Executors.newSingleThreadExecutor()
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        if (intent?.action == ACTION_ARRETER) {
            preferences(this).edit().putBoolean(CLE_ARRET_VOLONTAIRE, true).apply()
            stopSelf()
            return START_NOT_STICKY
        }
        if (intent?.action == ACTION_APPAIRER || intent?.action == ACTION_REFUSER) {
            val id = intent.getStringExtra("id") ?: ""
            if (actif && id.isNotEmpty()) {
                repondreAppairage(if (intent.action == ACTION_APPAIRER) "appairer" else "refuser_appareil", id)
            } else if (!actif) {
                stopSelf()
                return START_NOT_STICKY
            }
            return START_STICKY
        }
        if (!passerAuPremierPlan()) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (intent?.action == ACTION_REPRENDRE) {
            // Jamais de démarrage par cette voie : on a pu arrêter l'assistant entre-temps.
            if (!actif) {
                stopSelf()
                return START_NOT_STICKY
            }
            reprendre()
            return START_STICKY
        }
        // Relance par le système après une mort du processus : en mode station, on remet aussi
        // l'écran devant, sans quoi Android coupe micro et caméra à un service lancé en arrière-plan.
        if (intent == null && station(this)) Station.ouvrirEcran(this)
        preferences(this).edit().putBoolean(CLE_ARRET_VOLONTAIRE, false).apply()
        if (!actif) demarrer()
        return START_STICKY
    }

    override fun onDestroy() {
        val relancer = actif && station(this) && !preferences(this).getBoolean(CLE_ARRET_VOLONTAIRE, false)
        arreterTout()
        threadReseau.quitSafely()
        if (relancer) Station.planifierRelance(this)
        super.onDestroy()
    }

    /** Appli balayée des récentes : en mode station, le service est relancé quelques secondes après. */
    override fun onTaskRemoved(rootIntent: Intent?) {
        if (station(this) && !preferences(this).getBoolean(CLE_ARRET_VOLONTAIRE, false)) Station.planifierRelance(this)
        super.onTaskRemoved(rootIntent)
    }

    // ---------------------------------------------------------------- cycle de vie

    /** Caméra déclarée seulement si la vision est choisie et permise : Android 14 refuse sinon le service. */
    private fun typeService(): Int {
        var t = ServiceInfo.FOREGROUND_SERVICE_TYPE_MICROPHONE
        if (visionChoisie(this) != "off" && checkSelfPermission(Manifest.permission.CAMERA) == PackageManager.PERMISSION_GRANTED) {
            t = t or ServiceInfo.FOREGROUND_SERVICE_TYPE_CAMERA
        }
        return t
    }

    private fun passerAuPremierPlan(): Boolean = try {
        val notif = construireNotif()
        if (Build.VERSION.SDK_INT >= Build.VERSION_CODES.Q) {
            startForeground(ID_NOTIF, notif, typeService())
        } else {
            startForeground(ID_NOTIF, notif)
        }
        true
    } catch (e: Exception) {
        Log.e(TAG, "Passage au premier plan impossible", e)
        false
    }

    private fun demarrer() {
        actif = true
        enLecture = false
        ecouteServeur = false
        reveilChoix = reveilChoisi(this)
        seuil = seuilReveil(this)
        motReveil = motReveilChoisi(this)
        essaiRepli = false
        Etat.actionMotReveil = { mot ->
            motReveil = mot
            seuil = seuilReveil(this)
            reveilARecharger = true
            moteurLocal?.let {
                it.seuilReveil = seuil
                it.changerMotReveil(mot)
            }
        }
        Etat.actionAppareil = { type, id -> repondreAppairage(type, id) }
        Etat.actionReveil = { choix ->
            reveilChoix = choix
            reveilAReinitialiser = true
            majReveil()
        }
        Etat.actionSeuilReveil = { s ->
            seuil = s
            moteurLocal?.seuilReveil = s
        }
        Etat.modifier {
            it.copy(enMarche = true, lien = Etat.Lien.CONNEXION, connexion = "Connexion...", assistant = "")
        }
        Etat.actionParler = {
            val m = moteurLocal
            when {
                m != null -> m.parler()
                // Mode serveur : un second toucher pendant la réponse arrête sa lecture (0.17.0). Le
                // protocole ne permet pas d'interrompre l'écoute du serveur, qui finit seule au silence.
                enLecture -> couperLecture = true
                else -> envoyerTexte(avecQuiParle(JSONObject().put("type", "parler")).toString())
            }
        }
        Etat.actionVision = { mode -> changerVision(mode) }
        Etat.actionCouperParole = { oui -> moteurLocal?.couperParole = oui && echoAnnulable() }
        Etat.actionTranscriptionDirecte = { oui -> moteurLocal?.transcriptionDirecte = oui }
        Etat.actionMedia = { entite, service, donnees -> maison?.commandeMedia(entite, service, donnees) }
        Etat.actionPochette = { adresse, suite -> maison?.pochette(adresse, suite) ?: suite(null) }
        // Écrans Musique et Maison (0.17.0) : la personne reconnue accompagne la commande (règle 3).
        Etat.actionService = { service, corps, verification ->
            maison?.commande(service, corps, verification, Etat.courant.quiParle())
        }
        Etat.actionSuivreEnceintes = { oui -> maison?.suivreEnceintes(oui) }
        Etat.actionSuivreAppareils = { oui -> maison?.suivreAppareils(oui) }
        // Accueil de la tablette (0.18.0) : lumières du plan 3D. Prévisions météo prêtes pour le futur panneau Météo.
        Etat.actionSuivreLumieres = { oui -> maison?.suivreLumieres(oui) }
        Etat.actionHoraire = { suite -> maison?.horaire(suite) ?: suite(emptyList(), 0) }
        Etat.actionPrevisions = { suite ->
            maison?.previsions(suite) ?: suite(Previsions.Lecture(erreur = "${ConfigMaison.NOM_ASSISTANT} à l'arrêt"))
        }
        Etat.actionPrevisionsDe = { entite, suite ->
            maison?.previsions(entite, suite) ?: suite(Previsions.Lecture(erreur = "${ConfigMaison.NOM_ASSISTANT} à l'arrêt"))
        }
        // Santé du propriétaire sur l'accueil (0.19.0) : par la connexion au PC de la transcription déportée, sur un
        // fil à part (appel bloquant de 8 s au plus). La réponse n'est ni gardée ni écrite dans le journal.
        Etat.actionSanteHistorique = { corps, suite ->
            val pc = moteurLocal?.transcriptionPc
            if (pc == null || !pc.historiqueDispo) suite(null)
            else Thread({
                val r = try { pc.demanderHistorique(corps, DELAI_SANTE_MS) } catch (_: Exception) { null }
                principal.post { suite(r) }
            }, "sante-historique").start()
        }
        Etat.historiqueSante = { moteurLocal?.transcriptionPc?.historiqueDispo == true }
        Etat.actionSante = { suite ->
            val pc = moteurLocal?.transcriptionPc
            if (pc == null || !pc.santeDispo) suite(null)
            else Thread({
                val r = try { pc.sante(DELAI_SANTE_MS) } catch (_: Exception) { null }
                principal.post { suite(r) }
            }, "sante").start()
        }
        // Météo marine (0.25.0, page Mer) : au PC s'il l'annonce, sinon à l'appli de l'assistant sur HA, sur un fil à part
        // (25 s au plus : la première lecture de la source régionale prend une vingtaine de secondes).
        Etat.actionMeteoMer = { suite ->
            val m = moteurLocal
            val pc = m?.transcriptionPc
            if (m == null) suite(null)
            else Thread({
                val r = try {
                    if (pc != null && pc.meteoMerDispo) pc.meteoMer(DELAI_METEO_MER_MS)
                    else if (m.passerelle.meteoMerDispo) m.passerelle.echanger(org.json.JSONObject().put("type", "meteo_mer").put("id", 1), "meteo_mer", DELAI_METEO_MER_MS / 1000)
                    else null
                } catch (_: Exception) { null }
                principal.post { suite(r) }
            }, "meteo-mer").start()
        }
        // Vent mesuré (0.29.0) : même chemin que la météo marine, 15 s au plus (Balises 10 s, StationsOfficielles 20 s en
        // tâche de fond côté serveur, qui sert son cache).
        Etat.actionVentMesure = { suite ->
            val m = moteurLocal
            val pc = m?.transcriptionPc
            if (m == null) suite(null)
            else Thread({
                val r = try {
                    if (pc != null && pc.ventMesureDispo) pc.ventMesure(DELAI_VENT_MESURE_MS)
                    else if (m.passerelle.ventMesureDispo) m.passerelle.echanger(org.json.JSONObject().put("type", "vent_mesure").put("id", 1), "vent_mesure", DELAI_VENT_MESURE_MS / 1000)
                    else null
                } catch (_: Exception) { null }
                principal.post { suite(r) }
            }, "vent-mesure").start()
        }
        // Historique de l'air d'une pièce (0.47.0) : même chemin, la pièce et la durée viennent de la vue. Le serveur
        // refuse tout ce qui n'est pas une pièce connue et plafonne la durée à 7 jours.
        Etat.airHistoriqueDispo = {
            val m = moteurLocal
            m != null && (m.transcriptionPc?.airHistoriqueDispo == true || m.passerelle.airHistoriqueDispo)
        }
        Etat.actionAirHistorique = { piece, heures, suite ->
            val m = moteurLocal
            val pc = m?.transcriptionPc
            if (m == null) suite(null)
            else Thread({
                val r = try {
                    if (pc != null && pc.airHistoriqueDispo) pc.airHistorique(piece, heures, DELAI_AIR_HISTORIQUE_MS)
                    else if (m.passerelle.airHistoriqueDispo) m.passerelle.echanger(
                        org.json.JSONObject().put("type", "air_historique").put("id", 1).put("piece", piece).put("heures", heures),
                        "air_historique", DELAI_AIR_HISTORIQUE_MS / 1000,
                    )
                    else null
                } catch (_: Exception) { null }
                principal.post { suite(r) }
            }, "air-historique").start()
        }
        Etat.actionVisionSuspendre = { oui -> vision?.suspendre(oui) }
        Etat.actionVisionRecharger = { vision?.rechargerProfils() }
        Etat.surNouvelleCommande = { entree -> maison?.nouvelleCommande(entree) }
        Etat.actionCerveau = { choix ->
            val m = moteurLocal
            if (m != null) choisirCerveauLocal(m, choix) else envoyerCerveau(choix)
        }
        Etat.actionReconnecter = { reseau.post { reconnecterMaintenant() } }
        Etat.actionHistorique = { if (moteurLocal == null) demanderHistorique() }
        Etat.actionRetour = { entree, verdict ->
            Etat.modifier { e ->
                e.copy(historique = e.historique.map { if (it.memeCommande(entree)) it.copy(verdict = verdict) else it })
            }
            val m = moteurLocal
            if (m != null) {
                m.retour(entree, verdict)
            } else {
                envoyerTexte(
                    JSONObject().put("type", "retour").put("verdict", verdict).put("date", entree.date)
                        .put("heure", entree.heure).put("entendu", entree.entendu).put("compris_par", entree.comprisPar)
                        .put("detail", entree.detailVoie).put("fait", org.json.JSONArray(entree.fait))
                        .put("reponse", entree.reponse).put("essai", entree.essai)
                        .apply { if (entree.personne.isNotEmpty()) put("personne", entree.personne) }.toString()
                )
            }
        }
        Etat.actionTranscription = { choix ->
            val m = moteurLocal
            // Mode « Cet appareil » : où transcrire (0.17.0). Sinon, le choix du serveur.
            if (m != null) choisirLieuTranscription(m, choix)
            else envoyerTexte(JSONObject().put("type", "transcription").put("choix", choix).toString())
        }
        Etat.actionMode = { choix ->
            val m = moteurLocal
            if (m != null) choisirModeLocal(m, choix)
            else envoyerTexte(JSONObject().put("type", "mode").put("choix", choix).toString())
        }
        prendreVerrous()
        try {
            SonsEcoute.charger(this)
        } catch (e: Exception) {
            Log.w(TAG, "Sons d'écoute indisponibles", e)
        }
        client = Confiance.clientWebSocket()
        dernierBlocLe = SystemClock.elapsedRealtime()
        dernierSonLe = dernierBlocLe
        dernierSonReelLe = dernierBlocLe
        threadCapture = Thread({ boucleCapture() }, "jarvis-capture").also { it.start() }
        reseau.post { connecter() }
        maison = Maison { passerelleMaison() }.also { it.demarrer() }
        changerVision(visionChoisie(this))
        principal.postDelayed(chienDeGarde, 15_000)
        majNotif()
    }

    // ---------------------------------------------------------------- station et vision (0.16.0)

    /** Passerelle pour l'écran ambiant : celle du moteur local, sinon une dédiée en mode station. */
    private fun passerelleMaison(): PasserelleHa? {
        moteurLocal?.let { return it.passerelle }
        if (!actif || !station(this)) return null
        passerelleStation?.let { return it }
        synchronized(this) {
            passerelleStation?.let { return it }
            val p = PasserelleHa(this, adresse(this, "ha"), annonce = { j -> reseau.post { traiterTexte(j.toString()) } })
            p.ouvrir()
            passerelleStation = p
            return p
        }
    }

    private fun fermerPasserelleStation() {
        val p = passerelleStation ?: return
        passerelleStation = null
        try {
            p.close()
        } catch (_: Exception) {
        }
    }

    /** Fil principal. Crée, change ou arrête la vision, et met à jour le type du service. */
    private fun changerVision(mode: String) {
        if (!actif) return
        val v = vision
        if (mode == "off") {
            vision = null
            v?.close()
            Etat.modifier { it.copy(presence = false, personnes = emptyList(), visionEtat = "", visionNiveau = "") }
        } else if (v == null) {
            if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
                Etat.modifier { it.copy(visionEtat = "Caméra non autorisée : ouvre ${ConfigMaison.NOM_ASSISTANT} et accepte la caméra", visionNiveau = "erreur") }
                return
            }
            passerAuPremierPlan()
            vision = Vision(this, mode, surPresence = { }, surRegard = { regardSoutenu() }).also { it.demarrer() }
        } else {
            v.changerMode(mode)
        }
        passerAuPremierPlan()
    }

    /**
     * Mode serveur (0.16.4) : qui parle d'après la vision accompagne parler et reveil, pour la sécurité
     * (règle 3) et « ma chambre » côté serveur. Rien quand on ne sait pas.
     */
    private fun avecQuiParle(msg: JSONObject): JSONObject {
        val qui = Etat.courant.quiParle()
        if (qui.isNotEmpty()) msg.put("personne", qui)
        return msg
    }

    /** Une personne seule regarde la tablette depuis 1,5 s (option Parler en regardant). */
    private fun regardSoutenu() {
        if (Etat.courant.assistant != "Repos") return
        val m = moteurLocal
        if (m != null) m.parler("regard vers la tablette pendant 1,5 s")
        else envoyerTexte(avecQuiParle(JSONObject().put("type", "parler")).toString())
    }

    /**
     * L'écran de l'assistant est de nouveau affiché (0.17.3). La demande vient de l'activité visible : le
     * passage au premier plan qui la précède (onStartCommand) rend au service le micro et la caméra
     * qu'Android refuse à un service lancé écran éteint. La passerelle, la transcription du PC et la
     * vision sont revues tout de suite, et leur état republié, au lieu d'attendre le chien de garde (15 s).
     * Rien ici ne dépend de l'écran : le service tourne pareil écran éteint, l'écran ne fait que hâter.
     */
    private fun reprendre() {
        Log.i(TAG, "écran de nouveau affiché : passerelle, transcription du PC et vision revues")
        vision?.surveiller()
        moteurLocal?.let { m ->
            m.passerelle.ouvrir()
            m.transcriptionPc?.ouvrir()
            publierModeLocal(m)
            publierTranscriptionLocale(m)
        }
        passerelleStation?.ouvrir()
    }

    /** Chien de garde, toutes les 15 s : micro, caméra, passerelle. */
    private fun surveiller() {
        val maintenant = SystemClock.elapsedRealtime()
        val capture = threadCapture
        if (capture == null || !capture.isAlive) {
            Log.w(TAG, "Fil de capture arrêté, relancé par le chien de garde")
            threadCapture = Thread({ boucleCapture() }, "jarvis-capture").also { it.start() }
            Etat.modifier { it.copy(bref = "Micro relancé par le chien de garde", brefLe = maintenant) }
        } else if (maintenant - dernierBlocLe > 10_000 || maintenant - dernierSonLe > MICRO_MUET_MS) {
            // Micro bloqué, ou qui ne rend plus que des zéros (Android le coupe à un service en arrière-plan).
            Log.w(TAG, "Micro muet ou bloqué, réouverture")
            relancerMicro = true
            dernierSonLe = maintenant
            dernierBlocLe = maintenant
            Etat.modifier { it.copy(bref = "Micro relancé par le chien de garde", brefLe = maintenant) }
            // Écran remis devant seulement si le micro est vraiment mort depuis plus de 60 s et que
            // l'écran de l'assistant n'est pas déjà affiché : jamais à cause d'une réponse (0.16.3).
            if (station(this) && maintenant - dernierSonReelLe > MICRO_MORT_MS && !Station.ecranVisible) Station.ouvrirEcran(this)
        }
        vision?.surveiller()
        moteurLocal?.passerelle?.ouvrir()
        moteurLocal?.transcriptionPc?.ouvrir()
        passerelleStation?.ouvrir()
    }

    private fun arreterTout() {
        if (!actif) return
        actif = false
        Etat.actionParler = null
        Etat.actionCerveau = null
        Etat.actionMode = null
        Etat.actionTranscription = null
        Etat.actionReconnecter = null
        Etat.actionHistorique = null
        Etat.actionReveil = null
        Etat.actionSeuilReveil = null
        Etat.actionRetour = null
        Etat.actionTesterTexte = null
        Etat.actionMotReveil = null
        Etat.actionAppareil = null
        Etat.actionVision = null
        Etat.actionCouperParole = null
        Etat.actionTranscriptionDirecte = null
        Etat.actionMedia = null
        Etat.actionPochette = null
        Etat.actionService = null
        Etat.actionSuivreEnceintes = null
        Etat.actionSuivreAppareils = null
        Etat.actionSuivreLumieres = null
        Etat.actionPrevisions = null
        Etat.actionPrevisionsDe = null
        Etat.actionHoraire = null
        Etat.actionSante = null
        Etat.actionMeteoMer = null
        Etat.actionVentMesure = null
        Etat.actionAirHistorique = null
        Etat.airHistoriqueDispo = { false }
        Etat.actionSanteHistorique = null
        Etat.historiqueSante = { false }
        Etat.actionVisionSuspendre = null
        Etat.actionVisionRecharger = null
        Etat.surNouvelleCommande = null
        principal.removeCallbacks(chienDeGarde)
        vision?.close()
        vision = null
        maison?.close()
        maison = null
        fermerPasserelleStation()
        reseau.removeCallbacksAndMessages(null)
        fermerMoteurLocal()
        try {
            ws?.close(1000, "arret")
        } catch (_: Exception) {
        }
        ws = null
        connecte = false
        try {
            threadCapture?.join(1000)
        } catch (_: InterruptedException) {
        }
        threadCapture = null
        lecteur.shutdownNow()
        client?.let {
            it.dispatcher.executorService.shutdown()
            it.connectionPool.evictAll()
        }
        client = null
        lacherVerrous()
        Etat.modifier {
            it.copy(
                enMarche = false, lien = Etat.Lien.ARRETE, connexion = "Arrêté", assistant = "",
                niveauDb = -60f, cerveauActif = "", cerveauPret = false, cerveauMessage = "",
                modeActif = "", modeMessage = "", transcriptionActif = "", transcriptionMessage = "",
                score = null, capServeur = "", capVersion = "", capTranscription = null, capCerveau = null, capLibelles = null,
                capReveilAppareil = false, reveilEffectif = "", capMotReveil = "", demandeAppairage = null,
                passerelle = "", passerelleDispo = false, meteo = null, maison = null, cartes = emptyList(),
                presence = false, personnes = emptyList(), visionEtat = "", visionNiveau = "", lecteurs = emptyList(),
                enceintes = emptyList(), appareils = emptyList(), lumieres = emptyList(),
            )
        }
        annulerNotifAppairage()
        stopForeground(STOP_FOREGROUND_REMOVE)
    }

    @SuppressLint("WakelockTimeout")
    private fun prendreVerrous() {
        try {
            val pm = getSystemService(Context.POWER_SERVICE) as PowerManager
            verrouCpu = pm.newWakeLock(PowerManager.PARTIAL_WAKE_LOCK, "jarvis:satellite").apply {
                setReferenceCounted(false)
                acquire()
            }
        } catch (e: Exception) {
            Log.w(TAG, "Verrou CPU refusé", e)
        }
        try {
            val wm = applicationContext.getSystemService(Context.WIFI_SERVICE) as WifiManager
            @Suppress("DEPRECATION")
            verrouWifi = wm.createWifiLock(WifiManager.WIFI_MODE_FULL_HIGH_PERF, "jarvis:wifi").apply {
                setReferenceCounted(false)
                acquire()
            }
        } catch (e: Exception) {
            Log.w(TAG, "Verrou Wi-Fi refusé", e)
        }
    }

    private fun lacherVerrous() {
        try {
            verrouCpu?.takeIf { it.isHeld }?.release()
        } catch (_: Exception) {
        }
        try {
            verrouWifi?.takeIf { it.isHeld }?.release()
        } catch (_: Exception) {
        }
        verrouCpu = null
        verrouWifi = null
    }

    // ---------------------------------------------------------------- réseau

    /** Toujours exécuté sur le thread réseau. */
    private fun connecter() {
        if (!actif) return
        val c = client ?: return
        val serveur = serveurChoisi(this)
        Etat.modifier { it.copy(serveurCible = serveur) }
        if (serveur == "local") {
            demarrerLocal()
            return
        }
        val principale = adresse(this, serveur).trim().trimEnd('/')
        // Port chiffré muet au dernier essai : ancienne adresse en clair, si aucune clé n'est retenue.
        val repli = Confiance.repli(this, principale)
        // Cibles à tour de rôle (0.34.0) : dernière qui a répondu, noms d'hôte, puis l'adresse enregistrée.
        val cibles = Decouverte.candidats(principale, Decouverte.hotes(hotesDe(serveur)), Confiance.derniereCible(this, principale))
        val base = if (essaiRepli && repli != null) repli else (Decouverte.cibleDe(cibles, essaiCible) ?: principale)
        val surRepli = base == repli
        val requete = try {
            // Le jeton part dans l'en-tête Authorization, jamais dans l'adresse ni à l'écran.
            // Il est celui de l'adresse enregistrée, quelle que soit la cible essayée.
            Confiance.requete(this, base, identite = principale)
        } catch (e: IllegalArgumentException) {
            changer(connexion = "Adresse invalide : $base")
            planifierReconnexion()
            return
        }
        adresseCourante = base
        changer(connexion = if (surRepli) "Port chiffré muet, essai de l'ancienne adresse $base..." else "Connexion à $base...")
        try {
            ws = Confiance.client(c, this, base, principale).newWebSocket(requete, Ecouteur(base, surRepli, repli != null, principale))
        } catch (e: Exception) {
            Log.w(TAG, "Ouverture du WebSocket impossible", e)
            changer(connexion = "Échec de connexion, nouvel essai dans 3 s")
            planifierReconnexion()
        }
    }

    private fun demarrerLocal() {
        connecte = false
        Etat.modifier {
            it.copy(
                lien = Etat.Lien.CONNECTE, connexion = "Tout sur cet appareil", assistant = "Chargement",
                capServeur = "local", capVersion = BuildConfig.VERSION_BASE,
                capReveilAppareil = true, reveilEffectif = "appareil",
                capCerveau = listOf("claude", "local"),
                historique = emptyList(),
            )
        }
        val p = preferences(this)
        // Réel mémorisé : rien ne part tant que la passerelle de l'appli de l'assistant sur HA ne répond pas.
        val reel = p.getString(CLE_MODE_LOCAL, "essai") == "reel"
        val cerveau = if (p.getString(CLE_CERVEAU_LOCAL, "claude") == "local") "local" else "claude"
        var moteur: MoteurLocal? = null
        val m = MoteurLocal(
            this, { s -> son(s) }, seuil, reel, cerveau, adresse(this, "ha"), motReveil,
            annonce = { j -> reseau.post { traiterTexte(j.toString()) } },
            changementPasserelle = {
                moteur?.let {
                    publierModeLocal(it)
                    publierTranscriptionLocale(it)
                }
            },
            // Transcription déportée sur le PC (0.17.0) : connexion dédiée, moteurs publiés à leur arrivée.
            urlPc = adresse(this, "pc"),
            changementTranscription = { moteur?.let { publierTranscriptionLocale(it) } },
        )
        moteur = m
        m.couperParole = couperParole(this)
        m.transcriptionDirecte = transcriptionDirecte(this)
        m.lieuTranscription = lieuTranscription(this)
        moteurLocal = m
        // Le moteur local a sa passerelle : celle du mode station ferait double emploi.
        fermerPasserelleStation()
        Etat.actionTesterTexte = { texte -> moteurLocal?.testerTexte(texte) }
        publierModeLocal(m)
        publierCerveauLocal(m)
        publierTranscriptionLocale(m)
        m.demarrer()
        majNotif()
    }

    /** Où transcrire (0.17.0) : choix du propriétaire, mémorisé, pris à la phrase suivante. */
    private fun choisirLieuTranscription(m: MoteurLocal, choix: String) {
        val lieu = if (choix in OuTranscrire.LIEUX) choix else OuTranscrire.TABLETTE
        m.lieuTranscription = lieu
        preferences(this).edit().putString(CLE_LIEU_TRANSCRIPTION, lieu).apply()
        if (lieu == OuTranscrire.PC) m.transcriptionPc?.ouvrir()
        publierTranscriptionLocale(m)
    }

    /**
     * Carte Transcription en mode « Cet appareil » : les lieux annoncés par les serveurs (la tablette
     * toujours), le lieu choisi et ce qui se passe vraiment (repli sur la tablette s'il est indisponible).
     */
    private fun publierTranscriptionLocale(m: MoteurLocal) {
        val capPc = m.transcriptionPc?.transcriptions
        val capHa = m.passerelle.transcriptions
        val tablette = resources.configuration.smallestScreenWidthDp >= 600
        val lieu = m.lieuTranscription
        val voie = OuTranscrire.voie(lieu, capPc, capHa)
        val message = when {
            lieu == OuTranscrire.TABLETTE -> "Canary 1B v2 tourne sur cet appareil"
            voie != null -> "Phrase transcrite sur ${OuTranscrire.nom(lieu)} (moteur ${voie.moteur}), repli sur Canary de la tablette " +
                "sans réponse en 8 s. Réveil, détection de parole, transcription en direct et dictionnaire restent ici."
            lieu == OuTranscrire.PC -> "Sur le PC choisi, mais le PC ne répond pas (${m.transcriptionPc?.etat ?: "adresse absente"}) : " +
                "transcription sur la tablette en attendant"
            else -> "${OuTranscrire.libelle(lieu)} choisi, mais non annoncé par le serveur : transcription sur la tablette en attendant"
        }
        Etat.modifier {
            it.copy(
                capTranscription = OuTranscrire.disponibles(capPc, capHa),
                capLibelles = OuTranscrire.LIEUX.associateWith { l -> OuTranscrire.libelle(l, tablette) } + mapOf(
                    "claude" to "Haiku (par l'appli ${ConfigMaison.NOM_ASSISTANT} sur HA)",
                    "local" to "LLM sur cet appareil",
                ),
                transcriptionActif = lieu,
                transcriptionMessage = message,
            )
        }
    }

    private fun choisirModeLocal(m: MoteurLocal, choix: String) {
        if (choix == "reel" && !m.passerelle.disponible) {
            Etat.modifier {
                it.copy(modeMessage = "Passerelle Home Assistant indisponible (${m.passerelle.etat}) : réel impossible pour l'instant")
            }
            return
        }
        m.reel = choix == "reel"
        preferences(this).edit().putString(CLE_MODE_LOCAL, if (m.reel) "reel" else "essai").apply()
        publierModeLocal(m)
    }

    private fun publierModeLocal(m: MoteurLocal) {
        Etat.modifier {
            it.copy(
                modeActif = if (m.reel) "reel" else "essai",
                modeMessage = when {
                    !m.reel -> "Essai : tout est calculé ici, rien n'est envoyé à Home Assistant"
                    m.passerelle.disponible -> "Réel : Home Assistant piloté par la passerelle de l'appli ${ConfigMaison.NOM_ASSISTANT} sur HA"
                    else -> "Réel demandé, mais passerelle indisponible (${m.passerelle.etat}) : rien ne part"
                },
                passerelle = m.passerelle.etat,
                passerelleDispo = m.passerelle.disponible,
            )
        }
        changer()
    }

    private fun choisirCerveauLocal(m: MoteurLocal, choix: String) {
        m.cerveau = if (choix == "local") "local" else "claude"
        preferences(this).edit().putString(CLE_CERVEAU_LOCAL, m.cerveau).apply()
        if (m.cerveau == "local") m.prechargerLlm()
        publierCerveauLocal(m)
    }

    private fun publierCerveauLocal(m: MoteurLocal) {
        Etat.modifier {
            it.copy(
                cerveauActif = m.cerveau,
                cerveauPret = m.cerveau == "claude" || ModeleLiteRt.choisir(this) != null,
                cerveauMessage = if (m.cerveau == "claude") "Haiku, par l'appli ${ConfigMaison.NOM_ASSISTANT} sur Home Assistant (${adresse(this, "ha")})"
                else ModeleLiteRt.choisir(this)?.let { (f, gpu) ->
                    "${f.nameWithoutExtension} sur cet appareil (" + (if (gpu) "GPU" else "CPU") + "), chargé en arrière-plan, environ 10 s"
                } ?: "Aucun modèle dans ${ModeleLiteRt.dossier(this)} : à copier par adb",
            )
        }
        changer()
    }

    private fun fermerMoteurLocal() {
        val m = moteurLocal ?: return
        moteurLocal = null
        try {
            m.close()
        } catch (e: Exception) {
            Log.w(TAG, "Arrêt du moteur local", e)
        }
    }

    private fun planifierReconnexion() {
        reseau.removeCallbacks(reconnexion)
        // Jeton refusé : réessayer toutes les 3 s ne sert à rien tant que l'appairage n'est pas refait.
        val delai = if (Etat.courant.alerteJeton.isNotEmpty()) DELAI_JETON_REFUSE_MS else DELAI_RECONNEXION_MS
        if (actif) reseau.postDelayed(reconnexion, delai)
    }

    /** Enregistre la cause d'un échec et fait passer la prochaine tentative à la cible suivante. */
    private fun diagnostiquer(code: Int?, raison: String?, http: Int?, t: Throwable?, cible: String): Decouverte.Diagnostic {
        val d = Decouverte.diagnostic(code, raison, http, t, Decouverte.libelle(cible))
        Log.w(TAG, "Échec de connexion à ${Decouverte.libelle(cible)} : ${d.cause}")
        if (d.cause != Decouverte.Cause.RESEAU_REFUSE) essaiCible++
        Etat.modifier { it.copy(dernierEchec = d.texte, alerteJeton = if (d.jetonRefuse) d.texte else it.alerteJeton) }
        return d
    }

    /** Tout ce que le serveur avait confirmé est oublié jusqu'à ce qu'il le redise. */
    private fun oublierConfirmations() {
        Etat.modifier {
            it.copy(
                cerveauActif = "", cerveauPret = false, cerveauMessage = "", modeActif = "", modeMessage = "",
                transcriptionActif = "", transcriptionMessage = "", score = null,
                capServeur = "", capVersion = "", capTranscription = null, capCerveau = null, capLibelles = null,
                capReveilAppareil = false, reveilEffectif = "",
            )
        }
    }

    private fun perdu(socket: WebSocket, raison: String) {
        if (socket !== ws) return
        ws = null
        connecte = false
        reseau.removeCallbacks(envoiCerveauDiffere)
        ecouteServeur = false
        oublierConfirmations()
        val delaiS = if (Etat.courant.alerteJeton.isNotEmpty()) DELAI_JETON_REFUSE_MS / 1000 else 3L
        changer(connexion = "$raison, nouvel essai dans $delaiS s", assistant = "", lien = Etat.Lien.RECONNEXION)
        planifierReconnexion()
    }

    /** Changement de serveur : coupe la connexion en cours et se reconnecte tout de suite. */
    private fun reconnecterMaintenant() {
        if (!actif) return
        reseau.removeCallbacks(reconnexion)
        reseau.removeCallbacks(envoiCerveauDiffere)
        val ancien = ws
        ws = null // l'ancien socket est ignoré par l'écouteur, il ne relance rien
        connecte = false
        try {
            ancien?.cancel()
        } catch (_: Exception) {
        }
        fermerMoteurLocal()
        oublierConfirmations()
        // Changement de serveur : l'historique affiché n'est plus le bon.
        Etat.modifier { it.copy(historique = emptyList(), deroule = emptyList(), derouleTitre = "") }
        changer(assistant = "", lien = Etat.Lien.CONNEXION)
        connecter()
    }

    /**
     * Le cerveau mémorisé est renvoyé à chaque connexion, mais seulement s'il existe sur ce
     * serveur. Les capacités arrivent juste après l'ouverture : on les attend un instant, et
     * un serveur ancien qui n'en envoie pas reçoit quand même le choix.
     */
    private val envoiCerveauDiffere = Runnable {
        if (!actif || !connecte) return@Runnable
        val choix = preferences(this).getString(CLE_CERVEAU, null) ?: return@Runnable
        val possibles = Etat.courant.capCerveau
        if (possibles == null || choix in possibles) envoyerCerveau(choix)
    }

    private fun demanderHistorique() {
        envoyerTexte(JSONObject().put("type", "historique").put("n", Etat.TAILLE_HISTORIQUE).toString())
    }

    private fun lireEntree(o: JSONObject): Etat.EntreeHistorique {
        val fait = o.optJSONArray("fait")?.let { a ->
            (0 until a.length()).map { a.optString(it) }.filter { it.isNotBlank() }
        } ?: emptyList()
        return Etat.EntreeHistorique(
            date = o.optString("date"),
            heure = o.optString("heure"),
            essai = o.optBoolean("essai", false),
            entendu = o.optString("entendu"),
            comprisPar = o.optString("compris_par"),
            detailVoie = o.optString("detail_voie"),
            fait = fait,
            erreur = o.optBoolean("erreur", false),
            reponse = o.optString("reponse"),
            duree = o.optString("duree"),
            personne = o.optString("personne"),
        )
    }

    private fun envoyerCerveau(choix: String) {
        envoyerTexte(JSONObject().put("type", "cerveau").put("choix", choix).toString())
    }

    private fun envoyerTexte(texte: String) {
        try {
            ws?.send(texte)
        } catch (e: Exception) {
            Log.w(TAG, "Envoi texte impossible", e)
        }
    }

    private inner class Ecouteur(
        private val adresse: String,
        /** Connexion sur l'ancienne adresse en clair. */
        private val repli: Boolean,
        private val repliPossible: Boolean,
        /** Adresse enregistrée du serveur : jeton et clé retenus sont rangés dessous. */
        private val identite: String,
    ) : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            if (webSocket !== ws) return
            connecte = true
            essaiCible = 0
            if (!repli) Confiance.retenirCible(this@SatelliteService, identite, adresse)
            Etat.modifier { it.copy(alerteCle = "", alerteJeton = "", dernierEchec = "") }
            changer(
                connexion = if (repli) "Connecté en clair sur l'ancien port 8765 : serveur à mettre à jour (0.17.0) pour le port chiffré"
                else if (Confiance.chiffree(adresse)) "Connecté (chiffré)" else "Connecté",
                lien = Etat.Lien.CONNECTE,
            )
            // Le choix de cerveau mémorisé est renvoyé à chaque (re)connexion, après les capacités.
            reseau.removeCallbacks(envoiCerveauDiffere)
            reseau.postDelayed(envoiCerveauDiffere, 1500)
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            if (webSocket !== ws) return
            try {
                traiterTexte(text)
            } catch (e: Exception) {
                Log.w(TAG, "Message texte illisible", e)
            }
        }

        override fun onMessage(webSocket: WebSocket, bytes: ByteString) {
            if (webSocket !== ws) return
            val donnees = bytes.toByteArray()
            couperLecture = false
            enLecture = true
            try {
                lecteur.execute { jouerWav(donnees) }
            } catch (e: Exception) {
                enLecture = false
            }
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            try {
                webSocket.close(1000, null)
            } catch (_: Exception) {
            }
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            // Après une connexion en clair qui tombe, on retente d'abord le port chiffré.
            if (repli) essaiRepli = false
            if (webSocket !== ws) return
            val d = diagnostiquer(code, reason, null, null, adresse)
            perdu(
                webSocket,
                when {
                    code == 4001 && repli -> "Jeton refusé (serveur antérieur à 0.17.0 ? il attend l'ancien accès)"
                    code == 4001 || code == 4003 -> d.texte
                    else -> "Connexion fermée ($code)"
                },
            )
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            val cle = Confiance.cleChangee(t)
            if (cle != null) {
                // Jamais de repli en clair après un refus de clé : ce serait la porte ouverte à un intermédiaire.
                Etat.modifier { it.copy(alerteCle = cle.message ?: "La clé du serveur a changé") }
                perdu(webSocket, "Clé du serveur refusée")
                return
            }
            if (response == null && !repli && repliPossible) {
                essaiRepli = true
            } else if (repli) {
                essaiRepli = false
            }
            if (webSocket !== ws) return
            val d = diagnostiquer(null, null, response?.code, t, adresse)
            val raison = if (response == null && repli) "Ancienne adresse injoignable aussi" else d.texte
            perdu(webSocket, raison)
        }
    }

    private fun traiterTexte(texte: String) {
        val j = try {
            JSONObject(texte)
        } catch (e: JSONException) {
            return
        }
        when (j.optString("etat")) {
            "repos" -> {
                if (ecouteServeur) reveilAReinitialiser = true
                ecouteServeur = false
                val version = j.optString("version")
                if (version.isNotEmpty()) Etat.modifier { it.copy(versionServeur = version) }
                if (j.optString("raison") == "arbitre") {
                    // Un autre appareil a mieux entendu : retour au repos sans son, message bref.
                    reveilAReinitialiser = true
                    val message = j.optString("message").ifEmpty { "Un autre appareil a répondu" }
                    Etat.modifier { it.copy(bref = message, brefLe = SystemClock.elapsedRealtime()) }
                }
                changer(assistant = "Repos")
            }
            "appairage_demande" -> {
                val d = Etat.DemandeAppairage(j.optString("id"), j.optString("nom"), j.optString("code"))
                if (d.id.isNotEmpty()) {
                    Etat.modifier { it.copy(demandeAppairage = d) }
                    notifierAppairage(d)
                }
            }
            "appareils" -> {
                // Réponse à une acceptation ou un refus : la demande traitée disparaît.
                val attente = j.optJSONArray("attente")
                val ids = if (attente == null) emptySet() else (0 until attente.length()).mapNotNull { attente.optJSONObject(it)?.optString("id") }.toSet()
                val d = Etat.courant.demandeAppairage
                if (d != null && d.id !in ids) {
                    Etat.modifier { it.copy(demandeAppairage = null) }
                    annulerNotifAppairage()
                }
            }
            "cerveau" -> {
                val choix = j.optString("actif")
                Etat.modifier {
                    it.copy(
                        cerveauActif = if (choix == "claude" || choix == "local") choix else "",
                        cerveauPret = j.optBoolean("pret", false),
                        cerveauMessage = j.optString("message"),
                    )
                }
                changer()
            }
            "transcription" -> {
                // Comme le mode, le serveur fait foi : rien n'est renvoyé à la reconnexion.
                val choix = j.optString("actif")
                Etat.modifier {
                    it.copy(
                        transcriptionActif = choix,
                        transcriptionMessage = j.optString("message"),
                    )
                }
            }
            "mode" -> {
                // Le serveur fait foi : le mode n'est jamais renvoyé à la reconnexion.
                val mode = j.optString("actif")
                Etat.modifier {
                    it.copy(
                        modeActif = if (mode == "essai" || mode == "reel") mode else "",
                        modeMessage = j.optString("message"),
                    )
                }
                changer()
            }
            "ecoute" -> {
                ecouteServeur = true
                Etat.modifier { it.copy(activiteLe = SystemClock.elapsedRealtime(), entendu = "", entenduFinal = false, jarvis = "", parole = "", paroleFinLe = 0L) }
                // Le serveur ignore 600 ms depuis l'envoi, trop peu pour Halo et Bronze : le téléphone
                // retient lui-même le son de début.
                muetVersServeurJusqua = SystemClock.elapsedRealtime() + SonsEcoute.dureeSourdeMs(this)
                son(SonsEcoute.Son.DEBUT)
                changer(assistant = "Je t'écoute")
            }
            "reflexion" -> {
                ecouteServeur = false
                // Le mot de réveil guetté sur le téléphone reprend ici : pas pendant le son de fin.
                sourdJusqua = SystemClock.elapsedRealtime() + 600
                reveilAReinitialiser = true
                son(SonsEcoute.Son.FIN)
                val phrase = j.optString("texte")
                // Texte transcrit par le serveur, montré sous l'orbe dès qu'il arrive.
                if (phrase.isNotEmpty()) Etat.modifier { it.copy(toi = phrase, jarvis = "", voie = "", entendu = phrase, entenduFinal = true) }
                changer(assistant = "Je réfléchis")
            }
            "reponse" -> {
                // Réponse dite par l'orbe : le texte entier s'affiche, effacé 6 s après la fin de la voix.
                Etat.modifier { it.copy(parole = j.optString("reponse"), paroleFinLe = 0L) }
                Etat.modifier {
                    it.copy(
                        toi = j.optString("texte"),
                        entendu = j.optString("texte").ifEmpty { it.entendu },
                        entenduFinal = true,
                        jarvis = j.optString("reponse"),
                        voie = j.optString("voie"),
                    )
                }
                changer(assistant = "Je réponds")
            }
            "capacites" -> {
                fun liste(nom: String): List<String>? = j.optJSONArray(nom)?.let { a ->
                    (0 until a.length()).map { a.optString(it) }.filter { it.isNotEmpty() }
                }
                val serveur = j.optString("serveur")
                // L'empreinte annoncée doit être celle de la clé épinglée à la poignée de main.
                val annoncee = j.optString("empreinte")
                val retenue = if (Confiance.chiffree(adresseCourante)) Confiance.empreinte(this, adresseCourante) else null
                if (annoncee.isNotEmpty() && retenue != null && annoncee != retenue) {
                    Log.w(TAG, "empreinte annoncée différente de la clé reçue, connexion coupée")
                    Etat.modifier {
                        it.copy(alerteCle = "La clé annoncée par le serveur ne correspond pas à celle reçue : connexion coupée. Vérifie dans l'écran Appareils.")
                    }
                    ws?.cancel()
                    return
                }
                Etat.modifier {
                    it.copy(
                        capServeur = if (serveur == "pc" || serveur == "ha") serveur else "",
                        capVersion = j.optString("version"),
                        capTranscription = liste("transcription"),
                        capCerveau = liste("cerveau"),
                        capLibelles = j.optJSONObject("libelles")?.let { o ->
                            o.keys().asSequence().associateWith { o.optString(it) }.filterValues { it.isNotEmpty() }
                        },
                        capReveilAppareil = j.optBoolean("reveil_appareil", false),
                        capMotReveil = j.optString("mot_reveil"),
                    )
                }
                majReveil()
                changer()
                // Après chaque (re)connexion, une fois les capacités connues : historique récent.
                demanderHistorique()
            }
            "historique" -> {
                val a = j.optJSONArray("entrees")
                val entrees = if (a == null) emptyList() else (0 until a.length())
                    .mapNotNull { a.optJSONObject(it) }
                    .map { lireEntree(it) }
                    .let(HistoriqueLisible::sansDoublons)
                    .take(Etat.TAILLE_HISTORIQUE)
                Etat.modifier { it.copy(historique = entrees) }
            }
            "historique_ajout" -> {
                val o = j.optJSONObject("entree") ?: return
                val entree = lireEntree(o)
                // Déjà reçue avec l'historique complet (vu en double le 21/10) : ni ligne ni carte de plus.
                if (HistoriqueLisible.dejaVue(entree, Etat.courant.historique)) return
                Etat.modifier { it.copy(historique = (listOf(entree) + it.historique).take(Etat.TAILLE_HISTORIQUE)) }
                Etat.surNouvelleCommande?.invoke(entree)
            }
            "niveau" -> {
                val score = j.optDouble("score")
                if (!score.isNaN() && !reveilSurAppareil()) Etat.modifier { it.copy(score = score) }
            }
        }
    }

    private fun son(s: SonsEcoute.Son) = SonsEcoute.jouer(this, s)

    // ---------------------------------------------------------------- lecture des réponses

    private class Wav(val taux: Int, val canaux: Int, val debut: Int, val fin: Int)

    /** Lit l'en-tête RIFF : fréquence aux octets 24 à 27, données dans le bloc data. */
    private fun analyserWav(o: ByteArray): Wav? {
        if (o.size < 44) return null
        val b = ByteBuffer.wrap(o).order(ByteOrder.LITTLE_ENDIAN)
        if (String(o, 0, 4, Charsets.US_ASCII) != "RIFF" || String(o, 8, 4, Charsets.US_ASCII) != "WAVE") return null
        val canaux = b.getShort(22).toInt().coerceIn(1, 2)
        val taux = b.getInt(24)
        val bits = b.getShort(34).toInt()
        if (bits != 16 || taux !in 4000..96000) return null
        var debut = 44
        var fin = o.size
        var pos = 12
        while (pos + 8 <= o.size) {
            val id = String(o, pos, 4, Charsets.US_ASCII)
            val taille = b.getInt(pos + 4)
            if (id == "data") {
                debut = pos + 8
                fin = if (taille in 0..(o.size - debut)) debut + taille else o.size
                break
            }
            if (taille < 0) break
            pos += 8 + taille + (taille and 1)
        }
        val trame = 2 * canaux
        fin = debut + ((fin - debut) / trame) * trame
        return if (fin > debut) Wav(taux, canaux, debut, fin) else null
    }

    /** Exécuté sur le thread de lecture. Le micro n'est plus envoyé tant que la voix joue. */
    private fun jouerWav(donnees: ByteArray) {
        var piste: AudioTrack? = null
        try {
            val wav = analyserWav(donnees)
            if (wav == null) {
                Log.w(TAG, "WAV illisible (${donnees.size} octets)")
                return
            }
            val masque = if (wav.canaux == 2) AudioFormat.CHANNEL_OUT_STEREO else AudioFormat.CHANNEL_OUT_MONO
            val tailleMin = AudioTrack.getMinBufferSize(wav.taux, masque, AudioFormat.ENCODING_PCM_16BIT)
            val tampon = max(tailleMin, wav.taux * 2 * wav.canaux / 4)
            val p = AudioTrack.Builder()
                .setAudioAttributes(
                    AudioAttributes.Builder()
                        .setUsage(AudioAttributes.USAGE_MEDIA)
                        .setContentType(AudioAttributes.CONTENT_TYPE_SPEECH)
                        .build()
                )
                .setAudioFormat(
                    AudioFormat.Builder()
                        .setEncoding(AudioFormat.ENCODING_PCM_16BIT)
                        .setSampleRate(wav.taux)
                        .setChannelMask(masque)
                        .build()
                )
                .setBufferSizeInBytes(tampon)
                .setTransferMode(AudioTrack.MODE_STREAM)
                .build()
            piste = p
            p.play()
            var pos = wav.debut
            while (pos < wav.fin && actif && !couperLecture) {
                val n = p.write(donnees, pos, min(8192, wav.fin - pos))
                if (n <= 0) break
                pos += n
            }
            // Un AudioTrack en flux ne démarre qu'une fois son tampon plein : on complète
            // avec du silence pour que les réponses très courtes soient jouées aussi.
            if (!couperLecture) {
                val silence = ByteArray(tampon)
                p.write(silence, 0, silence.size)
            }
            val trames = (wav.fin - wav.debut) / (2 * wav.canaux)
            val limite = SystemClock.elapsedRealtime() + trames * 1000L / wav.taux + 3000L
            while (actif && !couperLecture && p.playbackHeadPosition < trames && SystemClock.elapsedRealtime() < limite) {
                Thread.sleep(20)
            }
            p.pause()
            p.flush()
        } catch (e: InterruptedException) {
            // arrêt du service
        } catch (e: Exception) {
            Log.w(TAG, "Lecture impossible", e)
        } finally {
            try {
                piste?.release()
            } catch (_: Exception) {
            }
            enLecture = false
            couperLecture = false
            sourdJusqua = SystemClock.elapsedRealtime() + 300
            reveilAReinitialiser = true
            envoyerTexte(JSONObject().put("type", "lecture_finie").toString())
            Etat.modifier { if (it.parole.isNotEmpty() && it.paroleFinLe == 0L) it.copy(paroleFinLe = SystemClock.elapsedRealtime()) else it }
        }
    }

    // ---------------------------------------------------------------- micro

    /**
     * [communication] : source VOICE_COMMUNICATION avec annulation d'écho (et réduction de bruit si
     * elle existe), seulement pendant une réponse qu'on peut couper. Le reste du temps
     * VOICE_RECOGNITION, la source avec laquelle Canary a été réglé : le traitement de la voix pour
     * le téléphone (filtre, réduction de bruit) risquerait d'abîmer la transcription.
     */
    @SuppressLint("MissingPermission")
    private fun ouvrirMicro(communication: Boolean = false): AudioRecord? {
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) return null
        val min = AudioRecord.getMinBufferSize(TAUX, AudioFormat.CHANNEL_IN_MONO, AudioFormat.ENCODING_PCM_16BIT)
        if (min <= 0) return null
        val micro = try {
            AudioRecord(
                if (communication) MediaRecorder.AudioSource.VOICE_COMMUNICATION else MediaRecorder.AudioSource.VOICE_RECOGNITION,
                TAUX,
                AudioFormat.CHANNEL_IN_MONO,
                AudioFormat.ENCODING_PCM_16BIT,
                max(min, BLOC * 2 * 4),
            )
        } catch (e: Exception) {
            Log.w(TAG, "AudioRecord refusé", e)
            return null
        }
        if (micro.state != AudioRecord.STATE_INITIALIZED) {
            micro.release()
            return null
        }
        if (communication) {
            try {
                annuleurEcho = AcousticEchoCanceler.create(micro.audioSessionId)?.apply { enabled = true }
            } catch (e: Exception) {
                Log.w(TAG, "Annulation d'écho impossible", e)
            }
            try {
                if (NoiseSuppressor.isAvailable()) reducteurBruit = NoiseSuppressor.create(micro.audioSessionId)?.apply { enabled = true }
            } catch (e: Exception) {
                Log.w(TAG, "Réduction de bruit impossible", e)
            }
        }
        microCommunication = communication
        return try {
            micro.startRecording()
            if (micro.recordingState == AudioRecord.RECORDSTATE_RECORDING) {
                micro
            } else {
                micro.release()
                null
            }
        } catch (e: Exception) {
            micro.release()
            null
        }
    }

    private fun fermerMicro(micro: AudioRecord?) {
        for (effet in listOf(annuleurEcho, reducteurBruit)) try {
            effet?.release()
        } catch (_: Exception) {
        }
        annuleurEcho = null
        reducteurBruit = null
        if (micro == null) return
        try {
            micro.stop()
        } catch (_: Exception) {
        }
        try {
            micro.release()
        } catch (_: Exception) {
        }
    }

    private fun dormir(ms: Long) {
        try {
            Thread.sleep(ms)
        } catch (_: InterruptedException) {
        }
    }

    private fun boucleCapture() {
        val bloc = ShortArray(BLOC)
        val octets = ByteArray(BLOC * 2)
        val tampon = ByteBuffer.wrap(octets).order(ByteOrder.LITTLE_ENDIAN)
        var micro: AudioRecord? = null
        var detecteur: ReveilLocal? = null
        try {
            while (actif) {
                // Réponse qu'on peut couper (ou fin de réponse) : micro rouvert dans l'autre source.
                val communication = moteurLocal?.sourceCommunication == true
                if (micro != null && (relancerMicro || communication != microCommunication)) {
                    relancerMicro = false
                    fermerMicro(micro)
                    micro = null
                }
                val m = micro ?: ouvrirMicro(communication)
                if (m == null) {
                    changer(assistant = "Micro indisponible, nouvel essai")
                    dormir(2000)
                    continue
                }
                micro = m
                var lus = 0
                while (lus < BLOC && actif) {
                    val n = m.read(bloc, lus, BLOC - lus)
                    if (n < 0) {
                        lus = -1
                        break
                    }
                    lus += n
                }
                if (lus < 0) {
                    fermerMicro(m)
                    micro = null
                    dormir(500)
                    continue
                }
                if (!actif) break
                val instant = SystemClock.elapsedRealtime()
                dernierBlocLe = instant

                var somme = 0.0
                for (s in bloc) somme += s.toDouble() * s
                if (somme > 0.0) {
                    dernierSonLe = instant
                    dernierSonReelLe = instant
                }
                val rms = sqrt(somme / BLOC)
                val db = if (rms < 1.0) -60f else (20 * log10(rms / 32768.0)).toFloat().coerceIn(-60f, 0f)
                Etat.modifier { it.copy(niveauDb = db) }

                val local = moteurLocal
                if (local != null) {
                    local.bloc(bloc)
                    continue
                }
                val socket = ws
                if (socket == null || !connecte || enLecture) continue
                // Mot de réveil guetté sur le téléphone : le son ne part au serveur que pendant
                // l'écoute d'une phrase. Sinon (choix serveur, serveur d'avant la 0.15.0, modèle
                // illisible), flux continu comme avant et le serveur guette lui-même.
                if (reveilSurAppareil() && !ecouteServeur) {
                    if (reveilARecharger) {
                        // Changement de mot de réveil à chaud : modèle refermé ici, rechargé juste après.
                        reveilARecharger = false
                        try {
                            detecteur?.close()
                        } catch (_: Exception) {
                        }
                        detecteur = null
                    }
                    val d = detecteur ?: try {
                        ReveilLocal(this, mot = motReveil).also {
                            detecteur = it
                            Log.i(TAG, "Mot de réveil « ${ReveilLocal.nom(motReveil)} » chargé sur le téléphone")
                        }
                    } catch (e: Exception) {
                        Log.e(TAG, "Mot de réveil local impossible, retour au serveur", e)
                        reveilIndisponible = true
                        majReveil()
                        continue
                    }
                    if (reveilAReinitialiser) {
                        reveilAReinitialiser = false
                        d.reinitialiser()
                    }
                    if (SystemClock.elapsedRealtime() < sourdJusqua) continue
                    val score = d.bloc(bloc)
                    Etat.modifier { it.copy(score = score.toDouble()) }
                    if (score >= seuil) {
                        Log.i(TAG, "${ReveilLocal.nom(motReveil)} détecté sur le téléphone, score $score")
                        sourdJusqua = SystemClock.elapsedRealtime() + 1500
                        reveilAReinitialiser = true
                        envoyerTexte(
                            avecQuiParle(JSONObject().put("type", "reveil")
                                .put("score", Math.round(score * 100) / 100.0)).toString()
                        )
                    }
                    continue
                }
                if (SystemClock.elapsedRealtime() < muetVersServeurJusqua) continue
                tampon.clear()
                tampon.asShortBuffer().put(bloc)
                socket.send(octets.toByteString(0, octets.size))
            }
        } catch (e: Exception) {
            Log.e(TAG, "Boucle de capture interrompue", e)
        } finally {
            fermerMicro(micro)
            try {
                detecteur?.close()
            } catch (_: Exception) {
            }
        }
    }

    /** Vrai si le mot de réveil est guetté sur le téléphone : choix appareil et serveur 0.15.0+. */
    private fun reveilSurAppareil(): Boolean =
        reveilChoix == "appareil" && Etat.courant.capReveilAppareil && !reveilIndisponible

    /** Publie où le mot de réveil est réellement guetté, pour la carte de l'écran. */
    private fun majReveil() {
        val effectif = when {
            Etat.courant.capServeur.isEmpty() -> ""
            reveilSurAppareil() -> "appareil"
            else -> "serveur"
        }
        Etat.modifier { it.copy(reveilEffectif = effectif) }
    }

    // ---------------------------------------------------------------- notification

    private fun creerCanal() {
        val canal = NotificationChannel(CANAL, "Satellite vocal", NotificationManager.IMPORTANCE_LOW).apply {
            description = "État du satellite ${ConfigMaison.NOM_ASSISTANT}"
            setShowBadge(false)
        }
        val appairage = NotificationChannel(CANAL_APPAIRAGE, "Demandes d'appairage", NotificationManager.IMPORTANCE_HIGH).apply {
            description = "Un nouvel appareil demande l'accès à ${ConfigMaison.NOM_ASSISTANT}"
        }
        getSystemService(NotificationManager::class.java)?.let {
            it.createNotificationChannel(canal)
            it.createNotificationChannel(appairage)
        }
    }

    // ---------------------------------------------------------------- appairage

    /** Accepte ou refuse une demande d'appairage, par la connexion du serveur ou la passerelle. */
    private fun repondreAppairage(type: String, id: String) {
        val msg = JSONObject().put("type", type).put("id", id)
        val m = moteurLocal
        if (m != null) {
            Thread({ m.passerelle.envoyer(msg) }, "jarvis-appairage").start()
        } else {
            envoyerTexte(msg.toString())
        }
        Etat.modifier { if (it.demandeAppairage?.id == id) it.copy(demandeAppairage = null) else it }
        annulerNotifAppairage()
    }

    private fun notifierAppairage(d: Etat.DemandeAppairage) {
        fun action(nom: String, code: Int) = PendingIntent.getService(
            this, code,
            Intent(this, SatelliteService::class.java).setAction(nom).putExtra("id", d.id),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val ouvrir = PendingIntent.getActivity(
            this, 2,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val texte = "« ${d.nom} » demande l'accès à ${ConfigMaison.NOM_ASSISTANT}. Code affiché sur cet appareil : ${d.code}"
        val notif = Notification.Builder(this, CANAL_APPAIRAGE)
            .setSmallIcon(android.R.drawable.ic_lock_lock)
            .setContentTitle("Demande d'appairage")
            .setContentText(texte)
            .setStyle(Notification.BigTextStyle().bigText("$texte\nAccepte seulement si le même code s'affiche sur le nouvel appareil."))
            .setCategory(Notification.CATEGORY_MESSAGE)
            .setAutoCancel(true)
            .setContentIntent(ouvrir)
            .addAction(Notification.Action.Builder(null, "Accepter", action(ACTION_APPAIRER, 3)).build())
            .addAction(Notification.Action.Builder(null, "Refuser", action(ACTION_REFUSER, 4)).build())
            .build()
        try {
            getSystemService(NotificationManager::class.java)?.notify(ID_NOTIF_APPAIRAGE, notif)
        } catch (e: Exception) {
            Log.w(TAG, "Notification d'appairage impossible", e)
        }
    }

    private fun annulerNotifAppairage() {
        try {
            getSystemService(NotificationManager::class.java)?.cancel(ID_NOTIF_APPAIRAGE)
        } catch (_: Exception) {
        }
    }

    private fun changer(connexion: String? = null, assistant: String? = null, lien: Etat.Lien? = null) {
        Etat.modifier {
            it.copy(
                connexion = connexion ?: it.connexion,
                assistant = assistant ?: it.assistant,
                lien = lien ?: it.lien,
            )
        }
        majNotif()
    }

    private fun texteCerveau(e: Etat.Instantane): String = when {
        e.cerveauActif.isEmpty() -> "cerveau non confirmé"
        e.cerveauPret -> "cerveau ${Etat.nomCerveau(e.cerveauActif)} prêt"
        else -> "cerveau ${Etat.nomCerveau(e.cerveauActif)} en préparation"
    }

    private fun texteMode(e: Etat.Instantane): String =
        if (e.modeActif.isEmpty()) "mode non confirmé" else "mode ${Etat.nomMode(e.modeActif)}"

    private fun majNotif() {
        if (!actif) return
        synchronized(this) {
            val e = Etat.courant
            val cle = e.connexion + "|" + e.assistant + "|" + texteCerveau(e) + "|" + texteMode(e) +
                "|" + e.serveurCible
            if (cle == derniereNotif) return
            derniereNotif = cle
        }
        try {
            getSystemService(NotificationManager::class.java)?.notify(ID_NOTIF, construireNotif())
        } catch (e: Exception) {
            Log.w(TAG, "Notification non mise à jour", e)
        }
    }

    private fun construireNotif(): Notification {
        val e = Etat.courant
        val version = "v${BuildConfig.VERSION_BASE} (${BuildConfig.UTILISATEUR}) du ${BuildConfig.HORODATAGE_COMPILATION}"
        val ouvrir = PendingIntent.getActivity(
            this, 0,
            Intent(this, MainActivity::class.java).addFlags(Intent.FLAG_ACTIVITY_SINGLE_TOP),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val arreter = PendingIntent.getService(
            this, 1,
            Intent(this, SatelliteService::class.java).setAction(ACTION_ARRETER),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )
        val texte = e.assistant.ifEmpty { "Démarrage" } + ", " + texteMode(e) + ", " + texteCerveau(e)
        return Notification.Builder(this, CANAL)
            .setSmallIcon(android.R.drawable.ic_btn_speak_now)
            .setContentTitle("${ConfigMaison.NOM_ASSISTANT}, ${nomServeur(e.serveurCible)} : ${e.connexion}")
            .setContentText(texte)
            .setSubText(version)
            .setStyle(Notification.BigTextStyle().bigText("$texte\n$version"))
            .setOngoing(true)
            .setOnlyAlertOnce(true)
            .setShowWhen(false)
            .setCategory(Notification.CATEGORY_SERVICE)
            .setContentIntent(ouvrir)
            .addAction(
                Notification.Action.Builder(
                    Icon.createWithResource(this, android.R.drawable.ic_menu_close_clear_cancel),
                    "Arrêter",
                    arreter,
                ).build()
            )
            .build()
    }
}
