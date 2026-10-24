package assistant.vocal.jarvis

import android.content.Context
import android.graphics.Canvas
import android.graphics.DashPathEffect
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Shader
import android.view.View
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Santé en un coup d'œil sur l'accueil (0.26.0, demande du 23/10/2026 : « mes données de santé rapides
 * dans quelques graphes, genre cercle, histogramme ou autre »). Piste « mélange » du canevas (version 27,
 * planches `SanteMelange` et `SanteEtats`, décisions dans docs/maquettes/revue-accueil-musique.md) : l'anneau
 * des pas du jour sur 6 000, les 7 dernières nuits en barres avec un repère de 7 h, le cœur au repos des 7 jours
 * en courbe. Logique pure ici ([CoupDOeilSante], testée par SanteAccueilTest), dessin dans [VueSanteAccueil].
 */
internal object CoupDOeilSante {

    /** Objectifs de la maquette : 6 000 pas (seuil des séries du serveur), nuits de 7 h. */
    const val OBJECTIF_PAS = 6000
    const val OBJECTIF_NUIT_MIN = 420
    /** Hauteur des barres des nuits : 9 h en haut, une nuit plus longue est écrêtée. */
    const val NUIT_MAX_MIN = 540
    /** Sous 3 jours connus, l'historique est caché et seul le chiffre du jour reste. */
    const val JOURS_MIN = 3
    /** Échelle du cœur au repos : plus ou moins 5 bpm autour de la moyenne, valeurs hors échelle au bord. */
    const val ECHELLE_COEUR = 5.0

    /** Part de l'anneau des pas : fermé au-delà de l'objectif, sans second tour. */
    fun fractionPas(pas: Int?): Float = if (pas == null || pas <= 0) 0f else min(1f, pas / OBJECTIF_PAS.toFloat())

    fun assez(valeurs: List<Int?>): Boolean = valeurs.count { it != null } >= JOURS_MIN

    enum class Genre { JOUR, AUTRE, MANQUE, JOUR_ABSENT }

    /** Une barre : hauteur en part de la hauteur du graphe (0 à 1), et ce qu'elle est. */
    data class Barre(val indice: Int, val hauteur: Float, val genre: Genre)

    /**
     * Barres des 7 nuits (de la plus ancienne à celle de ce matin) : la dernière dans la teinte santé, un jour
     * manquant en moignon, la nuit de ce matin pas encore reçue en case pointillée à mi-hauteur.
     */
    fun barresNuits(nuits: List<Int?>): List<Barre> = nuits.mapIndexed { i, v ->
        val dernier = i == nuits.lastIndex
        when {
            v == null && dernier -> Barre(i, 0.5f, Genre.JOUR_ABSENT)
            v == null -> Barre(i, 0f, Genre.MANQUE)
            else -> Barre(i, min(v, NUIT_MAX_MIN) / NUIT_MAX_MIN.toFloat(), if (dernier) Genre.JOUR else Genre.AUTRE)
        }
    }

    /** Hauteur du repère de 7 h, en part de la hauteur du graphe. */
    val repereNuit: Float get() = OBJECTIF_NUIT_MIN / NUIT_MAX_MIN.toFloat()

    /**
     * Courbe du cœur au repos : des tronçons de points (x de 0 à 1, y de 0 en haut à 1 en bas), coupés à chaque
     * jour manquant. Échelle fixe autour de la moyenne des jours connus, valeurs hors échelle bornées au bord.
     */
    fun courbe(valeurs: List<Int?>): List<List<Pair<Float, Float>>> {
        val connus = valeurs.filterNotNull()
        if (connus.isEmpty() || valeurs.size < 2) return emptyList()
        val moyenne = connus.average()
        val troncons = ArrayList<List<Pair<Float, Float>>>()
        var courant = ArrayList<Pair<Float, Float>>()
        for ((i, v) in valeurs.withIndex()) {
            if (v == null) {
                if (courant.isNotEmpty()) troncons.add(courant)
                courant = ArrayList()
                continue
            }
            val e = ((v - moyenne) / ECHELLE_COEUR).coerceIn(-1.0, 1.0)
            courant.add(i / (valeurs.size - 1f) to (0.5f - 0.5f * e.toFloat()))
        }
        if (courant.isNotEmpty()) troncons.add(courant)
        return troncons
    }
}

/**
 * Le bloc santé de l'accueil (maquette `SanteMelange`, 484 x 162 px de maquette) : l'anneau des pas (132 px,
 * trait de 12, chiffre en 44 px dans la teinte santé, ou « 0 » en texte3 et l'heure de la dernière lecture le
 * matin), les 7 nuits (barres de 16 px, repère de 7 h en pointillé), le cœur au repos (courbe de 3 px en
 * texte3, point du jour de 6 px). Pas de lueur : le relief passe par le dégradé de la barre du jour et un filet
 * clair en haut. Le soir, les barres des autres jours baissent à 60 %.
 */
internal class VueSanteAccueil(private val ctx: Context) : View(ctx) {

    var resume: Sante.Resume? = null
        set(v) {
            if (v == field) return
            field = v
            invalidate()
        }
    var echelle = CadreMaquette.estimer(ctx)
        set(v) {
            if (v == field) return
            field = v
            requestLayout()
            invalidate()
        }
    var soir = false
        set(v) {
            if (v == field) return
            field = v
            invalidate()
        }
    /** Teinte santé du moment (saturation du régime), posée par l'accueil. */
    var teinte = Palette.sante
        set(v) {
            if (v == field) return
            field = v
            invalidate()
        }

    private val trait = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE; strokeCap = Paint.Cap.ROUND; strokeJoin = Paint.Join.ROUND }
    private val plein = Paint(Paint.ANTI_ALIAS_FLAG)
    private val chiffres = Paint(Paint.ANTI_ALIAS_FLAG).apply { typeface = Polices.chiffres(ctx, 300) }
    private val mots = Paint(Paint.ANTI_ALIAS_FLAG).apply { typeface = Polices.texte(ctx) }
    private val chemin = Path()
    private val rect = RectF()
    private val pointille = DashPathEffect(floatArrayOf(4f, 4f), 0f)

    init {
        importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_YES
        isClickable = true
        isFocusable = true
    }

    override fun onMeasure(largeurSpec: Int, hauteurSpec: Int) {
        setMeasuredDimension(((LARGEUR + 2 * MARGE) * echelle).roundToInt(), ((HAUTEUR + 2 * MARGE) * echelle).roundToInt())
    }

    /** Le bloc se dessine sans recouvrement : l'opacité ne demande pas de couche hors écran à chaque image. */
    override fun hasOverlappingRendering(): Boolean = false

    override fun drawableStateChanged() {
        super.drawableStateChanged()
        // Retour au toucher : le bloc s'éclaircit un instant (relecture design, sans bordure ni fond).
        alpha = if (isPressed) 1f else 0.94f
    }

    private fun alpha(c: Int, a: Float): Int = (((c ushr 24) * a).roundToInt().coerceIn(0, 255) shl 24) or (c and 0xFFFFFF)

    override fun onDraw(c: Canvas) {
        val r = resume ?: return
        val s = echelle
        c.save()
        c.translate(MARGE * s, MARGE * s)
        c.scale(s, s)
        val sante = teinte
        val clair = Decor.melange(sante, Palette.texte1, 0.35f)
        val fonce = Couleurs.saturer(Decor.melange(sante, 0xFF000000.toInt(), 0.18f), 1.15f)
        dessinerAnneau(c, r, sante, clair, fonce)
        dessinerNuits(c, r, sante, clair, fonce, 158f)
        dessinerCoeur(c, r, sante, 334f)
        c.restore()
    }

    private fun legende(c: Canvas, texte: String, x: Float, centre: Boolean) {
        mots.textSize = 18f
        mots.color = Palette.texte3
        mots.textAlign = if (centre) Paint.Align.CENTER else Paint.Align.LEFT
        c.drawText(texte, x, HAUTEUR - 4f, mots)
    }

    private fun dessinerAnneau(c: Canvas, r: Sante.Resume, sante: Int, clair: Int, fonce: Int) {
        val cx = 66f
        val cy = 66f
        trait.pathEffect = null
        trait.shader = null
        trait.strokeWidth = 12f
        trait.color = alpha(Palette.barre, 0.6f)
        c.drawCircle(cx, cy, 58f, trait)
        val f = CoupDOeilSante.fractionPas(r.pas)
        if (f > 0f) {
            trait.shader = LinearGradient(8f, 8f, 124f, 124f, intArrayOf(clair, sante, fonce), floatArrayOf(0f, 0.55f, 1f), Shader.TileMode.CLAMP)
            rect.set(cx - 58f, cy - 58f, cx + 58f, cy + 58f)
            if (f >= 1f) c.drawCircle(cx, cy, 58f, trait) else c.drawArc(rect, -90f, 360f * f, false, trait)
            trait.shader = null
        }
        // Filet sombre à l'intérieur : l'anneau a de l'épaisseur.
        trait.strokeWidth = 2f
        trait.color = 0x66000000
        c.drawCircle(cx, cy, 51f, trait)
        val matin = r.pas == null || r.pas <= 0
        // 44 px, 38 px au-delà de 9 999 pour ne pas toucher l'anneau.
        chiffres.textSize = if ((r.pas ?: 0) > 9999) 38f else 44f
        chiffres.textAlign = Paint.Align.CENTER
        chiffres.color = if (matin) Palette.texte3 else sante
        val synchro = if (matin) r.luA?.let { "lu à $it" } else null
        val base = if (synchro != null) cy + 6f else cy + 15f
        c.drawText(if (matin) "0" else Sante.milliers(r.pas!!), cx, base, chiffres)
        if (synchro != null) {
            mots.textSize = 16f
            mots.color = Palette.texte3
            mots.textAlign = Paint.Align.CENTER
            c.drawText(synchro, cx, base + 22f, mots)
        }
        legende(c, "pas sur 6 000", cx, centre = true)
    }

    private fun valeur(c: Canvas, texte: String?, x: Float, sante: Int) {
        if (texte == null) {
            mots.textSize = 22f
            mots.color = Palette.texte3
            mots.textAlign = Paint.Align.LEFT
            c.drawText("pas reçue", x, 44f, mots)
            return
        }
        chiffres.textSize = 48f
        chiffres.textAlign = Paint.Align.LEFT
        chiffres.color = sante
        c.drawText(texte, x, 46f, chiffres)
    }

    private fun dessinerNuits(c: Canvas, r: Sante.Resume, sante: Int, clair: Int, fonce: Int, x0: Float) {
        valeur(c, r.sommeilMinutes?.let { Sante.duree(it) }, x0, sante)
        val haut = 54f
        val h = 80f
        if (CoupDOeilSante.assez(r.nuits)) {
            // Repère de 7 h, sous les barres : 2 px en pointillé, texte3 à 35 %.
            trait.shader = null
            trait.strokeWidth = 2f
            trait.color = alpha(Palette.texte3, 0.35f)
            trait.pathEffect = pointille
            val yr = haut + h - h * CoupDOeilSante.repereNuit
            c.drawLine(x0, yr, x0 + 150f, yr, trait)
            trait.pathEffect = null
            for (b in CoupDOeilSante.barresNuits(r.nuits)) {
                val x = x0 + b.indice * 22f
                when (b.genre) {
                    CoupDOeilSante.Genre.MANQUE -> {
                        plein.shader = null
                        plein.color = Palette.filet
                        c.drawRoundRect(x, haut + h - 4f, x + 16f, haut + h, 2f, 2f, plein)
                    }
                    CoupDOeilSante.Genre.JOUR_ABSENT -> {
                        trait.shader = null
                        trait.strokeWidth = 1.5f
                        trait.color = Palette.filet
                        trait.pathEffect = pointille
                        c.drawRoundRect(x + 0.75f, haut + h * 0.5f, x + 15.25f, haut + h - 0.75f, 2f, 2f, trait)
                        trait.pathEffect = null
                    }
                    else -> {
                        val hb = max(4f, h * b.hauteur)
                        val y = haut + h - hb
                        if (b.genre == CoupDOeilSante.Genre.JOUR) {
                            plein.shader = LinearGradient(0f, y, 0f, haut + h, intArrayOf(clair, sante, fonce), floatArrayOf(0f, 0.55f, 1f), Shader.TileMode.CLAMP)
                            plein.alpha = 255
                        } else {
                            plein.shader = LinearGradient(0f, y, 0f, haut + h, Palette.barre, Decor.melange(Palette.barre, 0xFF000000.toInt(), 0.3f), Shader.TileMode.CLAMP)
                            plein.alpha = if (soir) 153 else 204
                        }
                        chemin.rewind()
                        chemin.addRoundRect(RectF(x, y, x + 16f, haut + h), floatArrayOf(4f, 4f, 4f, 4f, 1f, 1f, 1f, 1f), Path.Direction.CW)
                        c.drawPath(chemin, plein)
                        plein.shader = null
                        plein.alpha = 255
                        if (b.genre == CoupDOeilSante.Genre.JOUR) {
                            plein.color = alpha(Palette.texte1, 0.25f)
                            c.drawRect(x + 2f, y, x + 14f, y + 1f, plein)
                        }
                    }
                }
            }
        }
        legende(c, "nuits, sur 7 h", x0, centre = false)
    }

    private fun dessinerCoeur(c: Canvas, r: Sante.Resume, sante: Int, x0: Float) {
        val aujourdhui = r.coeur.lastOrNull()
        valeur(c, aujourdhui?.toString(), x0, sante)
        val haut = 54f
        if (CoupDOeilSante.assez(r.coeur)) {
            trait.shader = null
            trait.pathEffect = null
            trait.strokeWidth = 3f
            trait.color = Palette.texte3
            val troncons = CoupDOeilSante.courbe(r.coeur)
            for (t in troncons) {
                chemin.rewind()
                for ((i, p) in t.withIndex()) {
                    val x = x0 + 150f * p.first
                    val y = haut + 6f + 68f * p.second
                    if (i == 0) chemin.moveTo(x, y) else chemin.lineTo(x, y)
                }
                if (t.size == 1) c.drawPoint(x0 + 150f * t[0].first, haut + 6f + 68f * t[0].second, trait) else c.drawPath(chemin, trait)
            }
            if (aujourdhui != null) {
                val der = troncons.last().last()
                val x = x0 + 150f * der.first
                val y = haut + 6f + 68f * der.second
                plein.shader = null
                plein.color = 0xFF000000.toInt()
                c.drawCircle(x, y, 7f, plein)
                plein.color = sante
                c.drawCircle(x, y, 5f, plein)
            }
        }
        legende(c, "cœur au repos", x0, centre = false)
    }

    companion object {
        /** Taille du bloc en pixels de maquette, et la marge de toucher autour (12 px). */
        const val LARGEUR = 484f
        const val HAUTEUR = 162f
        const val MARGE = 12f

        /** Libellé d'accessibilité : les chiffres ne sont dits que quand le bloc est montré. */
        fun libelle(r: Sante.Resume): String {
            val pas = r.pas?.takeIf { it > 0 }?.let { "${Sante.milliers(it)} pas" } ?: "pas encore de pas"
            val nuit = r.sommeilMinutes?.let { "nuit de ${Sante.duree(it)}" } ?: "nuit pas encore reçue"
            val coeur = r.coeur.lastOrNull()?.let { ", cœur au repos $it" } ?: ""
            return "Ouvrir la santé : $pas, $nuit$coeur"
        }
    }
}
