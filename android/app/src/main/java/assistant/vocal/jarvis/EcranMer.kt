package assistant.vocal.jarvis

import android.animation.ValueAnimator
import android.content.Context
import android.graphics.Canvas
import android.graphics.DashPathEffect
import android.graphics.Paint
import android.graphics.Path
import android.os.SystemClock
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.view.Gravity
import android.view.MotionEvent
import android.view.VelocityTracker
import android.view.View
import android.view.ViewConfiguration
import android.view.animation.DecelerateInterpolator
import android.widget.FrameLayout
import android.widget.LinearLayout
import java.time.LocalDateTime
import java.time.ZonedDateTime
import java.util.Locale
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Page Mer du panneau Météo (0.23.0, maquettes `MeteoMer`, `MeteoMerPharo` et `MeteoMerQuestion` relues le
 * 22/10), sous la page Terre, placée en pixels de maquette par [CadreMaquette] :
 * - en haut, le chevron vers le vent mesuré (0.29.0), le titre du point (« Mer au Prado ») et « Fermer » ;
 * - le vent du moment en grand, en nœuds, sa direction (« Variable » sous 3 nœuds), rafales et AROME, puis la
 *   station à terre du Prado quand sa mesure a moins de 15 min, sinon les vagues et l'eau ;
 * - en haut à droite, la synthèse de la journée de navigation, ou la réponse à la question posée ;
 * - la frise horaire ([FriseMer]) de l'heure en cours à 20 h puis les jours suivants de 7 h à 20 h, et la ligne
 *   de détail de l'heure touchée ou de la plage ;
 * - en bas, les trois points à l'heure choisie (on les touche pour changer de point), puis l'écart des modèles,
 *   les orages, l'eau et le soleil ([CasesMer]) ;
 * - tout en bas, la légende et les sources avec l'heure de lecture.
 * Toutes les valeurs sont calculées par [MeteoMer], données du serveur (message `meteo_mer`).
 */
internal class EcranMer(private val ctx: Context, private val surFermer: () -> Unit, private val surTerre: () -> Unit) {

    val cadre = CadreMaquette(ctx)

    private fun texte(couleur: Int, lignes: Int = 1) = TexteFondu(ctx).apply {
        peinture.typeface = Polices.texte(ctx)
        peinture.color = couleur
        maxLignes = lignes
    }

    private val libelleTerre = texte(Palette.texte2).apply { texte = "Vent mesuré" }
    private val chevron = ChevronPage(ctx, versLeBas = false)
    private val terre = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER
        isClickable = true
        isFocusable = true
        contentDescription = "Revenir au vent mesuré"
        setOnClickListener { surTerre() }
        addView(chevron)
        addView(libelleTerre)
    }
    private val titre = texte(Palette.texte1)
    private val libelleFermer = texte(Palette.texte2).apply { texte = "Fermer" }
    private val fermer = FrameLayout(ctx).apply {
        isClickable = true
        isFocusable = true
        contentDescription = "Fermer la météo"
        setOnClickListener { surFermer() }
        addView(libelleFermer, FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.CENTER))
    }
    private val grand = texte(Palette.meteo).apply {
        police(Polices.chiffres(ctx, 300))
        peinture.letterSpacing = -2f / 150f
    }
    private val unite = texte(Palette.texte2).apply { texte = "nœuds" }
    private val fleche = FlecheVue(ctx)
    private val direction = texte(Palette.texte1)
    private val ligneDirection = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        addView(fleche)
        addView(direction)
    }
    private val ligne2 = texte(Palette.texte2)
    private val ligne3 = texte(Palette.texte2)
    private val infos = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        addView(ligneDirection)
        addView(ligne2)
        addView(ligne3)
    }
    private val chiffre = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.BOTTOM
        addView(grand)
        addView(unite)
    }
    private val bloc = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        addView(chiffre)
        addView(infos)
    }
    private val entete = texte(Palette.meteo).apply { visibility = View.GONE }
    private val synthese = texte(Palette.texte1, 5).apply { interligne = 1.16f / 1.22f }
    private val blocSynthese = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        addView(entete)
        addView(synthese)
    }
    private val frise = FriseMer(ctx).apply { surChoix = { choisir(it) } }
    private val detail = texte(Palette.texte2)
    private val cases = CasesMer(ctx).apply { surPoint = { changerPoint(it) } }
    private val legende = texte(Palette.texte3).apply { texte = "Barre : vent moyen, rafales en transparence, trait : ${MeteoMer.NOM_SECOND}. Vagues : hauteur et période, clapot de la brise non prévu." }
    private val sources = texte(Palette.texte3)

    private var d: MeteoMer.Donnees? = null
    private var erreur = ""
    private var point = MeteoMer.DEFAUT
    private var demande: MeteoQuestion.Reponse? = null
    private var colonnes: List<MeteoMer.Colonne> = emptyList()

    init {
        val n = Float.NaN
        val P = CadreMaquette::Place
        cadre.setBackgroundColor(Palette.fond)
        cadre.addView(terre, P(520f, 0f, n, n, 240f, 48f))
        cadre.addView(FrameLayout(ctx).apply {
            addView(titre, FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.CENTER_VERTICAL))
        }, P(72f, 28f, n, n, 600f, 48f))
        cadre.addView(fermer, P(n, 28f, 66f, n, n, 48f))
        cadre.addView(bloc, P(72f, 84f, n, n, 660f, n))
        cadre.addView(blocSynthese, P(744f, 88f, n, n, 464f, n))
        cadre.addView(frise, P(72f, 262f, n, n, 1136f, 296f))
        cadre.addView(detail, P(72f, 566f, n, n, 1136f, n))
        cadre.addView(cases, P(72f, 606f, n, n, 1136f, 144f))
        cadre.addView(legende, P(72f, 756f, n, n, 1136f, n))
        cadre.addView(sources, P(72f, 775f, n, n, 1136f, n))
        cadre.surEchelle = { appliquer(it) }
        appliquer(cadre.echelle)
    }

    fun appliquer(s: Float) {
        fun lp(v: View, haut: Float = 0f, gauche: Float = 0f, bas: Float = 0f) {
            (v.layoutParams as? LinearLayout.LayoutParams ?: LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT))
                .also { it.topMargin = (haut * s).toInt(); it.marginStart = (gauche * s).toInt(); it.bottomMargin = (bas * s).toInt(); v.layoutParams = it }
        }
        libelleTerre.taille(16f * s)
        chevron.echelle = s
        lp(libelleTerre, 0f, 8f)
        titre.taille(24f * s)
        libelleFermer.taille(18f * s)
        fermer.minimumWidth = max((60 * s).toInt(), Decor.dp(ctx, 48f))
        grand.taille(150f * s)
        unite.taille(26f * s)
        lp(unite, 0f, 10f, 26f)
        fleche.echelle = s
        direction.taille(30f * s)
        lp(direction, 0f, 10f)
        ligne2.taille(19f * s)
        lp(ligne2, 6f)
        ligne3.taille(17f * s)
        lp(ligne3, 6f)
        lp(infos, 0f, 26f)
        entete.taille(19f * s)
        synthese.taille(30f * s)
        lp(synthese, if (entete.visibility == View.VISIBLE) 8f else 0f)
        frise.echelle = s
        detail.taille(18f * s)
        cases.echelle = s
        legende.taille(13f * s)
        sources.taille(13f * s)
    }

    /** Page rouverte : le point de la question, ou celui d'avant, en attendant les données. */
    fun ouvrir(q: MeteoQuestion.Reponse?) {
        demande = q
        if (q != null) point = q.point
        d = null
        erreur = ""
        colonnes = emptyList()
        frise.donnees(emptyList(), null, null)
        cases.donnees(emptyList(), point, emptyList(), "")
        titre.texte = MeteoMer.titre(point)
        grand.texte = ""
        unite.visibility = View.INVISIBLE
        fleche.visibility = View.INVISIBLE
        direction.texte = ""
        ligne2.texte = ""
        ligne3.texte = ""
        entete.visibility = if (q == null) View.GONE else View.VISIBLE
        entete.texte = q?.entete ?: ""
        synthese.texte = ""
        detail.couleur(Palette.texte3)
        detail.texte = "Lecture des prévisions en mer"
        sources.texte = ""
        appliquer(cadre.echelle)
    }

    /** Mesures du vent (0.29.0), pour la ligne du bloc du moment. */
    private var vent: MeteoVent.Donnees? = null

    fun mesures(v: MeteoVent.Donnees?) {
        if (v == null) return
        vent = v
        if (d != null) montrer()
    }

    /** Données reçues du serveur, ou null avec la raison. */
    fun donnees(donnees: MeteoMer.Donnees?, raison: String) {
        d = donnees
        erreur = raison
        montrer()
    }

    private fun changerPoint(id: String) {
        if (id == point) return
        point = id
        // La réponse portait sur un autre point : elle s'efface, la synthèse revient.
        demande = null
        entete.visibility = View.GONE
        appliquer(cadre.echelle)
        montrer()
    }

    private fun montrer() {
        val donnees = d
        titre.texte = MeteoMer.titre(point)
        if (donnees == null) {
            grand.texte = ""
            unite.visibility = View.INVISIBLE
            fleche.visibility = View.INVISIBLE
            synthese.texte = "Mer indisponible."
            detail.couleur(Palette.texte3)
            detail.texte = MeteoQuestion.majuscule(erreur.ifBlank { "pas de donnée" })
            return
        }
        val p = donnees.point(point) ?: return
        val maintenant = ZonedDateTime.now()
        val h = MeteoMer.maintenant(p, maintenant)
        grand.texte = h?.vent?.roundToInt()?.toString() ?: ""
        unite.visibility = if (h?.vent != null) View.VISIBLE else View.INVISIBLE
        val variable = h?.vent == null || h.dir == null || h.vent < MeteoMer.VARIABLE
        fleche.regler(h?.dir, if (variable) Palette.texte3 else Palette.texte1)
        fleche.visibility = if (h?.dir != null) View.VISIBLE else View.INVISIBLE
        direction.texte = MeteoMer.direction(h?.vent, h?.dir)
        ligne2.texte = MeteoMer.ligneRafales(h)
        // 0.29.0 : la mesure d'une balise du point d'abord, la station à terre ou les vagues sinon.
        ligne3.texte = MeteoVent.ligneMesure(vent, point, maintenant.toEpochSecond()) ?: MeteoMer.ligneMesure(point, donnees, h, maintenant)
        colonnes = MeteoMer.colonnes(p, maintenant)
        val coucher = donnees.soleil.firstOrNull { it.jour == maintenant.withZoneSameInstant(MeteoMer.ZONE).toLocalDate() }?.coucher
        frise.donnees(colonnes, coucher?.let { maintenant.withZoneSameInstant(MeteoMer.ZONE).toLocalDate().atTime(it) },
            maintenant.withZoneSameInstant(MeteoMer.ZONE).toLocalDateTime().withMinute(0).withSecond(0).withNano(0))
        val q = demande?.takeIf { it.point == point }
        val w = MeteoMer.journee(p, maintenant)
        val lignes = if (q != null) q.lignes else {
            val quand = if (w.firstOrNull()?.t?.toLocalDate() == maintenant.withZoneSameInstant(MeteoMer.ZONE).toLocalDate()) "aujourd'hui" else "demain"
            MeteoMer.synthese(w, quand).lignes
        }
        synthese.texte = texteLignes(lignes)
        sources.texte = MeteoMer.sources(donnees)
        if (colonnes.isEmpty()) {
            detail.couleur(Palette.texte3)
            detail.texte = "Pas de prévision en mer"
            cases.donnees(donnees.points, point, MeteoMer.cases(donnees, w, null, maintenant), "")
            return
        }
        detail.couleur(Palette.texte2)
        if (q != null && q.bandeDebut != null && q.bandeFin != null) {
            val zone = MeteoMer.ZONE
            val i0 = colonnes.indexOfFirst { it.h.t.atZone(zone).toInstant().toEpochMilli() >= q.bandeDebut }
            val i1 = colonnes.indexOfLast { it.h.t.atZone(zone).toInstant().toEpochMilli() < q.bandeFin }
            frise.mettreEnAvant(if (i0 >= 0 && i1 >= i0) i0..i1 else null)
            val c = q.choisi?.let { x -> colonnes.indexOfFirst { it.h.t.atZone(zone).toInstant().toEpochMilli() == x } }?.takeIf { it >= 0 }
                ?: max(0, i0)
            frise.choisir(c, defiler = false)
            if (i0 >= 0) frise.defilerA(max(0, i0 - 2))
            detail.texte = tete(q.detail.first, q.detail.second)
        } else {
            frise.mettreEnAvant(null)
            // Sans question : l'heure la plus ventée de la journée, comme la maquette (15 h).
            val c = w.maxByOrNull { it.vent ?: 0.0 }?.let { x -> colonnes.indexOfFirst { it.h.t == x.t } }?.takeIf { it >= 0 } ?: 0
            frise.choisir(c, defiler = false)
        }
    }

    /** Heure choisie dans la frise : ligne de détail et cases des points à cette heure. */
    private fun choisir(i: Int) {
        val donnees = d ?: return
        val c = colonnes.getOrNull(i) ?: return
        val (h, reste) = MeteoMer.detail(c.h)
        detail.couleur(Palette.texte2)
        detail.texte = tete(h, reste)
        val p = donnees.point(point) ?: return
        val maintenant = ZonedDateTime.now()
        val jour = java.time.temporal.ChronoUnit.DAYS.between(maintenant.withZoneSameInstant(MeteoMer.ZONE).toLocalDate(), c.h.t.toLocalDate()).toInt()
        cases.donnees(donnees.points, point, MeteoMer.cases(donnees, MeteoMer.journee(p, maintenant, jour), c.h, maintenant), "${c.h.t.hour} h", c.h.t)
    }

    private fun texteLignes(l: List<String>): CharSequence {
        val sb = SpannableStringBuilder()
        for ((i, p) in l.withIndex()) {
            if (sb.isNotEmpty()) sb.append('\n')
            val debut = sb.length
            sb.append(p)
            if (i == l.size - 1 && l.size > 1) sb.setSpan(ForegroundColorSpan(Palette.texte2), debut, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        }
        return sb
    }

    private fun tete(h: String, reste: String): CharSequence {
        val sb = SpannableStringBuilder(h)
        sb.setSpan(ForegroundColorSpan(Palette.texte1), 0, h.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        sb.append(reste)
        return sb
    }
}

/**
 * Frise de la page Mer : heure, grande flèche du vent (là où il va, grise quand il est variable), vent moyen,
 * « nœuds » sous la première colonne, rafales, barre du vent (moyen plein, rafales en transparence au-dessus,
 * trait blanc d'AROME) sur une échelle commune de 12 nœuds au moins, vagues et période, pluie ou orage s'il y
 * en a. Repères « Maintenant », le nom du jour à chaque nuit sautée, coucher du soleil en pointillé.
 */
internal class FriseMer(ctx: Context) : FriseHoraire(ctx) {

    private var colonnes: List<MeteoMer.Colonne> = emptyList()
    private var coucher: LocalDateTime? = null
    private var heureEnCours: LocalDateTime? = null
    private var echelleVent = 12.0

    override val nombre: Int get() = colonnes.size

    private val pTexte = android.text.TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = Polices.texte(ctx)
        textAlign = Paint.Align.CENTER
    }
    private val pFort = android.text.TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = Polices.texte(ctx, 500)
        textAlign = Paint.Align.CENTER
    }
    private val pGauche = android.text.TextPaint(Paint.ANTI_ALIAS_FLAG).apply { typeface = Polices.texte(ctx) }
    private val pTirets = Paint().apply { style = Paint.Style.STROKE }

    init {
        contentDescription = "Vent et vagues heure par heure"
    }

    fun donnees(c: List<MeteoMer.Colonne>, coucherDuSoleil: LocalDateTime?, enCours: LocalDateTime?) {
        colonnes = c
        coucher = coucherDuSoleil
        heureEnCours = enCours
        val g = c.mapNotNull { it.h.rafales ?: it.h.vent }.maxOrNull() ?: 0.0
        echelleVent = max(12.0, kotlin.math.ceil(g / 4.0) * 4.0)
        remettre()
        bande = null
        invalidate()
    }

    fun mettreEnAvant(b: IntRange?) {
        bande = b
        invalidate()
    }

    override fun onDraw(c: Canvas) {
        if (colonnes.isEmpty()) return
        val s = echelle
        val w = COLONNE * s
        val i0 = premiereVisible()
        val i1 = derniereVisible()
        c.save()
        c.clipRect(0, 0, width, height)
        c.translate(-decalage, 0f)
        fonds(c, i0, i1)
        // Repères : le jour après chaque nuit sautée, le coucher du soleil en pointillé, « Maintenant ».
        for ((i, col) in colonnes.withIndex()) {
            if (!col.saut || i < i0 || i > i1) continue
            pPlein.color = Palette.filet
            c.drawRect(i * w, 0f, i * w + max(1f, s * 0.5f), 296f * s, pPlein)
            pGauche.textSize = 16f * s
            pGauche.color = Palette.texte2
            val premier = colonnes.indexOfFirst { it.saut } == i
            val nom = if (premier && colonnes.first().h.t.toLocalDate().plusDays(1) == col.h.t.toLocalDate()) "Demain"
            else MeteoQuestion.majuscule(MeteoQuestion.nomJour(col.h.t.toLocalDate()))
            c.drawText(nom, i * w + 8f * s, base(pGauche, 2f * s, 16f * s), pGauche)
        }
        coucher?.let { k ->
            val i = colonnes.indexOfFirst { it.h.t.toLocalDate() == k.toLocalDate() && it.h.t.hour == k.hour }
            if (i >= 0) {
                val x = (i + k.minute / 60f) * w
                pTirets.color = Palette.filet
                pTirets.strokeWidth = max(1f, s * 0.75f)
                pTirets.pathEffect = DashPathEffect(floatArrayOf(3f * s, 3f * s), 0f)
                c.drawLine(x, 22f * s, x, 296f * s, pTirets)
                pTirets.pathEffect = null
                pGauche.textSize = 16f * s
                pGauche.color = Palette.texte2
                c.drawText("Coucher ${k.hour} h ${k.minute.toString().padStart(2, '0')}", x + 6f * s, base(pGauche, 2f * s, 16f * s), pGauche)
            }
        }
        val enCours = colonnes.first().h.t == heureEnCours
        if (enCours) {
            pGauche.textSize = 16f * s
            pGauche.color = Palette.meteo
            c.drawText("Maintenant", 8f * s, base(pGauche, 2f * s, 16f * s), pGauche)
        }
        for (i in i0..i1) colonne(c, i, colonnes[i].h, i * w, s, enCours)
        c.restore()
        fondu(c)
    }

    private fun colonne(c: Canvas, i: Int, h: MeteoMer.Heure, x: Float, s: Float, enCours: Boolean) {
        val cx = x + 33f * s
        val haut = 24f * s
        val dans = dansBande(i)
        val fort = (i == 0 && enCours) || i == choisi || dans
        pTexte.textSize = 16f * s
        pTexte.color = when {
            i == 0 && enCours -> Palette.meteo
            i == choisi -> Palette.texte1
            dans -> Palette.texte2
            else -> Palette.texte3
        }
        c.drawText("${h.t.hour} h", cx, base(pTexte, haut, 16f * s), pTexte)
        // Flèche du vent : là où il va, grise quand il est variable.
        val v = h.vent
        if (h.dir != null) {
            val couleur = if (v == null || v < MeteoMer.VARIABLE) Palette.texte3 else if (fort) Palette.texte1 else Palette.texte2
            PictosMeteo.flecheVent(c, cx, haut + 39f * s, 30f * s, ((h.dir + 180) % 360).toFloat(), couleur, 0.9f)
        }
        if (v != null) {
            pFort.textSize = 22f * s
            pFort.color = if (fort) Palette.texte1 else Palette.texte2
            c.drawText(v.roundToInt().toString(), cx, base(pFort, haut + 58f * s, 22f * s), pFort)
        }
        if (i == 0) {
            pTexte.textSize = 14f * s
            pTexte.color = Palette.texte2
            c.drawText("nœuds", cx, base(pTexte, haut + 86f * s, 14f * s), pTexte)
        }
        h.rafales?.let { g ->
            pTexte.textSize = 15f * s
            pTexte.color = if (dans) Palette.texte1 else Palette.texte2
            val t = g.roundToInt().toString()
            val lt = pTexte.measureText(t)
            val total = 13f * s + 3f * s + lt
            val gauche = cx - total / 2f
            PictosMeteo.rafale(c, gauche, haut + 106f * s + (1.22f * 15f - 10f) / 2f * s, 13f * s, pTexte.color)
            c.drawText(t, gauche + 16f * s + lt / 2f, base(pTexte, haut + 106f * s, 15f * s), pTexte)
        }
        // Barre : moyen plein, rafales en transparence au-dessus, trait d'AROME.
        val k = 66.0 / echelleVent
        val bas = haut + 196f * s
        val hb = max(2.0, (v ?: 0.0) * k).toFloat() * s
        val hr = max(hb / s, ((h.rafales ?: 0.0) * k).toFloat()) * s
        if (v != null) {
            pPlein.color = Palette.meteo
            pPlein.alpha = (255 * 0.45f).toInt()
            r.set(x + 22f * s, bas - hr, x + 44f * s, bas - hb)
            if (hr > hb) c.drawRoundRect(r, 3f * s, 3f * s, pPlein)
            pPlein.alpha = 255
            r.set(x + 22f * s, bas - hb, x + 44f * s, bas)
            c.drawRoundRect(r, 3f * s, 3f * s, pPlein)
        }
        h.vent2?.let { v2 ->
            pPlein.color = Palette.texte1
            val y = bas - (v2 * k).toFloat() * s
            r.set(x + 17f * s, y - 1f * s, x + 49f * s, y + 1f * s)
            c.drawRoundRect(r, 1f * s, 1f * s, pPlein)
        }
        // Vagues et période.
        h.vagues?.let { vg ->
            pTexte.textSize = 16f * s
            pTexte.color = if (dans) Palette.texte1 else Palette.texte2
            c.drawText(String.format(Locale.FRANCE, "%.1f", vg) + if (i == 0) " m" else "", cx, base(pTexte, haut + 204f * s, 16f * s), pTexte)
        }
        h.periode?.let { p ->
            pTexte.textSize = 15f * s
            pTexte.color = if (dans || i == choisi) Palette.texte2 else Palette.texte3
            c.drawText("${p.roundToInt()} s", cx, base(pTexte, haut + 226f * s, 15f * s), pTexte)
        }
        // Pluie ou orage, seulement s'il y en a.
        val orage = (h.cape ?: 0) >= 1000 || (h.foudre ?: 0.0) > 0.0
        val pluie = (h.pluie ?: 0.0) >= 0.1
        if (orage || pluie) {
            pTexte.textSize = 15f * s
            pTexte.color = if (orage) Palette.texte1 else Palette.accentPluie
            c.drawText(if (orage) "orage" else MeteoTexte.mm(h.pluie!!) + " mm", cx, base(pTexte, haut + 248f * s, 15f * s), pTexte)
        }
    }
}

/**
 * Cases du bas de la page Mer, sur la grille des jours : les trois points à l'heure choisie (on les touche pour
 * changer de point, celui affiché souligné), un filet, puis l'écart des modèles, les orages, l'eau et le soleil.
 */
internal class CasesMer(ctx: Context) : View(ctx) {
    var echelle = CadreMaquette.estimer(ctx)
        set(v) {
            field = v
            invalidate()
        }
    var surPoint: (String) -> Unit = {}
    private var points: List<MeteoMer.Point> = emptyList()
    private var point = MeteoMer.DEFAUT
    private var cases: List<MeteoMer.Case> = emptyList()
    private var heure = ""
    private var instant: LocalDateTime? = null
    private val pTexte = android.text.TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = Polices.texte(ctx)
        textAlign = Paint.Align.CENTER
    }
    private val pGauche = android.text.TextPaint(Paint.ANTI_ALIAS_FLAG)
    private val pPlein = Paint(Paint.ANTI_ALIAS_FLAG)
    private val fm = Paint.FontMetrics()

    init {
        isClickable = true
        contentDescription = "Points en mer et conditions du jour"
    }

    fun donnees(p: List<MeteoMer.Point>, choisi: String, c: List<MeteoMer.Case>, h: String, t: LocalDateTime? = null) {
        points = p
        point = choisi
        cases = c
        heure = h
        instant = t
        invalidate()
    }

    override fun onTouchEvent(ev: MotionEvent): Boolean {
        if (ev.actionMasked == MotionEvent.ACTION_UP) {
            val i = (ev.x / (width / 7f)).toInt()
            val id = MeteoMer.POINTS.getOrNull(i)
            if (id != null && points.any { it.id == id }) {
                point = id
                invalidate()
                surPoint(id)
            }
            performClick()
        }
        return true
    }

    override fun performClick(): Boolean = super.performClick()

    private fun base(p: Paint, haut: Float, px: Float): Float {
        p.getFontMetrics(fm)
        return haut + (1.22f * px - (fm.descent - fm.ascent)) / 2f - fm.ascent
    }

    override fun onDraw(c: Canvas) {
        val s = echelle
        val w = width / 7f
        for ((i, id) in MeteoMer.POINTS.withIndex()) {
            val p = points.firstOrNull { it.id == id } ?: continue
            val h = instant?.let { t -> p.heures.firstOrNull { it.t == t } }
            val cx = w * i + w / 2f
            pTexte.textSize = 18f * s
            pTexte.color = if (id == point) Palette.texte1 else Palette.texte2
            c.drawText(MeteoMer.NOMS[id] ?: p.nom, cx, base(pTexte, 10f * s, 18f * s), pTexte)
            if (h?.vent != null) {
                // Flèche, vent en grand, « nœuds à 15 h ».
                val v = h.vent.roundToInt().toString()
                pGauche.typeface = Polices.chiffres(context, 400)
                pGauche.textSize = 40f * s
                val lv = pGauche.measureText(v)
                pGauche.typeface = Polices.texte(context)
                pGauche.textSize = 15f * s
                val suite = "nœuds à $heure"
                val ls = pGauche.measureText(suite)
                val total = 20f * s + 6f * s + lv + 6f * s + ls
                var x = cx - total / 2f
                val centre = 60f * s
                if (h.dir != null) {
                    val couleur = if (h.vent < MeteoMer.VARIABLE) Palette.texte3 else Palette.texte2
                    PictosMeteo.flecheVent(c, x + 10f * s, centre, 20f * s, ((h.dir + 180) % 360).toFloat(), couleur, 1.1f)
                }
                x += 26f * s
                pGauche.typeface = Polices.chiffres(context, 400)
                pGauche.textSize = 40f * s
                pGauche.color = Palette.texte1
                pGauche.getFontMetrics(fm)
                val ligneBase = centre - (fm.ascent + fm.descent) / 2f
                c.drawText(v, x, ligneBase, pGauche)
                x += lv + 6f * s
                pGauche.typeface = Polices.texte(context)
                pGauche.textSize = 15f * s
                pGauche.color = Palette.texte2
                c.drawText(suite, x, ligneBase, pGauche)
                pTexte.textSize = 16f * s
                pTexte.color = Palette.texte2
                h.rafales?.let { c.drawText("rafales ${it.roundToInt()}", cx, base(pTexte, 88f * s, 16f * s), pTexte) }
                h.vagues?.let { c.drawText("vagues ${String.format(Locale.FRANCE, "%.1f", it)} m", cx, base(pTexte, 112f * s, 16f * s), pTexte) }
            }
            if (id == point) {
                pPlein.color = Palette.texte1
                c.drawRect(w * i, 142f * s, w * i + w, 144f * s, pPlein)
            }
        }
        // Filet entre les cases qu'on touche et les autres.
        pPlein.color = Palette.filet
        c.drawRect(w * 3, 0f, w * 3 + max(1f, s * 0.5f), 144f * s, pPlein)
        for ((k, case) in cases.withIndex()) {
            val cx = w * (3 + k) + w / 2f
            pTexte.textSize = 18f * s
            pTexte.color = Palette.texte2
            c.drawText(case.nom, cx, base(pTexte, 10f * s, 18f * s), pTexte)
            if (case.valeur.isNotEmpty()) {
                pTexte.typeface = if (case.chiffres) Polices.chiffres(context, 400) else Polices.texte(context)
                pTexte.textSize = (if (case.chiffres) 40f else 24f) * s
                pTexte.color = Palette.texte1
                pTexte.getFontMetrics(fm)
                c.drawText(case.valeur, cx, 60f * s - (fm.ascent + fm.descent) / 2f, pTexte)
                pTexte.typeface = Polices.texte(context)
            }
            pTexte.textSize = 16f * s
            pTexte.color = Palette.texte2
            if (case.ligne1.isNotEmpty()) c.drawText(case.ligne1, cx, base(pTexte, 88f * s, 16f * s), pTexte)
            if (case.ligne2.isNotEmpty()) c.drawText(case.ligne2, cx, base(pTexte, 112f * s, 16f * s), pTexte)
        }
    }
}

/**
 * Les deux pages du panneau Météo, l'une sous l'autre (0.23.0) : la page Terre en haut, la page Mer en dessous. Un
 * geste plutôt vertical les fait glisser sous le doigt (doigt vers le haut pour la mer, choix du 22/10),
 * puis elles se calent en 300 ms sur la plus proche, ou sur la suivante après un lancer.
 */
internal class PagesMeteo(ctx: Context) : FrameLayout(ctx) {

    var page = 0
        private set
    private var decalage = 0f
    private var x0 = 0f
    private var y0 = 0f
    private var depart = 0f
    private var glisse = false
    private var vitesse: VelocityTracker? = null
    private var anim: ValueAnimator? = null
    private val seuil = ViewConfiguration.get(ctx).scaledTouchSlop
    private val lancer = ViewConfiguration.get(ctx).scaledMinimumFlingVelocity * 4

    override fun onLayout(changed: Boolean, l: Int, t: Int, r: Int, b: Int) {
        super.onLayout(changed, l, t, r, b)
        if (anim?.isRunning != true && !glisse) decalage = page * height.toFloat()
        placer()
    }

    /** Les pages l'une sous l'autre : chacune visible seulement quand elle entre dans l'écran (0.29.0 : trois pages). */
    private fun placer() {
        val h = height.toFloat()
        for (i in 0 until childCount) {
            val c = getChildAt(i)
            val y = i * h - decalage
            c.translationY = y
            c.visibility = if (h > 0f && abs(y) >= h) View.INVISIBLE else View.VISIBLE
        }
    }

    private val derniere: Int get() = max(0, childCount - 1)

    /** Va sur la page [p] (0 Terre, 1 vent mesuré, 2 prévisions marines), animée ou d'un coup. */
    fun aller(p: Int, anime: Boolean = true) {
        page = p.coerceIn(0, derniere)
        anim?.cancel()
        val cible = page * height.toFloat()
        if (!anime || height == 0) {
            decalage = cible
            placer()
            return
        }
        anim = ValueAnimator.ofFloat(decalage, cible).apply {
            duration = 300
            interpolator = DecelerateInterpolator()
            addUpdateListener {
                decalage = it.animatedValue as Float
                placer()
            }
            start()
        }
    }

    override fun onInterceptTouchEvent(ev: MotionEvent): Boolean {
        when (ev.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                x0 = ev.x
                y0 = ev.y
                glisse = false
                if (anim?.isRunning == true) {
                    anim?.cancel()
                    depart = decalage
                    glisse = true
                    return true
                }
            }
            MotionEvent.ACTION_MOVE -> {
                val dy = ev.y - y0
                val dx = ev.x - x0
                if (abs(dy) > seuil && abs(dy) > abs(dx)) {
                    glisse = true
                    depart = decalage
                    y0 = ev.y
                    parent?.requestDisallowInterceptTouchEvent(true)
                    return true
                }
            }
        }
        return false
    }

    override fun onTouchEvent(ev: MotionEvent): Boolean {
        if (!glisse) {
            when (ev.actionMasked) {
                MotionEvent.ACTION_DOWN -> {
                    x0 = ev.x
                    y0 = ev.y
                    return true
                }
                MotionEvent.ACTION_MOVE -> {
                    val dy = ev.y - y0
                    if (abs(dy) > seuil && abs(dy) > abs(ev.x - x0)) {
                        glisse = true
                        depart = decalage
                        y0 = ev.y
                        parent?.requestDisallowInterceptTouchEvent(true)
                    } else return true
                }
                else -> return false
            }
        }
        if (vitesse == null) vitesse = VelocityTracker.obtain()
        vitesse?.addMovement(ev)
        when (ev.actionMasked) {
            MotionEvent.ACTION_MOVE -> {
                // Une page à la fois depuis celle où le geste a commencé.
                val dep = (depart / max(1, height)).roundToInt()
                decalage = (depart - (ev.y - y0)).coerceIn(max(0, dep - 1) * height.toFloat(), min(derniere, dep + 1) * height.toFloat())
                placer()
            }
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> {
                vitesse?.computeCurrentVelocity(1000)
                val vy = vitesse?.yVelocity ?: 0f
                vitesse?.recycle()
                vitesse = null
                glisse = false
                val dep = (depart / max(1, height)).roundToInt()
                val cible = when {
                    vy < -lancer -> dep + 1
                    vy > lancer -> dep - 1
                    else -> (decalage / max(1, height)).roundToInt()
                }
                aller(cible)
            }
        }
        return true
    }
}

/** Chevron vers le bas (aperçu de la mer) ou vers le haut (retour à la page Terre), 14 x 8 px de maquette. */
internal class ChevronPage(ctx: Context, private val versLeBas: Boolean) : View(ctx) {
    var echelle = CadreMaquette.estimer(ctx)
        set(v) {
            field = v
            requestLayout()
            invalidate()
        }
    private val p = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }
    private val chemin = Path()

    override fun onMeasure(l: Int, h: Int) = setMeasuredDimension((14 * echelle).roundToInt(), (8 * echelle).roundToInt())

    override fun onDraw(c: Canvas) {
        val s = echelle
        p.color = Palette.texte2
        p.strokeWidth = 1.6f * s
        chemin.reset()
        if (versLeBas) {
            chemin.moveTo(1f * s, 1f * s); chemin.lineTo(7f * s, 7f * s); chemin.lineTo(13f * s, 1f * s)
        } else {
            chemin.moveTo(1f * s, 7f * s); chemin.lineTo(7f * s, 1f * s); chemin.lineTo(13f * s, 7f * s)
        }
        c.drawPath(chemin, p)
    }
}

/** Flèche du vent du bloc du moment de la page Mer, 26 px de maquette, grise quand le vent est variable. */
internal class FlecheVue(ctx: Context) : View(ctx) {
    var echelle = CadreMaquette.estimer(ctx)
        set(v) {
            field = v
            requestLayout()
            invalidate()
        }
    private var dir: Int? = null
    private var couleur = Palette.texte1

    fun regler(d: Int?, c: Int) {
        dir = d
        couleur = c
        invalidate()
    }

    override fun onMeasure(l: Int, h: Int) = setMeasuredDimension((26 * echelle).roundToInt(), (26 * echelle).roundToInt())

    override fun onDraw(c: Canvas) {
        val d = dir ?: return
        PictosMeteo.flecheVent(c, width / 2f, height / 2f, 26f * echelle, ((d + 180) % 360).toFloat(), couleur, 1.0f)
    }
}
