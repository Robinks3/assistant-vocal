package assistant.vocal.jarvis

import android.app.Activity
import android.app.AlertDialog
import android.graphics.Color
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.os.Handler
import android.os.Looper
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.WindowInsets
import android.text.InputType
import android.widget.EditText
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import java.net.URLEncoder
import java.util.Locale

/**
 * Écran Appareils (0.15.0, serveur 0.17.0) : appairer cet appareil avec un serveur Jarvis, gérer
 * les appareils connus et les demandes en attente, oublier la clé épinglée d'un serveur.
 *
 * L'appairage se fait sans jeton sur le port chiffré (/appairage?nom=...) : le serveur affiche un
 * code à 4 chiffres ici et sur les appareils déjà connus, l'un d'eux accepte, et le serveur envoie
 * une seule fois le jeton propre à cet appareil, gardé dans les préférences. La gestion passe par
 * une connexion à part, jeton en en-tête, indépendante du service.
 */
class AppareilsActivity : Activity() {

    private var serveur = "pc"
    private val principal = Handler(Looper.getMainLooper())
    private val client = Confiance.clientWebSocket()
    @Volatile private var wsGestion: WebSocket? = null
    @Volatile private var wsAppairage: WebSocket? = null

    private lateinit var segmentPc: TextView
    private lateinit var segmentHa: TextView
    private lateinit var texteAdresse: TextView
    private lateinit var texteJeton: TextView
    private lateinit var texteCle: TextView
    private lateinit var texteEtat: TextView
    private lateinit var carteCode: LinearLayout
    private lateinit var texteCode: TextView
    private lateinit var texteCodeAide: TextView
    private lateinit var listeAttente: LinearLayout
    private lateinit var listeAppareils: LinearLayout
    private lateinit var texteFixes: TextView
    private lateinit var boutonOublierJeton: TextView
    private lateinit var texteDiagnostic: TextView
    private lateinit var champAmorcage: EditText
    private lateinit var boutonAmorcage: TextView
    /** Réappairage lancé tout seul à l'ouverture quand le jeton est refusé : une seule fois par ouverture. */
    private var reappairageAuto = false
    /** Numéro de la tentative de connexion, pour tourner sur les cibles de [cibles]. */
    private var essaiCible = 0

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        @Suppress("DEPRECATION")
        window.statusBarColor = Couleur.FOND_HAUT
        @Suppress("DEPRECATION")
        window.navigationBarColor = Couleur.FOND_BAS
        // « Cet appareil » s'appuie sur l'app Jarvis sur HA (passerelle) : c'est elle qu'on gère alors.
        serveur = if (SatelliteService.serveurChoisi(this) == "pc") "pc" else "ha"
        setContentView(construire())
        majServeur()
    }

    override fun onStart() {
        super.onStart()
        connecterGestion(repli = false)
        val refus = Etat.courant.alerteJeton
        if (refus.isNotEmpty() && !reappairageAuto && Confiance.chiffree(adresse())) {
            reappairageAuto = true
            appairer()
        }
        majDiagnostic(null)
    }

    override fun onStop() {
        fermer(wsGestion)
        wsGestion = null
        super.onStop()
    }

    override fun onDestroy() {
        fermer(wsAppairage)
        wsAppairage = null
        client.dispatcher.executorService.shutdown()
        super.onDestroy()
    }

    private fun fermer(ws: WebSocket?) {
        try {
            ws?.close(1000, "fin")
        } catch (_: Exception) {
        }
    }

    private fun ui(bloc: () -> Unit) {
        principal.post { if (!isFinishing && !isDestroyed) bloc() }
    }

    private fun adresse(): String = SatelliteService.adresse(this, serveur).trim().trimEnd('/')

    /** Cibles à essayer pour joindre le serveur choisi (0.34.0), voir [Decouverte.candidats]. */
    private fun cibles(): List<String> {
        val principale = adresse()
        return Decouverte.candidats(principale, Decouverte.hotes(SatelliteService.hotesDe(serveur)), Confiance.derniereCible(this, principale))
    }

    /**
     * Panneau de diagnostic : cause du dernier échec de connexion de cet appareil, et les derniers refus que le
     * serveur a notés (réseau, jeton, rôle), envoyés seulement aux administrateurs. [refus] vient du serveur.
     */
    private fun majDiagnostic(refus: JSONArray?) {
        val lignes = mutableListOf<String>()
        Etat.courant.dernierEchec.takeIf { it.isNotEmpty() }?.let { lignes += "Cet appareil : $it" }
        if (refus != null) {
            for (i in 0 until refus.length()) {
                val r = refus.optJSONObject(i) ?: continue
                lignes += "Serveur, " + r.optString("heure").replace("T", " à ") + " : " + r.optString("cause") + " (" + r.optString("ip") + ")"
            }
        }
        texteDiagnostic.text = if (lignes.isEmpty()) "Aucun échec récent." else lignes.joinToString("\n")
    }

    // ---------------------------------------------------------------- briques graphiques

    private fun dp(v: Int): Int = Decor.dp(this, v.toFloat())

    private fun texte(taille: Float, couleur: Int = Couleur.TEXTE, gras: Boolean = false) = TextView(this).apply {
        setTextSize(TypedValue.COMPLEX_UNIT_SP, taille)
        setTextColor(couleur)
        if (gras) typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        setLineSpacing(0f, 1.15f)
    }

    private fun bouton(libelle: String, couleur: Int, action: () -> Unit) = texte(15.5f, if (couleur == Couleur.CHAMP) Couleur.TEXTE else Color.WHITE, true).apply {
        text = libelle
        gravity = Gravity.CENTER
        minHeight = dp(48)
        setPadding(dp(16), dp(8), dp(16), dp(8))
        background = Decor.fondBouton(this@AppareilsActivity, couleur, 14f)
        Decor.relief(this, 3f)
        isClickable = true
        isFocusable = true
        setOnClickListener { action() }
    }

    private fun marge(haut: Int = 0, bas: Int = 0) =
        LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
            topMargin = dp(haut)
            bottomMargin = dp(bas)
        }

    private fun carte(titre: String): LinearLayout {
        val c = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = Decor.fondCarte(this@AppareilsActivity)
            setPadding(dp(20), dp(18), dp(20), dp(20))
        }
        Decor.relief(c, 6f)
        c.addView(texte(12.5f, Couleur.TEXTE_2, true).apply {
            text = titre.uppercase(Locale.FRANCE)
            letterSpacing = 0.1f
        }, marge(bas = 12))
        return c
    }

    private fun segment(libelle: String, action: () -> Unit) = texte(15f, Couleur.TEXTE_2, true).apply {
        text = libelle
        gravity = Gravity.CENTER
        minHeight = dp(50)
        background = Decor.fondNeutre(this@AppareilsActivity, 12f)
        isClickable = true
        setOnClickListener { action() }
    }

    private fun peindre(vue: TextView, choisi: Boolean) {
        if (choisi) {
            vue.background = Decor.fondBouton(this, Couleur.ACCENT, 12f)
            vue.setTextColor(Color.WHITE)
        } else {
            vue.background = Decor.fondNeutre(this, 12f)
            vue.setTextColor(Couleur.TEXTE_2)
        }
    }

    private fun rangee(vararg vues: View): LinearLayout {
        val r = LinearLayout(this).apply { orientation = LinearLayout.HORIZONTAL }
        vues.forEachIndexed { i, v ->
            r.addView(v, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply { if (i > 0) marginStart = dp(10) })
        }
        return r
    }

    // ---------------------------------------------------------------- construction

    private fun construire(): View {
        val colonne = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            clipChildren = false
        }
        val barre = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        barre.addView(bouton("Retour", Couleur.CHAMP) { finish() })
        barre.addView(
            texte(26f, gras = true).apply {
                text = "Appareils"
                setPadding(dp(14), 0, dp(14), 0)
            },
            LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f),
        )
        barre.addView(bouton("Actualiser", Couleur.ACCENT) { connecterGestion(repli = false) })
        colonne.addView(barre, marge(bas = 16))

        // Serveur géré.
        val cServeur = carte("Serveur")
        val rail = LinearLayout(this).apply {
            orientation = LinearLayout.HORIZONTAL
            background = Decor.fondCreux(this@AppareilsActivity, 16f)
            setPadding(dp(4), dp(4), dp(4), dp(4))
        }
        segmentPc = segment("PC fixe") { changerServeur("pc") }
        segmentHa = segment("Home Assistant") { changerServeur("ha") }
        rail.addView(segmentPc, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
        rail.addView(segmentHa, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply { marginStart = dp(4) })
        cServeur.addView(rail, marge())
        texteAdresse = texte(14f, Couleur.TEXTE_2)
        cServeur.addView(texteAdresse, marge(haut = 10))
        texteEtat = texte(14.5f, Couleur.TEXTE)
        cServeur.addView(texteEtat, marge(haut = 6))
        colonne.addView(cServeur, marge(bas = 16))

        // Cet appareil : jeton, clé retenue, appairage.
        val cAppareil = carte("Cet appareil (${Build.MODEL})")
        texteJeton = texte(15f)
        cAppareil.addView(texteJeton, marge(bas = 8))
        texteCle = texte(14f, Couleur.TEXTE_2).apply { setTextIsSelectable(true) }
        cAppareil.addView(texteCle, marge(bas = 14))
        cAppareil.addView(bouton("Appairer cet appareil", Couleur.ACCENT) { appairer() }, marge(bas = 10))
        boutonOublierJeton = bouton("Oublier le jeton d'appairage", Couleur.CHAMP) { oublierJeton() }
        cAppareil.addView(rangee(bouton("Oublier la clé du serveur", Couleur.CHAMP) { oublierCle() }, boutonOublierJeton), marge())

        carteCode = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            background = Decor.fondCreux(this@AppareilsActivity, 16f)
            setPadding(dp(16), dp(16), dp(16), dp(16))
            visibility = View.GONE
        }
        carteCode.addView(texte(13f, Couleur.TEXTE_2, true).apply {
            text = "CODE D'APPAIRAGE"
            letterSpacing = 0.12f
        })
        texteCode = texte(64f, Couleur.ACCENT_CLAIR, true).apply {
            letterSpacing = 0.2f
            gravity = Gravity.CENTER
        }
        carteCode.addView(texteCode)
        texteCodeAide = texte(14.5f, Couleur.TEXTE_2).apply { gravity = Gravity.CENTER }
        carteCode.addView(texteCodeAide, marge(haut = 4, bas = 10))
        carteCode.addView(bouton("Annuler", Couleur.CHAMP) { annulerAppairage() })
        cAppareil.addView(carteCode, marge(haut = 14))
        champAmorcage = EditText(this).apply {
            hint = "Code à 6 ou 8 chiffres"
            inputType = InputType.TYPE_CLASS_NUMBER
            setTextColor(Couleur.TEXTE)
            setHintTextColor(Couleur.GRIS)
            textSize = 20f
            gravity = Gravity.CENTER
            visibility = View.GONE
        }
        carteCode.addView(champAmorcage, marge(bas = 8))
        boutonAmorcage = bouton("Valider le code", Couleur.ACCENT) { envoyerAmorcage() }.apply { visibility = View.GONE }
        carteCode.addView(boutonAmorcage, marge(bas = 8))
        colonne.addView(cAppareil, marge(bas = 16))

        val cDiag = carte("Diagnostic de connexion")
        texteDiagnostic = texte(14f, Couleur.TEXTE_2)
        cDiag.addView(texteDiagnostic, marge())
        colonne.addView(cDiag, marge(bas = 16))

        val cAttente = carte("Demandes en attente")
        listeAttente = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        cAttente.addView(listeAttente, marge())
        colonne.addView(cAttente, marge(bas = 16))

        val cConnus = carte("Appareils appairés")
        listeAppareils = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        cConnus.addView(listeAppareils, marge())
        texteFixes = texte(13.5f, Couleur.GRIS)
        cConnus.addView(texteFixes, marge(haut = 10))
        colonne.addView(cConnus, marge(bas = 16))

        colonne.addView(texte(12.5f, Couleur.GRIS).apply {
            text = "Version ${BuildConfig.VERSION_BASE}, ${BuildConfig.UTILISATEUR}, compilée le ${BuildConfig.HORODATAGE_COMPILATION}"
            gravity = Gravity.CENTER_HORIZONTAL
        }, marge(haut = 4))

        val racine = ScrollView(this).apply {
            background = Decor.fondEcran(this@AppareilsActivity)
            isFillViewport = true
            clipToPadding = false
            addView(colonne)
        }
        racine.setOnApplyWindowInsetsListener { v, insets ->
            val (g, h, d, b) = if (Build.VERSION.SDK_INT >= 30) {
                val i = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                listOf(i.left, i.top, i.right, i.bottom)
            } else {
                @Suppress("DEPRECATION")
                listOf(insets.systemWindowInsetLeft, insets.systemWindowInsetTop, insets.systemWindowInsetRight, insets.systemWindowInsetBottom)
            }
            v.setPadding(g + dp(16), h + dp(16), d + dp(16), b + dp(16))
            insets
        }
        racine.setPadding(dp(16), dp(16), dp(16), dp(16))
        return racine
    }

    private fun changerServeur(s: String) {
        if (s == serveur) return
        serveur = s
        annulerAppairage()
        listeAttente.removeAllViews()
        listeAppareils.removeAllViews()
        texteFixes.text = ""
        majServeur()
        connecterGestion(repli = false)
    }

    /** Adresse, jeton et clé retenue du serveur choisi. */
    private fun majServeur() {
        peindre(segmentPc, serveur == "pc")
        peindre(segmentHa, serveur == "ha")
        val url = adresse()
        texteAdresse.text = "Adresse : $url" + if (!Confiance.chiffree(url)) " (en clair, l'appairage demande wss://)" else ""
        val appaire = Confiance.jetonAppaire(this, url) != null
        texteJeton.text = if (appaire) "Appairé : jeton propre à cet appareil" else "Pas encore appairé : jeton commun de l'APK"
        boutonOublierJeton.visibility = if (appaire) View.VISIBLE else View.GONE
        texteCle.text = Confiance.empreinte(this, url)?.let { "Clé du serveur retenue : sha256/$it" }
            ?: "Aucune clé retenue : elle le sera à la première connexion chiffrée"
    }

    private fun etat(t: String, couleur: Int = Couleur.TEXTE) {
        texteEtat.text = t
        texteEtat.setTextColor(couleur)
    }

    // ---------------------------------------------------------------- gestion

    private fun envoyer(msg: JSONObject) {
        val ws = wsGestion
        if (ws == null || !ws.send(msg.toString())) {
            Toast.makeText(this, "Pas connecté au serveur", Toast.LENGTH_LONG).show()
        }
    }

    /** Connexion de gestion, jeton en en-tête. Repli en clair seulement si aucune clé n'est retenue. */
    private fun connecterGestion(repli: Boolean) {
        fermer(wsGestion)
        val principale = adresse()
        val ancienne = Confiance.repli(this, principale)
        val url = if (repli && ancienne != null) ancienne else (Decouverte.cibleDe(cibles(), essaiCible) ?: principale)
        etat("Connexion à ${Decouverte.libelle(url)}...", Couleur.TEXTE_2)
        val ws = try {
            Confiance.client(client, this, url, principale).newWebSocket(Confiance.requete(this, url, identite = principale), object : WebSocketListener() {
                override fun onOpen(webSocket: WebSocket, response: Response) {
                    if (webSocket !== wsGestion) return
                    webSocket.send(JSONObject().put("type", "appareils").toString())
                    essaiCible = 0
                    if (!repli) Confiance.retenirCible(this@AppareilsActivity, principale, url)
                    ui {
                        etat(if (Confiance.chiffree(url)) "Connecté, liaison chiffrée" else "Connecté en clair (ancien port)", Couleur.VERT)
                        majServeur()
                    }
                }

                override fun onMessage(webSocket: WebSocket, text: String) {
                    if (webSocket !== wsGestion) return
                    val j = try {
                        JSONObject(text)
                    } catch (_: Exception) {
                        return
                    }
                    when (j.optString("etat")) {
                        "appareils" -> ui { remplir(j); majDiagnostic(j.optJSONArray("refus")) }
                        "appairage_demande" -> webSocket.send(JSONObject().put("type", "appareils").toString())
                        "capacites" -> if (!j.optBoolean("appairage", false)) {
                            ui { etat("Ce serveur ne propose pas l'appairage (port chiffré absent ou version antérieure à 0.17.0)", Couleur.ORANGE) }
                        }
                    }
                }

                override fun onClosed(webSocket: WebSocket, code: Int, reason: String) {
                    if (webSocket !== wsGestion) return
                    val d = Decouverte.diagnostic(code, reason, null, null, Decouverte.libelle(url))
                    ui {
                        if (code == 4001 || code == 4003) etat(d.texte, Couleur.ORANGE)
                        else etat("Connexion fermée ($code)", Couleur.TEXTE_2)
                    }
                }

                override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                    if (webSocket !== wsGestion) return
                    val cle = Confiance.cleChangee(t)
                    val d = Decouverte.diagnostic(null, null, response?.code, t, Decouverte.libelle(url))
                    ui {
                        when {
                            cle != null -> etat(cle.message ?: "La clé du serveur a changé", Couleur.ROUGE)
                            response == null && !repli && ancienne != null -> connecterGestion(repli = true)
                            else -> {
                                essaiCible++
                                etat(d.texte, Couleur.ORANGE)
                            }
                        }
                        majServeur()
                    }
                }
            })
        } catch (e: Exception) {
            etat("Adresse invalide : $url", Couleur.ROUGE)
            null
        }
        wsGestion = ws
    }

    private fun liste(j: JSONObject, nom: String): List<JSONObject> =
        j.optJSONArray(nom)?.let { a -> (0 until a.length()).mapNotNull { a.optJSONObject(it) } } ?: emptyList()

    private fun ligneAppareil(titre: String, detail: String, vararg actions: TextView): LinearLayout {
        val l = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            background = Decor.fondSousCarte(this@AppareilsActivity)
            setPadding(dp(14), dp(12), dp(14), dp(12))
        }
        l.addView(texte(16.5f, gras = true).apply { text = titre })
        l.addView(texte(14f, Couleur.TEXTE_2).apply { text = detail }, marge(haut = 2, bas = if (actions.isEmpty()) 0 else 10))
        if (actions.isNotEmpty()) l.addView(rangee(*actions))
        return l
    }

    private fun remplir(j: JSONObject) {
        listeAttente.removeAllViews()
        val attente = liste(j, "attente")
        if (attente.isEmpty()) listeAttente.addView(texte(15f, Couleur.GRIS).apply { text = "Aucune demande" })
        for (d in attente) {
            val id = d.optString("id")
            listeAttente.addView(
                ligneAppareil(
                    d.optString("nom"), "Code ${d.optString("code")}, depuis ${d.optString("ip")}",
                    bouton("Accepter", Couleur.VERT) { envoyer(JSONObject().put("type", "appairer").put("id", id)) },
                    bouton("Refuser", Couleur.CHAMP) { envoyer(JSONObject().put("type", "refuser_appareil").put("id", id)) },
                ),
                marge(bas = 10),
            )
        }
        listeAppareils.removeAllViews()
        val connus = liste(j, "appareils")
        if (connus.isEmpty()) listeAppareils.addView(texte(15f, Couleur.GRIS).apply { text = "Aucun appareil appairé" })
        for (a in connus) {
            val id = a.optString("id")
            val nom = a.optString("nom")
            val detail = "Appairé le " + a.optString("cree").replace("T", " à ") +
                (a.optString("dernier").takeIf { it.isNotBlank() }?.let { ", vu le " + it.replace("T", " à ") } ?: ", jamais revu")
            listeAppareils.addView(
                ligneAppareil(nom, detail, bouton("Révoquer", Decor.assombrir(Couleur.ROUGE, 0.1f)) { revoquer(id, nom) }),
                marge(bas = 10),
            )
        }
        val fixes = j.optJSONArray("jetons_fixes") ?: JSONArray()
        texteFixes.text = if (fixes.length() == 0) "" else
            "Jetons fixes de poc/.env, toujours acceptés : " + (0 until fixes.length()).joinToString(", ") { fixes.optString(it) }
    }

    private fun revoquer(id: String, nom: String) {
        AlertDialog.Builder(this)
            .setTitle("Révoquer « $nom »")
            .setMessage("Cet appareil perd l'accès tout de suite et devra être appairé de nouveau. Continuer ?")
            .setPositiveButton("Révoquer") { _, _ -> envoyer(JSONObject().put("type", "revoquer").put("id", id)) }
            .setNegativeButton("Annuler", null)
            .show()
    }

    private fun oublierCle() {
        val url = adresse()
        AlertDialog.Builder(this)
            .setTitle("Oublier la clé du serveur")
            .setMessage(
                "La prochaine connexion acceptera la clé présentée par $url et la retiendra. " +
                    "À faire seulement si le serveur a été réinstallé ou son certificat recréé. Continuer ?"
            )
            .setPositiveButton("Oublier") { _, _ ->
                Confiance.oublierEmpreinte(this, url)
                Etat.modifier { it.copy(alerteCle = "") }
                Etat.actionReconnecter?.invoke()
                majServeur()
                connecterGestion(repli = false)
            }
            .setNegativeButton("Annuler", null)
            .show()
    }

    private fun oublierJeton() {
        val url = adresse()
        AlertDialog.Builder(this)
            .setTitle("Oublier le jeton d'appairage")
            .setMessage("Cet appareil reprendra le jeton commun de l'APK pour ce serveur. Continuer ?")
            .setPositiveButton("Oublier") { _, _ ->
                Confiance.oublierJeton(this, url)
                Etat.actionReconnecter?.invoke()
                majServeur()
                connecterGestion(repli = false)
            }
            .setNegativeButton("Annuler", null)
            .show()
    }

    // ---------------------------------------------------------------- appairage

    private fun appairer() {
        val principale = adresse()
        val url = Decouverte.cibleDe(cibles(), essaiCible) ?: principale
        if (!Confiance.chiffree(url)) {
            Toast.makeText(this, "L'appairage passe par le port chiffré : l'adresse doit commencer par wss://", Toast.LENGTH_LONG).show()
            return
        }
        fermer(wsAppairage)
        carteCode.visibility = View.VISIBLE
        texteCode.text = "----"
        texteCodeAide.text = "Demande envoyée au serveur..."
        champAmorcage.visibility = View.GONE
        champAmorcage.text.clear()
        boutonAmorcage.visibility = View.GONE
        // Sans jeton : c'est justement ce que l'appairage doit fournir.
        val requete = Confiance.requete(this, url, "/appairage?nom=" + URLEncoder.encode(Build.MODEL, "UTF-8"), avecJeton = false, identite = principale)
        wsAppairage = Confiance.client(client, this, url, principale).newWebSocket(requete, object : WebSocketListener() {
            override fun onMessage(webSocket: WebSocket, text: String) {
                if (webSocket !== wsAppairage) return
                val j = try {
                    JSONObject(text)
                } catch (_: Exception) {
                    return
                }
                when (j.optString("etat")) {
                    "appairage" -> ui {
                        texteCode.text = j.optString("code")
                        if (j.optBoolean("amorcage", false)) {
                            texteCodeAide.text = j.optString("message") + ". Le code a 6 chiffres (affiché dans Home Assistant, valable 2 minutes) ou 8 chiffres (journal du serveur, valable 10 minutes)."
                            champAmorcage.visibility = View.VISIBLE
                            boutonAmorcage.visibility = View.VISIBLE
                        } else {
                            texteCodeAide.text = "Accepte la demande sur un appareil déjà connecté : le même code doit s'y afficher. " +
                                "La demande expire au bout de 5 minutes."
                        }
                    }
                    "appaire" -> {
                        val jeton = j.optString("jeton")
                        if (jeton.length >= 16) Confiance.enregistrerJeton(this@AppareilsActivity, principale, jeton)
                        Confiance.retenirCible(this@AppareilsActivity, principale, url)
                        Etat.modifier { it.copy(alerteJeton = "", dernierEchec = "") }
                        ui {
                            texteCode.text = "OK"
                            texteCodeAide.text = "Appairé sous le nom « ${j.optString("nom")} ». Le satellite se reconnecte avec son propre jeton."
                            Etat.actionReconnecter?.invoke()
                            majServeur()
                            connecterGestion(repli = false)
                        }
                    }
                    "amorcage_refuse" -> ui {
                        val restant = j.optInt("restant", 0)
                        val detail = j.optString("message")
                        texteCodeAide.text = when {
                            detail.isNotEmpty() -> detail
                            restant > 0 -> "Code d'amorçage faux, $restant essai(s) restant(s)."
                            else -> "Code d'amorçage refusé, plus d'essai. Relance la demande pour obtenir un nouveau code."
                        }
                        champAmorcage.text.clear()
                    }
                    "appairage_refuse" -> ui {
                        texteCode.text = "----"
                        texteCodeAide.text = "Demande refusée ou expirée."
                        champAmorcage.visibility = View.GONE
                        boutonAmorcage.visibility = View.GONE
                    }
                }
            }

            override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
                if (webSocket !== wsAppairage) return
                val cle = Confiance.cleChangee(t)
                val d = Decouverte.diagnostic(null, null, response?.code, t, Decouverte.libelle(url))
                ui {
                    essaiCible++
                    texteCodeAide.text = cle?.message ?: ("Appairage impossible : " + d.texte)
                    majServeur()
                }
            }
        })
    }

    /** Envoie le code saisi (6 chiffres d'invitation ou 8 d'amorçage) sur la demande d'appairage en cours. */
    private fun envoyerAmorcage() {
        val code = champAmorcage.text.toString().filter { it.isDigit() }
        if (!Appareils.codeAmorcageValide(code)) {
            Toast.makeText(this, "Le code a 6 ou 8 chiffres", Toast.LENGTH_SHORT).show()
            return
        }
        val ws = wsAppairage
        if (ws == null || !ws.send(JSONObject().put("type", "amorcage").put("code", code).toString())) {
            Toast.makeText(this, "Demande d'appairage fermée : relance-la", Toast.LENGTH_LONG).show()
        }
    }

    private fun annulerAppairage() {
        fermer(wsAppairage)
        wsAppairage = null
        carteCode.visibility = View.GONE
    }
}
