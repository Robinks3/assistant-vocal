package assistant.vocal.jarvis

import org.json.JSONObject

/**
 * Santé du propriétaire sur l'accueil de la tablette (0.19.0, maquette `AccueilCouleurs` du canevas) : « Tu as dormi
 * 7 h 12. » et « 4 210 pas aujourd'hui. », sous les phrases du repos.
 *
 * 0.21.1 (revue de code) : le propriétaire doit être reconnu sur une image de moins d'1 s, avec une identité soutenue
 * par cette image ([Garde]), et non d'après une liste de personnes figée par une analyse en panne ou une
 * identité gardée de mémoire 8 s. Une seule image vide est tolérée 500 ms, jamais une image où quelqu'un
 * d'autre apparaît. Le résumé est jeté au changement de jour.
 *
 * Données personnelles, d'où des règles strictes :
 * - visibles seulement quand la vision reconnaît le propriétaire et qu'il est la seule personne vue ([proprietaireSeul]),
 *   cachées sur-le-champ dès qu'une autre personne ou un inconnu apparaît, jamais en AOD ni sur fond noir,
 *   jamais pour un autre prénom.
 * - demandées au serveur du PC (message `{"type": "sante", "id": n}`, serveur 0.19.0, capacité `sante`) par
 *   la connexion de la transcription déportée, à la reconnaissance du propriétaire.
 * - gardées en mémoire seulement ([Memoire]) : 10 min au plus, effacées après 10 min d'absence, jamais sur
 *   disque, jamais dans Etat ni dans le journal. Seuls les nombres de [Resume] sont gardés, le reste de la
 *   réponse est oublié dès la lecture.
 *
 * 0.26.0, santé en un coup d'œil (piste « mélange » du canevas, version 27) : le résumé garde aussi les 7 nuits et
 * le cœur au repos des 7 jours, indexés par date à partir d'aujourd'hui (heure de Paris), et l'heure de la
 * lecture. Une réponse qui porte encore la journée d'hier (après minuit) ne donne jamais ses pas ni sa nuit pour
 * ceux du jour : l'anneau passe à « 0 » et l'heure de la lecture, la nuit à « pas reçue ». Le bloc n'apparaît
 * qu'en vivant plein ([montreAccueil]) : jamais en retrait, en AOD ni écran éteint.
 *
 * Lecture défensive de la réponse ([lire]) : tout champ peut manquer ou être nul, la ligne correspondante ne
 * s'affiche pas. La nuit du matin peut ne pas être encore arrivée (`nuit.minutes` nul) : la ligne du sommeil
 * ne montre jamais la nuit d'avant comme si c'était celle-ci.
 */
internal object Sante {

    /** Le jour à l'heure de Paris (celle du serveur de santé), pour la lecture comme pour la mémoire (0.26.0). */
    fun aujourdhui(): java.time.LocalDate = java.time.LocalDate.now(java.time.ZoneId.of("Europe/Paris"))

    /** Seul prénom pour lequel les lignes s'affichent : le propriétaire (proprietaire.nom de maison.json). */
    val PRENOM: String = ConfigMaison.NOM_PROPRIETAIRE

    /**
     * Ce que l'accueil garde : minutes de la nuit de ce matin et pas du jour, chacun nul s'il est inconnu, puis
     * (0.26.0) les 7 nuits et le cœur au repos des 7 jours, de la plus ancienne à aujourd'hui (nul pour un jour
     * sans mesure, listes vides sans historique), et l'heure de la lecture du serveur (« 7 h 10 »).
     */
    data class Resume(
        val sommeilMinutes: Int?,
        val pas: Int?,
        val nuits: List<Int?> = emptyList(),
        val coeur: List<Int?> = emptyList(),
        val luA: String? = null,
    ) {
        val vide: Boolean get() = sommeilMinutes == null && pas == null && nuits.all { it == null } && coeur.all { it == null }
    }

    /** Le propriétaire, reconnu sur cette image même (identité sûre), est la seule personne de l'image. */
    fun proprietaireSeulSur(personnes: List<PersonneVue>): Boolean {
        val p = personnes.singleOrNull() ?: return false
        return !p.inconnu && p.sur && p.nom != null && p.nom.trim().equals(PRENOM, ignoreCase = true)
    }

    /**
     * Garde de la santé (instants SystemClock.elapsedRealtime, fournis par l'appelant) : vrai seulement si la
     * dernière image date de moins de [FRAICHEUR_MS] et montre le propriétaire seul et sûr, ou si elle est vide moins
     * de [TOLERANCE_VIDE_MS] après une telle image. Une image avec quelqu'un d'autre annule la tolérance.
     */
    class Garde {
        private var okImage = -1L

        fun voir(personnes: List<PersonneVue>, personnesLe: Long, maintenant: Long): Boolean {
            if (personnesLe <= 0L || maintenant - personnesLe > FRAICHEUR_MS) return false
            if (proprietaireSeulSur(personnes)) {
                okImage = personnesLe
                return true
            }
            if (personnes.isNotEmpty()) {
                okImage = -1L
                return false
            }
            return okImage >= 0L && personnesLe - okImage <= TOLERANCE_VIDE_MS
        }
    }

    /** Âge maximal de l'image qui montre le propriétaire. */
    const val FRAICHEUR_MS = 1_000L
    /** Une image vide (5 images par seconde) ne cache pas tout de suite. */
    const val TOLERANCE_VIDE_MS = 500L

    /** Garde partagée par l'accueil et le panneau Santé (fil principal). */
    val garde = Garde()

    /** Le propriétaire seul et sûr devant la tablette d'après l'état [e], à l'instant [maintenant]. */
    fun proprietaireSeul(e: Etat.Instantane, maintenant: Long): Boolean = garde.voir(e.personnes, e.personnesLe, maintenant)

    fun entier(o: JSONObject?, cle: String): Int? {
        if (o == null || !o.has(cle) || o.isNull(cle)) return null
        val v = o.opt(cle)
        val d = when (v) {
            is Number -> v.toDouble()
            is String -> v.trim().replace(',', '.').toDoubleOrNull()
            else -> null
        } ?: return null
        if (d.isNaN() || d.isInfinite()) return null
        return Math.round(d).toInt()
    }

    fun texte(o: JSONObject?, cle: String): String? =
        if (o == null || !o.has(cle) || o.isNull(cle)) null else o.optString(cle).trim().ifEmpty { null }

    /**
     * Résumé lu dans la réponse du serveur (`{"etat": "sante", "id", "donnees": {...}}`, ou directement
     * l'objet `donnees`). Rend null pour une erreur, une réponse illisible ou sans rien d'utile.
     */
    fun lire(reponse: JSONObject?, aujourdhui: java.time.LocalDate? = null): Resume? {
        if (reponse == null || reponse.has("erreur")) return null
        val d = if (reponse.has("donnees")) reponse.optJSONObject("donnees") ?: return null else reponse
        val jour = texte(d, "date")
        // 0.26.0 : une réponse d'hier (lue avant minuit, servie après) ne donne ni les pas ni la nuit du jour.
        val dHier = aujourdhui != null && jour != null && jour != aujourdhui.toString()
        // Nuit du matin : seulement si ses minutes sont connues et qu'elle finit bien aujourd'hui.
        val nuit = d.optJSONObject("nuit")
        val dateNuit = texte(nuit, "date")
        // `cette_nuit` faux ou absent : la nuit lue n'est pas celle de ce matin, pas de ligne sur l'accueil.
        val cetteNuit = nuit != null && nuit.has("cette_nuit") && !nuit.isNull("cette_nuit") && nuit.optBoolean("cette_nuit", false)
        val sommeil = entier(nuit, "minutes")
            ?.takeIf { it in 1..(24 * 60) }
            ?.takeIf { cetteNuit }
            ?.takeIf { jour == null || dateNuit == null || dateNuit == jour }
            ?.takeIf { !dHier && (aujourdhui == null || (dateNuit ?: jour) == aujourdhui.toString()) }
        val auj = d.optJSONObject("aujourdhui")
        val dateAuj = texte(auj, "date")
        val pas = entier(auj, "pas")
            ?.takeIf { it in 0..500_000 }
            ?.takeIf { jour == null || dateAuj == null || dateAuj == jour }
            ?.takeIf { !dHier && (aujourdhui == null || (dateAuj ?: jour) == aujourdhui.toString()) }
        // 7 jours par date, d'aujourd'hui (local, sinon la date du serveur) en arrière : un jour absent reste nul.
        val fin = aujourdhui ?: jour?.let { runCatching { java.time.LocalDate.parse(it) }.getOrNull() }
        val jours = d.optJSONArray("jours")
        var nuits: List<Int?> = emptyList()
        var coeur: List<Int?> = emptyList()
        if (fin != null && jours != null) {
            val parDate = HashMap<String, JSONObject>()
            for (i in 0 until jours.length()) jours.optJSONObject(i)?.let { o -> texte(o, "date")?.let { parDate[it] = o } }
            val dates = (6 downTo 0).map { fin.minusDays(it.toLong()).toString() }
            nuits = dates.map { dt -> entier(parDate[dt], "sommeil_minutes")?.takeIf { it in 1..(24 * 60) } }
            coeur = dates.map { dt -> entier(parDate[dt], "fc_repos")?.takeIf { it in 25..150 } }
            // La nuit de ce matin n'est montrée que si elle a passé les règles de [sommeil] ci-dessus.
            nuits = nuits.dropLast(1) + sommeil
        }
        // Heure de la lecture du serveur, seulement pour une réponse du jour (jamais « lu à 23 h 58 » après minuit).
        val luA = if (dHier) null else texte(d, "lu_a")?.let { Regex("T(\\d{2}):(\\d{2})").find(it) }?.let { m -> "${m.groupValues[1].toInt()} h ${m.groupValues[2]}" }
        return Resume(sommeil, pas, nuits, coeur, luA).takeIf { !it.vide }
    }

    /**
     * Le bloc santé de l'accueil est-il montré (0.26.0) ? Seulement le propriétaire reconnu seul ([proprietaireSeul], Garde), en
     * vivant plein ([vivant] et [actif] : jamais en retrait, en AOD ni écran éteint), au repos, et avec un résumé.
     * Faux dès qu'un autre visage arrive ou que l'identité devient périmée : le bloc quitte l'écran sur-le-champ.
     */
    fun montreAccueil(proprietaireSeul: Boolean, vivant: Boolean, actif: Boolean, repos: Boolean, r: Resume?): Boolean =
        proprietaireSeul && vivant && actif && repos && r != null && !r.vide

    /** « 7 h 12 », « 7 h 05 », « 8 h », « 45 min ». */
    fun duree(minutes: Int): String {
        val h = minutes / 60
        val m = minutes % 60
        return when {
            h == 0 -> "$m min"
            m == 0 -> "$h h"
            else -> "$h h " + m.toString().padStart(2, '0')
        }
    }

    /** « 4 210 », « 12 345 », « 980 » : milliers séparés par une espace simple. */
    fun milliers(n: Int): String {
        val s = n.toString()
        val b = StringBuilder()
        for ((i, ch) in s.withIndex()) {
            if (i > 0 && (s.length - i) % 3 == 0) b.append(' ')
            b.append(ch)
        }
        return b.toString()
    }

    /** « Tu as dormi 7 h 12. », la valeur à colorer. */
    fun phraseSommeil(minutes: Int?): Accueil.Phrase? {
        if (minutes == null) return null
        val v = duree(minutes)
        val t = "Tu as dormi $v."
        val i = t.indexOf(v)
        return Accueil.Phrase(t, i until i + v.length)
    }

    /** « 4 210 pas aujourd'hui. », la valeur à colorer (revue design, 0.21.1). */
    fun phrasePas(pas: Int?): Accueil.Phrase? {
        if (pas == null) return null
        val v = milliers(pas) + " pas"
        val t = "$v aujourd'hui."
        return Accueil.Phrase(t, 0 until v.length)
    }

    /**
     * Mémoire du résumé, sans horloge propre (instants en millisecondes de SystemClock.elapsedRealtime) :
     * demandé quand le propriétaire seul apparaît, redemandé un peu avant ses [dureeMs], effacé à [dureeMs] et après
     * [absenceMs] sans le propriétaire seul. Une demande sans réponse n'est pas relancée avant [relanceMs].
     */
    class Memoire(
        private val dureeMs: Long = 10 * 60_000L,
        private val absenceMs: Long = 10 * 60_000L,
        private val relanceMs: Long = 60_000L,
    ) {
        var resume: Resume? = null
            private set
        private var luLe = 0L
        /** Jour (epochDay) du résumé gardé : jeté au changement de jour. */
        private var jourLu = Long.MIN_VALUE
        private var vuLe = 0L
        private var demandeLe = 0L
        private var enCours = false

        /** Pas de l'accueil : [proprietaireSeul] maintenant. Rend vrai s'il faut demander le résumé au serveur. */
        fun avancer(proprietaireSeul: Boolean, maintenant: Long, jour: Long = jourLu): Boolean {
            if (resume != null && jour != jourLu) oublier()
            if (proprietaireSeul) vuLe = maintenant
            if (resume != null && (maintenant - luLe >= dureeMs || (!proprietaireSeul && maintenant - vuLe >= absenceMs))) oublier()
            if (!proprietaireSeul || enCours) return false
            val aRelire = resume == null || maintenant - luLe >= dureeMs - RAFRAICHIR_AVANT_MS
            if (!aRelire) return false
            if (demandeLe != 0L && maintenant - demandeLe < relanceMs) return false
            demandeLe = maintenant
            enCours = true
            return true
        }

        /** Réponse du serveur (null : rien d'utile, l'ancien résumé reste jusqu'à sa fin). */
        fun recu(r: Resume?, maintenant: Long, jour: Long = jourLu) {
            enCours = false
            if (r == null) return
            resume = r
            luLe = maintenant
            jourLu = jour
        }

        fun oublier() {
            resume = null
            luLe = 0L
        }

        /** Ce que l'accueil montre : le résumé si le propriétaire est seul, rien sinon. */
        fun montre(proprietaireSeul: Boolean): Resume? = if (proprietaireSeul) resume else null

        companion object {
            /** Le résumé est redemandé une minute avant sa fin, pour ne pas laisser de trou à l'écran. */
            const val RAFRAICHIR_AVANT_MS = 60_000L
        }
    }
}
