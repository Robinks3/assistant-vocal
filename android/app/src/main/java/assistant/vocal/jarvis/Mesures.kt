package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject
import java.time.Instant
import java.time.ZoneId

/**
 * Mesures par pièce (S-L6) : température, humidité, CO2 et particules fines lues sur les capteurs de Home Assistant.
 * Même logique que poc/mesures.py, vérifiée par les mêmes cas (poc/tests/cas_mesures.json, MesuresTest).
 *
 * Découverte par un seul gabarit posté sur /api/template ([gabarit]). La zone d'un capteur est celle de l'entité,
 * sinon celle de son appareil. La clé « correspondance_pieces » de maison.json relie les pièces de la vue 3D aux zones
 * (remplie à la main, [correspondance]).
 *
 * Seuils : une valeur sous le premier seuil est « bon », puis chaque seuil est inclus dans la classe du dessous
 * (CO2 correct de 800 à 1000 compris, médiocre au-dessus de 1000 jusqu'à 1500 compris, mauvais au-dessus). Même règle
 * pour les particules PM2.5 (9, 35,4, 55,4 µg/m3). Température : frais sous 19, agréable de 19 à 24 compris, chaud au-dessus.
 *
 * Sécurité : tant que PROTEGER_OCCUPANT est vrai, une pièce dont une zone, l'identifiant ou le nom figure dans
 * securite.zones_protegees ne montre aucune valeur, et le gabarit écarte ces zones dès Home Assistant. Drapeau coupé
 * (levée complète du 27/10/2026), [zonesProtegees] est vide et toutes les pièces montrent leurs mesures.
 */
object Mesures {

    val MOTS_AIR = listOf("bon", "correct", "médiocre", "mauvais")
    val COULEURS_AIR = listOf("#D4E6C8", "#EDD48A", "#EE9A45", "#D6503A")
    const val COULEUR_GRIS = "#9AA0A6"
    private val SEUILS_CO2 = doubleArrayOf(800.0, 1000.0, 1500.0)
    private val SEUILS_PM25 = doubleArrayOf(9.0, 35.4, 55.4)
    const val SEUIL_FRAIS = 19.0
    const val SEUIL_CHAUD = 24.0
    /** Au-delà de 2 h sans nouvelle valeur, une mesure n'est plus montrée ni colorée. */
    const val PEREMPTION_S = 2 * 3600.0
    /** Relevé relu toutes les 60 s au plus (les capteurs d'air se mettent à jour par minutes). */
    const val PERIODE_MS = 60_000L

    private val CLASSES_UTILES = listOf("temperature", "humidity", "carbon_dioxide", "pm25", "pm10", "aqi", "volatile_organic_compounds")
    private val CLASSES_CONNUES = CLASSES_UTILES + "illuminance"
    private val CLASSES_THERMOMETRE = setOf("temperature", "humidity")
    private val ABSENTS = setOf("unavailable", "unknown", "none", "")
    private val NOMBRE = Regex("""[+-]?(\d+(\.\d*)?|\.\d+)([eE][+-]?\d+)?""")

    // ------------------------------------------------------------ seuils et mots

    fun rangAir(valeur: Double, seuils: DoubleArray): Int = when {
        valeur < seuils[0] -> 0
        valeur <= seuils[1] -> 1
        valeur <= seuils[2] -> 2
        else -> 3
    }

    fun motCo2(valeur: Double): String = MOTS_AIR[rangAir(valeur, SEUILS_CO2)]
    fun motPm25(valeur: Double): String = MOTS_AIR[rangAir(valeur, SEUILS_PM25)]

    fun motTemperature(valeur: Double): String = when {
        valeur < SEUIL_FRAIS -> "frais"
        valeur <= SEUIL_CHAUD -> "agréable"
        else -> "chaud"
    }

    /** Phrase qui dit où la mesure change de mot (vide si elle est déjà au pire). [classe] : carbon_dioxide ou pm25. */
    fun seuilSuivant(classe: String, valeur: Double): String {
        val co2 = classe == "carbon_dioxide"
        val seuils = if (co2) SEUILS_CO2 else SEUILS_PM25
        val unite = if (co2) "ppm" else "µg/m3"
        val r = rangAir(valeur, seuils)
        if (r >= 3) return ""
        val s = seuils[r]
        val nombre = (if (s == Math.floor(s)) s.toLong().toString() else s.toString()).replace('.', ',')
        val mot = MOTS_AIR[r + 1]
        return if (r == 0) "passe à $mot dès $nombre $unite" else "passe à $mot au-dessus de $nombre $unite"
    }

    /** Entier le plus proche, les demis vers le haut (comme poc/mesures.py). */
    fun arrondi(x: Double): Long = Math.floor(x + 0.5).toLong()

    // ------------------------------------------------------------ découverte

    private val MODELE = """
        {%- set classes = __CLASSES__ -%}
        {%- set protegees = __PROTEGEES__ -%}
        {%- set ns = namespace(a=[]) -%}
        {%- for s in states.sensor if s.attributes.device_class in classes -%}
        {%- set d = device_id(s.entity_id) or '' -%}
        {%- set ze = area_id(s.entity_id) or '' -%}
        {%- set za = (area_id(d) if d else '') or '' -%}
        {%- if (ze or za) not in protegees and ze not in protegees and za not in protegees -%}
        {%- set ns.a = ns.a + [{'id': s.entity_id, 'nom': s.name, 'classe': s.attributes.device_class, 'etat': s.state, 'unite': s.attributes.unit_of_measurement or '', 'zone': ze, 'zone_appareil': za, 'appareil': d, 'modifie': as_timestamp(s.last_reported or s.last_updated)}] -%}
        {%- endif -%}
        {%- endfor -%}
        {{ {'maintenant': as_timestamp(now()), 'capteurs': ns.a} | tojson }}
    """.trimIndent()

    /** Gabarit de découverte à poster sur /api/template. Les zones protégées en sont écartées dès Home Assistant. */
    fun gabarit(zonesProtegees: Collection<String> = emptyList()): String {
        val protegees = zonesProtegees.map { it.lowercase() }.toSortedSet()
        return MODELE.replace("__CLASSES__", JSONArray(CLASSES_CONNUES).toString())
            .replace("__PROTEGEES__", JSONArray(protegees.toList()).toString()).trim()
    }

    data class Capteur(
        val id: String, val classe: String, val etat: String, val zone: String, val zoneAppareil: String,
        val appareil: String, val modifie: Double,
    )

    data class Releve(val maintenant: Double, val capteurs: List<Capteur>)

    /** Relevé lu dans la réponse du gabarit, ou null si elle est illisible. */
    fun lireReleve(texte: String?): Releve? {
        if (texte.isNullOrBlank()) return null
        val j = try { JSONObject(texte) } catch (_: Exception) { return null }
        val a = j.optJSONArray("capteurs") ?: return null
        val capteurs = (0 until a.length()).mapNotNull { i ->
            val o = a.optJSONObject(i) ?: return@mapNotNull null
            Capteur(
                o.optString("id"), o.optString("classe"), if (o.isNull("etat")) "" else o.optString("etat"),
                o.optString("zone"), o.optString("zone_appareil"), o.optString("appareil"), o.optDouble("modifie", 0.0).let { if (it.isNaN()) 0.0 else it },
            )
        }
        return Releve(j.optDouble("maintenant", 0.0).let { if (it.isNaN()) 0.0 else it }, capteurs)
    }

    /** Correspondance pièce vers zones, lue dans [config] (maison.json) : une zone ou une liste, en minuscules. */
    fun correspondance(config: JSONObject): Map<String, List<String>> {
        val brute = config.optJSONObject("correspondance_pieces") ?: return emptyMap()
        val sortie = LinkedHashMap<String, List<String>>()
        for (piece in brute.keys()) {
            if (piece.startsWith("_")) continue
            val v = brute.opt(piece)
            val zones = when (v) {
                is String -> listOf(v)
                is JSONArray -> (0 until v.length()).map { v.opt(it)?.toString() ?: "" }
                else -> continue
            }.map { it.trim().lowercase() }.filter { it.isNotEmpty() }
            if (zones.isNotEmpty()) sortie[piece] = zones
        }
        return sortie
    }

    /** Zones protégées de la configuration (securite.zones_protegees), en minuscules, vides quand PROTEGER_OCCUPANT est coupé. */
    fun zonesProtegees(): Set<String> =
        if (Securite.PROTEGER_OCCUPANT) zonesProtegees(ConfigMaison.section("securite")) else emptySet()

    fun zonesProtegees(securite: JSONObject): Set<String> {
        val a = securite.optJSONArray("zones_protegees") ?: return emptySet()
        return (0 until a.length()).map { a.optString(it).lowercase() }.filter { it.isNotEmpty() }.toSet()
    }

    /** Correspondance de la configuration de la maison. */
    fun correspondance(): Map<String, List<String>> =
        correspondance(JSONObject().put("correspondance_pieces", ConfigMaison.section("correspondance_pieces")))

    // ------------------------------------------------------------ calcul par pièce

    enum class Statut { OK, PROTEGEE, AUCUN, SANS_AIR, SANS_THERMOMETRE, ABSENTE }

    /** [depuis] : « 14 h 30 », l'heure de la dernière valeur quand la mesure est absente ou périmée. */
    data class Temperature(val valeur: Double?, val mot: String?, val depuis: String?)
    data class Humidite(val valeur: Double?, val depuis: String?)
    data class Air(val valeur: Double?, val mot: String?, val couleur: String?, val suivant: String, val depuis: String?)
    data class AirPiece(val rang: Int, val mot: String, val couleur: String, val aerer: Boolean)

    data class PieceMesures(
        val statut: Statut, val texte: String, val couleur: String,
        val temperature: Temperature? = null, val humidite: Humidite? = null,
        val co2: Air? = null, val pm25: Air? = null, val air: AirPiece? = null, val alerte: String = "",
    )

    private fun nombre(etat: String?): Double? {
        if (etat == null) return null
        val t = etat.trim().lowercase()
        if (t in ABSENTS) return null
        val s = etat.trim().replace(',', '.')
        if (!NOMBRE.matches(s)) return null
        val v = s.toDoubleOrNull() ?: return null
        return if (v.isFinite()) v else null
    }

    fun heureLocale(horodatage: Double, fuseau: ZoneId): String {
        val d = Instant.ofEpochMilli(Math.floor(horodatage * 1000).toLong()).atZone(fuseau)
        return "${d.hour} h ${"%02d".format(d.minute)}"
    }

    private data class Lecture(val valeur: Double?, val ts: Double?, val depuis: String?)

    private fun lecture(capteurs: List<Capteur>, dedies: Set<String>, classe: String, maintenant: Double, fuseau: ZoneId): Lecture? {
        val ceux = capteurs.filter { it.classe == classe }
        if (ceux.isEmpty()) return null
        val bons = ceux.mapNotNull { c ->
            val v = nombre(c.etat)
            if (v != null && maintenant - c.modifie <= PEREMPTION_S) Pair(c, v) else null
        }
        if (bons.isEmpty()) {
            val derniere = ceux.maxOf { it.modifie }
            return Lecture(null, derniere, heureLocale(derniere, fuseau))
        }
        val d = bons.filter { it.first.id in dedies }.map { it.second }
        val xs = if (d.isNotEmpty()) d else bons.map { it.second }
        return Lecture(xs.sum() / xs.size, null, null)
    }

    private fun vide(statut: Statut, texte: String) = PieceMesures(statut, texte, COULEUR_GRIS)

    /** Mesures d'une pièce protégée : aucune valeur, jamais. */
    val PROTEGEE = PieceMesures(Statut.PROTEGEE, "pièce protégée", COULEUR_GRIS)

    /**
     * Mesures de chaque pièce de [corresp] à partir du [releve]. [protegees] : zones, pièces ou noms protégés (aucune
     * valeur pour ces pièces). [noms] : nom lisible de chaque pièce (sinon l'identifiant, comme le serveur : le repli lisible
     * se fait dans [deEtat]). [maintenant] remplace l'heure
     * du relevé quand l'appli a gardé ce relevé un moment.
     */
    fun parPiece(
        releve: Releve, corresp: Map<String, List<String>>, protegees: Collection<String>,
        fuseau: ZoneId = ZoneId.of("UTC"), noms: Map<String, String> = emptyMap(), maintenant: Double = releve.maintenant,
    ): Map<String, PieceMesures> {
        val prot = protegees.map { it.lowercase() }.toSet()
        // Un appareil qui n'expose que température et humidité est un thermomètre dédié.
        val classesParAppareil = HashMap<String, MutableSet<String>>()
        for (c in releve.capteurs) if (c.appareil.isNotEmpty()) classesParAppareil.getOrPut(c.appareil) { HashSet() }.add(c.classe)
        val dedies = releve.capteurs.filter { c ->
            val cl = classesParAppareil[c.appareil]
            c.appareil.isNotEmpty() && cl != null && cl.isNotEmpty() && CLASSES_THERMOMETRE.containsAll(cl)
        }.map { it.id }.toSet()
        val sortie = LinkedHashMap<String, PieceMesures>()
        for ((piece, zones) in corresp) {
            val nom = noms[piece]?.ifEmpty { null } ?: piece
            if (piece.lowercase() in prot || nom.lowercase() in prot || zones.any { it in prot }) {
                sortie[piece] = vide(Statut.PROTEGEE, "pièce protégée")
                continue
            }
            val ici = releve.capteurs.filter { c -> (c.zone.ifEmpty { c.zoneAppareil }).lowercase() in zones }
            sortie[piece] = piece(nom, ici, dedies, maintenant, fuseau)
        }
        return sortie
    }

    /**
     * Nom d'une pièce tel qu'il se dit et s'affiche (S-L7) : celui de la carte quand il est connu, sinon l'identifiant
     * rendu lisible (« chambre_camille » donne « Chambre camille »), jamais l'identifiant technique brut.
     */
    fun nomAffiche(piece: String, noms: Map<String, String>): String {
        noms[piece]?.trim()?.takeIf { it.isNotEmpty() }?.let { return it }
        val lisible = piece.replace('_', ' ').replace('-', ' ').trim()
        return if (lisible.isEmpty()) piece else lisible.replaceFirstChar { it.uppercaseChar() }
    }

    /** Un nom affiché par pièce de la configuration : celui de la carte, sinon le repli lisible de [nomAffiche]. */
    fun nomsLisibles(pieces: Collection<String>, noms: Map<String, String>): Map<String, String> =
        pieces.associateWith { nomAffiche(it, noms) }

    private fun piece(nom: String, capteurs: List<Capteur>, dedies: Set<String>, maintenant: Double, fuseau: ZoneId): PieceMesures {
        if (capteurs.isEmpty()) return vide(Statut.AUCUN, "pas de capteur")
        val t = lecture(capteurs, dedies, "temperature", maintenant, fuseau)
        val h = lecture(capteurs, dedies, "humidity", maintenant, fuseau)
        val co2 = lecture(capteurs, dedies, "carbon_dioxide", maintenant, fuseau)
        val pm = lecture(capteurs, dedies, "pm25", maintenant, fuseau)
        val temperature = t?.let { if (it.valeur == null) Temperature(null, null, it.depuis) else Temperature(it.valeur, motTemperature(it.valeur), null) }
        val humidite = h?.let { Humidite(it.valeur, it.depuis) }
        val rangs = ArrayList<Int>()
        val alertes = ArrayList<Pair<Int, String>>()
        val airs = HashMap<String, Air>()
        for ((cle, lec, seuils, classe, etiquette) in listOf(
            Quintuple("co2", co2, SEUILS_CO2, "carbon_dioxide", "CO2"),
            Quintuple("pm25", pm, SEUILS_PM25, "pm25", "PM2.5"),
        )) {
            if (lec == null) continue
            val v = lec.valeur
            if (v == null) {
                airs[cle] = Air(null, null, null, "", lec.depuis)
                continue
            }
            val rang = rangAir(v, seuils)
            airs[cle] = Air(v, MOTS_AIR[rang], COULEURS_AIR[rang], seuilSuivant(classe, v), null)
            rangs.add(rang)
            if (rang >= 2) alertes.add(Pair(rang, "$etiquette ${arrondi(v)} ${if (classe == "carbon_dioxide") "ppm" else "µg/m3"}"))
        }
        val air = if (rangs.isEmpty()) null else rangs.max().let { AirPiece(it, MOTS_AIR[it], COULEURS_AIR[it], it >= 2) }
        val alerte = if (air != null && air.aerer) "Aère la pièce $nom, " + alertes.maxWithOrNull(compareBy({ it.first }, { it.second }))!!.second else ""
        val tempOk = t != null && t.valeur != null
        val airOk = air != null
        val aAir = co2 != null || pm != null
        val absentes = listOfNotNull(t, co2, pm).filter { it.valeur == null }
        val depuis = if (absentes.isEmpty()) "" else heureLocale(absentes.maxOf { it.ts ?: 0.0 }, fuseau)
        val couleur = air?.couleur ?: COULEUR_GRIS
        fun avec(statut: Statut, texte: String) = PieceMesures(statut, texte, couleur, temperature, humidite, airs["co2"], airs["pm25"], air, alerte)
        return when {
            t == null && !aAir -> avec(Statut.SANS_THERMOMETRE, "pas de thermomètre")
            t != null && !aAir ->
                avec(Statut.SANS_AIR, (if (tempOk) "${arrondi(t.valeur!!)}°" else "mesure absente depuis $depuis") + ", pas de capteur d'air")
            !tempOk && !airOk && t != null -> avec(Statut.ABSENTE, "mesure absente depuis $depuis")
            else -> {
                val parties = ArrayList<String>()
                if (tempOk) parties.add("${arrondi(t!!.valeur!!)}°")
                else if (t != null) parties.add("température absente depuis ${heureLocale(t.ts ?: 0.0, fuseau)}")
                if (airOk) parties.add("air ${air!!.mot}")
                else parties.add("air absent depuis " + heureLocale(listOfNotNull(co2, pm).mapNotNull { it.ts }.maxOrNull() ?: 0.0, fuseau))
                val sansThermometre = t == null
                if (sansThermometre) parties.add("pas de thermomètre")
                avec(if (sansThermometre) Statut.SANS_THERMOMETRE else Statut.OK, parties.joinToString(", "))
            }
        }
    }

    private data class Quintuple(val a: String, val b: Lecture?, val c: DoubleArray, val d: String, val e: String)

    // ------------------------------------------------------------ pour l'appli

    /** Ligne d'accueil : « Salon 21°, air bon » (nom de la pièce puis le résumé). Vide si la pièce n'a rien à dire. */
    fun ligneAccueil(nom: String, p: PieceMesures): String =
        if (p.statut == Statut.AUCUN || p.statut == Statut.PROTEGEE) "" else "$nom ${p.texte}"

    /**
     * Ligne de l'accueil (S-L7), une seule, lisible de loin. Règle : si une pièce a l'air médiocre ou mauvais, c'est
     * elle qui parle (la pire d'abord, à égalité la première de la configuration). Sinon la pièce principale, c'est-à-dire
     * la première de `correspondance_pieces` qui a une température ou un air à dire. Une pièce protégée, sans capteur
     * ou dont tout est muet ne parle jamais. Vide quand personne n'a rien à dire.
     */
    fun ligneAccueil(pieces: Map<String, PieceMesures>, noms: Map<String, String> = emptyMap()): String {
        val parlantes = pieces.filter { (_, p) -> p.statut == Statut.OK || p.statut == Statut.SANS_AIR || p.statut == Statut.SANS_THERMOMETRE }
        if (parlantes.isEmpty()) return ""
        val alerte = parlantes.entries.filter { it.value.air?.aerer == true }.maxByOrNull { it.value.air?.rang ?: 0 }
        val choix = alerte ?: parlantes.entries.first()
        return ligneAccueil(nomAffiche(choix.key, noms), choix.value)
    }

    /** Alertes de toutes les pièces, la plus grave d'abord (une phrase par pièce à aérer). */
    fun alertes(pieces: Map<String, PieceMesures>): List<String> =
        pieces.values.filter { it.alerte.isNotEmpty() }.sortedByDescending { it.air?.rang ?: 0 }.map { it.alerte }

    /** Noms lisibles des pièces (page 3D), posés par l'écran d'accueil pour que la voix reconnaisse « le salon ». */
    @Volatile var nomsPieces: Map<String, String> = emptyMap()

    /**
     * Mesures de chaque pièce depuis l'état de l'appli : le dernier relevé, vieilli de l'horloge de l'appareil écoulée
     * depuis sa lecture (un capteur muet passe au gris sans attendre une nouvelle lecture). Vide sans relevé ni
     * correspondance_pieces.
     */
    fun deEtat(
        e: Etat.Instantane, noms: Map<String, String> = nomsPieces,
        horloge: Long = android.os.SystemClock.elapsedRealtime(),
    ): Map<String, PieceMesures> {
        val releve = e.mesures ?: return emptyMap()
        val corresp = correspondance()
        if (corresp.isEmpty()) return emptyMap()
        val ecoule = (horloge - e.mesuresLe) / 1000.0
        // Nom de la carte, sinon repli lisible : l'alerte « Aère la pièce X » ne dit jamais l'identifiant technique.
        return parPiece(releve, corresp, zonesProtegees(), ZoneId.systemDefault(), nomsLisibles(corresp.keys, noms), releve.maintenant + ecoule)
    }
}
