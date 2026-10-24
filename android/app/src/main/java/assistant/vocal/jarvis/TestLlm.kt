package assistant.vocal.jarvis

import android.content.Context
import android.os.SystemClock
import android.util.Log

/**
 * Banc du LLM sur l'appareil, sans micro ni action : charge un modèle de files/llm/, lit les
 * appareils dans HA (lecture seule, par la passerelle de l'app Jarvis sur HA) et note la décision
 * pour chaque phrase. Rien n'est exécuté.
 *   adb shell am start -n assistant.vocal.jarvis/.MainActivity --es test_llm "phrase 1|phrase 2" [--es modele fichier.litertlm]
 * Résultats dans logcat, étiquette JarvisLlm.
 */
object TestLlm {
    private const val TAG = "JarvisLlm"

    fun lancer(contexte: Context, phrases: String, modele: String?) {
        Thread({
            try {
                val t0 = SystemClock.elapsedRealtime()
                val m = ModeleLiteRt.charger(contexte, modele) ?: run {
                    Log.e(TAG, "aucun modèle dans ${ModeleLiteRt.dossier(contexte)}")
                    return@Thread
                }
                Log.i(TAG, "${m.nom}, sortie contrainte ${ModeleLiteRt.contrainteParDefaut}, chargé en ${SystemClock.elapsedRealtime() - t0} ms")
                val passerelle = PasserelleHa(contexte, SatelliteService.adresse(contexte, "ha"))
                CerveauAppareil(contexte, passerelle, m).use { c ->
                    for (p in phrases.split("|").map { it.trim() }.filter { it.isNotEmpty() }) {
                        val d = c.decider(p)
                        Log.i(TAG, "« $p » : inventaire ${d.msInventaire} ms, modèle ${d.msModele} ms, prompt ${d.tailleprompt} caractères")
                        Log.i(TAG, "   réponse « ${d.reponse} »")
                        for (a in d.actions) Log.i(TAG, "   action ${a.enJson()}")
                        for (e in d.ecartees) Log.i(TAG, "   écartée $e")
                        Log.i(TAG, "   brut ${d.brut.replace("\n", " ").take(400)}")
                    }
                }
                passerelle.close()
            } catch (e: Throwable) {
                Log.e(TAG, "Banc impossible", e)
            }
        }, "jarvis-test-llm").start()
    }
}
