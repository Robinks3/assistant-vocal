package assistant.vocal.jarvis

import android.content.Context
import android.os.SystemClock
import android.util.Base64
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONObject
import java.nio.ByteBuffer
import java.nio.ByteOrder
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * Où transcrire en mode « Cet appareil » (0.17.0, serveur 0.18.4), logique pure testée sur la machine
 * (TranscriptionTest). Le réveil, la détection de parole, la transcription en direct et le dictionnaire
 * restent sur la tablette. Seule la phrase découpée part, si le propriétaire l'a choisi :
 * - « Sur la tablette » : Canary, comme avant ;
 * - « Sur le PC » : Canary du PC fixe, par une connexion wss dédiée (comme la vision sur le PC) ;
 * - « Sur Home Assistant » : Speech-to-Phrase, par la passerelle de l'appli de l'assistant sur HA ;
 * - « En ligne » : le service en ligne du serveur qui l'annonce (HA d'abord, sinon le PC).
 * Un lieu n'est proposé que si le serveur concerné annonce le moteur dans capacites.transcription.
 * Message {"type":"transcrire","id","pcm","moteur"}, réponse {"etat":"transcrit","id","texte","moteur","ms"}
 * ou avec "erreur". Sans réponse en 8 s, sur erreur ou texte vide : repli sur Canary de la tablette.
 */
object OuTranscrire {
    const val TABLETTE = "tablette"
    const val PC = "pc"
    const val HA = "ha"
    const val EN_LIGNE = "api"
    const val DELAI_MS = 8_000L

    /** Les lieux dans l'ordre des réglages. */
    val LIEUX = listOf(TABLETTE, PC, HA, EN_LIGNE)

    fun libelle(lieu: String, tablette: Boolean = true): String = when (lieu) {
        PC -> "Sur le PC (Canary)"
        HA -> "Sur Home Assistant (Speech-to-Phrase)"
        EN_LIGNE -> "En ligne"
        else -> if (tablette) "Sur la tablette (Canary)" else "Sur cet appareil (Canary)"
    }

    /** Nom court du lieu, pour les messages et le Déroulé. */
    fun nom(lieu: String): String = when (lieu) {
        PC -> "le PC"
        HA -> "Home Assistant"
        EN_LIGNE -> "le service en ligne"
        else -> "la tablette"
    }

    /** Connexion qui porte la demande ("pc" ou "ha") et moteur demandé au serveur. */
    data class Voie(val connexion: String, val moteur: String)

    /**
     * Voie pour [lieu] d'après les moteurs annoncés par le PC ([capPc]) et par HA ([capHa]), null tant
     * qu'un serveur n'a rien annoncé. Null : impossible, ou « Sur la tablette ».
     */
    fun voie(lieu: String, capPc: List<String>?, capHa: List<String>?): Voie? = when (lieu) {
        PC -> if (capPc?.contains("pc") == true) Voie(PC, "pc") else null
        HA -> if (capHa?.contains("ha_stp") == true) Voie(HA, "ha_stp") else null
        EN_LIGNE -> when {
            capHa?.contains("api") == true -> Voie(HA, "api")
            capPc?.contains("api") == true -> Voie(PC, "api")
            else -> null
        }
        else -> null
    }

    /** Lieux proposés : la tablette toujours, les autres seulement si un serveur les annonce. */
    fun disponibles(capPc: List<String>?, capHa: List<String>?): List<String> =
        LIEUX.filter { it == TABLETTE || voie(it, capPc, capHa) != null }

    /** Issue d'une transcription déportée : le texte, ou la raison du repli sur la tablette. */
    data class Issue(val texte: String?, val repli: String?, val moteur: String = "", val msServeur: Long = 0L)

    fun issue(reponse: JSONObject?): Issue {
        if (reponse == null) return Issue(null, "pas de réponse en ${DELAI_MS / 1000} s")
        val erreur = reponse.optString("erreur")
        if (erreur.isNotBlank()) return Issue(null, "erreur du serveur : $erreur")
        val texte = reponse.optString("texte").trim()
        if (texte.isEmpty()) return Issue(null, "rien reconnu")
        return Issue(texte, null, reponse.optString("moteur"), reponse.optLong("ms", 0L))
    }

    /** Message envoyé au serveur : son PCM 16 bits 16 kHz mono en base64 (petit-boutiste). */
    fun message(id: Int, pcm: ShortArray, moteur: String, base64: (ByteArray) -> String): JSONObject {
        val octets = ByteBuffer.allocate(pcm.size * 2).order(ByteOrder.LITTLE_ENDIAN)
        octets.asShortBuffer().put(pcm)
        return JSONObject().put("type", "transcrire").put("id", id).put("moteur", moteur).put("pcm", base64(octets.array()))
    }
}

/**
 * Connexion dédiée vers le serveur du PC pour la transcription déportée (serveur 0.18.4), sur le modèle
 * de VisionPc : même jeton, même épinglage de la clé (Confiance), au plus un essai toutes les 10 s, port
 * chiffré seulement (pas de voix en clair sur le réseau). Les capacités annoncées disent si le PC
 * transcrit ([transcriptions]). [changement] est appelé quand elles arrivent ou que la connexion tombe.
 *
 * 0.19.0 : la même connexion sert au résumé de santé du propriétaire pour l'accueil ([sante], serveur 0.19.0, capacité
 * `sante` annoncée dans `capacites`), le serveur de l'appli HA n'ayant pas accès au service de santé. Rien de
 * la réponse n'est écrit dans le journal.
 */
class TranscriptionPc(
    private val contexte: Context,
    url: String,
    private val changement: () -> Unit = {},
) : AutoCloseable {
    private val adresse = url.trim().trimEnd('/')
    private val base = Confiance.clientWebSocket(connexionS = 4)
    @Volatile private var ws: WebSocket? = null
    /** Moteurs annoncés par le PC, null tant qu'il n'a rien annoncé (ou connexion perdue). */
    @Volatile var transcriptions: List<String>? = null
        private set
    /** Le PC annonce le résumé de santé (capacité `sante`), faux tant qu'il n'a rien annoncé. */
    @Volatile var santeDispo = false
        private set

    /** Capacité `meteo_mer` du PC (0.25.0, serveur 0.22.0) : page Mer du panneau Météo. */
    @Volatile var meteoMerDispo = false
        private set

    /** Capacité `vent_mesure` du PC (0.29.0, serveur 0.24.0) : page du vent mesuré. */
    @Volatile var ventMesureDispo = false
        private set

    /** Capacité `air_historique` du PC (serveur 0.48.0, appli 0.47.0) : courbes de l'air d'une pièce. */
    @Volatile var airHistoriqueDispo = false
        private set

    /** Le PC annonce l'historique de santé (capacité `sante_historique`, serveur 0.20, onglets de la santé). */
    @Volatile var historiqueDispo = false
        private set
    @Volatile var etat = "pas encore connecté"
        private set
    @Volatile private var ferme = false
    @Volatile private var prochainEssai = 0L
    private val identifiants = AtomicInteger(0)
    private val attentes = ConcurrentHashMap<Int, CompletableFuture<JSONObject?>>()

    /** Ouvre la connexion si besoin, au plus une tentative toutes les 10 s. */
    fun ouvrir() {
        if (ferme || ws != null || SystemClock.elapsedRealtime() < prochainEssai) return
        synchronized(this) {
            if (ws != null) return
            prochainEssai = SystemClock.elapsedRealtime() + 10_000
            if (!Confiance.chiffree(adresse)) {
                etat = "adresse du PC non chiffrée ($adresse)"
                return
            }
            etat = "connexion"
            try {
                ws = Confiance.client(base, contexte, adresse).newWebSocket(Confiance.requete(contexte, adresse), Ecouteur())
            } catch (_: Exception) {
                etat = "adresse invalide"
                ws = null
            }
        }
    }

    /** Transcrit la phrase par le moteur [moteur] du PC. Réponse du serveur, ou null sans réponse dans le délai. */
    fun transcrire(pcm: ShortArray, moteur: String, delaiMs: Long): JSONObject? {
        val socket = ws ?: return null
        if (transcriptions == null) return null
        val id = identifiants.incrementAndGet()
        val promesse = CompletableFuture<JSONObject?>()
        attentes[id] = promesse
        val msg = OuTranscrire.message(id, pcm, moteur) { Base64.encodeToString(it, Base64.NO_WRAP) }
        if (!socket.send(msg.toString())) {
            attentes.remove(id)
            return null
        }
        return try {
            promesse.get(delaiMs, TimeUnit.MILLISECONDS)
        } catch (_: Exception) {
            null
        } finally {
            attentes.remove(id)
        }
    }

    /**
     * Résumé de santé du jour (`{"type": "sante", "id": n}`) : la réponse entière du serveur (`donnees`, ou
     * `erreur`), ou null sans capacité, sans connexion ou sans réponse dans le délai. Appel bloquant.
     */
    fun sante(delaiMs: Long): JSONObject? {
        val socket = ws ?: return null
        if (!santeDispo) return null
        val id = identifiants.incrementAndGet()
        val promesse = CompletableFuture<JSONObject?>()
        attentes[id] = promesse
        if (!socket.send(JSONObject().put("type", "sante").put("id", id).toString())) {
            attentes.remove(id)
            return null
        }
        return try {
            promesse.get(delaiMs, TimeUnit.MILLISECONDS)
        } catch (_: Exception) {
            null
        } finally {
            attentes.remove(id)
        }
    }

    /**
     * Météo marine de la rade de Marseille (0.25.0, `{"type": "meteo_mer", "id": n}`) : la réponse entière du serveur, ou
     * null sans capacité, sans connexion ou sans réponse dans le délai. Appel bloquant.
     */
    fun meteoMer(delaiMs: Long): JSONObject? {
        if (!meteoMerDispo) return null
        return demanderHistorique(JSONObject().put("type", "meteo_mer"), delaiMs, verifier = false)
    }

    /** Vent mesuré dans le golfe (0.29.0, `{"type": "vent_mesure", "id": n}`), comme [meteoMer]. */
    fun ventMesure(delaiMs: Long): JSONObject? {
        if (!ventMesureDispo) return null
        return demanderHistorique(JSONObject().put("type", "vent_mesure"), delaiMs, verifier = false)
    }

    /**
     * Historique de l'air d'une pièce (serveur 0.48.0) : `{"type": "air_historique", "piece", "heures"}`.
     * [heures] entre 1 et 168, le serveur plafonne. Réponse entière (`donnees` ou `erreur`), ou null sans
     * capacité, sans connexion ou sans réponse dans le délai. Appel bloquant, comme [meteoMer].
     */
    fun airHistorique(piece: String, heures: Int, delaiMs: Long): JSONObject? {
        if (!airHistoriqueDispo) return null
        return demanderHistorique(
            JSONObject().put("type", "air_historique").put("piece", piece).put("heures", heures),
            delaiMs, verifier = false,
        )
    }

    /**
     * Demande d'historique de santé (0.22.0) : [corps] porte son `type` (`sante_periode`, `sante_seances`,
     * `sante_seance`, `sante_records`, `sante_jour`) et ses paramètres, l'identifiant est ajouté ici. Réponse
     * entière du serveur, ou null sans capacité, sans connexion ou sans réponse dans le délai. Appel bloquant.
     * Rien de la réponse n'est écrit dans le journal.
     */
    fun demanderHistorique(corps: JSONObject, delaiMs: Long, verifier: Boolean = true): JSONObject? {
        val socket = ws ?: return null
        if (verifier && !historiqueDispo) return null
        val id = identifiants.incrementAndGet()
        val promesse = CompletableFuture<JSONObject?>()
        attentes[id] = promesse
        if (!socket.send(JSONObject(corps.toString()).put("id", id).toString())) {
            attentes.remove(id)
            return null
        }
        return try {
            promesse.get(delaiMs, TimeUnit.MILLISECONDS)
        } catch (_: Exception) {
            null
        } finally {
            attentes.remove(id)
        }
    }

    private fun perdu(socket: WebSocket, raison: String) {
        if (socket !== ws) return
        ws = null
        transcriptions = null
        santeDispo = false
        historiqueDispo = false
        meteoMerDispo = false
        ventMesureDispo = false
        airHistoriqueDispo = false
        etat = raison
        for (p in attentes.values) p.complete(null)
        attentes.clear()
        changement()
    }

    private inner class Ecouteur : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            if (webSocket === ws) etat = "connecté, en attente des capacités"
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            if (webSocket !== ws) return
            val j = try {
                JSONObject(text)
            } catch (_: Exception) {
                return
            }
            when (j.optString("etat")) {
                "capacites" -> {
                    val annoncee = j.optString("empreinte")
                    val retenue = Confiance.empreinte(contexte, adresse)
                    if (annoncee.isNotEmpty() && retenue != null && annoncee != retenue) {
                        etat = "clé annoncée différente de la clé reçue : connexion coupée"
                        webSocket.cancel()
                        return
                    }
                    val a = j.optJSONArray("transcription")
                    transcriptions = if (a == null) emptyList() else (0 until a.length()).map { a.optString(it) }.filter { it.isNotEmpty() }
                    santeDispo = annonceSante(j)
                    historiqueDispo = annonceCapacite(j, "sante_historique")
                    meteoMerDispo = annonceCapacite(j, "meteo_mer")
                    ventMesureDispo = annonceCapacite(j, "vent_mesure")
                    airHistoriqueDispo = annonceCapacite(j, "air_historique")
                    // Seulement la capacité, jamais une valeur de santé (0.19.1).
                    android.util.Log.i("JarvisSante", "capacité santé du PC : " + (if (santeDispo) "oui" else "non"))
                    etat = "prêt (serveur v${j.optString("version")}" + (if (santeDispo) ", santé" else "") + ")"
                    changement()
                }
                "transcrit", "sante", "meteo_mer", "vent_mesure", "air_historique", "sante_periode", "sante_seances", "sante_seance", "sante_records", "sante_jour" ->
                    attentes.remove(j.optInt("id", -1))?.complete(j)
            }
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            try {
                webSocket.close(1000, null)
            } catch (_: Exception) {
            }
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) =
            perdu(webSocket, if (code == 4001) "jeton refusé par le PC" else "connexion fermée ($code)")

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            val cle = Confiance.cleChangee(t)
            perdu(webSocket, if (cle != null) "clé du PC refusée" else "PC injoignable (${t.javaClass.simpleName})")
        }
    }

    override fun close() {
        ferme = true
        val s = ws
        ws = null
        transcriptions = null
        santeDispo = false
        for (p in attentes.values) p.complete(null)
        try {
            s?.close(1000, "fin")
        } catch (_: Exception) {
        }
        base.dispatcher.executorService.shutdown()
    }
}

/** Capacité `sante` des capacités du PC : vrai, un objet ou une liste non vide, ou « sante » dans une liste. */
internal fun annonceSante(capacites: JSONObject): Boolean = annonceCapacite(capacites, "sante")

/** Capacité [nom] des capacités du PC (0.22.0) : vrai, un objet ou une liste non vide, ou [nom] dans une liste. */
internal fun annonceCapacite(capacites: JSONObject, nom: String): Boolean {
    when (val v = capacites.opt(nom)) {
        is Boolean -> return v
        is JSONObject -> return v.length() > 0
        is org.json.JSONArray -> return v.length() > 0
        is String -> return v.isNotBlank() && v != "false" && v != "0"
        is Number -> return v.toInt() != 0
    }
    for (cle in capacites.keys()) {
        val a = capacites.optJSONArray(cle) ?: continue
        for (i in 0 until a.length()) if (a.optString(i) == nom) return true
    }
    return false
}
