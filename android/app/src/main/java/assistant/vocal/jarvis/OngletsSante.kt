package assistant.vocal.jarvis

import android.content.Context
import android.graphics.Typeface
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.TextPaint
import android.text.style.AbsoluteSizeSpan
import android.text.style.ForegroundColorSpan
import android.text.style.MetricAffectingSpan
import android.view.Gravity
import android.view.View
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import java.time.LocalDate
import kotlin.math.max
import kotlin.math.roundToInt

/**
 * Onglets du panneau Santé (0.22.0, maquettes relues `Sante`, `SanteTendances`, `SanteSeances`, `SanteRecords`,
 * `SanteJour`) : chaque onglet est une vue indépendante placée en pixels de maquette sous l'en-tête commun.
 * Les données arrivent toutes prêtes (SanteHisto, SanteDetail), demandées et gardées en mémoire par EcranSante.
 */

/** Police d'une partie de texte (le chiffre en Big Shoulders, l'unité en Instrument Sans). */
internal class PoliceSpan(private val police: Typeface) : MetricAffectingSpan() {
    override fun updateDrawState(tp: TextPaint) {
        tp.typeface = police
    }

    override fun updateMeasureState(tp: TextPaint) {
        tp.typeface = police
    }
}

/** Morceaux d'un texte composé : texte, taille (px réels), couleur, police. */
internal class Morceaux {
    val sb = SpannableStringBuilder()
    fun ajouter(t: String, px: Float, couleur: Int, police: Typeface? = null): Morceaux {
        if (t.isEmpty()) return this
        val d = sb.length
        sb.append(t)
        sb.setSpan(AbsoluteSizeSpan(px.roundToInt()), d, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        sb.setSpan(ForegroundColorSpan(couleur), d, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        if (police != null) sb.setSpan(PoliceSpan(police), d, sb.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        return this
    }
}

/** Espace insécable (U+00A0), écrite par son code : seulement à l'affichage des nombres. */
private val INSECABLE = 0x00A0.toChar()

/** Nombre ou valeur avec unité qui ne se coupe jamais (white-space: nowrap). */
internal fun ns(t: String): String = t.replace(' ', INSECABLE)

/** Base des onglets : placement en pixels de maquette et tailles de texte à l'échelle. */
internal abstract class VueSante(protected val ctx: Context) {
    val vue = FrameLayout(ctx).apply { clipChildren = false }
    protected var s = CadreMaquette.estimer(ctx)
    private class Place(val v: View, val x: Float, val y: Float, val l: Float, val h: Float)
    private val places = ArrayList<Place>()
    private val textes = ArrayList<Pair<TexteFondu, Float>>()
    private val graphes = ArrayList<GrapheSante>()

    /** Vue placée en ([x], [y]) de largeur [l] et hauteur [h] (0 : selon son contenu). */
    protected fun <T : View> place(v: T, x: Float, y: Float, l: Float = 0f, h: Float = 0f): T {
        places.add(Place(v, x, y, l, h))
        vue.addView(v)
        if (v is GrapheSante) graphes.add(v)
        return v
    }

    /** Texte de [px] pixels de maquette, en Instrument Sans, ou en chiffres Big Shoulders ([chiffres] 300 ou 400). */
    protected fun texte(couleur: Int, px: Float, lignes: Int = 1, chiffres: Int = 0, interligne: Float = 1f): TexteFondu =
        TexteFondu(ctx).apply {
            peinture.typeface = if (chiffres > 0) Polices.chiffres(ctx, chiffres) else Polices.texte(ctx)
            peinture.color = couleur
            maxLignes = lignes
            this.interligne = interligne
            textes.add(this to px)
        }

    protected fun police(poids: Int): Typeface = Polices.chiffres(ctx, poids)
    protected fun policeTexte(): Typeface = Polices.texte(ctx)

    fun echelle(e: Float) {
        s = e
        for (p in places) {
            p.v.layoutParams = FrameLayout.LayoutParams(
                if (p.l > 0f) (p.l * e).roundToInt() else FrameLayout.LayoutParams.WRAP_CONTENT,
                if (p.h > 0f) max(1, (p.h * e).roundToInt()) else FrameLayout.LayoutParams.WRAP_CONTENT,
            ).apply {
                leftMargin = (p.x * e).roundToInt()
                topMargin = (p.y * e).roundToInt()
            }
        }
        for ((t, px) in textes) t.taille(px * e)
        for (g in graphes) g.echelle = e
        tailles(e)
    }

    protected open fun tailles(e: Float) {}

    /** Oublie la lecture au doigt de chaque graphe (fondu de masquage). */
    fun relacher() {
        for (g in graphes) g.relacher()
    }

    /** Ligne fine de séparation. */
    protected fun filet(x: Float, y: Float, l: Float) {
        place(View(ctx).apply { setBackgroundColor(Palette.filet) }, x, y, l, 1f)
    }

    /** Oublie tout ce qui est affiché (fermeture, autre jour). */
    abstract fun vider()

    protected fun montre(v: View, oui: Boolean) {
        v.visibility = if (oui) View.VISIBLE else View.GONE
    }
}

/** « Sport » : séances et durée sur une ligne, charge dessous (Aujourd'hui, vue Jour). */
private fun ligneSeances(m: Morceaux, n: Int, minutes: Int, s: Float, grand: Typeface, texte: Typeface) {
    m.ajouter(n.toString(), 64f * s, Palette.sante, grand)
    m.ajouter(" " + (if (n > 1) "séances" else "séance") + "   ", 28f * s, Palette.texte2, texte)
    m.ajouter(ns(SanteHisto.duree(minutes)), 64f * s, Palette.sante, grand)
}

// ================================================================ Aujourd'hui et vue Jour

/**
 * Gabarit commun d'Aujourd'hui et de la vue d'un jour passé (maquettes `Sante` et `SanteJour`) : sommeil et
 * stades, pas, sept jours (ou hypnogramme), cœur, sport des 7 jours, séance. Quatre blocs lus de loin,
 * chiffres de 88 et 64 px, unités accolées à 28 px.
 */
internal open class GabaritJour(ctx: Context) : VueSante(ctx) {
    var surJour: (LocalDate) -> Unit = {}
    var surSeance: (String?) -> Unit = {}

    protected val titreSommeil = place(texte(Palette.texte3, 18f), 72f, 140f, 280f)
    protected val sommeil = place(texte(Palette.sante, 88f, chiffres = 300), 72f, 160f, 300f)
    protected val stades = place(StadesLegende(ctx), 364f, 180f, 260f)
    protected val lit = place(texte(Palette.texte2, 19f), 72f, 262f, 552f)
    protected val oxygene = place(texte(Palette.texte3, 17f), 72f, 290f, 552f)
    protected val titrePas = place(texte(Palette.texte3, 18f), 656f, 140f, 552f)
    protected val pas = place(texte(Palette.sante, 88f), 656f, 160f, 552f)
    protected val lignePas = place(texte(Palette.texte2, 19f), 656f, 262f, 552f)
    protected val notePas = place(texte(Palette.texte3, 17f), 656f, 290f, 552f)
    protected val titreGaucheGraphe = place(texte(Palette.texte2, 17f), 72f, 334f, 552f)
    protected val titreDroitGraphe = place(texte(Palette.texte2, 17f), 656f, 334f, 552f)
    protected val graphePas = place(BarresSante(ctx), 656f, 362f, 552f)
    init {
        filet(72f, 524f, 1136f)
    }
    protected val titreCoeur = place(texte(Palette.texte3, 18f).apply { texte = "Cœur" }, 72f, 544f, 260f)
    protected val coeur = place(texte(Palette.sante, 88f), 72f, 564f, 280f)
    protected val coeurLigne = place(texte(Palette.texte2, 19f), 72f, 662f, 280f)
    protected val coeurLigne2 = place(texte(Palette.texte3, 17f, 2, interligne = 1.35f / 1.22f), 72f, 690f, 270f)
    protected val titreSport = place(texte(Palette.texte3, 18f), 364f, 544f, 280f)
    protected val sport1 = place(texte(Palette.sante, 64f), 364f, 566f, 290f)
    protected val sport2 = place(texte(Palette.sante, 64f), 364f, 636f, 290f)
    protected val sportAvant = place(texte(Palette.texte3, 16f), 364f, 716f, 290f)
    protected val titreSeance = place(texte(Palette.texte3, 16f), 656f, 544f, 552f)
    protected val ligneSeance = place(texte(Palette.texte1, 20f), 656f, 566f, 552f)
    protected val courbe = place(CourbeZones(ctx).apply { compact = true }, 656f, 608f, 552f, 140f)
    private var seanceId: String? = null

    init {
        graphePas.gabarit = BarresSante.Gabarit.SEPT
        for (v in listOf(titreSeance, ligneSeance, courbe)) {
            v.isClickable = true
            v.setOnClickListener { surSeance(seanceId) }
        }
        courbe.contentDescription = "Courbe du cœur de la séance, toucher pour l'ouvrir dans Séances"
    }

    /** « 4 210 » en 88 px et « pas » en 28 px, accolés. */
    protected fun grand(valeur: String, unite: String): CharSequence =
        Morceaux().ajouter(ns(valeur), 88f * s, Palette.sante, police(300)).ajouter(if (unite.isEmpty()) "" else " $unite", 28f * s, Palette.texte2, policeTexte()).sb

    protected fun titreAvecRegle(titre: String, regle: String): CharSequence =
        Morceaux().ajouter(titre, 17f * s, Palette.texte2).ajouter(regle, 17f * s, Palette.texte3).sb

    /**
     * Sommeil de la nuit : [valeur] en grand (calculée par l'appelant), temps au lit et éveil dessous, ou « au
     * lit, sans stades » quand la valeur est un temps au lit faute de stades ([estime]).
     */
    protected fun nuit(titre: String, valeur: Int?, auLit: Int?, stadesNuit: List<Pair<String, Int>>, ligneOxygene: String, estime: Boolean = false) {
        val eveil = stadesNuit.firstOrNull { it.first == "eveille" }?.second
        val montre = valeur
        titreSommeil.texte = titre
        sommeil.texte = montre?.let { ns(SanteHisto.duree(it)) } ?: ""
        stades.stades = stadesNuit
        montre(stades, stadesNuit.isNotEmpty())
        lit.texte = if (estime) "au lit, sans stades" else listOfNotNull(
            auLit?.takeIf { it != montre }?.let { ns(SanteHisto.duree(it)) + " au lit" },
            eveil?.let { ns(SanteHisto.duree(it)) + " éveillé" },
        ).joinToString(", ")
        oxygene.texte = ligneOxygene
        for (v in listOf(titreSommeil, sommeil, lit, oxygene)) montre(v, montre != null)
        montre(oxygene, montre != null && ligneOxygene.isNotEmpty())
    }

    protected fun coeur(principal: Int?, libelle: String, ligne2: String) {
        coeur.texte = principal?.let { grand(it.toString(), "bpm") } ?: ""
        coeurLigne.texte = libelle
        coeurLigne2.texte = ligne2
        for (v in listOf(titreCoeur, coeur, coeurLigne)) montre(v, principal != null)
        montre(coeurLigne2, ligne2.isNotEmpty())
    }

    protected fun sport(titre: String, seances: Int?, minutes: Int?, charge: Int?, avant: String) {
        val ok = seances != null && minutes != null
        titreSport.texte = titre
        sport1.texte = if (ok) Morceaux().also { ligneSeances(it, seances!!, minutes!!, s, police(300), policeTexte()) }.sb else ""
        sport2.texte = charge?.let { Morceaux().ajouter(ns(SanteHisto.milliers(it)), 64f * s, Palette.sante, police(300)).ajouter(" de charge", 28f * s, Palette.texte2, policeTexte()).sb } ?: ""
        sportAvant.texte = avant
        for (v in listOf(titreSport, sport1)) montre(v, ok)
        montre(sport2, ok && charge != null)
        montre(sportAvant, ok && avant.isNotEmpty())
    }

    /** Séance avec sa courbe et ses zones (détail du serveur), ou sans courbe (résumé du jour). */
    protected fun seance(titre: String, ligne: String, id: String?, points: List<Pair<Double, Int>>, bornes: List<SanteHisto.Borne>?, fcMax: Int?) {
        seanceId = id
        titreSeance.texte = titre
        ligneSeance.texte = ligne
        val max = points.maxOfOrNull { it.second }
        courbe.regler(points, bornes, fcMax, max?.toString() ?: "")
        for (v in listOf(titreSeance, ligneSeance)) montre(v, ligne.isNotEmpty())
        montre(courbe, points.size >= 2)
    }

    /** « Natation, 1 h 15, charge 142, cœur moyen 148 » (« 8,4 km » pour une course). */
    protected fun resumeSeance(nom: String, minutes: Int?, distance: Int?, charge: Int?, fcMoy: Int?): String = listOfNotNull(
        nom,
        minutes?.let { ns(SanteHisto.duree(it)) },
        distance?.takeIf { it >= 100 }?.let { ns(SanteHisto.km(it)) },
        charge?.let { ns("charge $it") },
        fcMoy?.let { ns("cœur moyen $it") },
    ).joinToString(", ")

    override fun vider() {
        for (t in listOf(titreSommeil, sommeil, lit, oxygene, pas, lignePas, notePas, coeur, coeurLigne, coeurLigne2, titreSport, sport1, sport2, sportAvant, titreSeance, ligneSeance)) t.texte = ""
        stades.stades = emptyList()
        graphePas.barres = emptyList()
        courbe.regler(emptyList(), null, null, "")
        seanceId = null
    }
}

/** Onglet Aujourd'hui (maquette `Sante` refaite). */
internal class OngletAujourdhui(ctx: Context) : GabaritJour(ctx) {
    private val grapheSommeil = place(BarresSante(ctx).apply { gabarit = BarresSante.Gabarit.SEPT }, 72f, 362f, 552f)

    init {
        titrePas.texte = "Pas aujourd'hui"
    }

    fun montrer(d: SanteDetail.Detail?, semaine: SanteHisto.Semaine?, seance: SanteHisto.SeanceComplete?, aujourdhui: LocalDate) {
        if (d == null) {
            vider()
            return
        }
        val n = d.nuit
        val reel = n?.stades?.filter { SanteDetail.dort(it.first) }?.sumOf { it.second }?.takeIf { it > 0 }
        nuit(
            if (n == null) "Sommeil cette nuit" else SanteDetail.titreNuit(n), reel ?: n?.minutes, n?.minutes, n?.stades ?: emptyList(),
            d.aujourdhui?.spo2Moyenne?.let { "Oxygène aujourd'hui, " + ns("$it %") + " en moyenne" } ?: "",
        )
        val a = d.aujourdhui
        val p = a?.pas?.takeIf { a.renseigne }
        titrePas.texte = "Pas aujourd'hui"
        pas.texte = p?.let { grand(SanteHisto.milliers(it), "pas") } ?: ""
        lignePas.texte = a?.distanceM?.takeIf { it > 0 }?.let { ns(SanteHisto.km(it)) + " parcourus" } ?: ""
        notePas.texte = ""
        for (v in listOf(titrePas, pas)) montre(v, p != null)
        // Mêmes sept jours sur les deux graphes, chaque nuit portant le jour du réveil.
        val jours = d.jours.filter { it.date != null }.takeLast(7)
        titreGaucheGraphe.texte = titreAvecRegle("Sommeil des 7 dernières nuits", ", chaque nuit porte le jour du réveil")
        titreDroitGraphe.texte = titreAvecRegle("Pas des 7 derniers jours", ", en milliers")
        grapheSommeil.barres = jours.map { j ->
            val dernier = j.date == aujourdhui
            val v = j.sommeilMinutes?.takeIf { j.renseigne || it > 0 }
            BarresSante.Barre(
                j.date!!, v?.toDouble(), enAvant = dernier && n?.cetteNuit == true,
                texteValeur = v?.let { SanteHisto.duree(it) } ?: "",
                lecture = v?.let { SanteHisto.lecture(j.date, SanteHisto.duree(it), aujourdhui) } ?: "",
            )
        }
        grapheSommeil.surJour = { if (it != aujourdhui) surJour(it) }
        graphePas.barres = jours.map { j ->
            val v = j.pas?.takeIf { j.renseigne }
            val enCours = j.date == aujourdhui
            BarresSante.Barre(
                j.date!!, v?.toDouble(), enCours = enCours,
                texteValeur = v?.let { SanteDetail.milliersDePas(it) } ?: "",
                lecture = v?.let { SanteHisto.lecture(j.date, SanteHisto.milliers(it) + " pas", aujourdhui) } ?: "",
            )
        }
        graphePas.surJour = { if (it != aujourdhui) surJour(it) }
        montre(titreGaucheGraphe, jours.isNotEmpty())
        montre(titreDroitGraphe, jours.isNotEmpty())
        // Cœur : au repos cette nuit en vedette, sinon le plus bas de la journée.
        val repos = a?.fcRepos
        coeur(
            repos ?: a?.fcMin, if (repos != null) "au repos cette nuit" else "au plus bas aujourd'hui",
            listOfNotNull(a?.fcMoyenne?.let { ns("$it en moyenne") + " aujourd'hui" }, a?.fcMax?.let { ns("$it au plus haut") }).joinToString(", "),
        )
        if (semaine != null) {
            sport(
                "Sport, " + SanteHisto.plage(semaine.du, semaine.au, aujourdhui), semaine.seances, semaine.minutes,
                semaine.charge.takeIf { semaine.avecCharge > 0 },
                semaine.avantMoyenne?.let { "${semaine.avantSemaines} semaines d'avant, " + ns(SanteHisto.milliers(it)) + " en moyenne" } ?: "",
            )
        } else sport("", null, null, null, "")
        // Dernière séance : le détail du serveur (zones et bornes) s'il est là, sinon le résumé du jour.
        if (seance != null) {
            val it = seance.item
            val quand = SanteDetail.quand(it.date ?: it.debut?.toLocalDate(), aujourdhui)?.lowercase(java.util.Locale.FRANCE)
            val heure = it.debut?.let { d0 -> "à " + ns("${d0.hour} h " + d0.minute.toString().padStart(2, '0')) }
            seance(
                "Dernière séance" + listOfNotNull(quand, heure).joinToString(" ").let { t -> if (t.isEmpty()) "" else ", $t" },
                resumeSeance(it.nom, it.minutes, if (it.sport == "course") it.distanceM else null, it.trimp, it.fcMoyenne),
                it.id, seance.courbe, seance.bornes, seance.fcMaxReference,
            )
        } else {
            val x = d.seances.firstOrNull()
            if (x == null) seance("", "", null, emptyList(), null, null)
            else seance(
                "Dernière séance, " + SanteDetail.quandSeance(x, aujourdhui).replaceFirstChar { it.lowercase() },
                resumeSeance(x.titre, x.minutes, x.distanceM, null, x.fcMoyenne), null, x.courbe, null, null,
            )
        }
    }

    override fun vider() {
        super.vider()
        grapheSommeil.barres = emptyList()
        titrePas.texte = "Pas aujourd'hui"
    }
}

/**
 * Vue d'un jour passé (maquette `SanteJour`) : gabarit d'Aujourd'hui avec une date. Toucher le bloc du sommeil
 * bascule entre l'hypnogramme de la nuit et les 7 nuits finies ce jour-là, une nuit sans stades montre
 * directement les 7 nuits.
 */
internal class VueJour(ctx: Context) : GabaritJour(ctx) {
    private val hypno = place(Hypnogramme(ctx), 72f, 368f, 552f, 140f)
    private val grapheNuits = place(BarresSante(ctx).apply { gabarit = BarresSante.Gabarit.SEPT }, 72f, 362f, 552f)
    private val zoneSommeil = place(View(ctx).apply {
        isClickable = true
        isFocusable = true
        contentDescription = "Sommeil de la nuit, afficher les stades heure par heure ou les 7 nuits"
    }, 64f, 132f, 568f, 192f)
    private var hypnoOuvert = true
    private var titreHypno: CharSequence = ""
    private var titreNuits: CharSequence = ""

    init {
        zoneSommeil.setOnClickListener {
            hypnoOuvert = !hypnoOuvert
            basculer()
        }
    }

    private fun basculer() {
        val avecHypno = hypno.seq.isNotEmpty()
        val avecNuits = grapheNuits.barres.isNotEmpty()
        val h = avecHypno && (hypnoOuvert || !avecNuits)
        montre(hypno, h)
        montre(grapheNuits, !h && avecNuits)
        titreGaucheGraphe.texte = if (h) titreHypno else if (avecNuits) titreNuits else ""
        montre(zoneSommeil, avecHypno && avecNuits)
    }

    /**
     * [jours] : points par jour d'une période du serveur qui contient les 7 jours finis ce jour-là (graphes des
     * pas et des 7 nuits), [semaine] : sport de ces 7 jours et des semaines d'avant, calculé sur la liste des
     * séances (null s'il n'est pas sûr).
     */
    fun montrer(j: SanteHisto.Jour?, jours: List<SanteHisto.Point>, semaine: SanteHisto.Semaine?, seance: SanteHisto.SeanceComplete?, records: SanteHisto.Records?, aujourdhui: LocalDate) {
        if (j == null) {
            vider()
            return
        }
        val n = j.nuit
        // Sommeil du serveur (même chiffre que Tendances et Records), temps au lit sans stades.
        nuit(
            "Sommeil de la nuit", n?.sommeil ?: j.sommeil, n?.auLit ?: j.auLit, n?.stades ?: emptyList(),
            j.spo2Min?.let { "Oxygène au plus bas cette nuit, " + ns("$it %") } ?: "", estime = j.sommeilEstime,
        )
        hypno.seq = n?.seq ?: emptyList()
        hypno.debut = n?.debut
        val total = n?.seq?.maxOfOrNull { it.first + it.second }?.toLong() ?: 0L
        titreHypno = if (n?.debut != null && n.seq.isNotEmpty()) titreAvecRegle(
            "Stades de la nuit", ", de " + ns(SanteHisto.heure(n.debut)) + " à " + ns(SanteHisto.heure(SanteHisto.apres(n.debut, total))),
        ) else ""
        // Sept jours finis ce jour-là, pris dans la série par jour d'une période qui les contient tous.
        val du7 = j.date.minusDays(6)
        val serie = jours.filter { !it.date.isBefore(du7) && !it.date.isAfter(j.date) }.takeIf { it.size == 7 } ?: emptyList()
        titreNuits = if (serie.isNotEmpty()) titreAvecRegle("Sommeil, " + SanteHisto.plage(du7, j.date, aujourdhui), ", chaque nuit porte le jour du réveil") else ""
        grapheNuits.barres = serie.map { p ->
            BarresSante.Barre(
                p.date, p.sommeil?.toDouble(), enAvant = p.date == j.date, texteValeur = p.sommeil?.let { SanteHisto.duree(it) } ?: "",
                lecture = p.sommeil?.let { SanteHisto.lecture(p.date, SanteHisto.duree(it) + (if (p.sommeilEstime) ", au lit" else ""), aujourdhui) } ?: "",
            )
        }
        grapheNuits.surJour = { if (it != j.date) surJour(it) }
        basculer()
        titrePas.texte = "Pas"
        pas.texte = j.pas?.let { grand(SanteHisto.milliers(it), "pas") } ?: ""
        lignePas.texte = j.distanceM?.takeIf { it > 0 }?.let { ns(SanteHisto.km(it)) + " parcourus" } ?: ""
        val record = records?.records?.get("journee_la_plus_active")
        notePas.texte = if (record?.date == j.date) "Journée la plus active depuis le " + (records.depuis?.let { SanteHisto.jourMois(it, -1) } ?: "début des données") else ""
        for (v in listOf(titrePas, pas)) montre(v, j.pas != null)
        titreDroitGraphe.texte = if (serie.isNotEmpty()) titreAvecRegle("Pas, " + SanteHisto.plage(du7, j.date, aujourdhui), ", en milliers") else ""
        graphePas.barres = serie.map { p ->
            BarresSante.Barre(
                p.date, p.pas?.toDouble(), enAvant = p.date == j.date, texteValeur = p.pas?.let { SanteDetail.milliersDePas(it) } ?: "",
                lecture = p.pas?.let { SanteHisto.lecture(p.date, SanteHisto.milliers(it) + " pas", aujourdhui) } ?: "",
            )
        }
        graphePas.surJour = { if (it != j.date) surJour(it) }
        coeur(j.fcMin, "au repos cette nuit", listOfNotNull(j.fcMoyenne?.let { ns("$it en moyenne") + " ce jour-là" }, j.fcMax?.let { ns("$it au plus haut") }).joinToString(", "))
        val w = semaine?.takeIf { it.au == j.date }
        if (w != null) sport(
            "Sport, " + SanteHisto.plage(w.du, w.au, aujourdhui), w.seances, w.minutes, w.charge.takeIf { w.avecCharge > 0 },
            w.avantMoyenne?.let { "${w.avantSemaines} semaines d'avant, " + ns(SanteHisto.milliers(it)) + " en moyenne" } ?: "",
        ) else sport("", null, null, null, "")
        val x = seance?.item ?: j.seances.firstOrNull()
        if (x == null) seance("", "", null, emptyList(), null, null)
        else seance(
            "Séance du jour" + (x.debut?.let { ", à " + ns(SanteHisto.heure(it)) } ?: ""),
            resumeSeance(x.nom, x.minutes, if (x.sport == "course") x.distanceM else null, x.trimp, x.fcMoyenne), x.id,
            seance?.courbe ?: emptyList(), seance?.bornes, seance?.fcMaxReference,
        )
    }

    override fun vider() {
        super.vider()
        hypno.seq = emptyList()
        hypno.debut = null
        grapheNuits.barres = emptyList()
        hypnoOuvert = true
        titreHypno = ""
        titreNuits = ""
        titreGaucheGraphe.texte = ""
        titreDroitGraphe.texte = ""
        montre(zoneSommeil, false)
    }
}

// ================================================================ Tendances

/** Légende d'un graphe à droite de son titre : mots colorés précédés d'une pastille, d'un carré creux ou d'un point. */
internal class LegendeSante(ctx: Context) : GrapheSante(ctx) {
    /** Libellé, couleur, forme : 'c' carré plein, 'o' carré creux, '.' point, '-' trait. */
    var elements: List<Triple<String, Int, Char>> = emptyList()
        set(v) {
            field = v
            invalidate()
        }

    override fun dessiner(c: android.graphics.Canvas, s: Float) {
        var x = width.toFloat()
        val px = 15f * s
        for ((t, coul, forme) in elements.reversed()) {
            pTexte.textSize = px
            val l = pTexte.measureText(t)
            x -= l
            texte(t, x, 0f, px, Palette.texte3)
            x -= 8f * s
            val cy = 1.22f * px / 2f
            when (forme) {
                'c' -> { plein.color = coul; r.set(x - 10f * s, cy - 5f * s, x, cy + 5f * s); c.drawRoundRect(r, 2f * s, 2f * s, plein) }
                'o' -> { trait.color = coul; trait.strokeWidth = 1.5f * s; r.set(x - 10f * s, cy - 5f * s, x, cy + 5f * s); c.drawRoundRect(r, 2f * s, 2f * s, trait) }
                '.' -> { plein.color = coul; c.drawCircle(x - 3f * s, cy, 2.5f * s, plein) }
                else -> { plein.color = coul; c.drawRect(x - 14f * s, cy - 1f * s, x, cy + 1f * s, plein) }
            }
            x -= if (forme == '-') 14f * s else 10f * s
            x -= 16f * s
        }
    }
}

/** Sélecteur à filet vert à gauche (période de Tendances, filtre de Séances). */
internal class Selecteur(ctx: Context, noms: List<String>, private val surChoix: (Int) -> Unit) : LinearLayout(ctx) {
    private val items = noms.mapIndexed { i, nom ->
        TexteFondu(ctx).apply {
            peinture.typeface = Polices.texte(ctx)
            texte = nom
            isClickable = true
            isFocusable = true
            contentDescription = nom
            setOnClickListener { surChoix(i) }
        }
    }
    private val filets = noms.map { View(ctx) }
    private val cellules = items.mapIndexed { i, t ->
        FrameLayout(ctx).apply {
            addView(filets[i])
            addView(t)
        }
    }
    var choisi = 0
        set(v) {
            field = v
            maj()
        }

    /** Nom affiché de la case [i]. */
    fun nom(i: Int): String = items.getOrNull(i)?.texte?.toString() ?: ""
    var echelle = 2f
        set(v) {
            field = v
            maj()
        }

    init {
        orientation = HORIZONTAL
        for (c in cellules) addView(c)
        maj()
    }

    private fun maj() {
        val s = echelle
        for ((i, c) in cellules.withIndex()) {
            val t = items[i]
            t.taille(18f * s)
            t.couleur(if (i == choisi) Palette.sante else Palette.texte3)
            t.layoutParams = FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.CENTER_VERTICAL).apply {
                leftMargin = (16f * s).roundToInt()
                rightMargin = (16f * s).roundToInt()
            }
            filets[i].setBackgroundColor(if (i == choisi) Palette.sante else 0)
            filets[i].layoutParams = FrameLayout.LayoutParams(max(2, (2f * s).roundToInt()), FrameLayout.LayoutParams.MATCH_PARENT)
            c.layoutParams = LayoutParams(LayoutParams.WRAP_CONTENT, max((44f * s).roundToInt(), Decor.dp(context, 44f)))
        }
    }
}

/** Onglet Tendances (maquette `SanteTendances`) : période, quatre chiffres, quatre graphes. */
internal class OngletTendances(ctx: Context) : VueSante(ctx) {
    var surJours: (Int) -> Unit = {}
    var surJour: (LocalDate) -> Unit = {}
    private val periodes = listOf(7, 30, 90, 365)
    private val selecteur = place(Selecteur(ctx, listOf("7 jours", "30 jours", "3 mois", "1 an")) { surJours(periodes[it]) }, 72f, 134f)
    private val plage = place(texte(Palette.texte3, 16f), 72f, 186f, 1136f)

    private class Chiffre(val titre: TexteFondu, val valeur: TexteFondu, val l1: TexteFondu, val l2: TexteFondu, val avant: TexteFondu)

    private val chiffres = listOf(72f, 364f, 656f, 948f).map { x ->
        Chiffre(
            place(texte(Palette.texte3, 16f), x, 222f, 260f), place(texte(Palette.sante, 46f), x, 240f, 280f),
            place(texte(Palette.texte2, 15f), x, 296f, 270f), place(texte(Palette.texte2, 15f), x, 318f, 270f), place(texte(Palette.texte3, 15f), x, 340f, 270f),
        )
    }
    private val tSommeil = place(texte(Palette.texte2, 16f).apply { texte = "Sommeil par nuit" }, 72f, 384f, 250f)
    private val lSommeil = place(LegendeSante(ctx), 330f, 384f, 294f, 22f)
    private val gSommeil = place(BarresSante(ctx).apply { gabarit = BarresSante.Gabarit.PERIODE; reperes = REPERES_SOMMEIL }, 72f, 414f, 552f)
    private val tPas = place(texte(Palette.texte2, 16f).apply { texte = "Pas par jour" }, 656f, 384f, 330f)
    private val lPas = place(LegendeSante(ctx), 914f, 384f, 294f, 22f)
    private val gPas = place(BarresSante(ctx).apply { gabarit = BarresSante.Gabarit.PERIODE }, 656f, 414f, 552f)
    private val tCoeur = place(texte(Palette.texte2, 16f).apply { texte = "Cœur, bpm" }, 72f, 572f, 200f)
    private val lCoeur = place(LegendeSante(ctx), 230f, 572f, 394f, 22f)
    private val gCoeur = place(LignesSante(ctx).apply { reperes = listOf(50.0 to "50", 70.0 to "70") }, 72f, 602f, 552f)
    private val tCharge = place(texte(Palette.texte2, 16f).apply { texte = "Charge d'entraînement par semaine" }, 656f, 572f, 300f)
    private val iCharge = place(RondInfo(ctx).apply { contentDescription = "Qu'est-ce que la charge ?" }, 948f, 566f, 30f, 30f)
    private val lCharge = place(LegendeSante(ctx), 990f, 572f, 218f, 22f)
    private val gCharge = place(ChargeSante(ctx), 656f, 602f, 552f)
    private val aide = place(texte(Palette.texte2, 15f, 2, interligne = 1.4f / 1.22f).apply {
        texte = "Durée pondérée par l'intensité cardiaque, pour comparer tes séances entre elles."
        setBackgroundColor(Palette.surface)
        visibility = View.GONE
        isClickable = true
        setOnClickListener { visibility = View.GONE }
    }, 704f, 602f, 504f)

    init {
        iCharge.isClickable = true
        iCharge.setOnClickListener { aide.visibility = if (aide.visibility == View.VISIBLE) View.GONE else View.VISIBLE }
        lSommeil.elements = listOf(Triple("sommeil profond", Palette.sante, 'c'), Triple("autres stades", Palette.colonne, 'c'), Triple("séance", Palette.texte2, '.'))
        lPas.elements = listOf(Triple("pas", Palette.colonne, 'c'), Triple("en cours", Palette.sante, 'o'), Triple("séance", Palette.texte2, '.'))
        lCoeur.elements = listOf(Triple("au repos, minimum de la nuit", Palette.sante, '-'), Triple("moyenne de la journée", Palette.texte3, '-'))
    }

    override fun tailles(e: Float) {
        selecteur.echelle = e
    }

    /**
     * [calage] : dates d'un record de semaine ou de série ouvert depuis Records, mises en avant sur les graphes
     * de sommeil et de pas (barres en vert) et rappelées sous le sélecteur.
     */
    fun montrer(p: SanteHisto.Periode?, jours: Int, aujourdhui: LocalDate, calage: Pair<LocalDate, LocalDate>? = null) {
        selecteur.choisi = periodes.indexOf(jours).coerceAtLeast(0)
        if (p == null) {
            vider()
            return
        }
        val parSemaine = p.jours >= 90
        // « sport par ... » seulement quand le sport n'a pas la granularité des points.
        val granPoints = if (parSemaine) "semaine" else "jour"
        plage.texte = listOfNotNull(
            if (p.du != null && p.au != null) SanteHisto.majuscule(SanteHisto.plage(p.du, p.au, aujourdhui)) else null,
            "un point par $granPoints",
            p.sportGranularite.takeIf { it != granPoints }?.let { "sport par $it" },
            calage?.let { "en vert, le record " + SanteHisto.plage(it.first, it.second, aujourdhui) },
        ).joinToString(", ")
        // Un point est dans le record si son jour (ou sa semaine, à 3 mois et 1 an) touche ses dates.
        fun dansRecord(d: LocalDate): Boolean {
            val c = calage ?: return false
            val fin = if (parSemaine) d.plusDays(6) else d
            return !fin.isBefore(c.first) && !d.isAfter(c.second)
        }
        val b = p.bilan
        val a = p.avant?.takeIf { p.jours < 365 || it.partielle || it.joursDisponibles != null }
        val avantNom = SanteHisto.avant(p.jours) + (a?.takeIf { it.partielle }?.joursDisponibles?.let { " (" + SanteHisto.partielle(it) + ")" } ?: "")
        // Sommeil.
        val c0 = chiffres[0]
        c0.titre.texte = "Sommeil"
        c0.valeur.texte = b?.sommeil?.let { valeur(SanteHisto.duree(it), "par nuit") } ?: ""
        c0.l1.texte = listOfNotNull(b?.auLit?.let { ns(SanteHisto.duree(it)) + " au lit" }, b?.profond?.let { ns(SanteHisto.duree(it)) + " de profond" }).joinToString(", ")
        c0.l2.texte = b?.spo2Min?.let { "oxygène la nuit, " + ns("$it %") + " au plus bas" } ?: ""
        c0.avant.texte = a?.sommeil?.let { "$avantNom, " + ns(SanteHisto.duree(it)) } ?: ""
        // Pas.
        val c1 = chiffres[1]
        c1.titre.texte = "Pas"
        c1.valeur.texte = b?.pas?.let { valeur(SanteHisto.milliers(it), "par jour") } ?: ""
        c1.l1.texte = b?.distanceM?.let { ns(SanteHisto.km(it)) + " parcourus par jour" } ?: ""
        c1.l2.texte = if (p.serie.any { it.enCours }) "sans aujourd'hui, en cours" else ""
        c1.avant.texte = a?.pas?.let { "$avantNom, " + ns(SanteHisto.milliers(it)) } ?: ""
        // Cœur : au repos (moyenne des minima de chaque nuit) en tête.
        val c2 = chiffres[2]
        c2.titre.texte = "Cœur"
        c2.valeur.texte = b?.fcRepos?.let { valeur(it.toString(), "bpm au repos") } ?: ""
        c2.l1.texte = if (b?.fcRepos != null) "moyenne des minima de chaque nuit" else ""
        c2.l2.texte = b?.fcMoyenne?.let { ns("$it en moyenne") + " sur la journée" } ?: ""
        c2.avant.texte = a?.fcRepos?.let { "$avantNom, " + ns("$it au repos") } ?: ""
        // Sport : durée et séances, par sport, charge, comparaison par semaine.
        val c3 = chiffres[3]
        val sp = b?.sport
        c3.titre.texte = "Sport"
        c3.valeur.texte = sp?.minutes?.let { m ->
            Morceaux().ajouter(ns(SanteHisto.duree(m)), 46f * s, Palette.sante, police(400))
                .ajouter(sp.seances?.let { " en $it " + if (it > 1) "séances" else "séance" } ?: "", 17f * s, Palette.texte2, policeTexte()).sb
        } ?: ""
        c3.l1.texte = sp?.parSport?.values?.filter { (it.seances ?: 0) > 0 }?.joinToString(", ") { it.nom.lowercase(java.util.Locale.FRANCE) + " " + it.seances } ?: ""
        c3.l2.texte = sp?.trimp?.let { "charge " + ns(SanteHisto.milliers(it)) } ?: ""
        // Période d'avant complète : son total, comme la maquette. Partielle : par semaine des deux côtés.
        // Deux lignes au plus, la mention « (7 mois seulement) » allongeant la ligne.
        for (c in chiffres) c.avant.maxLignes = 2
        c3.avant.texte = a?.sport?.let { sa ->
            if (a.partielle) sa.minutesParSemaine?.let { "$avantNom, " + ns(SanteHisto.duree(it)) + " par semaine" + (sp?.minutesParSemaine?.let { m -> " contre " + ns(SanteHisto.duree(m)) } ?: "") }
            else sa.minutes?.let { "$avantNom, " + ns(SanteHisto.duree(it)) }
        } ?: ""
        // Graphes.
        val pts = if (parSemaine) p.courbes else p.serie
        val pasDates = when {
            pts.size <= 7 -> 1
            pts.size > 20 && parSemaine -> 9
            parSemaine -> 4
            else -> 7
        }
        val dates = indicesDates(pts.size, pasDates).map { it to SanteHisto.court(pts[it].date) }
        // Par semaine : semaine en cours en barre creuse aussi pour le sommeil, pas de points de séance.
        tPas.texte = if (parSemaine) "Pas par jour, moyenne de chaque semaine" else "Pas par jour"
        lSommeil.elements = listOfNotNull(Triple("sommeil profond", Palette.sante, 'c'), Triple("autres stades", Palette.colonne, 'c'), Triple("séance", Palette.texte2, '.').takeIf { !parSemaine })
        lPas.elements = listOfNotNull(Triple("pas", Palette.colonne, 'c'), Triple("en cours", Palette.sante, 'o'), Triple("séance", Palette.texte2, '.').takeIf { !parSemaine })
        gSommeil.barres = pts.map { x ->
            BarresSante.Barre(
                x.date, x.sommeil?.toDouble(), part = x.profond?.toDouble().takeIf { !dansRecord(x.date) }, enCours = x.enCours && (parSemaine || x.sommeil == null), seance = x.seances > 0 && !parSemaine,
                enAvant = dansRecord(x.date),
                lecture = x.sommeil?.let { SanteHisto.lecture(x.date, SanteHisto.duree(it) + (if (x.sommeilEstime) ", estimé au lit" else ""), aujourdhui) } ?: "",
            )
        }
        gSommeil.dates = dates
        gSommeil.surJour = if (parSemaine) null else ({ d: LocalDate -> surJour(d) })
        val maxPas = pts.mapNotNull { it.pas }.maxOrNull() ?: 0
        gPas.reperes = reperePas(maxPas)
        gPas.barres = pts.map { x ->
            BarresSante.Barre(
                x.date, x.pas?.toDouble(), enCours = x.enCours, seance = x.seances > 0 && !parSemaine, enAvant = dansRecord(x.date),
                lecture = x.pas?.let { SanteHisto.lecture(x.date, SanteHisto.milliers(it) + " pas" + if (parSemaine) " par jour" else "", aujourdhui) } ?: "",
            )
        }
        gPas.dates = dates
        gPas.surJour = if (parSemaine) null else ({ d: LocalDate -> surJour(d) })
        // Pas de moyenne partielle du jour en cours (le minimum de la nuit, lui, est fini).
        fun moyenne(x: SanteHisto.Point) = x.fcMoyenne?.takeIf { !(x.enCours && !parSemaine) }
        gCoeur.series = listOf(
            LignesSante.Serie(pts.map { it.fcMin?.toDouble() }, Palette.sante),
            LignesSante.Serie(pts.map { moyenne(it)?.toDouble() }, Palette.texte3),
        )
        gCoeur.dates = dates
        gCoeur.jours = pts.map { it.date }
        gCoeur.lectures = pts.map { x -> listOfNotNull(x.fcMin?.let { "repos $it" }, moyenne(x)?.let { "moyenne $it" }).joinToString(", ").let { if (it.isEmpty()) "" else SanteHisto.lecture(x.date, it, aujourdhui) } }
        gCoeur.surJour = if (parSemaine) null else ({ d: LocalDate -> surJour(d) })
        // Charge : par semaine (par mois à 1 an), empilée par sport, deux opacités.
        // Sports rangés par charge totale : le plus chargé en vert plein, le second plus clair.
        val sports = p.groupes.flatMap { it.parSport.keys }.distinct().sortedByDescending { k -> p.groupes.sumOf { it.parSport[k]?.trimp ?: 0 } }
        tCharge.texte = if (p.sportGranularite == "mois") "Charge d'entraînement par mois" else if (p.sportGranularite == "jour") "Charge d'entraînement par jour" else "Charge d'entraînement par semaine"
        // Deux parts au plus : le sport le plus chargé en vert plein, le second (ou tous les autres regroupés)
        // en vert à 0,5, la pastille de la légende comme la barre.
        val second = (0x80 shl 24) or (Palette.sante and 0xFFFFFF)
        fun nom(k: String) = p.groupes.firstNotNullOfOrNull { it.parSport[k]?.nom }?.lowercase(java.util.Locale.FRANCE) ?: k
        lCharge.elements = listOfNotNull(
            sports.getOrNull(0)?.let { Triple(nom(it), Palette.sante, 'c') },
            sports.getOrNull(1)?.let { Triple(if (sports.size > 2) "autres sports" else nom(it), second, 'c') },
        )
        gCharge.groupes = p.groupes.takeLast(if (p.sportGranularite == "mois") 12 else 13).map { g ->
            val parts = if (g.parSport.isEmpty()) listOf((g.trimp ?: 0).toDouble() to 1f)
            else listOf(
                (sports.getOrNull(0)?.let { g.parSport[it]?.trimp } ?: 0).toDouble() to 1f,
                sports.drop(1).sumOf { g.parSport[it]?.trimp ?: 0 }.toDouble() to 0.5f,
            )
            // Par mois : le nom du mois abrégé (« oct. »), sinon le lundi de la semaine (« 12 oct. »).
            val date = if (p.sportGranularite == "mois") SanteHisto.court(g.debut).substringAfter(' ') else SanteHisto.court(g.debut)
            // Sans séance, ni charge ni durée écrites (pas de « 0 » au-dessus d'un jour de repos).
            val sport = (g.seances ?: 0) > 0
            ChargeSante.Groupe(parts, g.trimp?.takeIf { sport }, g.minutes?.takeIf { sport }?.let { SanteHisto.duree(it) } ?: "", date, g.enCours)
        }
        for (v in listOf(tCharge, iCharge, lCharge, gCharge)) montre(v, p.groupes.isNotEmpty())
    }

    private fun valeur(v: String, unite: String): CharSequence =
        Morceaux().ajouter(ns(v), 46f * s, Palette.sante, police(400)).ajouter(" $unite", 17f * s, Palette.texte2, policeTexte()).sb

    override fun vider() {
        plage.texte = ""
        for (c in chiffres) for (t in listOf(c.titre, c.valeur, c.l1, c.l2, c.avant)) t.texte = ""
        gSommeil.barres = emptyList()
        gPas.barres = emptyList()
        gCoeur.series = emptyList()
        gCoeur.lectures = emptyList()
        gCoeur.jours = emptyList()
        gCoeur.dates = emptyList()
        gCharge.groupes = emptyList()
        aide.visibility = View.GONE
    }
}

// ================================================================ Séances

/**
 * Onglet Séances (maquette `SanteSeances`) : liste à gauche, détail de la séance choisie à droite dans une
 * colonne défilante de 552 x 620 px (l'analyse écrite y tient entière, jusqu'à 6 000 caractères).
 */
internal class OngletSeances(ctx: Context) : VueSante(ctx) {
    var surFiltre: (String) -> Unit = {}
    var surSeance: (String) -> Unit = {}
    /** Clés des filtres : « tous », puis les sports principaux de la période (SanteHisto.sportsPrincipaux, 0.30.1). */
    private var filtres = listOf("tous")
    private val plage = place(texte(Palette.texte3, 16f), 72f, 136f, 552f)
    private val cadreFiltre = place(FrameLayout(ctx), 58f, 162f)
    private var filtre = Selecteur(ctx, listOf("Tous")) { surFiltre(filtres[it]) }.also { cadreFiltre.addView(it) }
    private var echelleFiltre = 2f
    private val totaux = place(LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }, 72f, 218f, 552f)
    init {
        filet(72f, 282f, 552f)
    }
    private val liste = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }
    private val defile = ScrollView(ctx).apply {
        isVerticalScrollBarEnabled = false
        addView(liste)
    }
    // Cadres qui coupent la liste et le détail à leur hauteur : la vue de l'onglet ne coupe pas ses enfants
    // (clipChildren faux), et ce qui défile n'est coupé que par son parent.
    init {
        place(FrameLayout(ctx).apply { addView(defile, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT)) }, 58f, 290f, 566f, 452f)
    }
    private val colonne = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }
    private val defileDetail = ScrollView(ctx).apply {
        isVerticalScrollBarEnabled = false
        addView(colonne)
    }
    init {
        place(FrameLayout(ctx).apply { addView(defileDetail, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT)) }, 656f, 132f, 552f, 620f)
    }
    private val titre = texte(Palette.texte1, 34f)
    private val date = texte(Palette.texte2, 18f)
    private val chiffres = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
    private val texteAide = texte(Palette.texte2, 15f, 3, interligne = 1.4f / 1.22f).apply {
        texte = "Durée pondérée par l'intensité cardiaque, pour comparer tes séances entre elles."
    }
    private val aide = FrameLayout(ctx).apply {
        setBackgroundColor(Palette.surface)
        visibility = View.GONE
        isClickable = true
        setOnClickListener { visibility = View.GONE }
        addView(texteAide)
    }
    private val courbe = CourbeZones(ctx).apply { compact = false }
    private val zones = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
    private val noteFc = texte(Palette.texte3, 15f)
    private val filetAnalyse = View(ctx).apply { setBackgroundColor(Palette.filet) }
    private val titreAnalyse = texte(Palette.texte2, 17f)
    private val chevronAnalyse = Chevron(ctx, 'v')
    private val enteteAnalyse = FrameLayout(ctx).apply {
        isClickable = true
        isFocusable = true
        addView(titreAnalyse, FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.START or Gravity.CENTER_VERTICAL))
        addView(chevronAnalyse)
    }
    private val texteAnalyse = texte(Palette.texte2, 17f, 10_000, interligne = 1.45f / 1.22f)
    private var analyseOuverte = false
    private var choisie: String? = null
    private var derniere: SanteHisto.ListeSeances? = null
    private var filtreCourant = "tous"
    private var aujourdhui = SanteHisto.aujourdhui()
    /** Barre et nom de chaque ligne de la liste, pour changer la sélection sans la reconstruire. */
    private val rangees = HashMap<String, Pair<View, TexteFondu>>()

    init {
        for (v in listOf(titre, date, chiffres, aide, courbe, zones, noteFc, filetAnalyse, enteteAnalyse, texteAnalyse)) colonne.addView(v)
        enteteAnalyse.setOnClickListener {
            analyseOuverte = !analyseOuverte
            montre(texteAnalyse, analyseOuverte)
            chevronAnalyse.rotation = if (analyseOuverte) 180f else 0f
            enteteAnalyse.contentDescription = titreAnalyse.texte.toString() + if (analyseOuverte) ", replier" else ", déplier"
        }
        texteAnalyse.visibility = View.GONE
    }

    override fun tailles(e: Float) {
        echelleFiltre = e
        filtre.echelle = e
        courbe.echelle = e
        chevronAnalyse.echelle = e
        fun lp(h: Int = LinearLayout.LayoutParams.WRAP_CONTENT, haut: Float = 0f) =
            LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, h).apply { topMargin = (haut * e).roundToInt() }
        titre.layoutParams = lp()
        date.layoutParams = lp(haut = 2f)
        chiffres.layoutParams = lp(haut = 16f)
        aide.layoutParams = lp(haut = 14f)
        texteAide.layoutParams = FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.WRAP_CONTENT).apply {
            // Marges et non padding : TexteFondu ignore le padding.
            setMargins((14f * e).roundToInt(), (10f * e).roundToInt(), (14f * e).roundToInt(), (10f * e).roundToInt())
        }
        courbe.layoutParams = lp((176f * e).roundToInt(), 22f)
        zones.layoutParams = lp(haut = 10f)
        noteFc.layoutParams = lp(haut = 12f)
        filetAnalyse.layoutParams = lp(max(1, (0.5f * e).roundToInt()), 16f)
        enteteAnalyse.layoutParams = lp((48f * e).roundToInt())
        chevronAnalyse.layoutParams = FrameLayout.LayoutParams((44f * e).roundToInt(), (44f * e).roundToInt(), Gravity.END or Gravity.CENTER_VERTICAL)
        texteAnalyse.layoutParams = lp().apply { bottomMargin = (8f * e).roundToInt() }
        derniere?.let { remplirListe(it) }
    }

    /** Liste [l] avec son filtre, la séance [id] choisie et son détail [detail] (null tant qu'il n'est pas lu). */
    fun montrer(l: SanteHisto.ListeSeances?, filtreSport: String, detail: SanteHisto.SeanceComplete?, id: String?, jour: LocalDate) {
        aujourdhui = jour
        filtreCourant = filtreSport
        if (l != null) majFiltres(l, filtreSport)
        filtre.choisi = filtres.indexOf(filtreSport).coerceAtLeast(0)
        choisie = id
        derniere = l
        if (l == null) {
            plage.texte = ""
            totaux.removeAllViews()
            liste.removeAllViews()
            rangees.clear()
        } else {
            // « 30 derniers jours » pour la fenêtre qui finit aujourd'hui, « 30 jours » pour une fenêtre passée.
            val finie = l.au == null || l.au == jour
            plage.texte = "${l.jours} " + (if (finie) "derniers jours" else "jours") +
                (if (l.du != null && l.au != null) ", " + SanteHisto.plage(l.du, l.au, jour) else "")
            remplirTotaux(l, filtreSport)
            remplirListe(l)
        }
        montrerDetail(detail)
    }

    /** Autre séance touchée : la sélection change sans reconstruire la liste, le détail suit quand il est lu. */
    fun selectionner(id: String, detail: SanteHisto.SeanceComplete?) {
        choisie = id
        for ((k, r) in rangees) {
            r.first.setBackgroundColor(if (k == id) Palette.sante else 0)
            r.second.couleur(if (k == id) Palette.sante else Palette.texte1)
        }
        montrerDetail(detail)
    }

    /**
     * Filtres tirés des sports de la liste (0.30.1) : « Tous » puis les deux sports principaux, recalculés sur la liste
     * de tous les sports. Un filtre en cours hors des principaux reste proposé. Sélecteur refait seulement s'il change.
     */
    private fun majFiltres(l: SanteHisto.ListeSeances, filtreSport: String) {
        val noms = LinkedHashMap<String, String>()
        noms["tous"] = "Tous"
        if (filtreSport == "tous") {
            for ((k, nom) in SanteHisto.sportsPrincipaux(l.parSport)) noms[k] = nom
        } else {
            for (k in filtres) if (k != "tous") noms[k] = filtre.nom(filtres.indexOf(k))
            if (filtreSport !in noms) noms[filtreSport] = l.parSport[filtreSport]?.nom ?: SanteDetail.libelleSeance(null, filtreSport)
        }
        if (noms.keys.toList() == filtres) return
        filtres = noms.keys.toList()
        cadreFiltre.removeView(filtre)
        filtre = Selecteur(ctx, noms.values.toList()) { surFiltre(filtres[it]) }.also {
            it.echelle = echelleFiltre
            cadreFiltre.addView(it)
        }
    }

    /**
     * Totaux par sport : les deux sports principaux de la période (0.30.1, aucun sport propre à quelqu'un dans le code), les
     * autres regroupés en « Autres » s'il y en a, les kilomètres pour la course seulement. Charge du serveur (`par_sport.trimp`, serveur 0.20.2), sinon somme
     * des charges de la liste. Ski et snowboard jamais dans la charge.
     */
    private fun remplirTotaux(l: SanteHisto.ListeSeances, filtreSport: String) {
        totaux.removeAllViews()
        fun chargeListe(cles: Set<String>): Int? =
            l.seances.filter { it.sport in cles && it.sport !in SanteHisto.HORS_CHARGE }.mapNotNull { it.trimp }.takeIf { it.isNotEmpty() }?.sum()
        fun charge(k: String): Int? = if (k in SanteHisto.HORS_CHARGE) null else l.parSport[k]?.trimp ?: chargeListe(setOf(k))
        class Ligne(val nom: String, val seances: Int, val minutes: Int, val km: Int?, val charge: Int?)
        val lignes = ArrayList<Ligne>()
        val principaux = SanteHisto.sportsPrincipaux(l.parSport).map { it.first }
        for (k in if (filtreSport == "tous") principaux else listOf(filtreSport)) {
            val sp = l.parSport[k] ?: continue
            if ((sp.seances ?: 0) == 0) continue
            lignes.add(Ligne(sp.nom, sp.seances ?: 0, sp.minutes ?: 0, if (k == "course") l.distances[k] else null, charge(k)))
        }
        if (filtreSport == "tous") {
            val autres = l.parSport.filterKeys { it !in principaux }
            if (autres.isNotEmpty()) {
                val c = autres.keys.mapNotNull { charge(it) }.takeIf { it.isNotEmpty() }?.sum()
                lignes.add(Ligne("Autres", autres.values.sumOf { it.seances ?: 0 }, autres.values.sumOf { it.minutes ?: 0 }, null, c))
            }
        }
        val h = if (lignes.size >= 3) 21f else 30f
        for (x in lignes) {
            val ligne = FrameLayout(ctx)
            ligne.addView(TexteFondu(ctx).apply { peinture.typeface = Polices.texte(ctx); taille(18f * s); couleur(Palette.texte1); texte = x.nom })
            ligne.addView(TexteFondu(ctx).apply {
                peinture.typeface = Polices.texte(ctx); taille(16f * s); couleur(Palette.texte2); aDroite = true
                texte = listOfNotNull(
                    ns("${x.seances} " + if (x.seances > 1) "séances" else "séance"), ns(SanteHisto.duree(x.minutes)),
                    x.km?.takeIf { it >= 100 }?.let { ns(SanteHisto.km(it)) }, x.charge?.let { ns("charge " + SanteHisto.milliers(it)) },
                ).joinToString(", ")
            }, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.END or Gravity.CENTER_VERTICAL))
            totaux.addView(ligne, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, (h * s).roundToInt()))
        }
    }

    private fun remplirListe(l: SanteHisto.ListeSeances) {
        liste.removeAllViews()
        rangees.clear()
        var mois = -1
        for (x in l.seances) {
            val d = x.date ?: x.debut?.toLocalDate()
            val m = d?.let { it.year * 12 + it.monthValue } ?: -1
            if (m != mois && d != null) {
                mois = m
                liste.addView(TexteFondu(ctx).apply {
                    peinture.typeface = Polices.texte(ctx); taille(15f * s); couleur(Palette.texte3)
                    texte = SanteHisto.majuscule(SanteHisto.mois(d)) + if (d.year != aujourdhui.year) " ${d.year}" else ""
                }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
                    // Marges et non padding : TexteFondu ignore le padding.
                    leftMargin = (14f * s).roundToInt()
                    topMargin = (10f * s).roundToInt()
                    bottomMargin = (4f * s).roundToInt()
                })
            }
            val choisi = x.id == choisie
            val ligne = FrameLayout(ctx).apply {
                isClickable = true
                isFocusable = true
                contentDescription = "${x.nom}, ${d?.let { SanteHisto.abrege(it) } ?: ""}"
                setOnClickListener { surSeance(x.id) }
            }
            val barre = View(ctx).apply { setBackgroundColor(if (choisi) Palette.sante else 0) }
            ligne.addView(barre, FrameLayout.LayoutParams(max(2, (2f * s).roundToInt()), FrameLayout.LayoutParams.MATCH_PARENT))
            ligne.addView(TexteFondu(ctx).apply { peinture.typeface = Polices.texte(ctx); taille(16f * s); couleur(Palette.texte3); texte = d?.let { SanteHisto.abrege(it) } ?: "" },
                FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.CENTER_VERTICAL).apply { leftMargin = (14f * s).roundToInt() })
            val nom = TexteFondu(ctx).apply { peinture.typeface = Polices.texte(ctx); taille(19f * s); couleur(if (choisi) Palette.sante else Palette.texte1); texte = x.nom }
            ligne.addView(nom, FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.CENTER_VERTICAL).apply { leftMargin = (100f * s).roundToInt() })
            ligne.addView(TexteFondu(ctx).apply {
                peinture.typeface = Polices.texte(ctx); taille(16f * s); couleur(Palette.texte2); aDroite = true
                texte = listOfNotNull(x.minutes?.let { ns(SanteHisto.duree(it)) }, x.distanceM?.takeIf { x.sport == "course" && it >= 100 }?.let { ns(SanteHisto.km(it)) }, x.trimp?.let { ns("charge $it") }).joinToString(", ")
            }, FrameLayout.LayoutParams(FrameLayout.LayoutParams.WRAP_CONTENT, FrameLayout.LayoutParams.WRAP_CONTENT, Gravity.END or Gravity.CENTER_VERTICAL))
            liste.addView(ligne, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, (60f * s).roundToInt()))
            rangees[x.id] = barre to nom
        }
        if (l.tronque) liste.addView(TexteFondu(ctx).apply { peinture.typeface = Polices.texte(ctx); taille(15f * s); couleur(Palette.texte3); texte = "Les 100 séances les plus récentes" })
    }

    private fun chiffre(valeur: String, nom: String, info: Boolean = false): View {
        val col = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }
        col.addView(TexteFondu(ctx).apply { peinture.typeface = Polices.chiffres(ctx, 400); taille(44f * s); couleur(Palette.sante); texte = ns(valeur) })
        val bas = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL; gravity = Gravity.CENTER_VERTICAL }
        bas.addView(TexteFondu(ctx).apply { peinture.typeface = Polices.texte(ctx); taille(15f * s); couleur(Palette.texte3); texte = nom })
        if (info) bas.addView(RondInfo(ctx).apply {
            echelle = s
            isClickable = true
            contentDescription = "Qu'est-ce que la charge ?"
            setOnClickListener { aide.visibility = if (aide.visibility == View.VISIBLE) View.GONE else View.VISIBLE }
        }, LinearLayout.LayoutParams((24f * s).roundToInt(), (24f * s).roundToInt()))
        col.addView(bas)
        return col
    }

    /** Opacité du trait de chaque zone, celle de sa bande multipliée par 2,6 (maquette). */
    private val traitsZones = floatArrayOf(0.21f, 0.34f, 0.47f, 0.65f, 0.86f)

    private fun montrerDetail(d: SanteHisto.SeanceComplete?) {
        chiffres.removeAllViews()
        zones.removeAllViews()
        analyseOuverte = false
        texteAnalyse.visibility = View.GONE
        chevronAnalyse.rotation = 0f
        aide.visibility = View.GONE
        defileDetail.scrollTo(0, 0)
        if (d == null) {
            for (v in listOf(titre, date, noteFc, titreAnalyse, texteAnalyse)) v.texte = ""
            courbe.regler(emptyList(), null, null, "")
            montre(filetAnalyse, false)
            montre(enteteAnalyse, false)
            return
        }
        val x = d.item
        titre.texte = x.nom
        date.texte = x.debut?.let { SanteHisto.majuscule(SanteHisto.jourSemaine(it.toLocalDate())) + " " + SanteHisto.jourMois(it.toLocalDate(), aujourdhui.year) + " à " + ns(SanteHisto.heure(it)) }
            ?: x.date?.let { SanteHisto.dateLongue(it, aujourdhui) } ?: ""
        val liste = ArrayList<View>()
        if (x.sport == "course") x.distanceM?.takeIf { it >= 100 }?.let { liste.add(chiffre(SanteHisto.km(it), "distance")) }
        x.minutes?.let { liste.add(chiffre(SanteHisto.duree(it), "durée")) }
        if (x.sport == "course") x.allure?.let { liste.add(chiffre(SanteHisto.allure(it).removeSuffix(" min/km"), "allure, min/km")) }
        x.fcMoyenne?.let { liste.add(chiffre(it.toString(), "cœur moyen, bpm")) }
        if (x.sport != "course") x.fcMax?.let { liste.add(chiffre(it.toString(), "cœur maxi, bpm")) }
        x.trimp?.let { liste.add(chiffre(it.toString(), "charge", info = true)) }
        val l = 552f / max(4, liste.size)
        for (v in liste) chiffres.addView(v, LinearLayout.LayoutParams((l * s).roundToInt(), LinearLayout.LayoutParams.WRAP_CONTENT))
        val max = d.courbe.maxOfOrNull { it.second }
        courbe.regler(d.courbe, d.bornes, d.fcMaxReference, max?.let { "$it au plus haut" } ?: "")
        // Zones : nom, bornes en bpm si le serveur les donne (« moins de 114 » pour la zone 1), minutes, trait de
        // 3 px à l'opacité de la zone, 12 px entre les colonnes.
        if (d.zones.any { it != null }) for (i in 0 until 5) {
            val col = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }
            col.addView(TexteFondu(ctx).apply { peinture.typeface = Polices.texte(ctx); taille(15f * s); couleur(Palette.texte2); texte = "Zone ${i + 1}" })
            d.bornes?.getOrNull(i)?.let { b ->
                val t = SanteHisto.texteBorne(b)
                if (t.isNotEmpty()) col.addView(TexteFondu(ctx).apply { peinture.typeface = Polices.texte(ctx); taille(14f * s); couleur(Palette.texte3); texte = ns(t) })
            }
            col.addView(TexteFondu(ctx).apply { peinture.typeface = Polices.texte(ctx); taille(16f * s); couleur(Palette.texte1); texte = d.zones.getOrNull(i)?.let { ns("$it min") } ?: "" })
            // Rangée horizontale : le trait prend la hauteur du texte (un FrameLayout lui donnait tout l'écran).
            val cadre = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
            val a = (traitsZones[i] * 255).roundToInt()
            cadre.addView(View(ctx).apply { setBackgroundColor((a shl 24) or (Palette.sante and 0xFFFFFF)) }, LinearLayout.LayoutParams(max(1, (3f * s).roundToInt()), LinearLayout.LayoutParams.MATCH_PARENT))
            cadre.addView(col, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { leftMargin = (10f * s).roundToInt() })
            zones.addView(cadre, LinearLayout.LayoutParams(((552f - 4 * 12f) / 5f * s).roundToInt(), LinearLayout.LayoutParams.WRAP_CONTENT).apply { if (i > 0) marginStart = (12f * s).roundToInt() })
        }
        noteFc.texte = if (d.bornes != null) d.fcMaxReference?.let { "Zones calculées sur une FC max de $it" } ?: "" else ""
        montre(noteFc, noteFc.texte.isNotEmpty())
        // Analyse écrite : masquée s'il n'y en a pas, repliée par défaut, entière une fois ouverte.
        val an = d.analyse
        titreAnalyse.texte = an?.let { "Analyse" + (it.genere?.let { g -> " du " + SanteHisto.jourMois(g.toLocalDate(), aujourdhui.year) } ?: "") } ?: ""
        texteAnalyse.texte = an?.texte ?: ""
        enteteAnalyse.contentDescription = titreAnalyse.texte.toString() + ", déplier"
        montre(filetAnalyse, an != null)
        montre(enteteAnalyse, an != null)
    }

    override fun vider() {
        plage.texte = ""
        totaux.removeAllViews()
        liste.removeAllViews()
        rangees.clear()
        derniere = null
        // Les sports d'une ouverture précédente ne restent pas affichés pendant la lecture suivante.
        if (filtres != listOf("tous")) {
            filtres = listOf("tous")
            cadreFiltre.removeView(filtre)
            filtre = Selecteur(ctx, listOf("Tous")) { surFiltre(filtres[it]) }.also {
                it.echelle = echelleFiltre
                cadreFiltre.addView(it)
            }
        }
        montrerDetail(null)
    }
}

// ================================================================ Records

/** Onglet Records (maquette `SanteRecords`) : quatre familles, la date sous chaque valeur, chevron vers le détail. */
internal class OngletRecords(ctx: Context) : VueSante(ctx) {
    var surRecord: (SanteHisto.Record) -> Unit = {}
    private val intro = place(texte(Palette.texte3, 16f), 72f, 136f, 1136f)
    private val colonnes = listOf(72f, 364f, 656f, 948f).map { x -> place(LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }, x, 176f, 260f) }

    fun montrer(r: SanteHisto.Records?, aujourdhui: LocalDate) {
        for (c in colonnes) c.removeAllViews()
        if (r == null) {
            intro.texte = ""
            return
        }
        intro.texte = (r.depuis?.let { "Depuis le " + SanteHisto.jourMois(it, -1) + ", début des données automatiques. " } ?: "") +
            "Toucher un record ouvre le jour, la séance ou la semaine concernée."
        val seuilPas = r.seuilPas?.let { SanteHisto.milliers(it) }
        val seuilNuit = r.seuilNuit?.let { SanteHisto.duree(it) }
        fun famille(col: Int, nom: String?, cles: List<Pair<String, String>>) {
            val c = colonnes[col]
            val vus = cles.filter { r.records.containsKey(it.first) }
            if (nom != null && (vus.isNotEmpty() || col == 1)) c.addView(titreFamille(nom), margesTitre(c.childCount > 0))
            // Colonne sans titre (suite du Sport) : un titre invisible garde les lignes alignées sur les voisines.
            if (nom == null) c.addView(titreFamille(" ").apply { visibility = View.INVISIBLE }, margesTitre(false))
            for ((cle, titre) in vus) c.addView(ligne(r.records.getValue(cle), titre, aujourdhui))
        }
        famille(0, "Activité", listOf(
            "serie_pas" to ("Plus longue série à " + (seuilPas?.let { ns(it) } ?: "[seuil]") + " pas ou plus"),
            "journee_la_plus_active" to "Journée la plus active",
            "meilleure_semaine_pas" to "Semaine avec le plus de pas",
        ))
        famille(1, "Sport", listOf(
            "seance_la_plus_longue" to "Plus longue séance", "seance_la_plus_chargee" to "Séance la plus chargée",
            "zone5_la_plus_longue" to "Plus long temps en zone 5", "semaine_la_plus_sportive" to "Semaine avec le plus de sport",
        ))
        famille(2, null, listOf("course_la_plus_longue" to "Plus longue course", "meilleure_allure_5km" to "Meilleure allure sur 5 km et plus"))
        famille(3, "Sommeil", listOf(
            "nuit_la_plus_longue" to "Nuit la plus longue",
            "serie_nuits" to ("Plus longue série de nuits de " + (seuilNuit?.let { ns(it) } ?: "[seuil]") + " ou plus"),
            "sommeil_profond_le_plus_long" to "Sommeil profond le plus long",
        ))
        famille(3, "Cœur", listOf("fc_la_plus_basse" to "Cœur au repos le plus bas", "fc_la_plus_haute" to "Cœur au plus haut"))
    }

    private fun titreFamille(nom: String): View = TexteFondu(ctx).apply {
        peinture.typeface = Polices.texte(ctx); taille(20f * s); couleur(Palette.texte1); texte = nom
    }

    /** 24 px au-dessus d'une famille qui en suit une autre, 12 px dessous (marges : TexteFondu ignore le padding). */
    private fun margesTitre(espace: Boolean) = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
        topMargin = if (espace) (24f * s).roundToInt() else 0
        bottomMargin = (6f * s).roundToInt()
    }

    /** Valeur d'un record selon son unité. */
    private fun valeur(r: SanteHisto.Record): String {
        val v = r.valeur
        return when (r.unite) {
            "minutes", "min" -> SanteHisto.duree(v.roundToInt())
            "pas" -> SanteHisto.milliers(v.roundToInt()) + " pas"
            "jours" -> "${v.roundToInt()} jours"
            "nuits" -> "${v.roundToInt()} nuits"
            "m" -> SanteHisto.km(v.roundToInt())
            "km" -> SanteHisto.km((v * 1000).roundToInt())
            "s_par_km", "s/km" -> SanteHisto.allure(v.roundToInt())
            "bpm" -> "${v.roundToInt()} bpm"
            else -> SanteHisto.milliers(v.roundToInt())
        }
    }

    /** « du 3 au 14 septembre 2025 », « samedi 16 août 2025 », « natation, samedi 30 août 2025 ». */
    private fun quand(r: SanteHisto.Record, aujourdhui: LocalDate): String {
        // Records de course : le titre dit déjà le sport (maquette).
        val sport = r.sport?.takeIf { r.cle !in setOf("course_la_plus_longue", "meilleure_allure_5km") }
            ?.let { SanteDetail.libelleSeance(null, it).lowercase(java.util.Locale.FRANCE).takeIf { n -> n != "séance" } }
        val au = r.au ?: r.lundi?.plusDays(6)
        val du = r.du ?: r.lundi
        val t = when {
            du != null && au != null -> SanteHisto.plage(du, au, aujourdhui)
            r.date != null -> (if (r.cle == "fc_la_plus_basse") "nuit du " else "") + SanteHisto.jourSemaine(r.date) + " " + SanteHisto.jourMois(r.date, aujourdhui.year)
            else -> ""
        }
        // Meilleure allure : la distance de sa course (serveur 0.20.2), « 6,1 km, dimanche 29 juin 2025 ».
        val km = r.distanceM?.takeIf { r.cle == "meilleure_allure_5km" && it >= 100 }?.let { ns(SanteHisto.km(it)) }
        return listOfNotNull(sport, km, t.ifEmpty { null }).joinToString(", ")
    }

    private fun ligne(r: SanteHisto.Record, titre: String, aujourdhui: LocalDate): View {
        val cadre = FrameLayout(ctx).apply {
            isClickable = true
            isFocusable = true
            contentDescription = "$titre, ouvrir le détail"
            setOnClickListener { surRecord(r) }
        }
        // Titre et valeur s'arrêtent avant le chevron, la date (sous le chevron) prend toute la largeur.
        val chevron = (28f * s).roundToInt()
        val col = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL; setPadding(0, (8f * s).roundToInt(), 0, (8f * s).roundToInt()) }
        fun avantChevron() = LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { marginEnd = chevron }
        col.addView(TexteFondu(ctx).apply { peinture.typeface = Polices.texte(ctx); taille(15f * s); couleur(Palette.texte3); maxLignes = 2; texte = titre }, avantChevron())
        // Vert réservé au nouveau : un record battu dans les 7 derniers jours, avec « battu mardi ».
        val recent = r.battuLe?.let { !it.isBefore(aujourdhui.minusDays(6)) } == true
        val v = Morceaux().ajouter(ns(valeur(r)), 34f * s, if (recent) Palette.sante else Palette.texte1, Polices.chiffres(ctx, 400))
        if (recent) v.ajouter("   battu " + (if (r.battuLe == aujourdhui) "aujourd'hui" else SanteHisto.jourSemaine(r.battuLe!!)), 15f * s, Palette.sante, Polices.texte(ctx))
        col.addView(TexteFondu(ctx).apply { peinture.typeface = Polices.chiffres(ctx, 400); taille(34f * s); texte = v.sb }, avantChevron())
        col.addView(TexteFondu(ctx).apply { peinture.typeface = Polices.texte(ctx); taille(15f * s); couleur(Palette.texte2); texte = quand(r, aujourdhui) })
        cadre.addView(View(ctx).apply { setBackgroundColor(Palette.filet) }, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, max(1, (s * 0.5f).roundToInt())))
        cadre.addView(col)
        cadre.addView(Chevron(ctx, '>').apply { echelle = s; couleur = Palette.texte3 }, FrameLayout.LayoutParams((24f * s).roundToInt(), (24f * s).roundToInt(), Gravity.END or Gravity.CENTER_VERTICAL))
        return cadre
    }

    override fun vider() {
        intro.texte = ""
        for (c in colonnes) c.removeAllViews()
    }
}
