package assistant.vocal.jarvis

import android.content.Context
import android.graphics.Typeface
import android.text.SpannableStringBuilder
import android.text.Spanned
import android.text.style.ForegroundColorSpan
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.widget.LinearLayout
import android.widget.TextView
import java.time.LocalDate
import java.time.ZoneId
import java.util.Locale

/** Construction des petites cartes d'historique, communes à l'écran principal et à l'historique. */
internal object VueHistorique {

    private fun dp(ctx: Context, v: Int): Int =
        TypedValue.applyDimension(TypedValue.COMPLEX_UNIT_DIP, v.toFloat(), ctx.resources.displayMetrics).toInt()

    private fun texte(ctx: Context, taille: Float, couleur: Int = Couleur.TEXTE, gras: Boolean = false): TextView =
        TextView(ctx).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, taille)
            setTextColor(couleur)
            if (gras) typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
            setLineSpacing(0f, 1.12f)
        }

    /** « Libellé : valeur », le libellé en gris clair, la valeur dans la couleur donnée. */
    private fun ligne(ctx: Context, libelle: String, valeur: String, couleurValeur: Int = Couleur.TEXTE): TextView {
        val s = SpannableStringBuilder()
        s.append("$libelle : ")
        s.setSpan(ForegroundColorSpan(Couleur.TEXTE_2), 0, s.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        val debut = s.length
        s.append(valeur)
        s.setSpan(ForegroundColorSpan(couleurValeur), debut, s.length, Spanned.SPAN_EXCLUSIVE_EXCLUSIVE)
        return texte(ctx, 15f).apply { text = s }
    }

    private fun parametres(ctx: Context, haut: Int = 0) =
        LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT)
            .apply { topMargin = dp(ctx, haut) }

    /** « 0.18 » devient « 0,18 s ». Valeur brute si elle n'est pas un nombre. */
    private fun duree(brute: String): String {
        if (brute.isBlank()) return ""
        val v = brute.trim().replace(',', '.').toDoubleOrNull() ?: return brute
        return String.format(Locale.FRANCE, "%.2f s", v)
    }

    /** Heure seule pour aujourd'hui, sinon date courte puis heure. */
    private fun horodatage(date: String, heure: String): String {
        val aujourdHui = LocalDate.now(ZoneId.of("Europe/Paris")).toString()
        if (date.isBlank() || date == aujourdHui) return heure
        val morceaux = date.split("-")
        val dateCourte = if (morceaux.size == 3) "${morceaux[2]}/${morceaux[1]}/${morceaux[0]}" else date
        return "$dateCourte, $heure"
    }

    /** « C'était bien » ou « Pas bien » : la note part au serveur pour corriger le dictionnaire. */
    private fun notes(ctx: Context, e: Etat.EntreeHistorique): View {
        if (e.verdict.isNotEmpty()) {
            val bien = e.verdict == "bien"
            return texte(ctx, 14f, if (bien) Couleur.VERT else Couleur.ORANGE, gras = true).apply {
                text = if (bien) "Noté : c'était bien" else "Noté : pas bien, je m'en sers pour corriger"
            }
        }
        val rangee = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
        for ((libelle, verdict, couleur) in listOf(
            Triple("C'était bien", "bien", Couleur.VERT),
            Triple("Pas bien", "mauvais", Couleur.ORANGE),
        )) {
            val bouton = texte(ctx, 14f, couleur, gras = true).apply {
                text = libelle
                gravity = Gravity.CENTER
                setPadding(dp(ctx, 14), dp(ctx, 9), dp(ctx, 14), dp(ctx, 9))
                background = Decor.fondSousCarte(ctx, 10f, couleur)
                isClickable = true
                isFocusable = true
                setOnClickListener { Etat.actionRetour?.invoke(e, verdict) }
            }
            rangee.addView(
                bouton,
                LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply {
                    if (verdict == "mauvais") marginStart = dp(ctx, 10)
                },
            )
        }
        return rangee
    }

    fun carte(ctx: Context, e: Etat.EntreeHistorique): View {
        val carte = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            background = Decor.fondSousCarte(ctx, 14f, if (e.erreur) Couleur.ROUGE else Couleur.CHAMP_BORD)
            setPadding(dp(ctx, 16), dp(ctx, 13), dp(ctx, 16), dp(ctx, 15))
        }
        Decor.relief(carte, 2f)

        // En-tête : heure, étiquette ESSAI ou RÉEL, durée à droite.
        val entete = LinearLayout(ctx).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        entete.addView(texte(ctx, 15f, gras = true).apply { text = horodatage(e.date, e.heure) })
        val (libelle, couleur) = if (e.essai) "ESSAI" to Couleur.ESSAI else "RÉEL" to Couleur.VERT
        entete.addView(
            texte(ctx, 11f, Couleur.FOND, gras = true).apply {
                text = libelle
                letterSpacing = 0.1f
                setPadding(dp(ctx, 8), dp(ctx, 2), dp(ctx, 8), dp(ctx, 2))
                background = Decor.degrade(ctx, Decor.eclaircir(couleur, 0.12f), Decor.assombrir(couleur, 0.08f), 8f)
            },
            LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT)
                .apply { marginStart = dp(ctx, 10) },
        )
        entete.addView(
            texte(ctx, 14f, Couleur.TEXTE_2).apply {
                text = duree(e.duree)
                gravity = Gravity.END
            },
            LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f),
        )
        carte.addView(entete, parametres(ctx))

        carte.addView(
            if (e.entendu.isBlank()) {
                ligne(ctx, "Entendu", "rien de compréhensible", Couleur.GRIS)
            } else {
                ligne(ctx, "Entendu", e.entendu)
            },
            parametres(ctx, 8),
        )

        carte.addView(ligne(ctx, "Compris par", e.comprisPar.ifBlank { "-" }), parametres(ctx, 4))
        if (e.detailVoie.isNotBlank()) {
            carte.addView(texte(ctx, 13f, Couleur.GRIS).apply { text = e.detailVoie }, parametres(ctx, 2))
        }

        // Noms des appareils plutôt que leurs identifiants (0.17.0, HistoriqueLisible).
        val fait = e.fait.map { HistoriqueLisible.ligne(it, Etat.courant.noms) }
        if (fait.isEmpty()) {
            carte.addView(ligne(ctx, "Fait", "aucune action", Couleur.GRIS), parametres(ctx, 4))
        } else {
            carte.addView(ligne(ctx, "Fait", fait.first()), parametres(ctx, 4))
            // Une ligne par action, alignées sous la première.
            for (action in fait.drop(1)) {
                carte.addView(
                    texte(ctx, 15f).apply {
                        text = action
                        setPadding(dp(ctx, 38), 0, 0, 0)
                    },
                    parametres(ctx, 2),
                )
            }
        }
        if (e.erreur) {
            carte.addView(
                texte(ctx, 15f, Couleur.ROUGE, gras = true).apply { text = "Home Assistant a refusé" },
                parametres(ctx, 4),
            )
        }

        if (e.reponse.isNotBlank()) {
            carte.addView(ligne(ctx, "Réponse", e.reponse), parametres(ctx, 4))
        }
        carte.addView(notes(ctx, e), parametres(ctx, 10))
        return carte
    }

    /**
     * Remplit un conteneur avec les entrées données, ou un message si la liste est vide.
     * Sur grand écran, les cartes sont rangées en plusieurs colonnes de même hauteur par rangée.
     */
    fun remplir(
        ctx: Context,
        conteneur: LinearLayout,
        entrees: List<Etat.EntreeHistorique>,
        siVide: String,
        colonnes: Int = 1,
    ) {
        conteneur.removeAllViews()
        // Une même commande reçue deux fois n'est montrée qu'une fois (0.17.0).
        val liste = HistoriqueLisible.sansDoublons(entrees)
        if (liste.isEmpty()) {
            conteneur.addView(texte(ctx, 15f, Couleur.GRIS).apply { text = siVide }, parametres(ctx))
            return
        }
        if (colonnes <= 1) {
            liste.forEachIndexed { i, e ->
                conteneur.addView(carte(ctx, e), parametres(ctx, if (i == 0) 0 else 10))
            }
            return
        }
        liste.chunked(colonnes).forEachIndexed { i, groupe ->
            val rangee = LinearLayout(ctx).apply {
                orientation = LinearLayout.HORIZONTAL
                clipChildren = false
            }
            for (j in 0 until colonnes) {
                val lp = LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.MATCH_PARENT, 1f)
                    .apply { if (j > 0) marginStart = dp(ctx, 12) }
                // Case vide en fin de liste : la dernière carte garde la largeur d'une colonne.
                rangee.addView(groupe.getOrNull(j)?.let { carte(ctx, it) } ?: View(ctx), lp)
            }
            conteneur.addView(rangee, parametres(ctx, if (i == 0) 0 else 12))
        }
    }
}
