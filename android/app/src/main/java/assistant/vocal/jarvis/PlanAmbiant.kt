package assistant.vocal.jarvis

import android.content.Context
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.view.MotionEvent
import android.view.View
import android.widget.FrameLayout
import org.json.JSONArray
import org.json.JSONObject

/**
 * Plan 3D de l'appartement au centre de l'accueil de la tablette (0.18.0). La page 3D (assets/maison3d)
 * montre l'appartement de nuit, les pièces allumées selon Home Assistant, et tourne lentement autour de
 * lui (un tour en 10 min) : c'est aussi sa protection contre le marquage de l'écran OLED.
 *
 * Il reprend la logique de l'aperçu 3D de la 0.17.4 à la 0.17.6 : après une action sur des lumières, la
 * page joue l'action (vol de caméra vers la pièce, flux de particules, bascule, ondes), l'état HA des
 * lampes visées étant retenu le temps de la bascule, puis la caméra revient à la vue large et reprend sa
 * rotation au bout de [DUREE_ACTION_MS].
 *
 * 0.18.1 (revues de design et de faisabilité) : plus d'étiquettes dans la page (la zone de texte dit les
 * pièces allumées), palette de l'appli envoyée au chargement, poussières dans les pièces allumées,
 * lumières en gris quand la maison ne répond plus. Une WebView permanente doit être robuste : processus de
 * rendu mort ou contexte WebGL perdu, la vue est recréée. Battement de la page toutes les 10 s : 30 s de
 * silence en régime vivant hors pause, elle est recréée. Hors régime vivant, pause (requestAnimationFrame
 * coupé et WebView.onPause) puis destruction au bout de [DESTRUCTION_MS] (la nuit, en écran noir, elle est
 * donc recréée chaque jour). Chaleur : rotation arrêtée et 12 images par seconde au plus, puis pause.
 * Toucher le plan ouvre l'écran Maison, toucher le noir autour de l'appartement montre la couche de service.
 *
 * 0.24.0, seconde passe de l'accueil (maquettes validées le 22/10/2026) : la page couvre toute la
 * fenêtre et cadre l'appartement dans la zone de l'état ([disposer] : sans musique, avec, à l'écoute), en
 * couleur ([intensite] 1 le jour, 0,2 le soir, 0,15 la nuit), avec un balancement de ± 25 degrés autour de 75
 * au lieu du tour complet. Elle montre la télé allumée et les enceintes qui jouent, et suit le régime de
 * l'accueil ([regime] : vivant ou en retrait).
 *
 * 0.27.0, la maison en grand (piste « mélange », canevas version 29) : [grand] fige la caméra et pose les étiquettes
 * des pièces ([etiquettes]), [choisir] cadre une pièce sous un voile et ses objets reçoivent des pastilles
 * ([pastilles]). En grand, un toucher n'ouvre plus rien lui-même : la page dit ce qui est sous le doigt
 * ([surDesigne] : une pastille, une pièce ou le vide) et l'accueil décide. Tout est gardé pour une page qui renaît.
 */
internal class PlanAmbiant(private val ctx: Context) {

    /** Toucher l'appartement (hors de l'écoute) : écran Maison connectée, posé par l'accueil. */
    var surToucher: () -> Unit = {}
    /** Toucher le noir autour de l'appartement : couche de service de l'accueil. */
    var surVide: () -> Unit = {}
    /** En grand (0.27.0) : ce qui est sous le doigt, `{genre, entite | id}` rendu par la page, ou null. */
    var surDesigne: (JSONObject?) -> Unit = {}

    /** Pixels CSS de la page par pixel de maquette (gardé pour la mise à l'échelle de la page). */
    var unite = 1f

    private val principal = Handler(Looper.getMainLooper())
    private var vue3d: Maison3dView? = null
    private var prete = false
    private var attenuee = false
    private var desaturee = false
    /** Niveau de chaleur : 0 normal, 1 modérée (rotation arrêtée, 12 images par seconde), 2 forte (pause). */
    private var chaleur = 0
    /** Instant où la vue a quitté le régime vivant (0 tant qu'elle y est). */
    private var horsVivantLe = 0L

    private var lumieres: List<Appareils.Appareil> = emptyList()
    /** Télé et enceintes (0.24.0), avec leur état et leur volume. */
    private var medias: List<Appareils.Appareil> = emptyList()
    /** Zone de l'appartement, intensité et régime voulus, renvoyés à une page qui renaît. */
    private var zone = Disposition.A
    private var intensite = 1f
    private var regime = 1f
    private var personne = ""
    /** Dernier état envoyé par lumière, pour n'envoyer que ce qui change. */
    private val envoyes = HashMap<String, String>()

    // Action en cours sur des lumières (logique de l'aperçu 3D, 0.17.5).
    private var effets: Map<String, String> = emptyMap()
    private var retenues: Set<String> = emptySet()
    private var demo = false
    private var aJouer = false
    private val finAction = Runnable { terminerAction() }
    private val liberation = Runnable {
        retenues = emptySet()
        envoyer()
    }

    val vue: FrameLayout = object : FrameLayout(ctx) {
        // La page ne reçoit aucun geste sur l'accueil : pas de bascule accidentelle d'une lampe.
        override fun onInterceptTouchEvent(ev: MotionEvent) = true

        private var x0 = 0f
        private var y0 = 0f

        override fun onTouchEvent(ev: MotionEvent): Boolean {
            when (ev.actionMasked) {
                MotionEvent.ACTION_DOWN -> { x0 = ev.x; y0 = ev.y }
                // Un doigt qui a glissé de plus de 24 dp n'est pas un toucher (rien ne part en grand par un geste).
                MotionEvent.ACTION_UP -> if (Math.hypot((ev.x - x0).toDouble(), (ev.y - y0).toDouble()) < Decor.dp(ctx, 24f)) toucher(ev.x, ev.y)
            }
            return true
        }
    }.apply {
        setBackgroundColor(Palette.fond)
        visibility = View.INVISIBLE
        alpha = 0f
        contentDescription = "Plan de l'appartement, toucher pour ouvrir la maison en grand"
    }

    private fun toucher(x: Float, y: Float) {
        val v = vue3d
        if (grandActif) {
            // En grand, rien n'ouvre l'écran Maison ni la couche de service : la page désigne, l'accueil décide.
            if (v == null || !prete) return
            v.designer(x, y) { d -> if (grandActif) surDesigne(d) }
            return
        }
        // Page pas encore prête : on ne sait pas où est l'appartement, la couche de service s'ouvre.
        if (v == null || !prete) {
            surVide()
            return
        }
        v.dansLePlan(x, y) { dedans -> if (dedans) surToucher() else surVide() }
    }

    /** Une action est en train d'être jouée par la page. */
    val enAction: Boolean get() = effets.isNotEmpty()

    /**
     * Posé à chaque pas de l'écran OLED : [opacite] (vie de l'écran), [montrable] (ni panneau, ni activité
     * cachée, ni écran éteint) et [vivant] (régime vivant : la page peut naître).
     */
    fun regler(opacite: Float, montrable: Boolean, vivant: Boolean) {
        val maintenant = SystemClock.elapsedRealtime()
        val avant = horsVivantLe
        horsVivantLe = if (vivant) 0L else if (horsVivantLe == 0L) maintenant else horsVivantLe
        // 0.21.1 : la destruction ne dépend plus de nouveaux appels (activité arrêtée la nuit, tic coupé) :
        // une minuterie la fait au bout de 10 min hors régime vivant, annulée au retour.
        if (vivant) principal.removeCallbacks(destruction)
        else if (avant == 0L) principal.postDelayed(destruction, DESTRUCTION_MS + 1_000L)
        // Hors régime vivant depuis 10 min : la WebView est détruite, elle renaîtra au retour de quelqu'un.
        if (!vivant && vue3d != null && maintenant - horsVivantLe > DESTRUCTION_MS) {
            android.util.Log.i(JOURNAL, "hors régime vivant depuis 10 min : vue détruite")
            detruire()
        }
        if (vivant && montrable && vue3d == null) creer()
        val v = vue3d
        val montrer = v != null && montrable && opacite > 0f
        if (montrer) {
            v!!.suspendre(chaleur >= 2)
            if (vue.visibility != View.VISIBLE) vue.visibility = View.VISIBLE
            // La WebView ne suit pas toujours la transparence de ses parents : fondus dans une couche matérielle.
            val couche = if (opacite < 1f) View.LAYER_TYPE_HARDWARE else View.LAYER_TYPE_NONE
            if (vue.layerType != couche) vue.setLayerType(couche, null)
            if (vue.alpha != opacite) vue.alpha = opacite
            // Page muette depuis 30 s alors qu'elle devrait vivre : elle est recréée.
            if (vivant && prete && !v.enPause && maintenant - v.battementLe > SILENCE_MS) {
                android.util.Log.w(JOURNAL, "page muette depuis ${(maintenant - v.battementLe) / 1000} s : vue recréée")
                detruire()
                creer()
            }
        } else {
            if (vue.visibility != View.INVISIBLE) vue.visibility = View.INVISIBLE
            vue.alpha = 0f
            v?.suspendre(true)
        }
    }

    private fun creer() {
        val v = Maison3dView(ctx, RESOLUTION)
        vue3d = v
        prete = false
        envoyes.clear()
        // Cachée jusqu'à ce que la page soit prête : son premier rendu passerait par-dessus le fondu.
        v.visibility = View.INVISIBLE
        v.surPrete = {
            prete = true
            v.jeuCouleur(intensite)
            v.palette()
            v.accueil(if (chaleur >= 1) 0 else PERIODE_TOUR_S, cadence(), AMPLITUDE_DEG, ANGLE_DEG)
            v.disposition(zone, 0)
            v.regime(regime, 0)
            allure(v)
            if (chaleur >= 1) v.cadence(CADENCE_CHAUD, CADENCE_CHAUD)
            if (attenuee) v.attenuer(OPACITE_ECOUTE, 0)
            if (desaturee) v.desaturer(true)
            envoyer(instant = true)
            if (aJouer) jouer(v)
            if (grandActif) renvoyerGrand(v)
            // Objets réglables de chaque pièce, une fois par page (ils ne changent qu'avec une nouvelle version).
            v.contenu { t -> if (t != null && vue3d === v) contenu = t }
            v.visibility = View.VISIBLE
        }
        v.surPerdue = { raison ->
            android.util.Log.w(JOURNAL, "vue perdue ($raison) : recréée au prochain pas en régime vivant")
            if (vue3d === v) {
                vue3d = null
                prete = false
                vue.removeAllViews()
            }
        }
        vue.addView(v, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
    }

    private val destruction = Runnable {
        if (horsVivantLe != 0L && vue3d != null && SystemClock.elapsedRealtime() - horsVivantLe > DESTRUCTION_MS) {
            android.util.Log.i(JOURNAL, "hors régime vivant depuis 10 min : vue détruite (minuterie)")
            detruire()
        }
    }

    private fun detruire() {
        vue3d?.liberer()
        vue3d = null
        prete = false
        vue.removeAllViews()
    }

    private fun cadence(): Int = if (chaleur >= 1) CADENCE_CHAUD else IMAGES_PAR_SECONDE

    /**
     * Chaleur de la tablette (statut thermique d'Android, ou température de la batterie) : 0 normale,
     * 1 modérée (rotation arrêtée, 12 images par seconde au plus), 2 forte (page en pause).
     */
    fun chaleur(niveau: Int) {
        val n = niveau.coerceIn(0, 2)
        if (n == chaleur) return
        chaleur = n
        android.util.Log.i(JOURNAL, "chaleur $n")
        val v = vue3d ?: return
        if (!prete) return
        v.cadence(cadence(), if (n >= 1) CADENCE_CHAUD else 30)
        if (n >= 1) v.rotation(0, cadence()) else v.balancement(PERIODE_TOUR_S, cadence(), AMPLITUDE_DEG, ANGLE_DEG)
        if (n >= 2) v.suspendre(true)
    }

    /**
     * Zone de la fenêtre où cadrer l'appartement (0.24.0), en [dureeMs] (0 : d'un coup, écran en veille).
     * Gardée pour une page qui renaît.
     */
    fun disposer(z: Disposition.Zone, dureeMs: Int) {
        if (z == zone) return
        zone = z
        if (prete) vue3d?.disposition(z, dureeMs)
    }

    /** Clarté de l'appartement (0.24.0) : 1 le jour, 0,2 le soir, 0,15 la nuit. */
    fun intensite(v: Float) {
        if (v == intensite) return
        intensite = v
        if (prete) vue3d?.intensite(v)
    }

    /**
     * Régime de l'accueil (0.24.0) : 1 vivant, 0 en retrait, transition en [dureeMs]. En retrait, poussières
     * coupées et balancement ralenti (1 200 s), comme le demande la revue de l'accueil.
     */
    fun regime(niveau: Float, dureeMs: Int) {
        if (niveau == regime) return
        regime = niveau
        val v = vue3d ?: return
        if (!prete) return
        v.regime(niveau, dureeMs)
        allure(v)
    }

    /** Poussières et balancement selon le régime et la chaleur. */
    private fun allure(v: Maison3dView) {
        v.poussieres(regime > 0f)
        if (chaleur == 0) v.balancement(if (regime > 0f) PERIODE_TOUR_S else PERIODE_RETRAIT_S, cadence(), AMPLITUDE_DEG, ANGLE_DEG)
    }

    // ------------------------------------------------------------ la maison en grand (0.27.0)

    private var grandActif = false
    private var taillePastille = 56f
    private var policeEtiquette = 20f
    private var voileOpacite = 0.65f
    private var choisie: String? = null
    private var etiquettesEnvoyees = ""
    private var pastillesEnvoyees = ""
    private var etiquettesVoulues = JSONArray()
    private var pastillesVoulues = JSONArray()

    /** Objets réglables de chaque pièce (texte JSON de maison3d.contenu), lus quand la page est prête. */
    var contenu: String? = null
        private set

    /** La page est prête et sait se mettre en grand. */
    val pretPourGrand: Boolean get() = prete && vue3d != null && contenu != null

    /**
     * Maison en grand ou non (0.27.0) : [taille] des pastilles et [police] des étiquettes en pixels de maquette,
     * convertis en pixels CSS de la page par [unite]. En sortant, pièce, étiquettes et pastilles sont oubliées.
     */
    fun grand(actif: Boolean, taille: Float = taillePastille, police: Float = policeEtiquette) {
        if (actif == grandActif) return
        grandActif = actif
        taillePastille = taille
        policeEtiquette = police
        if (!actif) {
            choisie = null
            etiquettesVoulues = JSONArray()
            pastillesVoulues = JSONArray()
        }
        etiquettesEnvoyees = ""
        pastillesEnvoyees = ""
        vue.contentDescription = if (actif) "Maison en grand, toucher une pièce pour la régler" else "Plan de l'appartement, toucher pour ouvrir la maison en grand"
        val v = vue3d ?: return
        if (prete) {
            v.grand(actif, taille * unite, police * unite)
            if (actif) v.voile(voileOpacite)
        }
    }

    /** Pièce choisie (null : la maison entière), cadrée en [dureeMs]. */
    fun choisir(piece: String?, dureeMs: Int) {
        if (!grandActif) return
        choisie = piece
        pastillesEnvoyees = ""
        if (piece == null) pastillesVoulues = JSONArray()
        if (prete) vue3d?.choisir(piece, dureeMs)
    }

    /** Étiquettes des pièces de la vue entière, envoyées seulement quand elles changent. */
    fun etiquettes(liste: JSONArray) {
        etiquettesVoulues = liste
        val t = liste.toString()
        if (!grandActif || t == etiquettesEnvoyees || !prete) return
        etiquettesEnvoyees = t
        vue3d?.etiquettes(liste)
    }

    /** Pastilles de la pièce choisie, envoyées seulement quand elles changent. */
    fun pastilles(liste: JSONArray) {
        pastillesVoulues = liste
        val t = liste.toString()
        if (!grandActif || t == pastillesEnvoyees || !prete) return
        pastillesEnvoyees = t
        vue3d?.pastilles(liste)
    }

    /** Voile sur les autres pièces : 0,65 le jour, 0,7 le soir. */
    fun voile(opacite: Float) {
        if (opacite == voileOpacite) return
        voileOpacite = opacite
        if (prete && grandActif) vue3d?.voile(opacite)
    }

    /** Page qui renaît pendant la maison en grand : tout est reposé d'un coup. */
    private fun renvoyerGrand(v: Maison3dView) {
        v.grand(true, taillePastille * unite, policeEtiquette * unite)
        v.voile(voileOpacite)
        etiquettesEnvoyees = etiquettesVoulues.toString()
        v.etiquettes(etiquettesVoulues)
        choisie?.let { p ->
            v.choisir(p, 0)
            pastillesEnvoyees = pastillesVoulues.toString()
            v.pastilles(pastillesVoulues)
        }
    }

    /** Version de la page 3D (maison3d.version), affichée dans la couche de service. */
    val versionPage: String get() = vue3d?.versionPage ?: ""

    /** Télé et enceintes lues dans Home Assistant (0.24.0) : télé allumée, ondes des enceintes qui jouent. */
    fun majMedias(lus: List<Appareils.Appareil>) {
        if (lus === medias0) return
        medias0 = lus
        medias = lus.filter { it.domaine == "media_player" }
        envoyer()
    }

    private var medias0: List<Appareils.Appareil>? = null

    /** Nouvelle lecture des lumières (toutes, avec leur pièce) et personne reconnue (règle 3). */
    fun maj(lues: List<Appareils.Appareil>, quiParle: String) {
        if (lues === lues0 && quiParle == personne) return
        lues0 = lues
        lumieres = lues.filter { it.domaine == "light" }
            .map { if (it.id in forcees) it.copy(etat = "on", luminosite = 60) else it }
        personne = quiParle
        envoyer()
    }

    /** Dernière liste reçue telle quelle, pour ne rien refaire tant qu'elle ne change pas. */
    private var lues0: List<Appareils.Appareil>? = null
    /** Démonstration : lumières montrées allumées sur le plan, sans rien envoyer à Home Assistant. */
    private var forcees: Set<String> = emptySet()

    /**
     * Démonstration par adb (appli de débogage) : ces lumières sont montrées allumées à 60 % sur le plan
     * pendant [dureeMs], puis le plan revient à l'état lu dans Home Assistant.
     */
    fun demoRepos(ids: Set<String>, dureeMs: Long) {
        forcees = ids
        val l = lues0 ?: emptyList()
        lues0 = null
        maj(l, personne)
        principal.postDelayed({
            forcees = emptySet()
            val r = lues0 ?: emptyList()
            lues0 = null
            maj(r, personne)
        }, dureeMs)
    }

    /** Lumières de la démonstration, montrées allumées (pour les phrases de l'accueil). */
    fun lumieresMontrees(lues: List<Appareils.Appareil>): List<Appareils.Appareil> =
        if (forcees.isEmpty()) lues else lues.map { if (it.id in forcees) it.copy(etat = "on", luminosite = 60) else it }

    /** Écoute : le plan s'assombrit à 28 % (la page s'en charge, la WebView suit mal l'opacité). */
    fun attenuer(oui: Boolean) {
        if (oui == attenuee) return
        attenuee = oui
        if (prete) vue3d?.attenuer(if (oui) OPACITE_ECOUTE else 1f, if (oui) 450 else 600)
    }

    /** La maison ne répond plus : les lumières du plan passent en gris (l'état montré n'est plus sûr). */
    fun desaturer(oui: Boolean) {
        if (oui == desaturee) return
        desaturee = oui
        if (prete) vue3d?.desaturer(oui)
    }

    /**
     * Action sur ces lumières (entité vers effet : allumer, eteindre, regler ou basculer). [essai] :
     * démonstration, l'état HA des lampes visées n'est jamais montré pendant l'action.
     */
    fun action(voulus: Map<String, String>, essai: Boolean) {
        if (voulus.isEmpty()) return
        // Un basculement est tranché avec l'état lu dans HA, déjà basculé quand la carte arrive.
        effets = voulus.mapValues { (id, e) ->
            if (e != "basculer") e else if (lumieres.firstOrNull { it.id == id }?.allume == true) "allumer" else "eteindre"
        }
        demo = essai
        // Retenues : les lumières visées, leurs ampoules, et les groupes qui contiennent l'une d'elles.
        val visees = effets.keys.toMutableSet()
        for (id in effets.keys) lumieres.firstOrNull { it.id == id }?.let { visees.addAll(it.membres) }
        retenues = visees + lumieres.filter { g -> g.membres.any { it in visees } }.map { it.id }
        principal.removeCallbacks(finAction)
        principal.removeCallbacks(liberation)
        val v = vue3d
        if (v != null && prete) jouer(v) else aJouer = true
        principal.postDelayed(finAction, DUREE_ACTION_MS)
    }

    /** L'action d'abord (lampes visées dans leur état d'avant, joué par la page), puis les autres lumières. */
    private fun jouer(v: Maison3dView) {
        aJouer = false
        val action = JSONObject()
        for ((id, effet) in effets) {
            val o = JSONObject().put("effet", effet)
            val a = lumieres.firstOrNull { it.id == id }
            if (a != null && !demo) {
                val e = Maison3d.etatHa(a)
                o.put("state", e.getString("state")).put("attributes", e.getJSONObject("attributes"))
            }
            action.put(id, o)
        }
        v.action(action)
        envoyes.clear()
        envoyer(instant = true)
        if (!demo) principal.postDelayed(liberation, LIBERATION_MS)
    }

    private fun terminerAction() {
        principal.removeCallbacks(liberation)
        effets = emptyMap()
        retenues = emptySet()
        demo = false
        aJouer = false
        if (prete) vue3d?.ensemble(RETOUR_MS)
        envoyer()
    }

    private fun envoyer(instant: Boolean = false) {
        val v = vue3d ?: return
        if (!prete) return
        val lot = JSONObject()
        for (a in lumieres) {
            if (a.id in retenues) continue
            // Rien de l'occupant protégé sur le plan, sauf ses lumières quand c'est lui qui est reconnu (règle 3).
            val e = if (Appareils.visible(a, personne)) Maison3d.etatHa(a) else ETEINTE
            val cle = e.toString()
            if (envoyes[a.id] == cle) continue
            envoyes[a.id] = cle
            if (instant) lot.put(a.id, e) else v.etat(a.id, e)
        }
        for (m in medias) {
            val e = if (Appareils.visible(m, personne)) etatMedia(m) else ETEINTE
            val cle = e.toString()
            if (envoyes[m.id] == cle) continue
            envoyes[m.id] = cle
            if (instant) lot.put(m.id, e) else v.etat(m.id, e)
        }
        if (lot.length() > 0) v.poser(lot)
    }

    fun liberer() {
        principal.removeCallbacksAndMessages(null)
        detruire()
        effets = emptyMap()
        retenues = emptySet()
        surToucher = {}
        surVide = {}
        surDesigne = {}
    }

    companion object {
        private const val JOURNAL = "JarvisPlan3d"
        /**
         * Balancement de l'accueil (0.24.0) : aller et retour en 10 min, ± 25 degrés autour de 75 (le grand côté
         * de l'appartement couché dans une zone en paysage), 10 images par seconde au repos, 30 pendant une action.
         */
        const val PERIODE_TOUR_S = 600
        const val IMAGES_PAR_SECONDE = 10
        const val AMPLITUDE_DEG = 25f
        /** En retrait, le balancement ralentit : aller et retour en 20 min. */
        const val PERIODE_RETRAIT_S = 1200
        const val ANGLE_DEG = 75f
        /** Chaleur modérée : rotation arrêtée, 12 images par seconde au plus, action comprise. */
        const val CADENCE_CHAUD = 12
        /** Résolution de la page (pixels de toile par pixel CSS) : 1,25 suffit à 2,25 de densité. */
        const val RESOLUTION = 1.25f
        /** Pendant l'écoute, le plan s'assombrit à 28 % (maquette). */
        const val OPACITE_ECOUTE = 0.28f
        /** La caméra revient à la vue large une dizaine de secondes après l'action. */
        const val DUREE_ACTION_MS = 10_000L
        const val RETOUR_MS = 1_600
        /** L'état HA des lampes visées est montré après la bascule de la page (1,15 s) et son effet. */
        const val LIBERATION_MS = 2_400L
        /** Page muette depuis 30 s en régime vivant : recréée (battement toutes les 10 s). */
        const val SILENCE_MS = 30_000L
        /** Hors régime vivant depuis 10 min : WebView détruite. */
        const val DESTRUCTION_MS = 10 * 60_000L
        private val ETEINTE: JSONObject get() = JSONObject().put("state", "off").put("attributes", JSONObject())

        /** État d'une télé ou d'une enceinte pour la page : `state` et `volume_level` quand il est connu. */
        fun etatMedia(a: Appareils.Appareil): JSONObject {
            val attributs = JSONObject()
            a.volume?.let { attributs.put("volume_level", it) }
            return JSONObject().put("state", a.etat).put("attributes", attributs)
        }
    }
}
