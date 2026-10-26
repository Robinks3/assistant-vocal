package assistant.vocal.jarvis

import android.content.Context
import android.util.Log
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * Passerelle Home Assistant du mode « Cet appareil » (0.15.0, serveur 0.17.0).
 *
 * L'APK n'embarque plus de jeton Home Assistant : toutes les requêtes passent par l'appli de l'assistant
 * sur HA, qui a son propre jeton, ne permet que quelques chemins et refait la vérification de
 * sécurité. Une seule connexion WebSocket reste ouverte vers ce serveur. Chaque requête porte un
 * identifiant croissant et attend sa réponse {"etat":"ha","id"} avec un délai, ce qui permet de
 * l'appeler de façon bloquante depuis le fil de travail du moteur local.
 *
 * Les messages llm, manque et retour vers l'appli de l'assistant sur HA passent aussi par cette connexion.
 * Les annonces du serveur (demande d'appairage) sont remises à [annonce].
 */
class PasserelleHa(
    private val contexte: Context,
    /** Adresse du serveur de l'assistant sur HA (wss://hôte:8766 en principe). */
    private val url: String,
    private val annonce: (JSONObject) -> Unit = {},
    /** Appelé quand la passerelle devient disponible ou ne l'est plus. */
    private val changement: () -> Unit = {},
    /** Le serveur signale que les routines ont changé (`routines_maj`, 0.40.0), avec le numéro de version. */
    private val routinesMaj: (Int) -> Unit = {},
) : AutoCloseable {

    /** Réponse de HA. Pour une image (serveur 0.18.1), [base64] et [type] remplacent [corps]. */
    class Reponse(val code: Int, val corps: String, val type: String = "", val base64: String = "") {
        val ok: Boolean get() = code in 200..299
    }

    private val base = Confiance.clientWebSocket()

    @Volatile private var ws: WebSocket? = null
    /** Capacités reçues et passerelle annoncée par le serveur : les requêtes peuvent partir. */
    @Volatile var disponible = false
        private set
    /** État lisible, pour l'écran et le déroulé. */
    @Volatile var etat = "pas encore connectée"
        private set
    @Volatile private var ferme = false
    @Volatile private var surRepli = false
    @Volatile private var pret = CompletableFuture<Boolean>()

    private val identifiants = AtomicInteger(0)
    private val attentes = ConcurrentHashMap<Int, CompletableFuture<Reponse>>()
    private val attentesEtat = ConcurrentHashMap<String, CompletableFuture<JSONObject>>()
    private val planif = Executors.newSingleThreadScheduledExecutor()

    /** Chien de garde (0.38.2) : socket ouverte mais passerelle indisponible depuis trop longtemps. */
    private val garde = GardeReconnexion()

    init {
        // Propre minuterie : la relance ne dépend plus seulement du chien de garde du service.
        try {
            planif.scheduleWithFixedDelay({ surveiller() }, PERIODE_GARDE_S, PERIODE_GARDE_S, TimeUnit.SECONDS)
        } catch (_: Exception) {
        }
    }

    /** Vrai si [socket] est la socket courante. Attend la fin d'[ouvrir], qui l'enregistre sous verrou. */
    private fun courante(socket: WebSocket): Boolean = synchronized(this) { socket === ws }

    /** Signale un changement à l'appelant sans que son erreur éventuelle ne coupe la relance. */
    private fun prevenir() {
        try {
            changement()
        } catch (e: Exception) {
            Log.w(TAG, "Rappel de changement en erreur", e)
        }
    }

    /** Annule et rouvre une socket qui reste ouverte sans que la passerelle soit disponible depuis 30 s. */
    private fun surveiller() {
        if (ferme) return
        val socket = ws
        if (!garde.doitRelancer(socket, disponible, System.nanoTime() / 1_000_000)) return
        if (socket == null) return
        val avant = etat
        Log.w(TAG, "Chien de garde : socket ouverte depuis plus de ${GardeReconnexion.DELAI_MS / 1000} s sans passerelle disponible ($avant), annulation et réouverture")
        perdu(socket, "chien de garde : passerelle indisponible depuis ${GardeReconnexion.DELAI_MS / 1000} s ($avant)", reessayerVite = true)
        try {
            socket.cancel()
        } catch (_: Exception) {
        }
        prevenir()
    }

    /** Ouvre la connexion si besoin, sans attendre. */
    fun ouvrir() {
        if (ferme) return
        surveiller()
        if (ws != null) return
        synchronized(this) {
            if (ferme || ws != null) return
            val principale = url.trim().trimEnd('/')
            val repli = Confiance.repli(contexte, principale)
            val adresse = if (surRepli && repli != null) repli else principale
            if (pret.isDone) pret = CompletableFuture()
            etat = "connexion à $adresse"
            Log.i(TAG, "Ouverture vers $adresse" + (if (adresse == repli) " (repli en clair)" else ""))
            try {
                ws = Confiance.client(base, contexte, adresse)
                    .newWebSocket(Confiance.requete(contexte, adresse), Ecouteur(adresse, adresse == repli, repli != null))
            } catch (e: Exception) {
                Log.w(TAG, "Ouverture impossible", e)
                etat = "adresse invalide : $adresse"
                ws = null
                planifier(5000)
            }
        }
    }

    /** Attend la connexion et les capacités, au plus [ms] millisecondes. */
    private fun attendre(ms: Long): Boolean {
        // Plusieurs tours : un premier échec peut être suivi tout de suite de l'essai en clair.
        val limite = System.currentTimeMillis() + ms
        while (!ferme) {
            if (disponible) return true
            val reste = limite - System.currentTimeMillis()
            if (reste <= 0) return false
            ouvrir()
            val p = pret
            try {
                if (p.get(reste, TimeUnit.MILLISECONDS) && disponible) return true
            } catch (_: Exception) {
                return false
            }
            if (capacitesRecues) return false // serveur joint, mais sans passerelle : inutile d'insister
            try {
                Thread.sleep(400)
            } catch (_: InterruptedException) {
                return false
            }
        }
        return false
    }

    /** Vrai si le dernier serveur joint a envoyé ses capacités (même sans passerelle). */
    @Volatile private var capacitesRecues = false

    /** Capacité `meteo_mer` de l'appli de l'assistant sur HA (0.25.0, serveur 0.22.0) : page Mer sans le PC. */
    @Volatile var meteoMerDispo = false
        private set

    /** Capacité `vent_mesure` de l'appli de l'assistant sur HA (0.29.0, serveur 0.24.0) : vent mesuré sans le PC. */
    @Volatile var ventMesureDispo = false
        private set

    /** Capacité `routines` (serveur 0.43.x, appli 0.40.0) : liste, lancement et gestion des routines par le serveur. */
    @Volatile var routinesDispo = false
        private set

    /** Moteurs de transcription annoncés par l'appli de l'assistant sur HA (0.17.0), null tant que rien n'est reçu. */
    @Volatile var transcriptions: List<String>? = null
        private set

    private val identifiantsTranscription = AtomicInteger(0)

    /**
     * Transcription déportée (0.17.0, serveur 0.18.4) : la phrase découpée par la tablette, transcrite par
     * le moteur [moteur] de l'appli sur HA. Réponse {"etat":"transcrit"} de cette demande-là (même
     * identifiant), ou null si la passerelle n'est pas prête ou ne répond pas dans le délai. N'attend
     * jamais la connexion : le repli sur la tablette doit rester rapide.
     */
    fun transcrire(pcm: ShortArray, moteur: String, delaiMs: Long): JSONObject? {
        if (!disponible || transcriptions == null) return null
        val id = identifiantsTranscription.incrementAndGet()
        val msg = OuTranscrire.message(id, pcm, moteur) { android.util.Base64.encodeToString(it, android.util.Base64.NO_WRAP) }
        val cle = "transcrit#$id"
        val promesse = CompletableFuture<JSONObject>()
        attentesEtat[cle] = promesse
        if (ws?.send(msg.toString()) != true) {
            attentesEtat.remove(cle, promesse)
            return null
        }
        return try {
            promesse.get(delaiMs, TimeUnit.MILLISECONDS)
        } catch (_: Exception) {
            null
        } finally {
            attentesEtat.remove(cle, promesse)
        }
    }

    /**
     * Requête Home Assistant bloquante : [methode] GET ou POST, [chemin] /api/..., [corps] JSON.
     * Codes sans HTTP derrière : 503 passerelle indisponible, 504 délai dépassé, 502 envoi impossible.
     */
    fun requete(methode: String, chemin: String, corps: JSONObject? = null, delaiS: Long = 20, personne: String = ""): Reponse {
        if (!attendre(6000)) return Reponse(503, "passerelle Home Assistant indisponible ($etat)")
        val id = identifiants.incrementAndGet()
        val promesse = CompletableFuture<Reponse>()
        attentes[id] = promesse
        val msg = JSONObject().put("type", "ha").put("id", id).put("methode", methode).put("chemin", chemin)
        if (corps != null) msg.put("corps", corps)
        if (personne.isNotEmpty()) msg.put("personne", personne)
        val socket = ws
        if (socket == null || !socket.send(msg.toString())) {
            attentes.remove(id)
            return Reponse(502, "envoi à la passerelle impossible")
        }
        return try {
            promesse.get(delaiS, TimeUnit.SECONDS)
        } catch (_: java.util.concurrent.TimeoutException) {
            Reponse(504, "pas de réponse de la passerelle en $delaiS s")
        } catch (e: Exception) {
            Reponse(502, "passerelle coupée (${e.cause?.message ?: e.javaClass.simpleName})")
        } finally {
            attentes.remove(id)
        }
    }

    /** Envoie [msg] et attend le premier message {"etat": [etatAttendu]}, ou null après [delaiS]. */
    fun echanger(msg: JSONObject, etatAttendu: String, delaiS: Long): JSONObject? {
        if (!attendre(6000)) return null
        val promesse = CompletableFuture<JSONObject>()
        attentesEtat[etatAttendu] = promesse
        if (ws?.send(msg.toString()) != true) {
            attentesEtat.remove(etatAttendu, promesse)
            return null
        }
        return try {
            promesse.get(delaiS, TimeUnit.SECONDS)
        } catch (_: Exception) {
            null
        } finally {
            attentesEtat.remove(etatAttendu, promesse)
        }
    }

    /** Envoi sans attendre de réponse (manque, retour, gestion des appareils). */
    fun envoyer(msg: JSONObject): Boolean {
        if (!attendre(6000)) return false
        return ws?.send(msg.toString()) == true
    }

    private fun planifier(ms: Long) {
        if (ferme) return
        try {
            planif.schedule({ ouvrir() }, ms, TimeUnit.MILLISECONDS)
        } catch (_: Exception) {
        }
    }

    private fun perdu(socket: WebSocket, raison: String, reessayerVite: Boolean = false) {
        // Sous verrou : un échec immédiat ne doit pas passer avant l'enregistrement de la socket par ouvrir(),
        // sinon elle resterait enregistrée, morte, et plus rien ne la rouvrirait.
        synchronized(this) {
            if (socket !== ws) {
                Log.i(TAG, "Perte d'une ancienne socket ignorée ($raison)")
                return
            }
            ws = null
        }
        meteoMerDispo = false
        ventMesureDispo = false
        routinesDispo = false
        Log.w(TAG, "Connexion perdue : $raison" + (if (reessayerVite) " (nouvel essai immédiat)" else " (nouvel essai dans 5 s)") +
            (if (surRepli) ", sur le repli en clair" else ""))
        val avant = disponible
        disponible = false
        capacitesRecues = false
        transcriptions = null
        etat = raison
        pret.complete(false)
        for (p in attentes.values) p.complete(Reponse(502, raison))
        attentes.clear()
        for (p in attentesEtat.values) p.complete(null)
        attentesEtat.clear()
        // La relance d'abord : une erreur du rappel ne doit jamais la faire perdre.
        planifier(if (reessayerVite) 300 else 5000)
        if (avant || !reessayerVite) prevenir()
    }

    private inner class Ecouteur(
        private val adresse: String,
        private val repli: Boolean,
        private val repliPossible: Boolean,
    ) : WebSocketListener() {

        override fun onOpen(webSocket: WebSocket, response: Response) {
            if (!courante(webSocket)) return
            Log.i(TAG, "Connexion ouverte vers $adresse" + (if (repli) " (en clair)" else ""))
            etat = if (repli) "connectée en clair ($adresse), appli ${ConfigMaison.NOM_ASSISTANT} sur HA à mettre à jour pour le port chiffré"
            else "connectée, en attente des capacités"
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            if (!courante(webSocket)) return
            val j = try {
                JSONObject(text)
            } catch (_: Exception) {
                return
            }
            when (val e = j.optString("etat")) {
                "ha" -> attentes.remove(j.optInt("id", -1))?.complete(
                    Reponse(j.optInt("code", 502), j.optString("corps"), j.optString("type"), j.optString("base64"))
                )
                "capacites" -> {
                    // Empreinte annoncée par le serveur : elle doit être celle épinglée à la connexion.
                    val annoncee = j.optString("empreinte")
                    val retenue = if (repli) null else Confiance.empreinte(contexte, adresse)
                    if (annoncee.isNotEmpty() && retenue != null && annoncee != retenue) {
                        etat = "clé annoncée par le serveur différente de celle reçue : connexion coupée"
                        Log.w(TAG, "Clé annoncée différente de la clé épinglée pour $adresse : connexion coupée")
                        Etat.modifier { it.copy(alerteCle = "La clé du serveur Home Assistant ne correspond pas à celle annoncée. Vérifie-la dans l'écran Appareils.") }
                        webSocket.cancel()
                        return
                    }
                    disponible = j.optBoolean("passerelle_ha", false)
                    meteoMerDispo = annonceCapacite(j, "meteo_mer")
                    ventMesureDispo = annonceCapacite(j, "vent_mesure")
                    // Pas de routines sur le repli en clair : le serveur les refuse hors du port chiffré.
                    routinesDispo = !repli && annonceCapacite(j, "routines")
                    transcriptions = j.optJSONArray("transcription")?.let { a ->
                        (0 until a.length()).map { a.optString(it) }.filter { it.isNotEmpty() }
                    }
                    etat = if (disponible) {
                        "prête (appli ${ConfigMaison.NOM_ASSISTANT} sur HA v${j.optString("version")}" + (if (repli) ", en clair)" else ", chiffrée)")
                    } else if (j.has("passerelle_ha")) {
                        "l'appli ${ConfigMaison.NOM_ASSISTANT} sur HA n'a pas de jeton Home Assistant configuré"
                    } else {
                        "appli ${ConfigMaison.NOM_ASSISTANT} sur HA trop ancienne (v${j.optString("version")}, 0.17.0 requise)"
                    }
                    capacitesRecues = true
                    Log.i(TAG, "Capacités reçues : version ${j.optString("version")}, disponible=$disponible, " +
                        "meteo_mer=$meteoMerDispo, vent_mesure=$ventMesureDispo, routines=$routinesDispo, repli=$repli")
                    pret.complete(true)
                    // Toujours signalé : l'écran affiche l'état lisible, même sans changement de disponibilité.
                    prevenir()
                }
                "appairage_demande" -> annonce(j)
                // Signal seul : chaque client redemande sa propre liste, filtrée pour lui. Jamais sur le fil réseau.
                "routines_maj" -> try {
                    routinesMaj(j.optInt("version", 0))
                } catch (ex: Exception) {
                    Log.w(TAG, "Rappel de routines_maj en erreur", ex)
                }
                // Réponse attendue par son identifiant (transcription), sinon par son seul état (llm).
                else -> if (e.isNotEmpty()) (attentesEtat.remove("$e#${j.opt("id")}") ?: attentesEtat.remove(e))?.complete(j)
            }
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            try {
                webSocket.close(1000, null)
            } catch (_: Exception) {
            }
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
            val raison = if (code == 4001) "jeton refusé par l'appli ${ConfigMaison.NOM_ASSISTANT} sur HA : appaire cet appareil (écran Appareils)"
            else "connexion fermée ($code)"
            perdu(webSocket, raison)
        }

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            val cle = Confiance.cleChangee(t)
            if (cle != null) {
                Etat.modifier { it.copy(alerteCle = cle.message ?: "La clé du serveur a changé") }
                perdu(webSocket, cle.message ?: "clé du serveur changée")
                return
            }
            // Port chiffré muet : un essai sur l'ancienne adresse, tant qu'aucune clé n'est retenue.
            if (response == null && !repli && repliPossible) {
                surRepli = true
                perdu(webSocket, "port chiffré muet, essai de l'ancienne adresse en clair", reessayerVite = true)
                return
            }
            if (repli) surRepli = false
            perdu(webSocket, when (val code = response?.code) {
                null -> "injoignable (${t.javaClass.simpleName})"
                else -> "réponse inattendue ($code)"
            })
        }
    }

    override fun close() {
        ferme = true
        planif.shutdownNow()
        val s = ws
        ws = null
        disponible = false
        pret.complete(false)
        for (p in attentes.values) p.complete(Reponse(502, "passerelle fermée"))
        for (p in attentesEtat.values) p.complete(null)
        try {
            s?.close(1000, "fin")
        } catch (_: Exception) {
        }
        base.dispatcher.executorService.shutdown()
    }

    private companion object {
        const val TAG = "JarvisPasserelle"
        const val PERIODE_GARDE_S = 10L
    }
}
