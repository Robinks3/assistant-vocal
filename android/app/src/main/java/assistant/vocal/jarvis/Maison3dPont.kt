package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject

/**
 * Logique pure de la vue 3D de l'appartement (assets/maison3d/vue3d.html, source dans carte/3d/) :
 * traduction des états Home Assistant en appels `window.assistant`, et file d'attente des appels
 * tant que la page n'a pas signalé `pret()`. Sans dépendance Android, testée par Maison3dPontTest.
 */
internal class Maison3dPont(private val executer: (String) -> Unit) {

    var prete = false
        private set
    private val attente = ArrayDeque<String>()

    /** Exécute le script tout de suite si la page est prête, sinon le garde pour plus tard. */
    fun appeler(script: String) {
        if (prete) { executer(script); return }
        attente.addLast(script)
        while (attente.size > ATTENTE_MAX) attente.removeFirst()
    }

    /** La page a fini de construire sa scène : on vide la file dans l'ordre. */
    fun surPret() {
        prete = true
        while (attente.isNotEmpty()) executer(attente.removeFirst())
    }

    /** Page rechargée : les appels en attente visaient l'ancienne page. */
    fun reinitialiser() {
        prete = false
        attente.clear()
    }

    companion object {
        /** Au-delà, les plus anciens appels sont oubliés (seul le dernier état compte). */
        const val ATTENTE_MAX = 64
        const val SCRIPT_ENSEMBLE = "assistant.ensemble()"
        /** Bords de la scène fondus dans le noir (0.17.6), pour l'aperçu de l'écran ambiant. */
        const val SCRIPT_FONDU = "assistant.fondu(true)"
        /** Accueil plein écran (0.24.0) : la page dessine elle-même son fond, aucun bord fondu. */
        const val SCRIPT_SANS_FONDU = "assistant.fondu(false)"
        /** Attributs lus par la page : couleur des lampes, et volume de la télé et des enceintes (page 0.6.0). */
        private val ATTRIBUTS = listOf("brightness", "rgb_color", "color_temp_kelvin", "volume_level")

        /** Ne garde d'un état HA que ce que la page lit : `state`, trois attributs de couleur et le volume. */
        fun etatReduit(etatHA: JSONObject): JSONObject {
            val r = JSONObject().put("state", etatHA.optString("state", "off"))
            val a = etatHA.optJSONObject("attributes") ?: return r
            val ra = JSONObject()
            for (cle in ATTRIBUTS) if (a.has(cle) && !a.isNull(cle)) ra.put(cle, a.get(cle))
            return r.put("attributes", ra)
        }

        /**
         * `assistant.etats([...])` avec les lumières, la télé et les enceintes (0.24.0, page 0.6.0 : télé allumée,
         * ondes des enceintes qui jouent) du tableau brut de `/api/states`.
         */
        fun scriptEtats(etats: JSONArray): String {
            val lumieres = JSONArray()
            for (i in 0 until etats.length()) {
                val e = etats.optJSONObject(i) ?: continue
                val id = e.optString("entity_id")
                if (!id.startsWith("light.") && !id.startsWith("media_player.")) continue
                lumieres.put(etatReduit(e).put("entity_id", id))
            }
            return "assistant.etats($lumieres)"
        }

        fun scriptEtat(entite: String, etatHA: JSONObject): String =
            "assistant.etat(${JSONObject.quote(entite)}, ${etatReduit(etatHA)})"

        fun scriptMontrer(cibles: List<String>): String =
            "assistant.montrer(${JSONArray(cibles)})"

        /** Effets que la page sait jouer (0.17.5), tout autre devient un réglage. */
        private val EFFETS = setOf("allumer", "eteindre", "regler")

        /**
         * `assistant.action({...})` (0.17.5) : pour chaque lumière, l'effet et, s'il est connu, l'état lu
         * dans HA réduit à ce que lit la page. La page joue toute la chorégraphie elle-même.
         */
        fun scriptAction(effets: JSONObject): String {
            val r = JSONObject()
            for (cle in effets.keys()) {
                val o = effets.optJSONObject(cle) ?: JSONObject().put("effet", effets.optString(cle))
                val effet = o.optString("effet").takeIf { it in EFFETS } ?: "regler"
                val sortie = JSONObject().put("effet", effet)
                if (o.has("state")) {
                    val e = etatReduit(o)
                    sortie.put("state", e.getString("state"))
                    e.optJSONObject("attributes")?.let { sortie.put("attributes", it) }
                }
                r.put(cle, sortie)
            }
            return "assistant.action($r)"
        }

        /** `assistant.poser({...})` (0.17.5) : états appliqués sans animation, `{entité: état HA}`. */
        fun scriptPoser(etats: JSONObject): String {
            val r = JSONObject()
            for (cle in etats.keys()) etats.optJSONObject(cle)?.let { r.put(cle, etatReduit(it)) }
            return "assistant.poser($r)"
        }

        // ------------------------------------------------ écran d'accueil (0.18.0, page 3D 0.4.0)

        /** Noms des pièces écrits au sol cachés : seules les pièces allumées sont nommées, par étiquette. */
        const val SCRIPT_NOMS_CACHES = "assistant.nomsAuSol(false)"

        /** Bords fondus sur une largeur [bord] (part de la vue), plus fins que ceux de l'aperçu. */
        fun scriptFondu(bord: Float): String = "assistant.fondu(true, ${nombre(bord)})"

        /** Rotation lente : un tour en [periodeS] secondes, [ips] images par seconde au plus, cadrage × [cadre]. */
        fun scriptRotation(periodeS: Int, ips: Int, cadre: Float): String =
            "assistant.rotation(${periodeS.coerceAtLeast(0)}, ${ips.coerceIn(1, 30)}, ${nombre(cadre)})"

        /**
         * Balancement de l'accueil (0.24.0, page 0.5.2) : la caméra va et vient de ± [amplitudeDeg] autour de
         * [angleDeg], aller et retour en [periodeS] secondes, au lieu du tour complet.
         */
        fun scriptRotation(periodeS: Int, ips: Int, cadre: Float, amplitudeDeg: Float, angleDeg: Float): String =
            "assistant.rotation(${periodeS.coerceAtLeast(0)}, ${ips.coerceIn(1, 30)}, ${nombre(cadre)}, ${nombre(amplitudeDeg)}, ${nombre(angleDeg)})"

        /**
         * Zone de la fenêtre où l'appartement est cadré (0.24.0, page 0.5.0), en fractions, transition en
         * [dureeMs] (sans durée : d'un coup, écran en veille).
         */
        fun scriptDisposition(z: Disposition.Zone, dureeMs: Int): String {
            val o = "{\"x\": ${nombre(z.x)}, \"y\": ${nombre(z.y)}, \"largeur\": ${nombre(z.largeur)}, \"hauteur\": ${nombre(z.hauteur)}" +
                (if (dureeMs > 0) ", \"duree_ms\": $dureeMs" else "") + "}"
            return "assistant.disposition($o)"
        }

        /** Jeu de teintes « couleur » (page 0.5.0) à l'[intensite] voulue : 1 le jour, 0,2 le soir, 0,15 la nuit. */
        fun scriptJeuCouleur(intensite: Float): String =
            "assistant.teintes({\"jeu\": \"couleur\", \"intensite\": ${nombre(intensite.coerceIn(0f, 1f))}})"

        /** Intensité seule, les autres teintes gardées (passage du soir à la nuit). */
        fun scriptIntensite(intensite: Float): String =
            "assistant.teintes({\"intensite\": ${nombre(intensite.coerceIn(0f, 1f))}})"

        /**
         * Régime de l'accueil (0.24.0) : 1 vivant (fond bleu de nuit, flaque, particules, couleurs pleines), 0 en
         * retrait (noir pur, couleurs à 40 %), en [dureeMs]. Sans effet sur une page qui ne le connaît pas encore.
         */
        fun scriptRegime(niveau: Float, dureeMs: Int): String =
            "if (typeof assistant.regime === \"function\") assistant.regime(${nombre(niveau.coerceIn(0f, 1f))}, ${dureeMs.coerceAtLeast(0)})"

        /** Scène atténuée (écoute) ou pleine, en [dureeMs]. */
        fun scriptAttenuer(opacite: Float, dureeMs: Int): String =
            "assistant.attenuer(${nombre(opacite.coerceIn(0f, 1f))}, ${dureeMs.coerceAtLeast(0)})"

        /** Retour animé à la vue de tout l'appartement, puis reprise de la rotation. */
        fun scriptEnsemble(dureeMs: Int): String = "assistant.ensemble(${dureeMs.coerceAtLeast(0)})"

        // ------------------------------------------------ 0.18.1 (page 3D 0.4.1)

        /** Teintes de la palette de l'appli (Palette.plan3d), envoyées au chargement. */
        fun scriptTeintes(teintes: JSONObject): String = "assistant.teintes($teintes)"

        /** Teintes du jeu de couleurs choisi (0.19.0, page 0.4.2) : lumière chaude, poussières, flux, pluie. */
        fun scriptPalette(teintes: JSONObject): String = "assistant.palette($teintes)"

        /** Cadence de repos (images par seconde) de la rotation et des poussières, et plafond pendant une action. */
        fun scriptCadence(ips: Int, action: Int = 30): String = "assistant.cadence(${ips.coerceIn(1, 30)}, ${action.coerceIn(1, 60)})"

        /** Pause : plus aucune image, requestAnimationFrame coupé. */
        fun scriptPause(oui: Boolean): String = "assistant.pause($oui)"

        /** Poussières ambre des pièces allumées (accueil seulement). */
        fun scriptPoussieres(oui: Boolean): String = "assistant.poussieres($oui)"

        /** Maison qui ne répond plus : lumières du plan en gris. */
        fun scriptDesaturer(oui: Boolean): String = "assistant.desaturer($oui)"

        /** Le point ([x], [y]) en pixels CSS de la page tombe-t-il sur l'appartement ? Rend true ou false. */
        fun scriptDansLePlan(x: Float, y: Float): String = "assistant.dansLePlan(${nombre(x)}, ${nombre(y)})"

        // ------------------------------------------------ la maison en grand (0.27.0, page 3D 0.8.0)

        /**
         * Maison en grand ou non : caméra figée, noms au sol de la page cachés, pastilles de [taille] et étiquettes en
         * [police] pixels CSS. Sans effet sur une page qui ne le connaît pas encore.
         */
        fun scriptGrand(actif: Boolean, taille: Float, police: Float): String =
            "if (typeof assistant.grand === \"function\") assistant.grand($actif, ${nombre(taille)}, ${nombre(police)})"

        /** Pièce choisie (null : retour à la maison entière), cadrée en [dureeMs] sous un voile. */
        fun scriptChoisir(piece: String?, dureeMs: Int): String =
            "if (typeof assistant.choisir === \"function\") assistant.choisir(${piece?.let { JSONObject.quote(it) } ?: "null"}, ${dureeMs.coerceAtLeast(0)})"

        /** Étiquettes des pièces de la vue entière : `[{piece, nom, etat, verrou}]`. */
        fun scriptEtiquettes(liste: JSONArray): String =
            "if (typeof assistant.etiquettes === \"function\") assistant.etiquettes($liste)"

        /** Pastilles de la pièce choisie : `[{entite, genre, fraction, allume, etat, surligne}]`. */
        fun scriptPastilles(liste: JSONArray): String =
            "if (typeof assistant.pastilles === \"function\") assistant.pastilles($liste)"

        /** Opacité du voile sur les autres pièces : 0,65 le jour, 0,7 le soir. */
        fun scriptVoile(opacite: Float): String =
            "if (typeof assistant.voile === \"function\") assistant.voile(${nombre(opacite.coerceIn(0f, 0.9f))})"

        /** Ce qui est sous le point ([x], [y]) en pixels CSS : une pastille, une pièce ou le vide (texte JSON). */
        fun scriptDesigner(x: Float, y: Float): String =
            "(typeof assistant.designer === \"function\") ? assistant.designer(${nombre(x)}, ${nombre(y)}) : null"

        /** Objets réglables de chaque pièce, lus une fois quand la page est prête (texte JSON). */
        const val SCRIPT_CONTENU = "(typeof assistant.contenu === \"function\") ? assistant.contenu() : null"

        /**
         * Résultat de evaluateJavascript pour une fonction qui rend un texte : la WebView l'encode en JSON (`"\"{...}\""`),
         * `null` quand il n'y a rien. Rend le texte, ou null.
         */
        fun texteRendu(r: String?): String? {
            if (r == null || r == "null" || r.isBlank()) return null
            return try {
                (org.json.JSONTokener(r).nextValue() as? String)?.takeIf { it.isNotEmpty() }
            } catch (_: Exception) {
                null
            }
        }

        /** Nombre en notation JavaScript (point décimal, jamais de virgule ni de NaN). */
        private fun nombre(v: Float): String =
            if (v.isNaN() || v.isInfinite()) "0" else String.format(java.util.Locale.ROOT, "%.3f", v).trimEnd('0').trimEnd('.')
    }
}
