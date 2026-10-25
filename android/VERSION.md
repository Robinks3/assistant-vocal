# Assistant vocal, versions de l'appli Android

Application Android `assistant.vocal.jarvis` : écran ambiant et assistant vocal de la maison sur une tablette posée
en paysage (mode « Cet appareil » ou serveur `poc/serveur_satellite.py`), satellite vocal sur les
téléphones. La version et la date de compilation s'affichent dans la couche de service de l'accueil de la
tablette (un toucher dans le noir), dans l'en-tête des réglages, en pied de l'écran du téléphone et dans la
notification du service.

## 0.32.2 (2026-10-25)
- Phrases apprises sorties de l'export versionnable : `android/outils/exporter_dictionnaire.py` n'écrit plus
  dans `genere/android/dictionnaire.json` du dossier de configuration que ce qui vient de `commandes.yaml`.
  Les phrases apprises de la machine partent dans `genere/android/dictionnaire_appris.json` du dossier de
  données (`JARVIS_DONNEES`, `poc/` par défaut, `poc/genere/` ignoré par git), réécrit même vide pour ne
  jamais embarquer d'anciennes phrases. `build.gradle.kts` ajoute ce dossier aux assets s'il existe
  (`-PdonneesDossier=...` pour un autre), jamais avec `config-exemple/`. `DictionnaireLocal` fusionne les
  deux fichiers, une phrase apprise ne remplace jamais une phrase de `commandes.yaml`.
- Option `--sortie FICHIER` de l'exporteur : `test_export_exemple_a_jour` compare l'export d'exemple refait
  dans un dossier temporaire et ne réécrit plus `config-exemple/genere/android/dictionnaire.json` suivi par git.
- Tests : `test_phrases_apprises_hors_export_de_configuration` (Python) et
  `phrasesApprisesFusionneesSansRemplacerLaConfiguration` (Kotlin). versionCode 59.

## 0.32.1 (2026-10-25)
- Passerelle HA qui ne se remettait pas d'un redémarrage de l'appli Home Assistant : la poignée de main
  WebSocket n'avait aucun délai (`readTimeout(0)` sans `callTimeout`), un serveur qui accepte la connexion
  puis se tait bloquait l'appel pour toujours et la reconnexion n'était jamais tentée. Toutes les liaisons
  WebSocket de l'appli (passerelle HA, satellite, transcription, vision, appareils) passent par
  `Confiance.clientWebSocket()` : poignée de main bornée à 15 s, liaison montée sans délai de lecture, ping
  toutes les 20 s.
- Test `ConfianceWebSocketTest` : serveur muet après accept, liaison montée qui survit au délai. versionCode 58.

## 0.32.0 (2026-10-25)
- Plus de plafond de volume de 50 % : `Securite.VOLUME_MAX` vient de `securite.plafond_volume` de
  `maison.json` (1 sans plafond, le défaut), mêmes règles que le serveur, cas communs compris.
- Pistes de volume de l'accueil, de la maison en grand et de l'écran Musique de 0 au volume permis, 100 %
  sans plafond. Trait et mention du plafond seulement quand un plafond est réglé. Les crans restent sous le
  plafond (borné après l'arrondi), et un plafond de 0 % ne fait plus planter le calcul de la piste.
- Monter le son par pas reste converti en volume précis, borné au volume permis.
- Tests avec et sans plafond (`SecuriteTest`, `AccueilDispositionTest`, `MaisonEnGrandTest`). versionCode 57.

## 0.31.0 (2026-10-25)
- Nom affiché de l'assistant lu dans la section `assistant` de `maison.json` (`ConfigMaison.NOM_ASSISTANT`) :
  nom de l'appli sous l'icône (`resValue app_name` dans `build.gradle.kts`), textes de l'accueil, des
  réglages, de la météo, de la musique, de la vision et des notifications, en formulations neutres.
  « Assistant » sans la section.
- Identifiants neutres : pont de la page 3D `window.maison3d` et `Maison3dAndroid` (page 3D à régénérer
  avec `carte/3d/generer_3d.py`), mot de réveil personnalisé `perso` (`segmentPerso`, `CLE_SEUIL_PERSO`).
  L'ancien seuil `seuil_reveil_assistant` est recopié une fois au démarrage, l'ancien choix enregistré reste
  lu comme mot personnalisé.
- Sons d'écoute : commentaire ICMT des WAV neutre, son inchangé.
- Test `ConfigMaisonTest`. versionCode 56.

## 0.30.1 (2026-10-24)
- Premier instantané du moteur, sans historique. La configuration de la maison (`maison.json`,
  dictionnaire exporté, page 3D, trait de côte, mot de réveil) vient du dossier de configuration et
  entre dans l'APK à la compilation. Une APK est refusée sans lui. La numérotation continue celle du
  projet d'origine. versionCode 55.
