package assistant.vocal.jarvis

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Typeface
import android.util.TypedValue
import android.view.View
import kotlin.math.PI
import kotlin.math.cos
import kotlin.math.sin

/**
 * Écran toujours allumé de la tablette (0.17.2, régime AOD de Veille) : quand personne n'est là de jour,
 * seules trois informations restent, en gris sombre et en trait fin, sans bulle, contour ni fond.
 * L'heure (grande, graisse fine), la météo (température et petite icône au trait), le nombre de
 * lumières allumées (petite ligne). Aucun texte gras, aucune couleur saturée, aucun aplat.
 *
 * Le bloc change de zone toutes les 3 min (Veille.placeAodX et placeAodY, grille de 3 sur 3 sans le
 * centre où reste le point de l'orbe), avec un fondu lent (Veille.opaciteAod). Le décalage global d'un
 * pixel par minute s'y ajoute (toute l'interface). La vue ne se redessine qu'au changement de minute ou
 * de contenu et pendant les fondus (15 images par seconde), jamais quand elle est cachée.
 */
internal class VueAod(ctx: Context) : View(ctx) {

    private val densite = resources.displayMetrics.density
    private fun sp(v: Float) = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP, v, resources.displayMetrics)

    private val pHeure = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = Polices.heure(ctx)
        color = Veille.GRIS_AOD_HEURE
        textSize = sp(68f)
        letterSpacing = -0.01f
    }
    private val pTexte = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = Typeface.create("sans-serif-light", Typeface.NORMAL)
        color = Veille.GRIS_AOD_TEXTE
        textSize = sp(20f)
    }
    private val pPetit = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = Typeface.create("sans-serif-light", Typeface.NORMAL)
        color = Veille.GRIS_AOD_TEXTE
        textSize = sp(15.5f)
    }
    private val pTrait = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
        strokeWidth = 1.2f * densite
        color = Veille.GRIS_AOD_TEXTE
    }
    private val chemin = Path()
    private val ovale = RectF()
    private val fm = Paint.FontMetrics()
    /** Prochaine image (fondu ou zone suivante) : une seule en attente à la fois. */
    private val rafraichir = Runnable { invalidate() }

    private var heure = ""
    private var temperature = ""
    private var code = ""
    private var lumieres = ""

    // Mise en page du bloc, recalculée seulement quand le contenu change.
    private var largeurBloc = 0f
    private var hauteurBloc = 0f
    private var baseHeure = 0f
    private var hautMeteo = 0f
    private var hauteurMeteo = 0f
    private var baseMeteo = 0f
    private var baseLumieres = 0f
    private val icone = 24f * densite
    private val ecartIcone = 9f * densite

    /** Opacité d'ensemble (0 : vivant ou noir, 1 : AOD), posée par l'écran selon Veille. */
    var opacite = 0f
        set(v) {
            val o = v.coerceIn(0f, 1f)
            if (o == field) return
            val reprise = field <= 0f && o > 0f
            field = o
            alpha = o
            visibility = if (o > 0f) VISIBLE else INVISIBLE
            if (reprise) invalidate()
        }

    init {
        alpha = 0f
        visibility = INVISIBLE
        importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO
    }

    /** Contenu du bloc. [lumieres] : ligne déjà rédigée, vide si la maison n'est pas encore lue. */
    fun regler(heure: String, temperature: String, code: String, lumieres: String) {
        if (heure == this.heure && temperature == this.temperature && code == this.code && lumieres == this.lumieres) return
        this.heure = heure
        this.temperature = temperature
        this.code = code
        this.lumieres = lumieres
        mesurer()
        if (opacite > 0f) invalidate()
    }

    private fun mesurer() {
        var y = 0f
        var l = 0f
        if (heure.isNotEmpty()) {
            pHeure.getFontMetrics(fm)
            baseHeure = -fm.ascent * 0.92f
            y = baseHeure + fm.descent * 0.6f
            l = pHeure.measureText(heure)
        }
        if (temperature.isNotEmpty()) {
            pTexte.getFontMetrics(fm)
            val hTexte = fm.descent - fm.ascent
            val h = maxOf(icone, hTexte)
            hauteurMeteo = h
            hautMeteo = y + 6f * densite
            baseMeteo = hautMeteo + (h - hTexte) / 2f - fm.ascent
            y = hautMeteo + h
            l = maxOf(l, icone + ecartIcone + pTexte.measureText(temperature))
        }
        if (lumieres.isNotEmpty()) {
            pPetit.getFontMetrics(fm)
            baseLumieres = y + 8f * densite - fm.ascent
            y = baseLumieres + fm.descent
            l = maxOf(l, pPetit.measureText(lumieres))
        }
        largeurBloc = l
        hauteurBloc = y
    }

    override fun onDraw(c: Canvas) {
        if (width == 0 || height == 0 || largeurBloc <= 0f || opacite <= 0f) return
        val instant = System.currentTimeMillis()
        val periode = Veille.periodeAod(instant)
        val marge = Veille.MARGE_AOD_DP * densite
        val x = Veille.placeAodX(periode, width.toFloat(), largeurBloc, marge)
        val y = Veille.placeAodY(periode, height.toFloat(), hauteurBloc, marge)
        val fondu = (255 * Veille.opaciteAod(instant)).toInt().coerceIn(0, 255)
        if (fondu > 0) {
            pHeure.alpha = fondu
            pTexte.alpha = fondu
            pPetit.alpha = fondu
            pTrait.alpha = fondu
            if (heure.isNotEmpty()) c.drawText(heure, x, y + baseHeure, pHeure)
            if (temperature.isNotEmpty()) {
                dessinerIcone(c, x + icone / 2f, y + hautMeteo + hauteurMeteo / 2f, icone)
                c.drawText(temperature, x + icone + ecartIcone, y + baseMeteo, pTexte)
            }
            if (lumieres.isNotEmpty()) c.drawText(lumieres, x, y + baseLumieres, pPetit)
        }
        // Prochaine image : pendant les fondus seulement. Le changement de minute passe par regler().
        removeCallbacks(rafraichir)
        if (isShown) postDelayed(rafraichir, Veille.attenteAod(instant))
    }

    override fun onDetachedFromWindow() {
        super.onDetachedFromWindow()
        removeCallbacks(rafraichir)
    }

    /** Retour au premier plan : la place et le fondu sont recalculés tout de suite. */
    override fun onVisibilityAggregated(isVisible: Boolean) {
        super.onVisibilityAggregated(isVisible)
        if (isVisible) reprendreRendu()
    }

    /** Relance franche (0.17.3, écran rallumé ou activité reprise) : l'image en attente est refaite tout de suite. */
    fun reprendreRendu() {
        removeCallbacks(rafraichir)
        if (opacite > 0f) invalidate()
    }

    /** Croissant de lune au trait, centré en (0, 0) : un disque moins un autre, construit une seule fois. */
    private val croissant: Path by lazy {
        val r = icone * 0.34f
        val plein = Path().apply { addCircle(0f, 0f, r, Path.Direction.CW) }
        val ombre = Path().apply { addCircle(icone * 0.18f, -icone * 0.14f, icone * 0.28f, Path.Direction.CW) }
        Path().apply { op(plein, ombre, Path.Op.DIFFERENCE) }
    }

    /** Icône météo au trait (soleil, lune, nuage, pluie, neige, orage, brouillard), d'après l'état HA. */
    private fun dessinerIcone(c: Canvas, cx: Float, cy: Float, s: Float) {
        val p = pTrait
        if (code == "clear-night") {
            c.save()
            c.translate(cx, cy)
            c.drawPath(croissant, p)
            c.restore()
            return
        }
        val nuage = code.isNotEmpty() && code != "sunny"
        val soleil = !nuage || code == "partlycloudy" || code == "windy-variant"
        if (nuage) {
            // Nuage au trait : base droite, deux petites bosses et une grande.
            val b = cy + s * 0.12f
            val g = cx - s * 0.34f
            val d = cx + s * 0.38f
            chemin.rewind()
            chemin.moveTo(g + s * 0.12f, b)
            chemin.lineTo(d - s * 0.12f, b)
            ovale.set(d - s * 0.24f, b - s * 0.24f, d, b)
            chemin.arcTo(ovale, 90f, -180f, false)
            ovale.set(cx - s * 0.2f, b - s * 0.42f, cx + s * 0.22f, b)
            chemin.arcTo(ovale, -15f, -165f, false)
            ovale.set(g, b - s * 0.24f, g + s * 0.24f, b)
            chemin.arcTo(ovale, -90f, -180f, false)
            chemin.close()
        }
        if (soleil) {
            val x = if (nuage) cx - s * 0.16f else cx
            val y = if (nuage) cy - s * 0.16f else cy
            val r = if (nuage) s * 0.13f else s * 0.18f
            // Le soleil passe derrière le nuage : ses traits ne le traversent pas.
            c.save()
            if (nuage) c.clipOutPath(chemin)
            c.drawCircle(x, y, r, p)
            for (i in 0 until 8) {
                val a = i * PI / 4
                val r1 = r + s * 0.07f
                val r2 = r + s * 0.14f
                c.drawLine(
                    x + (r1 * cos(a)).toFloat(), y + (r1 * sin(a)).toFloat(),
                    x + (r2 * cos(a)).toFloat(), y + (r2 * sin(a)).toFloat(), p,
                )
            }
            c.restore()
        }
        if (!nuage) return
        c.drawPath(chemin, p)
        val bas = cy + s * 0.22f
        when {
            code == "rainy" || code == "pouring" || code == "lightning-rainy" || code == "snowy-rainy" ->
                for (k in 0 until 3) {
                    val x = cx - s * 0.16f + k * s * 0.16f
                    c.drawLine(x, bas, x - s * 0.05f, bas + s * 0.16f, p)
                }
            code == "snowy" || code == "hail" ->
                for (k in 0 until 3) c.drawCircle(cx - s * 0.16f + k * s * 0.16f, bas + s * 0.08f, s * 0.025f, p)
            code == "fog" -> {
                c.drawLine(cx - s * 0.3f, bas + s * 0.03f, cx + s * 0.3f, bas + s * 0.03f, p)
                c.drawLine(cx - s * 0.22f, bas + s * 0.13f, cx + s * 0.26f, bas + s * 0.13f, p)
            }
        }
        if (code.startsWith("lightning")) {
            chemin.rewind()
            chemin.moveTo(cx + s * 0.04f, bas - s * 0.02f)
            chemin.lineTo(cx - s * 0.06f, bas + s * 0.12f)
            chemin.lineTo(cx + s * 0.02f, bas + s * 0.12f)
            chemin.lineTo(cx - s * 0.05f, bas + s * 0.26f)
            c.drawPath(chemin, p)
        }
    }
}
