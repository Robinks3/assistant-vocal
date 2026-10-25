package assistant.vocal.jarvis

import android.Manifest
import android.app.Activity
import android.app.AlertDialog
import android.content.pm.PackageManager
import android.graphics.Color
import android.graphics.Typeface
import android.os.Bundle
import android.os.SystemClock
import android.text.InputType
import android.util.Size
import android.util.TypedValue
import android.view.Gravity
import android.view.View
import android.view.WindowInsets
import android.widget.EditText
import android.widget.FrameLayout
import android.widget.LinearLayout
import android.widget.ScrollView
import android.widget.TextView
import android.widget.Toast
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.Preview
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.camera.view.PreviewView
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import java.util.Locale
import java.util.concurrent.Executors
import kotlin.math.abs

/**
 * Enrôlement des visages (0.16.0) : un prénom, puis une capture guidée en 5 positions avec l'aperçu
 * de la caméra (de face, tourné d'un côté puis de l'autre, en levant puis en baissant la tête).
 * La moyenne des empreintes est enregistrée, jamais d'image. Liste des profils avec Supprimer.
 *
 * Pendant que cet écran est ouvert, la vision du service rend la caméra (une seule appli à la
 * fois peut s'en servir) et la reprend en sortant. L'analyse se fait ici sur la tablette (OpenCV),
 * avec le même modèle SFace que le PC : les empreintes sont comparables quel que soit le moteur.
 */
class VisagesActivity : Activity(), LifecycleOwner {

    private val registre = LifecycleRegistry(this)
    override val lifecycle: Lifecycle get() = registre

    private val fil = Executors.newSingleThreadExecutor()
    private var moteur: MoteurVisageLocal? = null
    private var fournisseur: ProcessCameraProvider? = null

    private lateinit var listeProfils: LinearLayout
    private lateinit var champNom: EditText
    private lateinit var boutonCommencer: TextView
    private lateinit var zoneCapture: LinearLayout
    private lateinit var apercu: PreviewView
    private lateinit var texteConsigne: TextView
    private lateinit var texteProgres: TextView

    /** Une position de la capture guidée : consigne et condition sur la pose du visage. */
    private class Position(val consigne: String, val accepte: (Geometrie.Pose) -> Boolean)

    // État de la capture, lu et écrit sur le fil d'analyse seulement.
    @Volatile private var enCapture = false
    private var nom = ""
    private var rang = 0
    private var debutPosition = 0L
    private val vuesPosition = ArrayList<FloatArray>()
    private val vues = ArrayList<FloatArray>()
    private var hauteurFace = 0.7f
    private var signeCote = 0f
    private var positions: List<Position> = emptyList()

    private fun dp(v: Int): Int = Decor.dp(this, v.toFloat())

    private fun texte(taille: Float, couleur: Int = Couleur.TEXTE, gras: Boolean = false): TextView =
        TextView(this).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, taille)
            setTextColor(couleur)
            if (gras) typeface = Typeface.create("sans-serif-medium", Typeface.NORMAL)
            setLineSpacing(0f, 1.15f)
        }

    private fun bouton(libelle: String, couleur: Int, action: () -> Unit): TextView =
        texte(16f, Color.WHITE, gras = true).apply {
            text = libelle
            gravity = Gravity.CENTER
            minHeight = dp(52)
            setPadding(dp(18), dp(8), dp(18), dp(8))
            background = Decor.fondBouton(this@VisagesActivity, couleur, 14f)
            setOnClickListener { action() }
        }

    private fun marge(haut: Int = 0, bas: Int = 0) =
        LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, LinearLayout.LayoutParams.WRAP_CONTENT).apply {
            topMargin = dp(haut)
            bottomMargin = dp(bas)
        }

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        registre.currentState = Lifecycle.State.CREATED
        @Suppress("DEPRECATION")
        window.statusBarColor = Couleur.NUIT_HAUT
        setContentView(construire())
        afficherProfils()
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.CAMERA), 1)
        }
    }

    override fun onStart() {
        super.onStart()
        registre.currentState = Lifecycle.State.STARTED
    }

    override fun onResume() {
        super.onResume()
        registre.currentState = Lifecycle.State.RESUMED
    }

    override fun onPause() {
        arreterCapture(null)
        registre.currentState = Lifecycle.State.STARTED
        super.onPause()
    }

    override fun onStop() {
        registre.currentState = Lifecycle.State.CREATED
        super.onStop()
    }

    override fun onDestroy() {
        registre.currentState = Lifecycle.State.DESTROYED
        fil.execute { moteur = null }
        fil.shutdown()
        super.onDestroy()
    }

    private fun construire(): View {
        val colonne = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            setPadding(dp(20), dp(16), dp(20), dp(24))
        }
        colonne.addView(texte(30f, gras = true).apply { text = "Visages" })
        colonne.addView(texte(15f, Couleur.TEXTE_2).apply {
            text = "${ConfigMaison.NOM_ASSISTANT} reconnaît les personnes enregistrées ici. Seule une empreinte de 128 nombres est gardée, " +
                "dans un fichier privé de cette tablette, jamais une image. N'enregistre quelqu'un qu'avec son accord."
        }, marge(haut = 6, bas = 18))

        val carteProfils = carte("Profils enregistrés")
        listeProfils = LinearLayout(this).apply { orientation = LinearLayout.VERTICAL }
        carteProfils.addView(listeProfils, marge())
        colonne.addView(carteProfils, marge(bas = 16))

        val carteAjout = carte("Nouveau visage")
        champNom = EditText(this).apply {
            setTextSize(TypedValue.COMPLEX_UNIT_SP, 18f)
            setTextColor(Couleur.TEXTE)
            setHintTextColor(Couleur.GRIS)
            hint = "Prénom"
            inputType = InputType.TYPE_CLASS_TEXT or InputType.TYPE_TEXT_FLAG_CAP_WORDS
            setSingleLine(true)
            background = Decor.fondCreux(this@VisagesActivity, 12f)
            setPadding(dp(14), dp(12), dp(14), dp(12))
        }
        carteAjout.addView(champNom, marge(bas = 12))
        boutonCommencer = bouton("Commencer l'enregistrement", Couleur.BLEU) { commencer() }
        carteAjout.addView(boutonCommencer, marge())

        zoneCapture = LinearLayout(this).apply {
            orientation = LinearLayout.VERTICAL
            visibility = View.GONE
        }
        apercu = PreviewView(this).apply { scaleType = PreviewView.ScaleType.FILL_CENTER }
        val cadre = FrameLayout(this).apply {
            background = Decor.fondCreux(this@VisagesActivity, 16f)
            clipToOutline = true
            addView(apercu, FrameLayout.LayoutParams(FrameLayout.LayoutParams.MATCH_PARENT, FrameLayout.LayoutParams.MATCH_PARENT))
        }
        zoneCapture.addView(cadre, LinearLayout.LayoutParams(LinearLayout.LayoutParams.MATCH_PARENT, dp(320)).apply { topMargin = dp(14) })
        texteConsigne = texte(22f, Couleur.BLEU_CLAIR, gras = true).apply { gravity = Gravity.CENTER }
        zoneCapture.addView(texteConsigne, marge(haut = 12))
        texteProgres = texte(15f, Couleur.TEXTE_2).apply { gravity = Gravity.CENTER }
        zoneCapture.addView(texteProgres, marge(haut = 4, bas = 10))
        zoneCapture.addView(bouton("Annuler", Couleur.CHAMP) { arreterCapture("Enregistrement annulé") }, marge())
        carteAjout.addView(zoneCapture, marge())
        colonne.addView(carteAjout, marge(bas = 16))

        colonne.addView(bouton("Retour", Couleur.CHAMP) { finish() }, marge(haut = 4))
        colonne.addView(texte(12.5f, Couleur.GRIS).apply {
            text = "Version ${BuildConfig.VERSION_BASE}, compilée le ${BuildConfig.HORODATAGE_COMPILATION}"
            gravity = Gravity.CENTER_HORIZONTAL
        }, marge(haut = 14))

        return ScrollView(this).apply {
            background = Decor.fondNuit(this@VisagesActivity)
            isFillViewport = true
            addView(colonne)
            setOnApplyWindowInsetsListener { v, insets ->
                if (android.os.Build.VERSION.SDK_INT >= 30) {
                    val i = insets.getInsets(WindowInsets.Type.systemBars() or WindowInsets.Type.ime())
                    v.setPadding(i.left, i.top, i.right, i.bottom)
                }
                insets
            }
        }
    }

    private fun carte(titre: String): LinearLayout = LinearLayout(this).apply {
        orientation = LinearLayout.VERTICAL
        background = Decor.fondCarte(this@VisagesActivity)
        setPadding(dp(18), dp(16), dp(18), dp(18))
        addView(texte(12.5f, Couleur.TEXTE_2, gras = true).apply {
            text = titre.uppercase(Locale.FRANCE)
            letterSpacing = 0.1f
        }, marge(bas = 10))
    }

    private fun afficherProfils() {
        listeProfils.removeAllViews()
        val profils = ProfilsVisages.lire(this)
        if (profils.isEmpty()) {
            listeProfils.addView(texte(15f, Couleur.TEXTE_2).apply { text = "Aucun visage enregistré" })
            return
        }
        for (p in profils) {
            val ligne = LinearLayout(this).apply {
                orientation = LinearLayout.HORIZONTAL
                gravity = Gravity.CENTER_VERTICAL
            }
            ligne.addView(texte(18f, gras = true).apply { text = p.nom }, LinearLayout.LayoutParams(0, LinearLayout.LayoutParams.WRAP_CONTENT, 1f))
            ligne.addView(bouton("Supprimer", Decor.assombrir(Couleur.ROUGE, 0.1f)) { supprimer(p) })
            listeProfils.addView(ligne, marge(bas = 8))
        }
    }

    private fun supprimer(p: Profil) {
        AlertDialog.Builder(this)
            .setTitle("Supprimer ${p.nom}")
            .setMessage("L'empreinte de ${p.nom} sera effacée de cette tablette. ${ConfigMaison.NOM_ASSISTANT} ne le reconnaîtra plus.")
            .setPositiveButton("Supprimer") { _, _ ->
                ProfilsVisages.supprimer(this, p.id)
                Etat.actionVisionRecharger?.invoke()
                afficherProfils()
            }
            .setNegativeButton("Annuler", null)
            .show()
    }

    // ------------------------------------------------------------ capture guidée

    private fun commencer() {
        val prenom = champNom.text.toString().trim()
        if (prenom.isEmpty()) {
            Toast.makeText(this, "Écris d'abord le prénom", Toast.LENGTH_LONG).show()
            return
        }
        if (checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            requestPermissions(arrayOf(Manifest.permission.CAMERA), 1)
            return
        }
        // La caméra est rendue par le service le temps de l'enregistrement.
        Etat.actionVisionSuspendre?.invoke(true)
        zoneCapture.visibility = View.VISIBLE
        boutonCommencer.visibility = View.GONE
        champNom.isEnabled = false
        consigne("Préparation de la caméra", "")
        positions = listOf(
            Position("Regarde la tablette, de face") { abs(it.lacet) < 0.12f },
            Position("Tourne un peu la tête d'un côté") { abs(it.lacet) in 0.12f..0.5f },
            Position("Maintenant de l'autre côté") { abs(it.lacet) in 0.12f..0.5f && it.lacet * signeCote < 0f },
            Position("De face, lève un peu la tête") { abs(it.lacet) < 0.2f && it.hauteur < hauteurFace - 0.07f },
            Position("De face, baisse un peu la tête") { abs(it.lacet) < 0.2f && it.hauteur > hauteurFace + 0.07f },
        )
        fil.execute {
            nom = prenom
            rang = 0
            signeCote = 0f
            vues.clear()
            vuesPosition.clear()
            debutPosition = SystemClock.elapsedRealtime()
            enCapture = true
        }
        lierCamera()
        majConsigne()
    }

    private fun lierCamera() {
        val f = ProcessCameraProvider.getInstance(this)
        f.addListener({
            try {
                val p = f.get()
                fournisseur = p
                p.unbindAll()
                val preview = Preview.Builder().build().also { it.surfaceProvider = apercu.surfaceProvider }
                val analyse = ImageAnalysis.Builder()
                    .setResolutionSelector(
                        ResolutionSelector.Builder()
                            .setResolutionStrategy(ResolutionStrategy(Size(640, 480), ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER))
                            .build()
                    )
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
                    .build()
                analyse.setAnalyzer(fil) { image -> analyser(image) }
                p.bindToLifecycle(this, CameraSelector.DEFAULT_FRONT_CAMERA, preview, analyse)
            } catch (e: Exception) {
                arreterCapture("Caméra indisponible (${e.javaClass.simpleName})")
            }
        }, mainExecutor)
    }

    /** Fil d'analyse : chaque image, la pose du visage et, si elle convient, son empreinte. */
    private fun analyser(image: ImageProxy) {
        if (!enCapture) {
            image.close()
            return
        }
        val bmp = try {
            Vision.reduire(image.toBitmap(), image.imageInfo.rotationDegrees)
        } catch (_: Exception) {
            null
        } finally {
            image.close()
        }
        if (bmp == null) return
        val m = moteur ?: try {
            MoteurVisageLocal(this).also { moteur = it }
        } catch (e: Throwable) {
            runOnUiThread { arreterCapture("OpenCV indisponible : ${e.message ?: e.javaClass.simpleName}") }
            bmp.recycle()
            return
        }
        val visages = try {
            m.analyser(bmp)
        } catch (_: Exception) {
            emptyList()
        } finally {
            bmp.recycle()
        }
        val maintenant = SystemClock.elapsedRealtime()
        val ecoule = maintenant - debutPosition
        if (visages.size != 1) {
            montrer(if (visages.isEmpty()) "Aucun visage vu" else "Une seule personne devant la caméra")
            if (ecoule > 25_000) runOnUiThread { arreterCapture("Pas de visage vu assez longtemps, recommence") }
            return
        }
        val v = visages[0]
        val pose = Geometrie.pose(v.points)
        val assezGrand = minOf(v.boite[2], v.boite[3]) >= 40f
        // Après 10 s sans la bonne pose, on accepte la position telle qu'elle est.
        val ok = assezGrand && (positions[rang].accepte(pose) || ecoule > 10_000)
        if (!assezGrand) montrer("Rapproche-toi un peu")
        if (!ok) return
        if (rang == 0) hauteurFace = pose.hauteur
        if (rang == 1 && signeCote == 0f) signeCote = if (pose.lacet >= 0f) 1f else -1f
        vuesPosition.add(v.empreinte)
        montrer("Image ${vuesPosition.size} sur $VUES_PAR_POSITION")
        if (vuesPosition.size >= VUES_PAR_POSITION) {
            vues.addAll(vuesPosition)
            vuesPosition.clear()
            rang++
            debutPosition = maintenant
            if (rang >= positions.size) {
                enCapture = false
                val empreinte = Empreintes.moyenne(vues)
                val prenom = nom
                runOnUiThread { terminer(prenom, empreinte) }
            } else {
                runOnUiThread { majConsigne() }
            }
        }
    }

    private fun montrer(progres: String) = runOnUiThread { texteProgres.text = progres }

    private fun majConsigne() {
        val r = rang.coerceAtMost(positions.size - 1)
        consigne("${r + 1} sur ${positions.size} : ${positions[r].consigne}", "")
    }

    private fun consigne(c: String, progres: String) {
        texteConsigne.text = c
        texteProgres.text = progres
    }

    private fun terminer(prenom: String, empreinte: FloatArray) {
        ProfilsVisages.ajouter(this, prenom, empreinte)
        Etat.actionVisionRecharger?.invoke()
        champNom.setText("")
        arreterCapture("Visage de $prenom enregistré")
        afficherProfils()
    }

    /** Fin de capture : caméra rendue au service. [message] affiché s'il n'est pas nul. */
    private fun arreterCapture(message: String?) {
        enCapture = false
        try {
            fournisseur?.unbindAll()
        } catch (_: Exception) {
        }
        fournisseur = null
        if (::zoneCapture.isInitialized && zoneCapture.visibility == View.VISIBLE) {
            zoneCapture.visibility = View.GONE
            boutonCommencer.visibility = View.VISIBLE
            champNom.isEnabled = true
            Etat.actionVisionSuspendre?.invoke(false)
        }
        if (message != null) Toast.makeText(this, message, Toast.LENGTH_LONG).show()
    }

    companion object {
        /** Empreintes gardées par position, 15 en tout pour les 5 positions. */
        const val VUES_PAR_POSITION = 3
    }
}
