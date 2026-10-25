package assistant.vocal.jarvis

import android.graphics.Bitmap
import android.graphics.BitmapFactory
import android.graphics.Color
import android.os.Handler
import android.os.Looper
import android.util.LruCache
import android.os.SystemClock
import android.util.Log
import org.json.JSONArray
import org.json.JSONObject
import java.util.Locale
import java.util.concurrent.ConcurrentHashMap
import java.util.concurrent.Executors
import java.util.concurrent.TimeUnit
import java.util.concurrent.atomic.AtomicLong

/**
 * Ce que l'écran ambiant de la tablette montre de la maison (0.16.0), lu dans Home Assistant par la
 * passerelle de l'appli de l'assistant sur HA (aucun jeton HA dans l'APK) :
 * - toutes les 10 min, /api/states : noms lisibles (friendly_name) et météo (entité weather) ;
 * - toutes les 30 s, /api/template : lumières allumées et ce qui joue en ce moment ;
 * - après chaque commande, une carte par action, puis l'état relu dans HA (« confirmé » ou
 *   « sans réponse »).
 * Rien de ce qui appartient à l'occupant protégé n'est compté ni nommé (Securite.protege et zoneProtegee).
 *
 * 0.16.2 : lecteurs de musique pour la carte En cours (titre, artiste, position, volume, pochette),
 * relus toutes les 5 s tant que quelque chose joue, et leurs commandes (précédent, lecture ou pause,
 * suivant, volume), toujours vérifiées par Securite.kt avant l'envoi.
 */
class Maison(
    /** Passerelle à utiliser, ou null : celle du moteur local, ou celle du mode station. */
    private val passerelle: () -> PasserelleHa?,
) : AutoCloseable {

    private val planif = Executors.newSingleThreadScheduledExecutor()
    /** Identifiant vers nom lisible, d'après le dernier /api/states. */
    private val noms = ConcurrentHashMap<String, String>()
    private val identifiants = AtomicLong(0)
    @Volatile private var ferme = false

    fun demarrer() {
        // 0.24.0 : volume lu pour changer un volume_up en volume_set plafonné (Securite.monterSansDepasser).
        Securite.volumeLu = { id ->
            val e = Etat.courant
            e.mediasPlan.firstOrNull { it.id == id }?.volume ?: e.lecteurs.firstOrNull { it.id == id }?.volume
                ?: e.appareils.firstOrNull { it.id == id }?.volume
        }
        planif.scheduleWithFixedDelay({ garder { lireEtats() } }, 2, 600, TimeUnit.SECONDS)
        planif.schedule({ boucleMaison() }, 4, TimeUnit.SECONDS)
    }

    /** Toutes les 30 s, toutes les 5 s quand de la musique joue (barre de progression, titre qui change). */
    private fun boucleMaison() {
        if (ferme) return
        garder { lireMaison() }
        val joue = Etat.courant.lecteurs.any { it.etat == "playing" }
        try {
            planif.schedule({ boucleMaison() }, if (joue) 5L else 30L, TimeUnit.SECONDS)
        } catch (_: Exception) {
        }
    }

    /** Lecteurs vus en train de jouer : identifiant et instant, pour garder la carte d'une pause récente. */
    private val vusJouer = ConcurrentHashMap<String, Long>()

    /**
     * Travail confié au fil de Maison. Sans effet une fois Maison fermée (service arrêté) : un toucher
     * arrivé juste après l'arrêt ne doit pas faire planter l'écran (RejectedExecutionException).
     */
    private fun lancer(travail: () -> Unit) {
        if (ferme) return
        try {
            planif.execute(travail)
        } catch (_: java.util.concurrent.RejectedExecutionException) {
        }
    }

    /**
     * Comme [lancer], mais une demande refusée (Maison fermée, service qui s'arrête) rend quand même la main
     * à l'appelant par [sinon], sur le fil principal (0.21.1) : un panneau ne reste pas en attente.
     */
    private fun lancerOuRendre(sinon: () -> Unit, travail: () -> Unit) {
        if (ferme) {
            principal.post(sinon)
            return
        }
        try {
            planif.execute(travail)
        } catch (_: java.util.concurrent.RejectedExecutionException) {
            principal.post(sinon)
        }
    }


    private inline fun garder(corps: () -> Unit) {
        if (ferme) return
        try {
            corps()
        } catch (e: Exception) {
            Log.w(TAG, "Lecture de Home Assistant impossible", e)
        }
    }

    // ------------------------------------------------------------ états, noms et météo

    private fun lireEtats() {
        val p = passerelle() ?: return
        if (!p.disponible) return
        val r = p.requete("GET", "/api/states", null, 30)
        if (!r.ok) return
        val a = JSONArray(r.corps)
        var meteo: Etat.Meteo? = null
        var soleil: Etat.Soleil? = null
        val meteos = ArrayList<Pair<String, String>>()
        for (i in 0 until a.length()) {
            val o = a.optJSONObject(i) ?: continue
            val id = o.optString("entity_id")
            val attributs = o.optJSONObject("attributes") ?: JSONObject()
            val nom = attributs.optString("friendly_name")
            if (id.isEmpty() || Securite.protege(id) || Securite.protege(nom)) continue
            if (nom.isNotBlank()) noms[id] = nom
            if (meteo == null && id.startsWith("weather.")) meteo = lireMeteo(id, o.optString("state"), attributs)
            if (id == "sun.sun") soleil = Previsions.soleilEtat(o.optString("state"), attributs)
            if (id.startsWith("weather.")) meteos.add(id to nom)
        }
        // Noms lisibles publiés pour l'historique (0.17.0), rien de l'occupant protégé (écarté plus haut).
        val lus = HashMap(noms)
        Etat.modifier { it.copy(meteo = meteo ?: it.meteo, noms = lus, soleil = soleil ?: it.soleil, meteos = meteos) }
    }

    private fun lireMeteo(id: String, etat: String, a: JSONObject): Etat.Meteo? {
        val t = a.optDouble("temperature")
        if (t.isNaN()) return null
        val unite = a.optString("temperature_unit").ifEmpty { "°C" }
        return Etat.Meteo(String.format(Locale.FRANCE, "%.0f %s", t, unite), meteoEnFrancais(etat), etat, id, a.optLong("supported_features", 0L))
    }

    /**
     * Panneau Météo (0.18.0), lu à l'ouverture du panneau puis toutes les 15 min tant qu'il est ouvert :
     * la météo du moment (attributs de l'entité weather), le soleil (sun.sun), puis le service
     * weather.get_forecasts avec sa réponse, en horaire puis par jour (deux par jour en repli) selon
     * supported_features. Repli sur l'ancien attribut forecast si le service échoue. Le refus éventuel de
     * la passerelle est rendu tel quel (journal JarvisMeteo). Rendu sur le fil principal.
     */
    fun previsions(suite: (Previsions.Lecture) -> Unit) = previsions(null, suite)

    /** Prévisions de l'entité [voulue] (0.20.0, deuxième entité météo du panneau), sinon de l'entité de l'accueil. */
    fun previsions(voulue: String?, suite: (Previsions.Lecture) -> Unit) {
        lancerOuRendre({ suite(Previsions.Lecture(erreur = "${ConfigMaison.NOM_ASSISTANT} à l'arrêt")) }) {
            val m0 = Etat.courant.meteo
            val m = if (voulue != null && voulue != m0?.entite) Etat.Meteo("", "", "", voulue, 0L) else m0
            var lecture = Previsions.Lecture(erreur = "Aucune entité météo lue dans Home Assistant")
            try {
                val p = passerelle()
                if (m != null && m.entite.isNotBlank() && (p == null || !p.disponible)) {
                    lecture = Previsions.Lecture(erreur = "Passerelle Home Assistant indisponible")
                } else if (m != null && m.entite.isNotBlank() && p != null) {
                    val etat = p.requete("GET", "/api/states/${m.entite}", null, 10)
                    val actuel = if (etat.ok) Previsions.lireActuel(etat.corps) else null
                    // Fonctions de l'entité lues dans son état : une deuxième entité n'a pas été lue par l'accueil.
                    val fonctions = if (etat.ok) try {
                        JSONObject(etat.corps).optJSONObject("attributes")?.optLong("supported_features", m.fonctions) ?: m.fonctions
                    } catch (_: Exception) { m.fonctions } else m.fonctions
                    val soleil = p.requete("GET", "/api/states/sun.sun", null, 10).let { if (it.ok) Previsions.lireSoleil(it.corps) else null }
                    var refus: PasserelleHa.Reponse? = null
                    fun service(type: String): List<Previsions.Prevision> {
                        val r = p.requete("POST", Previsions.CHEMIN, Previsions.corps(m.entite, type), 15)
                        Log.i(TAG_METEO, "weather.get_forecasts ${m.entite} ($type, fonctions $fonctions) : code ${r.code}, ${r.corps.take(300)}")
                        if (!r.ok && refus == null) refus = r
                        return if (r.ok) Previsions.lire(r.corps, m.entite) else emptyList()
                    }
                    var horaire = if (Previsions.horaire(fonctions)) service(Previsions.HORAIRE) else emptyList()
                    var typeJours = Previsions.typeJours(fonctions) ?: Previsions.PAR_JOUR
                    var jours = if (Previsions.typeJours(fonctions) != null) service(typeJours) else emptyList()
                    if (jours.isEmpty() && typeJours == Previsions.PAR_JOUR && fonctions and 4L != 0L && refus == null) {
                        typeJours = Previsions.DEUX_PAR_JOUR
                        jours = service(typeJours)
                    }
                    // Repli : les intégrations qui gardent encore l'attribut forecast (horaire ou par jour).
                    if (horaire.isEmpty() && jours.isEmpty() && etat.ok) {
                        val ancienne = Previsions.lireAttribut(etat.corps)
                        if (ancienne.size >= 2 && ancienne[1].instant - ancienne[0].instant <= 2 * 3_600_000L) horaire = ancienne
                        else jours = ancienne
                    }
                    val r = refus
                    lecture = Previsions.Lecture(
                        horaire, jours, typeJours, actuel, soleil,
                        erreur = when {
                            r != null && horaire.isEmpty() && jours.isEmpty() -> "Prévisions refusées par la passerelle (code ${r.code})"
                            r == null && horaire.isEmpty() && jours.isEmpty() -> "Home Assistant n'a rendu aucune prévision"
                            else -> ""
                        },
                        code = r?.code ?: 200, reponse = r?.corps?.take(400) ?: "",
                    )
                }
            } catch (e: Exception) {
                Log.w(TAG_METEO, "Prévisions illisibles", e)
                lecture = Previsions.Lecture(erreur = "Prévisions illisibles (${e.javaClass.simpleName})")
            }
            val fin = lecture
            principal.post { suite(fin) }
        }
    }

    /**
     * Prévisions horaires seules (0.18.1), pour la phrase « Pluie vers 17 h. » de l'accueil : rendues sur le
     * fil principal avec le code de la passerelle (403 tant que le serveur refuse weather.get_forecasts).
     */
    fun horaire(suite: (List<Previsions.Prevision>, Int) -> Unit) {
        lancerOuRendre({ suite(emptyList(), 0) }) {
            var liste = emptyList<Previsions.Prevision>()
            var code = 0
            try {
                val m = Etat.courant.meteo
                val p = passerelle()
                if (m != null && m.entite.isNotBlank() && p != null && p.disponible && Previsions.horaire(m.fonctions)) {
                    val r = p.requete("POST", Previsions.CHEMIN, Previsions.corps(m.entite, Previsions.HORAIRE), 15)
                    code = r.code
                    if (r.ok) liste = Previsions.lire(r.corps, m.entite)
                    else Log.i(TAG_METEO, "prévisions horaires de l'accueil : code ${r.code}, ${r.corps.take(200)}")
                }
            } catch (e: Exception) {
                Log.w(TAG_METEO, "Prévisions horaires illisibles", e)
            }
            val l = liste
            val c = code
            principal.post { suite(l, c) }
        }
    }

    /**
     * Lumières allumées et lecteurs qui jouent, en une seule requête. Le modèle rend du JSON, la pièce
     * de chaque appareil sert à écarter celles de l'occupant protégé même quand son nom ne le dit pas.
     */
    private fun lireMaison() {
        val p = passerelle() ?: return
        if (!p.disponible) return
        val modele = """
            {%- set ns = namespace(l=[], m=[]) -%}
            {%- for s in states.light if s.state == 'on' -%}
            {%- set ns.l = ns.l + [{'id': s.entity_id, 'nom': s.name, 'etat': s.state, 'zone': area_id(s.entity_id) or '', 'piece': area_name(s.entity_id) or '', 'membres': s.attributes.entity_id or []}] -%}
            {%- endfor -%}
            {%- for s in states.media_player if s.state in ['playing', 'paused'] -%}
            {%- set ns.m = ns.m + [{'id': s.entity_id, 'nom': s.name, 'etat': s.state, 'zone': area_id(s.entity_id) or '', 'piece': area_name(s.entity_id) or '', 'titre': s.attributes.media_title or '', 'artiste': s.attributes.media_artist or '', 'membres': s.attributes.group_members or [], 'image': s.attributes.entity_picture or '', 'position': s.attributes.media_position or 0, 'duree': s.attributes.media_duration or 0, 'maj': as_timestamp(s.attributes.media_position_updated_at, 0) if s.attributes.media_position_updated_at else 0, 'volume': s.attributes.volume_level or 0, 'suivant': s.attributes.media_next_title or ''}] -%}
            {%- endfor -%}
            {{ {'lumieres': ns.l, 'medias': ns.m} | tojson }}
        """.trimIndent()
        val r = p.requete("POST", "/api/template", JSONObject().put("template", modele))
        if (!r.ok) return
        val j = JSONObject(r.corps)
        fun permis(o: JSONObject): Boolean =
            !Securite.protege(o.optString("id")) && !Securite.protege(o.optString("nom")) &&
                !Securite.zoneProtegee(o.optString("zone")) && !Securite.zoneProtegee(o.optString("piece"))
        // Lampes allumées (0.17.0) : un groupe n'est pas compté avec ses lampes, rien de l'occupant protégé sauf
        // ses lumières quand c'est lui qui est reconnu (Appareils.lumieresAllumees, règle 3).
        val lumieres = j.optJSONArray("lumieres") ?: JSONArray()
        val lues = (0 until lumieres.length()).mapNotNull { lumieres.optJSONObject(it)?.let(Appareils::lire) }
        val allumees = Appareils.lumieresAllumees(lues, Etat.courant.quiParle())
        val n = allumees.size
        val pieces = Appareils.piecesAllumees(allumees)
        val m = j.optJSONArray("medias") ?: JSONArray()
        val lecteurs = ArrayList<Lecteur>()
        val cartes = ArrayList<Etat.Lecteur>()
        val maintenant = System.currentTimeMillis()
        for (i in 0 until m.length()) {
            val o = m.optJSONObject(i) ?: continue
            if (!permis(o)) continue
            val id = o.optString("id")
            val etat = o.optString("etat", "playing")
            val membres = o.optJSONArray("membres")?.let { a -> (0 until a.length()).map { a.optString(it) }.toSet() } ?: emptySet()
            if (etat == "playing") {
                vusJouer[id] = maintenant
                lecteurs.add(Lecteur(id, o.optString("nom"), o.optString("titre"), o.optString("artiste"), membres))
            }
            // Une pause récente garde sa carte 10 min : on doit pouvoir relancer la lecture.
            val recent = etat == "playing" || maintenant - (vusJouer[id] ?: 0L) < PAUSE_GARDEE_MS
            if (recent && (o.optString("titre").isNotBlank() || etat == "playing")) {
                cartes.add(
                    Etat.Lecteur(
                        id, o.optString("nom"), etat, o.optString("titre"), o.optString("artiste"), o.optString("image"),
                        o.optDouble("position", 0.0), o.optDouble("duree", 0.0), (o.optDouble("maj", 0.0) * 1000).toLong(),
                        o.optDouble("volume", 0.0), membres, o.optString("suivant"),
                    )
                )
            }
        }
        val medias = regrouperLecteurs(lecteurs)
        Etat.modifier { it.copy(maison = Etat.Maison(n, medias, pieces), lecteurs = cartes) }
    }

    // ------------------------------------------------------------ musique (0.16.2)

    /**
     * Commande de la carte En cours sur un lecteur. Securite.kt d'abord (pas de son au salon la nuit),
     * puis la passerelle. Le résultat s'affiche en message bref sous l'orbe s'il y a un problème.
     */
    fun commandeMedia(entite: String, service: String, donnees: JSONObject) {
        lancer {
            garder {
                val p = passerelle()
                if (p == null || !p.disponible) {
                    bref("Passerelle Home Assistant indisponible, commande non envoyée")
                    return@garder
                }
                // Volume plafonné à 50 % (Securite.VOLUME_MAX) avant la vérification et l'envoi, d'où qu'il vienne,
                // volume_up compris (changé en volume_set au-dessus du volume lu).
                val (s0, d0) = Securite.monterSansDepasser("media_player.$service", JSONObject(donnees.toString()).put("entity_id", entite))
                var nom = s0.removePrefix("media_player.")
                var corps = Securite.plafonner(s0, d0)
                var refus = Securite.verifier(JSONObject(corps.toString()).put("service", "media_player.$nom"))
                // Baisser le volume reste permis la nuit par volume_down, que la règle tient pour silencieux.
                if (refus != null && nom == "volume_set" && donnees.optBoolean("baisse")) {
                    nom = "volume_down"
                    corps = JSONObject().put("entity_id", entite)
                    refus = Securite.verifier(JSONObject(corps.toString()).put("service", "media_player.$nom"))
                }
                corps.remove("baisse")
                if (refus != null) {
                    bref("Je ne le fais pas : $refus")
                    return@garder
                }
                val r = p.requete("POST", "/api/services/media_player/$nom", corps, 10)
                if (!r.ok) bref(if (r.code == 403) "Refusé par la passerelle : ${r.corps.take(120)}" else "Home Assistant n'a pas répondu (${r.code})")
                planif.schedule({ garder { lireMaison() } }, 800, TimeUnit.MILLISECONDS)
                // Volume relu avec le plan : la valeur affichée sur l'accueil ne revient pas en arrière.
                relireLumieres(1000)
            }
        }
    }

    private fun bref(message: String) {
        Etat.modifier { it.copy(bref = message, brefLe = SystemClock.elapsedRealtime()) }
    }

    /**
     * Commande des écrans Musique et Maison (0.17.0) : [service] « domaine.service », [corps] de l'appel.
     * Securite.kt vérifie d'abord [verification] (toutes les cibles, la personne qui parle pour la
     * règle 3), puis la passerelle refait la même vérification. Relecture de la maison juste après.
     */
    fun commande(service: String, corps: JSONObject, verification: JSONObject, personne: String = "") {
        lancer {
            garder {
                // Volume plafonné à 50 % (Securite.VOLUME_MAX), même si l'écran l'a déjà fait, volume_up compris.
                val (serviceEnvoye, corpsMonte) = Securite.monterSansDepasser(service, corps)
                val envoye = Securite.plafonner(serviceEnvoye, corpsMonte)
                val refus = Securite.verifier(if (serviceEnvoye != service) JSONObject(envoye.toString()).put("service", serviceEnvoye) else verification, personne = personne)
                if (refus != null) {
                    bref("Je ne le fais pas : $refus")
                    return@garder
                }
                val p = passerelle()
                if (p == null || !p.disponible) {
                    bref("Passerelle Home Assistant indisponible, commande non envoyée")
                    return@garder
                }
                val (domaine, nom) = serviceEnvoye.split(".", limit = 2).let { if (it.size == 2) it[0] to it[1] else return@garder }
                val r = p.requete("POST", "/api/services/$domaine/$nom", envoye, 10, personne)
                if (!r.ok) bref(if (r.code == 403) "Refusé par la passerelle : ${r.corps.take(120)}" else "Home Assistant n'a pas répondu (${r.code})")
                planif.schedule({ garder { lireMaison() } }, 800, TimeUnit.MILLISECONDS)
                if (suivreEnceintes) planif.schedule({ garder { lireEnceintes() } }, 1200, TimeUnit.MILLISECONDS)
                if (suivreAppareils) planif.schedule({ garder { lireAppareils() } }, 1000, TimeUnit.MILLISECONDS)
                relireLumieres(1000)
            }
        }
    }

    // ------------------------------------------------------------ plan 3D de l'accueil (0.18.0, 0.18.1)

    @Volatile private var suivreLumieres = false
    private val tourLumieres = AtomicLong(0)
    /**
     * Fil à part pour les lumières du plan (0.18.1, revue de faisabilité) : une pochette qui se télécharge
     * ou une relecture lente sur le fil de Maison ne retarde pas l'état des lampes.
     */
    private val planifLumieres = Executors.newSingleThreadScheduledExecutor()
    /** Champs fixes des lumières (nom, pièce, membres, modes), relus au départ puis toutes les 10 min. */
    private val fixes = ConcurrentHashMap<String, Appareils.Appareil>()
    @Volatile private var fixesLe = 0L

    /**
     * Accueil de la tablette vivant : les lumières sont relues tout de suite, puis toutes les 5 s, par un
     * modèle réduit à states.light (état, luminosité, couleur). Arrêt en AOD, écran noir ou caché.
     */
    fun suivreLumieres(oui: Boolean) {
        suivreLumieres = oui
        val tour = tourLumieres.incrementAndGet()
        if (oui && !ferme) {
            try {
                planifLumieres.execute { boucleLumieres(tour) }
            } catch (_: java.util.concurrent.RejectedExecutionException) {
            }
        }
    }

    private fun boucleLumieres(tour: Long) {
        if (ferme || !suivreLumieres || tour != tourLumieres.get()) return
        garder { lireLumieres() }
        try {
            planifLumieres.schedule({ boucleLumieres(tour) }, PERIODE_LUMIERES_S, TimeUnit.SECONDS)
        } catch (_: Exception) {
        }
    }

    /** Relecture des lumières sans attendre la boucle (après une commande), sur le fil des lumières. */
    private fun relireLumieres(delaiMs: Long) {
        if (!suivreLumieres || ferme) return
        try {
            planifLumieres.schedule({ garder { lireLumieres() } }, delaiMs, TimeUnit.MILLISECONDS)
        } catch (_: Exception) {
        }
    }

    private fun lireLumieres() {
        val p = passerelle() ?: return
        if (!p.disponible) return
        if (fixes.isEmpty() || SystemClock.elapsedRealtime() - fixesLe > PERIODE_FIXES_MS) lireLumieresFixes(p)
        // 0.24.0 : la télé et les enceintes viennent avec, état et volume, pour le plan et le volume de l'accueil.
        val modele = """
            {%- set ns = namespace(a=[], m=[]) -%}
            {%- for s in states.light -%}
            {%- set ns.a = ns.a + [{'id': s.entity_id, 'etat': s.state, 'lum': s.attributes.brightness if s.state == 'on' else none, 'rgb': s.attributes.rgb_color if s.state == 'on' else none, 'kelvin': s.attributes.color_temp_kelvin if s.state == 'on' else none}] -%}
            {%- endfor -%}
            {%- for s in states.media_player -%}
            {%- set ns.m = ns.m + [{'id': s.entity_id, 'nom': s.name, 'etat': s.state, 'zone': area_id(s.entity_id) or '', 'piece': area_name(s.entity_id) or '', 'volume': s.attributes.volume_level if s.attributes.volume_level is defined else none}] -%}
            {%- endfor -%}
            {{ {'lumieres': ns.a, 'medias': ns.m} | tojson }}
        """.trimIndent()
        val r = p.requete("POST", "/api/template", JSONObject().put("template", modele))
        if (!r.ok) return
        val j = JSONObject(r.corps)
        val a = j.optJSONArray("lumieres") ?: JSONArray()
        val lumieres = (0 until a.length()).mapNotNull { i ->
            val o = a.optJSONObject(i) ?: return@mapNotNull null
            val e = Appareils.lire(o) ?: return@mapNotNull null
            val f = fixes[e.id]
            if (f == null) e else f.copy(etat = e.etat, luminosite = e.luminosite, rgb = e.rgb, kelvin = e.kelvin)
        }
        val m = j.optJSONArray("medias") ?: JSONArray()
        val medias = (0 until m.length()).mapNotNull { i -> m.optJSONObject(i)?.let(Appareils::lire) }
        Etat.modifier { it.copy(lumieres = lumieres, mediasPlan = medias) }
    }

    /** Champs qui ne changent pas d'une lecture à l'autre : nom, pièce, membres d'un groupe, modes de couleur, bornes du blanc (0.27.0). */
    private fun lireLumieresFixes(p: PasserelleHa) {
        val modele = """
            {%- set ns = namespace(a=[]) -%}
            {%- for s in states.light -%}
            {%- set ns.a = ns.a + [{'id': s.entity_id, 'nom': s.name, 'etat': s.state, 'zone': area_id(s.entity_id) or '', 'piece': area_name(s.entity_id) or '', 'modes': s.attributes.supported_color_modes or [], 'membres': s.attributes.entity_id or [], 'kmin': s.attributes.min_color_temp_kelvin or 0, 'kmax': s.attributes.max_color_temp_kelvin or 0}] -%}
            {%- endfor -%}
            {{ ns.a | tojson }}
        """.trimIndent()
        val r = p.requete("POST", "/api/template", JSONObject().put("template", modele))
        if (!r.ok) return
        val a = JSONArray(r.corps)
        for (i in 0 until a.length()) a.optJSONObject(i)?.let(Appareils::lire)?.let { fixes[it.id] = it }
        fixesLe = SystemClock.elapsedRealtime()
    }

    // ------------------------------------------------------------ écran Maison connectée (0.17.0)

    @Volatile private var suivreAppareils = false
    private val tourAppareils = AtomicLong(0)

    /** Écran Maison ouvert : les appareils sont relus tout de suite, puis toutes les 3 s. */
    fun suivreAppareils(oui: Boolean) {
        suivreAppareils = oui
        val tour = tourAppareils.incrementAndGet()
        if (oui) lancer { boucleAppareils(tour) }
    }

    private fun boucleAppareils(tour: Long) {
        if (ferme || !suivreAppareils || tour != tourAppareils.get()) return
        garder { lireAppareils() }
        try {
            planif.schedule({ boucleAppareils(tour) }, 3, TimeUnit.SECONDS)
        } catch (_: Exception) {
        }
    }

    /**
     * Lumières, lecteurs, aspirateur, ventilateurs, volets et chauffage, avec leur pièce et ce qu'on peut
     * régler. Le filtre de l'occupant protégé est fait à l'affichage (Appareils.montres), avec la personne reconnue.
     */
    private fun lireAppareils() {
        val p = passerelle() ?: return
        if (!p.disponible) return
        val modele = """
            {%- set ns = namespace(a=[]) -%}
            {%- for s in states if s.domain in ['light', 'media_player', 'vacuum', 'fan', 'cover', 'climate'] -%}
            {%- set ns.a = ns.a + [{'id': s.entity_id, 'nom': s.name, 'etat': s.state, 'zone': area_id(s.entity_id) or '', 'piece': area_name(s.entity_id) or '', 'lum': s.attributes.brightness if s.domain == 'light' and s.state == 'on' else none, 'modes': s.attributes.supported_color_modes or [], 'membres': (s.attributes.entity_id or []) if s.domain == 'light' else [], 'volume': s.attributes.volume_level if s.domain == 'media_player' and s.attributes.volume_level is defined else none, 'sources': (s.attributes.source_list or []) if s.domain == 'media_player' else [], 'source': s.attributes.source or '', 'classe': s.attributes.device_class or '', 'kmin': s.attributes.min_color_temp_kelvin or 0, 'kmax': s.attributes.max_color_temp_kelvin or 0, 'rgb': s.attributes.rgb_color if s.domain == 'light' and s.state == 'on' else none, 'kelvin': s.attributes.color_temp_kelvin if s.domain == 'light' and s.state == 'on' else none}] -%}
            {%- endfor -%}
            {{ ns.a | tojson }}
        """.trimIndent()
        val r = p.requete("POST", "/api/template", JSONObject().put("template", modele))
        if (!r.ok) return
        val a = JSONArray(r.corps)
        val appareils = (0 until a.length()).mapNotNull { a.optJSONObject(it)?.let(Appareils::lire) }
        Etat.modifier { it.copy(appareils = appareils, lumieres = appareils.filter { l -> l.domaine == "light" }) }
    }

    // ------------------------------------------------------------ écran Musique (0.17.0)

    @Volatile private var suivreEnceintes = false
    private val tourEnceintes = AtomicLong(0)

    /** Écran Musique ouvert : les trois enceintes sont relues tout de suite, puis toutes les 3 s. */
    fun suivreEnceintes(oui: Boolean) {
        suivreEnceintes = oui
        val tour = tourEnceintes.incrementAndGet()
        if (oui) lancer { boucleEnceintes(tour) }
    }

    private fun boucleEnceintes(tour: Long) {
        if (ferme || !suivreEnceintes || tour != tourEnceintes.get()) return
        garder { lireEnceintes() }
        try {
            planif.schedule({ boucleEnceintes(tour) }, 3, TimeUnit.SECONDS)
        } catch (_: Exception) {
        }
    }

    /** État, volume, groupe et regroupement possible des enceintes de la sortie du son. */
    private fun lireEnceintes() {
        val p = passerelle() ?: return
        if (!p.disponible) return
        val ids = SortieSon.ENCEINTES.joinToString(", ") { "'${it.first}'" }
        val modele = """
            {%- set ns = namespace(e=[]) -%}
            {%- for s in states.media_player if s.entity_id in [$ids] -%}
            {%- set ns.e = ns.e + [{'id': s.entity_id, 'nom': s.name, 'etat': s.state, 'volume': s.attributes.volume_level or 0, 'membres': s.attributes.group_members or [], 'fonctions': s.attributes.supported_features or 0}] -%}
            {%- endfor -%}
            {{ ns.e | tojson }}
        """.trimIndent()
        val r = p.requete("POST", "/api/template", JSONObject().put("template", modele))
        if (!r.ok) return
        val a = JSONArray(r.corps)
        val lues = (0 until a.length()).mapNotNull { a.optJSONObject(it) }.associateBy { it.optString("id") }
        // Dans l'ordre de l'écran (Salon, Cuisine, Bureau), avec leur nom court.
        val enceintes = SortieSon.ENCEINTES.mapNotNull { (id, nom) ->
            val o = lues[id] ?: return@mapNotNull null
            val membres = o.optJSONArray("membres")?.let { m -> (0 until m.length()).map { m.optString(it) }.toSet() } ?: emptySet()
            SortieSon.Enceinte(id, nom, o.optString("etat"), o.optDouble("volume", 0.0), membres, SortieSon.regroupable(o.optLong("fonctions", 0L)))
        }
        Etat.modifier { it.copy(enceintes = enceintes) }
    }

    private val pochettes = object : LruCache<String, Pochette>(12) {}
    private val principal = Handler(Looper.getMainLooper())
    private val web by lazy {
        okhttp3.OkHttpClient.Builder().connectTimeout(5, TimeUnit.SECONDS).readTimeout(8, TimeUnit.SECONDS).build()
    }

    /** Pochette décodée et sa couleur dominante. */
    class Pochette(val image: Bitmap, val teinte: Int)

    /**
     * Pochette d'un lecteur, rendue sur le fil principal (null si illisible). Une adresse https publique
     * (Spotify) est téléchargée directement, un chemin /api/media_player_proxy/... est demandé à la
     * passerelle, qui le rend en base64. Cache en mémoire par adresse.
     */
    fun pochette(adresse: String, suite: (Pochette?) -> Unit) {
        pochettes.get(adresse)?.let { suite(it); return }
        lancer {
            var resultat: Pochette? = null
            try {
                val octets: ByteArray? = when {
                    adresse.startsWith("https://") -> web.newCall(okhttp3.Request.Builder().url(adresse).build()).execute().use { r ->
                        if (r.isSuccessful) r.body?.bytes() else null
                    }
                    adresse.startsWith("/") -> passerelle()?.takeIf { it.disponible }?.requete("GET", adresse, null, 10)?.let { r ->
                        if (r.ok && r.base64.isNotEmpty()) android.util.Base64.decode(r.base64, android.util.Base64.DEFAULT) else null
                    }
                    else -> null
                }
                if (octets != null && octets.size < 8_000_000) resultat = decoder(octets)
            } catch (e: Exception) {
                Log.w(TAG, "Pochette illisible", e)
            }
            resultat?.let { pochettes.put(adresse, it) }
            principal.post { suite(resultat) }
        }
    }

    private fun decoder(octets: ByteArray): Pochette? {
        val bornes = BitmapFactory.Options().apply { inJustDecodeBounds = true }
        BitmapFactory.decodeByteArray(octets, 0, octets.size, bornes)
        var echantillon = 1
        while (bornes.outWidth / (echantillon * 2) >= 256 && bornes.outHeight / (echantillon * 2) >= 256) echantillon *= 2
        val b = BitmapFactory.decodeByteArray(octets, 0, octets.size, BitmapFactory.Options().apply { inSampleSize = echantillon })
            ?: return null
        return Pochette(b, teinteDominante(b))
    }

    // ------------------------------------------------------------ cartes des commandes

    /** Une commande vient de se terminer : sa carte de réponse, une carte par action, puis la relecture. */
    /**
     * Une commande vient de se terminer (0.16.3) : une seule carte, et seulement si quelque chose a
     * vraiment été fait sur la maison (ni essai, ni refus, ni action écartée). Elle remplace la
     * précédente. La réponse, elle, s'affiche sous l'orbe au fil de la voix, sans carte.
     */
    fun nouvelleCommande(e: Etat.EntreeHistorique) {
        if (ferme || e.essai) return
        val faites = e.fait.mapNotNull { lireLigne(it) }.filter { !it.ecartee && !it.refusee && !it.essai }
            .filter { it.entites.none(Securite::protege) }
        if (faites.isEmpty()) return
        val maintenant = SystemClock.elapsedRealtime()
        val voie = voie(e.comprisPar, e.detailVoie, e.reponse)
        val dispo = passerelle()?.disponible == true
        val relire = faites.filter { it.entites.isNotEmpty() }
        val id = identifiants.incrementAndGet()
        val carte = Etat.Carte(
            id, false, nomCarte(faites), faites.map { verbe(it) }.distinct().joinToString(", "),
            faites.firstNotNullOfOrNull { pastille(it.donnees) }, "", "", voie, false, dureeLisible(e.duree),
            if (dispo && relire.isNotEmpty()) "attente" else "", maintenant, faites.flatMap { it.entites },
            effets = effetsLumieres(faites),
        )
        Etat.modifier { s -> s.copy(cartes = listOf(carte)) }
        if (carte.statut == "attente") planif.schedule({ garder { confirmer(id, relire, 1) } }, 1500, TimeUnit.MILLISECONDS)
        // Accueil vivant (0.18.0) : l'état des lumières touchées arrive sur le plan 3D sans attendre la boucle.
        if (carte.effets.isNotEmpty()) relireLumieres(1200)
    }

    private fun nomCarte(actions: List<ActionLue>): String {
        val noms = actions.map { nomDe(it) }.distinct()
        return if (noms.size <= 1) noms.joinToString("") else noms.dropLast(1).joinToString(", ") + " et " + noms.last()
    }

    /** Relit chaque entité visée et compare à l'état attendu, une seconde fois 2,5 s plus tard. */
    private fun confirmer(id: Long, actions: List<ActionLue>, essai: Int) {
        val p = passerelle()
        var toutBon = p != null && p.disponible
        if (toutBon) {
            boucle@ for (a in actions) for (ent in a.entites) {
                val r = p!!.requete("GET", "/api/states/$ent", null, 8)
                if (!r.ok) {
                    toutBon = false
                    break@boucle
                }
                val o = JSONObject(r.corps)
                val attr = o.optJSONObject("attributes") ?: JSONObject()
                attr.optString("friendly_name").takeIf { it.isNotBlank() && !Securite.protege(it) }?.let { noms[ent] = it }
                if (!conforme(a, o.optString("state"), attr)) toutBon = false
            }
        }
        if (!toutBon && essai < 2) {
            planif.schedule({ garder { confirmer(id, actions, essai + 1) } }, 2500, TimeUnit.MILLISECONDS)
            return
        }
        val nom = nomCarte(actions)
        Etat.modifier { s ->
            s.copy(cartes = s.cartes.map { c ->
                if (c.id == id) c.copy(statut = if (toutBon) "confirme" else "sans_reponse", nom = nom) else c
            })
        }
    }

    private fun nomDe(a: ActionLue): String =
        // Rien de l'occupant protégé à l'écran, même dans la carte d'un refus de sécurité.
        if (a.entites.any(Securite::protege) || Securite.protege(a.donnees["nom"] ?: "")) "Appareil protégé"
        else if (a.entites.isEmpty()) a.donnees["nom"]?.takeIf { it.isNotBlank() }?.let(::nomBrut) ?: "Maison"
        else a.entites.joinToString(", ") { noms[it] ?: nomBrut(it) }

    override fun close() {
        ferme = true
        planif.shutdownNow()
        planifLumieres.shutdownNow()
    }

    /** Lecteur qui joue : identifiant, nom, morceau, et membres s'il est un groupe (Enceintes). */
    class Lecteur(val id: String, val nom: String, val titre: String, val artiste: String, val membres: Set<String> = emptySet())

    /** Action relue dans une ligne « Fait » de l'historique. */
    class ActionLue(
        val service: String,
        val entites: List<String>,
        val donnees: Map<String, String>,
        val essai: Boolean,
        val refusee: Boolean,
        val ecartee: Boolean,
    )

    companion object {
        private const val TAG = "JarvisMaison"
        private const val TAG_METEO = "JarvisMeteo"
        /** Lumières du plan 3D de l'accueil relues toutes les 5 s en régime vivant (0.18.1, 4 s en 0.18.0). */
        const val PERIODE_LUMIERES_S = 5L
        /** Champs fixes des lumières (nom, pièce, membres) relus toutes les 10 min. */
        const val PERIODE_FIXES_MS = 10 * 60_000L
        /** Durée pendant laquelle un lecteur mis en pause garde sa carte En cours. */
        const val PAUSE_GARDEE_MS = 10 * 60_000L

        /**
         * Couleur dominante d'une pochette, calcul simple : histogramme des teintes sur une vignette
         * 24 x 24, chaque pixel pesé par sa saturation et sa luminosité (les gris ne comptent presque pas).
         */
        fun teinteDominante(b: Bitmap): Int {
            val v = Bitmap.createScaledBitmap(b, 24, 24, true)
            val poids = DoubleArray(36)
            val hsv = FloatArray(3)
            for (x in 0 until 24) for (y in 0 until 24) {
                Color.colorToHSV(v.getPixel(x, y), hsv)
                poids[(hsv[0] / 10f).toInt().coerceIn(0, 35)] += (hsv[1] * hsv[2]).toDouble()
            }
            if (v !== b) v.recycle()
            val meilleur = poids.indices.maxByOrNull { poids[it] } ?: return Couleur.BLEU
            if (poids[meilleur] < 1.0) return Couleur.BLEU
            return Color.HSVToColor(floatArrayOf(meilleur * 10f + 5f, 0.55f, 0.95f))
        }
        /** Une seule carte d'action à la fois (0.16.3), qui remplace la précédente. */
        const val MAX_CARTES = 1

        /**
         * Ligne « Fait » telle que l'écrivent le moteur local (MoteurLocal.resumeAction) et le serveur
         * (resume_action) : « light.turn_on light.salon (brightness_pct=40) », suivie au besoin de
         * « (non exécuté, essai) », « (refusé...) » ou « (écartée) ». Les lignes d'Assist sont
         * « ha <type> <entité ou nom> ». Null si la ligne ne ressemble à aucune action.
         */
        fun lireLigne(brute: String): ActionLue? {
            var l = brute.trim()
            var essai = false
            var refusee = false
            var ecartee = false
            while (true) {
                when {
                    l.endsWith("(non exécuté, essai)") -> { essai = true; l = l.removeSuffix("(non exécuté, essai)").trim() }
                    l.endsWith("(écartée)") -> { ecartee = true; l = l.removeSuffix("(écartée)").trim() }
                    Regex("""\(refusé[^()]*\)$""").containsMatchIn(l) -> {
                        refusee = true
                        l = l.replace(Regex("""\s*\(refusé[^()]*\)$"""), "").trim()
                    }
                    else -> break
                }
            }
            if (l.startsWith("ha ")) {
                val morceaux = l.split(" ").filter { it.isNotBlank() }
                val cible = morceaux.drop(2).joinToString(" ")
                val entites = if (Regex("""^[a-z_]+\.[a-z0-9_]+$""").matches(cible)) listOf(cible) else emptyList()
                if (cible.isNotEmpty() && Securite.protege(cible)) return null
                return ActionLue("assist.${morceaux.getOrNull(1) ?: ""}", entites, mapOf("nom" to cible), essai, refusee, ecartee)
            }
            var reglages = ""
            val ouverture = l.indexOf(" (")
            if (ouverture > 0 && l.endsWith(")")) {
                reglages = l.substring(ouverture + 2, l.length - 1)
                l = l.substring(0, ouverture)
            }
            val morceaux = l.split(" ").filter { it.isNotBlank() }
            val service = morceaux.firstOrNull() ?: return null
            if (!Regex("""^[a-z_]+\.[a-z_]+$""").matches(service)) return null
            val entites = morceaux.drop(1).filter { Regex("""^[a-z_]+\.[a-z0-9_]+$""").matches(it) }
            // Les valeurs JSON ([255,0,0]) n'ont pas d'espace : la virgule suivie d'une espace sépare.
            val donnees = LinkedHashMap<String, String>()
            if (reglages.isNotEmpty()) {
                for (r in reglages.split(", ")) {
                    val i = r.indexOf('=')
                    if (i > 0) donnees[r.substring(0, i).trim()] = r.substring(i + 1).trim()
                }
            }
            return ActionLue(service, entites, donnees, essai, refusee, ecartee)
        }

        /**
         * Une ligne par morceau (0.16.1) : un groupe Enceintes et ses enceintes jouent le même titre, qui
         * apparaissait deux fois. Les lecteurs au même titre et au même artiste sont réunis
         * (« sur Salon et Cuisine »), et un groupe qui contient tous les autres est seul
         * nommé. Sans titre connu, chaque lecteur garde sa ligne.
         */
        fun regrouperLecteurs(lecteurs: List<Lecteur>): List<String> {
            val sortie = ArrayList<String>()
            val paquets = LinkedHashMap<String, MutableList<Lecteur>>()
            for (l in lecteurs) {
                val cle = if (l.titre.isBlank()) "lecteur:" + l.id else l.titre.trim().lowercase(Locale.FRANCE) + "|" + l.artiste.trim().lowercase(Locale.FRANCE)
                paquets.getOrPut(cle) { ArrayList() }.add(l)
            }
            for (p in paquets.values) {
                val premier = p[0]
                val quoi = when {
                    premier.titre.isNotBlank() && premier.artiste.isNotBlank() -> "${premier.titre}, ${premier.artiste}"
                    premier.titre.isNotBlank() -> premier.titre
                    else -> "lecture en cours"
                }
                // Le groupe qui contient tous les autres lecteurs du paquet les représente seul.
                val groupe = p.firstOrNull { g -> p.all { it === g || it.id in g.membres } }
                val noms = if (groupe != null && p.size > 1) listOf(groupe.nom) else p.map { it.nom }.distinct()
                val liste = if (noms.size <= 1) noms.joinToString("") else noms.dropLast(1).joinToString(", ") + " et " + noms.last()
                sortie.add("$quoi sur $liste")
            }
            return sortie
        }

        /** Voie qui a répondu, d'après « compris par » et son détail (mêmes règles que la carte de réponse). Le nom
         *  de l'assistant, qui figure dans ces textes, est retiré avant les mots-clés : « Assistant » ou « Hal »
         *  ne doivent pas passer pour Home Assistant (cherché, lui, dans le texte entier). */
        fun voie(comprisPar: String, detail: String, reponse: String, nomAssistant: String = ConfigMaison.NOM_ASSISTANT): String {
            val brut = "$comprisPar $detail".trim().lowercase(Locale.FRANCE)
            val t = if (nomAssistant.isBlank()) brut else brut.replace(
                Regex("(?<![\\p{L}\\p{N}])" + Regex.escape(nomAssistant.trim()) + "(?![\\p{L}\\p{N}])", RegexOption.IGNORE_CASE), " ").trim()
            return when {
                "sécurité" in t || reponse.startsWith("Je ne le fais pas") -> "securite"
                "dictionnaire" in t -> "dictionnaire"
                "home assistant" in brut || t.startsWith("ha") || "assist" in t -> "ha"
                "claude" in t || "haiku" in t -> "claude"
                "llm" in t || "gemma" in t || "qwen" in t || "local" in t || "modèle" in t -> "llm"
                else -> "jarvis"
            }
        }

        /** « light.lampe_tv » devient « Lampe tv » quand HA n'a pas encore donné de nom. */
        fun nomBrut(id: String): String =
            id.substringAfter('.').replace('_', ' ').replaceFirstChar { it.titlecase(Locale.FRANCE) }

        private fun pourcent(v: String?): String? =
            v?.toDoubleOrNull()?.let { String.format(Locale.FRANCE, "%.0f %%", it) }

        /**
         * Effet de chaque lumière visée, pour l'aperçu 3D (0.17.5) : « allumer » ou « eteindre » pour un
         * allumage ou une extinction simples, « regler » quand la luminosité ou la couleur change (la lampe
         * pouvait déjà être allumée), « basculer » pour un toggle, tranché ensuite avec l'état lu dans HA.
         */
        fun effetsLumieres(actions: List<ActionLue>): Map<String, String> {
            val effets = LinkedHashMap<String, String>()
            for (a in actions) {
                val domaine = a.service.substringBefore('.')
                val nom = a.service.substringAfter('.')
                val effet = when {
                    domaine == "light" && nom == "turn_on" ->
                        if (a.donnees.keys.any { it != "transition" && it != "entity_id" }) "regler" else "allumer"
                    domaine == "light" && nom == "turn_off" -> "eteindre"
                    domaine == "light" && nom == "toggle" -> "basculer"
                    domaine == "assist" && nom == "HassTurnOn" -> "allumer"
                    domaine == "assist" && nom == "HassTurnOff" -> "eteindre"
                    domaine == "assist" && nom == "HassLightSet" -> "regler"
                    else -> null
                } ?: continue
                for (e in a.entites) if (e.startsWith("light.")) effets[e] = effet
            }
            return effets
        }

        /** Verbe en français, accordé au féminin pour une lumière. */
        fun verbe(a: ActionLue): String {
            val domaine = a.service.substringBefore('.')
            val nom = a.service.substringAfter('.')
            val f = domaine == "light"
            val d = a.donnees
            return when {
                domaine == "assist" -> "fait par Assist de Home Assistant"
                domaine == "light" && nom == "turn_on" -> when {
                    d["brightness_pct"] != null -> "luminosité ${pourcent(d["brightness_pct"])}"
                    d["brightness"] != null -> "luminosité ${pourcent(d["brightness"]!!.toDoubleOrNull()?.let { (it / 5.55).toString() })}"
                    d.keys.any { it in setOf("color_name", "rgb_color", "hs_color", "xy_color") } -> "couleur"
                    d["color_temp_kelvin"] != null || d["kelvin"] != null || d["color_temp"] != null -> "température de couleur"
                    else -> "allumée"
                }
                nom == "turn_on" && domaine in setOf("script", "automation") -> "lancé"
                nom == "turn_on" && domaine == "scene" -> "scène activée"
                nom == "turn_on" -> if (f) "allumée" else "allumé"
                nom == "turn_off" -> if (f) "éteinte" else "éteint"
                nom == "toggle" -> if (f) "basculée" else "basculé"
                nom == "media_pause" -> "pause"
                nom == "media_play" -> "lecture"
                nom == "media_play_pause" -> "lecture ou pause"
                nom == "media_stop" -> "arrêt"
                nom == "media_next_track" -> "morceau suivant"
                nom == "media_previous_track" -> "morceau précédent"
                nom == "play_media" -> "lecture lancée"
                nom == "volume_set" -> "volume " + (d["volume_level"]?.toDoubleOrNull()?.let { String.format(Locale.FRANCE, "%.0f %%", it * 100) } ?: "réglé")
                nom == "volume_up" -> "volume plus fort"
                nom == "volume_down" -> "volume moins fort"
                nom == "volume_mute" -> if (d["is_volume_muted"] == "false") "son remis" else "son coupé"
                nom == "open_cover" -> "ouvert"
                nom == "close_cover" -> "fermé"
                nom == "stop_cover" -> "arrêté"
                nom == "set_cover_position" -> "position ${pourcent(d["position"]) ?: ""}".trim()
                nom == "set_temperature" -> "consigne " + (d["temperature"] ?: "") + " °C"
                nom == "set_hvac_mode" -> "mode ${d["hvac_mode"] ?: ""}".trim()
                nom == "select_source" -> "source ${d["source"] ?: ""}".trim()
                else -> nom.replace('_', ' ')
            }
        }

        /** État attendu après l'action, ou null quand on ne sait pas le prévoir (on vérifie alors juste la lecture). */
        fun attendu(a: ActionLue): Set<String>? {
            val nom = a.service.substringAfter('.')
            val domaine = a.service.substringBefore('.')
            return when {
                domaine == "script" || domaine == "scene" || domaine == "automation" || domaine == "assist" -> null
                nom == "turn_on" -> setOf("on")
                nom == "turn_off" -> setOf("off")
                nom == "media_pause" -> setOf("paused", "idle", "off", "standby")
                nom == "media_play" || nom == "play_media" -> setOf("playing", "buffering")
                nom == "media_stop" -> setOf("idle", "off", "paused", "standby")
                nom == "open_cover" -> setOf("open", "opening")
                nom == "close_cover" -> setOf("closed", "closing")
                else -> null
            }
        }

        /** L'état relu correspond-il à l'action ? Luminosité et volume vérifiés à quelques points près. */
        fun conforme(a: ActionLue, etat: String, attr: JSONObject): Boolean {
            if (etat.isEmpty() || etat == "unavailable" || etat == "unknown") return false
            attendu(a)?.let { if (etat !in it) return false }
            val d = a.donnees
            d["brightness_pct"]?.toDoubleOrNull()?.let { pct ->
                val b = attr.optDouble("brightness")
                if (!b.isNaN() && kotlin.math.abs(b / 5.55 - pct) > 6) return false
            }
            d["volume_level"]?.toDoubleOrNull()?.let { v ->
                val lu = attr.optDouble("volume_level")
                if (!lu.isNaN() && kotlin.math.abs(lu - v) > 0.06) return false
            }
            return true
        }

        /** Couleur demandée à une lumière, pour la pastille de la carte. */
        fun pastille(d: Map<String, String>): Int? {
            d["rgb_color"]?.let { v ->
                val n = Regex("""\d+""").findAll(v).map { it.value.toInt().coerceIn(0, 255) }.toList()
                if (n.size >= 3) return Color.rgb(n[0], n[1], n[2])
            }
            d["hs_color"]?.let { v ->
                val n = Regex("""[\d.]+""").findAll(v).mapNotNull { it.value.toFloatOrNull() }.toList()
                if (n.size >= 2) return Color.HSVToColor(floatArrayOf(n[0], (n[1] / 100f).coerceIn(0f, 1f), 1f))
            }
            d["color_name"]?.let { return COULEURS[it.lowercase(Locale.ROOT).replace(" ", "")] }
            return null
        }

        // Paresseux : les tests sur la machine chargent cette classe sans les couleurs d'Android.
        private val COULEURS by lazy {
            mapOf(
            "red" to Color.rgb(255, 59, 48), "green" to Color.rgb(52, 199, 89), "blue" to Color.rgb(10, 132, 255),
            "purple" to Color.rgb(175, 82, 222), "violet" to Color.rgb(175, 82, 222), "pink" to Color.rgb(255, 105, 180),
            "orange" to Color.rgb(255, 149, 0), "yellow" to Color.rgb(255, 214, 10), "white" to Color.rgb(245, 245, 245),
            "warmwhite" to Color.rgb(255, 214, 170), "cyan" to Color.rgb(50, 220, 230), "magenta" to Color.rgb(255, 0, 200),
            "turquoise" to Color.rgb(64, 224, 208), "gold" to Color.rgb(255, 200, 60), "indigo" to Color.rgb(88, 86, 214),
            "lime" to Color.rgb(160, 230, 60), "crimson" to Color.rgb(220, 20, 60), "lightblue" to Color.rgb(140, 200, 255),
        )
        }

        fun dureeLisible(brute: String): String {
            if (brute.isBlank()) return ""
            val v = brute.replace(" s", "").trim().replace(',', '.').toDoubleOrNull() ?: return brute
            return String.format(Locale.FRANCE, "%.2f s", v)
        }

        /** États de l'entité weather de Home Assistant, en français. */
        fun meteoEnFrancais(etat: String): String = when (etat) {
            "clear-night" -> "nuit claire"
            "cloudy" -> "nuageux"
            "exceptional" -> "temps exceptionnel"
            "fog" -> "brouillard"
            "hail" -> "grêle"
            "lightning" -> "orage"
            "lightning-rainy" -> "orage et pluie"
            "partlycloudy" -> "éclaircies"
            "pouring" -> "averses"
            "rainy" -> "pluie"
            "snowy" -> "neige"
            "snowy-rainy" -> "neige et pluie"
            "sunny" -> "ensoleillé"
            "windy" -> "venteux"
            "windy-variant" -> "venteux et nuageux"
            else -> etat.replace('-', ' ')
        }
    }
}
