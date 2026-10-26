package assistant.vocal.jarvis

import android.content.Context
import android.os.SystemClock
import android.speech.tts.TextToSpeech
import android.speech.tts.UtteranceProgressListener
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.text.SimpleDateFormat
import java.util.Date
import java.util.Locale
import java.util.concurrent.Executors
import kotlin.math.sqrt

/**
 * Mode « Cet appareil » : tout l'assistant sur le téléphone ou la tablette, sans serveur.
 * Mot de réveil (ReveilLocal), découpe de la phrase (mêmes règles que poc/serveur_satellite.py),
 * transcription Canary (CanaryLocal), dictionnaire embarqué (DictionnaireLocal), puis réponse
 * lue par la voix française d'Android. Chaque étape est publiée en direct dans Etat.deroule.
 *
 * v0.10.0 : en réel, les actions du dictionnaire partent directement à l'API REST de Home
 * Assistant, une phrase inconnue va à Assist (API conversation), puis au LLM : Haiku par l'appli de
 * l'assistant sur HA (message {"type":"llm"}), ou un LLM sur l'appareil (pas encore installé).
 *
 * v0.15.0 : plus de jeton Home Assistant dans l'APK. Toutes les requêtes HA passent par la
 * passerelle de l'appli de l'assistant sur HA (PasserelleHa), qui a son propre jeton et revérifie la
 * sécurité. La fin de phrase est trouvée par Silero VAD (repli sur l'énergie si le modèle ne
 * charge pas), et le mot de réveil est au choix (Hey Jarvis ou celui de la configuration).
 *
 * v0.16.0 : « écoute attentive ». Avec l'option Couper la parole, le micro reste ouvert pendant que
 * l'assistant répond (source VOICE_COMMUNICATION et annulation d'écho, voir SatelliteService) et seul le
 * mot de réveil, avec un seuil relevé de 0,1 contre l'écho résiduel, arrête la voix et repart en
 * écoute. Une autre voix (la télé, une discussion) ne coupe rien. Toucher l'orbe coupe aussi. La
 * personne reconnue par la caméra accompagne chaque commande (historique, llm, manque, retour).
 *
 * v0.16.1 : transcription en direct. Canary ne travaille pas en flux : pendant l'écoute, toutes
 * les 1,2 s (2,5 s si une passe dépasse 1,5 s) et seulement quand Silero entend de la parole, une
 * passe transcrit tout le son depuis le début de la phrase, dans un fil à part, jamais deux à la
 * fois. Le texte partiel n'est qu'affiché : rien n'est décidé dessus, la transcription finale reste
 * celle de la fin de phrase.
 */
class MoteurLocal(
    private val contexte: Context,
    /** Son de début ou de fin d'écoute (SonsEcoute, 0.23.0). */
    private val son: (SonsEcoute.Son) -> Unit,
    @Volatile var seuilReveil: Float,
    /** true : Home Assistant est vraiment piloté. false : essai, rien ne part. */
    @Volatile var reel: Boolean,
    /** LLM de secours : "claude" (Haiku par l'appli de l'assistant sur HA) ou "local" (sur l'appareil). */
    @Volatile var cerveau: String,
    /** Adresse WebSocket de l'appli de l'assistant sur HA : passerelle Home Assistant et Haiku. */
    urlJarvisHa: String,
    /** Mot de réveil guetté : ReveilLocal.HEY_JARVIS ou ReveilLocal.PERSO. */
    @Volatile var motReveil: String = ReveilLocal.PERSO,
    /** Annonces de l'appli de l'assistant sur HA (demande d'appairage). */
    annonce: (JSONObject) -> Unit = {},
    /** La passerelle devient disponible ou ne l'est plus. */
    changementPasserelle: () -> Unit = {},
    /** Adresse du serveur du PC, pour la transcription déportée (0.17.0). Vide : pas de connexion. */
    urlPc: String = "",
    /** Les moteurs de transcription du PC sont connus, ou perdus. */
    changementTranscription: () -> Unit = {},
) : AutoCloseable {

    /** Seul chemin vers Home Assistant : aucun jeton HA n'est embarqué dans l'APK. */
    val passerelle = PasserelleHa(
        contexte, urlJarvisHa, annonce,
        changement = {
            surCapacitesRoutines()
            changementPasserelle()
        },
        routinesMaj = { surRoutinesMaj() },
    )

    /** Routines reçues du serveur (0.40.0, S-R3) : reconnues ici, exécutées et jugées par le serveur. */
    private val routines = RoutinesLocal()
    private val verrouRoutines = Any()
    /** Dernier échec de lecture de la liste des routines, pour ne pas retenter à chaque phrase. */
    @Volatile private var routinesEchecLe = 0L

    /**
     * Où transcrire la phrase découpée (0.17.0) : OuTranscrire.TABLETTE (Canary ici), PC, HA ou EN_LIGNE.
     * La transcription en direct pendant la phrase reste toujours sur la tablette.
     */
    @Volatile var lieuTranscription = OuTranscrire.TABLETTE

    /** Connexion au PC pour la transcription déportée, ouverte dès le démarrage pour connaître ses moteurs. */
    val transcriptionPc: TranscriptionPc? = if (urlPc.isNotBlank()) TranscriptionPc(contexte, urlPc, changementTranscription) else null

    private enum class Phase { CHARGEMENT, REPOS, ECOUTE, TRAITEMENT, REPONSE, ARRET }

    /** Option Couper la parole (préférence), relue à chaque réponse. */
    @Volatile var couperParole = false

    /**
     * Vrai pendant une réponse qu'on peut couper : la boucle de capture rouvre alors le micro en
     * source VOICE_COMMUNICATION avec l'annulation d'écho, et revient à VOICE_RECOGNITION ensuite
     * (meilleure pour Canary).
     */
    val sourceCommunication: Boolean get() = phase == Phase.REPONSE

    /** Transcription en direct (préférence, activée par défaut). */
    @Volatile var transcriptionDirecte = true
    /** Fil des passes partielles, à part du fil de travail : la fin de phrase n'attend jamais. */
    private val direct = Executors.newSingleThreadExecutor()
    @Volatile private var passeEnCours = false
    /** Numéro de la phrase écoutée : une passe d'une phrase finie est ignorée. */
    @Volatile private var generation = 0
    private var dernierePasseLe = 0L
    @Volatile private var intervallePasses = INTERVALLE_DIRECT_MS
    private var passes = 0
    private val detailPasses = StringBuilder()

    /** Qui parle au début de la commande en cours : prénom reconnu, « inconnu », ou vide (Etat.quiParle). */
    @Volatile private var personne = ""

    @Volatile private var phase = Phase.CHARGEMENT
    private val travail = Executors.newSingleThreadExecutor()
    private val minuteur = Executors.newSingleThreadScheduledExecutor()

    // Utilisés seulement par le thread de capture.
    private var reveil: ReveilLocal? = null
    /** Modèle rechargé à chaud, repris par le fil de capture au bloc suivant. */
    @Volatile private var reveilNouveau: ReveilLocal? = null
    private var reveilAReinitialiser = false
    /** Silero VAD, ou null : seuil d'énergie comme avant. */
    @Volatile private var vad: VadSilero? = null
    @Volatile private var vadAReinitialiser = false
    private var sourdJusqua = 0L
    private var bruit = 0.004
    private val capture = ArrayList<ShortArray>()
    private var parle = false
    private var silence = 0.0
    private var tEcoute = 0L
    private var origine = ""
    private var picVoix = 0.0

    @Volatile private var canary: CanaryLocal? = null
    @Volatile private var dico: DictionnaireLocal? = null
    @Volatile private var voix: TextToSpeech? = null
    @Volatile private var voixPrete = false
    @Volatile private var finLecture: (() -> Unit)? = null

    // ------------------------------------------------------------ chargement

    fun demarrer() {
        Etat.modifier { it.copy(deroule = emptyList(), derouleTitre = "Démarrage de ${ConfigMaison.NOM_ASSISTANT} sur cet appareil") }
        passerelle.ouvrir()
        transcriptionPc?.ouvrir()
        travail.execute {
            etape("Dictionnaire") {
                val d = DictionnaireLocal(contexte)
                dico = d
                "${d.taille} formes, généré le ${d.genereLe}, ${d.etatAppris}" to Etat.Statut.OK
            }
            etape("Mot de réveil") {
                reveil = ReveilLocal(contexte, mot = motReveil)
                "openWakeWord « ${ReveilLocal.nom(motReveil)} », seuil " + "%.2f".format(Locale.FRANCE, seuilReveil) to Etat.Statut.OK
            }
            etape("Détection de parole") {
                try {
                    vad = VadSilero(contexte)
                    "Silero VAD v5, fin de phrase après 0,45 s de silence" to Etat.Statut.OK
                } catch (e: Throwable) {
                    Log.e(TAG, "Silero VAD impossible", e)
                    "Silero VAD indisponible (${e.javaClass.simpleName}), seuil d'énergie à la place" to Etat.Statut.ECHEC
                }
            }
            etape("Voix de réponse") {
                val attente = java.util.concurrent.CountDownLatch(1)
                var resultat = TextToSpeech.ERROR
                val tts = TextToSpeech(contexte) { s ->
                    resultat = s
                    attente.countDown()
                }
                attente.await(10, java.util.concurrent.TimeUnit.SECONDS)
                if (resultat == TextToSpeech.SUCCESS) {
                    val langue = tts.setLanguage(Locale.FRANCE)
                    // Usage « assistant » : la voix reste sur le haut-parleur (pas l'écouteur d'un téléphone
                    // en mode communication) et l'annulation d'écho la prend comme voie de référence.
                    tts.setAudioAttributes(
                        android.media.AudioAttributes.Builder()
                            .setUsage(android.media.AudioAttributes.USAGE_ASSISTANT)
                            .setContentType(android.media.AudioAttributes.CONTENT_TYPE_SPEECH)
                            .build()
                    )
                    tts.setOnUtteranceProgressListener(object : UtteranceProgressListener() {
                        override fun onStart(id: String?) {}
                        // Le texte de la réponse avance au rythme de la voix, mot par mot.
                        override fun onRangeStart(id: String?, start: Int, end: Int, frame: Int) {
                            val t = texteDit
                            if (end in 1..t.length) {
                                val fin = t.indexOf(' ', end).let { if (it < 0) t.length else it }
                                Etat.modifier { it.copy(parole = t.substring(0, fin)) }
                            }
                        }
                        override fun onStop(id: String?, interrupted: Boolean) = finParole()
                        override fun onDone(id: String?) {
                            finParole()
                            lectureTerminee()
                        }
                        @Deprecated("Deprecated in Java")
                        override fun onError(id: String?) {
                            finParole()
                            lectureTerminee()
                        }
                    })
                    voix = tts
                    voixPrete = langue >= TextToSpeech.LANG_AVAILABLE
                    (if (voixPrete) "voix française d'Android (${tts.defaultEngine})" else "français indisponible, réponses affichées seulement") to
                        (if (voixPrete) Etat.Statut.OK else Etat.Statut.ECHEC)
                } else {
                    "synthèse vocale indisponible, réponses affichées seulement" to Etat.Statut.ECHEC
                }
            }
            val dossier = CanaryLocal.dossierModele(contexte)
            if (!CanaryLocal.modelePresent(contexte)) {
                ajouterEtape("Canary", "modèle absent de $dossier : à copier par adb (1,03 Go)", Etat.Statut.ECHEC)
                Etat.modifier { it.copy(assistant = "Modèle Canary absent") }
                return@execute
            }
            etape("Canary (chargement)") {
                val c = CanaryLocal(dossier)
                canary = c
                "1,03 Go en mémoire (${c.chargements.joinToString(", ")})" to Etat.Statut.OK
            }
            if (cerveau == "local") chargerLlmAppareil()
            if (phase == Phase.CHARGEMENT) phase = Phase.REPOS
            Etat.modifier { it.copy(assistant = "Repos") }
        }
    }

    // ------------------------------------------------------------ audio (thread de capture)

    /** Appelé toutes les 80 ms par la boucle de capture avec un bloc de 1280 échantillons. */
    fun bloc(b: ShortArray) {
        var somme = 0.0
        for (s in b) somme += s.toDouble() * s
        val niveau = sqrt(somme / b.size) / 32768.0
        when (phase) {
            Phase.REPOS -> {
                bruit = 0.95 * bruit + 0.05 * minOf(niveau, 0.05)
                reveilNouveau?.let { n ->
                    // Changement de mot de réveil : l'ancien modèle est fermé par ce fil, seul à s'en servir.
                    reveilNouveau = null
                    val ancien = reveil
                    reveil = n
                    try {
                        ancien?.close()
                    } catch (_: Exception) {
                    }
                }
                val r = reveil ?: return
                if (reveilAReinitialiser) {
                    reveilAReinitialiser = false
                    r.reinitialiser()
                }
                if (SystemClock.elapsedRealtime() < sourdJusqua) return
                val score = r.bloc(b)
                Etat.modifier { it.copy(score = score.toDouble()) }
                if (score >= seuilReveil) commencerEcoute("« ${ReveilLocal.nom(motReveil)} », score " + "%.2f".format(Locale.FRANCE, score))
            }
            Phase.ECOUTE -> ecouter(b, niveau)
            Phase.REPONSE -> guetterPendantReponse(b)
            else -> {}
        }
    }

    /**
     * Toucher l'orbe (ou regard soutenu) : au repos, lance l'écoute. Depuis la 0.17.0 (demande du
     * propriétaire), un second toucher coupe l'écoute en cours sans rien transcrire, ou coupe la réponse si
     * l'assistant parle, et revient au repos. Le mot de réveil dit pendant la réponse, lui, la coupe et
     * relance l'écoute (guetterPendantReponse).
     */
    fun parler(origine: String = "orbe touché") {
        when (phase) {
            Phase.REPOS -> commencerEcoute(origine)
            // Le fil de capture remplit la phrase : c'est lui qui l'abandonne, au bloc suivant.
            Phase.ECOUTE -> annulerEcoute = true
            Phase.REPONSE, Phase.TRAITEMENT -> if (finLecture != null) arreterReponse()
            else -> {}
        }
    }

    /** Second toucher sur l'orbe pendant l'écoute, pris en compte par le fil de capture. */
    @Volatile private var annulerEcoute = false

    /** Second toucher pendant la réponse : la voix s'arrête, retour au repos sans réécouter. */
    private fun arreterReponse() {
        finLecture = null
        try {
            voix?.stop()
        } catch (_: Exception) {
        }
        ajouterEtape("Réponse coupée", "orbe touché pendant la réponse", Etat.Statut.SAUTE)
        retourAuRepos()
    }

    /** Pendant la réponse : seul le mot de réveil choisi, seuil relevé de 0,1, coupe la parole. */
    private fun guetterPendantReponse(b: ShortArray) {
        reveilNouveau?.let { n ->
            reveilNouveau = null
            val ancien = reveil
            reveil = n
            try {
                ancien?.close()
            } catch (_: Exception) {
            }
        }
        val r = reveil ?: return
        if (reveilAReinitialiser) {
            reveilAReinitialiser = false
            r.reinitialiser()
        }
        // Le temps que le micro passe en mode communication et que l'écho du début retombe.
        if (SystemClock.elapsedRealtime() < sourdJusqua) return
        val score = r.bloc(b)
        Etat.modifier { it.copy(score = score.toDouble()) }
        if (score >= seuilReveil + SURCROIT_COUPURE) {
            couper("« ${ReveilLocal.nom(motReveil)} » pendant la réponse, score " + "%.2f".format(Locale.FRANCE, score))
        }
    }

    /** Arrêt immédiat de la voix, la suite de la réponse est abandonnée, écoute d'une nouvelle phrase. */
    private fun couper(origine: String) {
        finLecture = null
        try {
            voix?.stop()
        } catch (_: Exception) {
        }
        commencerEcoute(origine, avecSon = false)
    }

    /** Nouveau mot de réveil : chargé sur le fil de travail, pris par le fil de capture ensuite. */
    fun changerMotReveil(mot: String) {
        if (mot == motReveil) return
        motReveil = mot
        travail.execute {
            etape("Mot de réveil") {
                reveilNouveau = ReveilLocal(contexte, mot = mot)
                "openWakeWord « ${ReveilLocal.nom(mot)} » rechargé, seuil " + "%.2f".format(Locale.FRANCE, seuilReveil) to Etat.Statut.OK
            }
        }
    }

    private fun commencerEcoute(origine: String, avecSon: Boolean = true) {
        this.origine = origine
        annulerEcoute = false
        personne = Etat.courant.quiParle()
        capture.clear()
        parle = false
        silence = 0.0
        picVoix = 0.0
        tEcoute = SystemClock.elapsedRealtime()
        vadAReinitialiser = true
        generation++
        dernierePasseLe = tEcoute
        intervallePasses = INTERVALLE_DIRECT_MS
        passes = 0
        synchronized(detailPasses) { detailPasses.setLength(0) }
        // Comme le serveur : on ignore le son de début et la fin du mot de réveil, plus longtemps pour un
        // son de début qui traîne (Halo, Bronze, 0.23.0).
        sourdJusqua = tEcoute + if (avecSon) maxOf(600L, SonsEcoute.dureeSourdeMs(contexte)) else 600L
        phase = Phase.ECOUTE
        // Après une parole coupée, pas de son : la voix qui s'arrête suffit comme signal.
        if (avecSon) son(SonsEcoute.Son.DEBUT)
        Etat.modifier {
            it.copy(
                assistant = "Je t'écoute",
                activiteLe = SystemClock.elapsedRealtime(),
                entendu = "", entenduFinal = false, toi = "", jarvis = "", parole = "", paroleFinLe = 0L,
                derouleTitre = "Commande de " + HEURE.format(Date()) + if (personne.isNotEmpty()) ", $personne" else "",
                deroule = listOf(
                    Etat.Etape("Réveil", origine, null, Etat.Statut.OK),
                    Etat.Etape("Écoute", "parle maintenant", null, Etat.Statut.EN_COURS),
                ),
            )
        }
    }

    private fun ecouter(b: ShortArray, niveau: Double) {
        if (annulerEcoute) {
            // Second toucher sur l'orbe : la phrase est abandonnée, rien ne part à la transcription.
            annulerEcoute = false
            generation++
            capture.clear()
            majEtape("Écoute", "coupée : orbe touché une seconde fois, rien n'est transcrit", null, Etat.Statut.SAUTE)
            Etat.modifier { it.copy(entendu = "", entenduFinal = false) }
            retourAuRepos()
            return
        }
        val maintenant = SystemClock.elapsedRealtime()
        if (maintenant < sourdJusqua) return
        // Plus tolérant que le serveur (3,5 fois le bruit, 0,012 au moins) : on parle
        // doucement dans sa chambre, loin de la tablette (13/10/2026).
        val seuil = maxOf(bruit * SEUIL_BRUIT, NIVEAU_MIN)
        val v = vad
        if (v != null && vadAReinitialiser) {
            vadAReinitialiser = false
            v.reinitialiser()
        }
        // Silero VAD décide s'il y a de la parole, l'énergie ne sert plus que de repli.
        val fort = if (v != null) v.parole(b) else niveau > seuil
        if (niveau > picVoix) picVoix = niveau
        capture.add(b.copyOf())
        if (parle && fort) lancerPasseDirecte(maintenant)
        if (!parle) {
            if (fort) {
                parle = true
                majEtape("Écoute", "je t'entends", null, Etat.Statut.EN_COURS)
            } else if (maintenant - tEcoute > ATTENTE_MAX_MS) {
                majEtape(
                    "Écoute",
                    if (v != null) "rien entendu en 8 s : Silero n'a pas reconnu de parole (voix au plus à ${db(picVoix)}, bruit de fond ${db(bruit)})"
                    else "rien entendu en 8 s : voix au plus à ${db(picVoix)}, il fallait dépasser ${db(seuil)} (bruit de fond ${db(bruit)})",
                    null, Etat.Statut.ECHEC,
                )
                retourAuRepos()
            } else {
                while (capture.size > 4) capture.removeAt(0) // 320 ms gardées avant la parole
            }
            return
        }
        silence = if (fort) 0.0 else silence + BLOC_S
        val duree = capture.size * BLOC_S
        if (silence >= (if (v != null) SILENCE_FIN_VAD_S else SILENCE_FIN_S) || duree > DUREE_MAX_S) {
            phase = Phase.TRAITEMENT
            generation++
            if (passes > 0) {
                majEtape("Transcription en direct", synchronized(detailPasses) { detailPasses.toString() }, null, Etat.Statut.OK)
            }
            val pcm = ShortArray(capture.sumOf { it.size })
            var k = 0
            for (c in capture) {
                System.arraycopy(c, 0, pcm, k, c.size)
                k += c.size
            }
            capture.clear()
            majEtape(
                "Écoute",
                "%.1f s de son, fin sur %.1f s de silence\nvoix au plus à %s, %s, bruit de fond %s".format(
                    Locale.FRANCE, duree, silence, db(picVoix),
                    if (v != null) "parole détectée par Silero VAD" else "seuil " + db(seuil), db(bruit),
                ),
                null, Etat.Statut.OK,
            )
            son(SonsEcoute.Son.FIN)
            Etat.modifier { it.copy(assistant = "Je réfléchis") }
            travail.execute { traiter(pcm) }
        }
    }

    /**
     * Fil de capture : une passe partielle sur tout le son de la phrase, si l'option est active,
     * si Silero entend de la parole (seul appelant), si l'intervalle est écoulé et si aucune passe
     * ne tourne encore.
     */
    private fun lancerPasseDirecte(maintenant: Long) {
        if (!transcriptionDirecte || passeEnCours || muet) return
        val c = canary ?: return
        if (maintenant - dernierePasseLe < intervallePasses) return
        dernierePasseLe = maintenant
        val pcm = ShortArray(capture.sumOf { it.size })
        var k = 0
        for (morceau in capture) {
            System.arraycopy(morceau, 0, pcm, k, morceau.size)
            k += morceau.size
        }
        val numero = generation
        passeEnCours = true
        try {
            direct.execute {
                try {
                    amplifier(pcm)
                    val t0 = SystemClock.elapsedRealtime()
                    val r = c.transcrire(pcm)
                    val ms = SystemClock.elapsedRealtime() - t0
                    // Passe trop lente pour l'appareil : on les espace.
                    if (ms > LENTEUR_DIRECT_MS) intervallePasses = INTERVALLE_DIRECT_LENT_MS
                    if (numero != generation || phase != Phase.ECOUTE) return@execute
                    passes++
                    val ligne = "passe $passes : " + "%.2f".format(Locale.FRANCE, ms / 1000.0) + " s pour " +
                        "%.1f".format(Locale.FRANCE, pcm.size / 16000.0) + " s de son, « ${r.texte} »"
                    val detail = synchronized(detailPasses) {
                        if (detailPasses.isNotEmpty()) detailPasses.append('\n')
                        detailPasses.append(ligne)
                        if (intervallePasses == INTERVALLE_DIRECT_LENT_MS) detailPasses.append(" (passes espacées à 2,5 s)")
                        detailPasses.toString()
                    }
                    majEtape("Transcription en direct", detail, ms, Etat.Statut.EN_COURS)
                    if (r.texte.isNotBlank()) Etat.modifier { it.copy(entendu = r.texte, entenduFinal = false) }
                } catch (e: Exception) {
                    Log.w(TAG, "Passe partielle impossible", e)
                } finally {
                    passeEnCours = false
                }
            }
        } catch (_: Exception) {
            passeEnCours = false
        }
    }

    private fun retourAuRepos() {
        reveilAReinitialiser = true
        sourdJusqua = SystemClock.elapsedRealtime() + 300
        phase = Phase.REPOS
        Etat.modifier { it.copy(assistant = "Repos") }
    }

    // ------------------------------------------------------------ traitement (thread de travail)

    private fun traiter(pcm: ShortArray) {
        val debut = SystemClock.elapsedRealtime()
        val c = canary
        val d = dico
        if (c == null || d == null) {
            ajouterEtape("Transcription", "Canary n'est pas chargé", Etat.Statut.ECHEC)
            retourAuRepos()
            return
        }
        val gain = amplifier(pcm)
        // Où transcrire (0.17.0) : la phrase part au serveur choisi, sinon (ou en repli) Canary ici.
        val texte = transcrireDeporte(pcm, gain) ?: run {
            ajouterEtape("Transcription (Canary)", "en cours", Etat.Statut.EN_COURS)
            val r = try {
                c.transcrire(pcm)
            } catch (e: Exception) {
                Log.e(TAG, "Canary a échoué", e)
                majEtape("Transcription (Canary)", "erreur : ${e.message}", null, Etat.Statut.ECHEC)
                retourAuRepos()
                return
            }
            val msStt = r.msPreparation + r.msEncodeur + r.msDecodeur
            majEtape(
                "Transcription (Canary)",
                "« ${r.texte} »  (encodeur ${r.msEncodeur} ms, décodeur ${r.msDecodeur} ms pour ${r.jetons} jetons" +
                    (if (gain > 1.01) ", voix basse amplifiée x" + "%.1f".format(Locale.FRANCE, gain) else "") + ")",
                msStt, if (r.texte.isBlank()) Etat.Statut.ECHEC else Etat.Statut.OK,
            )
            r.texte
        }
        Etat.modifier { it.copy(toi = texte, jarvis = "", voie = "", entendu = texte, entenduFinal = true) }
        if (texte.isBlank()) {
            terminer(texte, "rien compris", "", emptyList(), "Je n'ai rien entendu.", SystemClock.elapsedRealtime() - debut)
            return
        }
        comprendre(texte, d, debut)
    }

    /**
     * Transcription déportée (0.17.0) : la phrase découpée part au PC, à HA ou en ligne selon
     * [lieuTranscription], 8 s au plus. Rend le texte, ou null pour transcrire ici avec Canary (lieu
     * « Sur la tablette », moteur non annoncé, pas de réponse, erreur ou rien reconnu), avec un message
     * bref sous l'orbe. Le Déroulé dit le moteur, son temps côté serveur et l'aller-retour.
     */
    private fun transcrireDeporte(pcm: ShortArray, gain: Double): String? {
        val lieu = lieuTranscription
        if (lieu == OuTranscrire.TABLETTE) return null
        val nom = "Transcription (${OuTranscrire.nom(lieu)})"
        val voie = OuTranscrire.voie(lieu, transcriptionPc?.transcriptions, passerelle.transcriptions)
        if (voie == null) {
            val pourquoi = if (lieu == OuTranscrire.PC) "PC injoignable ou sans transcription (${transcriptionPc?.etat ?: "adresse absente"})"
            else "moteur non annoncé par le serveur (passerelle : ${passerelle.etat})"
            ajouterEtape(nom, "$pourquoi : faite sur la tablette", Etat.Statut.ECHEC)
            bref("Transcription sur ${OuTranscrire.nom(lieu)} indisponible : faite sur la tablette")
            return null
        }
        ajouterEtape(nom, "%.1f".format(Locale.FRANCE, pcm.size / 16000.0) + " s de son envoyées, moteur ${voie.moteur}", Etat.Statut.EN_COURS)
        val t0 = SystemClock.elapsedRealtime()
        val reponse = try {
            if (voie.connexion == OuTranscrire.PC) transcriptionPc?.transcrire(pcm, voie.moteur, OuTranscrire.DELAI_MS)
            else passerelle.transcrire(pcm, voie.moteur, OuTranscrire.DELAI_MS)
        } catch (e: Exception) {
            Log.w(TAG, "Transcription déportée impossible", e)
            null
        }
        val ms = SystemClock.elapsedRealtime() - t0
        val issue = OuTranscrire.issue(reponse)
        if (issue.texte == null) {
            majEtape(nom, "${issue.repli} : repli sur Canary de la tablette", ms, Etat.Statut.ECHEC)
            bref("Transcription sur ${OuTranscrire.nom(lieu)} : ${issue.repli}, faite sur la tablette")
            return null
        }
        majEtape(
            nom,
            "« ${issue.texte} »  (moteur ${issue.moteur.ifEmpty { voie.moteur }}, ${issue.msServeur} ms côté serveur, " +
                "$ms ms aller-retour" + (if (gain > 1.01) ", voix basse amplifiée x" + "%.1f".format(Locale.FRANCE, gain) else "") + ")",
            ms, Etat.Statut.OK,
        )
        return issue.texte
    }

    private fun bref(message: String) {
        Etat.modifier { it.copy(bref = message, brefLe = SystemClock.elapsedRealtime()) }
    }

    /**
     * Phrase écrite envoyée par adb (RecepteurBanc, extra « phrase ») : même parcours qu'une phrase
     * entendue, dans le service au premier plan, mais TOUJOURS en essai, rien n'est exécuté.
     */
    fun testerTexte(texte: String) {
        travail.execute {
            val d = dico ?: return@execute
            if (phase != Phase.REPOS) return@execute
            phase = Phase.TRAITEMENT
            val ancien = reel
            reel = false
            muet = true // test de nuit : la réponse s'affiche sans être dite
            try {
                Etat.modifier {
                    it.copy(
                        toi = texte, jarvis = "", voie = "", assistant = "Je réfléchis",
                        derouleTitre = "Test écrit de " + HEURE.format(Date()) + " (essai forcé)",
                        deroule = listOf(Etat.Etape("Phrase écrite", "« $texte », envoyée par adb", null, Etat.Statut.OK)),
                    )
                }
                comprendre(texte, d, SystemClock.elapsedRealtime())
            } finally {
                reel = ancien
                muet = false
            }
        }
    }

    private fun comprendre(texteEntendu: String, d: DictionnaireLocal, debut: Long) {
        // Routines (0.40.0, S-R3) : avant tout le reste, comme sur le serveur. Une phrase de routine est reconnue ici
        // (liste reçue du serveur), exécutée et jugée par lui. Une demande de création ou de gestion, ou la réponse
        // « oui » ou « non » à un brouillon, ne va jamais au LLM ordinaire, qui agirait sur-le-champ.
        val routine = try {
            traiterRoutines(texteEntendu, debut)
        } catch (e: Exception) {
            Log.w(TAG, "Routines : traitement impossible", e)
            false
        }
        if (routine) return
        // Question de météo (0.25.0, remplace le raccourci « quel temps demain » de la 0.20.0) : comprise sans LLM,
        // la réponse est calculée sur les prévisions lues, dite, et le panneau Météo s'ouvre sur la bonne page, le bon
        // jour et la plage demandée, avec la réponse écrite. Rien n'est commandé.
        val meteo = try {
            repondreMeteo(texteEntendu, debut)
        } catch (e: Exception) {
            Log.w(TAG, "Question de météo illisible", e)
            false
        }
        if (meteo) return
        // Palette des écrans (0.19.0) : comprise ici, sans le dictionnaire ni le LLM. Rien n'est envoyé à Home
        // Assistant, d'où le même effet en essai : seul l'affichage de la tablette change.
        Apparence.commande(texteEntendu)?.let { demande ->
            val choix = demande.nom ?: Palette.suivant(Etat.courant.palette.ifEmpty { Palette.choix })
            ajouterEtape("Apparence", "palette $choix" + if (demande.nom == null) " (la suivante)" else "", Etat.Statut.OK)
            Etat.modifier { it.copy(palette = choix) }
            terminer(texteEntendu, ConfigMaison.NOM_ASSISTANT, "palette", listOf("palette $choix"), Apparence.reponse(choix),
                SystemClock.elapsedRealtime() - debut)
            return
        }
        val r = object { val texte = texteEntendu }
        val t0 = SystemClock.elapsedRealtime()
        val chemin = d.parcourir(r.texte)
        val msDico = SystemClock.elapsedRealtime() - t0
        val trouve = chemin.trouve
        dernierChemin = chemin
        ajouterEtape("Dictionnaire", decrireChemin(chemin, d.taille), if (trouve != null) Etat.Statut.OK else Etat.Statut.ECHEC, msDico)
        val faits = ArrayList<String>()
        var comprisPar = ""
        var detail = ""
        var reponse = ""
        var erreur = false
        if (trouve != null) {
            val f = trouve.forme
            comprisPar = "dictionnaire"
            detail = "${f.source} ligne ${f.ligne}"
            reponse = f.reponse
            // « Ma chambre » selon la personne qui parle (section personnes de commandes.yaml, 21/10/2026).
            val brutes = (0 until f.actions.length()).map { f.actions.getJSONObject(it) }
            val pourQui = d.personnes.appliquer(brutes, f.cle, personne)
            val actions = pourQui.actions
            if (pourQui.reponse != null) reponse = pourQui.reponse
            if (d.personnes.personnelle(brutes, f.cle)) {
                val qui = if (personne.isEmpty()) "qui parle n'est pas établi, chambre par défaut" else "dit par $personne"
                ajouterEtape(
                    "Personne",
                    if (pourQui.refus != null) "$qui : on ne sait pas de quelle chambre il s'agit, rien fait"
                    else "« ma chambre », $qui : " + actions.joinToString(", ") { resumeAction(it) },
                    if (pourQui.refus != null) Etat.Statut.ECHEC else Etat.Statut.OK,
                )
            }
            val refus = actions.mapNotNull { a -> Securite.verifier(a, personne = personne)?.let { resumeAction(a) to it } }
            if (pourQui.refus != null) {
                reponse = pourQui.refus
                faits.add("rien fait (personne non reconnue)")
                erreur = true
            } else if (refus.isNotEmpty()) {
                ajouterEtape("Sécurité", refus.joinToString("\n") { "${it.first} : refusé, ${it.second}" }, Etat.Statut.ECHEC)
                for ((a, r) in refus) faits.add("$a (refusé : $r)")
                reponse = "Je ne le fais pas : ${refus.first().second}."
                erreur = true
            } else if (!reel) {
                for (a in actions) faits.add(resumeAction(a) + " (non exécuté, essai)")
                ajouterEtape("Actions", actions.joinToString("\n") { resumeAction(it) } + "\nnon exécutées : mode essai", Etat.Statut.SAUTE)
            } else {
                for (a in actions) {
                    val nom = "Action ${resumeAction(a)}"
                    ajouterEtape(nom, "envoi à Home Assistant", Etat.Statut.EN_COURS)
                    val ta = SystemClock.elapsedRealtime()
                    val (ok, message) = executer(a)
                    majEtape(nom, message, SystemClock.elapsedRealtime() - ta, if (ok) Etat.Statut.OK else Etat.Statut.ECHEC)
                    faits.add(resumeAction(a) + if (ok) "" else " (refusé)")
                    if (!ok) {
                        erreur = true
                        reponse = "Je n'ai pas réussi à le faire, Home Assistant a refusé."
                    }
                }
            }
        } else {
            // Assist de Home Assistant : ses intentions intégrées, ses alias et l'automatisation
            // « <nom de l'assistant> : dictionnaire ». Il exécute ce qu'il comprend : jamais en essai.
            if (Securite.SECURITE_ACTIVE) {
                // Les règles nommées sont seulement celles en vigueur (0.17.2, règles 1 et 2 levées le 22/10/2026).
                val regles = listOfNotNull(
                    "sécurité ${Securite.NOM_OCCUPANT}".takeIf { Securite.PROTEGER_OCCUPANT },
                    "son la nuit".takeIf { Securite.HEURE_CALME_ACTIVE },
                )
                ajouterEtape("Assist de Home Assistant", "sauté : il agit sans qu'on puisse vérifier sa cible avant" +
                    (if (regles.isEmpty()) "" else " (${regles.joinToString(" et ")})"), Etat.Statut.SAUTE)
            } else if (!reel) {
                ajouterEtape("Assist de Home Assistant", "non sollicité en essai (il exécuterait la commande)", Etat.Statut.SAUTE)
            } else {
                ajouterEtape("Assist de Home Assistant", "phrase « ${chemin.epure} » envoyée", Etat.Statut.EN_COURS)
                val ta = SystemClock.elapsedRealtime()
                val ha = assist(chemin.epure)
                val msHa = SystemClock.elapsedRealtime() - ta
                if (ha.compris) {
                    majEtape("Assist de Home Assistant", "compris : « ${ha.parole} »" +
                        (if (ha.cibles.isNotEmpty()) "\n" + ha.cibles.joinToString("\n") else ""), msHa, Etat.Statut.OK)
                    comprisPar = "Home Assistant"
                    detail = "Assist"
                    reponse = ha.parole.ifBlank { "C'est fait." }
                    faits.addAll(ha.cibles)
                } else {
                    majEtape("Assist de Home Assistant", "pas compris (${ha.code})", msHa, Etat.Statut.ECHEC)
                }
            }
            if (comprisPar.isEmpty()) {
                val llm = demanderLlm(chemin.epure)
                comprisPar = llm.comprisPar
                detail = llm.detail
                reponse = llm.reponse
                faits.addAll(llm.faitsDirects?.map { if (reel || it.endsWith("(écartée)")) it else "$it (non exécuté, essai)" }
                    ?: llm.actions.map { if (reel) it else "$it (non exécuté, essai)" })
                erreur = llm.erreur
            }
        }
        terminer(r.texte, comprisPar.ifEmpty { "rien" }, detail, faits, reponse.ifBlank { "Je n'ai pas compris." },
            SystemClock.elapsedRealtime() - debut, erreur)
        if (trouve == null) noterManque(chemin, comprisPar.ifEmpty { "rien" }, detail, faits, reponse)
    }

    // ------------------------------------------------------------ routines (0.40.0, lot S-R3)

    /** Qui parle, tel qu'envoyé au serveur : vide pour un test écrit (muet) ou quand on ne sait pas. */
    private fun personneRoutines(): String = if (muet) "" else personne

    /** La passerelle vient de recevoir les capacités : retenir que le serveur gère les routines, lire la liste. */
    private fun surCapacitesRoutines() {
        if (!passerelle.routinesDispo) return
        routines.serveurSait = true
        // Hors du fil réseau de la passerelle : lire la liste attend la réponse du serveur.
        try {
            minuteur.execute { actualiserRoutines(personneRoutines()) }
        } catch (_: Exception) {
        }
    }

    /** `routines_maj` : les listes gardées ne sont plus sûres, chaque personne connue redemande la sienne. */
    private fun surRoutinesMaj() {
        routines.perimer()
        val aRelire = (routines.personnes() + RoutinesLocal.cle(personneRoutines())).distinct()
        try {
            minuteur.execute { for (p in aRelire) actualiserRoutines(p) }
        } catch (_: Exception) {
        }
    }

    /** Lit la liste des routines visibles de [personne] sur le serveur. Faux si le serveur ne répond pas. */
    private fun actualiserRoutines(personne: String): Boolean = synchronized(verrouRoutines) {
        val demande = JSONObject().put("type", "routines")
        if (personne.isNotEmpty()) demande.put("personne", personne)
        val j = passerelle.echanger(demande, "routines", 5)
        if (j == null) {
            routinesEchecLe = SystemClock.elapsedRealtime()
            return false
        }
        val n = routines.enregistrer(personne, j)
        routinesEchecLe = 0L
        Log.i(TAG, "Routines lues pour « $personne » : $n (version ${j.optInt("version")})")
        true
    }

    /** Relit la liste de la personne qui parle si elle manque ou si le serveur a signalé un changement. */
    private fun rafraichirRoutines() {
        if (!routines.serveurSait || !passerelle.disponible) return
        val p = personneRoutines()
        if (routines.aJour(p)) return
        // Un serveur qui ne répond pas ne retarde pas chaque phrase : un nouvel essai après 30 s.
        if (routinesEchecLe != 0L && SystemClock.elapsedRealtime() - routinesEchecLe < 30_000) return
        actualiserRoutines(p)
    }

    /**
     * Vrai si la phrase a reçu sa réponse du côté des routines. Faux : la chaîne ordinaire continue (météo,
     * palette, dictionnaire, Assist, LLM). Une confirmation de brouillon en attente passe avant tout.
     */
    private fun traiterRoutines(texte: String, debut: Long): Boolean {
        if (routines.confirmationEnAttente(SystemClock.elapsedRealtime())) return routineTexte(texte, debut, "réponse à la proposition")
        if (!routines.serveurSait && routines.vide) return false
        rafraichirRoutines()
        return when (val decision = routines.decider(texte, personneRoutines())) {
            is RoutinesLocal.Decision.Lancer -> lancerRoutine(texte, decision.routine, debut)
            is RoutinesLocal.Decision.Serveur -> routineTexte(texte, debut, decision.raison)
            RoutinesLocal.Decision.Aucune -> false
        }
    }

    /** Message au serveur : essai si rien ne doit partir, personne si elle est connue. */
    private fun demandeRoutine(type: String): JSONObject {
        val demande = JSONObject().put("type", type).put("essai", !reel)
        // Qui parle : le serveur s'en sert pour la portée de la routine et pour la sécurité (règle 3).
        val p = personneRoutines()
        if (p.isNotEmpty()) demande.put("personne", p)
        return demande
    }

    /** Lance une routine reconnue ici. Toujours vrai : la phrase a été prise en charge, réussie ou non. */
    private fun lancerRoutine(texte: String, r: RoutinesLocal.Routine, debut: Long): Boolean {
        Securite.phraseProtegee(texte, personne)?.let { refus ->
            ajouterEtape("Sécurité", "phrase refusée avant la routine : $refus", Etat.Statut.ECHEC)
            terminer(texte, "sécurité", "refus avant la routine", emptyList(), "Je ne le fais pas : $refus.",
                SystemClock.elapsedRealtime() - debut, true)
            return true
        }
        val nom = "Routine ${r.nom}"
        ajouterEtape(nom, "demandée au serveur" + if (reel) "" else " en essai, rien ne sera exécuté", Etat.Statut.EN_COURS)
        val t0 = SystemClock.elapsedRealtime()
        val demande = demandeRoutine("routine_lancer").put("id", r.id)
        Etat.modifier { it.copy(aideReflexion = "Je lance la routine...") }
        // 90 s : une routine peut enchaîner des pauses et de la musique.
        val j = try {
            passerelle.echanger(demande, "routine_lancee", 90)
        } finally {
            Etat.modifier { it.copy(aideReflexion = "") }
        }
        val ms = SystemClock.elapsedRealtime() - t0
        if (j == null) {
            majEtape(nom, "serveur injoignable ou trop lent (${passerelle.etat})", ms, Etat.Statut.ECHEC)
            terminer(texte, ConfigMaison.NOM_ASSISTANT, "routine", emptyList(), RoutinesLocal.SANS_SERVEUR_LANCER,
                SystemClock.elapsedRealtime() - debut, true)
            return true
        }
        val parole = j.optString("parole")
        val ok = j.optBoolean("ok", false)
        val echecs = j.optJSONArray("echecs")?.let { a -> (0 until a.length()).map { a.optString(it) } } ?: emptyList()
        majEtape(
            nom,
            "« $parole »" + (if (echecs.isNotEmpty()) "\n" + echecs.joinToString("\n") else "") + if (reel) "" else "\n(essai : rien exécuté)",
            ms, if (ok) Etat.Statut.OK else Etat.Statut.ECHEC,
        )
        val fait = listOf("routine ${r.nom}" + if (reel) "" else " (non exécutée, essai)") + echecs
        terminer(texte, ConfigMaison.NOM_ASSISTANT, "routine", fait, parole.ifBlank { if (ok) "C'est fait." else "Je n'ai pas pu lancer la routine." },
            SystemClock.elapsedRealtime() - debut, !ok)
        return true
    }

    /**
     * Confie la phrase au serveur (`routine_texte`) : gestion à la voix, création, réponse à un brouillon, routine
     * réservée à un autre. Faux si le serveur dit que ce n'est pas une demande de routine : la chaîne ordinaire continue.
     */
    private fun routineTexte(texte: String, debut: Long, raison: String): Boolean {
        Securite.phraseProtegee(texte, personne)?.let { refus ->
            ajouterEtape("Sécurité", "phrase refusée avant les routines : $refus", Etat.Statut.ECHEC)
            terminer(texte, "sécurité", "refus avant les routines", emptyList(), "Je ne le fais pas : $refus.",
                SystemClock.elapsedRealtime() - debut, true)
            routines.finirConfirmation()
            return true
        }
        val nom = "Routines"
        ajouterEtape(nom, "$raison : phrase envoyée au serveur" + if (reel) "" else " en essai", Etat.Statut.EN_COURS)
        val t0 = SystemClock.elapsedRealtime()
        val demande = demandeRoutine("routine_texte").put("texte", texte)
        val j = passerelle.echanger(demande, "routine_texte", 20)
        val ms = SystemClock.elapsedRealtime() - t0
        if (j == null) {
            majEtape(nom, "serveur injoignable ou trop lent (${passerelle.etat})", ms, Etat.Statut.ECHEC)
            routines.finirConfirmation()
            terminer(texte, ConfigMaison.NOM_ASSISTANT, "routine", emptyList(), RoutinesLocal.SANS_SERVEUR_GESTION,
                SystemClock.elapsedRealtime() - debut, true)
            return true
        }
        val parole = j.optString("parole")
        val attente = j.optInt("confirmation_attendue", 0)
        // Marge pour la lecture de la proposition : le serveur reste juge de son propre délai.
        routines.attendreConfirmation(if (attente > 0) attente + RoutinesLocal.MARGE_CONFIRMATION_S else 0, SystemClock.elapsedRealtime())
        if (parole.isBlank() || parole == RoutinesLocal.PAS_UNE_ROUTINE) {
            majEtape(nom, "pas une demande de routine, la phrase suit son cours", ms, Etat.Statut.SAUTE)
            return false
        }
        majEtape(nom, "« $parole »" + if (attente > 0) "\nréponse attendue pendant $attente s" else "", ms, Etat.Statut.OK)
        terminer(texte, ConfigMaison.NOM_ASSISTANT, "routine", emptyList(), parole, SystemClock.elapsedRealtime() - debut)
        return true
    }

    // ------------------------------------------------------------ ratés et notes (demande du 13/10)

    @Volatile private var dernierChemin: DictionnaireLocal.Chemin? = null

    /** Phrase absente du dictionnaire : gardée sur l'appareil et envoyée à l'appli de l'assistant sur HA. */
    private fun noterManque(c: DictionnaireLocal.Chemin, traitePar: String, detail: String, faits: List<String>, reponse: String) {
        val candidats = JSONArray()
        for (k in c.candidats) {
            candidats.put(
                JSONObject().put("cle", k.forme.cle).put("ressemblance", Math.round(k.ressemblance * 100) / 100.0)
                    .put("verdict", k.verdict).put("source", k.forme.source).put("ligne", k.forme.ligne)
            )
        }
        val msg = JSONObject().put("type", "manque").put("texte", c.entendu).put("epure", c.epure).put("cle", c.cle)
            .put("regles", JSONArray(c.regles)).put("candidats", candidats).put("traite_par", "$traitePar ($detail)")
            .put("actions", JSONArray(faits)).put("reponse", reponse).put("essai", !reel)
            .put("appareil", android.os.Build.MODEL).put("dictionnaire", dico?.genereLe ?: "")
            .put("test", muet) // phrase écrite par Claude via adb, pas une vraie commande du propriétaire
        if (personne.isNotEmpty() && !muet) msg.put("personne", personne)
        journalLocal("manques.jsonl", msg)
        envoyerJarvisHa(msg)
    }

    /** Note du propriétaire sur une commande : gardée ici et envoyée à l'appli de l'assistant sur HA. */
    fun retour(e: Etat.EntreeHistorique, verdict: String) {
        val msg = JSONObject().put("type", "retour").put("verdict", verdict).put("date", e.date).put("heure", e.heure)
            .put("entendu", e.entendu).put("compris_par", e.comprisPar).put("detail", e.detailVoie)
            .put("fait", JSONArray(e.fait)).put("reponse", e.reponse).put("essai", e.essai)
            .put("appareil", android.os.Build.MODEL)
        if (e.personne.isNotEmpty()) msg.put("personne", e.personne)
        travail.execute {
            journalLocal("retours.jsonl", msg)
            envoyerJarvisHa(msg)
        }
    }

    private fun journalLocal(nom: String, msg: JSONObject) {
        try {
            val dossier = java.io.File(contexte.getExternalFilesDir(null), "journal").apply { mkdirs() }
            java.io.File(dossier, nom).appendText(
                JSONObject(msg.toString()).put("horodatage", JOUR.format(Date()) + "T" + HEURE.format(Date())).toString() + "\n",
                Charsets.UTF_8,
            )
        } catch (ex: Exception) {
            Log.w(TAG, "Journal $nom impossible", ex)
        }
    }

    /** Envoi par la connexion de la passerelle, sans attendre de réponse utile. */
    private fun envoyerJarvisHa(msg: JSONObject) {
        if (!passerelle.envoyer(msg)) Log.w(TAG, "${msg.optString("type")} non transmis à l'appli de l'assistant sur HA (${passerelle.etat})")
    }

    /** Texte du déroulé pour le chemin parcouru dans le dictionnaire. */
    private fun decrireChemin(c: DictionnaireLocal.Chemin, taille: Int): String = buildString {
        append("1. Nettoyage : ")
        if (c.regles.isEmpty()) append("rien à retirer") else append(c.regles.joinToString(", "))
        append("\n   donne « ${c.epure} »")
        append("\n2. Normalisation : « ${c.cle} »")
        append("\n3. Recherche exacte parmi $taille formes : ")
        if (c.exacte) {
            append("trouvée")
        } else {
            append("absente")
            append("\n4. Recherche approchée, les 5 plus ressemblantes :")
            for (k in c.candidats) {
                append("\n   ").append(if (k.retenu) "[retenue] " else "[écartée] ")
                append("%.2f".format(Locale.FRANCE, k.ressemblance)).append(" « ${k.forme.cle} »")
                if (!k.retenu) append(" : ${k.verdict}")
            }
        }
        val t = c.trouve
        if (t == null) {
            append("\nRésultat : aucune ligne")
        } else {
            val f = t.forme
            append("\nRésultat : ${f.source}, ligne ${f.ligne}")
            append("\n   motif « ${f.motif} »")
            if (f.valeurs.isNotEmpty()) append("\n   emplacements ").append(f.valeurs.entries.joinToString(", ") { "${it.key} = ${it.value}" })
        }
    }

    // ------------------------------------------------------------ Home Assistant

    /** Une action du dictionnaire vers /api/services/<domaine>/<service>, par la passerelle. */
    private fun executer(brute: JSONObject): Pair<Boolean, String> {
        // Volume plafonné (Securite.VOLUME_MAX, si un plafond est réglé), pour le dictionnaire comme pour le LLM de l'appareil.
        val (s0, d0) = Securite.monterSansDepasser(brute.optString("service"), brute)
        val a = Securite.plafonner(s0, d0).put("service", s0)
        // La sécurité locale passe avant l'envoi, la passerelle la refait de son côté.
        Securite.verifier(a, personne = personne)?.let { return false to "refusé : $it" }
        val service = a.optString("service")
        val (domaine, nom) = service.split(".", limit = 2).let { if (it.size == 2) it[0] to it[1] else return false to "service invalide « $service »" }
        val corps = JSONObject()
        for (k in a.keys()) if (k != "service") corps.put(k, a.get(k))
        // La passerelle refait la sécurité avec la même personne (règle 3).
        val r = passerelle.requete("POST", "/api/services/$domaine/$nom", corps, personne = personne)
        return when {
            r.ok -> true to "fait (HTTP ${r.code}, par la passerelle)"
            r.code == 403 -> false to "refusé par la passerelle : ${r.corps.take(160)}"
            r.code in 502..504 -> false to r.corps
            else -> false to "refusé par Home Assistant (HTTP ${r.code})"
        }
    }

    private class Assist(val compris: Boolean, val parole: String, val cibles: List<String>, val code: String)

    private fun assist(texte: String): Assist {
        val corps = JSONObject().put("text", texte).put("language", "fr").put("agent_id", "conversation.home_assistant")
        return try {
            passerelle.requete("POST", "/api/conversation/process", corps).let { r ->
                if (!r.ok) return Assist(false, "", emptyList(), "HTTP ${r.code}")
                val rep = JSONObject(r.corps.ifBlank { "{}" }).optJSONObject("response") ?: JSONObject()
                val parole = rep.optJSONObject("speech")?.optJSONObject("plain")?.optString("speech") ?: ""
                val data = rep.optJSONObject("data") ?: JSONObject()
                val succes = data.optJSONArray("success") ?: JSONArray()
                val cibles = (0 until succes.length()).map { i ->
                    val c = succes.getJSONObject(i)
                    "ha ${c.optString("type")} ${c.optString("id").ifEmpty { c.optString("name") }}".trim()
                }
                Assist(rep.optString("response_type") != "error", parole, cibles, data.optString("code", rep.optString("response_type")))
            }
        } catch (e: Exception) {
            Assist(false, "", emptyList(), "injoignable, ${e.javaClass.simpleName}")
        }
    }

    // ------------------------------------------------------------ LLM

    private class Llm(val comprisPar: String, val detail: String, val reponse: String, val actions: List<String>, val erreur: Boolean) {
        /** Actions déjà rédigées pour l'historique (LLM sur l'appareil). */
        var faitsDirects: List<String>? = null
    }

    @Volatile private var cerveauAppareil: CerveauAppareil? = null
    @Volatile private var muet = false

    /** Charge le LLM de files/llm/ si besoin (10 s environ), avec son étape dans le déroulé. */
    /** Choix du LLM local en cours de route : chargement tout de suite, pas à la première phrase. */
    fun prechargerLlm() {
        travail.execute { chargerLlmAppareil() }
    }

    private fun chargerLlmAppareil(): CerveauAppareil? {
        cerveauAppareil?.let { return it }
        if (ModeleLiteRt.choisir(contexte) == null) {
            ajouterEtape("LLM sur cet appareil", "aucun modèle .litertlm dans ${ModeleLiteRt.dossier(contexte)} : à copier par adb", Etat.Statut.ECHEC)
            return null
        }
        var c: CerveauAppareil? = null
        etape("LLM sur cet appareil (chargement)") {
            val m = ModeleLiteRt.charger(contexte) ?: error("modèle illisible")
            c = CerveauAppareil(contexte, passerelle, m)
            "${m.nom} prêt" to Etat.Statut.OK
        }
        cerveauAppareil = c
        return c
    }

    private fun demanderLlmAppareil(texte: String): Llm {
        val c = chargerLlmAppareil()
            ?: return Llm("rien", "LLM sur l'appareil absent", "Je n'ai pas compris.", emptyList(), false)
        val nom = "LLM ${c.nom}"
        ajouterEtape(nom, "phrase « $texte » envoyée au modèle", Etat.Statut.EN_COURS)
        val t0 = SystemClock.elapsedRealtime()
        val d = try {
            c.decider(texte)
        } catch (e: Exception) {
            majEtape(nom, "erreur : ${e.message ?: e.javaClass.simpleName}", SystemClock.elapsedRealtime() - t0, Etat.Statut.ECHEC)
            return Llm("rien", nom, "Le modèle de langage n'a pas répondu.", emptyList(), true)
        }
        majEtape(
            nom,
            "réponse « ${d.reponse} » (liste des appareils ${d.msInventaire} ms, modèle ${d.msModele} ms)" +
                (if (d.actions.isEmpty()) "\naucune action proposée" else "\n" + d.actions.joinToString("\n") { resumeAction(it.enJson()) }) +
                (if (d.ecartees.isEmpty()) "" else "\nécartées : " + d.ecartees.joinToString("\n")) +
                "\nsortie brute : " + d.brut.take(300),
            SystemClock.elapsedRealtime() - t0, if (d.actions.isNotEmpty() || d.ecartees.isEmpty()) Etat.Statut.OK else Etat.Statut.ECHEC,
        )
        val faits = ArrayList<String>()
        var erreur = false
        for (a in d.actions) {
            val json = a.enJson()
            if (!reel) {
                faits.add(resumeAction(json))
                continue
            }
            val etapeNom = "Action ${resumeAction(json)}"
            ajouterEtape(etapeNom, "envoi à Home Assistant", Etat.Statut.EN_COURS)
            val ta = SystemClock.elapsedRealtime()
            val (ok, message) = executer(json)
            majEtape(etapeNom, message, SystemClock.elapsedRealtime() - ta, if (ok) Etat.Statut.OK else Etat.Statut.ECHEC)
            faits.add(resumeAction(json) + if (ok) "" else " (refusé)")
            if (!ok) erreur = true
        }
        if (!reel && d.actions.isNotEmpty()) ajouterEtape("Actions", "non exécutées : mode essai", Etat.Statut.SAUTE)
        faits.addAll(d.ecartees.map { "$it (écartée)" })
        return Llm(c.nom, "LLM sur cet appareil", d.reponse, emptyList(), erreur).also { it.faitsDirects = faits }
    }

    private fun demanderLlm(texte: String): Llm {
        Securite.phraseProtegee(texte, personne)?.let { refus ->
            ajouterEtape("Sécurité", "phrase refusée avant le LLM : $refus", Etat.Statut.ECHEC)
            return Llm("sécurité", "refus avant le LLM", "Je ne le fais pas : $refus.", emptyList(), false)
        }
        if (cerveau == "local") return demanderLlmAppareil(texte)
        val nom = "LLM Haiku (appli ${ConfigMaison.NOM_ASSISTANT} sur HA)"
        ajouterEtape(nom, "phrase « $texte » envoyée" + if (reel) "" else " en essai, rien ne sera exécuté", Etat.Statut.EN_COURS)
        val t0 = SystemClock.elapsedRealtime()
        // Même connexion que la passerelle : jeton en en-tête, port chiffré.
        val demande = JSONObject().put("type", "llm").put("texte", texte).put("essai", !reel)
        // Qui parle : le serveur s'en sert pour la sécurité (règle 3), l'inventaire et « ma chambre ».
        if (personne.isNotEmpty() && !muet) demande.put("personne", personne)
        // 45 s : une demande de musique peut chercher longtemps (Music Assistant). Pendant l'attente,
        // l'écran dit que l'assistant réfléchit, puis qu'il est toujours en cours, plutôt que de conclure trop tôt.
        Etat.modifier { it.copy(aideReflexion = "Je réfléchis...") }
        val rappel = minuteur.schedule({
            Etat.modifier { if (it.aideReflexion.isNotEmpty()) it.copy(aideReflexion = "Toujours en cours...") else it }
            majEtape(nom, "toujours en cours, réponse attendue jusqu'à 45 s", null, Etat.Statut.EN_COURS)
        }, 15, java.util.concurrent.TimeUnit.SECONDS)
        val j = try {
            passerelle.echanger(demande, "llm", 45)
        } finally {
            rappel.cancel(false)
            Etat.modifier { it.copy(aideReflexion = "") }
        }
        val ms = SystemClock.elapsedRealtime() - t0
        if (j == null) {
            majEtape(nom, "appli ${ConfigMaison.NOM_ASSISTANT} sur HA injoignable ou trop lente (${passerelle.etat})", ms, Etat.Statut.ECHEC)
            return Llm("rien", "Haiku injoignable", "Je n'ai pas pu joindre le modèle de langage.", emptyList(), true)
        }
        val actions = j.optJSONArray("actions")?.let { a -> (0 until a.length()).map { a.optString(it) } } ?: emptyList()
        val erreur = j.optString("erreur")
        majEtape(
            nom,
            (if (erreur.isNotEmpty()) "erreur : $erreur\n" else "") +
                "réponse « ${j.optString("reponse")} » en ${j.optLong("ms")} ms côté serveur" +
                (if (actions.isNotEmpty()) "\n" + actions.joinToString("\n") else "\naucune action") +
                if (reel) "" else "\n(essai : rien exécuté)",
            ms, if (erreur.isEmpty()) Etat.Statut.OK else Etat.Statut.ECHEC,
        )
        return Llm(j.optString("cerveau", "Claude Haiku"), "appli ${ConfigMaison.NOM_ASSISTANT} sur HA", j.optString("reponse"), actions, erreur.isNotEmpty())
    }

    /**
     * Question de météo (0.25.0, [MeteoQuestion]) : vrai si la phrase en était une et qu'elle a reçu sa réponse.
     * Prévisions de Home Assistant pour la terre (12 s au plus), données du serveur pour la mer (25 s au plus : la
     * première lecture de la source régionale prend une vingtaine de secondes).
     */
    private fun repondreMeteo(texteEntendu: String, debut: Long): Boolean {
        val maintenant = java.time.ZonedDateTime.now()
        val lieux = Etat.courant.meteos.mapNotNull { MeteoTexte.lieu(it.second) }
        val q = MeteoQuestion.comprendre(texteEntendu, maintenant, lieux) ?: return false
        val r: MeteoQuestion.Reponse
        if (q.sujet == MeteoQuestion.Sujet.MER) {
            // Vent en mer maintenant (0.29.0) : les mesures réelles d'abord, demandées en même temps que les prévisions.
            val attenteVent = java.util.concurrent.CompletableFuture<org.json.JSONObject?>()
            if (q.mesure) {
                val v = Etat.actionVentMesure
                if (v == null) attenteVent.complete(null) else v { attenteVent.complete(it) }
            } else attenteVent.complete(null)
            val attente = java.util.concurrent.CompletableFuture<org.json.JSONObject?>()
            val a = Etat.actionMeteoMer
            if (a == null) attente.complete(null) else a { attente.complete(it) }
            val jv = try { attenteVent.get(33, java.util.concurrent.TimeUnit.SECONDS) } catch (_: Exception) { null }
            val (dv, _) = MeteoVent.lire(jv)
            // Avec une mesure fraîche en mer, les prévisions ne servent qu'au rappel de la prévision : on ne les
            // attend que peu. Sans elle, la réponse vient des prévisions, attendues en entier.
            val parMesure = MeteoVent.reponse(q, dv, null, maintenant) != null
            val j = try { attente.get(if (parMesure) 4 else 33, java.util.concurrent.TimeUnit.SECONDS) } catch (_: Exception) { null }
            val (d, erreur) = MeteoMer.lire(j)
            r = MeteoVent.reponse(q, dv, d, maintenant) ?: MeteoMer.reponse(q, d, maintenant, if (a == null) "aucun serveur ne la fournit" else erreur)
            ajouterEtape("Météo", "mer, ${q.point}, ${q.plage.nom}" + (if (r.page == MeteoQuestion.Page.VENT) ", mesure" else "") +
                if (d == null && r.page != MeteoQuestion.Page.VENT) " : $erreur" else "", if (d == null && r.page != MeteoQuestion.Page.VENT) Etat.Statut.ECHEC else Etat.Statut.OK)
        } else {
            val attente = java.util.concurrent.CompletableFuture<Previsions.Lecture?>()
            val entite = q.lieu?.let { l -> Etat.courant.meteos.firstOrNull { MeteoTexte.lieu(it.second) == l }?.first }
            val suite: (Previsions.Lecture) -> Unit = { attente.complete(it) }
            if (entite != null) Etat.actionPrevisionsDe?.invoke(entite, suite) ?: attente.complete(null)
            else Etat.actionPrevisions?.invoke(suite) ?: attente.complete(null)
            val l = try { attente.get(12, java.util.concurrent.TimeUnit.SECONDS) } catch (_: Exception) { null }
            r = MeteoQuestion.repondre(q, l ?: Previsions.Lecture(erreur = "pas de lecture"), maintenant, q.lieu)
            val vide = l == null || (l.horaire.isEmpty() && l.journalier.isEmpty())
            ajouterEtape("Météo", "${q.sujet.name.lowercase(Locale.FRANCE)}, ${q.plage.nom}" + if (vide) " : prévisions indisponibles" else "",
                if (vide) Etat.Statut.ECHEC else Etat.Statut.OK)
        }
        Etat.modifier { it.copy(meteoDemandeeLe = SystemClock.elapsedRealtime(), meteoDemande = r) }
        terminer(texteEntendu, ConfigMaison.NOM_ASSISTANT, "météo", listOf("panneau Météo : ${r.entete}"), r.parle, SystemClock.elapsedRealtime() - debut)
        return true
    }

    private fun terminer(
        entendu: String, comprisPar: String, detail: String, fait: List<String>, reponse: String, ms: Long,
        erreur: Boolean = false,
    ) {
        // Jamais de texte libre dans une chaîne de format : « à 100% » faisait planter l'appli (13/10/2026).
        ajouterEtape("Réponse", "« $reponse »  (" + "%.2f".format(Locale.FRANCE, ms / 1000.0) + " s après la fin de la phrase)", Etat.Statut.OK, ms)
        val entree = Etat.EntreeHistorique(
            id = System.currentTimeMillis().toString(),
            date = JOUR.format(Date()), heure = HEURE.format(Date()), essai = !reel, entendu = entendu,
            comprisPar = comprisPar, detailVoie = detail, fait = fait, erreur = erreur, reponse = reponse,
            duree = "%.2f s".format(Locale.FRANCE, ms / 1000.0),
            personne = if (muet) "" else personne,
        )
        Etat.modifier {
            it.copy(
                jarvis = reponse, voie = "$comprisPar ($detail)", assistant = "Je réponds",
                historique = (listOf(entree) + it.historique).take(Etat.TAILLE_HISTORIQUE),
            )
        }
        Etat.surNouvelleCommande?.invoke(entree)
        val v = voix
        texteDit = reponse
        if (v != null && voixPrete && !muet) {
            // Sous l'orbe, la réponse commence vide et se remplit au fil de la voix.
            Etat.modifier { it.copy(parole = "", paroleFinLe = 0L) }
            finLecture = { apresReponse() }
            if (couperParole) {
                // Écoute attentive : le mot de réveil peut couper la réponse (guetterPendantReponse).
                reveilAReinitialiser = true
                sourdJusqua = SystemClock.elapsedRealtime() + 400
                phase = Phase.REPONSE
            }
            v.speak(reponse, TextToSpeech.QUEUE_FLUSH, null, "reponse")
        } else {
            Etat.modifier { it.copy(parole = reponse, paroleFinLe = SystemClock.elapsedRealtime()) }
            apresReponse()
        }
    }

    /**
     * Fin d'une réponse. Quand le serveur attend « oui » ou « non » à un brouillon de routine
     * (`confirmation_attendue`), l'écoute se rouvre sans mot de réveil, la phrase suivante repart en `routine_texte`.
     * Sinon retour au repos.
     */
    private fun apresReponse() {
        if (routines.confirmationEnAttente(SystemClock.elapsedRealtime())) {
            commencerEcoute("réponse attendue à la proposition de routine")
        } else {
            retourAuRepos()
        }
    }

    /** Réponse en cours de lecture, pour l'affichage au fil de la voix. */
    @Volatile private var texteDit = ""

    /** Fin (ou arrêt) de la voix : la réponse entière reste affichée, effacée 6 s plus tard. */
    private fun finParole() {
        val t = texteDit
        Etat.modifier { if (it.paroleFinLe == 0L) it.copy(parole = t, paroleFinLe = SystemClock.elapsedRealtime()) else it }
    }

    /** Voix basse : remonte le signal pour que son pic atteigne la moitié de la pleine échelle (x8 au plus). */
    private fun amplifier(pcm: ShortArray): Double {
        var pic = 1
        for (v in pcm) pic = maxOf(pic, kotlin.math.abs(v.toInt()))
        val gain = minOf(16000.0 / pic, 8.0)
        if (gain <= 1.0) return 1.0
        for (i in pcm.indices) pcm[i] = (pcm[i] * gain).toInt().coerceIn(-32768, 32767).toShort()
        return gain
    }

    private fun db(niveau: Double): String =
        if (niveau <= 0.000_01) "-100 dB" else "%.0f dB".format(Locale.FRANCE, 20 * kotlin.math.log10(niveau))

    private fun lectureTerminee() {
        val f = finLecture
        finLecture = null
        f?.invoke()
    }

    // ------------------------------------------------------------ déroulé

    private inline fun etape(nom: String, corps: () -> Pair<String, Etat.Statut>) {
        ajouterEtape(nom, "en cours", Etat.Statut.EN_COURS)
        val t0 = SystemClock.elapsedRealtime()
        try {
            val (detail, statut) = corps()
            majEtape(nom, detail, SystemClock.elapsedRealtime() - t0, statut)
        } catch (e: Throwable) {
            Log.e(TAG, "Étape $nom impossible", e)
            majEtape(nom, "erreur : ${e.message ?: e.javaClass.simpleName}", SystemClock.elapsedRealtime() - t0, Etat.Statut.ECHEC)
        }
    }

    private fun ajouterEtape(nom: String, detail: String, statut: Etat.Statut, ms: Long? = null) {
        Etat.modifier { it.copy(deroule = it.deroule + Etat.Etape(nom, detail, ms, statut)) }
    }

    private fun majEtape(nom: String, detail: String, ms: Long?, statut: Etat.Statut) {
        Etat.modifier { e ->
            val i = e.deroule.indexOfLast { it.nom == nom }
            if (i < 0) e.copy(deroule = e.deroule + Etat.Etape(nom, detail, ms, statut))
            else e.copy(deroule = e.deroule.toMutableList().also { it[i] = Etat.Etape(nom, detail, ms, statut) })
        }
    }

    override fun close() {
        phase = Phase.ARRET
        direct.shutdownNow()
        minuteur.shutdownNow()
        try {
            direct.awaitTermination(3, java.util.concurrent.TimeUnit.SECONDS)
        } catch (_: InterruptedException) {
        }
        travail.shutdownNow()
        try {
            travail.awaitTermination(3, java.util.concurrent.TimeUnit.SECONDS)
        } catch (_: InterruptedException) {
        }
        voix?.shutdown()
        passerelle.close()
        try {
            transcriptionPc?.close()
        } catch (_: Exception) {
        }
        voix = null
        for (r in listOf<AutoCloseable?>(reveil, reveilNouveau, vad, canary, cerveauAppareil)) try {
            r?.close()
        } catch (_: Exception) {
        }
        reveil = null
        reveilNouveau = null
        vad = null
        canary = null
    }

    companion object {
        private const val TAG = "JarvisLocal"
        private const val BLOC_S = 1280 / 16000.0
        private const val SILENCE_FIN_S = 0.8
        /** Avec Silero VAD, qui ne confond pas un souffle ou la télé avec la parole (comme le serveur 0.17.0). */
        private const val SILENCE_FIN_VAD_S = 0.45
        private const val ATTENTE_MAX_MS = 8000L
        private const val SEUIL_BRUIT = 2.5
        private const val NIVEAU_MIN = 0.006
        private const val DUREE_MAX_S = 12.0
        /** Seuil du mot de réveil relevé pendant la réponse, contre l'écho résiduel de la voix. */
        const val SURCROIT_COUPURE = 0.1f
        /** Transcription en direct : une passe toutes les 1,2 s, 2,5 s si une passe dépasse 1,5 s. */
        private const val INTERVALLE_DIRECT_MS = 1200L
        private const val INTERVALLE_DIRECT_LENT_MS = 2500L
        private const val LENTEUR_DIRECT_MS = 1500L
        private val HEURE = SimpleDateFormat("HH:mm:ss", Locale.FRANCE)
        private val JOUR = SimpleDateFormat("yyyy-MM-dd", Locale.FRANCE)

        /** « light.turn_on light.salon_lampe_tele (color_name=purple) », comme resume_action du serveur. */
        fun resumeAction(a: JSONObject): String {
            val cible = a.opt("entity_id")?.let { e ->
                if (e is org.json.JSONArray) (0 until e.length()).joinToString(" ") { e.optString(it) } else e.toString()
            } ?: ""
            val reglages = a.keys().asSequence().filter { it != "service" && it != "entity_id" }
                .joinToString(", ") { "$it=${a.opt(it)}" }
            return "${a.optString("service")} $cible".trim() + if (reglages.isNotEmpty()) " ($reglages)" else ""
        }
    }
}
