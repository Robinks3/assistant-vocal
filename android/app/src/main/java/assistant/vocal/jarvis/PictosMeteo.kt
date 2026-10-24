package assistant.vocal.jarvis

import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF

/**
 * Pictos météo en vecteurs (0.20.0), tracés au Canvas d'après les chemins SVG de la maquette `Meteo2`
 * (viewBox de 32 x 32) : soleil, éclaircies, nuage, pluie, neige, lune et lune voilée, et les deux petits
 * pictos du vent (flèche de direction, rafale). Couleurs de la palette : soleil en teinte `soleil`, gouttes
 * en teinte `pluie`, nuages en texte tertiaire (ombre) et texte principal.
 */
internal object PictosMeteo {

    private fun p(d: String): Path = CheminSvg.chemin(CheminSvg.lire(d))

    private val rayons by lazy { p("M16 3v3M16 26v3M3 16h3M26 16h3M6.8 6.8l2.1 2.1M23.1 23.1l2.1 2.1M6.8 25.2l2.1-2.1M23.1 8.9l2.1-2.1") }
    private val nuageEclaircies by lazy { p("M11 26h13a5 5 0 0 0 .5-10A7.5 7.5 0 0 0 10.2 17.5 4.3 4.3 0 0 0 11 26Z") }
    private val nuageOmbre by lazy { p("M14 18h11a4.5 4.5 0 0 0 .4-9A7 7 0 0 0 12.6 10.5") }
    private val nuagePlein by lazy { p("M8 26h14a5.2 5.2 0 0 0 .6-10.4A8 8 0 0 0 7.2 17.4 4.4 4.4 0 0 0 8 26Z") }
    private val nuagePluie by lazy { p("M8 20h14a5.2 5.2 0 0 0 .6-10.4A8 8 0 0 0 7.2 11.4 4.4 4.4 0 0 0 8 20Z") }
    private val luneVoilee by lazy { p("M18 4.5a8 8 0 1 0 8.5 12A6.8 6.8 0 0 1 18 4.5Z") }
    private val nuageNuit by lazy { p("M8 27h12a4.6 4.6 0 0 0 .5-9.2A7 7 0 0 0 7.3 19.2 3.9 3.9 0 0 0 8 27Z") }
    private val lune by lazy { p("M19 5a10 10 0 1 0 9 14.5A8.5 8.5 0 0 1 19 5Z") }
    /** Flèche du vent (viewBox 12 x 12), pointe en haut. */
    private val fleche by lazy { p("M6 1v10M6 1 3 4.5M6 1l3 3.5") }
    /** Rafale (viewBox 13 x 10). */
    private val rafale by lazy { p("M1 3h7.5a2 2 0 1 0-2-2M1 7h10a1.8 1.8 0 1 1-1.8 1.8") }

    private val plein = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.FILL }
    private val trait = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }
    private val ovale = RectF()

    private fun alpha(c: Int, a: Float): Int = (((c ushr 24) * a).toInt().coerceIn(0, 255) shl 24) or (c and 0xFFFFFF)

    /** Picto [picto] dans le carré ([x], [y], [taille]) en pixels, à l'opacité [opacite]. */
    fun dessiner(c: Canvas, picto: MeteoTexte.Picto, x: Float, y: Float, taille: Float, opacite: Float = 1f) {
        val s = taille / 32f
        c.save()
        c.translate(x, y)
        c.scale(s, s)
        val ombre = alpha(Palette.texte3, opacite)
        val clair = alpha(Palette.texte1, opacite)
        val soleil = alpha(Palette.soleil, opacite)
        fun remplir(path: Path, couleur: Int) {
            plein.color = couleur
            c.drawPath(path, plein)
        }
        when (picto) {
            MeteoTexte.Picto.SOLEIL -> {
                plein.color = soleil
                c.drawCircle(16f, 16f, 6.5f, plein)
                trait.color = soleil
                trait.strokeWidth = 2.4f
                c.drawPath(rayons, trait)
            }
            MeteoTexte.Picto.ECLAIRCIES -> {
                plein.color = soleil
                c.drawCircle(12f, 11f, 5.5f, plein)
                remplir(nuageEclaircies, ombre)
            }
            MeteoTexte.Picto.NUAGE -> {
                remplir(nuageOmbre, ombre)
                remplir(nuagePlein, clair)
            }
            MeteoTexte.Picto.PLUIE, MeteoTexte.Picto.NEIGE -> {
                remplir(nuagePluie, ombre)
                val neige = picto == MeteoTexte.Picto.NEIGE
                plein.color = alpha(if (neige) Palette.texte1 else Palette.accentPluie, opacite)
                for ((gx, gy) in listOf(10.5f to 25.5f, 16f to 26.5f, 21.5f to 25.5f)) {
                    if (neige) {
                        c.drawCircle(gx, gy, 1.9f, plein)
                    } else {
                        c.save()
                        c.rotate(18f, gx, gy)
                        ovale.set(gx - 1.6f, gy - 2.6f, gx + 1.6f, gy + 2.6f)
                        c.drawOval(ovale, plein)
                        c.restore()
                    }
                }
            }
            MeteoTexte.Picto.NUIT_NUAGE -> {
                remplir(luneVoilee, ombre)
                remplir(nuageNuit, clair)
            }
            MeteoTexte.Picto.NUIT -> remplir(lune, clair)
        }
        c.restore()
    }

    /**
     * Flèche du vent de [taille] px, centrée en ([cx], [cy]), tournée de [degres] (0 : vers le haut). [epaisseur] :
     * trait en unités du dessin de 12 (0.23.0 : plus fin pour les grandes flèches de la page Mer).
     */
    fun flecheVent(c: Canvas, cx: Float, cy: Float, taille: Float, degres: Float, couleur: Int, epaisseur: Float = 1.4f) {
        val s = taille / 12f
        c.save()
        c.translate(cx, cy)
        c.rotate(degres)
        c.scale(s, s)
        c.translate(-6f, -6f)
        trait.color = couleur
        trait.strokeWidth = epaisseur
        c.drawPath(fleche, trait)
        c.restore()
    }

    /** Petit picto de rafale, [largeur] px, coin haut gauche en ([x], [y]). */
    fun rafale(c: Canvas, x: Float, y: Float, largeur: Float, couleur: Int) {
        val s = largeur / 13f
        c.save()
        c.translate(x, y)
        c.scale(s, s)
        trait.color = couleur
        trait.strokeWidth = 1.3f
        c.drawPath(rafale, trait)
        c.restore()
    }
}
