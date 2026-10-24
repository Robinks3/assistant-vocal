package assistant.vocal.jarvis

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.Typeface
import android.graphics.drawable.Drawable
import android.graphics.drawable.GradientDrawable
import android.graphics.drawable.LayerDrawable
import android.graphics.drawable.RippleDrawable
import android.os.Build
import android.os.SystemClock
import android.util.TypedValue
import android.view.MotionEvent
import android.view.View
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.hypot
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin

/** Briques graphiques communes : fonds en relief, ombres douces, couleurs dérivées. */
internal object Decor {

    fun dp(ctx: Context, v: Float): Int =
        TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v, ctx.resources.displayMetrics).roundToInt()

    /** Mélange linéaire de deux couleurs, f = 0 donne a, f = 1 donne b. */
    fun melange(a: Int, b: Int, f: Float): Int {
        val g = 1f - f
        return Color.argb(
            (Color.alpha(a) * g + Color.alpha(b) * f).roundToInt(),
            (Color.red(a) * g + Color.red(b) * f).roundToInt(),
            (Color.green(a) * g + Color.green(b) * f).roundToInt(),
            (Color.blue(a) * g + Color.blue(b) * f).roundToInt(),
        )
    }

    fun eclaircir(c: Int, f: Float): Int = melange(c, Color.WHITE, f)
    fun assombrir(c: Int, f: Float): Int = melange(c, Color.BLACK, f)
    fun alpha(c: Int, a: Int): Int = Color.argb(a.coerceIn(0, 255), Color.red(c), Color.green(c), Color.blue(c))

    /** Rectangle arrondi en dégradé vertical, avec un liseré facultatif. */
    fun degrade(ctx: Context, haut: Int, bas: Int, rayonDp: Float, bord: Int? = null, bordDp: Float = 1f): GradientDrawable =
        GradientDrawable(GradientDrawable.Orientation.TOP_BOTTOM, intArrayOf(haut, bas)).apply {
            shape = GradientDrawable.RECTANGLE
            cornerRadius = dp(ctx, rayonDp).toFloat()
            if (bord != null) setStroke(max(1, dp(ctx, bordDp)), bord)
        }

    fun uni(ctx: Context, couleur: Int, rayonDp: Float): GradientDrawable =
        GradientDrawable().apply {
            shape = GradientDrawable.RECTANGLE
            cornerRadius = dp(ctx, rayonDp).toFloat()
            setColor(couleur)
        }

    fun fondCarte(ctx: Context, rayonDp: Float = 22f): GradientDrawable =
        degrade(ctx, Couleur.CARTE_HAUT, Couleur.CARTE_BAS, rayonDp, Couleur.CARTE_BORD)

    fun fondSousCarte(ctx: Context, rayonDp: Float = 14f, bord: Int = Couleur.CHAMP_BORD): GradientDrawable =
        degrade(ctx, Couleur.CHAMP_HAUT, Couleur.CHAMP_BAS, rayonDp, bord, if (bord == Couleur.CHAMP_BORD) 1f else 2f)

    fun fondCreux(ctx: Context, rayonDp: Float): GradientDrawable =
        degrade(ctx, Couleur.CREUX_HAUT, Couleur.CREUX_BAS, rayonDp, Couleur.CREUX_BORD)

    private fun masque(ctx: Context, rayonDp: Float) = uni(ctx, Color.WHITE, rayonDp)

    /** Bouton en relief : dégradé de la couleur, liseré plus clair, onde au toucher. */
    fun fondBouton(ctx: Context, couleur: Int, rayonDp: Float, contour: Int? = null): Drawable {
        val fond = degrade(
            ctx,
            eclaircir(couleur, 0.10f),
            assombrir(couleur, 0.10f),
            rayonDp,
            contour ?: eclaircir(couleur, 0.16f),
            if (contour != null) 2f else 1f,
        )
        return RippleDrawable(ColorStateList.valueOf(Palette.ondulation), fond, masque(ctx, rayonDp))
    }

    /** Segment non choisi : transparent sur son rail, seule l'onde apparaît au toucher. */
    fun fondNeutre(ctx: Context, rayonDp: Float): Drawable =
        RippleDrawable(ColorStateList.valueOf(Palette.ondulationDiscrete), null, masque(ctx, rayonDp))

    /** Ombre portée douce et noire (les ombres teintées grisaillent sur fond sombre). */
    fun relief(v: View, elevationDp: Float) {
        v.elevation = dp(v.context, elevationDp).toFloat()
        if (Build.VERSION.SDK_INT >= 28) {
            v.outlineAmbientShadowColor = Palette.ombre
            v.outlineSpotShadowColor = Palette.ombre
        }
    }

    /** Fond bleu nuit de l'écran ambiant (0.16.0), avec une lueur bleue derrière l'orbe. */
    fun fondNuit(ctx: Context): Drawable {
        val base = GradientDrawable(
            GradientDrawable.Orientation.TOP_BOTTOM,
            intArrayOf(Couleur.NUIT_HAUT, Couleur.NUIT, Couleur.NUIT_BAS),
        )
        val lueur = GradientDrawable().apply {
            gradientType = GradientDrawable.RADIAL_GRADIENT
            colors = intArrayOf(alpha(Couleur.BLEU, 34), alpha(Couleur.BLEU, 0))
            gradientRadius = dp(ctx, 520f).toFloat()
            setGradientCenter(0.5f, 0.45f)
        }
        return LayerDrawable(arrayOf(base, lueur))
    }

    /**
     * Carte de verre de l'écran ambiant : fond bleu nuit presque opaque, liseré fin et lueur sur le
     * bord gauche à la teinte de la voie (dictionnaire, Home Assistant, Claude, LLM local, sécurité).
     */
    fun carteVerre(ctx: Context, teinte: Int): Drawable {
        val rayon = dp(ctx, 22f).toFloat()
        val fond = GradientDrawable(
            GradientDrawable.Orientation.TOP_BOTTOM,
            intArrayOf(Palette.verreHaut, Palette.verreBas),
        ).apply {
            cornerRadius = rayon
            setStroke(max(1, dp(ctx, 1f)), alpha(teinte, 170))
        }
        val bord = GradientDrawable(GradientDrawable.Orientation.LEFT_RIGHT, intArrayOf(alpha(teinte, 80), alpha(teinte, 0))).apply {
            cornerRadii = floatArrayOf(rayon, rayon, 0f, 0f, 0f, 0f, rayon, rayon)
        }
        return LayerDrawable(arrayOf(fond, bord)).apply {
            setLayerWidth(1, dp(ctx, 46f))
            setLayerInset(1, dp(ctx, 1f), dp(ctx, 1f), 0, dp(ctx, 1f))
        }
    }

    /** Fond de l'écran : dégradé vertical plus une lueur bleutée en haut à gauche. */
    fun fondEcran(ctx: Context): Drawable {
        val base = GradientDrawable(
            GradientDrawable.Orientation.TOP_BOTTOM,
            intArrayOf(Couleur.FOND_HAUT, Couleur.FOND, Couleur.FOND_BAS),
        )
        val lueur = GradientDrawable().apply {
            gradientType = GradientDrawable.RADIAL_GRADIENT
            colors = intArrayOf(alpha(Couleur.ACCENT, 30), alpha(Couleur.ACCENT, 0))
            gradientRadius = dp(ctx, 560f).toFloat()
            setGradientCenter(0.08f, 0f)
        }
        return LayerDrawable(arrayOf(base, lueur))
    }
}

/** Rail vertical d'une étape du déroulé : trait qui relie les étapes et pastille d'état. */
internal class RailEtape(
    ctx: Context,
    private val couleur: Int,
    private val premier: Boolean,
    private val dernier: Boolean,
    private val enCours: Boolean,
    private val yPointDp: Float,
) : View(ctx) {

    private val densite = resources.displayMetrics.density
    private val pTrait = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        color = Couleur.TRAIT
        strokeWidth = 2f * densite
        strokeCap = Paint.Cap.ROUND
    }
    private val pPoint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val pHalo = Paint(Paint.ANTI_ALIAS_FLAG)

    override fun onDraw(c: Canvas) {
        val cx = width / 2f
        val y = yPointDp * densite
        val r = 6f * densite
        val ecart = 4f * densite
        if (!premier) c.drawLine(cx, 0f, cx, y - r - ecart, pTrait)
        if (!dernier) c.drawLine(cx, y + r + ecart, cx, height.toFloat(), pTrait)
        if (enCours) {
            pHalo.color = Decor.alpha(couleur, 70)
            c.drawCircle(cx, y, r * 1.9f, pHalo)
        }
        pPoint.shader = LinearGradient(
            0f, y - r, 0f, y + r,
            Decor.eclaircir(couleur, 0.25f), Decor.assombrir(couleur, 0.15f),
            Shader.TileMode.CLAMP,
        )
        c.drawCircle(cx, y, r, pPoint)
    }
}
