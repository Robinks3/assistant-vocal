package assistant.vocal.jarvis

import org.json.JSONObject
import java.text.Normalizer
import java.util.concurrent.ConcurrentHashMap

/**
 * Routines reçues du serveur de l'assistant (0.40.0, lot S-R3 du plan, note conception/routines.md section 7.5).
 *
 * La tablette ne fait que reconnaître la phrase et la confier au serveur : les routines vivent et s'exécutent
 * côté serveur, avec la sécurité en dur et les contrôles existants. Ce qu'elle garde ici, c'est la liste reçue
 * (message `routines`), pour que « bonne nuit » soit reconnue sur place, PC éteint comme PC allumé. Le
 * serveur reste le juge : une routine que la personne ne peut pas lancer, une demande de gestion à la voix et
 * la confirmation d'un brouillon partent en texte au serveur, qui répond.
 *
 * Logique pure, sans Android, pour les tests (RoutinesLocalTest). L'heure est toujours passée par l'appelant.
 */
class RoutinesLocal(
    /** Forme comparée d'une phrase : la même que `forme()` de poc/routines.py (épurée puis normalisée). */
    private val forme: (String) -> String = { DictionnaireLocal.normaliser(DictionnaireLocal.epurer(it)) },
) {

    /** Une routine reçue. [formes] : les phrases et variantes sous leur forme comparée. */
    class Routine(
        val id: String,
        val nom: String,
        val auteur: String,
        /** "auteur" ou "tous". */
        val pour: String,
        val actif: Boolean,
        val phrases: List<String>,
        val formes: Set<String>,
    ) {
        /** Même règle que `peut_lancer` du serveur : « tous », ou l'auteur reconnu. */
        fun lancablePar(personne: String): Boolean {
            val p = cle(personne)
            return pour == "tous" || (p.isNotEmpty() && cle(auteur) == p)
        }
    }

    /** Ce que la tablette fait d'une phrase. */
    sealed class Decision {
        /** Phrase d'une routine active que la personne peut lancer : `routine_lancer`. */
        class Lancer(val routine: Routine) : Decision()

        /** Phrase de gestion, de création, ou d'une routine que la personne ne peut pas lancer : `routine_texte`. */
        class Serveur(val raison: String) : Decision()

        object Aucune : Decision()
    }

    private class Liste(val routines: List<Routine>, val version: Int) {
        @Volatile var perimee = false
    }

    /** Listes reçues, une par personne : le serveur ne renvoie que les routines visibles de celle qui parle. */
    private val listes = ConcurrentHashMap<String, Liste>()

    /**
     * Vrai dès que le serveur a annoncé la capacité `routines`. Reste vrai quand la connexion tombe, pour que
     * la tablette dise qu'elle ne peut pas lancer une routine au lieu de laisser le LLM agir à sa place.
     */
    @Volatile var serveurSait = false

    // Confirmation d'un brouillon : la phrase suivante, dans le délai, est « oui » ou « non ».
    @Volatile private var confirmationJusqua = 0L

    // ------------------------------------------------------------ liste reçue

    /** Retient la réponse `{"etat":"routines"}` du serveur pour [personne]. Renvoie le nombre de routines lues. */
    fun enregistrer(personne: String, reponse: JSONObject): Int {
        val tableau = reponse.optJSONArray("routines")
        val lues = ArrayList<Routine>()
        if (tableau != null) {
            for (i in 0 until tableau.length()) {
                val r = tableau.optJSONObject(i) ?: continue
                val id = r.optString("id")
                if (id.isEmpty()) continue
                val phrases = ArrayList<String>()
                for (cle in arrayOf("phrases", "variantes")) {
                    val a = r.optJSONArray(cle) ?: continue
                    for (k in 0 until a.length()) {
                        val p = a.optString(k).trim()
                        if (p.isNotEmpty()) phrases.add(p)
                    }
                }
                lues.add(
                    Routine(
                        id = id, nom = r.optString("nom"), auteur = if (r.isNull("auteur")) "" else r.optString("auteur"),
                        pour = r.optString("pour"), actif = r.optBoolean("actif", false), phrases = phrases,
                        formes = phrases.map { forme(it) }.filter { it.isNotEmpty() }.toSet(),
                    )
                )
            }
        }
        listes[cle(personne)] = Liste(lues, reponse.optInt("version", 0))
        return lues.size
    }

    /** Le serveur annonce que les routines ont changé (`routines_maj`) : les listes gardées ne sont plus sûres. */
    fun perimer() {
        for (l in listes.values) l.perimee = true
    }

    /** Une liste à jour est gardée pour cette personne. */
    fun aJour(personne: String): Boolean = listes[cle(personne)]?.perimee == false

    /** Personnes dont une liste est gardée (clés normalisées), pour les redemander après `routines_maj`. */
    fun personnes(): List<String> = listes.keys.toList()

    /** Aucune liste reçue du tout. */
    val vide: Boolean get() = listes.isEmpty()

    /** Version annoncée avec la liste de [personne], ou -1. */
    fun version(personne: String): Int = listes[cle(personne)]?.version ?: -1

    /**
     * Routines connues pour [personne] : sa liste, sinon celle reçue sans personne (les routines « tous »),
     * sinon rien. Les routines coupées sont comprises, [decider] les écarte.
     */
    fun routines(personne: String): List<Routine> =
        (listes[cle(personne)] ?: listes[""])?.routines ?: emptyList()

    // ------------------------------------------------------------ décision

    /**
     * Que faire de [texte] dit par [personne] (vide ou « inconnu » : non reconnue) :
     *  1. une demande de gestion ou de création de routine part au serveur (le LLM ordinaire agirait sur-le-champ) ;
     *  2. la phrase d'une routine active que la personne peut lancer la lance ;
     *  3. la phrase d'une routine active qu'elle ne peut pas lancer part au serveur, qui dit pourquoi.
     * Sans serveur connu pour gérer les routines, rien n'est fait de plus qu'avant la 0.40.0.
     */
    fun decider(texte: String, personne: String): Decision {
        if (!serveurSait && listes.isEmpty()) return Decision.Aucune
        val f = forme(texte)
        if (f.isEmpty()) return Decision.Aucune
        if (f.contains(MOT_ROUTINE)) return Decision.Serveur("gestion des routines")
        if (INTENTION_ROUTINE.containsMatchIn(texte)) return Decision.Serveur("création d'une routine")
        var reservee: Routine? = null
        for (r in routines(personne)) {
            if (!r.actif || f !in r.formes) continue
            if (r.lancablePar(personne)) return Decision.Lancer(r)
            if (reservee == null) reservee = r
        }
        if (reservee != null) return Decision.Serveur("routine ${reservee.nom} réservée")
        return Decision.Aucune
    }

    // ------------------------------------------------------------ confirmation d'un brouillon

    /** Le serveur attend « oui » ou « non » pendant [delaiS] secondes (0 : plus rien n'attend). */
    fun attendreConfirmation(delaiS: Int, maintenantMs: Long) {
        confirmationJusqua = if (delaiS > 0) maintenantMs + delaiS * 1000L else 0L
    }

    fun finirConfirmation() {
        confirmationJusqua = 0L
    }

    /** Une confirmation est en attente et son délai n'est pas écoulé : la phrase suivante part au serveur. */
    fun confirmationEnAttente(maintenantMs: Long): Boolean = confirmationJusqua > maintenantMs

    companion object {
        /** Réponse du serveur à une phrase qui n'est pas une demande de routine : la chaîne ordinaire continue. */
        const val PAS_UNE_ROUTINE = "Ce n'est pas une demande de routine."
        const val SANS_SERVEUR_LANCER = "Je ne peux pas lancer la routine sans le serveur."
        const val SANS_SERVEUR_GESTION = "Je ne peux pas gérer les routines sans le serveur."

        /** Secondes ajoutées au délai de confirmation du serveur : la proposition est lue à voix haute avant l'écoute. */
        const val MARGE_CONFIRMATION_S = 20

        private const val MOT_ROUTINE = "routine"

        /**
         * Phrase qui crée ou change une routine. Recopie de INTENTION_ROUTINE (poc/assistant.py), vérifiée sur les
         * mêmes cas (poc/tests/cas_routines.json). (?U) : \b et la casse comprennent les lettres accentuées.
         * Les formes à verbe (« crée-moi », « fais », « ajoute », « programme », « mets en place », « enregistre »,
         * « configure », « prépare », « peux-tu me ... », « je voudrais ... ») exigent le mot « routine » : « fais une
         * pause » ou « ajoute du lait à la liste » n'en font pas partie.
         */
        val INTENTION_ROUTINE = Regex(
            "(?iU)\\b(?:quand|lorsque|si|(?:à|a) chaque fois que|chaque fois que)\\s+je\\s+(?:te\\s+)?(?:dis|dirai|disais)\\b" +
                "|\\b(?:dorénavant|désormais|à partir de maintenant|a partir de maintenant)\\b" +
                "|\\b(?:cr[ée]e[rz]?|nouvelle|change[rz]?|modifie[rz]?|remplace[rz]?)\\s+(?:une\\s+|la\\s+|ma\\s+|cette\\s+)?" +
                "(?:nouvelle\\s+)?routine\\b" +
                // Verbe de création, avec ou sans « -moi » : crée-moi, fais-moi, fais, ajoute, programme, mets en place...
                "|\\b(?:cr[ée]e[rz]?|fais|fait|faire|ajoute[rz]?|programme[rz]?|mets?|mettre|enregistre[rz]?|configure[rz]?" +
                "|pr[ée]pare[rz]?)(?:[-\\s]+(?:moi|nous))?\\s+(?:en\\s+place\\s+)?(?:une\\s+|la\\s+|ma\\s+|cette\\s+|notre\\s+)?" +
                "(?:nouvelle\\s+)?routine\\b" +
                // Demande polie : peux-tu me créer / me faire / m'ajouter une routine.
                "|\\b(?:peux|peut|pouvez|pourrais|pourriez)[-\\s]+(?:tu|vous)\\s+(?:me\\s+|m['’]|nous\\s+)?(?:\\p{L}+\\s+){0,3}?" +
                "(?:une\\s+|la\\s+|ma\\s+|cette\\s+)?(?:nouvelle\\s+)?routine\\b" +
                // Souhait : je voudrais / je veux / j'aimerais (créer, faire, avoir) une routine.
                "|\\b(?:je\\s+(?:voudrais|veux|souhaite|souhaiterais)|j['’]aimerais|j['’]aurais\\s+envie)\\s+" +
                "(?:(?:de\\s+|d['’])?(?:cr[ée]er|faire|avoir|ajouter|programmer|configurer|pr[ée]parer|enregistrer)\\s+)?" +
                "(?:une\\s+|la\\s+|ma\\s+|cette\\s+)?(?:nouvelle\\s+)?routine\\b"
        )

        /** Clé d'une personne : sans accent, en minuscules. « inconnu » vaut « personne reconnue » (vide). */
        fun cle(personne: String): String {
            val p = Normalizer.normalize(personne.trim().lowercase(), Normalizer.Form.NFD)
                .replace(Regex("\\p{Mn}+"), "").trim()
            return if (p == DictionnaireLocal.INCONNU) "" else p
        }
    }
}
