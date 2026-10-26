package assistant.vocal.jarvis

/**
 * Chien de garde de la passerelle Home Assistant (0.38.2).
 *
 * Une socket peut rester ouverte et saine (les pings passent) sans que la passerelle devienne
 * disponible : capacités jamais reçues, ou reçues sans `passerelle_ha` pendant que l'appli de
 * l'assistant sur HA redémarre. Aucun échec ne survient alors, donc aucune relance. Cette garde dit
 * quand il faut annuler la socket et rouvrir : une même socket, existante mais pas disponible, depuis
 * plus de [delaiMs]. Sans Android, pour être testée sur la JVM.
 */
class GardeReconnexion(private val delaiMs: Long = DELAI_MS) {

    private var suivie: Any? = null
    private var depuis = 0L

    /**
     * Vrai si la [socket] courante doit être annulée. Une autre socket que la précédente (réouverture)
     * relance le chronomètre, de même qu'une passerelle [disponible] ou l'absence de socket.
     */
    @Synchronized
    fun doitRelancer(socket: Any?, disponible: Boolean, maintenantMs: Long): Boolean {
        if (socket == null || disponible) {
            suivie = null
            return false
        }
        if (socket !== suivie) {
            suivie = socket
            depuis = maintenantMs
            return false
        }
        if (maintenantMs - depuis < delaiMs) return false
        suivie = null
        return true
    }

    companion object {
        const val DELAI_MS = 30_000L
    }
}
