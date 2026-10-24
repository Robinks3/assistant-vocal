package assistant.vocal.jarvis

import android.content.Context
import android.graphics.Typeface

/**
 * Polices de la tablette (0.18.0), sous licence OFL (dépôt google/fonts, licences dans assets/polices) :
 * Big Shoulders Display pour l'heure, Instrument Sans pour le texte, italique pour la transcription.
 *
 * 0.18.1 (revue de faisabilité) : instances statiques par graisse, tirées des polices variables par
 * fonttools (`varLib.instancer`) et rangées dans res/font, chargées une fois par `resources.getFont` puis
 * gardées. Plus de police variable ni de `sans-serif-thin`. Une police illisible retombe sur celles du
 * système, sans planter l'écran.
 */
internal object Polices {

    private val cache = HashMap<Int, Typeface>()

    /** Chiffres de l'heure : Big Shoulders Display, graisse 200 (fûts fins, moins d'usure OLED). */
    fun heure(ctx: Context): Typeface = charger(ctx, R.font.big_shoulders_display_200) { Typeface.create("sans-serif-light", Typeface.NORMAL) }

    /**
     * Grands chiffres du panneau Météo (0.20.0, maquette Meteo2) : Big Shoulders Display 300 pour la
     * température du moment, 400 pour les maximales des jours.
     */
    fun chiffres(ctx: Context, poids: Int): Typeface =
        if (poids >= 350) charger(ctx, R.font.big_shoulders_display_400) { Typeface.create("sans-serif", Typeface.NORMAL) }
        else charger(ctx, R.font.big_shoulders_display_300) { Typeface.create("sans-serif-light", Typeface.NORMAL) }

    /** Texte : Instrument Sans 400, 500 au-delà de 450, italique 400 pour la transcription. */
    fun texte(ctx: Context, poids: Int = 400, italique: Boolean = false): Typeface = when {
        italique -> charger(ctx, R.font.instrument_sans_italique_400) { Typeface.create("sans-serif", Typeface.ITALIC) }
        poids >= 450 -> charger(ctx, R.font.instrument_sans_500) { Typeface.create("sans-serif-medium", Typeface.NORMAL) }
        else -> charger(ctx, R.font.instrument_sans_400) { Typeface.create("sans-serif", Typeface.NORMAL) }
    }

    /** Équivalent Instrument Sans d'un nom de police du système (« sans-serif-medium », « sans-serif-light »...). */
    fun depuis(ctx: Context, police: String?): Typeface = texte(ctx, if (police != null && "medium" in police) 500 else 400)

    private fun charger(ctx: Context, id: Int, repli: () -> Typeface): Typeface {
        cache[id]?.let { return it }
        val t = try {
            ctx.resources.getFont(id)
        } catch (_: Exception) {
            repli()
        }
        cache[id] = t
        return t
    }
}
