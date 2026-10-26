package assistant.vocal.jarvis

import java.util.Locale

/**
 * Historique lisible (0.17.0), logique pure testée sur la machine (HistoriqueLisibleTest).
 *
 * Les lignes « Fait » s'écrivaient avec les identifiants de Home Assistant (« light.turn_off
 * light.salon_plafond light.cuisine_suspensions »). Elles s'affichent maintenant avec les noms des appareils et un
 * verbe en français (« Salon et Cuisine : éteintes »), les mentions d'essai, de refus et d'action
 * écartée gardées. La ligne brute reste dans les données (journal, retours au serveur).
 * Une même commande reçue deux fois (historique complet puis ajout, vu à 23:27:38 le 21/10) n'est
 * montrée qu'une fois.
 */
object HistoriqueLisible {

    /** Ligne « Fait » avec les noms lisibles. [noms] : identifiant vers nom (friendly_name de HA). */
    fun ligne(brute: String, noms: Map<String, String>): String {
        // Le refus est retiré d'abord : sa raison contient souvent « (sécurité) », des parenthèses
        // imbriquées que Maison.lireLigne ne sait pas lire.
        var l = brute.trim()
        var raison: String? = null
        val i = l.indexOf(" (refusé")
        if (i > 0 && l.endsWith(")")) {
            raison = l.substring(i + " (refusé".length, l.length - 1).trim().removePrefix(":").trim()
            l = l.substring(0, i)
        }
        val a = Maison.lireLigne(l) ?: return brute
        val suite = when {
            a.essai -> " (essai, rien n'a été envoyé)"
            raison != null || a.refusee -> if (!raison.isNullOrEmpty()) " (refusé : $raison)" else " (refusé)"
            a.ecartee -> " (écartée)"
            else -> ""
        }
        if (a.service.startsWith("assist.")) {
            val cible = a.entites.firstOrNull()?.let { noms[it] ?: Maison.nomBrut(it) } ?: (a.donnees["nom"] ?: "")
            return "Assist de Home Assistant : ${cible.ifBlank { "fait" }}$suite"
        }
        val qui = when {
            // Rien de l'occupant protégé en clair, même dans un refus.
            a.entites.any(Securite::protege) -> listOf("Appareil protégé")
            a.entites.isEmpty() -> listOf(a.service.substringBefore('.').let(::domaineLisible))
            else -> a.entites.map { noms[it]?.takeIf { n -> n.isNotBlank() } ?: Maison.nomBrut(it) }.distinct()
        }
        val verbe = Maison.verbe(a)
        return "${liste(qui)} : ${accorder(verbe, qui.size)}$suite"
    }

    /** « A », « A et B », « A, B et C ». */
    fun liste(noms: List<String>): String =
        if (noms.size <= 1) noms.joinToString("") else noms.dropLast(1).joinToString(", ") + " et " + noms.last()

    /** Participe au pluriel pour plusieurs appareils : « éteinte » devient « éteintes ». */
    fun accorder(verbe: String, nombre: Int): String {
        if (nombre <= 1 || verbe.contains(' ')) return verbe
        return if (verbe.endsWith("e") || verbe.endsWith("é")) verbe + "s" else verbe
    }

    private fun domaineLisible(d: String): String = when (d) {
        "light" -> "Lumières"
        "media_player" -> "Musique"
        "script" -> "Script"
        "scene" -> "Scène"
        "automation" -> "Automatisation"
        else -> d.replaceFirstChar { it.titlecase(Locale.FRANCE) }
    }

    /**
     * Sans doublon : une commande à la même date, à la même seconde, avec le même texte entendu et la
     * même réponse n'apparaît qu'une fois (la plus récente de la liste est gardée).
     */
    fun sansDoublons(entrees: List<Etat.EntreeHistorique>): List<Etat.EntreeHistorique> = entrees.distinctBy(::cle)

    /** Vrai si [e] est déjà dans [liste] (même date, même seconde, même texte et même réponse). */
    fun dejaVue(e: Etat.EntreeHistorique, liste: List<Etat.EntreeHistorique>): Boolean = liste.any { cle(it) == cle(e) }

    private fun cle(e: Etat.EntreeHistorique) = listOf(e.date, e.heure, e.entendu.trim().lowercase(Locale.FRANCE), e.reponse.trim())
}
