# Dépannage

Une question par panne rencontrée dans le code, avec le message exact et la correction. L'installation
pas à pas est dans [`INSTALLER.md`](INSTALLER.md), la configuration dans [`CONFIGURER.md`](CONFIGURER.md).
Les commandes sont écrites pour Windows (PowerShell), depuis la racine du dépôt.

## Sommaire

- [Compilation de l'APK](#compilation-de-lapk)
- [Démarrage du serveur](#démarrage-du-serveur)
- [Mot de réveil](#mot-de-réveil)
- [Connexion de la tablette ou du téléphone](#connexion-de-la-tablette-ou-du-téléphone)
- [Transcription et compréhension](#transcription-et-compréhension)
- [Santé, Mer et Vent](#santé-mer-et-vent)
- [Appli Home Assistant](#appli-home-assistant)
- [Garde-fou et tests](#garde-fou-et-tests)

## Compilation de l'APK

### Gradle s'arrête : maison.json absent

```text
<dossier>/maison.json absent : copier config-exemple/ en config/ et y mettre les vraies valeurs avant de compiler une APK.
```

Gradle ne compile jamais une APK sur la configuration fictive. Créez `config/` (étape 4 de
`INSTALLER.md`), ou désignez votre dossier par `ASSISTANT_VOCAL_CONFIG` ou `-PconfigDossier=<chemin>`. Un
chemin relatif part de la racine du dépôt, pas de `android/`.

### Gradle s'arrête : dictionnaire.json ou vue3d.html absent

```text
<dossier>/genere/android/dictionnaire.json absent : lancer python android/outils/exporter_dictionnaire.py.
```

```text
<dossier>/genere/android/maison3d/vue3d.html absent : lancer python carte/3d/generer_3d.py.
```

Lancez les deux générateurs depuis la racine du dépôt, avec le même dossier de configuration que Gradle :

```powershell
.venv\Scripts\python android/outils/exporter_dictionnaire.py
```

```powershell
.venv\Scripts\python carte/3d/generer_3d.py
```

Si `generer_3d.py` répond que `pieces.json` est absent, le plan du logement manque dans `carte/` de la
configuration.

### Gradle s'arrête sur le mot de réveil

```text
<dossier>/maison.json : reveil.mot vaut « <mot> » mais <dossier>/reveil/<mot>.onnx est absent.
```

Rangez le modèle openWakeWord dans `reveil/<mot>.onnx` de la configuration, ou retirez la section
`reveil` de `maison.json`. Le nom du fichier doit être `reveil.mot` en minuscules.

```text
<dossier>/maison.json : reveil.mot ne peut pas valoir « hey_jarvis », nom d'un modèle du dépôt.
```

Les noms `melspectrogram`, `embedding_model`, `hey_jarvis` et `hey_jarvis_v0.1` sont pris par les
modèles d'openWakeWord rangés dans l'APK. Renommez votre mot. Un simple avertissement signale aussi un
modèle sans sa licence (`<mot>.onnx.LICENSE`) : ajoutez-la à côté.

### Gradle s'arrête sur la carte du vent

```text
<dossier>/maison.json : vent.carte.cote (« carte/golfe_cote.txt ») absent de genere/android/, la carte du vent sortirait sans côte.
```

Avec `vent.actif` à `true`, les fichiers nommés par `vent.carte.cote` et `vent.carte.terre` doivent
exister dans `genere/android/` de la configuration. Copiez ceux de votre plan d'eau, ou passez
`vent.actif` à `false`.

### Gradle signale un jeton absent

```text
SATELLITE_JETON absent de poc/.env : le satellite sera refusé par le serveur.
```

Ce n'est qu'un avertissement : l'APK sort, mais sans jeton fixe, et le serveur la refusera tant qu'elle
n'est pas appairée. Ajoutez `SATELLITE_JETON=` suivi d'au moins 16 caractères dans `poc/.env`, puis
recompilez. Avec `-Putilisateur=<nom>`, c'est une erreur :

```text
SATELLITE_JETON_<NOM> absent de poc/.env.
```

Ajoutez la ligne `SATELLITE_JETON_<NOM>=...` correspondante. Le nom n'accepte que des lettres
minuscules, des chiffres et `_` :

```text
Propriété utilisateur invalide : lettres, chiffres et _ seulement.
```

### Gradle ne trouve pas le SDK ou Java

`SDK location not found` : `android/local.properties` manque ou ne contient pas `sdk.dir`. Ouvrez le
dossier `android/` dans Android Studio, qui le crée, ou écrivez la ligne `sdk.dir=` à la main, ou réglez
`ANDROID_HOME`.

`JAVA_HOME is not set and no 'java' command could be found in your PATH` : pointez `JAVA_HOME` vers le
JBR d'Android Studio :

```powershell
$env:JAVA_HOME = "C:\Program Files\Android\Android Studio\jbr"
```

Une plateforme Android 37 manquante ou une licence non acceptée arrête aussi la compilation :
l'appli est compilée avec `compileSdk` 37. Installez cette plateforme dans le gestionnaire du SDK
d'Android Studio et acceptez les licences.

### Gradle s'arrête : configuration illisible

```text
Configuration de la maison illisible (<dossier>/maison.json) : <détail>
```

`maison.json` n'est pas du JSON valide. Le détail donne la ligne fautive. Une virgule en trop en fin de
liste est l'erreur la plus courante.

### Sous Linux ou macOS, la compilation part dans un dossier étrange

Passez `-PdossierBuild="$HOME/assistant-vocal-build"` : le dossier de compilation par défaut, `C:/Dev/assistant-vocal-build`,
n'a de sens que sous Windows.

### L'APK compilée ne s'installe pas

Une APK de `assembleRelease` n'est pas signée par le projet et ne s'installe pas. Utilisez
`assembleDebug`, ou signez-la vous-même. `INSTALL_FAILED_UPDATE_INCOMPATIBLE` signale une signature
différente de l'appli déjà installée : il faut désinstaller, ce qui efface ses réglages, la clé retenue
du serveur, le jeton d'appairage et les visages.

## Démarrage du serveur

### Le serveur s'arrête faute de configuration

```text
Configuration de la maison illisible (<chemin>/maison.json) : <erreur>. Copier le dossier config-exemple/ en config/ (ou régler ASSISTANT_VOCAL_CONFIG) et y mettre les vraies valeurs de la maison.
```

Le serveur, l'assistant, l'export du dictionnaire et la vue 3D s'arrêtent tous ainsi quand le dossier de
configuration manque ou contient un `maison.json` illisible. Si le dossier manque, copiez `config-exemple/`
en `config/`, ou réglez `ASSISTANT_VOCAL_CONFIG`.

Si le dossier existe et que `<erreur>` contient `BOM`, `Expecting value` ou `Expecting ','`, ne recopiez pas
l'exemple : vos modifications seraient perdues. Le fichier n'est pas du JSON valide en UTF-8 sans BOM.
Réenregistrez-le en « UTF-8 » (sans BOM) dans votre éditeur, ou corrigez la virgule ou le guillemet signalé.
Sous Windows PowerShell 5.1, `Set-Content -Encoding utf8` ajoute un BOM : préférez un éditeur de texte.

`ASSISTANT_VOCAL_CONFIG` doit être réglée dans le terminal, pas dans `poc/.env` : le dossier est lu au
chargement du programme, avant `poc/.env`. Il en va de même pour `JARVIS_DONNEES`, `VAD_MODELE` et
`JARVIS_PORT_TLS`.

```powershell
$env:ASSISTANT_VOCAL_CONFIG = "D:\maison\config"
```

### Le serveur s'arrête : SATELLITE_JETON absent ou trop court

```text
SATELLITE_JETON absent ou trop court dans poc/.env
```

Le serveur exige au moins un jeton fixe d'au moins 16 caractères, même en essai. Inventez-en un :

```powershell
.venv\Scripts\python -c "import secrets; print(secrets.token_urlsafe(32))"
```

et écrivez-le dans `poc/.env` (`SATELLITE_JETON=...`). Recompilez l'APK du propriétaire ensuite, puisque
ce jeton y est compilé.

### Le serveur démarre mais ne pilote rien

```text
  ! HA_TOKEN absent de poc/.env : pilotage de la maison désactivé, LLM seul.
```

Créez un jeton d'accès longue durée dans Home Assistant (page de votre profil, onglet Sécurité) et
écrivez-le dans `poc/.env` (`HA_TOKEN=...`). Vérifiez aussi `HA_URL`, et que le serveur n'est pas en
essai : sa dernière ligne de démarrage dit `ESSAI, rien n est exécuté` ou `actions réelles`.

### Le serveur ne démarre pas : port déjà utilisé

Python signale une adresse déjà utilisée (`OSError`, erreur 10048 sous Windows, 98 sous Linux). Un autre
serveur tourne déjà sur 8765 ou 8766, souvent le calibrage du mot de réveil, qui utilise les mêmes ports.
Fermez l'autre fenêtre, ou changez de ports avec `--port` et `--port-tls`.

### Avertissement sur le propriétaire

```text
maison : section proprietaire absente de <dossier>/maison.json, propriétaire « Moi » (santé, jeton principal et correction du prénom en dépendent)
```

Ajoutez la section `proprietaire` (`nom`, `cle`, `variantes`) à `maison.json`. Sans elle, le jeton
`SATELLITE_JETON` est rattaché à « moi », la santé ne s'affiche pour personne et l'APK s'affiche au nom
de « Moi ».

### Détection de parole ou vision absente au démarrage

```text
  détection de parole : seuil d énergie (modèle Silero absent)
```

`poc/modeles/silero_vad.onnx` manque (il est pourtant dans le dépôt) ou ne se charge pas. Vérifiez le
clone, ou la variable `VAD_MODELE`.

Si la ligne `vision : YuNet et SFace prêts pour les tablettes` n'apparaît pas, SFace manque :

```powershell
.venv\Scripts\python poc/outils/telecharger_modeles.py
```

Une ligne `vision indisponible (...)` signale un modèle présent mais illisible par OpenCV.

## Mot de réveil

### Le mot de réveil ne répond pas

Vérifiez dans l'ordre :

1. Où il est guetté. Dans l'appli, section Voix et réveil : Sur cet appareil (modèle de l'APK) ou Sur le
   serveur (modèle du PC, ou appli openWakeWord de Home Assistant en profil `ha`).
2. Quel mot est actif. Le PC prend `MOT_REVEIL` de `poc/.env`, mais retombe sans le dire sur « Hey
   Jarvis » si `reveil/<mot>.onnx` est absent de la configuration. L'appli ne propose le mot de la
   configuration que s'il a été compilé dans l'APK (section `reveil` et modèle présents à la
   compilation). L'appli Home Assistant ne connaît que « Hey Jarvis ».
3. Le seuil. Lancez `Calibrer le mot de réveil.bat` (serveur arrêté), suivez les deux étapes, puis
   acceptez d'enregistrer le seuil dans `poc/.env` (`SEUIL_REVEIL`). Le seuil se donne aussi au
   lancement avec `--seuil`.
4. Le micro. Sans la permission du micro, l'appli affiche `Autorise le micro, puis appuie de nouveau sur
   Démarrer`.

### Le serveur coupe la connexion d'un téléphone dès son arrivée

Le journal du serveur montre :

```text
ValueError: Could not find pretrained model for model name 'hey_jarvis'
```

Les modèles openWakeWord du PC n'ont jamais été téléchargés : le serveur ne le fait pas lui-même. Le
script des modèles s'en charge depuis la 0.25.1 :

```powershell
.venv\Scripts\python poc/outils/telecharger_modeles.py
```

Il doit afficher `openWakeWord : hey_jarvis prêt`. Il apporte aussi les modèles de prétraitement dont
un mot de réveil personnalisé a besoin. S'il s'arrête sur `openwakeword absent : installer d'abord les
dépendances (pip install -r poc/requirements.txt)`, installez d'abord les dépendances :

```powershell
.venv\Scripts\python -m pip install -r poc/requirements.txt
```

## Connexion de la tablette ou du téléphone

### L'appli refuse l'adresse

```text
L'adresse du PC fixe doit commencer par ws:// ou wss://
```

Saisissez l'adresse complète, port compris, de préférence chiffrée : `wss://<adresse IP>:8766`. Même
règle pour l'adresse de Home Assistant.

### Jeton refusé

Dans l'appli :

```text
Jeton refusé par le serveur : appaire cet appareil (écran Appareils)
```

et dans le journal du serveur :

```text
connexion refusée (jeton invalide) depuis <adresse>
```

L'APK porte un jeton que le serveur ne connaît pas : APK compilée avant un changement de
`SATELLITE_JETON`, compilée sans jeton, ou jeton différent dans l'appli Home Assistant
(`satellite_jeton`). Corrigez `poc/.env`, recompilez et réinstallez l'APK, ou appairez l'appareil depuis
l'écran Appareils et accès. Une ligne `SATELLITE_JETON_<NOM>` retirée de `poc/.env` coupe l'accès de
cette personne au redémarrage du serveur. L'appli Home Assistant ne connaît que le jeton de son option
`satellite_jeton` et les appareils appairés.

```text
Jeton refusé (serveur antérieur à 0.17.0 ? il attend l'ancien accès)
```

L'appli s'est repliée sur le port en clair et le serveur refuse. Mettez le serveur à jour et passez
l'adresse en `wss://<adresse>:8766`.

### La clé du serveur a changé

```text
La clé du serveur a changé (<hôte>:8766). Connexion refusée : si tu as réinstallé le serveur, oublie l'ancienne clé dans l'écran Appareils.
```

L'appareil a retenu à sa première connexion l'empreinte de la clé du serveur, et le serveur en présente
une autre : dossier `poc/tls/` effacé, `JARVIS_DONNEES` différent, serveur réinstallé sur une autre
machine, appli Home Assistant réinstallée. Comparez l'empreinte affichée au démarrage du serveur
(`port chiffré 8766, empreinte de la clé sha256/...`) avec celle de l'écran Appareils et accès. Si le
changement est voulu, appuyez sur Oublier la clé du serveur. Sinon, ne forcez rien : un autre appareil
répond peut-être à cette adresse. L'appli ne se replie jamais en clair après ce refus.

Pour éviter ce cas, sauvegardez le dossier `tls/` des données et remettez-le en place lors d'une
réinstallation.

### L'appairage n'aboutit pas

Le nouvel appareil affiche un code, puis rien. L'appairage n'existe que sur le port chiffré : l'adresse
doit être `wss://...:8766`. Un appareil déjà connecté doit accepter la demande dans son écran Appareils
et accès, en moins de 5 minutes, faute de quoi le serveur répond `appairage_refuse`. Le premier appareil
ne peut pas s'appairer seul : il doit porter le jeton fixe compilé dans son APK.

### Le serveur ne voit jamais l'appareil

Rien n'apparaît dans le journal du serveur. Vérifiez ces points :

- Le PC et la tablette sont sur le même réseau, et l'adresse IP du PC n'a pas changé.
- Le pare-feu de Windows laisse entrer les ports TCP 8765 et 8766 (le dépôt ne règle pas le pare-feu).
- Le serveur tourne, et sa dernière ligne cite bien le port chiffré.

Règle de pare-feu, dans un PowerShell administrateur :

```powershell
New-NetFirewallRule -DisplayName "Assistant vocal" -Direction Inbound -Protocol TCP -LocalPort 8765,8766 -Action Allow -Profile Private
```

### La tablette s'arrête la nuit ou ne redémarre pas seule

En mode station, l'appli doit être exemptée de l'optimisation de batterie et autorisée à s'afficher
par-dessus les autres applications, et sur Samsung être ajoutée aux applications jamais mises en veille.
Section Station des réglages, puis bouton Désactiver l'optimisation de batterie de la section Général.

## Transcription et compréhension

### Transcription sur la tablette impossible

Le Diagnostic de l'appli montre :

```text
modèle absent de <dossier> : à copier par adb (1,03 Go)
```

Les quatre fichiers de Canary manquent dans `Android/data/assistant.vocal.jarvis/files/canary/`. Copiez-les
comme décrit à l'étape 7 de `INSTALLER.md`, ou choisissez un autre lieu de transcription. Lancez l'appli
une fois avant la copie : Android 16 refuse de lire un dossier créé par adb. Si le dossier a été créé
par adb, supprimez-le, relancez l'appli, puis recopiez.

### Pas de LLM sur l'appareil

```text
aucun modèle .litertlm dans <dossier> : à copier par adb
```

Déposez un fichier `.litertlm` reconnu dans `Android/data/assistant.vocal.jarvis/files/llm/`, ou laissez le repli
à Claude par le serveur.

### Les phrases inconnues ne reçoivent jamais de réponse

L'assistant répond :

```text
Le modèle de langage ne répond pas. Le PC est peut-être occupé.
```

Le cerveau de repli n'est pas joignable. Sans ligne `LLM_FOURNISSEUR` dans `poc/.env`, le code choisit
le LLM local (`llama-server` sur `http://127.0.0.1:8080/v1`), qui ne tourne pas forcément. Mettez
`LLM_FOURNISSEUR=claude` et une clé `ANTHROPIC_API_KEY` valide, ou démarrez votre LLM local. Les fichiers
`.bat` du serveur forcent déjà `claude`.

### La musique est refusée

Les commandes de musique demandent une section `appareils.musique` avec une enceinte `toutes` dans
`maison.json`, et l'intégration Music Assistant dans Home Assistant. Sans elles, elles sont refusées
volontairement.

### Speech-to-Phrase ne comprend pas mes phrases

Speech-to-Phrase ne reconnaît que les phrases que Home Assistant connaît. Envoyez votre dictionnaire à
Home Assistant :

```powershell
.venv\Scripts\python ha-app/configurer-ha.py
```

Pour les autres phrases, réglez une transcription en ligne (`STT_API_CLE`, ou l'option `stt_api_cle` de
l'appli Home Assistant) : elle sert de repli quand Speech-to-Phrase ne rend rien.

## Santé, Mer et Vent

### La santé ne s'affiche pas

Toutes ces conditions sont nécessaires :

1. Un service `sante-api` joignable par Tailscale depuis le PC (il ne fait pas partie de ce dépôt), et
   `SANTE_JETON` dans `poc/.env`. Sans jeton, le serveur affiche `santé : relais éteint (SANTE_JETON
   absent)`.
2. Le serveur du PC : l'appli Home Assistant ne relaie pas la santé.
3. La liaison chiffrée. En clair, le serveur refuse avec `santé réservée à la liaison chiffrée (wss)`.
4. Un appareil permis par `SANTE_PERSONNES` (le propriétaire par défaut). Sinon : `santé non permise
   pour cet appareil`. Un appareil appairé se désigne par `appareil:<id>`, jamais par son nom.
5. La vision active, et un visage enregistré sous le prénom exact de `proprietaire.nom` de `maison.json`,
   seul devant la tablette et reconnu avec assurance. La santé disparaît dès qu'un autre visage
   apparaît.

Si le serveur écrit `sante-api ne répond pas`, le service est éteint ou Tailscale est coupé sur le PC.
Le jeton ne part jamais vers une adresse hors de Tailscale.

### Les pages Mer et Vent n'apparaissent pas

Le serveur dit pourquoi au démarrage :

```text
  météo marine : éteinte (pas de section « mer » active dans maison.json)
```

```text
  vent mesuré : éteint (pas de sections « mer » et « vent » actives dans maison.json)
```

La page Mer demande une section `mer` avec `"actif": true` et au moins un point. La page Vent demande
les deux sections `mer` et `vent` actives. `METEO_MER=0` dans `poc/.env` éteint la météo marine et le vent
mesuré, `VENT_MESURE=0` le vent mesuré seul (le message de démarrage dit alors `METEO_MER=0` ou
`VENT_MESURE=0`).

L'appli ne montre ces pages que si le serveur auquel elle parle annonce la capacité. En mode Cet
appareil, c'est l'appli Home Assistant ou le PC : redéployez l'appli Home Assistant après avoir activé
les sections, puisqu'elle lit sa propre copie de `maison.json`. Pour le vent, recompilez aussi l'APK,
qui embarque le trait de côte. Les données viennent de sources publiques en ligne : sans Internet, les
pages restent vides.

## Appli Home Assistant

### deployer.sh s'arrête aussitôt

```text
<dossier>/maison.json absent : copier config-exemple/ en config/ et l'adapter.
```

Le script refuse de déployer sans configuration réelle (`maison.json` et `commandes.yaml`). Créez
`config/` ou réglez `ASSISTANT_VOCAL_CONFIG`.

Sous Windows, lancez-le dans Git Bash. Le script appelle `python` pour lire l'alias SSH : si Git Bash ne
le trouve pas, ajoutez Python au `PATH` de ce terminal. Une erreur SSH signale un alias `reseau.ssh_ha`
absent de `~/.ssh/config`, ou une appli SSH qui refuse la clé.

### L'appli n'apparaît pas dans Home Assistant

Le script copie l'appli dans `/local_apps/jarvis`. Dans Home Assistant, demandez une recherche de mises
à jour dans la boutique des applis pour faire apparaître les applis locales. Si votre appli SSH range
les applis locales ailleurs, adaptez le chemin dans `ha-app/deployer.sh`. L'appli n'est déclarée que pour
`amd64` : un Home Assistant sur Raspberry Pi ne la propose pas.

### Le journal de l'appli dit ABSENT

```text
Iris : clé Anthropic ABSENTE, jeton satellites ABSENT, transcription en ligne non configurée
```

Réglez les options `anthropic_api_key` et `satellite_jeton` (au moins 16 caractères) dans l'onglet de
configuration de l'appli, ou envoyez-les depuis `poc/.env` :

```powershell
.venv\Scripts\python ha-app/configurer-options.py
```

Le script affiche `réponse du superviseur :` suivi de la réponse. Une erreur à cet endroit signale une
session SSH sans `SUPERVISOR_TOKEN` ou une appli installée sous un autre identifiant que `local_jarvis`.

## Garde-fou et tests

### Le garde-fou refuse un commit

Le message se termine par :

```text
Garde-fou : commit refusé. Retirer ces éléments de l'index (git restore --staged <fichier>),
mettre les secrets dans poc/.env, puis recommencer.
```

Il est précédé d'une ou plusieurs de ces rubriques :

| Rubrique | Cause | Correction |
|---|---|---|
| `Fichiers à ne jamais versionner (secrets, données personnelles, binaires produits) :` | `.env`, `local.properties`, keystore, clés, `poc/tls/`, `maison.json` hors de l'exemple, `config/`, journaux, `appareils.json`, APK, sons, poids de modèles | `git restore --staged <fichier>`, puis vérifier `.gitignore`. |
| `Motifs de secrets dans des lignes ajoutées (valeurs masquées) :` | Un jeton Home Assistant, une clé d'API, une clé privée, ou une variable de `poc/.env` remplie, dans un fichier suivi | Retirer la valeur du fichier et la mettre dans `poc/.env`. |
| `Fichiers de plus de 5 Mo` | Un gros fichier | Le laisser hors du dépôt. Le seuil se règle par `GARDE_FOU_TAILLE_MAX_MO`. |

Pour un faux positif, ajoutez le commentaire `garde-fou: ignorer` sur la ligne concernée. Ne contournez
pas le garde-fou par `git commit --no-verify` sans l'accord du propriétaire du dépôt.

### Le garde-fou refuse un envoi

```text
Garde-fou : envoi de <branche> vers <branche distante> refusé. Un commit envoyé contient ce qui précède.
Le retirer des commits à envoyer (git commit --amend, ou git rebase sur les commits pas encore envoyés), ne pas contourner.
```

Un commit pas encore envoyé contient l'élément signalé. Le supprimer dans un nouveau commit ne suffit
pas : il resterait dans l'historique envoyé. Corrigez le dernier commit avec `git commit --amend`, ou les
précédents avec `git rebase`, tant qu'ils n'ont pas quitté la machine.

Contrôlez tout l'historique avec :

```bash
bash .githooks/garde-fou.sh --historique
```

Si ce contrôle répond :

```text
Garde-fou : l'historique contient ce qui précède. Ne pas partager ce dépôt tel quel : publier un instantané sans historique.
```

l'élément est déjà dans des commits anciens. Ne partagez pas ce dépôt tel quel : publiez un instantané
des fichiers actuels, sans historique, dans un nouveau dépôt.

### Le garde-fou ne se déclenche pas

Vérifiez qu'il est activé dans ce clone :

```powershell
git config --get core.hooksPath
```

La réponse doit être `.githooks`. Les crochets, `android/gradlew` et `ha-app/deployer.sh` sont rangés
exécutables dans git. Seule une copie du dépôt faite sans git (archive décompressée) peut perdre ce droit.
Sous Linux et macOS, Git ignore alors les crochets et `./gradlew` refuse de se lancer :
`chmod +x .githooks/* android/gradlew ha-app/deployer.sh` le rend.

### Les tests Python échouent en masse

Si `ASSISTANT_VOCAL_CONFIG` est réglée dans le terminal, les tests tournent sur ce dossier au lieu de
`config-exemple/`, et les cas écrits pour l'exemple échouent. Retirez la variable :

```powershell
Remove-Item Env:ASSISTANT_VOCAL_CONFIG
```

Un `ModuleNotFoundError` sur `websockets`, `onnx_asr` ou `pytest` signale un environnement installé avant
la 0.25.1, quand `poc/requirements.txt` ne les listait pas encore. Réinstallez les dépendances :

```powershell
.venv\Scripts\python -m pip install -r poc/requirements.txt
```

### L'installation des dépendances échoue sous Linux

L'erreur porte sur `tflite-runtime`, demandé par openwakeword. Sous Linux, openwakeword 0.6.0 exige
`tflite-runtime`, qui n'existe pas au-delà de Python 5.11 : Python 5.11 est obligatoire. Recréez
l'environnement avec cette version :

```bash
rm -rf .venv
```

```bash
python5.11 -m venv .venv
```

```bash
.venv/bin/python -m pip install -r poc/requirements.txt
```

Sous Windows, Python 5.11 et 5.13 conviennent tous les deux.

### Le test de l'export d'exemple échoue

```text
export d'exemple périmé : python android/outils/exporter_dictionnaire.py --exemple, puis le committer
```

`test_export_exemple_a_jour` refait l'export de `config-exemple/commandes.yaml` dans un dossier temporaire
et échoue s'il diffère de `config-exemple/genere/android/dictionnaire.json`. Depuis 0.32.2 il ne réécrit
plus ce fichier lui-même : refaites l'export à la main, puis committez-le avec le dictionnaire d'exemple :

```powershell
.venv\Scripts\python android/outils/exporter_dictionnaire.py --exemple
```
