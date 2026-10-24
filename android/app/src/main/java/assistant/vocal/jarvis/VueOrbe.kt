package assistant.vocal.jarvis

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Matrix
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RadialGradient
import android.graphics.Shader
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import kotlin.math.PI
import kotlin.math.abs
import kotlin.math.cos
import kotlin.math.exp
import kotlin.math.hypot
import kotlin.math.min
import kotlin.math.roundToInt
import kotlin.math.sin

/**
 * Orbe animé du centre de l'écran (0.15.0) : l'état d'un projet d'inspiration se lit de loin, par la couleur
 * et le mouvement, sans texte.
 *
 * Disque en dégradé radial éclairé en haut à gauche, liseré plus lumineux, halo doux. Le contour
 * ondule lentement (somme de sinus, 5 à 10 % du rayon) et l'orbe respire. Pendant l'écoute, une
 * petite onde dessous suit le niveau du micro. Couleur par état en teinte, saturation, luminosité,
 * avec des transitions de 200 ms. Au plus 30 images par seconde, et aucune quand la vue est cachée :
 * la tablette reste allumée en poste fixe, l'animation ne doit pas la chauffer.
 *
 * 0.16.0 : en mode station avec la vision, l'orbe n'est qu'un point minuscule tant que personne
 * n'est là, et grandit jusqu'à sa taille pleine quand quelqu'un arrive (ou dès que assistant écoute).
 * Réduit, il ne se redessine que 10 fois par seconde.
 *
 * 0.17.0, écran OLED : en protection ([veille] 1), le point est gris bleuté, sans halo. Quand quelqu'un
 * revient, l'orbe se déploie du point à sa taille avec un léger rebond (ressort un peu sous-amorti),
 * et se rétracte en 2 s environ quand la pièce se vide. Il grossit un peu pendant l'écoute.
 *
 * 0.17.2, écran AOD : l'orbe n'est plus qu'un point de quelques pixels (Veille.RAYON_POINT_AOD_DP), gris
 * bleuté très foncé (Veille.GRIS_AOD_POINT), sans halo ni relief, et ne se redessine plus tant que rien
 * ne change. Centre, rayon et couleurs lus par le champ de particules ([lireCentre], [cibleHsl]).
 *
 * 0.24.0, accueil de la tablette (demande du propriétaire : « quand je lui parle, je mets bien l'orbe qui
 * apparaissait ») : l'orbe revient au centre de la zone du plan, à un rayon imposé ([rayonFixe]), avec des
 * particules discrètes autour ([particules]) et une version douce le soir ([doux]). La réponse passe au bleu
 * d'un projet d'inspiration, l'ambre reste aux lampes.
 */
internal class VueOrbe(ctx: Context) : View(ctx) {

    enum class Humeur { ARRETE, DECONNECTE, REPOS, ECOUTE, REFLEXION, REPONSE, ERREUR }

    private fun cible(h: Humeur): FloatArray = cibleHsl(h)

    private var humeur = Humeur.ARRETE
    private val depart = cible(Humeur.ARRETE)
    private val arrivee = cible(Humeur.ARRETE)
    private val courant = cible(Humeur.ARRETE)
    private var tTransition = 0L
    private var niveauCible = 0f
    private var niveau = 0f
    private var dernierDessin = 0L
    /** Taille relative de l'orbe (1 : pleine), menée vers sa cible par un ressort. */
    private var tailleCible = 1f
    private var taille = 1f
    private var vitesseTaille = 0f
    /** Le dernier changement de cible fait grandir l'orbe (ressort vif à léger rebond) ou le réduit (doux). */
    private var grandit = false
    /** Écran OLED : 0 vivant, 1 AOD (point de quelques pixels gris bleuté très foncé, sans halo). */
    var veille = 0f
        set(v) {
            val c = v.coerceIn(0f, 1f)
            if (c == field) return
            field = c
            relancer()
        }
    /** Rayon imposé en pixels (accueil, 0.24.0), centré dans la vue ; 0 : rayon d'après la taille de la vue. */
    var rayonFixe = 0f
        set(v) {
            if (v == field) return
            field = v
            relancer()
        }
    /** Accueil (0.24.0) : il s'ouvre en 0,45 s avec un léger rebond et se referme en 0,4 s, sur place. */
    var rapide = false
    /** Particules autour de l'orbe pendant l'écoute, la réflexion et la réponse (22 le jour, 10 le soir). */
    var particules = 0
    /** Le soir (Veillée) : saturation × 0,55, clarté × 0,7, halo et particules à moitié. */
    var doux = false
        set(v) {
            if (v == field) return
            field = v
            couleurShader = 0
            relancer()
        }
    private val pParticule = Paint(Paint.ANTI_ALIAS_FLAG)
    /** Tirage fixe des particules : angle, distance (en rayons), diamètre (dp), opacité. */
    private val graines = FloatArray(4 * 22).also { g ->
        var x = 12345L
        fun alea(): Float { x = (x * 16807L) % 2147483647L; return ((x - 1) / 2147483646.0).toFloat() }
        for (i in 0 until 22) {
            g[4 * i] = alea() * 2f * PI.toFloat()
            g[4 * i + 1] = 1.3f + alea() * 1.25f
            g[4 * i + 2] = 1.4f + alea() * 2.2f
            g[4 * i + 3] = 0.25f + alea() * 0.5f
        }
    }
    private var couleurShader = 0
    private val debut = SystemClock.uptimeMillis()

    private val densite = resources.displayMetrics.density
    private val pHalo = Paint(Paint.ANTI_ALIAS_FLAG)
    private val pDisque = Paint(Paint.ANTI_ALIAS_FLAG)
    private val pBord = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
    private val pOnde = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }
    private val pPoint = Paint(Paint.ANTI_ALIAS_FLAG)
    private val contour = Path()
    private val onde = Path()
    private val matrice = Matrix()
    private var shaderHalo: RadialGradient? = null
    private var shaderDisque: RadialGradient? = null

    init {
        isClickable = true
        isFocusable = true
        contentDescription = "Parler"
    }

    /** État à montrer et niveau du micro (0 à 1). */
    fun regler(h: Humeur, niveauMicro: Float) {
        niveauCible = niveauMicro.coerceIn(0f, 1f)
        if (h != humeur) {
            humeur = h
            System.arraycopy(courant, 0, depart, 0, 3)
            System.arraycopy(cible(h), 0, arrivee, 0, 3)
            tTransition = SystemClock.uptimeMillis()
            relancer()
        }
    }

    /** Rayon dessiné à la dernière image, pour les bulles qui naissent de son bord. */
    private var rayonDessine = 0f

    /** Centre (x, y) et rayon actuel de l'orbe, dans les coordonnées de la vue. */
    fun centre(): FloatArray = floatArrayOf(width / 2f, cyOrbe(), if (rayonDessine > 0f) rayonDessine else rayonBase() * taille)

    /** Comme [centre], écrit dans [dans] (trois cases) : sans allocation, pour chaque image des particules. */
    fun lireCentre(dans: FloatArray) {
        dans[0] = width / 2f
        dans[1] = cyOrbe()
        dans[2] = if (rayonDessine > 0f) rayonDessine else rayonBase() * taille
    }

    /** Pleine taille, ou point minuscule quand personne n'est là. */
    fun reglerTaille(pleine: Boolean) = reglerTaille(if (pleine) 1f else TAILLE_PETITE)

    /** Taille posée sans ressort (accueil, vue cachée) : la prochaine ouverture repart de là. */
    fun poserTaille(c: Float) {
        tailleCible = c
        taille = c
        vitesseTaille = 0f
        dernierDessin = 0L
    }

    /** Taille relative voulue (1 : pleine, un peu plus pendant l'écoute). */
    fun reglerTaille(c: Float) {
        if (c == tailleCible) return
        grandit = c > tailleCible
        tailleCible = c
        relancer()
    }

    private fun relancer() {
        if (isShown) postInvalidateOnAnimation()
    }

    /** Relance de l'animation (0.17.3) : écran rallumé ou activité reprise, l'image suivante est redemandée. */
    fun reprendreRendu() {
        dernierDessin = 0L
        relancer()
    }

    override fun onVisibilityAggregated(isVisible: Boolean) {
        super.onVisibilityAggregated(isVisible)
        if (isVisible) relancer()
    }

    /** Seul le disque réagit au doigt, pas toute la largeur de la vue. */
    @android.annotation.SuppressLint("ClickableViewAccessibility")
    override fun onTouchEvent(event: MotionEvent): Boolean {
        if (event.actionMasked == MotionEvent.ACTION_DOWN) {
            val rayon = maxOf(rayonBase() * taille * 1.25f, 70f * densite)
            if (hypot(event.x - width / 2f, event.y - cyOrbe()) > rayon) return false
        }
        return super.onTouchEvent(event)
    }

    private fun rayonBase(): Float = if (rayonFixe > 0f) rayonFixe else min(width * 0.5f, height * 0.40f) * 0.62f
    private fun cyOrbe(): Float = if (rayonFixe > 0f) height / 2f else height * 0.45f

    private fun avancer(maintenant: Long) {
        val f = ((maintenant - tTransition) / 200f).coerceIn(0f, 1f)
        val l = f * f * (3 - 2 * f)
        // Teinte par le plus court chemin sur le cercle.
        var dh = arrivee[0] - depart[0]
        if (dh > 180f) dh -= 360f
        if (dh < -180f) dh += 360f
        courant[0] = (depart[0] + dh * l + 360f) % 360f
        courant[1] = depart[1] + (arrivee[1] - depart[1]) * l
        courant[2] = depart[2] + (arrivee[2] - depart[2]) * l
        // Niveau lissé : monte vite, retombe doucement.
        val dt = if (dernierDessin == 0L) 0.033f else ((maintenant - dernierDessin) / 1000f).coerceIn(0f, 0.2f)
        val k = 1f - exp(-dt / if (niveauCible > niveau) 0.06f else 0.25f)
        niveau += (niveauCible - niveau) * k
        // Ressort de la taille, par petits pas : grandir en 0,8 s avec un léger rebond (amortissement
        // 0,55, environ 12 % de dépassement), se réduire sans rebond en 2 s environ.
        val raideur = if (grandit) (if (rapide) 160f else 70f) else (if (rapide) 110f else 6.5f)
        val amorti = 2f * kotlin.math.sqrt(raideur) * (if (grandit) 0.55f else 1f)
        var reste = dt
        while (reste > 0f) {
            val p = min(reste, 1f / 120f)
            vitesseTaille += (raideur * (tailleCible - taille) - amorti * vitesseTaille) * p
            taille += vitesseTaille * p
            reste -= p
        }
        if (taille < 0f) {
            taille = 0f
            vitesseTaille = 0f
        }
        if (abs(tailleCible - taille) < 0.002f && abs(vitesseTaille) < 0.01f) {
            taille = tailleCible
            vitesseTaille = 0f
        }
    }

    override fun onDraw(c: Canvas) {
        val maintenant = SystemClock.uptimeMillis()
        avancer(maintenant)
        dernierDessin = maintenant
        val cx = width / 2f
        val cy = cyOrbe()
        // Rayon minimal : 5 dp vivant, le point de quelques pixels de l'AOD en veille (0.17.2).
        val r0 = maxOf(rayonBase() * taille, (5f + (Veille.RAYON_POINT_AOD_DP - 5f) * veille) * densite)
        if (rayonBase() <= 0f) return
        // Accueil : refermé, rien à dessiner (pas de point de 5 dp sur le plan).
        if (rayonFixe > 0f && tailleCible == 0f && taille < 0.02f) {
            dernierDessin = 0L
            return
        }

        // Écran AOD (0.17.2) : un point de quelques pixels, gris bleuté très foncé, sans halo ni relief.
        // Rien ne bouge : aucune image suivante tant que l'état, la taille ou la veille ne changent pas.
        if (veille >= 0.999f && taille == tailleCible) {
            pPoint.color = Veille.GRIS_AOD_POINT
            rayonDessine = Veille.RAYON_POINT_AOD_DP * densite
            c.drawCircle(cx, cy, rayonDessine, pPoint)
            dernierDessin = 0L
            return
        }

        if (humeur == Humeur.ARRETE) {
            // Service arrêté : un point minuscule, rien ne bouge.
            pPoint.color = hsl(courant[0], courant[1], courant[2], 200)
            c.drawCircle(cx, cy, 4f * densite, pPoint)
            dernierDessin = 0L
            return
        }

        val t = (maintenant - debut) / 1000f
        val vivant = humeur != Humeur.DECONNECTE
        val n = if (vivant) niveau else 0f
        val souffle = 1f + sin(t) * 0.025f + n * 0.055f
        val r = r0 * souffle
        rayonDessine = r

        // Écran OLED vers l'AOD : la couleur glisse vers le gris bleuté très foncé du point, sans halo.
        val h0 = courant[0]
        val ds = if (doux) 0.55f else 1f
        val dl = if (doux) 0.7f else 1f
        val s0 = courant[1] * ds + (0.22f - courant[1] * ds) * veille
        val l0 = courant[2] * dl + (0.13f - courant[2] * dl) * veille
        val base = hsl(h0, s0, l0, 255)
        if (base != couleurShader) {
            couleurShader = base
            // Shaders construits pour un rayon 1 en (0, 0), placés à chaque image par une matrice.
            shaderHalo = RadialGradient(
                0f, 0f, 1f,
                intArrayOf(hsl(h0, s0, l0, 90), hsl(h0, s0, l0, 28), Color.TRANSPARENT),
                floatArrayOf(0.55f, 0.75f, 1f), Shader.TileMode.CLAMP,
            )
            shaderDisque = RadialGradient(
                0f, 0f, 1f,
                intArrayOf(
                    hsl(h0, s0 * 0.85f, (l0 + 0.22f).coerceAtMost(0.92f), 255),
                    base,
                    hsl(h0, s0, l0 * 0.42f, 255),
                ),
                floatArrayOf(0f, 0.45f, 1f), Shader.TileMode.CLAMP,
            )
        }

        // Halo doux, plus large quand le micro entend.
        val rHalo = r * (1.55f + 0.25f * n)
        matrice.setScale(rHalo, rHalo)
        matrice.postTranslate(cx, cy)
        shaderHalo?.setLocalMatrix(matrice)
        pHalo.shader = shaderHalo
        pHalo.alpha = (255 * (1f - veille) * (if (doux) 0.5f else 1f)).toInt().coerceIn(0, 255)
        if (pHalo.alpha > 0) c.drawCircle(cx, cy, rHalo, pHalo)

        // Particules discrètes autour (accueil, 0.24.0), qui tournent très lentement, à moitié le soir.
        val n0 = if (humeur == Humeur.ECOUTE || humeur == Humeur.REFLEXION || humeur == Humeur.REPONSE) min(particules, 22) else 0
        for (i in 0 until n0) {
            val a = graines[4 * i] + t * 0.05f
            val d = graines[4 * i + 2] * densite
            val x = cx + cos(a) * r * graines[4 * i + 1]
            val y = cy + sin(a) * r * graines[4 * i + 1] * 0.92f
            pParticule.color = hsl(h0, s0 * 0.8f, (l0 * 1.35f).coerceAtMost(0.9f), (255 * graines[4 * i + 3] * (if (doux) 0.5f else 1f) * (1f - veille)).toInt())
            c.drawCircle(x, y, d / 2f, pParticule)
        }

        // Contour qui ondule : trois sinus lents, amplitude de 6 % au repos, jusqu'à 10 % en parlant.
        val amp = if (vivant) 1f + 0.6f * n else 0.4f
        contour.rewind()
        val pas = 96
        for (i in 0..pas) {
            val a = (i % pas) * 2.0 * PI / pas
            val d = amp * (
                0.030 * sin(3 * a + t * 0.9) +
                    0.020 * sin(5 * a - t * 1.3 + 1.7) +
                    0.012 * sin(2 * a + t * 0.5 + 0.6)
                )
            val rr = r * (1f + d.toFloat())
            val x = cx + rr * cos(a).toFloat()
            val y = cy + rr * sin(a).toFloat()
            if (i == 0) contour.moveTo(x, y) else contour.lineTo(x, y)
        }
        contour.close()

        // Disque : lumière décalée en haut à gauche (35 % de la largeur, 30 % de la hauteur).
        val lx = cx - r + 0.70f * r
        val ly = cy - r + 0.60f * r
        val rLumiere = r * 1.55f
        matrice.setScale(rLumiere, rLumiere)
        matrice.postTranslate(lx, ly)
        shaderDisque?.setLocalMatrix(matrice)
        pDisque.shader = shaderDisque
        c.drawPath(contour, pDisque)

        // Liseré plus lumineux sur le bord.
        pBord.strokeWidth = 1.6f * densite
        pBord.color = hsl(h0, s0 * 0.7f, (l0 + 0.28f).coerceAtMost(0.95f), (170 * (1f - veille)).toInt())
        c.drawPath(contour, pBord)

        // Onde sous l'orbe pendant l'écoute, qui suit le niveau du micro.
        if (humeur == Humeur.ECOUTE) {
            val largeur = r * 1.3f
            val y0 = cy + r * 1.42f
            val hauteur = r * 0.16f * (0.15f + 0.85f * n)
            onde.rewind()
            val points = 48
            for (i in 0..points) {
                val u = i / points.toFloat()
                val enveloppe = sin(u * PI).toFloat()
                val y = y0 + hauteur * enveloppe * sin(u * 14f + t * 7f) * (0.7f + 0.3f * sin(u * 5f - t * 3f))
                val x = cx - largeur / 2 + largeur * u
                if (i == 0) onde.moveTo(x, y) else onde.lineTo(x, y)
            }
            pOnde.strokeWidth = 2.2f * densite
            pOnde.color = hsl(courant[0], courant[1], (courant[2] + 0.15f).coerceAtMost(0.9f), 220)
            c.drawPath(onde, pOnde)
        }

        // 30 images par seconde au plus, et seulement quand la vue est visible.
        if (isShown) {
            val reduit = taille == tailleCible && taille < 0.3f && humeur == Humeur.REPOS
            val attente = ((if (reduit) 100L else 33L) - (SystemClock.uptimeMillis() - maintenant)).coerceAtLeast(1L)
            postInvalidateDelayed(attente)
        } else {
            dernierDessin = 0L
        }
    }

    companion object {
        const val TAILLE_PETITE = 0.05f
        /** Écran AOD (0.17.2) : l'orbe se réduit jusqu'au point de Veille.RAYON_POINT_AOD_DP. */
        const val TAILLE_AOD = 0f

        /**
         * Teinte (degrés), saturation et luminosité (0 à 1) de chaque état, charte assistant. Partagées
         * avec le champ de particules (0.17.2), qui prend la couleur de l'orbe.
         */
        fun cibleHsl(h: Humeur): FloatArray = when (h) {
            Humeur.REPOS -> floatArrayOf(218f, 0.55f, 0.56f)
            Humeur.ECOUTE -> floatArrayOf(186f, 0.90f, 0.55f)
            Humeur.REFLEXION -> floatArrayOf(268f, 0.62f, 0.62f)
            // 0.24.0 : bleu d'un projet d'inspiration pour la réponse (revue de l'accueil, l'ambre reste aux lampes).
            Humeur.REPONSE -> floatArrayOf(218f, 0.80f, 0.60f)
            Humeur.ERREUR -> floatArrayOf(2f, 0.62f, 0.40f)
            Humeur.DECONNECTE, Humeur.ARRETE -> floatArrayOf(218f, 0.08f, 0.46f)
        }

        /** Couleur depuis teinte (0 à 360), saturation et luminosité (0 à 1), avec opacité. */
        fun hsl(h: Float, s: Float, l: Float, alpha: Int): Int {
            val c = (1f - abs(2f * l - 1f)) * s
            val hp = (h % 360f) / 60f
            val x = c * (1f - abs(hp % 2f - 1f))
            val (r1, g1, b1) = when {
                hp < 1 -> Triple(c, x, 0f)
                hp < 2 -> Triple(x, c, 0f)
                hp < 3 -> Triple(0f, c, x)
                hp < 4 -> Triple(0f, x, c)
                hp < 5 -> Triple(x, 0f, c)
                else -> Triple(c, 0f, x)
            }
            val m = l - c / 2f
            fun v(k: Float) = ((k + m) * 255f).roundToInt().coerceIn(0, 255)
            return Color.argb(alpha.coerceIn(0, 255), v(r1), v(g1), v(b1))
        }
    }
}
