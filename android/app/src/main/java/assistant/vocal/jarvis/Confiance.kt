package assistant.vocal.jarvis

import android.annotation.SuppressLint
import android.content.Context
import android.util.Log
import okhttp3.OkHttpClient
import okhttp3.Request
import java.net.URI
import java.security.MessageDigest
import java.security.cert.CertificateException
import java.security.cert.X509Certificate
import java.util.Base64
import java.util.concurrent.TimeUnit
import javax.net.ssl.HostnameVerifier
import javax.net.ssl.SSLContext
import javax.net.ssl.SSLSession
import javax.net.ssl.X509TrustManager

/**
 * Liaison sécurisée avec les serveurs Jarvis (0.15.0, serveur 0.17.0).
 *
 * Le port chiffré (wss, 8766) présente un certificat auto-signé : aucune autorité ne peut le
 * garantir, on épingle donc sa clé publique à la première connexion (TOFU). L'empreinte SHA-256
 * de la clé SPKI est retenue par adresse, puis toute autre clé est refusée. Le nom d'hôte n'est
 * pas vérifié (on se connecte par IP et le certificat dit « jarvis ») : c'est l'épinglage qui
 * remplace cette vérification.
 *
 * Le jeton part dans l'en-tête Authorization, jamais dans l'adresse, qui finit dans les journaux.
 * Jeton utilisé : celui obtenu par appairage avec ce serveur s'il existe, sinon celui de l'APK.
 */
object Confiance {
    private const val TAG = "JarvisConfiance"
    private const val PREFIXE_EMPREINTE = "empreinte_"
    private const val PREFIXE_JETON = "jeton_"
    const val PORT_CHIFFRE = 8766
    const val PORT_CLAIR = 8765
    /** Délai de la poignée de main WebSocket (0.32.1), en millisecondes. */
    const val POIGNEE_DE_MAIN_MS = 15_000L

    /**
     * Client de base de toutes les liaisons WebSocket de l'appli (0.32.1) : ping toutes les 20 s, lecture sans
     * limite pour la liaison montée, et [poigneeDeMainMs] pour la poignée de main (TLS, requête, réponse 101).
     * OkHttp n'applique ce callTimeout qu'à la poignée de main et le lève dès la liaison montée. Sans lui, un
     * serveur qui accepte la connexion puis se tait (appli HA qui redémarre) bloquait l'appel pour toujours :
     * ni onOpen ni onFailure, le WebSocket restait attribué et aucune reconnexion ne partait.
     */
    fun clientWebSocket(connexionS: Long = 5, poigneeDeMainMs: Long = POIGNEE_DE_MAIN_MS): OkHttpClient =
        OkHttpClient.Builder()
            .pingInterval(20, TimeUnit.SECONDS)
            .connectTimeout(connexionS, TimeUnit.SECONDS)
            .readTimeout(0, TimeUnit.MILLISECONDS)
            .callTimeout(poigneeDeMainMs, TimeUnit.MILLISECONDS)
            .build()

    /** Refus d'une clé qui n'est pas celle retenue : le message est affiché tel quel. */
    class CleChangee(val adresse: String, val attendue: String, val recue: String) : CertificateException(
        "La clé du serveur a changé ($adresse). Connexion refusée : si tu as réinstallé le serveur, " +
            "oublie l'ancienne clé dans l'écran Appareils."
    )

    private fun prefs(ctx: Context) = SatelliteService.preferences(ctx)

    /** « hôte:port » de l'adresse, clé des empreintes retenues. */
    fun cleAdresse(url: String): String {
        val u = try {
            URI(url.trim())
        } catch (_: Exception) {
            return url.trim()
        }
        val port = if (u.port > 0) u.port else if (u.scheme == "wss") 443 else 80
        return "${u.host ?: url}:$port"
    }

    /** Hôte seul : le jeton d'appairage vaut pour le serveur, en chiffré comme en clair. */
    fun hote(url: String): String = try {
        URI(url.trim()).host ?: url.trim()
    } catch (_: Exception) {
        url.trim()
    }

    fun chiffree(url: String): Boolean = url.trim().startsWith("wss://")

    /** ws://hôte:8765 devient wss://hôte:8766 (migration de la 0.15.0), sinon null. */
    fun versChiffre(url: String): String? {
        val m = Regex("^ws://([^/:]+):$PORT_CLAIR/?$").find(url.trim()) ?: return null
        return "wss://${m.groupValues[1]}:$PORT_CHIFFRE"
    }

    /**
     * Ancienne adresse en clair à essayer si le port chiffré ne répond pas (serveur pas encore à
     * jour). Jamais une fois qu'une clé a été retenue pour cette adresse : le chiffrement a déjà
     * marché, un port muet ressemblerait alors à une tentative de faire passer le jeton en clair.
     */
    fun repli(ctx: Context, url: String): String? {
        val m = Regex("^wss://([^/:]+):$PORT_CHIFFRE/?$").find(url.trim()) ?: return null
        if (empreinte(ctx, url) != null) return null
        return "ws://${m.groupValues[1]}:$PORT_CLAIR"
    }

    fun empreinte(ctx: Context, url: String): String? = prefs(ctx).getString(PREFIXE_EMPREINTE + cleAdresse(url), null)

    fun oublierEmpreinte(ctx: Context, url: String) {
        prefs(ctx).edit().remove(PREFIXE_EMPREINTE + cleAdresse(url)).apply()
        Log.i(TAG, "clé oubliée pour ${cleAdresse(url)}")
    }

    private fun retenir(ctx: Context, url: String, e: String) {
        prefs(ctx).edit().putString(PREFIXE_EMPREINTE + cleAdresse(url), e).commit()
        Log.i(TAG, "clé retenue pour ${cleAdresse(url)} : sha256/$e")
    }

    fun jetonAppaire(ctx: Context, url: String): String? = prefs(ctx).getString(PREFIXE_JETON + hote(url), null)

    fun jeton(ctx: Context, url: String): String = jetonAppaire(ctx, url) ?: BuildConfig.JETON_DEFAUT

    fun enregistrerJeton(ctx: Context, url: String, jeton: String) {
        prefs(ctx).edit().putString(PREFIXE_JETON + hote(url), jeton).commit()
    }

    fun oublierJeton(ctx: Context, url: String) {
        prefs(ctx).edit().remove(PREFIXE_JETON + hote(url)).apply()
    }

    /** Empreinte SHA-256 en base64 de la clé publique SPKI, comme acces.certificat côté serveur. */
    fun spki(cert: X509Certificate): String =
        Base64.getEncoder().encodeToString(MessageDigest.getInstance("SHA-256").digest(cert.publicKey.encoded))

    private const val PREFIXE_DERNIERE = "derniere_cible_"

    /** Dernière cible qui a répondu pour l'adresse configurée [identite] (0.34.0), ou null. */
    fun derniereCible(ctx: Context, identite: String): String? =
        prefs(ctx).getString(PREFIXE_DERNIERE + cleAdresse(identite), null)

    fun retenirCible(ctx: Context, identite: String, cible: String) {
        prefs(ctx).edit().putString(PREFIXE_DERNIERE + cleAdresse(identite), cible).apply()
    }

    /**
     * Requête WebSocket vers [url] + [chemin], jeton en en-tête si [avecJeton]. [identite] (0.34.0) est l'adresse
     * configurée du serveur : le jeton est celui de cette identité, même quand [url] est une autre cible
     * (nom d'hôte, dernière adresse connue) qui mène au même serveur.
     */
    fun requete(ctx: Context, url: String, chemin: String = "/", avecJeton: Boolean = true, identite: String = url): Request {
        val b = Request.Builder().url(url.trim().trimEnd('/') + chemin)
        if (avecJeton) b.header("Authorization", "Bearer " + jeton(ctx, identite))
        return b.build()
    }

    /**
     * Client dérivé de [base] qui épingle la clé de [identite] (adresse wss, [url] par défaut), ou [base] pour ws.
     * Une cible alternative présente donc la même clé que l'adresse configurée, sinon elle est refusée.
     */
    fun client(base: OkHttpClient, ctx: Context, url: String, identite: String = url): OkHttpClient {
        if (!chiffree(url)) return base
        val gardien = Gardien(ctx.applicationContext, identite)
        val tls = SSLContext.getInstance("TLS").apply { init(null, arrayOf(gardien), null) }
        return base.newBuilder()
            .sslSocketFactory(tls.socketFactory, gardien)
            .hostnameVerifier(gardien)
            .build()
    }

    /** Remonte les causes d'un échec pour y trouver un refus de clé. */
    fun cleChangee(t: Throwable?): CleChangee? {
        var e = t
        var n = 0
        while (e != null && n++ < 8) {
            if (e is CleChangee) return e
            e.suppressed.firstOrNull { it is CleChangee }?.let { return it as CleChangee }
            e = e.cause
        }
        return null
    }

    /**
     * Épinglage d'une adresse : retient la clé à la première poignée de main, refuse ensuite
     * toute autre. Sert aussi de vérificateur de nom d'hôte, qui contrôle la même empreinte.
     */
    @SuppressLint("CustomX509TrustManager")
    private class Gardien(private val ctx: Context, private val url: String) : X509TrustManager, HostnameVerifier {

        @SuppressLint("TrustAllX509TrustManager")
        override fun checkClientTrusted(chain: Array<out X509Certificate>?, authType: String?) {
            throw CertificateException("pas de certificat client attendu")
        }

        override fun checkServerTrusted(chain: Array<out X509Certificate>?, authType: String?) {
            val cert = chain?.firstOrNull() ?: throw CertificateException("aucun certificat présenté")
            val recue = spki(cert)
            synchronized(Confiance) {
                val attendue = empreinte(ctx, url)
                if (attendue == null) {
                    retenir(ctx, url, recue)
                } else if (attendue != recue) {
                    Log.w(TAG, "clé refusée pour ${cleAdresse(url)} : attendue $attendue, reçue $recue")
                    throw CleChangee(cleAdresse(url), attendue, recue)
                }
            }
        }

        override fun getAcceptedIssuers(): Array<X509Certificate> = emptyArray()

        override fun verify(hostname: String?, session: SSLSession?): Boolean {
            val cert = try {
                session?.peerCertificates?.firstOrNull() as? X509Certificate
            } catch (_: Exception) {
                null
            } ?: return false
            return spki(cert) == empreinte(ctx, url)
        }
    }
}
