# Architecture du moteur

Ce document s'adresse au développeur qui reprend le projet. Il décrit les blocs du moteur, le trajet d'une
phrase, le protocole entre les appareils et le serveur, la sécurité, la façon d'étendre l'ensemble, puis les
tests, les versions et le garde-fou git. Il a été écrit pour le serveur 0.33.0 et l'appli 0.35.0. Les changements
apportés depuis (sources météo désactivables, mot de réveil lu dans la configuration, schémas clair et sombre)
sont décrits dans `VERSION.md`. L'inventaire des modèles, machine par machine, est dans `QUOI-TOURNE-OU.md`.

Le moteur ne contient aucune donnée réelle. Tout ce qui décrit un logement est lu dans le dossier de
configuration, dans cet ordre (`dossier_config()` de `poc/maison.py`) :

1. la variable `ASSISTANT_VOCAL_CONFIG`, ou son ancien nom `MAISON_DOSSIER`,
2. `config/` à la racine du dépôt, ignoré par git,
3. l'ancien dossier `maison/`, tant que `config/` n'existe pas.

Sans `maison.json` lisible, le serveur s'arrête (`maison.charger`) et la compilation d'un APK échoue. Les
exemples de ce document viennent de `config-exemple/`, dont toutes les valeurs sont fictives.

## 1. Les grands blocs

### Vue d'ensemble

```
 Tablette ou téléphone (appli assistant.vocal.jarvis)
   micro 16 kHz, réveil, VAD, Canary, dictionnaire, écran ambiant, vision, page 3D
        |                                   |
        | wss 8766 (ou ws 8765)             | wss 8766
        v                                   v
 Serveur du PC (poc/, profil pc)      Appli Home Assistant (ha-app/, profil ha)
   Canary, Piper, openWakeWord,         Speech-to-Phrase, Piper, openWakeWord de HA
   vision, relais santé, LLM local      par Wyoming, Claude seulement
        |                                   |
        +------------- HTTP ----------------+
                         v
                  Home Assistant (API REST)
```

### Serveur Python, `poc/`

| Fichier | Rôle | Éléments principaux |
|---|---|---|
| `assistant.py` | Chaîne de compréhension et d'action, utilisable seule en ligne de commande (`--texte`, `--clavier`, `--reveil`, `--essai`, `--claude`, `--version`) | `VERSION`, `SERVICES_PERMIS`, `OUTILS`, `CONSIGNE`, `HomeAssistant`, `Cerveau` (LLM compatible OpenAI), `CerveauClaude`, `Transcripteur` (Canary), `Voix` (Piper), `Reveil`, `Oreille`, `Assistant`, `garde_fou_volume`, `garde_fou_musique`, journaux |
| `dictionnaire.py` | Phrases de `commandes.yaml` développées en formes exactes, recherche tolérante, phrases apprises | `normaliser`, `epurer`, `developper`, `Personnes`, `Dictionnaire` (`chercher`, `apprendre`, `oublier`), `SEUIL_FLOU = 0.88` |
| `securite.py` | Sécurité écrite en dur, copiée dans `Securite.kt` | `SECURITE_ACTIVE`, `PROTEGER_OCCUPANT`, `HEURE_CALME_ACTIVE`, `VOLUME_MAX`, `verifier`, `phrase_protegee`, `entites_permises` |
| `serveur_satellite.py` | Serveur WebSocket des satellites, les deux profils | `Moteur` (ressources partagées, capacités, bascules), `Satellite` (machine à états d'une connexion), `Arbitre`, `Calibration`, `passerelle_ha`, `CanalWyoming`, `ReveilWyoming`, `transcrire_api`, `transcrire_ha`, `synthetiser_ha`, `servir` |
| `acces.py` | Jetons, appairage, certificat, passerelle Home Assistant | `Appareils`, `Amorcage`, `jeton_de_la_requete`, `certificat`, `reseaux_autorises`, `adresse_autorisee`, `adresse_locale`, `est_administrateur`, `verifier_requete_ha`, `refus_launch_app`, `DOMAINES_INTERDITS` |
| `maison.py` | Lecture du dossier de configuration | `DOSSIER`, `CONFIG`, `reseau()`, `liste()`, `NOM_PROPRIETAIRE`, `CLE_PROPRIETAIRE` |
| `vad.py` | Silero VAD v5 | `creer()`, `Vad.parole()` |
| `vision.py` | Visages pour la tablette (YuNet, SFace) | `Vision.analyser`, `traiter_message`, `regard` |
| `sante.py`, `sante_hist.py` | Relais santé (résumé, puis historique des onglets) | `depuis_env`, `refus`, `personnes_permises`, contrôles Tailscale |
| `meteo_mer.py`, `vent_mesure.py` | Météo marine et vent mesuré du plan d'eau | `MeteoMer`, `VentMesure`, `depuis_env()` |
| `outils/` | Téléchargement des modèles, mesures, bancs, faux téléphone, essais du protocole | `telecharger_modeles.py`, `mesures.py`, `essai_*.py`, `banc_*.py`, `faux_telephone.py` |
| `tests/` | Tests pytest sur `config-exemple/` | voir la partie 6 |

Les données vivantes ne sont pas de la configuration. Elles vont dans le dossier `JARVIS_DONNEES` (`poc/` par
défaut, `/data` dans l'appli Home Assistant) : `journal/latences.csv` (durées seules, sans phrase), `journal/assistant-AAAA-MM-JJ.jsonl` (historique avec phrases, purgé après `journal.conserver_jours`), `journal/manques.jsonl`,
`journal/retours.jsonl`, `journal/musique.jsonl`, `commandes_apprises.yaml` (et son export pour l'appli,
`genere/android/dictionnaire_appris.json`), `appareils.json` et le certificat
`tls/cert.pem`, `tls/cle.pem`.

Variables lues par le serveur, en plus de celles de `poc/.env.exemple` :

| Variable | Effet | Défaut |
|---|---|---|
| `JARVIS_PROFIL` | `pc` ou `ha` | `pc` |
| `JARVIS_DONNEES` | Dossier des données vivantes | `poc/` |
| `JARVIS_PORT_TLS` | Port chiffré | `8766` |
| `JARVIS_ANCIEN_ACCES` | `?jeton=` accepté sur le port en clair tant qu'il vaut autre chose que `0`. Réglé et non vide, il l'emporte sur `acces.ancien_acces` | absent (alors `acces.ancien_acces`, permis par défaut) |
| `JARVIS_WYOMING_SSH` | Profil `ha` testé depuis le PC, Wyoming par SSH | absent |
| `SEUIL_REVEIL` | Score du mot de réveil côté serveur | `0.5` |
| `VAD_MODELE` | Chemin du modèle Silero | `poc/modeles/silero_vad.onnx` |
| `VOIX` | Voix Piper | `poc/voix/fr_FR-siwis-medium.onnx` |
| `CLAUDE_MODELE` | Modèle de `CerveauClaude` | `claude-haiku-5-5` |

### Appli Android, `android/`

Paquet `assistant.vocal.jarvis`, sources dans `android/app/src/main/java/assistant/vocal/jarvis/`. Toute l'interface est
construite en code, sans XML de mise en page.

| Famille | Fichiers |
|---|---|
| Activités | `MainActivity` (lanceur, réglages, panneaux), `VisagesActivity` (enrôlement des visages), `HistoriqueActivity`, `AppareilsActivity` (appairage, amorçage, diagnostic) |
| Service et réseau | `SatelliteService` (service au premier plan de type micro et caméra : micro, connexion, lecture des WAV, chien de garde), `Confiance` (wss, épinglage, jeton), `Decouverte` (ordre d'essai des cibles), `PasserelleHa` (connexion vers l'appli Home Assistant), `Transcription.kt` (`OuTranscrire`, `TranscriptionPc`), `Etat` (état partagé et rappels `Etat.action*`), `Maison` (lecture de Home Assistant pour l'écran), `Station` et `RecepteurDemarrage` (démarrage avec la tablette), `RecepteurBanc` (essais par adb, permission `DUMP`) |
| Moteur local | `MoteurLocal` (chaîne complète du mode Cet appareil), `ReveilLocal`, `VadSilero`, `CanaryLocal`, `DictionnaireLocal`, `CerveauAppareil` et `ModeleLiteRt`, `MeteoQuestion`, `Securite`, `ConfigMaison` |
| Écran ambiant | `EcranAmbiant`, `Accueil`, `AccueilDisposition`, `PlanAmbiant`, `Veille`, `VueAod`, `LumiereAmbiante`, `Souffle`, `VueOrbe`, `VuesAccueil`, `CarteEnCours` |
| Panneaux | Météo (`EcranMeteo` avec les pages Terre, Vent et Mer, `EcranMer`, `EcranVent`, `MeteoTexte`, `MeteoMer`, `MeteoVent`, `Previsions`, `PictosMeteo`, `CheminSvg`), Santé (`EcranSante`, `OngletsSante`, `GraphesSante`, `Sante`, `SanteAccueil`, `SanteDetail`, `SanteHisto`, `SanteDemo`), Musique (`EcranMusique`, `SortieSon`), Maison (`EcranMaison`, `ReglageLampe` (volet Blanc et Couleur, `Cadence`), `Appareils`, `MaisonEnGrand`, `VueMaisonGrand`) |
| Page 3D | `Maison3dView` (WebView), `Maison3dPont` (scripts vers la page), `Maison3d` (état des lampes) |
| Vision | `Vision.kt` (`MoteurVisageLocal`, `VisionPc`, `ProfilsVisages`), `Reconnaissance` (logique pure : seuils, votes, regard) |
| Outils et apparence | `TestReveil`, `TestCanary`, `TestLlm`, `Palette`, `Couleur`, `Apparence`, `Decor`, `Polices`, `SonsEcoute`, `HistoriqueLisible`, `VueHistorique` |

`app/build.gradle.kts` relie l'appli à la configuration : `maison.json` entier devient
`BuildConfig.MAISON_JSON`, `genere/android/` devient un dossier d'assets (dictionnaire, page 3D, trait de côte),
la tâche `copierReveil` copie `reveil/<mot>.onnx` et sa licence, et `SATELLITE_JETON` est lu dans
`poc/.env` pour devenir `BuildConfig.JETON_DEFAUT`. Les adresses par défaut viennent de
`reseau.android_serveur_pc` et `reseau.android_serveur_ha`. Si l'IP change, l'appli essaie aussi les noms d'hôte de `android_hotes_pc` et `android_hotes_ha` (voir `Decouverte.kt`).

### Appli Home Assistant, `ha-app/`

| Fichier | Rôle |
|---|---|
| `jarvis/config.yaml` | Manifeste de l'appli `local_jarvis` : version, `arch: amd64` et `aarch64`, ports 8765 et 8766, options (`anthropic_api_key`, `satellite_jeton`, `essai`, `ancien_acces`, `stt_api_*`) |
| `jarvis/Dockerfile`, `jarvis/requirements.txt` | Image `python:5.12-slim`, sans OpenCV ni modèle de transcription |
| `jarvis/app/demarrage.py` | Options vers variables : `JARVIS_PROFIL=ha`, `JARVIS_DONNEES=/data`, `ASSISTANT_VOCAL_CONFIG=/app/config`, `HA_URL=http://supervisor/core`, jeton du superviseur, `LLM_FOURNISSEUR=claude`, puis lance `serveur_satellite.py` |
| `deployer.sh` | Copie les modules de `poc/`, `maison.json`, `commandes.yaml`, Silero et les phrases apprises, puis les pousse par SSH (`reseau.ssh_ha`) dans `/local_apps/jarvis` |
| `configurer-options.py` | Envoie les options depuis `poc/.env` par l'API du superviseur, sans afficher les secrets |
| `configurer-ha.py` | Pousse dans Home Assistant les alias, l'exposition à Assist et une automatisation à déclencheurs vocaux tirée du dictionnaire, pour que Speech-to-Phrase connaisse les commandes |

### Générateurs, `carte/`

`carte/generer_plan.py` produit `plan.svg` et `plan.png` à partir de `carte/pieces.json` de la configuration
(Pillow requis). `carte/3d/generer_3d.py` assemble `vue3d_modele.html`, three.js r170 (`vendor/`) et les
fichiers `pieces.json`, `meubles.json`, `lampes.json`, et écrit `genere/android/maison3d/vue3d.html` dans la
configuration, plus `carte/modele.glb`. La page tourne hors ligne dans la WebView de l'appli
(`file:///android_asset/maison3d/vue3d.html`, chargements réseau bloqués). Elle parle à Kotlin par l'objet
`Maison3dAndroid` (`pret`, `battement`, `contextePerdu`, `basculer`) et reçoit des appels
`window.maison3d.*` construits par `Maison3dPont`.

### Les trois modes de fonctionnement

L'appli range son choix dans la préférence `serveur` (fichier de préférences `satellite`) : `pc` par défaut,
`ha` ou `local` (`SatelliteService.serveurChoisi`).

| Mode | Préférence | Qui écoute | Qui transcrit | Qui décide | Qui parle |
|---|---|---|---|---|---|
| Cet appareil | `local` | L'appareil (`ReveilLocal`, `VadSilero`) | L'appareil (Canary), ou en déporté le PC, Home Assistant ou le service en ligne | L'appareil (dictionnaire, puis LLM : Claude par l'appli Home Assistant ou LiteRT-LM local) | Synthèse d'Android |
| Serveur du PC | `pc` | Le serveur, ou l'appareil s'il guette le mot lui-même | Le PC | Le PC | Piper sur le PC, WAV joué par l'appareil |
| Appli Home Assistant | `ha` | Le serveur (openWakeWord de HA), ou l'appareil | Speech-to-Phrase de HA, ou l'API en ligne | L'appli Home Assistant, Claude seulement | Piper de HA |

En mode Cet appareil, la seule connexion obligatoire est celle de la passerelle vers l'appli Home Assistant
(`PasserelleHa`) : elle porte les requêtes à Home Assistant et le LLM Claude. La connexion au PC
(`TranscriptionPc`, `VisionPc`) ne sert qu'à la transcription déportée, à la vision sur le PC et à la santé.

### Différences entre les profils `pc` et `ha`

| Sujet | Profil `pc` | Profil `ha` |
|---|---|---|
| Accès à Home Assistant | `HA_URL` et `HA_TOKEN` de `poc/.env` | `http://supervisor/core` et `SUPERVISOR_TOKEN` |
| Mot de réveil | openWakeWord local, un modèle par connexion, mot de `reveil.mot` (puis `MOT_REVEIL`), repli `hey_jarvis` | Appli openWakeWord de HA par Wyoming, toujours `hey_jarvis` |
| Transcription | Canary chargé au démarrage, plus `ha_stp`, `ha_whisper` (par `ssh nc`) et `api` si configurée | `ha_stp`, `ha_whisper`, et `api` si configurée |
| Voix | Piper chargé au démarrage | Appli Piper de HA |
| Cerveau | `claude` ou `local`, bascule à chaud | `claude` seulement |
| Vision | Si OpenCV et les deux modèles sont là | Jamais |
| Santé | Si `SANTE_JETON` est réglé | Jamais |
| Météo marine, vent mesuré | Si les sections de `maison.json` sont actives | Idem |
| Calibrage `--calibrer` | Possible | Non (pas de score local) |

### Services en ligne facultatifs

Deux étapes ont une alternative en ligne codée. La transcription passe par tout service compatible avec
`POST /v1/audio/transcriptions` d'OpenAI (`transcrire_api`), réglé par `STT_API_CLE` (obligatoire, plus de 10
caractères), `STT_API_URL`, `STT_API_MODELE` et `STT_API_NOM`, avec Voxtral de Mistral par défaut
(`STT_API_DEFAUTS`). Le cerveau passe par Claude avec `LLM_FOURNISSEUR=claude`. En profil `pc`, Canary et
Piper sont chargés au démarrage quoi qu'il arrive : la transcription en ligne n'est qu'un choix fait depuis
l'appli (`Moteur.changer_stt`), avec Canary en repli. En profil `ha`, la clé se règle dans les options de
l'appli Home Assistant (`stt_api_cle`). L'appli Android ne garde aucune clé : son lieu "En ligne" passe par le
serveur qui annonce `api`.

Piste non codée : une voix en ligne compatible avec `POST /v1/audio/speech` d'OpenAI se brancherait de la même
façon, par une fonction voisine de `synthetiser_ha` choisie dans `Moteur.traiter`, sa clé lue dans `poc/.env`
et dans les options de l'appli Home Assistant.

## 2. Le trajet d'une phrase

### Serveur du PC, appareil en satellite

| Étape | Où | Fichiers et fonctions |
|---|---|---|
| Capture | Appareil | `SatelliteService` lit le micro à 16 kHz par blocs de 1280 échantillons (80 ms) et envoie le PCM 16 bits en binaire. Avec la préférence `reveil` à `appareil`, `ReveilLocal` guette le mot et le service envoie `{"type":"reveil","score"}` avant de transmettre le son |
| Réveil | Serveur | `Satellite.recevoir_audio` puis `Satellite.bloc` : `Model.predict` d'openWakeWord sur chaque bloc, seuil `SEUIL_REVEIL`. `Arbitre.demander` choisit un seul appareil quand plusieurs ont entendu (fenêtre de 250 ms, échos ignorés 1,5 s). `commencer_ecoute` envoie `ecoute` et ignore le son 0,6 ou 0,9 s, le temps du son de début |
| Fin de phrase | Serveur | Silero (`vad.creer`) : fin après 0,45 s de silence (0,8 s au seuil d'énergie), 6 s au plus pour commencer, 12 s au plus en tout, 320 ms gardées avant la parole |
| Transcription | Serveur | `Satellite.terminer_phrase` envoie `reflexion`, puis `Moteur.traiter` appelle `Moteur.transcrire` : Canary (`Transcripteur.transcrire`), Wyoming (`transcrire_ha`) ou API (`transcrire_api`). Speech-to-Phrase vide se replie sur l'API si elle est configurée |
| Dictionnaire | Serveur | `Assistant._traiter` : `epurer`, correction vocale d'une leçon récente ("non", "annule" dans les 30 s), `Dictionnaire.chercher`, puis `Personnes.appliquer` pour "ma chambre" selon la personne reconnue |
| Sécurité | Serveur | `securite.verifier` sur chaque action, avec la personne reconnue |
| Action | Serveur | `Assistant.executer` : `POST /api/services/<domaine>/<service>`, puis `HomeAssistant.confirmer` relit l'état (1,5 s au plus pour une lumière, une prise, un ventilateur, 12 s pour un script de musique) |
| Intentions de HA | Serveur | `HomeAssistant.conversation` est sautée tant que `SECURITE_ACTIVE` vaut vrai, ce qui est le cas en dur : Assist agirait sans qu'on voie sa cible |
| LLM | Serveur | `securite.phrase_protegee`, puis `Cerveau.repondre` ou `CerveauClaude.repondre` : six tours au plus, outils `appeler_service`, `jouer_musique`, `lire_etat`. `HomeAssistant.service` applique la liste blanche, la sécurité, la liste fermée des entités, puis confirme l'état (3 s). `garde_fou_volume` et `garde_fou_musique` corrigent les excès du modèle. `Assistant.apprendre` range la phrase réussie dans `commandes_apprises.yaml` |
| Journal | Serveur | `journaliser` (une ligne anonyme de `latences.csv` : voie, durées, rôle, issue, sans phrase, et une entrée de l'historique `assistant-AAAA-MM-JJ.jsonl`), `manques.jsonl` si le dictionnaire n'a rien trouvé |
| Réponse | Serveur | `Voix.synthetiser` (Piper), `wav_de`, message `reponse` puis le WAV en binaire. `historique_ajout` est diffusé aux seuls appareils qui ont le droit de voir l'entrée (`entrees_visibles`, règle de CONFIGURER.md). Le serveur reste sourd jusqu'à `lecture_finie`, ou durée du WAV plus 3 s |
| Lecture et écran | Appareil | `SatelliteService.jouerWav` (AudioTrack), puis `{"type":"lecture_finie"}`. `Etat` alimente l'orbe, la carte de réponse et l'historique |

### Appli Home Assistant

Même trajet, avec trois différences : le son part vers l'appli openWakeWord de HA (`ReveilWyoming`), la phrase
vers Speech-to-Phrase (`transcrire_ha`), et la réponse est dite par l'appli Piper de HA (`synthetiser_ha`). Le
cerveau est toujours Claude.

### Cet appareil

| Étape | Fichiers et fonctions |
|---|---|
| Réveil et fin de phrase | `MoteurLocal.bloc`, `ReveilLocal`, `commencerEcoute`, `ecouter` avec `VadSilero` (0,45 s de silence, 8 s pour commencer, 12 s au plus). Pendant l'écoute, une passe Canary toutes les 1,2 s affiche le texte partiel, sans rien décider dessus |
| Transcription | `MoteurLocal.traiter` : `transcrireDeporte` selon `lieuTranscription` (message `transcrire`, 8 s au plus), sinon `CanaryLocal.transcrire` |
| Questions sans LLM | `MoteurLocal.comprendre` : `repondreMeteo` (`MeteoQuestion`), puis `Apparence.commande` (palette des écrans) |
| Dictionnaire et sécurité | `DictionnaireLocal.parcourir`, `personnes.appliquer`, `Securite.verifier` |
| Action | `MoteurLocal.executer` : `Securite.monterSansDepasser`, `Securite.plafonner`, `Securite.verifier`, puis `PasserelleHa.requete("POST", "/api/services/...")`. Le serveur refait `acces.verifier_requete_ha` et `securite.verifier` |
| Intentions de HA | Sautées tant que `Securite.SECURITE_ACTIVE` vaut vrai |
| LLM | `demanderLlm` : `Securite.phraseProtegee`, puis `CerveauAppareil.decider` (LiteRT-LM) avec le choix `local`, sinon `{"type":"llm"}` par la passerelle, 45 s au plus |
| Réponse | `terminer` : `TextToSpeech.speak`, mise à jour d'`Etat`, `noterManque` envoie le raté au serveur |

### Ordres de grandeur

Les chiffres viennent du code et des journaux de versions d'avant la séparation du moteur. Ils ont été
mesurés sur une installation d'exemple : un PC de bureau, une tablette Android d'entrée de gamme, un téléphone
Android haut de gamme et un Home Assistant sur un mini-PC à processeur petit serveur.

| Étape | Durée typique |
|---|---|
| Mot de réveil sur l'appareil | 25 ms de calcul par bloc de 80 ms (tablette, un fil, XNNPACK) |
| Arbitrage entre appareils | 250 ms quand plusieurs appareils sont au repos, rien sinon |
| Fin de phrase | 0,45 s de silence avec Silero |
| Canary sur le PC | 0,2 à 0,7 s par commande |
| Canary sur l'appareil | 0,44 à 0,61 s (téléphone haut de gamme), 0,7 à 1,1 s (tablette) pour 3 s de parole |
| Speech-to-Phrase | 0,7 à 1,5 s, autour de 0,5 s de plus depuis le PC par SSH |
| Dictionnaire | Quelques dizaines de millisecondes, 0,07 à 0,11 s pour comprendre une commande |
| Lampe qui réagit | 0,2 s après l'ordre, confirmation relue toutes les 0,15 s |
| Claude Haiku | 1,9 à 2,5 s par commande, environ 2,7 s depuis l'appareil par l'appli Home Assistant |
| LLM local Qwen3.5-9B | 2,7 à 3,8 s par commande |
| Piper | 0,2 s sur le PC, 0,7 s sur le mini-PC petit serveur |
| Vision | 16 ms par image sur le PC (44 ms aller-retour), 27 à 28 ms par image sur la tablette |

Par addition, une commande du dictionnaire sur le serveur du PC répond environ 1 à 1,5 s après la fin de la
parole, et une commande qui passe par Claude 3 à 4 s. Ce sont des estimations, pas des mesures de bout en bout.
Le journal `latences.csv` donne les vraies valeurs de chaque commande (`stt_s`, `cerveau_s`, `tts_s`).

## 3. Le protocole entre les satellites et le serveur

### Connexion

| Point | Règle | Où |
|---|---|---|
| Ports | 8765 en clair (`--port`, 0 le coupe), 8766 chiffré (`--port-tls` ou `JARVIS_PORT_TLS`) | `serveur_satellite.main` |
| Taille et vie | Messages de 4 Mio au plus (`max_size=2**22`), ping toutes les 20 s | `servir` |
| Jeton | En-tête `Authorization: Bearer <jeton>`. L'ancienne forme `?jeton=` n'est acceptée que sur le port en clair et tant que l'ancien accès est permis (`JARVIS_ANCIEN_ACCES`, sinon `acces.ancien_acces`). Le jeton passe de préférence par l'en-tête | `acces.jeton_de_la_requete` |
| Jetons valables | `SATELLITE_JETON` (le propriétaire, clé `proprietaire.cle`), `SATELLITE_JETON_<NOM>` (16 caractères au moins), et les appareils appairés. Le serveur ne garde que l'empreinte SHA-256, comparée à temps constant | `acces.Appareils.identite` |
| Réseaux autorisés | Section `acces` de `maison.json` : `ecoute` (adresses d'écoute, `0.0.0.0` par défaut) et `reseaux_autorises` (liste de CIDR, `*` ou `0.0.0.0/0` pour ouvrir à tous). Sans liste, seuls passent le bouclage, les réseaux privés, le lien local, le tailnet (`100.64.0.0/10`) et les IPv6 locales. Une entrée illisible est ignorée avec un message, une IPv4 mappée en IPv6 est ramenée à l'IPv4 | `acces.reseaux_autorises`, `acces.adresse_autorisee` |
| Refus | Fermeture avec le code 4003 (réseau non autorisé, y compris sur `/appairage`) ou 4001 ("jeton absent", "jeton invalide" ou "appareil révoqué"). Le journal note la cause et les 8 premiers caractères de l'empreinte. `Appareils.refus` garde les 20 derniers refus (cause, adresse, heure) | `servir.accueil` |
| Rôles | Les types `appareils`, `appairer`, `refuser_appareil`, `revoquer`, `transcription`, `mode`, `cerveau` et `manques` sont réservés aux administrateurs : le propriétaire (`proprietaire.cle`) et les identités de `acces.administrateurs` (par exemple `appareil:ab12cd34`). Un autre appareil reçoit `{"etat":"refuse","type":...,"message":"réservé à un administrateur"}` | `acces.est_administrateur`, `serveur_satellite.TYPES_ADMINISTRATEUR` |
| Certificat | Auto-signé, clé EC P-256, valable 10 ans, créé au premier démarrage dans `tls/` | `acces.certificat` |
| Épinglage | L'appli retient l'empreinte SHA-256 de la clé publique à la première connexion (`empreinte_<hôte:port>`), refuse ensuite toute autre clé et coupe si l'empreinte annoncée dans `capacites` diffère | `Confiance.kt`, `SatelliteService.traiterTexte` |
| Repli en clair | `ws://hôte:8765` n'est tenté que si aucune clé n'a encore été retenue pour l'adresse chiffrée | `Confiance.repli` |
| Appairage | `wss://<hôte>:8766/appairage?nom=<nom>`, sans jeton, port chiffré seulement. Code à 4 chiffres, accepté par un administrateur, 300 s au plus. Le jeton n'est envoyé qu'une fois | `servir.appairage`, `AppareilsActivity` |
| Amorçage | Premier appairage sans jeton fixe : tant qu'aucun administrateur n'est connecté et que la demande vient du réseau local (privé ou bouclage, jamais le tailnet), le serveur écrit dans son journal un code à 8 chiffres (« CODE D'AMORÇAGE pour <nom> ») et le message `appairage` porte `"amorcage": true`. L'appareil renvoie `{"type":"amorcage","code":...}`. Code à usage unique, valable 600 s, 5 essais (la 5e erreur le détruit), un nouveau code au plus par minute. Un échec répond `{"etat":"amorcage_refuse","restant":...}`. Un administrateur qui se connecte ferme l'amorçage | `acces.Amorcage`, `servir.appairage` |

À l'ouverture, le serveur envoie dans l'ordre `repos` (avec `version`), `cerveau`, `mode`, `transcription` et
`capacites`. Un message texte qui n'est pas un objet JSON, ou dont le type est inconnu, est ignoré sans
réponse. Les messages du serveur portent un champ `etat`, ceux de l'appareil un champ `type`.

### Capacités annoncées

`Moteur.capacites(sat)` envoie `{"etat":"capacites", ...}` avec ces champs :

| Champ | Sens |
|---|---|
| `serveur`, `version` | Profil (`pc` ou `ha`) et version du serveur |
| `transcription`, `libelles` | Moteurs proposés (`pc`, `ha_stp`, `ha_whisper`, `api`) et leurs libellés |
| `cerveau` | `["claude", "local"]` en profil `pc`, `["claude"]` en profil `ha` |
| `reveil_appareil`, `mot_reveil` | L'appareil peut guetter le mot lui-même, nom affiché du mot |
| `vad` | `silero` ou `energie` |
| `passerelle_ha`, `previsions` | Home Assistant configuré sur ce serveur (jeton présent) |
| `appairage`, `empreinte` | Port chiffré actif, empreinte de sa clé publique |
| `vision`, `meteo_mer`, `vent_mesure` | Fonctions présentes sur ce serveur |
| `sante`, `sante_historique` | Calculées pour chaque connexion : vraies seulement sur la liaison chiffrée et pour une clé permise |

### Voix et réveil

| Message | Sens | Champs | Réponse ou suite |
|---|---|---|---|
| binaire | Appareil vers serveur | PCM 16 bits, 16 kHz, mono, découpé en blocs de 1280 échantillons à l'arrivée | Ignoré pendant `reflexion` et tant que le serveur est sourd |
| `reveil` | Appareil vers serveur | `score`, `personne` facultatif | Arbitrage, puis `ecoute`, ou `repos` avec `raison: "arbitre"` |
| `parler` | Appareil vers serveur | `personne` facultatif | `ecoute`, au repos seulement |
| `lecture_finie` | Appareil vers serveur | aucun | Serveur sourd 0,3 s, puis guet du mot |
| `repos` | Serveur vers appareil | `version` à l'ouverture, `raison` et `message` après un arbitrage perdu | |
| `ecoute` | Serveur vers appareil | aucun | L'appareil joue le son de début |
| `niveau` | Serveur vers appareil | `score` arrondi, envoyé au-dessus de 0,2 | |
| `reflexion` | Serveur vers appareil | `texte` (vide) | L'appareil joue le son de fin |
| `reponse` | Serveur vers appareil | `texte`, `reponse`, `voie` | Suivi du WAV en binaire si une réponse est dite |
| binaire | Serveur vers appareil | WAV complet, 16 bits | L'appareil le joue puis envoie `lecture_finie` |
| `historique_ajout` | Serveur vers les appareils autorisés à voir l'entrée | `entree` | Filtré par rôle, appareil et personne |

### Transcription et LLM délégués

| Message | Sens | Champs | Réponse |
|---|---|---|---|
| `transcrire` | Appareil vers serveur | `id`, `pcm` (base64, 20 s au plus), `moteur` facultatif | `{"etat":"transcrit","id","texte","moteur","ms"}`, ou `texte` vide avec `erreur` (et `moteurs` si le moteur n'est pas proposé ici) |
| `llm` | Appareil vers serveur | `texte`, `essai` (vrai par défaut), `personne` facultatif | `{"etat":"llm","reponse","actions","cerveau","ms","erreur","essai"}`, sans `id`. Puis `historique_ajout` diffusé |

### Réglages du serveur

| Message | Champs | Réponse |
|---|---|---|
| `transcription` | `choix` parmi les moteurs annoncés | `{"etat":"transcription","actif","message"}` diffusé à tous |
| `mode` | `choix` : `essai` ou `reel` | `{"etat":"mode","actif","message"}` diffusé à tous |
| `cerveau` | `choix` : `claude` ou `local` | `{"etat":"cerveau","actif","pret","message"}` diffusé deux fois (`pret` faux puis vrai). Le choix `local` lance `poc/lancer-llm.ps1` et attend 90 s au plus, sinon reste sur Claude |

### Historique et journaux

| Message | Champs | Réponse |
|---|---|---|
| `historique` | `n` (1 à 200, 30 par défaut) | `{"etat":"historique","entrees"}`. Chaque entrée : `heure`, `date`, `essai`, `entendu`, `compris_par`, `detail_voie`, `fait`, `erreur`, `reponse`, `duree` |
| `manque` | `texte`, `epure`, `cle`, `regles`, `candidats`, `traite_par`, `actions`, `reponse`, `essai`, `appareil`, `dictionnaire`, `test`, `personne` | `{"etat":"manque","message":"noté"}`, ligne ajoutée à `manques.jsonl` |
| `retour` | `verdict` (`bien` ou autre valeur, prise pour `mauvais`), `date`, `heure`, `entendu`, `compris_par`, `detail`, `fait`, `reponse`, `essai`, `personne` | `{"etat":"retour","message"}`. Une phrase apprise jugée mauvaise est oubliée |
| `manques` | `n` (1 à 2000, 200 par défaut) | `{"etat":"manques","manques","retours"}` |

### Passerelle Home Assistant

| Message | Champs | Réponse |
|---|---|---|
| `ha` | `id`, `methode`, `chemin`, `corps`, `personne` facultatif | `{"etat":"ha","id","code","corps"}`. Pour une image : `corps` vide, `type` et `base64` (2 Mo au plus, sinon code 413). Codes propres : 503 sans Home Assistant, 403 refus de la passerelle, 502 erreur de transport |

Chemins permis (`acces.verifier_requete_ha`) : `GET /api/states` et `GET /api/states/<entité>`,
`GET /api/media_player_proxy/media_player.<nom>`, `POST /api/template`, `POST /api/conversation/process`,
`POST /api/services/weather/get_forecasts?return_response` avec exactement `{"entity_id": "weather.<nom>",
"type": "hourly" | "daily" | "twice_daily"}`, et `POST /api/services/<domaine>/<service>` hors des domaines
interdits, après `securite.verifier`.

### Appareils et appairage

| Message | Sens | Champs | Réponse |
|---|---|---|---|
| `appareils` | Administrateur vers serveur | aucun | `{"etat":"appareils","attente","appareils","jetons_fixes","roles_jetons_fixes","refus"}`, `refus` donnant les 10 derniers refus, chaque appareil portant son `role` effectif et sa `personne` (0.38.0). Le code d'appairage n'y figure que pour un administrateur |
| `appairer`, `refuser_appareil`, `revoquer` | Administrateur vers serveur | `id` (`appairer` accepte `role` parmi `habitant`, `partage`, `invite` et `personne`) | `appareils`. Une révocation ferme aussitôt les connexions de cet appareil (code 4001). `administrateur` n'est jamais attribuable (refus) |
| `changer_role`, `changer_personne` | Administrateur vers serveur | `id`, `role` ou `personne` | `appareils`, ou un refus. La personne doit être un habitant connu. Tout message réservé à un administrateur est refusé aux autres rôles (rôle effectif, `acces.role_effectif`) |
| `appairage_demande` | Serveur vers les administrateurs | `id`, `nom`, `code` | L'appli affiche une notification |
| `appairage` | Serveur vers le nouvel appareil, sur `/appairage` | `code`, `id`, `message` | |
| `appaire` | Idem | `jeton`, `nom` | Connexion fermée ensuite |
| `appairage_refuse` | Idem | aucun | Connexion fermée |
| `amorcage` | Nouvel appareil vers serveur, sur `/appairage` | `code` (8 chiffres) | `appaire`, ou `amorcage_refuse` avec `restant` |

### Vision, santé, météo

| Message | Champs | Réponse | Condition |
|---|---|---|---|
| `vision` | `id`, `jpeg` (base64, 4 000 000 caractères au plus) | `{"etat":"vision","id","ms","largeur","hauteur","visages"}`, chaque visage avec `boite`, `score`, `points`, `regard`, `lacet`, `empreinte`. Ou `erreur` | Profil `pc` avec OpenCV. L'appli n'envoie d'image que sur wss |
| `sante` | `id` | `{"etat":"sante","id","donnees"}` ou `erreur` | Liaison chiffrée et clé de `SANTE_PERSONNES` |
| `sante_periode` | `id`, `jours` (7, 30, 90 ou 365) | `{"etat":"sante_periode","id","donnees"}` ou `erreur` | Idem, historique actif |
| `sante_seances` | `id`, `jours`, `sport` | Idem avec son type | Idem |
| `sante_seance` | `id`, `seance_id` | Idem | Idem |
| `sante_records` | `id` | Idem | Idem |
| `sante_jour` | `id`, `date` (`AAAA-MM-JJ`) | Idem | Idem |
| `meteo_mer` | `id` | `{"etat":"meteo_mer","id","donnees"}` ou `erreur` | Section `mer` active. Servi à toute connexion |
| `vent_mesure` | `id` | `{"etat":"vent_mesure","id","donnees"}` ou `erreur` | Sections `mer` et `vent` actives. Servi à toute connexion |

La forme détaillée de `donnees` est décrite dans les docstrings de `sante.py`, `sante_hist.py`, `meteo_mer.py`
et `vent_mesure.py`.

## 4. La sécurité

### Sécurité en dur

`poc/securite.py` et `android/.../Securite.kt` appliquent les mêmes règles avec les mêmes listes, lues dans la
section `securite` de `maison.json`. Les cas communs sont dans `poc/tests/cas_securite.json`, vérifiés par
`test_securite.py` et `SecuriteTest.kt`.

| Règle | Drapeau | État actuel |
|---|---|---|
| Ne jamais toucher à ce qui appartient à l'occupant protégé (`nom_occupant`, `mots_proteges`, `zones_protegees`, `entites_protegees`), ni viser `all` ou une de ses zones | `PROTEGER_OCCUPANT` | Levée (`False`) |
| Pas de son dans le salon (`son_salon`) pendant les heures calmes (`heures_calmes`, de 0 à 9 h par défaut), sauf éteindre, mettre en pause, arrêter, baisser, couper | `HEURE_CALME_ACTIVE` | Levée (`False`) |
| Exception : la personne reconnue seule par la tablette pilote ses propres lumières (`permis_personne`) | suit la règle 1 | Sans effet tant que la règle 1 est levée |
| Refus de viser un appareil par `device_id`, un étage par `floor_id` ou une étiquette par `label_id` | `SECURITE_ACTIVE` | Actif |
| Refus de `media_player.volume_up` quand un plafond de volume est réglé | `SECURITE_ACTIVE` | Sans effet sans plafond |
| Volume plafonné à `securite.plafond_volume` de `maison.json` (`VOLUME_MAX`, pourcentage, 100 par défaut, soit aucun plafond) | aucun | Toujours lu, aucun plafond par défaut |

Remettre une règle demande de passer son drapeau à `True` dans les deux fichiers, puis d'adapter les cas
communs. Le plafond du volume se règle dans la configuration, pas dans le code : `securite.plafond_volume`
(de 0 à 100, absent ou 100 pour aucun plafond, une valeur illisible garde 50 par prudence). `securite.verifier`
plafonne le volume sur place. Côté Kotlin, le plafond est appliqué par `Securite.plafonner` avant l'envoi, et
`Securite.monterSansDepasser` change un `volume_up` en `volume_set` 5 points plus haut, borné par le plafond,
quand le volume actuel est connu. Sans plafond, `volume_up` est aussi permis au LLM du serveur
(`SERVICES_PERMIS`), et les écrans de l'appli ne dessinent ni trait ni mention de plafond.

### Autres verrous du serveur

| Verrou | Où |
|---|---|
| Liste blanche des services (décision D6, 0.37.0) : tout ce que Home Assistant expose pour les domaines d'équipement (lumières, interrupteurs, ventilateurs, volets, climat, humidificateurs, chauffe-eau, vannes, sirènes, lecteurs, Music Assistant, aspirateurs, tondeuses, caméras en marche et arrêt, scènes, scripts, automatisations, entrées `input_*`, boutons, nombres, textes, minuteurs, compteurs, `remote`, `select`, `domaine_tele`), complété au démarrage par `GET /api/services` quand Home Assistant répond. Restent refusés : toute cible par `device_id`, `floor_id` ou `label_id`, les `DOMAINES_INTERDITS` (serrure, alarme, notification, etc.), les rechargements, `camera.snapshot`, `scene.apply`, `media_player.play_media`, `remote.learn_command` et ce qui écrit un fichier ou désigne d'autres appareils dans ses données. `domaine_tele`, `remote` et `select` sont dans `DOMAINES_HORS_LLM` : hors du contexte du LLM et de son outil `appeler_service`, réservés au dictionnaire. `launch_app` n'accepte qu'une URL `https://` | `SERVICES_PERMIS`, `services_depuis_ha`, `HomeAssistant.service` |
| Le LLM ne voit que les domaines de `DOMAINES_CONTEXTE` (`DOMAINES_LLM`, soit lumières, ventilateurs, volets, climat, lecteurs, Music Assistant, aspirateur, scènes, scripts et booléens, plus les capteurs de température, d'humidité, de porte, de fenêtre et la météo) et l'outil `appeler_service` n'accepte que `DOMAINES_OUTIL_LLM` (ces domaines, plus `button` et `switch`) : l'élargissement de la liste blanche ne change rien à ce que voit le modèle, qui reste sans les entités masquées par `llm.masquer` ni les entités protégées | `HomeAssistant.inventaire` |
| Les entités permises partent en `enum` dans le schéma des outils, et toute entité hors de la liste est refusée par le code | `outils_avec_entites`, `HomeAssistant.service` |
| Un changement de volume non demandé dans la phrase est refusé | `garde_fou_volume` |
| "C'est lancé" interdit sans confirmation de la musique | `garde_fou_musique` |
| Phrase qui parle de l'occupant protégé refusée avant tout LLM | `securite.phrase_protegee` |
| Une action sur une entité protégée n'est jamais apprise | `Assistant.apprendre` |
| Assist de Home Assistant sauté | `HomeAssistant.conversation`, `MoteurLocal.comprendre` |
| Passerelle : domaines interdits (`lock`, `alarm_control_panel`, `homeassistant`, `hassio`, `shell_command`, `rest_command`, `python_script`, `notify`, `persistent_notification`, `recorder`, `system_log`), chemins en correspondance exacte | `acces.verifier_requete_ha` |
| Aucun jeton Home Assistant dans l'APK | `PasserelleHa` |

Les actions du dictionnaire ne passent pas par la liste blanche, puisque le dictionnaire est écrit par le
propriétaire, mais elles passent toutes par `securite.verifier`.

### Santé

| Protection | Où |
|---|---|
| Relais en profil `pc` seulement, éteint sans `SANTE_JETON` | `sante.depuis_env` |
| Servi seulement sur la liaison chiffrée et à une clé de `SANTE_PERSONNES` (le propriétaire par défaut). Le refus est décidé avant tout appel à sante-api | `sante.refus`, `Moteur.refus_sante` |
| Le jeton ne part que vers une adresse Tailscale (100.64.0.0/10 ou fd7a:115c:a1e0::/48), vérifiée avant chaque appel, route locale comprise | `sante.adresse_tailscale`, `sante.route_tailscale` |
| Cache en mémoire seulement, aucune valeur dans le journal, une erreur inattendue ne renvoie que le nom de sa classe | `Satellite.repondre_sante` |
| Affichage seulement quand la caméra voit le propriétaire seul, reconnu avec assurance depuis 1 s (`Sante.Garde`, prénom comparé à `ConfigMaison.NOM_PROPRIETAIRE`). Le bloc disparaît dès qu'un autre visage apparaît | `Sante.kt`, `EcranAmbiant.majSante`, `EcranSante.maj` |
| `FLAG_SECURE` posé dès qu'une santé réelle est montrée, captures d'écran impossibles | `MainActivity.majSecurite` |
| Valeurs de démonstration réservées aux compilations de débogage | `SanteDemo.kt`, `MainActivity.demoLumieres` |

### Ce qui ne quitte jamais la maison

Le son du micro, les images de la caméra, les empreintes des visages (`filesDir/visages.json` sur la tablette,
rien sur le serveur), les données de santé, les journaux et les phrases apprises restent entre les appareils,
le serveur et Home Assistant. Deux exceptions sont des choix explicites : la transcription en ligne (le WAV de
la phrase part chez le fournisseur) et le cerveau Claude.

### Ce qui part au LLM

Quand le dictionnaire n'a pas compris, Claude reçoit la consigne (`CONSIGNE`, avec le lieu et les consignes de
`llm` dans `maison.json`), la liste des appareils permis (`entity_id | nom | pièce`), les états des appareils
allumés ou actifs, la date et l'heure, le prénom de la personne reconnue et ce que désigne "ma chambre" pour
elle, la phrase transcrite, les trois derniers échanges (oubliés après 2 min de silence ou au changement de
personne) et les résultats des outils. Il ne reçoit ni son, ni image, ni donnée de santé.

## 5. Étendre le moteur

### Ajouter un écran ou un panneau à l'appli

Il n'existe aucun registre de panneaux : chacun est câblé à la main dans `MainActivity`.

1. Créer `EcranX.kt` avec une `vue` (`GONE` par défaut) et les fonctions `ouvrir()`, `fermer()`, `maj(Etat.Instantane)`
   et `tic()`. Mettre la logique pure dans un `object` testable, sur le modèle de `MeteoTexte` et `EcranMeteo`.
   Placer les éléments avec `CadreMaquette` (maquette de 1280 x 800) et prendre les couleurs dans `Palette`.
2. Dans `EcranAmbiant.kt`, ajouter un rappel `surX` et la zone à toucher.
3. Dans `MainActivity.kt` : le champ `ecranX`, son instanciation dans la pile des panneaux, le branchement de
   `surX`, `ouvrirX` qui ferme les autres panneaux, l'ajout à `panneauOuvert()` et `fermerPanneaux()`, l'appel de
   `maj` dans `afficher()`, de `tic` dans la boucle d'horloge, et la libération à la destruction.
4. Si le panneau a besoin du service, ajouter un rappel `Etat.actionX`, le poser dans `SatelliteService` et le
   remettre à `null` à l'arrêt.
5. Une simple vue ne se déclare pas dans `AndroidManifest.xml`. Une nouvelle activité, si.
6. Écrire `XTest.kt` dans `app/src/test/java/assistant/vocal/jarvis/` pour la logique pure.

### Ajouter un outil au LLM

1. Ajouter sa définition à la fin de `OUTILS` dans `poc/assistant.py`. `outils_avec_entites` modifie
   `OUTILS[0]` (`appeler_service`) et `OUTILS[2]` (`lire_etat`) par leur position.
2. Traiter son appel dans les deux boucles, `Cerveau.repondre` et `CerveauClaude.repondre`, qui sont écrites
   deux fois. Le résultat est un objet JSON, avec `erreur` en cas d'échec.
3. Faire passer toute action par `securite.verifier`, et par une liste blanche si l'outil touche Home Assistant.
4. Décrire son usage dans `CONSIGNE`.
5. Tester sur le modèle de `test_dictionnaire.py` (`test_outils_enum`, `test_outil_musique`) et de
   `test_musique.py`, sans appel réseau réel.

Le LLM de l'appareil n'a pas d'outils : `CerveauAppareil` attend un JSON `{actions, reponse}`. Un outil du
serveur n'y est donc pas disponible.

### Ajouter une commande

1. L'écrire dans `commandes.yaml` de la configuration, section `commandes`, avec `phrases` (`(a|b)` pour une
   alternative, `[mot]` pour un mot facultatif, `{emplacement}` pour une valeur de la section `emplacements`),
   `action` (service exact et cible, une liste pour plusieurs actions) et `reponse`.

   ```yaml
   - phrases: ["(éteins|coupe) [la] (télé|télévision)"]
     action: {service: media_player.turn_off, entity_id: media_player.tele_salon}
     reponse: "J'éteins la télé."
   ```

2. Essayer sans rien exécuter : `python poc/assistant.py --texte "éteins la télé" --essai`.
3. Pour l'appli, régénérer `genere/android/dictionnaire.json` avec `android/outils/exporter_dictionnaire.py`,
   puis recompiler. Pour l'appli Home Assistant, relancer `ha-app/deployer.sh`, et `ha-app/configurer-ha.py`
   pour que Speech-to-Phrase apprenne la phrase.
4. Si la commande doit servir aux tests, l'ajouter aussi à `config-exemple/commandes.yaml`, relancer
   `exporter_dictionnaire.py --exemple` (`test_export_exemple_a_jour` vérifie que l'export est à jour) et
   compléter `test_phrases_connues`.

### Ajouter un message au protocole

1. Serveur : une branche dans `Satellite.recevoir_texte`. Un traitement long passe par
   `asyncio.create_task` et `asyncio.to_thread`. La réponse porte `etat`, et `id` si l'appareil en attend un.
2. Décider de ses conditions : liaison chiffrée (`sat.chiffre`), identité (`sat.identite`), profil. Si la
   fonction est facultative, l'annoncer dans `Moteur.capacites`. Une erreur ne renvoie que le nom de la classe
   de l'exception quand elle peut citer une donnée.
3. Documenter le message dans la docstring de `poc/serveur_satellite.py`.
4. Appli : la réception dans `SatelliteService.traiterTexte` (modes `pc` et `ha`), dans `PasserelleHa`
   (Cet appareil, vers l'appli Home Assistant) ou dans `TranscriptionPc` (Cet appareil, vers le PC). Les
   données vont dans `Etat`.
5. Un nouveau module Python doit être ajouté à la liste `cp` de `ha-app/deployer.sh`.
6. Tests : un test pytest de la logique côté serveur, un test Kotlin de la lecture de la réponse (modèles :
   `MeteoMerTest`, `SanteHistoTest`, `TranscriptionTest`).

## 6. Tests, versions et garde-fou

### Tests

| Côté | Commande | Configuration |
|---|---|---|
| Serveur | `python -m pytest poc/tests` | `conftest.py` règle `ASSISTANT_VOCAL_CONFIG` sur `config-exemple/` si la variable est vide, et détourne `journal/musique.jsonl` vers un dossier temporaire |
| Appli | `./gradlew testDebugUnitTest` dans `android/` | La propriété `maison.dossier` pointe sur `config-exemple/`. `-PmaisonTests=reel` relance sur la vraie configuration, où les cas écrits pour l'exemple échouent |

Côté serveur, onze fichiers et 206 fonctions de test : accès et arbitre (`test_acces.py`), dictionnaire et
outils (`test_dictionnaire.py`), météo marine, vent mesuré, musique, personnes, mot de réveil, santé, historique
de santé, sécurité et vision. Aucun appel réseau réel, les réponses sont inventées. Côté appli, trente fichiers
JUnit 4 sur la logique pure, sans Robolectric. `cas_securite.json` et `cas_personnes.json` sont lus par les deux
côtés. La règle du dépôt est d'avoir les deux suites vertes avant chaque commit.

### Versions

| Partie | Numéro | Journal |
|---|---|---|
| Serveur et appli Home Assistant | `VERSION` et `DATE_VERSION` de `poc/assistant.py`, `version` de `ha-app/jarvis/config.yaml` | `VERSION.md` |
| Appli Android | `versionApplication` et `versionCode` de `android/app/build.gradle.kts` | `android/VERSION.md` |
| Page 3D | Version de `meubles.json` de la configuration | Avec la configuration |

Le numéro change avec le code, partout en même temps : les deux fichiers de version et le journal du serveur
ensemble, les deux champs de Gradle et le journal de l'appli ensemble. Le serveur affiche sa version au
démarrage et l'annonce dans `capacites`. L'appli affiche `BuildConfig.VERSION_BASE`, le nom du propriétaire et
l'heure de compilation dans ses réglages et dans l'écran Appareils. Avec `-Putilisateur=<nom>`, le
`versionName` de l'APK prend le suffixe `-<nom>`.

### Garde-fou git

À activer une fois par clone : `git config core.hooksPath .githooks`. Le script `.githooks/garde-fou.sh` a
trois modes.

| Mode | Appelé par | Ce qu'il contrôle |
|---|---|---|
| `--index` | `pre-commit` et `pre-merge-commit` | Fichiers indexés et lignes ajoutées |
| `--pousse` | `pre-push` | Tous les commits qui partent |
| `--historique` | À la main, avant un partage | Tout l'historique de toutes les branches |

Il refuse les chemins interdits (`.env`, `local.properties`, clés et keystores, `poc/tls/`, `maison.json` hors de
`config-exemple/`, `config/`, journaux, phrases apprises, `appareils.json`, APK, sons et vidéos, poids de
modèles, bases de données, captures), les secrets reconnaissables (jeton Home Assistant, clés Anthropic, OpenAI,
GitHub, AWS, Slack, clés privées, variables de `poc/.env` remplies) et les fichiers de plus de 5 Mo
(`GARDE_FOU_TAILLE_MAX_MO`). Les valeurs trouvées ne sont jamais affichées. Un faux positif se marque par le
commentaire `garde-fou: ignorer` sur la ligne. Le contournement par `--no-verify` demande l'accord explicite du
propriétaire du dépôt.

Un commit refusé se corrige avant l'envoi : retirer l'élément de l'index (`git restore --staged <fichier>`),
puis recommencer. Si `--historique` trouve quelque chose dans un commit déjà fait, cet historique ne se partage
pas tel quel : on publie un instantané du code, sans historique.
