package assistant.vocal.jarvis

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.Path
import android.graphics.drawable.GradientDrawable
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import org.json.JSONObject
import java.time.ZoneId
import kotlin.math.abs
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * Graphique de l'air d'une pièce en fonction du temps (S-L8, app 0.47.0). On y arrive en touchant la carte des mesures de
 * la vue 3D ou la ligne de l'air de l'accueil. Le panneau remplit l'écran : titre et bouton Fermer en haut, onglets
 * (l'air, la température et l'humidité) et durée (6 h, 24 h, 7 jours), puis deux courbes l'une sous l'autre avec les
 * bandes de seuil de Mesures. Glisser le doigt sur une courbe lit la valeur et l'heure, sur les deux courbes à la fois.
 *
 * Les données viennent du serveur du PC (message `air_historique`, une seule requête par durée, les quatre séries
 * dedans). Trois états en plus du graphique : lecture en cours, aucune mesure, erreur avec « Réessayer ». Toute la
 * logique (échelle, bandes, segments, heures, phrases) est dans [AirHistorique] et testée sans Android.
 */
internal class VueAirGraphique(private val ctx: Context) {

    var surFermer: () -> Unit = {}
    /** Un toucher sur le panneau : le compte des 45 s de l'accueil repart. */
    var surToucher: () -> Unit = {}
    /** Envoi de la demande au serveur (pièce, heures, suite sur le fil principal), null tant que la liaison manque. */
    var demander: ((String, Int, (JSONObject?) -> Unit) -> Unit)? = null
    var fuseau: ZoneId = AirHistorique.fuseau(ConfigMaison.json.optString("fuseau"))

    val vue = CadreMaquette(ctx).apply {
        visibility = View.GONE
        setBackgroundColor(Palette.fond)
        // Le panneau avale les touchers : rien ne tombe sur le plan ou sur l'accueil dessous.
        surVide = {}
    }

    private var s = CadreMaquette.estimer(ctx)
    private fun px(v: Float) = (v * s).roundToInt()

    private fun texte(couleur: Int, taille: Float) = TexteFondu(ctx).apply {
        peinture.typeface = Polices.texte(ctx)
        peinture.color = couleur
        taille(taille * s)
    }

    // ------------------------------------------------------------ état

    private enum class Phase { LECTURE, ERREUR, PRET }

    private var pieceId = ""
    private var nomPiece = ""
    private var duree = AirHistorique.Duree.PAR_DEFAUT
    private var groupe = AirHistorique.Groupe.AIR
    private var phase = Phase.LECTURE
    private var donnees: AirHistorique.Donnees? = null
    private var messageErreur = ""
    private var demande = 0
    private var curseur: Double? = null

    val ouverte: Boolean get() = vue.visibility == View.VISIBLE
    /** Un doigt est posé sur le panneau : le compte des 45 s est suspendu. */
    val doigtPose: Boolean get() = vue.doigtPose

    // ------------------------------------------------------------ vues

    private val titre = texte(Palette.texte2, 30f)

    private inner class Pilule(libelle: String, description: String, action: () -> Unit) {
        val mot = texte(Palette.texte2, 24f).apply { texte = libelle }
        val cadre = FrameLayout(ctx).apply {
            isClickable = true
            contentDescription = description
            setOnClickListener { action() }
            addView(mot, FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER))
        }

        fun style(choisie: Boolean) {
            mot.taille(24f * s)
            mot.couleur(if (choisie) Palette.texte1 else Palette.texte2)
            cadre.background = GradientDrawable().apply {
                cornerRadius = 28f * s
                setColor(if (choisie) Decor.melange(Palette.surface, Palette.texte1, 0.16f) else Decor.melange(Palette.fond, Palette.surface, 0.85f))
                setStroke(max(1, px(1f)), Decor.melange(Palette.surface, Palette.texte1, if (choisie) 0.25f else 0.08f))
            }
            cadre.setPadding(px(22f), 0, px(22f), 0)
        }
    }

    private val pilulesGroupe = AirHistorique.Groupe.values().map { g ->
        g to Pilule(g.titre, "Afficher ${g.titre.lowercase()}") { choisirGroupe(g) }
    }
    private val pilulesDuree = AirHistorique.Duree.values().map { d ->
        d to Pilule(d.libelle, "Afficher les mesures sur ${d.libelle}") { choisirDuree(d) }
    }
    private val rangGroupes = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        for ((_, p) in pilulesGroupe) addView(p.cadre)
    }
    private val rangDurees = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        for ((_, p) in pilulesDuree) addView(p.cadre)
    }

    private val croix = BoutonGlyphe(ctx, BoutonGlyphe.Forme.FERMER, 22f, Palette.texte2).apply {
        isClickable = false
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
    }
    private val motFermer = texte(Palette.texte2, 20f).apply { texte = "Fermer" }
    private val fermer = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        isClickable = true
        contentDescription = "Fermer le graphique de l'air"
        addView(croix)
        addView(motFermer)
        setOnClickListener { surFermer() }
    }

    private val haut = GrapheAir(ctx)
    private val bas = GrapheAir(ctx).apply { avecAxe = true }

    private val message = texte(Palette.texte2, 30f).apply { maxLignes = 3 }
    private val reessayer = Pilule("Réessayer", "Réessayer de lire les mesures") { charger() }
    private val blocEtat = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        gravity = Gravity.CENTER
        addView(message)
        addView(reessayer.cadre)
    }

    init {
        val n = Float.NaN
        val P = CadreMaquette::Place
        vue.addView(titre, P(44f, 30f, n, n, 820f, n))
        vue.addView(fermer, P(n, 24f, 32f, n, n, 60f))
        vue.addView(rangGroupes, P(44f, 108f, n, n, n, 56f))
        vue.addView(rangDurees, P(n, 108f, 32f, n, n, 56f))
        vue.addView(haut, P(0f, 176f, 0f, n, n, 296f))
        vue.addView(bas, P(0f, 476f, 0f, n, n, 308f))
        vue.addView(blocEtat, P(0f, 176f, 0f, 16f, n, n))
        // Les touchers sur le panneau comptent pour le retour automatique.
        vue.capter = { _, _ -> surToucher(); false }
        for (g in listOf(haut, bas)) g.surCurseur = { t, fini -> glisse(t, fini) }
        echelle(s)
        afficher()
    }

    /** Tailles de la maquette à l'échelle [e] de l'écran. */
    fun echelle(e: Float) {
        s = e
        titre.taille(30f * s)
        motFermer.taille(20f * s)
        croix.echelle = s
        croix.layoutParams = LinearLayout.LayoutParams(px(22f), px(22f)).apply { marginEnd = px(12f) }
        fermer.background = GradientDrawable().apply {
            cornerRadius = 30f * s
            setColor(Decor.melange(Palette.fond, Palette.surface, 0.85f))
            setStroke(max(1, px(1f)), Decor.melange(Palette.surface, Palette.texte1, 0.08f))
        }
        fermer.setPadding(px(18f), 0, px(22f), 0)
        fermer.layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, px(60f))
        for (p in pilulesGroupe.map { it.second } + pilulesDuree.map { it.second }) {
            p.cadre.layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, px(56f)).apply { marginEnd = px(10f) }
        }
        reessayer.cadre.layoutParams =LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, px(56f)).apply { topMargin = px(24f) }
        message.taille(30f * s)
        haut.echelle = s
        bas.echelle = s
        styler()
    }

    private fun styler() {
        for ((g, p) in pilulesGroupe) p.style(g == groupe)
        for ((d, p) in pilulesDuree) p.style(d == duree)
        reessayer.style(false)
    }

    // ------------------------------------------------------------ ouverture

    /** Ouvre le graphique de la pièce [id] (nom affiché [nom]) sur la durée par défaut et lance la lecture. */
    fun ouvrir(id: String, nom: String) {
        pieceId = id
        nomPiece = nom
        duree = AirHistorique.Duree.PAR_DEFAUT
        groupe = AirHistorique.Groupe.AIR
        curseur = null
        vue.visibility = View.VISIBLE
        styler()
        charger()
    }

    fun fermer() {
        demande++
        vue.removeCallbacks(efface)
        vue.visibility = View.GONE
        curseur = null
        donnees = null
        haut.relacher()
        bas.relacher()
    }

    private fun charger() {
        val n = ++demande
        phase = Phase.LECTURE
        curseur = null
        afficher()
        val envoi = demander
        val suite: (JSONObject?) -> Unit = { reponse ->
            if (n == demande && ouverte) recevoir(AirHistorique.lire(reponse))
        }
        if (envoi == null) suite(null) else envoi(pieceId, duree.heures, suite)
    }

    private fun recevoir(r: AirHistorique.Resultat) {
        when (r) {
            is AirHistorique.Resultat.Charge -> { donnees = r.donnees; phase = Phase.PRET }
            is AirHistorique.Resultat.Vide -> { donnees = r.donnees; phase = Phase.PRET }
            is AirHistorique.Resultat.Erreur -> { donnees = null; messageErreur = AirHistorique.messageErreur(r.message); phase = Phase.ERREUR }
        }
        afficher()
    }

    private fun choisirGroupe(g: AirHistorique.Groupe) {
        if (g == groupe) return
        groupe = g
        curseur = null
        styler()
        afficher()
    }

    private fun choisirDuree(d: AirHistorique.Duree) {
        if (d == duree) return
        duree = d
        styler()
        charger()
    }

    // ------------------------------------------------------------ lecture au doigt

    private val efface = Runnable {
        curseur = null
        majCurseur()
    }

    private fun glisse(t: Double?, fini: Boolean) {
        vue.removeCallbacks(efface)
        if (t != null) curseur = t
        majCurseur()
        // Le repère reste 5 s après le doigt levé, le temps de lire.
        if (fini) vue.postDelayed(efface, 5_000L)
    }

    private fun majCurseur() {
        haut.curseurT = curseur
        bas.curseurT = curseur
    }

    // ------------------------------------------------------------ affichage

    private fun afficher() {
        titre.texte = AirHistorique.titre(nomPiece, duree)
        val d = donnees
        val g = groupe.grandeurs
        val montrerGraphes = phase == Phase.PRET && d != null && d.aDesPoints(groupe)
        haut.visibility = if (montrerGraphes) View.VISIBLE else View.GONE
        bas.visibility = if (montrerGraphes) View.VISIBLE else View.GONE
        blocEtat.visibility = if (montrerGraphes) View.GONE else View.VISIBLE
        reessayer.cadre.visibility =if (phase == Phase.ERREUR) View.VISIBLE else View.GONE
        when (phase) {
            Phase.LECTURE -> message.texte = "Lecture des mesures de la pièce"
            Phase.ERREUR -> message.texte = messageErreur
            Phase.PRET -> message.texte = AirHistorique.phraseVide(groupe)
        }
        if (montrerGraphes && d != null) {
            for ((i, gr) in listOf(haut, bas).withIndex()) {
                gr.regler(g[i], d, fuseau)
                gr.curseurT = curseur
            }
        }
    }
}

/**
 * Une courbe d'une grandeur sur la période : bandes de seuil colorées (avec leur mot), repères horizontaux, repères du
 * temps en heure locale, courbe coupée aux trous de mesure, résumé de la période en haut à droite. Un doigt posé donne
 * l'heure et la valeur du point le plus proche (le repère est partagé avec l'autre courbe par le panneau).
 */
internal class GrapheAir(ctx: Context) : GrapheSante(ctx) {

    /** Instant lu au doigt, ou null. */
    var curseurT: Double? = null
        set(v) {
            if (v == field) return
            field = v
            invalidate()
        }
    /** Axe du temps écrit sous la courbe (la courbe du bas seulement). */
    var avecAxe = false
    /** Doigt posé ou déplacé (instant lu, fin du geste faux), puis levé (instant, fin du geste vrai). */
    var surCurseur: (Double?, Boolean) -> Unit = { _, _ -> }

    private var grandeur = AirHistorique.Grandeur.CO2
    private var donnees: AirHistorique.Donnees? = null
    private var fuseau: ZoneId = ZoneId.of("UTC")
    private val chemin = Path()

    private var gauche = 0f
    private var droite = 0f
    private var sommet = 0f
    private var fond = 0f

    fun regler(g: AirHistorique.Grandeur, d: AirHistorique.Donnees, z: ZoneId) {
        grandeur = g
        donnees = d
        fuseau = z
        contentDescription = description(g, d)
        invalidate()
    }

    private fun description(g: AirHistorique.Grandeur, d: AirHistorique.Donnees): String {
        val r = AirHistorique.resume(d.points(g)) ?: return "${g.titre}, aucune mesure sur la période"
        return "${g.titre}, ${AirHistorique.phraseResume(g, r)}"
    }

    override fun relacher() {
        curseurT = null
    }

    private fun geometrie(s: Float) {
        gauche = 96f * s
        droite = width - 44f * s
        sommet = 56f * s
        fond = height - (if (avecAxe) 48f else 10f) * s
    }

    private fun tDe(x: Float): Double? {
        val d = donnees ?: return null
        geometrie(echelle)
        if (droite <= gauche) return null
        val f = ((x - gauche) / (droite - gauche)).coerceIn(0f, 1f)
        return d.debut + f * (d.fin - d.debut)
    }

    override fun onTouchEvent(ev: MotionEvent): Boolean {
        when (ev.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                parent?.requestDisallowInterceptTouchEvent(true)
                surCurseur(tDe(ev.x), false)
            }
            MotionEvent.ACTION_MOVE -> surCurseur(tDe(ev.x), false)
            MotionEvent.ACTION_UP, MotionEvent.ACTION_CANCEL -> surCurseur(null, true)
        }
        return true
    }

    private fun couleurCourbe(g: AirHistorique.Grandeur): Int = when (g) {
        AirHistorique.Grandeur.TEMPERATURE -> Palette.accentLumiere
        AirHistorique.Grandeur.HUMIDITE -> Palette.accentPluie
        else -> Palette.texte1
    }

    override fun dessiner(c: Canvas, s: Float) {
        val d = donnees ?: return
        val g = grandeur
        val pts = d.points(g)
        val e = AirHistorique.echelle(g, pts)
        geometrie(s)
        if (droite <= gauche || fond <= sommet) return
        val etendue = if (d.fin > d.debut) d.fin - d.debut else 1.0
        fun xDe(t: Double): Float = gauche + ((t - d.debut) / etendue).toFloat().coerceIn(0f, 1f) * (droite - gauche)
        fun yDe(v: Double): Float = fond - e.fraction(v).toFloat() * (fond - sommet)

        // Bandes de seuil, avec le mot de chaque classe.
        plein.style = Paint.Style.FILL
        for (b in AirHistorique.bandes(g, e)) {
            val col = Palette.c(Mesures.COULEURS_AIR[b.rang])
            val yh = yDe(b.a)
            val yb = yDe(b.de)
            plein.color = alpha(col, 0.14f)
            c.drawRect(gauche, yh, droite, yb, plein)
            if (yb - yh >= 28f * s) texte(Mesures.MOTS_AIR[b.rang], droite - 10f * s, yh + 4f * s, 20f * s, alpha(col, 0.85f), Paint.Align.RIGHT)
        }

        // Repères horizontaux et leurs valeurs.
        trait.strokeWidth = max(1f, s)
        trait.color = alpha(Palette.filet, 0.8f)
        val decimales = if (e.pas % 1.0 != 0.0) 1 else 0
        for (v in e.graduations()) {
            val y = yDe(v)
            c.drawLine(gauche, y, droite, y, trait)
            texte(AirHistorique.formater(v, decimales), gauche - 12f * s, y - 12f * s, 20f * s, Palette.texte3, Paint.Align.RIGHT)
        }

        // Repères du temps, en heure locale.
        trait.color = alpha(Palette.filet, 0.5f)
        for (rp in AirHistorique.reperesTemps(d.debut, d.fin, fuseau)) {
            val x = xDe(rp.t)
            c.drawLine(x, sommet, x, fond, trait)
            if (avecAxe) texte(rp.libelle, x, fond + 10f * s, 22f * s, Palette.texte3, Paint.Align.CENTER)
        }

        // En-tête : la grandeur, puis le résumé de la période ou la lecture au doigt.
        texte("${g.titre}, ${g.unite}", 44f * s, 6f * s, 28f * s, Palette.texte1)
        val t = curseurT
        val limite = if (d.pas > 0.0) d.pas * 1.5 else Double.MAX_VALUE
        val proche = if (t != null) AirHistorique.plusProche(pts, t)?.takeIf { abs(it.t - t) <= limite } else null
        when {
            t != null && proche != null -> texte(AirHistorique.lecture(g, proche, fuseau), droite, 8f * s, 26f * s, Palette.texte1, Paint.Align.RIGHT)
            t != null -> texte("Pas de mesure à ${AirHistorique.heure(t, fuseau)}", droite, 8f * s, 26f * s, Palette.texte2, Paint.Align.RIGHT)
            else -> {
                val r = AirHistorique.resume(pts)
                texte(
                    if (r == null) "Aucune mesure" else AirHistorique.phraseResume(g, r),
                    droite, 8f * s, 24f * s, Palette.texte2, Paint.Align.RIGHT,
                )
            }
        }

        // Courbe, coupée aux trous de mesure.
        val col = couleurCourbe(g)
        trait.color = col
        trait.strokeWidth = 3.5f * s
        for (seg in AirHistorique.segments(pts, d.pas)) {
            if (seg.size == 1) {
                plein.color = col
                c.drawCircle(xDe(seg[0].t), yDe(seg[0].v), 3.5f * s, plein)
                continue
            }
            chemin.rewind()
            for ((i, p) in seg.withIndex()) if (i == 0) chemin.moveTo(xDe(p.t), yDe(p.v)) else chemin.lineTo(xDe(p.t), yDe(p.v))
            c.drawPath(chemin, trait)
        }
        if (pts.isEmpty()) {
            texte("Pas de mesure de ${g.titre} sur cette période", (gauche + droite) / 2f, (sommet + fond) / 2f - 14f * s, 26f * s, Palette.texte3, Paint.Align.CENTER)
        }

        // Repère du doigt et point lu.
        if (t != null) {
            val x = xDe(proche?.t ?: t.coerceIn(d.debut, d.fin))
            trait.color = alpha(Palette.texte1, 0.6f)
            trait.strokeWidth = max(1.5f, 2f * s)
            c.drawLine(x, sommet, x, fond, trait)
            if (proche != null) {
                val y = yDe(proche.v)
                plein.color = Palette.fond
                c.drawCircle(x, y, 11f * s, plein)
                plein.color = AirHistorique.couleurAir(g, proche.v)?.let { Palette.c(it) } ?: col
                c.drawCircle(x, y, 7.5f * s, plein)
            }
        }
    }
}
