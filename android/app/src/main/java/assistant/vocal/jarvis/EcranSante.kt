package assistant.vocal.jarvis

import android.content.Context
import android.graphics.Canvas
import android.graphics.Paint
import android.os.SystemClock
import android.text.TextPaint
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.widget.FrameLayout
import android.widget.LinearLayout
import org.json.JSONObject
import java.time.LocalDate
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * Panneau Santé de la tablette (0.21.0), quatre onglets et la vue d'un jour passé depuis la 0.22.0 (maquettes
 * relues `Sante`, `SanteTendances`, `SanteSeances`, `SanteRecords`, `SanteJour` et décisions de
 * `docs/maquettes/revue-sante-onglets.md`).
 *
 * En-tête commun (Santé, onglets soulignés en vert, « Se masque si quelqu'un arrive », Fermer), puis la ligne
 * de contexte : « Jeudi 22 octobre, données de 9 h 40 », ou, dans la vue d'un jour, « Retour », la date et les
 * chevrons jour précédent et suivant (l'onglet d'origine reste souligné). Navigation : un record d'un jour
 * ouvre ce jour, un record de séance l'ouvre dans Séances, un record de semaine ou de série ouvre Tendances
 * 7 jours calé sur ses dates. Dans les graphes, glisser lit une valeur et lever ouvre le jour.
 *
 * Données : Aujourd'hui lit `sante` (jour et nuit) et, avec la capacité `sante_historique` du serveur 0.20, la
 * liste des séances de 90 jours (bloc Sport, voir SanteHisto.semaine) et la dernière séance. Tendances,
 * Séances, Records et la vue Jour n'existent qu'avec cette capacité. Réponses gardées en mémoire par demande,
 * vidées à la fermeture et au changement de jour, jamais sur disque, jamais dans Etat ni dans le journal.
 *
 * Vie privée : ouvert seulement pour le propriétaire seul et sûr (Sante.Garde), fermé en fondu de 300 ms dès qu'une
 * autre personne apparaît, au bout de 2 min sans toucher, en pause, écran éteint, en AOD, par Retour et par
 * Fermer. FLAG_SECURE posé par l'écran principal tant que le panneau montre de vraies valeurs.
 */
internal class EcranSante(private val ctx: Context, private val surFermer: () -> Unit) {

    private val cadre = CadreMaquette(ctx)
    private var toucheLe = 0L

    val vue: FrameLayout = object : FrameLayout(ctx) {
        override fun dispatchTouchEvent(ev: MotionEvent): Boolean {
            // Pendant le fondu de masquage, le panneau ne répond plus à rien (revue de code 0.22.0).
            if (enFermeture) return true
            toucheLe = SystemClock.elapsedRealtime()
            return super.dispatchTouchEvent(ev)
        }
    }.apply {
        setBackgroundColor(Palette.fond)
        isClickable = true
        visibility = View.GONE
        addView(cadre, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
    }

    private fun texte(couleur: Int) = TexteFondu(ctx).apply {
        peinture.typeface = Polices.texte(ctx)
        peinture.color = couleur
    }

    // ------------------------------------------------------------ en-tête et contexte

    private val titre = texte(Palette.texte1).apply { texte = "Santé" }
    private val noms = listOf("Aujourd'hui", "Tendances", "Séances", "Records")
    private val onglets = noms.mapIndexed { i, nom ->
        Onglet(ctx, nom).apply {
            isClickable = true
            isFocusable = true
            setOnClickListener { choisirOnglet(i) }
        }
    }
    private val rangOnglets = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        for (o in onglets) addView(o)
    }
    private val mention = texte(Palette.texte3).apply { texte = "Se masque si quelqu'un arrive" }
    private val libelleFermer = texte(Palette.texte2).apply { texte = "Fermer" }
    private val fermer = FrameLayout(ctx).apply {
        isClickable = true
        isFocusable = true
        contentDescription = "Fermer la santé"
        setOnClickListener { surFermer() }
        addView(libelleFermer, FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.CENTER))
    }
    private val enTete = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        addView(titre)
        addView(rangOnglets)
        addView(View(ctx), LinearLayout.LayoutParams(0, 1, 1f))
        addView(mention)
        addView(fermer)
    }

    private val chevronRetour = Chevron(ctx, '<')
    private val libelleRetour = texte(Palette.texte2).apply { texte = "Retour" }
    private val retour = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        isClickable = true
        isFocusable = true
        contentDescription = "Retour"
        addView(chevronRetour)
        addView(libelleRetour)
        setOnClickListener { revenir() }
    }
    private val separateur = View(ctx).apply { setBackgroundColor(Palette.filet) }
    private val contexteTexte = texte(Palette.texte3)
    private val precedent = Chevron(ctx, '<').apply {
        isClickable = true
        contentDescription = "Jour précédent"
        setOnClickListener { jour?.let { ouvrirJour(it.minusDays(1), origine) } }
    }
    private val suivant = Chevron(ctx, '>').apply {
        isClickable = true
        contentDescription = "Jour suivant"
        setOnClickListener { jour?.let { j -> val d = j.plusDays(1); if (!d.isBefore(aujourdhui())) choisirOnglet(0) else ouvrirJour(d, origine) } }
    }
    private val contexte = LinearLayout(ctx).apply {
        orientation = LinearLayout.HORIZONTAL
        gravity = Gravity.CENTER_VERTICAL
        addView(retour)
        addView(separateur)
        addView(contexteTexte)
        addView(precedent)
        addView(suivant)
    }

    // ------------------------------------------------------------ onglets

    private val aujourdhuiVue = OngletAujourdhui(ctx)
    private val tendancesVue = OngletTendances(ctx)
    private val seancesVue = OngletSeances(ctx)
    private val recordsVue = OngletRecords(ctx)
    private val jourVue = VueJour(ctx)
    private val vues: List<VueSante> = listOf(aujourdhuiVue, tendancesVue, seancesVue, recordsVue, jourVue)
    private val attente = texte(Palette.texte3)

    init {
        val n = Float.NaN
        val P = CadreMaquette::Place
        for (v in vues) cadre.addView(v.vue, P(0f, 0f, 0f, 0f, n, n))
        cadre.addView(enTete, P(72f, 22f, 66f, n, n, 56f))
        cadre.addView(contexte, P(72f, 80f, 72f, n, n, 44f))
        cadre.addView(attente, P(72f, 140f, n, n, 1136f, n))
        cadre.surEchelle = { appliquer(it) }
        appliquer(cadre.echelle)
        aujourdhuiVue.surJour = { ouvrirJour(it, 0) }
        aujourdhuiVue.surSeance = { id -> if (historique()) { seanceId = id; filtre = "tous"; seancesAu = null; choisirOnglet(2, garder = true) } }
        tendancesVue.surJours = { periodeJours = it; calage = null; periodeAu = null; periodeRepli = null; afficher() }
        tendancesVue.surJour = { ouvrirJour(it, 1) }
        seancesVue.surFiltre = { filtre = it; seanceId = null; seancesAu = null; afficher() }
        seancesVue.surSeance = { choisirSeance(it) }
        recordsVue.surRecord = { r -> ouvrirRecord(r) }
        jourVue.surJour = { ouvrirJour(it, origine) }
        jourVue.surSeance = { id ->
            if (id != null) {
                seanceId = id
                filtre = "tous"
                // Séance d'un jour de plus de 30 jours : la liste est calée sur ce jour.
                seancesAu = jour?.takeIf { java.time.temporal.ChronoUnit.DAYS.between(it, aujourdhui()) >= 30 }
                choisirOnglet(2, garder = true)
            }
        }
    }

    private fun appliquer(s: Float) {
        titre.taille(26f * s)
        (rangOnglets.layoutParams as? LinearLayout.LayoutParams ?: LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT))
            .also { it.marginStart = (28f * s).toInt(); rangOnglets.layoutParams = it }
        for ((i, o) in onglets.withIndex()) {
            o.echelle = s
            (o.layoutParams as? LinearLayout.LayoutParams ?: LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT))
                .also { it.marginStart = if (i == 0) 0 else (4f * s).toInt(); o.layoutParams = it }
        }
        mention.taille(16f * s)
        libelleFermer.taille(18f * s)
        fermer.minimumWidth = max((60 * s).toInt(), Decor.dp(ctx, 48f))
        fermer.minimumHeight = max((48 * s).toInt(), Decor.dp(ctx, 48f))
        (fermer.layoutParams as? LinearLayout.LayoutParams ?: LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT))
            .also { it.marginStart = (22f * s).toInt(); fermer.layoutParams = it }
        val c44 = max((44f * s).roundToInt(), Decor.dp(ctx, 44f))
        for (c in listOf(chevronRetour, precedent, suivant)) {
            c.echelle = s
            c.layoutParams = LinearLayout.LayoutParams((if (c === chevronRetour) 26f * s else 44f * s).roundToInt(), c44)
        }
        (precedent.layoutParams as LinearLayout.LayoutParams).marginStart = (8f * s).roundToInt()
        libelleRetour.taille(17f * s)
        libelleRetour.layoutParams = LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { marginEnd = (12f * s).roundToInt() }
        separateur.layoutParams = LinearLayout.LayoutParams(max(1, (s * 0.5f).roundToInt()), (22f * s).roundToInt()).apply { marginEnd = (16f * s).roundToInt() }
        contexteTexte.taille(17f * s)
        attente.taille(18f * s)
        for (v in vues) v.echelle(s)
    }

    // ------------------------------------------------------------ état

    val ouvert: Boolean get() = vue.visibility == View.VISIBLE && !enFermeture
    private var enFermeture = false
    private var tour = 0
    private var demonstration = false
    /** Démonstration traitée comme de vraies valeurs pour la fenêtre (essai de FLAG_SECURE, appli de débogage). */
    private var demoProtegee = false

    /**
     * De vraies valeurs de santé peuvent être à l'écran (pas une démonstration) : la fenêtre doit être protégée.
     * Tant que la vue est visible, fondu de masquage compris. L'écran principal ne lève le drapeau qu'après
     * une image dessinée sans elle.
     */
    val reel: Boolean get() = vue.visibility == View.VISIBLE && (!demonstration || demoProtegee)

    /** Appelé quand [reel] peut avoir changé hors des appels de l'écran principal (fin du fondu). */
    var surSecurite: () -> Unit = {}

    private var onglet = 0
    private var jour: LocalDate? = null
    private var origine = 0
    private var periodeJours = 30
    /** Dates d'un record de semaine ou de série ouvert dans Tendances, mises en avant. */
    private var calage: Pair<LocalDate, LocalDate>? = null
    /** Fin de la période de Tendances calée sur un record (serveur 0.20.2), null : finie aujourd'hui. */
    private var periodeAu: LocalDate? = null
    /** Période de repli si le serveur ne cale pas sur [periodeAu] : la plus courte finie aujourd'hui qui contient le record. */
    private var periodeRepli: Int? = null
    private var filtre = "tous"
    private var seanceId: String? = null
    /** Fin de la liste de Séances pour un record de séance de plus de 30 jours (serveur 0.20.2). */
    private var seancesAu: LocalDate? = null
    /** Premier jour de l'historique (réponses du serveur), pour ne pas proposer de jour d'avant. */
    private var premierJour: LocalDate? = null
    /** Chaque affichage a son numéro : une réponse arrivée après un changement d'onglet ou de jour est ignorée. */
    private var generation = 0
    /** Dernière liste de Séances montrée, pour changer de séance sans la redemander ni la reconstruire. */
    private var listeSeances: SanteHisto.ListeSeances? = null

    /** Réponses gardées le temps de l'ouverture, par demande, et le jour où elles ont été lues. */
    private val cache = HashMap<String, JSONObject>()
    private var cacheJour: LocalDate = SanteHisto.aujourdhui()

    /** Aujourd'hui à Paris, comme le serveur, et non au fuseau de l'appareil. */
    private fun aujourdhui(): LocalDate = SanteHisto.aujourdhui()

    private fun historique(): Boolean = demonstration || Etat.historiqueSante()

    // ------------------------------------------------------------ cycle

    /** Ouvre le panneau sur Aujourd'hui si le propriétaire est seul devant la tablette. */
    fun ouvrir(): Boolean {
        if (!Sante.proprietaireSeul(Etat.courant, SystemClock.elapsedRealtime())) return false
        demarrer(demo = false, protegee = false)
        choisirOnglet(0)
        return true
    }

    /**
     * Démonstration de l'appli de débogage : valeurs fictives (SanteDemo), sans le serveur ni la vision, sur
     * l'onglet [nom] (aujourdhui, tendances, seances, records, jour). Une réponse réelle encore attendue ne la
     * remplit jamais.
     */
    fun demo(protegee: Boolean = false, nom: String = "aujourdhui") {
        demarrer(demo = true, protegee = protegee)
        when (nom) {
            "tendances" -> choisirOnglet(1)
            "seances" -> choisirOnglet(2)
            "records" -> choisirOnglet(3)
            "jour" -> ouvrirJour(SanteDemo.jourActif(aujourdhui()), 3)
            else -> choisirOnglet(0)
        }
    }

    private fun demarrer(demo: Boolean, protegee: Boolean) {
        tour++
        enFermeture = false
        demonstration = demo
        demoProtegee = protegee
        cache.clear()
        cacheJour = aujourdhui()
        vue.animate().cancel()
        vue.alpha = 1f
        vue.visibility = View.VISIBLE
        toucheLe = SystemClock.elapsedRealtime()
        oublierNavigation()
        vider()
    }

    private fun oublierNavigation() {
        onglet = 0
        jour = null
        origine = 0
        periodeJours = 30
        calage = null
        periodeAu = null
        periodeRepli = null
        filtre = "tous"
        seanceId = null
        seancesAu = null
        premierJour = null
        listeSeances = null
    }

    /** Fermeture immédiate (Fermer, Retour, AOD, pause) : tout est oublié. */
    fun fermer() {
        tour++
        generation++
        vue.animate().cancel()
        for (v in vues) v.relacher()
        vue.visibility = View.GONE
        vue.alpha = 1f
        enFermeture = false
        demonstration = false
        demoProtegee = false
        cache.clear()
        oublierNavigation()
        vider()
    }

    /** Bouton Retour d'Android : dans la vue d'un jour, retour à l'onglet d'origine. Vrai s'il est pris. */
    fun retour(): Boolean {
        if (!ouvert || jour == null) return false
        revenir()
        return true
    }

    private fun vider() {
        for (v in vues) v.vider()
        attente.texte = ""
        contexteTexte.texte = ""
    }

    /** Chaque état : dès que le propriétaire n'est plus seul et sûr, fondu de sortie de 300 ms et retour à l'accueil. */
    fun maj(e: Etat.Instantane) {
        if (!ouvert || demonstration || Sante.proprietaireSeul(e, SystemClock.elapsedRealtime())) return
        masquer()
    }

    /**
     * Fondu de sortie : tout est oublié dès le début (mémoire, lectures au doigt, réponses en attente), le
     * panneau ne répond plus aux touchers, et la fenêtre reste protégée jusqu'à la fin du fondu et au-delà.
     */
    private fun masquer() {
        if (enFermeture) return
        enFermeture = true
        tour++
        generation++
        cache.clear()
        for (v in vues) v.relacher()
        vue.animate().cancel()
        vue.animate().alpha(0f).setDuration(FONDU_MS).withEndAction {
            vue.visibility = View.GONE
            vue.alpha = 1f
            enFermeture = false
            oublierNavigation()
            vider()
            surFermer()
            surSecurite()
        }.start()
    }

    /** Toutes les secondes : retour à l'accueil au bout de 2 min sans toucher, masquage si l'image du propriétaire est trop vieille. */
    fun tic() {
        if (!ouvert) return
        if (SystemClock.elapsedRealtime() - toucheLe > FERMETURE_MS) {
            surFermer()
            return
        }
        if (cacheJour != aujourdhui()) {
            // Changement de jour : tout est relu.
            cache.clear()
            cacheJour = aujourdhui()
            afficher()
        }
        maj(Etat.courant)
    }

    // ------------------------------------------------------------ navigation

    /** Onglet [i] choisi dans l'en-tête, ou ouvert par une navigation qui a déjà réglé son état ([garder]). */
    private fun choisirOnglet(i: Int, garder: Boolean = false) {
        if (i > 0 && !historique()) return
        if (!garder) {
            if (i == 1) {
                calage = null
                periodeAu = null
                periodeRepli = null
            }
            if (i == 2 && onglet != 2) {
                seanceId = null
                seancesAu = null
            }
        }
        onglet = i
        jour = null
        afficher()
    }

    private fun ouvrirJour(d: LocalDate, depuis: Int) {
        if (!historique()) return
        if (!d.isBefore(aujourdhui())) {
            choisirOnglet(0)
            return
        }
        premierJour?.let { if (d.isBefore(it)) return }
        origine = depuis
        jour = d
        afficher()
    }

    private fun revenir() {
        if (jour == null) return
        jour = null
        onglet = origine
        afficher()
    }

    /**
     * Record touché : une séance s'ouvre dans Séances (liste calée sur sa date si elle a plus de 30 jours), un
     * jour dans la vue Jour, une semaine ou une série dans Tendances sur la plus courte période qui la tient,
     * finie au dernier jour du record (`au`, serveur 0.20.2). Repli sans `au` : la plus courte période finie
     * aujourd'hui qui le contient, ses dates mises en avant, et au-delà d'un an la vue de son premier jour.
     */
    private fun ouvrirRecord(r: SanteHisto.Record) {
        val du = r.du ?: r.lundi
        val au = r.au ?: r.lundi?.plusDays(6)
        val aujourdhui = aujourdhui()
        when {
            r.seanceId != null -> {
                seanceId = r.seanceId
                filtre = "tous"
                seancesAu = r.date?.takeIf { java.time.temporal.ChronoUnit.DAYS.between(it, aujourdhui) >= 30 }
                choisirOnglet(2, garder = true)
            }
            du != null && au != null -> {
                val repli = if (java.time.temporal.ChronoUnit.DAYS.between(du, aujourdhui) < 7) 7 else SanteHisto.periodeCouvrant(du, aujourdhui)
                val n = SanteHisto.periodeTenant(java.time.temporal.ChronoUnit.DAYS.between(du, au) + 1)
                if (n == null && repli == null) {
                    ouvrirJour(du, 3)
                    return
                }
                calage = du to au
                periodeAu = au.takeIf { n != null && it.isBefore(aujourdhui) }
                periodeJours = if (periodeAu != null) n!! else repli ?: n!!
                periodeRepli = repli
                choisirOnglet(1, garder = true)
            }
            r.date != null -> ouvrirJour(r.date, 3)
        }
    }

    // ------------------------------------------------------------ demandes

    /**
     * Demande au serveur (ou à la démonstration), avec la mémoire de l'ouverture. Sans réponse, nouvel essai
     * automatique (trois en tout), « Lecture en cours » restant affiché. Sur une erreur du serveur, aucun
     * nouvel essai : [echec] si l'appelant a un repli, sinon « Santé indisponible pour l'instant ». Une réponse
     * n'est montrée que s'il est toujours seul, jamais dans une autre ouverture ([tour]) ni après un
     * changement d'onglet ou de jour ([generation]) : elle est alors seulement gardée en mémoire.
     */
    private fun demander(corps: JSONObject, echec: (() -> Unit)? = null, suite: (JSONObject) -> Unit) {
        if (!ouvert) return
        val cle = corps.toString()
        cache[cle]?.let { suite(it); return }
        val t = tour
        val g = generation
        if (demonstration) {
            val r = SanteDemo.reponse(corps, aujourdhui())
            vue.post {
                if (t != tour || !ouvert) return@post
                if (r.has("erreur")) {
                    if (g == generation) refuse(echec)
                    return@post
                }
                cache[cle] = r
                if (g == generation) suite(r)
            }
            return
        }
        essai(corps, cle, t, g, 1, echec, suite)
    }

    private fun refuse(echec: (() -> Unit)?) {
        if (echec != null) echec()
        else if (attente.texte.isNotEmpty()) attente.texte = "Santé indisponible pour l'instant"
    }

    private fun essai(corps: JSONObject, cle: String, t: Int, g: Int, n: Int, echec: (() -> Unit)?, suite: (JSONObject) -> Unit) {
        val rendu: (JSONObject?) -> Unit = rendu@{ r ->
            if (t != tour || !ouvert || demonstration) return@rendu
            if (!Sante.proprietaireSeul(Etat.courant, SystemClock.elapsedRealtime())) {
                masquer()
                return@rendu
            }
            if (r == null) {
                // Réponse absente (connexion, délai) : seul cas d'un nouvel essai.
                if (g != generation) return@rendu
                if (n < ESSAIS) vue.postDelayed({ if (t == tour && g == generation && ouvert) essai(corps, cle, t, g, n + 1, echec, suite) }, RELANCE_MS)
                else refuse(null)
                return@rendu
            }
            if (r.has("erreur") || !r.has("donnees")) {
                if (g == generation) refuse(echec)
                return@rendu
            }
            cache[cle] = r
            SanteHisto.entete(SanteHisto.donnees(r)).premierJour?.let { premierJour = it }
            if (g == generation) suite(r)
        }
        if (corps.optString("type") == "sante") {
            val a = Etat.actionSante
            if (a == null) rendu(null) else a(rendu)
        } else {
            val a = Etat.actionSanteHistorique
            if (a == null) rendu(null) else a(corps, rendu)
        }
    }

    /**
     * Fenêtre passée (`au`, serveur 0.20.2) : [corpsAu] doit revenir finie le jour [au] ([fin] lit sa fin). Sur
     * une erreur, ou si le serveur l'ignore et répond pour aujourd'hui, la demande de [repli] (s'il y en a une).
     */
    private fun demanderAu(corpsAu: JSONObject, au: LocalDate, fin: (JSONObject) -> LocalDate?, repli: JSONObject?, suite: (JSONObject) -> Unit) {
        val secours: () -> Unit = { repli?.let { demander(it, suite = suite) } }
        demander(corpsAu, echec = secours) { r -> if (fin(r) == au) suite(r) else secours() }
    }

    private fun corps(type: String) = JSONObject().put("type", type)

    private fun finPeriode(r: JSONObject): LocalDate? = SanteHisto.date(SanteHisto.donnees(r), "au")

    // ------------------------------------------------------------ affichage

    private fun afficher() {
        if (!ouvert) return
        generation++
        val aujourdhui = aujourdhui()
        for ((i, o) in onglets.withIndex()) {
            o.actif = i == (if (jour != null) origine else onglet)
            o.disponible = i == 0 || historique()
            o.contentDescription = noms[i] + when {
                o.actif -> ", ouvert"
                !o.disponible -> ", indisponible"
                else -> ""
            }
        }
        val j = jour
        for (v in listOf(retour, separateur, precedent, suivant)) v.visibility = if (j != null) View.VISIBLE else View.GONE
        if (j != null) {
            val premier = premierJour
            precedent.isEnabled = premier == null || !j.minusDays(1).isBefore(premier)
            precedent.invalidate()
        }
        contexteTexte.couleur(if (j != null) Palette.texte1 else Palette.texte3)
        contexteTexte.texte = if (j != null) SanteHisto.dateLongue(j, aujourdhui) else ""
        val visible = if (j != null) jourVue else vues[onglet]
        for (v in vues) v.vue.visibility = if (v === visible) View.VISIBLE else View.GONE
        visible.vider()
        attente.texte = "Lecture en cours"
        fun pret(entete: SanteHisto.Entete?) {
            attente.texte = ""
            if (j == null && entete != null) contexteTexte.texte = SanteHisto.contexte(entete, aujourdhui)
        }
        when {
            j != null -> afficherJour(j, aujourdhui, ::pret)
            onglet == 0 -> {
                demander(corps("sante")) { r ->
                    val d = SanteDetail.lire(r)
                    pret(SanteHisto.entete(SanteHisto.donnees(r)))
                    aujourdhuiVue.montrer(d, null, null, aujourdhui)
                    if (!historique()) return@demander
                    var semaine: SanteHisto.Semaine? = null
                    var seance: SanteHisto.SeanceComplete? = null
                    demander(corps("sante_seances").put("jours", 90).put("sport", "tous")) { l ->
                        val liste = SanteHisto.seances(l) ?: return@demander
                        semaine = SanteHisto.semaine(liste, aujourdhui)
                        aujourdhuiVue.montrer(d, semaine, seance, aujourdhui)
                        liste.seances.firstOrNull()?.let { x ->
                            demander(corps("sante_seance").put("seance_id", x.id)) { s ->
                                seance = SanteHisto.seance(s)
                                aujourdhuiVue.montrer(d, semaine, seance, aujourdhui)
                            }
                        }
                    }
                }
            }
            onglet == 1 -> {
                val n = periodeJours
                val c = calage
                val au = periodeAu
                val montrer: (JSONObject) -> Unit = { r ->
                    val p = SanteHisto.periode(r)
                    pret(p?.entete)
                    // Période exactement celle du record : rien à mettre en avant, sinon ses dates en vert.
                    val cc = c?.takeIf { p?.du != it.first || p.au != it.second }
                    tendancesVue.montrer(p, p?.jours?.takeIf { it > 0 } ?: n, aujourdhui, cc)
                }
                if (au == null) demander(corps("sante_periode").put("jours", n), suite = montrer)
                else demanderAu(
                    corps("sante_periode").put("jours", n).put("au", au.toString()), au, ::finPeriode,
                    periodeRepli?.let { corps("sante_periode").put("jours", it) }, montrer,
                )
            }
            onglet == 2 -> {
                val au = seancesAu
                val base = corps("sante_seances").put("jours", 30).put("sport", filtre)
                val montrer: (JSONObject) -> Unit = { r ->
                    val l = SanteHisto.seances(r)
                    listeSeances = l
                    pret(l?.entete)
                    val id = seanceId ?: l?.seances?.firstOrNull()?.id
                    seanceId = id
                    seancesVue.montrer(l, filtre, null, id, aujourdhui)
                    if (id != null) demander(corps("sante_seance").put("seance_id", id)) { s ->
                        seancesVue.selectionner(id, SanteHisto.seance(s))
                    }
                }
                if (au == null) demander(base, suite = montrer)
                else demanderAu(JSONObject(base.toString()).put("au", au.toString()), au, ::finPeriode, base, montrer)
            }
            else -> {
                demander(corps("sante_records")) { r ->
                    val rec = SanteHisto.records(r)
                    pret(rec?.entete)
                    recordsVue.montrer(rec, aujourdhui)
                }
            }
        }
    }

    /**
     * Vue d'un jour passé : le jour, puis ses 7 jours (pas et nuits) et son bloc Sport par des fenêtres finies ce
     * jour-là (`au`, serveur 0.20.2 : période de 7 jours, séances de 90 jours, le serveur ne prenant que 7, 30,
     * 90 ou 365 jours). Repli sans `au` : la plus courte période finie aujourd'hui qui les contient, et pas de
     * bloc Sport sur une liste tronquée qui ne les couvre pas (SanteHisto.semaine).
     */
    private fun afficherJour(j: LocalDate, aujourdhui: LocalDate, pret: (SanteHisto.Entete?) -> Unit) {
        demander(corps("sante_jour").put("date", j.toString())) { r ->
            val d = SanteHisto.jour(r)
            pret(d?.entete)
            d?.entete?.premierJour?.let { premier ->
                precedent.isEnabled = !j.minusDays(1).isBefore(premier)
                precedent.invalidate()
            }
            var points: List<SanteHisto.Point> = emptyList()
            var semaine: SanteHisto.Semaine? = null
            var seance: SanteHisto.SeanceComplete? = null
            var records: SanteHisto.Records? = null
            fun remplir() = jourVue.montrer(d, points, semaine, seance, records, aujourdhui)
            remplir()
            val repliPeriode = SanteHisto.periodeCouvrant(j.minusDays(6), aujourdhui)?.let { corps("sante_periode").put("jours", it) }
            demanderAu(corps("sante_periode").put("jours", 7).put("au", j.toString()), j, ::finPeriode, repliPeriode) { p ->
                points = SanteHisto.periode(p)?.serie ?: emptyList()
                remplir()
            }
            val repliSport = SanteHisto.periodeCouvrant(j.minusDays(6), aujourdhui)?.let {
                val n = SanteHisto.periodeCouvrant(j.minusDays(6L + 7L * SanteHisto.SEMAINES_AVANT), aujourdhui) ?: 365
                corps("sante_seances").put("jours", n).put("sport", "tous")
            }
            demanderAu(corps("sante_seances").put("jours", 90).put("sport", "tous").put("au", j.toString()), j, ::finPeriode, repliSport) { l ->
                semaine = SanteHisto.seances(l)?.let { SanteHisto.semaine(it, j) }
                remplir()
            }
            d?.seances?.firstOrNull()?.let { x ->
                demander(corps("sante_seance").put("seance_id", x.id)) { s ->
                    seance = SanteHisto.seance(s)
                    remplir()
                }
            }
            demander(corps("sante_records")) { rr ->
                records = SanteHisto.records(rr)
                remplir()
            }
        }
    }

    /** Autre séance touchée dans la liste : seul le détail est demandé, la liste n'est pas reconstruite. */
    private fun choisirSeance(id: String) {
        if (!ouvert || onglet != 2 || jour != null) return
        seanceId = id
        generation++
        seancesVue.selectionner(id, null)
        demander(corps("sante_seance").put("seance_id", id)) { s -> seancesVue.selectionner(id, SanteHisto.seance(s)) }
    }

    companion object {
        /** Retour à l'accueil après 2 min sans toucher (revue des onglets). */
        const val FERMETURE_MS = 120_000L
        /** Sortie en moins de 0,5 s quand quelqu'un d'autre apparaît. */
        const val FONDU_MS = 300L
        /** Essais de lecture, et attente entre deux (0.21.1). */
        const val ESSAIS = 3
        const val RELANCE_MS = 2_000L
    }
}

/** Onglet de l'en-tête de la santé : 19 px, 48 px de haut, souligné en vert s'il est ouvert, éteint s'il est indisponible. */
internal class Onglet(ctx: Context, private val nom: String) : View(ctx) {
    var echelle = CadreMaquette.estimer(ctx)
        set(v) {
            field = v
            requestLayout()
            invalidate()
        }
    var actif = false
        set(v) {
            field = v
            invalidate()
        }
    var disponible = true
        set(v) {
            field = v
            isEnabled = v
            invalidate()
        }
    private val p = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { typeface = Polices.texte(ctx) }
    private val trait = Paint()
    private val fm = Paint.FontMetrics()

    override fun onMeasure(l: Int, h: Int) {
        p.textSize = 19f * echelle
        val w = p.measureText(nom) + 28f * echelle
        setMeasuredDimension(w.roundToInt(), max((48f * echelle).roundToInt(), Decor.dp(context, 48f)))
    }

    override fun onDraw(c: Canvas) {
        p.textSize = 19f * echelle
        p.color = when {
            actif -> Palette.texte1
            disponible -> Palette.texte3
            else -> Palette.filet
        }
        p.getFontMetrics(fm)
        c.drawText(nom, 14f * echelle, height / 2f - (fm.ascent + fm.descent) / 2f, p)
        if (actif) {
            trait.color = Palette.sante
            c.drawRect(0f, height - 2f * echelle, width.toFloat(), height.toFloat(), trait)
        }
    }
}
