package assistant.vocal.jarvis

import android.content.Context
import android.graphics.Canvas
import android.graphics.DashPathEffect
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.graphics.Shader
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.widget.FrameLayout
import android.widget.LinearLayout
import java.time.ZonedDateTime
import java.util.Locale
import kotlin.math.abs
import kotlin.math.ceil
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * Page « Vent mesuré dans le golfe » du panneau Météo (0.29.0, maquettes `MeteoBalises`, `MeteoBalisesRegate` et
 * `MeteoBalisesSoir` validées le 24/10), entre la page Terre et les prévisions marines, placée en pixels de maquette :
 * - en haut, le titre et l'heure de lecture, le chevron vers « Météo à ... », « Fermer » ;
 * - à gauche, la carte du golfe ([CarteVent]) avec une flèche par station (plus longue quand le vent est plus fort,
 *   rond creux quand la mesure est trop vieille), la station choisie cerclée dans la teinte météo ;
 * - à droite, la fiche de la station choisie (vent, âge, direction, rafale, moyenne et rafale max sur 15 min, prévision
 *   Exemple5 de l'heure), puis les autres stations ([ListeVent]), qu'on touche pour les choisir ;
 * - en bas, la courbe des 3 dernières heures ([CourbeVent]) avec le curseur temporel : glisser fixe un instant pour
 *   la carte, la fiche et la liste, « Revenir au direct » ramène au présent ;
 * - le chevron vers les prévisions de la journée et l'attribution des sources.
 * Toutes les valeurs viennent de [MeteoVent].
 */
internal class EcranVent(
    private val ctx: Context,
    private val surFermer: () -> Unit,
    private val surTerre: () -> Unit,
    private val surPrevisions: () -> Unit,
) {

    val cadre = CadreMaquette(ctx)

    private fun texte(couleur: Int, lignes: Int = 1) = TexteFondu(ctx).apply {
        peinture.typeface = Polices.texte(ctx)
        peinture.color = couleur
        maxLignes = lignes
    }

    private val titre = texte(Palette.texte1).apply { texte = ConfigMaison.section("vent").optString("titre").ifEmpty { "Vent mesuré" } }
    private val lu = texte(Palette.texte2)
    private val enTete = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        addView(titre)
        addView(lu)
    }
    private val libelleTerre = texte(Palette.texte2).apply { texte = MeteoMer.LIBELLE_TERRE }
    private val chevronHaut = ChevronPage(ctx, versLeBas = false)
    private val terre = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER
        isClickable = true
        isFocusable = true
        contentDescription = "Revenir à la " + MeteoMer.LIBELLE_TERRE.replaceFirstChar { it.lowercase() }
        setOnClickListener { surTerre() }
        addView(chevronHaut)
        addView(libelleTerre)
    }
    private val libelleFermer = texte(Palette.texte2).apply { texte = "Fermer" }
    private val fermer = FrameLayout(ctx).apply {
        isClickable = true
        isFocusable = true
        contentDescription = "Fermer la météo"
        setOnClickListener { surFermer() }
        addView(libelleFermer, FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.CENTER))
    }
    private val carte = CarteVent(ctx).apply { surStation = { choisir(it) } }
    private val legende = texte(Palette.texte2).apply { texte = "Flèche : là où va le vent, plus longue quand il est plus fort. Rond creux : pas de mesure récente." }
    private val nom = texte(Palette.texte1)
    private val genre = texte(Palette.texte2)
    private val ligneNom = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.BOTTOM
        addView(nom)
        addView(genre)
    }
    private val grand = texte(Palette.meteo).apply {
        police(Polices.chiffres(ctx, 300))
        peinture.letterSpacing = -2f / 120f
        // Interligne de 0,95 comme la maquette : sinon la fiche descend sur la liste.
        interligne = 0.95f / 1.22f
    }
    private val unite = texte(Palette.texte2).apply { texte = "nœuds" }
    private val chiffre = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.BOTTOM
        addView(grand)
        addView(unite)
    }
    private val age = texte(Palette.texte2).apply { aDroite = true }
    private val ligne1 = texte(Palette.texte1)
    private val ligne2 = texte(Palette.texte2)
    private val ligne3 = texte(Palette.texte2)
    private val fiche = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        addView(ligneNom)
        addView(chiffre)
        addView(ligne1)
        addView(ligne2)
        addView(ligne3)
    }
    private val liste = ListeVent(ctx).apply { surStation = { choisir(it) } }
    private val titreCourbe = texte(Palette.texte1)
    private val legendeCourbe = texte(Palette.texte2).apply { texte = "Trait : mesure, zone claire : rafales, pointillés : prévision ${MeteoMer.NOM_PRINCIPAL}. Glisser sur la courbe pour revoir un instant." }
    private val bandeau = texte(Palette.meteo)
    private val bandeauNote = texte(Palette.texte2).apply { texte = "carte, fiche et liste à cet instant" }
    private val libelleDirect = texte(Palette.meteo).apply { texte = "Revenir au direct" }
    private val direct = FrameLayout(ctx).apply {
        isClickable = true
        isFocusable = true
        contentDescription = "Revenir au direct"
        setOnClickListener { fixer(null) }
        addView(libelleDirect, FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.CENTER))
    }
    private val ligneCourbe = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        addView(titreCourbe)
        addView(legendeCourbe)
        addView(bandeau)
        addView(bandeauNote)
        addView(View(ctx), LinearLayout.LayoutParams(0, 1, 1f))
        addView(direct)
    }
    private val courbe = CourbeVent(ctx).apply { surInstant = { fixer(it) } }
    private val libellePrevisions = texte(Palette.texte2).apply { texte = "Prévisions de la journée" }
    private val chevronBas = ChevronPage(ctx, versLeBas = true)
    private val previsions = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER
        isClickable = true
        isFocusable = true
        contentDescription = "Voir les prévisions marines de la journée"
        setOnClickListener { surPrevisions() }
        addView(libellePrevisions)
        addView(chevronBas)
    }
    private val sources = texte(Palette.texte3).apply {
        texte = ConfigMaison.section("vent").optJSONObject("carte")?.optString("attribution") ?: ""
    }

    private var d: MeteoVent.Donnees? = null
    private var mer: MeteoMer.Donnees? = null
    private var erreur = ""
    private var choisie: String? = null
    /** Instant du curseur en secondes, null pour le direct. */
    private var instant: Long? = null

    init {
        val n = Float.NaN
        val P = CadreMaquette::Place
        cadre.setBackgroundColor(Palette.fond)
        cadre.addView(terre, P(520f, 0f, n, n, 240f, 48f))
        cadre.addView(FrameLayout(ctx).apply {
            addView(enTete, FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.CENTER_VERTICAL))
        }, P(72f, 28f, n, n, 640f, 48f))
        cadre.addView(fermer, P(n, 28f, 66f, n, n, 48f))
        cadre.addView(carte, P(72f, 84f, n, n, MeteoVent.LARGEUR, MeteoVent.HAUTEUR))
        cadre.addView(legende, P(72f, 516f, n, n, 640f, n))
        cadre.addView(fiche, P(760f, 84f, n, n, 448f, n))
        cadre.addView(age, P(n, 196f, 72f, n, 240f, n))
        cadre.addView(liste, P(760f, 340f, n, n, 448f, 222f))
        cadre.addView(ligneCourbe, P(72f, 566f, n, n, 1136f, 44f))
        cadre.addView(courbe, P(72f, 612f, n, n, 1136f, 130f))
        cadre.addView(previsions, P(440f, 738f, n, n, 400f, 44f))
        cadre.addView(sources, P(72f, 780f, n, n, 1136f, n))
        cadre.surEchelle = { appliquer(it) }
        appliquer(cadre.echelle)
    }

    fun appliquer(s: Float) {
        fun lp(v: View, haut: Float = 0f, gauche: Float = 0f, bas: Float = 0f) {
            (v.layoutParams as? LinearLayout.LayoutParams ?: LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT))
                .also { it.topMargin = (haut * s).toInt(); it.marginStart = (gauche * s).toInt(); it.bottomMargin = (bas * s).toInt(); v.layoutParams = it }
        }
        titre.taille(24f * s)
        lu.taille(16f * s)
        lp(lu, 0f, 14f)
        libelleTerre.taille(16f * s)
        chevronHaut.echelle = s
        lp(libelleTerre, 0f, 8f)
        libelleFermer.taille(18f * s)
        fermer.minimumWidth = max((60 * s).toInt(), Decor.dp(ctx, 48f))
        carte.echelle = s
        legende.taille(13f * s)
        nom.taille(24f * s)
        genre.taille(17f * s)
        lp(genre, 0f, 12f, 2f)
        grand.taille(120f * s)
        unite.taille(26f * s)
        lp(unite, 0f, 10f, 20f)
        age.taille(17f * s)
        ligne1.taille(19f * s)
        lp(ligne1, 0f)
        ligne2.taille(17f * s)
        lp(ligne2, 3f)
        ligne3.taille(17f * s)
        lp(ligne3, 3f)
        liste.echelle = s
        titreCourbe.taille(16f * s)
        legendeCourbe.taille(13f * s)
        lp(legendeCourbe, 0f, 16f)
        bandeau.taille(18f * s)
        bandeauNote.taille(15f * s)
        lp(bandeauNote, 0f, 16f)
        libelleDirect.taille(16f * s)
        direct.minimumHeight = (44 * s).toInt()
        direct.setPadding((18 * s).toInt(), 0, (18 * s).toInt(), 0)
        direct.background = GradientDrawable().apply {
            cornerRadius = 22f * s
            setStroke(max(1, (1.5f * s).roundToInt()), Palette.meteo)
        }
        courbe.echelle = s
        libellePrevisions.taille(16f * s)
        chevronBas.echelle = s
        lp(chevronBas, 0f, 10f)
        sources.taille(13f * s)
    }

    /** Page rouverte : la station d'une question, sinon le choix par défaut à l'arrivée des données, au direct. */
    fun ouvrir(q: MeteoQuestion.Reponse?) {
        choisie = q?.station
        instant = null
        d = null
        erreur = ""
        montrer()
    }

    fun donnees(donnees: MeteoVent.Donnees?, raison: String) {
        // Une lecture vide ne remplace pas une bonne lecture déjà montrée (actualisation qui échoue).
        if (donnees == null && d != null) return
        d = donnees
        erreur = raison
        montrer()
    }

    fun previsionsMer(m: MeteoMer.Donnees?) {
        mer = m
        montrer()
    }

    private fun choisir(id: String) {
        choisie = id
        montrer()
    }

    private fun fixer(t: Long?) {
        instant = t
        montrer()
    }

    /** Dernières mesures montrées, gardées malgré une relecture qui échoue. */
    val actuelles: MeteoVent.Donnees? get() = d

    /** Toutes les minutes : les âges avancent même sans nouvelle lecture. */
    fun rafraichir() = montrer()

    private fun montrer() {
        val donnees = d
        val maintenantS = ZonedDateTime.now().toEpochSecond()
        // Un curseur sorti de la fenêtre de 3 h (le temps a passé) revient au direct.
        instant = instant?.takeIf { it >= maintenantS - MeteoVent.FENETRE_S }
        val refS = instant ?: maintenantS
        val passe = instant != null
        lu.texte = donnees?.luA?.let { "lu à ${it.hour} h " + it.minute.toString().padStart(2, '0') } ?: ""
        titreCourbe.visibility = if (passe) View.GONE else View.VISIBLE
        legendeCourbe.visibility = if (passe) View.GONE else View.VISIBLE
        bandeau.visibility = if (passe) View.VISIBLE else View.GONE
        bandeauNote.visibility = if (passe) View.VISIBLE else View.GONE
        direct.visibility = if (passe) View.VISIBLE else View.GONE
        if (donnees == null) {
            carte.donnees(null, null, refS)
            liste.donnees(emptyList(), refS, passe, "")
            courbe.donnees(null, null, maintenantS, null)
            nom.texte = if (erreur.isBlank()) "Lecture des mesures" else "Mesures indisponibles"
            genre.texte = ""
            grand.texte = ""
            unite.visibility = View.INVISIBLE
            age.texte = ""
            ligne1.texte = MeteoQuestion.majuscule(erreur)
            ligne2.texte = ""
            ligne3.texte = ""
            titreCourbe.texte = ""
            return
        }
        val s = donnees.station(choisie) ?: MeteoVent.parDefaut(donnees, maintenantS)
        choisie = s?.id
        carte.donnees(donnees, s?.id, refS)
        val autres = donnees.stations.filter { it.id != s?.id }
        val pannes = donnees.erreurs.joinToString(", ")
        liste.donnees(autres, refS, passe, pannes)
        if (s == null) return
        nom.texte = s.nom
        genre.texte = s.genre
        val m = MeteoVent.mesure(s, refS)
        val fraiche = MeteoVent.fraiche(s, m, refS)
        grand.texte = if (m != null && fraiche) m.vent.roundToInt().toString() else ""
        unite.visibility = if (m != null && fraiche) View.VISIBLE else View.INVISIBLE
        age.texte = when {
            m == null -> "pas de mesure"
            passe -> "à " + MeteoVent.heure(m.t)
            else -> MeteoVent.ilYa(MeteoVent.age(m, refS))
        }
        age.couleur(if (passe) Palette.meteo else Palette.texte2)
        if (m == null || !fraiche) {
            ligne1.texte = m?.let { "Pas de mesure depuis ${MeteoVent.age(it, refS)} min" } ?: "Pas de mesure"
            ligne2.texte = ""
        } else {
            ligne1.texte = (MeteoVent.direction(m)?.let { d0 -> MeteoQuestion.majuscule(d0) + ", ${m.dir}°" } ?: "Variable") +
                (m.rafale?.let { ", rafale ${it.roundToInt()}" } ?: "")
            ligne2.texte = MeteoVent.quinze(s, refS)?.let { (moy, raf) -> "Sur 15 min : moyenne ${moy.roundToInt()}, rafale max ${raf.roundToInt()}" } ?: ""
        }
        ligne3.texte = MeteoVent.prevu(s, mer, refS)?.let { (h, v) -> "Prévu à $h h : ${MeteoVent.noeuds(v)} (${MeteoMer.NOM_PRINCIPAL})" } ?: ""
        titreCourbe.texte = "${s.nom}, les 3 dernières heures"
        if (passe) {
            val minutes = ((maintenantS - refS) / 60).toInt()
            bandeau.texte = "Il y a ${if (minutes >= 60) "${minutes / 60} h " + (minutes % 60).toString().padStart(2, '0') else "$minutes min"}, à ${MeteoVent.heure(refS)}"
        }
        courbe.donnees(s, mer, maintenantS, instant)
    }
}

/** Carte du golfe de la page du vent mesuré : mer teintée, terre en relief, une flèche par station du cadre. */
internal class CarteVent(ctx: Context) : View(ctx) {
    var echelle = CadreMaquette.estimer(ctx)
        set(v) {
            field = v
            invalidate()
        }
    var surStation: (String) -> Unit = {}

    // Trait de côte et terre (vent.carte.cote et terre : assets générés dans la configuration de la maison).
    private val cote: Path = lire(ctx, CARTE.optString("cote"))
    private val terre: Path = lire(ctx, CARTE.optString("terre"))
    private var blocs: List<MeteoVent.Bloc> = emptyList()
    private var choisie: String? = null
    private var refS = 0L
    private val pPlein = Paint(Paint.ANTI_ALIAS_FLAG)
    private val pTrait = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeJoin = Paint.Join.ROUND
        strokeCap = Paint.Cap.ROUND
    }
    private val pTexte = android.text.TextPaint(Paint.ANTI_ALIAS_FLAG).apply { textAlign = Paint.Align.CENTER }
    private val fleche = Path()

    init {
        isClickable = true
        contentDescription = "Carte du golfe avec le vent mesuré à chaque station"
    }

    fun donnees(d: MeteoVent.Donnees?, station: String?, instantS: Long) {
        blocs = d?.let { MeteoVent.blocs(it) } ?: emptyList()
        choisie = station
        refS = instantS
        invalidate()
    }

    override fun onTouchEvent(ev: MotionEvent): Boolean {
        if (ev.actionMasked == MotionEvent.ACTION_UP) {
            MeteoVent.touchee(blocs, ev.x / echelle, ev.y / echelle)?.let { surStation(it.id) }
            performClick()
        }
        return true
    }

    override fun performClick(): Boolean = super.performClick()

    override fun onDraw(c: Canvas) {
        val s = echelle
        c.save()
        c.clipRect(0, 0, width, height)
        c.scale(s, s)
        val w = MeteoVent.LARGEUR
        val h = MeteoVent.HAUTEUR
        pPlein.shader = LinearGradient(0f, 0f, 0f, h, alpha(Palette.meteo, 0.03f), alpha(Palette.meteo, 0.11f), Shader.TileMode.CLAMP)
        c.drawRect(0f, 0f, w, h, pPlein)
        pPlein.shader = null
        pPlein.color = Palette.surface
        c.drawPath(terre, pPlein)
        pTrait.color = alpha(Palette.meteo, 0.16f)
        pTrait.strokeWidth = 5f
        c.drawPath(cote, pTrait)
        pTrait.color = Palette.texte3
        pTrait.strokeWidth = 1.3f
        c.drawPath(cote, pTrait)
        // Repères des quartiers, en petites capitales espacées.
        pTexte.typeface = Polices.texte(context)
        pTexte.textSize = 14f
        pTexte.letterSpacing = 1f / 14f
        pTexte.color = Palette.texte2
        pTexte.textAlign = Paint.Align.LEFT
        for ((nom, lat, lon) in LIEUX) MeteoVent.carte(lat, lon)?.let { (x, y) -> c.drawText(nom, x, y, pTexte) }
        pTexte.letterSpacing = 0f
        pTexte.textAlign = Paint.Align.CENTER
        for (b in blocs) bloc(c, b)
        c.restore()
    }

    private fun bloc(c: Canvas, b: MeteoVent.Bloc) {
        val st = b.station
        val m = MeteoVent.mesure(st, refS)
        val frais = MeteoVent.fraiche(st, m, refS)
        val choisi = st.id == choisie
        // Trait de rappel, point de la station.
        pTrait.color = Palette.texte3
        pTrait.strokeWidth = 1f
        c.drawLine(b.x, b.y, b.bx, b.by - 44f, pTrait)
        pPlein.color = Palette.texte1
        c.drawCircle(b.x, b.y, 3f, pPlein)
        val cy = b.by - 16f
        if (choisi) {
            pTrait.color = Palette.meteo
            pTrait.strokeWidth = 1.8f
            c.drawCircle(b.bx, cy, 24f, pTrait)
        }
        if (frais && m != null) {
            // Flèche là où va le vent, plus longue quand il est plus fort.
            val l = 8f + min(m.vent, 25.0).toFloat() * 0.9f
            pTrait.color = when {
                choisi -> Palette.meteo
                st.type == "mer" -> Palette.texte1
                else -> Palette.texte2
            }
            pTrait.strokeWidth = if (st.enMer) 2.6f else 1.8f
            if (m.dir != null && m.vent >= MeteoMer.VARIABLE) {
                fleche.reset()
                fleche.moveTo(0f, l); fleche.lineTo(0f, -l)
                fleche.moveTo(-6f, -l + 7f); fleche.lineTo(0f, -l); fleche.lineTo(6f, -l + 7f)
                c.save()
                c.translate(b.bx, cy)
                c.rotate(((m.dir + 180) % 360).toFloat())
                c.drawPath(fleche, pTrait)
                c.restore()
            } else {
                // Vent variable : un petit rond plein.
                pPlein.color = pTrait.color
                c.drawCircle(b.bx, cy, 4f, pPlein)
            }
            pTexte.typeface = Polices.chiffres(context, 400)
            pTexte.textSize = if (st.enMer) 30f else 24f
            pTexte.color = if (choisi) Palette.meteo else Palette.texte1
            c.drawText(m.vent.roundToInt().toString(), b.bx, b.by + 34f, pTexte)
        } else {
            pTrait.color = Palette.texte2
            pTrait.strokeWidth = 1.6f
            c.drawCircle(b.bx, cy, 7f, pTrait)
            pTexte.typeface = Polices.texte(context)
            pTexte.textSize = 15f
            pTexte.color = Palette.texte2
            c.drawText(m?.let { "${MeteoVent.age(it, refS)} min" } ?: "aucune", b.bx, b.by + 16f, pTexte)
        }
        pTexte.typeface = Polices.texte(context)
        pTexte.textSize = 13f
        pTexte.color = Palette.texte2
        c.drawText(st.nom + if (st.type == "abritee") ", abritée" else "", b.bx, b.by + if (frais) 49f else 31f, pTexte)
    }

    companion object {
        private val CARTE: org.json.JSONObject = ConfigMaison.section("vent").optJSONObject("carte") ?: org.json.JSONObject()
        /** Noms de lieux écrits sur la carte (vent.carte.lieux). */
        private val LIEUX: List<Triple<String, Double, Double>> = CARTE.optJSONArray("lieux")?.let { a ->
            (0 until a.length()).mapNotNull { a.optJSONObject(it) }.map { Triple(it.optString("nom"), it.optDouble("lat"), it.optDouble("lon")) }
        } ?: emptyList()

        private fun alpha(c: Int, a: Float): Int = ((255 * a).toInt().coerceIn(0, 255) shl 24) or (c and 0xFFFFFF)

        /** Chemin SVG d'un asset (trait de côte OpenStreetMap), vide s'il manque. */
        private fun lire(ctx: Context, nom: String): Path = try {
            CheminSvg.chemin(CheminSvg.lire(ctx.assets.open(nom).bufferedReader().use { it.readText() }))
        } catch (_: Exception) {
            Path()
        }
    }
}

/** Autres stations de la page du vent mesuré : quatre lignes qu'on touche pour choisir, puis le reste en une phrase. */
internal class ListeVent(ctx: Context) : View(ctx) {
    var echelle = CadreMaquette.estimer(ctx)
        set(v) {
            field = v
            invalidate()
        }
    var surStation: (String) -> Unit = {}
    private var stations: List<MeteoVent.Station> = emptyList()
    private var refS = 0L
    private var passe = false
    private var pannes = ""
    private val pTexte = android.text.TextPaint(Paint.ANTI_ALIAS_FLAG)
    private val pPlein = Paint(Paint.ANTI_ALIAS_FLAG)
    private val pTrait = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
    private val fm = Paint.FontMetrics()

    init {
        isClickable = true
        contentDescription = "Autres stations"
    }

    fun donnees(l: List<MeteoVent.Station>, instantS: Long, auCurseur: Boolean, enPanne: String) {
        stations = l
        refS = instantS
        passe = auCurseur
        pannes = enPanne
        invalidate()
    }

    override fun onTouchEvent(ev: MotionEvent): Boolean {
        if (ev.actionMasked == MotionEvent.ACTION_UP) {
            val i = (ev.y / (LIGNE * echelle)).toInt()
            stations.getOrNull(i)?.takeIf { i < 4 }?.let { surStation(it.id) }
            performClick()
        }
        return true
    }

    override fun performClick(): Boolean = super.performClick()

    private fun milieu(p: Paint, cy: Float): Float {
        p.getFontMetrics(fm)
        return cy - (fm.ascent + fm.descent) / 2f
    }

    override fun onDraw(c: Canvas) {
        val s = echelle
        val w = width.toFloat()
        val montrees = stations.take(4)
        for ((i, st) in montrees.withIndex()) {
            val haut = i * LIGNE * s
            val cy = haut + LIGNE * s / 2f
            pPlein.color = Palette.filet
            c.drawRect(0f, haut, w, haut + max(1f, s * 0.5f), pPlein)
            val m = MeteoVent.mesure(st, refS)
            val frais = MeteoVent.fraiche(st, m, refS)
            if (frais && m != null && m.dir != null && m.vent >= MeteoMer.VARIABLE) {
                PictosMeteo.flecheVent(c, 9f * s, cy, 18f * s, ((m.dir + 180) % 360).toFloat(), Palette.texte2, 1.6f)
            } else {
                pTrait.color = Palette.texte2
                pTrait.strokeWidth = 1.6f * s
                c.drawCircle(9f * s, cy, 5f * s, pTrait)
            }
            pTexte.typeface = Polices.texte(context)
            pTexte.textAlign = Paint.Align.LEFT
            pTexte.textSize = 18f * s
            pTexte.color = Palette.texte1
            c.drawText(st.nom, 28f * s, milieu(pTexte, cy), pTexte)
            val ln = pTexte.measureText(st.nom)
            pTexte.textSize = 15f * s
            pTexte.color = Palette.texte2
            // À droite : âge (ou heure au curseur), puis le vent en chiffres. Le genre seulement s'il a la place.
            val ageTexte = when {
                m == null -> "aucune mesure"
                !frais -> "pas de mesure depuis ${MeteoVent.age(m, refS)} min"
                passe -> MeteoVent.heure(m.t)
                else -> "${max(1, MeteoVent.age(m, refS))} min"
            }
            val droite = if (frais) w - 70f * s else w
            val debutGenre = 28f * s + ln + 10f * s
            if (debutGenre + pTexte.measureText(st.genre) + 16f * s < droite - pTexte.measureText(ageTexte)) {
                c.drawText(st.genre, debutGenre, milieu(pTexte, cy), pTexte)
            }
            pTexte.textAlign = Paint.Align.RIGHT
            c.drawText(ageTexte, droite, milieu(pTexte, cy), pTexte)
            if (frais && m != null) {
                pTexte.typeface = Polices.chiffres(context, 400)
                pTexte.textSize = 28f * s
                pTexte.color = Palette.texte1
                c.drawText(m.vent.roundToInt().toString(), w, milieu(pTexte, cy), pTexte)
            }
        }
        val haut = montrees.size * LIGNE * s
        pPlein.color = Palette.filet
        c.drawRect(0f, haut, w, haut + max(1f, s * 0.5f), pPlein)
        val reste = stations.drop(4)
        val phrase = listOfNotNull(
            if (reste.isEmpty()) null else "Aussi : " + reste.joinToString(", ") { st ->
                val m = MeteoVent.mesure(st, refS)
                st.nom + " " + if (MeteoVent.fraiche(st, m, refS) && m != null) m.vent.roundToInt().toString() else "(sans mesure récente)"
            },
            pannes.takeIf { it.isNotBlank() }?.let { MeteoQuestion.majuscule(it) },
        ).joinToString(". ").ifEmpty { ConfigMaison.section("vent").optString("note_regate") }
        pTexte.typeface = Polices.texte(context)
        pTexte.textAlign = Paint.Align.LEFT
        pTexte.textSize = 15f * s
        pTexte.color = Palette.texte2
        c.drawText(phrase, 0f, haut + 24f * s, pTexte)
    }

    companion object {
        const val LIGNE = 46f
    }
}

/**
 * Courbe des 3 dernières heures de la station choisie : vent mesuré (trait), rafales (zone claire), prévision Exemple5
 * de son point (pointillés), sur un axe qui s'adapte à la plus forte rafale. Le curseur suit le doigt et fixe un
 * instant, revenu au direct quand on le lâche dans les 2 dernières minutes.
 */
internal class CourbeVent(ctx: Context) : View(ctx) {
    var echelle = CadreMaquette.estimer(ctx)
        set(v) {
            field = v
            invalidate()
        }
    var surInstant: (Long?) -> Unit = {}
    private var station: MeteoVent.Station? = null
    private var mer: MeteoMer.Donnees? = null
    private var maintenantS = 0L
    private var instant: Long? = null
    private var x0 = 0f
    private var y0 = 0f
    private var glisse = false
    private val pPlein = Paint(Paint.ANTI_ALIAS_FLAG)
    private val pTrait = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeJoin = Paint.Join.ROUND
    }
    private val pTexte = android.text.TextPaint(Paint.ANTI_ALIAS_FLAG)
    private val r = RectF()

    init {
        isClickable = true
        contentDescription = "Vent des 3 dernières heures, glisser pour revoir un instant"
    }

    fun donnees(s: MeteoVent.Station?, m: MeteoMer.Donnees?, maintenant: Long, curseur: Long?) {
        station = s
        mer = m
        maintenantS = maintenant
        instant = curseur
        invalidate()
    }

    private fun debut() = maintenantS - MeteoVent.FENETRE_S
    private fun gauche() = 40f * echelle
    private fun largeur() = width - gauche() - 14f * echelle
    private fun xDe(t: Long): Float = gauche() + (t - debut()).toFloat() / MeteoVent.FENETRE_S * largeur()
    private fun tDe(x: Float): Long = debut() + ((x - gauche()) / largeur() * MeteoVent.FENETRE_S).toLong()

    override fun onTouchEvent(ev: MotionEvent): Boolean {
        if (station == null) return false
        when (ev.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                x0 = ev.x
                y0 = ev.y
                glisse = false
                return true
            }
            MotionEvent.ACTION_MOVE -> {
                if (!glisse && abs(ev.x - x0) > abs(ev.y - y0) && abs(ev.x - x0) > 8f * echelle) {
                    glisse = true
                    parent?.requestDisallowInterceptTouchEvent(true)
                }
                if (glisse) placer(ev.x)
            }
            MotionEvent.ACTION_UP -> {
                if (!glisse) placer(ev.x)
                performClick()
            }
        }
        return true
    }

    override fun performClick(): Boolean = super.performClick()

    private fun placer(x: Float) {
        val t = tDe(x.coerceIn(gauche(), gauche() + largeur())).coerceIn(debut(), maintenantS)
        surInstant(if (maintenantS - t < 120L) null else t)
    }

    override fun onDraw(c: Canvas) {
        val st = station ?: return
        val s = echelle
        val l = st.mesures.filter { it.t >= debut() - 600 && it.t <= maintenantS }
        if (l.isEmpty()) return
        val haut = l.maxOf { it.rafale ?: it.vent }
        val ax = max(10.0, ceil((haut + 2.0) / 5.0) * 5.0)
        val y0 = 108f * s
        val ky = 100f * s / ax.toFloat()
        fun yv(v: Double) = y0 - min(v, ax).toFloat() * ky
        c.save()
        c.clipRect(0, 0, width, height)
        // Grille et graduations.
        val pas = if (ax <= 30) 5 else 10
        pTexte.typeface = Polices.texte(context)
        pTexte.textSize = 13f * s
        pTexte.color = Palette.texte2
        pTexte.textAlign = Paint.Align.RIGHT
        pPlein.color = Palette.filet
        var v = pas
        while (v <= ax) {
            val y = yv(v.toDouble())
            c.drawRect(gauche(), y, width.toFloat(), y + max(1f, s * 0.5f), pPlein)
            c.drawText(v.toString(), 30f * s, y + 4f * s, pTexte)
            v += pas
        }
        // Rafales en zone claire, là où elles existent.
        val avecRafale = l.filter { it.rafale != null }
        if (avecRafale.size >= 2) {
            val p = Path()
            avecRafale.forEachIndexed { i, m -> if (i == 0) p.moveTo(xDe(m.t), yv(m.rafale!!)) else p.lineTo(xDe(m.t), yv(m.rafale!!)) }
            avecRafale.asReversed().forEach { m -> p.lineTo(xDe(m.t), yv(m.vent)) }
            p.close()
            pPlein.color = (0x38 shl 24) or (Palette.meteo and 0xFFFFFF)
            c.drawPath(p, pPlein)
        }
        // Prévision Exemple5 du point de la station, en pointillés.
        mer?.points?.firstOrNull { it.id == st.point }?.let { pt ->
            val hs = pt.heures.filter { it.vent != null }.map { it.t.atZone(MeteoMer.ZONE).toEpochSecond() to it.vent!! }
                .filter { it.first >= debut() - 3600 && it.first <= maintenantS + 3600 }
            if (hs.size >= 2) {
                val p = Path()
                hs.forEachIndexed { i, (t, vv) -> if (i == 0) p.moveTo(xDe(t), yv(vv)) else p.lineTo(xDe(t), yv(vv)) }
                pTrait.color = Palette.texte2
                pTrait.strokeWidth = 1.6f * s
                pTrait.pathEffect = DashPathEffect(floatArrayOf(4f * s, 4f * s), 0f)
                c.save()
                c.clipRect(gauche(), 0f, gauche() + largeur(), height.toFloat())
                c.drawPath(p, pTrait)
                c.restore()
                pTrait.pathEffect = null
            }
        }
        // Vent mesuré.
        val p = Path()
        l.forEachIndexed { i, m -> if (i == 0) p.moveTo(xDe(m.t), yv(m.vent)) else p.lineTo(xDe(m.t), yv(m.vent)) }
        pTrait.color = Palette.meteo
        pTrait.strokeWidth = 2.4f * s
        c.save()
        c.clipRect(gauche(), 0f, gauche() + largeur(), height.toFloat())
        c.drawPath(p, pTrait)
        c.restore()
        // Curseur et sa poignée.
        val xc = xDe(instant ?: maintenantS)
        pPlein.color = Palette.texte1
        c.drawRect(xc - 0.8f * s, 4f * s, xc + 0.8f * s, 108f * s, pPlein)
        r.set(xc - 8f * s, 40f * s, xc + 8f * s, 70f * s)
        pPlein.color = Palette.fond
        c.drawRoundRect(r, 8f * s, 8f * s, pPlein)
        pTrait.color = Palette.texte1
        pTrait.strokeWidth = 1.8f * s
        c.drawRoundRect(r, 8f * s, 8f * s, pTrait)
        pTrait.strokeWidth = 1.4f * s
        c.drawLine(xc - 3f * s, 48f * s, xc - 3f * s, 62f * s, pTrait)
        c.drawLine(xc + 3f * s, 48f * s, xc + 3f * s, 62f * s, pTrait)
        // Graduations du temps.
        pTexte.textSize = 14f * s
        pTexte.color = Palette.texte2
        for ((nom, dt, align) in listOf(Triple("il y a 3 h", 3 * 3600L, Paint.Align.LEFT), Triple("il y a 2 h", 2 * 3600L, Paint.Align.CENTER),
            Triple("il y a 1 h", 3600L, Paint.Align.CENTER), Triple("maintenant", 0L, Paint.Align.RIGHT))) {
            pTexte.textAlign = align
            c.drawText(nom, xDe(maintenantS - dt), 126f * s, pTexte)
        }
        c.restore()
    }
}
