package assistant.vocal.jarvis

import android.content.Context
import android.graphics.Canvas
import android.graphics.DashPathEffect
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Shader
import android.os.SystemClock
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.view.GestureDetector
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.OverScroller
import java.time.Instant
import java.time.ZoneId
import java.time.ZonedDateTime
import java.util.Locale
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.floor
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Panneau Météo de la tablette (0.20.0, maquette `Meteo2` relue le 22/10), plein écran sur fond noir,
 * placé en pixels de maquette par [CadreMaquette] :
 * - en haut, « Météo à ... », un point de page par entité météo s'il y en a plusieurs (Lille), « Fermer » ;
 * - la température du moment en grand (teinte météo), le ciel, minimum, maximum et ressenti, puis
 *   humidité, indice UV et coucher (ou lever) du soleil ;
 * - en haut à droite, la phrase de synthèse calculée ([MeteoTexte.synthese]), ou la réponse à la question posée
 *   à la voix (0.23.0, maquettes `MeteoQuestion*`) : ce que assistant a compris, puis la phrase qu'il dit ;
 * - la frise horaire défilante ([FriseMeteo]) sur toute la durée fournie, la plage demandée surlignée en bande et
 *   la ligne du sujet mise en avant, et la ligne de détail de l'heure touchée ou de la plage ;
 * - les jours en sept colonnes ([JoursMeteo]) : toucher un jour fait défiler la frise sur ce jour ;
 * - tout en bas, l'aperçu de la mer (0.23.0) : la page Mer ([EcranMer]) est sous celle-ci, on y va en poussant le
 *   doigt vers le haut ou en touchant l'aperçu ([PagesMeteo]).
 * Ouvert en touchant les phrases de l'accueil, ou à la voix (une question de météo, [MeteoQuestion]).
 * Fermé au bout de 60 s sans toucher, par Retour et par Fermer.
 */
internal class EcranMeteo(private val ctx: Context, private val surFermer: () -> Unit) {

    private val cadre = CadreMaquette(ctx)
    private var toucheLe = 0L
    private val mer: EcranMer = EcranMer(ctx, surFermer) { pages.aller(PAGE_VENT) }
    // 0.29.0 : le vent mesuré entre la page Terre et les prévisions marines.
    private val vent: EcranVent = EcranVent(ctx, surFermer, { pages.aller(PAGE_TERRE) }, { pages.aller(PAGE_MER) })
    private val pages: PagesMeteo = PagesMeteo(ctx).apply {
        addView(cadre, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        // Pages Vent et Mer seulement avec les sections « mer » et « vent » actives (MeteoMer.ACTIF).
        if (MeteoMer.ACTIF) {
            addView(vent.cadre, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
            addView(mer.cadre, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        }
    }

    val vue: FrameLayout = object : FrameLayout(ctx) {
        override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
            toucheLe = SystemClock.elapsedRealtime()
            return super.dispatchTouchEvent(ev)
        }
    }.apply {
        setBackgroundColor(Palette.fond)
        // Le toucher ne traverse pas vers l'accueil.
        isClickable = true
        visibility = View.GONE
        addView(pages, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
    }

    private fun texte(couleur: Int, lignes: Int = 1) = TexteFondu(ctx).apply {
        peinture.typeface = Polices.texte(ctx)
        peinture.color = couleur
        maxLignes = lignes
    }

    private val titre = texte(Palette.texte1)
    private val points = PointsPage(ctx).apply {
        contentDescription = "Autre lieu"
        setOnClickListener { pageSuivante() }
    }
    private val enTete = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        addView(titre)
        addView(points)
    }
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
    private val ciel = texte(Palette.texte1)
    private val ligne2 = texte(Palette.texte2)
    private val ligne3 = texte(Palette.texte3)
    private val infos = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        addView(ciel)
        addView(ligne2)
        addView(ligne3)
    }
    private val bloc = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        addView(grand)
        addView(infos)
    }
    private val synthese = texte(Palette.texte1, 3).apply { interligne = 1.16f / 1.22f }
    // Réponse à la question posée (0.23.0) : ce qui a été compris, puis la phrase dite.
    private val entete = texte(Palette.meteo)
    private val reponse = texte(Palette.texte1, 3).apply { interligne = 1.16f / 1.22f }
    private val blocReponse = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        visibility = View.GONE
        addView(entete)
        addView(reponse)
    }
    private val frise = FriseMeteo(ctx).apply { surChoix = { majDetail(it) } }
    private val detail = texte(Palette.texte2)
    private val rangee = JoursMeteo(ctx).apply { surChoix = { choisirJour(it) } }
    // Aperçu de la mer (0.23.0), sous les jours : y mène aussi.
    private val apercuLieu = texte(Palette.texte1).apply { texte = MeteoMer.titre(MeteoMer.DEFAUT) }
    private val apercuTexte = texte(Palette.texte2)
    private val chevron = ChevronPage(ctx, versLeBas = true)
    private val apercu = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER
        isClickable = true
        isFocusable = true
        contentDescription = "Voir la météo de la mer"
        setOnClickListener { pages.aller(PAGE_VENT) }
        addView(apercuLieu)
        addView(apercuTexte)
        addView(chevron)
        if (!MeteoMer.ACTIF) visibility = android.view.View.GONE
    }

    private var entite: String? = null
    private var tour = 0
    private var tourMer = 0
    private var tourVent = 0
    private var ventLuLe = 0L
    private var apercuMesure: String? = null
    private var apercuPrevision: String? = null
    private var secondes = 0
    private var colonnes: List<MeteoTexte.Colonne> = emptyList()
    private var jours: List<MeteoTexte.Jour> = emptyList()
    private var uniteVent = "km/h"
    private var demande: MeteoQuestion.Reponse? = null

    init {
        val n = Float.NaN
        val P = CadreMaquette::Place
        cadre.addView(enTete, P(72f, 28f, n, n, n, 48f))
        cadre.addView(fermer, P(n, 28f, 66f, n, n, 48f))
        cadre.addView(bloc, P(72f, 84f, n, n, n, n))
        cadre.addView(synthese, P(760f, 92f, n, n, 448f, n))
        cadre.addView(blocReponse, P(760f, 88f, n, n, 448f, n))
        cadre.addView(frise, P(72f, 262f, n, n, 1136f, 296f))
        cadre.addView(detail, P(72f, 566f, n, n, 1136f, n))
        cadre.addView(rangee, P(72f, 612f, n, n, 1136f, 140f))
        cadre.addView(apercu, P(290f, 752f, n, n, 700f, 48f))
        cadre.surEchelle = { appliquer(it) }
        appliquer(cadre.echelle)
    }

    private fun appliquer(s: Float) {
        fun lp(v: View, haut: Float = 0f, gauche: Float = 0f) {
            (v.layoutParams as? LinearLayout.LayoutParams ?: LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT))
                .also { it.topMargin = (haut * s).toInt(); it.marginStart = (gauche * s).toInt(); v.layoutParams = it }
        }
        titre.taille(24f * s)
        points.echelle = s
        lp(points, 0f, 18f)
        libelleFermer.taille(18f * s)
        fermer.minimumWidth = max((60 * s).toInt(), Decor.dp(ctx, 48f))
        grand.taille(150f * s)
        ciel.taille(30f * s)
        ligne2.taille(19f * s)
        lp(ligne2, 6f)
        ligne3.taille(17f * s)
        lp(ligne3, 6f)
        lp(infos, 0f, 30f)
        synthese.taille(38f * s)
        entete.taille(19f * s)
        reponse.taille(38f * s)
        lp(reponse, 8f)
        frise.echelle = s
        detail.taille(18f * s)
        rangee.echelle = s
        apercuLieu.taille(18f * s)
        apercuTexte.taille(18f * s)
        lp(apercuTexte, 0f, 10f)
        chevron.echelle = s
        lp(chevron, 0f, 10f)
        mer.appliquer(s)
        vent.appliquer(s)
    }

    // ------------------------------------------------------------ cycle

    val ouvert: Boolean get() = vue.visibility == View.VISIBLE

    /**
     * Ouvre le panneau et lit les prévisions. [d] : la réponse à une question posée à la voix (0.23.0), qui choisit
     * la page, le lieu, le jour, la bande et le bloc de réponse. Sans elle, la page Terre et sa synthèse.
     */
    fun ouvrir(d: MeteoQuestion.Reponse? = null) {
        demande = d
        entite = d?.lieu?.let { l -> Etat.courant.meteos.firstOrNull { MeteoTexte.lieu(it.second) == l }?.first }
        toucheLe = SystemClock.elapsedRealtime()
        vue.visibility = View.VISIBLE
        pages.aller(when (d?.page) {
            MeteoQuestion.Page.MER -> PAGE_MER
            MeteoQuestion.Page.VENT -> PAGE_VENT
            else -> PAGE_TERRE
        }, anime = false)
        val m = Etat.courant.meteo
        // 0.21.1 : un panneau rouvert ne montre pas l'ancienne lecture comme actuelle, il recharge tout.
        colonnes = emptyList()
        jours = emptyList()
        frise.donnees(emptyList(), emptyList())
        frise.mettreEnAvant(null, null)
        rangee.donnees(emptyList())
        synthese.texte = ""
        ligne2.texte = ""
        ligne3.texte = ""
        majReponse()
        run {
            titre.texte = MeteoTexte.titre(Etat.courant.meteos.firstOrNull { it.first == (entite ?: m?.entite) }?.second ?: "")
            grand.texte = MeteoTexte.degres(m?.temperature?.let { Regex("""-?\d+(?:[.,]\d+)?""").find(it)?.value?.replace(',', '.')?.toDoubleOrNull() })
            ciel.texte = m?.etat?.replaceFirstChar { it.titlecase(Locale.FRANCE) } ?: ""
            detail.texte = "Lecture des prévisions"
            detail.couleur(Palette.texte3)
        }
        apercuMesure = null
        apercuPrevision = null
        majApercu()
        mer.ouvrir(d?.takeIf { it.page == MeteoQuestion.Page.MER })
        vent.ouvrir(d?.takeIf { it.page == MeteoQuestion.Page.VENT })
        majPoints()
        charger()
        chargerMer()
        chargerVent()
    }

    fun fermer() {
        vue.visibility = View.GONE
        demande = null
        pages.aller(0, anime = false)
    }

    /** Toutes les secondes : fermeture au bout de 60 s sans toucher, mesures relues toutes les 2 min sur leur page. */
    fun tic() {
        if (ouvert && SystemClock.elapsedRealtime() - toucheLe > FERMETURE_MS) surFermer()
        else if (ouvert && pages.page == PAGE_VENT && SystemClock.elapsedRealtime() - ventLuLe > RELECTURE_VENT_MS) chargerVent()
        else if (ouvert && pages.page == PAGE_VENT && ++secondes % 60 == 0) vent.rafraichir()
    }

    private fun majPoints() {
        val l = Etat.courant.meteos
        val i = l.indexOfFirst { it.first == (entite ?: Etat.courant.meteo?.entite) }.coerceAtLeast(0)
        points.regler(l.size, i)
        points.visibility = if (l.size >= 2) View.VISIBLE else View.GONE
    }

    private fun pageSuivante() {
        val l = Etat.courant.meteos
        if (l.size < 2) return
        val i = l.indexOfFirst { it.first == (entite ?: Etat.courant.meteo?.entite) }
        entite = l[(i + 1).mod(l.size)].first
        // La réponse portait sur l'autre lieu : elle s'efface.
        demande = demande?.takeIf { it.page == MeteoQuestion.Page.MER }
        majReponse()
        frise.mettreEnAvant(null, null)
        colonnes = emptyList()
        majPoints()
        charger()
    }

    private fun charger() {
        val t = ++tour
        val suite: (Previsions.Lecture) -> Unit = { l -> if (t == tour && ouvert) montrer(l) }
        val e = entite
        if (e != null) Etat.actionPrevisionsDe?.invoke(e, suite) ?: suite(Previsions.Lecture(erreur = "assistant arrêté"))
        else Etat.actionPrevisions?.invoke(suite) ?: suite(Previsions.Lecture(erreur = "assistant arrêté"))
    }

    /** Données de la mer (0.23.0), demandées au serveur à chaque ouverture : page Mer et aperçu. */
    private fun chargerMer() {
        val t = ++tourMer
        val a = Etat.actionMeteoMer
        val suite: (org.json.JSONObject?) -> Unit = { r ->
            if (t == tourMer && ouvert) {
                val (d, erreur) = MeteoMer.lire(r)
                val maintenant = ZonedDateTime.now()
                apercuPrevision = d?.let { MeteoMer.apercu(it, maintenant) }
                majApercu()
                mer.donnees(d, if (r == null && a == null) "aucun serveur ne la fournit" else erreur)
                vent.previsionsMer(d)
            }
        }
        if (a == null) suite(null) else a(suite)
    }

    /** Mesures du vent dans le golfe (0.29.0) : page du vent mesuré, aperçu et bloc du moment des prévisions. */
    private fun chargerVent() {
        val t = ++tourVent
        ventLuLe = SystemClock.elapsedRealtime()
        val a = Etat.actionVentMesure
        val suite: (org.json.JSONObject?) -> Unit = { r ->
            if (t == tourVent && ouvert) {
                val (d, erreur) = MeteoVent.lire(r)
                vent.donnees(d, if (r == null && a == null) "aucun serveur ne les fournit" else erreur)
                mer.mesures(d)
                // Relecture qui échoue : l'aperçu se recalcule sur les mesures gardées, dont l'âge avance.
                apercuMesure = (d ?: vent.actuelles)?.let { MeteoVent.apercu(it, ZonedDateTime.now().toEpochSecond()) }
                majApercu()
            }
        }
        if (a == null) suite(null) else a(suite)
    }

    /** Aperçu du bas de la page Terre : la mesure d'abord, la prévision à défaut. */
    private fun majApercu() {
        val m = apercuMesure
        apercuLieu.texte = if (m != null) "Vent en mer" else MeteoMer.titre(MeteoMer.DEFAUT)
        apercuTexte.texte = m ?: apercuPrevision ?: ""
    }

    // ------------------------------------------------------------ contenu

    /** Bloc de réponse à la place de la synthèse quand une question de la page Terre a ouvert le panneau. */
    private fun majReponse() {
        val d = demande?.takeIf { it.page == MeteoQuestion.Page.TERRE }
        synthese.visibility = if (d == null) View.VISIBLE else View.GONE
        blocReponse.visibility = if (d == null) View.GONE else View.VISIBLE
        if (d == null) return
        entete.texte = d.entete
        reponse.texte = lignes(d.lignes)
    }

    private fun montrer(l: Previsions.Lecture) {
        val maintenant = ZonedDateTime.now()
        val zone = maintenant.zone
        val a = l.actuel
        uniteVent = a?.uniteVent ?: "km/h"
        val nom = a?.nom?.takeIf { it.isNotBlank() } ?: Etat.courant.meteos.firstOrNull { it.first == (entite ?: Etat.courant.meteo?.entite) }?.second ?: ""
        titre.texte = MeteoTexte.titre(nom)
        colonnes = MeteoTexte.colonnes(l.horaire, maintenant, l.soleil?.lever, l.soleil?.coucher)
        jours = MeteoTexte.jours(l.journalier, maintenant.toLocalDate(), zone)
        val aujourdhui = jours.firstOrNull { it.date == maintenant.toLocalDate() }
        val t = a?.temperature ?: colonnes.firstOrNull()?.temperature
        grand.texte = MeteoTexte.degres(t)
        ciel.texte = a?.condition?.let { Maison.meteoEnFrancais(it).replaceFirstChar { c -> c.titlecase(Locale.FRANCE) } } ?: ""
        ligne2.texte = majuscule(listOfNotNull(
            aujourdhui?.min?.let { "minimum ${MeteoTexte.degres(it)}" },
            aujourdhui?.max?.let { "maximum ${MeteoTexte.degres(it)}" },
            a?.ressenti?.let { "ressenti ${MeteoTexte.degres(it)}" },
        ).joinToString(", "))
        val s = l.soleil
        val soleil = when {
            s?.coucher != null && (s.lever == null || s.coucher < s.lever) -> "coucher à ${MeteoTexte.heureMinute(s.coucher, zone)}"
            s?.lever != null -> "lever à ${MeteoTexte.heureMinute(s.lever, zone)}"
            else -> null
        }
        ligne3.texte = majuscule(listOfNotNull(a?.humidite?.let { "humidité $it %" }, a?.uv?.let { MeteoTexte.uv(it) }, soleil).joinToString(", "))
        synthese.texte = lignes(MeteoTexte.synthese(l.horaire, jours, l.journalier, maintenant), seulementDemain = true)
        frise.uniteVent = uniteVent
        frise.donnees(colonnes, couchers(s?.coucher, zone))
        rangee.donnees(jours)
        if (colonnes.isEmpty()) {
            detail.texte = l.erreur.ifBlank { "Pas de prévision horaire" }
            detail.couleur(Palette.texte3)
        } else {
            detail.couleur(Palette.texte2)
            frise.choisir(0, defiler = false)
        }
        rangee.choisi = 0
        val d = demande?.takeIf { it.page == MeteoQuestion.Page.TERRE }
        if (d != null) montrerDemande(d)
    }

    /** La question posée : jour choisi, bande et sujet dans la frise, heure choisie, détail de la plage. */
    private fun montrerDemande(d: MeteoQuestion.Reponse) {
        val k = jours.indexOfFirst { it.date == d.jour }
        if (k >= 0) rangee.choisi = k
        val debut = d.bandeDebut
        val fin = d.bandeFin
        val i0 = if (debut == null) -1 else colonnes.indexOfFirst { it.instant >= debut }
        val i1 = if (fin == null) -1 else colonnes.indexOfLast { it.instant < fin }
        if (i0 >= 0 && i1 >= i0) {
            frise.mettreEnAvant(i0..i1, d.sujet)
            val c = d.choisi?.let { x -> colonnes.indexOfFirst { it.instant == x } }?.takeIf { it >= 0 } ?: i0
            frise.choisir(c, defiler = false)
            frise.defilerA(max(0, i0 - 2))
        } else if (k >= 0) {
            // Jour hors de la frise : pas de bande, la frise va sur ce jour s'il y figure.
            val zone = ZoneId.systemDefault()
            val c = colonnes.indexOfFirst { Instant.ofEpochMilli(it.instant).atZone(zone).toLocalDate() == d.jour }
            if (c >= 0) {
                frise.choisir(c, defiler = false)
                frise.defilerA(c)
            }
        }
        if (colonnes.isNotEmpty() || d.detail.first.isNotEmpty()) {
            detail.couleur(Palette.texte2)
            detail.texte = tete(d.detail.first, d.detail.second)
        }
    }

    /** Lignes de texte, la dernière en texte secondaire (toutes, ou seulement celle de demain pour la synthèse). */
    private fun lignes(l: List<String>, seulementDemain: Boolean = false): CharSequence {
        val sb = SpannableStringBuilder()
        for ((i, p) in l.withIndex()) {
            if (sb.isNotEmpty()) sb.append('\n')
            val d = sb.length
            sb.append(p)
            val secondaire = i == l.size - 1 && l.size > 1 && (!seulementDemain || p.startsWith("Demain"))
            if (secondaire) sb.setSpan(ForegroundColorSpan(Palette.texte2), d, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        }
        return sb
    }

    private fun tete(h: String, reste: String): CharSequence {
        val sb = SpannableStringBuilder(h)
        sb.setSpan(ForegroundColorSpan(Palette.texte1), 0, h.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        sb.append(reste)
        return sb
    }

    /** Couchers du soleil dans la durée de la frise : colonne, part de l'heure (minutes), libellé. */
    private fun couchers(coucher: Long?, zone: ZoneId): List<Pair<Float, String>> {
        if (coucher == null || colonnes.isEmpty()) return emptyList()
        val sortie = ArrayList<Pair<Float, String>>()
        var c = coucher
        while (c > colonnes.first().instant + 3_600_000L) c -= 24 * 3_600_000L
        val fin = colonnes.last().instant + 3_600_000L
        while (c < fin) {
            if (c >= colonnes.first().instant) {
                val i = colonnes.indexOfLast { it.instant <= c }
                if (i >= 0) {
                    val minutes = Instant.ofEpochMilli(c).atZone(zone).minute
                    sortie.add((i + minutes / 60f) to "Coucher ${MeteoTexte.heureMinute(c, zone)}")
                }
            }
            c += 24 * 3_600_000L
        }
        return sortie
    }

    private fun majDetail(i: Int) {
        val c = colonnes.getOrNull(i) ?: return
        val (h, reste) = MeteoTexte.detail(c, uniteVent)
        detail.texte = tete(h, reste)
    }

    private fun choisirJour(i: Int) {
        val j = jours.getOrNull(i) ?: return
        rangee.choisi = i
        val zone = ZoneId.systemDefault()
        // Par la date du jour : la première colonne de ce jour (celle du moment pour aujourd'hui).
        val k = colonnes.indexOfFirst { Instant.ofEpochMilli(it.instant).atZone(zone).toLocalDate() == j.date }
        if (k >= 0) frise.choisir(k, defiler = true)
    }

    private fun majuscule(s: String) = s.replaceFirstChar { it.titlecase(Locale.FRANCE) }

    companion object {
        /** Fermeture au bout de 60 s sans toucher (maquette relue). */
        const val FERMETURE_MS = 60_000L
        /** Mesures du vent relues toutes les 2 min tant que leur page est visible (0.29.0). */
        const val RELECTURE_VENT_MS = 120_000L
        const val PAGE_TERRE = 0
        const val PAGE_VENT = 1
        const val PAGE_MER = 2
    }
}

/** Points de page du panneau Météo, un par entité météo, celui en cours en texte principal. */
internal class PointsPage(ctx: Context) : View(ctx) {
    var echelle = CadreMaquette.estimer(ctx)
        set(v) {
            field = v
            requestLayout()
            invalidate()
        }
    private var nombre = 0
    private var courant = 0
    private val p = Paint(Paint.ANTI_ALIAS_FLAG)

    init {
        isClickable = true
    }

    fun regler(n: Int, i: Int) {
        nombre = n
        courant = i
        requestLayout()
        invalidate()
    }

    override fun onMeasure(l: Int, h: Int) {
        val s = echelle
        val w = if (nombre == 0) 0 else ((nombre * 8 + (nombre - 1) * 8) * s).roundToInt()
        setMeasuredDimension(max(w, Decor.dp(context, 48f)), max((8 * s).roundToInt(), Decor.dp(context, 48f)))
    }

    override fun onDraw(c: Canvas) {
        val s = echelle
        val cy = height / 2f
        for (i in 0 until nombre) {
            p.color = if (i == courant) Palette.texte1 else Palette.texte3
            c.drawCircle((4 + 16 * i) * s, cy, 4 * s, p)
        }
    }
}

/**
 * Frise horaire défilante (0.23.0, partagée par les pages Terre et Mer) : une colonne de 66 px de maquette par
 * heure, défilante au doigt, qui ne dessine que les colonnes visibles. Toucher une colonne la choisit. Un geste
 * plutôt vertical est laissé au parent ([PagesMeteo]), seul un geste plutôt horizontal fait défiler la frise.
 * La plage d'une question est surlignée en bande ([bande]), sous la ligne des repères.
 */
internal abstract class FriseHoraire(ctx: Context) : View(ctx) {

    var echelle = CadreMaquette.estimer(ctx)
        set(v) {
            field = v
            echelleChangee()
            invalidate()
        }
    var surChoix: (Int) -> Unit = {}

    protected var choisi = 0
    protected var decalage = 0f
    /** Colonnes surlignées (question posée), ou null. */
    protected var bande: IntRange? = null
    private val defile = OverScroller(ctx)
    private var horizontal = false

    protected val pPlein = Paint(Paint.ANTI_ALIAS_FLAG)
    protected val pFondu = Paint()
    protected val r = RectF()
    private val fm = Paint.FontMetrics()

    protected abstract val nombre: Int
    protected open fun echelleChangee() {}

    private val gestes = GestureDetector(ctx, object : GestureDetector.SimpleOnGestureListener() {
        override fun onDown(e: MotionEvent): Boolean {
            defile.forceFinished(true)
            horizontal = false
            return true
        }

        override fun onScroll(e1: MotionEvent?, e2: MotionEvent, dx: Float, dy: Float): Boolean {
            if (!horizontal) {
                val debut = e1 ?: return false
                if (abs(e2.x - debut.x) < abs(e2.y - debut.y)) return false
                horizontal = true
            }
            parent?.requestDisallowInterceptTouchEvent(true)
            decaler(decalage + dx)
            return true
        }

        override fun onFling(e1: MotionEvent?, e2: MotionEvent, vx: Float, vy: Float): Boolean {
            if (!horizontal) return false
            defile.fling(decalage.toInt(), 0, -vx.toInt(), 0, 0, maxDecalage().toInt(), 0, 0)
            postInvalidateOnAnimation()
            return true
        }

        override fun onSingleTapUp(e: MotionEvent): Boolean {
            val i = floor((e.x + decalage) / (COLONNE * echelle)).toInt()
            if (i in 0 until nombre) choisir(i, defiler = false)
            performClick()
            return true
        }
    })

    init {
        isClickable = true
    }

    override fun onTouchEvent(ev: MotionEvent): Boolean = gestes.onTouchEvent(ev) || super.onTouchEvent(ev)

    override fun performClick(): Boolean = super.performClick()

    override fun computeScroll() {
        if (defile.computeScrollOffset()) {
            decalage = defile.currX.toFloat().coerceIn(0f, maxDecalage())
            postInvalidateOnAnimation()
        }
    }

    protected fun maxDecalage(): Float = max(0f, nombre * COLONNE * echelle - width)

    private fun decaler(v: Float) {
        val d = v.coerceIn(0f, maxDecalage())
        if (d != decalage) {
            decalage = d
            invalidate()
        }
    }

    /** Remet la frise au début, sans bande ni choix. */
    protected fun remettre() {
        decalage = 0f
        choisi = 0
        defile.forceFinished(true)
    }

    /** Choisit la colonne [i] (ligne de détail) et, si [defiler], amène la frise dessus. */
    fun choisir(i: Int, defiler: Boolean) {
        if (i !in 0 until nombre) return
        choisi = i
        surChoix(i)
        if (defiler) {
            val cible = (i * COLONNE * echelle).coerceIn(0f, maxDecalage())
            defile.forceFinished(true)
            defile.startScroll(decalage.toInt(), 0, (cible - decalage).toInt(), 0, 600)
            postInvalidateOnAnimation()
        }
        invalidate()
    }

    /** Amène tout de suite la colonne [i] au bord gauche (ouverture sur une question). */
    fun defilerA(i: Int) {
        defile.forceFinished(true)
        if (width == 0) {
            enAttente = i
            return
        }
        enAttente = -1
        decalage = (i * COLONNE * echelle).coerceIn(0f, maxDecalage())
        invalidate()
    }

    private var enAttente = -1

    override fun onSizeChanged(w: Int, h: Int, ancienW: Int, ancienH: Int) {
        super.onSizeChanged(w, h, ancienW, ancienH)
        if (w > 0 && enAttente >= 0) defilerA(enAttente)
    }

    protected fun dansBande(i: Int): Boolean = bande?.contains(i) == true

    /** Ligne de base d'un texte de [px] dont le haut de ligne CSS (interligne 1,22) est en [haut]. */
    protected fun base(p: Paint, haut: Float, px: Float): Float {
        p.getFontMetrics(fm)
        return haut + (1.22f * px - (fm.descent - fm.ascent)) / 2f - fm.ascent
    }

    /** Bande de la question et colonne choisie, derrière tout (repère translaté de -[decalage]). */
    protected fun fonds(c: Canvas, i0: Int, i1: Int) {
        val s = echelle
        val w = COLONNE * s
        val b = bande
        if (b != null && b.last >= i0 && b.first <= i1) {
            pPlein.color = Palette.surface
            r.set(b.first * w, 22f * s, (b.last + 1) * w, 296f * s)
            c.drawRoundRect(r, 8f * s, 8f * s, pPlein)
        }
        if (choisi in i0..i1) {
            pPlein.color = if (b != null) Palette.filet else Palette.surface
            r.set(choisi * w, if (b != null) 22f * s else 0f, choisi * w + w, 296f * s)
            c.drawRoundRect(r, 8f * s, 8f * s, pPlein)
        }
    }

    /** Fondu à droite sur le dernier dixième (maquette). */
    protected fun fondu(c: Canvas) {
        val debut = width * 0.9f
        pFondu.shader = LinearGradient(debut, 0f, width.toFloat(), 0f, Palette.fond and 0x00FFFFFF, Palette.fond, Shader.TileMode.CLAMP)
        c.drawRect(debut, 0f, width.toFloat(), height.toFloat(), pFondu)
    }

    protected fun premiereVisible(): Int = max(0, floor(decalage / (COLONNE * echelle)).toInt())
    protected fun derniereVisible(): Int = min(nombre - 1, ceil((decalage + width) / (COLONNE * echelle)).toInt())

    companion object {
        /** Largeur d'une colonne en pixels de maquette. */
        const val COLONNE = 66f
    }
}

/**
 * Frise horaire de la page Terre : heure, picto (de nuit atténué sauf la première heure de nuit), température sur
 * une courbe lissée sans dépassement, barre de pluie selon les millimètres, probabilité, vent avec sa flèche (km/h
 * une seule fois) et rafales au-dessus de 30. Repères « Maintenant », « Demain » à minuit et coucher du soleil en
 * pointillé à sa minute. Question posée (0.23.0) : la ligne de son sujet mise en avant dans la bande (pluie,
 * températures avec leur courbe dans la teinte météo, vent avec toutes ses rafales).
 */
internal class FriseMeteo(ctx: Context) : FriseHoraire(ctx) {

    /** Unité du vent de l'entité (0.21.1), écrite sous la première colonne, et seuil des rafales converti. */
    var uniteVent = "km/h"

    private var colonnes: List<MeteoTexte.Colonne> = emptyList()
    private var opacites: List<Float> = emptyList()
    private var textesMm: List<String> = emptyList()
    private var couchers: List<Pair<Float, String>> = emptyList()
    private var emphase: MeteoQuestion.Sujet? = null
    private var tMin = 0.0
    private var tMax = 0.0
    private var courbe: Path? = null

    override val nombre: Int get() = colonnes.size

    private val pTexte = android.text.TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = Polices.texte(ctx)
        textAlign = Paint.Align.CENTER
    }
    private val pGauche = android.text.TextPaint(Paint.ANTI_ALIAS_FLAG).apply { typeface = Polices.texte(ctx) }
    private val pTrait = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
    }
    private val pTirets = Paint().apply { style = Paint.Style.STROKE }

    init {
        contentDescription = "Prévisions heure par heure"
    }

    override fun echelleChangee() {
        courbe = null
    }

    fun donnees(c: List<MeteoTexte.Colonne>, couchersDuSoleil: List<Pair<Float, String>>) {
        colonnes = c
        opacites = MeteoTexte.opacites(c)
        textesMm = MeteoTexte.textesMm(c)
        couchers = couchersDuSoleil
        val t = c.mapNotNull { it.temperature }
        tMin = t.minOrNull() ?: 0.0
        tMax = t.maxOrNull() ?: 0.0
        courbe = null
        remettre()
        invalidate()
    }

    /** Plage d'une question posée (0.23.0) et la ligne de son sujet, ou null pour revenir à la frise simple. */
    fun mettreEnAvant(b: IntRange?, sujet: MeteoQuestion.Sujet?) {
        bande = b
        emphase = sujet
        invalidate()
    }

    /** Ordonnée de la courbe pour [t] degrés, en pixels de maquette de la colonne (sans les 24 px de l'en-tête). */
    private fun yT(t: Double): Float {
        val e = tMax - tMin
        val k = if (e <= 0.0) 0.0 else min(10.0, 80.0 / e)
        return (132.0 - (t - (tMin + tMax) / 2) * k).toFloat()
    }

    /** Courbe lissée sans dépassement (tangentes de Fritsch et Carlson), en pixels réels, frise entière. */
    private fun courbe(): Path {
        courbe?.let { return it }
        val s = echelle
        val pts = colonnes.mapIndexedNotNull { i, c -> c.temperature?.let { ((COLONNE * i + 33f) * s) to ((yT(it) + 24f) * s) } }
        val p = Path()
        if (pts.isEmpty()) return p.also { courbe = it }
        val n = pts.size
        val d = (0 until n - 1).map { (pts[it + 1].second - pts[it].second) / (pts[it + 1].first - pts[it].first) }
        val m = (0 until n).map { i ->
            when {
                n == 1 -> 0f
                i == 0 -> d[0]
                i == n - 1 -> d[n - 2]
                d[i - 1] * d[i] <= 0f -> 0f
                else -> (d[i - 1] + d[i]) / 2f
            }
        }
        p.moveTo(pts[0].first, pts[0].second)
        for (i in 0 until n - 1) {
            val h = (pts[i + 1].first - pts[i].first) / 3f
            p.cubicTo(pts[i].first + h, pts[i].second + m[i] * h, pts[i + 1].first - h, pts[i + 1].second - m[i + 1] * h, pts[i + 1].first, pts[i + 1].second)
        }
        courbe = p
        return p
    }

    private fun enAvant(i: Int, sujet: MeteoQuestion.Sujet): Boolean = emphase == sujet && dansBande(i)

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
        // Repères : minuit (trait plein, « Demain » puis le nom du jour) et couchers du soleil (pointillés).
        pTirets.color = Palette.filet
        pTirets.strokeWidth = max(1f, s * 0.75f)
        var premierMinuit = true
        for ((i, col) in colonnes.withIndex()) {
            if (!col.minuit) continue
            val nom = if (premierMinuit) "Demain" else Instant.ofEpochMilli(col.instant).atZone(ZoneId.systemDefault()).dayOfWeek
                .getDisplayName(java.time.format.TextStyle.FULL, Locale.FRANCE).replaceFirstChar { it.titlecase(Locale.FRANCE) }
            premierMinuit = false
            if (i < i0 || i > i1) continue
            pPlein.color = Palette.filet
            c.drawRect(i * w, 0f, i * w + max(1f, s * 0.5f), 296f * s, pPlein)
            pGauche.textSize = 16f * s
            pGauche.color = Palette.texte2
            c.drawText(nom, i * w + 8f * s, base(pGauche, 2f * s, 16f * s), pGauche)
        }
        pTirets.pathEffect = DashPathEffect(floatArrayOf(3f * s, 3f * s), 0f)
        for ((pos, libelle) in couchers) {
            val x = pos * w
            if (x < decalage - 2f || x > decalage + width + 10f) continue
            c.drawLine(x, 22f * s, x, 296f * s, pTirets)
            pGauche.textSize = 16f * s
            pGauche.color = Palette.texte2
            c.drawText(libelle, x + 6f * s, base(pGauche, 2f * s, 16f * s), pGauche)
        }
        pTirets.pathEffect = null
        pGauche.textSize = 16f * s
        pGauche.color = Palette.meteo
        c.drawText("Maintenant", 8f * s, base(pGauche, 2f * s, 16f * s), pGauche)
        // Courbe des températures et point du moment, et le morceau de la bande dans la teinte météo.
        pTrait.color = Palette.texte3
        pTrait.strokeWidth = 2f * s
        c.drawPath(courbe(), pTrait)
        val b = bande
        if (emphase == MeteoQuestion.Sujet.TEMPERATURE && b != null) {
            c.save()
            c.clipRect(b.first * w + 33f * s, 0f, b.last * w + 33f * s, 296f * s)
            pTrait.color = Palette.meteo
            pTrait.strokeWidth = 2.5f * s
            c.drawPath(courbe(), pTrait)
            c.restore()
        }
        colonnes.first().temperature?.let {
            pPlein.color = Palette.meteo
            c.drawCircle(33f * s, (yT(it) + 24f) * s, 5f * s, pPlein)
        }
        for (i in i0..i1) colonne(c, i, colonnes[i], i * w, s)
        c.restore()
        fondu(c)
    }

    private fun colonne(c: Canvas, i: Int, col: MeteoTexte.Colonne, x: Float, s: Float) {
        val cx = x + 33f * s
        val haut = 24f * s
        val dans = dansBande(i)
        // Heure. Dans la bande, le texte3 passe en texte2 (4,5:1 sur surface et filet).
        pTexte.textSize = 16f * s
        pTexte.color = when {
            i == 0 -> Palette.meteo
            i == choisi -> Palette.texte1
            dans -> Palette.texte2
            else -> Palette.texte3
        }
        c.drawText("${col.heure} h", cx, base(pTexte, haut, 16f * s), pTexte)
        // Picto.
        PictosMeteo.dessiner(c, col.picto, x + 17f * s, haut + 24f * s, 32f * s, opacites.getOrElse(i) { 1f })
        // Température.
        col.temperature?.let {
            pTexte.textSize = 18f * s
            pTexte.color = if (i == 0 || enAvant(i, MeteoQuestion.Sujet.TEMPERATURE)) Palette.texte1 else Palette.texte2
            c.drawText(MeteoTexte.degres(it), cx, base(pTexte, haut + (yT(it) - 30f) * s, 18f * s), pTexte)
        }
        // Pluie : barre selon les mm, mm au-dessus dès 0,5, probabilité dessous.
        val pluie = enAvant(i, MeteoQuestion.Sujet.PLUIE)
        val b = MeteoTexte.barre(col.millimetres)
        if (b > 0f) {
            pPlein.color = Palette.accentPluie
            r.set(x + 22f * s, haut + (198f - b) * s, x + 44f * s, haut + 198f * s)
            c.drawRoundRect(r, 3f * s, 3f * s, pPlein)
        }
        val mm = textesMm.getOrElse(i) { "" }
        if (mm.isNotEmpty()) {
            pTexte.textSize = 15f * s
            pTexte.color = if (pluie) Palette.texte1 else Palette.texte2
            c.drawText(mm, cx, base(pTexte, haut + (198f - b - 22f) * s, 15f * s), pTexte)
        }
        col.probabilite?.takeIf { it >= 10 }?.let {
            pTexte.textSize = 15f * s
            pTexte.color = when {
                pluie -> Palette.texte1
                dans || i == choisi -> Palette.texte2
                else -> Palette.texte3
            }
            c.drawText("$it %", cx, base(pTexte, haut + 206f * s, 15f * s), pTexte)
        }
        // Vent : flèche orientée là où va le vent, vitesse, « km/h » sous la première colonne, rafales.
        val vent = enAvant(i, MeteoQuestion.Sujet.VENT)
        val couleurVent = if (vent) Palette.texte1 else Palette.texte2
        var y = haut + 234f * s
        col.vent?.let { v ->
            pTexte.textSize = 16f * s
            pTexte.color = couleurVent
            val t = v.roundToInt().toString()
            val lt = pTexte.measureText(t)
            val total = 12f * s + 4f * s + lt
            val gauche = cx - total / 2f
            col.direction?.let { d -> PictosMeteo.flecheVent(c, gauche + 6f * s, y + 1.22f * 16f * s / 2f, 12f * s, ((d + 180.0) % 360.0).toFloat(), couleurVent) }
            c.drawText(t, gauche + 16f * s + lt / 2f, base(pTexte, y, 16f * s), pTexte)
            y += 1.22f * 16f * s + 2f * s
        }
        if (i == 0 && col.vent != null) {
            pTexte.textSize = 15f * s
            pTexte.color = Palette.texte3
            c.drawText(uniteVent, cx, base(pTexte, y, 15f * s), pTexte)
            y += 1.22f * 15f * s + 2f * s
        }
        // Rafales au-dessus de 30 km/h, et toutes celles de la bande pour une question sur le vent.
        if (MeteoTexte.rafaleMontree(col.rafales, uniteVent) || (vent && (col.rafales ?: 0.0) > 0.0)) {
            pTexte.textSize = 15f * s
            pTexte.color = couleurVent
            val t = col.rafales!!.roundToInt().toString()
            val lt = pTexte.measureText(t)
            val total = 13f * s + 3f * s + lt
            val gauche = cx - total / 2f
            PictosMeteo.rafale(c, gauche, y + (1.22f * 15f - 10f) / 2f * s, 13f * s, couleurVent)
            c.drawText(t, gauche + 16f * s + lt / 2f, base(pTexte, y, 15f * s), pTexte)
        }
    }
}

/**
 * Jours du panneau Météo, sept colonnes : nom, picto, pluie, maximum et minimum avec une barre verticale fine
 * sur une échelle commune. Le jour choisi est souligné. Toucher un jour le choisit. 140 px de haut depuis 0.23.0
 * (l'aperçu de la mer prend le bas de l'écran).
 */
internal class JoursMeteo(ctx: Context) : View(ctx) {
    var echelle = CadreMaquette.estimer(ctx)
        set(v) {
            field = v
            invalidate()
        }
    var surChoix: (Int) -> Unit = {}
    var choisi = 0
        set(v) {
            field = v
            invalidate()
        }
    private var jours: List<MeteoTexte.Jour> = emptyList()
    private val pTexte = android.text.TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        typeface = Polices.texte(ctx)
        textAlign = Paint.Align.CENTER
    }
    private val pGauche = android.text.TextPaint(Paint.ANTI_ALIAS_FLAG)
    private val pPlein = Paint(Paint.ANTI_ALIAS_FLAG)
    private val r = RectF()
    private val fm = Paint.FontMetrics()

    init {
        isClickable = true
        contentDescription = "Prévisions des prochains jours"
    }

    fun donnees(j: List<MeteoTexte.Jour>) {
        jours = j
        invalidate()
    }

    override fun onTouchEvent(ev: MotionEvent): Boolean {
        if (ev.actionMasked == MotionEvent.ACTION_UP) {
            val i = (ev.x / (width / 7f)).toInt()
            if (i in jours.indices) {
                choisi = i
                surChoix(i)
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
        for ((i, j) in jours.withIndex()) {
            val cx = w * i + w / 2f
            pTexte.textSize = 18f * s
            pTexte.color = if (i == 0) Palette.texte1 else Palette.texte2
            c.drawText(j.nom, cx, base(pTexte, 4f * s, 18f * s), pTexte)
            PictosMeteo.dessiner(c, j.picto, cx - 18f * s, 27f * s, 36f * s)
            val pluie = j.probabilite?.takeIf { it >= 10 }?.let { "$it %" }
                ?: j.millimetres?.takeIf { it >= 0.5 }?.let { MeteoTexte.mm(it) + " mm" }
            if (pluie != null) {
                pTexte.textSize = 16f * s
                pTexte.color = Palette.accentPluie
                c.drawText(pluie, cx, base(pTexte, 64f * s, 16f * s), pTexte)
            }
            // Maximum, barre fine sur l'échelle commune, minimum.
            val tMax = j.max?.let { "${it.roundToInt()}°" } ?: ""
            val tMin = j.min?.let { "${it.roundToInt()}°" } ?: ""
            pGauche.typeface = Polices.chiffres(context, 400)
            pGauche.textSize = 34f * s
            val lMax = pGauche.measureText(tMax)
            pGauche.typeface = Polices.texte(context)
            pGauche.textSize = 20f * s
            val lMin = pGauche.measureText(tMin)
            val total = lMax + 10f * s + 4f * s + 10f * s + lMin
            var x = cx - total / 2f
            val centre = 108f * s
            pGauche.typeface = Polices.chiffres(context, 400)
            pGauche.textSize = 34f * s
            pGauche.color = Palette.texte1
            pGauche.getFontMetrics(fm)
            c.drawText(tMax, x, centre - (fm.ascent + fm.descent) / 2f, pGauche)
            x += lMax + 10f * s
            pPlein.color = Palette.barre
            r.set(x, centre - 22f * s, x + 4f * s, centre + 22f * s)
            c.drawRoundRect(r, 2f * s, 2f * s, pPlein)
            MeteoTexte.echelleJour(j, jours)?.let { (haut, h) ->
                pPlein.color = Palette.texte2
                r.set(x, centre - 22f * s + haut * s, x + 4f * s, centre - 22f * s + (haut + h) * s)
                c.drawRoundRect(r, 2f * s, 2f * s, pPlein)
            }
            x += 4f * s + 10f * s
            pGauche.typeface = Polices.texte(context)
            pGauche.textSize = 20f * s
            pGauche.color = Palette.texte2
            pGauche.getFontMetrics(fm)
            c.drawText(tMin, x, centre - (fm.ascent + fm.descent) / 2f, pGauche)
            if (i == choisi) {
                pPlein.color = Palette.texte1
                c.drawRect(w * i, 138f * s, w * i + w, 140f * s, pPlein)
            }
        }
    }
}
