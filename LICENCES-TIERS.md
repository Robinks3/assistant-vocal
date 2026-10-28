# Licences des modèles et du code tiers

Le code de cet assistant est publié sous licence MIT, texte complet dans le fichier `LICENSE` à la racine (décision D2 du plan de travail, 26/10/2026). Cette licence ne couvre que le code du dépôt. Les modèles, polices et bibliothèques ci-dessous gardent leur propre licence.
Le nom affiché de l'assistant se règle dans la configuration, section `assistant` de `maison.json`. Il n'a aucun lien avec une licence.

Dernière vérification : 26/10/2026 (version 0.34.1). Chaque ligne dit ce qui a été contrôlé à la source et ce qui ne l'a pas été. La liste de ce qui reste à confirmer est en fin de document.

## Modèles et fichiers livrés avec le code

| Élément | Où | Licence | Remarque |
|---|---|---|---|
| Mot de réveil personnalisé de l'installation | Dans la configuration privée (`reveil/`), jamais dans ce dépôt | CC BY-NC-SA 4.0, auteurs du modèle d'origine | Pas d'usage commercial, partage dans les mêmes conditions. Chacun range son propre modèle dans `reveil/` de sa configuration. Licence reprise de l'ancienne version de ce document, non revérifiée à la source. |
| Mot de réveil « Hey Jarvis » (`hey_jarvis_v0.1.onnx`) | `android/app/src/main/assets/reveil/` | CC BY-NC-SA 4.0 (openWakeWord, David Scripka) | À retirer de l'instantané public, voir plus bas. Licence lue dans les métadonnées de la roue openwakeword 0.6.0 : le code est sous Apache 2.0, tous les modèles pré-entraînés sous CC BY-NC-SA 4.0. |
| Prétraitement openWakeWord (`embedding_model.onnx`, `melspectrogram.onnx`) | `android/app/src/main/assets/reveil/` | CC BY-NC-SA 4.0 (openWakeWord, David Scripka) | Même cas, à retirer de l'instantané public. |
| Silero VAD v5.1.2 | `poc/modeles/silero_vad.onnx`, `android/.../assets/vad/` | MIT (snakers4/silero-vad) | Licence prise dans les commentaires du code. Le dépôt ne contient pas de fichier de licence pour ce modèle, or la MIT demande de livrer la mention. À ajouter, voir « Reste à confirmer ». |
| YuNet, détection de visages | `poc/modeles/vision/yunet.onnx`, assets `vision/` | MIT (Shiqi Yu, 2020, opencv_zoo) | Texte de la licence dans `poc/modeles/vision/`, vérifié. |
| SFace, reconnaissance de visages | téléchargé par `poc/outils/telecharger_modeles.py` | Apache 2.0 (opencv_zoo) | Texte de la licence dans `poc/modeles/vision/`, vérifié. Empreinte SHA-256 contrôlée au téléchargement. |
| Voix Piper fr_FR-siwis-medium | téléchargée par `poc/outils/telecharger_modeles.py` | Voir la fiche de la voix dans rhasspy/piper-voices (jeu de données SIWIS) | Licence du jeu de données non vérifiée, voir « Reste à confirmer ». |
| Voix Piper en_US-lessac-medium | téléchargée par `poc/outils/telecharger_modeles.py` | Voir la fiche de la voix dans rhasspy/piper-voices (jeu de données Lessac) | Outil de test `faux_telephone.py` seulement. Licence du jeu de données non vérifiée. |
| Canary 1B v2 | téléchargé par onnx-asr au premier lancement | CC BY 4.0 (NVIDIA) | Licence reprise de l'ancienne version de ce document, non revérifiée à la source. |
| three.js r170 (0.170.0, vue 3D de l'appartement) | `android/.../assets/maison3d/vue3d.html`, `carte/3d/vendor/` | MIT (three.js authors) | Fichier `carte/3d/vendor/LICENSE-three.txt` à côté, vérifié. |
| Police Big Shoulders Display (heure de l'accueil et de l'AOD de la tablette) | `android/.../res/font/big_shoulders_display_200.ttf`, `big_shoulders_display_300.ttf`, `big_shoulders_display_400.ttf` (panneau Météo, 0.20.0) | SIL Open Font License 1.1, The Big Shoulders Project Authors (github.com/xotypeco/big_shoulders), fichier `assets/polices/OFL-BigShouldersDisplay.txt` | Prise dans le dépôt google/fonts (`ofl/bigshouldersdisplay`) le 22/10/2026. Depuis l'appli 0.18.1, instance statique de la police variable à la graisse 200 (fontTools `varLib.instancer`, aucun dessin modifié), chargée par `resources.getFont`. |
| Police Instrument Sans (texte de la tablette) | `android/.../res/font/instrument_sans_400.ttf`, `instrument_sans_500.ttf`, `instrument_sans_italique_400.ttf` | SIL Open Font License 1.1, The Instrument Sans Project Authors (github.com/Instrument/instrument-sans), fichier `assets/polices/OFL-InstrumentSans.txt` | Prise dans le dépôt google/fonts (`ofl/instrumentsans`) le 22/10/2026. Depuis l'appli 0.18.1, instances statiques (droit 400 et 500, italique 400) de la police variable (fontTools `varLib.instancer`, aucun dessin modifié). La page 3D ne l'embarque plus (plan 0.4.1). |

## Modèles à retirer de l'instantané public

Ces trois fichiers sont sous CC BY-NC-SA 4.0 (usage non commercial). Une publication sous MIT ne peut pas les redistribuer comme s'ils étaient libres. Ils sont encore versionnés dans le dépôt privé et ne doivent pas figurer dans l'instantané public. Ils se téléchargent depuis la publication officielle d'openWakeWord, avec vérification de l'empreinte et affichage de la licence : `python poc/outils/telecharger_modeles.py`.

| Fichier à retirer | Source officielle | SHA-256 |
|---|---|---|
| `android/app/src/main/assets/reveil/hey_jarvis_v0.1.onnx` | https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/hey_jarvis_v0.1.onnx | `94a13cfe60075b132f6a472e7e462e8123ee70861bc3fb58434a73712ee0d2cb` |
| `android/app/src/main/assets/reveil/embedding_model.onnx` | https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/embedding_model.onnx | `70d164290c1d095d1d4ee149bc5e00543250a7316b59f31d056cff7bd3075c1f` |
| `android/app/src/main/assets/reveil/melspectrogram.onnx` | https://github.com/dscripka/openWakeWord/releases/download/v0.5.1/melspectrogram.onnx | `ba2b0e0f8b7b875369a2c89cb13360ff53bac436f2895cced9f479fa65eb176f` |

Les empreintes sont celles des fichiers de la roue openwakeword 0.6.0 et des fichiers actuellement versionnés, qui sont identiques. L'adresse de la publication v0.5.1 est déduite des adresses `.tflite` du paquet et n'a pas été interrogée (pas de réseau lors de la vérification).

Le modèle du mot de réveil personnalisé (configuration privée) reste aussi hors de l'instantané public, puisqu'il n'est jamais dans ce dépôt.

Le serveur utilise les mêmes modèles, rangés par openWakeWord dans son propre paquet Python (dossier `resources/models`). Ils ne sont pas dans le dépôt.

Un modèle manquant produit un message clair (fonction `verifier_au_demarrage` de `poc/outils/telecharger_modeles.py`) qui nomme le fichier, cite la licence et donne la commande de téléchargement. Le branchement de cette fonction au démarrage du serveur reste à faire dans `poc/assistant.py`.

## Bibliothèques Python du serveur (`poc/requirements.txt`)

Licences lues dans les métadonnées des paquets installés dans l'environnement virtuel du dépôt (Python 3.11.9). Source de chaque paquet : `https://pypi.org/project/<nom>/`.

| Paquet | Version contrôlée | Licence | Remarque |
|---|---|---|---|
| faster-whisper | 1.2.1 | MIT | Outil de mesure seulement. Les modèles qu'il charge ont leur propre licence, non vérifiée. |
| sounddevice | 0.5.6 | MIT | |
| numpy | 2.4.6 | BSD-3-Clause, 0BSD, MIT, Zlib, CC0-1.0 | Expression d'ensemble des composants. |
| httpx | 0.28.1 | BSD-3-Clause | |
| python-dotenv | 1.2.4 | BSD-3-Clause | |
| piper-tts | 1.8.0 | GPL-3.0-or-later | Voir la note GPL plus bas. |
| openwakeword | 0.6.0 | Apache 2.0 pour le code | Les modèles pré-entraînés sont sous CC BY-NC-SA 4.0, voir plus haut. |
| pyyaml | 6.0.3 | MIT | |
| psutil | 7.2.2 | BSD-3-Clause | |
| anthropic | 1.13.0 | MIT | |
| wyoming | 1.10.2 | MIT | |
| cryptography | 50.0.2 | Apache 2.0 ou BSD-3-Clause, au choix | |
| opencv-python-headless | 5.0.0.93 | Apache 2.0 | |
| websockets | 17.2 | BSD-3-Clause | |
| onnx-asr (extras cpu, hub) | 0.12.0 | MIT | Les dépendances des extras n'ont pas été auditées une à une. |
| onnxruntime | 1.31.0 | MIT | |
| pytest | 9.1.1 | MIT | Tests seulement. |
| pillow | non installé ici | non vérifiée | Plan 2D (`carte/generer_plan.py`) seulement. À contrôler sur une machine qui l'installe. |
| tzdata | 2026.5 | Apache 2.0 | |
| segno | 1.6.6 | BSD (classifieur du paquet) | Génération locale du QR code d'appairage du client web. |

Les dépendances indirectes de ces paquets ne sont pas listées.

### Note sur piper-tts (GPL-3.0-or-later)

`piper-tts` est sous GPL 3 ou ultérieure. Le serveur l'importe dans `poc/assistant.py`. Le code MIT du dépôt n'embarque pas piper-tts : il est installé séparément par `pip`, et chacun le reçoit de son éditeur sous sa propre licence. Qui redistribue un ensemble contenant piper-tts (une image, une archive prête à l'emploi) doit respecter la GPL pour cet ensemble. L'analyse juridique de l'effet de l'import sur la licence du serveur n'a pas été faite, voir « Reste à confirmer ».

## Bibliothèques Python de l'application Home Assistant (`ha-app/jarvis/requirements.txt`)

Mêmes paquets, mêmes licences que ci-dessus : numpy, websockets, wyoming, httpx, python-dotenv, pyyaml, anthropic, tzdata, onnxruntime, cryptography et segno. Aucun paquet de plus. L'application Home Assistant n'embarque ni piper-tts ni openwakeword. Les versions installées dans l'image dépendent de la date de construction et n'ont pas été contrôlées une à une. L'image de base du `Dockerfile` et ses paquets système n'ont pas été audités.

## Dépendances Gradle de l'application Android (`android/app/build.gradle.kts`)

Licences lues dans les fichiers POM et les archives du cache Gradle local (Google Maven et Maven Central).

| Dépendance | Version | Licence | Source |
|---|---|---|---|
| com.squareup.okhttp3:okhttp | 4.12.0 | Apache 2.0 | Non vérifiée localement (ni POM ni fichier de licence dans le cache). Licence connue du projet, à confirmer. |
| com.microsoft.onnxruntime:onnxruntime-android | 1.22.0 | MIT | POM, vérifié |
| com.google.ai.edge.litertlm:litertlm-android | 0.18.0 | Apache 2.0 | POM, vérifié |
| org.opencv:opencv | 4.14.0 | Apache 2.0 | POM, vérifié |
| androidx.camera:camera-camera2, camera-lifecycle, camera-view | 1.6.2 | Apache 2.0 | POM, vérifié |
| androidx.lifecycle:lifecycle-runtime | 2.8.7 | Apache 2.0 | POM, vérifié |
| junit:junit (tests) | 4.13.2 | EPL 1.0 | Archive du jar, vérifié. Tests seulement. |
| org.json:json (tests) | 20240303 | Domaine public | POM, vérifié. Tests seulement. |

Le plugin Android Gradle (9.2.1) et Gradle 9.4.1 sont des outils de compilation, non livrés dans l'application. Leur licence n'a pas été vérifiée.

## Reste à confirmer

Points que la vérification du 26/10/2026 n'a pas pu clore, faute de réseau ou de source dans le dépôt :

- OkHttp 4.12.0 sous Apache 2.0 : pas de POM ni de licence dans le cache local.
- Silero VAD sous MIT : annoncé par les commentaires du code seulement. Ajouter le fichier de licence du projet d'origine à côté du modèle.
- Canary 1B v2 sous CC BY 4.0 : reprise de l'ancien document.
- Voix Piper : licence des jeux de données SIWIS (voix française, utilisée par le serveur) et Lessac (voix anglaise, outil de test). À lire sur les fiches de rhasspy/piper-voices avant toute redistribution d'une voix.
- Modèles de langage utilisés par LiteRT-LM (Gemma 4 E2B, Qwen2.5-1.5B, qwen3 0.6B) : seulement donnés comme Apache 2.0 par un commentaire du code. Une famille peut avoir des conditions propres. Ces modèles ne sont pas dans le dépôt.
- Modèles de faster-whisper (outil de mesure) : licences non vérifiées.
- Publication v0.5.1 d'openWakeWord : les empreintes sont celles de la roue, la publication elle-même n'a pas été téléchargée pour comparer.
- pillow : non installé dans l'environnement contrôlé.
- piper-tts et GPL : effet de l'import sur la licence du serveur à faire analyser.
- Sources de données citées dans la documentation (Open-Meteo, VaguesRegional, Balises, StationsOfficielles, OpenStreetMap sous ODbL) : conditions d'usage non vérifiées ici.
- Nom du titulaire du droit d'auteur dans `LICENSE` : « les auteurs de l'assistant vocal local », neutre, à remplacer par le propriétaire du dépôt s'il le souhaite.

## Idées reprises d'un projet tiers

Des idées viennent d'un projet tiers publié sous PolyForm Noncommercial 1.0.0. Le code a été réécrit, aucun fichier n'a été copié.
