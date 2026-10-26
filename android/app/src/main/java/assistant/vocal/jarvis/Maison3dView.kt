package assistant.vocal.jarvis

import android.annotation.SuppressLint
import android.content.Context
import android.graphics.Color
import android.os.Handler
import android.os.Looper
import android.view.View
import android.webkit.JavascriptInterface
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import android.widget.FrameLayout
import org.json.JSONArray
import org.json.JSONObject

/**
 * Vue 3D de l'appartement : WebView sur assets/maison3d/vue3d.html (three.js inclus, aucun accès
 * réseau ni fichier). Les lampes s'animent quand on leur passe un état Home Assistant, et un toucher
 * sur une lampe remonte par [surBasculer] sans rien changer : l'appelant applique la sécurité en dur,
 * agit sur HA puis renvoie le vrai état par [etat]. La page ne dessine que pendant une animation ou
 * un geste. Appeler [liberer] quand la vue n'est plus utilisée.
 */
@SuppressLint("SetJavaScriptEnabled", "ViewConstructor")
class Maison3dView(context: Context, resolution: Float = 0f) : FrameLayout(context) {

    /** Toucher sur une lampe : entité de l'ampoule (`light.salon_plafond`) et état voulu. Fil principal. */
    var surBasculer: ((String, Boolean) -> Unit)? = null
    /** La page est prête (scène construite) : le moment d'envoyer les états courants. Fil principal. */
    var surPrete: (() -> Unit)? = null
    /**
     * La page ne rend plus : processus de rendu mort (onRenderProcessGone) ou contexte WebGL perdu (0.18.1).
     * Le propriétaire détruit la vue et en recrée une. Fil principal.
     */
    var surPerdue: ((String) -> Unit)? = null
    /** Version de la page, reçue avec pret() (0.24.0). */
    var versionPage = ""
        private set
    /** Dernier battement de la page (toutes les 10 s), SystemClock.elapsedRealtime. */
    @Volatile var battementLe = android.os.SystemClock.elapsedRealtime()
        private set

    private val principal = Handler(Looper.getMainLooper())
    private val web = WebView(context)
    private val pont = Maison3dPont { script -> web.evaluateJavascript(script, null) }
    private var liberee = false

    init {
        setBackgroundColor(Palette.fond)
        web.setBackgroundColor(Palette.fond)
        web.isVerticalScrollBarEnabled = false
        web.isHorizontalScrollBarEnabled = false
        web.overScrollMode = View.OVER_SCROLL_NEVER
        web.settings.apply {
            javaScriptEnabled = true
            // Les assets restent lisibles avec allowFileAccess à false (file:///android_asset/).
            allowFileAccess = false
            allowContentAccess = false
            blockNetworkLoads = true
            domStorageEnabled = false
            setSupportZoom(false)
        }
        web.webViewClient = object : WebViewClient() {
            // La page ne doit jamais naviguer ailleurs : le pont JavaScript ne sert qu'à elle.
            override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest) = true

            /**
             * Processus de rendu mort (0.18.1, revue de faisabilité) : rendre vrai empêche Android de tuer tout
             * le processus de l'appli, micro et vision compris. Cette WebView est inutilisable : elle est
             * libérée et son propriétaire en recrée une.
             */
            override fun onRenderProcessGone(view: WebView, detail: android.webkit.RenderProcessGoneDetail): Boolean {
                val raison = if (detail.didCrash()) "rendu planté" else "rendu tué par Android (mémoire)"
                android.util.Log.w("JarvisPlan3d", "processus de rendu perdu : $raison")
                principal.post {
                    if (liberee) return@post
                    val s = surPerdue
                    liberer()
                    s?.invoke(raison)
                }
                return true
            }
        }
        web.addJavascriptInterface(PontJs(), "Maison3dAndroid")
        addView(web, LayoutParams(LayoutParams.MATCH_PARENT, LayoutParams.MATCH_PARENT))
        // Résolution de la page réglable une fois au chargement (?pr=1.25), 1,5 par défaut.
        web.loadUrl(if (resolution > 0f) "$PAGE?pr=${String.format(java.util.Locale.ROOT, "%.2f", resolution)}" else PAGE)
    }

    // ------------------------------------------------ 0.18.1

    /** Teintes de la palette de l'appli : à envoyer dès que la page est prête. */
    fun teintes() = appeler(Maison3dPont.scriptTeintes(Palette.plan3dJson()))

    /** Teintes du jeu de couleurs choisi (0.19.0), après les teintes neutres. */
    fun palette() = appeler(Maison3dPont.scriptPalette(Palette.plan3dPaletteJson()))

    /** Cadence de repos, et plafond pendant une action (30 d'ordinaire, moins quand la tablette chauffe). */
    fun cadence(ips: Int, action: Int = 30) = appeler(Maison3dPont.scriptCadence(ips, action))
    /** Rotation lente (0 l'arrête), à [ips] images par seconde au plus. */
    fun rotation(periodeS: Int, ips: Int) = appeler(Maison3dPont.scriptRotation(periodeS, ips, 1f))
    /** Balancement de l'accueil (0.24.0) : ± [amplitudeDeg] autour de [angleDeg], aller et retour en [periodeS]. */
    fun balancement(periodeS: Int, ips: Int, amplitudeDeg: Float, angleDeg: Float) =
        appeler(Maison3dPont.scriptRotation(periodeS, ips, 1f, amplitudeDeg, angleDeg))
    /** Zone de la fenêtre où l'appartement est cadré (0.24.0), transition en [dureeMs], d'un coup sans durée. */
    internal fun disposition(z: Disposition.Zone, dureeMs: Int) = appeler(Maison3dPont.scriptDisposition(z, dureeMs))
    /** Jeu de teintes couleur (0.24.0) à cette intensité, puis l'intensité seule quand elle change. */
    fun jeuCouleur(intensite: Float) = appeler(Maison3dPont.scriptJeuCouleur(intensite))
    fun intensite(v: Float) = appeler(Maison3dPont.scriptIntensite(v))
    /** Régime de l'accueil (0.24.0) : 1 vivant, 0 en retrait, en [dureeMs]. */
    fun regime(niveau: Float, dureeMs: Int) = appeler(Maison3dPont.scriptRegime(niveau, dureeMs))
    fun pause(oui: Boolean) = appeler(Maison3dPont.scriptPause(oui))
    fun poussieres(oui: Boolean) = appeler(Maison3dPont.scriptPoussieres(oui))
    fun desaturer(oui: Boolean) = appeler(Maison3dPont.scriptDesaturer(oui))

    /**
     * Le toucher ([x], [y] en pixels de la vue) tombe-t-il sur l'appartement ou dans le noir autour ? Rendu
     * sur le fil principal, vrai par défaut tant que la page n'est pas prête.
     */
    fun dansLePlan(x: Float, y: Float, suite: (Boolean) -> Unit) {
        if (liberee || !pont.prete) { suite(true); return }
        val d = resources.displayMetrics.density
        web.evaluateJavascript(Maison3dPont.scriptDansLePlan(x / d, y / d)) { r -> principal.post { suite(r != "false") } }
    }

    // ------------------------------------------------ la maison en grand (0.27.0, page 0.8.0)

    /** Maison en grand ou non, pastilles de [taille] et étiquettes en [police] pixels CSS. */
    fun grand(actif: Boolean, taille: Float, police: Float) = appeler(Maison3dPont.scriptGrand(actif, taille, police))
    fun choisir(piece: String?, dureeMs: Int) = appeler(Maison3dPont.scriptChoisir(piece, dureeMs))
    fun etiquettes(liste: JSONArray) = appeler(Maison3dPont.scriptEtiquettes(liste))
    fun pastilles(liste: JSONArray) = appeler(Maison3dPont.scriptPastilles(liste))
    fun voile(opacite: Float) = appeler(Maison3dPont.scriptVoile(opacite))

    /**
     * Ce qui est sous le toucher ([x], [y] en pixels de la vue) : `{genre: pastille, entite}`, `{genre: piece, id}` ou
     * `{genre: vide}`. Rendu sur le fil principal, null si la page n'est pas prête ou ne sait pas répondre.
     */
    fun designer(x: Float, y: Float, suite: (JSONObject?) -> Unit) {
        if (liberee || !pont.prete) { suite(null); return }
        val d = resources.displayMetrics.density
        web.evaluateJavascript(Maison3dPont.scriptDesigner(x / d, y / d)) { r ->
            val o = Maison3dPont.texteRendu(r)?.let { t -> try { JSONObject(t) } catch (_: Exception) { null } }
            principal.post { if (!liberee) suite(o) }
        }
    }

    /** Objets réglables de chaque pièce (texte JSON de maison3d.contenu), null si la page ne le connaît pas. */
    fun contenu(suite: (String?) -> Unit) {
        if (liberee || !pont.prete) { suite(null); return }
        web.evaluateJavascript(Maison3dPont.SCRIPT_CONTENU) { r ->
            val t = Maison3dPont.texteRendu(r)
            principal.post { if (!liberee) suite(t) }
        }
    }

    /** Tableau brut de `/api/states` : seules les lumières, la télé et les enceintes sont transmises à la page. */
    fun etats(json: JSONArray) = appeler(Maison3dPont.scriptEtats(json))

    /** Une lumière ou un groupe HA (`light.cuisine_suspensions` allume ses deux ampoules dans la vue), la télé ou une enceinte. */
    fun etat(entite: String, etatHA: JSONObject) = appeler(Maison3dPont.scriptEtat(entite, etatHA))

    /** Vol de caméra vers des lumières, des groupes ou des pièces (`chambre_sacha`). */
    fun montrer(entites: List<String>) = appeler(Maison3dPont.scriptMontrer(entites))

    /** Action de l'assistant (0.17.5) : `{entité: {effet, state, attributes}}`, chorégraphie jouée par la page. */
    fun action(effets: JSONObject) = appeler(Maison3dPont.scriptAction(effets))

    /** États posés sans animation (0.17.5), `{entité: état HA}`. */
    fun poser(etats: JSONObject) = appeler(Maison3dPont.scriptPoser(etats))

    /** Bords de la scène fondus dans le noir (0.17.6) : la vue flotte sur l'écran au lieu d'être encadrée. */
    fun fondu() = appeler(Maison3dPont.SCRIPT_FONDU)

    /** Retour à la vue de tout l'appartement. */
    fun ensemble() = appeler(Maison3dPont.SCRIPT_ENSEMBLE)

    // ------------------------------------------------ écran d'accueil (0.18.0)

    /**
     * Réglages de l'accueil : sans noms au sol, poussières des pièces allumées. Depuis la 0.24.0, la page couvre
     * toute la fenêtre et cadre l'appartement dans sa zone (disposition) : plus de bords fondus, et un
     * balancement de ± [amplitudeDeg] autour de [angleDeg] au lieu du tour complet ([periodeS] 0 l'arrête).
     */
    fun accueil(periodeS: Int, ips: Int, amplitudeDeg: Float, angleDeg: Float) {
        appeler(Maison3dPont.SCRIPT_SANS_FONDU)
        appeler(Maison3dPont.SCRIPT_NOMS_CACHES)
        appeler(if (periodeS > 0) Maison3dPont.scriptRotation(periodeS, ips, 1f, amplitudeDeg, angleDeg) else Maison3dPont.scriptRotation(0, ips, 1f))
        appeler(Maison3dPont.scriptPoussieres(true))
    }

    /** Scène atténuée pendant l'écoute de l'assistant. */
    fun attenuer(opacite: Float, dureeMs: Int) = appeler(Maison3dPont.scriptAttenuer(opacite, dureeMs))

    /** Retour animé à la vue large et reprise de la rotation, après une action. */
    fun ensemble(dureeMs: Int) = appeler(Maison3dPont.scriptEnsemble(dureeMs))

    /**
     * Page masquée (AOD, écran noir, panneau ouvert, activité cachée) : plus aucune image, la rotation
     * reprend où elle en était au retour. La page garde sa dernière image, la vue doit donc être cachée.
     * Depuis la 0.18.1, la page coupe aussi son requestAnimationFrame (maison3d.pause), WebView.onPause
     * ne mettant pas le JavaScript en pause.
     */
    fun suspendre(oui: Boolean) {
        if (liberee || oui == suspendue) return
        suspendue = oui
        if (oui) {
            pause(true)
            web.onPause()
        } else {
            web.onResume()
            battementLe = android.os.SystemClock.elapsedRealtime()
            pause(false)
        }
    }

    val enPause: Boolean get() = suspendue

    private var suspendue = false

    fun liberer() {
        if (liberee) return
        liberee = true
        surBasculer = null
        surPrete = null
        surPerdue = null
        pont.reinitialiser()
        principal.removeCallbacksAndMessages(null)
        web.removeJavascriptInterface("Maison3dAndroid")
        web.stopLoading()
        removeView(web)
        web.destroy()
    }

    private fun appeler(script: String) {
        if (liberee) return
        if (Looper.myLooper() == Looper.getMainLooper()) pont.appeler(script)
        else principal.post { if (!liberee) pont.appeler(script) }
    }

    /** Appelé par la page sur un fil du WebView : tout est renvoyé sur le fil principal. */
    private inner class PontJs {
        @JavascriptInterface
        fun pret(version: String) {
            principal.post {
                if (liberee) return@post
                versionPage = version.take(20)
                pont.surPret()
                surPrete?.invoke()
            }
        }

        /** Battement de la page, toutes les 10 s (0.18.1). */
        @JavascriptInterface
        fun battement() {
            battementLe = android.os.SystemClock.elapsedRealtime()
        }

        /** Contexte WebGL perdu (0.18.1) : la vue est recréée par son propriétaire. */
        @JavascriptInterface
        fun contextePerdu() {
            principal.post {
                if (liberee) return@post
                android.util.Log.w("JarvisPlan3d", "contexte WebGL perdu")
                val s = surPerdue
                liberer()
                s?.invoke("contexte WebGL perdu")
            }
        }

        @JavascriptInterface
        fun basculer(entite: String, on: Boolean) {
            if (!entite.startsWith("light.")) return
            principal.post { if (!liberee) surBasculer?.invoke(entite, on) }
        }
    }

    companion object {
        const val PAGE = "file:///android_asset/maison3d/vue3d.html"
    }
}
