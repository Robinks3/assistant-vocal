package assistant.vocal.jarvis

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.DashPathEffect
import android.graphics.LinearGradient
import android.graphics.Paint
import android.graphics.RadialGradient
import android.graphics.Shader
import android.graphics.drawable.GradientDrawable
import android.os.SystemClock
import android.view.Gravity
import android.view.View
import android.view.ViewGroup
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import org.json.JSONArray
import org.json.JSONObject
import java.time.LocalTime
import kotlin.math.max
import kotlin.math.min
import kotlin.math.roundToInt

/**
 * La maison en grand (0.27.0) : ce que l'appli pose au-dessus du plan 3D agrandi, piste « mélange » du canevas
 * (version 29, planches `MaisonMelange`, `MaisonEntiere`, `MaisonChambre`, `MaisonMelangeEchec`, `MaisonHorsLigne`).
 *
 * En haut à gauche « La maison » et la consigne, en haut à droite « Tous les appareils » (écran Maison) et Fermer.
 * Une pièce choisie ouvre son panneau à droite (x 812, 436 px de large) : ses lampes (rond mat pour allumer ou
 * éteindre, piste de l'intensité, appui long pour la couleur ou le blanc), la télé, la musique qui y joue et le
 * volume de chaque enceinte, jamais au-delà du plafond s'il y en a un. Toute la ligne est cible.
 *
 * Chaque commande passe par les mêmes contrôles que la voix : Securite.verifier ici pour répondre tout de suite,
 * puis Maison.commande ou Maison.commandeMedia qui plafonnent le volume et revérifient avant l'envoi, la passerelle
 * vérifiant encore de son côté. Un réglage au doigt part au plus toutes les 300 ms pendant le geste et à la fin
 * (Cadence), jamais une commande par pixel. L'état demandé est montré tout de suite (Attentes) : sans confirmation
 * de Home Assistant au bout de 5 s, la ligne garde la valeur en fantôme et dit « n'a pas répondu », une phrase ambre
 * le dit en bas pendant 8 s.
 */
internal class VueMaisonGrand(private val ctx: Context) {

    var surFermer: () -> Unit = {}
    var surAppareils: () -> Unit = {}
    /** Quelque chose a changé ici (commande partie, surlignage) : l'accueil renvoie les pastilles à la page. */
    var surChange: () -> Unit = {}
    /** Un toucher sur le panneau ou la barre du haut : le compte des 45 s repart. */
    var surToucher: () -> Unit = {}

    val vue = CadreMaquette(ctx).apply {
        clipChildren = false
        visibility = View.GONE
    }

    private var s = CadreMaquette.estimer(ctx)
    private fun px(v: Float) = (v * s).roundToInt()

    private fun texte(couleur: Int, taille: Float = 18f) = TexteFondu(ctx).apply {
        peinture.typeface = Polices.texte(ctx)
        peinture.color = couleur
        taille(taille * s)
    }

    private val titre = texte(Palette.texte2, 30f).apply { texte = "La maison" }
    private val consigne = texte(Palette.texte3, 18f)
    private val tete = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        // Un toucher sur le titre ne tombe pas dans le vide du plan (il fermerait la maison en grand).
        isClickable = true
        addView(titre)
        addView(consigne)
    }

    private val motAppareils = texte(Palette.texte2, 20f).apply { texte = "Tous les appareils" }
    private val appareils = FrameLayout(ctx).apply {
        isClickable = true
        contentDescription = "Tous les appareils, écran Maison"
        setOnClickListener { surAppareils() }
        addView(motAppareils, FrameLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT, Gravity.CENTER_VERTICAL))
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
        contentDescription = "Fermer la maison et revenir à l'accueil"
        addView(croix)
        addView(motFermer)
        setOnClickListener { surFermer() }
    }
    private val barre = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        isClickable = true
        gravity = Gravity.CENTER_VERTICAL
        addView(appareils)
        addView(fermer)
    }

    /** Panneau de la pièce : défilement si son contenu dépasse la hauteur de l'écran. */
    private val contenuPanneau = LinearLayout(ctx).apply {
        orientation = LinearLayout.VERTICAL
        // Les lignes débordent de 10 px de chaque côté (fond de surlignage), comme la maquette.
        clipToPadding = false
    }
    private val defile = ScrollView(ctx).apply {
        isVerticalScrollBarEnabled = false
        overScrollMode = View.OVER_SCROLL_NEVER
        addView(contenuPanneau)
    }
    private val panneau = object : FrameLayout(ctx) {
        override fun onMeasure(l: Int, h: Int) {
            val hMax = px(HAUTEUR_MAX_PANNEAU)
            super.onMeasure(l, MeasureSpec.makeMeasureSpec(min(MeasureSpec.getSize(h), hMax), MeasureSpec.AT_MOST))
        }
    }.apply {
        addView(defile)
        visibility = View.GONE
    }

    private val pointMessage = View(ctx)
    private val texteMessage = texte(Palette.accentLumiere, 20f)
    private val message = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        isClickable = true
        gravity = Gravity.CENTER_VERTICAL
        addView(pointMessage)
        addView(texteMessage)
        visibility = View.GONE
    }

    init {
        val n = Float.NaN
        val P = CadreMaquette::Place
        vue.addView(tete, P(44f, 30f, n, n, 700f, n))
        vue.addView(barre, P(n, 24f, 32f, n, n, 60f))
        vue.addView(panneau, P(812f, 112f, n, n, LARGEUR_PANNEAU, n))
        vue.addView(message, P(44f, n, n, 34f, 740f, n))
        // Les touchers sur le panneau et la barre comptent pour le retour automatique.
        vue.capter = { _, _ -> surToucher(); false }
        echelle(s)
    }

    /** Tailles de la maquette à l'échelle [e] de l'écran (le panneau ouvert est refait). */
    fun echelle(e: Float) {
        s = e
        titre.taille(30f * s)
        consigne.taille(18f * s)
        consigne.layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = px(6f) }
        motAppareils.taille(20f * s)
        appareils.setPadding(px(18f), 0, px(18f), 0)
        appareils.layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, px(60f)).apply { marginEnd = px(10f) }
        croix.echelle = s
        croix.layoutParams = LinearLayout.LayoutParams(px(22f), px(22f)).apply { marginEnd = px(12f) }
        motFermer.taille(20f * s)
        fermer.background = GradientDrawable().apply {
            cornerRadius = 30f * s
            setColor(Decor.melange(Palette.fond, Palette.surface, 0.85f))
            setStroke(max(1, px(1f)), Decor.melange(Palette.surface, Palette.texte1, 0.08f))
        }
        fermer.setPadding(px(18f), 0, px(22f), 0)
        fermer.layoutParams = LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, px(60f))
        panneau.background = GradientDrawable(
            GradientDrawable.Orientation.TOP_BOTTOM,
            intArrayOf(
                Decor.melange(Palette.surface, Palette.texte1, 0.05f) and 0x00FFFFFF or (0xF0 shl 24),
                Palette.surface and 0x00FFFFFF or (0xF0 shl 24),
                Decor.melange(Palette.surface, Palette.fond, 0.3f) and 0x00FFFFFF or (0xF5 shl 24),
            ),
        ).apply { cornerRadius = 24f * s }
        panneau.elevation = 24f * s
        contenuPanneau.setPadding(px(26f), px(24f), px(26f), px(18f))
        pointMessage.background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(Palette.accentLumiere) }
        pointMessage.layoutParams = LinearLayout.LayoutParams(px(10f), px(10f)).apply { marginEnd = px(12f) }
        texteMessage.taille(20f * s)
        piece?.let { construire(it) }
    }

    // ------------------------------------------------------------ état

    private var piece: MaisonEnGrand.Piece? = null
    private var lus: Map<String, Appareils.Appareil> = emptyMap()
    private var lecteurs: List<Etat.Lecteur> = emptyList()
    private var injoignable = false
    private var soir = false
    private val attentes = Attentes()
    private val cadences = HashMap<String, Cadence>()
    private val cadencesBlanc = HashMap<String, Cadence>()
    private val cadencesTeinte = HashMap<String, Cadence>()
    private val visees = HashMap<String, VolumeVise>()
    private var surligne: String? = null
    private var surligneJusqua = 0L
    private var messageJusqua = 0L
    private val echecsDits = HashSet<String>()
    private var brefVu = 0L
    private val lignes = mutableListOf<Ligne>()
    private var teinteOuverte: String? = null

    val ouverte: Boolean get() = vue.visibility == View.VISIBLE
    val pieceChoisie: MaisonEnGrand.Piece? get() = piece
    /** Un doigt est posé sur une piste du panneau : rien ne bouge, le compte des 45 s est suspendu. */
    val doigtSurPiste: Boolean get() = lignes.any { it.glisse }

    fun ouvrir() {
        vue.visibility = View.VISIBLE
        brefVu = Etat.courant.brefLe
    }

    fun fermer() {
        vue.visibility = View.GONE
        montrerPiece(null)
        attentes.oublier()
        cadences.clear()
        cadencesBlanc.clear()
        cadencesTeinte.clear()
        visees.clear()
        echecsDits.clear()
        messageJusqua = 0L
        message.visibility = View.GONE
    }

    /** Pièce dont le panneau s'ouvre, ou null pour la maison entière (sans panneau). */
    fun montrerPiece(p: MaisonEnGrand.Piece?) {
        if (p?.id == piece?.id && (p == null || lignes.isNotEmpty())) return
        piece = p
        teinteOuverte = null
        surligne = null
        if (p == null) {
            panneau.visibility = View.GONE
            contenuPanneau.removeAllViews()
            lignes.clear()
        } else {
            construire(p)
            panneau.visibility = View.VISIBLE
            defile.scrollTo(0, 0)
        }
        majConsigne()
    }

    /** Phrase brève en bas à gauche, en ambre, [dureeMs]. */
    fun dire(t: String, dureeMs: Long = DUREE_MESSAGE_MS) {
        if (t.isBlank()) return
        texteMessage.texte = t
        message.visibility = View.VISIBLE
        messageJusqua = SystemClock.elapsedRealtime() + dureeMs
    }

    /**
     * États lus et contexte, à chaque rafraîchissement de l'accueil. [depuis] : début de la panne de la maison.
     * Rend vrai si les pastilles doivent être renvoyées (une demande confirmée ou en échec).
     */
    fun maj(
        lumieres: List<Appareils.Appareil>, medias: List<Appareils.Appareil>, lecteurs: List<Etat.Lecteur>,
        injoignable: Boolean, depuis: LocalTime?, soir: Boolean, bref: String, brefLe: Long,
    ): Boolean {
        val t = SystemClock.elapsedRealtime()
        lus = MaisonEnGrand.index(lumieres, medias)
        this.lecteurs = lecteurs
        val avant = this.injoignable
        this.injoignable = injoignable
        this.soir = soir
        var change = attentes.avancer(lus, t)
        // Échecs nouveaux : une phrase ambre, 8 s.
        val echecs = attentes.echecs.filter { it !in echecsDits }
        if (echecs.isNotEmpty()) {
            echecsDits.addAll(echecs)
            dire(MaisonEnGrand.phraseEchec(echecs.map { id -> objetDe(id)?.let { MaisonEnGrand.nom(it, lus[id]) } ?: Maison.nomBrut(id) }), Attentes.DUREE_ECHEC_MS)
        }
        echecsDits.retainAll(attentes.echecs.toSet())
        // Refus de la sécurité ou de la passerelle, erreur de HA : dits ici, la colonne de l'accueil étant cachée.
        if (brefLe != brefVu) {
            brefVu = brefLe
            if (bref.isNotBlank() && t - brefLe < DUREE_MESSAGE_MS) dire(bref)
        }
        if (injoignable) {
            val h = depuis?.let { " depuis ${it.hour} h ${"%02d".format(it.minute)}" } ?: ""
            if (!avant || t >= messageJusqua) dire("La maison ne répond plus$h : rien ne peut partir.", 60_000L)
        } else if (avant) {
            messageJusqua = 0L
        }
        if (surligne != null && t >= surligneJusqua) {
            surligne = null
            change = true
        }
        if (message.visibility == View.VISIBLE && t >= messageJusqua) message.visibility = View.GONE
        majConsigne()
        majLignes(t)
        return change
    }

    /** Une demande attend sa confirmation, ou un surlignage doit s'éteindre : l'accueil se revoit plus vite. */
    val enMouvement: Boolean get() = attentes.enAttente || surligne != null

    /** Pastilles de la pièce choisie pour la page (états prévus compris), ou une liste vide. */
    fun pastilles(): JSONArray {
        val p = piece ?: return JSONArray()
        val vus = attentes.vus(lus)
        val suivis = p.objets.mapNotNull { o ->
            val a = MaisonEnGrand.trouver(o, vus) ?: return@mapNotNull null
            if (attentes.fantome(a.id) != null) o.entite to MaisonEnGrand.Suivi.RATE else null
        }.toMap()
        return MaisonEnGrand.pastilles(p, vus, suivis, surligne, injoignable)
    }

    /**
     * Pastille touchée sur la 3D : une lampe ou la télé s'allume ou s'éteint, une enceinte montre sa ligne. Dans tous
     * les cas la ligne est surlignée 400 ms et amenée dans le panneau.
     */
    fun pastille(entite: String) {
        val o = piece?.objets?.firstOrNull { it.entite == entite } ?: return
        surToucher()
        surligner(o.entite)
        lignes.firstOrNull { it.objet.entite == o.entite }?.let { l -> defile.post { defile.smoothScrollTo(0, max(0, l.vue.top - px(12f))) } }
        if (o.genre != MaisonEnGrand.Genre.ENCEINTE) basculer(o)
    }

    private fun surligner(entite: String) {
        surligne = entite
        surligneJusqua = SystemClock.elapsedRealtime() + DUREE_SURLIGNE_MS
        majLignes(SystemClock.elapsedRealtime())
        surChange()
        vue.postDelayed({ if (surligne == entite && SystemClock.elapsedRealtime() >= surligneJusqua) { surligne = null; majLignes(SystemClock.elapsedRealtime()); surChange() } }, DUREE_SURLIGNE_MS + 20L)
    }

    private fun objetDe(id: String): MaisonEnGrand.Objet? =
        piece?.objets?.firstOrNull { it.entite == id || id in it.alias }

    private fun majConsigne() {
        val c = when {
            injoignable -> "Home Assistant ne répond plus."
            piece == null -> "Touche une pièce pour la régler."
            else -> "Touche une autre pièce, ou le vide pour revoir la maison."
        }
        if (consigne.texte.toString() != c) consigne.texte = c
    }

    // ------------------------------------------------------------ commandes

    private fun maintenant() = SystemClock.elapsedRealtime()

    /** Appareil montré pour un objet : l'état prévu s'il attend sa confirmation, sinon l'état lu. */
    private fun vu(o: MaisonEnGrand.Objet): Appareils.Appareil? = MaisonEnGrand.trouver(o, attentes.vus(lus))

    /** Commande d'un objet par les contrôles de la voix : Securite d'abord, puis Maison.commande. */
    private fun envoyer(c: Appareils.Commande?, prevu: Appareils.Appareil?, volume: Boolean = false): Boolean {
        if (c == null) return false
        if (injoignable) { dire("La maison ne répond plus : rien ne peut partir."); return false }
        val action = Etat.actionService
        if (action == null) { dire("${ConfigMaison.NOM_ASSISTANT} est à l'arrêt : commande non envoyée."); return false }
        Securite.verifier(c.verification(), personne = Etat.courant.quiParle())?.let { dire("Je ne le fais pas : $it"); return false }
        prevu?.let { attentes.poser(it, maintenant(), volume) }
        action(c.service, c.corps, c.verification())
        majLignes(maintenant())
        surChange()
        return true
    }

    private fun basculer(o: MaisonEnGrand.Objet) {
        val a = vu(o) ?: return
        if (MaisonEnGrand.horsLigne(a)) { dire("${MaisonEnGrand.nom(o, a)} est hors ligne."); return }
        val c = Appareils.basculer(a) ?: return
        val prevu = when (o.genre) {
            MaisonEnGrand.Genre.LAMPE -> MaisonEnGrand.prevuBascule(a, c)
            else -> a.copy(etat = if (c.service.endsWith("turn_on")) "on" else "off")
        }
        envoyer(c, prevu)
    }

    private fun intensite(o: MaisonEnGrand.Objet, pct: Int) {
        val a = vu(o) ?: return
        if (MaisonEnGrand.horsLigne(a)) return
        envoyer(Appareils.regler(a, pct / 100f), MaisonEnGrand.prevuIntensite(a, pct))
    }

    /** Blanc au kelvin près (bornes de la lampe), relu ensuite par la conformité à 100 K. */
    private fun blancK(o: MaisonEnGrand.Objet, kelvin: Int) {
        val a = vu(o) ?: return
        val c = Appareils.blanc(a, kelvin)
        envoyer(c, a.copy(etat = "on", mode = "color_temp", kelvin = c.corps.optInt("color_temp_kelvin", kelvin)))
    }

    /** Couleur nommée ou teinte du curseur : hs_color à pleine saturation, la luminosité ne bouge pas. */
    private fun teinte(o: MaisonEnGrand.Objet, degres: Int) {
        val a = vu(o) ?: return
        val d = ((degres % 360) + 360) % 360
        envoyer(
            Appareils.teinte(a, d),
            a.copy(etat = "on", mode = "hs", teinte = d.toFloat(), rgb = ReglageLampe.rgbDeTeinte(d.toFloat()), kelvin = null),
        )
    }

    /**
     * Volume d'une enceinte, comme sur l'accueil : par Etat.actionMedia (Maison.commandeMedia, qui applique le
     * plafond réglé et revérifie, baisse permise la nuit par volume_down). La valeur est bornée ici aussi
     * (VolumeVise.MAX).
     */
    private fun volume(o: MaisonEnGrand.Objet, sens: Int, fraction: Float?) {
        val a = vu(o) ?: return
        if (MaisonEnGrand.horsLigne(a)) { dire("${MaisonEnGrand.nom(o, a)} est hors ligne."); return }
        if (injoignable) { dire("La maison ne répond plus : rien ne peut partir."); return }
        val action = Etat.actionMedia
        if (action == null) { dire("${ConfigMaison.NOM_ASSISTANT} est à l'arrêt : commande non envoyée."); return }
        val t = maintenant()
        val lu = lus[a.id]?.volume ?: a.volume ?: 0.0
        val vise = visees.getOrPut(a.id) { VolumeVise(Attentes.DELAI_MS) }
        val avant = vise.affiche(lu, t)
        val apres = (if (fraction != null) vise.glisser(fraction * VolumeVise.MAX, t) else vise.pas(lu, sens, t) ?: return)
            .let { Securite.plafonnerVolume(it) }
        val baisse = apres < avant
        val corps = JSONObject().put("entity_id", a.id).put("volume_level", apres)
        if (!baisse) Securite.verifier(JSONObject(corps.toString()).put("service", "media_player.volume_set"))?.let { dire("Je ne le fais pas : $it"); return }
        attentes.poser(a.copy(volume = apres), t, volume = true)
        action(a.id, "volume_set", JSONObject().put("volume_level", apres).put("baisse", baisse))
        majLignes(t)
        surChange()
    }

    // ------------------------------------------------------------ panneau

    /** Une ligne du panneau : sa vue et ce qu'elle montre de l'objet. */
    private abstract inner class Ligne(val objet: MaisonEnGrand.Objet) {
        abstract val vue: View
        open val glisse: Boolean get() = false
        abstract fun maj(a: Appareils.Appareil?, fantome: Appareils.Appareil?, t: Long)

        /** Fond de 6 % de blanc 400 ms quand sa pastille vient d'être touchée, ou elle-même. */
        protected val fondSurligne = GradientDrawable().apply { cornerRadius = 14f * s }
        protected fun surlignee(on: Boolean) {
            fondSurligne.setColor(if (on) 0x0FFFFFFF else 0)
        }
    }

    private fun construire(p: MaisonEnGrand.Piece) {
        contenuPanneau.removeAllViews()
        lignes.clear()
        val nom = texte(Palette.texte1, 30f).apply { texte = p.nom }
        contenuPanneau.addView(nom)
        val resume = texte(Palette.texte2, 18f)
        resume.tag = TAG_RESUME
        contenuPanneau.addView(resume, lp(haut = 6f))
        for (o in p.lampes) {
            val l = LigneLampe(o)
            lignes.add(l)
            contenuPanneau.addView(l.vue, lp(haut = 14f, gauche = -10f, droite = -10f, hauteur = 64f))
            contenuPanneau.addView(l.teintes, lp(haut = 6f, gauche = 72f))
        }
        val tele = p.tele
        val enceintes = p.enceintes
        if (tele != null || enceintes.isNotEmpty()) {
            if (p.lampes.isNotEmpty()) contenuPanneau.addView(View(ctx).apply { setBackgroundColor(Palette.filet) }, lp(haut = 18f, hauteur = 1f))
            if (tele != null) {
                val l = LigneTele(tele)
                lignes.add(l)
                contenuPanneau.addView(l.vue, lp(haut = 14f, gauche = -10f, droite = -10f, hauteur = 64f))
            }
            val musique = LinearLayout(ctx).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                tag = TAG_MUSIQUE
                addView(View(ctx).apply { background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(Palette.musique) } }, LinearLayout.LayoutParams(px(8f), px(8f)).apply { marginEnd = px(10f) })
                addView(texte(Palette.texte3, 17f))
                visibility = View.GONE
            }
            contenuPanneau.addView(musique, lp(haut = 12f))
            for (o in enceintes) {
                val l = LigneVolume(o)
                lignes.add(l)
                contenuPanneau.addView(l.vue, lp(haut = 10f))
            }
        }
        majLignes(maintenant())
    }

    /** Texte posé seulement s'il change : TexteFondu refait sa mise en page à chaque nouvelle chaîne. */
    private fun poser(t: TexteFondu, v: String) {
        if (t.texte.toString() != v) t.texte = v
    }

    private fun lp(haut: Float = 0f, gauche: Float = 0f, droite: Float = 0f, hauteur: Float = Float.NaN) =
        LinearLayout.LayoutParams(ViewGroup.LayoutParams.MATCH_PARENT, if (hauteur.isNaN()) ViewGroup.LayoutParams.WRAP_CONTENT else px(hauteur)).apply {
            topMargin = px(haut)
            marginStart = px(gauche)
            marginEnd = px(droite)
        }

    private fun majLignes(t: Long) {
        val p = piece ?: return
        val vus = attentes.vus(lus)
        (contenuPanneau.findViewWithTag<TexteFondu>(TAG_RESUME))?.let { r ->
            val v = if (injoignable) "" else MaisonEnGrand.resume(p, vus)
            if (r.texte.toString() != v) r.texte = v
            r.visibility = if (v.isEmpty()) View.GONE else View.VISIBLE
        }
        for (l in lignes) {
            val a = MaisonEnGrand.trouver(l.objet, vus)
            val f = a?.let { attentes.fantome(it.id) }
            l.maj(if (injoignable) null else a, f, t)
        }
        // La musique qui joue sur une enceinte de la pièce, sous la télé.
        (contenuPanneau.findViewWithTag<LinearLayout>(TAG_MUSIQUE))?.let { m ->
            val ids = p.enceintes.flatMap { listOf(it.entite) + it.alias }.toSet()
            val l = lecteurs.firstOrNull { it.etat == "playing" && (it.id in ids || it.membres.any { x -> x in ids }) }
            val txt = if (injoignable || l == null) "" else listOf(l.titre, l.artiste).filter { it.isNotBlank() }.joinToString(", ").ifEmpty { "Musique en cours" }
            val tv = m.getChildAt(1) as TexteFondu
            if (tv.texte.toString() != txt) tv.texte = txt
            m.visibility = if (txt.isEmpty()) View.GONE else View.VISIBLE
        }
    }

    /** Lampe : rond pour allumer ou éteindre, nom et état, piste de l'intensité, appui long pour la teinte. */
    private inner class LigneLampe(o: MaisonEnGrand.Objet) : Ligne(o) {
        private val rond = RondBascule(ctx, RondBascule.Glyphe.AMPOULE)
        private val nom = texte(Palette.texte1, 21f)
        private val etat = texte(ETAT, 17f)
        private val etatDroite = texte(Palette.texte2, 17f)
        private val piste = PisteVolume(ctx).apply {
            plafond = false
            echelle = s
        }
        private val cadence = cadences.getOrPut(o.entite) { Cadence() }
        private val cadenceBlanc = cadencesBlanc.getOrPut(o.entite) { Cadence() }
        private val cadenceTeinte = cadencesTeinte.getOrPut(o.entite) { Cadence() }
        override val glisse: Boolean get() = piste.glisse || pisteBlanc.glisse || pisteTeinte.glisse
        private var reglable = false
        private val chevron = ChevronVolet(ctx)

        /** Onglet choisi au doigt (true : Couleur), null tant que personne n'a choisi : la lampe décide. */
        private var ongletCouleur: Boolean? = null

        /** Ligne qui s'ouvre sous la lampe (0.34.0) : onglets Blanc et Couleur, chacun avec ses pastilles nommées et sa piste. */
        val teintes = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            visibility = View.GONE
        }
        private val entete = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        private val onglets = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
        private val ongletBlanc = texte(Palette.texte1, 18f)
        private val ongletCoul = texte(Palette.texte1, 18f)
        private val valeurReglage = texte(Palette.texte2, 18f)
        private val panneauBlanc = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }
        private val panneauCouleur = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }
        private val pastillesBlanc = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
        private val pastillesCouleur = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
        private val pisteBlanc = PisteBlanc(ctx)
        private val pisteTeinte = PisteBlanc(ctx).apply {
            bande = true
            degrade = IntArray(7) { Color.HSVToColor(floatArrayOf(it * 60f, 1f, 1f)) }
            gauche = ""
            droite = ""
            contentDescription = "Teinte de la couleur"
        }

        override val vue: View = LinearLayout(ctx).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            background = fondSurligne
            setPadding(px(10f), 0, 0, 0)
            isClickable = true
            isLongClickable = true
            // La ligne déplie le volet (lampe réglable) ou bascule (simple marche / arrêt), le rond bascule toujours.
            setOnClickListener { surToucher(); surligner(o.entite); toucherLigne(o) }
            setOnLongClickListener { surToucher(); ouvrirTeintes(); true }
            addView(rond, LinearLayout.LayoutParams(px(56f), px(56f)).apply { marginEnd = px(16f) })
            addView(LinearLayout(ctx).apply {
                orientation = LinearLayout.VERTICAL
                addView(nom)
                addView(etat, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = px(2f) })
            }, LinearLayout.LayoutParams(px(LARGEUR_NOM), ViewGroup.LayoutParams.WRAP_CONTENT).apply { marginEnd = px(4f) })
            // Variante C : le chevron suit le nom, la piste d'intensité prend toute la largeur restante.
            addView(chevron, LinearLayout.LayoutParams(px(48f), px(56f)).apply { marginEnd = px(12f) })
            addView(etatDroite, LinearLayout.LayoutParams(0, ViewGroup.LayoutParams.WRAP_CONTENT, 1f).apply { marginEnd = px(24f) })
            addView(piste, LinearLayout.LayoutParams(0, px(56f), 1f).apply { marginEnd = px(16f) })
        }

        init {
            etatDroite.aDroite = true
            rond.setOnClickListener { surToucher(); surligner(o.entite); basculer(o) }
            piste.surDebut = { surToucher(); surligner(o.entite) }
            piste.surBouge = { f -> surToucher(); cadence.bouge(pourcent(f), maintenant())?.let { intensite(o, it) } }
            piste.surLacher = { f -> surToucher(); cadence.fin(pourcent(f), maintenant())?.let { intensite(o, it) } }
            // Le chevron n'est qu'un indice : le toucher passe à la ligne.
            chevron.isClickable = false
            roleBouton(rond)
            roleBouton(vue)
            for (b in ReglageLampe.BLANCS) {
                pastillesBlanc.addView(pastille(b.rgb, "Blanc ${b.nom.lowercase()}", b.nom) {
                    surToucher(); surligner(o.entite); blancK(o, b.kelvin)
                }, LinearLayout.LayoutParams(px(88f), ViewGroup.LayoutParams.WRAP_CONTENT).apply { marginEnd = px(8f) })
            }
            for (t in ReglageLampe.TEINTES) {
                val rgb = ReglageLampe.rgbDeTeinte(t.degres.toFloat())
                pastillesCouleur.addView(pastille(Color.rgb(rgb[0], rgb[1], rgb[2]), "Couleur ${t.nom.lowercase()}", t.nom) {
                    surToucher(); surligner(o.entite); teinte(o, t.degres)
                }, LinearLayout.LayoutParams(px(72f), ViewGroup.LayoutParams.WRAP_CONTENT).apply { marginEnd = px(6f) })
            }
            ongletBlanc.texte = "Blanc"
            ongletCoul.texte = "Couleur"
            ongletBlanc.setOnClickListener { surToucher(); ongletCouleur = false; majLignes(maintenant()) }
            ongletCoul.setOnClickListener { surToucher(); ongletCouleur = true; majLignes(maintenant()) }
            ongletBlanc.contentDescription = "Réglage du blanc"
            ongletCoul.contentDescription = "Réglage de la couleur"
            onglets.addView(ongletBlanc, LinearLayout.LayoutParams(px(110f), px(48f)).apply { marginEnd = px(8f) })
            onglets.addView(ongletCoul, LinearLayout.LayoutParams(px(110f), px(48f)).apply { marginEnd = px(16f) })
            // La valeur vit hors des onglets : une lampe à un seul mode les cache mais garde sa valeur.
            entete.addView(onglets)
            entete.addView(valeurReglage, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, px(48f)))
            panneauBlanc.addView(pastillesBlanc)
            panneauBlanc.addView(pisteBlanc, LinearLayout.LayoutParams(px(380f), px(56f)).apply { topMargin = px(8f) })
            panneauCouleur.addView(pastillesCouleur)
            panneauCouleur.addView(pisteTeinte, LinearLayout.LayoutParams(px(380f), px(56f)).apply { topMargin = px(8f) })
            teintes.addView(entete)
            teintes.addView(panneauBlanc, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = px(8f) })
            teintes.addView(panneauCouleur, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = px(8f) })
            // Les deux pistes passent par la Cadence : une valeur toutes les 300 ms pendant le geste, la dernière au lâcher.
            pisteBlanc.surDebut = { surToucher(); surligner(o.entite) }
            pisteBlanc.surBouge = { f -> surToucher(); vu(o)?.let { a -> cadenceBlanc.bouge(ReglageLampe.kelvinDe(a, f), maintenant())?.let { blancK(o, it) } } }
            pisteBlanc.surAnnule = { cadenceBlanc.fin(0, maintenant()) }
            pisteBlanc.surLacher = { f -> surToucher(); vu(o)?.let { a -> cadenceBlanc.fin(ReglageLampe.kelvinDe(a, f), maintenant())?.let { blancK(o, it) } } }
            pisteTeinte.surDebut = { surToucher(); surligner(o.entite) }
            pisteTeinte.surBouge = { f -> surToucher(); cadenceTeinte.bouge(degresDe(f), maintenant())?.let { teinte(o, it) } }
            pisteTeinte.surAnnule = { cadenceTeinte.fin(0, maintenant()) }
            pisteTeinte.surLacher = { f -> surToucher(); cadenceTeinte.fin(degresDe(f), maintenant())?.let { teinte(o, it) } }
        }

        /** Position de la bande (0 à 1) en degrés de teinte, de 0 à 359. */
        private fun degresDe(f: Float) = (f.coerceIn(0f, 1f) * 359f).roundToInt()

        /** Pastille ronde de la couleur [rgb] avec son nom dessous. */
        private fun pastille(rgb: Int, description: String, nomCourt: String, clic: () -> Unit) = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            isClickable = true
            contentDescription = description
            setOnClickListener { clic() }
            addView(View(ctx).apply {
                background = GradientDrawable().apply { shape = GradientDrawable.OVAL; setColor(rgb) }
            }, LinearLayout.LayoutParams(px(48f), px(48f)))
            addView(texte(Palette.texte3, 14f).apply { texte = nomCourt }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = px(2f) })
        }

        /** Pourcentage d'intensité au doigt : au moins 1 % (une lampe ne s'éteint que par son rond). */
        private fun pourcent(f: Float) = (f * 100).roundToInt().coerceIn(1, 100)

        /** Bouton pour TalkBack, sans changer le reste du comportement de la vue. */
        private fun roleBouton(v: View) {
            v.accessibilityDelegate = object : View.AccessibilityDelegate() {
                override fun onInitializeAccessibilityNodeInfo(host: View, info: android.view.accessibility.AccessibilityNodeInfo) {
                    super.onInitializeAccessibilityNodeInfo(host, info)
                    info.className = android.widget.Button::class.java.name
                }
            }
        }

        private fun toucherLigne(o: MaisonEnGrand.Objet) {
            val a = vu(o)
            when (ReglageLampe.gesteLigne(a, MaisonEnGrand.horsLigne(a))) {
                ReglageLampe.Geste.DEPLIER -> ouvrirTeintes()
                ReglageLampe.Geste.BASCULER -> basculer(o)
            }
        }

        private fun ouvrirTeintes() {
            val a = vu(objet) ?: return
            if (!a.couleur && !a.blanc) return
            val ouvre = teinteOuverte != objet.entite
            teinteOuverte = if (ouvre) objet.entite else null
            // À chaque ouverture, l'onglet repart du mode réel de la lampe (Couleur si elle est en couleur).
            if (ouvre) ongletCouleur = null
            majLignes(maintenant())
        }

        override fun maj(a: Appareils.Appareil?, fantome: Appareils.Appareil?, t: Long) {
            val hors = MaisonEnGrand.horsLigne(a)
            val n = MaisonEnGrand.nom(objet, a)
            if (nom.texte.toString() != n) nom.texte = n
            reglable = !hors && a!!.reglable
            // Le rond suit l'état réel (un toucher part de lui), le fantôme ne colore que le texte et la piste.
            val on = !hors && a!!.allume
            val e = when {
                fantome != null -> "n'a pas répondu"
                else -> MaisonEnGrand.etatLampe(n, a)
            }
            // Lampe en marche ou arrêt seulement : son état à droite, comme la maquette (« Cuisine, allumée »).
            val aDroite = !reglable && fantome == null
            poser(etat, if (aDroite) "" else e)
            etat.visibility = if (aDroite) View.GONE else View.VISIBLE
            etat.couleur(if (fantome != null) Palette.accentLumiere else if (hors) Palette.texte3 else ETAT)
            poser(etatDroite, if (aDroite) e else "")
            etatDroite.visibility = if (aDroite) View.VISIBLE else View.GONE
            piste.visibility = if (reglable) View.VISIBLE else View.GONE
            piste.fantome = fantome != null
            piste.eteinte = !on
            if (!piste.glisse) piste.fraction = when {
                fantome != null -> (fantome.luminosite ?: 100) / 100f
                on -> (a!!.luminosite ?: 100) / 100f
                else -> 0f
            }
            rond.etat = when {
                hors -> RondBascule.Etat.HORS
                on -> RondBascule.Etat.ALLUME
                else -> RondBascule.Etat.ETEINT
            }
            rond.soir = soir
            rond.contentDescription = (if (on) "Éteindre " else "Allumer ") + n.lowercase()
            piste.contentDescription = "Intensité de ${n.lowercase()}"
            vue.isEnabled = !hors
            rond.isEnabled = !hors
            piste.isEnabled = !hors
            surlignee(surligne == objet.entite)
            val ouverte = teinteOuverte == objet.entite && !hors
            teintes.visibility = if (ouverte) View.VISIBLE else View.GONE
            val reglage = !hors && a != null && (a.couleur || a.blanc)
            chevron.visibility = if (reglage) View.VISIBLE else View.GONE
            chevron.ouvert = ouverte
            // Sans réglage, la ligne et le rond font la même chose : TalkBack ne lit que la ligne.
            rond.importantForAccessibility = if (reglage) View.IMPORTANT_FOR_ACCESSIBILITY_YES else View.IMPORTANT_FOR_ACCESSIBILITY_NO
            vue.contentDescription = if (reglage) {
                (if (ouverte) "Replier les réglages de " else "Déplier les réglages de ") + n.lowercase() + ", " + e
            } else {
                (if (on) "Éteindre " else "Allumer ") + n.lowercase()
            }
            if (ouverte && a != null) {
                // Couleur seulement si la lampe sait en faire, Blanc seulement si elle sait régler sa chaleur.
                val surCouleur = ReglageLampe.surCouleur(a, ongletCouleur)
                onglets.visibility = if (a.couleur && a.blanc) View.VISIBLE else View.GONE
                ongletBlanc.couleur(if (!surCouleur) Palette.texte1 else Palette.texte3)
                ongletCoul.couleur(if (surCouleur) Palette.texte1 else Palette.texte3)
                // Valeur actuelle à côté des onglets : « 2700 K chaud » ou le nom de la couleur.
                poser(valeurReglage, ReglageLampe.valeurVolet(a, surCouleur))
                panneauBlanc.visibility = if (!surCouleur) View.VISIBLE else View.GONE
                panneauCouleur.visibility = if (surCouleur) View.VISIBLE else View.GONE
                val (k0, k1) = ReglageLampe.bornes(a)
                pisteBlanc.gauche = "$k0 K"
                pisteBlanc.droite = "$k1 K"
                if (!pisteBlanc.glisse) pisteBlanc.fraction = a.kelvin?.let { ReglageLampe.fractionDe(a, it) } ?: 0.5f
                if (!pisteTeinte.glisse) pisteTeinte.fraction = (a.teinte ?: 0f) / 359f
                pisteTeinte.couleurCurseur = a.teinte?.let { Color.HSVToColor(floatArrayOf(it, 1f, 1f)) }
            }
        }
    }

    /** Télé : rond bleu pour l'allumer ou l'éteindre, son nom et son état. */
    private inner class LigneTele(o: MaisonEnGrand.Objet) : Ligne(o) {
        private val rond = RondBascule(ctx, RondBascule.Glyphe.TELE)
        private val nom = texte(Palette.texte1, 21f)
        private val etat = texte(Palette.texte2, 17f)
        override val vue: View = LinearLayout(ctx).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            background = fondSurligne
            setPadding(px(10f), 0, 0, 0)
            isClickable = true
            setOnClickListener { surToucher(); surligner(o.entite); basculer(o) }
            addView(rond, LinearLayout.LayoutParams(px(56f), px(56f)).apply { marginEnd = px(16f) })
            addView(LinearLayout(ctx).apply {
                orientation = LinearLayout.VERTICAL
                addView(nom)
                addView(etat, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { topMargin = px(2f) })
            })
        }

        init {
            rond.setOnClickListener { surToucher(); surligner(o.entite); basculer(o) }
        }

        override fun maj(a: Appareils.Appareil?, fantome: Appareils.Appareil?, t: Long) {
            val hors = MaisonEnGrand.horsLigne(a)
            val n = MaisonEnGrand.nom(objet, a)
            if (nom.texte.toString() != n) nom.texte = n
            val on = !hors && MaisonEnGrand.teleAllumee(a)
            poser(etat, when {
                fantome != null -> "n'a pas répondu"
                hors -> "hors ligne"
                on -> "allumée"
                else -> "éteinte"
            })
            etat.couleur(if (fantome != null) Palette.accentLumiere else if (hors) Palette.texte3 else Palette.texte2)
            rond.etat = when {
                hors -> RondBascule.Etat.HORS
                on -> RondBascule.Etat.ALLUME
                else -> RondBascule.Etat.ETEINT
            }
            rond.soir = soir
            rond.contentDescription = if (on) "Éteindre la télé" else "Allumer la télé"
            vue.isEnabled = !hors
            rond.isEnabled = !hors
            surlignee(surligne == objet.entite)
        }
    }

    /** Volume d'une enceinte : nom et valeur, puis moins, la piste jusqu'au volume permis (VolumeVise.MAX), plus. */
    private inner class LigneVolume(o: MaisonEnGrand.Objet) : Ligne(o) {
        private val nom = texte(Palette.texte3, 18f)
        private val valeur = texte(Palette.texte1, 20f)
        private val moins = BoutonGlyphe(ctx, BoutonGlyphe.Forme.MOINS, 24f, Palette.texte2).apply { echelle = s; contentDescription = "Moins fort" }
        private val plus = BoutonGlyphe(ctx, BoutonGlyphe.Forme.PLUS, 24f, Palette.texte2).apply { echelle = s; contentDescription = "Plus fort" }
        private val piste = PisteVolume(ctx).apply { echelle = s }
        override val glisse: Boolean get() = piste.glisse
        override val vue: View = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            background = fondSurligne
            addView(LinearLayout(ctx).apply {
                orientation = LinearLayout.HORIZONTAL
                isBaselineAligned = true
                addView(nom)
                addView(valeur, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, ViewGroup.LayoutParams.WRAP_CONTENT).apply { marginStart = px(10f) })
            })
            addView(LinearLayout(ctx).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
                addView(moins, LinearLayout.LayoutParams(px(56f), px(56f)))
                addView(piste, LinearLayout.LayoutParams(px(236f), px(56f)).apply { marginStart = px(8f); marginEnd = px(8f) })
                addView(plus, LinearLayout.LayoutParams(px(56f), px(56f)))
            }, LinearLayout.LayoutParams(ViewGroup.LayoutParams.WRAP_CONTENT, px(56f)).apply { marginStart = px(-14f) })
        }

        init {
            moins.setOnClickListener { surToucher(); surligner(o.entite); volume(o, -1, null) }
            plus.setOnClickListener { surToucher(); surligner(o.entite); volume(o, +1, null) }
            piste.surDebut = { surToucher(); surligner(o.entite) }
            // Le volume ne part qu'au lâcher (le doigt ne monte jamais le son par à-coups).
            piste.surLacher = { f -> surToucher(); volume(o, 0, f) }
        }

        override fun maj(a: Appareils.Appareil?, fantome: Appareils.Appareil?, t: Long) {
            val horsLigne = MaisonEnGrand.horsLigne(a)
            // Enceinte éteinte : HA ne dit pas son volume, rien ne se règle sans qu'elle soit hors ligne.
            val sansVolume = !horsLigne && a?.volume == null
            val hors = horsLigne || sansVolume
            val n = MaisonEnGrand.nom(objet, a)
            if (nom.texte.toString() != n) nom.texte = n
            // L'état prévu tant que la demande attend (Attentes), l'état lu sinon : ligne et pastille disent la même chose.
            val v = if (hors) 0.0 else a?.volume ?: 0.0
            poser(valeur, when {
                fantome != null -> "n'a pas répondu"
                horsLigne -> "hors ligne"
                sansVolume -> "éteinte"
                else -> TextesCourts.pourcent(v)
            })
            valeur.couleur(if (fantome != null) Palette.accentLumiere else if (hors) Palette.texte3 else Palette.texte1)
            val auMax = !hors && v >= VolumeVise.MAX - 0.005
            moins.couleur = if (hors) Palette.texteEteint else Palette.texte2
            plus.couleur = if (hors || auMax) Palette.texteEteint else Palette.texte2
            moins.isEnabled = !hors
            plus.isEnabled = !hors
            piste.isEnabled = !hors
            piste.eteinte = hors
            piste.fantome = fantome != null
            if (!piste.glisse) piste.fraction = VolumeVise.fraction(fantome?.volume ?: v).toFloat()
            piste.contentDescription = "$n, ${valeur.texte}"
            surlignee(surligne == objet.entite)
        }
    }

    companion object {
        const val LARGEUR_PANNEAU = 436f
        /** Nom d'une lampe et piste de l'intensité : « Lampe de la télé » tient en entier à 21 px (vu sur la tablette). */
        const val LARGEUR_NOM = 160f
        /** Le panneau part à y 112 et s'arrête 24 px au-dessus du bas de l'écran. */
        const val HAUTEUR_MAX_PANNEAU = 664f
        const val DUREE_SURLIGNE_MS = 400L
        const val DUREE_MESSAGE_MS = 4_000L
        /** Blanc du chaud au froid quand la lampe ne dit pas ses bornes. */
        /** État sous le nom d'une lampe (maquette `MaisonMelange`). */
        private const val ETAT = 0xFFC9C2B6.toInt()
        private const val TAG_RESUME = "resume"
        private const val TAG_MUSIQUE = "musique"
        /** Les 5 couleurs de la ligne qui s'ouvre (maquette `MaisonMelangeCouleur`). */
    }
}

/**
 * Rond d'une ligne de la maison en grand (56 px de maquette) : mat ambre avec un liseré clair en haut et sombre en bas
 * pour une lampe allumée, bleu de l'assistant pour la télé allumée, cerclé de gris quand c'est éteint, en pointillé
 * hors ligne. Le glyphe (ampoule ou télé) est au trait de 2 sur une grille de 24, à 26 px.
 */
internal class RondBascule(ctx: Context, private val glyphe: Glyphe) : View(ctx) {
    enum class Glyphe { AMPOULE, TELE }
    enum class Etat { ALLUME, ETEINT, HORS }

    var etat = Etat.ETEINT
        set(v) {
            if (field != v) {
                field = v
                invalidate()
            }
        }
    var soir = false
        set(v) {
            if (field != v) {
                field = v
                invalidate()
            }
        }
    private val p = Paint(Paint.ANTI_ALIAS_FLAG)
    private val trait = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }

    init {
        isClickable = true
        isFocusable = true
    }

    override fun drawableStateChanged() {
        super.drawableStateChanged()
        invalidate()
    }

    override fun onDraw(c: Canvas) {
        val r = min(width, height) / 2f
        val cx = width / 2f
        val cy = height / 2f
        val k = r / 28f
        p.shader = null
        p.style = Paint.Style.FILL
        when (etat) {
            Etat.ALLUME -> {
                if (glyphe == Glyphe.TELE) {
                    val b = Palette.accentAssistant
                    p.shader = RadialGradient(cx - r * 0.2f, cy - r * 0.3f, r * 1.2f, intArrayOf(Decor.melange(b, 0xFFFFFFFF.toInt(), 0.3f), b, Decor.melange(b, 0xFF000000.toInt(), 0.3f)), floatArrayOf(0f, 0.65f, 1f), Shader.TileMode.CLAMP)
                } else {
                    p.color = if (soir) MAT_SOIR else MAT
                }
                c.drawCircle(cx, cy, r, p)
                p.shader = null
                // Ombre interne de 1 px : clair en haut, sombre en bas.
                trait.pathEffect = null
                trait.strokeWidth = 1f * k
                trait.color = 0x4DFFFFFF
                c.drawArc(cx - r + k, cy - r + k, cx + r - k, cy + r - k, 200f, 140f, false, trait)
                trait.color = 0x4D000000
                c.drawArc(cx - r + k, cy - r + k, cx + r - k, cy + r - k, 20f, 140f, false, trait)
            }
            Etat.ETEINT, Etat.HORS -> {
                trait.strokeWidth = 2f * k
                trait.color = Palette.colonne
                trait.pathEffect = if (etat == Etat.HORS) DashPathEffect(floatArrayOf(4f * k, 5f * k), 0f) else null
                c.drawCircle(cx, cy, r - k, trait)
                trait.pathEffect = null
            }
        }
        val couleur = when (etat) {
            Etat.ALLUME -> if (glyphe == Glyphe.TELE) Palette.texte1 else 0xFF1A1712.toInt()
            Etat.ETEINT -> Palette.texte3
            Etat.HORS -> Palette.colonne
        }
        trait.color = if (isPressed) Decor.melange(couleur, Palette.fond, 0.4f) else couleur
        val g = 26f / 24f * k
        c.save()
        c.translate(cx - 12f * g, cy - 12f * g)
        c.scale(g, g)
        trait.strokeWidth = 2f
        c.drawPath(if (glyphe == Glyphe.TELE) TELE else AMPOULE, trait)
        c.restore()
    }

    private companion object {
        const val MAT = 0xFFE9A865.toInt()
        const val MAT_SOIR = 0xFFC98F5C.toInt()
        private fun chemin(d: String) = CheminSvg.chemin(CheminSvg.lire(d))
        val AMPOULE by lazy { chemin("M9 18h6M10 21h4M12 3a6 6 0 0 0-3.5 10.9c.6.5 1 1.2 1 2.1h5c0-.9.4-1.6 1-2.1A6 6 0 0 0 12 3Z") }
        val TELE by lazy { chemin("M5 5h14a2 2 0 0 1 2 2v8a2 2 0 0 1-2 2H5a2 2 0 0 1-2-2V7a2 2 0 0 1 2-2ZM8 21h8") }
    }
}

/**
 * Piste du blanc, du chaud au froid (270 x 48 px de maquette) : dégradé de 10 px, curseur de 24 px cerclé de noir,
 * « chaud » et « froid » en dessous. La valeur part au lâcher ([surLacher], fraction de 0 chaud à 1 froid).
 */
internal class PisteBlanc(ctx: Context) : View(ctx) {
    var fraction = 0.5f
        set(v) {
            val f = v.coerceIn(0f, 1f)
            if (field != f) {
                field = f
                invalidate()
            }
        }
    var surLacher: (Float) -> Unit = {}
    var surAnnule: () -> Unit = {}
    /** Le doigt bouge : la valeur part en cours de geste, par la Cadence de l'appelant. */
    var surBouge: (Float) -> Unit = {}
    var surDebut: () -> Unit = {}
    var glisse = false
        private set
    /** Dégradé de la piste, mots aux deux bouts et couleur du curseur (null : crème du blanc). */
    var degrade = intArrayOf(0xFFF6B26B.toInt(), 0xFFF7E3C8.toInt(), 0xFFCFE0F7.toInt())
        set(v) { field = v; invalidate() }
    var gauche = "chaud"
        set(v) { if (field != v) { field = v; invalidate() } }
    var droite = "froid"
        set(v) { if (field != v) { field = v; invalidate() } }
    var couleurCurseur: Int? = null
        set(v) { if (field != v) { field = v; invalidate() } }
    /** Bande de teinte : pas de mots sous la piste. */
    var bande = false
    private val p = Paint(Paint.ANTI_ALIAS_FLAG)
    private val mot = Paint(Paint.ANTI_ALIAS_FLAG).apply { typeface = Polices.texte(ctx) }

    init {
        isClickable = true
        isFocusable = true
        contentDescription = "Blanc, du chaud au froid"
    }

    @android.annotation.SuppressLint("ClickableViewAccessibility")
    override fun onTouchEvent(ev: android.view.MotionEvent): Boolean {
        val r = height * 12f / 52f
        val f = ((ev.x - r) / (width - 2 * r).coerceAtLeast(1f)).coerceIn(0f, 1f)
        when (ev.actionMasked) {
            android.view.MotionEvent.ACTION_DOWN -> {
                glisse = true
                parent?.requestDisallowInterceptTouchEvent(true)
                fraction = f
                surDebut()
                surBouge(f)
            }
            android.view.MotionEvent.ACTION_MOVE -> {
                fraction = f
                surBouge(f)
            }
            android.view.MotionEvent.ACTION_UP -> {
                fraction = f
                glisse = false
                surLacher(f)
            }
            android.view.MotionEvent.ACTION_CANCEL -> {
                glisse = false
                surAnnule()
            }
        }
        return true
    }

    override fun onDraw(c: Canvas) {
        val k = height / 52f
        val y = 24f * k
        val e = 10f * k
        val rc = 12f * k
        val n = degrade.size
        p.shader = LinearGradient(0f, 0f, width.toFloat(), 0f, degrade, FloatArray(n) { it / (n - 1f) }, Shader.TileMode.CLAMP)
        c.drawRoundRect(0f, y - e / 2, width.toFloat(), y + e / 2, e / 2, e / 2, p)
        p.shader = null
        val xc = rc + (width - 2 * rc) * fraction
        p.color = Palette.fond
        c.drawCircle(xc, y, rc + 3f * k, p)
        p.color = couleurCurseur ?: 0xFFF7DFC0.toInt()
        c.drawCircle(xc, y, rc, p)
        if (bande) return
        mot.textSize = 14f * k
        mot.color = Palette.texte3
        c.drawText(gauche, 0f, height.toFloat() - 2f * k, mot)
        val l = mot.measureText(droite)
        c.drawText(droite, width - l, height.toFloat() - 2f * k, mot)
    }
}

/** Chevron de la ligne d'une lampe : pointe vers le bas, se retourne quand le volet est ouvert. */
internal class ChevronVolet(ctx: Context) : View(ctx) {
    var ouvert = false
        set(v) { if (field != v) { field = v; invalidate() } }
    private val p = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }

    init { isClickable = true }

    override fun onDraw(c: Canvas) {
        val k = width / 56f
        p.strokeWidth = 3f * k
        p.color = Palette.texte2
        val cx = width / 2f
        val cy = height / 2f
        val sens = if (ouvert) -1f else 1f
        val ch = android.graphics.Path().apply {
            moveTo(cx - 8f * k, cy - 4f * k * sens)
            lineTo(cx, cy + 4f * k * sens)
            lineTo(cx + 8f * k, cy - 4f * k * sens)
        }
        c.drawPath(ch, p)
    }
}
