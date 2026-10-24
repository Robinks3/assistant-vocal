package assistant.vocal.jarvis

import android.content.Context
import android.graphics.Canvas
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.text.TextPaint
import android.view.MotionEvent
import android.view.View
import java.time.LocalDate
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Graphes des onglets de la santé (0.22.0, maquettes relues), dessinés au Canvas en pixels de maquette fois
 * [echelle]. Règles de la revue : barres qui partent de zéro, gris des données en `colonne`, vert (`sante`)
 * réservé à ce qui est actuel, jour ou semaine en cours en barre creuse, jour sans donnée en trou marqué « non
 * enregistré », repères d'échelle neutres. Glisser lit une valeur (curseur et étiquette), lever ouvre le jour.
 */
internal abstract class GrapheSante(ctx: Context) : View(ctx) {
    var echelle = CadreMaquette.estimer(ctx)
        set(v) {
            field = v
            requestLayout()
            invalidate()
        }
    protected val plein = Paint(Paint.ANTI_ALIAS_FLAG)
    protected val trait = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeJoin = Paint.Join.ROUND
        strokeCap = Paint.Cap.ROUND
    }
    protected val tirets = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
    protected val pTexte = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { typeface = Polices.texte(ctx) }
    protected val r = RectF()
    protected val fm = Paint.FontMetrics()

    /** Ligne de base d'un texte de [px] dont le haut de ligne CSS (interligne 1,22) est en [haut]. */
    protected fun base(haut: Float, px: Float): Float {
        pTexte.textSize = px
        pTexte.getFontMetrics(fm)
        return haut + (1.22f * px - (fm.descent - fm.ascent)) / 2f - fm.ascent
    }

    protected fun texte(t: String, x: Float, haut: Float, px: Float, couleur: Int, align: Paint.Align = Paint.Align.LEFT) {
        pTexte.textAlign = align
        pTexte.color = couleur
        c?.drawText(t, x, base(haut, px), pTexte)
    }

    protected fun alpha(couleur: Int, a: Float): Int = ((255 * a).toInt().coerceIn(0, 255) shl 24) or (couleur and 0xFFFFFF)

    protected fun pointilles(s: Float) {
        tirets.pathEffect = DashPathEffect(floatArrayOf(3f * s, 4f * s), 0f)
        tirets.strokeWidth = max(1f, s * 0.6f)
    }

    private var c: Canvas? = null

    final override fun onDraw(canvas: Canvas) {
        c = canvas
        dessiner(canvas, echelle)
        c = null
    }

    protected abstract fun dessiner(c: Canvas, s: Float)

    /** Oublie la lecture au doigt en cours (fondu de masquage, panneau vidé). */
    open fun relacher() {}
}

/**
 * Barres par jour ou par semaine. Deux gabarits : [SEPT] (Aujourd'hui et vue Jour : sept barres larges, valeur
 * au-dessus de chacune, jour et numéro dessous) et [PERIODE] (Tendances : repères à gauche, barres fines, dates
 * espacées dessous, point sous l'axe les jours de séance).
 */
internal class BarresSante(ctx: Context) : GrapheSante(ctx) {

    class Barre(
        val date: LocalDate,
        val valeur: Double?,
        /** Part du bas de la barre en teinte santé (sommeil profond), null sinon. */
        val part: Double? = null,
        val enCours: Boolean = false,
        val seance: Boolean = false,
        /** Barre mise en avant (la dernière nuit) : teinte santé, valeur en texte principal. */
        val enAvant: Boolean = false,
        /** Valeur écrite au-dessus (gabarit SEPT), vide pour rien. */
        val texteValeur: String = "",
        /** Lecture au doigt (« Ven. 16 octobre, 11 420 pas »). */
        val lecture: String = "",
    )

    enum class Gabarit { SEPT, PERIODE }

    var gabarit = Gabarit.SEPT
    var barres: List<Barre> = emptyList()
        set(v) {
            field = v
            lu = -1
            invalidate()
        }
    var reperes: List<Pair<Double, String>> = emptyList()
    /** Étiquettes des dates (gabarit PERIODE) : indice de la barre et texte, la dernière en texte principal. */
    var dates: List<Pair<Int, String>> = emptyList()
    /** Lever le doigt sur une barre ouvre ce jour (null : pas de vue Jour, granularité par semaine). */
    var surJour: ((LocalDate) -> Unit)? = null

    private var lu = -1

    override fun onMeasure(l: Int, h: Int) {
        val s = echelle
        val hauteur = if (gabarit == Gabarit.SEPT) 116f + 8f + 16f * 1.22f else 104f + 14f + 14f * 1.22f
        setMeasuredDimension(MeasureSpec.getSize(l), (hauteur * s).roundToInt())
    }

    private fun zone(s: Float): RectF {
        val g = if (gabarit == Gabarit.SEPT) 0f else 48f * s
        return RectF(g, 0f, width.toFloat(), (if (gabarit == Gabarit.SEPT) 116f else 104f) * s)
    }

    private fun place(i: Int, s: Float): Pair<Float, Float> {
        val z = zone(s)
        val n = max(1, barres.size)
        return if (gabarit == Gabarit.SEPT) {
            val ecart = 12f * s
            val l = (z.width() - ecart * (n - 1)) / n
            (z.left + i * (l + ecart)) to l
        } else {
            val pas = z.width() / n
            val l = max(2f * s, pas * 0.72f)
            (z.left + i * pas + (pas - l) / 2f) to l
        }
    }

    override fun dessiner(c: Canvas, s: Float) {
        if (barres.isEmpty()) return
        val z = zone(s)
        // 74 px au plus en gabarit SEPT (maquette) : la valeur et « en cours » au-dessus ne touchent jamais le titre.
        val haut = if (gabarit == Gabarit.SEPT) 74f * s else 92f * s
        val vmax = max(barres.mapNotNull { it.valeur }.maxOrNull() ?: 0.0, reperes.maxOfOrNull { it.first } ?: 0.0).takeIf { it > 0 } ?: return
        fun y(v: Double) = (z.bottom - (v / vmax * haut)).toFloat()
        // Repères neutres (5 000 et 10 000 pas, 6 h et 8 h).
        pointilles(s)
        tirets.color = Palette.texte3
        for ((v, nom) in reperes) {
            val yy = y(v)
            c.drawLine(z.left, yy, z.right, yy, tirets)
            texte(nom, 40f * s, yy - 1.22f * 14f * s / 2f, 14f * s, Palette.texte3, Paint.Align.RIGHT)
        }
        for ((i, b) in barres.withIndex()) {
            val (x, l) = place(i, s)
            val v = b.valeur
            if (v == null) {
                // Trou marqué, jamais une barre à zéro.
                pointilles(s)
                tirets.color = Palette.texte3
                if (gabarit == Gabarit.SEPT) {
                    c.drawLine(x, z.bottom - 1f, x + l, z.bottom - 1f, tirets)
                    texte("non", x + l / 2f, z.bottom - (6f + 2 * 14f * 1.3f) * s, 14f * s, Palette.texte3, Paint.Align.CENTER)
                    texte("enregistré", x + l / 2f, z.bottom - (6f + 14f * 1.3f) * s, 14f * s, Palette.texte3, Paint.Align.CENTER)
                } else if (!b.enCours) {
                    val cx = x + l / 2f
                    c.drawLine(cx, 20f * s, cx, z.bottom, tirets)
                }
                continue
            }
            val h = max(4f * s, z.bottom - y(v))
            r.set(x, z.bottom - h, x + l, z.bottom)
            val rayon = 3f * s
            if (b.enCours) {
                trait.color = Palette.sante
                trait.strokeWidth = 1.5f * s
                r.inset(0.75f * s, 0.75f * s)
                c.drawRoundRect(r, rayon, rayon, trait)
            } else {
                plein.color = if (b.enAvant) Palette.sante else Palette.colonne
                c.drawRoundRect(r, rayon, rayon, plein)
                b.part?.let { p ->
                    val hp = min(h, max(2f * s, (p / vmax * haut).toFloat()))
                    plein.color = Palette.sante
                    r.set(x, z.bottom - hp, x + l, z.bottom)
                    c.drawRoundRect(r, rayon, rayon, plein)
                }
            }
            if (gabarit == Gabarit.SEPT && b.texteValeur.isNotEmpty()) {
                val coul = if (b.enAvant || b.enCours) Palette.texte1 else Palette.texte3
                texte(b.texteValeur, x + l / 2f, z.bottom - h - (5f + 15f * 1.22f) * s, 15f * s, coul, Paint.Align.CENTER)
                if (b.enCours) texte("en cours", x + l / 2f, z.bottom - h - (5f + 2 * 15f * 1.22f) * s, 14f * s, Palette.texte3, Paint.Align.CENTER)
            }
        }
        // Jours non enregistrés du gabarit PERIODE : une seule étiquette en haut.
        if (gabarit == Gabarit.PERIODE) {
            val trou = barres.indexOfFirst { it.valeur == null && !it.enCours }
            if (trou >= 0) {
                val (x, l) = place(trou, s)
                texte("non enregistré", x + l / 2f, 0f, 14f * s, Palette.texte3, Paint.Align.CENTER)
            }
            // Axe, points des jours de séance, dates.
            plein.color = Palette.filet
            c.drawRect(z.left, z.bottom, z.right, z.bottom + max(1f, s * 0.5f), plein)
            for ((i, b) in barres.withIndex()) {
                if (!b.seance) continue
                val (x, l) = place(i, s)
                plein.color = Palette.texte2
                c.drawCircle(x + l / 2f, z.bottom + 7.5f * s, 2.5f * s, plein)
            }
            for ((k, d) in dates.withIndex()) {
                val (x, l) = place(d.first, s)
                val dernier = k == dates.size - 1 && d.first == barres.size - 1
                texte(d.second, x + l / 2f, z.bottom + 13f * s, 14f * s, if (dernier) Palette.texte1 else Palette.texte3, Paint.Align.CENTER)
            }
        } else {
            for ((i, b) in barres.withIndex()) {
                val (x, l) = place(i, s)
                val dernier = i == barres.size - 1
                texte(SanteHisto.initialeNumero(b.date), x + l / 2f, z.bottom + 8f * s, 16f * s, if (dernier) Palette.texte1 else Palette.texte3, Paint.Align.CENTER)
            }
        }
        // Lecture au doigt.
        barres.getOrNull(lu)?.takeIf { it.lecture.isNotEmpty() }?.let { b ->
            val (x, l) = place(lu, s)
            val cx = x + l / 2f
            plein.color = Palette.texte2
            c.drawRect(cx - 0.5f * s, 16f * s, cx + 0.5f * s, z.bottom, plein)
            pTexte.textSize = 14f * s
            val lt = pTexte.measureText(b.lecture) + 16f * s
            val gauche = (cx - lt / 2f).coerceIn(0f, width - lt)
            plein.color = Palette.surface
            r.set(gauche, 0f, gauche + lt, 20f * s)
            c.drawRoundRect(r, 4f * s, 4f * s, plein)
            texte(b.lecture, gauche + lt / 2f, 1f * s, 14f * s, Palette.texte1, Paint.Align.CENTER)
        }
    }

    override fun relacher() {
        lu = -1
        invalidate()
    }

    override fun onTouchEvent(ev: MotionEvent): Boolean {
        if (barres.isEmpty()) {
            lu = -1
            return false
        }
        val s = echelle
        val i = barres.indices.minByOrNull { k -> val (x, l) = place(k, s); abs(x + l / 2f - ev.x) } ?: return false
        when (ev.actionMasked) {
            MotionEvent.ACTION_DOWN, MotionEvent.ACTION_MOVE -> {
                parent?.requestDisallowInterceptTouchEvent(true)
                if (i != lu) {
                    lu = i
                    invalidate()
                }
            }
            MotionEvent.ACTION_UP -> {
                val b = barres.getOrNull(lu)
                lu = -1
                invalidate()
                if (b != null && b.valeur != null) surJour?.invoke(b.date)
                performClick()
            }
            MotionEvent.ACTION_CANCEL -> {
                lu = -1
                invalidate()
            }
        }
        return true
    }

    override fun performClick(): Boolean = super.performClick()
}

/** Courbes de la carte Cœur de Tendances : séries par jour, trous aux jours sans donnée, repères 50 et 70. */
internal class LignesSante(ctx: Context) : GrapheSante(ctx) {
    class Serie(val valeurs: List<Double?>, val couleur: Int)

    var series: List<Serie> = emptyList()
        set(v) {
            field = v
            lu = -1
            invalidate()
        }
    var reperes: List<Pair<Double, String>> = emptyList()
    var dates: List<Pair<Int, String>> = emptyList()
    var jours: List<LocalDate> = emptyList()
    var lectures: List<String> = emptyList()
    var surJour: ((LocalDate) -> Unit)? = null
    private var lu = -1

    override fun onMeasure(l: Int, h: Int) {
        setMeasuredDimension(MeasureSpec.getSize(l), ((104f + 14f + 14f * 1.22f) * echelle).roundToInt())
    }

    private fun n() = series.maxOfOrNull { it.valeurs.size } ?: 0

    private fun x(i: Int, s: Float): Float {
        val l = width - 48f * s
        val n = max(1, n())
        return 48f * s + (i + 0.5f) * l / n
    }

    override fun dessiner(c: Canvas, s: Float) {
        val n = n()
        if (n == 0) return
        val tout = series.flatMap { it.valeurs.filterNotNull() } + reperes.map { it.first }
        val vmin = (tout.minOrNull() ?: return) - 5
        val vmax = (tout.maxOrNull() ?: return) + 5
        val bas = 104f * s
        fun y(v: Double) = (bas - 8f * s - (v - vmin) / (vmax - vmin) * (bas - 16f * s)).toFloat()
        pointilles(s)
        tirets.color = Palette.texte3
        for ((v, nom) in reperes) {
            val yy = y(v)
            c.drawLine(48f * s, yy, width.toFloat(), yy, tirets)
            texte(nom, 40f * s, yy - 1.22f * 14f * s / 2f, 14f * s, Palette.texte3, Paint.Align.RIGHT)
        }
        plein.color = Palette.filet
        c.drawRect(48f * s, bas, width.toFloat(), bas + max(1f, s * 0.5f), plein)
        trait.strokeWidth = 2f * s
        for (se in series) {
            trait.color = se.couleur
            val p = Path()
            var ouvert = false
            for ((i, v) in se.valeurs.withIndex()) {
                if (v == null) {
                    ouvert = false
                    continue
                }
                if (!ouvert) p.moveTo(x(i, s), y(v)) else p.lineTo(x(i, s), y(v))
                ouvert = true
                // Valeur isolée entre deux trous : un point, sans quoi elle ne se verrait pas.
                if (se.valeurs.getOrNull(i - 1) == null && se.valeurs.getOrNull(i + 1) == null) {
                    plein.color = se.couleur
                    c.drawCircle(x(i, s), y(v), 2.5f * s, plein)
                }
            }
            c.drawPath(p, trait)
        }
        for ((k, d) in dates.withIndex()) {
            val dernier = k == dates.size - 1 && d.first == n - 1
            texte(d.second, x(d.first, s), bas + 13f * s, 14f * s, if (dernier) Palette.texte1 else Palette.texte3, Paint.Align.CENTER)
        }
        lectures.getOrNull(lu)?.takeIf { it.isNotEmpty() }?.let { t ->
            val cx = x(lu, s)
            plein.color = Palette.texte2
            c.drawRect(cx - 0.5f * s, 16f * s, cx + 0.5f * s, bas, plein)
            pTexte.textSize = 14f * s
            val lt = pTexte.measureText(t) + 16f * s
            val gauche = (cx - lt / 2f).coerceIn(0f, width - lt)
            plein.color = Palette.surface
            r.set(gauche, 0f, gauche + lt, 20f * s)
            c.drawRoundRect(r, 4f * s, 4f * s, plein)
            texte(t, gauche + lt / 2f, 1f * s, 14f * s, Palette.texte1, Paint.Align.CENTER)
        }
    }

    override fun relacher() {
        lu = -1
        invalidate()
    }

    override fun onTouchEvent(ev: MotionEvent): Boolean {
        val n = n()
        if (n == 0) {
            lu = -1
            return false
        }
        val s = echelle
        val i = ((ev.x - 48f * s) / ((width - 48f * s) / n)).toInt().coerceIn(0, n - 1)
        when (ev.actionMasked) {
            MotionEvent.ACTION_DOWN, MotionEvent.ACTION_MOVE -> {
                parent?.requestDisallowInterceptTouchEvent(true)
                if (i != lu) {
                    lu = i
                    invalidate()
                }
            }
            MotionEvent.ACTION_UP -> {
                // Un jour sans aucune valeur ne s'ouvre pas.
                val k = lu
                val d = jours.getOrNull(k)?.takeIf { series.any { se -> se.valeurs.getOrNull(k) != null } }
                lu = -1
                invalidate()
                if (d != null) surJour?.invoke(d)
                performClick()
            }
            MotionEvent.ACTION_CANCEL -> {
                lu = -1
                invalidate()
            }
        }
        return true
    }

    override fun performClick(): Boolean = super.performClick()
}

/**
 * Charge d'entraînement par semaine (ou par mois à 1 an) : barres empilées par sport (même vert, deux
 * opacités), charge au-dessus et heures dessous en libellé secondaire, semaine en cours en barre creuse.
 */
internal class ChargeSante(ctx: Context) : GrapheSante(ctx) {
    class Groupe(val parts: List<Pair<Double, Float>>, val charge: Int?, val heures: String, val date: String, val enCours: Boolean)

    var groupes: List<Groupe> = emptyList()
        set(v) {
            field = v
            invalidate()
        }

    override fun onMeasure(l: Int, h: Int) {
        setMeasuredDimension(MeasureSpec.getSize(l), ((104f + 14f + 14f * 1.22f) * echelle).roundToInt())
    }

    override fun dessiner(c: Canvas, s: Float) {
        if (groupes.isEmpty()) return
        val n = groupes.size
        val gauche = 48f * s
        val largeur = width - gauche
        val pas = largeur / n
        val l = min(pas * 0.82f, 92f * s)
        val bas = 104f * s
        val vmax = groupes.maxOf { g -> g.parts.sumOf { it.first } }.takeIf { it > 0 } ?: 1.0
        val haut = 62f * s
        // Au-delà de 6 groupes (3 mois, 1 an) : la charge seule au-dessus, une date sur quatre (ou trois) dessous.
        val serre = n > 6
        val dates = if (serre) indicesDates(n, if (n > 12) 4 else 3).toSet() else (0 until n).toSet()
        for ((i, g) in groupes.withIndex()) {
            val x = gauche + i * pas + (pas - l) / 2f
            val total = g.parts.sumOf { it.first }
            val h = max(4f * s, (total / vmax * haut).toFloat())
            if (g.enCours) {
                trait.color = Palette.sante
                trait.strokeWidth = 1.5f * s
                r.set(x + 0.75f * s, bas - h + 0.75f * s, x + l - 0.75f * s, bas - 0.75f * s)
                c.drawRoundRect(r, 3f * s, 3f * s, trait)
            } else {
                var y = bas
                for ((v, a) in g.parts) {
                    val hp = (v / vmax * haut).toFloat()
                    if (hp <= 0f) continue
                    plein.color = alpha(Palette.sante, a)
                    r.set(x, y - hp, x + l, y)
                    c.drawRoundRect(r, 3f * s, 3f * s, plein)
                    y -= hp + 2f * s
                }
            }
            val sommet = bas - h - 4f * s
            val sousCharge = if (serre && !g.enCours) 0f else 13f * 1.22f * s
            g.charge?.let { texte(SanteHisto.milliers(it), x + l / 2f, sommet - 15f * 1.22f * s - sousCharge, (if (serre) 13f else 15f) * s, Palette.texte1, Paint.Align.CENTER) }
            if (!serre || g.enCours) texte(if (g.enCours) "en cours" else g.heures, x + l / 2f, sommet - 13f * 1.22f * s, 13f * s, Palette.texte3, Paint.Align.CENTER)
            if (i in dates) texte(g.date, x + l / 2f, bas + 13f * s, 14f * s, if (i == n - 1) Palette.texte1 else Palette.texte3, Paint.Align.CENTER)
        }
    }
}

/**
 * Courbe du cœur d'une séance avec les bandes des zones derrière (bornes en bpm si le serveur les donne),
 * le maximum marqué et l'axe du temps. [compact] : gabarit d'Aujourd'hui et de la vue Jour (bandes sur 420 px,
 * noms des zones à droite, « FC max ») ; sinon gabarit de Séances (bornes à gauche, axe de 15 en 15 min).
 */
internal class CourbeZones(ctx: Context) : GrapheSante(ctx) {
    var compact = true
    var points: List<Pair<Double, Int>> = emptyList()
    var bornes: List<SanteHisto.Borne>? = null
    var fcMax: Int? = null
    var libelleMax = ""

    fun regler(p: List<Pair<Double, Int>>, b: List<SanteHisto.Borne>?, max: Int?, libelle: String) {
        points = p.sortedBy { it.first }
        bornes = b?.takeIf { l -> l.any { it.min != null } }
        fcMax = max
        libelleMax = libelle
        invalidate()
    }

    override fun dessiner(c: Canvas, s: Float) {
        if (points.size < 2) return
        val gauche = if (compact) 0f else 36f * s
        val droite = if (compact) 420f * s else width.toFloat()
        val hauteur = (if (compact) 118f else 150f) * s
        val zb = bornes
        // Échelle bornée par la courbe (la zone 1 part de 0 bpm), bandes rognées à cette échelle.
        val bmin = points.minOf { it.second } - 6
        val bmax = points.maxOf { it.second } + 6
        fun y(v: Double) = (hauteur - (v - bmin) / (bmax - bmin) * hauteur).toFloat()
        if (zb != null) {
            val op = floatArrayOf(0.08f, 0.13f, 0.18f, 0.25f, 0.33f)
            var dernierNom = Float.MAX_VALUE
            for ((i, z) in zb.withIndex()) {
                val bas = (z.min ?: 0).toDouble()
                val haut = zb.getOrNull(i + 1)?.min?.toDouble() ?: Double.MAX_VALUE
                if (haut <= bmin || bas >= bmax) continue
                val y1 = y(min(haut, bmax.toDouble())).coerceAtLeast(0f)
                val y2 = y(max(bas, bmin.toDouble())).coerceAtMost(hauteur)
                if (y2 <= y1) continue
                plein.color = alpha(Palette.sante, op[i.coerceIn(0, 4)])
                c.drawRect(gauche, y1, droite, y2, plein)
                if (compact) {
                    // Noms à droite, de bas en haut, jamais l'un sur l'autre.
                    val yy = min((y1 + y2) / 2f - 7f * s, dernierNom - 14f * s)
                    if (yy >= -2f * s) {
                        texte("zone ${i + 1}, " + SanteHisto.texteBorne(z), droite + 12f * s, yy, 13f * s, Palette.texte3)
                        dernierNom = yy
                    }
                } else if (bas > bmin) {
                    texte(bas.roundToInt().toString(), 30f * s, y2 - 7f * s, 13f * s, Palette.texte3, Paint.Align.RIGHT)
                }
            }
        }
        val m0 = points.first().first
        val m1 = points.last().first
        fun x(m: Double) = (gauche + (m - m0) / max(1e-9, m1 - m0) * (droite - gauche)).toFloat()
        val p = Path()
        for ((i, pt) in points.withIndex()) {
            if (i == 0) p.moveTo(x(pt.first), y(pt.second.toDouble())) else p.lineTo(x(pt.first), y(pt.second.toDouble()))
        }
        trait.color = Palette.sante
        trait.strokeWidth = 2f * s
        c.drawPath(p, trait)
        val sommet = points.maxBy { it.second }
        plein.color = Palette.sante
        val hx = x(sommet.first)
        val hy = y(sommet.second.toDouble())
        c.drawCircle(hx, hy, 4f * s, plein)
        texte(if (libelleMax.isEmpty()) sommet.second.toString() else libelleMax, hx + 8f * s, hy - 9f * s, 14f * s, Palette.texte1)
        // Axe du temps.
        plein.color = Palette.filet
        c.drawRect(gauche, hauteur + 4f * s, droite, hauteur + 4f * s + max(1f, s * 0.5f), plein)
        val duree = m1 - m0
        val pasMin = if (compact) 30.0 else 15.0
        var t = 0.0
        while (t <= duree + 0.01) {
            val xx = x(m0 + t)
            val nom = if (t + pasMin > duree + 0.01) "${t.roundToInt()} min" else "${t.roundToInt()}"
            texte(nom, xx, hauteur + 7f * s, 13f * s, Palette.texte3, if (t == 0.0) Paint.Align.LEFT else Paint.Align.CENTER)
            t += pasMin
        }
        if (compact && zb != null) fcMax?.let { texte("FC max $it", droite + 12f * s, hauteur + 7f * s, 13f * s, Palette.texte3) }
    }
}

/** Hypnogramme de la vue Jour : stades de la nuit en escalier (éveil, paradoxal, léger, profond) et heures. */
internal class Hypnogramme(ctx: Context) : GrapheSante(ctx) {
    var seq: List<Triple<Int, Int, String>> = emptyList()
        set(v) {
            field = v
            invalidate()
        }
    var debut: java.time.LocalDateTime? = null
        set(v) {
            field = v
            invalidate()
        }

    private val lignes = listOf("eveille" to "éveil", "paradoxal" to "paradoxal", "leger" to "léger", "profond" to "profond")

    private fun rang(stade: String): Int = when (stade) {
        "eveille", "hors du lit", "inconnu" -> 0
        "paradoxal" -> 1
        "leger", "endormi" -> 2
        "profond" -> 3
        else -> 0
    }

    override fun dessiner(c: Canvas, s: Float) {
        if (seq.isEmpty()) return
        val gauche = 80f * s
        val droite = width.toFloat()
        val pasLigne = 32f * s
        for ((i, l) in lignes.withIndex()) {
            val yy = 8f * s + i * pasLigne
            texte(l.second, 0f, yy - 8f * s, 14f * s, Palette.texte3)
            pointilles(s)
            tirets.color = Palette.filet
            c.drawLine(gauche, yy, droite, yy, tirets)
        }
        val total = seq.maxOf { it.first + it.second }.toFloat().coerceAtLeast(1f)
        fun x(m: Float) = gauche + m / total * (droite - gauche)
        val p = Path()
        for ((k, e) in seq.sortedBy { it.first }.withIndex()) {
            val yy = 8f * s + rang(e.third) * pasLigne
            if (k == 0) p.moveTo(x(e.first.toFloat()), yy) else p.lineTo(x(e.first.toFloat()), yy)
            p.lineTo(x((e.first + e.second).toFloat()), yy)
        }
        trait.color = Palette.sante
        trait.strokeWidth = 2f * s
        c.drawPath(p, trait)
        // Heures : début, chaque heure paire, fin, à l'heure de Paris changement d'heure compris.
        val d = debut ?: return
        val yt = 8f * s + 3 * pasLigne + 14f * s
        texte(SanteHisto.heure(d), x(0f), yt, 14f * s, Palette.texte3, Paint.Align.CENTER)
        for ((m, nom) in SanteHisto.heuresNuit(d, total.toLong())) texte(nom, x(m.toFloat()), yt, 14f * s, Palette.texte3, Paint.Align.CENTER)
        texte(SanteHisto.heure(SanteHisto.apres(d, total.toLong())), x(total), yt, 14f * s, Palette.texte3, Paint.Align.CENTER)
    }
}

/** Barre des stades de sommeil et sa légende en deux colonnes (pastille, nom, durée). */
internal class StadesLegende(ctx: Context) : GrapheSante(ctx) {
    var stades: List<Pair<String, Int>> = emptyList()
        set(v) {
            field = v
            invalidate()
        }

    override fun onMeasure(l: Int, h: Int) {
        setMeasuredDimension(MeasureSpec.getSize(l), ((10f + 12f + 2 * 21f) * echelle).roundToInt())
    }

    private fun couleur(cle: String): Pair<Int, Float> = when (cle) {
        "profond" -> Palette.sante to 1f
        "paradoxal" -> Palette.sante to 0.7f
        "leger" -> Palette.sante to 0.45f
        "endormi" -> Palette.sante to 0.5f
        "eveille" -> Palette.barre to 1f
        else -> Palette.barre to 1f
    }

    override fun dessiner(c: Canvas, s: Float) {
        val total = stades.sumOf { it.second }.toFloat()
        if (total <= 0f) return
        val w = width.toFloat()
        val chemin = Path()
        r.set(0f, 0f, w, 10f * s)
        chemin.addRoundRect(r, 5f * s, 5f * s, Path.Direction.CW)
        c.save()
        c.clipPath(chemin)
        var x = 0f
        for ((cle, m) in stades) {
            val l = w * m / total
            val (coul, a) = couleur(cle)
            plein.color = alpha(coul, a)
            c.drawRect(x, 0f, x + l, 10f * s, plein)
            x += l
        }
        c.restore()
        // Légende : deux colonnes de 124 et 136 px, quatre stades au plus (hors du lit et inconnu sans légende).
        val montres = stades.filter { SanteDetail.dort(it.first) || it.first == "eveille" }.take(4)
        for ((i, st) in montres.withIndex()) {
            val col = i % 2
            val lig = i / 2
            val gx = if (col == 0) 0f else 124f * s
            val gy = 22f * s + lig * 25f * s
            val (coul, a) = couleur(st.first)
            plein.color = alpha(coul, a)
            r.set(gx, gy + 4f * s, gx + 10f * s, gy + 14f * s)
            c.drawRoundRect(r, 3f * s, 3f * s, plein)
            val nom = SanteDetail.nomStade(st.first)
            pTexte.textSize = 15f * s
            val ln = pTexte.measureText(nom)
            texte(nom, gx + 17f * s, gy, 15f * s, Palette.texte3)
            texte(SanteDetail.duree(st.second), gx + 17f * s + ln + 7f * s, gy, 15f * s, Palette.texte2)
        }
    }
}

/** Petit rond « i » d'explication (charge), au trait. */
internal class RondInfo(ctx: Context) : GrapheSante(ctx) {
    override fun dessiner(c: Canvas, s: Float) {
        val cx = width / 2f
        val cy = height / 2f
        trait.color = Palette.texte3
        trait.strokeWidth = 1.2f * s
        c.drawCircle(cx, cy, 7f * s, trait)
        plein.color = Palette.texte3
        c.drawCircle(cx, cy - 3f * s, 0.9f * s, plein)
        c.drawRect(cx - 0.6f * s, cy - 1f * s, cx + 0.6f * s, cy + 3.8f * s, plein)
    }
}

/** Chevron au trait (gauche, droite ou bas), 22 px de maquette, dans une zone de toucher de 44 px. */
internal class Chevron(ctx: Context, private val sens: Char) : GrapheSante(ctx) {
    var couleur = Palette.texte2
    override fun dessiner(c: Canvas, s: Float) {
        val cx = width / 2f
        val cy = height / 2f
        val k = 4.5f * s
        val p = Path()
        when (sens) {
            '<' -> { p.moveTo(cx + k / 2, cy - k); p.lineTo(cx - k / 2, cy); p.lineTo(cx + k / 2, cy + k) }
            '>' -> { p.moveTo(cx - k / 2, cy - k); p.lineTo(cx + k / 2, cy); p.lineTo(cx - k / 2, cy + k) }
            else -> { p.moveTo(cx - k, cy - k / 2); p.lineTo(cx, cy + k / 2); p.lineTo(cx + k, cy - k / 2) }
        }
        trait.color = if (isEnabled) couleur else Palette.filet
        trait.strokeWidth = 1.6f * s
        c.drawPath(p, trait)
    }
}

/** Arrondi de [v] au millier inférieur pour les repères de pas (5 000, 10 000). */
internal fun reperePas(max: Int): List<Pair<Double, String>> =
    if (max >= 12_000) listOf(5000.0 to "5 000", 10000.0 to "10 000") else listOf(5000.0 to "5 000")

/** Repères de sommeil : 6 h et 8 h. */
internal val REPERES_SOMMEIL = listOf(360.0 to "6 h", 480.0 to "8 h")

/**
 * Indices des dates écrites sous un graphe de [n] points, comme la maquette : un tous les [pas] depuis le
 * premier, et toujours le dernier, qui remplace son voisin s'il en est trop près (23 sept., 30 sept., 7 oct.,
 * 14 oct., 22 oct.).
 */
internal fun indicesDates(n: Int, pas: Int): List<Int> {
    if (n <= 0) return emptyList()
    val p = max(1, pas)
    val l = (0 until n step p).toMutableList()
    if (l.last() != n - 1) {
        if (l.size > 1 && n - 1 - l.last() < (p + 1) / 2) l.removeAt(l.size - 1)
        l.add(n - 1)
    }
    return l
}
