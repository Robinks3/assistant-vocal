package assistant.vocal.jarvis

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent

/**
 * Bancs lancés par adb sans ouvrir l'écran (on peut utiliser la tablette pendant ce temps) :
 *   adb shell am broadcast -n assistant.vocal.jarvis/.RecepteurBanc --es test_llm "phrase 1|phrase 2" [--es modele f.litertlm]
 * Mêmes extras que MainActivity (test_reveil, test_canary, fils). Protégé par la permission DUMP,
 * que seul le shell adb possède : aucune autre appli ne peut le déclencher.
 */
class RecepteurBanc : BroadcastReceiver() {
    override fun onReceive(contexte: Context, intent: Intent) {
        val app = contexte.applicationContext
        // Dossiers des modèles créés par l'appli : Android 16 refuse ceux créés par adb (errno 13).
        CanaryLocal.dossierModele(app).mkdirs()
        ModeleLiteRt.dossier(app).mkdirs()
        // Phrase écrite traitée par le service en marche (mode « Cet appareil »), toujours en essai.
        intent.getStringExtra("phrase")?.let { Etat.actionTesterTexte?.invoke(it) }
        intent.getStringExtra("test_reveil")?.let { TestReveil.lancer(app, it) }
        intent.getStringExtra("test_canary")?.let { TestCanary.lancer(app, it, intent.getIntExtra("fils", 4)) }
        if (intent.hasExtra("contraint")) ModeleLiteRt.contrainteParDefaut = intent.getBooleanExtra("contraint", true)
        intent.getStringExtra("test_llm")?.let { TestLlm.lancer(app, it, intent.getStringExtra("modele")) }
    }
}
