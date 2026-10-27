package assistant.vocal.jarvis

import org.json.JSONArray
import org.json.JSONObject

/**
 * Logique pure de la vue 3D de l'appartement (assets/maison3d/vue3d.html, source dans carte/3d/) :
 * traduction des états Home Assistant en appels `window.maison3d`, et file d'attente des appels
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
        const val SCRIPT_ENSEMBLE = "maison3d.ensemble()"
        /** Bords de la scène fondus dans le noir (0.17.6), pour l'aperçu de l'écran ambiant. */
        const val SCRIPT_FONDU = "maison3d.fondu(true)"
        /** Accueil plein écran (0.24.0) : la page dessine elle-même son fond, aucun bord fondu. */
        const val SCRIPT_SANS_FONDU = "maison3d.fondu(false)"
        /** États où Home Assistant ne sait rien de l'appareil : la page le montre éteint, sans couleur ni volume. */
        private val ETATS_SANS_VALEUR = setOf("unavailable", "unknown")

        /** Bornes de la température de couleur gardées pour la page : au-delà, la formule du corps noir n'a plus de sens. */
        const val KELVIN_MIN = 1000
        const val KELVIN_MAX = 40000

        /** Nombre fini d'un attribut HA (nombre ou texte numérique), null sinon (absent, null JSON, NaN, texte). */
        private fun chiffre(a: JSONObject, cle: String): Double? {
            if (!a.has(cle) || a.isNull(cle)) return null
            val v = when (val o = a.opt(cle)) {
                is Number -> o.toDouble()
                is String -> o.trim().toDoubleOrNull()
                else -> null
            }
            return v?.takeIf { !it.isNaN() && !it.isInfinite() }
        }

        /** Couleur rgb de HA : trois composantes numériques, bornées à 0..255. Null si le tableau est mal formé. */
        private fun rgbValide(a: JSONObject): JSONArray? {
            val t = a.optJSONArray("rgb_color") ?: return null
            if (t.length() != 3) return null
            val r = JSONArray()
            for (i in 0 until 3) {
                val v = (t.opt(i) as? Number)?.toDouble()?.takeIf { !it.isNaN() && !it.isInfinite() } ?: return null
                r.put(Math.round(v).toInt().coerceIn(0, 255))
            }
            return r
        }

        /**
         * Ne garde d'un état HA que ce que la page lit : `state`, la luminosité, UNE couleur et le volume.
         * - `state` en minuscules, « unknown » s'il manque ou s'il est vide. Inconnu ou indisponible : aucun attribut.
         * - luminosité entière de 0 à 255, volume de 0 à 1, kelvins de 1000 à 40000, rgb de 0 à 255 par composante.
         * - couleur : la température si la lampe est en mode `color_temp` (HA donne alors aussi un rgb déduit,
         *   moins juste), sinon le rgb, sinon la température.
         */
        fun etatReduit(etatHA: JSONObject): JSONObject {
            val etat = etatHA.optString("state", "").trim().lowercase().ifEmpty { "unknown" }
            val r = JSONObject().put("state", etat)
            val a = etatHA.optJSONObject("attributes") ?: return r
            if (etat in ETATS_SANS_VALEUR) return r.put("attributes", JSONObject())
            val ra = JSONObject()
            chiffre(a, "brightness")?.let { ra.put("brightness", Math.round(it).toInt().coerceIn(0, 255)) }
            chiffre(a, "volume_level")?.let { ra.put("volume_level", it.coerceIn(0.0, 1.0)) }
            val kelvin = chiffre(a, "color_temp_kelvin")?.takeIf { it > 0 }
                ?.let { Math.round(it).toInt().coerceIn(KELVIN_MIN, KELVIN_MAX) }
            val rgb = rgbValide(a)
            when {
                kelvin != null && (a.optString("color_mode") == "color_temp" || rgb == null) -> ra.put("color_temp_kelvin", kelvin)
                rgb != null -> ra.put("rgb_color", rgb)
            }
            return r.put("attributes", ra)
        }

        /** État d'un lecteur multimédia (télé, enceinte) tel que le lit la page : `state` et `volume_level`. */
        fun etatMedia(etat: String, volume: Double?): JSONObject {
            val brut = JSONObject().put("state", etat)
            if (volume != null) brut.put("attributes", JSONObject().put("volume_level", volume))
            return etatReduit(brut)
        }

        /** Entité de la vue 3D qui représente [id] : celle de la correspondance configurée, sinon [id] lui-même. */
        fun entiteVue(id: String, correspondances: Map<String, String> = Maison3d.CORRESPONDANCES): String =
            correspondances[id] ?: id

        /**
         * `maison3d.etats([...])` avec les lumières, la télé et les enceintes (0.24.0, page 0.6.0 : télé allumée,
         * ondes des enceintes qui jouent) du tableau brut de `/api/states`.
         */
        fun scriptEtats(etats: JSONArray, correspondances: Map<String, String> = Maison3d.CORRESPONDANCES): String {
            val lumieres = JSONArray()
            for (i in 0 until etats.length()) {
                val e = etats.optJSONObject(i) ?: continue
                val id = e.optString("entity_id")
                if (!id.startsWith("light.") && !id.startsWith("media_player.")) continue
                lumieres.put(etatReduit(e).put("entity_id", entiteVue(id, correspondances)))
            }
            return "maison3d.etats($lumieres)"
        }

        fun scriptEtat(entite: String, etatHA: JSONObject, correspondances: Map<String, String> = Maison3d.CORRESPONDANCES): String =
            "maison3d.etat(${JSONObject.quote(entiteVue(entite, correspondances))}, ${etatReduit(etatHA)})"

        fun scriptMontrer(cibles: List<String>, correspondances: Map<String, String> = Maison3d.CORRESPONDANCES): String =
            "maison3d.montrer(${JSONArray(cibles.map { entiteVue(it, correspondances) })})"

        /** Effets que la page sait jouer (0.17.5), tout autre devient un réglage. */
        private val EFFETS = setOf("allumer", "eteindre", "regler")

        /**
         * `maison3d.action({...})` (0.17.5) : pour chaque lumière, l'effet et, s'il est connu, l'état lu
         * dans HA réduit à ce que lit la page. La page joue toute la chorégraphie elle-même.
         */
        fun scriptAction(effets: JSONObject, correspondances: Map<String, String> = Maison3d.CORRESPONDANCES): String {
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
                r.put(entiteVue(cle, correspondances), sortie)
            }
            return "maison3d.action($r)"
        }

        /** `maison3d.poser({...})` (0.17.5) : états appliqués sans animation, `{entité: état HA}`. */
        fun scriptPoser(etats: JSONObject, correspondances: Map<String, String> = Maison3d.CORRESPONDANCES): String {
            val r = JSONObject()
            for (cle in etats.keys()) etats.optJSONObject(cle)?.let { r.put(entiteVue(cle, correspondances), etatReduit(it)) }
            return "maison3d.poser($r)"
        }

        // ------------------------------------------------ écran d'accueil (0.18.0, page 3D 0.4.0)

        /** Noms des pièces écrits au sol cachés : seules les pièces allumées sont nommées, par étiquette. */
        const val SCRIPT_NOMS_CACHES = "maison3d.nomsAuSol(false)"

        /** Bords fondus sur une largeur [bord] (part de la vue), plus fins que ceux de l'aperçu. */
        fun scriptFondu(bord: Float): String = "maison3d.fondu(true, ${nombre(bord)})"

        /** Rotation lente : un tour en [periodeS] secondes, [ips] images par seconde au plus, cadrage × [cadre]. */
        fun scriptRotation(periodeS: Int, ips: Int, cadre: Float): String =
            "maison3d.rotation(${periodeS.coerceAtLeast(0)}, ${ips.coerceIn(1, 30)}, ${nombre(cadre)})"

        /**
         * Balancement de l'accueil (0.24.0, page 0.5.2) : la caméra va et vient de ± [amplitudeDeg] autour de
         * [angleDeg], aller et retour en [periodeS] secondes, au lieu du tour complet.
         */
        fun scriptRotation(periodeS: Int, ips: Int, cadre: Float, amplitudeDeg: Float, angleDeg: Float): String =
            "maison3d.rotation(${periodeS.coerceAtLeast(0)}, ${ips.coerceIn(1, 30)}, ${nombre(cadre)}, ${nombre(amplitudeDeg)}, ${nombre(angleDeg)})"

        /**
         * Zone de la fenêtre où l'appartement est cadré (0.24.0, page 0.5.0), en fractions, transition en
         * [dureeMs] (sans durée : d'un coup, écran en veille).
         */
        fun scriptDisposition(z: Disposition.Zone, dureeMs: Int): String {
            val o = "{\"x\": ${nombre(z.x)}, \"y\": ${nombre(z.y)}, \"largeur\": ${nombre(z.largeur)}, \"hauteur\": ${nombre(z.hauteur)}" +
                (if (dureeMs > 0) ", \"duree_ms\": $dureeMs" else "") + "}"
            return "maison3d.disposition($o)"
        }

        /** Jeu de teintes « couleur » (page 0.5.0) à l'[intensite] voulue : 1 le jour, 0,2 le soir, 0,15 la nuit. */
        fun scriptJeuCouleur(intensite: Float): String =
            "maison3d.teintes({\"jeu\": \"couleur\", \"intensite\": ${nombre(intensite.coerceIn(0f, 1f))}})"

        /** Intensité seule, les autres teintes gardées (passage du soir à la nuit). */
        fun scriptIntensite(intensite: Float): String =
            "maison3d.teintes({\"intensite\": ${nombre(intensite.coerceIn(0f, 1f))}})"

        /**
         * Régime de l'accueil (0.24.0) : 1 vivant (fond bleu de nuit, flaque, particules, couleurs pleines), 0 en
         * retrait (noir pur, couleurs à 40 %), en [dureeMs]. Sans effet sur une page qui ne le connaît pas encore.
         */
        fun scriptRegime(niveau: Float, dureeMs: Int): String =
            "if (typeof maison3d.regime === \"function\") maison3d.regime(${nombre(niveau.coerceIn(0f, 1f))}, ${dureeMs.coerceAtLeast(0)})"

        /**
         * Mode développeur (0.48.0) : la page cache ses repères de débogage (version, cadence, compteurs) quand
         * [actif] est faux. Sans effet sur une page qui ne connaît pas encore la fonction.
         */
        fun scriptModeDeveloppeur(actif: Boolean): String =
            "if (typeof maison3d.modeDeveloppeur === \"function\") maison3d.modeDeveloppeur($actif)"

        /** Scène atténuée (écoute) ou pleine, en [dureeMs]. */
        fun scriptAttenuer(opacite: Float, dureeMs: Int): String =
            "maison3d.attenuer(${nombre(opacite.coerceIn(0f, 1f))}, ${dureeMs.coerceAtLeast(0)})"

        /** Retour animé à la vue de tout l'appartement, puis reprise de la rotation. */
        fun scriptEnsemble(dureeMs: Int): String = "maison3d.ensemble(${dureeMs.coerceAtLeast(0)})"

        // ------------------------------------------------ 0.18.1 (page 3D 0.4.1)

        /** Teintes de la palette de l'appli (Palette.plan3d), envoyées au chargement. */
        fun scriptTeintes(teintes: JSONObject): String = "maison3d.teintes($teintes)"

        /** Teintes du jeu de couleurs choisi (0.19.0, page 0.4.2) : lumière chaude, poussières, flux, pluie. */
        fun scriptPalette(teintes: JSONObject): String = "maison3d.palette($teintes)"

        /** Cadence de repos (images par seconde) de la rotation et des poussières, et plafond pendant une action. */
        fun scriptCadence(ips: Int, action: Int = 30): String = "maison3d.cadence(${ips.coerceIn(1, 30)}, ${action.coerceIn(1, 60)})"

        /** Pause : plus aucune image, requestAnimationFrame coupé. */
        fun scriptPause(oui: Boolean): String = "maison3d.pause($oui)"

        /** Poussières ambre des pièces allumées (accueil seulement). */
        fun scriptPoussieres(oui: Boolean): String = "maison3d.poussieres($oui)"

        /** Maison qui ne répond plus : lumières du plan en gris. */
        fun scriptDesaturer(oui: Boolean): String = "maison3d.desaturer($oui)"

        /** Le point ([x], [y]) en pixels CSS de la page tombe-t-il sur l'appartement ? Rend true ou false. */
        fun scriptDansLePlan(x: Float, y: Float): String = "maison3d.dansLePlan(${nombre(x)}, ${nombre(y)})"

        // ------------------------------------------------ la maison en grand (0.27.0, page 3D 0.8.0)

        /**
         * Maison en grand ou non : caméra figée, noms au sol de la page cachés, pastilles de [taille] et étiquettes en
         * [police] pixels CSS. Sans effet sur une page qui ne le connaît pas encore.
         */
        fun scriptGrand(actif: Boolean, taille: Float, police: Float): String =
            "if (typeof maison3d.grand === \"function\") maison3d.grand($actif, ${nombre(taille)}, ${nombre(police)})"

        /** Pièce choisie (null : retour à la maison entière), cadrée en [dureeMs] sous un voile. */
        fun scriptChoisir(piece: String?, dureeMs: Int): String =
            "if (typeof maison3d.choisir === \"function\") maison3d.choisir(${piece?.let { JSONObject.quote(it) } ?: "null"}, ${dureeMs.coerceAtLeast(0)})"

        /** Étiquettes des pièces de la vue entière : `[{piece, nom, etat, verrou}]`. */
        fun scriptEtiquettes(liste: JSONArray): String =
            "if (typeof maison3d.etiquettes === \"function\") maison3d.etiquettes($liste)"

        /** Pastilles de la pièce choisie : `[{entite, genre, fraction, allume, etat, surligne}]`. */
        fun scriptPastilles(liste: JSONArray): String =
            "if (typeof maison3d.pastilles === \"function\") maison3d.pastilles($liste)"

        /**
         * Mesures de la pièce choisie (S-L7) : `{piece, nom, statut, texte, couleur, lignes, air}`, ou null pour effacer
         * le carton (maison entière). Sans effet sur une page qui ne le connaît pas encore.
         */
        fun scriptMesures(charge: JSONObject?): String =
            "if (typeof maison3d.mesures === \"function\") maison3d.mesures(${charge ?: "null"})"

        /** Opacité du voile sur les autres pièces : 0,65 le jour, 0,7 le soir. */
        fun scriptVoile(opacite: Float): String =
            "if (typeof maison3d.voile === \"function\") maison3d.voile(${nombre(opacite.coerceIn(0f, 0.9f))})"

        /** Ce qui est sous le point ([x], [y]) en pixels CSS : une pastille, une pièce ou le vide (texte JSON). */
        fun scriptDesigner(x: Float, y: Float): String =
            "(typeof maison3d.designer === \"function\") ? maison3d.designer(${nombre(x)}, ${nombre(y)}) : null"

        /** Objets réglables de chaque pièce, lus une fois quand la page est prête (texte JSON). */
        const val SCRIPT_CONTENU = "(typeof maison3d.contenu === \"function\") ? maison3d.contenu() : null"

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
