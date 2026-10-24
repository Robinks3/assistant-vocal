package assistant.vocal.jarvis

import android.content.Context
import android.content.res.ColorStateList
import android.graphics.Bitmap
import android.graphics.Color
import android.graphics.Typeface
import android.os.SystemClock
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.widget.CheckBox
import android.widget.HorizontalScrollView
import android.widget.ImageView
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.SeekBar
import android.widget.TextView
import org.json.JSONObject
import java.util.Locale

/**
 * Écran Musique de la tablette (0.17.0), ouvert par un toucher sur la bulle En cours. Grande pochette,
 * titre, artiste, progression, gros contrôles, choix du lecteur suivi quand plusieurs jouent, puis la
 * sortie du son : Salon, Cuisine et Bureau en cases à cocher (une seule musique synchronisée, voir
 * SortieSon), le volume de chaque enceinte, et « À suivre » quand le lecteur l'annonce.
 *
 * Tout part par la passerelle après Securite.kt : les cases par Etat.actionService (vérifiées ici puis
 * dans Maison.commande), les contrôles et le volume par Etat.actionMedia. Les refus s'affichent en bas
 * de la colonne de droite. Les enceintes sont relues toutes les 3 s tant que l'écran est ouvert.
 */
internal class EcranMusique(
    private val ctx: Context,
    /** Bulle En cours : lecteur suivi, pochette, commandes. */
    private val carte: CarteEnCours,
    private val fermer: () -> Unit,
) {
    private fun dp(v: Int): Int = Decor.dp(ctx, v.toFloat())

    private fun texte(taille: Float, couleur: Int, police: String? = null, lignes: Int = 1) = TextView(ctx).apply {
        setTextSize(TypedValue.COMPLEX_UNIT_SP, taille)
        setTextColor(couleur)
        // Instrument Sans, comme l'accueil de la tablette (0.18.0).
        typeface = Polices.depuis(ctx, police)
        maxLines = lignes
        ellipsize = android.text.TextUtils.TruncateAt.END
    }

    /** Titre de section en casse normale (0.18.0), plus de capitales espacées. */
    private fun surtitre(libelle: String) = texte(16f, Couleur.OR, "sans-serif-medium").apply {
        text = libelle
    }

    private val pochette = ImageView(ctx).apply {
        scaleType = ImageView.ScaleType.CENTER_CROP
        background = Decor.uni(ctx, Palette.musiquePochette, 18f)
        clipToOutline = true
    }
    private val titre = texte(26f, Palette.musiqueTitre, "sans-serif-medium", 2).apply { gravity = Gravity.CENTER_HORIZONTAL }
    private val artiste = texte(18f, Couleur.TEXTE_2).apply { gravity = Gravity.CENTER_HORIZONTAL }
    private val lecteurs = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
    private val defileLecteurs = HorizontalScrollView(ctx).apply {
        isHorizontalScrollBarEnabled = false
        addView(lecteurs)
        visibility = View.GONE
    }
    private val barre = BarreProgression(ctx).apply { teinte = Couleur.OR }
    private val tempsPasse = texte(13f, Couleur.GRIS)
    private val tempsTotal = texte(13f, Couleur.GRIS).apply { gravity = Gravity.END }
    private val lecture = BoutonMedia(ctx, BoutonMedia.Forme.PAUSE, Couleur.OR)
    private val suivantTitre = surtitre("À suivre")
    private val suivant = texte(16f, Couleur.TEXTE_2, lignes = 2)
    private val message = texte(15f, Decor.eclaircir(Couleur.ORANGE, 0.1f), lignes = 3)

    /** Une ligne par enceinte : case, volume et pourcentage. */
    private class Ligne(val id: String, val caseACocher: CheckBox, val volume: SeekBar, val pourcent: TextView) {
        /** Choix fait au doigt pas encore confirmé par HA (case ou volume), et quand. */
        var caseVoulue: Boolean? = null
        var caseLe = 0L
        var volumeLe = 0L
        var glisse = false
    }
    private val lignes = ArrayList<Ligne>()
    private var cleLecteurs = ""
    private var imageMontree: Bitmap? = null
    private var messageLocal = ""
    private var messageLocalLe = 0L

    val vue: View

    init {
        val colonneGauche = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            gravity = Gravity.CENTER_HORIZONTAL
            addView(pochette, LinearLayout.LayoutParams(dp(280), dp(280)))
            addView(titre, marge(16))
            addView(artiste, marge(4))
            addView(defileLecteurs, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(12) })
            addView(barre, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(16)).apply { topMargin = dp(16) })
            val temps = LinearLayout(ctx).apply { orientation = LinearLayout.HORIZONTAL }
            temps.addView(tempsPasse, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            temps.addView(tempsTotal, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            addView(temps, marge(2))
            val commandes = LinearLayout(ctx).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER
            }
            val boutons = listOf(
                BoutonMedia(ctx, BoutonMedia.Forme.PRECEDENT, Couleur.OR).apply { contentDescription = "Morceau précédent"; setOnClickListener { carte.commande("media_previous_track") } },
                lecture.apply { contentDescription = "Lecture ou pause"; setOnClickListener { carte.lectureOuPause() } },
                BoutonMedia(ctx, BoutonMedia.Forme.SUIVANT, Couleur.OR).apply { contentDescription = "Morceau suivant"; setOnClickListener { carte.commande("media_next_track") } },
            )
            for ((i, b) in boutons.withIndex()) {
                val t = if (b === lecture) 84 else 64
                commandes.addView(b, LinearLayout.LayoutParams(dp(t), dp(t)).apply { if (i > 0) marginStart = dp(28) })
            }
            addView(commandes, marge(14))
        }

        val colonneDroite = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            addView(surtitre("Sortie du son"))
            addView(texte(14f, Couleur.TEXTE_2, lignes = 4).apply {
                // La règle de nuit n'est annoncée que si elle est en vigueur (levée le 22/10/2026).
                text = "Une seule musique, synchronisée sur les enceintes cochées." + if (Securite.HEURE_CALME_ACTIVE)
                    " Pas de son au salon de minuit à 9 h : le Salon et la Cuisine ne peuvent pas être ajoutés la nuit." else ""
            }, marge(6))
            for ((id, nom) in SortieSon.ENCEINTES) addView(construireLigne(id, nom), marge(14))
            addView(suivantTitre, marge(24))
            addView(suivant, marge(4))
            addView(message, marge(18))
        }

        val corps = LinearLayout(ctx).apply {
            orientation = LinearLayout.HORIZONTAL
            addView(colonneGauche, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            addView(colonneDroite, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f).apply { marginStart = dp(40) })
        }
        val entete = LinearLayout(ctx).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
            addView(texte(24f, Couleur.OR, "sans-serif-light").apply { text = "Musique" }, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            addView(boutonFermer(), LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, dp(44)))
        }
        val pile = LinearLayout(ctx).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(32), dp(20), dp(32), dp(24))
            addView(entete, marge(0))
            addView(corps, marge(20))
        }
        vue = ScrollView(ctx).apply {
            isFillViewport = true
            isVerticalScrollBarEnabled = false
            // Fond presque noir (écran OLED), et le toucher ne traverse pas vers les bulles.
            setBackgroundColor(Couleur.PANNEAU)
            isClickable = true
            addView(pile)
            visibility = View.GONE
        }
    }

    private fun marge(haut: Int) =
        LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply { topMargin = dp(haut) }

    private fun boutonFermer() = texte(16f, Couleur.TEXTE, "sans-serif-medium").apply {
        text = "Fermer"
        gravity = Gravity.CENTER
        setPadding(dp(20), 0, dp(20), 0)
        background = Decor.fondBouton(ctx, Couleur.CHAMP, 14f)
        isClickable = true
        setOnClickListener { fermer() }
    }

    private fun construireLigne(id: String, nom: String): View {
        val ligne = LinearLayout(ctx).apply {
            orientation = LinearLayout.HORIZONTAL
            gravity = Gravity.CENTER_VERTICAL
        }
        val case = CheckBox(ctx).apply {
            text = nom
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 18f)
            setTextColor(Palette.musiqueTexte)
            buttonTintList = ColorStateList.valueOf(Couleur.OR)
            minWidth = dp(150)
        }
        val volume = SeekBar(ctx).apply {
            // De 0 à 50 % seulement (Securite.VOLUME_MAX) : toute la piste couvre le volume permis.
            max = Math.round(Securite.VOLUME_MAX * 100).toInt()
            progressTintList = ColorStateList.valueOf(Couleur.OR)
            thumbTintList = ColorStateList.valueOf(Couleur.OR)
            progressBackgroundTintList = ColorStateList.valueOf(Palette.musiqueRail)
            contentDescription = "Volume $nom"
        }
        val pourcent = texte(14f, Couleur.TEXTE_2).apply {
            gravity = Gravity.END
            minWidth = dp(52)
        }
        ligne.addView(case, LinearLayout.LayoutParams(dp(160), LinearLayout.LayoutParams.WRAP_CONTENT))
        ligne.addView(volume, LinearLayout.LayoutParams(0, dp(40), 1f))
        ligne.addView(pourcent, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT))
        val l = Ligne(id, case, volume, pourcent)
        lignes.add(l)
        case.setOnClickListener { cocher(l, case.isChecked) }
        volume.setOnSeekBarChangeListener(object : SeekBar.OnSeekBarChangeListener {
            override fun onProgressChanged(s: SeekBar?, p: Int, deUtilisateur: Boolean) {
                if (deUtilisateur) pourcent.text = "$p %"
            }

            override fun onStartTrackingTouch(s: SeekBar?) {
                l.glisse = true
            }

            override fun onStopTrackingTouch(s: SeekBar?) {
                l.glisse = false
                l.volumeLe = SystemClock.elapsedRealtime()
                val avant = Etat.courant.enceintes.firstOrNull { it.id == id }?.volume ?: 0.0
                val v = volume.progress / 100.0
                // Baisser reste permis la nuit au salon (volume_down, Maison.commandeMedia).
                Etat.actionMedia?.invoke(id, "volume_set", JSONObject().put("volume_level", v).put("baisse", v < avant))
            }
        })
        return ligne
    }

    /** On coche ou décoche une enceinte : décision de SortieSon, sécurité, puis envoi. */
    private fun cocher(l: Ligne, oui: Boolean) {
        val e = Etat.courant.enceintes
        val d = SortieSon.basculer(e, l.id, oui)
        val c = d.commande
        if (c == null) {
            l.caseACocher.isChecked = !oui
            if (d.message != null) montrer(d.message)
            return
        }
        // Vérifiée ici pour répondre tout de suite, et de nouveau avant l'envoi (Maison.commande).
        val refus = SortieSon.refus(c, personne = Etat.courant.quiParle())
        if (refus != null) {
            l.caseACocher.isChecked = !oui
            montrer("Je ne le fais pas : $refus")
            return
        }
        val action = Etat.actionService
        if (action == null) {
            l.caseACocher.isChecked = !oui
            montrer("assistant est arrêté : commande non envoyée")
            return
        }
        l.caseVoulue = oui
        l.caseLe = SystemClock.elapsedRealtime()
        action("media_player.${c.service}", c.corps(), c.verification())
    }

    private fun montrer(texte: String) {
        messageLocal = texte
        messageLocalLe = SystemClock.elapsedRealtime()
        message.text = texte
        message.visibility = View.VISIBLE
    }

    /** Nouvel état : lecteur suivi, enceintes, message de refus de la passerelle. */
    fun maj(e: Etat.Instantane) {
        if (vue.visibility != View.VISIBLE) return
        val l = carte.courant
        if (l == null) {
            titre.text = "Rien ne joue en ce moment"
            artiste.text = "Lance une musique à la voix, puis choisis ici où l'écouter"
            pochette.setImageDrawable(null)
            imageMontree = null
            lecture.forme = BoutonMedia.Forme.LECTURE
            suivantTitre.visibility = View.GONE
            suivant.visibility = View.GONE
        } else {
            titre.text = l.titre.ifBlank { "Lecture en cours" }
            artiste.text = listOf(l.artiste, "sur ${l.nom}").filter { it.isNotBlank() }.joinToString(", ")
            lecture.forme = if (l.etat == "playing") BoutonMedia.Forme.PAUSE else BoutonMedia.Forme.LECTURE
            val image = carte.image
            if (image !== imageMontree) {
                imageMontree = image
                if (image != null) pochette.setImageBitmap(image) else pochette.setImageDrawable(null)
            }
            barre.teinte = carte.teinte
            // « À suivre » seulement si le lecteur l'annonce.
            val montrer = l.suivant.isNotBlank()
            suivantTitre.visibility = if (montrer) View.VISIBLE else View.GONE
            suivant.visibility = if (montrer) View.VISIBLE else View.GONE
            suivant.text = l.suivant
        }
        majLecteurs()
        majEnceintes(e.enceintes)
        // Dernier message : refus local, ou réponse de la passerelle (Maison.bref), 8 s au plus.
        val t = SystemClock.elapsedRealtime()
        val texte = when {
            e.brefLe > messageLocalLe && t - e.brefLe < DUREE_MESSAGE_MS -> e.bref
            t - messageLocalLe < DUREE_MESSAGE_MS -> messageLocal
            else -> ""
        }
        message.text = texte
        message.visibility = if (texte.isEmpty()) View.GONE else View.VISIBLE
        tic()
    }

    private fun majLecteurs() {
        val liste = carte.lecteurs
        val courant = carte.courant?.id ?: ""
        val cle = liste.joinToString(",") { it.id + it.etat } + "|" + courant
        if (cle == cleLecteurs) return
        cleLecteurs = cle
        lecteurs.removeAllViews()
        defileLecteurs.visibility = if (liste.size > 1) View.VISIBLE else View.GONE
        if (liste.size < 2) return
        for ((i, x) in liste.withIndex()) {
            val actif = x.id == courant
            lecteurs.addView(texte(15f, if (actif) Palette.texteSurClair else Couleur.TEXTE_2, "sans-serif-medium").apply {
                text = x.nom
                setPadding(dp(16), dp(8), dp(16), dp(8))
                background = if (actif) Decor.fondBouton(ctx, Couleur.OR, 16f) else Decor.uni(ctx, Palette.musiqueLecteur, 16f)
                isClickable = true
                setOnClickListener {
                    carte.choisir(x.id)
                    maj(Etat.courant)
                }
            }, LinearLayout.LayoutParams(LinearLayout.LayoutParams.WRAP_CONTENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
                if (i > 0) marginStart = dp(8)
            })
        }
    }

    private fun majEnceintes(enceintes: List<SortieSon.Enceinte>) {
        val cochees = SortieSon.cochees(enceintes)
        val meneur = SortieSon.meneur(enceintes)
        val t = SystemClock.elapsedRealtime()
        for (l in lignes) {
            val e = enceintes.firstOrNull { it.id == l.id }
            l.caseACocher.isEnabled = e != null
            l.volume.isEnabled = e != null
            l.caseACocher.alpha = if (e == null) 0.4f else 1f
            if (e == null) {
                l.pourcent.text = "-"
                continue
            }
            // Choix récent fait au doigt gardé 5 s, le temps que HA le confirme.
            val voulue = l.caseVoulue
            if (voulue != null && t - l.caseLe < ATTENTE_CONFIRMATION_MS) {
                l.caseACocher.isChecked = voulue
            } else {
                l.caseVoulue = null
                l.caseACocher.isChecked = e.id in cochees
            }
            // Une enceinte qui ne se regroupe pas reste utilisable seule, pas en groupe.
            val seule = !e.regroupable && meneur != null && meneur.id != e.id
            l.caseACocher.text = if (seule) "${SortieSon.nomCourt(e.id)}\nne se regroupe pas" else SortieSon.nomCourt(e.id)
            if (!l.glisse && t - l.volumeLe > ATTENTE_CONFIRMATION_MS) {
                val p = Math.round(e.volume * 100).toInt().coerceIn(0, 100)
                // Enceinte déjà plus haut (réglée depuis l'appli Enceintes) : piste pleine, valeur lue affichée telle quelle.
                l.volume.progress = p.coerceAtMost(l.volume.max)
                l.pourcent.text = "$p %"
            }
        }
    }

    /** Toutes les secondes : la progression avance entre deux lectures de HA. */
    fun tic() {
        if (vue.visibility != View.VISIBLE) return
        val l = carte.courant
        if (l == null || l.duree <= 0.0) {
            barre.fraction = 0f
            tempsPasse.text = ""
            tempsTotal.text = ""
            return
        }
        val pos = CarteEnCours.position(l, System.currentTimeMillis())
        barre.fraction = (pos / l.duree).toFloat()
        tempsPasse.text = CarteEnCours.minutes(pos)
        tempsTotal.text = CarteEnCours.minutes(l.duree)
    }

    companion object {
        const val DUREE_MESSAGE_MS = 8_000L
        const val ATTENTE_CONFIRMATION_MS = 5_000L
    }
}
