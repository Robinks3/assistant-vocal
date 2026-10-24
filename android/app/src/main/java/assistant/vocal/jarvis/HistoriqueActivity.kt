package assistant.vocal.jarvis

import android.app.Activity
import android.graphics.Color
import android.graphics.Typeface
import android.os.Build
import android.os.Bundle
import android.util.TypedValue
import android.view.Gravity
import android.view.WindowInsets
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast

/** Écran d'historique : les 50 dernières commandes, ce qui a été entendu, compris et fait. */
class HistoriqueActivity : Activity() {

    private lateinit var liste: LinearLayout
    private lateinit var texteEtat: TextView
    private var historiqueAffiche: List<Etat.EntreeHistorique>? = null

    private val ecouteur: (Etat.Instantane) -> Unit = { afficher(it) }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        @Suppress("DEPRECATION")
        window.statusBarColor = Couleur.FOND_HAUT
        @Suppress("DEPRECATION")
        window.navigationBarColor = Couleur.FOND_BAS
        setContentView(construire())
    }

    override fun onStart() {
        super.onStart()
        Etat.ajouter(ecouteur)
        actualiser(silencieux = true)
    }

    override fun onStop() {
        Etat.retirer(ecouteur)
        super.onStop()
    }

    private fun dp(v: Int): Int =
        TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), resources.displayMetrics).toInt()

    private fun bouton(libelle: String, couleur: Int, action: () -> Unit) = TextView(this).apply {
        text = libelle
        setTextSize(TypedValue.COMPLEX_UNIT_SP, 16f)
        setTextColor(if (couleur == Couleur.CHAMP) Couleur.TEXTE else Color.WHITE)
        typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
        gravity = Gravity.CENTER
        minHeight = dp(48)
        setPadding(dp(18), dp(8), dp(18), dp(8))
        background = Decor.fondBouton(this@HistoriqueActivity, couleur, 14f)
        Decor.relief(this, 3f)
        isClickable = true
        isFocusable = true
        setOnClickListener { action() }
    }

    /** Deux colonnes de cartes dès que la largeur le permet (tablette en paysage). */
    private fun colonnes(): Int = if (resources.configuration.screenWidthDp >= 840) 2 else 1

    private fun construire(): ScrollView {
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
            TextView(this).apply {
                text = "Historique"
                setTextSize(TypedValue.COMPLEX_UNIT_SP, 26f)
                setTextColor(Couleur.TEXTE)
                typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
                setPadding(dp(14), 0, dp(14), 0)
            },
            LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f),
        )
        barre.addView(bouton("Actualiser", Couleur.ACCENT) { actualiser(silencieux = false) })
        colonne.addView(barre)

        texteEtat = TextView(this).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 14f)
            setTextColor(Couleur.TEXTE_2)
            setPadding(dp(4), dp(12), dp(4), dp(12))
        }
        colonne.addView(texteEtat)

        liste = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            clipChildren = false
        }
        colonne.addView(liste)

        val racine = ScrollView(this).apply {
            background = Decor.fondEcran(this@HistoriqueActivity)
            isFillViewport = true
            clipToPadding = false
            addView(colonne)
        }
        // Affichage bord à bord imposé sur Android 15 : marges des barres système.
        racine.setOnApplyWindowInsetsListener { v, insets ->
            val (g, h, d, b) = if (Build.VERSION.SDK_INT >= 30) {
                val i = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.displayCutout())
                listOf(i.left, i.top, i.right, i.bottom)
            } else {
                @Suppress("DEPRECATION")
                listOf(
                    insets.systemWindowInsetLeft, insets.systemWindowInsetTop,
                    insets.systemWindowInsetRight, insets.systemWindowInsetBottom,
                )
            }
            v.setPadding(g + dp(16), h + dp(16), d + dp(16), b + dp(16))
            insets
        }
        racine.setPadding(dp(16), dp(16), dp(16), dp(16))
        return racine
    }

    private fun actualiser(silencieux: Boolean) {
        val action = Etat.actionHistorique
        if (action != null && Etat.courant.lien == Etat.Lien.CONNECTE) {
            action()
            if (!silencieux) Toast.makeText(this, "Historique demandé au serveur", Toast.LENGTH_SHORT).show()
        } else if (!silencieux) {
            Toast.makeText(this, "Satellite non connecté au serveur", Toast.LENGTH_LONG).show()
        }
    }

    private fun afficher(e: Etat.Instantane) {
        texteEtat.text = when {
            e.lien != Etat.Lien.CONNECTE -> "Non connecté : historique de la dernière connexion"
            e.historique.isEmpty() -> "Connecté"
            else -> "${e.historique.size} commandes, la plus récente en haut"
        }
        // Reconstruit la liste seulement quand elle change (le vumètre publie souvent).
        if (e.historique === historiqueAffiche) return
        historiqueAffiche = e.historique
        VueHistorique.remplir(this, liste, e.historique, "Aucune commande pour l'instant", colonnes())
    }
}
