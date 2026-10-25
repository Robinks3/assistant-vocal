# Installer l'assistant vocal

Ce guide part d'une machine vierge et va jusqu'à une première commande vocale exécutée dans Home
Assistant. Il suit l'ordre dans lequel les pièces dépendent les unes des autres : le matériel, le moteur,
Python, la configuration de la maison, les secrets, la liaison chiffrée, l'appli Android, le serveur du
PC, l'appli Home Assistant, les vérifications, puis la mise à jour. Une variante sans PC puissant est
décrite à la fin.

Versions décrites : serveur 0.25.2 (`poc/assistant.py`, `ha-app/jarvis/config.yaml`), appli Android
0.30.1 (`android/app/build.gradle.kts`). Le détail de chaque fichier de configuration est dans
[`CONFIGURER.md`](CONFIGURER.md), le dépannage dans [`FAQ.md`](FAQ.md).

Toutes les commandes se lancent depuis la racine du dépôt, sauf mention contraire. Les commandes Windows
sont écrites pour PowerShell. Les variantes Linux et macOS sont données quand elles sont simples, mais
le dépôt n'a été mené jusqu'au bout que sous Windows : les scripts `.bat` et `.ps1`, le dossier de
compilation par défaut `C:/Dev/assistant-vocal-build` et le lanceur du LLM local sont propres à Windows.

## Sommaire

1. [Matériel](#1-matériel)
2. [Récupérer le moteur et activer le garde-fou](#2-récupérer-le-moteur-et-activer-le-garde-fou)
3. [Python, dépendances et modèles](#3-python-dépendances-et-modèles)
4. [Configuration de la maison](#4-configuration-de-la-maison)
5. [Le fichier poc/.env, variable par variable](#5-le-fichier-pocenv-variable-par-variable)
6. [Liaison chiffrée et appairage](#6-liaison-chiffrée-et-appairage)
7. [Appli Android](#7-appli-android)
8. [Serveur du PC](#8-serveur-du-pc)
9. [Appli Home Assistant](#9-appli-home-assistant)
10. [Vérifications du premier lancement](#10-vérifications-du-premier-lancement)
11. [Mettre à jour](#11-mettre-à-jour)
12. [Variante : profil sans PC puissant](#12-variante--profil-sans-pc-puissant)

Les trois façons de faire tourner l'assistant, rappelées du `README.md` :

| Mode | Ce qui tourne où | Ce qu'il faut installer |
|---|---|---|
| Cet appareil | Tout sur la tablette ou le téléphone. Home Assistant est joint par la passerelle de l'appli Home Assistant. | Appli Android, appli Home Assistant |
| Serveur du PC | Les téléphones et la tablette servent de micros, le PC transcrit et décide. | Appli Android, Python sur le PC |
| Appli Home Assistant | Le même serveur, emballé dans Home Assistant, quand le PC est éteint. | Appli Android, appli Home Assistant |

## 1. Matériel

### Tablette ou téléphone Android

| Besoin | Valeur | D'où elle vient |
|---|---|---|
| Version d'Android | Android 8.0 (API 26) au minimum, appli ciblée pour l'API 36 | `minSdk = 26`, `targetSdk = 36` dans `android/app/build.gradle.kts` |
| Processeur | ARM 64 bits (`arm64-v8a`) ou ARM 32 bits (`armeabi-v7a`) | `abiFilters` du même fichier : ONNX Runtime et OpenCV n'embarquent que ces deux architectures. Un émulateur x86_64 n'est pas prévu. |
| Micro | Obligatoire | Permission `RECORD_AUDIO` du manifeste. L'appli refuse de démarrer sans elle. |
| Caméra frontale | Facultative | `android.hardware.camera.front` marquée `required="false"`. Elle sert à la vision (qui est devant l'écran) et donc à l'affichage de la santé. |
| Stockage | Environ 1,1 Go libre pour transcrire sur l'appareil | Canary 1B int8 pèse 1,03 Go (`CanaryLocal.kt`) et n'entre pas dans l'APK. |
| Mémoire | Pas de minimum écrit dans le dépôt | Le code note que Canary met une dizaine de secondes à se charger sur une tablette de milieu de gamme, et qu'un essai à 4,9 Go de mémoire a fait tuer l'appli par Android. Une tablette récente avec plusieurs Go de mémoire est préférable pour transcrire sur l'appareil. |
| LLM sur l'appareil | Facultatif | Fichiers `.litertlm` (Gemma 4 E2B, Qwen) copiés à part, voir l'étape 7. Le GPU (OpenCL) est utilisé s'il est présent, sinon le processeur. |

Pour la tablette du séjour en mode station : une alimentation sur secteur, et un support qui la tient en
paysage (l'orientation est forcée en paysage en station).

### PC (facultatif)

Le PC n'est utile que pour le mode Serveur du PC, pour compiler l'APK et pour lancer les scripts de
déploiement. Il peut rester éteint en mode Cet appareil ou avec l'appli Home Assistant.

| Besoin | Valeur |
|---|---|
| Système | Windows 10 ou 11 conseillé (scripts `.bat` et `.ps1`). Linux ou macOS possibles pour la partie Python, avec les réserves de l'étape 3. |
| Python | 5.11 ou 5.13 sous Windows, 5.11 obligatoire sous Linux, voir l'étape 3. |
| Réseau | Le même réseau local que la tablette. Ports TCP 8765 (en clair) et 8766 (chiffré) ouverts en entrée. |
| Micro et haut-parleurs | Seulement pour faire tourner l'assistant sur le PC lui-même (`poc/assistant.py`). |
| Android Studio | Pour compiler l'APK, sur ce PC ou sur une autre machine. |

Ce qui tourne sur le PC en mode Serveur du PC : la transcription Canary 1B sur le processeur, la voix
Piper, le mot de réveil openWakeWord, la détection de parole Silero VAD, la vision des tablettes (YuNet et
SFace par OpenCV), et en option le relais santé, la météo marine, le vent mesuré et un LLM local par
`llama-server`. Le LLM de repli par défaut est Claude Haiku, par l'API d'Anthropic.

### Home Assistant

| Besoin | Détail |
|---|---|
| Version | Le dépôt ne fixe pas de version minimale. Il emploie le service `weather.get_forecasts` (Home Assistant 2023.9 et plus, selon `Previsions.kt`), la syntaxe d'automatisation à `triggers` et `actions` au pluriel (`ha-app/configurer-ha.py`), et le nom « applis » donné aux modules complémentaires (`ha-app/deployer.sh`). Prenez une version récente. |
| Jeton d'accès longue durée | Obligatoire pour piloter la maison depuis le PC, voir l'étape 5. |
| Entité `weather.*` | Pour le panneau Météo de la tablette. |
| Musique | Facultative. Le code appelle `music_assistant.play_media` et `music_assistant.search` (intégration Music Assistant), et décrit les enceintes Enceintes natives derrière chaque lecteur. Sans enceinte « toutes » dans `appareils.musique`, les commandes de musique sont refusées proprement. |
| Applis Wyoming | Facultatives : Speech-to-Phrase, Piper et openWakeWord (Whisper pour essai). Le serveur les joint sous les noms `core-speech-to-phrase:10300`, `core-piper:10200`, `core-openwakeword:10400` et `core-whisper:10300`. Elles sont nécessaires à l'appli Home Assistant de l'assistant (profil sans modèle local) et au choix de transcription « Sur Home Assistant ». |
| Appli SSH | Pour `ha-app/deployer.sh` et `ha-app/configurer-options.py` : une session SSH sur Home Assistant qui dispose de `tar`, `curl`, `nc` et de la variable `SUPERVISOR_TOKEN`. |
| Processeur | L'appli Home Assistant de l'assistant n'est déclarée que pour `amd64` (`ha-app/jarvis/config.yaml`). Un Home Assistant sur Raspberry Pi (`aarch64`) ne peut pas l'installer telle quelle. |

## 2. Récupérer le moteur et activer le garde-fou

Installez Git (sous Windows, Git for Windows fournit aussi le Bash dont ont besoin le garde-fou et
`ha-app/deployer.sh`), puis clonez le dépôt :

```powershell
git clone <adresse du dépôt du moteur> assistant-vocal
```

```powershell
cd assistant-vocal
```

Activez le garde-fou, une fois par clone. Il refuse au commit et à l'envoi les secrets, les données
d'usage et les fichiers de plus de 5 Mo :

```powershell
git config core.hooksPath .githooks
```

Vérifiez :

```powershell
git config --get core.hooksPath
```

La réponse attendue est `.githooks`.

Les crochets, `android/gradlew` et `ha-app/deployer.sh` sont rangés exécutables dans git : un clone
les reçoit prêts à servir, sous Linux et macOS aussi. Seule une copie du dépôt faite sans git (archive
décompressée, par exemple) peut perdre ce droit. Git ignore alors les crochets et `./gradlew` refuse de
se lancer, et `chmod +x` sur ces fichiers le rend.

Pour contrôler tout l'historique avant un partage :

```bash
bash .githooks/garde-fou.sh --historique
```

## 3. Python, dépendances et modèles

### Version de Python

Aucune version n'est fixée dans `poc/requirements.txt` ni dans les scripts. Ce qui a été vérifié :

| Système | Version de Python |
|---|---|
| Windows | 5.11 ou 5.13 : les dépendances s'installent avec l'une comme avec l'autre. |
| Linux | 5.11 obligatoire. Sous Linux, openwakeword 0.6.0 exige `tflite-runtime`, qui n'existe pas au-delà de Python 5.11 : avec une version plus récente, l'installation des dépendances échoue. |
| macOS | Non essayé. |

L'appli Home Assistant, elle, tourne sur l'image `python:5.12-slim` (`ha-app/jarvis/Dockerfile`), sans
openwakeword : elle n'est pas concernée.

Les scripts `.bat` et `.ps1` cherchent l'interpréteur dans `.venv\Scripts\python.exe` à la racine du
dépôt : l'environnement doit porter ce nom et cet emplacement.

### Environnement virtuel

Windows :

```powershell
py 5.11 -m venv .venv
```

Linux (5.11 obligatoire) ou macOS :

```bash
python5.11 -m venv .venv
```

Dans la suite, `.venv\Scripts\python` (Windows) devient `.venv/bin/python` sous Linux et macOS.

### Dépendances

```powershell
.venv\Scripts\python -m pip install -r poc/requirements.txt
```

Depuis la 0.25.1, ce fichier liste tout ce que le code importe, y compris le moteur de transcription
Canary (`onnx-asr[cpu,hub]` et `onnxruntime`), le serveur WebSocket (`websockets`), l'outil de test
(`pytest`) et Pillow pour le plan 2D (`pillow`). Rien n'est à installer en plus.

Sous Linux, `sounddevice` a besoin en plus de la bibliothèque PortAudio du système (paquet
`libportaudio2` sous Debian et Ubuntu).

### Modèles

Les petits modèles sont dans le dépôt : Silero VAD (`poc/modeles/silero_vad.onnx`), YuNet
(`poc/modeles/vision/yunet.onnx`) et le mot de réveil « Hey Jarvis » de l'appli
(`android/app/src/main/assets/reveil/`). Les gros se téléchargent.

Un seul script s'en charge, après l'installation des dépendances :

```powershell
.venv\Scripts\python poc/outils/telecharger_modeles.py
```

Il télécharge la voix Piper française et SFace (reconnaissance des visages) à des versions épinglées,
avec contrôle de l'empreinte SHA-256, et copie SFace dans les assets de l'appli Android, ce qui est
nécessaire avant de la compiler. Il fait aussi télécharger par openWakeWord le modèle « hey_jarvis » et
ses modèles de prétraitement, rangés dans le dossier d'openWakeWord sans contrôle d'empreinte : le serveur
des satellites en a besoin pour guetter le mot de réveil. Les deux dernières lignes attendues sont
`openWakeWord : hey_jarvis prêt` puis `modèles prêts`. Si openwakeword n'est pas installé, le script
s'arrête sur `openwakeword absent : installer d'abord les dépendances (pip install -r
poc/requirements.txt)`.

Canary 1B v2 se télécharge seul au premier démarrage du serveur, par onnx-asr, depuis le dépôt Hugging
Face `istupakov/canary-1b-v2-onnx`, dans le cache Hugging Face de l'utilisateur (par défaut
`%USERPROFILE%\.cache\huggingface\hub` sous Windows, `~/.cache/huggingface/hub` ailleurs). Prévoyez la
connexion Internet et le temps de ce premier démarrage.

## 4. Configuration de la maison

Le moteur ne contient rien d'un logement réel. Tout ce qui décrit la maison est lu dans un seul dossier :
la variable d'environnement `ASSISTANT_VOCAL_CONFIG` si elle est réglée, sinon `config/` à la racine du
dépôt (ignoré par git). Sans `maison.json` lisible, le serveur s'arrête et l'APK refuse de se compiler.

Copiez la configuration fictive comme point de départ.

Windows :

```powershell
Copy-Item -Recurse config-exemple config
```

Linux ou macOS :

```bash
cp -r config-exemple config
```

Le plus sûr est d'en faire ensuite un dépôt privé à part, cloné dans `config/`, pour le sauvegarder sans
jamais le mêler au moteur. Adaptez ensuite chaque fichier en suivant [`CONFIGURER.md`](CONFIGURER.md) :

| Fichier | Contenu |
|---|---|
| `config/maison.json` | Adresses, fuseau, propriétaire, appareils, consignes du LLM, alias exposés à Assist, listes de sécurité, et en option `mer`, `vent` et `reveil`. Le champ `_lisez_moi` décrit chaque section. |
| `config/commandes.yaml` | Dictionnaire des phrases et des actions Home Assistant. |
| `config/carte/` | Plan du logement : `pieces.json`, `meubles.json`, `lampes.json`. |
| `config/reveil/` | Facultatif : modèle du mot de réveil `<mot>.onnx` et sa licence `<mot>.onnx.LICENSE`. |
| `config/genere/` | Fichiers produits pour l'appli, à refaire quand la source change. |

Pour garder la configuration ailleurs, réglez `ASSISTANT_VOCAL_CONFIG` dans l'environnement du terminal,
et non dans `poc/.env` : le dossier est lu au chargement du programme, avant `poc/.env`. Un chemin
relatif part du dossier courant pour Python et de la racine du dépôt pour Gradle, d'où l'intérêt de
toujours lancer depuis la racine.

```powershell
$env:ASSISTANT_VOCAL_CONFIG = "D:\maison\config"
```

```bash
export ASSISTANT_VOCAL_CONFIG=/srv/maison/config
```

Vérifiez que la configuration se lit (le programme s'arrête avec un message explicite sinon) :

```powershell
.venv\Scripts\python poc/assistant.py --version
```

La réponse attendue est `Assistant vocal local v0.25.2 (2026-10-24)`.

### Fichiers produits pour l'appli

Le dictionnaire exporté, que l'APK embarque (écrit dans `genere/android/dictionnaire.json` de la
configuration, et les phrases apprises de la machine dans `genere/android/dictionnaire_appris.json` du dossier
de données, `poc/` par défaut) :

```powershell
.venv\Scripts\python android/outils/exporter_dictionnaire.py
```

La vue 3D du logement (écrit `carte/modele.glb` et `genere/android/maison3d/vue3d.html` de la
configuration) :

```powershell
.venv\Scripts\python carte/3d/generer_3d.py
```

Le plan 2D (`carte/plan.svg` et `carte/plan.png`), qui demande Pillow :

```powershell
.venv\Scripts\python carte/generer_plan.py
```

Si la section `vent` est active, la carte du vent mesuré attend le trait de côte et la terre de votre
plan d'eau dans `genere/android/`, aux chemins donnés par `vent.carte.cote` et `vent.carte.terre`.
Ceux de l'exemple couvrent un seul golfe : aucun outil du dépôt ne les produit pour un autre lieu.

## 5. Le fichier poc/.env, variable par variable

`poc/.env` contient les secrets de la machine. Il n'est jamais versionné, et le garde-fou refuse de le
committer. Créez-le à partir du modèle.

Windows :

```powershell
Copy-Item poc/.env.exemple poc/.env
```

Linux ou macOS :

```bash
cp poc/.env.exemple poc/.env
```

Le serveur et l'assistant lisent `poc/.env` au démarrage, sans écraser une variable déjà présente dans
l'environnement. Gradle en lit seulement la ligne `SATELLITE_JETON` (ou `SATELLITE_JETON_<NOM>`) pour la
compiler dans l'APK.

### Variables du modèle `poc/.env.exemple`

| Variable | Rôle | Défaut dans le code | Obligatoire | Comment obtenir la valeur |
|---|---|---|---|---|
| `HA_URL` | Adresse de Home Assistant | `reseau.ha_url` de `maison.json` | Non | Par exemple `http://homeassistant.local:8123`. |
| `HA_TOKEN` | Jeton longue durée de Home Assistant | vide | Pour piloter la maison. Vide : le serveur affiche `! HA_TOKEN absent de poc/.env : pilotage de la maison désactivé, LLM seul.` | Dans Home Assistant, page de votre profil (votre nom en bas du menu), onglet Sécurité, section Jetons d'accès longue durée, Créer un jeton. Il ne s'affiche qu'une fois. |
| `SATELLITE_JETON` | Jeton fixe du propriétaire, compilé dans son APK | vide | Oui pour le serveur, qui s'arrête sans lui. Au moins 16 caractères. | À inventer, voir la commande sous ce tableau. |
| `LLM_FOURNISSEUR` | Cerveau de repli : `claude` (API Anthropic) ou `local` (`llama-server` compatible OpenAI) | `local` | Non | Le modèle met `claude`, et les fichiers `.bat` du serveur forcent `claude`. |
| `ANTHROPIC_API_KEY` | Clé de l'API d'Anthropic, lue par le SDK officiel | vide | Avec `LLM_FOURNISSEUR=claude` | Console de la plateforme Claude d'Anthropic, rubrique des clés d'API. |
| `LLM_URL` | Adresse du LLM local | `http://127.0.0.1:8080/v1` | Avec `LLM_FOURNISSEUR=local` | Celle de votre `llama-server`. |
| `LLM_MODELE` | Nom du modèle local | `assistant-vocal` | Non | L'alias donné à `llama-server` (`--alias`). |
| `MICRO` | Morceau du nom du micro du PC | `fifine` si la ligne est absente, micro par défaut si elle est vide | Non | Nom affiché par Windows pour le micro. Sert seulement à `poc/assistant.py`. |
| `SORTIE` | Morceau du nom de la sortie son du PC | sortie par défaut | Non | Idem, pour les haut-parleurs. |
| `MOT_REVEIL` | Mot de réveil guetté par le PC : `hey_jarvis` ou un mot dont le modèle est dans `reveil/<mot>.onnx` de la configuration | `hey_jarvis` | Non | Le mot de la section `reveil` de `maison.json`, en minuscules. |
| `STT_API_CLE` | Clé d'une transcription en ligne compatible avec l'API d'OpenAI | vide | Non. Prise en compte au-delà de 10 caractères. | Console du fournisseur (par exemple Mistral pour Voxtral). |
| `STT_API_NOM` | Libellé affiché de cette transcription | `API` | Non | Texte libre, `Voxtral` dans le modèle. |
| `SANTE_URL` | Adresse du service `sante-api` | `reseau.sante_url` de `maison.json` | Non | Service de santé externe, absent de ce dépôt, joignable seulement par Tailscale. |
| `SANTE_JETON` | Jeton de `sante-api` | vide : relais santé éteint | Non | Fourni par ce service externe. Le jeton ne part que vers une adresse Tailscale (100.64.0.0/10). |
| `SANTE_PERSONNES` | Connexions permises pour la santé, séparées par des virgules | ligne absente : le propriétaire seul. Ligne vide : personne. | Non | Clés : la clé du propriétaire, le nom en minuscules d'un `SATELLITE_JETON_<NOM>`, ou `appareil:<id>` pour un appareil appairé (id lu dans l'écran Appareils et accès de l'appli). |
| `SANTE_SEUIL_PAS` | Pas d'une journée active | `6000` | Non | Nombre entier. |
| `SANTE_SEUIL_NUIT_MIN` | Minutes d'une bonne nuit | `420` | Non | Nombre entier. |
| `SANTE_FC_MAX` | Fréquence cardiaque maximale pour les zones | vide : pas de zones | Non | Entre 100 et 250. |
| `METEO_MER` | Page Mer de la tablette | `1` | Non | `0` l'éteint, avec la page Vent mesuré. Sans section `mer` active dans `maison.json`, elle reste éteinte. |
| `VENT_MESURE` | Page Vent mesuré | `1` | Non | `0` l'éteint seule. Elle demande aussi les sections `mer` et `vent` actives, et `METEO_MER` différent de `0`. |

Pour inventer un jeton de satellite solide :

```powershell
.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(32))"
```

Ajoutez une ligne `SATELLITE_JETON_<NOM>=...` par personne qui aura sa propre APK (voir `-Putilisateur` à
l'étape 7). Supprimer la ligne d'une personne lui coupe l'accès au prochain démarrage du serveur.

### Variables lues par le code mais absentes du modèle

| Variable | Rôle | Défaut | Où la régler |
|---|---|---|---|
| `SATELLITE_JETON_<NOM>` | Jeton fixe d'une autre personne | aucun | `poc/.env` |
| `CLAUDE_MODELE` | Modèle Claude du repli | `claude-haiku-5-5` | `poc/.env` |
| `VOIX` | Fichier de la voix Piper du PC | `poc/voix/fr_FR-siwis-medium.onnx` | `poc/.env` |
| `SEUIL_REVEIL` | Score du mot de réveil, de 0 à 1 | `0.5` | `poc/.env`. Écrit par le calibrage guidé. |
| `STT_API_URL` | Adresse de la transcription en ligne | `https://api.mistral.ai/v1/audio/transcriptions` | `poc/.env` |
| `STT_API_MODELE` | Modèle de la transcription en ligne | `voxtral-mini-latest` | `poc/.env` |
| `JARVIS_ANCIEN_ACCES` | Accepte l'ancienne forme `ws://...:8765/?jeton=` sur le port en clair | `1` | `poc/.env`. Mettre `0` quand tous les appareils sont en wss. |
| `JARVIS_PROFIL` | `pc` ou `ha` (sans modèle local, réglé par l'appli Home Assistant) | `pc` | `poc/.env` |
| `JARVIS_WYOMING_SSH` | Essai du profil `ha` depuis le PC, par SSH | vide | `poc/.env` |
| `ASSISTANT_VOCAL_CONFIG` | Dossier de configuration | `config/` | Environnement du terminal seulement |
| `MAISON_DOSSIER` | Ancien nom de la précédente | aucun | Environnement du terminal seulement |
| `JARVIS_DONNEES` | Dossier des données vivantes (journaux, phrases apprises, `tls/`, `appareils.json`) | `poc/` | Environnement du terminal seulement |
| `VAD_MODELE` | Modèle Silero VAD | `poc/modeles/silero_vad.onnx` | Environnement du terminal seulement |
| `JARVIS_PORT_TLS` | Port chiffré par défaut | `8766` | Environnement du terminal seulement, ou option `--port-tls` |
| `GARDE_FOU_TAILLE_MAX_MO` | Taille maximale d'un fichier pour le garde-fou | `5` | Environnement du terminal |
| `HOTE_TEST`, `PORT_TEST`, `MODE_ESSAI` | Outil de test `poc/outils/faux_telephone.py`, qui demande aussi la voix Piper `en_US-lessac-medium` dans `poc/voix/` (non téléchargée par `telecharger_modeles.py`) | `127.0.0.1`, `8765`, vide | Environnement du terminal |

Les quatre variables marquées « environnement du terminal seulement » sont lues au chargement des
modules Python, avant `poc/.env` : écrites dans `poc/.env`, elles sont sans effet.

## 6. Liaison chiffrée et appairage

### Clés TLS du port chiffré

Le serveur ouvre deux ports : 8765 en clair et 8766 chiffré (wss). Au premier démarrage, la fonction
`certificat` de `poc/acces.py` crée seule un certificat auto-signé valable 10 ans (clé EC P-256, nom
`jarvis`) dans le dossier `tls/` des données :

| Lancement | Emplacement |
|---|---|
| PC, sans `JARVIS_DONNEES` | `poc/tls/cert.pem` et `poc/tls/cle.pem` |
| Appli Home Assistant | `/data/tls/`, qui survit aux mises à jour de l'appli |

Rien n'est à fournir. Pour imposer votre propre paire, déposez `cert.pem` et `cle.pem` (PEM, clé privée
non chiffrée) dans ce dossier avant le démarrage : le code ne les recrée que si l'un des deux manque.

Au démarrage, le serveur affiche l'empreinte SHA-256 de la clé publique :

```text
  port chiffré 8766, empreinte de la clé sha256/<empreinte en base64>
```

Chaque appareil retient cette empreinte à sa première connexion, puis refuse toute autre clé. Comparez-la
avec celle de l'écran Appareils et accès de l'appli (`Clé du serveur retenue : sha256/...`). Sauvegardez
le dossier `tls/` hors du dépôt : si la clé change (dossier effacé, autre `JARVIS_DONNEES`, appli Home
Assistant réinstallée), chaque appareil refuse la connexion jusqu'à ce qu'on lui fasse oublier
l'ancienne clé. `poc/tls/` est ignoré par git et refusé par le garde-fou.

### Appairage d'un nouvel appareil

Un appareil est accepté par l'un de ces deux moyens :

- un jeton fixe de `poc/.env` (`SATELLITE_JETON` ou `SATELLITE_JETON_<NOM>`), compilé dans son APK.
- Un jeton propre obtenu par appairage, sur le port chiffré seulement.

Le protocole, décrit en tête de `poc/serveur_satellite.py` et dans `poc/acces.py` :

1. Le nouvel appareil se connecte sans jeton à `wss://<hôte>:8766/appairage?nom=<nom>` (l'appli envoie le
   modèle de l'appareil comme nom).
2. Le serveur répond `{"etat":"appairage","code"}` avec un code à 4 chiffres, que l'appareil affiche, et
   prévient les appareils déjà connectés.
3. Sur un appareil déjà connu, l'écran Appareils et accès montre la demande et son code. Vérifiez que
   le code est le même, puis acceptez.
4. Le serveur crée alors un jeton, l'envoie une seule fois au nouvel appareil (`{"etat":"appaire","jeton"}`)
   et n'en garde que l'empreinte dans `appareils.json` des données.
5. Sans réponse en 5 minutes, la demande est refusée (`{"etat":"appairage_refuse"}`).

Le premier appareil doit donc porter un jeton fixe : c'est l'APK du propriétaire, compilée avec
`SATELLITE_JETON`. Un appareil appairé se révoque depuis le même écran. Sa clé pour `SANTE_PERSONNES`
est `appareil:<id>`.

Quand tous les appareils passent par le port chiffré, coupez l'ancien accès en clair avec
`JARVIS_ANCIEN_ACCES=0` dans `poc/.env`, ou fermez le port en clair avec `--port 0`.

## 7. Appli Android

### Android Studio, JDK et SDK

1. Installez Android Studio. Il fournit un JDK, le JBR, dans son dossier d'installation (`jbr`).
2. Au premier lancement, laissez-le installer le SDK Android. Ouvrez ensuite le dossier `android/` du
   dépôt comme projet.
3. Dans le gestionnaire du SDK, installez la plateforme Android 37 : l'appli est compilée avec
   `compileSdk` 37. Acceptez les licences demandées.

Le projet utilise Gradle 9.4.1 (`gradle-wrapper.properties`) et le plugin Android 9.2.1. Le démon Gradle
demande un JDK 21 (`android/gradle/gradle-daemon-jvm.properties`), que Gradle peut télécharger seul s'il
n'en trouve pas.

Pour compiler en ligne de commande, pointez `JAVA_HOME` vers le JBR. Windows, avec le dossier
d'installation par défaut :

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
```

macOS :

```bash
export JAVA_HOME="/Applications/Android Studio.app/Contents/jbr/Contents/Home"
```

Linux, en adaptant le dossier d'installation :

```bash
export JAVA_HOME="$HOME/android-studio/jbr"
```

### android/local.properties

`build.gradle.kts` ne lit rien dans `local.properties`. Seul le plugin Android y lit `sdk.dir`, le
chemin du SDK. Android Studio crée ce fichier en ouvrant le projet. Sinon, créez `android/local.properties`
avec une seule ligne, par exemple sous Windows :

```properties
sdk.dir=C\:\\Users\\<vous>\\AppData\\Local\\Android\\Sdk
```

ou réglez la variable `ANDROID_HOME`. Ce fichier n'est jamais versionné.

### Avant de compiler

Gradle refuse de produire une APK tant qu'il manque l'un de ces éléments :

| Élément | Étape |
|---|---|
| `config/maison.json` (ou le dossier de `ASSISTANT_VOCAL_CONFIG`) | 4 |
| `genere/android/dictionnaire.json` de la configuration | 4, `exporter_dictionnaire.py` |
| `genere/android/maison3d/vue3d.html` de la configuration | 4, `generer_3d.py` |
| `reveil/<mot>.onnx` si la section `reveil` existe | 4 |
| Les fichiers de `vent.carte` si la section `vent` est active | 4 |

Il compile aussi SFace dans l'APK (copié par `telecharger_modeles.py`, étape 3) et le jeton
`SATELLITE_JETON` de `poc/.env` (étape 5). Sans ce jeton, la compilation passe avec un avertissement,
mais le serveur refusera l'appareil tant qu'il n'est pas appairé.

### Compilation

Windows :

```powershell
cd android
```

```powershell
.\gradlew.bat assembleDebug
```

Linux ou macOS :

```bash
cd android
```

```bash
./gradlew assembleDebug -PdossierBuild="$HOME/assistant-vocal-build"
```

Le dossier de compilation est écrit hors du dépôt, par défaut dans `C:/Dev/assistant-vocal-build` (pour éviter
les blocages de l'antivirus quand le dépôt est sous Documents). L'option `-PdossierBuild` en choisit un
autre, et elle est indispensable hors de Windows, où le chemin par défaut n'a pas de sens. L'APK de
débogage est alors dans :

```text
<dossierBuild>/SatelliteJarvis-app/outputs/apk/debug/app-debug.apk
```

Autres propriétés utiles :

| Propriété | Effet |
|---|---|
| `-Putilisateur=camille` | APK d'une autre personne : jeton `SATELLITE_JETON_CAMILLE` de `poc/.env`, version suffixée `-camille`. Lettres minuscules, chiffres et `_` seulement. |
| `-PconfigDossier=<chemin>` | Dossier de configuration, prioritaire sur `ASSISTANT_VOCAL_CONFIG`. |
| `-PdossierBuild=<chemin>` | Dossier de compilation. |
| `-PmaisonTests=reel` | Tests unitaires sur la vraie configuration au lieu de `config-exemple/` (les cas écrits pour l'exemple y échouent, c'est attendu). |

L'APK contient le jeton du satellite et la configuration de la maison : ne la faites pas circuler.

### Signature

`assembleDebug` signe l'APK avec la clé de débogage qu'Android Studio crée sur la machine. C'est le
chemin prévu par le dépôt.

Le dépôt ne déclare aucune signature de publication : `assembleRelease` produit une APK non signée, qui
ne s'installe pas. Pour une version signée, créez votre propre keystore hors du dépôt et signez l'APK
avec `apksigner` du SDK. Les fichiers `*.jks`, `*.keystore` et `keystore.properties` sont ignorés par git
et refusés par le garde-fou. Passer d'une signature à une autre oblige à désinstaller l'appli, ce qui
efface ses réglages, la clé retenue du serveur, le jeton d'appairage et les visages enregistrés
(l'appli interdit la sauvegarde Android).

### Installation par adb

Sur l'appareil, activez les options pour les développeurs puis le débogage USB, branchez-le, et
vérifiez qu'il est vu (`adb` est dans `platform-tools` du SDK) :

```powershell
adb devices
```

Installez ou remplacez l'appli :

```powershell
adb install -r C:\Dev\assistant-vocal-build\SatelliteJarvis-app\outputs\apk\debug\app-debug.apk
```

### Premier lancement et permissions

Ouvrez l'appli (nom affiché : celui de la section `assistant` de la configuration), à la main ou par adb :

```powershell
adb shell am start -n assistant.vocal.jarvis/.MainActivity
```

Elle demande le micro, les notifications (Android 13 et plus), et la caméra si la vision est choisie.
Au premier lancement, elle crée aussi ses dossiers de modèles, `files/canary` et `files/llm`. Ils doivent
appartenir à l'appli : Android 16 refuse de lire un dossier créé par adb.

### Modèles sur l'appareil (facultatif)

Pour transcrire sur la tablette (choix « Sur la tablette (Canary) »), copiez les quatre fichiers attendus
par `CanaryLocal.kt` dans `Android/data/assistant.vocal.jarvis/files/canary/`. Le dépôt n'a pas d'outil pour cette
étape. Trois fichiers viennent du dépôt Hugging Face de Canary, le quatrième (`nemo128.onnx`, le
prétraitement) est livré avec le paquet onnx-asr.

Téléchargement des trois fichiers du modèle dans un dossier `canary` :

```powershell
.venv\Scripts\python -c "from huggingface_hub import snapshot_download; snapshot_download('istupakov/canary-1b-v2-onnx', allow_patterns=['encoder-model.int8.onnx', 'decoder-model.int8.onnx', 'vocab.txt'], local_dir='canary')"
```

Emplacement de `nemo128.onnx` sur le PC :

```powershell
.venv\Scripts\python -c "import onnx_asr, pathlib; print(pathlib.Path(onnx_asr.__file__).parent / 'preprocessors' / 'data' / 'nemo128.onnx')"
```

Puis un envoi par fichier, l'appli ayant été lancée une fois :

```powershell
adb push canary/encoder-model.int8.onnx /sdcard/Android/data/assistant.vocal.jarvis/files/canary/
```

```powershell
adb push canary/decoder-model.int8.onnx /sdcard/Android/data/assistant.vocal.jarvis/files/canary/
```

```powershell
adb push canary/vocab.txt /sdcard/Android/data/assistant.vocal.jarvis/files/canary/
```

```powershell
adb push <chemin affiché plus haut>/nemo128.onnx /sdcard/Android/data/assistant.vocal.jarvis/files/canary/
```

Ces noms de fichiers sont ceux de `CanaryLocal.kt` et d'onnx-asr 0.12. Une autre version d'onnx-asr peut
les ranger autrement.

Pour un LLM sur l'appareil, déposez un fichier `.litertlm` dans `Android/data/assistant.vocal.jarvis/files/llm/`.
Noms reconnus par `ModeleLiteRt.kt`, du préféré au plus léger : `gemma-4-E2B-it-gpu.litertlm`,
`gemma-4-E2B-it.litertlm`, `Qwen2.5-1.5B-Instruct_multi-prefill-seq_q8_ekv4096.litertlm`,
`qwen3_0.6b_nothink_q4_block32_ekv1280.litertlm` (modèles de `litert-community` sur Hugging Face).

### Réglages de l'appli

Le panneau des réglages est découpé en sections :

| Section | Réglages |
|---|---|
| Général | Serveur : PC fixe, Home Assistant ou Cet appareil. Mode : Essai (rien n'est exécuté) ou Réel. Connexion : Adresse du PC fixe et Adresse de Home Assistant, qui doivent commencer par `ws://` ou `wss://`. Laissées vides, elles prennent `reseau.android_serveur_pc` et `reseau.android_serveur_ha` de `maison.json`. Bouton Désactiver l'optimisation de batterie. |
| Voix et réveil | Mot de réveil : « Hey Jarvis (anglais) » ou le mot de la configuration, proposé et pris par défaut s'il a été compilé dans l'APK. Où il est guetté : Sur cet appareil ou Sur le serveur. Sons. Lieu de la transcription. |
| Compréhension | Cerveau de repli. |
| Vision et visages | Désactivée, Sur la tablette ou Sur le PC. Visages enregistrés. Parler en regardant. |
| Station | Mode station. |
| Appareils et accès | Appairage, demandes en attente, clé retenue du serveur, oubli de la clé ou du jeton. |
| Historique, Diagnostic | Commandes passées et déroulé technique de la dernière commande. |

Adresses à saisir, avec une adresse IP fixe pour chaque serveur :

```text
wss://192.168.0.10:8766
```

Commencez en mode Essai, appuyez sur Démarrer, puis passez en Réel une fois la chaîne vérifiée
(étape 10).

### Mode station de la tablette

Dans la section Station, activez le mode station. L'appli passe alors en plein écran, en paysage, choisit
le serveur Cet appareil (modifiable ensuite), et explique ce qu'il reste à accorder :

1. L'exemption de l'optimisation de batterie.
2. L'autorisation « Afficher par-dessus les autres applications », qui lui permet de rouvrir son écran au
   démarrage de la tablette.
3. Sur Samsung, l'ajout de l'appli aux applications jamais mises en veille.

En station, l'appli redémarre avec la tablette et se relance si Android la tue.

## 8. Serveur du PC

### Lancement

Le tout premier lancement se fait en mode essai : le serveur comprend et répond, mais n'exécute rien dans
Home Assistant.

```powershell
.venv\Scripts\python poc/serveur_satellite.py --essai
```

Ensuite, double-clic sur `Lancer le serveur satellite.bat` à la racine, ou la même commande sans `--essai`.
Éditez `poc/.env` et les fichiers de la configuration avec un éditeur de texte qui enregistre en UTF-8
sans BOM : sous Windows PowerShell 5.1, `Set-Content -Encoding utf8` ajoute un BOM, que le programme refuse.

Le fichier `.bat` force `LLM_FOURNISSEUR=claude` et transmet ses arguments au serveur. Options :

| Option | Effet | Défaut |
|---|---|---|
| `--essai` | Comprend et répond, n'exécute rien dans Home Assistant. Basculable ensuite depuis l'appli. | non |
| `--port <n>` | Port en clair, `0` pour le couper | `8765` |
| `--port-tls <n>` | Port chiffré, `0` pour le couper | `8766` ou `JARVIS_PORT_TLS` |
| `--seuil <x>` | Score du mot de réveil, de 0 à 1 | `SEUIL_REVEIL`, sinon `0.5` |
| `--calibrer` | Calibrage guidé du mot de réveil au démarrage | non |

Le calibrage guidé a son propre fichier, `Calibrer le mot de réveil.bat`, qui lance le serveur en essai
avec `--calibrer`. Fermez d'abord le serveur s'il tourne. À la fin, il propose d'écrire le seuil trouvé
dans `poc/.env`.

Autorisez les deux ports en entrée dans le pare-feu de Windows, pour le réseau privé seulement. Le
dépôt ne le fait pas. Par exemple, dans un PowerShell lancé en administrateur :

```powershell
New-NetFirewallRule -DisplayName "Assistant vocal" -Direction Inbound -Protocol TCP -LocalPort 8765,8766 -Action Allow -Profile Private
```

### Ce qu'il affiche quand tout va bien

Les lignes sont dans cet ordre, les valeurs varient :

```text
  jetons fixes acceptés : sacha
  dictionnaire : 1234 formes de phrases
  cerveau : Claude (claude-haiku-5-5) par API
  modèles chargés en 0.4 s
  transcription et voix chargées en 9.8 s
  détection de parole : Silero VAD
  vision : YuNet et SFace prêts pour les tablettes
  santé : relais éteint (SANTE_JETON absent)
  historique santé : éteint
  météo marine : <modèle principal>, <second modèle>, MFWAM, VaguesRegional et station
  vent mesuré : Balises, StationsOfficielles et station
  appareils appairés : aucun
  port chiffré 8766, empreinte de la clé sha256/<empreinte>
Serveur satellite v0.25.2, port 8765 (ancien accès ?jeton= permis) et port chiffré 8766, seuil du mot de réveil 0.50, cerveau claude (actions réelles). Ctrl+C pour arrêter.
```

À surveiller : une ligne `! HA_TOKEN absent`, une détection de parole par `seuil d énergie`, l'absence
de la ligne `vision` (SFace ou YuNet manquant), et les lignes `éteinte` ou `éteint` des pages Mer et
Vent, qui donnent leur raison. Quand un appareil se connecte, le serveur écrit
`[<nom> <adresse> (chiffré)] satellite connecté`.

Une `ANTHROPIC_API_KEY` vide ne se voit pas au démarrage : la ligne `cerveau : Claude` s'affiche quand
même, et seule la première phrase inconnue échoue, avec `Le modèle de langage ne répond pas`. Vérifiez la
clé avant de chercher plus loin.

### Assistant sur le PC seul (facultatif)

`Lancer l'assistant.bat` fait tourner l'assistant avec le micro et les haut-parleurs du PC et un LLM
local. Son lanceur `poc/lancer-llm.ps1` contient des chemins écrits en dur vers `llama-server.exe` et un
modèle Qwen3.5-9B : adaptez-les avant usage. Sans LLM local, l'assistant au clavier suffit pour les
essais :

```powershell
.venv\Scripts\python poc/assistant.py --clavier --claude --essai
```

## 9. Appli Home Assistant

L'appli Home Assistant (dossier `ha-app/`, nom affiché pris dans la section `assistant` de la configuration, identifiant `local_jarvis`) est le même
serveur, sans modèle local lourd : elle transcrit par Speech-to-Phrase, parle par Piper et guette le mot
de réveil par openWakeWord, trois applis Wyoming de Home Assistant, et répond par Claude. Elle sert de
passerelle Home Assistant au mode Cet appareil. Elle ne sait faire ni la vision ni la santé.

### Accès SSH

`deployer.sh` et `configurer-options.py` se connectent par l'alias SSH donné par `reseau.ssh_ha` de
`maison.json` (`ha` dans l'exemple). Installez une appli SSH dans Home Assistant, avec une clé, puis
déclarez l'alias dans `~/.ssh/config` (sous Windows, `%USERPROFILE%\.ssh\config`) :

```text
Host ha
    HostName 192.168.0.20
    User root
    IdentityFile ~/.ssh/id_ed25519_ha
```

Vérifiez :

```bash
ssh ha ls /
```

La session doit disposer de `tar`, de `curl` et de la variable `SUPERVISOR_TOKEN`. Le dossier
`/local_apps` utilisé par le script est celui des applis locales dans les versions récentes de Home
Assistant. Si votre appli SSH ne le montre pas, adaptez le chemin dans `ha-app/deployer.sh`.

### Déploiement

Depuis un terminal Bash (Git Bash sous Windows), à la racine du dépôt. Le script appelle `python`, qui
doit être trouvé dans ce terminal :

```bash
bash ha-app/deployer.sh
```

Le script copie le code de `poc/`, `maison.json` et `commandes.yaml` de la configuration, le modèle Silero
et, s'il existe, `poc/commandes_apprises.yaml` comme graine, dans `/local_apps/jarvis`. Il refuse de
partir sans configuration réelle, pour ne jamais déployer les listes fictives de l'exemple. Le dossier
`reveil/` n'est pas copié : l'appli Home Assistant n'annonce que « Hey Jarvis ».

### Installation dans Home Assistant

Les libellés exacts dépendent de la version de Home Assistant :

1. Paramètres, Applis (anciennement Modules complémentaires), Boutique.
2. Menu en haut à droite, Rechercher des mises à jour, pour faire apparaître les applis locales.
3. Ouvrez l'appli (nom de la section `assistant`) dans la section des applis locales, puis Installer. L'image est construite sur place
   (`python:5.12-slim`), ce qui prend quelques minutes.
4. Dans l'onglet de configuration, réglez les options, puis Démarrer.

| Option | Rôle |
|---|---|
| `anthropic_api_key` | Clé de l'API d'Anthropic. Le profil Home Assistant répond toujours par Claude. |
| `satellite_jeton` | Jeton fixe du propriétaire, le même que `SATELLITE_JETON` de `poc/.env`, au moins 16 caractères. |
| `essai` | Rien n'est exécuté dans la maison. |
| `ancien_acces` | Accepte `ws://...:8765/?jeton=` en clair. À décocher quand tous les appareils sont en wss. |
| `stt_api_cle`, `stt_api_url`, `stt_api_modele`, `stt_api_nom` | Transcription en ligne facultative, voir l'étape 12. |

Les options peuvent aussi être envoyées depuis `poc/.env`, sans qu'aucun secret ne s'affiche ni
n'apparaisse dans une ligne de commande :

```powershell
.venv\Scripts\python ha-app/configurer-options.py
```

Ajoutez `--essai` pour démarrer l'appli en essai, `--sans-ancien-acces` pour couper l'accès en clair.
L'appli n'a pas besoin de jeton Home Assistant : elle utilise celui du superviseur.

Au démarrage, le journal de l'appli doit montrer :

```text
Iris : clé Anthropic présente, jeton satellites présent, transcription en ligne non configurée
```

La ligne commence par le nom de la section `assistant` (ici celui de la configuration d'exemple).

puis les mêmes lignes que le serveur du PC, avec `profil ha : Speech-to-Phrase, Piper et openWakeWord des
applis de Home Assistant`. L'appli publie les ports 8765 et 8766 de la machine Home Assistant.

### Transférer le dictionnaire à Home Assistant

`ha-app/configurer-ha.py` ajoute les alias de `ha.alias`, expose à Assist les entités de `ha.exposer`,
et crée l'automatisation « <nom de l'assistant> : dictionnaire » avec un déclencheur vocal par commande, pour que
Speech-to-Phrase apprenne vos phrases. Il utilise `HA_URL` et `HA_TOKEN` de `poc/.env`. Aperçu sans
rien envoyer (écrit dans `genere/ha/` de la configuration) :

```powershell
.venv\Scripts\python ha-app/configurer-ha.py --essai
```

Envoi :

```powershell
.venv\Scripts\python ha-app/configurer-ha.py
```

Les commandes que la sécurité en dur refuse sont retirées de l'automatisation, et le script les affiche.

## 10. Vérifications du premier lancement

### Tests automatiques

Les tests Python tournent sur `config-exemple/`, réglé seul par `poc/tests/conftest.py` si
`ASSISTANT_VOCAL_CONFIG` n'est pas déjà définie :

```powershell
.venv\Scripts\python -m pytest poc/tests
```

Résultat attendu : environ 300 tests réussis et 4 ignorés. Les tests ignorés portent sur une règle de
sécurité désactivée par défaut (occupant protégé), c'est normal.

Les tests de l'appli tournent aussi sur `config-exemple/`, depuis le dossier `android/` :

```powershell
cd android
```

```powershell
.\gradlew.bat testDebugUnitTest -PdossierBuild=C:/Dev/assistant-vocal-build
```

```bash
./gradlew testDebugUnitTest -PdossierBuild="$HOME/assistant-vocal-build"
```

### Serveur en essai sur la configuration d'exemple

Ce test vérifie Python, les modèles et les ports sans toucher à votre configuration. Il demande quand
même `SATELLITE_JETON` dans `poc/.env`.

```powershell
$env:ASSISTANT_VOCAL_CONFIG = "config-exemple"
```

```powershell
.venv\Scripts\python poc/serveur_satellite.py --essai
```

La dernière ligne doit contenir `(ESSAI, rien n est exécuté)`. Arrêtez par Ctrl+C, puis retirez la
variable pour revenir à votre configuration :

```powershell
Remove-Item Env:ASSISTANT_VOCAL_CONFIG
```

### Une commande écrite, de bout en bout

Sur la configuration d'exemple, sans micro et sans rien exécuter :

```powershell
$env:ASSISTANT_VOCAL_CONFIG = "config-exemple"
```

```powershell
.venv\Scripts\python poc/assistant.py --texte "allume le salon" --essai
```

La sortie doit contenir une ligne de cette forme, qui montre que le dictionnaire a trouvé la phrase et
que la sécurité l'a laissée passer :

```text
  [dictionnaire (allume le salon)] Salon allumé.   actions : light.turn_on light.exemple6
```

Retirez ensuite la variable comme plus haut, et refaites l'essai avec une phrase de votre propre
`commandes.yaml`.

### Une commande vocale, de bout en bout

1. Lancez le serveur du PC (ou démarrez l'appli Home Assistant), en essai.
2. Sur la tablette, choisissez le serveur, laissez le mode Essai et appuyez sur Démarrer. Le serveur doit
   écrire `satellite connecté`.
3. Dites « Hey Jarvis » (ou votre mot de réveil), attendez le signal d'écoute, puis une phrase de votre
   dictionnaire.
4. Le serveur écrit la transcription (`transcription pc : 0.31 s` puis `Vous (1.6 s) : ...`) et la voie
   choisie. Sur la tablette, la section Diagnostic montre chaque étape.
5. Passez en mode Réel dans l'appli et recommencez : l'appareil doit réagir dans Home Assistant.

## 11. Mettre à jour

1. Tirez le moteur :

```powershell
git pull
```

2. Tirez la configuration, si c'est un dépôt privé cloné dans `config/` :

```powershell
git -C config pull
```

3. Remettez les dépendances et les modèles à niveau :

```powershell
.venv\Scripts\python -m pip install -r poc/requirements.txt
```

```powershell
.venv\Scripts\python poc/outils/telecharger_modeles.py
```

4. Refaites le dictionnaire exporté et la page 3D :

```powershell
.venv\Scripts\python android/outils/exporter_dictionnaire.py
```

```powershell
.venv\Scripts\python carte/3d/generer_3d.py
```

5. Relancez les tests (étape 10).
6. Recompilez l'APK depuis `android/` et réinstallez-la, sans désinstaller (les réglages et la clé
   retenue sont gardés) :

```powershell
.\gradlew.bat assembleDebug
```

```powershell
adb install -r C:\Dev\assistant-vocal-build\SatelliteJarvis-app\outputs\apk\debug\app-debug.apk
```

7. Redéployez l'appli Home Assistant, puis, dans Home Assistant, installez la mise à jour proposée ou
   reconstruisez l'appli :

```bash
bash ha-app/deployer.sh
```

8. Si le dictionnaire a changé, renvoyez-le à Home Assistant :

```powershell
.venv\Scripts\python ha-app/configurer-ha.py
```

9. Redémarrez le serveur du PC. Son numéro de version s'affiche dans sa dernière ligne de démarrage, celui
   de l'appli dans l'en-tête des réglages.

Les phrases apprises restent propres à chaque serveur : `poc/commandes_apprises.yaml` sur le PC,
`/data/commandes_apprises.yaml` dans l'appli Home Assistant (la graine du PC n'est copiée qu'au premier
démarrage de l'appli).

## 12. Variante : profil sans PC puissant

Cette variante se passe de PC allumé en permanence et de carte graphique. Le PC ne sert qu'à préparer
(compiler l'APK, déployer), et un ordinateur portable modeste y suffit.

### Principe

| Pièce | Où elle tourne |
|---|---|
| Home Assistant | Une petite machine `amd64` (l'appli de l'assistant n'existe pas pour `aarch64`). |
| Serveur de l'assistant | L'appli Home Assistant, profil `ha` : aucun modèle local lourd. |
| Mot de réveil | Sur la tablette (« Sur cet appareil »), ou par l'appli openWakeWord de Home Assistant. |
| Transcription | Speech-to-Phrase de Home Assistant, et en option un service en ligne. Ou Canary sur la tablette si elle en a la mémoire. |
| Dictionnaire, sécurité | Sur la tablette (mode Cet appareil) ou dans l'appli Home Assistant. |
| Repli pour les phrases inconnues | Claude, par l'API d'Anthropic. |
| Voix | Voix d'Android, ou Piper de Home Assistant. |

### Pas à pas

1. Installez dans Home Assistant les applis Speech-to-Phrase, Piper et openWakeWord (étape 1).
2. Sur la machine de préparation, faites les étapes 2 à 5. Dans `poc/.env`, seuls `SATELLITE_JETON`,
   `ANTHROPIC_API_KEY` et, si vous voulez la transcription en ligne, `STT_API_CLE`, `STT_API_URL`,
   `STT_API_MODELE` et `STT_API_NOM` sont utiles ici. Inutile de télécharger les modèles du PC (étape 3,
   partie Modèles), sauf SFace si la tablette doit reconnaître les visages : le script le copie dans
   l'APK.
3. Réglez `reseau.android_serveur_ha` de `maison.json` sur l'adresse wss de Home Assistant, compilez et
   installez l'APK (étape 7).
4. Déployez et installez l'appli Home Assistant (étape 9). Options : `satellite_jeton`,
   `anthropic_api_key`, et pour la transcription en ligne `stt_api_cle`, `stt_api_url`, `stt_api_modele`,
   `stt_api_nom`. `configurer-options.py` les envoie toutes depuis `poc/.env`.
5. Envoyez le dictionnaire à Home Assistant avec `configurer-ha.py`, pour que Speech-to-Phrase connaisse
   vos phrases.
6. Sur la tablette, choisissez le serveur :
   - Cet appareil : réveil, détection de parole, dictionnaire et sécurité tournent sur la tablette, qui
     passe par l'appli Home Assistant pour agir. Transcription au choix : Sur la tablette (Canary, à
     copier, étape 7), Sur Home Assistant (Speech-to-Phrase) ou En ligne. L'appli Android ne garde aucune
     clé de transcription : la voie En ligne passe par le serveur qui l'annonce (`Transcription.kt`).
   - Home Assistant : la tablette sert de micro à l'appli Home Assistant, qui transcrit par
     Speech-to-Phrase.

Dans l'appli Home Assistant, Speech-to-Phrase est le choix par défaut. Il rend un texte vide pour toute
phrase qu'il ne connaît pas. Si une clé de transcription en ligne est réglée, la phrase part alors au
service en ligne en repli.

Sur un PC en profil `pc`, Canary et Piper sont chargés au démarrage même quand une clé de transcription
en ligne est réglée : ce choix n'y économise pas la mémoire du PC. L'économie vient du profil `ha`.

### Ce qui part en ligne

| Donnée | Vers qui | Quand |
|---|---|---|
| Le son de la phrase (WAV 16 kHz) | Le fournisseur de transcription (`STT_API_URL`, Mistral par défaut) | Quand la voie En ligne est choisie, ou en repli quand Speech-to-Phrase ne reconnaît rien. |
| Le texte de la demande, la date, la liste des appareils permis (identifiant, nom, pièce) avec leur état, les consignes de `maison.json` et, si la tablette la reconnaît, la personne qui parle | Anthropic | Quand ni le dictionnaire ni, sur la tablette en mode Cet appareil, Assist n'ont compris la phrase. Sur le serveur, Assist est sauté tant que la sécurité en dur est active, et une phrase absente du dictionnaire va directement à Claude. |
| Les demandes de météo marine et de vent mesuré | Sources publiques, sans clé ni donnée personnelle | Pages Mer et Vent, si elles sont actives. |

Le mot de réveil, la détection de parole, le dictionnaire et la sécurité ne quittent jamais la maison.
Les appareils masqués par la section `llm.masquer` de `commandes.yaml` ne figurent pas dans la liste
envoyée à Claude, ni ceux de l'occupant protégé quand sa protection est active (drapeau
`PROTEGER_OCCUPANT` de `poc/securite.py`, désactivé dans cette version).

### Estimer le coût

Méthode, avec vos propres chiffres :

1. N, le nombre de phrases par jour.
2. p, la part qui va au LLM. Le journal `journal/latences.csv` des données (colonne `voie`) dit, pour
   chaque phrase, si elle est passée par le dictionnaire ou par `llm (...)`.
3. Les jetons d'un appel à Claude : entrée (consignes et liste des appareils, mises en cache entre deux
   appels rapprochés, plus les états et la demande), lecture en cache, et sortie. La console d'Anthropic
   les donne par jour.
4. q, la part des phrases qui part à la transcription en ligne, et d, la durée moyenne d'une phrase en
   minutes.

Coût du LLM par jour : N x p x (jetons d'entrée x prix d'entrée + jetons d'écriture en cache x prix
d'écriture + jetons lus en cache x prix de lecture + jetons de sortie x prix de sortie).

Coût de la transcription par jour : N x q x d x prix à la minute.

Tarifs publics de Claude Haiku 5.5, modèle par défaut (`CLAUDE_MODELE`), pour des demandes de moins de
100 000 jetons, relevés le 24 octobre 2026 sur
[la page des tarifs d'Anthropic](https://platform.claude.com/docs/en/about-claude/pricing) :

| Poste | Prix par million de jetons |
|---|---|
| Entrée | 0,10 $ |
| Écriture en cache (5 minutes) | 0,125 $ |
| Lecture en cache | 0,01 $ |
| Sortie | 0,50 $ |

Le tarif à la minute de Voxtral n'a pas pu être lu sur les pages publiques de Mistral à cette date :
reportez-vous à [la page des tarifs de Mistral](https://mistral.ai/pricing) ou à la console de votre
fournisseur. Les prix changent : revérifiez-les avant de vous engager.

### Piste non codée

La voix est produite par Android ou par Piper. Une voix en ligne compatible avec l'API d'OpenAI se
brancherait de la même façon que la transcription en ligne (une clé, une adresse, un modèle), mais rien
de tel n'existe dans le code à ce jour.
