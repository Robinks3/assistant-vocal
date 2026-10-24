package assistant.vocal.jarvis

import android.content.Context
import android.hardware.Sensor
import android.hardware.SensorEvent
import android.hardware.SensorEventListener
import android.hardware.SensorManager
import kotlin.math.abs
import kotlin.math.log10
import kotlin.math.max
import kotlin.math.min

/**
 * Luminosité de l'écran selon la lumière de la pièce (0.28.0), logique pure testée sur la machine
 * (LumiereAmbianteTest). Demande du 24/10/2026 à 0 h 45 : « Pourquoi là c'est en mode très peu de
 * lumière ? », puis « Utilise le capteur de lumière pour adapter les choses ». Jusqu'à la 0.27.0, le plafond du
 * régime vivant suivait l'heure : 40 %, 10 % de minuit à 7 h, même dans un séjour éclairé.
 *
 * Le capteur de la tablette (veml3328, android.sensor.light) ne parle que quand la lumière change. Trois filtres
 * avant la courbe :
 * - médiane des mesures des [FENETRE_MS] dernières secondes (la dernière reste valable tant qu'aucune ne la
 *   remplace) : une lampe de téléphone passée devant, une main, un reflet ne comptent pas ;
 * - hystérésis : un nouveau niveau n'est retenu que s'il s'écarte de plus de [SEUIL_LOG] décade du niveau retenu
 *   (environ 40 %), et cela pendant [STABLE_MS] sans interruption. Quelqu'un qui se penche ne change rien. L'écran
 *   ne se voit pas sur le capteur (0 lux mesuré dans le séjour éteint, écran encore à sa consigne du séjour
 *   allumé) : pas de boucle entre l'écran et le capteur ;
 * - la consigne qui en sort rejoint la nouvelle valeur lentement ([MONTEE_PAR_S], [DESCENTE_PAR_S]) : l'écran ne
 *   pompe pas.
 *
 * Sans capteur, ou sans mesure depuis l'abonnement, [plafond] rend la règle de l'heure d'avant (40 %, 10 % la
 * nuit). Horloge monotone en millisecondes donnée par l'appelant.
 */
class LumiereAmbiante {

    private val mesures = ArrayDeque<Pair<Long, Float>>()
    /** Niveau de la pièce retenu (lux), après médiane et hystérésis, null sans mesure. */
    var luxRetenu: Float? = null
        private set
    /** Écart au niveau retenu vu depuis cet instant (-1 : aucun), et la valeur qui le porte. */
    private var ecartDepuis = -1L
    private var candidat = 0f
    /** Consigne appliquée, qui rejoint la courbe lentement, et la cible qu'elle rejoint. */
    private var applique = -1f
    private var cible = -1f
    private var dernierPas = -1L
    /** Capteur rebranché : l'estimation d'avant tient jusqu'à cet instant, la première mesure est prise sans hystérésis. */
    private var attenteJusqua = -1L
    private var premiere = false

    /** Une mesure du capteur, en lux. */
    fun mesure(lux: Float, maintenant: Long) {
        if (lux.isNaN() || lux < 0f) return
        mesures.addLast(maintenant to lux)
        // On garde la fenêtre, plus la mesure encore en vigueur à son début (un capteur à changement peut se taire
        // longtemps : sa dernière valeur reste celle de la pièce).
        while (mesures.size > 1 && maintenant - mesures[1].first >= FENETRE_MS) mesures.removeFirst()
        while (mesures.size > MESURES_MAX) mesures.removeFirst()
    }

    /**
     * Capteur coupé (activité arrêtée) : les mesures sont oubliées, mais pas le dernier niveau ni la consigne. Au
     * retour, ils tiennent lieu d'estimation pendant [ATTENTE_MS] (pas de creux vers la règle de l'heure à chaque
     * réveil), la première mesure est retenue sans hystérésis et la consigne la rejoint lentement.
     */
    fun oublier() {
        mesures.clear()
        ecartDepuis = -1L
        premiere = true
    }

    /** Capteur rebranché à [maintenant] : début de l'attente de sa première mesure. */
    fun attendre(maintenant: Long) {
        attenteJusqua = maintenant + ATTENTE_MS
        premiere = true
    }

    val disponible: Boolean get() = mesures.isNotEmpty()

    /** La consigne n'a pas encore rejoint la courbe : l'appelant l'avance plus souvent qu'une fois par seconde. */
    val enTransition: Boolean get() = applique >= 0f && cible >= 0f && abs(applique - cible) > 1e-4f

    /**
     * Médiane des [FENETRE_MS] dernières secondes, chaque valeur pesant le temps où elle a été en vigueur (le capteur ne
     * parle qu'aux changements) : un éclair d'1 s dans une pièce stable ne pèse qu'un quart de la fenêtre. À égalité
     * de poids, la valeur la plus claire l'emporte (une ombre ne fait pas basculer vers le sombre).
     */
    fun luxMedian(maintenant: Long): Float? {
        if (mesures.isEmpty()) return null
        val debut = maintenant - FENETRE_MS
        val poids = ArrayList<Pair<Float, Long>>(mesures.size)
        for (i in mesures.indices) {
            val de = max(mesures[i].first, debut)
            val a = if (i + 1 < mesures.size) mesures[i + 1].first else maintenant
            if (a > de) poids.add(mesures[i].second to (a - de))
        }
        if (poids.isEmpty()) return mesures.last().second
        poids.sortBy { it.first }
        val moitie = poids.sumOf { it.second } / 2.0
        var cumul = 0L
        for ((v, w) in poids) {
            cumul += w
            if (cumul > moitie) return v
        }
        return poids.last().first
    }

    /**
     * Avance jusqu'à [maintenant] : niveau retenu (hystérésis) puis consigne lissée. Rend la consigne du régime
     * vivant plein, entre [PLANCHER] et [MAXI], ou celle de l'heure sans capteur ([nuit] : minuit à 7 h).
     */
    fun plafond(maintenant: Long, nuit: Boolean): Float {
        val m = luxMedian(maintenant)
        val dt = if (dernierPas < 0L) 0f else ((maintenant - dernierPas).coerceIn(0L, 2_000L)) / 1000f
        dernierPas = maintenant
        if (m == null) {
            // Capteur rebranché, première mesure pas encore arrivée : l'estimation d'avant tient.
            if (applique >= 0f && maintenant < attenteJusqua) return applique
            // Sans capteur : la règle de l'heure, d'où une mesure future repartira lentement.
            val heure = if (nuit) Veille.LUMINOSITE_NUIT else Veille.LUMINOSITE_PLAFOND
            luxRetenu = null
            applique = heure
            cible = heure
            return heure
        }
        val retenu = luxRetenu
        if (retenu == null || premiere) {
            luxRetenu = m
            premiere = false
            ecartDepuis = -1L
        } else if (abs(niveau(m) - niveau(retenu)) > SEUIL_LOG) {
            // Chronomètre relancé quand l'écart change de valeur (ombre puis lampe) : seul un niveau tenu 4 s compte.
            if (ecartDepuis < 0L || abs(niveau(m) - niveau(candidat)) > SEUIL_LOG) {
                ecartDepuis = maintenant
                candidat = m
            }
            if (maintenant - ecartDepuis >= STABLE_MS) {
                luxRetenu = m
                ecartDepuis = -1L
            }
        } else {
            ecartDepuis = -1L
        }
        cible = courbe(luxRetenu!!)
        applique = if (applique < 0f) cible
        else if (cible > applique) min(cible, applique + MONTEE_PAR_S * dt)
        else max(cible, applique - DESCENTE_PAR_S * dt)
        return applique
    }

    /** La pièce est-elle dans le noir (moins de [LUX_SOMBRE] retenus) ? null sans mesure. */
    fun sombre(): Boolean? = luxRetenu?.let { it < LUX_SOMBRE }

    companion object {
        const val FENETRE_MS = 4_000L
        const val STABLE_MS = 4_000L
        /** 0,15 décade : environ 40 % d'écart de lumière. */
        const val SEUIL_LOG = 0.15f
        /** La consigne monte de 3 points par seconde au plus, descend de 1,5 : de 6 % à 40 % en une douzaine de secondes. */
        const val MONTEE_PAR_S = 0.03f
        const val DESCENTE_PAR_S = 0.015f
        const val MESURES_MAX = 200
        /** Au retour de l'activité, la première mesure du capteur arrive en quelques centaines de ms (300 vues). */
        const val ATTENTE_MS = 1_500L
        /** Pièce noire : moins d'un demi-lux retenu (une seule lampe du séjour en donne 1 à l'endroit de la tablette). */
        const val LUX_SOMBRE = 0.5f
        const val PLANCHER = 0.06f
        const val MAXI = 0.70f

        /**
         * Courbe lux vers consigne de la fenêtre (0 à 1), linéaire en log10(lux + 1) entre ces points. Mesures sur la
         * tablette à sa place dans le séjour (24/10/2026, 0 h 48) : 0 lux tout éteint, 1 avec la suspension seule à 100 %,
         * 3 avec la lampe de la télé en plus, 14 avec les trois lampes du séjour, et de 80 à 215 lux un après-midi
         * (22/10, capteur de couleur). Noir 6 %, séjour tout allumé le soir 35 % (10 % avant), jour 55 % (40 % avant).
         */
        val POINTS = listOf(
            0f to 0.06f,
            1f to 0.12f,
            3f to 0.20f,
            14f to 0.35f,
            60f to 0.45f,
            200f to 0.55f,
            1_000f to 0.70f,
        )

        fun niveau(lux: Float): Float = log10(max(0f, lux) + 1f)

        fun courbe(lux: Float): Float {
            val x = niveau(lux)
            val p = POINTS
            if (x <= niveau(p.first().first)) return p.first().second
            for (i in 1 until p.size) {
                val (l1, v1) = p[i]
                val x1 = niveau(l1)
                if (x <= x1) {
                    val (l0, v0) = p[i - 1]
                    val x0 = niveau(l0)
                    return v0 + (v1 - v0) * (x - x0) / (x1 - x0)
                }
            }
            return p.last().second
        }
    }
}

/**
 * Capteur de lumière de la tablette (android.sensor.light), branché tant que l'activité est visible. Chaque mesure
 * part dans [lumiere], et le niveau retenu est écrit dans le journal `JarvisLumiere` quand il change (mesures de la
 * courbe sur la tablette, `adb logcat -s JarvisLumiere`).
 */
internal class CapteurLumiere(ctx: Context, private val lumiere: LumiereAmbiante) : SensorEventListener {
    private val gestionnaire = ctx.getSystemService(Context.SENSOR_SERVICE) as? SensorManager
    private val capteur: Sensor? = gestionnaire?.getDefaultSensor(Sensor.TYPE_LIGHT)
    private var branche = false
    private var dernierJournal = -1f

    val existe: Boolean get() = capteur != null

    fun brancher() {
        if (branche || capteur == null) return
        lumiere.attendre(android.os.SystemClock.elapsedRealtime())
        branche = gestionnaire?.registerListener(this, capteur, SensorManager.SENSOR_DELAY_NORMAL) == true
        android.util.Log.i(JOURNAL, "capteur ${capteur.name} ${if (branche) "branché" else "refusé"}")
    }

    fun debrancher() {
        if (!branche) return
        gestionnaire?.unregisterListener(this)
        branche = false
        lumiere.oublier()
    }

    override fun onSensorChanged(e: SensorEvent) {
        val lux = e.values.firstOrNull() ?: return
        // Instant de la mesure (même base que elapsedRealtime), celui de la livraison s'il est illisible.
        val maintenant = android.os.SystemClock.elapsedRealtime()
        val le = (e.timestamp / 1_000_000L).takeIf { it in (maintenant - 10_000L)..maintenant } ?: maintenant
        lumiere.mesure(lux, le)
        if (abs(lux - dernierJournal) >= max(1f, dernierJournal * 0.1f)) {
            dernierJournal = lux
            android.util.Log.i(JOURNAL, "lux ${"%.1f".format(java.util.Locale.ROOT, lux)} retenu ${lumiere.luxRetenu?.let { "%.1f".format(java.util.Locale.ROOT, it) } ?: "aucun"}")
        }
    }

    override fun onAccuracyChanged(s: Sensor?, precision: Int) {}

    companion object {
        const val JOURNAL = "JarvisLumiere"
    }
}
