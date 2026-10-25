package assistant.vocal.jarvis

import android.os.Handler
import android.os.Looper
import java.util.concurrent.CopyOnWriteArraySet
import java.util.concurrent.atomic.AtomicBoolean

/**
 * État partagé entre le service et l'écran. Le service écrit depuis ses threads,
 * les écouteurs sont toujours appelés sur le thread principal. Les publications
 * rapprochées (vumètre toutes les 80 ms) sont regroupées en un seul appel.
 */
object Etat {

    /** Une commande traitée par le serveur : ce qui a été entendu, compris et fait. */
    data class EntreeHistorique(
        val date: String,
        val heure: String,
        val essai: Boolean,
        val entendu: String,
        val comprisPar: String,
        val detailVoie: String,
        val fait: List<String>,
        val erreur: Boolean,
        val reponse: String,
        val duree: String,
        /** Identifiant local (mode « Cet appareil »), vide pour une entrée venue d'un serveur. */
        val id: String = "",
        /** Note du propriétaire : "", "bien" ou "mauvais". */
        val verdict: String = "",
        /** Personne reconnue par la caméra au moment de la commande (0.16.0), vide sinon. */
        val personne: String = "",
    ) {
        fun memeCommande(o: EntreeHistorique): Boolean =
            if (id.isNotEmpty() || o.id.isNotEmpty()) id == o.id
            else date == o.date && heure == o.heure && entendu == o.entendu
    }

    /** Nombre d'entrées demandées au serveur et gardées en mémoire. */
    const val TAILLE_HISTORIQUE = 50

    /** Étape du déroulé d'une commande, affichée en direct (mode « Cet appareil »). */
    enum class Statut { EN_COURS, OK, ECHEC, SAUTE }

    data class Etape(val nom: String, val detail: String, val ms: Long?, val statut: Statut)

    /** Demande d'appairage d'un nouvel appareil, reçue d'un serveur (0.15.0). */
    data class DemandeAppairage(val id: String, val nom: String, val code: String)

    /**
     * Météo lue dans Home Assistant (entité weather), température et état en français. [entite] et
     * [fonctions] (supported_features) servent aux prévisions du panneau Météo (0.18.0).
     */
    data class Meteo(val temperature: String, val etat: String, val code: String = "", val entite: String = "", val fonctions: Long = 0L)

    /**
     * Soleil lu dans Home Assistant (sun.sun, 0.19.0) : levé ou non à la lecture, prochains lever et coucher
     * (millisecondes depuis 1970). Sert au mode « Selon l'heure » de la palette.
     */
    data class Soleil(
        val leve: Boolean,
        val lever: Long?,
        val coucher: Long?,
        /** Instant de la lecture (millisecondes depuis 1970, 0.21.1), null s'il est inconnu. */
        val luLe: Long? = null,
    )

    /** État de la maison : lumières allumées (rien de l'occupant protégé), ce qui joue en ce moment. */
    data class Maison(val lumieres: Int, val medias: List<String>, val pieces: List<String> = emptyList())

    /**
     * Carte de l'écran ambiant (0.16.0) : une par action faite, plus une pour la réponse.
     * [voie] : "dictionnaire", "ha", "claude", "llm", "securite" ou "jarvis".
     * [statut] : "attente", "confirme", "sans_reponse", "essai", "refuse" ou "" (non relu).
     */
    data class Carte(
        val id: Long,
        val reponse: Boolean,
        val nom: String,
        val verbe: String,
        /** Couleur de la pastille (couleur demandée à une lumière), ou null. */
        val pastille: Int?,
        val entendu: String,
        val texte: String,
        val voie: String,
        val essai: Boolean,
        val duree: String,
        val statut: String,
        /** Instant d'apparition (SystemClock.elapsedRealtime). */
        val creeLe: Long,
        /** Entités visées, pour relire leur état dans HA. */
        val entites: List<String> = emptyList(),
        /** Effet à montrer en 3D par lumière visée (0.17.5) : allumer, eteindre, regler ou basculer. */
        val effets: Map<String, String> = emptyMap(),
    )

    /**
     * Lecteur de musique lu dans HA (0.16.2). [position] et [duree] en secondes, [positionLe] :
     * instant de la position (millisecondes depuis 1970, media_position_updated_at), [volume] de 0 à 1.
     */
    data class Lecteur(
        val id: String,
        val nom: String,
        val etat: String,
        val titre: String,
        val artiste: String,
        val image: String,
        val position: Double,
        val duree: Double,
        val positionLe: Long,
        val volume: Double,
        val membres: Set<String> = emptySet(),
        /** Morceau suivant, si le lecteur l'annonce (attribut media_next_title), vide sinon. */
        val suivant: String = "",
    )

    /** État du lien avec le serveur, pour la pastille colorée. */
    enum class Lien { ARRETE, CONNEXION, CONNECTE, RECONNEXION }

    data class Instantane(
        val enMarche: Boolean = false,
        val lien: Lien = Lien.ARRETE,
        val connexion: String = "Arrêté",
        val assistant: String = "",
        val niveauDb: Float = -60f,
        val toi: String = "",
        val jarvis: String = "",
        val voie: String = "",
        val score: Double? = null,
        val versionServeur: String = "",
        /** Cerveau confirmé par le serveur : "claude", "local", ou vide si inconnu. */
        val cerveauActif: String = "",
        val cerveauPret: Boolean = false,
        val cerveauMessage: String = "",
        /** Mode confirmé par le serveur : "essai", "reel", ou vide si inconnu. */
        val modeActif: String = "",
        val modeMessage: String = "",
        /** Transcription confirmée par le serveur : "pc", "ha_stp", "ha_whisper", ou vide. */
        val transcriptionActif: String = "",
        val transcriptionMessage: String = "",
        /** Serveur visé par la connexion en cours : "pc" ou "ha". */
        val serveurCible: String = "pc",
        /** Capacités annoncées par le serveur. Listes nulles tant que rien n'est reçu. */
        val capServeur: String = "",
        val capVersion: String = "",
        val capTranscription: List<String>? = null,
        val capCerveau: List<String>? = null,
        /** Libellés lisibles des choix, fournis par le serveur (identifiant vers libellé). */
        val capLibelles: Map<String, String>? = null,
        /** Le serveur accepte que le téléphone guette le mot de réveil lui-même (0.15.0+). */
        val capReveilAppareil: Boolean = false,
        /** Où le mot de réveil est réellement guetté : "appareil", "serveur", ou vide si inconnu. */
        val reveilEffectif: String = "",
        /** Historique des commandes, la plus récente en premier. */
        val historique: List<EntreeHistorique> = emptyList(),
        /** Déroulé de la commande en cours ou de la dernière, et son titre. */
        val deroule: List<Etape> = emptyList(),
        val derouleTitre: String = "",
        /** Mot de réveil guetté par le serveur, d'après ses capacités (« Hey Jarvis » ou celui de la configuration). */
        val capMotReveil: String = "",
        /** Nouvel appareil qui attend d'être accepté, ou null. */
        val demandeAppairage: DemandeAppairage? = null,
        /** Clé d'un serveur refusée par l'épinglage : message à afficher, vide sinon. */
        val alerteCle: String = "",
        /** Message bref affiché quelques secondes sous l'orbe (arbitre), et son horodatage. */
        val bref: String = "",
        val brefLe: Long = 0L,
        /** Mode « Cet appareil » : état lisible de la passerelle Home Assistant, et sa disponibilité. */
        val passerelle: String = "",
        val passerelleDispo: Boolean = false,
        /** Vision (0.16.0) : personnes vues maintenant, présence, et état lisible de la caméra. */
        val personnes: List<PersonneVue> = emptyList(),
        /** Instant de l'image qui a donné [personnes] (SystemClock.elapsedRealtime, 0.21.1), 0 sans image. */
        val personnesLe: Long = 0L,
        val presence: Boolean = false,
        val visionEtat: String = "",
        /** Couleur du point d'état de la vision : "ok", "attente", "erreur" ou "" (désactivée). */
        val visionNiveau: String = "",
        /** Écran ambiant : météo, maison, cartes des dernières actions (la plus récente en premier). */
        val meteo: Meteo? = null,
        val maison: Maison? = null,
        val cartes: List<Carte> = emptyList(),
        /**
         * Ce que l'assistant entend de la phrase en cours (0.16.1) : texte partiel de la transcription en
         * direct ([entenduFinal] faux), puis la transcription finale, jusqu'à la réponse.
         */
        val entendu: String = "",
        /**
         * Ce que dit l'assistant, affiché sous l'orbe au fil de la voix (0.16.3), et l'instant où la voix
         * s'est tue (SystemClock.elapsedRealtime, 0 tant qu'elle parle). Effacé 6 s après.
         */
        val parole: String = "",
        val paroleFinLe: Long = 0L,
        /** Ligne d'aide pendant une longue réflexion du LLM (0.16.2) : « Je réfléchis... », puis « Toujours en cours... ». */
        val aideReflexion: String = "",
        /** Lecteurs de musique qui jouent (ou en pause depuis peu), pour la carte En cours (0.16.2). */
        val lecteurs: List<Lecteur> = emptyList(),
        val entenduFinal: Boolean = false,
        /** Dernier réveil ou dernière commande (SystemClock.elapsedRealtime), pour la luminosité. */
        val activiteLe: Long = 0L,
        /** Écran Musique (0.17.0) : les trois enceintes de la sortie du son, relues tant qu'il est ouvert. */
        val enceintes: List<SortieSon.Enceinte> = emptyList(),
        /** Écran Maison connectée (0.17.0) : appareils lus dans HA tant qu'il est ouvert (occupant protégé filtré à l'affichage). */
        val appareils: List<Appareils.Appareil> = emptyList(),
        /**
         * Toutes les lumières lues dans HA (0.18.0), pour le plan 3D de l'accueil : relues toutes les 4 s
         * en régime vivant seulement, et à chaque lecture des appareils. occupant protégé filtré à l'affichage.
         */
        val lumieres: List<Appareils.Appareil> = emptyList(),
        /**
         * Télé et enceintes (0.24.0), relues avec les lumières du plan : état et volume, pour la télé allumée et
         * les ondes des enceintes sur le plan 3D, et pour le volume réglé depuis l'accueil.
         */
        val mediasPlan: List<Appareils.Appareil> = emptyList(),
        /** Noms lisibles des appareils (friendly_name, rien de l'occupant protégé), pour l'historique (0.17.0). */
        val noms: Map<String, String> = emptyMap(),
        /**
         * Palette demandée (0.19.0) : nom d'un jeu de Palette, posé par une commande vocale. L'écran principal
         * l'applique et la retient. Vide tant que rien n'est demandé.
         */
        val palette: String = "",
        /** Soleil lu avec les états de Home Assistant (0.19.0), null tant qu'il n'est pas lu. */
        val soleil: Soleil? = null,
        /** Entités météo de Home Assistant (0.20.0), identifiant et nom : un point de page par entité s'il y en a plusieurs. */
        val meteos: List<Pair<String, String>> = emptyList(),
        /**
         * Panneau Météo demandé à la voix (0.20.0) : instant de la demande. 0.25.0 : la réponse à la question posée
         * ([MeteoQuestion.Reponse] : page, jour, bande, bloc de réponse), null pour le panneau simple.
         */
        val meteoDemandeeLe: Long = 0L,
        val meteoDemande: MeteoQuestion.Reponse? = null,
    ) {
        /**
         * Nom de la personne reconnue quand elle est seule devant la tablette, vide sinon. C'est ce
         * nom qui accompagne une commande : à plusieurs, on ne sait pas qui a parlé.
         */
        fun personneSeule(): String = personnes.singleOrNull()?.nom ?: ""

        /**
         * Qui parle, pour la sécurité (règle 3) et « ma chambre » (0.16.4) : le prénom reconnu d'une
         * personne seule, « inconnu » pour une personne seule vue nettement sans ressembler à aucun
         * profil, vide sinon (pas de vision, personne, plusieurs personnes, identité pas encore sûre).
         */
        fun quiParle(): String {
            val p = personnes.singleOrNull() ?: return ""
            return p.nom ?: if (p.inconnu) DictionnaireLocal.INCONNU else ""
        }
    }

    private val principal = Handler(Looper.getMainLooper())
    private val ecouteurs = CopyOnWriteArraySet<(Instantane) -> Unit>()
    private val publicationPrevue = AtomicBoolean(false)

    @Volatile
    var courant: Instantane = Instantane()
        private set

    /** Action du bouton Parler, posée par le service quand il tourne. */
    @Volatile
    var actionParler: (() -> Unit)? = null

    /** Envoi du choix de cerveau au serveur, posé par le service quand il tourne. */
    @Volatile
    var actionCerveau: ((String) -> Unit)? = null

    /** Envoi du choix de mode (essai ou réel) au serveur, posé par le service. */
    @Volatile
    var actionMode: ((String) -> Unit)? = null

    /** Envoi du choix de transcription au serveur, posé par le service. */
    @Volatile
    var actionTranscription: ((String) -> Unit)? = null

    /** Redemande l'historique au serveur, posé par le service quand il tourne. */
    @Volatile
    var actionHistorique: (() -> Unit)? = null

    /** Choix de l'endroit où guetter le mot de réveil ("appareil" ou "serveur"), posé par le service. */
    @Volatile
    var actionReveil: ((String) -> Unit)? = null

    /** Nouveau seuil du mot de réveil guetté sur le téléphone, posé par le service. */
    @Volatile
    var actionSeuilReveil: ((Float) -> Unit)? = null

    /** Note « bien » ou « mauvais » du propriétaire sur une commande de l'historique, posé par le service. */
    @Volatile
    var actionRetour: ((EntreeHistorique, String) -> Unit)? = null

    /** Phrase écrite à traiter en essai par le moteur local (bancs adb), posé par le service. */
    @Volatile
    var actionTesterTexte: ((String) -> Unit)? = null

    /** Choix du mot de réveil (ReveilLocal.HEY_JARVIS ou ReveilLocal.PERSO), rechargé à chaud, posé par le service. */
    @Volatile
    var actionMotReveil: ((String) -> Unit)? = null

    /** Réponse à une demande d'appairage ("appairer" ou "refuser_appareil", identifiant), posé par le service. */
    @Volatile
    var actionAppareil: ((String, String) -> Unit)? = null

    /** Vision : nouveau mode ("off", "tablette", "pc"), posé par le service. */
    @Volatile
    var actionVision: ((String) -> Unit)? = null

    /** Caméra rendue (true) ou reprise (false) par le service, pour l'écran d'enrôlement. */
    @Volatile
    var actionVisionSuspendre: ((Boolean) -> Unit)? = null

    /** Profils de visages modifiés : à relire par la vision, posé par le service. */
    @Volatile
    var actionVisionRecharger: (() -> Unit)? = null

    /** Option Couper la parole changée (mode « Cet appareil »), posé par le service. */
    @Volatile
    var actionCouperParole: ((Boolean) -> Unit)? = null

    /** Option Transcription en direct changée (mode « Cet appareil »), posé par le service. */
    @Volatile
    var actionTranscriptionDirecte: ((Boolean) -> Unit)? = null

    /** Commande de musique depuis la carte En cours : entité, service media_player, données. Posé par le service. */
    @Volatile
    var actionMedia: ((String, String, org.json.JSONObject) -> Unit)? = null

    /** Pochette d'un lecteur (adresse entity_picture), rendue sur le fil principal. Posé par le service. */
    @Volatile
    var actionPochette: ((String, (Maison.Pochette?) -> Unit) -> Unit)? = null

    /**
     * Commande d'un écran de la tablette (0.17.0) : service « domaine.service », corps de l'appel, et ce
     * que vérifie Securite.kt avant l'envoi. Posé par le service, envoyé par la passerelle.
     */
    @Volatile
    var actionService: ((String, org.json.JSONObject, org.json.JSONObject) -> Unit)? = null

    /** Écran Musique ouvert (vrai) ou fermé : les enceintes sont relues toutes les 3 s. Posé par le service. */
    @Volatile
    var actionSuivreEnceintes: ((Boolean) -> Unit)? = null

    /** Écran Maison ouvert (vrai) ou fermé : les appareils sont relus toutes les 3 s. Posé par le service. */
    @Volatile
    var actionSuivreAppareils: ((Boolean) -> Unit)? = null

    /** Accueil de la tablette vivant (vrai) ou endormi : les lumières sont relues toutes les 4 s (0.18.0). Posé par le service. */
    @Volatile
    var actionSuivreLumieres: ((Boolean) -> Unit)? = null

    /** Prévisions horaires seules (0.18.1), avec le code de la passerelle : phrase de pluie de l'accueil. Posé par le service. */
    @Volatile
    var actionHoraire: (((List<Previsions.Prevision>, Int) -> Unit) -> Unit)? = null

    /** Prévisions météo (0.18.0), pour le panneau Météo qui attend sa maquette, rendues sur le fil principal. Posé par le service. */
    @Volatile
    var actionPrevisions: (((Previsions.Lecture) -> Unit) -> Unit)? = null


    /** Prévisions d'une entité météo donnée (0.20.0, panneau Météo, points de page). Posé par le service. */
    @Volatile
    var actionPrevisionsDe: ((String, (Previsions.Lecture) -> Unit) -> Unit)? = null

    /**
     * Résumé de santé du propriétaire (0.19.0) demandé au serveur du PC par la connexion de la transcription déportée :
     * la réponse du serveur, ou null, rendue sur le fil principal. Jamais gardée ici. Posé par le service.
     */
    @Volatile
    var actionSante: (((org.json.JSONObject?) -> Unit) -> Unit)? = null

    /**
     * Météo marine du golfe de Marseille (0.25.0, page Mer) demandée au serveur (message `meteo_mer`, serveur 0.22.0) :
     * au PC, sinon à l'appli de l'assistant sur HA. La réponse du serveur, ou null, sur le fil principal. Posé par le service.
     */
    @Volatile
    var actionMeteoMer: (((org.json.JSONObject?) -> Unit) -> Unit)? = null

    /**
     * Vent mesuré dans le golfe (0.29.0, message `vent_mesure`, serveur 0.24.0) : au PC, sinon à l'appli de l'assistant sur
     * HA. La réponse du serveur, ou null, sur le fil principal. Posé par le service.
     */
    @Volatile
    var actionVentMesure: (((org.json.JSONObject?) -> Unit) -> Unit)? = null

    /**
     * Historique de santé (0.22.0, onglets Tendances, Séances, Records et vue d'un jour) : la demande (avec son
     * `type`), puis la réponse du serveur ou null, sur le fil principal. Jamais gardée ici. Posé par le service.
     */
    @Volatile
    var actionSanteHistorique: ((org.json.JSONObject, (org.json.JSONObject?) -> Unit) -> Unit)? = null

    /** Le PC annonce l'historique de santé (capacité `sante_historique`). Posé par le service. */
    @Volatile
    var historiqueSante: () -> Boolean = { false }

    /** Nouvelle commande terminée (mode « Cet appareil » ou serveur) : cartes de l'écran ambiant. */
    @Volatile
    var surNouvelleCommande: ((EntreeHistorique) -> Unit)? = null

    /** Coupe la connexion et se reconnecte tout de suite (changement de serveur). */
    @Volatile
    var actionReconnecter: (() -> Unit)? = null

    fun modifier(transformation: (Instantane) -> Instantane) {
        synchronized(this) { courant = transformation(courant) }
        if (ecouteurs.isEmpty()) return
        if (publicationPrevue.compareAndSet(false, true)) {
            principal.post {
                publicationPrevue.set(false)
                val e = courant
                for (ecouteur in ecouteurs) {
                    try {
                        ecouteur(e)
                    } catch (_: Exception) {
                    }
                }
            }
        }
    }

    /** À appeler sur le thread principal. */
    fun ajouter(ecouteur: (Instantane) -> Unit) {
        ecouteurs.add(ecouteur)
        ecouteur(courant)
    }

    fun retirer(ecouteur: (Instantane) -> Unit) {
        ecouteurs.remove(ecouteur)
    }

    fun nomCerveau(cle: String): String = when (cle) {
        "claude" -> "Claude"
        "local" -> "PC"
        else -> "inconnu"
    }

    fun nomMode(cle: String): String = when (cle) {
        "essai" -> "essai"
        "reel" -> "réel"
        else -> "inconnu"
    }
}
