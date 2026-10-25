package assistant.vocal.jarvis

import android.Manifest
import android.content.Context
import android.content.pm.PackageManager
import android.graphics.Bitmap
import android.graphics.Matrix
import android.os.Handler
import android.os.Looper
import android.os.SystemClock
import android.util.Base64
import android.util.Log
import android.util.Size
import androidx.camera.core.CameraSelector
import androidx.camera.core.ImageAnalysis
import androidx.camera.core.ImageProxy
import androidx.camera.core.resolutionselector.ResolutionSelector
import androidx.camera.core.resolutionselector.ResolutionStrategy
import androidx.camera.lifecycle.ProcessCameraProvider
import androidx.lifecycle.Lifecycle
import androidx.lifecycle.LifecycleOwner
import androidx.lifecycle.LifecycleRegistry
import okhttp3.OkHttpClient
import okhttp3.Response
import okhttp3.WebSocket
import okhttp3.WebSocketListener
import org.json.JSONArray
import org.json.JSONObject
import org.opencv.android.OpenCVLoader
import org.opencv.android.Utils
import org.opencv.core.CvType
import org.opencv.core.Mat
import org.opencv.imgproc.Imgproc
import org.opencv.objdetect.FaceDetectorYN
import org.opencv.objdetect.FaceRecognizerSF
import java.io.ByteArrayOutputStream
import java.io.File
import java.util.Locale
import java.util.concurrent.CompletableFuture
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicInteger

/**
 * Vision de la tablette (0.16.0) : caméra avant, visages, présence et regard.
 *
 * La caméra filme une pièce commune : la vision est désactivée par défaut, et aucune image n'est
 * jamais gardée, ni ici ni sur le PC. Chaque image est réduite à 320 x 240 environ, analysée puis
 * oubliée. Seules les empreintes des profils enregistrés (128 nombres) restent, dans un fichier
 * privé de l'appli.
 *
 * Deux moteurs : OpenCV sur la tablette (YuNet pour trouver les visages, SFace pour l'empreinte),
 * ou le serveur du PC (poc/vision.py, mêmes modèles) par une connexion wss dédiée. Si le PC ne
 * répond pas, l'analyse repasse sur la tablette. La reconnaissance (Reconnaissance.kt) tourne
 * toujours ici : les profils ne quittent jamais la tablette.
 *
 * 2 images par seconde sans personne, 5 quand quelqu'un est là. Le cycle de vie est porté par
 * cette classe elle-même (LifecycleOwner), sur le fil principal, comme CameraX l'exige.
 */
class Vision(
    private val contexte: Context,
    @Volatile var mode: String,
    private val surPresence: (Boolean) -> Unit,
    private val surRegard: () -> Unit,
) : LifecycleOwner, AutoCloseable {

    private val registre = LifecycleRegistry(this)
    override val lifecycle: Lifecycle get() = registre

    private val principal = Handler(Looper.getMainLooper())
    private val fil = Executors.newSingleThreadExecutor()
    private var fournisseur: ProcessCameraProvider? = null
    @Volatile private var suspendue = false
    @Volatile private var ferme = false
    @Volatile private var derniereImageLe = 0L
    @Volatile private var dernierTraitementLe = 0L
    @Volatile private var liaisonLe = 0L

    // Utilisés seulement par le fil d'analyse.
    private var local: MoteurVisageLocal? = null
    private var localEchec: String? = null
    private var pc: VisionPc? = null
    private val reconnaissance = Reconnaissance(ProfilsVisages.lire(contexte))
    private val presence = Presence()
    private val regard = RegardSoutenu()
    private var msDerniere = 0L
    private var moteurUtilise = ""

    init {
        registre.currentState = Lifecycle.State.CREATED
    }

    /** À appeler sur le fil principal. */
    fun demarrer() {
        if (ferme) return
        registre.currentState = Lifecycle.State.RESUMED
        publier("Démarrage de la caméra", "attente")
        lier()
    }

    private fun lier() {
        if (ferme || suspendue || mode == "off") return
        if (contexte.checkSelfPermission(Manifest.permission.CAMERA) != PackageManager.PERMISSION_GRANTED) {
            publier("Caméra non autorisée : ouvre ${ConfigMaison.NOM_ASSISTANT} et accepte la caméra", "erreur")
            return
        }
        liaisonLe = SystemClock.elapsedRealtime()
        val f = ProcessCameraProvider.getInstance(contexte)
        f.addListener({
            if (ferme || suspendue) return@addListener
            try {
                val p = f.get()
                fournisseur = p
                p.unbindAll()
                val analyse = ImageAnalysis.Builder()
                    .setResolutionSelector(
                        ResolutionSelector.Builder()
                            .setResolutionStrategy(
                                ResolutionStrategy(Size(320, 240), ResolutionStrategy.FALLBACK_RULE_CLOSEST_HIGHER_THEN_LOWER)
                            )
                            .build()
                    )
                    .setBackpressureStrategy(ImageAnalysis.STRATEGY_KEEP_ONLY_LATEST)
                    .setOutputImageFormat(ImageAnalysis.OUTPUT_IMAGE_FORMAT_RGBA_8888)
                    .build()
                analyse.setAnalyzer(fil) { image -> recevoir(image) }
                p.bindToLifecycle(this, CameraSelector.DEFAULT_FRONT_CAMERA, analyse)
                derniereImageLe = SystemClock.elapsedRealtime()
            } catch (e: Exception) {
                Log.e(TAG, "Caméra impossible", e)
                publier("Caméra indisponible (${e.javaClass.simpleName})", "erreur")
            }
        }, { principal.post(it) })
    }

    private fun delier() {
        try {
            fournisseur?.unbindAll()
        } catch (_: Exception) {
        }
    }

    /** Écran d'enrôlement ouvert : il prend la caméra, la vision la rend puis la reprend. Fil principal. */
    fun suspendre(oui: Boolean) {
        if (oui == suspendue) return
        suspendue = oui
        if (oui) {
            delier()
            publier("Caméra prêtée à l'écran des visages", "attente")
            fixerPresence(false)
        } else {
            lier()
        }
    }

    fun changerMode(m: String) {
        if (m == mode) return
        mode = m
        if (m == "off") {
            delier()
            publier("", "")
            fixerPresence(false)
        } else {
            lier()
        }
    }

    fun rechargerProfils() {
        fil.execute { reconnaissance.changerProfils(ProfilsVisages.lire(contexte)) }
    }

    /** Chien de garde (fil principal) : plus aucune image depuis 10 s alors que la caméra devrait tourner. */
    fun surveiller() {
        if (ferme || suspendue || mode == "off") return
        val maintenant = SystemClock.elapsedRealtime()
        if (maintenant - derniereImageLe > 10_000 && maintenant - liaisonLe > 10_000) {
            Log.w(TAG, "Plus d'image depuis 10 s, caméra relancée")
            delier()
            lier()
            publier("Caméra relancée par le chien de garde", "attente")
        }
    }

    // ------------------------------------------------------------ analyse (fil d'analyse)

    private fun recevoir(image: ImageProxy) {
        val maintenant = SystemClock.elapsedRealtime()
        derniereImageLe = maintenant
        // 2 images par seconde sans personne, 5 quand quelqu'un est là.
        val intervalle = if (presence.present) 200L else 500L
        if (maintenant - dernierTraitementLe < intervalle || mode == "off" || suspendue) {
            image.close()
            return
        }
        dernierTraitementLe = maintenant
        val bmp = try {
            reduire(image.toBitmap(), image.imageInfo.rotationDegrees)
        } catch (e: Exception) {
            Log.w(TAG, "Image illisible", e)
            null
        } finally {
            image.close()
        }
        if (bmp == null) return
        try {
            analyser(bmp, maintenant)
        } catch (e: Exception) {
            Log.w(TAG, "Analyse impossible", e)
            publier("Analyse impossible (${e.javaClass.simpleName})", "erreur")
        } finally {
            bmp.recycle()
        }
    }

    private fun analyser(bmp: Bitmap, t: Long) {
        val t0 = SystemClock.elapsedRealtime()
        var visages: List<Visage>? = null
        if (mode == "pc") {
            val v = pc ?: VisionPc(contexte, SatelliteService.adresse(contexte, "pc")).also { pc = it }
            v.ouvrir()
            if (v.disponible) {
                visages = v.analyser(enJpeg(bmp), 1500)
                moteurUtilise = if (visages != null) "pc" else "repli"
            } else {
                moteurUtilise = "repli"
            }
        } else {
            pc?.close()
            pc = null
            moteurUtilise = "tablette"
        }
        if (visages == null) visages = moteurLocal()?.analyser(bmp)
        if (visages == null) {
            publier(
                if (mode == "pc") "PC sans réponse (${pc?.etat}) et OpenCV indisponible sur la tablette (${localEchec ?: "?"})"
                else "OpenCV indisponible sur la tablette (${localEchec ?: "?"})",
                "erreur",
            )
            return
        }
        msDerniere = SystemClock.elapsedRealtime() - t0
        val personnes = reconnaissance.image(visages, t)
        noterBilan(t, msDerniere, visages.size, personnes)
        val change = presence.image(visages.size, t)
        if (change) fixerPresence(presence.present)
        val seul = personnes.size == 1
        val parlerEnRegardant = SatelliteService.preferences(contexte).getBoolean(SatelliteService.CLE_PARLER_REGARD, false)
        if (parlerEnRegardant && presence.present && regard.image(seul, personnes.firstOrNull()?.regard == true, t)) {
            principal.post { surRegard() }
        }
        val cadence = if (presence.present) 5 else 2
        val (texte, niveau) = when (moteurUtilise) {
            "pc" -> "Vision sur le PC, ${msDerniere} ms par image, $cadence images/s" to "ok"
            "repli" -> "PC sans réponse (${pc?.etat}), analyse sur la tablette, $cadence images/s" to "attente"
            else -> "Vision sur la tablette (OpenCV ${OpenCVLoader.OPENCV_VERSION}), ${msDerniere} ms par image, $cadence images/s" to "ok"
        }
        Etat.modifier {
            it.copy(
                personnes = if (presence.present) personnes else emptyList(),
                personnesLe = t,
                visionEtat = texte,
                visionNiveau = niveau,
            )
        }
    }

    // Bilan mesuré toutes les 10 s dans logcat (0.16.4) : la cadence affichée est la consigne, pas
    // la mesure. adb logcat -s JarvisVision donne les images par seconde et le temps d'analyse réels.
    private var bilanDepuis = 0L
    private var bilanImages = 0
    private var bilanMs = 0L
    private var bilanMax = 0L
    private var bilanVisages = 0

    private fun noterBilan(t: Long, ms: Long, visages: Int, personnes: List<PersonneVue>) {
        if (bilanDepuis == 0L) bilanDepuis = t
        bilanImages++
        bilanMs += ms
        bilanMax = maxOf(bilanMax, ms)
        bilanVisages += visages
        val duree = t - bilanDepuis
        if (duree < 10_000) return
        Log.i(
            TAG,
            "bilan ${duree / 1000} s : moteur $moteurUtilise, $bilanImages images (" +
                "%.1f".format(Locale.FRANCE, bilanImages * 1000.0 / duree) + "/s), analyse moyenne ${bilanMs / bilanImages} ms, " +
                "max $bilanMax ms, visages par image " + "%.2f".format(Locale.FRANCE, bilanVisages.toDouble() / bilanImages) +
                ", présence ${presence.present}, personnes " +
                personnes.joinToString(", ") { it.nom ?: if (it.inconnu) "inconnu" else "pas encore sûr" }.ifEmpty { "aucune" },
        )
        bilanDepuis = t
        bilanImages = 0
        bilanMs = 0
        bilanMax = 0
        bilanVisages = 0
    }

    private fun moteurLocal(): MoteurVisageLocal? {
        local?.let { return it }
        if (localEchec != null) return null
        return try {
            MoteurVisageLocal(contexte).also { local = it }
        } catch (e: Throwable) {
            Log.e(TAG, "OpenCV impossible", e)
            localEchec = e.message ?: e.javaClass.simpleName
            null
        }
    }

    private fun fixerPresence(p: Boolean) {
        Etat.modifier { it.copy(presence = p, personnes = if (p) it.personnes else emptyList()) }
        principal.post { surPresence(p) }
    }

    private fun publier(texte: String, niveau: String) {
        Etat.modifier { it.copy(visionEtat = texte, visionNiveau = niveau) }
    }

    override fun close() {
        ferme = true
        principal.post {
            delier()
            registre.currentState = Lifecycle.State.DESTROYED
        }
        fil.execute {
            try {
                local?.close()
            } catch (_: Exception) {
            }
            pc?.close()
            local = null
            pc = null
        }
        fil.shutdown()
        Etat.modifier { it.copy(presence = false, personnes = emptyList(), visionEtat = "", visionNiveau = "") }
    }

    companion object {
        private const val TAG = "JarvisVision"

        /** Image tournée à l'endroit et réduite à 320 pixels de large au plus. */
        fun reduire(source: Bitmap, rotation: Int): Bitmap {
            val echelle = minOf(1f, 320f / maxOf(source.width, source.height).toFloat().coerceAtLeast(1f))
            if (rotation == 0 && echelle >= 0.999f) return source
            val m = Matrix().apply {
                postScale(echelle, echelle)
                postRotate(rotation.toFloat())
            }
            val r = Bitmap.createBitmap(source, 0, 0, source.width, source.height, m, true)
            if (r !== source) source.recycle()
            return r
        }

        fun enJpeg(bmp: Bitmap): ByteArray {
            val sortie = ByteArrayOutputStream()
            bmp.compress(Bitmap.CompressFormat.JPEG, 80, sortie)
            return sortie.toByteArray()
        }
    }
}

/**
 * Moteur de visages sur la tablette, OpenCV 4.14 : FaceDetectorYN (YuNet, seuil 0,7, nms 0,3) et
 * FaceRecognizerSF (SFace, alignement sur les 5 points puis empreinte de 128 nombres). Les deux
 * modèles sont copiés des assets dans les fichiers de l'appli, OpenCV ne lit qu'un chemin.
 */
class MoteurVisageLocal(contexte: Context) : AutoCloseable {
    private val detecteur: FaceDetectorYN
    private val reconnaisseur: FaceRecognizerSF

    init {
        check(OpenCVLoader.initLocal()) { "bibliothèque OpenCV introuvable" }
        val dossier = File(contexte.filesDir, "vision").apply { mkdirs() }
        // Recopie à chaque mise à jour de l'appli. Pas d'openFd pour connaître la taille : les .onnx
        // sont compressés dans l'APK et openFd y échoue (« probably compressed », vu sur la tablette le
        // 21/10/2026 : vision sur la tablette jamais démarrée en 0.16.0 à 0.16.3).
        val majApk = contexte.packageManager.getPackageInfo(contexte.packageName, 0).lastUpdateTime
        fun copier(nom: String): String {
            val f = File(dossier, nom)
            if (!f.isFile || f.length() == 0L || f.lastModified() < majApk) {
                val provisoire = File(dossier, "$nom.part")
                contexte.assets.open("vision/$nom").use { e -> provisoire.outputStream().use { e.copyTo(it) } }
                check(provisoire.renameTo(f) || (f.delete() && provisoire.renameTo(f))) { "copie de $nom impossible" }
            }
            return f.absolutePath
        }
        detecteur = FaceDetectorYN.create(copier("yunet.onnx"), "", org.opencv.core.Size(320.0, 240.0), SEUIL_VISAGE, NMS, 20)
        reconnaisseur = FaceRecognizerSF.create(copier("sface.onnx"), "")
    }

    @Synchronized
    fun analyser(bmp: Bitmap): List<Visage> {
        val rgba = Mat()
        val bgr = Mat()
        val visages = Mat()
        try {
            Utils.bitmapToMat(bmp, rgba)
            Imgproc.cvtColor(rgba, bgr, Imgproc.COLOR_RGBA2BGR)
            detecteur.inputSize = org.opencv.core.Size(bgr.cols().toDouble(), bgr.rows().toDouble())
            detecteur.detect(bgr, visages)
            val sortie = ArrayList<Visage>()
            for (i in 0 until visages.rows()) {
                val ligne = FloatArray(15)
                visages.get(i, 0, ligne)
                val points = ligne.copyOfRange(4, 14)
                val aligne = Mat()
                val empreinte = Mat()
                try {
                    reconnaisseur.alignCrop(bgr, visages.row(i), aligne)
                    reconnaisseur.feature(aligne, empreinte)
                    val e = Mat()
                    empreinte.convertTo(e, CvType.CV_32F)
                    val v = FloatArray(e.total().toInt())
                    e.get(0, 0, v)
                    e.release()
                    sortie.add(
                        Visage(
                            ligne.copyOfRange(0, 4), ligne[14], points, Geometrie.regard(points),
                            Geometrie.pose(points).lacet, Empreintes.normaliser(v),
                        )
                    )
                } finally {
                    aligne.release()
                    empreinte.release()
                }
            }
            return sortie
        } finally {
            rgba.release()
            bgr.release()
            visages.release()
        }
    }

    override fun close() {}

    companion object {
        const val SEUIL_VISAGE = 0.7f
        const val NMS = 0.3f
    }
}

/**
 * Connexion dédiée vers le serveur du PC pour l'analyse d'image (serveur 0.18.0, capacité vision).
 * Même jeton et même épinglage de clé que le service (Confiance). Rien n'est gardé sur le PC.
 */
class VisionPc(private val contexte: Context, url: String) : AutoCloseable {
    private val adresse = url.trim().trimEnd('/')
    private val base = OkHttpClient.Builder()
        .pingInterval(20, TimeUnit.SECONDS)
        .connectTimeout(4, TimeUnit.SECONDS)
        .readTimeout(0, TimeUnit.MILLISECONDS)
        .build()
    @Volatile private var ws: WebSocket? = null
    @Volatile var disponible = false
        private set
    @Volatile var etat = "pas encore connecté"
        private set
    @Volatile private var ferme = false
    @Volatile private var prochainEssai = 0L
    private val identifiants = AtomicInteger(0)
    private val attentes = ConcurrentHashMap<Int, CompletableFuture<List<Visage>?>>()

    /** Ouvre la connexion si besoin, au plus une tentative toutes les 10 s. */
    fun ouvrir() {
        if (ferme || ws != null || SystemClock.elapsedRealtime() < prochainEssai) return
        synchronized(this) {
            if (ws != null) return
            prochainEssai = SystemClock.elapsedRealtime() + 10_000
            if (!Confiance.chiffree(adresse)) {
                // Pas d'image de la pièce en clair sur le réseau.
                etat = "adresse du PC non chiffrée ($adresse)"
                return
            }
            etat = "connexion"
            try {
                ws = Confiance.client(base, contexte, adresse).newWebSocket(Confiance.requete(contexte, adresse), Ecouteur())
            } catch (e: Exception) {
                etat = "adresse invalide"
                ws = null
            }
        }
    }

    /** Analyse une image JPEG, ou null si le PC ne répond pas dans le délai. */
    fun analyser(jpeg: ByteArray, delaiMs: Long): List<Visage>? {
        val socket = ws ?: return null
        if (!disponible) return null
        val id = identifiants.incrementAndGet()
        val promesse = CompletableFuture<List<Visage>?>()
        attentes[id] = promesse
        val msg = JSONObject().put("type", "vision").put("id", id).put("jpeg", Base64.encodeToString(jpeg, Base64.NO_WRAP))
        if (!socket.send(msg.toString())) {
            attentes.remove(id)
            return null
        }
        return try {
            promesse.get(delaiMs, TimeUnit.MILLISECONDS)
        } catch (_: Exception) {
            etat = "pas de réponse en ${delaiMs} ms"
            null
        } finally {
            attentes.remove(id)
        }
    }

    private fun perdu(socket: WebSocket, raison: String) {
        if (socket !== ws) return
        ws = null
        disponible = false
        etat = raison
        for (p in attentes.values) p.complete(null)
        attentes.clear()
    }

    private inner class Ecouteur : WebSocketListener() {
        override fun onOpen(webSocket: WebSocket, response: Response) {
            if (webSocket === ws) etat = "connecté, en attente des capacités"
        }

        override fun onMessage(webSocket: WebSocket, text: String) {
            if (webSocket !== ws) return
            val j = try {
                JSONObject(text)
            } catch (_: Exception) {
                return
            }
            when (j.optString("etat")) {
                "capacites" -> {
                    val annoncee = j.optString("empreinte")
                    val retenue = Confiance.empreinte(contexte, adresse)
                    if (annoncee.isNotEmpty() && retenue != null && annoncee != retenue) {
                        etat = "clé annoncée différente de la clé reçue : connexion coupée"
                        webSocket.cancel()
                        return
                    }
                    disponible = j.optBoolean("vision", false)
                    etat = if (disponible) "prêt (serveur v${j.optString("version")})"
                    else "serveur du PC sans vision (v${j.optString("version")}, 0.18.0 requise)"
                }
                "vision" -> {
                    val p = attentes.remove(j.optInt("id", -1)) ?: return
                    if (j.has("erreur")) {
                        etat = "erreur du PC : ${j.optString("erreur")}"
                        p.complete(null)
                    } else {
                        p.complete(lireVisages(j.optJSONArray("visages") ?: JSONArray()))
                    }
                }
            }
        }

        override fun onClosing(webSocket: WebSocket, code: Int, reason: String) {
            try {
                webSocket.close(1000, null)
            } catch (_: Exception) {
            }
        }

        override fun onClosed(webSocket: WebSocket, code: Int, reason: String) =
            perdu(webSocket, if (code == 4001) "jeton refusé par le PC" else "connexion fermée ($code)")

        override fun onFailure(webSocket: WebSocket, t: Throwable, response: Response?) {
            val cle = Confiance.cleChangee(t)
            perdu(webSocket, if (cle != null) "clé du PC refusée" else "PC injoignable (${t.javaClass.simpleName})")
        }
    }

    override fun close() {
        ferme = true
        val s = ws
        ws = null
        disponible = false
        for (p in attentes.values) p.complete(null)
        try {
            s?.close(1000, "fin")
        } catch (_: Exception) {
        }
        base.dispatcher.executorService.shutdown()
    }

    companion object {
        fun lireVisages(a: JSONArray): List<Visage> {
            val sortie = ArrayList<Visage>()
            for (i in 0 until a.length()) {
                val o = a.optJSONObject(i) ?: continue
                val b = o.optJSONArray("boite") ?: continue
                val pts = o.optJSONArray("points") ?: continue
                val emp = o.optJSONArray("empreinte") ?: continue
                if (b.length() < 4 || pts.length() < 5 || emp.length() < 16) continue
                val points = FloatArray(10)
                for (k in 0 until 5) {
                    val p = pts.optJSONArray(k) ?: continue
                    points[2 * k] = p.optDouble(0).toFloat()
                    points[2 * k + 1] = p.optDouble(1).toFloat()
                }
                sortie.add(
                    Visage(
                        FloatArray(4) { b.optDouble(it).toFloat() },
                        o.optDouble("score").toFloat(),
                        points,
                        o.optBoolean("regard", false),
                        o.optDouble("lacet", 0.0).toFloat(),
                        Empreintes.normaliser(FloatArray(emp.length()) { emp.optDouble(it).toFloat() }),
                    )
                )
            }
            return sortie
        }
    }
}

/**
 * Profils des visages, dans un fichier privé de l'appli (files/visages.json) : prénom et empreinte
 * moyenne seulement, jamais d'image. allowBackup est faux dans le manifeste : rien ne part en sauvegarde.
 */
object ProfilsVisages {
    private fun fichier(ctx: Context) = File(ctx.filesDir, "visages.json")

    @Synchronized
    fun lire(ctx: Context): List<Profil> = try {
        val f = fichier(ctx)
        if (!f.isFile) emptyList() else {
            val a = JSONObject(f.readText(Charsets.UTF_8)).optJSONArray("profils") ?: JSONArray()
            (0 until a.length()).mapNotNull { i ->
                val o = a.optJSONObject(i) ?: return@mapNotNull null
                val e = o.optJSONArray("empreinte") ?: return@mapNotNull null
                Profil(o.optString("id"), o.optString("nom"), FloatArray(e.length()) { e.optDouble(it).toFloat() })
            }
        }
    } catch (e: Exception) {
        Log.w("JarvisVisages", "Profils illisibles", e)
        emptyList()
    }

    @Synchronized
    private fun ecrire(ctx: Context, liste: List<Profil>) {
        val a = JSONArray()
        for (p in liste) {
            val e = JSONArray()
            for (x in p.empreinte) e.put(Math.round(x * 100000.0) / 100000.0)
            a.put(JSONObject().put("id", p.id).put("nom", p.nom).put("empreinte", e))
        }
        val f = fichier(ctx)
        val provisoire = File(f.parentFile, f.name + ".tmp")
        provisoire.writeText(JSONObject().put("version", 1).put("profils", a).toString(), Charsets.UTF_8)
        if (!provisoire.renameTo(f)) {
            f.delete()
            provisoire.renameTo(f)
        }
    }

    @Synchronized
    fun ajouter(ctx: Context, nom: String, empreinte: FloatArray) {
        ecrire(ctx, lire(ctx) + Profil(System.currentTimeMillis().toString(), nom, Empreintes.normaliser(empreinte)))
    }

    @Synchronized
    fun supprimer(ctx: Context, id: String) {
        ecrire(ctx, lire(ctx).filter { it.id != id })
    }
}
