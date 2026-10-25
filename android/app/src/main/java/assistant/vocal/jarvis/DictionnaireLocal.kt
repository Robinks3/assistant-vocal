package assistant.vocal.jarvis

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject
import java.text.Normalizer

/**
 * Dictionnaire de Jarvis embarqué (assets/dictionnaire.json, produit par
 * android/outils/exporter_dictionnaire.py depuis commandes.yaml du dossier de configuration), complété par les phrases
 * apprises de assets/dictionnaire_appris.json quand l'APK en porte (0.32.2, export à part du dossier de données).
 * Une phrase apprise ne remplace jamais une phrase de commandes.yaml.
 * Reprise de poc/dictionnaire.py : epurer, normaliser, recherche exacte puis tolérance aux
 * fautes (difflib.get_close_matches, n=5, seuil 0,88, mots_compatibles, jamais pour une
 * phrase apprise).
 */
class DictionnaireLocal(j: JSONObject, appris: JSONObject? = null) {

    constructor(contexte: Context) : this(
        JSONObject(contexte.assets.open("dictionnaire.json").bufferedReader(Charsets.UTF_8).use { it.readText() }),
        kotlin.runCatching {
            JSONObject(contexte.assets.open("dictionnaire_appris.json").bufferedReader(Charsets.UTF_8).use { it.readText() })
        }.getOrNull(),
    )

    /** Une phrase du dictionnaire : sa clé, le modèle (motif, actions à trous) et les valeurs des emplacements. */
    class Forme(
        val cle: String,
        private val modele: JSONObject,
        /** Emplacements remplis par cette forme, ex. hdmi=HDMI3. */
        val valeurs: Map<String, String>,
    ) {
        val reponse: String get() = modele.optString("reponse", "C'est fait.")
        val source: String get() = modele.optString("source")
        val ligne: Int get() = modele.optInt("ligne")
        val motif: String get() = modele.optString("motif")
        val appris: Boolean get() = modele.optBoolean("appris", false)

        /** Actions du modèle, emplacements remplacés comme str.format côté serveur. */
        val actions: JSONArray
            get() {
                var texte = modele.getJSONArray("actions").toString()
                for ((k, v) in valeurs) texte = texte.replace("{$k}", v)
                return JSONArray(texte)
            }
    }

    /** Résultat d'une recherche : la forme trouvée, et si elle l'a été à une faute près. */
    class Trouve(val forme: Forme, val approchee: Boolean, val ressemblance: Double)

    val version: String
    val genereLe: String
    private val formes = LinkedHashMap<String, Forme>()
    /** « Ma chambre » selon la personne qui parle (section personnes de commandes.yaml, 21/10/2026). */
    val personnes = Personnes(j.optJSONObject("personnes"))

    init {
        version = j.optString("version")
        genereLe = j.optString("genere_le")
        lire(j, remplacer = true)
        appris?.let { lire(it, remplacer = false) }
    }

    private fun lire(j: JSONObject, remplacer: Boolean) {
        val modeles = j.getJSONArray("modeles")
        val a = j.getJSONArray("formes")
        for (i in 0 until a.length()) {
            val o = a.getJSONArray(i)
            val v = o.optJSONObject(2)
            val f = Forme(
                o.getString(0), modeles.getJSONObject(o.getInt(1)),
                v?.let { x -> x.keys().asSequence().associateWith { x.optString(it) } } ?: emptyMap(),
            )
            if (remplacer) formes[f.cle] = f else formes.putIfAbsent(f.cle, f)
        }
    }

    val taille: Int get() = formes.size

    /** Une phrase proche examinée par la recherche approchée, et pourquoi elle est gardée ou non. */
    class Candidat(val forme: Forme, val ressemblance: Double, val verdict: String, val retenu: Boolean)

    /** Chemin complet d'une recherche, affiché dans le déroulé. */
    class Chemin(
        val entendu: String,
        val regles: List<String>,
        val epure: String,
        val cle: String,
        val exacte: Boolean,
        val candidats: List<Candidat>,
        val trouve: Trouve?,
    )

    fun chercher(phrase: String): Trouve? = parcourir(phrase).trouve

    /** Même recherche que chercher(), en gardant chaque embranchement. */
    fun parcourir(entendu: String): Chemin {
        val regles = ArrayList<String>()
        val epure = epurer(entendu, regles)
        val cle = normaliser(epure)
        formes[cle]?.let { return Chemin(entendu, regles, epure, cle, true, emptyList(), Trouve(it, false, 1.0)) }
        // Comme difflib.get_close_matches : les 5 meilleures au-dessus de 0,88, puis le filtre.
        // Comme real_quick_ratio de difflib : une phrase de longueur trop différente ne peut pas
        // ressembler, inutile de la comparer (17 000 formes depuis la luminosité).
        val meilleures = formes.values.asSequence()
            .filter { 2.0 * minOf(it.cle.length, cle.length) / (it.cle.length + cle.length) >= 0.7 }
            .map { it to ratio(it.cle, cle) }
            .sortedByDescending { it.second }
            .take(5)
            .toList()
        val candidats = ArrayList<Candidat>()
        var trouve: Trouve? = null
        for ((f, r) in meilleures) {
            val raison = when {
                r < SEUIL_FLOU -> "sous le seuil de 0,88"
                f.appris -> "phrase apprise, reconnue mot pour mot seulement"
                else -> motDiscordant(cle, f.cle)?.let { "le mot « $it » n'a pas d'équivalent proche" }
            }
            val retenu = raison == null && trouve == null
            if (retenu) trouve = Trouve(f, true, r)
            candidats.add(Candidat(f, r, raison ?: if (retenu) "retenue" else "valable, mais une meilleure passe avant", retenu))
        }
        return Chemin(entendu, regles, epure, cle, false, candidats, trouve)
    }

    /**
     * « Ma chambre » selon la personne qui parle, comme la classe Personnes de poc/dictionnaire.py
     * (cas communs dans poc/tests/cas_personnes.json, DictionnaireTest). Une commande dont toutes les
     * cibles sont dans la chambre du propriétaire et dont la phrase ne le nomme pas vise les lumières de
     * celui-ci quand il parle ou qu'on ne sait pas qui parle, celles de la personne reconnue si elle a une
     * chambre déclarée, et rien pour une personne inconnue (refus expliqué).
     */
    class Personnes(section: JSONObject?) {
        /** Actions à faire, refus expliqué (actions vides), et réponse qui remplace celle du dictionnaire. */
        class Resultat(val actions: List<JSONObject>, val refus: String?, val reponse: String?)

        val defaut: String = normaliser(section?.optString("defaut")?.ifEmpty { null } ?: ConfigMaison.CLE_PROPRIETAIRE)
        private val inconnu = section?.optString("inconnu")?.ifEmpty { null } ?: "Je ne sais pas de quelle chambre tu parles."
        private val sansChambre = section?.optString("sans_chambre")?.ifEmpty { null } ?: inconnu
        /** Par personne : entité de la chambre par défaut vers son entité (texte) ou son action (objet). */
        val remplacer: Map<String, Map<String, Any>> = buildMap {
            if (section != null) for (nom in section.keys()) {
                val table = section.optJSONObject(nom)?.optJSONObject("remplacer") ?: continue
                put(normaliser(nom), table.keys().asSequence().associateWith { table.get(it) })
            }
        }
        val chambre: Set<String> = remplacer.values.flatMap { it.keys }.toSet()

        fun personnelle(actions: List<JSONObject>, cle: String): Boolean {
            if (chambre.isEmpty() || actions.isEmpty() || defaut in cle.split(" ")) return false
            return actions.all { a -> cibles(a).let { it.isNotEmpty() && chambre.containsAll(it) } }
        }

        fun appliquer(actions: List<JSONObject>, cle: String, personne: String): Resultat {
            if (!personnelle(actions, cle)) return Resultat(actions, null, null)
            val p = normaliser(personne)
            if (p.isEmpty() || p == defaut) return Resultat(actions, null, null)
            if (p == INCONNU) return Resultat(emptyList(), inconnu, null)
            val table = remplacer[p] ?: return Resultat(emptyList(), sansChambre, null)
            val sortie = ArrayList<JSONObject>()
            var reponse: String? = null
            for (a in actions) {
                val entites = cibles(a)
                val unique = entites.singleOrNull()?.let { table[it] }
                if (unique is JSONObject) {
                    val nouvelle = JSONObject(unique.toString())
                    if (nouvelle.has("reponse")) reponse = nouvelle.remove("reponse") as String
                    sortie.add(nouvelle)
                    continue
                }
                if (entites.any { table[it] !is String }) return Resultat(emptyList(), sansChambre, null)
                val nouvelles = entites.map { table.getValue(it) as String }.distinct()
                val copie = JSONObject(a.toString())
                copie.put("entity_id", if (a.opt("entity_id") is JSONArray) JSONArray(nouvelles) else nouvelles.joinToString(","))
                sortie.add(copie)
            }
            return Resultat(sortie, null, reponse)
        }

        private fun cibles(a: JSONObject): List<String> = when (val v = a.opt("entity_id")) {
            null -> emptyList()
            is JSONArray -> (0 until v.length()).map { v.optString(it) }
            else -> v.toString().split(",").map { it.trim() }.filter { it.isNotEmpty() }
        }
    }

    companion object {
        const val SEUIL_FLOU = 0.88
        /** Valeur de « personne » quand la tablette voit une seule personne sans la reconnaître. */
        const val INCONNU = "inconnu"

        fun normaliser(texte: String): String {
            val sansAccents = Normalizer.normalize(texte.lowercase(), Normalizer.Form.NFD)
                .replace(Regex("\\p{Mn}+"), "")
            return sansAccents.replace(Regex("[^a-z0-9{}]+"), " ").trim().split(Regex("\\s+")).joinToString(" ")
        }

        private val DEBUT = Regex(
            "^\\s*(?:(?:est|et)[- ]ce (?:que|qu')\\s*)?(?:tu peux|tu pourrais|peux[- ]tu|" +
                "pourrais[- ]tu|vous pouvez|pouvez[- ]vous|pourriez[- ]vous|" +
                "j'aimerais que tu|je veux que tu|merci de|merci|ok|okay|bon|alors|dis)[\\s,]+",
            RegexOption.IGNORE_CASE,
        )
        private val FIN = Regex(
            "[\\s,]*(?:s'il te pla[iî]t|s'il vous pla[iî]t|stp|svp|merci|maintenant|tout de suite|vite)[\\s.!?]*$",
            RegexOption.IGNORE_CASE,
        )
        /** Canary entend mal le prénom du propriétaire (proprietaire.variantes de maison.json), comme poc/dictionnaire.py. */
        private val PRENOM: Regex? = ConfigMaison.chaines(ConfigMaison.section("proprietaire"), "variantes").filter { it.isNotBlank() }
            .takeIf { it.isNotEmpty() }?.let { v -> Regex("\\b(" + v.joinToString("|") { Regex.escape(it) } + ")\\b", RegexOption.IGNORE_CASE) }
        private val INFINITIF = mapOf(
            "éteindre" to "éteins", "eteindre" to "éteins", "allumer" to "allume", "lancer" to "lance",
            "mettre" to "mets", "couper" to "coupe", "arrêter" to "arrête", "aspirer" to "aspire",
            "laver" to "lave", "nettoyer" to "nettoie", "transférer" to "transfère", "ramener" to "ramène",
            "baisser" to "baisse", "monter" to "monte", "remettre" to "remets", "passer" to "passe",
        )
        private val ARTICLE = Regex("(le|la|les|l'|toutes?|tous|un|une|du|des|ma|mon|mes|ta|ton|une)\\b", RegexOption.IGNORE_CASE)

        /** « Est-ce que tu peux éteindre la télé s'il te plaît ? » devient « éteins la télé ».
         *  Chaque règle appliquée est ajoutée à [regles] si la liste est fournie. */
        fun epurer(phrase: String, regles: MutableList<String>? = null): String {
            var t = (PRENOM?.replace(phrase.trim(), ConfigMaison.NOM_PROPRIETAIRE) ?: phrase.trim()).trimEnd(' ', '?', '.', '!')
            if (regles != null && t != phrase.trim().trimEnd(' ', '?', '.', '!')) regles.add("prénom mal entendu corrigé en « ${ConfigMaison.NOM_PROPRIETAIRE} »")
            var avant: String? = null
            while (avant != t) {
                avant = t
                DEBUT.find(t)?.let { m ->
                    regles?.add("début retiré : « ${m.value.trim().trimEnd(',')} »")
                    t = t.substring(m.range.last + 1)
                }
            }
            FIN.find(t)?.let { m ->
                regles?.add("fin retirée : « ${m.value.trim().trimStart(',').trim()} »")
                t = t.substring(0, m.range.first)
            }
            val mots = t.split(" ", limit = 2).toMutableList()
            if (mots.isNotEmpty() && mots[0].lowercase() in INFINITIF) {
                val imperatif = INFINITIF.getValue(mots[0].lowercase())
                regles?.add("infinitif vers impératif : « ${mots[0]} » devient « $imperatif »")
                mots[0] = imperatif
            }
            if (mots.size == 2 && mots[0].lowercase() in setOf("mais", "met", "mes") &&
                ARTICLE.matchesAt(mots[1], 0)
            ) {
                regles?.add("« ${mots[0]} » devant un article corrigé en « mets »")
                mots[0] = "mets"
            }
            return if (t.isNotEmpty()) mots.joinToString(" ") else phrase
        }

        fun motsCompatibles(a: String, b: String): Boolean = motDiscordant(a, b) == null

        /** Premier mot présent d'un seul côté sans mot proche de l'autre côté, ou null. */
        fun motDiscordant(a: String, b: String): String? {
            fun proche(m: String, o: String): Boolean {
                val r = ratio(m, o)
                return r >= 0.75 || (r >= 0.5 && m[0] == o[0])
            }
            val ma = a.split(" ")
            val mb = b.split(" ")
            for ((seuls, autres) in listOf((ma.toSet() - mb.toSet()) to mb, (mb.toSet() - ma.toSet()) to ma)) {
                for (m in seuls) if (m.length > 3 && autres.none { proche(m, it) }) return m
            }
            return null
        }

        /** difflib.SequenceMatcher(None, a, b).ratio() sans heuristique de rebut (chaînes courtes). */
        fun ratio(a: String, b: String): Double {
            if (a.isEmpty() && b.isEmpty()) return 1.0
            return 2.0 * correspondances(a, 0, a.length, b, 0, b.length) / (a.length + b.length)
        }

        private fun correspondances(a: String, alo: Int, ahi: Int, b: String, blo: Int, bhi: Int): Int {
            // find_longest_match de difflib : plus long bloc commun, le plus tôt dans a puis dans b.
            var meilleurI = alo
            var meilleurJ = blo
            var taille = 0
            var precedent = IntArray(bhi - blo + 1)
            for (i in alo until ahi) {
                val courant = IntArray(bhi - blo + 1)
                for (j in blo until bhi) {
                    if (a[i] == b[j]) {
                        val k = precedent[j - blo] + 1
                        courant[j - blo + 1] = k
                        if (k > taille) {
                            meilleurI = i - k + 1
                            meilleurJ = j - k + 1
                            taille = k
                        }
                    }
                }
                precedent = courant
            }
            if (taille == 0) return 0
            return taille +
                correspondances(a, alo, meilleurI, b, blo, meilleurJ) +
                correspondances(a, meilleurI + taille, ahi, b, meilleurJ + taille, bhi)
        }
    }
}
