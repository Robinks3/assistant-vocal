package assistant.vocal.jarvis

import android.content.Context
import org.json.JSONArray
import org.json.JSONObject

/**
 * Moteur de génération de texte qui tourne sur l'appareil (Gemma, Qwen...). Une implémentation par
 * bibliothèque. La consigne système et les exemples passent par le modèle de conversation du modèle.
 */
interface ModeleTexte : AutoCloseable {
    /** Nom affiché dans le déroulé, ex. « gemma-4-E2B-it-gpu (GPU) ». */
    val nom: String

    /** Réponse à [phrase] après [systeme] et les [exemples] (phrase, réponse attendue). Hors thread principal. */
    fun generer(systeme: String, exemples: List<Pair<String, String>>, phrase: String): String
}

/**
 * LLM de secours sur l'appareil (mode « Cet appareil »). Les petits modèles n'ont pas d'appel
 * d'outils fiable : on leur demande une réponse JSON unique, puis on la vérifie ici.
 *
 * Consigne « C » retenue au banc du 13/10/2026 (poc/outils/banc_llm_maison.py, 20 phrases notées) :
 * Gemma 4 E2B passe de 12/20 avec l'ancienne consigne à 18/20, Haiku fait 19 à 20/20 avec la même.
 * Ce qui a aidé : consigne système séparée, exemples sous forme d'échanges, appareils groupés par
 * type avec leur nom et leur pièce, pièges de la maison dits explicitement (la lampe de la télé
 * n'est pas la télé), règle de la pièce absente. La sécurité en dur reste le dernier mot.
 */
class CerveauAppareil(contexte: Context, private val passerelle: PasserelleHa, private val modele: ModeleTexte) : AutoCloseable {

    class Action(val service: String, val donnees: JSONObject) {
        fun enJson(): JSONObject = JSONObject(donnees.toString()).put("service", service)
    }

    class Decision(
        val reponse: String,
        val actions: List<Action>,
        /** Actions proposées par le modèle et écartées, avec la raison. */
        val ecartees: List<String>,
        val brut: String,
        val msInventaire: Long,
        val msModele: Long,
        val tailleprompt: Int = 0,
    )

    /** Appareil pilotable : identifiant, nom affiché, état, pièce. */
    private class Appareil(val id: String, val nom: String, val etat: String, val piece: String)

    private val renommer = HashMap<String, String>()
    private val masquer = HashSet<String>()
    private val permis = HashMap<String, Set<String>>()
    private var inventaire: List<Appareil> = emptyList()
    private var inventaireLe = 0L

    val nom: String get() = modele.nom

    init {
        val j = JSONObject(contexte.assets.open("dictionnaire.json").bufferedReader(Charsets.UTF_8).use { it.readText() })
        val llm = j.optJSONObject("llm") ?: JSONObject()
        llm.optJSONObject("renommer")?.let { o -> o.keys().forEach { renommer[it] = o.getString(it) } }
        llm.optJSONArray("masquer")?.let { a -> for (i in 0 until a.length()) masquer.add(a.getString(i)) }
        j.optJSONObject("services_permis")?.let { o ->
            o.keys().forEach { d -> permis[d] = o.getJSONArray(d).let { a -> (0 until a.length()).map { a.getString(it) }.toSet() } }
        }
    }

    /** Appareils lus dans HA avec leur pièce, sans rien de l'occupant protégé ni d'appareil masqué (5 min de cache). */
    private fun majInventaire() {
        if (System.currentTimeMillis() - inventaireLe < 5 * 60_000 && inventaire.isNotEmpty()) return
        val modeleHa = "{% for s in states %}{{ s.entity_id }}\t{{ s.name }}\t{{ s.state }}\t{{ area_name(s.entity_id) or '' }}\n{% endfor %}"
        // Lecture par la passerelle de l'app Jarvis sur HA (0.15.0) : plus de jeton HA dans l'APK.
        val r = passerelle.requete("POST", "/api/template", JSONObject().put("template", modeleHa))
        if (!r.ok) error("Home Assistant a répondu HTTP ${r.code} (${r.corps.take(120)})")
        val texte = r.corps
        val liste = ArrayList<Appareil>()
        for (ligne in texte.lines()) {
            val p = ligne.split("\t")
            if (p.size != 4) continue
            val (id, nomHa, etat, piece) = p
            val domaine = id.substringBefore(".")
            if (domaine !in DOMAINES || id in masquer || Securite.pieceProtegee(piece)) continue
            if (Securite.verifier(JSONObject().put("service", "$domaine.turn_on").put("entity_id", id), 12) != null) continue
            liste.add(Appareil(id, renommer[id] ?: nomHa, etat, piece))
        }
        inventaire = liste
        inventaireLe = System.currentTimeMillis()
    }

    private fun systeme(): String {
        fun lignes(filtre: (String) -> Boolean) = inventaire.filter { filtre(it.id) }.joinToString("\n") { a ->
            "- ${a.nom}" + (if (a.piece.isNotBlank()) " (${a.piece})" else "") + " : ${a.id}"
        }.ifBlank { "- (aucun)" }
        return CONSIGNE
            .replace("{lumieres}", lignes { it.startsWith("light.") })
            .replace("{medias}", lignes { it.startsWith("media_player.") })
            .replace("{autres}", lignes { !it.startsWith("light.") && !it.startsWith("media_player.") })
    }

    fun decider(texte: String): Decision {
        val t0 = System.currentTimeMillis()
        majInventaire()
        val sys = systeme()
        val t1 = System.currentTimeMillis()
        val brut = modele.generer(sys, EXEMPLES, texte)
        val t2 = System.currentTimeMillis()
        return interpreter(brut, t1 - t0, t2 - t1).let {
            Decision(it.reponse, it.actions, it.ecartees, it.brut, it.msInventaire, it.msModele, sys.length + texte.length)
        }
    }

    /** Premier objet JSON complet du texte (accolades équilibrées, hors chaînes) qui contient « actions ».
     *  Gemma recopiait parfois les exemples à la suite, ou commençait par « {"{" » avec la sortie contrainte. */
    private fun premierObjet(brut: String): JSONObject? {
        var i = brut.indexOf('{')
        while (i >= 0) {
            var profondeur = 0
            var dansChaine = false
            var echappe = false
            var fin = -1
            for (k in i until brut.length) {
                val ch = brut[k]
                if (dansChaine) {
                    if (echappe) echappe = false
                    else if (ch == '\\') echappe = true
                    else if (ch == '"') dansChaine = false
                    continue
                }
                when (ch) {
                    '"' -> dansChaine = true
                    '{' -> profondeur++
                    '}' -> if (--profondeur == 0) { fin = k; break }
                }
            }
            if (fin >= 0) {
                try {
                    val o = JSONObject(brut.substring(i, fin + 1))
                    if (o.has("actions") || o.has("reponse")) return o
                } catch (_: Exception) {
                }
            }
            i = brut.indexOf('{', i + 1)
        }
        return null
    }

    private fun interpreter(brut: String, msInv: Long, msMod: Long): Decision {
        android.util.Log.i("JarvisLlm", "sortie brute : " + brut.replace("\n", " ").take(600))
        val j = premierObjet(brut)
            ?: return Decision("Je n'ai pas compris.", emptyList(), listOf("réponse du modèle illisible (pas de JSON)"), brut, msInv, msMod)
        val connus = inventaire.map { it.id }.toSet()
        val actions = ArrayList<Action>()
        val ecartees = ArrayList<String>()
        val a = j.optJSONArray("actions") ?: JSONArray()
        for (i in 0 until minOf(a.length(), 3)) {
            val o = a.optJSONObject(i) ?: continue
            var service = o.optString("service")
            var cibles: Any? = o.opt("entity_id")
            // « script.nom » appelé comme service : c'est script.turn_on sur script.nom (valable dans HA).
            if (service.startsWith("script.") && service.substringAfter(".") !in (permis["script"] ?: emptySet())) {
                cibles = service
                service = "script.turn_on"
            }
            val domaine = service.substringBefore(".")
            val nomService = service.substringAfter(".", "")
            // Volume plafonné à 50 % (Securite.VOLUME_MAX) dès la lecture, pour que le compte rendu dise ce qui part.
            val donnees = Securite.plafonner(service, o.optJSONObject("donnees") ?: JSONObject())
            if (cibles != null) donnees.put("entity_id", cibles)
            val ids = when (cibles) {
                is JSONArray -> (0 until cibles.length()).map { cibles.optString(it) }
                null -> emptyList()
                else -> cibles.toString().split(",").map { it.trim() }.filter { it.isNotEmpty() }
            }
            val raison = when {
                nomService !in (permis[domaine] ?: emptySet()) -> "service $service hors de la liste permise"
                ids.isEmpty() -> "aucun appareil visé"
                ids.any { it !in connus } -> "appareil inconnu : ${ids.first { it !in connus }}"
                domaine != "script" && domaine != "scene" && ids.any { it.substringBefore(".") != domaine } ->
                    "service $service incohérent avec ${ids.first { it.substringBefore(".") != domaine }}"
                else -> Securite.verifier(JSONObject(donnees.toString()).put("service", service))
            }
            if (raison != null) ecartees.add("$service ${ids.joinToString(" ")} : $raison") else actions.add(Action(service, donnees))
        }
        val reponse = j.optString("reponse").ifBlank { if (actions.isEmpty()) "Je n'ai pas compris." else "C'est fait." }
        return Decision(reponse, actions, ecartees, brut, msInv, msMod)
    }

    override fun close() = modele.close()

    companion object {
        private val DOMAINES = setOf("light", "media_player", "script", "scene", "vacuum", "fan", "cover", "climate", "input_boolean")

        /** Consigne C du banc du 13/10/2026 (banc_llm_maison.py, outils de la configuration de la maison), à garder identique aux deux endroits. */
        private val CONSIGNE_MODELE = """Tu transformes une phrase de @UTILISATEUR@ en commandes Home Assistant pour son appartement.
Réponds par UN SEUL objet JSON, rien d'autre :
{"actions": [{"service": "...", "entity_id": "...", "donnees": {...}}], "reponse": "phrase courte en français"}

Règles strictes :
- entity_id : recopié tel quel dans la liste ci-dessous. N'invente jamais un identifiant.
- Le domaine du service est celui de l'appareil : une lumière (light.) prend light.turn_on ou light.turn_off, la télé (media_player.) prend media_player.*.
@CONSIGNES@- Son de la télé : media_player.volume_down, media_player.volume_set avec {"volume_level": 0.3}, ou media_player.volume_mute avec {"is_volume_muted": true}.
- Source de la télé : media_player.select_source avec {"source": "HDMI2"} ou {"source": "Netflix"}.
- Luminosité : light.turn_on avec {"brightness_pct": 1 à 100}. Tamisé ou cosy = 30, à fond = 100, à moitié = 50. Couleur : {"color_name": "green"} (nom anglais). Blanc chaud : {"color_temp_kelvin": 2700}.
- Au plus 3 actions. Si ce n'est pas une commande de la maison, ou si l'appareil n'est pas dans la liste : "actions": [] et dis-le en une phrase.

Lumières :
{lumieres}
Lecteurs multimédia (télé, enceintes) :
{medias}
Autres :
{autres}

Chaque appareil est suivi de sa pièce entre parenthèses. Si la phrase vise une pièce qui n'est pas dans la liste, n'agis pas : "actions": [] et dis que tu ne connais pas cette pièce. N'agis jamais sur une autre pièce que celle demandée."""

        /** Parties propres à la maison (section llm de maison.json) : qui parle, règles sur les appareils (une
         *  ligne « - ... » chacune), exemples [phrase, réponse JSON] donnés au modèle. */
        private val LLM = ConfigMaison.section("llm")
        private val CONSIGNE = CONSIGNE_MODELE
            .replace("@UTILISATEUR@", LLM.optString("utilisateur").ifEmpty { "l'utilisateur" })
            .replace("@CONSIGNES@", ConfigMaison.chaines(LLM, "consignes_appareil").joinToString("") { it + "\n" })

        private val EXEMPLES: List<Pair<String, String>> = LLM.optJSONArray("exemples_appareil")?.let { a ->
            (0 until a.length()).mapNotNull { i -> a.optJSONArray(i)?.takeIf { it.length() >= 2 }?.let { it.getString(0) to it.getString(1) } }
        } ?: emptyList()
    }
}
