package assistant.vocal.jarvis

/**
 * Questions vocales sur les mesures d'une pièce (S-L6), comprises en local sans LLM, sur le modèle de [MeteoQuestion] :
 * « quelle température dans le salon », « comment est l'air de la chambre », « l'humidité du séjour ».
 * La réponse vient des mesures déjà lues ([Mesures]) et ne commande rien. Une pièce protégée ne livre aucune valeur.
 */
internal object MesuresQuestion {

    enum class Sujet { TEMPERATURE, AIR, HUMIDITE, TOUT }

    data class Question(val piece: String, val nom: String, val sujet: Sujet)

    /** Verbes de commande : une phrase qui en contient un n'est pas une question de mesure (« mets l'air du salon »). */
    private val ORDRES = Regex("""\b(allume|allumer|eteins|eteindre|mets|mettre|baisse|baisser|monte|monter|active|activer|coupe|couper|lance|lancer|regle|regler|joue|ouvre|ferme)\b""")

    private fun sujet(t: String): Sujet? = when {
        Regex("""\b(co2|air|aerer|aeration|particules|qualite)\b""").containsMatchIn(t) -> Sujet.AIR
        Regex("""\bhumidite\b""").containsMatchIn(t) -> Sujet.HUMIDITE
        Regex("""\b(temperature|degres)\b""").containsMatchIn(t) ||
            Regex("""\b(combien fait il|il fait combien|combien il fait|fait il chaud|fait il froid|quel temps fait il)\b""").containsMatchIn(t) -> Sujet.TEMPERATURE
        Regex("""\bmesures\b""").containsMatchIn(t) -> Sujet.TOUT
        else -> null
    }

    /**
     * La pièce dont un nom est dans la phrase : son nom lisible, son identifiant ou une de ses zones de Home Assistant
     * (« salon » désigne la pièce « Séjour et cuisine » si elle est reliée à la zone salon). Le nom le plus long l'emporte,
     * sinon un mot de quatre lettres ou plus qui ne désigne qu'une pièce. Ambiguë ou absente : null.
     */
    private fun piece(t: String, pieces: Map<String, String>, zones: Map<String, List<String>>): Pair<String, String>? {
        val phrase = " $t "
        val candidats = pieces.map { (id, nom) ->
            val noms = (listOf(nom, id) + (zones[id] ?: emptyList())).map { DictionnaireLocal.normaliser(it.replace('_', ' ')) }.filter { it.isNotEmpty() }
            Triple(id, nom, noms)
        }
        candidats.mapNotNull { c -> c.third.filter { phrase.contains(" $it ") }.maxByOrNull { it.length }?.let { c to it.length } }
            .maxByOrNull { it.second }?.let { return it.first.first to it.first.second }
        val parMot = candidats.filter { c -> c.third.any { n -> n.split(' ').any { it.length >= 4 && phrase.contains(" $it ") } } }
        return if (parMot.size == 1) parMot[0].first to parMot[0].second else null
    }

    /**
     * [pieces] : identifiant vers nom lisible, pour les pièces reliées à des capteurs. [zones] : zones de Home Assistant
     * de chaque pièce (correspondance_pieces). Null si la phrase n'est pas une question de mesure.
     */
    fun comprendre(texteEntendu: String, pieces: Map<String, String>, zones: Map<String, List<String>> = emptyMap()): Question? {
        if (pieces.isEmpty()) return null
        val t = DictionnaireLocal.normaliser(texteEntendu)
        if (ORDRES.containsMatchIn(t)) return null
        val s = sujet(t) ?: return null
        val (id, nom) = piece(t, pieces, zones) ?: return null
        return Question(id, nom.ifEmpty { id.replace('_', ' ') }, s)
    }

    private fun entier(x: Double) = Mesures.arrondi(x)

    fun repondre(q: Question, p: Mesures.PieceMesures?): String {
        val lieu = "la pièce ${q.nom}"
        if (p == null) return "Je n'ai pas de mesure pour $lieu."
        return when (p.statut) {
            Mesures.Statut.PROTEGEE -> "Je ne donne pas les mesures de cette pièce."
            Mesures.Statut.AUCUN -> "Il n'y a pas de capteur dans $lieu."
            else -> when (q.sujet) {
                Sujet.TEMPERATURE -> {
                    val t = p.temperature
                    when {
                        t == null -> "Il n'y a pas de thermomètre dans $lieu."
                        t.valeur == null -> "La mesure de température de $lieu est absente depuis ${t.depuis}."
                        else -> "Il fait ${entier(t.valeur)}° dans $lieu, c'est ${t.mot}."
                    }
                }
                Sujet.HUMIDITE -> {
                    val h = p.humidite
                    when {
                        h == null -> "Il n'y a pas de capteur d'humidité dans $lieu."
                        h.valeur == null -> "La mesure d'humidité de $lieu est absente depuis ${h.depuis}."
                        else -> "L'humidité de $lieu est de ${entier(h.valeur)} %."
                    }
                }
                Sujet.AIR -> air(lieu, p)
                Sujet.TOUT -> {
                    val ligne = Mesures.ligneAccueil(q.nom, p)
                    if (ligne.isEmpty()) "Je n'ai pas de mesure pour $lieu." else ligne + if (p.alerte.isEmpty()) "." else ". " + p.alerte + "."
                }
            }
        }
    }

    private fun air(lieu: String, p: Mesures.PieceMesures): String {
        val a = p.air
        if (a == null) {
            val muet = p.co2?.depuis ?: p.pm25?.depuis
            return if (muet != null) "La mesure d'air de $lieu est absente depuis $muet." else "Il n'y a pas de capteur d'air dans $lieu."
        }
        val details = mutableListOf<String>()
        p.co2?.valeur?.let { details.add("CO2 ${entier(it)} ppm") }
        p.pm25?.valeur?.let { details.add("PM2.5 ${entier(it)} µg/m3") }
        val suivant = p.co2?.suivant?.takeIf { it.isNotEmpty() }?.let { " Le CO2 $it." } ?: ""
        val aerer = if (a.aerer) " Pense à aérer." else ""
        return "L'air de $lieu est ${a.mot}" + (if (details.isEmpty()) "" else ", " + details.joinToString(", ")) + "." + suivant + aerer
    }
}
