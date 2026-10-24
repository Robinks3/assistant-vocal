package assistant.vocal.jarvis

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.PorterDuff
import android.graphics.PorterDuffXfermode
import android.graphics.Shader
import android.os.SystemClock
import android.text.Layout
import android.text.StaticLayout
import android.text.TextPaint
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin

/**
 * Vues de l'accueil de la tablette (0.18.0). Tout y est dessiné à l'échelle de la maquette validée par
 * le propriétaire (1280 x 800 px, la moitié de l'écran de la tablette) : [CadreMaquette] place ses enfants en pixels
 * de maquette et donne l'échelle réelle (2 px réels par pixel de maquette sur la tablette). Couleurs : [Palette].
 */

/**
 * Cadre qui place ses enfants en pixels de maquette (gauche, haut, droite, bas, largeur, hauteur), à
 * l'échelle de sa taille réelle : min(largeur / 1280, hauteur / 800). Un enfant plus grand que le cadre
 * est coupé (la vue 3D déborde à droite, comme sur la maquette).
 */
internal class CadreMaquette(ctx: Context) : ViewGroup(ctx) {

    /**
     * Toucher pris par le cadre avant ses enfants (coordonnées du cadre) : vrai pour l'avaler. Sert à
     * arrêter l'écoute ou la réponse par un toucher n'importe où.
     */
    var capter: (Float, Float) -> Boolean = { _, _ -> false }
    /** Fin d'un toucher capté (doigt levé, ou geste annulé : [leve] faux). */
    var surCapte: (Float, Float, Boolean) -> Unit = { _, _, _ -> }
    /** Toucher qu'aucun enfant n'a pris : une zone noire de l'écran (0.18.1), ou null pour l'ignorer. */
    var surVide: (() -> Unit)? = null
    private var capte = false
    private var vide = false
    /** Un doigt est posé sur le cadre (0.24.0) : rien ne doit bouger dessous. */
    var doigtPose = false
        private set

    override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
        when (ev.actionMasked) {
            MotionEvent.ACTION_DOWN -> doigtPose = true
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> doigtPose = false
        }
        return super.dispatchTouchEvent(ev)
    }

    override fun onInterceptTouchEvent(ev: MotionEvent): Boolean {
        if (ev.actionMasked == MotionEvent.ACTION_DOWN) capte = capter(ev.x, ev.y)
        return capte
    }

    override fun onTouchEvent(ev: MotionEvent): Boolean {
        if (!capte) {
            // Arrivé ici sans enfant preneur : le toucher est tombé dans le noir.
            val s = surVide ?: return false
            when (ev.actionMasked) {
                MotionEvent.ACTION_DOWN -> vide = true
                MotionEvent.ACTION_UP -> { if (vide) s(); vide = false }
                MotionEvent.ACTION_CANCEL -> vide = false
            }
            return true
        }
        when (ev.actionMasked) {
            MotionEvent.ACTION_UP -> { capte = false; surCapte(ev.x, ev.y, true) }
            MotionEvent.ACTION_CANCEL -> { capte = false; surCapte(ev.x, ev.y, false) }
        }
        return true
    }

    class Place(
        val gauche: Float = LIBRE, val haut: Float = LIBRE, val droite: Float = LIBRE, val bas: Float = LIBRE,
        val largeur: Float = LIBRE, val hauteur: Float = LIBRE,
    ) : ViewGroup.LayoutParams(WRAP_CONTENT, WRAP_CONTENT)

    /** Pixels réels par pixel de maquette, estimé d'après l'écran avant la première mesure. */
    var echelle: Float = estimer(ctx)
        private set
    /**
     * Échelle donnée par le parent (0.24.0) : un bloc de la maquette (le bloc Musique) placé en pixels de maquette
     * relatifs à son propre coin, à l'échelle de l'écran entier et non de sa propre taille. 0 : échelle calculée.
     */
    var echelleImposee = 0f
        set(v) {
            if (v == field) return
            field = v
            requestLayout()
        }
    /** L'échelle change (première mesure, rotation) : tailles de texte à refaire. */
    var surEchelle: (Float) -> Unit = {}

    override fun onMeasure(largeurSpec: Int, hauteurSpec: Int) {
        val w = MeasureSpec.getSize(largeurSpec)
        val h = MeasureSpec.getSize(hauteurSpec)
        if (echelleImposee > 0f && abs(echelleImposee - echelle) > 0.001f) {
            echelle = echelleImposee
            surEchelle(echelle)
        } else if (echelleImposee <= 0f && w > 0 && h > 0) {
            val s = min(w / LARGEUR, h / HAUTEUR)
            if (abs(s - echelle) > 0.001f) {
                echelle = s
                surEchelle(s)
            }
        }
        val s = echelle
        for (i in 0 until childCount) {
            val c = getChildAt(i)
            if (c.visibility == GONE) continue
            val p = c.layoutParams as? Place ?: Place()
            c.measure(mesure(p.largeur, p.gauche, p.droite, w, s), mesure(p.hauteur, p.haut, p.bas, h, s))
        }
        setMeasuredDimension(w, h)
    }

    private fun mesure(taille: Float, debut: Float, fin: Float, total: Int, s: Float): Int = when {
        !taille.isNaN() -> MeasureSpec.makeMeasureSpec((taille * s).roundToInt(), MeasureSpec.EXACTLY)
        !debut.isNaN() && !fin.isNaN() -> MeasureSpec.makeMeasureSpec(max(0, total - ((debut + fin) * s).roundToInt()), MeasureSpec.EXACTLY)
        else -> MeasureSpec.makeMeasureSpec(
            max(0, total - (((if (debut.isNaN()) 0f else debut) + (if (fin.isNaN()) 0f else fin)) * s).roundToInt()),
            MeasureSpec.AT_MOST,
        )
    }

    override fun onLayout(changed: Boolean, l: Int, t: Int, r: Int, b: Int) {
        val w = r - l
        val h = b - t
        val s = echelle
        for (i in 0 until childCount) {
            val c = getChildAt(i)
            if (c.visibility == GONE) continue
            val p = c.layoutParams as? Place ?: Place()
            val x = when {
                !p.gauche.isNaN() -> (p.gauche * s).roundToInt()
                !p.droite.isNaN() -> w - (p.droite * s).roundToInt() - c.measuredWidth
                else -> 0
            }
            val y = when {
                !p.haut.isNaN() -> (p.haut * s).roundToInt()
                !p.bas.isNaN() -> h - (p.bas * s).roundToInt() - c.measuredHeight
                else -> 0
            }
            c.layout(x, y, x + c.measuredWidth, y + c.measuredHeight)
        }
    }

    override fun generateDefaultLayoutParams(): LayoutParams = Place()
    override fun checkLayoutParams(p: LayoutParams?): Boolean = p is Place
    override fun shouldDelayChildPressedState(): Boolean = false

    companion object {
        val LIBRE = Float.NaN
        const val LARGEUR = 1280f
        const val HAUTEUR = 800f

        /** Échelle d'après l'écran, quelle que soit son orientation au moment de la construction. */
        fun estimer(ctx: Context): Float {
            val m = ctx.resources.displayMetrics
            val l = max(m.widthPixels, m.heightPixels).toFloat()
            val h = min(m.widthPixels, m.heightPixels).toFloat()
            return if (l <= 0f || h <= 0f) 2f else min(l / LARGEUR, h / HAUTEUR)
        }
    }
}

/**
 * L'heure de l'accueil (revue de design et revue de faisabilité du 22/10) : Big Shoulders Display graisse 200
 * à 150 px de maquette, même taille et même place dans tous les états, gris éteint (usure OLED de ses fûts).
 * Chaque chiffre est centré dans une cellule de largeur fixe (la police n'a pas de chiffres tabulaires) :
 * les deux points ne sautent pas quand l'heure change.
 *
 * Les deux points sont le seul signe d'un projet d'inspiration : au repos de la teinte de l'heure, sans halo. À l'écoute
 * de la couleur d'un projet d'inspiration, 14 px de maquette qui pulsent avec la voix (jusqu'à 17 px au plus fort du
 * micro, revue des palettes du 22/10). En réflexion, ils clignotent lentement.
 * Pendant la réponse bleus, ils respirent au fil de la voix (Souffle), et redeviennent gris à la fin.
 */
internal class VueHeure(ctx: Context) : View(ctx) {

    enum class Points { REPOS, ECOUTE, REFLEXION, REPONSE }

    var echelle = CadreMaquette.estimer(ctx)
        set(v) {
            if (v == field) return
            field = v
            requestLayout()
            invalidate()
        }

    private val pChiffres = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = Polices.heure(ctx)
        color = Palette.heure
    }
    private val pPoint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val fm = Paint.FontMetrics()
    private val souffle = Souffle()

    private var heures = "--"
    private var minutes = "--"
    private var points = Points.REPOS
    private var niveau = 0f
    private var micro = 0f
    private var longueurParole = 0
    /** Mélange gris vers bleu des points (0 à 1), lissé. */
    private var bleu = 0f
    /** Couleur des points hors du repos (0.24.0) : celle de l'orbe, posée par l'accueil. */
    var couleurPoints = Palette.accentAssistant
        set(v) {
            if (v == field) return
            field = v
            invalidate()
        }
    private var dernierLe = 0L
    private var temps = 0f
    private val suivante = Runnable { invalidate() }

    init {
        importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO
    }

    /** Nouvelle heure : ne redessine que si elle change. */
    fun regler(hh: String, mm: String) {
        if (hh == heures && mm == minutes) return
        heures = hh
        minutes = mm
        invalidate()
    }

    /** État des points, niveau du micro (0 à 1), réponse écrite au fil de la voix. */
    fun reglerPoints(p: Points, niveauMicro: Float, parole: String) {
        val n = parole.length
        souffle.mode = if (p == Points.REPONSE) Souffle.Mode.REPONSE else Souffle.Mode.REPOS
        if (p == Points.REPONSE && n > longueurParole) souffle.mot(((n - longueurParole).coerceAtMost(12)) / 12f)
        longueurParole = n
        niveau = niveauMicro.coerceIn(0f, 1f)
        if (p != points) {
            points = p
            relancer()
        } else if (p != Points.REPOS) {
            relancer()
        }
    }

    private fun relancer() {
        removeCallbacks(suivante)
        invalidate()
    }

    /** Largeur d'une cellule de chiffre : la plus large des dix, à la taille courante. */
    private fun cellule(): Float = (0..9).maxOf { pChiffres.measureText(it.toString()) }

    override fun onMeasure(largeurSpec: Int, hauteurSpec: Int) {
        pChiffres.textSize = TAILLE * echelle
        val l = 4 * cellule() + (2 * ECART + POINT_MAX) * echelle
        setMeasuredDimension(l.roundToInt() + 1, (TAILLE * HAUTEUR_LIGNE * echelle).roundToInt())
    }

    override fun onDraw(c: Canvas) {
        val t = SystemClock.uptimeMillis()
        val dt = if (dernierLe == 0L) 0f else ((t - dernierLe) / 1000f).coerceIn(0f, 0.1f)
        dernierLe = t
        temps += dt
        val s = echelle
        pChiffres.textSize = TAILLE * s
        pChiffres.color = Palette.heure
        val h = TAILLE * HAUTEUR_LIGNE * s
        pChiffres.getFontMetrics(fm)
        // Ligne de hauteur 0,92 em comme sur la maquette : la ligne de base suit la demi-interligne CSS.
        val base = (h - (fm.descent - fm.ascent)) / 2f - fm.ascent
        val w = cellule()
        fun chiffres(texte: String, x0: Float) {
            for ((i, ch) in texte.withIndex()) {
                val g = ch.toString()
                c.drawText(g, x0 + i * w + (w - pChiffres.measureText(g)) / 2f, base, pChiffres)
            }
        }
        chiffres(heures, 0f)
        val cx = 2 * w + (ECART + POINT_MAX / 2f) * s
        chiffres(minutes, 2 * w + (2 * ECART + POINT_MAX) * s)

        // Points : couleur lissée (250 ms), taille selon l'état.
        val voulu = if (points == Points.REPOS) 0f else 1f
        bleu = if (voulu > bleu) min(voulu, bleu + dt / 0.25f) else max(voulu, bleu - dt / 0.35f)
        micro += (niveau - micro) * min(1f, dt / 0.12f)
        val i = souffle.avancer(dt)
        val diametre = when (points) {
            Points.ECOUTE -> POINT_ECOUTE + (POINT_MAX - POINT_ECOUTE) * micro
            Points.REPONSE -> POINT + 3f * i
            else -> POINT
        }
        val opacite = if (points == Points.REFLEXION) 0.35f + 0.65f * (0.5f + 0.5f * sin(2f * Math.PI.toFloat() * temps / CLIGNOTEMENT_S)) else 1f
        val couleur = Decor.melange(Palette.heure, couleurPoints, bleu)
        pPoint.color = Color.argb((255 * opacite).roundToInt(), Color.red(couleur), Color.green(couleur), Color.blue(couleur))
        val cy = h / 2f + DECALAGE * s / 2f
        val r = diametre * s / 2f
        val dy = (ECART_POINTS + POINT) * s / 2f
        c.drawCircle(cx, cy - dy, r, pPoint)
        c.drawCircle(cx, cy + dy, r, pPoint)
        // Images à suivre seulement quand les points vivent (écoute, réflexion, réponse) ou changent de couleur.
        if ((points != Points.REPOS || bleu > 0f) && isShown) postDelayed(suivante, 33L) else dernierLe = 0L
    }

    override fun onDetachedFromWindow() {
        super.onDetachedFromWindow()
        removeCallbacks(suivante)
    }

    companion object {
        /** Taille des chiffres en pixels de maquette (revue du 22/10). */
        const val TAILLE = 150f
        const val HAUTEUR_LIGNE = 0.92f
        /** Écart entre les chiffres et la colonne des points. */
        const val ECART = 10f
        /** Diamètre des points au repos, à l'écoute, et au plus fort du micro. */
        const val POINT = 11f
        const val POINT_ECOUTE = 14f
        const val POINT_MAX = 17f
        const val ECART_POINTS = 23f
        const val DECALAGE = 11f
        const val CLIGNOTEMENT_S = 1.6f
    }
}

/**
 * Bouton glyphe de la musique (précédent, lecture, pause, suivant) : un trait fin, sans fond ni contour,
 * dessiné d'après la maquette (traits de 1,6 sur une grille de 24). La zone de toucher fait au moins 48 dp.
 * 0.24.0 : traits de 2 (revue du contraste), moins et plus pour le volume de l'accueil.
 * 0.27.0 : croix du bouton Fermer de la maison en grand.
 */
internal class BoutonGlyphe(ctx: Context, forme: Forme, var tailleGlyphe: Float, couleur: Int) : View(ctx) {
    enum class Forme { PRECEDENT, LECTURE, PAUSE, SUIVANT, MOINS, PLUS, FERMER }

    var forme = forme
        set(v) {
            if (field != v) {
                field = v
                invalidate()
            }
        }
    var couleur = couleur
        set(v) {
            if (field != v) {
                field = v
                invalidate()
            }
        }
    var echelle = CadreMaquette.estimer(ctx)
        set(v) {
            field = v
            invalidate()
        }
    private val p = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }
    private val chemin = Path()

    init {
        isClickable = true
        isFocusable = true
    }

    override fun drawableStateChanged() {
        super.drawableStateChanged()
        invalidate()
    }

    override fun onDraw(c: Canvas) {
        val k = tailleGlyphe * echelle / 24f
        c.save()
        c.translate(width / 2f - 12f * k, height / 2f - 12f * k)
        c.scale(k, k)
        p.strokeWidth = 2f
        p.color = if (isPressed) Decor.melange(couleur, Palette.fond, 0.45f) else couleur
        chemin.rewind()
        when (forme) {
            Forme.PRECEDENT -> {
                chemin.moveTo(18f, 5f); chemin.lineTo(9f, 12f); chemin.lineTo(18f, 19f); chemin.close()
                chemin.moveTo(6f, 5f); chemin.lineTo(6f, 19f)
            }
            Forme.SUIVANT -> {
                chemin.moveTo(6f, 5f); chemin.lineTo(15f, 12f); chemin.lineTo(6f, 19f); chemin.close()
                chemin.moveTo(18f, 5f); chemin.lineTo(18f, 19f)
            }
            Forme.PAUSE -> {
                chemin.moveTo(8f, 5f); chemin.lineTo(8f, 19f)
                chemin.moveTo(16f, 5f); chemin.lineTo(16f, 19f)
            }
            Forme.LECTURE -> {
                chemin.moveTo(7f, 4.5f); chemin.lineTo(19f, 12f); chemin.lineTo(7f, 19.5f); chemin.close()
            }
            Forme.MOINS -> {
                chemin.moveTo(5f, 12f); chemin.lineTo(19f, 12f)
            }
            Forme.PLUS -> {
                chemin.moveTo(5f, 12f); chemin.lineTo(19f, 12f)
                chemin.moveTo(12f, 5f); chemin.lineTo(12f, 19f)
            }
            Forme.FERMER -> {
                chemin.moveTo(6f, 6f); chemin.lineTo(18f, 18f)
                chemin.moveTo(18f, 6f); chemin.lineTo(6f, 18f)
            }
        }
        c.drawPath(chemin, p)
        c.restore()
    }
}

/**
 * Texte coupé par un fondu à droite au lieu de points de suspension (revue du 22/10 : jamais de caractère de points de suspension).
 * Au plus [maxLignes] lignes. Quand le texte ne tient pas, la dernière ligne visible reprend tout le reste
 * sur une seule ligne, qui s'efface dans le noir sur le dernier sixième de la largeur. Les étendues de
 * style (couleur d'un mot) sont gardées.
 */
internal class TexteFondu(ctx: Context) : View(ctx) {

    val peinture = TextPaint(Paint.ANTI_ALIAS_FLAG)
    var texte: CharSequence = ""
        set(v) {
            if (v === field) return
            field = v
            mise = null
            requestLayout()
            invalidate()
        }
    /** Lignes alignées à droite (ligne de panne, couche de service). */
    var aDroite = false
        set(v) {
            field = v
            mise = null
            requestLayout()
        }

    fun police(t: android.graphics.Typeface) {
        if (peinture.typeface == t) return
        peinture.typeface = t
        mise = null
        requestLayout()
        invalidate()
    }
    var maxLignes = 1
        set(v) {
            field = v
            mise = null
            requestLayout()
        }
    /** Interligne en part de la hauteur naturelle de la police (1,12 em CSS / 1,22 em pour Instrument Sans). */
    var interligne = 1f
        set(v) {
            field = v
            mise = null
            requestLayout()
        }

    private var mise: StaticLayout? = null
    private var reste: StaticLayout? = null
    private val pFondu = Paint().apply { xfermode = PorterDuffXfermode(PorterDuff.Mode.DST_OUT) }

    fun taille(px: Float) {
        if (peinture.textSize == px) return
        peinture.textSize = px
        mise = null
        requestLayout()
        invalidate()
    }

    fun couleur(c: Int) {
        if (peinture.color == c) return
        peinture.color = c
        invalidate()
    }

    /** Nombre de lignes du texte sur [largeur] px à la taille [px] (pour réduire un texte qui ne tient pas). */
    fun lignes(px: Float, largeur: Int): Int {
        val p = TextPaint(peinture).apply { textSize = px }
        return StaticLayout.Builder.obtain(texte, 0, texte.length, p, max(1, largeur))
            .setAlignment(Layout.Alignment.ALIGN_NORMAL).setLineSpacing(0f, interligne).setIncludePad(false).build().lineCount
    }

    private fun preparer(largeur: Int) {
        val l = StaticLayout.Builder.obtain(texte, 0, texte.length, peinture, max(1, largeur))
            .setAlignment(if (aDroite) Layout.Alignment.ALIGN_OPPOSITE else Layout.Alignment.ALIGN_NORMAL)
            .setLineSpacing(0f, interligne).setIncludePad(false).build()
        mise = l
        reste = if (l.lineCount > maxLignes) {
            // Tout ce qui ne tient pas, sur une ligne, sans retour à la ligne.
            val debut = l.getLineStart(maxLignes - 1)
            val suite = android.text.SpannableStringBuilder(texte, debut, texte.length)
            for (i in suite.indices) if (suite[i] == '\n') suite.replace(i, i + 1, " ")
            StaticLayout.Builder.obtain(suite, 0, suite.length, peinture, 100_000)
                .setAlignment(Layout.Alignment.ALIGN_NORMAL).setIncludePad(false).setMaxLines(1).build()
        } else null
    }

    override fun onMeasure(largeurSpec: Int, hauteurSpec: Int) {
        val dispo = MeasureSpec.getSize(largeurSpec)
        val mode = MeasureSpec.getMode(largeurSpec)
        val l0 = if (mode == MeasureSpec.UNSPECIFIED) 100_000 else dispo
        if (mise == null || mise!!.width != l0) preparer(l0)
        val l = mise!!
        val n = min(l.lineCount, maxLignes)
        val largeurTexte = (0 until n).maxOfOrNull { l.getLineWidth(it) } ?: 0f
        var w = if (mode == MeasureSpec.EXACTLY) dispo else min(dispo, kotlin.math.ceil(largeurTexte).toInt() + 1)
        if (reste != null && mode != MeasureSpec.UNSPECIFIED) w = dispo
        // Aligné à droite dans une largeur plus étroite que l'offre : la mise en page suit la largeur finale.
        if (aDroite && w != l.width) preparer(max(1, w))
        val m = mise!!
        val h = if (n == 0) 0 else m.getLineBottom(min(m.lineCount, maxLignes) - 1)
        setMeasuredDimension(w, h)
    }

    override fun onDraw(c: Canvas) {
        val l = mise ?: return
        val r = reste
        if (r == null) {
            l.draw(c)
            return
        }
        // Lignes entières d'abord, puis la dernière, coupée en fondu sur le dernier sixième.
        val haut = l.getLineTop(maxLignes - 1)
        c.save()
        c.clipRect(0, 0, width, haut)
        l.draw(c)
        c.restore()
        val calque = c.saveLayer(0f, haut.toFloat(), width.toFloat(), height.toFloat(), null)
        c.save()
        c.translate(0f, haut.toFloat())
        c.clipRect(0, 0, width, height - haut)
        r.draw(c)
        c.restore()
        val debut = width * 5f / 6f
        pFondu.shader = LinearGradient(debut, 0f, width.toFloat(), 0f, 0x00000000, Palette.fond, Shader.TileMode.CLAMP)
        c.drawRect(debut, haut.toFloat(), width.toFloat(), height.toFloat(), pFondu)
        c.restoreToCount(calque)
    }
}
