package assistant.vocal.jarvis

import android.app.AlarmManager
import android.app.PendingIntent
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.os.SystemClock
import android.provider.Settings
import android.util.Log
import java.util.Calendar

/**
 * Mode station (0.16.0) : la tablette du séjour fait tourner assistant en permanence, sur secteur.
 *
 * Android coupe le micro et la caméra à un service lancé en arrière-plan (démarrage, relance après
 * une mort du processus). Le chemin sûr est donc de remettre l'écran d'un projet d'inspiration devant, qui démarre
 * lui-même le service. Ouvrir un écran depuis l'arrière-plan demande l'autorisation « Afficher
 * par-dessus les autres applications », que la carte Station fait accorder.
 */
object Station {
    private const val TAG = "JarvisStation"
    const val EXTRA_STATION = "station_demarrage"

    /**
     * Nuit de minuit à 7 h, à l'heure de l'appareil : écran éteint sans personne, luminosité à 10 %
     * au plus avec quelqu'un. La luminosité elle-même est calculée par Veille (0.17.0).
     */
    fun nuit(heure: Int = Calendar.getInstance().get(Calendar.HOUR_OF_DAY)): Boolean = heure in 0 until 7

    /** L'écran principal d'un projet d'inspiration est affiché (entre onStart et onStop). */
    @Volatile var ecranVisible = false

    fun peutOuvrirEcran(ctx: Context): Boolean = Settings.canDrawOverlays(ctx)

    /** Remet l'écran d'un projet d'inspiration devant (il démarre le service s'il ne tourne pas). */
    fun ouvrirEcran(ctx: Context) {
        try {
            ctx.startActivity(
                Intent(ctx, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
                    .putExtra(EXTRA_STATION, true)
            )
        } catch (e: Exception) {
            Log.w(TAG, "Écran impossible à ouvrir depuis l'arrière-plan", e)
        }
    }

    /** Démarre le service directement, au cas où l'écran ne pourrait pas s'ouvrir. */
    fun demarrerService(ctx: Context) {
        try {
            ctx.startForegroundService(Intent(ctx, SatelliteService::class.java))
        } catch (e: Exception) {
            Log.w(TAG, "Service impossible à démarrer depuis l'arrière-plan", e)
        }
    }

    /** Service tué hors d'un arrêt demandé : l'écran est rouvert 5 s plus tard. */
    fun planifierRelance(ctx: Context) {
        try {
            val am = ctx.getSystemService(AlarmManager::class.java) ?: return
            val pi = PendingIntent.getActivity(
                ctx, 7,
                Intent(ctx, MainActivity::class.java)
                    .addFlags(Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP)
                    .putExtra(EXTRA_STATION, true),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            )
            am.setAndAllowWhileIdle(AlarmManager.ELAPSED_REALTIME_WAKEUP, SystemClock.elapsedRealtime() + 5_000, pi)
        } catch (e: Exception) {
            Log.w(TAG, "Relance impossible à planifier", e)
        }
    }
}

/** Démarrage de la tablette (ou mise à jour de l'appli) : assistant repart seul en mode station. */
class RecepteurDemarrage : BroadcastReceiver() {
    override fun onReceive(contexte: Context, intent: Intent) {
        val action = intent.action ?: return
        if (action != Intent.ACTION_BOOT_COMPLETED && action != Intent.ACTION_MY_PACKAGE_REPLACED) return
        val app = contexte.applicationContext
        if (!SatelliteService.station(app)) return
        SatelliteService.preferences(app).edit().putBoolean(SatelliteService.CLE_ARRET_VOLONTAIRE, false).apply()
        if (Station.peutOuvrirEcran(app)) Station.ouvrirEcran(app) else Station.demarrerService(app)
    }
}
