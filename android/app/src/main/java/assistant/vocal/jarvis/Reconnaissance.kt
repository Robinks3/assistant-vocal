package assistant.vocal.jarvis

import kotlin.math.abs
import kotlin.math.max
import kotlin.math.sqrt

/**
 * Reconnaissance des visages de la tablette (0.16.0), logique pure sans Android pour être testée
 * sur la machine (ReconnaissanceTest).
 *
 * Idée reprise d'un projet d'inspiration (auteurs inspiration, perception/recognition.py et vision.py), réécrite ici
 * avec nos propres règles. Un visage seul ne suffit pas à nommer quelqu'un : une image floue ou de
 * biais ressemble vite à un proche. Il faut donc une ressemblance nette (seuil), un écart franc avec
 * le deuxième profil (marge), et que cela se répète dans le temps (votes). Une fois confirmée,
 * l'identité tient quelques secondes sans nouvelle preuve (tête tournée), mais tombe tout de suite
 * si le visage suivi ne ressemble plus du tout au profil.
 *
 * Les empreintes (128 nombres de SFace, normalisées) sont les seules données gardées : jamais
 * d'image. Elles ne vivent que sur la tablette, que l'analyse tourne sur la tablette ou sur le PC.
 */

/** Visage trouvé dans une image : boîte (x, y, l, h), score de YuNet, 5 points, empreinte normalisée. */
class Visage(
    val boite: FloatArray,
    val score: Float,
    /** Œil droit, œil gauche, nez, coin droit puis coin gauche de la bouche : x0, y0, x1, y1... */
    val points: FloatArray,
    val regard: Boolean,
    val lacet: Float,
    val empreinte: FloatArray,
)

/** Profil enregistré : moyenne normalisée des empreintes de l'enrôlement. */
class Profil(val id: String, val nom: String, val empreinte: FloatArray)

/**
 * Personne vue dans l'image courante, nom connu seulement une fois l'identité confirmée.
 * [inconnu] : vue assez longtemps, nettement, sans ressembler à aucun profil enregistré (0.16.4,
 * « ma chambre » refusée). Faux tant qu'on n'en est pas sûr : la commande vise alors la chambre par défaut.
 * [sur] (0.21.1) : l'identité a été soutenue par une image de moins d'1 s ([Identite.SUR_MS]), pas seulement
 * gardée de mémoire (jusqu'à 8 s, tête tournée). La santé du propriétaire ne s'affiche que sur une identité sûre.
 */
data class PersonneVue(
    val piste: Int,
    val profil: String?,
    val nom: String?,
    val regard: Boolean,
    val inconnu: Boolean = false,
    val sur: Boolean = false,
)

object Geometrie {
    /** Lacet et hauteur du nez, rapportés à l'écart des yeux. */
    class Pose(val lacet: Float, val hauteur: Float)

    fun pose(points: FloatArray): Pose {
        val xd = points[0]
        val yd = points[1]
        val xg = points[2]
        val yg = points[3]
        val xn = points[4]
        val yn = points[5]
        val ecart = max(abs(xg - xd), 1e-6f)
        return Pose((xn - (xd + xg) / 2f) / ecart, (yn - (yd + yg) / 2f) / ecart)
    }

    /**
     * Vrai si la personne regarde l'appareil : même calcul que regard() de poc/vision.py, pour que
     * les moteurs de la tablette et du PC donnent la même réponse. Le nez reste entre les yeux
     * (lacet faible) et sous leur ligne (hauteur de face).
     */
    fun regard(points: FloatArray): Boolean {
        val p = pose(points)
        return abs(p.lacet) < 0.22f && p.hauteur > 0.25f && p.hauteur < 1.2f
    }
}

object Empreintes {
    fun cosinus(a: FloatArray, b: FloatArray): Float {
        var s = 0f
        for (i in 0 until minOf(a.size, b.size)) s += a[i] * b[i]
        return s
    }

    fun normaliser(v: FloatArray): FloatArray {
        var n = 0.0
        for (x in v) n += x.toDouble() * x
        val k = (1.0 / max(sqrt(n), 1e-9)).toFloat()
        return FloatArray(v.size) { v[it] * k }
    }

    /** Moyenne de plusieurs vues, renormalisée : l'empreinte du profil. */
    fun moyenne(vues: List<FloatArray>): FloatArray {
        require(vues.isNotEmpty()) { "aucune vue" }
        val somme = FloatArray(vues[0].size)
        for (v in vues) {
            val n = normaliser(v)
            for (i in somme.indices) somme[i] += n[i]
        }
        return normaliser(somme)
    }
}

/**
 * Confirmation d'une identité dans le temps, pour une piste (un visage suivi d'image en image).
 * Les instants sont en millisecondes, fournis par l'appelant (testable sans horloge).
 */
class Identite {
    companion object {
        /** Ressemblance cosinus minimale avec le profil (ce n'est pas une probabilité). */
        const val SEUIL = 0.42f
        /** Écart minimal entre le meilleur profil et le deuxième. */
        const val MARGE = 0.05f
        /** Une identité déjà confirmée tolère une image un peu moins nette. */
        const val TOLERANCE = 0.08f
        /** Sous ce score, le visage suivi n'est plus du tout cette personne : oubli immédiat. */
        const val CONTRADICTION = 0.20f
        /** Au moins VOTES images concordantes sur FENETRE_MS, sans vote confiant contraire. */
        const val VOTES = 4
        const val FENETRE_MS = 1200L
        /** Durée de vie d'une identité confirmée sans nouvelle preuve. */
        const val GARDE_MS = 8000L
        /** Identité sûre (0.21.1) : soutenue par une image de moins d'une seconde. */
        const val SUR_MS = 1000L
    }

    var profil: String? = null
        private set
    private var soutenuLe = 0L
    /** Votes récents : instant et profil voté (null pour une image sans avis net). */
    private val votes = ArrayDeque<Pair<Long, String?>>()

    fun oublier() {
        profil = null
        votes.clear()
    }

    /**
     * Nouvelle image de cette piste. [scores] : ressemblance à chaque profil. [utilisable] : faux
     * pour un visage trop petit ou trop de biais, qui n'apporte ni preuve ni contradiction.
     * Rend le profil confirmé, ou null.
     */
    fun image(scores: Map<String, Float>, t: Long, utilisable: Boolean = true): String? {
        val classes = scores.entries.sortedByDescending { it.value }
        val meilleur = classes.getOrNull(0)
        val marge = if (classes.size > 1) classes[0].value - classes[1].value else 1f
        val net = meilleur != null && meilleur.value >= SEUIL && marge >= MARGE
        val courant = profil
        if (courant != null) {
            if (utilisable) {
                val sien = scores[courant] ?: -1f
                if (sien < CONTRADICTION || (net && meilleur!!.key != courant)) {
                    // Quelqu'un d'autre reconnu nettement, ou plus aucune ressemblance.
                    oublier()
                } else if (meilleur?.key == courant && meilleur.value >= SEUIL - TOLERANCE && marge >= MARGE) {
                    soutenuLe = t
                }
            }
            if (profil != null) {
                if (t - soutenuLe <= GARDE_MS) return profil
                oublier()
            }
        }
        if (!utilisable) return null
        votes.addLast(t to if (net) meilleur!!.key else null)
        while (votes.isNotEmpty() && t - votes.first().first > FENETRE_MS) votes.removeFirst()
        if (net) {
            val avis = votes.mapNotNull { it.second }
            val pour = avis.count { it == meilleur!!.key }
            if (pour >= VOTES && pour == avis.size) {
                profil = meilleur!!.key
                soutenuLe = t
                votes.clear()
            }
        }
        return profil
    }

    /** Identité confirmée et soutenue par une image de moins de [SUR_MS] à l'instant [t]. */
    fun sur(t: Long): Boolean = profil != null && t - soutenuLe < SUR_MS

    /** Pas de visage pour cette piste dans l'image : l'identité vieillit seulement. */
    fun absente(t: Long): String? {
        val p = profil ?: return null
        if (t - soutenuLe > GARDE_MS) oublier()
        return profil
    }
}

/**
 * Suivi des visages d'image en image et reconnaissance de chacun. Une piste par personne, rattachée
 * par la ressemblance de l'empreinte, ou par la position quand la ressemblance reste correcte.
 */
class Reconnaissance(profils: List<Profil> = emptyList()) {

    private class Piste(val numero: Int, var empreinte: FloatArray, var cx: Float, var cy: Float, var vueLe: Long) {
        val identite = Identite()
        val neeLe = vueLe
        /** Images nettes (assez grandes, de face) vues pour cette piste. */
        var nettes = 0
    }

    @Volatile var profils: List<Profil> = profils
        private set
    private val pistes = ArrayList<Piste>()
    private var suivant = 1

    companion object {
        /** Une piste non revue disparaît après ce délai (le temps qu'une identité reste gardée). */
        const val OUBLI_PISTE_MS = Identite.GARDE_MS
        /** Visage trop petit (pixels de l'image analysée, environ 320 x 240) ou trop de biais. */
        const val COTE_MIN = 36f
        const val LACET_MAX = 0.35f
        /** Inconnu : suivi depuis au moins INCONNU_MS, avec INCONNU_IMAGES images nettes, sans identité. */
        const val INCONNU_MS = 2500L
        const val INCONNU_IMAGES = 6
    }

    @Synchronized
    fun changerProfils(liste: List<Profil>) {
        profils = liste
        pistes.clear()
    }

    /** Image analysée à l'instant [t] : les personnes vues, avec leur nom si l'identité est confirmée. */
    @Synchronized
    fun image(visages: List<Visage>, t: Long): List<PersonneVue> {
        pistes.removeAll { t - it.vueLe > OUBLI_PISTE_MS }
        val libres = ArrayList(pistes)
        val sortie = ArrayList<PersonneVue>()
        for (v in visages.take(8)) {
            val cx = v.boite[0] + v.boite[2] / 2f
            val cy = v.boite[1] + v.boite[3] / 2f
            var choisie: Piste? = null
            var mieux = -1f
            for (p in libres) {
                val s = Empreintes.cosinus(v.empreinte, p.empreinte)
                val proche = hypot(p.cx - cx, p.cy - cy) < v.boite[2] * 1.2f
                if ((s >= 0.35f || (proche && s >= 0.25f)) && s > mieux) {
                    mieux = s
                    choisie = p
                }
            }
            val piste = choisie?.also { libres.remove(it) }
                ?: Piste(suivant++, v.empreinte, cx, cy, t).also { pistes.add(it) }
            val scores = HashMap<String, Float>()
            for (pr in profils) scores[pr.id] = Empreintes.cosinus(v.empreinte, pr.empreinte)
            val utilisable = minOf(v.boite[2], v.boite[3]) >= COTE_MIN && abs(v.lacet) <= LACET_MAX
            val id = piste.identite.image(scores, t, utilisable)
            if (utilisable) piste.nettes++
            // Empreinte de piste lissée : elle suit les petits changements d'angle.
            piste.empreinte = Empreintes.normaliser(FloatArray(v.empreinte.size) { piste.empreinte[it] * 0.8f + v.empreinte[it] * 0.2f })
            piste.cx = cx
            piste.cy = cy
            piste.vueLe = t
            val inconnu = id == null && profils.isNotEmpty() && piste.nettes >= INCONNU_IMAGES && t - piste.neeLe >= INCONNU_MS
            sortie.add(PersonneVue(piste.numero, id, profils.firstOrNull { it.id == id }?.nom, v.regard, inconnu, id != null && piste.identite.sur(t)))
        }
        for (p in libres) p.identite.absente(t)
        return sortie
    }

    private fun hypot(a: Float, b: Float): Float = sqrt(a * a + b * b)
}

/** Présence : quelqu'un vu sur 2 images de suite, absent après 3 s sans aucun visage. */
class Presence {
    companion object {
        const val IMAGES_POUR_PRESENCE = 2
        const val ABSENCE_MS = 3000L
    }

    var present = false
        private set
    private var suite = 0
    private var derniereVueLe = 0L

    /** Rend vrai quand l'état a changé. */
    fun image(nombre: Int, t: Long): Boolean {
        val avant = present
        if (nombre > 0) {
            suite++
            derniereVueLe = t
            if (suite >= IMAGES_POUR_PRESENCE) present = true
        } else {
            suite = 0
            if (present && t - derniereVueLe >= ABSENCE_MS) present = false
        }
        return avant != present
    }
}

/**
 * « Parler en regardant » : une personne seule qui regarde la tablette 1,5 s de suite déclenche
 * l'écoute une fois. Il faut détourner le regard (ou qu'elle parte) pour réarmer.
 */
class RegardSoutenu(private val dureeMs: Long = 1500L) {
    private var debut = -1L
    private var declenche = false

    fun image(seul: Boolean, regarde: Boolean, t: Long): Boolean {
        if (!seul || !regarde) {
            debut = -1L
            declenche = false
            return false
        }
        if (declenche) return false
        if (debut < 0) debut = t
        if (t - debut >= dureeMs) {
            declenche = true
            return true
        }
        return false
    }
}
