package assistant.vocal.jarvis

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.graphics.drawable.GradientDrawable
import android.os.SystemClock
import android.view.Gravity
import android.view.View
import android.widget.LinearLayout
import java.text.SimpleDateFormat
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZonedDateTime
import java.util.Calendar
import java.util.Date
import java.util.Locale
import kotlin.math.abs
import kotlin.math.max

/**
 * Écran ambiant de la tablette posée en paysage, pour voir de loin ce que fait l'assistant.
 *
 * 0.16.0 à 0.17.6 : bulles organiques autour d'un orbe, particules, aperçu 3D après une action. Le propriétaire le
 * trouvait « trop made by AI ».
 *
 * 0.18.0, piste « la maison » validée le 22/10/2026 (canevas de design) : écran sobre et
 * typographique, plan 3D au centre.
 * 0.18.1 à 0.22 : zone de texte à gauche sous l'heure, l'heure (VueHeure) qui dérive, couche de service au
 * toucher dans le noir, un jour sur deux la colonne à x 120, couleurs du jeu choisi, santé du propriétaire seul.
 *
 * 0.24.0, seconde passe (demandes du 22/10/2026, maquettes validées sur le canevas version 24,
 * décisions dans docs/maquettes/revue-accueil-musique.md) :
 * - Colonne de gauche minimaliste (piste A) : l'heure seule en grand, la date courte, « 21° » en grand avec un
 *   pictogramme au trait, « pluie 17 h » seulement quand elle arrive, la santé en deux chiffres suivis d'un
 *   mot, une seule ligne ambre en panne. Plus de phrase des pièces allumées : le plan les montre.
 * - Le plan 3D couvre toute la fenêtre et cadre l'appartement dans sa zone (Disposition) : centré en hauteur
 *   sans musique, monté et un peu plus petit avec la musique, dont le bloc prend le bas de la moitié droite.
 *   Jamais deux changements de disposition à la fois, rien ne bouge sous un doigt posé.
 * - Le volume se règle depuis l'accueil (CarteEnCours), jamais au-delà du plafond réglé. Après l'arrêt de la musique,
 *   30 s sans rien changer, puis le bloc reste en pause, atténué, 10 min (SuiviMusique).
 * - L'orbe revient quand on parle à l'assistant, au centre de la zone du plan atténué à 0,28, avec ses
 *   particules (choix du propriétaire), plus doux le soir. « Je t'écoute » et les points de l'heure prennent sa teinte.
 * - Deux régimes (Veille.eclat) : vivant (visage, toucher, voix), couleurs pleines et fond de la page en bleu
 *   de nuit, puis en retrait 30 s après, couleurs à 40 %, noir pur, commandes éteintes.
 *
 * 0.27.0, la maison en grand (demande du 23/10/2026, piste « mélange » du canevas version 29) : toucher le
 * plan au repos, en vivant plein, l'agrandit à tout l'écran (VueMaisonGrand). Chaque pièce qui a quelque chose à
 * régler porte son nom au sol, une pièce touchée est cadrée à gauche sous un voile et son panneau s'ouvre à droite,
 * des pastilles sur ses objets. Retour par Fermer, le vide (de la pièce à la maison, puis à l'accueil), 45 s sans
 * toucher, et d'office en retrait, en AOD, écran éteint, panneau ouvert ou dès que l'assistant écoute. Ni santé, ni
 * musique, ni colonne pendant ce temps.
 * Couleurs : Palette.
 */
internal class EcranAmbiant(private val ctx: Context) {

    /** Toucher l'heure au repos (écoute), ou l'écran pendant l'écoute et la réponse (arrêt) : parler(). */
    var surParler: () -> Unit = {}
    var surMaison: () -> Unit = {}
    var surMusique: () -> Unit = {}
    /** Toucher la date et la météo : panneau Météo. */
    var surMeteo: () -> Unit = {}
    /** Toucher les chiffres de santé : panneau Santé. */
    var surSante: () -> Unit = {}
    /**
     * Demande du résumé de santé au serveur du PC, posée par l'écran principal : la suite reçoit le résumé
     * (deux nombres) ou null. Rien n'est gardé ailleurs que dans la mémoire de l'accueil.
     */
    var surDemanderSante: ((Sante.Resume?) -> Unit) -> Unit = { it(null) }
    var surReglages: () -> Unit = {}
    /** La santé apparaît ou disparaît : l'écran principal pose ou lève FLAG_SECURE tout de suite. */
    var surSecurite: () -> Unit = {}
    var surDemarrer: () -> Unit = {}
    var surAppareils: () -> Unit = {}
    /** Le jour (lever et coucher du soleil), posé par l'écran principal : intensité du plan et orbe du soir. */
    var jour: () -> Boolean = { true }
    /**
     * Pièce dans le noir selon le capteur de lumière (0.28.0), null sans mesure : le plan passe à l'intensité de
     * la nuit (0,15) dans une pièce sombre plutôt que de minuit à 7 h.
     */
    var sombre: () -> Boolean? = { null }
    /** Le micro est autorisé (sinon, l'assistant à l'arrêt dit de l'autoriser). */
    var microAutorise = true
    /** Mot de réveil affiché dans la consigne de la couche de service. */
    var motReveil = ReveilLocal.nom(ReveilLocal.PERSO)
    /** Dernier toucher sur l'écran (SystemClock.elapsedRealtime) : la musique s'éteint 30 s après. */
    var dernierToucherLe = 0L

    private fun texte(couleur: Int, poids: Int = 400, italique: Boolean = false, lignes: Int = 1) = TexteFondu(ctx).apply {
        peinture.typeface = Polices.texte(ctx, poids, italique)
        peinture.color = couleur
        maxLignes = lignes
    }

    /** Chiffre en Big Shoulders Display (graisse 200), la police de l'heure. */
    private fun chiffre(couleur: Int) = TexteFondu(ctx).apply {
        peinture.typeface = Polices.heure(ctx)
        peinture.color = couleur
    }

    private fun lignes(o: Int = LinearLayout.VERTICAL) = LinearLayout(ctx).apply {
        orientation = o
        clipChildren = false
        clipToPadding = false
    }

    // ------------------------------------------------------------ vues

    /** Le plan 3D, sous tout le reste, sur toute la fenêtre. */
    val plan = PlanAmbiant(ctx)
    /** Couche des textes : elle suit la vie de l'écran (fondu vers l'AOD). */
    private val couche = CadreMaquette(ctx).apply { clipChildren = false }
    /** Écran AOD (0.17.2) : heure, météo et lumières en gris sombre, bloc qui change de zone toutes les 3 min. */
    val aod = VueAod(ctx)

    val vue = CadreMaquette(ctx)

    private val heure = VueHeure(ctx)
    private val zoneHeure = View(ctx).apply {
        isClickable = true
        contentDescription = "Heure, toucher pour parler à ${ConfigMaison.NOM_ASSISTANT}"
        setOnClickListener { surParler() }
    }

    // Colonne du repos (piste A).
    private val ligneDate = texte(Palette.texte2)
    private val picto = PictoTrait(ctx)
    private val temperature = chiffre(Palette.meteo)
    private val pluie = texte(Palette.accentPluie)
    private val ligneMeteo = lignes(LinearLayout.HORIZONTAL).apply {
        gravity = Gravity.BOTTOM
        addView(picto)
        addView(temperature)
        addView(pluie)
    }
    private val blocMeteo = lignes().apply {
        addView(ligneDate)
        addView(ligneMeteo)
        isClickable = true
        contentDescription = "Météo, toucher pour ouvrir le panneau Météo"
        setOnClickListener { surMeteo() }
    }
    /**
     * Santé du propriétaire (0.19.0), en graphes depuis la 0.26.0 (anneau des pas, 7 nuits, cœur au repos), seulement
     * quand il est reconnu et seul, en vivant plein. Retirée de l'arbre (GONE, sans libellé) dès qu'elle ne l'est plus.
     */
    private val sante = VueSanteAccueil(ctx).apply {
        setOnClickListener { surSante() }
        visibility = View.GONE
    }
    /** Panne, en une seule ligne ambre, dernière ligne de la colonne (0.24.0). */
    private val panne = texte(Palette.accentLumiere).apply {
        visibility = View.GONE
        setOnClickListener { if (alerteCle) surAppareils() }
    }
    /** Message bref de l'arbitre, quelques secondes, sous la colonne. */
    private val bref = texte(Palette.texte2).apply { visibility = View.GONE }
    private val colRepos = lignes().apply {
        addView(blocMeteo)
        addView(sante)
        addView(panne)
        addView(bref)
    }

    // Colonne de l'écoute, de la réflexion, de la réponse, de l'arrêt.
    private val entete = texte(Palette.texte3)
    private val principal = texte(Palette.texte1, lignes = 6).apply { interligne = INTERLIGNE }
    private val aide = texte(Palette.texte3)
    private val demarrer = texte(Palette.texte1).apply {
        texte = "Démarrer ${ConfigMaison.NOM_ASSISTANT}"
        isClickable = true
        contentDescription = "Démarrer ${ConfigMaison.NOM_ASSISTANT}"
        setOnClickListener { surDemarrer() }
    }
    private val colEchange = lignes().apply {
        addView(entete)
        addView(principal)
        addView(aide)
        addView(demarrer)
        visibility = View.GONE
    }
    private val zoneTexte = lignes().apply {
        addView(colRepos)
        addView(colEchange)
    }

    /** Toucher le haut du bloc Musique : écran Musique, posé par l'écran principal. */
    val musique = CarteEnCours(ctx) { surMusique() }
    /** Suivi de l'arrêt de la musique, gardé par l'écran principal d'une reconstruction à l'autre (comme [salutation]). */
    var suiviMusique = SuiviMusique()
    private var phaseMusique = SuiviMusique.Phase.ABSENT

    /** L'orbe de l'écoute (0.24.0), au centre de la zone du plan. */
    private val orbe = VueOrbe(ctx).apply {
        isClickable = false
        isFocusable = false
        importantForAccessibility = View.IMPORTANT_FOR_ACCESSIBILITY_NO
        rapide = true
        reglerTaille(0f)
        visibility = View.GONE
    }

    /** La maison en grand (0.27.0), au-dessus du plan et de la couche des textes. */
    private val maisonGrand = VueMaisonGrand(ctx)
    private var grandToucheLe = 0L
    /** La maison est en grand : la veille la compte comme une activité (MainActivity.majVeille). */
    val enGrand: Boolean get() = maisonGrand.ouverte
    private var contenuLu: String? = null
    private var pieces: List<MaisonEnGrand.Piece> = emptyList()

    // Couche de service, 10 s après un toucher dans le noir, en bas de la colonne de gauche (0.24.0).
    private val pointsVues = List(3) { GradientDrawable().apply { shape = GradientDrawable.OVAL } }
    private val libellesPoints = listOf("Serveur", "Maison", "Caméra").map { texte(Palette.texte3).apply { texte = it } }
    private val lignePoints = lignes(LinearLayout.HORIZONTAL).apply { gravity = Gravity.CENTER_VERTICAL }
    private val boutonMusique = texte(Palette.texte2).apply {
        texte = "Musique"
        isClickable = true
        contentDescription = "Musique"
        setOnClickListener { surMusique() }
    }
    private val reglages = texte(Palette.texte2).apply {
        texte = "Réglages"
        isClickable = true
        contentDescription = "Réglages"
        setOnClickListener { surReglages() }
    }
    private val ligneBoutons = lignes(LinearLayout.HORIZONTAL).apply {
        gravity = Gravity.CENTER_VERTICAL
        addView(boutonMusique)
        addView(reglages)
    }
    private val consigne = texte(Palette.texte3)
    /** Version et date de compilation de l'appli, posée par l'écran principal, suivie de celle de la page 3D. */
    var libelleVersion = ""
    private val version = texte(Palette.texte3)
    private val service = lignes().apply {
        addView(lignePoints)
        addView(ligneBoutons)
        addView(consigne)
        addView(version)
        alpha = 0f
        visibility = View.INVISIBLE
    }

    init {
        val n = Float.NaN
        val P = CadreMaquette::Place
        couche.addView(heure, P(72f, 48f, n, n, n, n))
        couche.addView(zoneTexte, P(72f, 230f, n, n, LARGEUR_COLONNE, n))
        couche.addView(orbe, P(0f, 0f, n, n, COTE_ORBE, COTE_ORBE))
        couche.addView(musique.vue, P(X_MUSIQUE, Y_MUSIQUE, n, n, CarteEnCours.LARGEUR, CarteEnCours.HAUTEUR))
        couche.addView(service, P(72f, 648f, n, n, LARGEUR_COLONNE, n))
        couche.addView(zoneHeure, P(56f, 32f, n, n, 260f, 170f))
        vue.addView(plan.vue, P(0f, 0f, 0f, 0f, n, n))
        vue.addView(couche, P(0f, 0f, 0f, 0f, n, n))
        vue.addView(maisonGrand.vue, P(0f, 0f, 0f, 0f, n, n))
        vue.addView(aod, P(0f, 0f, 0f, 0f, n, n))
        vue.setBackgroundColor(Palette.fond)
        for ((i, l) in libellesPoints.withIndex()) {
            lignePoints.addView(View(ctx).apply { background = pointsVues[i] })
            lignePoints.addView(l)
        }
        musique.vue.visibility = View.GONE
        musique.vue.alpha = 0f
        demarrer.visibility = View.GONE
        plan.surToucher = { toucherPlan() }
        plan.surVide = { montrerService() }
        plan.surDesigne = { designe(it) }
        maisonGrand.surFermer = { fermerGrand() }
        maisonGrand.surAppareils = {
            fermerGrand()
            surMaison()
        }
        maisonGrand.surChange = { if (maisonGrand.ouverte) majGrand(dernier, SystemClock.elapsedRealtime()) }
        maisonGrand.surToucher = { grandToucheLe = SystemClock.elapsedRealtime() }
        vue.surEchelle = { appliquer(it) }
        // Pendant l'écoute et la réponse, toucher l'écran n'importe où arrête.
        vue.capter = { _, _ -> capturable() }
        vue.surCapte = { _, _, leve -> if (leve && capturable()) surParler() }
        // Toucher dans le noir (hors plan et hors textes) : couche de service.
        vue.surVide = { montrerService() }
        appliquer(vue.echelle)
        majHeure()
        placerOrbe(Disposition.A)
    }

    /** Écoute en cours ou voix qui parle : le toucher n'importe où arrête (second toucher de l'orbe). */
    private fun capturable(): Boolean {
        val e = dernier
        return e.enMarche && (e.assistant == "Je t'écoute" || e.assistant == "Je réponds")
    }

    /** Tailles de la maquette (pixels de maquette) à l'échelle [s] de l'écran (48 dp au moins pour toucher). */
    private fun appliquer(s: Float) {
        fun lp(v: View, haut: Float = 0f, gauche: Float = 0f) {
            (v.layoutParams as? LinearLayout.LayoutParams ?: LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT))
                .also { it.topMargin = (haut * s).toInt(); it.marginStart = (gauche * s).toInt(); v.layoutParams = it }
        }
        val toucher = Decor.dp(ctx, 48f)
        heure.echelle = s
        musique.echelle(s)
        // Colonne du repos (maquette `AccueilMusique`, piste A).
        ligneDate.taille(30f * s)
        picto.layoutParams = LinearLayout.LayoutParams((58 * s).toInt(), (58 * s).toInt()).apply { marginEnd = (14 * s).toInt(); bottomMargin = (6 * s).toInt() }
        temperature.taille(TAILLE_TEMPERATURE * s)
        pluie.taille(26f * s)
        lp(pluie, 0f, 26f)
        lp(ligneMeteo, 20f)
        // Bloc santé : 28 px sous la météo, avec sa marge de toucher de 12 px tout autour (maquette `SanteMelange`).
        sante.echelle = s
        lp(sante, 28f, -VueSanteAccueil.MARGE)
        panne.taille(24f * s)
        lp(panne, 44f)
        bref.taille(24f * s)
        lp(bref, 36f)
        // Colonne de l'échange.
        entete.taille(TAILLE_PETITE * s)
        principal.taille(TAILLE_ZONE * s)
        lp(principal, 14f)
        aide.taille(TAILLE_CONSIGNE * s)
        lp(aide, 20f)
        demarrer.taille(30f * s)
        demarrer.minimumHeight = max((48 * s).toInt(), toucher)
        lp(demarrer, 10f)
        // Couche de service : points, Musique et Réglages, consigne et version.
        val d = (10 * s).toInt()
        for ((i, l) in libellesPoints.withIndex()) {
            pointsVues[i].setSize(d, d)
            (lignePoints.getChildAt(2 * i).layoutParams as? LinearLayout.LayoutParams ?: LinearLayout.LayoutParams(d, d)).also {
                it.width = d; it.height = d; it.marginStart = if (i == 0) 0 else (20 * s).toInt()
                lignePoints.getChildAt(2 * i).layoutParams = it
            }
            l.taille(18f * s)
            lp(l, 0f, 8f)
        }
        for ((i, b) in listOf(boutonMusique, reglages).withIndex()) {
            b.taille(20f * s)
            b.minimumHeight = max((48 * s).toInt(), toucher)
            b.setPadding((12 * s).toInt(), 0, (12 * s).toInt(), 0)
            lp(b, 0f, if (i == 0) -12f else 0f)
        }
        lp(ligneBoutons, 4f)
        consigne.taille(16f * s)
        lp(consigne, 4f)
        version.taille(16f * s)
        lp(version, 2f)
        // Pixels CSS de la page 3D par pixel de maquette (la page compte en dp).
        plan.unite = s / ctx.resources.displayMetrics.density
        maisonGrand.echelle(s)
        cleRepos = ""
        cleEchange = ""
        zoneOrbe = null
    }

    // ------------------------------------------------------------ mise à jour

    private var dernier = Etat.Instantane()
    private var mode = Accueil.Mode.REPOS
    private val retenuePanne = Accueil.Retenue(Accueil.DELAI_PANNE_MS)
    private var alerteCle = false
    private var panneMaisonDepuis: LocalTime? = null
    private var lecteursVus: List<Etat.Lecteur>? = null
    private var mediasVus: List<Appareils.Appareil>? = null
    private var aodTemperature = ""
    private var aodCode = ""
    private var aodLumieres = ""
    /** Cartes d'action déjà vues, et celle de l'action en cours sur le plan. */
    private val cartesVues = HashSet<Long>()
    private var carteAction = -1L
    /** Salutation, gardée par l'écran principal d'une reconstruction à l'autre (0.21.1) : pas de second « Bonjour ». */
    var salutation = Accueil.Salut()
    private var serviceJusqua = 0L
    private var jourDispo = -1L
    private var decale = false
    private var cleRepos = ""
    private var cleEchange = ""
    /** Prévisions horaires pour « pluie 17 h », posées par l'écran principal (vides tant que le serveur les refuse). */
    var horaire: List<Previsions.Prevision> = emptyList()
    /** Résumé de santé en mémoire seulement (10 min au plus), et régime vivant de l'écran. */
    private val memoireSante = Sante.Memoire()
    private var vivantAccueil = false
    private var cleSante = ""
    private var santeMontree = false

    // Disposition (0.24.0) : zone du plan appliquée, fin du mouvement en cours, bloc Musique d'avant l'écoute.
    private var zonePlan = Disposition.A
    private var mouvementJusqua = 0L
    private var blocAvantEcoute = false
    private var orbeOuvert = false
    /** L'orbe se referme en 0,4 s avant que le plan et la zone ne reviennent. */
    private var fermetureOrbeLe = 0L
    private var erreurLe = 0L
    /** Ouverture de l'orbe, et dernière action sur des lampes confirmée par Home Assistant. */
    private var ouvertLe = 0L
    private var actionLe = -1L
    private var zoneOrbe: Disposition.Zone? = null
    /** Régime : vivant plein (1) ou en retrait (0), lissé par Veille. */
    private var eclat = 1f
    private var actif = true
    private var cleCouleurs = ""

    /** Relance de l'affichage (0.17.3) : écran rallumé, activité reprise, focus retrouvé. */
    fun reprendreRendu() {
        aod.reprendreRendu()
        heure.invalidate()
        orbe.reprendreRendu()
    }

    /** Toutes les secondes : l'heure et sa dérive, la retenue de la panne, la réponse qui s'efface, la couche de service. */
    fun tic() {
        val hh = majHeure()
        aod.regler(hh, aodTemperature, aodCode, aodLumieres)
        musique.tic()
        majDisposition()
        // Maison en grand : retour à l'accueil après 45 s sans toucher, compte suspendu sous un doigt posé.
        if (maisonGrand.ouverte) {
            val t = SystemClock.elapsedRealtime()
            if (vue.doigtPose || maisonGrand.doigtSurPiste) grandToucheLe = t
            else if (t - max(grandToucheLe, dernierToucherLe) > MaisonEnGrand.RETOUR_MS) fermerGrand()
        }
        plan.intensite(Disposition.intensite(jour(), sombre() ?: Station.nuit()))
        rafraichir()
    }

    private var jourAffiche = ""

    private fun majHeure(): String {
        val hh = HEURE.format(Date())
        heure.regler(hh.substring(0, 2), hh.substring(3, 5))
        val jour = TextesCourts.date(LocalDate.now())
        if (jour != jourAffiche) {
            jourAffiche = jour
            cleRepos = ""
        }
        return hh
    }

    /**
     * Disposition du jour (un jour sur deux, colonne de gauche à x 120 et moitié droite décalée de 24 px) et
     * dérive propre de l'heure, en pixels réels, en plus du décalage global de toute l'interface.
     */
    private fun majDisposition() {
        val s = vue.echelle
        val jour = LocalDate.now().toEpochDay()
        if (jour != jourDispo) {
            jourDispo = jour
            decale = Veille.miroir(jour)
            zoneTexte.translationX = if (decale) DECALAGE_COLONNE * s else 0f
            service.translationX = zoneTexte.translationX
            musique.vue.translationX = if (decale) Disposition.DECALAGE_DROITE * s else 0f
        }
        val (x, y) = Veille.deriveHeure(System.currentTimeMillis())
        val dx = (if (decale) DECALAGE_COLONNE * s else 0f) + x
        for (v in listOf(heure, zoneHeure)) {
            v.translationX = dx
            v.translationY = y
        }
        // La colonne suit la dérive de l'heure (usure de l'OLED sous la température et les chiffres de santé).
        zoneTexte.translationX = dx
        zoneTexte.translationY = y
    }

    fun maj(e: Etat.Instantane) {
        dernier = e
        majMusique(e)
        majCartes(e)
        rafraichir()
    }

    private fun rafraichir() {
        val e = dernier
        val maintenant = SystemClock.elapsedRealtime()
        mode = Accueil.mode(e.enMarche, e.assistant, e.parole, e.paroleFinLe, maintenant)
        val l = musique.courant
        phaseMusique = suiviMusique.avancer(l?.etat == "playing", l != null, maintenant)
        majPanne(e, maintenant)
        majSante(e, maintenant)
        majSalut(e, maintenant)
        majOrbe(e, maintenant)
        // La maison en grand ne vit qu'au repos, en vivant plein, sans l'orbe.
        if (maisonGrand.ouverte && (!vivantAccueil || !actif || mode != Accueil.Mode.REPOS || orbeOuvert)) fermerGrand()
        majPlan(maintenant)
        placerOrbe(zonePlan)
        majZone(e, maintenant)
        majMusiqueVisible(maintenant)
        majService(e, maintenant)
        plan.maj(e.lumieres, e.quiParle())
        plan.majMedias(e.mediasPlan)
        plan.desaturer(panneMaisonDepuis != null && retenuePanne.montre.isNotEmpty())
        // Heure et colonne cachées pendant la maison en grand.
        val g = maisonGrand.ouverte
        for (v in listOf(heure, zoneHeure, zoneTexte)) fondre(v, !g, instant = !vivantAccueil)
        if (g) majGrand(e, maintenant)
        majAod(e)
    }

    private fun majAod(e: Etat.Instantane) {
        val maison = e.maison
        val t = e.meteo?.temperature ?: ""
        val c = e.meteo?.code ?: ""
        val l = when {
            maison == null -> ""
            maison.lumieres == 0 -> "Lumières éteintes"
            maison.lumieres == 1 -> "1 lumière allumée"
            else -> "${maison.lumieres} lumières allumées"
        }
        if (t == aodTemperature && c == aodCode && l == aodLumieres) return
        aodTemperature = t
        aodCode = c
        aodLumieres = l
        aod.regler(HEURE.format(Date()), aodTemperature, aodCode, aodLumieres)
    }

    /** Lecteurs et volumes des enceintes : la carte garde le dernier lecteur tant que le bloc doit rester. */
    private fun majMusique(e: Etat.Instantane) {
        if (e.mediasPlan !== mediasVus) {
            mediasVus = e.mediasPlan
            musique.volumes(e.mediasPlan)
        }
        if (e.lecteurs === lecteursVus) return
        lecteursVus = e.lecteurs
        musique.maj(e.lecteurs, retenir = phaseMusique != SuiviMusique.Phase.ABSENT)
    }

    /**
     * Bloc Musique (0.24.0) : là tant qu'une musique joue, puis 30 s sans rien changer après l'arrêt, puis 10 min
     * en pause atténuée. Caché pendant l'écoute et la réponse. Il n'apparaît qu'une fois le plan arrivé en haut.
     */
    private fun majMusiqueVisible(maintenant: Long) {
        if (phaseMusique == SuiviMusique.Phase.ABSENT && musique.courant != null && dernier.lecteurs.isEmpty()) musique.oublier()
        musique.pause(phaseMusique == SuiviMusique.Phase.PAUSE)
        // Maison hors ligne : rien ne peut partir, les commandes sont éteintes.
        musique.eteindre(maintenant - dernierToucherLe > DELAI_COMMANDES_MS || (panneMaisonDepuis != null && retenuePanne.montre.isNotEmpty()))
        val repos = mode == Accueil.Mode.REPOS || mode == Accueil.Mode.ARRETE
        val montrer = repos && !orbeOuvert && !maisonGrand.ouverte && suiviMusique.montre(phaseMusique) && zonePlan.estMusique() && maintenant >= mouvementJusqua
        fondre(musique.vue, montrer, gone = true, cible = if (phaseMusique == SuiviMusique.Phase.PAUSE) OPACITE_PAUSE else 1f, instant = !vivantAccueil)
    }

    /** Zone d'un état avec le bloc Musique (B, ou l'écoute avec musique) : la seule à monter le plan. */
    private fun Disposition.Zone.estMusique(): Boolean = this.y < Disposition.A.y

    /**
     * Zone du plan (0.24.0) : A sans le bloc, B avec, resserrée pendant l'écoute autour du même centre. Une seule
     * transition à la fois, rien sous un doigt posé, d'un coup quand l'écran n'est pas vivant. Tant que l'assistant
     * répond, le plan garde la place qu'il avait à l'ouverture de l'orbe (pas de détour par A).
     */
    private fun majPlan(maintenant: Long) {
        // En grand, la zone suit la pièce choisie (ouvrirGrand, choisirPiece).
        if (maisonGrand.ouverte) return
        val avecBloc = if (orbeOuvert || Accueil.occupe(mode)) blocAvantEcoute
        else suiviMusique.montre(phaseMusique) && (mode == Accueil.Mode.REPOS || mode == Accueil.Mode.ARRETE)
        val z = Disposition.zone(avecBloc, orbeOuvert, decale)
        if (z == zonePlan) return
        val immediat = !vivantAccueil
        if (!immediat && (maintenant < mouvementJusqua || vue.doigtPose || musique.glisse)) return
        val duree = when {
            immediat -> 0
            orbeOuvert -> 450
            else -> 600
        }
        zonePlan = z
        mouvementJusqua = maintenant + duree
        plan.disposer(z, duree)
        plan.attenuer(orbeOuvert)
        placerOrbe(z)
        // Le bloc s'efface pendant que le plan glisse vers la zone A, il apparaît une fois le plan arrivé en B.
        if (duree > 0) vue.postDelayed({ rafraichir() }, duree + 20L)
    }

    /**
     * L'orbe (0.24.0) : il s'ouvre au mot de réveil ou au toucher de l'heure, au centre de la zone du plan, et se
     * referme sur place en 0,4 s à la fin de la réponse (6 s après la voix), à la confirmation d'une action sur des
     * lampes, ou après 1 s de rouge en erreur. Le plan et la zone reviennent ensuite.
     */
    private fun majOrbe(e: Etat.Instantane, maintenant: Long) {
        val erreur = mode == Accueil.Mode.REPONSE && e.historique.firstOrNull()?.let { it.erreur && it.reponse == e.jarvis } == true
        if (erreur && erreurLe == 0L) erreurLe = maintenant
        if (!erreur) erreurLe = 0L
        // Action sur des lampes partie pendant cette ouverture (réflexion ou réponse) : l'orbe laisse voir le plan.
        val action = ouvertLe > 0L && actionLe >= ouvertLe
        val ouvert = Accueil.occupe(mode) && !action && (erreurLe == 0L || maintenant - erreurLe < DUREE_ERREUR_MS)
        if (ouvert && !orbeOuvert) {
            ouvertLe = maintenant
            // Entrée en écoute : le bloc Musique reste comme il était (caché s'il ne l'était pas).
            blocAvantEcoute = musique.vue.visibility == View.VISIBLE && cibles[musique.vue] != 0f
            orbeOuvert = true
            fermetureOrbeLe = 0L
            orbe.poserTaille(0f)
            orbe.visibility = View.VISIBLE
            orbe.reprendreRendu()
        } else if (ouvert && fermetureOrbeLe != 0L) {
            // Réveil pendant la fermeture : nouvelle ouverture.
            fermetureOrbeLe = 0L
            ouvertLe = maintenant
        } else if (!ouvert && orbeOuvert) {
            if (fermetureOrbeLe == 0L) {
                fermetureOrbeLe = maintenant + FERMETURE_ORBE_MS
                vue.postDelayed({ rafraichir() }, FERMETURE_ORBE_MS + 20L)
            }
            if (maintenant >= fermetureOrbeLe) {
                orbeOuvert = false
                orbe.visibility = View.GONE
                orbe.poserTaille(0f)
            }
        }
        val humeur = when {
            erreur -> VueOrbe.Humeur.ERREUR
            mode == Accueil.Mode.ECOUTE -> VueOrbe.Humeur.ECOUTE
            mode == Accueil.Mode.REFLEXION -> VueOrbe.Humeur.REFLEXION
            else -> VueOrbe.Humeur.REPONSE
        }
        val niveau = ((e.niveauDb + 50f) / 40f).coerceIn(0f, 1f)
        val soir = !jour()
        orbe.doux = soir
        orbe.particules = if (soir) 10 else 22
        if (ouvert) orbe.regler(humeur, if (e.enMarche) niveau else 0f)
        // Pleine taille à l'écoute et pendant la réponse, 85 % en réflexion, refermé dès qu'il n'est plus ouvert.
        orbe.reglerTaille(if (!ouvert) 0f else if (mode == Accueil.Mode.REFLEXION) TAILLE_REFLEXION else 1f)
        // Les points de l'heure prennent la teinte de l'orbe.
        heure.couleurPoints = couleurOrbe(humeur, soir, texte = false)
        val parle = e.enMarche && e.assistant == "Je réponds"
        heure.reglerPoints(
            when {
                mode == Accueil.Mode.ECOUTE -> VueHeure.Points.ECOUTE
                mode == Accueil.Mode.REFLEXION -> VueHeure.Points.REFLEXION
                parle -> VueHeure.Points.REPONSE
                else -> VueHeure.Points.REPOS
            },
            if (e.enMarche) niveau else 0f, e.parole,
        )
    }

    /** Orbe centré sur la zone du plan, 200 px sans musique, 170 avec, 85 % le soir. */
    private fun placerOrbe(z: Disposition.Zone) {
        val s = vue.echelle
        val avecMusique = z.estMusique()
        val diametre = Disposition.diametreOrbe(avecMusique, !jour())
        orbe.rayonFixe = diametre / 2f * s
        if (z == zoneOrbe) return
        zoneOrbe = z
        val n = Float.NaN
        orbe.layoutParams = CadreMaquette.Place(z.centreX - COTE_ORBE / 2f, z.centreY - COTE_ORBE / 2f, n, n, COTE_ORBE, COTE_ORBE)
    }

    /** Teinte de l'orbe (VueOrbe.cibleHsl), plus douce le soir, et assez claire pour un texte ([texte]). */
    private fun couleurOrbe(h: VueOrbe.Humeur, soir: Boolean, texte: Boolean): Int {
        val c = VueOrbe.cibleHsl(h)
        val sa = c[1] * (if (soir) 0.55f else 1f)
        var l = c[2] * (if (soir) 0.7f else 1f)
        if (texte) l = max(l, 0.5f)
        return VueOrbe.hsl(c[0], sa, l, 255)
    }

    /**
     * Action vraiment faite à l'instant (carte de moins de 3 s, ni essai ni refus) : le plan la joue si
     * elle touche des lumières. Les cartes retrouvées après une rotation de l'écran ne rejouent rien.
     */
    private fun majCartes(e: Etat.Instantane) {
        val t = SystemClock.elapsedRealtime()
        for (c in e.cartes) {
            if (c.reponse || !cartesVues.add(c.id)) continue
            if (t - c.creeLe >= 3_000L || c.essai || c.statut == "refuse" || c.statut == "essai") continue
            val lumieres = c.entites.filter { it.startsWith("light.") }
            if (lumieres.isEmpty()) continue
            carteAction = c.id
            // 0.24.1 (retour du propriétaire : « l'orbe cache l'animation sur la maison ») : l'orbe se referme dès que
            // l'action part, et la page ne la joue qu'une fois l'orbe refermé, sur un plan qui revient à 1.
            actionLe = t
            val effets = lumieres.associateWith { c.effets[it] ?: "regler" }
            val demo = c.statut == "demo"
            if (orbeOuvert) {
                vue.postDelayed({ plan.action(effets, demo) }, FERMETURE_ORBE_MS + 50L)
            } else {
                plan.action(effets, demo)
            }
        }
    }

    /** Carte d'une action sur des lumières restée sans réponse de Home Assistant, encore récente. */
    private fun echec(e: Etat.Instantane, maintenant: Long): Etat.Carte? =
        e.cartes.firstOrNull { it.id == carteAction && it.statut == "sans_reponse" && maintenant - it.creeLe < DUREE_ECHEC_MS }

    private fun majPanne(e: Etat.Instantane, maintenant: Long) {
        val texte = Accueil.panne(
            e.enMarche, e.lien == Etat.Lien.CONNECTE, e.capServeur == "local", e.passerelleDispo, e.maison != null,
            e.visionNiveau, e.alerteCle, e.alerteJeton,
        )
        alerteCle = e.alerteCle.isNotBlank() || e.alerteJeton.isNotBlank()
        // Début de la panne de la maison (serveur ou Home Assistant), pour « depuis 10 h 02 ».
        val maisonEnPanne = texte == "Home Assistant ne répond plus" || texte == "Serveur injoignable"
        if (maisonEnPanne && panneMaisonDepuis == null) panneMaisonDepuis = LocalTime.now()
        if (!maisonEnPanne) panneMaisonDepuis = null
        val montre = retenuePanne.avancer(texte, maintenant, immediat = alerteCle)
        val depuis = panneMaisonDepuis
        val ligne = TextesCourts.panne(montre, depuis?.hour, depuis?.minute)
        if (panne.texte.toString() != ligne) panne.texte = ligne
        panne.isClickable = alerteCle
        panne.visibility = if (ligne.isEmpty()) View.GONE else View.VISIBLE
    }

    /**
     * Santé du propriétaire (0.19.0) : demandée au serveur quand il est reconnu et seul, montrée au repos en régime
     * vivant, cachée sur-le-champ (sans fondu) dès qu'il n'est plus seul ou plus reconnu.
     */
    private fun majSante(e: Etat.Instantane, maintenant: Long) {
        val jourCivil = Sante.aujourdhui().toEpochDay()
        val demo = demoSanteJusqua != 0L && maintenant < demoSanteJusqua
        if (demoSanteJusqua != 0L && !demo) {
            demoSanteJusqua = 0L
            memoireSante.oublier()
        }
        // 0.21.1 : le propriétaire seul sur une image de moins d'1 s, identité soutenue par cette image (Sante.Garde).
        val proprietaireSeul = vivantAccueil && (demo || Sante.proprietaireSeul(e, maintenant))
        if (!demo && memoireSante.avancer(proprietaireSeul, maintenant, jourCivil)) {
            surDemanderSante { r ->
                val t = SystemClock.elapsedRealtime()
                // Second contrôle à l'arrivée de la réponse : propriétaire toujours seul, et pas de démonstration en
                // cours (une vraie valeur ne remplit jamais une démonstration).
                val enDemo = demoSanteJusqua != 0L && t < demoSanteJusqua
                if (enDemo || !vivantAccueil || !Sante.proprietaireSeul(Etat.courant, t)) {
                    memoireSante.recu(null, t, jourCivil)
                } else {
                    memoireSante.recu(r, t, Sante.aujourdhui().toEpochDay())
                }
                rafraichir()
            }
        }
        val r = memoireSante.montre(proprietaireSeul)
        // 0.26.0 : seulement en vivant plein (jamais en retrait, en AOD ni écran éteint), au repos.
        val montrer = Sante.montreAccueil(proprietaireSeul, vivantAccueil, actif, mode == Accueil.Mode.REPOS && !maisonGrand.ouverte, r)
        val cle = if (montrer) r.toString() else ""
        if (montrer != santeMontree) {
            santeMontree = montrer
            sante.animate().cancel()
            if (montrer) {
                // Fenêtre protégée avant que les chiffres ne s'affichent, pas à la seconde suivante.
                surSecurite()
                cleSante = cle
                sante.resume = r
                sante.contentDescription = VueSanteAccueil.libelle(r!!)
                sante.soir = !jour()
                sante.alpha = 0f
                sante.visibility = View.VISIBLE
                sante.animate().alpha(0.94f).setDuration(DUREE_APPARITION_SANTE_MS).start()
            } else {
                // Départ : hors de l'écran sur-le-champ, ni lisible ni touchable pendant un fondu.
                sante.visibility = View.GONE
                sante.resume = null
                sante.contentDescription = null
                cleSante = ""
                surSecurite()
            }
        } else if (montrer && cle != cleSante) {
            cleSante = cle
            sante.resume = r
            sante.contentDescription = VueSanteAccueil.libelle(r!!)
        }
        if (montrer) {
            sante.soir = !jour()
            // Vision qui se tait : la garde est revue toutes les 300 ms, pas seulement à la seconde.
            vue.removeCallbacks(revoirSante)
            vue.postDelayed(revoirSante, REVUE_SANTE_MS)
        }
    }

    private var demoSanteJusqua = 0L
    private val revoirSante = Runnable { if (santeMontree) majSante(dernier, SystemClock.elapsedRealtime()) }

    /** Démonstration de l'appli de débogage : [r] montré [dureeMs] sans la vision ni le serveur, puis oublié. */
    fun demoSante(r: Sante.Resume, dureeMs: Long) {
        val t = SystemClock.elapsedRealtime()
        memoireSante.oublier()
        memoireSante.recu(r, t, Sante.aujourdhui().toEpochDay())
        demoSanteJusqua = t + dureeMs
        rafraichir()
    }

    /** De vraies valeurs de santé sont à l'écran (pas une démonstration) : la fenêtre doit être protégée. */
    val santeReelleMontree: Boolean get() = santeMontree && demoSanteJusqua == 0L

    /**
     * Activité en pause, écran éteint (0.21.1) : chiffres de santé effacés sur-le-champ et résumé oublié, pour
     * que la capture des applis récentes ne garde rien.
     */
    fun effacerSante() {
        memoireSante.oublier()
        demoSanteJusqua = 0L
        sante.animate().cancel()
        sante.visibility = View.GONE
        sante.resume = null
        sante.contentDescription = null
        cleSante = ""
        santeMontree = false
    }

    /** « Bonjour Sacha » remplace la date pendant 10 s après la reconnaissance (revue des palettes). */
    private var salutActuel = ""

    private fun majSalut(e: Etat.Instantane, maintenant: Long) {
        val nom = salutation.avancer(e.personneSeule().ifEmpty { null }, maintenant)
        salutActuel = Accueil.salutation(nom, Calendar.getInstance().get(Calendar.HOUR_OF_DAY))
    }

    /** Ce que dit la colonne, selon l'état : le repos minimaliste, ou l'écoute, la réflexion, la réponse, l'échec. */
    private fun majZone(e: Etat.Instantane, maintenant: Long) {
        val rate = echec(e, maintenant)
        val repos = mode == Accueil.Mode.REPOS && rate == null
        colRepos.visibility = if (repos) View.VISIBLE else View.GONE
        colEchange.visibility = if (repos) View.GONE else View.VISIBLE
        zoneTexte.isClickable = false
        if (repos) majRepos(e, maintenant) else majEchange(e, rate)
    }

    /** Colonne du repos (piste A) : date courte, température en grand et son pictogramme, pluie qui arrive. */
    private fun majRepos(e: Etat.Instantane, maintenant: Long) {
        val date = salutActuel.ifEmpty { jourAffiche }
        val temp = TextesCourts.temperature(e.meteo)
        val p = TextesCourts.pluie(Accueil.pluie(horaire, ZonedDateTime.now()))
        val nuit = !jour()
        val dessin = MeteoTexte.picto(e.meteo?.code ?: "", nuit)
        val b = if (e.bref.isNotEmpty() && maintenant - e.brefLe < EcranAmbiantDelais.BREF_MS && panne.visibility != View.VISIBLE) e.bref else ""
        val cle = "$date|$temp|$p|$dessin|$b"
        if (cle == cleRepos) return
        cleRepos = cle
        ligneDate.texte = date
        temperature.texte = temp
        picto.picto = dessin
        ligneMeteo.visibility = if (temp.isEmpty()) View.GONE else View.VISIBLE
        pluie.texte = p
        pluie.visibility = if (p.isEmpty()) View.GONE else View.VISIBLE
        bref.texte = b
        bref.visibility = if (b.isEmpty()) View.GONE else View.VISIBLE
    }

    /** Colonne de l'échange : écoute, réflexion, réponse, échec d'une action, assistant à l'arrêt. */
    private fun majEchange(e: Etat.Instantane, rate: Etat.Carte?) {
        var tete = ""
        var couleurTete = Palette.texte3
        var corps: CharSequence
        var couleurCorps = Palette.texte1
        var italique = false
        var consigne = ""
        var bouton = false
        when {
            rate != null && (mode == Accueil.Mode.REPOS || mode == Accueil.Mode.REPONSE) -> {
                tete = majuscule(e.entendu.trim())
                val noms = rate.entites.filter { it.startsWith("light.") }.map { id -> e.lumieres.firstOrNull { it.id == id }?.nom ?: e.noms[id] ?: Maison.nomBrut(id) }
                corps = Accueil.echec(noms.distinct(), rate.effets.values.firstOrNull { it == "allumer" || it == "eteindre" } ?: "regler")
            }
            mode == Accueil.Mode.ECOUTE -> {
                tete = "Je t'écoute"
                couleurTete = couleurOrbe(VueOrbe.Humeur.ECOUTE, !jour(), texte = true)
                corps = majuscule(e.entendu.trim())
                italique = true
                consigne = "Touche l'écran pour arrêter"
            }
            mode == Accueil.Mode.REFLEXION -> {
                corps = majuscule(e.entendu.trim())
                couleurCorps = Palette.texte2
                italique = true
                consigne = e.aideReflexion
            }
            mode == Accueil.Mode.REPONSE -> {
                tete = majuscule(e.entendu.trim())
                corps = e.parole.trim()
            }
            mode == Accueil.Mode.ARRETE -> {
                corps = if (microAutorise) "${ConfigMaison.NOM_ASSISTANT} est à l'arrêt." else "Autorise le micro, puis démarre ${ConfigMaison.NOM_ASSISTANT}."
                couleurCorps = Palette.texte2
                bouton = true
            }
            else -> corps = ""
        }
        val cle = "$mode|$tete|$couleurTete|$corps|$couleurCorps|$italique|$consigne|$bouton"
        if (cle == cleEchange) return
        cleEchange = cle
        entete.texte = tete
        entete.couleur(couleurTete)
        entete.visibility = if (tete.isEmpty()) View.GONE else View.VISIBLE
        principal.police(Polices.texte(ctx, 400, italique))
        principal.couleur(couleurCorps)
        principal.texte = corps
        principal.visibility = if (corps.isEmpty()) View.INVISIBLE else View.VISIBLE
        aide.texte = consigne
        aide.visibility = if (consigne.isEmpty()) View.GONE else View.VISIBLE
        demarrer.visibility = if (bouton) View.VISIBLE else View.GONE
        principal.requestLayout()
    }

    /** Points d'état, Musique, Réglages, consigne et version : 10 s après un toucher dans le noir. */
    private fun majService(e: Etat.Instantane, maintenant: Long) {
        val p = Accueil.points(e.enMarche, e.lien == Etat.Lien.CONNECTE, e.capServeur == "local", e.passerelleDispo, e.maison != null, e.visionNiveau)
        for ((i, pt) in p.withIndex()) {
            pointsVues[i].setColor(
                when (pt) {
                    Accueil.Point.OK -> Palette.texte3
                    Accueil.Point.PANNE -> Palette.accentLumiere
                    Accueil.Point.ETEINT -> Palette.filet
                }
            )
        }
        val c = "Touche l'heure ou dis $motReveil."
        if (consigne.texte.toString() != c) consigne.texte = c
        val v = libelleVersion + (plan.versionPage.takeIf { it.isNotEmpty() }?.let { ", plan 3D $it" } ?: "")
        if (version.texte.toString() != v) version.texte = v
        fondre(service, maintenant < serviceJusqua && !maisonGrand.ouverte)
    }

    private fun montrerService() {
        serviceJusqua = SystemClock.elapsedRealtime() + DUREE_SERVICE_MS
        rafraichir()
    }

    private val cibles = HashMap<View, Float>()

    /** Fondu de 300 ms vers [cible]. Une vue cachée ne prend plus les touchers (INVISIBLE, ou GONE si [gone]). */
    private fun fondre(v: View, visible: Boolean, gone: Boolean = false, cible: Float = 1f, instant: Boolean = false) {
        val c = if (visible) cible else 0f
        if (cibles[v] == c) return
        cibles[v] = c
        v.animate().cancel()
        // Écran en veille : posé d'un coup, sans fondu.
        if (instant) {
            v.alpha = c
            v.visibility = if (visible) View.VISIBLE else if (gone) View.GONE else View.INVISIBLE
            return
        }
        if (visible) {
            v.visibility = View.VISIBLE
            v.animate().alpha(c).setDuration(DUREE_FONDU_MS).start()
        } else {
            v.animate().alpha(0f).setDuration(DUREE_FONDU_MS).withEndAction {
                if (cibles[v] == 0f) v.visibility = if (gone) View.GONE else View.INVISIBLE
            }.start()
        }
    }

    private fun majuscule(s: String): String = s.replaceFirstChar { it.titlecase(Locale.FRANCE) }

    /**
     * Pas de l'écran OLED (MainActivity.majVeille) : [vie] (1 vivant, 0 AOD), [visible] (0 sur fond noir),
     * [montrable] (aucun panneau ouvert, activité au premier plan), [vivant] (régime vivant), [eclat] (1 vivant
     * plein, 0 en retrait, lissé) et sa cible [actifVoulu].
     */
    fun reglerVie(vie: Float, visible: Float, montrable: Boolean, vivant: Boolean, eclat: Float = 1f, actifVoulu: Boolean = true) {
        val o = (vie * visible).coerceIn(0f, 1f)
        // La santé ne vit qu'en régime vivant, écran visible : jamais en AOD ni sur fond noir.
        val v = vivant && visible > 0f
        if (v != vivantAccueil) {
            vivantAccueil = v
            if (!v) majSante(dernier, SystemClock.elapsedRealtime())
        }
        if (couche.alpha != o) couche.alpha = o
        // Jamais en grand en AOD, écran éteint ou sous un panneau.
        if (maisonGrand.ouverte && (!v || !montrable)) fermerGrand()
        plan.regler(o, montrable, vivant)
        aod.opacite = (1f - vie) * visible
        majRegime(eclat, actifVoulu)
    }

    /**
     * Régime de l'accueil (0.24.0) : la page passe au vivant en 0,8 s ou au retrait en 6 s, les teintes de famille
     * de la colonne suivent l'éclat lissé (saturation de 40 % en retrait à 125 % en vivant), le bloc Musique est
     * désaturé et ses commandes éteintes en retrait.
     */
    private fun majRegime(e: Float, voulu: Boolean) {
        if (voulu != actif) {
            actif = voulu
            if (!voulu && maisonGrand.ouverte) fermerGrand()
            plan.regime(if (voulu) 1f else 0f, if (voulu) Veille.DUREE_REPRISE_MS.toInt() else Veille.DUREE_RETRAIT_MS.toInt())
            // Passage en retrait : la santé quitte l'écran tout de suite.
            majSante(dernier, SystemClock.elapsedRealtime())
        }
        if (abs(e - eclat) < 0.02f && e != 0f && e != 1f) return
        eclat = e
        musique.retrait(e < 0.5f)
        val k = SATURATION_RETRAIT + (SATURATION_VIVANT - SATURATION_RETRAIT) * e
        val cle = "${Palette.jeu.nom}|$k"
        if (cle == cleCouleurs) return
        cleCouleurs = cle
        val meteo = Couleurs.saturer(Palette.meteo, k)
        temperature.couleur(meteo)
        picto.couleur = meteo
        pluie.couleur(Couleurs.saturer(Palette.accentPluie, k))
        sante.teinte = Couleurs.saturer(Palette.sante, k)
        panne.couleur(Couleurs.saturer(Palette.accentLumiere, k))
    }

    // ------------------------------------------------------------ la maison en grand (0.27.0)

    /**
     * Toucher l'appartement : au repos, en vivant plein, la maison en grand. En retrait, le toucher ne fait que
     * réveiller l'écran. Assistant à l'arrêt ou page pas encore prête : l'écran Maison, comme avant.
     */
    private fun toucherPlan() {
        if (!vivantAccueil || !actif) return
        if (mode == Accueil.Mode.REPOS && !orbeOuvert && plan.pretPourGrand && piecesConnues().any { it.objets.isNotEmpty() }) ouvrirGrand()
        else surMaison()
    }

    /** Pièces de la page 3D (maison3d.contenu), relues quand la page change de version. */
    private fun piecesConnues(): List<MaisonEnGrand.Piece> {
        val c = plan.contenu
        if (c != contenuLu) {
            contenuLu = c
            pieces = MaisonEnGrand.lireContenu(c)
        }
        return pieces
    }

    private fun ouvrirGrand() {
        val t = SystemClock.elapsedRealtime()
        grandToucheLe = t
        serviceJusqua = 0L
        maisonGrand.ouvrir()
        plan.grand(true, MaisonEnGrand.TAILLE_PASTILLE, MaisonEnGrand.POLICE_ETIQUETTE)
        plan.voile(if (jour()) MaisonEnGrand.VOILE_JOUR else MaisonEnGrand.VOILE_SOIR)
        cadrer(MaisonEnGrand.ZONE_ENTIERE, t)
        // La santé quitte l'écran tout de suite, sans attendre la seconde suivante.
        majSante(dernier, t)
        rafraichir()
    }

    private fun cadrer(z: Disposition.Zone, t: Long) {
        zonePlan = z
        mouvementJusqua = t + MaisonEnGrand.DUREE_CADRAGE_MS
        plan.disposer(z, MaisonEnGrand.DUREE_CADRAGE_MS.toInt())
    }

    /** Ce que la page a désigné sous le doigt : une pastille, une pièce, ou le vide. */
    private fun designe(d: org.json.JSONObject?) {
        if (!maisonGrand.ouverte || d == null) return
        grandToucheLe = SystemClock.elapsedRealtime()
        when (d.optString("genre")) {
            "pastille" -> maisonGrand.pastille(d.optString("entite"))
            "piece" -> choisirPiece(d.optString("id"))
            else -> videGrand()
        }
    }

    private fun choisirPiece(id: String) {
        val p = piecesConnues().firstOrNull { it.id == id } ?: return
        val e = dernier
        if (injoignable()) {
            maisonGrand.dire("La maison ne répond plus : rien ne peut partir.")
            return
        }
        if (p.objets.isEmpty()) {
            maisonGrand.dire("Rien à régler ici.")
            return
        }
        if (MaisonEnGrand.protegee(p, MaisonEnGrand.index(e.lumieres, e.mediasPlan), e.quiParle())) {
            maisonGrand.dire("${p.nom} : pièce protégée, rien ne s'y règle.")
            return
        }
        if (maisonGrand.pieceChoisie?.id == p.id) return
        val t = SystemClock.elapsedRealtime()
        maisonGrand.montrerPiece(p)
        // La pièce d'abord (la page la vise), puis la zone : un seul mouvement vers la pièce cadrée à gauche.
        plan.choisir(p.id, MaisonEnGrand.DUREE_CADRAGE_MS.toInt())
        cadrer(MaisonEnGrand.ZONE_PIECE, t)
        majGrand(e, t)
    }

    /** Toucher le vide : de la pièce à la maison entière, puis de la maison à l'accueil. */
    private fun videGrand() {
        if (maisonGrand.pieceChoisie == null) {
            fermerGrand()
            return
        }
        val t = SystemClock.elapsedRealtime()
        maisonGrand.montrerPiece(null)
        plan.choisir(null, MaisonEnGrand.DUREE_CADRAGE_MS.toInt())
        cadrer(MaisonEnGrand.ZONE_ENTIERE, t)
        majGrand(dernier, t)
    }

    private fun fermerGrand() {
        if (!maisonGrand.ouverte) return
        maisonGrand.fermer()
        vue.removeCallbacks(revoirGrand)
        plan.choisir(null, MaisonEnGrand.DUREE_CADRAGE_MS.toInt())
        plan.grand(false)
        // La zone de l'accueil revient au prochain rafraîchissement, sans attendre la fin du cadrage en grand.
        mouvementJusqua = 0L
        vue.post { rafraichir() }
    }

    private fun injoignable(): Boolean = panneMaisonDepuis != null && retenuePanne.montre.isNotEmpty()

    /** États de la maison vers le panneau, les étiquettes de la vue entière et les pastilles de la pièce choisie. */
    private fun majGrand(e: Etat.Instantane, maintenant: Long) {
        val inj = injoignable()
        maisonGrand.maj(e.lumieres, e.mediasPlan, e.lecteurs, inj, panneMaisonDepuis, !jour(), e.bref, e.brefLe)
        // Maison injoignable, ou pièce devenue protégée pour la personne reconnue (l'occupant parti) : retour à la maison.
        val choisie = maisonGrand.pieceChoisie
        if (choisie != null && (inj || MaisonEnGrand.protegee(choisie, MaisonEnGrand.index(e.lumieres, e.mediasPlan), e.quiParle()))) {
            videGrand()
            return
        }
        plan.voile(if (jour()) MaisonEnGrand.VOILE_JOUR else MaisonEnGrand.VOILE_SOIR)
        if (maisonGrand.pieceChoisie == null) {
            plan.etiquettes(MaisonEnGrand.etiquettes(piecesConnues(), MaisonEnGrand.index(e.lumieres, e.mediasPlan), e.quiParle(), inj))
        } else {
            plan.pastilles(maisonGrand.pastilles())
        }
        // Une demande attend sa confirmation : revu toutes les 300 ms (échec à 5 s, surlignage de 400 ms).
        vue.removeCallbacks(revoirGrand)
        if (maisonGrand.enMouvement) vue.postDelayed(revoirGrand, MaisonEnGrand.REVUE_MS)
    }

    private val revoirGrand = Runnable { if (maisonGrand.ouverte) majGrand(dernier, SystemClock.elapsedRealtime()) }

    fun liberer() {
        maisonGrand.fermer()
        plan.liberer()
    }

    companion object {
        private val HEURE = SimpleDateFormat("HH:mm", Locale.FRANCE)
        const val DUREE_FONDU_MS = 300L
        const val DUREE_SERVICE_MS = 10_000L
        /** Un échec d'action se dit pendant 20 s, comme vivait la carte d'action. */
        const val DUREE_ECHEC_MS = 20_000L
        /** Commandes de musique en gris éteint 30 s après le dernier toucher. */
        const val DELAI_COMMANDES_MS = 30_000L
        /** Bloc Musique en pause, atténué, après l'arrêt (planche `AccueilMusiquePause`). */
        const val OPACITE_PAUSE = 0.55f
        /** L'orbe se referme en 0,4 s, une erreur le laisse rouge 1 s. */
        const val FERMETURE_ORBE_MS = 400L
        const val DUREE_ERREUR_MS = 1_000L
        /** En réflexion, l'orbe prend 85 % de sa taille. */
        const val TAILLE_REFLEXION = 0.85f
        /** Saturation des teintes de famille en retrait et en vivant (maquette `AccueilRegimes`). */
        const val SATURATION_RETRAIT = 0.4f
        const val SATURATION_VIVANT = 1.25f
        /** Tailles en pixels de maquette (revue du 22/10 : 44 au moins pour le canapé, 24 à 30 pour 1 à 2 m, 16 au moins). */
        const val TAILLE_ZONE = 46f
        const val TAILLE_PETITE = 26f
        const val TAILLE_CONSIGNE = 24f
        /** Colonne minimaliste (0.24.0) : température à 80 px, chiffres de santé à 64 px, en Big Shoulders. */
        const val TAILLE_TEMPERATURE = 80f
        /** Apparition du bloc santé en 0,4 s (relecture design). Son départ est immédiat. */
        const val DUREE_APPARITION_SANTE_MS = 400L
        /** Tant que la santé est montrée, la garde est revue à ce rythme (identité périmée sans nouvelle image). */
        const val REVUE_SANTE_MS = 300L
        const val LARGEUR_COLONNE = 480f
        /** Interligne CSS 1,12 : Android multiplie la hauteur naturelle d'Instrument Sans (1,22 em, table hhea). */
        const val INTERLIGNE = 1.12f / 1.22f
        /** Bloc Musique de la piste B, en bas de la moitié droite. */
        const val X_MUSIQUE = 640f
        const val Y_MUSIQUE = 448f
        /** Cadre carré de l'orbe : place pour le halo, les particules et l'onde sous lui. */
        const val COTE_ORBE = 600f
        /** Un jour sur deux (revue du 22/10). */
        const val DECALAGE_COLONNE = 48f
        val COULEUR_LLM: Int = Palette.voieLlm

        /** Libellé et teinte de chaque voie, partagés avec la carte de réponse du téléphone. */
        fun voie(cle: String): Pair<String, Int> = when (cle) {
            "securite" -> "Refus de sécurité" to Couleur.ROUGE
            "dictionnaire" -> "Dictionnaire" to Couleur.ACCENT_CLAIR
            "ha" -> "Home Assistant" to Couleur.VERT
            "claude" -> "Claude" to Couleur.ORANGE
            "llm" -> "LLM local" to COULEUR_LLM
            else -> ConfigMaison.NOM_ASSISTANT to Couleur.TEXTE_2
        }
    }
}

/** Délais de l'accueil. */
internal object EcranAmbiantDelais {
    /** Message bref de l'arbitre, quelques secondes. */
    const val BREF_MS = 4_000L
}

/** Saturation d'une couleur, clarté gardée (0.24.0, régimes de l'accueil). */
internal object Couleurs {
    /** Saturation HSL de [c] multipliée par [k] (bornée à 1), même teinte, même clarté, même opacité. */
    fun saturer(c: Int, k: Float): Int {
        val a = (c ushr 24) and 0xFF
        val r = ((c shr 16) and 0xFF) / 255f
        val g = ((c shr 8) and 0xFF) / 255f
        val b = (c and 0xFF) / 255f
        val mx = maxOf(r, g, b)
        val mn = minOf(r, g, b)
        val l = (mx + mn) / 2f
        val d = mx - mn
        if (d == 0f) return c
        val s = d / (1f - abs(2f * l - 1f))
        var h = when (mx) {
            r -> ((g - b) / d) % 6f
            g -> (b - r) / d + 2f
            else -> (r - g) / d + 4f
        } * 60f
        if (h < 0f) h += 360f
        val v = VueOrbe.hsl(h, (s * k).coerceIn(0f, 1f), l, a)
        return v
    }
}

/**
 * Pictogramme météo au trait fin (0.24.0, colonne minimaliste) : soleil, nuage, lune, pluie, neige, dessinés
 * sur une grille de 40 (maquette `ColonneMinimaliste`), trait de 1,5 dans la teinte météo, le nuage posé
 * devant le soleil masque ses rayons.
 */
internal class PictoTrait(ctx: Context) : View(ctx) {
    var picto = MeteoTexte.Picto.SOLEIL
        set(v) {
            if (field != v) {
                field = v
                invalidate()
            }
        }
    var couleur = Palette.meteo
        set(v) {
            if (field != v) {
                field = v
                invalidate()
            }
        }
    private val trait = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
        strokeJoin = Paint.Join.ROUND
    }
    private val masque = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.FILL
        xfermode = android.graphics.PorterDuffXfermode(android.graphics.PorterDuff.Mode.CLEAR)
    }

    init {
        importantForAccessibility = IMPORTANT_FOR_ACCESSIBILITY_NO
        setLayerType(LAYER_TYPE_HARDWARE, null)
    }

    override fun onDraw(c: Canvas) {
        val k = minOf(width, height) / 40f
        c.save()
        c.scale(k, k)
        trait.color = couleur
        trait.strokeWidth = 1.5f
        val nuage = when (picto) {
            MeteoTexte.Picto.SOLEIL -> { soleil(c, 20f, 20f); false }
            MeteoTexte.Picto.ECLAIRCIES -> { soleil(c, 15f, 14f); true }
            MeteoTexte.Picto.NUIT -> { c.drawPath(LUNE_SEULE, trait); false }
            MeteoTexte.Picto.NUIT_NUAGE -> { c.drawPath(LUNE, trait); true }
            else -> true
        }
        if (nuage) {
            // Le nuage efface ce qui est derrière lui (rayons, lune), puis se dessine au trait.
            c.drawPath(NUAGE, masque)
            c.drawPath(NUAGE, trait)
        }
        when (picto) {
            MeteoTexte.Picto.PLUIE -> for (x in listOf(15f, 21f, 27f)) c.drawLine(x, 35f, x - 1.5f, 38.5f, trait)
            MeteoTexte.Picto.NEIGE -> for (x in listOf(15f, 21f, 27f)) c.drawCircle(x, 37f, 0.9f, trait)
            else -> {}
        }
        c.restore()
    }

    private fun soleil(c: Canvas, cx: Float, cy: Float) {
        c.drawCircle(cx, cy, 6f, trait)
        val d = 10.5f
        val l = 2.5f
        for (a in listOf(-90f, -135f, -45f, 180f, 0f, 135f, 45f, 90f)) {
            val r = Math.toRadians(a.toDouble())
            val x = kotlin.math.cos(r).toFloat()
            val y = kotlin.math.sin(r).toFloat()
            c.drawLine(cx + x * d, cy + y * d, cx + x * (d + l), cy + y * (d + l), trait)
        }
    }

    private companion object {
        private fun p(d: String) = CheminSvg.chemin(CheminSvg.lire(d))
        val NUAGE by lazy { p("M13.5 33h15.5a6.5 6.5 0 0 0 .7-13 8.5 8.5 0 0 0-16.4 2.6A5.2 5.2 0 0 0 13.5 33Z") }
        val LUNE by lazy { p("M26 27.5a12 12 0 0 1-12.5-17 12 12 0 1 0 12.5 17Z") }
        val LUNE_SEULE by lazy { p("M28 27a12 12 0 0 1-12.5-17 12 12 0 1 0 12.5 17Z") }
    }
}
