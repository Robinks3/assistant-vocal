package assistant.vocal.jarvis

import kotlin.math.PI
import kotlin.math.exp
import kotlin.math.max
import kotlin.math.sin

/**
 * Respiration de la lumière de l'assistant sur l'accueil de la tablette (0.18.0), logique pure testée sur la
 * machine (SouffleTest). Elle reprend le rythme des particules de la 0.17.2 en plus sobre, sur le seul
 * point bleu : pendant la réponse, une impulsion à chaque mot qui s'ajoute à la réponse écrite (rythme de
 * la voix), et un rythme de syllabes quand aucun mot n'arrive depuis [SILENCE_S] (mode serveur, texte d'un
 * coup). À l'écoute, elle suit doucement le niveau du micro. En réflexion, une lente pulsation.
 * [avancer] rend l'intensité de 0 à 1, que la vue traduit en taille et en éclat.
 */
internal class Souffle {

    enum class Mode { REPOS, ECOUTE, REFLEXION, REPONSE }

    var mode = Mode.REPOS
        set(v) {
            if (v != field) {
                field = v
                depuisMot = if (v == Mode.REPONSE) 0f else 10f
                reserve = 0f
            }
        }
    /** Niveau du micro, de 0 à 1. */
    var niveau = 0f

    private var impulsion = 0f
    private var depuisMot = 10f
    private var reserve = 0f
    private var temps = 0f
    private var micro = 0f

    /** Un mot de la réponse vient de s'écrire ([force] de 0 à 1, selon sa longueur). */
    fun mot(force: Float) {
        if (mode != Mode.REPONSE) return
        val f = if (force.isNaN()) 0f else force.coerceIn(0f, 1f)
        impulsion = max(impulsion, 0.55f + 0.45f * f)
        depuisMot = 0f
    }

    /** Avance de [dt] secondes, rend l'intensité (0 à 1). */
    fun avancer(dt: Float): Float {
        val pas = if (dt.isNaN()) 0f else dt.coerceIn(0f, 0.5f)
        temps += pas
        impulsion *= exp(-pas / DECLIN_S)
        micro += (niveau.coerceIn(0f, 1f) - micro) * minOf(1f, pas / LISSAGE_S)
        return when (mode) {
            Mode.REPOS -> 0f
            Mode.ECOUTE -> (0.12f + 0.6f * micro).coerceIn(0f, 1f)
            Mode.REFLEXION -> 0.22f + 0.16f * sin(2f * PI.toFloat() * temps / PERIODE_REFLEXION_S)
            Mode.REPONSE -> {
                depuisMot += pas
                if (depuisMot > SILENCE_S) {
                    // Syllabes : un peu plus de cinq par seconde, cadence légèrement irrégulière.
                    reserve += pas * (CADENCE + 2f * sin(temps * 9.5f))
                    while (reserve >= 1f) {
                        impulsion = max(impulsion, 0.5f)
                        reserve -= 1f
                    }
                }
                max(0.15f, impulsion)
            }
        }
    }

    companion object {
        /** Une impulsion retombe de moitié en 0,12 s environ. */
        const val DECLIN_S = 0.18f
        const val LISSAGE_S = 0.12f
        const val SILENCE_S = 0.45f
        const val CADENCE = 5.5f
        const val PERIODE_REFLEXION_S = 1.6f
    }
}
