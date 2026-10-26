package assistant.vocal.jarvis

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.ActivityNotFoundException
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.IntentFilter
import android.content.pm.ActivityInfo
import android.content.pm.PackageManager
import android.content.res.Configuration
import android.graphics.Color
import android.graphics.Typeface
import android.graphics.drawable.ClipDrawable
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.LayerDrawable
import android.net.Uri
import android.os.SystemClock
import android.os.BatteryManager
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.os.PowerManager
import android.provider.Settings
import android.text.InputType
import android.text.SpannableString
import android.text.Spanned
import android.text.style.RelativeSizeSpan
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.view.WindowInsets
import android.view.WindowManager
import android.view.animation.DecelerateInterpolator
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ProgressBar
import android.widget.FrameLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import java.util.Locale

/**
 * Écran principal, en vues du framework construites en code.
 *
 * Depuis la 0.15.0, l'écran de repos est épuré : l'orbe animé au centre (VueOrbe), l'état en
 * dessous, la dernière réponse dans une carte de verre qui reste 60 s. Les cartes de réglages
 * passent dans un panneau repliable. Deux dispositions selon la largeur disponible, recalculées
 * à chaque rotation sans recréer l'activité (configChanges dans le manifeste) :
 * - moins de 840 dp (téléphone, tablette en portrait) : une colonne qui défile, réglages repliés
 *   sous l'orbe.
 * - 840 dp et plus (tablette en paysage) : la réponse et le déroulé à gauche, l'orbe au centre,
 *   l'historique à droite, remplacé par les réglages sur le bouton de l'en-tête.
 * La version et l'horodatage de compilation restent toujours visibles en pied d'écran.
 *
 * 0.16.0 : en paysage sur tablette, l'écran devient l'écran ambiant (EcranAmbiant) : heure, météo
 * et maison à gauche, l'orbe au centre, les cartes des actions à droite, les personnes présentes
 * et l'état en bas. Les réglages s'ouvrent par-dessus. Le téléphone garde la disposition 0.15.0.
 * Mode station (carte Station) : plein écran immersif, paysage, écran allumé sur secteur, lumière
 * baissée après 2 min sans présence ni commande, au minimum la nuit.
 *
 * 0.17.0, l'assistant change de nom : écran OLED protégé (Veille, majVeille), second toucher sur
 * l'orbe qui coupe, bouton Retour qui ferme un panneau sans jamais quitter l'appli, écrans Musique
 * (EcranMusique) et Maison connectée (EcranMaison) ouverts depuis leurs bulles, réglages de la
 * tablette par sections (sections à gauche, contenu à droite, déroulé dans Diagnostic).
 *
 * 0.17.2 : quand personne n'est là de jour, vrai écran AOD (Veille.Regime.AOD, VueAod) à la luminosité
 * plancher de la fenêtre.
 *
 * 0.17.3 : démarrée écran éteint (installation par adb, démarrage de la tablette en station), l'interface
 * restait figée à l'allumage. L'affichage est relancé à onResume, au retour du focus et à l'allumage de
 * l'écran (reprendreAffichage), plus seulement à onStart. Cycle journalisé : adb logcat -s JarvisEcran.
 *
 * 0.17.4 : après une action sur des lumières, aperçu 3D de l'appartement à gauche de l'orbe (Apercu3d),
 * en régime vivant seulement et jamais sous un panneau ouvert. Il disparaît sur-le-champ dès que
 * l'écran s'endort (la page 3D garde sa dernière image, écran OLED).
 *
 * 0.17.5 : animation d'une action sur des lumières (gerbe de l'orbe vers l'aperçu, flux et bascule de
 * la lampe dans la page 3D). Démonstration sans Home Assistant par adb : voir demoLumieres.
 *
 * 0.18.0, accueil typographique de la tablette (EcranAmbiant, piste « la maison ») : le plan 3D au centre,
 * l'heure, la date, la météo en mots, la musique, la lumière de l'assistant à la place de l'orbe. Plus de
 * bulles, de particules ni d'aperçu 3D séparé : le plan central joue lui-même les actions. Le téléphone
 * garde sa disposition.
 */
class MainActivity : Activity() {

    /** Disposition en panneaux (tablette en paysage). */
    private var largeEcran = false
    /** Écran de tablette, quelle que soit l'orientation : textes du poste agrandis. */
    private var grandeTaille = false
    /** L'écran est maintenu allumé (tablette, satellite en marche). */
    private var ecranGarde = false

    private var panneauReglages: View? = null
    /** Tablette en paysage : historique à droite, caché quand les réglages sont ouverts. */
    private var panneauHistorique: View? = null
    private var boutonPanneau: TextView? = null

    private lateinit var pastille: TextView
    private lateinit var pointPastille: GradientDrawable

    private lateinit var etiquetteEssai: TextView
    private lateinit var segmentEssai: TextView
    private lateinit var segmentReel: TextView
    private lateinit var pointMode: GradientDrawable
    private lateinit var texteMode: TextView
    /** Mode cliqué mais pas encore confirmé par le serveur (non mémorisé). */
    private var modeDemande = ""
    private var cleMode = ""

    private var segmentsTranscription: List<Triple<TextView, String, Int>> = emptyList()
    private lateinit var pileTranscription: LinearLayout
    /** Liste et libellés des boutons actuellement construits, pour ne reconstruire qu'au besoin. */
    private var cleBoutonsTranscription = ""
    private lateinit var pointTranscription: GradientDrawable
    private lateinit var texteTranscription: TextView
    /** Transcription cliquée mais pas encore confirmée par le serveur (non mémorisée). */
    private var transcriptionDemandee = ""
    private var cleTranscription = ""

    private companion object {
        /** Choix affichés, grisés, tant que le serveur n'a pas envoyé ses capacités. */
        val CHOIX_TRANSCRIPTION_DEFAUT = listOf(
            "pc" to "PC (Canary)",
            "ha_stp" to "Home Assistant (Speech-to-Phrase)",
            "ha_whisper" to "Home Assistant (Whisper, très lent)",
        )
        /** Libellés de la carte Compréhension quand le serveur n'en fournit pas. */
        val LIBELLES_CERVEAU_DEFAUT = mapOf(
            "claude" to "En ligne (Claude)",
            "local" to "PC (carte graphique)",
        )
        const val CLE_API_ACCEPTEE = "transcription_api_acceptee"
        const val PREFS_INTERFACE = "interface"
        /** Réglages ouverts ou repliés (0.15.0 : repliés par défaut, écran de repos épuré). */
        const val CLE_REGLAGES_OUVERTS = "reglages_ouverts"
        /** Section des réglages choisie sur la tablette (0.17.0). */
        const val CLE_SECTION = "section_reglages"
        /** Durée d'affichage de la carte de réponse, et du message bref sous l'orbe. */
        const val DUREE_REPONSE_MS = 60_000L
        const val DUREE_BREF_MS = 4_000L
        /** La réponse dite sous l'orbe s'efface 6 s après la fin de la voix. */
        const val DUREE_PAROLE_MS = 6_000L
        const val REPONSE_SOUS_ORBE = true
        /** L'assistant a déjà été démarré une fois : il repart seul à l'ouverture. */
        const val CLE_DEJA_DEMARRE = "deja_demarre"
        /** Largeur à partir de laquelle l'écran passe en panneaux. */
        const val LARGEUR_PANNEAUX_DP = 840
        /** États où l'assistant travaille : l'écran reste vivant (Veille). */
        val ASSISTANT_OCCUPE = setOf("Je t'écoute", "Je réfléchis", "Je réponds")
        /** Journal du cycle de l'écran (0.17.3) : adb logcat -s JarvisEcran. */
        const val JOURNAL = "JarvisEcran"
        /** Repli de la chaleur par la température de la batterie (0.18.1). */
        const val TEMPERATURE_MODEREE = 40f
        const val TEMPERATURE_FORTE = 45f
        /** Bouton « Revenir à ... » de Réglages, Apparence, après un changement de palette (0.19.0). */
        const val RETOUR_PALETTE_MS = 10_000L
    }

    /** Choix de transcription à afficher : ceux du serveur s'il les a annoncés, sinon ceux d'avant. */
    private fun choixTranscription(e: Etat.Instantane): List<Pair<String, String>> {
        val liste = e.capTranscription ?: return CHOIX_TRANSCRIPTION_DEFAUT
        return liste.map { id -> id to (e.capLibelles?.get(id) ?: id) }
    }

    private fun libelleCerveau(e: Etat.Instantane, cle: String): String =
        e.capLibelles?.get(cle) ?: LIBELLES_CERVEAU_DEFAUT[cle] ?: cle

    private lateinit var texteAssistant: TextView
    private lateinit var texteAide: TextView
    private lateinit var orbe: VueOrbe
    private lateinit var texteBref: TextView
    /** Ce que l'assistant entend de la phrase en cours (0.16.1), sous l'orbe. */
    private lateinit var texteDirect: TextView
    /** Ce que dit l'assistant, sous l'orbe, au fil de la voix (0.16.3). */
    private lateinit var texteParole: TextView
    /** Rangée du bouton Démarrer, cachée tant que l'assistant tourne. */
    private lateinit var ligneMarche: LinearLayout
    private var paroleAffichee = ""
    private var paroleEffacee = false
    private lateinit var segmentDirectNon: TextView
    private lateinit var segmentDirectOui: TextView
    private var cleDirect = ""
    private lateinit var texteAlerte: TextView
    private lateinit var boutonMarche: TextView
    private lateinit var boutonArreter: TextView
    private var cleMarche = ""
    private lateinit var vumetre: ProgressBar
    private lateinit var remplissageVumetre: GradientDrawable
    private lateinit var texteNiveau: TextView
    private lateinit var texteScore: TextView

    private lateinit var segmentClaude: TextView
    private lateinit var segmentLocal: TextView
    private lateinit var pointCerveau: GradientDrawable
    private lateinit var segmentHeyJarvis: TextView
    private lateinit var segmentPerso: TextView
    private lateinit var segmentReveilAppareil: TextView
    private lateinit var segmentReveilServeur: TextView
    private lateinit var pointReveil: GradientDrawable
    private lateinit var texteReveil: TextView
    private lateinit var texteSeuil: TextView
    private var cleReveil = ""
    private lateinit var texteCerveau: TextView

    // Carte de réponse en verre.
    private lateinit var carteReponse: LinearLayout
    private lateinit var fondReponse: GradientDrawable
    private lateinit var texteSurtitre: TextView
    private lateinit var texteEntendu: TextView
    private lateinit var texteReponse: TextView
    private lateinit var conteneurFait: LinearLayout
    private lateinit var texteDuree: TextView
    /** Réponse déjà vue (null avant le premier affichage), et quand la carte est apparue. */
    private var reponseVue: String? = null
    private var reponseMontreeLe = 0L
    private var historiqueReponse: List<Etat.EntreeHistorique>? = null
    private val masquerReponse = Runnable { cacherReponse() }
    private val masquerBref = Runnable { texteBref.visibility = View.GONE }

    /** Demande d'appairage montrée en boîte de dialogue. */
    private var dialogueAppairage: AlertDialog? = null
    private var idDialogue = ""

    private lateinit var champUrlPc: EditText
    private lateinit var champUrlHa: EditText
    private lateinit var segmentPc: TextView
    private lateinit var segmentHa: TextView
    private lateinit var segmentAppareil: TextView
    private lateinit var conteneurDeroule: LinearLayout
    private lateinit var texteDerouleTitre: TextView
    private var derouleAffiche: List<Etat.Etape>? = null
    private lateinit var pointServeur: GradientDrawable
    private lateinit var texteServeurEtat: TextView
    private var cleServeur = ""
    private lateinit var conteneurHistorique: LinearLayout
    private var historiqueAffiche: List<Etat.EntreeHistorique>? = null
    private lateinit var texteBatterie: TextView
    private lateinit var texteDetailConnexion: TextView

    private var couleurVumetre = 0
    private var cleSegments = ""

    // Écran ambiant et mode station (0.16.0).
    private var ambiant: EcranAmbiant? = null
    /** Écran Musique de la tablette (0.17.0), par-dessus l'écran ambiant. */
    private var ecranMusique: EcranMusique? = null
    /** Écran Maison connectée de la tablette (0.17.0), par-dessus l'écran ambiant. */
    private var ecranMaison: EcranMaison? = null
    /** Panneau Météo de la tablette (0.20.0). */
    private var ecranMeteo: EcranMeteo? = null
    /** Panneau Santé de la tablette (0.21.0). */
    private var ecranSante: EcranSante? = null
    /** Lumières du plan 3D relues par le service (accueil vivant), et l'action qui a servi à le demander. */
    private var lumieresSuivies = false
    private var actionLumieres: ((Boolean) -> Unit)? = null
    private lateinit var segmentStationNon: TextView
    private lateinit var segmentStationOui: TextView
    private lateinit var texteStation: TextView
    private lateinit var segmentVisionNon: TextView
    private lateinit var segmentVisionTablette: TextView
    private lateinit var segmentVisionPc: TextView
    private lateinit var segmentRegardNon: TextView
    private lateinit var segmentRegardOui: TextView
    private lateinit var pointVision: GradientDrawable
    private lateinit var texteVision: TextView
    private lateinit var segmentCoupureNon: TextView
    private lateinit var segmentCoupureOui: TextView
    private lateinit var texteCoupure: TextView
    private lateinit var segmentsSons: List<TextView>
    private lateinit var texteSons: TextView
    private var cleStation = ""
    private var cleVision = ""
    private var cleCoupure = ""
    private var enCharge = false
    private var toucherLe = SystemClock.elapsedRealtime()
    private var luminositeAppliquee = -2f
    private var immersifApplique = false

    // Écran OLED de la tablette (0.17.0) : régimes vivant et protection, décalage global (Veille).
    private val veille = Veille()
    /** Lumière de la pièce (0.28.0) : le plafond du vivant suit les lux du capteur, l'heure sans capteur. */
    private val lumiere = LumiereAmbiante()
    private val capteurLumiere by lazy { CapteurLumiere(this, lumiere) }
    private var consigneJournal = -1f
    private var regimeApplique: Veille.Regime? = null
    /** Écran endormi touché : ce geste réveille seulement, il n'appuie sur rien. */
    private var avalerGeste = false
    private var racineVue: View? = null
    private var versionVue: TextView? = null
    private var decalageMinute = Long.MIN_VALUE
    private val animVeille = Runnable { majVeille() }
    /** Luminosité réelle de la dalle relevée une fois en AOD (journal JarvisVeille, 0.17.2). */
    private var plancherMesure = false
    private val mesurePlancher = Runnable { journaliserPlancher() }

    // Reprise de l'affichage (0.17.3).
    /** Entre onStart et onStop, et entre onResume et onPause. */
    private var demarree = false
    private var auPremierPlan = false
    /** L'écouteur d'Etat et l'horloge de la seconde tournent. */
    private var abonne = false
    /** Dernière image dessinée par la fenêtre (journal JarvisEcran). */
    private var derniereImageLe = 0L
    private val dessinFenetre = android.view.ViewTreeObserver.OnDrawListener { derniereImageLe = SystemClock.elapsedRealtime() }
    /** Dernière demande de reprise envoyée au service, pour ne pas l'inonder (plusieurs signaux à l'allumage). */
    private var repriseServiceLe = 0L
    /** État de la dalle (Display.STATE_*), suivi par DisplayManager. */
    private var etatDalle = android.view.Display.STATE_UNKNOWN
    private var suiviDalle: android.hardware.display.DisplayManager.DisplayListener? = null
    private val ecranAllume = object : BroadcastReceiver() {
        override fun onReceive(c: Context?, i: Intent?) {
            when (i?.action) {
                Intent.ACTION_SCREEN_ON -> {
                    // L'écran qui s'allume compte comme un toucher : l'écran ambiant reprend vie 2 min.
                    toucherLe = SystemClock.elapsedRealtime()
                    reprendreAffichage("écran allumé")
                }
                Intent.ACTION_SCREEN_OFF -> {
                    journal("écran éteint")
                    cacherAccueil()
                }
            }
        }
    }

    private val horloge = Handler(Looper.getMainLooper())
    private val tic = object : Runnable {
        override fun run() {
            ambiant?.tic()
            ecranMusique?.tic()
            ecranMeteo?.tic()
            ecranSante?.tic()
            // Les états prévus d'une tuile expirent même sans nouvelle lecture de HA.
            ecranMaison?.maj(Etat.courant)
            if (::texteParole.isInitialized) afficherDirect(Etat.courant)
            majVeille()
            majHoraire()
            majPaletteAuto()
            majSecurite()
            horloge.postDelayed(this, 1000)
        }
    }
    private val batterie = object : BroadcastReceiver() {
        override fun onReceive(c: Context?, i: Intent?) {
            if (i == null) return
            enCharge = i.getIntExtra(BatteryManager.EXTRA_PLUGGED, 0) != 0
            // Température de la batterie en dixièmes de degré : repli de la chaleur sans statut thermique.
            val t = i.getIntExtra(BatteryManager.EXTRA_TEMPERATURE, Int.MIN_VALUE)
            if (t != Int.MIN_VALUE) temperatureBatterie = t / 10f
            majChaleur()
            garderEcran(Etat.courant.enMarche)
        }
    }

    // Chaleur de la tablette (0.18.1, revue de faisabilité) : le plan 3D ralentit puis se met en pause.
    private var temperatureBatterie = 0f
    private var statutThermique = 0
    private var suiviThermique: Any? = null

    /** Statut thermique d'Android (API 29 et plus), suivi pendant toute la vie de l'activité. */
    private fun suivreChaleur() {
        if (Build.VERSION.SDK_INT < 29) return
        val pm = getSystemService(PowerManager::class.java) ?: return
        statutThermique = pm.currentThermalStatus
        val l = PowerManager.OnThermalStatusChangedListener { s ->
            statutThermique = s
            majChaleur()
        }
        pm.addThermalStatusListener(mainExecutor, l)
        suiviThermique = l
        majChaleur()
    }

    /** Niveau de chaleur du plan : modérée (rotation arrêtée, 12 images par seconde), forte (pause). */
    private fun majChaleur() {
        val n = if (Build.VERSION.SDK_INT >= 29) when {
            statutThermique >= PowerManager.THERMAL_STATUS_SEVERE -> 2
            statutThermique >= PowerManager.THERMAL_STATUS_MODERATE -> 1
            else -> 0
        } else 0
        val b = when {
            temperatureBatterie >= TEMPERATURE_FORTE -> 2
            temperatureBatterie >= TEMPERATURE_MODEREE -> 1
            else -> 0
        }
        ambiant?.plan?.chaleur(maxOf(n, b))
    }

    // Prévisions horaires pour « Pluie vers 17 h. » (0.18.1) : toutes les 30 min en régime vivant, 6 h après un refus.
    private var horaireLe = 0L
    private var horaireRefuse = false

    private fun majHoraire() {
        val a = ambiant ?: return
        val action = Etat.actionHoraire ?: return
        if (veille.regime != Veille.Regime.VIVANT || !Etat.courant.enMarche || Etat.courant.meteo == null) return
        val maintenant = SystemClock.elapsedRealtime()
        val attente = if (horaireRefuse) 6 * 3_600_000L else 30 * 60_000L
        if (horaireLe != 0L && maintenant - horaireLe < attente) return
        horaireLe = maintenant
        action { liste, code ->
            horaireRefuse = code in 400..499
            horaireDernier = liste
            ambiant?.horaire = liste
        }
    }

    /** Dernières prévisions horaires, reposées sur l'accueil reconstruit (0.21.1) : la pluie ne disparaît pas 30 min. */
    private var horaireDernier: List<Previsions.Prevision> = emptyList()
    /** Salutation de l'accueil, gardée par l'activité : une reconstruction ne redit pas « Bonjour Sacha. ». */
    private val salutation = Accueil.Salut()
    /** Arrêt de la musique sur l'accueil (0.24.0), gardé d'une reconstruction à l'autre : la pause ne repart pas à zéro. */
    private val suiviMusique = SuiviMusique()
    private var fenetreProtegee = false

    /**
     * Santé masquée (0.21.1, revue de code) : panneau fermé et lignes de l'accueil effacées, en pause, écran
     * éteint et activité cachée, pour que la capture des applis récentes ne garde aucune valeur.
     */
    private fun masquerSante() {
        ecranSante?.fermer()
        ambiant?.effacerSante()
        majSecurite()
    }

    /** Numéro de la dernière demande de retrait de FLAG_SECURE : une nouvelle protection l'annule. */
    private var retraitSecurite = 0

    /**
     * FLAG_SECURE tant que de vraies valeurs de santé sont à l'écran (panneau ou lignes de l'accueil) : ni
     * capture, ni miniature des applis récentes. Pas pendant les démonstrations aux valeurs fictives. Posé tout
     * de suite, levé seulement trois images plus tard (0.22.1, revue de code) : le panneau caché (fondu fini,
     * vue GONE) ou les lignes effacées doivent d'abord avoir été redessinés, en pause comme ailleurs.
     */
    private fun majSecurite() {
        val proteger = santeAProteger()
        if (proteger) {
            retraitSecurite++
            if (!fenetreProtegee) {
                fenetreProtegee = true
                window.addFlags(WindowManager.LayoutParams.FLAG_SECURE)
            }
            return
        }
        if (!fenetreProtegee) return
        val n = ++retraitSecurite
        apresImages(3) {
            if (n != retraitSecurite || !fenetreProtegee || santeAProteger()) return@apresImages
            fenetreProtegee = false
            window.clearFlags(WindowManager.LayoutParams.FLAG_SECURE)
        }
    }

    private fun santeAProteger(): Boolean = ecranSante?.reel == true || ambiant?.santeReelleMontree == true

    /** [action] après [n] images du Choreographer (l'état courant a donc été dessiné). */
    private fun apresImages(n: Int, action: () -> Unit) {
        android.view.Choreographer.getInstance().postFrameCallback { if (n <= 1) action() else apresImages(n - 1, action) }
    }

    private val ecouteur: (Etat.Instantane) -> Unit = { afficher(it) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        @Suppress("DEPRECATION")
        window.statusBarColor = Couleur.FOND_HAUT
        @Suppress("DEPRECATION")
        window.navigationBarColor = Couleur.FOND_BAS
        journal("onCreate : écran ${if (interactif()) "allumé" else "éteint"}, ${resources.configuration.screenWidthDp} x ${resources.configuration.screenHeightDp} dp")
        // Palette retenue (0.19.0), avant toute vue : chaque vue prend ses couleurs à sa construction.
        Apparence.charger(this)
        Palette.reglerJour(jourMaintenant())
        // La fenêtre doit exister avant le plein écran (plantage 0.16.0 sur la tablette, 21/10/2026).
        setContentView(construireInterface())
        // Allumage de l'écran suivi pendant toute la vie de l'activité, arrêtée comprise (0.17.3) : le
        // retour de l'écran relance l'affichage même si Android ne rappelle pas onStart.
        registerReceiver(ecranAllume, IntentFilter().apply {
            addAction(Intent.ACTION_SCREEN_ON)
            addAction(Intent.ACTION_SCREEN_OFF)
        })
        suivreDalle()
        suivreChaleur()
        window.decorView.viewTreeObserver.addOnDrawListener(dessinFenetre)
        appliquerStation()
        // Retour d'Android (0.17.0) : ferme un panneau, ne quitte jamais l'écran ambiant. Android 13 et
        // plus passent par ce rappel (obligatoire à partir d'Android 16), les plus anciens par onBackPressed.
        if (Build.VERSION.SDK_INT >= 33) {
            val rappel = android.window.OnBackInvokedCallback { retour() }
            onBackInvokedDispatcher.registerOnBackInvokedCallback(android.window.OnBackInvokedDispatcher.PRIORITY_DEFAULT, rappel)
            rappelRetour = rappel
        }
        demanderPermissions()
        relancerSiStation()
        // Le dossier du modèle Canary doit appartenir à l'appli : créé par adb, Android 16 en
        // refuse la lecture (errno 13 sur le téléphone le 13/10/2026). Les fichiers y sont ensuite poussés.
        CanaryLocal.dossierModele(this).mkdirs()
        ModeleLiteRt.dossier(this).mkdirs()
        // Extras de banc (S-D5, I11) : MainActivity est exportée, ils ne sont lus que dans un build de débogage.
        val essais = ExtrasTest.lisibles(BuildConfig.DEBUG, { intent?.getStringExtra(it) },
            { cle, defaut -> intent?.getIntExtra(cle, defaut) ?: defaut })
        essais.reveil?.let { TestReveil.lancer(applicationContext, it) }
        essais.llm?.let { TestLlm.lancer(applicationContext, it, essais.modele) }
        essais.canary?.let { TestCanary.lancer(applicationContext, it, essais.fils) }
    }

    /**
     * Rotation ou redimensionnement : l'activité n'est pas recréée (pas de relance des
     * tests ni des permissions), l'interface est reconstruite pour la nouvelle largeur
     * en gardant les adresses en cours de saisie.
     */
    override fun onConfigurationChanged(newConfig: Configuration) {
        super.onConfigurationChanged(newConfig)
        reconstruire()
    }

    /**
     * Interface reconstruite sur place (rotation, palette) : panneau des réglages et section retrouvés par
     * leurs préférences, adresses en cours de saisie gardées, état repeint.
     */
    private fun reconstruire() {
        val pc = champUrlPc.text.toString()
        val ha = champUrlHa.text.toString()
        setContentView(construireInterface())
        champUrlPc.setText(pc)
        champUrlHa.setText(ha)
        // 0.21.1 : l'accueil reconstruit retrouve la pluie, la chaleur et la sécurité de la fenêtre.
        ambiant?.horaire = horaireDernier
        majChaleur()
        afficher(Etat.courant)
        majBatterie()
        majVeille()
        majSecurite()
    }

    /**
     * Palette des écrans (0.19.0) : choisie dans Réglages, Apparence, ou à la voix (Etat.palette), un jeu ou le
     * mode Selon l'heure. Elle est retenue, puis toute l'interface est reconstruite avec les couleurs du jeu :
     * accueil, plan 3D (teintes et maison3d.palette au chargement de la page), écrans Maison, Musique,
     * Réglages et AOD. Pas de redémarrage. Pendant 10 s, Réglages propose de revenir au choix d'avant.
     */
    private fun choisirPalette(nom: String, retour: Boolean = true) {
        val avantChoix = Palette.choix
        val avant = Palette.jeu
        Palette.reglerJour(jourMaintenant())
        if (!Apparence.enregistrer(this, nom)) return
        if (Etat.courant.palette != Palette.choix) Etat.modifier { it.copy(palette = Palette.choix) }
        if (Palette.choix == avantChoix && Palette.jeu === avant) return
        if (retour && Palette.choix != avantChoix) {
            retourPalette = avantChoix
            retourPaletteJusqua = SystemClock.elapsedRealtime() + RETOUR_PALETTE_MS
        } else if (!retour) {
            retourPalette = null
        }
        journal("palette ${Palette.choix} (${Palette.jeu.nom})")
        reconstruire()
    }

    /** Dernière demande vocale du panneau Météo déjà ouverte. */
    private var meteoDemandeeVue = 0L

    /** Choix d'avant le dernier changement, proposé 10 s dans Réglages, Apparence. */
    private var retourPalette: String? = null
    private var retourPaletteJusqua = 0L
    private var paletteAutoLe = 0L

    /** Le soleil est-il levé (sun.sun lu dans Home Assistant, sinon de 7 h à 19 h) ? */
    private fun jourMaintenant(): Boolean =
        Apparence.jour(Etat.courant.soleil, System.currentTimeMillis(), java.util.Calendar.getInstance().get(java.util.Calendar.HOUR_OF_DAY))

    /**
     * Mode Selon l'heure : toutes les 30 s, Pastels le jour et Veillée du coucher au lever du soleil. Le
     * changement attend que l'assistant ne soit plus en train d'écouter, de réfléchir ou de parler.
     */
    private fun majPaletteAuto() {
        if (Palette.choix != Palette.AUTO) return
        val t = SystemClock.elapsedRealtime()
        if (t - paletteAutoLe < 30_000L) return
        paletteAutoLe = t
        val j = jourMaintenant()
        if (j == Palette.jour) return
        val e = Etat.courant
        if (e.enMarche && e.assistant in ASSISTANT_OCCUPE) return
        if (Palette.reglerJour(j)) {
            journal("palette ${Palette.jeu.nom} (selon l'heure)")
            reconstruire()
        }
    }

    /** « 20 degrés, allumée, 7 h 12 » écrits dans les couleurs du jeu [j] (aperçu de Réglages, Apparence). */
    private fun apercuPalette(j: Palette.Jeu): CharSequence {
        val sb = android.text.SpannableStringBuilder()
        fun morceau(t: String, couleur: Int) {
            val d = sb.length
            sb.append(t)
            sb.setSpan(android.text.style.ForegroundColorSpan(couleur), d, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        }
        morceau("20 degrés", j.meteo)
        morceau(", ", j.texte2)
        morceau("allumée", j.lumiere)
        morceau(", ", j.texte2)
        morceau("7 h 12", j.sante)
        return sb
    }

    /**
     * Section Apparence des réglages de la tablette (0.19.0, revue design des palettes) : le mode Selon
     * l'heure en tête, puis une ligne par jeu avec un aperçu en contexte écrit dans ses couleurs. Le bouton du
     * choix en cours prend la couleur de l'assistant du jeu. 10 s après un changement, « Revenir à ... ».
     */
    private fun construireApparence(): View {
        val col = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(4), dp(4), dp(4), dp(8))
        }
        col.addView(texte(30f, Palette.texte1).apply { text = "Apparence" }, marge(bas = 4))
        col.addView(texte(16f, Palette.texte2).apply {
            text = "Palette de couleurs, appliquée tout de suite à tous les écrans"
        }, marge(haut = 4, bas = 14))
        val ancien = retourPalette
        val reste = retourPaletteJusqua - SystemClock.elapsedRealtime()
        if (ancien != null && reste > 0) {
            val b = boutonDiscret("Revenir à $ancien", 52) { horloge.post { choisirPalette(ancien, retour = false) } }
            col.addView(b, marge(bas = 14, largeur = LinearLayout.LayoutParams.WRAP_CONTENT))
            horloge.postDelayed({ b.visibility = View.GONE }, reste)
        }
        val jourVu = Apparence.jour(Etat.courant.soleil, System.currentTimeMillis(), java.util.Calendar.getInstance().get(java.util.Calendar.HOUR_OF_DAY))
        val lignes = listOf(Triple(Palette.AUTO, "Pastels le jour, Veillée après le coucher du soleil", if (jourVu) Palette.PASTELS else Palette.VEILLEE)) +
            Palette.JEUX.map { Triple(it.nom, it.esprit, it) }
        for ((nom, esprit, j) in lignes) {
            val actif = nom == Palette.choix
            val ligne = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                minimumHeight = dp(75)
                setPadding(dp(16), dp(8), dp(16), dp(8))
                if (actif) background = GradientDrawable().apply {
                    cornerRadius = dp(11).toFloat()
                    setColor(Palette.selection)
                }
                isClickable = true
                isFocusable = true
                contentDescription = "Palette $nom" + if (actif) ", choisie" else ""
                setOnClickListener { horloge.post { choisirPalette(nom) } }
            }
            val anneau = FrameLayout(this).apply {
                background = GradientDrawable().apply {
                    shape = GradientDrawable.OVAL
                    setStroke(dp(2), if (actif) j.assistant else Palette.texteEteint)
                }
            }
            if (actif) anneau.addView(View(this).apply { background = rond(j.assistant, 10) }, FrameLayout.LayoutParams(dp(10), dp(10), Gravity.CENTER))
            ligne.addView(anneau, LinearLayout.LayoutParams(dp(22), dp(22)))
            val noms = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
            noms.addView(texte(19.5f, Palette.texte1).apply { text = nom })
            noms.addView(texte(14f, Palette.texte3).apply { text = esprit })
            ligne.addView(noms, LinearLayout.LayoutParams(dp(300), LinearLayout.LayoutParams.WRAP_CONTENT).apply { marginStart = dp(20) })
            ligne.addView(texte(19.5f, j.texte2).apply {
                // Selon l'heure : l'aperçu du jour, puis la suite du soir en texte tertiaire (maquette).
                text = if (nom == Palette.AUTO) android.text.SpannableStringBuilder(apercuPalette(Palette.PASTELS)).apply {
                    val d = length
                    append(", puis Veillée le soir")
                    setSpan(android.text.style.ForegroundColorSpan(Palette.PASTELS.texte3), d, length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
                } else apercuPalette(j)
                contentDescription = "Aperçu de la palette $nom"
            }, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply { marginStart = dp(12) })
            col.addView(ligne, marge(bas = 6))
        }
        col.addView(texte(15f, Palette.texte3).apply {
            text = "Aussi à la voix : « mets la palette Méditerranée », ou « palette suivante »"
        }, marge(haut = 12))
        return col
    }

    override fun onStart() {
        super.onStart()
        demarree = true
        journal("onStart")
        Station.ecranVisible = true
        capteurLumiere.brancher()
        abonner()
        registerReceiver(batterie, IntentFilter(Intent.ACTION_BATTERY_CHANGED))?.let { batterie.onReceive(this, it) }
        // Écran Musique resté ouvert : les enceintes sont de nouveau relues.
        if (ecranMusique?.vue?.visibility == View.VISIBLE) Etat.actionSuivreEnceintes?.invoke(true)
        if (ecranMaison?.vue?.visibility == View.VISIBLE) Etat.actionSuivreAppareils?.invoke(true)
    }

    override fun onResume() {
        super.onResume()
        auPremierPlan = true
        majBatterie()
        appliquerStation()
        relancerSiStation()
        cleStation = ""
        afficherStation()
        reprendreAffichage("onResume")
    }

    override fun onPause() {
        auPremierPlan = false
        journal("onPause")
        masquerSante()
        super.onPause()
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        setIntent(intent)
        relancerSiStation()
        demoLumieres(intent)
    }

    /**
     * Démonstration de l'animation d'une action sur des lumières (0.17.5), sans rien envoyer à Home
     * Assistant, pour la voir ou la filmer sans toucher à l'appartement :
     * `adb shell am start -n assistant.vocal.jarvis/.MainActivity --es demo_lumieres light.salon_plafond --es demo_effet allumer`
     * (effet : allumer, eteindre ou regler). Une carte « démonstration » naît de l'orbe et l'aperçu 3D
     * joue l'effet, les lampes visées gardant l'état joué au lieu de celui de HA.
     */
    private fun demoLumieres(i: Intent?) {
        if (!BuildConfig.DEBUG || i == null) return
        // Bloc Musique de l'accueil (0.18.0), sans rien faire jouer : `--es demo_musique "Titre|Artiste"`. Le
        // lecteur est fictif (media_player.demonstration) : ses boutons ne peuvent toucher aucune enceinte.
        i.getStringExtra("demo_musique")?.let { m ->
            i.removeExtra("demo_musique")
            val (titre, artiste) = m.split('|').let { (it.getOrNull(0) ?: "").take(80) to (it.getOrNull(1) ?: "").take(80) }
            toucherLe = SystemClock.elapsedRealtime()
            val l = Etat.Lecteur(
                "media_player.demonstration", "Démonstration", "playing", titre, artiste, "", 0.0, 0.0, 0L, 0.3,
                setOfNotNull(SortieSon.ENCEINTES.firstOrNull()?.first),
            )
            Etat.modifier { it.copy(lecteurs = listOf(l)) }
        }
        // Lecture des prévisions (0.18.0), en lecture seule (états, sun.sun, weather.get_forecasts) pour le
        // futur panneau Météo : `--es test_previsions 1`, résultat dans `adb logcat -s JarvisMeteo JarvisEcran`.
        if (i.getStringExtra("test_previsions") != null) {
            i.removeExtra("test_previsions")
            Etat.actionPrevisions?.invoke { l ->
                journal("prévisions : ${l.horaire.size} heures, ${l.journalier.size} jours (${l.typeJours}), actuel ${l.actuel != null}, " +
                    "soleil ${l.soleil != null}, erreur « ${l.erreur} », code ${l.code}, réponse ${l.reponse}")
            }
        }
        // Santé de l'accueil (0.19.0) avec des valeurs fictives, 20 s, sans le serveur ni la vision :
        // `--es demo_sante 432,4210` (minutes de sommeil, pas). Seulement dans l'appli de débogage.
        i.getStringExtra("demo_sante")?.let { v ->
            i.removeExtra("demo_sante")
            val n = v.split(',').map { it.trim().toIntOrNull() }
            toucherLe = SystemClock.elapsedRealtime()
            // 0.26.0 : 7 nuits et cœur au repos fictifs (`--es demo_sante 425,5320` ; `0,0` pour le matin tôt).
            val nuitDemo = n.getOrNull(0)?.takeIf { it > 0 }
            ambiant?.demoSante(
                Sante.Resume(nuitDemo, n.getOrNull(1), listOf(400, 440, 350, 465, 415, 490, nuitDemo), listOf(56, 55, 57, 54, 55, 53, 54), "7 h 10"),
                20_000L,
            )
        }
        // Essai de la santé du PC (0.21.0) : `--es test_sante 1`. Le journal ne dit que ce qui est présent,
        // jamais une valeur (adb logcat -s JarvisSante).
        if (i.getStringExtra("test_sante") != null) {
            i.removeExtra("test_sante")
            val action = Etat.actionSante
            if (action == null) android.util.Log.i("JarvisSante", "essai : pas de connexion au PC")
            else action { r -> android.util.Log.i("JarvisSante", "essai : " + SanteDetail.presence(r)) }
        }
        // Essai de l'historique de santé (0.22.0, serveur 0.20) : `--es test_sante_historique 1`. Les cinq demandes,
        // puis, pour chacune, les champs attendus qui manquent, jamais une valeur (adb logcat -s JarvisSante).
        if (i.getStringExtra("test_sante_historique") != null) {
            i.removeExtra("test_sante_historique")
            essaiHistorique()
        }
        // Panneau Santé (0.21.0) avec des valeurs fictives, sans le serveur ni la vision : `--es demo_sante_panneau 1`.
        // `--es demo_sante_panneau protege` : mêmes valeurs fictives, fenêtre protégée comme pour de vraies valeurs
        // (essai de FLAG_SECURE et de la capture des applis récentes). Onglet choisi (0.22.0) : `tendances`,
        // `seances`, `records` ou `jour`, seul ou après `protege,`.
        i.getStringExtra("demo_sante_panneau")?.let { mode ->
            i.removeExtra("demo_sante_panneau")
            toucherLe = SystemClock.elapsedRealtime()
            val mots = mode.split(',').map { it.trim() }
            ecranSante?.let { s ->
                fermerMusique()
                fermerMaison()
                fermerMeteo()
                s.demo(protegee = "protege" in mots, nom = mots.firstOrNull { it in setOf("tendances", "seances", "records", "jour") } ?: "aujourdhui")
                majVeille()
                majSecurite()
            }
        }
        // Pièces allumées sur le plan de l'accueil (0.18.0), sans rien envoyer à Home Assistant, 20 s :
        // `--es demo_repos light.salon_plafond,light.salon_lampe_tele`.
        i.getStringExtra("demo_repos")?.let { r ->
            i.removeExtra("demo_repos")
            val ids = r.split(',').map { it.trim() }.filter { Regex("""^light\.[a-z0-9_]+$""").matches(it) }.toSet()
            toucherLe = SystemClock.elapsedRealtime()
            if (ids.isNotEmpty()) ambiant?.plan?.demoRepos(ids, 20_000L)
        }
        val brut = i.getStringExtra("demo_lumieres") ?: return
        i.removeExtra("demo_lumieres")
        val liste = brut.split(',').map { it.trim() }.filter { Regex("""^light\.[a-z0-9_]+$""").matches(it) }
        if (liste.isEmpty()) return
        val effet = i.getStringExtra("demo_effet")?.takeIf { it in setOf("allumer", "eteindre", "regler") } ?: "allumer"
        journal("démonstration : $effet ${liste.joinToString(", ")}")
        // Comme une commande : l'écran reprend vie avant que la carte n'arrive.
        toucherLe = SystemClock.elapsedRealtime()
        majVeille()
        val maintenant = SystemClock.elapsedRealtime()
        val carte = Etat.Carte(
            -maintenant, false, "Démonstration", if (effet == "eteindre") "éteinte" else "allumée",
            null, "", "", "jarvis", false, "", "demo", maintenant, liste, liste.associateWith { effet },
        )
        // Phrase comprise et réponse de l'accueil (0.18.0), sans voix : `--es demo_phrase "Allume le salon"
        // --es demo_reponse "C'est fait, le salon est allumé."`. Elles restent écrites une dizaine de secondes.
        val phrase = i.getStringExtra("demo_phrase")?.take(200) ?: ""
        val reponse = i.getStringExtra("demo_reponse")?.take(400) ?: ""
        i.removeExtra("demo_phrase")
        i.removeExtra("demo_reponse")
        Etat.modifier {
            if (reponse.isEmpty()) it.copy(cartes = listOf(carte))
            else it.copy(cartes = listOf(carte), entendu = phrase, entenduFinal = true, parole = reponse, paroleFinLe = maintenant + 4_000L)
        }
    }

    override fun onStop() {
        demarree = false
        journal("onStop")
        Station.ecranVisible = false
        capteurLumiere.debrancher()
        desabonner()
        cacherAccueil()
        // Écran caché : plus de lecture des enceintes ni des appareils toutes les 3 s.
        if (ecranMusique?.vue?.visibility == View.VISIBLE) Etat.actionSuivreEnceintes?.invoke(false)
        if (ecranMaison?.vue?.visibility == View.VISIBLE) Etat.actionSuivreAppareils?.invoke(false)
        try {
            unregisterReceiver(batterie)
        } catch (_: Exception) {
        }
        super.onStop()
    }

    override fun onWindowFocusChanged(hasFocus: Boolean) {
        super.onWindowFocusChanged(hasFocus)
        journal("focus ${if (hasFocus) "gagné" else "perdu"}")
        if (hasFocus) {
            immersifApplique = false
            appliquerImmersif()
            reprendreAffichage("focus")
        }
    }

    // ---------------------------------------------------------------- reprise de l'affichage (0.17.3)

    private fun journal(message: String) {
        android.util.Log.i(JOURNAL, message)
    }

    private fun interactif(): Boolean = (getSystemService(POWER_SERVICE) as? PowerManager)?.isInteractive ?: true

    /**
     * Activité cachée ou écran éteint (0.18.0) : le plan 3D de l'accueil est masqué et suspendu tout de
     * suite (majVeille ne tourne plus), et ses lumières ne sont plus relues.
     */
    private fun cacherAccueil() {
        masquerSante()
        ambiant?.plan?.regler(0f, false, false)
        suivreLumieres(false)
    }

    /** Écouteur d'Etat et horloge de la seconde. Rend vrai si l'abonnement vient d'être pris (écran déjà repeint). */
    private fun abonner(): Boolean {
        horloge.removeCallbacks(tic)
        horloge.post(tic)
        if (abonne) return false
        abonne = true
        Etat.ajouter(ecouteur)
        return true
    }

    private fun desabonner() {
        abonne = false
        Etat.retirer(ecouteur)
        horloge.removeCallbacks(tic)
        horloge.removeCallbacks(animVeille)
    }

    /**
     * Reprise de l'affichage. Démarrée écran éteint (installation par adb, tablette qui démarre en station),
     * l'activité pouvait réapparaître à l'allumage sans que rien ne la fasse revivre : l'écouteur d'Etat et
     * l'horloge n'étaient repris qu'à onStart, et les animations des vues s'arrêtaient pour de bon quand
     * leur image tombait écran éteint. Ici tout est relancé, à chacun des signaux possibles : onResume,
     * retour du focus, allumage de l'écran (diffusion et DisplayManager). Rien si l'activité n'est ni
     * démarrée ni au premier plan (écran allumé sur une autre appli).
     */
    private fun reprendreAffichage(raison: String) {
        val focus = hasWindowFocus()
        val image = if (derniereImageLe == 0L) "aucune" else "il y a ${(SystemClock.elapsedRealtime() - derniereImageLe) / 1000} s"
        journal(
            "reprise ($raison) : démarrée $demarree, premier plan $auPremierPlan, focus $focus, écran " +
                "${if (interactif()) "allumé" else "éteint"}, dernière image $image, interface ${racineVue?.width} x ${racineVue?.height}",
        )
        if (!demarree && !focus) return
        if (focus) Station.ecranVisible = true
        // Écouteur repris s'il manquait (il repeint alors l'écran), sinon l'écran est repeint ici.
        if (!abonner()) afficher(Etat.courant)
        if (::orbe.isInitialized) orbe.reprendreRendu()
        ambiant?.reprendreRendu()
        luminositeAppliquee = -2f
        majVeille()
        racineVue?.requestLayout()
        window.decorView.invalidate()
        // Service : la demande part de l'activité affichée, ce qui lui rend le micro et la caméra refusés à
        // un service lancé écran éteint, et lui fait revoir passerelle et vision sans attendre.
        val maintenant = SystemClock.elapsedRealtime()
        if (Etat.courant.enMarche && (auPremierPlan || focus) && interactif() && maintenant - repriseServiceLe > 2_000L) {
            repriseServiceLe = maintenant
            try {
                startForegroundService(Intent(this, SatelliteService::class.java).setAction(SatelliteService.ACTION_REPRENDRE))
            } catch (e: Exception) {
                journal("reprise du service impossible : ${e.javaClass.simpleName}")
            }
        }
    }

    /** Suivi de l'état de la dalle (allumée, AOD, éteinte) : le retour à l'état allumé relance l'affichage. */
    private fun suivreDalle() {
        val dm = getSystemService(android.hardware.display.DisplayManager::class.java) ?: return
        etatDalle = dm.getDisplay(android.view.Display.DEFAULT_DISPLAY)?.state ?: android.view.Display.STATE_UNKNOWN
        journal("dalle ${nomEtatDalle(etatDalle)}")
        val suivi = object : android.hardware.display.DisplayManager.DisplayListener {
            override fun onDisplayAdded(id: Int) {}
            override fun onDisplayRemoved(id: Int) {}
            override fun onDisplayChanged(id: Int) {
                if (id != android.view.Display.DEFAULT_DISPLAY) return
                val etat = dm.getDisplay(id)?.state ?: return
                if (etat == etatDalle) return
                journal("dalle : ${nomEtatDalle(etatDalle)}, puis ${nomEtatDalle(etat)}")
                etatDalle = etat
                if (etat == android.view.Display.STATE_ON) reprendreAffichage("dalle allumée")
            }
        }
        dm.registerDisplayListener(suivi, horloge)
        suiviDalle = suivi
    }

    private fun nomEtatDalle(etat: Int): String = when (etat) {
        android.view.Display.STATE_ON -> "allumée"
        android.view.Display.STATE_OFF -> "éteinte"
        android.view.Display.STATE_DOZE -> "en AOD"
        android.view.Display.STATE_DOZE_SUSPEND -> "en AOD figé"
        else -> "état $etat"
    }

    /**
     * Un toucher rallume l'écran et montre les textes d'état. Sur l'écran ambiant endormi (protection
     * OLED), ce premier geste ne fait que réveiller : il n'appuie sur aucun bouton invisible.
     */
    override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
        if (ev.actionMasked == MotionEvent.ACTION_DOWN) {
            val endormi = ambiant != null && veille.regime != Veille.Regime.VIVANT
            toucherLe = SystemClock.elapsedRealtime()
            majVeille()
            avalerGeste = endormi
        }
        if (avalerGeste) {
            if (ev.actionMasked == MotionEvent.ACTION_UP || ev.actionMasked == MotionEvent.ACTION_CANCEL) avalerGeste = false
            return true
        }
        return super.dispatchTouchEvent(ev)
    }

    override fun onDestroy() {
        journal("onDestroy")
        dialogueAppairage?.dismiss()
        ecranMaison?.fermerDialogues()
        ecranMaison?.liberer()
        ambiant?.liberer()
        try {
            unregisterReceiver(ecranAllume)
        } catch (_: Exception) {
        }
        suiviDalle?.let { getSystemService(android.hardware.display.DisplayManager::class.java)?.unregisterDisplayListener(it) }
        if (Build.VERSION.SDK_INT >= 29) {
            (suiviThermique as? PowerManager.OnThermalStatusChangedListener)?.let { getSystemService(PowerManager::class.java)?.removeThermalStatusListener(it) }
        }
        suiviThermique = null
        suiviDalle = null
        window.decorView.viewTreeObserver.let { if (it.isAlive) it.removeOnDrawListener(dessinFenetre) }
        horloge.removeCallbacksAndMessages(null)
        if (Build.VERSION.SDK_INT >= 33) {
            (rappelRetour as? android.window.OnBackInvokedCallback)?.let { onBackInvokedDispatcher.unregisterOnBackInvokedCallback(it) }
        }
        rappelRetour = null
        super.onDestroy()
    }

    /** Rappel du bouton Retour (Android 13 et plus), gardé pour le retirer à la destruction. */
    private var rappelRetour: Any? = null

    @Deprecated("Android 13 et plus passent par OnBackInvokedCallback")
    @Suppress("OVERRIDE_DEPRECATION")
    override fun onBackPressed() {
        retour()
    }

    /**
     * Bouton Retour : ferme le panneau ouvert. Sur l'écran ambiant ou en station, sans effet sinon :
     * l'appli n'est jamais quittée. Sur le téléphone hors station, l'appli passe derrière, comme d'habitude.
     */
    private fun retour() {
        // Vue d'un jour passé de la santé : Retour ramène à l'onglet d'origine, pas à l'accueil.
        if (ecranSante?.retour() == true) return
        if (fermerPanneaux()) return
        if (ambiant != null || SatelliteService.station(this)) return
        moveTaskToBack(true)
    }

    // ---------------------------------------------------------------- briques graphiques

    private fun dp(v: Int): Int = Decor.dp(this, v.toFloat())

    /** Taille de texte selon l'écran : téléphone, ou tablette. */
    private fun taille(petit: Float, grand: Float): Float = if (grandeTaille) grand else petit

    private fun rond(couleur: Int, tailleDp: Int): GradientDrawable =
        GradientDrawable().apply {
            shape = GradientDrawable.OVAL
            setColor(couleur)
            setSize(dp(tailleDp), dp(tailleDp))
        }

    private fun texte(taille: Float, couleur: Int = Couleur.TEXTE, gras: Boolean = false): TextView =
        TextView(this).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, taille)
            setTextColor(couleur)
            // Tablette (0.18.0) : Instrument Sans, comme l'accueil. Le téléphone garde les polices du système.
            if (largeEcran) typeface = Polices.texte(this@MainActivity, if (gras) 500 else 400)
            else if (gras) typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
            setLineSpacing(0f, 1.15f)
        }

    /**
     * Petit intitulé des cartes (titres de cartes, « Toi », nom de l'assistant). En capitales espacées sur le
     * téléphone, en casse normale sur la tablette (0.18.0).
     */
    private fun intitule(libelle: String, couleur: Int = Couleur.TEXTE_2): TextView =
        if (largeEcran) texte(15.5f, couleur, gras = true).apply { text = libelle }
        else texte(taille(12.5f, 13.5f), couleur, gras = true).apply {
            text = libelle.uppercase(Locale.FRANCE)
            letterSpacing = 0.1f
        }

    private fun bouton(libelle: String, couleur: Int, hauteurDp: Int = 56, action: () -> Unit): TextView =
        texte(17f, Palette.texteSurAccent, gras = true).apply {
            text = libelle
            gravity = Gravity.CENTER
            minHeight = dp(hauteurDp)
            setPadding(dp(20), dp(10), dp(20), dp(10))
            background = Decor.fondBouton(this@MainActivity, couleur, 16f)
            Decor.relief(this, 3f)
            isClickable = true
            isFocusable = true
            setOnClickListener { action() }
        }

    /** Bouton secondaire, gris en relief, texte clair. */
    private fun boutonDiscret(libelle: String, hauteurDp: Int = 52, action: () -> Unit): TextView =
        bouton(libelle, Couleur.CHAMP, hauteurDp, action).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 15.5f)
            setTextColor(Couleur.TEXTE)
            background = Decor.fondBouton(this@MainActivity, Couleur.CHAMP, 14f, null)
        }

    private fun activer(vue: View, actif: Boolean) {
        vue.isEnabled = actif
        vue.alpha = if (actif) 1f else 0.35f
    }

    private fun marge(haut: Int = 0, bas: Int = 0, largeur: Int = LinearLayout.LayoutParams.MATCH_PARENT) =
        LinearLayout.LayoutParams(largeur, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
            topMargin = dp(haut)
            bottomMargin = dp(bas)
        }

    private fun carte(titre: String?, sousTitre: String? = null): LinearLayout {
        val c = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = Decor.fondCarte(this@MainActivity)
            val cote = if (largeEcran) 18 else 20
            setPadding(dp(cote), dp(18), dp(cote), dp(20))
        }
        Decor.relief(c, 6f)
        if (titre != null) c.addView(intitule(titre), marge(bas = if (sousTitre == null) 12 else 2))
        if (sousTitre != null) {
            c.addView(texte(13f, Couleur.GRIS).apply { text = sousTitre }, marge(bas = 12))
        }
        return c
    }

    // ---------------------------------------------------------------- construction

    /** Oublie ce qui est peint, pour que la nouvelle interface soit entièrement repeinte. */
    private fun oublierAffichage() {
        cleMode = ""
        cleTranscription = ""
        cleBoutonsTranscription = ""
        cleSegments = ""
        cleReveil = ""
        cleServeur = ""
        cleStation = ""
        cleVision = ""
        cleCoupure = ""
        cleDirect = ""
        // Plan 3D de l'ancien accueil libéré (WebView détruite), lumières plus relues pour lui.
        ambiant?.liberer()
        ambiant = null
        suivreLumieres(false)
        // L'écran Musique ouvert disparaît avec l'ancienne interface : les enceintes ne sont plus relues.
        if (ecranMusique?.vue?.visibility == View.VISIBLE) Etat.actionSuivreEnceintes?.invoke(false)
        ecranMusique = null
        if (ecranMaison?.vue?.visibility == View.VISIBLE) Etat.actionSuivreAppareils?.invoke(false)
        ecranMaison?.fermerDialogues()
        ecranMaison?.liberer()
        ecranMaison = null
        ecranMeteo = null
        ecranSante?.fermer()
        ecranSante = null
        // Nouvelle interface : la luminosité sera réappliquée.
        luminositeAppliquee = -2f
        regimeApplique = null
        versionVue = null
        racineVue = null
        decalageMinute = Long.MIN_VALUE
        derouleAffiche = null
        historiqueAffiche = null
        historiqueReponse = null
        reponseVue = null
        cleMarche = ""
        panneauReglages = null
        panneauHistorique = null
        boutonPanneau = null
    }

    private fun construireInterface(): View {
        oublierAffichage()
        val config = resources.configuration
        grandeTaille = config.smallestScreenWidthDp >= 600
        largeEcran = config.screenWidthDp >= LARGEUR_PANNEAUX_DP && config.screenHeightDp >= 480

        val entete = construireEntete()
        val poste = construirePoste()
        val reponse = construireCarteReponse()
        val deroule = construireDeroule()
        val historique = construireHistorique()
        val carteServeur = construireServeur()
        val carteMode = construireMode()
        val carteReveil = construireReveil()
        val carteSons = construireSons()
        val carteTranscription = construireTranscription()
        val carteCerveau = construireCerveau()
        val carteStation = construireStation()
        val carteVision = construireVision()
        val carteConnexion = construireReglages()
        val reglages = listOf(
            carteServeur, carteMode, carteReveil, carteSons, carteTranscription, carteCerveau, carteStation, carteVision, carteConnexion,
        )
        // Pied d'écran hors du défilement : la version se voit toujours (règle du propriétaire). Sur l'écran
        // ambiant (OLED), en gris sombre, au toucher et 10 s après une commande (cahier de l'écran).
        val libelleVersion = "Version ${BuildConfig.VERSION_BASE}, ${BuildConfig.UTILISATEUR}, compilée le ${BuildConfig.HORODATAGE_COMPILATION}"
        val version = texte(12.5f, Couleur.GRIS).apply {
            text = libelleVersion
            gravity = Gravity.CENTER_HORIZONTAL
            setPadding(0, dp(6), 0, 0)
        }

        val corps: View = if (largeEcran) {
            // Accueil typographique (0.18.0) : plan 3D, heure, météo, musique, lumière de l'assistant. Le poste
            // (orbe et textes du téléphone) est construit mais pas affiché : l'accueil lit Etat lui-même.
            val a = EcranAmbiant(this)
            ambiant = a
            a.libelleVersion = libelleVersion
            a.suiviMusique = suiviMusique
            a.surSecurite = { majSecurite() }
            val musique = EcranMusique(this, a.musique) { fermerMusique() }
            ecranMusique = musique
            a.surMusique = { ouvrirMusique() }
            val maison = EcranMaison(this) { fermerMaison() }
            ecranMaison = maison
            a.surMaison = { ouvrirMaison() }
            // Panneau Météo (0.20.0) : en touchant les phrases de l'accueil.
            val meteo = EcranMeteo(this) { fermerMeteo() }
            ecranMeteo = meteo
            a.surMeteo = { ouvrirMeteo(null) }
            // Panneau Santé (0.21.0) : en touchant les lignes de santé, le propriétaire seul devant la tablette.
            val sante = EcranSante(this) { fermerSante() }
            sante.surSecurite = { majSecurite() }
            ecranSante = sante
            a.surSante = { ouvrirSante() }
            a.surParler = { parler() }
            a.jour = { jourMaintenant() }
            a.sombre = { lumiere.sombre() }
            a.surReglages = { basculerReglages() }
            a.surDemarrer = { demarrer() }
            a.surAppareils = { ouvrirAppareils() }
            // Santé du propriétaire (0.19.0) : demandée au PC par le service, lue ici, gardée par l'accueil seulement.
            a.salutation = salutation
            a.surDemanderSante = { suite ->
                val action = Etat.actionSante
                if (action == null) suite(null) else action { r -> suite(Sante.lire(r, Sante.aujourdhui())) }
            }
            val ecran = a.vue
            // Réglages par sections (0.17.0) : sections à gauche, contenu à droite, le déroulé technique
            // dans Diagnostic. Panneau plein écran, presque noir.
            val vueReglages = construireSections(
                entete,
                listOf(
                    Section("general", "Général", listOf(carteServeur, carteMode, carteConnexion)),
                    Section("apparence", "Apparence", listOf(construireApparence())),
                    Section("voix", "Voix et réveil", listOf(carteReveil, carteSons, carteTranscription)),
                    Section("comprehension", "Compréhension", listOf(carteCerveau)),
                    Section("vision", "Vision et visages", listOf(carteVision)),
                    Section("station", "Station", listOf(carteStation)),
                    Section("acces", "Appareils et accès", listOf(construireAcces())),
                    Section("historique", "Historique", listOf(historique)),
                    Section("diagnostic", "Diagnostic", listOf(deroule)),
                ),
            )
            val pile = FrameLayout(this).apply { clipChildren = false }
            pile.addView(ecran)
            pile.addView(musique.vue, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
            pile.addView(maison.vue, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
            pile.addView(meteo.vue, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
            pile.addView(sante.vue, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
            pile.addView(
                vueReglages,
                FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT),
            )
            panneauReglages = vueReglages
            pile
        } else {
            val colonne = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                clipChildren = false
                setPadding(dp(4), 0, dp(4), 0)
            }
            colonne.addView(entete, marge(bas = 4))
            colonne.addView(poste, marge(bas = 12))
            colonne.addView(reponse, marge(bas = 16))
            val tiroir = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                clipChildren = false
            }
            for (v in listOf(deroule, historique) + reglages) tiroir.addView(v, marge(bas = 16))
            colonne.addView(tiroir, marge())
            panneauReglages = tiroir
            ScrollView(this).apply {
                isFillViewport = true
                clipToPadding = false
                isVerticalScrollBarEnabled = false
                addView(colonne)
            }
        }
        appliquerPanneauReglages(prefsInterface().getBoolean(CLE_REGLAGES_OUVERTS, false))

        // Écran ambiant : noir pur partout (OLED, un pixel noir est éteint), fenêtre comprise.
        if (largeEcran) window.setBackgroundDrawable(android.graphics.drawable.ColorDrawable(Palette.fond))
        val racine = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = if (largeEcran) android.graphics.drawable.ColorDrawable(Palette.fond) else Decor.fondEcran(this@MainActivity)
            clipChildren = false
            addView(corps, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
            // Tablette (0.18.0) : la version est dans l'accueil, au toucher, et dans l'en-tête des réglages.
            if (!largeEcran) {
                addView(version, marge())
                versionVue = version
            }
        }
        racineVue = racine

        // Affichage bord à bord imposé sur Android 15 : on recule le contenu sous la barre
        // d'état, au-dessus de la barre de navigation et du clavier, et loin des encoches.
        racine.setOnApplyWindowInsetsListener { v, insets ->
            val (g, h, d, b) = if (Build.VERSION.SDK_INT >= 30) {
                val i = insets.getInsets(
                    WindowInsets.Type.systemBars() or WindowInsets.Type.ime() or WindowInsets.Type.displayCutout()
                )
                listOf(i.left, i.top, i.right, i.bottom)
            } else {
                @Suppress("DEPRECATION")
                listOf(
                    insets.systemWindowInsetLeft, insets.systemWindowInsetTop,
                    insets.systemWindowInsetRight, insets.systemWindowInsetBottom,
                )
            }
            // Tablette : l'accueil occupe tout l'écran (maquette en plein écran), les panneaux ont leurs marges.
            if (largeEcran) v.setPadding(g, h, d, b)
            else v.setPadding(g + dp(12), h + dp(14), d + dp(12), b + dp(8))
            insets
        }
        if (largeEcran) racine.setPadding(0, 0, 0, 0) else racine.setPadding(dp(12), dp(14), dp(12), dp(8))
        return racine
    }

    private fun prefsInterface() = getSharedPreferences(PREFS_INTERFACE, MODE_PRIVATE)

    /** Ouvre ou replie les réglages, et met le bouton à jour. */
    private fun appliquerPanneauReglages(ouverts: Boolean) {
        panneauReglages?.visibility = if (ouverts) View.VISIBLE else View.GONE
        panneauHistorique?.visibility = if (ouverts) View.GONE else View.VISIBLE
        boutonPanneau?.text = if (ouverts) (if (largeEcran) "Fermer" else "Masquer les réglages") else "Réglages"
    }

    private fun basculerReglages() {
        val ouverts = panneauReglages?.visibility != View.VISIBLE
        if (ouverts) {
            fermerMusique()
            fermerMaison()
        }
        prefsInterface().edit().putBoolean(CLE_REGLAGES_OUVERTS, ouverts).apply()
        appliquerPanneauReglages(ouverts)
    }

    /** Écran Musique (0.17.0) : par-dessus l'écran ambiant, les enceintes relues tant qu'il est ouvert. */
    private fun ouvrirMusique() {
        val m = ecranMusique ?: return
        fermerMaison()
        if (panneauReglages?.visibility == View.VISIBLE) {
            prefsInterface().edit().putBoolean(CLE_REGLAGES_OUVERTS, false).apply()
            appliquerPanneauReglages(false)
        }
        m.vue.visibility = View.VISIBLE
        Etat.actionSuivreEnceintes?.invoke(true)
        m.maj(Etat.courant)
    }

    /** Écran Maison connectée (0.17.0) : par-dessus l'écran ambiant, les appareils relus tant qu'il est ouvert. */
    private fun ouvrirMaison() {
        val m = ecranMaison ?: return
        fermerMusique()
        if (panneauReglages?.visibility == View.VISIBLE) {
            prefsInterface().edit().putBoolean(CLE_REGLAGES_OUVERTS, false).apply()
            appliquerPanneauReglages(false)
        }
        m.vue.visibility = View.VISIBLE
        Etat.actionSuivreAppareils?.invoke(true)
        m.maj(Etat.courant)
    }

    /** Panneau Météo (0.20.0) : par-dessus l'accueil. [d] : la réponse à une question posée à la voix (0.25.0), ou null. */
    private fun ouvrirMeteo(d: MeteoQuestion.Reponse?) {
        val m = ecranMeteo ?: return
        // La santé d'abord : jamais sous un autre panneau (0.21.1).
        fermerSante()
        fermerMusique()
        fermerMaison()
        if (panneauReglages?.visibility == View.VISIBLE) {
            prefsInterface().edit().putBoolean(CLE_REGLAGES_OUVERTS, false).apply()
            appliquerPanneauReglages(false)
        }
        m.ouvrir(d)
        majVeille()
    }

    /** Panneau Santé (0.21.0) : seulement pour le propriétaire seul devant la tablette. */
    private fun ouvrirSante() {
        val m = ecranSante ?: return
        fermerMusique()
        fermerMaison()
        fermerMeteo()
        if (panneauReglages?.visibility == View.VISIBLE) {
            prefsInterface().edit().putBoolean(CLE_REGLAGES_OUVERTS, false).apply()
            appliquerPanneauReglages(false)
        }
        if (m.ouvrir()) majVeille()
        majSecurite()
    }

    /**
     * Essai de l'historique de santé (appli de débogage) : les cinq messages du serveur 0.20, la période à 30 et
     * à 90 jours (courbes par jour et par semaine), la séance la plus récente de la liste, la veille. Le journal
     * ne dit que les champs attendus qui manquent, rien ne s'affiche, rien n'est gardé.
     */
    private fun essaiHistorique() {
        val action = Etat.actionSanteHistorique
        if (action == null || !Etat.historiqueSante()) {
            android.util.Log.i("JarvisSante", "essai historique : pas de capacité sante_historique")
            return
        }
        fun journal(type: String, r: org.json.JSONObject?) = android.util.Log.i("JarvisSante", "essai historique : " + SanteHisto.presence(type, r))
        fun corps(type: String) = org.json.JSONObject().put("type", type)
        val veille = SanteHisto.aujourdhui().minusDays(1).toString()
        val passe = SanteHisto.aujourdhui().minusDays(200).toString()
        action(corps("sante_periode").put("jours", 30)) { journal("sante_periode", it) }
        action(corps("sante_periode").put("jours", 90)) { journal("sante_periode", it) }
        // Fenêtres passées : la réponse doit finir le jour demandé, sans jour en cours.
        action(corps("sante_periode").put("jours", 7).put("au", veille)) { r ->
            journal("sante_periode", r)
            android.util.Log.i("JarvisSante", "essai historique : période au " + SanteHisto.presenceAu(r, veille))
        }
        action(corps("sante_seances").put("jours", 90).put("sport", "tous").put("au", passe)) { r ->
            journal("sante_seances", r)
            android.util.Log.i("JarvisSante", "essai historique : séances au " + SanteHisto.presenceAu(r, passe))
        }
        action(corps("sante_records")) { journal("sante_records", it) }
        action(corps("sante_jour").put("date", veille)) { journal("sante_jour", it) }
        action(corps("sante_seances").put("jours", 30).put("sport", "tous")) { r ->
            journal("sante_seances", r)
            val id = SanteHisto.seances(r)?.seances?.firstOrNull()?.id
            if (id == null) android.util.Log.i("JarvisSante", "essai historique : sante_seance non essayé, liste vide")
            else action(corps("sante_seance").put("seance_id", id)) { journal("sante_seance", it) }
        }
    }

    private fun fermerSante(): Boolean {
        val m = ecranSante ?: return false
        if (!m.ouvert) return false
        m.fermer()
        majVeille()
        majSecurite()
        return true
    }

    private fun fermerMeteo(): Boolean {
        val m = ecranMeteo ?: return false
        if (!m.ouvert) return false
        m.fermer()
        majVeille()
        return true
    }

    private fun fermerMaison(): Boolean {
        val m = ecranMaison ?: return false
        if (m.vue.visibility != View.VISIBLE) return false
        m.fermerDialogues()
        m.vue.visibility = View.GONE
        Etat.actionSuivreAppareils?.invoke(false)
        return true
    }

    private fun fermerMusique(): Boolean {
        val m = ecranMusique ?: return false
        if (m.vue.visibility != View.VISIBLE) return false
        m.vue.visibility = View.GONE
        Etat.actionSuivreEnceintes?.invoke(false)
        return true
    }

    /** Un panneau (Musique, Maison, Réglages) couvre l'écran ambiant. */
    private fun panneauOuvert(): Boolean =
        panneauReglages?.visibility == View.VISIBLE || ecranMusique?.vue?.visibility == View.VISIBLE ||
            ecranMaison?.vue?.visibility == View.VISIBLE || ecranMeteo?.ouvert == true || ecranSante?.ouvert == true

    /**
     * Ferme les panneaux ouverts par-dessus l'écran ambiant. Rend vrai s'il y en avait un (bouton
     * Retour). Sans effet sur le téléphone, dont les réglages font partie de la page.
     */
    private fun fermerPanneaux(): Boolean {
        if (ambiant == null) return false
        var ferme = fermerMusique()
        if (fermerMaison()) ferme = true
        if (fermerMeteo()) ferme = true
        if (fermerSante()) ferme = true
        if (panneauReglages?.visibility == View.VISIBLE) {
            prefsInterface().edit().putBoolean(CLE_REGLAGES_OUVERTS, false).apply()
            appliquerPanneauReglages(false)
            ferme = true
        }
        return ferme
    }

    /** Section du panneau des réglages de la tablette : identifiant, titre et cartes. */
    private class Section(val cle: String, val titre: String, val cartes: List<View>)

    /**
     * Panneau des réglages de la tablette (0.17.0) : l'en-tête, puis les sections à gauche et le contenu
     * de la section choisie à droite. La section choisie est retenue.
     */
    private fun construireSections(entete: View, sections: List<Section>): View {
        val contenu = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            clipChildren = false
            clipToPadding = false
        }
        val defile = ScrollView(this).apply {
            isFillViewport = true
            clipToPadding = false
            isVerticalScrollBarEnabled = false
            setPadding(dp(6), dp(4), dp(6), dp(8))
            addView(contenu)
        }
        val liste = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        val boutons = HashMap<String, TextView>()
        fun montrer(cle: String) {
            val s = sections.firstOrNull { it.cle == cle } ?: sections.first()
            prefsInterface().edit().putString(CLE_SECTION, s.cle).apply()
            contenu.removeAllViews()
            for (c in s.cartes) contenu.addView(c, marge(bas = 16))
            defile.scrollTo(0, 0)
            for ((k, b) in boutons) {
                val choisie = k == s.cle
                b.background = if (choisie) Decor.fondBouton(this, Couleur.ACCENT, 14f) else Decor.fondNeutre(this, 14f)
                b.setTextColor(if (choisie) Palette.texteSurAccent else Couleur.TEXTE_2)
            }
        }
        for (s in sections) {
            val b = texte(16f, Couleur.TEXTE_2, gras = true).apply {
                text = s.titre
                gravity = Gravity.CENTER_VERTICAL
                minHeight = dp(52)
                setPadding(dp(18), dp(8), dp(14), dp(8))
                isClickable = true
                isFocusable = true
                setOnClickListener { montrer(s.cle) }
            }
            boutons[s.cle] = b
            liste.addView(b, marge(bas = 6))
        }
        montrer(prefsInterface().getString(CLE_SECTION, null) ?: sections.first().cle)
        val colonnes = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(ScrollView(this@MainActivity).apply {
                isVerticalScrollBarEnabled = false
                addView(liste)
            }, LinearLayout.LayoutParams(dp(250), LinearLayout.LayoutParams.MATCH_PARENT))
            addView(defile, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.MATCH_PARENT, 1f).apply { marginStart = dp(20) })
        }
        return LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setBackgroundColor(Couleur.PANNEAU)
            setPadding(dp(18), dp(10), dp(18), dp(10))
            // Le toucher ne traverse pas vers les bulles.
            isClickable = true
            addView(entete, marge(bas = 12))
            addView(colonnes, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f))
        }
    }

    /** Carte Appareils et accès : téléphones appairés, demandes d'appairage, clés retenues. */
    private fun construireAcces(): LinearLayout {
        val c = carte("Appareils et accès", "téléphones et tablettes autorisés à parler à ${ConfigMaison.NOM_ASSISTANT}")
        c.addView(texte(14f, Couleur.TEXTE_2).apply {
            text = "Appairage d'un nouvel appareil par un code à 4 chiffres accepté depuis un appareil connu, " +
                "révocation qui coupe tout de suite, clés des serveurs retenues à la première connexion."
        }, marge(bas = 12))
        c.addView(boutonDiscret("Gérer les appareils") { ouvrirAppareils() })
        return c
    }

    private fun construireEntete(): View {
        val ligne = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            setPadding(dp(6), dp(4), dp(6), dp(4))
        }
        val titres = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        titres.addView(texte(taille(32f, 34f), gras = true).apply {
            text = ConfigMaison.NOM_ASSISTANT
            letterSpacing = 0.01f
        })
        titres.addView(texte(14.5f, Couleur.TEXTE_2).apply {
            text = if (largeEcran) "Assistant vocal de la maison, version ${BuildConfig.VERSION_BASE} du ${BuildConfig.HORODATAGE_COMPILATION}" else "Assistant vocal de la maison"
        })
        ligne.addView(titres, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))

        pointPastille = rond(Couleur.GRIS, 10)
        pastille = texte(15f, gras = true).apply {
            text = "Arrêté"
            gravity = Gravity.CENTER_VERTICAL
            setCompoundDrawablesRelativeWithIntrinsicBounds(pointPastille, null, null, null)
            compoundDrawablePadding = dp(10)
            setPadding(dp(16), dp(10), dp(18), dp(10))
            background = Decor.fondSousCarte(this@MainActivity, 22f)
        }
        Decor.relief(pastille, 3f)
        ligne.addView(pastille)

        val appareils = boutonDiscret("Appareils", hauteurDp = 46) { ouvrirAppareils() }.apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
            setPadding(dp(16), 0, dp(16), 0)
        }
        ligne.addView(
            appareils,
            LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, dp(46)).apply { marginStart = dp(10) },
        )
        if (largeEcran) {
            val b = boutonDiscret("Réglages", hauteurDp = 46) { basculerReglages() }.apply {
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 15f)
                setPadding(dp(18), 0, dp(18), 0)
            }
            ligne.addView(
                b,
                LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, dp(46)).apply { marginStart = dp(10) },
            )
            boutonPanneau = b
        }
        return ligne
    }

    /**
     * Le poste : l'orbe au centre (toucher l'orbe vaut le bouton Parler), l'état et l'aide en
     * dessous, le message bref de l'arbitre, l'alerte de clé, puis Démarrer ou Arrêter.
     */
    private fun construirePoste(): LinearLayout {
        val c = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            clipChildren = false
        }
        orbe = VueOrbe(this).apply { setOnClickListener { parler() } }
        val hauteurOrbe = if (largeEcran) LinearLayout.LayoutParams.MATCH_PARENT else dp(if (grandeTaille) 400 else 310)
        c.addView(
            orbe,
            if (largeEcran) LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, 0, 1f)
            else LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, hauteurOrbe),
        )

        etiquetteEssai = texte(12.5f, Couleur.FOND, gras = true).apply {
            text = "ESSAI"
            letterSpacing = 0.14f
            gravity = Gravity.CENTER
            setPadding(dp(12), dp(4), dp(12), dp(4))
            background = Decor.degrade(
                this@MainActivity, Decor.eclaircir(Couleur.ESSAI, 0.12f), Decor.assombrir(Couleur.ESSAI, 0.08f), 12f,
            )
            visibility = View.GONE
        }
        texteAssistant = texte(taille(28f, 36f), gras = true).apply {
            setLineSpacing(0f, 1.0f)
            letterSpacing = -0.01f
            gravity = Gravity.CENTER
        }
        val tete = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
        }
        tete.addView(texteAssistant)
        tete.addView(
            etiquetteEssai,
            LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT)
                .apply { marginStart = dp(12) },
        )
        // Textes et boutons sous l'orbe, dans un bloc à part : l'écran OLED les éteint sans toucher à l'orbe.
        val bloc = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            clipChildren = false
        }
        c.addView(bloc, marge())
        bloc.addView(tete, marge())
        texteAide = texte(taille(15f, 17f), Couleur.TEXTE_2).apply { gravity = Gravity.CENTER }
        bloc.addView(texteAide, marge(haut = 2))
        texteDirect = texte(taille(17f, 21f), Couleur.TEXTE_2).apply {
            gravity = Gravity.CENTER
            maxLines = 3
            setPadding(dp(16), 0, dp(16), 0)
            visibility = View.GONE
        }
        bloc.addView(texteDirect, marge(haut = 8))
        texteParole = texte(taille(19f, 24f), Couleur.BLEU_CLAIR, gras = true).apply {
            gravity = Gravity.CENTER
            maxLines = 5
            setPadding(dp(16), 0, dp(16), 0)
            setLineSpacing(0f, 1.1f)
            visibility = View.GONE
        }
        bloc.addView(texteParole, marge(haut = 6))
        texteBref = texte(taille(14.5f, 16f), Couleur.ACCENT_CLAIR).apply {
            gravity = Gravity.CENTER
            visibility = View.GONE
        }
        bloc.addView(texteBref, marge(haut = 6))
        texteAlerte = texte(14.5f, Decor.eclaircir(Couleur.ROUGE, 0.2f), gras = true).apply {
            gravity = Gravity.CENTER
            setPadding(dp(14), dp(10), dp(14), dp(10))
            background = Decor.uni(this@MainActivity, Decor.alpha(Couleur.ROUGE, 40), 14f)
            visibility = View.GONE
            isClickable = true
            setOnClickListener { ouvrirAppareils() }
        }
        bloc.addView(texteAlerte, marge(haut = 10))

        // Démarrer ou Arrêter, et en colonne les réglages repliables.
        val ligne = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER
            clipChildren = false
        }
        boutonMarche = bouton("Démarrer", Couleur.VERT, hauteurDp = 50) { basculerMarche() }.apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
        }
        ligne.addView(boutonMarche, LinearLayout.LayoutParams(dp(150), LinearLayout.LayoutParams.WRAP_CONTENT))
        if (!largeEcran) {
            val b = boutonDiscret("Réglages", hauteurDp = 50) { basculerReglages() }
            ligne.addView(
                b,
                LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT)
                    .apply { marginStart = dp(12) },
            )
            boutonPanneau = b
        }
        bloc.addView(ligne, marge(haut = 16, bas = 4))
        ligneMarche = ligne
        return c
    }

    private fun couleursVumetre(c: Int) = intArrayOf(Decor.assombrir(c, 0.30f), Decor.eclaircir(c, 0.12f))

    /**
     * Sélecteur à segments posé dans un rail creusé. Les segments sont en MATCH_PARENT dans
     * une rangée en WRAP_CONTENT : la rangée prend la hauteur du plus haut libellé (deux
     * lignes au besoin) et tous les segments s'alignent sur cette même hauteur.
     */
    private fun selecteur(carte: LinearLayout, vararg segments: TextView) {
        val rangee = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            background = Decor.fondCreux(this@MainActivity, 16f)
            setPadding(dp(4), dp(4), dp(4), dp(4))
            clipChildren = false
        }
        segments.forEachIndexed { i, vue ->
            rangee.addView(
                vue,
                LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.MATCH_PARENT, 1f).apply { if (i > 0) marginStart = dp(4) },
            )
        }
        carte.addView(rangee, marge())
    }

    private fun ligneMessage(point: GradientDrawable): TextView =
        texte(15f, Couleur.TEXTE_2).apply {
            setCompoundDrawablesRelativeWithIntrinsicBounds(point, null, null, null)
            compoundDrawablePadding = dp(10)
            gravity = Gravity.CENTER_VERTICAL
        }

    private fun construireMode(): LinearLayout {
        val c = carte("Mode")
        segmentEssai = segment("Essai") { choisirMode("essai") }
        segmentReel = segment("Réel") { choisirMode("reel") }
        selecteur(c, segmentEssai, segmentReel)
        pointMode = rond(Couleur.GRIS, 10)
        texteMode = ligneMessage(pointMode)
        c.addView(texteMode, marge(haut = 12))
        return c
    }

    /**
     * Carte Mot de réveil : le mot (Hey Jarvis ou celui de la configuration, changé à chaud), l'endroit où il est
     * guetté (cet appareil ou le serveur), le seuil, et le micro avec le score du réveil.
     */
    private fun construireReveil(): LinearLayout {
        val c = carte("Mot de réveil", "le mot qui réveille ${ConfigMaison.NOM_ASSISTANT}")
        segmentHeyJarvis = segment("Hey Jarvis\n(anglais)") { choisirMotReveil(ReveilLocal.HEY_JARVIS) }
        // Second mot : celui de la configuration (section reveil de maison.json), absent sans elle.
        val perso = ReveilLocal.nom(ReveilLocal.PERSO) + (ReveilLocal.LANGUE_PERSO.takeIf { it.isNotBlank() }?.let { "\n($it)" } ?: "")
        segmentPerso = segment(perso) { choisirMotReveil(ReveilLocal.PERSO) }
        selecteur(c, segmentHeyJarvis, segmentPerso)
        if (!ReveilLocal.PERSO_DISPONIBLE) segmentPerso.visibility = View.GONE
        if (ReveilLocal.PERSO_DISPONIBLE && ReveilLocal.LICENCE_PERSO.isNotBlank()) {
            c.addView(texte(13f, Couleur.GRIS).apply { text = ReveilLocal.LICENCE_PERSO }, marge(haut = 8))
        }

        c.addView(texte(14f, Couleur.TEXTE_2).apply { text = "Où il est guetté" }, marge(haut = 16, bas = 6))
        segmentReveilAppareil = segment("Sur cet appareil") { choisirReveil("appareil") }
        segmentReveilServeur = segment("Sur le serveur") { choisirReveil("serveur") }
        selecteur(c, segmentReveilAppareil, segmentReveilServeur)
        pointReveil = rond(Couleur.GRIS, 10)
        texteReveil = ligneMessage(pointReveil)
        c.addView(texteReveil, marge(haut = 12))

        texteSeuil = texte(15f, Couleur.TEXTE)
        c.addView(texteSeuil, marge(haut = 14, bas = 8))
        val ligne = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val moins = boutonDiscret("Plus sensible", hauteurDp = 46) { changerSeuil(-0.05f) }
        val plus = boutonDiscret("Moins sensible", hauteurDp = 46) { changerSeuil(0.05f) }
        listOf(moins, plus).forEachIndexed { i, b ->
            b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14.5f)
            b.setPadding(dp(8), 0, dp(8), 0)
            ligne.addView(
                b,
                LinearLayout.LayoutParams(0, dp(46), 1f).apply { if (i > 0) marginStart = dp(10) },
            )
        }
        c.addView(ligne, marge())

        // Micro et score du réveil, utiles pour régler le seuil.
        remplissageVumetre = GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT, couleursVumetre(Couleur.ACCENT)).apply {
            cornerRadius = dp(8).toFloat()
        }
        couleurVumetre = Couleur.ACCENT
        val couches = LayerDrawable(
            arrayOf(Decor.fondCreux(this, 8f), ClipDrawable(remplissageVumetre, Gravity.START, ClipDrawable.HORIZONTAL))
        ).apply {
            setId(0, android.R.id.background)
            setId(1, android.R.id.progress)
        }
        vumetre = ProgressBar(this, null, android.R.attr.progressBarStyleHorizontal).apply {
            isIndeterminate = false
            max = 60
            progressDrawable = couches
        }
        c.addView(vumetre, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(12)).apply { topMargin = dp(16) })
        val mesures = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        texteNiveau = texte(14f, Couleur.TEXTE_2)
        texteScore = texte(14f, Couleur.TEXTE_2).apply { gravity = Gravity.END }
        mesures.addView(texteNiveau, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        mesures.addView(texteScore, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        c.addView(mesures, marge(haut = 8))

        // Couper la parole (0.16.0), mode « Cet appareil » : micro ouvert pendant la réponse.
        c.addView(texte(14f, Couleur.TEXTE_2).apply { text = "Couper la parole à ${ConfigMaison.NOM_ASSISTANT} pendant sa réponse" }, marge(haut = 18, bas = 6))
        segmentCoupureNon = segment("Désactivé") { choisirCoupure(false) }
        segmentCoupureOui = segment("Activé") { choisirCoupure(true) }
        selecteur(c, segmentCoupureNon, segmentCoupureOui)
        texteCoupure = texte(13.5f, Couleur.TEXTE_2)
        c.addView(texteCoupure, marge(haut = 8))
        return c
    }

    /**
     * Carte Sons d'écoute (0.23.0) : la paire jouée au début et à la fin de l'écoute, choisie par le propriétaire
     * parmi les quatre de SonsEcoute. Toucher une paire la garde et la fait entendre, début puis fin.
     */
    private fun construireSons(): LinearLayout {
        val c = carte("Sons d'écoute", "au début et à la fin de l'écoute")
        segmentsSons = SonsEcoute.PAIRES.map { p -> segment(p.libelle) { choisirSons(p.nom) } }
        selecteur(c, *segmentsSons.toTypedArray())
        texteSons = texte(13.5f, Couleur.TEXTE_2)
        c.addView(texteSons, marge(haut = 8))
        val ligne = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        val jour = boutonDiscret("Écouter de jour", hauteurDp = 46) { SonsEcoute.essayer(this, SonsEcoute.choisie(this), nuit = false) }
        val nuit = boutonDiscret("Écouter de nuit", hauteurDp = 46) { SonsEcoute.essayer(this, SonsEcoute.choisie(this), nuit = true) }
        listOf(jour, nuit).forEachIndexed { i, b ->
            b.setTextSize(TypedValue.COMPLEX_UNIT_SP, 14.5f)
            b.setPadding(dp(8), 0, dp(8), 0)
            ligne.addView(b, LinearLayout.LayoutParams(0, dp(46), 1f).apply { if (i > 0) marginStart = dp(10) })
        }
        c.addView(ligne, marge(haut = 12))
        try {
            SonsEcoute.charger(this)
        } catch (e: Exception) {
            android.util.Log.w("JarvisSons", "Sons d'écoute indisponibles", e)
        }
        afficherSons()
        return c
    }

    private fun choisirSons(paire: String) {
        SonsEcoute.choisir(this, paire)
        SonsEcoute.essayer(this, paire)
        afficherSons()
    }

    private fun afficherSons() {
        val choisie = SonsEcoute.choisie(this)
        peindreSegments(segmentsSons.zip(SonsEcoute.PAIRES) { v, p -> Triple(v, p.nom, Couleur.ACCENT) }, choisie, "")
        val description = SonsEcoute.PAIRES.first { it.nom == choisie }.description
        texteSons.text = "$description Du coucher au lever du soleil, la même paire joue 6 dB plus bas."
    }

    // ---------------------------------------------------------------- station et vision (0.16.0)

    /** Carte Station : la tablette du séjour fait tourner l'assistant en permanence. */
    private fun construireStation(): LinearLayout {
        val c = carte("Station", "tablette posée en permanence, sur secteur")
        // Arrêter l'assistant vit ici depuis la 0.16.3 : il ne se démarre qu'une fois.
        boutonArreter = bouton("Arrêter ${ConfigMaison.NOM_ASSISTANT}", Decor.assombrir(Couleur.ROUGE, 0.1f), hauteurDp = 50) { confirmerArret() }
        c.addView(boutonArreter, marge(bas = 14))
        segmentStationNon = segment("Désactivée") { choisirStation(false) }
        segmentStationOui = segment("Activée") { choisirStation(true) }
        selecteur(c, segmentStationNon, segmentStationOui)
        c.addView(texte(13.5f, Couleur.TEXTE_2).apply {
            text = "Démarre avec la tablette et se relance si Android l'arrête, sur « Cet appareil » par défaut. " +
                "Plein écran en paysage, écran allumé tant que la tablette charge, lumière baissée après 2 minutes " +
                "sans présence ni commande, au minimum de minuit à 7 h."
        }, marge(haut = 10))
        texteStation = texte(14f, Couleur.TEXTE)
        c.addView(texteStation, marge(haut = 12, bas = 12))
        c.addView(boutonDiscret("Ouverture automatique au démarrage") { ouvrirSuperposition() }, marge(bas = 10))
        c.addView(boutonDiscret("Exemption d'optimisation de batterie") { expliquerBatterie() }, marge(bas = 10))
        c.addView(texte(13f, Couleur.GRIS).apply {
            text = "Sur Samsung, sors aussi ${ConfigMaison.NOM_ASSISTANT} de la mise en veille : Paramètres, Batterie et maintenance de " +
                "l'appareil, Batterie, Limites d'utilisation en arrière-plan, Applications jamais en veille, ajouter ${ConfigMaison.NOM_ASSISTANT}."
        }, marge())
        return c
    }

    /** Carte Vision : caméra avant, désactivée par défaut. */
    private fun construireVision(): LinearLayout {
        val c = carte("Vision", "détection des personnes par la caméra avant")
        c.addView(texte(14f, Decor.eclaircir(Couleur.ORANGE, 0.15f)).apply {
            text = "La caméra filme une pièce commune : à n'activer qu'avec l'accord de tous les occupants. " +
                "Aucune image n'est jamais gardée, seules les empreintes des visages enregistrés restent sur cette tablette."
        }, marge(bas = 12))
        segmentVisionNon = segment("Désactivée") { choisirVision("off") }
        segmentVisionTablette = segment("Sur la tablette") { choisirVision("tablette") }
        segmentVisionPc = segment("Sur le PC") { choisirVision("pc") }
        selecteur(c, segmentVisionNon, segmentVisionTablette, segmentVisionPc)
        pointVision = rond(Couleur.GRIS, 10)
        texteVision = ligneMessage(pointVision)
        c.addView(texteVision, marge(haut = 12))
        c.addView(texte(14f, Couleur.TEXTE_2).apply {
            text = "Parler en regardant : seul devant la tablette, la regarder 1,5 s vaut le mot de réveil. " +
                "Désactivé par défaut : un simple regard lançait l'écoute, et les conversations du séjour partaient " +
                "à la transcription puis au modèle de langage. Le mot de réveil ou un toucher sur l'orbe suffisent."
        }, marge(haut = 16, bas = 6))
        segmentRegardNon = segment("Désactivé") { choisirRegard(false) }
        segmentRegardOui = segment("Activé") { choisirRegard(true) }
        selecteur(c, segmentRegardNon, segmentRegardOui)
        c.addView(
            boutonDiscret("Visages enregistrés") { startActivity(Intent(this, VisagesActivity::class.java)) },
            marge(haut = 14),
        )
        return c
    }

    private fun afficherStation() {
        if (!::texteStation.isInitialized) return
        val station = SatelliteService.station(this)
        val superposition = Station.peutOuvrirEcran(this)
        val pm = getSystemService(PowerManager::class.java)
        val batterieLibre = pm?.isIgnoringBatteryOptimizations(packageName) == true
        val cle = "$station|$superposition|$batterieLibre|$enCharge"
        if (cle == cleStation) return
        cleStation = cle
        peindreSegments(
            listOf(Triple(segmentStationNon, "non", Couleur.ACCENT), Triple(segmentStationOui, "oui", Couleur.ACCENT)),
            if (station) "oui" else "non", "",
        )
        texteStation.text = if (!station) "Mode station désactivé" else listOf(
            if (superposition) "Ouverture au démarrage : autorisée" else "Ouverture au démarrage : à autoriser (bouton ci-dessous)",
            if (batterieLibre) "Optimisation de batterie : désactivée pour ${ConfigMaison.NOM_ASSISTANT}" else "Optimisation de batterie : encore active",
            if (enCharge) "Sur secteur : écran gardé allumé" else "Sur batterie : l'écran peut s'éteindre",
        ).joinToString("\n")
    }

    private fun afficherVision(e: Etat.Instantane) {
        val mode = SatelliteService.visionChoisie(this)
        val regard = SatelliteService.preferences(this).getBoolean(SatelliteService.CLE_PARLER_REGARD, false)
        val profils = ProfilsVisages.lire(this).size
        val cle = "$mode|$regard|${e.visionEtat}|${e.visionNiveau}|${e.enMarche}|$profils"
        if (cle == cleVision) return
        cleVision = cle
        peindreSegments(
            listOf(
                Triple(segmentVisionNon, "off", Couleur.ACCENT),
                Triple(segmentVisionTablette, "tablette", Couleur.ACCENT),
                Triple(segmentVisionPc, "pc", Couleur.ACCENT),
            ),
            mode, "",
        )
        peindreSegments(
            listOf(Triple(segmentRegardNon, "non", Couleur.ACCENT), Triple(segmentRegardOui, "oui", Couleur.ACCENT)),
            if (regard) "oui" else "non", "",
        )
        // Un message de vision peut encore porter l'ancien nom Jarvis : remplacé par le nom de l'assistant.
        val etat = e.visionEtat.replace("Jarvis", ConfigMaison.NOM_ASSISTANT)
        val (couleur, message) = when {
            mode == "off" -> Couleur.GRIS to "Caméra éteinte"
            checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED ->
                Couleur.ORANGE to "Caméra à autoriser"
            !e.enMarche -> Couleur.GRIS to "Démarre ${ConfigMaison.NOM_ASSISTANT} pour allumer la caméra"
            e.visionNiveau == "ok" -> Couleur.VERT to etat
            e.visionNiveau == "erreur" -> Couleur.ROUGE to etat
            else -> Couleur.ORANGE to etat.ifEmpty { "Démarrage de la caméra" }
        }
        pointVision.setColor(couleur)
        texteVision.text = message + "\n" + when (profils) {
            0 -> "Aucun visage enregistré"
            1 -> "1 visage enregistré"
            else -> "$profils visages enregistrés"
        }
    }

    private fun afficherCoupure(e: Etat.Instantane) {
        val dispo = SatelliteService.echoAnnulable()
        val active = SatelliteService.couperParole(this)
        val cle = "$dispo|$active|${e.capServeur}"
        if (cle == cleCoupure) return
        cleCoupure = cle
        peindreSegments(
            listOf(Triple(segmentCoupureNon, "non", Couleur.ACCENT), Triple(segmentCoupureOui, "oui", Couleur.ACCENT)),
            if (active) "oui" else "non", "",
        )
        if (!dispo) {
            for (v in listOf(segmentCoupureNon, segmentCoupureOui)) activer(v, false)
        }
        texteCoupure.text = when {
            !dispo -> "Annulation d'écho indisponible sur cet appareil : ${ConfigMaison.NOM_ASSISTANT} entendrait sa propre voix, " +
                "le micro reste donc fermé pendant ses réponses. Toucher l'orbe coupe quand même la réponse."
            active -> "Annulation d'écho disponible. Pendant la réponse, seul « ${ReveilLocal.nom(SatelliteService.motReveilChoisi(this))} » " +
                "(seuil relevé de 0,1) coupe ${ConfigMaison.NOM_ASSISTANT}, une autre voix ne coupe rien. Mode « Cet appareil » seulement."
            else -> "Annulation d'écho disponible, option désactivée : micro fermé pendant les réponses."
        }
    }

    /**
     * Sous l'orbe : « J'entends : » en italique et plus pâle pendant la phrase, puis « Compris : »
     * avec la transcription finale, jusqu'à ce que la réponse arrive.
     */
    private fun afficherDirect(e: Etat.Instantane) {
        val voulu = SatelliteService.transcriptionDirecte(this)
        val cleOption = "option|$voulu"
        if (cleOption != cleDirect) {
            cleDirect = cleOption
            peindreSegments(
                listOf(Triple(segmentDirectNon, "non", Couleur.ACCENT), Triple(segmentDirectOui, "oui", Couleur.ACCENT)),
                if (voulu) "oui" else "non", "",
            )
        }
        afficherParole(e)
        // « Compris » reste tant que la réponse est dite sous l'orbe, puis part avec elle.
        val montrer = e.enMarche && e.entendu.isNotBlank() && (e.jarvis.isBlank() || texteParole.visibility == View.VISIBLE)
        if (!montrer) {
            texteDirect.visibility = View.GONE
            return
        }
        texteDirect.text = (if (e.entenduFinal) "Compris : " else "J'entends : ") + e.entendu
        texteDirect.setTypeface(null, if (e.entenduFinal) Typeface.NORMAL else Typeface.ITALIC)
        texteDirect.setTextColor(if (e.entenduFinal) Couleur.TEXTE else Decor.alpha(Couleur.TEXTE_2, 200))
        texteDirect.visibility = View.VISIBLE
    }

    /**
     * La réponse de l'assistant sous l'orbe, comme si c'était lui qui parlait : elle se remplit au fil de
     * la voix, puis s'efface en fondu 6 s après la fin. Pas de carte pour la réponse (0.16.3).
     */
    private fun afficherParole(e: Etat.Instantane) {
        val fini = e.paroleFinLe > 0L && SystemClock.elapsedRealtime() - e.paroleFinLe >= DUREE_PAROLE_MS
        if (!e.enMarche || e.parole.isBlank() || fini) {
            if (texteParole.visibility == View.VISIBLE && !paroleEffacee) {
                paroleEffacee = true
                texteParole.animate().alpha(0f).setDuration(700).withEndAction {
                    texteParole.visibility = View.GONE
                    texteParole.alpha = 1f
                    if (texteDirect.visibility == View.VISIBLE) texteDirect.visibility = View.GONE
                }.start()
            }
            return
        }
        paroleEffacee = false
        if (e.parole != paroleAffichee || texteParole.visibility != View.VISIBLE) {
            paroleAffichee = e.parole
            texteParole.animate().cancel()
            texteParole.alpha = 1f
            texteParole.text = e.parole
            texteParole.visibility = View.VISIBLE
        }
    }

    private fun choisirDirect(oui: Boolean) {
        SatelliteService.preferences(this).edit().putBoolean(SatelliteService.CLE_TRANSCRIPTION_DIRECTE, oui).apply()
        Etat.actionTranscriptionDirecte?.invoke(oui)
        cleDirect = ""
        afficherDirect(Etat.courant)
    }

    private fun choisirCoupure(oui: Boolean) {
        if (!SatelliteService.echoAnnulable()) return
        SatelliteService.preferences(this).edit().putBoolean(SatelliteService.CLE_COUPER_PAROLE, oui).apply()
        Etat.actionCouperParole?.invoke(oui)
        cleCoupure = ""
        afficherCoupure(Etat.courant)
    }

    private fun choisirStation(oui: Boolean) {
        if (oui == SatelliteService.station(this)) return
        SatelliteService.preferences(this).edit()
            .putBoolean(SatelliteService.CLE_STATION, oui)
            .putBoolean(SatelliteService.CLE_ARRET_VOLONTAIRE, false)
            .apply()
        if (oui) {
            // Serveur « Cet appareil » par défaut en station (modifiable ensuite).
            choisirServeur("local")
            AlertDialog.Builder(this)
                .setTitle("Mode station")
                .setMessage(
                    "Pour tourner en permanence, ${ConfigMaison.NOM_ASSISTANT} doit échapper à l'optimisation de batterie et pouvoir " +
                        "rouvrir son écran au démarrage de la tablette (autorisation « Afficher par-dessus les autres " +
                        "applications »). Sur Samsung, ajoute aussi ${ConfigMaison.NOM_ASSISTANT} aux applications jamais en veille."
                )
                .setPositiveButton("Continuer") { _, _ -> demanderExemption() }
                .setNegativeButton("Plus tard", null)
                .show()
            if (!Etat.courant.enMarche) demarrer()
        }
        appliquerStation()
        cleStation = ""
        afficherStation()
        setContentView(construireInterface())
        afficher(Etat.courant)
        majBatterie()
    }

    private fun choisirVision(mode: String) {
        if (mode == SatelliteService.visionChoisie(this)) return
        if (mode != "off" && checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            SatelliteService.preferences(this).edit().putString(SatelliteService.CLE_VISION, mode).apply()
            requestPermissions(arrayOf(Manifest.permission.CAMERA), 2)
            cleVision = ""
            afficherVision(Etat.courant)
            return
        }
        SatelliteService.preferences(this).edit().putString(SatelliteService.CLE_VISION, mode).apply()
        Etat.actionVision?.invoke(mode)
        cleVision = ""
        afficherVision(Etat.courant)
    }

    override fun onRequestPermissionsResult(requestCode: Int, permissions: Array<out String>, grantResults: IntArray) {
        super.onRequestPermissionsResult(requestCode, permissions, grantResults)
        if (requestCode == 2 && grantResults.firstOrNull() == PackageManager.PERMISSION_GRANTED) {
            Etat.actionVision?.invoke(SatelliteService.visionChoisie(this))
        }
        cleVision = ""
        afficherVision(Etat.courant)
    }

    private fun choisirRegard(oui: Boolean) {
        SatelliteService.preferences(this).edit().putBoolean(SatelliteService.CLE_PARLER_REGARD, oui).apply()
        cleVision = ""
        afficherVision(Etat.courant)
    }

    private fun ouvrirSuperposition() {
        try {
            startActivity(Intent(Settings.ACTION_MANAGE_OVERLAY_PERMISSION, Uri.parse("package:$packageName")))
        } catch (_: Exception) {
            message("Réglage introuvable : Paramètres, Applications, ${ConfigMaison.NOM_ASSISTANT}, Afficher par-dessus les autres applications")
        }
    }

    private fun expliquerBatterie() {
        AlertDialog.Builder(this)
            .setTitle("Optimisation de batterie")
            .setMessage(
                "Android endort les applications pour économiser la batterie, ce qui couperait le micro et la caméra " +
                    "de ${ConfigMaison.NOM_ASSISTANT} au bout de quelques minutes. Sur secteur, l'exemption ne coûte rien. " +
                    "Accepte la demande qui va s'afficher."
            )
            .setPositiveButton("Continuer") { _, _ -> demanderExemption() }
            .setNegativeButton("Annuler", null)
            .show()
    }

    private fun demanderExemption() {
        ouvrirBatterie()
        if (!Station.peutOuvrirEcran(this)) {
            message("Autorise ensuite « Afficher par-dessus les autres applications » (bouton Ouverture automatique au démarrage)")
        }
    }

    /** Orientation, écran sur verrouillage et plein écran selon le mode station. */
    private fun appliquerStation() {
        val station = SatelliteService.station(this)
        val voulue = if (station) ActivityInfo.SCREEN_ORIENTATION_SENSOR_LANDSCAPE else ActivityInfo.SCREEN_ORIENTATION_UNSPECIFIED
        if (requestedOrientation != voulue) requestedOrientation = voulue
        if (Build.VERSION.SDK_INT >= 27) {
            setShowWhenLocked(station)
            setTurnScreenOn(station)
        } else {
            @Suppress("DEPRECATION")
            val drapeaux = WindowManager.LayoutParams.FLAG_SHOW_WHEN_LOCKED or WindowManager.LayoutParams.FLAG_TURN_SCREEN_ON
            if (station) window.addFlags(drapeaux) else window.clearFlags(drapeaux)
        }
        immersifApplique = false
        appliquerImmersif()
        luminositeAppliquee = -2f
        majVeille()
    }

    /** Plein écran immersif en station : les barres reviennent d'un glissement depuis le bord. */
    private fun appliquerImmersif() {
        val station = SatelliteService.station(this)
        if (immersifApplique || window.peekDecorView() == null) return
        immersifApplique = true
        if (Build.VERSION.SDK_INT >= 30) {
            val c = window.insetsController ?: return
            if (station) {
                c.hide(WindowInsets.Type.systemBars())
                c.systemBarsBehavior = android.view.WindowInsetsController.BEHAVIOR_SHOW_TRANSIENT_BARS_BY_SWIPE
            } else {
                c.show(WindowInsets.Type.systemBars())
            }
        } else {
            @Suppress("DEPRECATION")
            window.decorView.systemUiVisibility = if (station) {
                View.SYSTEM_UI_FLAG_IMMERSIVE_STICKY or View.SYSTEM_UI_FLAG_FULLSCREEN or
                    View.SYSTEM_UI_FLAG_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_LAYOUT_STABLE or
                    View.SYSTEM_UI_FLAG_LAYOUT_HIDE_NAVIGATION or View.SYSTEM_UI_FLAG_LAYOUT_FULLSCREEN
            } else 0
        }
    }

    /**
     * Écran OLED (0.17.0, Veille) : régime vivant ou AOD (0.17.2) selon la présence vue par la caméra (ou,
     * sans vision, le dernier toucher, réveil ou commande), puis tout ce qui en dépend : luminosité de
     * la fenêtre en station (40 % au plus, plancher en AOD et la nuit sans personne), orbe, bulles,
     * textes sous l'orbe, bas de l'écran, bloc AOD, version et décalage global. Appelé
     * chaque seconde, à chaque changement d'état et au toucher, et 30 fois par seconde pendant une
     * transition (reprise en 0,8 s, fondu de 2 s).
     */
    private fun majVeille() {
        horloge.removeCallbacks(animVeille)
        if (!::orbe.isInitialized) return
        val maintenant = SystemClock.elapsedRealtime()
        val e = Etat.courant
        val occupe = e.enMarche && e.assistant in ASSISTANT_OCCUPE
        val nuit = Station.nuit()
        val station = SatelliteService.station(this)
        // 0.24.0 : quand une musique joue, l'AOD attend 10 min (quelqu'un écoute sans regarder).
        val musique = e.lecteurs.any { it.etat == "playing" }
        // 0.27.0 : la maison en grand compte comme une activité, l'écran reste vivant jusqu'à son retour de 45 s.
        val activite = if (ambiant?.enGrand == true) maintenant else maxOf(toucherLe, e.activiteLe)
        var anime = veille.avancer(maintenant, e.presence, activite, occupe, nuit, musique)

        // Luminosité de la fenêtre (pas le réglage du système), en station seulement.
        val voulue = if (!station) WindowManager.LayoutParams.BRIGHTNESS_OVERRIDE_NONE
        else if (ambiant == null) 1f
        else veille.luminositeAvec(lumiere.plafond(maintenant, nuit))
        // Montée et descente lentes de la consigne : avancées à chaque image, sans marches d'une seconde.
        if (station && lumiere.enTransition) anime = true
        if (station && kotlin.math.abs(voulue - consigneJournal) >= 0.05f) {
            consigneJournal = voulue
            android.util.Log.i(CapteurLumiere.JOURNAL, "consigne ${"%.2f".format(java.util.Locale.ROOT, voulue)}, retenu ${lumiere.luxRetenu?.let { "%.1f lux".format(java.util.Locale.ROOT, it) } ?: "aucun (règle de l'heure)"}, régime ${veille.regime}")
        }
        val ecart = kotlin.math.abs(voulue - luminositeAppliquee)
        if (ecart >= 0.01f || (ecart > 0f && (voulue <= Veille.LUMINOSITE_MIN || !anime))) {
            luminositeAppliquee = voulue
            val p = window.attributes
            p.screenBrightness = voulue
            window.attributes = p
        }

        val a = ambiant
        if (a == null) {
            racineVue?.let {
                it.translationX = 0f
                it.translationY = 0f
            }
            return
        }
        val regime = veille.regime
        if (regime != regimeApplique) {
            val avant = regimeApplique
            regimeApplique = regime
            // La pièce s'est vidée : un panneau resté ouvert ne doit pas marquer l'écran.
            if (regime != Veille.Regime.VIVANT && avant == Veille.Regime.VIVANT) fermerPanneaux()
            // Première AOD de la session : la luminosité réelle de la dalle est relevée une fois le
            // fondu fini (journal JarvisVeille), pour vérifier le plancher sur la tablette.
            horloge.removeCallbacks(mesurePlancher)
            if (regime == Veille.Regime.AOD && station && !plancherMesure) horloge.postDelayed(mesurePlancher, 5_000L)
        }
        val vie = veille.vie
        val visible = 1f - veille.noir
        // Accueil (0.18.0) : tout suit la vie de l'écran. Le plan 3D n'existe qu'en régime vivant et reste
        // masqué en AOD, sur fond noir, sous un panneau ou activité cachée (la page garde sa dernière image).
        val montrable = (demarree || auPremierPlan) && !panneauOuvert() && interactif()
        val vivant = regime == Veille.Regime.VIVANT
        a.microAutorise = checkSelfPermission(Manifest.permission.RECORD_AUDIO) == PackageManager.PERMISSION_GRANTED
        a.dernierToucherLe = toucherLe
        a.reglerVie(vie, visible, montrable, vivant, veille.eclat, veille.actif)
        // Lumières du plan relues toutes les 5 s seulement tant qu'il est vivant et montré.
        suivreLumieres(vivant && montrable && e.enMarche)
        // 0.18.1 : réglages et version ne suivent plus le toucher partout, mais la couche de service de
        // l'accueil (un toucher dans le noir, 10 s).
        majDecalage()
        if (anime) horloge.postDelayed(animVeille, 33)
    }

    /**
     * Lecture des lumières pour le plan 3D de l'accueil (0.18.0), demandée au service seulement quand elle
     * change. Un service redémarré pose une nouvelle action : la demande est alors refaite.
     */
    private fun suivreLumieres(oui: Boolean) {
        val action = Etat.actionSuivreLumieres
        if (oui == lumieresSuivies && action === actionLumieres) return
        if (action !== actionLumieres && !oui && !lumieresSuivies) {
            actionLumieres = action
            return
        }
        lumieresSuivies = oui
        actionLumieres = action
        action?.invoke(oui)
    }

    /**
     * Mesure du plancher (0.17.2) : la fenêtre demande 0 (BRIGHTNESS_OVERRIDE_OFF, la plus basse valeur
     * acceptée) et Android la ramène au minimum de la dalle. Les valeurs réelles ne sont lisibles que
     * par des interfaces cachées d'Android, essayées sans risque : `adb logcat -s JarvisVeille`.
     */
    private fun journaliserPlancher() {
        if (plancherMesure || veille.regime != Veille.Regime.AOD) return
        plancherMesure = true
        val demande = window.attributes.screenBrightness
        val mesures = ArrayList<String>()
        try {
            val info = window.decorView.display?.let { d -> d.javaClass.getMethod("getBrightnessInfo").invoke(d) }
            if (info != null) {
                for (champ in listOf("brightness", "adjustedBrightness", "brightnessMinimum", "brightnessMaximum")) {
                    val v = info.javaClass.getField(champ).get(info)
                    mesures.add("$champ=$v")
                }
            }
        } catch (e: Throwable) {
            mesures.add("BrightnessInfo illisible (${e.javaClass.simpleName})")
        }
        try {
            val pm = getSystemService(POWER_SERVICE)
            val m = pm.javaClass.getMethod("getBrightnessConstraint", Int::class.javaPrimitiveType)
            mesures.add("minimum de la dalle=${m.invoke(pm, 0)}")
        } catch (e: Throwable) {
            mesures.add("contrainte de luminosité illisible (${e.javaClass.simpleName})")
        }
        android.util.Log.i("JarvisVeille", "AOD : fenêtre à $demande, ${mesures.joinToString(", ")}")
    }

    /** Toute l'interface glisse d'un pixel par minute, dans un carré de ±12 px (Veille.decalage). */
    private fun majDecalage() {
        val r = racineVue ?: return
        val minute = System.currentTimeMillis() / 60_000L
        if (minute == decalageMinute) return
        decalageMinute = minute
        val (x, y) = Veille.decalage(minute)
        r.translationX = x.toFloat()
        r.translationY = y.toFloat()
    }

    /**
     * L'assistant démarre seul s'il tournait la dernière fois (ou en station), tant qu'on ne l'a pas
     * arrêté lui-même depuis les réglages (0.16.3) : on ne le démarre qu'une fois.
     */
    private fun relancerSiStation() {
        val p = SatelliteService.preferences(this)
        if (!SatelliteService.station(this) && !p.getBoolean(CLE_DEJA_DEMARRE, false)) return
        if (p.getBoolean(SatelliteService.CLE_ARRET_VOLONTAIRE, false)) return
        if (Etat.courant.enMarche) return
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) return
        if (::champUrlPc.isInitialized) demarrer()
    }

    /** Choix empilés, trop longs pour tenir côte à côte. Les boutons suivent la liste du serveur. */
    private fun construireTranscription(): LinearLayout {
        val c = carte("Transcription", "où la voix est convertie en texte")
        pileTranscription = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = Decor.fondCreux(this@MainActivity, 16f)
            setPadding(dp(4), dp(4), dp(4), dp(4))
            clipChildren = false
        }
        reconstruireBoutonsTranscription(CHOIX_TRANSCRIPTION_DEFAUT)
        c.addView(pileTranscription, marge())
        pointTranscription = rond(Couleur.GRIS, 10)
        texteTranscription = ligneMessage(pointTranscription)
        c.addView(texteTranscription, marge(haut = 12))
        // Transcription en direct (0.16.1), mode « Cet appareil » : affichage seulement.
        c.addView(texte(14f, Couleur.TEXTE_2).apply {
            text = "Transcription en direct : le texte s'affiche pendant que tu parles (mode « Cet appareil »)"
        }, marge(haut = 16, bas = 6))
        segmentDirectNon = segment("Désactivée") { choisirDirect(false) }
        segmentDirectOui = segment("Activée") { choisirDirect(true) }
        selecteur(c, segmentDirectNon, segmentDirectOui)
        return c
    }

    private fun reconstruireBoutonsTranscription(choix: List<Pair<String, String>>) {
        val cle = choix.joinToString("|") { "${it.first}=${it.second}" }
        if (cle == cleBoutonsTranscription) return
        cleBoutonsTranscription = cle
        pileTranscription.removeAllViews()
        segmentsTranscription = choix.mapIndexed { i, (id, libelle) ->
            val vue = segment(libelle) { choisirTranscription(id) }
            pileTranscription.addView(
                vue,
                LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)
                    .apply { if (i > 0) topMargin = dp(4) },
            )
            Triple(vue, id, Couleur.ACCENT)
        }
    }

    private fun construireCerveau(): LinearLayout {
        val c = carte("Compréhension", "quand le dictionnaire ne suffit pas")
        segmentClaude = segment(LIBELLES_CERVEAU_DEFAUT.getValue("claude")) { choisirCerveau("claude") }
        segmentLocal = segment(LIBELLES_CERVEAU_DEFAUT.getValue("local")) { choisirCerveau("local") }
        selecteur(c, segmentClaude, segmentLocal)
        pointCerveau = rond(Couleur.GRIS, 10)
        texteCerveau = ligneMessage(pointCerveau)
        c.addView(texteCerveau, marge(haut = 12))
        return c
    }

    private fun segment(libelle: String, action: () -> Unit): TextView =
        texte(15f, Couleur.TEXTE_2, gras = true).apply {
            text = libelle
            tag = libelle
            gravity = Gravity.CENTER
            minHeight = dp(52)
            setPadding(dp(5), dp(8), dp(5), dp(8))
            background = Decor.fondNeutre(this@MainActivity, 12f)
            isClickable = true
            isFocusable = true
            setOnClickListener { action() }
        }

    /**
     * Remplit le segment confirmé par le serveur, entoure celui seulement demandé. Si le
     * serveur a annoncé ses capacités, les choix absents sont grisés et non cliquables.
     */
    private fun peindreSegments(
        segments: List<Triple<TextView, String, Int>>,
        confirme: String,
        demande: String,
        possibles: List<String>? = null,
    ) {
        for ((vue, nom, couleur) in segments) {
            val libelle = vue.tag as? String ?: ""
            val disponible = possibles == null || nom in possibles
            vue.isEnabled = disponible
            vue.alpha = if (disponible) 1f else 0.5f
            if (disponible) {
                vue.text = libelle
            } else {
                val mention = "indisponible sur ce serveur"
                vue.text = SpannableString("$libelle\n$mention").apply {
                    setSpan(
                        RelativeSizeSpan(0.8f),
                        libelle.length + 1,
                        length,
                        Spanned.SPAN_EXCLUSIVE_EXCLUSIVE,
                    )
                }
                vue.background = Decor.fondNeutre(this, 12f)
                vue.elevation = 0f
                vue.setTextColor(Couleur.GRIS)
                continue
            }
            when {
                nom == confirme -> {
                    vue.background = Decor.fondBouton(this, couleur, 12f)
                    Decor.relief(vue, 2f)
                    vue.setTextColor(Palette.texteSurAccent)
                }
                nom == demande -> {
                    vue.background = Decor.fondBouton(this, Couleur.CHAMP, 12f, contour = couleur)
                    vue.elevation = 0f
                    vue.setTextColor(couleur)
                }
                else -> {
                    vue.background = Decor.fondNeutre(this, 12f)
                    vue.elevation = 0f
                    vue.setTextColor(Couleur.TEXTE_2)
                }
            }
        }
    }

    private fun champAdresse(carte: LinearLayout, titre: String, serveur: String, defaut: String): EditText {
        carte.addView(texte(14f, Couleur.TEXTE_2).apply { text = titre }, marge(bas = 6))
        val champ = EditText(this).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 17f)
            setTextColor(Couleur.TEXTE)
            setHintTextColor(Couleur.GRIS)
            hint = defaut
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_VARIATION_URI
            setSingleLine(true)
            background = Decor.fondCreux(this@MainActivity, 12f)
            setPadding(dp(14), dp(12), dp(14), dp(12))
            setText(SatelliteService.adresse(this@MainActivity, serveur))
        }
        carte.addView(champ, marge(bas = 14))
        return champ
    }

    /** Carte Serveur : sélecteur PC fixe / Home Assistant / cet appareil, choix local mémorisé. */
    private fun construireServeur(): LinearLayout {
        val c = carte("Serveur")
        segmentPc = segment("PC fixe") { choisirServeur("pc") }
        segmentHa = segment("Home Assistant") { choisirServeur("ha") }
        segmentAppareil = segment("Cet appareil") { choisirServeur("local") }
        selecteur(c, segmentPc, segmentHa, segmentAppareil)
        pointServeur = rond(Couleur.GRIS, 10)
        texteServeurEtat = ligneMessage(pointServeur)
        c.addView(texteServeurEtat, marge(haut = 12))
        return c
    }

    /** Chaque étape de la commande en cours, en direct (mode « Cet appareil »). */
    private fun construireDeroule(): LinearLayout {
        val c = carte("Déroulé", "chaque étape de la dernière commande")
        texteDerouleTitre = texte(taille(16f, 18f), Couleur.TEXTE)
        c.addView(texteDerouleTitre, marge(bas = 14))
        conteneurDeroule = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        c.addView(conteneurDeroule, marge())
        return c
    }

    private fun afficherDeroule(e: Etat.Instantane) {
        if (e.deroule === derouleAffiche) return
        derouleAffiche = e.deroule
        texteDerouleTitre.text = e.derouleTitre.ifEmpty {
            if (e.capServeur == "local") "Dis « ${ReveilLocal.nom(motAffiche(e))} » ou touche l'orbe"
            else "Le déroulé détaillé s'affiche en mode « Cet appareil »"
        }
        texteDerouleTitre.setTextColor(if (e.derouleTitre.isEmpty()) Couleur.TEXTE_2 else Couleur.TEXTE)
        conteneurDeroule.removeAllViews()
        val tailleNom = taille(16f, 17f)
        val tailleDetail = taille(14f, 15f)
        for ((i, etape) in e.deroule.withIndex()) {
            val (couleur, marque) = when (etape.statut) {
                Etat.Statut.EN_COURS -> Couleur.ORANGE to "en cours"
                Etat.Statut.OK -> Couleur.VERT to ""
                Etat.Statut.ECHEC -> Couleur.ROUGE to ""
                Etat.Statut.SAUTE -> Couleur.GRIS to ""
            }
            val ligne = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
            // Le rail prend la hauteur de l'étape : le trait relie les pastilles sans coupure.
            ligne.addView(
                RailEtape(
                    this,
                    couleur,
                    premier = i == 0,
                    dernier = i == e.deroule.lastIndex,
                    enCours = etape.statut == Etat.Statut.EN_COURS,
                    yPointDp = tailleNom * 0.72f,
                ),
                LinearLayout.LayoutParams(dp(26), LinearLayout.LayoutParams.MATCH_PARENT),
            )
            val contenu = LinearLayout(this).apply {
                orientation = LinearLayout.VERTICAL
                setPadding(dp(8), 0, 0, dp(if (i == e.deroule.lastIndex) 0 else 14))
            }
            val tete = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
            }
            tete.addView(
                texte(tailleNom, if (etape.statut == Etat.Statut.SAUTE) Couleur.TEXTE_2 else Couleur.TEXTE, gras = true)
                    .apply { text = etape.nom },
                LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f),
            )
            val temps = etape.ms?.let { ms ->
                if (ms >= 1000) String.format(Locale.FRANCE, "%.2f s", ms / 1000.0) else "$ms ms"
            } ?: marque
            if (temps.isNotEmpty()) {
                tete.addView(
                    texte(13.5f, Decor.eclaircir(couleur, 0.15f), gras = true).apply {
                        text = temps
                        setPadding(dp(10), dp(3), dp(10), dp(3))
                        background = Decor.uni(this@MainActivity, Decor.alpha(couleur, 38), 10f)
                    },
                    LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT)
                        .apply { marginStart = dp(8) },
                )
            }
            contenu.addView(tete, marge())
            if (etape.detail.isNotEmpty()) {
                contenu.addView(texte(tailleDetail, Couleur.TEXTE_2).apply {
                    text = etape.detail
                    setTextIsSelectable(true)
                }, marge(haut = 2))
            }
            ligne.addView(contenu, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            conteneurDeroule.addView(ligne, marge())
        }
    }

    /** Les 5 dernières commandes, et l'accès à l'historique complet. */
    private fun construireHistorique(): LinearLayout {
        val c = carte("Historique", "ce que ${ConfigMaison.NOM_ASSISTANT} a entendu, compris et fait")
        conteneurHistorique = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        c.addView(conteneurHistorique, marge(bas = 14))
        c.addView(
            boutonDiscret("Tout l'historique") {
                startActivity(Intent(this, HistoriqueActivity::class.java))
            }
        )
        return c
    }

    /**
     * Carte de verre de la dernière réponse : fond très sombre presque opaque, liseré fin teinté
     * selon la voie (dictionnaire, Home Assistant, Claude, LLM local, refus de sécurité).
     */
    private fun construireCarteReponse(): LinearLayout {
        fondReponse = GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            cornerRadius = dp(22).toFloat()
            setColor(Palette.carteReponse)
            setStroke(Math.max(1, dp(1)), Decor.alpha(Couleur.ACCENT_CLAIR, 150))
        }
        carteReponse = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = fondReponse
            setPadding(dp(20), dp(16), dp(20), dp(18))
            visibility = View.GONE
        }
        Decor.relief(carteReponse, 8f)
        texteSurtitre = texte(12.5f, Couleur.ACCENT_CLAIR, gras = true).apply { letterSpacing = 0.12f }
        carteReponse.addView(texteSurtitre, marge(bas = 10))
        carteReponse.addView(intitule("Entendu"), marge(bas = 2))
        texteEntendu = texte(taille(16f, 19f), Couleur.TEXTE_2)
        carteReponse.addView(texteEntendu, marge(bas = 12))
        texteReponse = texte(taille(22f, 28f), Couleur.TEXTE, gras = true).apply { setLineSpacing(0f, 1.1f) }
        carteReponse.addView(texteReponse, marge(bas = 12))
        conteneurFait = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        carteReponse.addView(conteneurFait, marge())
        texteDuree = texte(13f, Couleur.GRIS)
        carteReponse.addView(texteDuree, marge(haut = 8))
        return carteReponse
    }

    /** Libellé en capitales et couleur du liseré selon la voie qui a répondu (règles partagées avec l'écran ambiant). */
    private fun voieReponse(comprisPar: String, detail: String, reponse: String): Pair<String, Int> =
        EcranAmbiant.voie(Maison.voie(comprisPar, detail, reponse))

    private val COULEUR_LLM = EcranAmbiant.COULEUR_LLM

    /** Nouvelle réponse : la carte apparaît, puis reste 60 s. L'entrée d'historique la complète. */
    private fun afficherReponse(e: Etat.Instantane) {
        // 0.16.3 : la réponse est dite sous l'orbe (afficherParole), plus de carte de réponse.
        if (carteReponse.visibility == View.VISIBLE) carteReponse.visibility = View.GONE
        reponseVue = e.jarvis
        if (REPONSE_SOUS_ORBE) return
        val vue = reponseVue
        if (vue == null) {
            // Premier affichage : une réponse ancienne n'est pas remontrée à l'ouverture.
            reponseVue = e.jarvis
            if (SystemClock.elapsedRealtime() - reponseMontreeLe < DUREE_REPONSE_MS && e.jarvis.isNotBlank()) {
                // Rotation : la carte encore valable est remise sans animation.
                remplirReponse(e)
                carteReponse.visibility = View.VISIBLE
                carteReponse.removeCallbacks(masquerReponse)
                carteReponse.postDelayed(masquerReponse, DUREE_REPONSE_MS - (SystemClock.elapsedRealtime() - reponseMontreeLe))
            }
            return
        }
        if (e.jarvis != vue) {
            reponseVue = e.jarvis
            if (e.jarvis.isBlank()) return
            remplirReponse(e)
            montrerReponse()
            return
        }
        if (carteReponse.visibility == View.VISIBLE && e.historique !== historiqueReponse) remplirReponse(e)
    }

    private fun remplirReponse(e: Etat.Instantane) {
        historiqueReponse = e.historique
        val entree = e.historique.take(3).firstOrNull { it.reponse == e.jarvis }
        val (voie, couleur) = voieReponse(entree?.comprisPar ?: e.voie, entree?.detailVoie ?: e.voie, e.jarvis)
        val essai = entree?.essai ?: (e.modeActif == "essai")
        texteSurtitre.text = (voie + if (essai) ", essai" else "").uppercase(Locale.FRANCE)
        texteSurtitre.setTextColor(Decor.eclaircir(couleur, 0.1f))
        fondReponse.setStroke(Math.max(1, dp(1)), Decor.alpha(couleur, 170))
        texteEntendu.text = (entree?.entendu ?: e.toi).ifBlank { "-" }
        texteReponse.text = e.jarvis
        conteneurFait.removeAllViews()
        val fait = entree?.fait ?: emptyList()
        if (fait.isNotEmpty()) {
            conteneurFait.addView(intitule("Fait"), marge(bas = 2))
            for (ligne in fait) conteneurFait.addView(texte(taille(15f, 17f), Couleur.TEXTE).apply { text = ligne }, marge(bas = 2))
        }
        val duree = entree?.duree?.let { d -> d.replace(',', '.').toDoubleOrNull()?.let { String.format(Locale.FRANCE, "%.2f s", it) } ?: d } ?: ""
        texteDuree.text = if (duree.isNotBlank()) "Répondu en $duree" else ""
        texteDuree.visibility = if (duree.isBlank()) View.GONE else View.VISIBLE
    }

    /** Apparition en 0,9 s : fondu, montée de 8 dp, légère échelle. */
    private fun montrerReponse() {
        reponseMontreeLe = SystemClock.elapsedRealtime()
        carteReponse.removeCallbacks(masquerReponse)
        carteReponse.animate().cancel()
        carteReponse.alpha = 0f
        carteReponse.translationY = dp(8).toFloat()
        carteReponse.scaleX = 0.97f
        carteReponse.scaleY = 0.97f
        carteReponse.visibility = View.VISIBLE
        carteReponse.animate().alpha(1f).translationY(0f).scaleX(1f).scaleY(1f)
            .setDuration(900).setInterpolator(DecelerateInterpolator(2f)).start()
        carteReponse.postDelayed(masquerReponse, DUREE_REPONSE_MS)
    }

    private fun cacherReponse() {
        carteReponse.animate().cancel()
        carteReponse.animate().alpha(0f).setDuration(400).withEndAction {
            carteReponse.visibility = View.GONE
            carteReponse.alpha = 1f
        }.start()
    }

    private fun construireReglages(): LinearLayout {
        val c = carte("Connexion")
        champUrlPc = champAdresse(c, "Adresse du PC fixe", "pc", BuildConfig.SERVEUR_PC_DEFAUT)
        champUrlHa = champAdresse(c, "Adresse de Home Assistant", "ha", BuildConfig.SERVEUR_HA_DEFAUT)

        texteDetailConnexion = texte(14f, Couleur.TEXTE_2)
        c.addView(texteDetailConnexion, marge(bas = 16))

        texteBatterie = texte(14f, Couleur.TEXTE_2)
        c.addView(texteBatterie, marge(bas = 10))
        c.addView(boutonDiscret("Désactiver l'optimisation de batterie") { ouvrirBatterie() })
        return c
    }

    // ---------------------------------------------------------------- affichage

    private fun afficher(e: Etat.Instantane) {
        // Santé : fermée en fondu dès que le propriétaire n'est plus seul devant la tablette (0.21.0).
        ecranSante?.maj(e)
        // Panneau Météo demandé à la voix (0.20.0) : une seule fois par demande, si elle est récente.
        if (e.meteoDemandeeLe != meteoDemandeeVue) {
            meteoDemandeeVue = e.meteoDemandeeLe
            if (e.meteoDemandeeLe != 0L && SystemClock.elapsedRealtime() - e.meteoDemandeeLe < 30_000L) {
                val d = e.meteoDemande
                horloge.post { ouvrirMeteo(d) }
            }
        }
        // Palette demandée à la voix (0.19.0) : appliquée hors de ce passage, l'interface est reconstruite.
        if (e.palette.isNotEmpty() && e.palette != Palette.choix) horloge.post { choisirPalette(e.palette) }
        val (couleurLien, libelleLien) = when (e.lien) {
            Etat.Lien.ARRETE -> Couleur.GRIS to "Arrêté"
            Etat.Lien.CONNEXION -> Couleur.ORANGE to "Connexion"
            Etat.Lien.CONNECTE -> Couleur.VERT to "Connecté"
            Etat.Lien.RECONNEXION -> Couleur.ORANGE to "Reconnexion"
        }
        pointPastille.setColor(couleurLien)
        pastille.text = libelleLien
        texteDetailConnexion.text = e.connexion
        garderEcran(e.enMarche)

        val (etatAssistant, couleurAssistant, aide) = when {
            !e.enMarche -> Triple(
                "Arrêté", Couleur.TEXTE_2,
                if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED)
                    "Autorise le micro, puis appuie sur Démarrer : ${ConfigMaison.NOM_ASSISTANT} repartira ensuite automatiquement"
                else "Appuie sur Démarrer : ${ConfigMaison.NOM_ASSISTANT} repartira ensuite automatiquement à chaque ouverture",
            )
            e.lien != Etat.Lien.CONNECTE -> Triple("En attente", Couleur.TEXTE_2, "Recherche du serveur")
            e.assistant == "Repos" || e.assistant.isEmpty() ->
                Triple("Repos", Couleur.TEXTE, "Dis « ${ReveilLocal.nom(motAffiche(e))} » ou touche l'orbe")
            // Un second toucher sur l'orbe coupe l'écoute, ou la réponse (0.17.0).
            e.assistant == "Je t'écoute" -> Triple(e.assistant, Couleur.ACCENT_CLAIR, "Touche l'orbe pour couper")
            e.assistant == "Je réfléchis" -> Triple(e.assistant, COULEUR_LLM, e.aideReflexion)
            e.assistant == "Je réponds" -> Triple(e.assistant, Couleur.ORANGE, "Touche l'orbe pour couper la réponse")
            else -> Triple(e.assistant, Couleur.TEXTE, "")
        }
        // Écran ambiant au repos : une seule ligne d'aide sous l'orbe, pas de « Repos ».
        texteAssistant.text = if (largeEcran && etatAssistant == "Repos") "" else etatAssistant
        texteAssistant.setTextColor(couleurAssistant)
        texteAide.text = aide
        // Ligne gardée même vide : l'orbe ne saute pas à chaque changement d'état.
        texteAide.visibility = if (aide.isEmpty()) View.INVISIBLE else View.VISIBLE

        vumetre.progress = (e.niveauDb + 60f).toInt().coerceIn(0, 60)
        val couleur = when {
            e.niveauDb > -10f -> Couleur.ORANGE
            e.niveauDb > -45f -> Couleur.ACCENT
            else -> Couleur.GRIS
        }
        if (couleur != couleurVumetre) {
            couleurVumetre = couleur
            remplissageVumetre.colors = couleursVumetre(couleur)
            vumetre.invalidate()
        }
        texteNiveau.text = if (e.enMarche) "Micro : ${e.niveauDb.toInt()} dB" else "Micro coupé"
        texteScore.text = "Réveil : " +
            (e.score?.let { String.format(Locale.FRANCE, "%.2f", it) } ?: "-")
        orbe.isEnabled = e.enMarche && e.lien == Etat.Lien.CONNECTE
        // Niveau du micro pour l'orbe : de -50 dB (silence) à -10 dB (voix proche).
        val niveau = ((e.niveauDb + 50f) / 40f).coerceIn(0f, 1f)
        orbe.regler(humeur(e), if (e.enMarche) niveau else 0f)
        afficherBref(e)
        val alerte = e.alerteCle.ifEmpty { e.alerteJeton }
        texteAlerte.text = alerte
        texteAlerte.visibility = if (alerte.isEmpty()) View.GONE else View.VISIBLE
        afficherMarche(e)
        afficherDemande(e)
        afficherStation()
        afficherVision(e)
        afficherCoupure(e)
        afficherDirect(e)
        ambiant?.motReveil = ReveilLocal.nom(motAffiche(e))
        ambiant?.maj(e)
        majSecurite()
        ecranMusique?.maj(e)
        ecranMaison?.maj(e)
        // Présence, réveil ou commande : l'écran OLED reprend vie tout de suite, sans attendre la seconde.
        majVeille()

        afficherMode(e)
        afficherTranscription(e)
        afficherCerveau(e)
        afficherReveil(e)

        afficherReponse(e)

        for (champ in listOf(champUrlPc, champUrlHa)) {
            champ.isEnabled = !e.enMarche
            champ.alpha = if (e.enMarche) 0.6f else 1f
        }
        afficherServeur(e)
        afficherDeroule(e)
        // La carte Historique n'est reconstruite que si la liste a changé.
        if (e.historique !== historiqueAffiche) {
            historiqueAffiche = e.historique
            VueHistorique.remplir(
                this,
                conteneurHistorique,
                e.historique.take(5),
                if (e.lien == Etat.Lien.CONNECTE) "Aucune commande pour l'instant" else "Historique reçu à la connexion",
            )
        }
    }

    /** État de l'orbe d'après celui du service. */
    private fun humeur(e: Etat.Instantane): VueOrbe.Humeur = when {
        !e.enMarche -> VueOrbe.Humeur.ARRETE
        e.lien != Etat.Lien.CONNECTE -> VueOrbe.Humeur.DECONNECTE
        e.alerteCle.isNotEmpty() || e.alerteJeton.isNotEmpty() -> VueOrbe.Humeur.ERREUR
        e.assistant == "Je t'écoute" -> VueOrbe.Humeur.ECOUTE
        e.assistant == "Je réfléchis" -> VueOrbe.Humeur.REFLEXION
        e.assistant == "Je réponds" ->
            if (e.historique.firstOrNull()?.let { it.erreur && it.reponse == e.jarvis } == true) VueOrbe.Humeur.ERREUR
            else VueOrbe.Humeur.REPONSE
        "indisponible" in e.assistant || "absent" in e.assistant -> VueOrbe.Humeur.ERREUR
        else -> VueOrbe.Humeur.REPOS
    }

    /** Mot de réveil affiché : celui du serveur quand c'est lui qui guette. */
    private fun motAffiche(e: Etat.Instantane): String =
        if (e.reveilEffectif == "serveur" && ReveilLocal.PERSO_DISPONIBLE &&
            e.capMotReveil.equals(ReveilLocal.nom(ReveilLocal.PERSO), true)) ReveilLocal.PERSO
        else if (e.reveilEffectif == "serveur") ReveilLocal.HEY_JARVIS
        else SatelliteService.motReveilChoisi(this)

    /** Message bref de l'arbitre (« Un autre appareil a répondu »), quelques secondes. */
    private fun afficherBref(e: Etat.Instantane) {
        val age = SystemClock.elapsedRealtime() - e.brefLe
        if (e.bref.isEmpty() || age >= DUREE_BREF_MS) {
            if (texteBref.visibility == View.VISIBLE && age >= DUREE_BREF_MS) texteBref.visibility = View.GONE
            return
        }
        if (texteBref.visibility != View.VISIBLE || texteBref.text != e.bref) {
            texteBref.text = e.bref
            texteBref.visibility = View.VISIBLE
            texteBref.removeCallbacks(masquerBref)
            texteBref.postDelayed(masquerBref, DUREE_BREF_MS - age)
        }
    }

    /** Le bouton Démarrer n'apparaît que si l'assistant est arrêté. L'arrêt se fait dans les réglages (carte Station). */
    private fun afficherMarche(e: Etat.Instantane) {
        val cle = e.enMarche.toString()
        if (cle == cleMarche) return
        cleMarche = cle
        boutonMarche.text = "Démarrer"
        boutonMarche.background = Decor.fondBouton(this, Couleur.VERT, 16f)
        boutonMarche.visibility = if (e.enMarche) View.GONE else View.VISIBLE
        // Sur la tablette, la rangée ne porte que ce bouton. Sur le téléphone, elle garde Réglages.
        if (largeEcran) ligneMarche.visibility = if (e.enMarche) View.GONE else View.VISIBLE
        if (::boutonArreter.isInitialized) activer(boutonArreter, e.enMarche)
    }

    private fun confirmerArret() {
        AlertDialog.Builder(this)
            .setTitle("Arrêter ${ConfigMaison.NOM_ASSISTANT}")
            .setMessage("${ConfigMaison.NOM_ASSISTANT} n'écoutera plus et ne redémarrera pas automatiquement, même au démarrage de la tablette, jusqu'à ce que tu appuies sur Démarrer.")
            .setPositiveButton("Arrêter") { _, _ -> arreter() }
            .setNegativeButton("Annuler", null)
            .show()
    }

    private fun basculerMarche() {
        if (Etat.courant.enMarche) arreter() else demarrer()
    }

    /** Nouvel appareil qui demande l'accès : boîte de dialogue avec son nom et son code. */
    private fun afficherDemande(e: Etat.Instantane) {
        val d = e.demandeAppairage
        if (d == null) {
            if (dialogueAppairage != null) {
                dialogueAppairage?.dismiss()
                dialogueAppairage = null
            }
            idDialogue = ""
            return
        }
        if (d.id == idDialogue) return
        idDialogue = d.id
        dialogueAppairage?.dismiss()
        dialogueAppairage = AlertDialog.Builder(this)
            .setTitle("Demande d'appairage")
            .setMessage(
                "« ${d.nom} » demande l'accès à ${ConfigMaison.NOM_ASSISTANT}.\n\nCode : ${d.code}\n\n" +
                    "Accepte seulement si le même code s'affiche sur le nouvel appareil."
            )
            .setPositiveButton("Accepter") { _, _ -> Etat.actionAppareil?.invoke("appairer", d.id) }
            .setNegativeButton("Refuser") { _, _ -> Etat.actionAppareil?.invoke("refuser_appareil", d.id) }
            .setOnDismissListener { dialogueAppairage = null }
            .show()
    }

    private fun ouvrirAppareils() {
        startActivity(Intent(this, AppareilsActivity::class.java))
    }

    /**
     * Tablette posée en poste fixe : écran allumé tant que le satellite tourne. En mode station,
     * seulement quand la tablette charge (sur batterie, on la laisse s'éteindre).
     */
    private fun garderEcran(enMarche: Boolean) {
        val garder = if (SatelliteService.station(this)) enCharge
        else enMarche && resources.configuration.smallestScreenWidthDp >= 600
        if (garder == ecranGarde) return
        ecranGarde = garder
        if (garder) {
            window.addFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        } else {
            window.clearFlags(WindowManager.LayoutParams.FLAG_KEEP_SCREEN_ON)
        }
    }

    private fun afficherServeur(e: Etat.Instantane) {
        val choisi = SatelliteService.serveurChoisi(this)
        val cle = "$choisi|${e.lien}|${e.connexion}|${e.capServeur}|${e.capVersion}|${e.passerelle}|${e.passerelleDispo}"
        if (cle == cleServeur) return
        cleServeur = cle

        // Choix local : le segment choisi est toujours plein.
        peindreSegments(
            listOf(
                Triple(segmentPc, "pc", Couleur.ACCENT),
                Triple(segmentHa, "ha", Couleur.ACCENT),
                Triple(segmentAppareil, "local", Couleur.ACCENT),
            ),
            choisi,
            "",
        )
        val (couleurPoint, message) = when {
            e.lien == Etat.Lien.CONNECTE && e.capServeur == "local" ->
                (if (e.passerelleDispo) Couleur.VERT else Couleur.ORANGE) to
                    "Tout sur cet appareil (v${e.capVersion}) : réveil, Canary et dictionnaire\nPasserelle Home Assistant : ${e.passerelle.ifEmpty { "en attente" }}"
            e.lien == Etat.Lien.CONNECTE && e.capServeur.isNotEmpty() -> {
                val nom = if (e.capServeur == "ha") "Home Assistant" else "PC"
                val version = if (e.capVersion.isNotEmpty()) " v${e.capVersion}" else ""
                val clair = e.connexion.contains("en clair")
                (if (clair) Couleur.ORANGE else Couleur.VERT) to
                    "Connecté au serveur $nom$version" + if (clair) ", en clair (ancien port)" else ", liaison chiffrée"
            }
            e.lien == Etat.Lien.CONNECTE -> Couleur.VERT to "Connecté"
            e.lien == Etat.Lien.ARRETE -> Couleur.GRIS to "Satellite arrêté"
            else -> Couleur.ORANGE to e.connexion
        }
        pointServeur.setColor(couleurPoint)
        texteServeurEtat.text = message
    }

    private fun afficherMode(e: Etat.Instantane) {
        val connecte = e.lien == Etat.Lien.CONNECTE
        if (!connecte || e.modeActif == modeDemande) modeDemande = ""
        val cle = "${e.modeActif}|$modeDemande|$connecte|${e.modeMessage}"
        if (cle == cleMode) return
        cleMode = cle

        etiquetteEssai.visibility = if (e.modeActif == "essai") View.VISIBLE else View.GONE
        // Essai et Réel sont permis sur tous les serveurs, « Cet appareil » compris.
        peindreSegments(
            listOf(
                Triple(segmentEssai, "essai", Couleur.ESSAI),
                Triple(segmentReel, "reel", Couleur.VERT),
            ),
            e.modeActif,
            modeDemande,
        )
        val (couleurPoint, message) = when {
            !connecte -> Couleur.GRIS to "Le mode est fixé par le serveur à la connexion"
            e.modeActif.isEmpty() -> Couleur.GRIS to "En attente de la confirmation du serveur"
            e.modeActif == "essai" -> Couleur.ESSAI to e.modeMessage.ifEmpty { "Mode essai" }
            else -> Couleur.VERT to e.modeMessage.ifEmpty { "Mode réel" }
        }
        pointMode.setColor(couleurPoint)
        texteMode.text = message
    }

    private fun afficherTranscription(e: Etat.Instantane) {
        val connecte = e.lien == Etat.Lien.CONNECTE
        if (!connecte || e.transcriptionActif == transcriptionDemandee) transcriptionDemandee = ""
        val choix = choixTranscription(e)
        val cle = "${e.transcriptionActif}|$transcriptionDemandee|$connecte|${e.transcriptionMessage}|" +
            choix.joinToString(",") { "${it.first}=${it.second}" } + "|" + (e.capTranscription != null)
        if (cle == cleTranscription) return
        cleTranscription = cle

        reconstruireBoutonsTranscription(choix)
        peindreSegments(segmentsTranscription, e.transcriptionActif, transcriptionDemandee)
        if (e.capTranscription == null) {
            // Rien d'annoncé par le serveur : choix d'avant, grisés et inactifs.
            for ((vue, _, _) in segmentsTranscription) {
                vue.isEnabled = false
                vue.alpha = 0.5f
            }
        }
        val libelle = choix.firstOrNull { it.first == e.transcriptionActif }?.second ?: e.transcriptionActif
        val (couleurPoint, message) = when {
            !connecte -> Couleur.GRIS to "La transcription est fixée par le serveur à la connexion"
            e.transcriptionActif.isEmpty() -> Couleur.GRIS to "En attente de la confirmation du serveur"
            e.transcriptionActif == "ha_whisper" -> Couleur.ORANGE to e.transcriptionMessage.ifEmpty { libelle }
            else -> Couleur.VERT to e.transcriptionMessage.ifEmpty { libelle }
        }
        pointTranscription.setColor(couleurPoint)
        texteTranscription.text = message
    }

    private fun afficherCerveau(e: Etat.Instantane) {
        val souhaite = SatelliteService.preferences(this).getString(SatelliteService.CLE_CERVEAU, null) ?: ""
        val connecte = e.lien == Etat.Lien.CONNECTE
        val libelleClaude = libelleCerveau(e, "claude")
        val libelleLocal = libelleCerveau(e, "local")
        val cle = "${e.cerveauActif}|$souhaite|$connecte|${e.cerveauPret}|${e.cerveauMessage}|${e.capCerveau}|" +
            "$libelleClaude|$libelleLocal"
        if (cle == cleSegments) return
        cleSegments = cle

        // Libellés fournis par le serveur (comme la carte Transcription), sinon ceux d'avant.
        segmentClaude.tag = libelleClaude
        segmentLocal.tag = libelleLocal
        peindreSegments(
            listOf(
                Triple(segmentClaude, "claude", Couleur.ACCENT),
                Triple(segmentLocal, "local", Couleur.ACCENT),
            ),
            e.cerveauActif,
            souhaite,
            e.capCerveau,
        )

        val (couleurPoint, message) = when {
            !connecte -> Couleur.GRIS to
                if (souhaite.isEmpty()) "Choix envoyé au serveur dès la connexion"
                else "${Etat.nomCerveau(souhaite)} sera demandé à la connexion"
            e.cerveauActif.isEmpty() -> Couleur.GRIS to "En attente de la confirmation du serveur"
            e.cerveauPret -> Couleur.VERT to e.cerveauMessage.ifEmpty { "Prêt" }
            else -> Couleur.ORANGE to e.cerveauMessage.ifEmpty { "Préparation..." }
        }
        pointCerveau.setColor(couleurPoint)
        texteCerveau.text = message
    }

    // ---------------------------------------------------------------- actions

    private fun demanderPermissions() {
        val manquantes = mutableListOf<String>()
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            manquantes += Manifest.permission.RECORD_AUDIO
        }
        if (Build.VERSION.SDK_INT >= 33 &&
            checkSelfPermission(Manifest.permission.POST_NOTIFICATIONS) != PackageManager.PERMISSION_GRANTED
        ) {
            manquantes += Manifest.permission.POST_NOTIFICATIONS
        }
        if (SatelliteService.visionChoisie(this) != "off" &&
            checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED
        ) {
            manquantes += Manifest.permission.CAMERA
        }
        if (manquantes.isNotEmpty()) requestPermissions(manquantes.toTypedArray(), 1)
    }

    private fun demarrer() {
        if (Etat.courant.enMarche) return
        if (!enregistrerAdresses()) return
        if (checkSelfPermission(Manifest.permission.RECORD_AUDIO) != PackageManager.PERMISSION_GRANTED) {
            message("Autorise le micro, puis appuie de nouveau sur Démarrer")
            demanderPermissions()
            return
        }
        SatelliteService.preferences(this).edit().putBoolean(SatelliteService.CLE_ARRET_VOLONTAIRE, false)
            .putBoolean(CLE_DEJA_DEMARRE, true).apply()
        try {
            startForegroundService(Intent(this, SatelliteService::class.java))
        } catch (e: Exception) {
            message("Démarrage du service impossible : ${e.javaClass.simpleName}")
        }
    }

    /** Mémorise les deux adresses. Un champ vidé reprend l'adresse par défaut. */
    private fun enregistrerAdresses(): Boolean {
        val pc = champUrlPc.text.toString().trim().ifEmpty { BuildConfig.SERVEUR_PC_DEFAUT }
        val ha = champUrlHa.text.toString().trim().ifEmpty { BuildConfig.SERVEUR_HA_DEFAUT }
        for ((nom, url) in listOf("du PC fixe" to pc, "de Home Assistant" to ha)) {
            if (!url.startsWith("ws://") && !url.startsWith("wss://")) {
                message("L'adresse $nom doit commencer par ws:// ou wss://")
                return false
            }
        }
        SatelliteService.preferences(this).edit()
            .putString(SatelliteService.CLE_URL_PC, pc)
            .putString(SatelliteService.CLE_URL_HA, ha)
            .apply()
        return true
    }

    private fun choisirServeur(serveur: String) {
        if (serveur == SatelliteService.serveurChoisi(this)) return
        if (!Etat.courant.enMarche && !enregistrerAdresses()) return
        SatelliteService.preferences(this).edit().putString(SatelliteService.CLE_SERVEUR, serveur).apply()
        cleServeur = ""
        afficherServeur(Etat.courant)
        val action = Etat.actionReconnecter
        if (action != null && Etat.courant.enMarche) {
            action()
            message("Connexion à ${SatelliteService.nomServeur(serveur)}")
        }
    }

    private fun arreter() {
        // Arrêt demandé : le mode station ne relance pas le service.
        SatelliteService.preferences(this).edit().putBoolean(SatelliteService.CLE_ARRET_VOLONTAIRE, true).apply()
        stopService(Intent(this, SatelliteService::class.java))
    }

    private fun parler() {
        val action = Etat.actionParler
        if (action == null || !Etat.courant.enMarche) {
            message("Démarre d'abord le satellite")
            return
        }
        action()
    }

    private fun choisirCerveau(choix: String) {
        SatelliteService.preferences(this).edit().putString(SatelliteService.CLE_CERVEAU, choix).apply()
        val action = Etat.actionCerveau
        if (action != null && Etat.courant.lien == Etat.Lien.CONNECTE) {
            action(choix)
        } else {
            message("Choix mémorisé, il sera envoyé à la connexion")
        }
        cleSegments = ""
        afficherCerveau(Etat.courant)
    }

    private fun choisirReveil(choix: String) {
        if (choix == SatelliteService.reveilChoisi(this)) return
        SatelliteService.preferences(this).edit().putString(SatelliteService.CLE_REVEIL, choix).apply()
        Etat.actionReveil?.invoke(choix)
        cleReveil = ""
        afficherReveil(Etat.courant)
    }

    /** Hey Jarvis ou le mot de la configuration : mémorisé, puis rechargé à chaud par le service s'il tourne. */
    private fun choisirMotReveil(mot: String) {
        if (mot == SatelliteService.motReveilChoisi(this)) return
        SatelliteService.preferences(this).edit().putString(SatelliteService.CLE_MOT_REVEIL, mot).apply()
        Etat.actionMotReveil?.invoke(mot)
        cleReveil = ""
        afficherReveil(Etat.courant)
        message("Mot de réveil : ${ReveilLocal.nom(mot)}")
    }

    private fun changerSeuil(pas: Float) {
        val actuel = SatelliteService.seuilReveil(this)
        val nouveau = (Math.round((actuel + pas) * 100) / 100f).coerceIn(0.2f, 0.9f)
        // Chaque mot a son seuil (celui de la configuration 0,5 par défaut, Hey Jarvis 0,4).
        SatelliteService.preferences(this).edit().putFloat(SatelliteService.cleSeuilReveil(this), nouveau).apply()
        Etat.actionSeuilReveil?.invoke(nouveau)
        cleReveil = ""
        afficherReveil(Etat.courant)
    }

    private fun afficherReveil(e: Etat.Instantane) {
        val choisi = SatelliteService.reveilChoisi(this)
        val seuil = SatelliteService.seuilReveil(this)
        val mot = SatelliteService.motReveilChoisi(this)
        val cle = "$choisi|$seuil|$mot|${e.reveilEffectif}|${e.capReveilAppareil}|${e.capMotReveil}|${e.lien}|${e.enMarche}"
        if (cle == cleReveil) return
        cleReveil = cle
        peindreSegments(
            listOf(
                Triple(segmentHeyJarvis, ReveilLocal.HEY_JARVIS, Couleur.ACCENT),
                Triple(segmentPerso, ReveilLocal.PERSO, Couleur.ACCENT),
            ),
            mot,
            "",
        )
        // Choix local, comme le serveur : le segment choisi est toujours plein.
        peindreSegments(
            listOf(
                Triple(segmentReveilAppareil, "appareil", Couleur.ACCENT),
                Triple(segmentReveilServeur, "serveur", Couleur.ACCENT),
            ),
            choisi,
            "",
        )
        val (couleur, message) = when {
            !e.enMarche -> Couleur.GRIS to "Satellite arrêté"
            e.reveilEffectif == "appareil" ->
                Couleur.VERT to "« ${ReveilLocal.nom(mot)} » guetté sur cet appareil, le son ne part qu'après le mot"
            e.reveilEffectif == "serveur" && choisi == "appareil" && !e.capReveilAppareil ->
                Couleur.ORANGE to "Serveur trop ancien, c'est lui qui guette (son envoyé en continu)"
            e.reveilEffectif == "serveur" && choisi == "appareil" ->
                Couleur.ORANGE to "Modèle illisible sur cet appareil, c'est le serveur qui guette"
            e.reveilEffectif == "serveur" -> Couleur.VERT to
                "Guetté par le serveur : « ${e.capMotReveil.ifEmpty { "Hey Jarvis" }} », réglé sur le serveur (son envoyé en continu)"
            else -> Couleur.GRIS to "En attente du serveur"
        }
        pointReveil.setColor(couleur)
        texteReveil.text = message
        texteSeuil.text = if (choisi == "appareil") {
            "Seuil de réveil : " + String.format(Locale.FRANCE, "%.2f", seuil)
        } else {
            "Seuil réglé sur le serveur"
        }
    }

    private fun choisirMode(choix: String) {
        val action = Etat.actionMode
        if (action == null || Etat.courant.lien != Etat.Lien.CONNECTE) {
            message("Connecte d'abord le satellite au serveur")
            return
        }
        action(choix)
        modeDemande = if (Etat.courant.modeActif == choix) "" else choix
        cleMode = ""
        afficherMode(Etat.courant)
    }

    private fun choisirTranscription(choix: String) {
        if (Etat.actionTranscription == null || Etat.courant.lien != Etat.Lien.CONNECTE) {
            message("Connecte d'abord le satellite au serveur")
            return
        }
        val prefs = SatelliteService.preferences(this)
        when {
            choix == "ha_whisper" && Etat.courant.transcriptionActif != "ha_whisper" -> confirmer(
                "Transcription Whisper",
                "Whisper sur Home Assistant met environ 90 secondes par phrase. Continuer ?",
            ) { envoyerTranscription(choix) }
            // Transcription en ligne : confirmation la première fois seulement (mémorisée).
            choix == "api" && !prefs.getBoolean(CLE_API_ACCEPTEE, false) -> confirmer(
                "Transcription en ligne",
                "En ligne, ta voix est envoyée à un service extérieur pour être transcrite. Continuer ?",
            ) {
                prefs.edit().putBoolean(CLE_API_ACCEPTEE, true).apply()
                envoyerTranscription(choix)
            }
            else -> envoyerTranscription(choix)
        }
    }

    private fun confirmer(titre: String, texte: String, suite: () -> Unit) {
        AlertDialog.Builder(this)
            .setTitle(titre)
            .setMessage(texte)
            .setPositiveButton("Continuer") { _, _ -> suite() }
            .setNegativeButton("Annuler", null)
            .show()
    }

    private fun envoyerTranscription(choix: String) {
        val action = Etat.actionTranscription
        if (action == null || Etat.courant.lien != Etat.Lien.CONNECTE) {
            message("Connexion perdue, choix non envoyé")
            return
        }
        action(choix)
        transcriptionDemandee = if (Etat.courant.transcriptionActif == choix) "" else choix
        cleTranscription = ""
        afficherTranscription(Etat.courant)
    }

    private fun majBatterie() {
        val pm = getSystemService(PowerManager::class.java)
        val ignoree = pm?.isIgnoringBatteryOptimizations(packageName) == true
        cleStation = ""
        afficherStation()
        texteBatterie.text = if (ignoree) {
            "Optimisation de batterie désactivée pour ${ConfigMaison.NOM_ASSISTANT}"
        } else {
            "Optimisation de batterie active : le service risque d'être coupé écran éteint"
        }
    }

    private fun ouvrirBatterie() {
        val pm = getSystemService(PowerManager::class.java)
        val dejaFait = pm?.isIgnoringBatteryOptimizations(packageName) == true
        try {
            if (dejaFait) {
                message("Déjà désactivée pour ${ConfigMaison.NOM_ASSISTANT}")
                startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            } else {
                startActivity(
                    Intent(Settings.ACTION_REQUEST_IGNORE_BATTERY_OPTIMIZATIONS, Uri.parse("package:$packageName"))
                )
            }
        } catch (e: ActivityNotFoundException) {
            try {
                startActivity(Intent(Settings.ACTION_IGNORE_BATTERY_OPTIMIZATION_SETTINGS))
            } catch (_: Exception) {
                message("Réglage introuvable sur cet appareil")
            }
        }
    }

    private fun message(texte: String) {
        Toast.makeText(this, texte, Toast.LENGTH_LONG).show()
    }
}
