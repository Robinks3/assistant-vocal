# Ce qui tourne où

Inventaire de chaque modèle et de chaque composant du moteur : la machine qui le fait tourner, le
processeur ou la carte graphique qu'il occupe, la taille de son fichier, sa licence, ce qu'il envoie sur le
réseau, ce qui peut le remplacer en ligne et le matériel sur lequel il a été vu tourner. Tout est tiré du
code du serveur (version 0.33.0) et de l'appli Android (version 0.35.0). Les durées viennent des docstrings
et des journaux de versions du projet d'origine, elles sont citées comme mesures et non comme garanties.

Les trois façons de faire tourner l'assistant reviennent dans la colonne Machine :

| Nom court | Mode | Ce qui tourne |
|---|---|---|
| Appareil | Cet appareil | L'appli Android seule sur la tablette ou le téléphone (`MoteurLocal.kt`). |
| PC | Serveur du PC | `poc/serveur_satellite.py` en profil `pc` (`JARVIS_PROFIL=pc`, valeur par défaut). |
| Appli HA | Appli Home Assistant | Le même serveur en profil `ha`, emballé par `ha-app/` et lancé par `ha-app/jarvis/app/demarrage.py`. |
| Service HA | | Une appli déjà installée dans Home Assistant (openWakeWord, Speech-to-Phrase, Piper), jointe par le protocole Wyoming. |
| Externe | | Un service sur Internet. |

Les tailles sont mesurées avec `ls -l` sur les fichiers du dépôt, ou sur la copie locale après
`poc/outils/telecharger_modeles.py` pour les fichiers ignorés par git. 1 Mo vaut ici 1 000 000 octets.

## Le tableau

| Composant | Rôle | Machine | Processeur ou carte graphique | Fichier et taille | Licence | Ce qui part sur le réseau | Alternative en ligne | Matériel minimum |
|---|---|---|---|---|---|---|---|---|
| openWakeWord, prétraitement | Spectrogramme mel puis plongement de 96 valeurs, communs à tous les mots de réveil | Appareil (`ReveilLocal.kt`), PC (paquet `openwakeword`, `inference_framework="onnx"`) | Appareil : onnxruntime-android 1.22.0 sur le processeur, XNNPACK, un fil. PC : onnxruntime sur le processeur | `assets/reveil/melspectrogram.onnx` 1,1 Mo et `embedding_model.onnx` 1,3 Mo. Sur le PC, les fichiers du paquet Python | Apache 2.0 (code openWakeWord) | Rien | Léger, tourne partout : 2,4 Mo, 25 ms par bloc de 80 ms sur un seul cœur de tablette | Mesuré sur tablette (Snapdragon 855). Android 8 au moins (`minSdk 26`), ABI arm64-v8a ou armeabi-v7a |
| Mot de réveil "Hey Jarvis" | Dernier étage du réveil, par défaut | Appareil, PC, Service HA (`core-openwakeword:10400`, seul mot demandé en profil `ha`) | Comme ci-dessus | `assets/reveil/hey_jarvis_v0.1.onnx` 1,3 Mo. Sur le PC, `poc/outils/telecharger_modeles.py` le fait télécharger par openWakeWord avec ses modèles de prétraitement, rangés dans le dossier du paquet, sans vérification d'empreinte | Modèle sous CC BY-NC-SA 4.0 selon le dépôt d'openWakeWord, à vérifier avant publication (`LICENCES-TIERS.md`) | Rien en local. En profil `ha`, le son du micro part en continu vers l'appli openWakeWord de HA | Léger, tourne partout | Idem |
| Mot de réveil de la configuration | Remplace "Hey Jarvis" quand la section `reveil` de `maison.json` le décrit (défaut "assistant") | Appareil (copié dans les assets par la tâche Gradle `copierReveil`), PC (`reveil.mot`, sinon `MOT_REVEIL`, repli sur "Hey Jarvis" journalisé). Pas en profil `ha` | Comme ci-dessus | `reveil/<mot>.onnx` de la configuration, hors dépôt | Celle du modèle choisi, rangée à côté (`<mot>.onnx.LICENSE`) | Rien | Léger, tourne partout | Idem |
| Silero VAD v5.1.2 | Début et fin de la phrase (seuils 0,5 et 0,35, fin après 0,45 s de silence) | Appareil (`VadSilero.kt`), PC et Appli HA (`poc/vad.py`) | Processeur, un fil (`CPUExecutionProvider` sur le PC) | `poc/modeles/silero_vad.onnx` et `assets/vad/silero_vad.onnx`, 2,3 Mo chacun | MIT | Rien | Léger, tourne partout. Sans le modèle, repli sur un seuil d'énergie | Aucun constaté, fenêtres de 32 ms |
| Canary 1B v2 int8, appareil | Transcription de la phrase en français imposé | Appareil (`CanaryLocal.kt`) | onnxruntime-android sur le processeur, 4 fils, sans XNNPACK ni NNAPI | `nemo128.onnx`, `encoder-model.int8.onnx`, `decoder-model.int8.onnx`, `vocab.txt` dans `Android/data/assistant.vocal.jarvis/files/canary/`, copiés par adb : 1,03 Go (chiffre de `CanaryLocal.kt`) | CC BY 4.0 (NVIDIA) | Rien | API compatible OpenAI par le serveur qui l'annonce (lieu "En ligne"), l'appli ne garde aucune clé | 2,1 Go de mémoire. 0,44 à 0,61 s par phrase de 3 s sur téléphone, 0,7 à 1,1 s sur tablette |
| Canary 1B v2 int8, PC | Transcription (`Transcripteur` de `poc/assistant.py`) | PC. Chargé à chaque démarrage par `Moteur.__init__`, même si une transcription en ligne est réglée | Processeur, fournisseur par défaut d'onnx-asr | Téléchargé par onnx-asr au premier lancement (`nemo-canary-1b-v2`, `quantization="int8"`), même modèle que sur l'appareil | CC BY 4.0 (NVIDIA) | Rien, sauf le premier téléchargement | API compatible OpenAI : `STT_API_CLE`, `STT_API_URL`, `STT_API_MODELE`, `STT_API_NOM` (Voxtral de Mistral par défaut) | 1,1 Go de RAM, 5 à 6 cœurs pendant 0,5 à 0,7 s pour une commande de 3,6 s |
| Speech-to-Phrase | Transcription limitée aux phrases connues de Home Assistant (`ha_stp`) | Service HA (`core-speech-to-phrase:10300`). Depuis le PC, le flux passe par `ssh <reseau.ssh_ha> nc` | Processeur de la machine de Home Assistant | Appli de HA, hors dépôt | Non documentée dans le dépôt | Le son de la phrase, de la machine qui écoute vers Home Assistant, sur le réseau de la maison | Repli automatique sur l'API en ligne quand le texte revient vide et qu'une clé est réglée | petit serveur : 0,7 à 1,4 s par phrase |
| Whisper de HA | Transcription libre (`ha_whisper`), test seulement | Service HA (`core-whisper:10300`) | Processeur de Home Assistant | Appli de HA, hors dépôt | Non documentée dans le dépôt | Comme Speech-to-Phrase | API en ligne | Inutilisable sur petit serveur : environ 90 s par phrase |
| Transcription en ligne | Service compatible avec `POST /v1/audio/transcriptions` d'OpenAI (`transcrire_api`) | Externe, appelé par le PC ou l'Appli HA | Aucun en local | Aucun | Conditions du fournisseur | Le WAV de la phrase, `language=fr`, la clé dans l'en-tête `Authorization`. La voix quitte la maison | Elle est l'alternative | Une connexion Internet |
| Dictionnaire de commandes | Phrase exacte vers action Home Assistant (`poc/dictionnaire.py`, `DictionnaireLocal.kt`) | Appareil, PC, Appli HA | Processeur, quelques dizaines de ms | `commandes.yaml` de la configuration. Pour l'appli, `genere/android/dictionnaire.json` (1,6 Mo pour `config-exemple`), et les phrases apprises dans `genere/android/dictionnaire_appris.json` du dossier de données | Code du projet | Rien | Sans objet | Aucun |
| Synthèse vocale d'Android | Réponse dite en mode Cet appareil (`TextToSpeech`, `Locale.FRANCE`) | Appareil | Moteur de synthèse choisi dans le système | Aucun dans le dépôt | Celle du moteur du système | Selon le moteur de synthèse installé sur l'appareil, rien côté appli | Aucune codée | Un moteur de synthèse français installé |
| Piper, voix fr_FR-siwis-medium | Réponse dite en mode Serveur du PC, envoyée en WAV | PC (`Voix` de `poc/assistant.py`, paquet `piper-tts`). Chargée à chaque démarrage en profil `pc` | Processeur | `poc/voix/fr_FR-siwis-medium.onnx` 63,2 Mo et son `.json`, téléchargés par `telecharger_modeles.py` (empreinte SHA-256 vérifiée) | Voir la fiche de la voix dans rhasspy/piper-voices (jeu de données SIWIS) | Le WAV de la réponse vers le satellite, sur le réseau de la maison | Léger, tourne partout. Aucune voix en ligne codée | 0,12 Go de RAM, 0,2 s par phrase sur le PC, 0,7 s sur petit serveur |
| Piper de HA | Réponse dite en profil `ha` (`synthetiser_ha`, voix `fr_FR-siwis-medium`) | Service HA (`core-piper:10200`) | Processeur de Home Assistant | Appli de HA, hors dépôt | Comme ci-dessus | Le texte de la réponse vers Piper, puis le WAV vers le satellite, en local | Aucune codée | petit serveur : 0,7 s par phrase |
| Claude Haiku par API | LLM de repli avec outils (`CerveauClaude`, SDK `anthropic`, modèle `CLAUDE_MODELE`, `claude-haiku-5-5` par défaut) | Externe, appelé par le PC ou l'Appli HA (seul cerveau du profil `ha`). L'appareil y passe par le message `llm` | Aucun en local | Aucun | Conditions de l'API Anthropic | Texte de la demande, liste des appareils permis, états des appareils actifs, date, prénom reconnu par la tablette, trois derniers échanges, résultats des outils | Il est l'alternative en ligne (`LLM_FOURNISSEUR=claude`) | Une connexion Internet. 1,9 à 2,5 s par commande |
| LLM local compatible OpenAI | LLM de repli avec outils (`Cerveau`), requête `POST {LLM_URL}/chat/completions` | PC seulement (cerveau `local`) | Carte graphique : `poc/lancer-llm.ps1` lance llama-server (llama.cpp) en Vulkan avec Qwen3.5-9B Q6_K. LM Studio n'est pas utilisé (il ignore `enable_thinking=false`) | Fichier GGUF hors dépôt, taille non mesurée ici | Celle du modèle choisi, non documentée dans le dépôt | Rien hors du PC (`LLM_URL=http://127.0.0.1:8080/v1` par défaut) | Claude par API (`LLM_FOURNISSEUR=claude`) | 6,5 Go de VRAM et 0,65 Go de RAM pour Qwen3.5-9B. 2,7 à 3,8 s par commande |
| LLM de l'appareil, LiteRT-LM | LLM de repli sans outils : une réponse JSON `{actions, reponse}` vérifiée par `CerveauAppareil.kt` | Appareil (`ModeleLiteRt.kt`), choix `cerveau_local=local` | Carte graphique de l'appareil pour un fichier `-gpu` (`Backend.GPU()`, OpenCL facultatif), sinon processeur sur 4 fils | Fichiers `.litertlm` dans `Android/data/assistant.vocal.jarvis/files/llm/`, copiés par adb. Ordre de préférence : `gemma-4-E2B-it-gpu`, `gemma-4-E2B-it`, `Qwen2.5-1.5B-Instruct`, `qwen3_0.6b`. Tailles non mesurées ici | Apache 2.0 selon `ModeleLiteRt.kt` (Hugging Face litert-community), absent de `LICENCES-TIERS.md` | Rien, sauf la lecture des appareils par la passerelle Home Assistant | Claude Haiku par l'appli HA (message `llm`) | Non établi : seules des mesures en arrière-plan existent, où Android a tué Gemma 4 faute de mémoire sur téléphone |
| YuNet | Détection des visages et des cinq points (seuil 0,7) | Appareil (`MoteurVisageLocal` de `Vision.kt`, OpenCV pour Android 4.14.0) ou PC (`poc/vision.py`, `cv2.FaceDetectorYN`) selon la préférence `vision` (`off` par défaut) | Processeur, module DNN d'OpenCV sans réglage de cible | `poc/modeles/vision/yunet.onnx` et `assets/vision/yunet.onnx`, 0,23 Mo chacun | MIT | Vision sur le PC seulement : une image JPEG de 320 px au plus, 2 à 5 par seconde, sur wss | Léger, tourne partout | tablette : 27 à 28 ms par image. PC : 16 ms par image, 44 ms aller-retour |
| SFace | Empreinte de 128 nombres d'un visage, comparée aux profils sur la tablette | Comme YuNet (`cv2.FaceRecognizerSF`) | Processeur | `sface.onnx` 38,7 Mo, téléchargé par `telecharger_modeles.py` puis copié dans les assets de l'appli | Apache 2.0 (opencv_zoo) | Vision sur le PC : le PC renvoie les empreintes, rien n'est gardé sur le serveur | Tourne sur la tablette, aucun service en ligne codé | tablette, sans mesure propre |
| Page 3D | Plan 3D du logement, lampes allumées, toucher d'une lampe | Appareil, dans une WebView (`Maison3dView.kt`, `file:///android_asset/maison3d/vue3d.html`) | Carte graphique de l'appareil (WebGL) | three.js r170 : `carte/3d/vendor/three.module.min.js` 0,69 Mo. Page générée par `carte/3d/generer_3d.py`, environ 700 Ko | MIT (three.js) | Rien : `blockNetworkLoads = true`, liens refusés | Sans objet | WebGL. Vue recréée si le rendu meurt ou après 30 s sans battement |
| Prévisions terrestres | Panneau Météo et questions de météo à la voix | Home Assistant, lu par la passerelle (`weather.get_forecasts`, chemin exact permis par `poc/acces.py`) | Aucun en local | Aucun | Celle de l'intégration météo de Home Assistant | Rien de plus que ce que fait Home Assistant | Sans objet | Une entité `weather.*` dans Home Assistant |
| Météo marine | Page Mer (`poc/meteo_mer.py`, section `mer`, éteinte par `METEO_MER=0`) | PC ou Appli HA, appelés par l'appareil (message `meteo_mer`) | Aucun en local | Aucun | Non documentée dans le dépôt | Vers Open-Meteo (ARPEGE, AROME, MFWAM marine) : les coordonnées des points de `mer.points`. Vers la source régionale : un code de lieu (modèle WW3), puis la station du Vieux-Port | Ce sont des services en ligne | Aucun, cache de 1 h à 3 h en mémoire |
| Vent mesuré | Page Vent mesuré (`poc/vent_mesure.py`, sections `mer` et `vent`, éteinte par `VENT_MESURE=0` ou `METEO_MER=0`) | PC ou Appli HA (message `vent_mesure`) | Aucun en local | Aucun | Non documentée dans le dépôt | Vers Balises (API non officielle des balises de la régate) : latitude et longitude du plan d'eau et l'en-tête `User-Agent` de la configuration. Vers StationsOfficielles (une source officielle) : une plage horaire, sans coordonnées. Vers VaguesRegional : rien | Ce sont des services en ligne | Aucun, cache de 2 à 10 min |
| Relais santé | Panneau Santé et chiffres de l'accueil (`poc/sante.py`, `poc/sante_hist.py`) | PC seulement, quand `SANTE_JETON` est réglé | Aucun en local | Aucun | Code du projet | `GET /api/resume` de sante-api avec le jeton, et le fichier `data-auto.js` du tableau de bord HealthStats, seulement vers une adresse Tailscale (100.64.0.0/10 ou fd7a:115c:a1e0::/48) vérifiée avant chaque appel | Aucune | Le PC dans le même réseau Tailscale que sante-api |

## Notes

### Transcription

Le README annonce "Parakeet sur le PC". Le code transcrit sur le PC avec Canary 1B v2 (`Transcripteur` de
`poc/assistant.py`). Parakeet v3 n'apparaît que dans les outils de mesure (`poc/outils/mesure_parakeet.py`) et
a été écarté parce qu'il devine la langue à chaque phrase.

En profil `pc`, `Moteur.__init__` charge toujours Canary et Piper au démarrage. La transcription en ligne n'est
qu'un choix fait depuis l'appli (message `transcription`, `Moteur.changer_stt`), Canary restant en repli. En
profil `ha`, aucun modèle de transcription ni de voix n'est chargé : Speech-to-Phrase de Home Assistant, et la
voie `api` quand la clé est réglée dans les options de l'appli Home Assistant (`stt_api_cle`, lue par
`demarrage.py`).

Le choix "En ligne" de l'appli ne porte aucune clé : `OuTranscrire.voie` (`Transcription.kt`) envoie la phrase
au serveur qui annonce `api` dans ses capacités, l'appli Home Assistant d'abord, sinon le PC. Sans réponse en
8 s, en cas d'erreur ou de texte vide, la tablette transcrit elle-même avec Canary.

### Mot de réveil

En profil `pc`, chaque connexion d'un satellite charge son propre modèle openWakeWord (`Satellite.__init__`). En
profil `ha`, `ReveilWyoming` demande toujours `hey_jarvis` à l'appli openWakeWord de HA, et les capacités
annoncent "Hey Jarvis" : le mot de la configuration n'y est pas utilisé. Dans tous les modes, l'appli peut
guetter le mot elle-même (préférence `reveil` à `appareil`) et n'envoyer le son qu'après la détection.

### LLM

Le cerveau par défaut diffère selon l'endroit où on le lit : `charger_env()` prend `local` quand
`LLM_FOURNISSEUR` est absent, alors que `poc/.env.exemple` et `Lancer le serveur satellite.bat` règlent
`claude`. L'appli Home Assistant force `claude` (pas de carte graphique). Le corps envoyé au LLM local contient
`cache_prompt` et `chat_template_kwargs`, propres à llama-server : un autre serveur compatible OpenAI peut les
ignorer.

### Pistes non codées

Aucune voix en ligne n'est branchée. Une voix compatible avec `POST /v1/audio/speech` d'OpenAI se brancherait
comme la transcription en ligne, à côté de `synthetiser_ha` dans `poc/serveur_satellite.py`.

### Ce qui reste sur le réseau de la maison

Le son des satellites, les images de la caméra (vision sur le PC) et les données de santé ne circulent qu'entre
les appareils et le serveur, en wss pour les images et la santé. Le son ne sort de la maison que par la
transcription en ligne, choisie explicitement. Le texte de la demande ne sort que vers Claude, quand le
dictionnaire ne l'a pas compris. Les pochettes d'album en `https://` sont téléchargées directement par l'appli
(`Maison.pochette`), les autres passent par la passerelle.

Le serveur n'accepte de connexion que depuis les réseaux de `acces.reseaux_autorises` (réseaux privés et tailnet par défaut). Les noms d'hôte de `reseau.android_hotes_pc` et `android_hotes_ha` ne servent qu'à retrouver le serveur sur le réseau, avec la même clé épinglée.
