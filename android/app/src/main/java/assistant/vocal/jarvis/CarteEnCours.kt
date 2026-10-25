package assistant.vocal.jarvis

import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.ColorMatrix
import android.graphics.ColorMatrixColorFilter
import android.graphics.Paint
import android.graphics.Path
import android.graphics.RectF
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import android.widget.ImageView
import android.widget.LinearLayout
import org.json.JSONObject
import java.util.Locale

/**
 * Carte « En cours » de l'écran ambiant (0.16.2) : la musique qui joue, avec la pochette, le titre,
 * l'artiste et les commandes. Les commandes partent par Etat.actionMedia, donc par la passerelle après
 * Securite.kt. Les icônes sont dessinées, pas des caractères.
 *
 * 0.17.0 : bulle compacte, la progression, le volume et le choix de l'enceinte dans l'écran Musique, ouvert
 * par un toucher sur la bulle ([ouvrir]).
 *
 * 0.18.0 à 0.22 : bloc typographique en bas à gauche, sans cadre, commandes en gris éteint 30 s après le
 * dernier toucher.
 *
 * 0.24.0, seconde passe de l'accueil (piste B validée le 22/10/2026, maquette `AccueilMusique`) : le
 * bloc prend le bas de la moitié droite (568 x 280 px de maquette, sous le plan). Pochette de 168 px, lieu,
 * titre sur deux lignes au plus, artiste, filet de progression, puis une rangée de commandes : précédent,
 * lecture ou pause, suivant, et le volume (moins, la piste, plus). Cibles de 60 px de maquette, 48 dp au
 * moins. Le volume se règle par pas de 5 points ou en glissant (envoi au lâcher), jamais au-delà du plafond
 * quand la configuration en règle un (Securite.VOLUME_MAX, marqué alors par un trait au bout de la piste, la
 * piste couvre sinon tout le volume). Pour un groupe d'enceintes, le geste décale
 * chaque enceinte du même écart. Après l'arrêt de la musique, le bloc reste en pause, atténué ([pause]). En
 * retrait ([retrait]), pochette désaturée et commandes éteintes.
 */
internal class CarteEnCours(
    private val ctx: Context,
    private val ouvrir: () -> Unit = {},
) {

    private fun texte(couleur: Int, lignes: Int = 1, interligne: Float = 1f) = TexteFondu(ctx).apply {
        peinture.color = couleur
        peinture.typeface = Polices.texte(ctx)
        maxLignes = lignes
        this.interligne = interligne
    }

    private val pochette = ImageView(ctx).apply {
        scaleType = ImageView.ScaleType.CENTER_CROP
        visibility = View.GONE
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
    }
    private val lieu = texte(Palette.texte3)
    /** Titre à 34 px, interligne CSS 1,1 (Instrument Sans : 1,22 em naturel). */
    private val titre = texte(Palette.texte1, 2, 1.1f / 1.22f)
    private val artiste = texte(Palette.texte2)
    /** Filet de progression de 3 px au bas des textes (0.19.0) : rail `filet`, avancée `musique`. */
    private val filet = FiletProgression(ctx).apply { visibility = View.GONE }
    private val precedent = BoutonGlyphe(ctx, BoutonGlyphe.Forme.PRECEDENT, 26f, Palette.texte2)
    private val lecture = BoutonGlyphe(ctx, BoutonGlyphe.Forme.PAUSE, 30f, Palette.texte1)
    private val suivant = BoutonGlyphe(ctx, BoutonGlyphe.Forme.SUIVANT, 26f, Palette.texte2)
    private val moins = BoutonGlyphe(ctx, BoutonGlyphe.Forme.MOINS, 26f, Palette.texte2)
    private val plus = BoutonGlyphe(ctx, BoutonGlyphe.Forme.PLUS, 26f, Palette.texte2)
    private val piste = PisteVolume(ctx)
    private val libelleVolume = texte(Palette.texte3)
    private val valeurVolume = texte(Palette.texte1)
    private val noteVolume = texte(Palette.texte3)
    /** Dernier toucher sur le bloc ou ses boutons (SystemClock.elapsedRealtime). */
    var toucheLe = 0L
        private set
    private val textes = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }
    private val ligneVolume = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        isBaselineAligned = true
    }

    /** Lecteur suivi par la carte (choisi dans l'écran Musique, sinon le premier qui joue). */
    private var choisi = ""
    /** Lecteur montré par la bulle, et la liste lue dans HA. */
    var courant: Etat.Lecteur? = null
        private set
    var lecteurs: List<Etat.Lecteur> = emptyList()
        private set
    /** Pochette et teinte du lecteur courant, reprises par l'écran Musique. */
    var image: android.graphics.Bitmap? = null
        private set
    var teinte = Couleur.OR
        private set
    /** Pochette montrée ; null au départ, pour que le premier lecteur sans pochette place aussi les textes. */
    private var imageAffichee: String? = null

    /** Volumes lus des enceintes (relus avec les lumières du plan, toutes les 5 s), par entité. */
    private var volumesLus: Map<String, Double> = emptyMap()
    private val vise = VolumeVise()
    private var eteint = false
    private var retrait = false
    private var enPause = false

    /** Le bloc, ses vues placées en pixels de maquette relatifs à son coin, à l'échelle de l'écran ([echelle]). */
    val vue: CadreMaquette = CadreMaquette(ctx).apply {
        clipChildren = false
        val n = Float.NaN
        val P = CadreMaquette::Place
        // Toucher le haut du bloc (pochette et textes) : écran Musique.
        val zoneOuvrir = View(ctx).apply {
            isClickable = true
            contentDescription = "Ouvrir l'écran Musique"
            setOnClickListener { touche(); ouvrir() }
        }
        addView(zoneOuvrir, P(0f, 0f, n, n, LARGEUR, 168f))
        addView(pochette, P(0f, 0f, n, n, 168f, 168f))
        textes.addView(lieu)
        textes.addView(titre)
        textes.addView(artiste)
        addView(textes, P(X_TEXTES, 0f, n, n, LARGEUR - X_TEXTES, n))
        addView(filet, P(X_TEXTES, 165f, n, n, LARGEUR - X_TEXTES, 3f))
        ligneVolume.addView(libelleVolume)
        ligneVolume.addView(valeurVolume)
        ligneVolume.addView(noteVolume)
        addView(ligneVolume, P(229f, 186f, n, n, 339f, n))
        precedent.apply { contentDescription = "Morceau précédent"; setOnClickListener { touche(); commande("media_previous_track") } }
        lecture.apply { contentDescription = "Lecture ou pause"; setOnClickListener { touche(); lectureOuPause() } }
        suivant.apply { contentDescription = "Morceau suivant"; setOnClickListener { touche(); commande("media_next_track") } }
        moins.apply { contentDescription = "Moins fort"; setOnClickListener { touche(); pas(-1) } }
        plus.apply { contentDescription = "Plus fort"; setOnClickListener { touche(); pas(+1) } }
        for ((i, b) in listOf(precedent, lecture, suivant).withIndex()) addView(b, P(-17f + 60f * i, 220f, n, n, 60f, 60f))
        addView(moins, P(212f, 220f, n, n, 60f, 60f))
        addView(piste, P(284f, 220f, n, n, 212f, 60f))
        addView(plus, P(508f, 220f, n, n, 60f, 60f))
        piste.surDebut = { touche() }
        piste.surLacher = { f -> touche(); glisser(f * VolumeVise.MAX) }
        echelleImposee = CadreMaquette.estimer(ctx)
    }

    private fun touche() {
        toucheLe = SystemClock.elapsedRealtime()
    }

    /** Un doigt est posé sur la piste du volume : rien ne doit bouger dessous. */
    val glisse: Boolean get() = piste.glisse

    /** Commandes en gris éteint ([oui]) 30 s après le dernier toucher sur l'écran, ou à leurs couleurs. */
    fun eteindre(oui: Boolean) {
        if (oui == eteint) return
        eteint = oui
        majCouleurs()
    }

    /** Régime en retrait (0.24.0) : pochette désaturée, commandes éteintes. */
    fun retrait(oui: Boolean) {
        if (oui == retrait) return
        retrait = oui
        pochette.colorFilter = if (oui) FILTRE_RETRAIT else null
        majCouleurs()
    }

    /** Après l'arrêt de la musique (0.24.0) : « En pause dans le salon », l'opacité de 0,55 est posée par l'accueil. */
    fun pause(oui: Boolean) {
        if (oui == enPause) return
        enPause = oui
        majLieu()
    }

    private fun majCouleurs() {
        val e = eteint || retrait
        val gris = Palette.texteEteint
        precedent.couleur = if (e) gris else Palette.texte2
        suivant.couleur = if (e) gris else Palette.texte2
        lecture.couleur = if (e) gris else Palette.texte1
        moins.couleur = if (e) gris else Palette.texte2
        majVolume()
    }

    /** Tailles de la maquette (pixels de maquette) à l'échelle [s] de l'écran. */
    fun echelle(s: Float) {
        fun px(v: Float) = (v * s).toInt()
        vue.echelleImposee = s
        lieu.taille(18f * s)
        titre.taille(34f * s)
        artiste.taille(22f * s)
        for ((v, haut) in listOf(lieu to 0f, titre to 6f, artiste to 4f)) {
            v.layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = px(haut) }
        }
        libelleVolume.taille(18f * s)
        valeurVolume.taille(22f * s)
        noteVolume.taille(16f * s)
        for ((v, gauche) in listOf(libelleVolume to 0f, valeurVolume to 10f, noteVolume to 10f)) {
            v.layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { marginStart = px(gauche) }
        }
        for (g in listOf(precedent, lecture, suivant, moins, plus)) {
            g.echelle = s
            // Cibles de 60 px de maquette, et 48 dp au moins quelle que soit la densité (revue du 22/10).
            g.minimumWidth = Decor.dp(ctx, 48f)
            g.minimumHeight = Decor.dp(ctx, 48f)
        }
        piste.echelle = s
    }

    /** Lecteurs lus dans HA. [retenir] : la liste est vide mais le bloc doit rester (pause après l'arrêt). */
    fun maj(lecteurs: List<Etat.Lecteur>, retenir: Boolean = false): Boolean {
        this.lecteurs = lecteurs
        if (lecteurs.isEmpty()) {
            val c = courant
            if (!retenir || c == null) {
                courant = null
                return false
            }
            // Le lecteur a quitté la liste (arrêt, fin de liste) : il reste montré, en pause, pour pouvoir relancer.
            if (c.etat != "paused") montrer(c.copy(etat = "paused"))
            return true
        }
        val l = lecteurs.firstOrNull { it.id == choisi }
            ?: lecteurs.firstOrNull { it.etat == "playing" }
            ?: lecteurs.first()
        montrer(l)
        return true
    }

    /** Plus rien à montrer (10 min après l'arrêt) : le lecteur retenu est oublié. */
    fun oublier() {
        if (lecteurs.isEmpty()) courant = null
    }

    private fun montrer(l: Etat.Lecteur) {
        courant = l
        majLieu()
        titre.texte = l.titre.ifBlank { "Lecture en cours" }
        artiste.texte = l.artiste
        artiste.visibility = if (l.artiste.isBlank()) View.GONE else View.VISIBLE
        majFilet()
        val joue = l.etat == "playing"
        lecture.forme = if (joue) BoutonGlyphe.Forme.PAUSE else BoutonGlyphe.Forme.LECTURE
        lecture.contentDescription = if (joue) "Pause" else "Reprendre"
        vise.lu(volumeLu(l))
        majVolume()
        if (l.image != imageAffichee) {
            imageAffichee = l.image
            image = null
            pochette.setImageDrawable(null)
            montrerPochette(false)
            if (l.image.isNotBlank()) {
                val attendue = l.image
                Etat.actionPochette?.invoke(attendue) { p ->
                    if (attendue == imageAffichee && p != null) {
                        image = p.image
                        pochette.setImageBitmap(p.image)
                        montrerPochette(true)
                        // Or de la musique, nuancé par la couleur dominante de la pochette (écran Musique).
                        teinte = Decor.melange(Couleur.OR, p.teinte, 0.4f)
                    }
                }
            }
        }
    }

    /** Sans pochette, les textes prennent toute la largeur du bloc. */
    private fun montrerPochette(oui: Boolean) {
        pochette.visibility = if (oui) View.VISIBLE else View.GONE
        val x = if (oui) X_TEXTES else 0f
        val n = Float.NaN
        textes.layoutParams = CadreMaquette.Place(x, 0f, n, n, LARGEUR - x, n)
        filet.layoutParams = CadreMaquette.Place(x, 165f, n, n, LARGEUR - x, 3f)
    }

    private fun majLieu() {
        val l = courant ?: return
        val dans = Accueil.lieuMusique(l)
        lieu.texte = if (enPause) "En pause " + dans.replaceFirstChar { it.lowercase(Locale.FRANCE) } else dans
    }

    /** Écran Musique : on choisit le lecteur suivi quand plusieurs jouent. */
    fun choisir(id: String) {
        choisi = id
        maj(lecteurs)
    }

    /** Volumes relus des enceintes (0.24.0) : la valeur affichée suit Home Assistant. */
    fun volumes(medias: List<Appareils.Appareil>) {
        val v = medias.mapNotNull { m -> m.volume?.let { m.id to it } }.toMap()
        if (v == volumesLus) return
        volumesLus = v
        courant?.let { vise.lu(volumeLu(it)) }
        majVolume()
    }

    /** Toutes les secondes : le filet de progression avance avec la lecture, la visée du volume s'efface. */
    fun tic() {
        majFilet()
        majVolume()
    }

    /** Filet seulement quand la durée du morceau est connue. */
    private fun majFilet() {
        val l = courant
        if (l == null || l.duree <= 0.0) {
            filet.visibility = View.GONE
            return
        }
        filet.visibility = View.VISIBLE
        filet.fraction = (position(l, System.currentTimeMillis()) / l.duree).toFloat()
    }

    /** Enceintes du lecteur courant : celles du groupe connues de la sortie du son, sinon le lecteur lui-même. */
    private fun enceintes(l: Etat.Lecteur): List<String> {
        val connues = (listOf(l.id) + l.membres).distinct().filter { id -> SortieSon.ENCEINTES.any { it.first == id } }
        return if (connues.size >= 2) connues else listOf(l.id)
    }

    /** Volume lu : celui de l'enceinte la plus forte du groupe, relu avec le plan, sinon celui du lecteur. */
    private fun volumeLu(l: Etat.Lecteur): Double =
        enceintes(l).mapNotNull { volumesLus[it] }.maxOrNull() ?: l.volume

    private fun majVolume() {
        val l = courant ?: return
        val v = vise.affiche(volumeLu(l), SystemClock.elapsedRealtime())
        val e = eteint || retrait
        val max = VolumeVise.MAX
        val audessus = v > max + 0.005
        val auMax = !audessus && v >= max - 0.005
        val libelle = TextesCourts.volume(l)
        if (libelleVolume.texte.toString() != libelle) libelleVolume.texte = libelle
        val valeur = TextesCourts.pourcent(v)
        if (valeurVolume.texte.toString() != valeur) valeurVolume.texte = valeur
        valeurVolume.couleur(if (e) Palette.texte3 else Palette.texte1)
        // Les mentions du plafond n'existent que si la configuration en règle un (securite.plafond_volume).
        val note = when {
            !Securite.PLAFOND_ACTIF -> ""
            audessus -> "au-dessus du plafond"
            auMax -> "plafond atteint"
            else -> ""
        }
        if (noteVolume.texte.toString() != note) noteVolume.texte = note
        noteVolume.visibility = if (note.isEmpty()) View.GONE else View.VISIBLE
        // Plus au gris éteint au maximum permis (planche `AccueilSobre`), seul moins agit au-dessus.
        plus.couleur = if (e || auMax || audessus) Palette.texteEteint else Palette.texte2
        if (!piste.glisse) piste.fraction = VolumeVise.fraction(v).toFloat()
        piste.eteinte = e
        piste.contentDescription = "$libelle, $valeur"
    }

    /** Moins ou plus : 5 points de plus ou de moins sur la valeur affichée, cumulés. */
    private fun pas(sens: Int) {
        val l = courant ?: return
        val lu = volumeLu(l)
        val t = SystemClock.elapsedRealtime()
        val avant = vise.affiche(lu, t)
        val apres = vise.pas(lu, sens, t) ?: return
        envoyerVolume(l, avant, apres)
    }

    /** Doigt levé sur la piste : la valeur visée part. */
    private fun glisser(valeur: Double) {
        val l = courant ?: return
        val t = SystemClock.elapsedRealtime()
        val avant = vise.affiche(volumeLu(l), t)
        val apres = vise.glisser(valeur, t)
        envoyerVolume(l, avant, apres)
    }

    private fun envoyerVolume(l: Etat.Lecteur, avant: Double, apres: Double) {
        val ids = enceintes(l)
        // Groupe : décalage compté depuis la valeur lue (plafonnée), pour que les touchers rapides se cumulent.
        val cibles = if (ids.size >= 2) VolumeVise.groupe(ids.associateWith { volumesLus[it] ?: l.volume }, minOf(volumeLu(l), VolumeVise.MAX), apres)
        else mapOf(l.id to apres)
        for ((id, v) in cibles) {
            Etat.actionMedia?.invoke(id, "volume_set", JSONObject().put("volume_level", v).put("baisse", apres < avant))
        }
        majVolume()
    }

    fun commande(service: String, donnees: JSONObject = JSONObject()) {
        val l = courant ?: return
        Etat.actionMedia?.invoke(l.id, service, donnees)
    }

    /**
     * Pause quand ça joue, lecture sinon, plutôt que media_play_pause : la pause reste permise la nuit
     * au salon (Securite.kt la tient pour silencieuse), la reprise non.
     */
    fun lectureOuPause() {
        val l = courant ?: return
        commande(if (l.etat == "playing") "media_pause" else "media_play")
    }

    companion object {
        /** Taille du bloc et place des textes (à droite de la pochette de 168 px), en pixels de maquette. */
        const val LARGEUR = 568f
        const val HAUTEUR = 280f
        const val X_TEXTES = 192f

        /** Pochette en retrait : saturation 0,4 et clarté 0,85 (maquette `AccueilRegimes`). */
        private val FILTRE_RETRAIT = ColorMatrixColorFilter(
            ColorMatrix().apply {
                setSaturation(0.4f)
                postConcat(ColorMatrix().apply { setScale(0.85f, 0.85f, 0.85f, 1f) })
            },
        )

        /** « 2:05 » pour 125 s. */
        fun minutes(s: Double): String {
            val t = s.toInt().coerceAtLeast(0)
            return String.format(Locale.FRANCE, "%d:%02d", t / 60, t % 60)
        }

        /** Position actuelle (s) : elle avance d'elle-même entre deux lectures de HA quand ça joue. */
        fun position(l: Etat.Lecteur, maintenantMs: Long): Double {
            if (l.duree <= 0.0) return 0.0
            var pos = l.position
            if (l.etat == "playing" && l.positionLe > 0) pos += (maintenantMs - l.positionLe) / 1000.0
            return pos.coerceIn(0.0, l.duree)
        }
    }
}

/**
 * Piste du volume de l'accueil (0.24.0) : trait de 6 px de maquette sur 212, remplissage et curseur de 22 px en
 * `texte2` (gris éteint en retrait ou 30 s après le dernier toucher), petit trait vertical au bout quand un
 * plafond de volume est réglé. La zone de toucher fait toute la rangée (60 px). Le curseur suit le doigt, la
 * valeur ne part qu'au lâcher ([surLacher], fraction de 0 à 1 du volume permis).
 *
 * 0.27.0, maison en grand : la même piste règle aussi l'intensité d'une lampe ([plafond] faux : pas de trait au
 * bout, fraction de 0 à 1 de l'intensité), suit le doigt par [surBouge] (l'appelant limite la cadence d'envoi),
 * et montre en [fantome] la dernière valeur demandée restée sans réponse (curseur gris, remplissage en pointillé).
 */
internal class PisteVolume(ctx: Context) : View(ctx) {
    var fraction = 0f
        set(v) {
            val f = v.coerceIn(0f, 1f)
            if (field != f) {
                field = f
                invalidate()
            }
        }
    var eteinte = false
        set(v) {
            if (field != v) {
                field = v
                invalidate()
            }
        }
    var echelle = CadreMaquette.estimer(ctx)
        set(v) {
            field = v
            invalidate()
        }
    var surDebut: () -> Unit = {}
    var surLacher: (Float) -> Unit = {}
    /** Le doigt glisse (0.27.0) : fraction courante, à chaque mouvement. */
    var surBouge: (Float) -> Unit = {}
    /**
     * Trait du plafond au bout de la piste : vrai pour un volume quand la configuration règle un plafond
     * (Securite.PLAFOND_ACTIF), faux sans plafond et pour l'intensité d'une lampe.
     */
    var plafond = Securite.PLAFOND_ACTIF
        set(v) {
            if (field != v) {
                field = v
                invalidate()
            }
        }
    /** Dernière valeur demandée sans réponse de Home Assistant (0.27.0) : curseur #8A8378, remplissage en pointillé. */
    var fantome = false
        set(v) {
            if (field != v) {
                field = v
                invalidate()
            }
        }
    /** Teinte du remplissage et du curseur quand la piste n'est ni éteinte ni en fantôme (texte2 par défaut). */
    var teinte: Int? = null
        set(v) {
            if (field != v) {
                field = v
                invalidate()
            }
        }
    /** Un doigt glisse sur la piste. */
    var glisse = false
        private set
    private val p = Paint(Paint.ANTI_ALIAS_FLAG)

    init {
        isClickable = true
        isFocusable = true
        contentDescription = "Volume"
    }

    @android.annotation.SuppressLint("ClickableViewAccessibility")
    override fun onTouchEvent(ev: MotionEvent): Boolean {
        val r = (CURSEUR / 2f) * echelle
        val f = ((ev.x - r) / (width - 2 * r).coerceAtLeast(1f)).coerceIn(0f, 1f)
        when (ev.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                glisse = true
                parent?.requestDisallowInterceptTouchEvent(true)
                surDebut()
                fraction = f
            }
            MotionEvent.ACTION_MOVE -> {
                fraction = f
                surBouge(f)
            }
            MotionEvent.ACTION_UP -> {
                fraction = f
                glisse = false
                surLacher(f)
            }
            MotionEvent.ACTION_CANCEL -> glisse = false
        }
        return true
    }

    override fun onDraw(c: Canvas) {
        val s = echelle
        val y = height / 2f
        val e = 6f * s
        val rc = (CURSEUR / 2f) * s
        val x1 = width.toFloat()
        val clair = when {
            fantome -> FANTOME
            eteinte -> Palette.texteEteint
            else -> teinte ?: Palette.texte2
        }
        p.color = Palette.barre
        c.drawRoundRect(0f, y - e / 2, x1, y + e / 2, e / 2, e / 2, p)
        // Trait du plafond au bout de la piste : 2 x 16 px de maquette.
        if (plafond) {
            p.color = if (eteinte) Palette.barre else Palette.texte3
            c.drawRect(x1 - 2f * s, y - 8f * s, x1, y + 8f * s, p)
        }
        val xc = rc + (x1 - 2 * rc) * fraction
        p.color = clair
        if (fantome) {
            // Pointillé de 1,5 px autour du remplissage, comme la maquette `MaisonMelangeEchec`.
            p.style = Paint.Style.STROKE
            p.strokeWidth = 1.5f * s
            p.pathEffect = android.graphics.DashPathEffect(floatArrayOf(4f * s, 3f * s), 0f)
            c.drawRoundRect(0.75f * s, y - e / 2 + 0.75f * s, maxOf(xc, e) - 0.75f * s, y + e / 2 - 0.75f * s, e / 2, e / 2, p)
            p.pathEffect = null
            p.style = Paint.Style.FILL
        } else {
            c.drawRoundRect(0f, y - e / 2, maxOf(xc, e), y + e / 2, e / 2, e / 2, p)
        }
        // Curseur entouré d'un anneau noir de 3 px, qui le détache de la piste.
        p.color = Palette.fond
        c.drawCircle(xc, y, rc + 3f * s, p)
        p.color = clair
        c.drawCircle(xc, y, rc, p)
    }

    companion object {
        const val CURSEUR = 22f
        /** Curseur d'une valeur restée sans réponse (maquette `MaisonMelangeEchec`). */
        const val FANTOME = 0xFF8A8378.toInt()
    }
}

/** Filet de progression de l'accueil (0.19.0) : 3 px de maquette depuis la 0.24.0, rail `filet`, avancée `musique`, sans arrondi. */
internal class FiletProgression(ctx: Context) : View(ctx) {
    var fraction = 0f
        set(v) {
            val f = v.coerceIn(0f, 1f)
            if (field != f) {
                field = f
                invalidate()
            }
        }
    private val p = Paint()

    init {
        importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO
    }

    override fun onDraw(c: Canvas) {
        p.color = Palette.filet
        c.drawRect(0f, 0f, width.toFloat(), height.toFloat(), p)
        p.color = Palette.musique
        c.drawRect(0f, 0f, width * fraction, height.toFloat(), p)
    }
}

/** Barre de progression fine, à la teinte de la pochette. */
internal class BarreProgression(ctx: Context) : View(ctx) {
    var fraction = 0f
        set(v) {
            if (field != v) {
                field = v
                invalidate()
            }
        }
    var teinte = Couleur.BLEU_CLAIR
        set(v) {
            field = v
            invalidate()
        }
    private val p = Paint(Paint.ANTI_ALIAS_FLAG)
    private val r = RectF()

    override fun onDraw(c: Canvas) {
        val h = height * 0.32f
        val y = height / 2f
        r.set(0f, y - h / 2, width.toFloat(), y + h / 2)
        p.color = Palette.progressionRail
        c.drawRoundRect(r, h, h, p)
        r.right = width * fraction.coerceIn(0f, 1f)
        p.color = teinte
        c.drawRoundRect(r, h, h, p)
    }
}

/** Bouton rond des commandes de musique, icône dessinée en Canvas. */
internal class BoutonMedia(ctx: Context, forme: Forme, private val accent: Int = Couleur.BLEU) : View(ctx) {
    enum class Forme { PRECEDENT, LECTURE, PAUSE, SUIVANT, MOINS, PLUS }

    var forme = forme
        set(v) {
            if (field != v) {
                field = v
                invalidate()
            }
        }
    private val fond = Paint(Paint.ANTI_ALIAS_FLAG)
    private val trait = Paint(Paint.ANTI_ALIAS_FLAG).apply { color = Palette.texteSurAccent }
    private val chemin = Path()

    init {
        isClickable = true
        isFocusable = true
        background = Decor.fondNeutre(ctx, 28f)
    }

    override fun onDraw(c: Canvas) {
        val cx = width / 2f
        val cy = height / 2f
        val r = minOf(width, height) / 2f
        val principal = forme == Forme.LECTURE || forme == Forme.PAUSE
        fond.color = if (principal) accent else Palette.boutonMusique
        c.drawCircle(cx, cy, r * 0.96f, fond)
        // Glyphe sombre sur un fond clair (or de la musique), blanc sinon.
        val clair = principal && (Color.red(accent) * 0.299 + Color.green(accent) * 0.587 + Color.blue(accent) * 0.114) > 160
        trait.color = if (clair) Palette.texteSurClair else Palette.texteSurAccent
        val s = r * 0.42f
        trait.style = Paint.Style.FILL
        chemin.rewind()
        when (forme) {
            Forme.LECTURE -> {
                chemin.moveTo(cx - s * 0.6f, cy - s)
                chemin.lineTo(cx + s * 0.95f, cy)
                chemin.lineTo(cx - s * 0.6f, cy + s)
                chemin.close()
                c.drawPath(chemin, trait)
            }
            Forme.PAUSE -> {
                val l = s * 0.36f
                c.drawRoundRect(cx - s * 0.75f, cy - s, cx - s * 0.75f + l, cy + s, l / 3, l / 3, trait)
                c.drawRoundRect(cx + s * 0.75f - l, cy - s, cx + s * 0.75f, cy + s, l / 3, l / 3, trait)
            }
            Forme.SUIVANT, Forme.PRECEDENT -> {
                val sens = if (forme == Forme.SUIVANT) 1f else -1f
                val k = s * 0.8f
                chemin.moveTo(cx - sens * k, cy - k)
                chemin.lineTo(cx + sens * k * 0.6f, cy)
                chemin.lineTo(cx - sens * k, cy + k)
                chemin.close()
                c.drawPath(chemin, trait)
                val l = k * 0.28f
                val x = cx + sens * k * 0.6f
                c.drawRect(minOf(x, x + sens * l), cy - k, maxOf(x, x + sens * l), cy + k, trait)
            }
            Forme.MOINS, Forme.PLUS -> {
                val e = s * 0.22f
                c.drawRoundRect(cx - s * 0.8f, cy - e, cx + s * 0.8f, cy + e, e, e, trait)
                if (forme == Forme.PLUS) c.drawRoundRect(cx - e, cy - s * 0.8f, cx + e, cy + s * 0.8f, e, e, trait)
            }
        }
    }
}
