package assistant.vocal.jarvis

import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.atan2
import kotlin.math.ceil
import kotlin.math.cos
import kotlin.math.sin
import kotlin.math.sqrt
import kotlin.math.tan

/**
 * Lecture des chemins SVG des pictos des maquettes (0.20.0, panneau Météo) : M, L, H, V, C, S, A et Z, en
 * absolu et en relatif, drapeaux d'arc séparés par des espaces (comme dans les maquettes). Logique pure,
 * testée sur la machine (CheminSvgTest) : le chemin devient une suite de déplacements, de lignes et de
 * courbes de Bézier cubiques en coordonnées absolues (les arcs découpés en quarts au plus), que les vues
 * tracent dans un android.graphics.Path.
 */
internal object CheminSvg {

    sealed class Pas {
        data class Aller(val x: Float, val y: Float) : Pas()
        data class Ligne(val x: Float, val y: Float) : Pas()
        data class Courbe(val x1: Float, val y1: Float, val x2: Float, val y2: Float, val x: Float, val y: Float) : Pas()
        object Fermer : Pas()
    }

    private val JETON = Regex("[MmLlHhVvCcSsAaZz]|[-+]?(?:\\d+\\.?\\d*|\\.\\d+)(?:[eE][-+]?\\d+)?")

    fun lire(d: String): List<Pas> {
        val t = JETON.findAll(d).map { it.value }.toList()
        val sortie = ArrayList<Pas>()
        var i = 0
        var cmd = ' '
        var x = 0f
        var y = 0f
        var x0 = 0f
        var y0 = 0f
        var cx2 = 0f
        var cy2 = 0f
        var courbePrecedente = false
        fun n(): Float = t[i++].toFloat()
        while (i < t.size) {
            if (t[i][0].isLetter()) {
                cmd = t[i][0]
                i++
            } else if (cmd == ' ') {
                i++
                continue
            }
            val rel = cmd.isLowerCase()
            val ox = if (rel) x else 0f
            val oy = if (rel) y else 0f
            var courbe = false
            when (cmd.uppercaseChar()) {
                'Z' -> {
                    sortie.add(Pas.Fermer)
                    x = x0
                    y = y0
                }
                'M' -> {
                    x = ox + n(); y = oy + n()
                    x0 = x; y0 = y
                    sortie.add(Pas.Aller(x, y))
                    // Les paires qui suivent un M sont des lignes.
                    cmd = if (rel) 'l' else 'L'
                }
                'L' -> { x = ox + n(); y = oy + n(); sortie.add(Pas.Ligne(x, y)) }
                'H' -> { x = ox + n(); sortie.add(Pas.Ligne(x, y)) }
                'V' -> { y = oy + n(); sortie.add(Pas.Ligne(x, y)) }
                'C', 'S' -> {
                    val (x1, y1) = if (cmd.uppercaseChar() == 'C') (ox + n()) to (oy + n())
                    else if (courbePrecedente) (2 * x - cx2) to (2 * y - cy2) else x to y
                    cx2 = ox + n(); cy2 = oy + n()
                    x = ox + n(); y = oy + n()
                    sortie.add(Pas.Courbe(x1, y1, cx2, cy2, x, y))
                    courbe = true
                }
                'A' -> {
                    val rx = n(); val ry = n(); val rot = n()
                    val grand = n() != 0f
                    val sens = n() != 0f
                    val xf = ox + n(); val yf = oy + n()
                    sortie.addAll(arc(x, y, rx, ry, rot, grand, sens, xf, yf))
                    x = xf; y = yf
                }
                else -> i++
            }
            courbePrecedente = courbe
            // Après Z, une commande sans nouvelle lettre n'a pas de sens : on attend la lettre suivante.
            if (cmd == 'Z' || cmd == 'z') cmd = ' '
        }
        return sortie
    }

    /** Arc elliptique SVG découpé en courbes cubiques (paramétrisation par le centre, W3C SVG 1.1, annexe F.6). */
    private fun arc(x1: Float, y1: Float, rx0: Float, ry0: Float, rotDeg: Float, grand: Boolean, sens: Boolean, x2: Float, y2: Float): List<Pas> {
        if (x1 == x2 && y1 == y2) return emptyList()
        var rx = abs(rx0.toDouble())
        var ry = abs(ry0.toDouble())
        if (rx == 0.0 || ry == 0.0) return listOf(Pas.Ligne(x2, y2))
        val phi = rotDeg * PI / 180
        val cp = cos(phi)
        val sp = sin(phi)
        val dx = (x1 - x2) / 2.0
        val dy = (y1 - y2) / 2.0
        val x1p = cp * dx + sp * dy
        val y1p = -sp * dx + cp * dy
        val lambda = (x1p * x1p) / (rx * rx) + (y1p * y1p) / (ry * ry)
        if (lambda > 1) {
            val r = sqrt(lambda)
            rx *= r
            ry *= r
        }
        val num = rx * rx * ry * ry - rx * rx * y1p * y1p - ry * ry * x1p * x1p
        val den = rx * rx * y1p * y1p + ry * ry * x1p * x1p
        var coef = if (den == 0.0) 0.0 else sqrt(maxOf(0.0, num / den))
        if (grand == sens) coef = -coef
        val cxp = coef * rx * y1p / ry
        val cyp = -coef * ry * x1p / rx
        val cx = cp * cxp - sp * cyp + (x1 + x2) / 2.0
        val cy = sp * cxp + cp * cyp + (y1 + y2) / 2.0
        fun angle(ux: Double, uy: Double, vx: Double, vy: Double): Double = atan2(ux * vy - uy * vx, ux * vx + uy * vy)
        val t1 = angle(1.0, 0.0, (x1p - cxp) / rx, (y1p - cyp) / ry)
        var dt = angle((x1p - cxp) / rx, (y1p - cyp) / ry, (-x1p - cxp) / rx, (-y1p - cyp) / ry)
        if (!sens && dt > 0) dt -= 2 * PI
        if (sens && dt < 0) dt += 2 * PI
        val morceaux = ceil(abs(dt) / (PI / 2) - 1e-9).toInt().coerceAtLeast(1)
        val pas = dt / morceaux
        val k = 4.0 / 3.0 * tan(pas / 4)
        fun point(t: Double): Pair<Double, Double> {
            val ex = rx * cos(t)
            val ey = ry * sin(t)
            return (cp * ex - sp * ey + cx) to (sp * ex + cp * ey + cy)
        }
        fun derivee(t: Double): Pair<Double, Double> {
            val ex = -rx * sin(t)
            val ey = ry * cos(t)
            return (cp * ex - sp * ey) to (sp * ex + cp * ey)
        }
        val sortie = ArrayList<Pas>()
        var a = t1
        repeat(morceaux) { m ->
            val b = a + pas
            val (pax, pay) = point(a)
            val (dax, day) = derivee(a)
            val (pbx, pby) = if (m == morceaux - 1) (x2.toDouble() to y2.toDouble()) else point(b)
            val (dbx, dby) = derivee(b)
            sortie.add(
                Pas.Courbe(
                    (pax + k * dax).toFloat(), (pay + k * day).toFloat(),
                    (pbx - k * dbx).toFloat(), (pby - k * dby).toFloat(),
                    pbx.toFloat(), pby.toFloat(),
                )
            )
            a = b
        }
        return sortie
    }

    /** Trace [pas] dans un chemin Android. */
    fun chemin(pas: List<Pas>, p: android.graphics.Path = android.graphics.Path()): android.graphics.Path {
        for (s in pas) when (s) {
            is Pas.Aller -> p.moveTo(s.x, s.y)
            is Pas.Ligne -> p.lineTo(s.x, s.y)
            is Pas.Courbe -> p.cubicTo(s.x1, s.y1, s.x2, s.y2, s.x, s.y)
            Pas.Fermer -> p.close()
        }
        return p
    }
}
