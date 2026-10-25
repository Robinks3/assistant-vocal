package assistant.vocal.jarvis

import java.net.ConnectException
import java.net.NoRouteToHostException
import java.net.SocketTimeoutException
import java.net.URI
import java.net.UnknownHostException
import javax.net.ssl.SSLException

/**
 * Retrouver un serveur dont l'adresse a changé, et dire pourquoi une connexion échoue (0.34.0).
 *
 * L'adresse enregistrée (une IP au départ) reste l'identité du serveur : jeton et clé retenus sont rangés
 * dessous (voir [Confiance]). Les [candidats] ne font que changer le chemin pour l'atteindre : la dernière cible qui
 * a répondu, les noms d'hôte de la configuration (`android_hotes_pc`, `android_hotes_ha`), puis l'adresse
 * enregistrée en dernier recours. Rien de sensible ne change de main : le jeton ne part qu'après l'épinglage de la
 * clé du serveur, quelle que soit la cible.
 */
object Decouverte {

    enum class Cause { RESEAU, CERTIFICAT, JETON, RESEAU_REFUSE, ROLE, SERVEUR }

    class Diagnostic(val cause: Cause, val texte: String) {
        /** Une cause qui se règle par un nouvel appairage. */
        val jetonRefuse: Boolean get() = cause == Cause.JETON
    }

    /** Noms d'hôte séparés par des virgules (BuildConfig), sans doublon ni entrée vide. */
    fun hotes(liste: String): List<String> =
        liste.split(',').map { it.trim() }.filter { it.isNotEmpty() && !it.contains("/") && !it.contains(" ") }.distinct()

    /**
     * Cibles à essayer, dans l'ordre : [derniere] (la dernière qui a répondu), un [hotes] par nom d'hôte sur le
     * schéma et le port de [configuree], puis [configuree]. Sans doublon. [configuree] est vide ou illisible :
     * la liste ne contient que ce qui est exploitable.
     */
    fun candidats(configuree: String, hotes: List<String>, derniere: String?): List<String> {
        val base = configuree.trim().trimEnd('/')
        val u = try {
            URI(base)
        } catch (_: Exception) {
            null
        }
        val parNom = if (u?.scheme == null || u.host == null) emptyList() else hotes.map { h ->
            val port = if (u.port > 0) ":${u.port}" else ""
            "${u.scheme}://$h$port"
        }
        val coherente = derniere?.trim()?.trimEnd('/')?.takeIf { d ->
            d.isNotEmpty() && u?.scheme != null && Regex("^${Regex.escape(u.scheme)}://").containsMatchIn(d)
        }
        return (listOfNotNull(coherente) + parNom + listOf(base)).filter { it.isNotEmpty() }.distinct()
    }

    /** Cible de la tentative numéro [essai] (0, 1, 2...), en tournant sur [cibles]. */
    fun cibleDe(cibles: List<String>, essai: Int): String? =
        if (cibles.isEmpty()) null else cibles[Math.floorMod(essai, cibles.size)]

    /**
     * Cause d'un échec. [code] et [raison] viennent de la fermeture du WebSocket par le serveur, [http] du code
     * de la réponse à la poignée de main, [t] de l'exception du réseau. Ne contient jamais de jeton.
     */
    fun diagnostic(code: Int?, raison: String?, http: Int?, t: Throwable?, cible: String): Diagnostic {
        val r = raison?.trim().orEmpty()
        when (code) {
            4001 -> return Diagnostic(
                Cause.JETON,
                when {
                    r.contains("révoqué") -> "Cet appareil a été révoqué par le serveur : il doit être appairé de nouveau"
                    r.contains("absent") -> "Jeton absent : le serveur n'en a reçu aucun, appairage nécessaire"
                    else -> "Jeton refusé : le serveur ne le connaît pas (serveur réinstallé ou jeton de l'APK périmé), appairage nécessaire"
                },
            )
            4003 -> return Diagnostic(
                Cause.RESEAU_REFUSE,
                "Réseau refusé par le serveur : cet appareil n'est pas dans les réseaux autorisés (acces.reseaux_autorises)",
            )
        }
        if (http == 401 || http == 403) {
            return Diagnostic(Cause.JETON, "Jeton refusé par le serveur ($http), appairage nécessaire")
        }
        if (http != null) return Diagnostic(Cause.SERVEUR, "Réponse inattendue du serveur ($http) sur $cible")
        var e = t
        var n = 0
        while (e != null && n++ < 8) {
            when {
                e is Confiance.CleChangee -> return Diagnostic(
                    Cause.CERTIFICAT, "Clé du serveur différente de celle retenue : réinstallation du serveur ou serveur usurpé",
                )
                e is UnknownHostException -> return Diagnostic(Cause.RESEAU, "Nom d'hôte introuvable ($cible), l'adresse a peut-être changé")
                e is SocketTimeoutException -> return Diagnostic(Cause.RESEAU, "Pas de réponse de $cible (serveur éteint, coupure ou autre réseau)")
                e is ConnectException || e is NoRouteToHostException ->
                    return Diagnostic(Cause.RESEAU, "Connexion à $cible impossible (serveur éteint, redémarrage en cours ou adresse changée)")
                e is SSLException -> return Diagnostic(Cause.CERTIFICAT, "Liaison chiffrée avec $cible impossible (${e.javaClass.simpleName})")
            }
            e = e.cause
        }
        return Diagnostic(Cause.RESEAU, "Déconnecté de $cible (${t?.javaClass?.simpleName ?: "fermeture"})")
    }

    /** Clé de l'hôte pour l'affichage d'une cible : « hôte:port ». */
    fun libelle(cible: String): String = Confiance.cleAdresse(cible)
}
