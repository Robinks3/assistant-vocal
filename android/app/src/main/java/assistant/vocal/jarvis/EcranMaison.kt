package assistant.vocal.jarvis

import android.app.AlertDialog
import android.content.Context
import android.graphics.Canvas
import android.graphics.Color
import android.graphics.Paint
import android.graphics.RectF
import android.graphics.Typeface
import android.graphics.drawable.GradientDrawable
import android.os.SystemClock
import android.text.TextPaint
import android.text.TextUtils
import android.util.TypedValue
import android.view.Gravity
import android.view.MotionEvent
import android.view.View
import android.view.ViewConfiguration
import android.widget.FrameLayout
import android.widget.HorizontalScrollView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import java.util.Locale
import kotlin.math.abs

/**
 * Écran Maison connectée de la tablette (0.17.0), ouvert par un toucher sur la bulle Maison. Résumé,
 * filtre par pièce (et « Musique et télé », « Aspirateur »), une tuile par appareil : toucher pour
 * allumer ou éteindre, glisser de gauche à droite pour la luminosité ou le volume, appui long pour la
 * couleur, le blanc ou la source. « Tout éteindre (pièces communes) » et un emplacement réservé au plan.
 *
 * Rien de l'occupant protégé n'est montré (Appareils.montres), sauf ses lumières quand c'est lui qui est reconnu.
 * Chaque commande part par Etat.actionService, vérifiée par Securite.kt avec la personne reconnue
 * (Maison.commande), puis par la passerelle. L'état affiché revient de Home Assistant (relu toutes les
 * 3 s tant que l'écran est ouvert), le choix fait au doigt est montré tout de suite en attendant.
 *
 * 0.17.2 : un groupe de lampes (« Cuisine », « Chevets Sacha ») n'a plus qu'une tuile, qui pilote tout le
 * groupe, avec « 2 lampes » et une flèche. La flèche ou un appui long déplient ses lampes dans un
 * sous-niveau juste sous sa rangée (Appareils.regrouper), un appui long sur le groupe déplié ouvre ses
 * réglages fins.
 *
 * 0.17.4 : l'emplacement du plan accueille la vue 3D de l'appartement (Maison3dView, page de la session
 * de photogrammétrie). Elle reçoit l'état de chaque lumière à chaque mise à jour, et un toucher sur une
 * lampe en 3D suit exactement le chemin d'un toucher de tuile (toucher, donc Securite.kt puis la passerelle).
 */
internal class EcranMaison(private val ctx: Context, private val fermer: () -> Unit) {

    private fun dp(v: Int): Int = Decor.dp(ctx, v.toFloat())

    private fun texte(taille: Float, couleur: Int, police: String? = null) = TextView(ctx).apply {
        setTextSize(TypedValue.COMPLEX_UNIT_SP, taille)
        setTextColor(couleur)
        // Instrument Sans, comme l'accueil de la tablette (0.18.0).
        typeface = Polices.depuis(ctx, police)
    }

    private val resume = texte(17f, Couleur.TEXTE_2)
    private val filtres = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
    private val grille = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }
    private val message = texte(15f, Decor.eclaircir(Couleur.ORANGE, 0.1f)).apply { visibility = View.GONE }
    private val vide = texte(16f, Couleur.TEXTE_2).apply { visibility = View.GONE }

    private var filtre = Appareils.FILTRE_TOUTES
    private var montres: List<Appareils.Appareil> = emptyList()
    private var cleFiltres = ""
    private var cleGrille = ""
    /** Tuiles par appareil (une lampe de deux groupes dépliés en a deux). */
    private val tuiles = HashMap<String, ArrayList<TuileAppareil>>()
    /** Groupes de lampes dépliés (0.17.2). */
    private val deplies = HashSet<String>()
    /** État prévu après un toucher, montré 4 s le temps que HA le confirme. */
    private val prevus = HashMap<String, Pair<Appareils.Appareil, Long>>()
    private var messageLocal = ""
    private var messageLocalLe = 0L
    /** Vue 3D de l'appartement, créée au premier affichage (une WebView coûte), libérée avec l'écran. */
    private var vue3d: Maison3dView? = null
    private val cadre3d = FrameLayout(ctx)
    /** Dernier état envoyé à la vue 3D par lumière, pour ne renvoyer que ce qui change. */
    private val envoyes3d = HashMap<String, String>()
    private var appareils3d: List<Appareils.Appareil> = emptyList()
    /** Boîte de dialogue ouverte (appui long, tout éteindre), fermée avec l'écran. */
    private var dialogueOuvert: AlertDialog? = null

    /** L'écran se ferme (Retour, Fermer, pièce vide) : sa boîte de dialogue aussi. */
    fun fermerDialogues() {
        dialogueOuvert?.dismiss()
        dialogueOuvert = null
    }

    val vue: View

    init {
        val entete = LinearLayout(ctx).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            addView(texte(24f, Couleur.AMBRE, "sans-serif-light").apply { text = "Maison" }, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            addView(bouton("Tout éteindre (pièces communes)", Decor.assombrir(Couleur.AMBRE, 0.55f)) { toutEteindre() },
                LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, dp(44)))
            addView(bouton("Fermer", Couleur.CHAMP) { fermer() },
                LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, dp(44)).apply { marginStart = dp(12) })
        }
        val defile = HorizontalScrollView(ctx).apply {
            isHorizontalScrollBarEnabled = false
            addView(filtres)
        }
        // Vue 3D de l'appartement (0.17.4), à la place de l'ancien emplacement réservé au plan.
        val plan = cadre3d.apply {
            background = GradientDrawable().apply {
                cornerRadius = dp(18).toFloat()
                setColor(Palette.fond)
                setStroke(maxOf(1, dp(1)), Palette.maisonCadre3d)
            }
            clipToOutline = true
            outlineProvider = android.view.ViewOutlineProvider.BACKGROUND
        }
        val pile = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(32), dp(20), dp(32), dp(24))
            addView(entete, marge(0))
            addView(resume, marge(10))
            addView(defile, marge(14))
            addView(message, marge(12))
            addView(vide, marge(18))
            addView(grille, marge(16))
            addView(plan, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(420)).apply { topMargin = dp(20) })
        }
        vue = ScrollView(ctx).apply {
            isFillViewport = true
            isVerticalScrollBarEnabled = false
            setBackgroundColor(Couleur.PANNEAU)
            isClickable = true
            addView(pile)
            visibility = View.GONE
        }
    }

    private fun marge(haut: Int) =
        LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(haut) }

    private fun bouton(libelle: String, couleur: Int, action: () -> Unit) = texte(15f, Couleur.TEXTE, "sans-serif-medium").apply {
        text = libelle
        gravity = Gravity.CENTER
        setPadding(dp(18), 0, dp(18), 0)
        background = Decor.fondBouton(ctx, couleur, 14f)
        isClickable = true
        setOnClickListener { action() }
    }

    // ------------------------------------------------------------ mise à jour

    fun maj(e: Etat.Instantane) {
        if (vue.visibility != View.VISIBLE) return
        val personne = e.quiParle()
        montres = Appareils.montres(e.appareils, personne).map { prevu(it) }
        maj3d(montres)
        val allumees = Appareils.lumieresAllumees(e.appareils.map { prevu(it) }, personne)
        resume.text = when {
            e.appareils.isEmpty() && !e.enMarche -> "${ConfigMaison.NOM_ASSISTANT} est à l'arrêt : appareils indisponibles"
            e.appareils.isEmpty() -> "Lecture des appareils dans Home Assistant..."
            else -> Appareils.resume(allumees)
        }
        majFiltres()
        majGrille()
        val t = SystemClock.elapsedRealtime()
        val texte = when {
            e.brefLe > messageLocalLe && t - e.brefLe < DUREE_MESSAGE_MS -> e.bref
            t - messageLocalLe < DUREE_MESSAGE_MS -> messageLocal
            else -> ""
        }
        message.text = texte
        message.visibility = if (texte.isEmpty()) View.GONE else View.VISIBLE
    }

    // ------------------------------------------------------------ vue 3D (0.17.4)

    private fun maj3d(liste: List<Appareils.Appareil>) {
        appareils3d = liste
        val v = vue3d ?: Maison3dView(ctx).also { nouvelle ->
            vue3d = nouvelle
            // Page prête : les lumières déjà allumées le sont tout de suite, sans s'allumer une à une (0.17.5).
            nouvelle.surPrete = {
                // Palette de l'appli posée au chargement (0.18.1), avant les états des lampes.
                nouvelle.teintes()
                nouvelle.palette()
                envoyes3d.clear()
                val lot = org.json.JSONObject()
                for (a in appareils3d) {
                    val e = Maison3d.etat3d(a) ?: continue
                    envoyes3d[a.id] = e.toString()
                    lot.put(a.id, e)
                }
                nouvelle.poser(lot)
            }
            nouvelle.surBasculer = { entite, on -> touche3d(entite, on) }
            cadre3d.addView(nouvelle, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        }
        envoyer3d(liste)
    }

    /** Ne renvoie à la page que les lampes, télés et enceintes dont ce qu'elle affiche a changé : état, luminosité,
     *  couleur, chaleur, volume (la clé est l'état réduit lui-même, 0.42.0). La vue met en file d'attente
     *  tant que la page n'est pas prête, puis surPrete renvoie tout. */
    private fun envoyer3d(liste: List<Appareils.Appareil>) {
        val v = vue3d ?: return
        for (a in liste) {
            val e = Maison3d.etat3d(a) ?: continue
            val cle = e.toString()
            if (envoyes3d[a.id] == cle) continue
            envoyes3d[a.id] = cle
            v.etat(a.id, e)
        }
    }

    /** Toucher une lampe en 3D : même chemin qu'un toucher de tuile, la page attend le vrai état. */
    private fun touche3d(entite: String, on: Boolean) {
        // La page parle de ses propres entités : on retrouve l'appareil HA derrière (correspondances, 0.42.0).
        val a = appareils3d.firstOrNull { it.id == entite } ?: appareils3d.firstOrNull { Maison3dPont.entiteVue(it.id) == entite }
        if (a == null) {
            montrer("Lampe inconnue de Home Assistant : $entite")
            return
        }
        if (a.allume == on) {
            envoyes3d.remove(a.id)  // la page revient d'elle-même au vrai état
            envoyer3d(listOf(a))
            return
        }
        toucher(a)
    }

    /** Vol de caméra vers ces lumières, depuis l'extérieur (surimpression après une action). */
    fun montrer3d(entites: List<String>) = vue3d?.montrer(entites)

    /** À appeler quand l'écran disparaît pour de bon (nouvelle interface, activité détruite). */
    fun liberer() {
        vue3d?.liberer()
        vue3d = null
        envoyes3d.clear()
        cadre3d.removeAllViews()
    }

    /** L'état prévu remplace celui de HA tant qu'il n'est pas confirmé (4 s au plus). */
    private fun prevu(a: Appareils.Appareil): Appareils.Appareil {
        val (p, le) = prevus[a.id] ?: return a
        if (SystemClock.elapsedRealtime() - le > ATTENTE_MS || (p.etat == a.etat && p.luminosite == a.luminosite && p.volume == a.volume)) {
            prevus.remove(a.id)
            return a
        }
        return p
    }

    private fun majFiltres() {
        val liste = Appareils.filtres(montres)
        if (liste.none { it.first == filtre }) filtre = Appareils.FILTRE_TOUTES
        val cle = liste.joinToString("|") { it.first } + "#" + filtre
        if (cle == cleFiltres) return
        cleFiltres = cle
        filtres.removeAllViews()
        for ((i, f) in liste.withIndex()) {
            val actif = f.first == filtre
            filtres.addView(texte(15f, if (actif) Palette.texteSurClair else Couleur.TEXTE_2, "sans-serif-medium").apply {
                text = f.second
                setPadding(dp(16), dp(9), dp(16), dp(9))
                background = if (actif) Decor.fondBouton(ctx, Couleur.AMBRE, 18f) else Decor.uni(ctx, Palette.maisonFiltre, 18f)
                isClickable = true
                setOnClickListener {
                    filtre = f.first
                    cleGrille = ""
                    majFiltres()
                    majGrille()
                }
            }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
                if (i > 0) marginStart = dp(8)
            })
        }
    }

    private fun majGrille() {
        val liste = Appareils.filtrer(montres, filtre)
        // Un groupe de lampes : une seule tuile, ses lampes dans un sous-niveau qu'on déplie (0.17.2).
        val entrees = Appareils.regrouper(liste)
        vide.text = if (montres.isEmpty()) "" else "Aucun appareil ici"
        vide.visibility = if (liste.isEmpty() && montres.isNotEmpty()) View.VISIBLE else View.GONE
        val cle = filtre + "#" + entrees.joinToString(",") { t -> t.appareil.id + t.lampes.joinToString("+", "[", "]") { it.id } } +
            "#" + deplies.sorted().joinToString(",")
        if (cle != cleGrille) {
            cleGrille = cle
            grille.removeAllViews()
            tuiles.clear()
            for ((r, rang) in entrees.chunked(COLONNES).withIndex()) {
                val rangee = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
                grille.addView(rangee, marge(if (r == 0) 0 else 12))
                remplirRangee(rangee, rang.map { it.appareil }, 124)
                // Lampes des groupes dépliés de cette rangée, juste dessous, en retrait.
                for (t in rang) if (t.groupe && t.lampes.isNotEmpty() && t.appareil.id in deplies) {
                    grille.addView(sousNiveau(t), marge(10).apply { marginStart = dp(28) })
                }
            }
        }
        for (t in entrees) {
            // Un groupe sans ses lampes dans ce filtre reste une tuile simple, « (groupe) », sans flèche.
            val n = if (t.groupe) t.lampes.size else 0
            poser(t.appareil, n, t.appareil.id in deplies)
            for (l in t.lampes) poser(l, 0, false)
        }
    }

    /** Une rangée de [COLONNES] cases : les tuiles, puis des cases vides pour qu'elles gardent leur largeur. */
    private fun remplirRangee(rangee: LinearLayout, appareils: List<Appareils.Appareil>, hauteurDp: Int) {
        for ((i, a) in appareils.withIndex()) {
            val t = TuileAppareil(ctx).apply {
                surToucher = { toucher(it) }
                surRegler = { x, f -> regler(x, f) }
                surAppuiLong = { appuiLong(it) }
                surDeplier = { deplier(it) }
            }
            tuiles.getOrPut(a.id) { ArrayList() }.add(t)
            rangee.addView(t, LinearLayout.LayoutParams(0, dp(hauteurDp), 1f).apply { if (i > 0) marginStart = dp(12) })
        }
        for (k in appareils.size until COLONNES) {
            rangee.addView(View(ctx), LinearLayout.LayoutParams(0, dp(hauteurDp), 1f).apply { if (k > 0) marginStart = dp(12) })
        }
    }

    /** Sous-niveau d'un groupe déplié : un titre, puis ses lampes en tuiles un peu plus basses. */
    private fun sousNiveau(t: Appareils.Tuile): View {
        val boite = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(14), dp(10), dp(14), dp(14))
            background = GradientDrawable().apply {
                cornerRadius = dp(18).toFloat()
                setColor(Palette.maisonSousNiveau)
                setStroke(maxOf(1, dp(1)), Palette.maisonSousNiveauBord)
            }
        }
        boite.addView(texte(14f, Couleur.TEXTE_2).apply {
            text = "Lampes du groupe ${t.appareil.nom}"
        }, marge(0))
        for ((r, rang) in t.lampes.chunked(COLONNES).withIndex()) {
            val rangee = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
            boite.addView(rangee, marge(if (r == 0) 8 else 10))
            remplirRangee(rangee, rang, 104)
        }
        return boite
    }

    /** Pose l'appareil à jour sur toutes ses tuiles ([lampes] : nombre de lampes d'un groupe, 0 sinon). */
    private fun poser(a: Appareils.Appareil, lampes: Int, deplie: Boolean) {
        for (t in tuiles[a.id] ?: return) {
            t.lampes = lampes
            t.deplie = deplie
            t.appareil = a
        }
    }

    /** Flèche ou appui long sur un groupe : ses lampes se déplient ou se replient. */
    private fun deplier(a: Appareils.Appareil) {
        if (!deplies.remove(a.id)) deplies.add(a.id)
        // Grille refaite après le geste en cours : la tuile touchée n'est pas retirée pendant son toucher.
        grille.post { majGrille() }
    }

    // ------------------------------------------------------------ commandes

    private fun envoyer(c: Appareils.Commande?, prevu: Appareils.Appareil?) {
        if (c == null) return
        val action = Etat.actionService
        if (action == null) {
            montrer("${ConfigMaison.NOM_ASSISTANT} est à l'arrêt : commande non envoyée")
            return
        }
        // Réponse immédiate si la sécurité refuse (elle revérifie avant l'envoi, dans Maison.commande).
        Securite.verifier(c.verification(), personne = Etat.courant.quiParle())?.let {
            montrer("Je ne le fais pas : $it")
            return
        }
        if (prevu != null) {
            val t = SystemClock.elapsedRealtime()
            prevus[prevu.id] = prevu to t
            tuiles[prevu.id]?.forEach { it.appareil = prevu }
            // Un groupe pilote toutes ses lampes : leur tuile du sous-niveau suit tout de suite (0.17.2).
            if (prevu.domaine == "light" && prevu.membres.isNotEmpty()) {
                for (m in montres.filter { it.id in prevu.membres && it.id != prevu.id }) {
                    val p = m.copy(etat = prevu.etat, luminosite = if (prevu.etat == "on") prevu.luminosite ?: m.luminosite else null)
                    prevus[m.id] = p to t
                    tuiles[m.id]?.forEach { it.appareil = p }
                }
            }
        }
        action(c.service, c.corps, c.verification())
    }

    private fun toucher(a: Appareils.Appareil) {
        val c = Appareils.basculer(a)
        val etat = when (c?.service?.substringAfter('.')) {
            "turn_off" -> "off"
            "turn_on" -> "on"
            "media_pause" -> "paused"
            "media_play" -> "playing"
            "start" -> "cleaning"
            "return_to_base" -> "returning"
            else -> a.etat
        }
        envoyer(c, a.copy(etat = etat, luminosite = if (etat == "off") null else a.luminosite))
    }

    private fun regler(a: Appareils.Appareil, fraction: Float) {
        val c = Appareils.regler(a, fraction) ?: return
        val p = Math.round(fraction.coerceIn(0f, 1f) * 100)
        val prevu = if (a.domaine == "light") a.copy(etat = if (p <= 0) "off" else "on", luminosite = if (p <= 0) null else p)
        else a.copy(volume = Securite.plafonnerVolume(p / 100.0))
        envoyer(c, prevu)
    }

    /** Appui long : couleur et blanc pour une lumière, source pour la télé ou une enceinte. */
    private fun appuiLong(a: Appareils.Appareil) {
        val boite = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(22), dp(10), dp(22), dp(6))
        }
        var dialogue: AlertDialog? = null
        fun fermerApres(c: Appareils.Commande, prevu: Appareils.Appareil?) {
            envoyer(c, prevu)
            dialogue?.dismiss()
        }
        if (a.domaine == "light" && a.couleur) {
            boite.addView(texte(14f, Couleur.TEXTE_2).apply { text = "Couleur" }, marge(4))
            val rangee = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
            for ((i, c) in COULEURS.withIndex()) {
                rangee.addView(View(ctx).apply {
                    background = GradientDrawable().apply {
                        shape = GradientDrawable.OVAL
                        setColor(Color.rgb(c[0], c[1], c[2]))
                        setStroke(maxOf(1, dp(1)), Palette.pastilleBord)
                    }
                    contentDescription = "Couleur ${i + 1}"
                    isClickable = true
                    setOnClickListener { fermerApres(Appareils.couleur(a, c[0], c[1], c[2]), a.copy(etat = "on")) }
                }, LinearLayout.LayoutParams(dp(40), dp(40)).apply { if (i > 0) marginStart = dp(10) })
            }
            boite.addView(HorizontalScrollView(ctx).apply { addView(rangee) }, marge(8))
        }
        if (a.domaine == "light" && a.blanc) {
            boite.addView(texte(14f, Couleur.TEXTE_2).apply { text = "Blanc" }, marge(16))
            val rangee = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
            for ((i, b) in listOf("Chaud" to 2700, "Neutre" to 4000, "Froid" to 6000).withIndex()) {
                rangee.addView(bouton(b.first, Couleur.CHAMP) { fermerApres(Appareils.blanc(a, b.second), a.copy(etat = "on")) },
                    LinearLayout.LayoutParams(0, dp(44), 1f).apply { if (i > 0) marginStart = dp(8) })
            }
            boite.addView(rangee, marge(8))
        }
        if (a.domaine == "media_player" && a.sources.isNotEmpty()) {
            boite.addView(texte(14f, Couleur.TEXTE_2).apply { text = "Source" + if (a.source.isNotBlank()) " (actuelle : ${a.source})" else "" }, marge(4))
            val liste = LinearLayout(ctx).apply { orientation = LinearLayout.VERTICAL }
            for (s in a.sources) {
                liste.addView(texte(16f, if (s == a.source) Couleur.AMBRE else Couleur.TEXTE).apply {
                    text = s
                    setPadding(dp(4), dp(10), dp(4), dp(10))
                    isClickable = true
                    background = Decor.fondNeutre(ctx, 8f)
                    setOnClickListener { fermerApres(Appareils.source(a, s), null) }
                }, marge(0))
            }
            boite.addView(ScrollView(ctx).apply { addView(liste) }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(320)))
        }
        if (boite.childCount == 0) {
            montrer("Pas de réglage fin pour ${a.nom}")
            return
        }
        dialogue = AlertDialog.Builder(ctx)
            .setTitle(a.nom)
            .setView(boite)
            .setNegativeButton("Fermer", null)
            .show()
        dialogueOuvert = dialogue
    }

    private fun toutEteindre() {
        val c = Appareils.toutEteindre(montres)
        if (c == null) {
            montrer("Aucune lumière allumée dans les pièces communes")
            return
        }
        val ids = (0 until c.corps.getJSONArray("entity_id").length()).map { c.corps.getJSONArray("entity_id").getString(it) }
        val noms = montres.filter { it.id in ids }.map { it.nom }
        dialogueOuvert = AlertDialog.Builder(ctx)
            .setTitle("Tout éteindre (pièces communes)")
            .setMessage("Éteindre " + (if (noms.size == 1) "1 lumière" else "${noms.size} lumières") + " : " + noms.joinToString(", ") + " ?")
            .setPositiveButton("Éteindre") { _, _ ->
                val action = Etat.actionService ?: return@setPositiveButton montrer("${ConfigMaison.NOM_ASSISTANT} est à l'arrêt : commande non envoyée")
                Securite.verifier(c.verification(), personne = Etat.courant.quiParle())?.let {
                    montrer("Je ne le fais pas : $it")
                    return@setPositiveButton
                }
                val t = SystemClock.elapsedRealtime()
                for (a in montres.filter { it.id in ids }) prevus[a.id] = a.copy(etat = "off", luminosite = null) to t
                action(c.service, c.corps, c.verification())
                maj(Etat.courant)
            }
            .setNegativeButton("Annuler", null)
            .show()
    }

    private fun montrer(texte: String) {
        messageLocal = texte
        messageLocalLe = SystemClock.elapsedRealtime()
        message.text = texte
        message.visibility = View.VISIBLE
    }

    companion object {
        const val COLONNES = 4
        const val ATTENTE_MS = 4_000L
        const val DUREE_MESSAGE_MS = 8_000L
        /** Couleurs proposées à l'appui long : rouge, orange, ambre, vert, cyan, bleu, violet, rose. */
        val COULEURS = listOf(
            intArrayOf(255, 64, 48), intArrayOf(255, 140, 30), intArrayOf(255, 200, 87), intArrayOf(80, 220, 110),
            intArrayOf(60, 210, 230), intArrayOf(76, 141, 255), intArrayOf(170, 100, 255), intArrayOf(255, 105, 180),
        )
    }
}

/**
 * Tuile d'un appareil, dessinée en Canvas : nom, pièce, état lisible et barre de niveau (luminosité ou
 * volume). Toucher : [surToucher]. Glisser de gauche à droite : niveau suivi au doigt, envoyé au lâcher
 * ([surRegler]). Appui long : [surAppuiLong]. Fond presque noir, ambre quand l'appareil est allumé.
 * Groupe de lampes (0.17.2, [lampes] plus grand que 0) : « 2 lampes » sous le nom et une flèche en haut
 * à droite. La flèche, ou un appui long sur le groupe replié, déplie ses lampes ([surDeplier]).
 */
internal class TuileAppareil(ctx: Context) : View(ctx) {
    var appareil: Appareils.Appareil? = null
        set(v) {
            if (field == v) return
            field = v
            decrire()
            invalidate()
        }
    /** Nombre de lampes d'un groupe montré en une tuile, 0 pour un appareil seul. */
    var lampes = 0
        set(v) {
            if (field == v) return
            field = v
            decrire()
            invalidate()
        }
    /** Groupe déplié : ses lampes sont montrées dessous, la flèche pointe vers le haut. */
    var deplie = false
        set(v) {
            if (field == v) return
            field = v
            decrire()
            invalidate()
        }
    var surToucher: (Appareils.Appareil) -> Unit = {}
    var surRegler: (Appareils.Appareil, Float) -> Unit = { _, _ -> }
    var surAppuiLong: (Appareils.Appareil) -> Unit = {}
    var surDeplier: (Appareils.Appareil) -> Unit = {}

    private fun decrire() {
        val a = appareil
        contentDescription = when {
            a == null -> null
            lampes > 0 -> "${a.nom}, groupe de ${Appareils.nombreLampes(lampes)}, ${Appareils.etatLisible(a)}, " +
                if (deplie) "lampes montrées" else "appui long pour voir les lampes"
            else -> "${a.nom}, ${Appareils.etatLisible(a)}"
        }
    }

    /** La flèche d'un groupe : un carré de 56 dp en haut à droite de la tuile. */
    private fun surFleche(x: Float, y: Float): Boolean = lampes > 0 && x >= width - 56f * densite && y <= 56f * densite

    private val densite = resources.displayMetrics.density
    private val fond = Paint(Paint.ANTI_ALIAS_FLAG)
    private val bord = Paint(Paint.ANTI_ALIAS_FLAG).apply { style = Paint.Style.STROKE }
    private val pNom = TextPaint(Paint.ANTI_ALIAS_FLAG).apply {
        textSize = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP, 17f, resources.displayMetrics)
        typeface = Polices.texte(context, 500)
    }
    private val pPetit = TextPaint(Paint.ANTI_ALIAS_FLAG).apply { textSize = TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_SP, 13.5f, resources.displayMetrics) }
    private val pBarre = Paint(Paint.ANTI_ALIAS_FLAG)
    private val pFleche = Paint(Paint.ANTI_ALIAS_FLAG).apply {
        style = Paint.Style.STROKE
        strokeCap = Paint.Cap.ROUND
    }
    private val r = RectF()

    private val seuil = ViewConfiguration.get(ctx).scaledTouchSlop.toFloat()
    private var x0 = 0f
    private var y0 = 0f
    private var glisse = false
    private var appuiLongFait = false
    /** Niveau suivi au doigt pendant un glissé, ou -1. */
    private var niveauDoigt = -1f
    private var niveauDepart = 0f
    private val appuiLong = Runnable {
        appareil?.let {
            appuiLongFait = true
            // Groupe replié : l'appui long déplie ses lampes. Déplié, il ouvre ses réglages fins.
            if (lampes > 0 && !deplie) surDeplier(it) else surAppuiLong(it)
        }
    }

    init {
        isClickable = true
        isFocusable = true
    }

    private fun niveau(a: Appareils.Appareil): Float? = when {
        a.domaine == "light" && a.reglable -> (if (a.etat == "on") (a.luminosite ?: 100) else 0) / 100f
        a.domaine == "media_player" && a.volume != null -> a.volume.toFloat()
        else -> null
    }

    override fun onDraw(c: Canvas) {
        val a = appareil ?: return
        val allume = a.allume || a.etat == "playing"
        val rayon = 18f * densite
        r.set(densite, densite, width - densite, height - densite)
        fond.color = if (allume) Palette.tuileAllumee else Palette.tuileEteinte
        c.drawRoundRect(r, rayon, rayon, fond)
        bord.strokeWidth = maxOf(1f, densite)
        bord.color = if (allume) Decor.alpha(Couleur.AMBRE, 150) else Palette.tuileBord
        c.drawRoundRect(r, rayon, rayon, bord)
        val marge = 16f * densite
        val largeur = width - 2 * marge
        pNom.color = if (allume) Palette.tuileNomAllume else Palette.tuileNom
        // Groupe en une tuile (0.17.2) : son nom seul, « 2 lampes » dessous, la flèche à droite.
        val libelle = if (lampes == 0 && a.membres.isNotEmpty()) "${a.nom} (groupe)" else a.nom
        val placeNom = if (lampes > 0) largeur - 26f * densite else largeur
        val nom = TextUtils.ellipsize(libelle, pNom, placeNom.coerceAtLeast(0f), TextUtils.TruncateAt.END)
        c.drawText(nom, 0, nom.length, marge, marge + pNom.textSize * 0.9f, pNom)
        pPetit.color = Couleur.GRIS
        val sousTitre = if (lampes > 0) listOf(a.piece, Appareils.nombreLampes(lampes)).filter { it.isNotBlank() }.joinToString(", ") else a.piece
        val piece = TextUtils.ellipsize(sousTitre.ifBlank { " " }, pPetit, largeur, TextUtils.TruncateAt.END)
        c.drawText(piece, 0, piece.length, marge, marge + pNom.textSize + pPetit.textSize * 1.3f, pPetit)
        if (lampes > 0) {
            // Flèche : vers le bas replié, vers le haut déplié.
            val fx = width - marge - 7f * densite
            val fy = marge + 8f * densite
            val d = 6f * densite
            val sens = if (deplie) -1f else 1f
            pFleche.color = if (allume) Decor.alpha(Couleur.AMBRE, 220) else Palette.tuileFleche
            pFleche.strokeWidth = 2f * densite
            c.drawLine(fx - d, fy - sens * d / 2f, fx, fy + sens * d / 2f, pFleche)
            c.drawLine(fx, fy + sens * d / 2f, fx + d, fy - sens * d / 2f, pFleche)
        }
        pPetit.color = if (allume) Couleur.AMBRE else Couleur.TEXTE_2
        val n = niveau(a)
        val etat = if (niveauDoigt >= 0f) "${Math.round(niveauDoigt * 100)} %" else Appareils.etatLisible(a)
        val e = TextUtils.ellipsize(etat, pPetit, largeur, TextUtils.TruncateAt.END)
        c.drawText(e, 0, e.length, marge, height - marge - 14f * densite, pPetit)
        if (n != null) {
            // Barre de niveau en bas de la tuile.
            val y = height - marge - 4f * densite
            val h = 5f * densite
            pBarre.color = Palette.tuileBarre
            c.drawRoundRect(marge, y - h / 2, width - marge, y + h / 2, h, h, pBarre)
            val f = (if (niveauDoigt >= 0f) niveauDoigt else n).coerceIn(0f, 1f)
            pBarre.color = Couleur.AMBRE
            if (f > 0f) c.drawRoundRect(marge, y - h / 2, marge + largeur * f, y + h / 2, h, h, pBarre)
        }
    }

    @android.annotation.SuppressLint("ClickableViewAccessibility")
    override fun onTouchEvent(ev: MotionEvent): Boolean {
        val a = appareil ?: return false
        when (ev.actionMasked) {
            MotionEvent.ACTION_DOWN -> {
                x0 = ev.x
                y0 = ev.y
                glisse = false
                appuiLongFait = false
                niveauDoigt = -1f
                niveauDepart = niveau(a) ?: 0f
                postDelayed(appuiLong, ViewConfiguration.getLongPressTimeout().toLong())
                isPressed = true
                return true
            }
            MotionEvent.ACTION_MOVE -> {
                val dx = ev.x - x0
                val dy = ev.y - y0
                if (!glisse && (abs(dx) > seuil || abs(dy) > seuil)) {
                    removeCallbacks(appuiLong)
                    // Glissé horizontal sur un appareil réglable : niveau. Sinon le défilement reprend la main.
                    if (abs(dx) > abs(dy) && niveau(a) != null) {
                        glisse = true
                        parent?.requestDisallowInterceptTouchEvent(true)
                    }
                }
                if (glisse && width > 0) {
                    niveauDoigt = (niveauDepart + (ev.x - x0) / (width * 0.8f)).coerceIn(0f, 1f)
                    invalidate()
                }
                return true
            }
            MotionEvent.ACTION_UP -> {
                removeCallbacks(appuiLong)
                isPressed = false
                when {
                    glisse -> surRegler(a, niveauDoigt.coerceIn(0f, 1f))
                    !appuiLongFait && abs(ev.x - x0) <= seuil && abs(ev.y - y0) <= seuil -> {
                        performClick()
                        // Sur la flèche d'un groupe : déplier ou replier, sans allumer ni éteindre.
                        if (surFleche(x0, y0)) surDeplier(a) else surToucher(a)
                    }
                }
                glisse = false
                niveauDoigt = -1f
                invalidate()
                return true
            }
            MotionEvent.ACTION_CANCEL -> {
                removeCallbacks(appuiLong)
                isPressed = false
                glisse = false
                niveauDoigt = -1f
                invalidate()
                return true
            }
        }
        return false
    }

    override fun onDetachedFromWindow() {
        removeCallbacks(appuiLong)
        super.onDetachedFromWindow()
    }
}
