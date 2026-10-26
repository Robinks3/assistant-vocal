package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject
import kotlin.math.abs
import kotlin.math.roundToInt

/**
 * La maison en grand (0.27.0), logique pure testée sur la machine (MaisonEnGrandTest). Demande du
 * 23/10/2026 : « Je veux pouvoir cliquer sur la maison, que ça mette en grand la maison et que je puisse interagir
 * sur la vue 3D pour modifier des réglages. » Piste « mélange » du canevas (version 29), décisions dans
 * docs/maquettes/revue-accueil-musique.md.
 *
 * Les pièces et leurs objets viennent de la page 3D (maison3d.contenu : lampes, groupes, télé et enceintes posées
 * sur un meuble de la pièce), leurs états de Home Assistant (Etat.lumieres et Etat.mediasPlan). Une pièce qui a
 * quelque chose à régler porte son nom au sol. Une pièce protégée (drapeau de l'occupant remis dans Securite)
 * reste nommée, avec un cadenas, mais ne dit rien de ses lampes et ne s'ouvre pas.
 */
internal object MaisonEnGrand {

    /** Zones du plan en grand : la maison entière sous la barre du haut, la pièce choisie à gauche du panneau. */
    val ZONE_ENTIERE = Disposition.Zone(0.03f, 0.13f, 0.94f, 0.83f)
    val ZONE_PIECE = Disposition.Zone(0.02f, 0.12f, 0.6f, 0.84f)
    /** Cadrage en 600 ms, pastilles de 56 px et noms au sol en 20 px de maquette, voile de 0,65 le jour et 0,7 le soir. */
    const val DUREE_CADRAGE_MS = 600L
    const val TAILLE_PASTILLE = 56f
    const val POLICE_ETIQUETTE = 20f
    const val VOILE_JOUR = 0.65f
    const val VOILE_SOIR = 0.7f
    /** Retour automatique à l'accueil après 45 s sans toucher. */
    const val RETOUR_MS = 45_000L
    /** Tant qu'une demande attend sa confirmation, l'accueil se revoit à ce rythme. */
    const val REVUE_MS = 300L

    enum class Genre(val page: String) { LAMPE("lampe"), TELE("tele"), ENCEINTE("enceinte") }

    /** Objet réglable d'une pièce : [entite] de la page (et ses [alias] dans HA pour une enceinte). */
    data class Objet(val entite: String, val nom: String, val genre: Genre, val alias: List<String> = emptyList())

    data class Piece(val id: String, val nom: String, val objets: List<Objet>) {
        val lampes: List<Objet> get() = objets.filter { it.genre == Genre.LAMPE }
        val tele: Objet? get() = objets.firstOrNull { it.genre == Genre.TELE }
        val enceintes: List<Objet> get() = objets.filter { it.genre == Genre.ENCEINTE }
    }

    /** Suivi d'un objet sur la pastille et la ligne : normal, demande restée sans réponse, hors ligne. */
    enum class Suivi(val page: String) { OK("ok"), RATE("rate"), HORS("hors") }

    /** Noms courts du panneau (maquette `MaisonMelange`), sinon celui de la page ou de Home Assistant. */
    // appareils.noms_courts de la configuration de la maison (maison.json).
    private val NOMS: Map<String, String> = ConfigMaison.section("appareils").optJSONObject("noms_courts")?.let { o ->
        o.keys().asSequence().associateWith { o.getString(it) }
    } ?: emptyMap()

    /** Noms masculins, pour accorder « allumé » et « éteint ». Un nom en s est au pluriel. */
    private val MASCULINS = listOf("Plafond", "Chevet", "Plafonnier", "Lampadaire", "Spot")

    /** États où une lampe, une télé ou une enceinte ne répond pas. */
    private val HORS_LIGNE = setOf("unavailable", "unknown")

    /** Pièces de maison3d.contenu, celles sans rien à régler comprises (elles ne sont pas nommées). */
    fun lireContenu(json: String?): List<Piece> {
        if (json.isNullOrBlank()) return emptyList()
        val a = try { JSONArray(json) } catch (_: Exception) { return emptyList() }
        return (0 until a.length()).mapNotNull { i ->
            val p = a.optJSONObject(i) ?: return@mapNotNull null
            val id = p.optString("id").ifBlank { return@mapNotNull null }
            val objets = mutableListOf<Objet>()
            p.optJSONArray("lampes")?.let { l ->
                for (k in 0 until l.length()) l.optJSONObject(k)?.let { o ->
                    val e = o.optString("entite")
                    if (e.startsWith("light.")) objets.add(Objet(e, o.optString("nom"), Genre.LAMPE))
                }
            }
            p.optJSONArray("medias")?.let { m ->
                for (k in 0 until m.length()) m.optJSONObject(k)?.let { o ->
                    val e = o.optString("entite")
                    if (!e.startsWith("media_player.")) return@let
                    val alias = o.optJSONArray("alias")?.let { x -> (0 until x.length()).map { x.optString(it) }.filter { it.isNotEmpty() } } ?: emptyList()
                    objets.add(Objet(e, o.optString("nom"), if (o.optString("type") == "tele") Genre.TELE else Genre.ENCEINTE, alias))
                }
            }
            // Ordre du panneau : les lampes, puis la télé, puis les enceintes.
            Piece(id, p.optString("nom").ifBlank { id }, objets.sortedBy { it.genre.ordinal })
        }
    }

    /** États lus dans HA (lumières et lecteurs), par entité. */
    fun index(lumieres: List<Appareils.Appareil>, medias: List<Appareils.Appareil>): Map<String, Appareils.Appareil> =
        (lumieres + medias).associateBy { it.id }

    /** L'appareil HA d'un objet : son entité, sinon un alias qui répond (barre de son groupée). */
    fun trouver(o: Objet, lus: Map<String, Appareils.Appareil>): Appareils.Appareil? {
        val candidats = (listOf(o.entite) + o.alias).mapNotNull { lus[it] }
        return candidats.firstOrNull { it.etat !in HORS_LIGNE } ?: candidats.firstOrNull()
    }

    fun nom(o: Objet, a: Appareils.Appareil?): String =
        NOMS[o.entite] ?: o.nom.ifBlank { a?.nom?.ifBlank { null } ?: Maison.nomBrut(o.entite) }

    /** « allumé » accordé au nom : allumée, allumés, allumées. */
    fun accorder(base: String, nom: String): String {
        val masculin = MASCULINS.any { nom.startsWith(it) }
        val pluriel = nom.trim().endsWith("s")
        return base + (if (masculin) "" else "e") + (if (pluriel) "s" else "")
    }

    fun horsLigne(a: Appareils.Appareil?): Boolean = a == null || a.etat in HORS_LIGNE

    /** Télé allumée : tout état autre qu'éteinte, en veille ou hors ligne. */
    fun teleAllumee(a: Appareils.Appareil?): Boolean = a != null && a.etat !in setOf("off", "standby") && a.etat !in HORS_LIGNE

    /**
     * Pièce protégée : drapeau de l'occupant remis (Securite.pieceProtegee, zoneProtegee), ou un de ses objets caché
     * à la personne reconnue (Appareils.visible). Rien ne l'est quand tous ses objets sont permis à cette personne
     * (règle 3 : l'occupant reconnu règle sa chambre).
     */
    fun protegee(p: Piece, lus: Map<String, Appareils.Appareil>, personne: String): Boolean {
        val permises = Securite.entitesPermises(personne)
        if (p.objets.isNotEmpty() && p.objets.all { it.entite in permises }) return false
        if (Securite.pieceProtegee(p.nom) || Securite.zoneProtegee(p.id)) return true
        return p.objets.any { o ->
            val a = trouver(o, lus)
            if (a != null) !Appareils.visible(a, personne) else Securite.protege(o.entite)
        }
    }

    /** État court d'une pièce sous son nom : « 3 allumées », « télé allumée », « éteinte ». */
    fun etatPiece(p: Piece, lus: Map<String, Appareils.Appareil>): String {
        val on = p.lampes.count { trouver(it, lus)?.let { a -> a.allume && !horsLigne(a) } == true }
        val parties = mutableListOf<String>()
        if (on == 1) parties.add("1 allumée") else if (on > 1) parties.add("$on allumées")
        if (p.tele?.let { teleAllumee(trouver(it, lus)) } == true) parties.add("télé allumée")
        if (p.enceintes.any { trouver(it, lus)?.etat == "playing" }) parties.add("musique")
        return parties.joinToString(", ").ifEmpty { if (p.lampes.isEmpty()) "" else "éteinte" }
    }

    /**
     * Étiquettes de la vue entière : chaque pièce qui a quelque chose à régler, avec ce qui y est allumé. Une pièce
     * protégée garde son nom et un cadenas, sans rien dire de ses lampes. [injoignable] : la maison ne répond plus,
     * les noms seuls.
     */
    fun etiquettes(
        pieces: List<Piece>, lus: Map<String, Appareils.Appareil>, personne: String, injoignable: Boolean,
        estProtegee: (Piece) -> Boolean = { protegee(it, lus, personne) },
        mesures: Map<String, Mesures.PieceMesures> = emptyMap(),
    ): JSONArray {
        val r = JSONArray()
        for (p in pieces) {
            if (p.objets.isEmpty()) continue
            val verrou = estProtegee(p)
            val o = JSONObject().put("piece", p.id).put("nom", p.nom)
                .put("etat", if (verrou || injoignable) "" else etatPiece(p, lus)).put("verrou", verrou)
            // S-L6 : pastille de mesures (texte, couleur). Une pièce verrouillée ne livre aucune valeur, même si un
            // relevé existe : la barrière du gabarit et celle-ci se doublent.
            val m = mesures[p.id]
            if (m != null && !injoignable) {
                val sure = if (verrou) Mesures.PROTEGEE else m
                o.put("mesure", JSONObject().put("texte", sure.texte).put("couleur", sure.couleur).put("statut", sure.statut.name.lowercase()))
            }
            r.put(o)
        }
        return r
    }

    /**
     * Charge de mesures envoyée à la page 3D pour la pièce [p] (S-L7), prête à afficher : la page ne calcule rien.
     * Les textes sont ceux de [Mesures] (même texte et même couleur que la pastille de la vue entière).
     * Une pièce [verrou]illée, ou que [Mesures] dit protégée, ne livre AUCUNE valeur, seulement « pièce protégée ».
     * Une pièce sans capteur ([m] nul ou statut AUCUN) dit « pas de capteur » et n'a pas de lignes.
     */
    fun mesuresPiece(p: Piece, m: Mesures.PieceMesures?, verrou: Boolean): JSONObject {
        val o = JSONObject().put("piece", p.id).put("nom", p.nom)
        if (verrou || m?.statut == Mesures.Statut.PROTEGEE) {
            val s = Mesures.PROTEGEE
            return o.put("statut", "protegee").put("texte", s.texte).put("couleur", s.couleur).put("lignes", JSONArray())
        }
        if (m == null || m.statut == Mesures.Statut.AUCUN) {
            return o.put("statut", "aucun").put("texte", "pas de capteur").put("couleur", Mesures.COULEUR_GRIS).put("lignes", JSONArray())
        }
        o.put("statut", m.statut.name.lowercase()).put("texte", m.texte).put("couleur", m.couleur)
        val lignes = JSONArray()
        fun ligne(cle: String, nom: String, valeur: String, mot: String?, couleur: String?, suivant: String = "") {
            lignes.put(
                JSONObject().put("cle", cle).put("nom", nom).put("valeur", valeur).put("mot", mot ?: "")
                    .put("couleur", couleur ?: Mesures.COULEUR_GRIS).put("suivant", suivant),
            )
        }
        m.temperature?.let { t ->
            if (t.valeur != null) ligne("temperature", "Température", "${Mesures.arrondi(t.valeur)}°", t.mot, Mesures.COULEUR_GRIS)
            else ligne("temperature", "Température", "absente depuis ${t.depuis}", null, null)
        }
        m.humidite?.let { h ->
            if (h.valeur != null) ligne("humidite", "Humidité", "${Mesures.arrondi(h.valeur)} %", null, null)
            else ligne("humidite", "Humidité", "absente depuis ${h.depuis}", null, null)
        }
        m.co2?.let { a ->
            if (a.valeur != null) ligne("co2", "CO2", "${Mesures.arrondi(a.valeur)} ppm", a.mot, a.couleur, a.suivant)
            else ligne("co2", "CO2", "absent depuis ${a.depuis}", null, null)
        }
        m.pm25?.let { a ->
            if (a.valeur != null) ligne("pm25", "Particules", "${Mesures.arrondi(a.valeur)} µg/m3", a.mot, a.couleur, a.suivant)
            else ligne("pm25", "Particules", "absentes depuis ${a.depuis}", null, null)
        }
        o.put("lignes", lignes)
        m.air?.let { a -> o.put("air", JSONObject().put("mot", a.mot).put("couleur", a.couleur).put("aerer", a.aerer)) }
        if (m.alerte.isNotEmpty()) o.put("alerte", m.alerte)
        return o
    }

    /**
     * Pastilles de la pièce choisie, une par objet, les mêmes partout (lampes, groupes, télé, enceintes). Fraction :
     * l'intensité d'une lampe allumée, le volume d'une enceinte sur le volume permis (Securite.VOLUME_MAX). [suivis] : demandes restées
     * sans réponse. [surligne] : l'entité dont la ligne vient d'être touchée.
     */
    fun pastilles(
        p: Piece, lus: Map<String, Appareils.Appareil>, suivis: Map<String, Suivi>, surligne: String?, injoignable: Boolean,
    ): JSONArray {
        val r = JSONArray()
        for (o in p.objets) {
            val a = trouver(o, lus)
            val suivi = when {
                injoignable || horsLigne(a) -> Suivi.HORS
                else -> suivis[o.entite] ?: Suivi.OK
            }
            val allume = when (o.genre) {
                Genre.LAMPE -> a?.allume == true
                Genre.TELE -> teleAllumee(a)
                Genre.ENCEINTE -> a != null && a.etat !in setOf("off", "standby") && !horsLigne(a)
            }
            val fraction = when {
                a == null -> 0.0
                o.genre == Genre.LAMPE -> if (a.allume) (a.luminosite ?: 100) / 100.0 else 0.0
                o.genre == Genre.ENCEINTE -> VolumeVise.fraction(a.volume ?: 0.0)
                else -> 0.0
            }
            r.put(
                JSONObject().put("entite", o.entite).put("genre", o.genre.page)
                    .put("fraction", (fraction * 100).roundToInt() / 100.0).put("allume", allume)
                    .put("etat", suivi.page).put("surligne", o.entite == surligne),
            )
        }
        return r
    }

    /** Résumé sous le titre du panneau : « 3 lampes allumées », « 1 lampe allumée sur 3 », « Lampes éteintes ». */
    fun resume(p: Piece, lus: Map<String, Appareils.Appareil>): String {
        val lampes = p.lampes.map { trouver(it, lus) }
        val n = lampes.size
        if (n == 0) return ""
        val on = lampes.count { it != null && it.allume && !horsLigne(it) }
        return when {
            on == 0 -> if (n == 1) "Lampe éteinte" else "Lampes éteintes"
            on == n -> if (n == 1) "1 lampe allumée" else "$n lampes allumées"
            on == 1 -> "1 lampe allumée sur $n"
            else -> "$on lampes allumées sur $n"
        }
    }

    /** État d'une lampe sous son nom : « allumée, 80 % », « allumés », « éteinte », « hors ligne ». */
    fun etatLampe(nom: String, a: Appareils.Appareil?): String = when {
        horsLigne(a) -> "hors ligne"
        a!!.allume -> accorder("allumé", nom) + (a.luminosite?.takeIf { a.reglable }?.let { ", $it %" } ?: "") +
            (ReglageLampe.blancAffiche(a)?.let { ", $it" } ?: if (ReglageLampe.enCouleur(a)) ", couleur" else "")
        else -> accorder("éteint", nom)
    }

    /** Phrase de l'échec, en bas à gauche, 8 s : « La lampe de la télé n'a pas répondu. » */
    fun phraseEchec(noms: List<String>): String {
        if (noms.isEmpty()) return ""
        val d = noms.distinct()
        val sujet = if (d.size == 1) article(d[0]) else d.dropLast(1).joinToString(", ") { article(it) } + " et " + article(d.last())
        return majuscule(sujet) + (if (d.size == 1) " n'a pas répondu." else " n'ont pas répondu.")
    }

    private fun article(nom: String): String {
        val n = nom.replaceFirstChar { it.lowercase() }
        return when {
            n.endsWith("s") -> "les $n"
            n.first() in "aeéèêiîoôuyh" -> "l'$n"
            MASCULINS.any { nom.startsWith(it) } -> "le $n"
            else -> "la $n"
        }
    }

    private fun majuscule(s: String) = s.replaceFirstChar { it.titlecase() }

    /** État que la ligne montre tout de suite après un toucher, avant que HA ne le confirme. */
    fun prevuBascule(a: Appareils.Appareil, c: Appareils.Commande): Appareils.Appareil = when (c.service.substringAfter('.')) {
        "turn_off" -> a.copy(etat = "off", luminosite = null, mode = "", kelvin = null, teinte = null)
        "turn_on" -> a.copy(etat = "on", mode = "", kelvin = null, teinte = null)
        else -> a
    }

    fun prevuIntensite(a: Appareils.Appareil, pct: Int): Appareils.Appareil =
        if (pct <= 0) a.copy(etat = "off", luminosite = null, mode = "", kelvin = null, teinte = null)
        else a.copy(etat = "on", luminosite = pct, mode = "", kelvin = null, teinte = null)
}

/**
 * Demandes en attente de Home Assistant (0.27.0) : l'état prévu est montré tout de suite. Confirmé par une lecture,
 * il s'efface. Sans confirmation au bout de [delaiMs], la demande devient un échec, gardé [dureeEchecMs] : la ligne
 * garde la valeur demandée en fantôme et dit « n'a pas répondu ». Horloge monotone donnée par l'appelant.
 */
internal class Attentes(private val delaiMs: Long = DELAI_MS, private val dureeEchecMs: Long = DUREE_ECHEC_MS) {

    private class Demande(val prevu: Appareils.Appareil, val le: Long, val volume: Boolean) {
        var rateLe = 0L
    }

    private val demandes = HashMap<String, Demande>()

    /** Demande partie : [prevu] est l'état attendu, [volume] vrai pour un volume (seul le volume est alors comparé). */
    fun poser(prevu: Appareils.Appareil, maintenant: Long, volume: Boolean = false) {
        demandes[prevu.id] = Demande(prevu, maintenant, volume)
    }

    /** Nouvelle lecture ou seconde qui passe : confirmations, échecs, échecs oubliés. Rend vrai si quelque chose change. */
    fun avancer(lus: Map<String, Appareils.Appareil>, maintenant: Long): Boolean {
        var change = false
        val it = demandes.entries.iterator()
        while (it.hasNext()) {
            val d = it.next().value
            val l = lus[d.prevu.id]
            val confirme = l != null && conforme(l, d.prevu, d.volume)
            if (d.rateLe == 0L) {
                if (confirme) { it.remove(); change = true } else if (maintenant - d.le >= delaiMs) { d.rateLe = maintenant; change = true }
            } else if (confirme || maintenant - d.rateLe >= dureeEchecMs) {
                it.remove()
                change = true
            }
        }
        return change
    }

    /** Les états lus, recouverts des états prévus encore en attente (pas des échecs, qui montrent le vrai état). */
    fun vus(lus: Map<String, Appareils.Appareil>): Map<String, Appareils.Appareil> {
        val enAttente = demandes.values.filter { it.rateLe == 0L }
        if (enAttente.isEmpty()) return lus
        return lus + enAttente.associate { it.prevu.id to it.prevu }
    }

    /** Valeur demandée restée sans réponse, montrée en fantôme, ou null. */
    fun fantome(id: String): Appareils.Appareil? = demandes[id]?.takeIf { it.rateLe != 0L }?.prevu

    val echecs: List<String> get() = demandes.values.filter { it.rateLe != 0L }.sortedBy { it.rateLe }.map { it.prevu.id }

    /** Une demande attend encore sa confirmation (l'accueil se revoit alors plus souvent). */
    val enAttente: Boolean get() = demandes.values.any { it.rateLe == 0L }

    fun oublier() = demandes.clear()

    companion object {
        const val DELAI_MS = 5_000L
        const val DUREE_ECHEC_MS = 8_000L

        /**
         * La lecture confirme la demande : même marche ou arrêt et intensité à 2 points près pour une lampe, volume à
         * 2 points près pour un volume ([volume]), télé allumée ou éteinte comme demandé sinon.
         */
        fun conforme(l: Appareils.Appareil, p: Appareils.Appareil, volume: Boolean = false): Boolean = when {
            p.domaine == "light" -> (l.etat == "on") == (p.etat == "on") &&
                (p.etat != "on" || p.luminosite == null || l.luminosite == null || abs(l.luminosite - p.luminosite) <= 2) &&
                (p.etat != "on" || ReglageLampe.reglageConforme(l, p))
            volume -> p.volume != null && l.volume != null && abs(l.volume - p.volume) <= 0.02
            p.domaine == "media_player" -> MaisonEnGrand.teleAllumee(l) == MaisonEnGrand.teleAllumee(p)
            else -> l.etat == p.etat
        }
    }
}

/**
 * Cadence d'envoi d'un réglage au doigt (0.27.0, retouche du 23/10) : pendant le geste, une valeur au plus toutes
 * les [intervalleMs] et seulement si elle change ; à la fin du geste, la dernière valeur part si elle n'est pas
 * déjà partie. Jamais une commande par pixel. Horloge monotone donnée par l'appelant.
 */
internal class Cadence(private val intervalleMs: Long = INTERVALLE_MS) {
    private var envoiLe = Long.MIN_VALUE / 2
    private var envoyee: Int? = null

    /** Le doigt bouge à [valeur] : la valeur à envoyer maintenant, ou null. */
    fun bouge(valeur: Int, maintenant: Long): Int? {
        if (valeur == envoyee || maintenant - envoiLe < intervalleMs) return null
        envoiLe = maintenant
        envoyee = valeur
        return valeur
    }

    /** Doigt levé à [valeur] : elle part, sauf si c'est déjà la dernière envoyée. Le geste suivant repart de zéro. */
    fun fin(valeur: Int, maintenant: Long): Int? {
        val r = if (valeur == envoyee) null else valeur
        envoiLe = Long.MIN_VALUE / 2
        envoyee = null
        return r
    }

    companion object {
        const val INTERVALLE_MS = 300L
    }
}
