# Configurer l'assistant vocal

Référence de la configuration d'une maison, écrite pour le serveur 0.33.0 et l'appli Android 0.35.0
(25/10/2026). Le moteur ne contient aucune donnée réelle : tout ce qui décrit un logement vit dans un
dossier de configuration à part. Les exemples ci-dessous viennent de `config-exemple/` (valeurs fictives)
ou sont inventés.

Sommaire :

1. [Le dossier de configuration](#1-le-dossier-de-configuration)
2. [maison.json, section par section](#2-maisonjson-section-par-section)
3. [Le dictionnaire commandes.yaml](#3-le-dictionnaire-commandesyaml)
4. [Le plan du logement](#4-le-plan-du-logement)
5. [Les modules facultatifs](#5-les-modules-facultatifs)
6. [La sécurité et ce que la configuration en règle](#6-la-sécurité-et-ce-que-la-configuration-en-règle)

## 1. Le dossier de configuration

### Où le moteur le cherche

Côté Python (`poc/maison.py`), dans cet ordre :

1. La variable d'environnement `ASSISTANT_VOCAL_CONFIG`, ou son ancien nom `MAISON_DOSSIER`. Un chemin
   relatif part du dossier courant du programme.
2. Le dossier `config/` à la racine du dépôt.
3. L'ancien dossier `maison/`, seulement si `config/maison.json` n'existe pas et que `maison/maison.json`
   existe. Un avertissement demande alors de le renommer en `config/`.

Sans `maison.json` lisible (fichier absent, JSON invalide, ou contenu qui n'est pas un objet), le programme
s'arrête avec un message. Il ne retombe jamais sur `config-exemple/`, pour ne pas tourner avec des listes
de sécurité fictives.

Côté appli Android (`android/app/build.gradle.kts`), l'ordre est le même, avec deux propriétés Gradle en
tête : `-PconfigDossier=...` (ancien nom `-PmaisonDossier`), puis `ASSISTANT_VOCAL_CONFIG`, `MAISON_DOSSIER`,
`config/` et `maison/`. Un chemin relatif part de la racine du dépôt. Sans `maison.json`, la fabrication
d'une APK est refusée. Les tests unitaires tournent toujours sur `config-exemple/`, sauf avec
`-PmaisonTests=reel`.

Les tests Python (`poc/tests/conftest.py`) règlent `ASSISTANT_VOCAL_CONFIG` sur `config-exemple/` quand la
variable n'est pas déjà définie.

L'appli Home Assistant reçoit sa configuration par `bash ha-app/deployer.sh`, qui cherche le dossier dans le
même ordre, puis copie seulement `maison.json` et `commandes.yaml` dans `/app/config` du conteneur. Le
démarrage de l'appli règle `ASSISTANT_VOCAL_CONFIG=/app/config` et `JARVIS_DONNEES=/data`. Chaque
déploiement remplace `/app/config`. Le plan, le mot de réveil et `genere/` ne sont pas copiés.

### Ce qu'il contient

| Chemin | Rôle | Lu par |
|---|---|---|
| `maison.json` | Adresses, fuseau, propriétaire, appareils, consignes du LLM, alias pour Assist, listes de sécurité, météo marine, mot de réveil. | Tout le moteur, et l'APK qui le compile en entier dans `BuildConfig.MAISON_JSON`. |
| `commandes.yaml` | Dictionnaire des phrases et des actions Home Assistant, vue du LLM, "ma chambre" selon qui parle. | `poc/dictionnaire.py`, `android/outils/exporter_dictionnaire.py`, `ha-app/configurer-ha.py`. |
| `carte/` | Plan du logement : `pieces.json`, `meubles.json`, `lampes.json`, et les sorties `plan.svg`, `plan.png`, `modele.glb`. | `carte/generer_plan.py`, `carte/3d/generer_3d.py`. |
| `reveil/` | Facultatif : modèle `reveil/<mot>.onnx` du mot de réveil et sa licence `reveil/<mot>.onnx.LICENSE`. | `poc/assistant.py`, `build.gradle.kts`. |
| `genere/` | Fichiers produits, à refaire quand leur source change. | Voir ci-dessous. |

Contenu de `genere/` :

| Fichier | Produit par | Usage |
|---|---|---|
| `genere/android/dictionnaire.json` | `.venv\Scripts\python android/outils/exporter_dictionnaire.py` | Dictionnaire embarqué dans l'APK. Obligatoire pour fabriquer une APK. Les phrases apprises vont à part, dans le dossier de données (ligne suivante). |
| `genere/android/maison3d/vue3d.html` | `.venv\Scripts\python carte/3d/generer_3d.py` | Vue 3D du logement embarquée dans l'APK. Obligatoire pour fabriquer une APK. |
| `genere/android/carte/*.txt` | À fournir (aucun générateur dans le moteur) | Trait de côte et terre de la carte du vent mesuré (section `vent`). |
| `genere/ha/jarvis_dictionnaire.apercu.json` | `python ha-app/configurer-ha.py --essai` | Aperçu de l'automatisation envoyée à Home Assistant. |

Tout le dossier `genere/android/` devient un dossier d'assets de l'APK.

### En faire un dépôt privé

Le dépôt du moteur ignore `/config/` (voir `.gitignore`). La configuration peut donc être son propre dépôt
privé, cloné à cet endroit :

```bash
cp -r config-exemple config
cd config
git init
git add .
git commit -m "Configuration de la maison"
git remote add origin <adresse de votre dépôt privé>
git push -u origin main
```

Sur un autre poste, il suffit de cloner ce dépôt dans `config/` à la racine du moteur, ou ailleurs avec
`ASSISTANT_VOCAL_CONFIG` qui pointe dessus.

`genere/android/dictionnaire.json` ne contient que ce qui vient de `commandes.yaml` : depuis l'appli 0.32.2,
les phrases apprises de la machine partent dans un export à part, hors de ce dossier (voir
[l'export à refaire avant de compiler l'APK](#lexport-à-refaire-avant-de-compiler-lapk)). Le versionner ne
versionne donc pas ces phrases. Un `dictionnaire.json` committé dans un dépôt de configuration avant la 0.32.2
contient encore les phrases apprises jusqu'au prochain export, et l'historique git les garde : le refaire,
puis réécrire l'historique si ces phrases ne doivent pas y rester.

### Ce qui n'y va pas

La configuration décrit la maison, elle ne contient ni secret ni donnée d'usage.

| Donnée | Où elle reste |
|---|---|
| Jeton Home Assistant, jetons des satellites (`SATELLITE_JETON`, `SATELLITE_JETON_<NOM>`), clé Anthropic, clé de transcription en ligne, jeton du service de santé | `poc/.env` de chaque machine (modèle : `poc/.env.exemple`). Sur l'appli Home Assistant, ses options (`ha-app/configurer-options.py`). |
| Phrases apprises (`commandes_apprises.yaml` et leur export pour l'appli, `genere/android/dictionnaire_appris.json`), journaux (`journal/`), appareils appairés (`appareils.json`), clés TLS (`tls/`) | Dossier de données de la machine : `JARVIS_DONNEES`, `poc/` par défaut sur le PC, `/data` dans l'appli Home Assistant. |
| Profils de visages | Fichier privé de l'appli, sur la tablette seulement. |
| APK | Nulle part : elle embarque `maison.json` en entier et le jeton `SATELLITE_JETON`, elle ne doit pas circuler. |

## 2. maison.json, section par section

### Vue d'ensemble

| Section | Lue par | Si elle manque |
|---|---|---|
| `_lisez_moi` | Personne | Texte d'aide, ignoré par le code. |
| `reseau` | `poc/maison.py`, `poc/assistant.py`, `poc/sante.py`, `poc/sante_hist.py`, `poc/serveur_satellite.py`, `ha-app/*`, `build.gradle.kts` | Adresses vides. `deployer.sh` s'arrête. |
| `acces` | `poc/acces.py`, `poc/maison.py`, `poc/serveur_satellite.py` | Écoute sur `0.0.0.0`, réseaux privés et tailnet autorisés, ancien accès permis, propriétaire seul administrateur. |
| `routines` | `poc/routines.py`, `poc/assistant.py`, `poc/serveur_satellite.py` | Routines actives avec les limites par défaut décrites plus bas. |
| `journal` | `poc/assistant.py` | Historique gardé 30 jours, journal des durées limité à 512 Ko sur 5 fichiers, phrases absentes de la console. |
| `fuseau` | `poc/securite.py`, `poc/assistant.py`, `Securite.kt` | `UTC`. |
| `securite` | `poc/securite.py`, `Securite.kt` | Listes vides. |
| `appareils` | `poc/assistant.py`, `SortieSon.kt`, `Appareils.kt`, `MaisonEnGrand.kt`, outils de banc | Musique refusée proprement, écran Musique sans enceinte. |
| `llm` | `poc/assistant.py`, `CerveauAppareil.kt` | Consignes génériques. |
| `ha` | `ha-app/configurer-ha.py` | Aucun alias ajouté, rien d'exposé en plus. |
| `assistant` | `poc/maison.py`, `ha-app/deployer.sh`, `ha-app/configurer-ha.py`, `ha-app/jarvis/app/demarrage.py`, `ConfigMaison.kt`, `build.gradle.kts` | Assistant nommé `Assistant`. |
| `proprietaire` | `poc/maison.py`, `poc/dictionnaire.py`, `poc/sante.py`, `poc/serveur_satellite.py`, `ConfigMaison.kt`, `DictionnaireLocal.kt`, `Sante.kt`, `build.gradle.kts` | Propriétaire nommé `Moi`, avertissement au démarrage et à la compilation. |
| `mer` | `poc/meteo_mer.py`, `MeteoMer.kt`, `MeteoQuestion.kt`, `EcranMeteo.kt` | Météo marine éteinte. |
| `vent` | `poc/vent_mesure.py`, `MeteoVent.kt`, `EcranVent.kt`, `build.gradle.kts` | Vent mesuré éteint. Dans l'appli, la page Mer disparaît aussi. |
| `reveil` | `poc/assistant.py`, `ReveilLocal.kt`, `SatelliteService.kt`, `build.gradle.kts` | Sans section, le mot vaut "assistant" (ou `MOT_REVEIL`), avec repli sur "Hey Jarvis" si son modèle manque. |
| `reglages` | `poc/liste_blanche.py`, `ReglageTele.kt`, `Maison3d.kt` | Aucune appli ni aucun interrupteur en plus, volet de la télé sans tuiles de sources, vue 3D sans correspondance d'entités. |
| `correspondance_pieces` | `poc/mesures.py`, `poc/serveur_satellite.py`, `Mesures.kt` | Aucune mesure par pièce : l'appli ne lit aucun capteur et le serveur n'annonce pas la capacité `mesures`. |

Aucune autre section n'est lue par le code.

### `reseau`

Adresses des services de la maison.

| Champ | Type | Effet |
|---|---|---|
| `ha_url` | texte | Adresse de Home Assistant utilisée par l'assistant et le serveur du PC. `HA_URL` de `poc/.env`, quand elle est définie, passe devant. |
| `sante_url` | texte | Adresse du service de santé pour le relais (voir [la santé](#santé)). `SANTE_URL` de `poc/.env` passe devant. |
| `sante_donnees_url` | texte | Adresse du fichier `data-auto.js` du tableau de bord de santé, pour l'historique. Aucune variable ne la remplace. |
| `ssh_ha` | texte | Alias SSH de la machine Home Assistant. Sert à `ha-app/deployer.sh`, à `ha-app/configurer-options.py`, et au serveur du PC pour joindre les applis Wyoming de Home Assistant (`ssh <alias> nc <hôte> <port>`). |
| `android_serveur_pc` | texte | Adresse wss par défaut du serveur du PC, compilée dans l'APK (`BuildConfig.SERVEUR_PC_DEFAUT`) et modifiable dans les réglages de l'appli. |
| `android_serveur_ha` | texte | Adresse wss par défaut de l'appli Home Assistant, compilée de la même façon (`SERVEUR_HA_DEFAUT`). |
| `android_hotes_pc` | texte | Noms d'hôte séparés par des virgules (par exemple un nom mDNS en `.local`) essayés avant l'adresse enregistrée pour joindre le serveur du PC, si son IP a changé. Vide : aucune découverte. |
| `android_hotes_ha` | texte | Même chose pour l'appli Home Assistant. |

```json
"reseau": {
  "ha_url": "http://homeassistant.local:8123",
  "ssh_ha": "ha",
  "android_serveur_pc": "wss://192.168.0.10:8766",
  "android_serveur_ha": "wss://192.168.0.20:8766",
  "android_hotes_pc": "pc-maison.local",
  "android_hotes_ha": "homeassistant.local"
}
```

Un champ absent vaut une chaîne vide. Sans `ha_url` ni `HA_URL`, Home Assistant n'est pas joignable. Sans
`ssh_ha`, `deployer.sh` s'arrête sur une erreur Python.

### `acces`

Qui peut se connecter au serveur du PC et qui peut le gouverner. Chaque champ est facultatif.

| Champ | Type | Effet |
|---|---|---|
| `ecoute` | liste de textes | Adresses sur lesquelles les ports 8765 et 8766 s'ouvrent. Défaut : `["0.0.0.0"]` (toutes). Le filtre par réseau ci-dessous s'applique dans tous les cas. |
| `reseaux_autorises` | liste de CIDR | Réseaux dont une connexion est acceptée. `"*"` ou `0.0.0.0/0` ouvre à tous. Absente, la liste vaut `127.0.0.0/8`, `::1/128`, `10.0.0.0/8`, `172.16.0.0/12`, `192.168.0.0/16`, `169.254.0.0/16`, `100.64.0.0/10` (tailnet), `fe80::/10` et `fd00::/8`. Une entrée illisible est ignorée avec un message au démarrage. Une connexion refusée est fermée avec le code 4003, y compris sur `/appairage`. |
| `ancien_acces` | booléen | Accepte `ws://...:8765/?jeton=` sur le port en clair. Permis par défaut. `JARVIS_ANCIEN_ACCES` de `poc/.env` (ou l'option `ancien_acces` de l'appli Home Assistant), quand il est réglé, passe devant. Le jeton en en-tête `Authorization: Bearer` marche toujours. |
| `administrateurs` | liste de textes | Identités administrateurs en plus du propriétaire (`proprietaire.cle`), par exemple `appareil:ab12cd34` pour un appareil appairé (l'identifiant s'affiche dans l'écran Appareils et accès). |
| `roles` | objet | Rôle de chaque jeton fixe de `poc/.env` : clé de l'identité (le nom du jeton, en minuscules) vers `habitant`, `partage` ou `invite`. Un jeton absent de la liste est `habitant`. Une valeur inconnue vaut `invite`. La clé du propriétaire reste `administrateur` quoi qu'on écrive ici (la valeur contraire est ignorée, avec un avertissement au démarrage), et `administrateur` n'est pas une valeur permise ici. |
| `invitation_essais_par_ip` | entier | Essais de code d'invitation permis à une même adresse source dans la fenêtre ci-dessous, puis cette adresse seule est bloquée. Défaut : 3. Une valeur absente, nulle ou illisible rend le défaut. |
| `invitation_fenetre_s` | entier | Durée en secondes de la fenêtre glissante où les essais d'une adresse sont comptés. Défaut : 120. |
| `invitation_essais_global` | entier | Filet toutes adresses confondues : au-delà, le code d'invitation est détruit (balayage depuis de nombreuses adresses). Défaut : 30. |

```json
"acces": {
  "ecoute": ["0.0.0.0"],
  "reseaux_autorises": ["127.0.0.0/8", "::1/128", "10.0.0.0/8", "172.16.0.0/12", "192.168.0.0/16", "100.64.0.0/10"],
  "ancien_acces": true,
  "administrateurs": [],
  "roles": {"camille": "habitant", "tablette": "partage"}
}
```

Seuls les administrateurs voient le code d'appairage, acceptent ou révoquent un appareil, changent le mode,
le cerveau ou la transcription et lisent la liste des manques. Un appareil appairé ou amorcé n'est donc pas
administrateur tant qu'il n'est pas listé ici. Le déroulé de l'appairage et de l'amorçage est dans
[INSTALLER.md](INSTALLER.md#6-liaison-chiffrée-et-appairage).

#### Les rôles (0.38.0)

Le rôle d'une identité borne ses droits. Il y en a quatre. Le rôle « propriétaire » de la conception s'appelle
`administrateur` dans le code et dans les fichiers : c'est le même.

| Rôle | Qui l'a | Ce qu'il permet |
|---|---|---|
| `administrateur` | La clé `proprietaire.cle` et les clés de `acces.administrateurs`, rien d'autre. | Tous les messages de gestion : appareils, appairage, invitation, rôles et personnes, mode, cerveau, transcription, manques. Peut déclarer la personne qui parle. |
| `habitant` | Un jeton fixe absent de `acces.roles`, ou listé en `habitant`. Un appareil appairé au rôle `habitant`. | Parler à l'assistant. La personne reconnue n'est jamais celle que le message déclare : un jeton fixe vaut sa clé (si c'est un habitant connu), un appareil appairé vaut le champ `personne` de son entrée, sinon aucune. |
| `partage` | Un jeton fixe listé en `partage`, un appareil appairé à ce rôle. | Comme `habitant`, mais la personne déclarée est acceptée si c'est un habitant connu (tablette partagée dont la caméra dit qui parle). |
| `invite` | Un appareil dont l'entrée d'`appareils.json` n'a pas de champ `role` ou un rôle inconnu, un jeton fixe à la valeur inconnue. | Parler à l'assistant, sans aucune personne reconnue. |

Règles qui ne bougent pas :

- `administrateur` ne s'attribue jamais depuis l'écran Appareils et accès, ni par une invitation, ni à
  l'appairage, ni par `changer_role`. Le rôle d'un administrateur ne se change pas d'ici non plus.
- Un appareil appairé garde le rôle écrit dans `appareils.json`. Sans champ `role` ou avec un rôle inconnu, il
  vaut `invite`, et le fichier n'est pas réécrit. Une acceptation ou une invitation sans précision donne `habitant`.
- Le champ `personne` d'un appareil appairé se fixe à l'acceptation ou avec le message `changer_personne`
  (réservé aux administrateurs, comme `changer_role`). La personne doit être un habitant connu (le
  propriétaire, une clé de la liste `habitants` de `maison.json` ou une clé de `securite.permis_personne`),
  sinon le message est refusé.
- L'export `appareils` donne le rôle effectif et la personne de chaque appareil, et le rôle effectif de
  chaque jeton fixe (`roles_jetons_fixes`). Aucun jeton ni aucune empreinte n'y figure.

La liste des habitants se déclare à la racine de `maison.json` :

```json
"habitants": ["sacha", "camille"]
```

#### Messages permis par rôle (0.39.0)

Sur le port chiffré 8766, chaque message est contrôlé contre une table unique (`acces.TYPES_PAR_ROLE`). Un type
absent de la ligne du rôle est refusé : l'appareil reçoit `{"etat":"refuse","type":...,"message":"type de message
non permis pour ce rôle"}` (pour la santé, la forme `erreur` que l'appli attend), et le journal note le type, le
rôle et rien du contenu. Un message sans type exploitable est ignoré sans réponse.

| Rôle | Types permis |
|---|---|
| `invite` | `lecture_finie`, `parler`, `reveil`, `llm`, `ha`, `meteo_mer`, `vent_mesure`, `retour`, `transcrire`, `historique` |
| `partage` | ceux de `invite`, plus `vision` et `manque` |
| `habitant` | ceux de `partage`, plus les messages `sante*` |
| `administrateur` | tous, plus `appareils`, `appairer`, `refuser_appareil`, `revoquer`, `changer_role`, `changer_personne`, `inviter`, `annuler_invitation`, `transcription`, `mode`, `cerveau`, `manques` |

Le port en clair 8765 (ancien accès `?jeton=`) ne consulte pas cette table. La liste des habitants et le
filtre fin de la santé (`securite.permis_personne`) continuent de s'appliquer en plus.

L'historique des échanges est filtré selon le destinataire, pour la réponse au message `historique` comme
pour la diffusion `historique_ajout`. Règle la plus fermée : l'administrateur voit tout, l'habitant voit les
échanges de son appareil, de sa personne et ceux des appareils partagés (sans personne), le partage et l'invité
ne voient que ceux de leur propre appareil. Une entrée sans appareil connu (micro du PC, entrée écrite avant la
0.39.0) n'est vue que d'un administrateur.

#### Origin et Ingress (0.39.0)

Derrière le proxy de Home Assistant (`172.30.32.2`), l'en-tête `Origin` du navigateur peut différer de `Host`.
Le serveur accepte alors `Origin` égal à `X-Forwarded-Host`, seulement si la connexion vient de cette adresse.
Partout ailleurs, `X-Forwarded-Host` est ignoré.

#### Pare-feu des ports 8765 et 8766 (décision D7)

Aucune règle de pare-feu n'est posée ni modifiée par le serveur, et aucun port n'est fermé. La fermeture de 8765
attend sept jours de tablette sur 8766 et un mot du propriétaire (décision D7 du plan). Tant que ce n'est pas
fait, `acces.ancien_acces` et `reseaux_autorises` sont les seuls leviers.

### `routines`

Les routines à la voix (serveur 0.42.0) : une phrase déclenche une suite d'étapes (services Home Assistant,
annonce, question, pause, musique). Toute la section est facultative, chaque champ aussi. Les routines
elles-mêmes ne sont pas ici : elles vivent dans `routines.json`, dans le dossier de données du serveur
(`JARVIS_DONNEES`, sinon `poc/`), avec leur journal dans `journal/routines.jsonl`.

| Champ | Type | Effet |
|---|---|---|
| `active` | booléen | `false` coupe toute la fonction : plus de création, de lancement ni de message réseau, la capacité `routines` annoncée aux appareils passe à faux. Défaut : true. |
| `delai_confirmation_s` | entier | Temps dont dispose la personne pour répondre « oui » à la reformulation d'une routine. Défaut : 30. |
| `absorption_s` | entier | Durée pendant laquelle un « oui » isolé arrivé trop tard est absorbé au lieu de partir au LLM. Défaut : 120. |
| `nombre_max` | entier | Nombre total de routines. Défaut : 30. |
| `etapes_max` | entier | Étapes par routine. Défaut : 8. |
| `variantes_max` | entier | Variantes de phrase gardées en plus de la phrase principale. Défaut : 5. |
| `lettres_min` | entier | Nombre minimal de lettres d'une phrase de déclenchement. Défaut : 6. |
| `pause_max_s` | entier | Durée maximale d'une pause. Défaut : 600. |
| `duree_max_s` | entier | Somme maximale des pauses d'une routine. Défaut : 1800. |
| `intervalle_min_s` | entier | Délai minimal entre deux lancements de la même routine. Défaut : 10. |
| `question_delai_s` | entier | Délai accordé à une étape question. Défaut : 10. |
| `phrases_interdites` | liste de textes | Phrases qui ne peuvent jamais déclencher une routine, en plus de la liste écrite en dur (oui, non, stop, formules de gestion). Défaut : vide. |

```json
"routines": {
  "active": true,
  "etapes_max": 8,
  "phrases_interdites": ["bonne nuit sacha"]
}
```

Une valeur absente, mal typée, nulle ou négative rend le défaut.

Ce que la section ne règle pas : une routine ne permet jamais plus qu'une commande directe. Chaque étape qui
appelle un service Home Assistant passe par `acces.controler_service`, comme une commande dite, à la création
puis à chaque lancement. Serrures, alarmes, domaines interdits, liste blanche de services, réglages refusés de
`liste_blanche` et sécurité en dur s'appliquent donc telles quelles, et aucune clé de cette section ne les
desserre. Une étape qui vise une pièce, un étage, un appareil, une étiquette, `all` ou un joker est refusée.
Une routine dont une étape devient refusée après un changement de configuration est coupée au chargement et
marquée « à revoir ».

Qui peut quoi : le propriétaire crée, lance, gère et exporte tout. Un habitant crée et gère les siennes. Un
invité et une personne non reconnue ne créent rien. Une routine « pour tous » se lance par tout le monde, une
routine « pour son auteur » seulement par lui.

### `journal`

Ce que le serveur écrit sur ce qui se dit, et combien de temps. Chaque champ est facultatif.

| Champ | Type | Effet |
|---|---|---|
| `conserver_jours` | entier | Durée de garde des fichiers `journal/assistant-AAAA-MM-JJ.jsonl`, les seuls à contenir les phrases dites et répondues (l'écran Historique de l'appli les lit). Plus ancien, le fichier est supprimé. Défaut : 30. |
| `taille_max_ko` | entier | Taille à partir de laquelle `journal/latences.csv` tourne vers `latences.1.csv`, `latences.2.csv`, etc. Défaut : 512. |
| `fichiers_max` | entier | Nombre de fichiers de rotation gardés à côté de `latences.csv`. Défaut : 5. |
| `phrases_dans_la_console` | booléen | Remet les phrases dans la sortie du serveur (diagnostic). Défaut : false, la console ne montre que le nombre de caractères. `JARVIS_DIAGNOSTIC=1` dans `poc/.env` l'emporte. Seul `true` ouvre. |

```json
"journal": {
  "conserver_jours": 30,
  "taille_max_ko": 512,
  "fichiers_max": 5,
  "phrases_dans_la_console": false
}
```

Une valeur absente, nulle, négative ou illisible rend le défaut. `latences.csv` ne contient plus aucune phrase
ni réponse : horodatage, version, voie (catégorie seule), durées, rôle, issue (`ok`, `non compris`, `erreur`,
`refus`, `non confirmé`), nombre d'actions et indicateur d'essai. Un ancien `latences.csv` qui contenait les
phrases est mis de côté sous `latences-ancien-<date>.csv` au premier lancement, puis soumis à la rotation.
`manques.jsonl`, `retours.jsonl` et `musique.jsonl` gardent leurs phrases (ce sont des données
d'apprentissage) et ne sont pas purgés par ce réglage.

### `fuseau`

Texte, nom de fuseau IANA (`"Europe/Paris"`). Il donne l'heure de la maison pour les heures calmes de la
sécurité (quand elles sont actives, voir la [section 6](#6-la-sécurité-et-ce-que-la-configuration-en-règle))
et la date et l'heure glissées dans la demande au LLM du PC. Absent : `UTC`. La santé et son historique
comptent les jours à l'heure de `Europe/Paris`, écrite dans le code, quel que soit ce champ.

### `securite`

Listes appliquées par la sécurité écrite en dur (`poc/securite.py` et sa copie `Securite.kt`). Dans cette
version, la plupart sont lues mais restent sans effet, parce que les règles qui s'en servent sont coupées
dans le code. Seuls `plafond_volume` (dès qu'il est inférieur à 100) et `assist_repli` agissent. Le détail est à la
[section 6](#6-la-sécurité-et-ce-que-la-configuration-en-règle).

| Champ | Type | Effet quand la règle correspondante est active |
|---|---|---|
| `nom_occupant` | texte | Nom de l'occupant protégé, cité dans les refus. Par défaut : `l'occupant`. |
| `mots_proteges` | liste de textes | Tout identifiant d'entité, de zone ou de service qui contient l'un de ces mots (sans tenir compte de la casse) est intouchable. Une phrase qui en contient un est refusée avant le LLM. |
| `mots_pieces` | liste de textes | Mots d'un nom de pièce Home Assistant qui rendent la pièce protégée : ses appareils sont cachés au LLM et la pièce porte un cadenas dans la maison en grand. Vide : les `mots_proteges` servent. |
| `zones_protegees` | liste de textes | Identifiants de zones Home Assistant (`area_id`) refusées. |
| `entites_protegees` | liste de textes | Entités protégées dont l'identifiant ne contient aucun mot protégé (automatisation de réveil, script qui éteint tout). |
| `son_salon` | liste de textes | Lecteurs et scripts qui font du son dans la pièce de vie : pendant les heures calmes, seuls éteindre, mettre en pause, arrêter, baisser et couper le son passent. Comparaison exacte, casse comprise. |
| `heures_calmes` | objet `{debut, fin}`, heures entières | Plage des heures calmes, `debut` compris, `fin` exclue, à l'heure de `fuseau`. Par défaut : 0 et 9. Un `debut` après la `fin` (22 et 7) donne une plage qui passe minuit, un `debut` égal à la `fin` une plage vide. |
| `permis_personne` | objet, clé = prénom en minuscules sans accent | Pour chaque personne reconnue par la tablette : `entites` et `services` qu'elle peut piloter parmi ses affaires protégées. |
| `plafond_volume` | nombre de 0 à 100 | Toujours actif : volume le plus fort permis, en pourcentage. Absent ou 100 : aucun plafond. Voir [le plafond de volume](#le-plafond-de-volume). |
| `assist_repli` | booléen | Ouvre le repli vers Assist de Home Assistant quand le LLM échoue. Absent, `false` ou autre chose que `true` : repli coupé (défaut). Voir [le repli Assist](#le-repli-assist). |

```json
"securite": {
  "nom_occupant": "Camille",
  "mots_proteges": ["camille", "cam"],
  "zones_protegees": ["chambre_camille"],
  "heures_calmes": {"debut": 0, "fin": 9},
  "plafond_volume": 100,
  "assist_repli": false,
  "permis_personne": {
    "camille": {"entites": ["light.chambre_camille_plafonds"], "services": ["light.turn_on", "light.turn_off"]}
  }
}
```

Section absente : toutes les listes sont vides, rien n'est protégé même si les règles sont remises.

### `appareils`

Appareils propres à la maison, vus par le serveur et par l'appli.

| Champ | Type | Effet |
|---|---|---|
| `tele` | entité | La télé. Rappelée au LLM du PC quand il répond sans appeler d'outil. |
| `tele_famille` | préfixe d'entité | Les entités qui commencent par ce préfixe gagnent un point dans la présélection des appareils proposés au LLM quand la demande ne parle pas de lumière. |
| `musique` | objet | Musique par Music Assistant et Spotify, détaillé plus bas. |
| `sortie_son` | liste de `{entite, nom}` | Enceintes de l'écran Musique de l'appli, dans l'ordre, avec leur nom court. Seuls ces lecteurs et les télés apparaissent dans la liste des appareils de l'appli. |
| `noms_courts` | objet entité vers nom | Noms affichés dans le panneau de la maison en grand. Sans nom court : le nom de la vue 3D, puis celui de Home Assistant. |
| `lumieres_banc` | liste de deux entités | Lumière du salon puis lampe de la télé, pour les outils de banc `poc/outils/banc_actions.py` et `poc/outils/test_voix.py`. |
| `ordre_pieces` | liste de textes | Ordre des filtres par pièce de l'écran des appareils de l'appli. Ce sont les noms des pièces dans Home Assistant, comparés en minuscules. Une pièce absente de la liste passe à la fin. |

Champs de `musique` :

| Champ | Type | Effet |
|---|---|---|
| `enceintes` | objet nom vers lecteur | Lecteurs Music Assistant par nom d'enceinte. Ces noms forment la liste de choix de l'outil `jouer_musique` du LLM. La clé `toutes` (le groupe) est obligatoire : sans elle, toute demande de morceau précis répond "aucune enceinte de musique configurée". |
| `natifs` | objet lecteur vers liste d'entités | Entités de l'intégration native des enceintes derrière chaque lecteur. Elles seules servent à confirmer que le son sort vraiment. |
| `spotify` | entité | Lecteur Spotify de Home Assistant. |
| `spotify_appareil` | texte | Nom de l'appareil Spotify Connect qui représente le groupe `toutes`. |
| `source_connect` | texte | Source que prend le groupe pendant une session Spotify Connect. |
| `scripts` | liste d'entités | Scripts qui lancent la musique : après leur appel, le serveur attend jusqu'à 12 s que le groupe `toutes` joue, et le note dans le journal de la musique. |
| `script_lancer` | entité | Script proposé au LLM pour "mets de la musique" sans précision. |

Un titre Spotify demandé sur le groupe `toutes` part par Spotify Connect quand `spotify` existe et que
`spotify_appareil` figure dans ses sources. Sinon, il part par Music Assistant.

```json
"appareils": {
  "tele": "media_player.tele_salon",
  "musique": {
    "enceintes": {"toutes": "media_player.enceintes_maison", "salon": "media_player.barre_son_salon"},
    "script_lancer": "script.lancer_musique"
  },
  "sortie_son": [{"entite": "media_player.barre_son_salon", "nom": "Salon"}],
  "ordre_pieces": ["séjour", "entrée", "couloir"]
}
```

Section absente : pas de télé désignée, musique refusée avec un message, écran Musique vide, ordre des
pièces alphabétique selon Home Assistant.

### `llm`

Ce qui personnalise les consignes des deux LLM : celui du PC (Claude ou un modèle local) et celui de
l'appareil (mode "Cet appareil").

| Champ | Type | Lu par | Effet |
|---|---|---|---|
| `lieu` | texte | PC | Complète "Tu es l'assistant vocal de ...". Par défaut : `la maison`. |
| `consignes` | liste de textes | PC | Lignes ajoutées telles quelles à la consigne. |
| `utilisateur` | texte | Appareil | Personne nommée dans la consigne. Par défaut : `l'utilisateur`. |
| `consignes_appareil` | liste de textes | Appareil | Règles ajoutées à la consigne, une ligne chacune, écrites `- ...`. |
| `exemples_appareil` | liste de paires `[phrase, réponse JSON]` | Appareil | Exemples donnés au modèle. La réponse est un texte JSON `{"actions": [...], "reponse": "..."}`. |

```json
"llm": {
  "lieu": "l'appartement de Sacha",
  "consignes": ["La télé du séjour est media_player.tele_salon."],
  "exemples_appareil": [
    ["allume la cuisine à moitié",
     "{\"actions\": [{\"service\": \"light.turn_on\", \"entity_id\": \"light.cuisine_suspensions\", \"donnees\": {\"brightness_pct\": 50}}], \"reponse\": \"La cuisine est allumée à moitié.\"}"]
  ]
}
```

Les accolades des textes du PC sont protégées avant d'entrer dans la consigne. La vue des appareils
donnée au LLM (noms, appareils masqués) se règle dans `commandes.yaml`, pas ici.

### `ha`

Lu seulement par `python ha-app/configurer-ha.py`, qui pousse le dictionnaire dans Home Assistant.

| Champ | Type | Effet |
|---|---|---|
| `alias` | objet entité vers liste de textes | Alias ajoutés à ceux que l'entité a déjà dans Home Assistant (jamais retirés). |
| `exposer` | liste d'entités | Entités exposées à Assist. |

```json
"ha": {
  "alias": {"vacuum.robot": ["aspirateur"]},
  "exposer": ["media_player.barre_son_salon"]
}
```

Le même script crée l'automatisation "<nom de l'assistant> : dictionnaire" (id `jarvis_dictionnaire`) avec un
déclencheur vocal par commande de `commandes.yaml` et par phrase apprise. Les commandes à deux emplacements
ne sont pas transférées, celles que la sécurité refuse à 14 h non plus (aujourd'hui : celles qui visent un
`device_id`, et celles qui utilisent `media_player.volume_up` quand `securite.plafond_volume` règle un
plafond). `--essai` écrit seulement l'aperçu dans `genere/ha/`.

### `assistant`

Le nom de l'assistant, tel qu'il s'affiche : nom de l'appli Android sur l'écran d'accueil et dans ses
messages, nom de l'appli Home Assistant et de son automatisation de dictionnaire, première ligne du
journal de l'appli HA.

| Champ | Type | Effet |
|---|---|---|
| `nom` | texte | Nom affiché. Par défaut : `Assistant`. |

```json
"assistant": {"nom": "Iris"}
```

Le nom affiché ne change pas le mot qui réveille l'assistant, réglé à part dans la section `reveil`. Les
deux peuvent différer. Après un changement : nouvel APK pour l'appli Android, nouveau déploiement
(`ha-app/deployer.sh`) pour l'appli HA, et `ha-app/configurer-ha.py` pour renommer l'automatisation.

### `proprietaire`

La personne à qui appartient l'installation.

| Champ | Type | Effet |
|---|---|---|
| `nom` | texte | Prénom affiché. Nom de l'APK par défaut, prénom proposé au LLM pour "la chambre de ...", seul prénom pour lequel la santé s'affiche (comparé au nom du profil de visage, sans tenir compte de la casse). Par défaut : `Moi`. |
| `cle` | texte | Clé du propriétaire : le jeton `SATELLITE_JETON` lui est attribué, `SANTE_PERSONNES` vaut cette clé par défaut, et `personnes.defaut` de `commandes.yaml` aussi. Par défaut : `nom` en minuscules. À écrire sans accent. |
| `variantes` | liste de textes | Transcriptions erronées du prénom, remplacées par `nom` avant la recherche dans le dictionnaire (mots entiers, casse ignorée). |

```json
"proprietaire": {"nom": "Sacha", "cle": "sacha", "variantes": ["sasha", "sachat"]}
```

Section absente : propriétaire `Moi`, avertissement au démarrage du serveur et à la compilation, et la
santé ne s'affiche pour personne.

### `mer`

Météo marine d'un plan d'eau : page Mer du panneau Météo de la tablette et questions sur la mer. Le module
n'existe que si `"actif": true` (un vrai booléen JSON). Le détail de l'activation est dans
[la section 5](#météo-marine-et-vent-mesuré).

| Champ | Type | Effet |
|---|---|---|
| `actif` | booléen | Allume le module. Absent ou faux : module éteint. |
| `fuseau` | texte | Fuseau des heures affichées et demandées aux sources. Par défaut : `UTC`. |
| `points` | liste d'objets | Points de prévision, tous en mer, dans l'ordre du message. Sans point, le module reste éteint. |
| `modele_principal` | `{modele, nom}` | Modèle Open-Meteo du vent, de l'air, de la pluie, de l'orage et du soleil. `nom` est affiché (par défaut : `prévision`). |
| `modele_second` | `{modele, nom}` | Second modèle Open-Meteo pour le vent et la visibilité (par défaut : `second modèle`). |
| `vagues_regional` | `{url, lieux}` | Vagues WaveWatch III de la source régionale. `url` contient `{lieu}`. Chaque lieu : `point` servi, `lieu` (code de la source), `nom`, `panne` (libellé affiché en cas d'échec). Facultatif : sans lieu, les vagues viennent d'Open-Meteo Marine. |
| `station` | `{url, nom, point}` | Station à terre : vent mesuré affiché dans le bloc du moment du `point` indiqué. |
| `alias` | liste de paires `[mot, point]` | Mots qui désignent un point dans une question, cherchés dans l'ordre. |
| `mots_lieu` | liste de textes | Autres noms du plan d'eau acceptés après "à" dans une question. |
| `titre` | texte | Titre par défaut de la page. Absent, c'est `nom`, et sans `nom`, `Mer`. |
| `libelle_terre` | texte | Libellé de la page météo à terre vu depuis la mer (par défaut : `Météo`). |
| `attribution` | texte | Crédit des sources en pied de page. |
| `nom` | texte | Nom du plan d'eau. Sert de titre à la page quand `titre` est absent. Le titre choisi est aussi renvoyé au client dans les données de la mer (clé `titre`). |

Champs d'un point :

| Champ | Type | Effet |
|---|---|---|
| `id` | texte | Identifiant du point. |
| `nom` | texte | Nom affiché. |
| `lat`, `lon` | texte | Coordonnées, recopiées telles quelles dans les adresses d'Open-Meteo. |
| `titre` | texte | Titre de la page pour ce point. |
| `stations` | liste d'identifiants | Stations du vent mesuré rattachées au point, la plus représentative d'abord. |
| `defaut` | booléen | Point par défaut. Sinon, le premier. |
| `soleil` | booléen | Point qui donne le lever et le coucher du soleil. Sinon, le premier. |
| `eau` | booléen | Point qui donne la température de l'eau. Sinon, aucune. |
| `sans_station` | booléen | Point sans station à lui : la réponse ne dit pas que sa balise n'émet pas. |

```json
"mer": {
  "actif": true,
  "fuseau": "Europe/Paris",
  "points": [
    {"id": "prado", "nom": "Prado", "lat": "43.25", "lon": "5.36", "soleil": true,
     "titre": "Mer au Prado", "stations": ["prado", "callelongue"], "defaut": true}
  ],
  "modele_principal": {"modele": "meteofrance_arpege_europe", "nom": "ARPEGE"},
  "modele_second": {"modele": "meteofrance_arome_france_hd", "nom": "AROME"},
  "titre": "Mer à Marseille"
}
```

Les sources possibles sont fixées par le code : les deux modèles d'Open-Meteo, Open-Meteo Marine, les
lieux VaguesRegional et la station. Chacune est interrogée par défaut. Une source dont l'adresse manque ou ne
répond pas reste en panne, son libellé s'affiche dans les erreurs et les autres continuent. Le module ne
renvoie une erreur que si le modèle principal n'a jamais pu être lu.

Pour retirer une source sans effacer sa fiche, ajouter `"actif": false` dans sa fiche. Absent, `actif` vaut
vrai (contrairement à celui de la section, qui doit être écrit). Une source retirée n'est pas interrogée,
n'est pas comptée en panne et n'apparaît pas dans les erreurs ni dans les crédits. Cela marche sur
`modele_principal`, `modele_second`, `vagues_regional` (entier), chacun des `lieux` de VaguesRegional, le bloc
`mfwam` (vagues Open-Meteo Marine) et `station` :

```json
"vagues_regional": {"url": "https://exemple.invalid/{lieu}", "actif": false},
"station": {"url": "https://exemple.invalid/mer", "nom": "Station", "point": "prado", "actif": false}
```

Avec `modele_principal` inactif, le module de la mer n'a plus de source de base et reste éteint, comme sans
point. Section `mer` active sans section `vent` utilisable (absente, inactive ou sans aucune source), le
serveur écrit un avertissement dans son journal au démarrage : la page météo marine fonctionne, mais le vent
mesuré (carte, balises, station) est absent. L'avertissement n'arrête rien.

### `vent`

Vent réellement mesuré autour du plan d'eau : page Vent mesuré du panneau Météo. Le module suppose la
section `mer` active, ses `points` servant de rattachement.

| Champ | Type | Effet |
|---|---|---|
| `actif` | booléen | Allume le module. Absent ou faux : éteint. |
| `cadre` | `[lat_min, lat_max, lon_min, lon_max]` | Emprise de la carte. Les stations hors cadre ne sont pas dessinées. L'appli exige quatre nombres. |
| `balises` | objet | Balises Balises : `doc_type`, `fenetre`, `latitude`, `longitude` de la requête, `user_agent` (en ASCII seulement), `panne` (libellé d'échec), `balises` (objet id Balises vers fiche). |
| `stations_officielles` | objet | Stations StationsOfficielles : `url` (contient `{q}`), `nommees` (stations reconnues par `nom_brut`, avec leur fiche), `reseau_amateur` (code du réseau des stations amateurs), `quartiers` (code de station amateur vers nom affiché). |
| `station` | fiche avec `url` | Station à terre. |
| `points_proches` | objet point vers `[lat, lon]` | Rattache une station sans `point` au point de prévision le plus proche. |
| `titre` | texte | Titre de la page (par défaut : `Vent mesuré`). |
| `preferees` | liste d'identifiants | Stations essayées d'abord comme station par défaut. |
| `note_regate` | texte | Phrase affichée sous la liste quand rien d'autre n'y est écrit. |
| `carte` | objet | Dessin de la carte, voir plus bas. |

Une fiche de station ou de balise contient `id`, `nom`, `genre` (texte affiché), `type` (`mer`, `abritee`,
`terre` ou `amateur`), `lat`, `lon` et `point` (point de rattachement, ou `null` pour une donnée hors carte).

Champs de `carte` :

| Champ | Type | Effet |
|---|---|---|
| `largeur`, `hauteur` | nombres | Taille de la carte en pixels de maquette (par défaut 640 et 423). |
| `cote`, `terre` | chemins relatifs à `genere/android/` | Trait de côte et terre, en chemin SVG. Obligatoires pour fabriquer une APK quand `vent` est actif. |
| `lieux` | liste de `{nom, lat, lon}` | Noms de lieux écrits sur la carte. |
| `decalages` | objet id vers `[dx, dy]` | Position de l'étiquette de chaque station par rapport à son point. Par défaut : `[0, 90]`. |
| `attribution` | texte | Crédit des sources en pied de page. |

```json
"vent": {
  "actif": true,
  "cadre": [43.2, 43.32, 5.22, 5.47],
  "station": {"url": "https://exemple.invalid/station", "id": "port", "nom": "Vieux-Port",
              "genre": "station à terre", "type": "terre", "lat": 43.3, "lon": 5.37, "point": "prado"},
  "points_proches": {"prado": [43.25, 5.36]},
  "carte": {"largeur": 640, "hauteur": 423, "cote": "carte/golfe_cote.txt", "terre": "carte/golfe_terre.txt"}
}
```

Le serveur interroge par défaut ses trois sources (Balises, StationsOfficielles et la station). Pour en retirer
une, y ajouter `"actif": false` (absent vaut vrai), sur `balises`, sur une seule balise de `balises`,
sur `stations_officielles` ou sur `station`. Une source retirée n'est pas interrogée et n'apparaît pas dans les erreurs,
et quand toutes les sources sont retirées le vent mesuré reste éteint. Une source en échec est réessayée
après 1, 2, 4, 8 puis 15 minutes au plus, et son libellé apparaît dans les erreurs.

### `reveil`

Mot de réveil de la maison. "Hey Jarvis" reste le modèle de repli quand le fichier du mot manque.

| Champ | Type | Effet |
|---|---|---|
| `mot` | texte | Nom du modèle : `reveil/<mot>.onnx` dans le dossier de configuration. Par défaut : `MOT_REVEIL` de `poc/.env`, puis `assistant`. Interdit : `melspectrogram`, `embedding_model`, `hey_jarvis`, `hey_jarvis_v0.1` (la compilation échoue). |
| `nom` | texte | Nom affiché. Par défaut : `mot` avec une majuscule. |
| `langue` | texte | Affichée sous le nom dans les réglages de l'appli. |
| `licence` | texte | Affichée dans les réglages de l'appli. |

```json
"reveil": {"mot": "jeeves", "nom": "Jeeves", "langue": "français", "licence": "Licence du modèle, en une phrase."}
```

Cette section n'a pas de champ `actif` : `"actif": false` n'y change rien. Pour l'éteindre, la retirer ou
vider `mot`. Détails dans [la section 5](#mot-de-réveil).

### `reglages.tele` (appli 0.39.0)

Tuiles de sources du volet de la télévision, dans l'écran de la maison en grand. Les noms de sources sont ceux de
la télé, jamais ceux du code. La section `reglages` existe déjà (`applis`, `interrupteurs`, `attributs_refuses`,
voir ARCHITECTURE.md) et `tele` s'y ajoute sans rien changer aux règles de sécurité.

| Champ | Type | Effet |
|---|---|---|
| `sources` | liste d'objets | Les tuiles, dans l'ordre d'affichage, quatre par rangée. Sans cette clé, le volet n'offre que le curseur de volume et la tuile Toutes. |
| `sources[].nom` | texte | Libellé de la tuile (« TNT », « HDMI 1 »). `Toutes` est réservé : l'appli ajoute elle-même cette dernière tuile, qui déplie toutes les sources de la télé. |
| `sources[].source` | texte | Nom de la source tel que Home Assistant le donne, à copier de `attributes.source_list` de l'entité (Outils de développement, États). Majuscules, espaces et accents sont ignorés à la comparaison (« HDMI 1 » vaut « HDMI1 »). |

```json
"reglages": {
  "tele": {
    "sources": [
      {"nom": "TNT", "source": "TV"},
      {"nom": "Netflix", "source": "Netflix"},
      {"nom": "HDMI 1", "source": "HDMI1"}
    ]
  }
}
```

Une tuile dont la source n'est pas dans la liste de la télé est masquée. Si Home Assistant ne donne pas cette
liste, toutes les tuiles restent. Le choix d'une tuile envoie `media_player.select_source`, le curseur envoie
`media_player.volume_set` avec le plafond de volume en dur (voir [Le plafond de volume](#le-plafond-de-volume)),
et le rond allume ou éteint par `turn_on` et `turn_off`. Ces quatre services sont déjà dans la liste blanche de
`media_player`. Si un autre service de télé est refusé, le permettre par la configuration (`reglages`), sans
toucher à `poc/securite.py` ni à `Securite.kt`. Après un changement, régénérer le dictionnaire et reconstruire l'APK.

L'état affiché (allumée, source, volume) vient de Home Assistant. La source lue étant peu fiable sur certaines
télés, elle s'affiche au conditionnel (« allumée, sans doute Netflix »). La sortie audio (barre de son ou haut-parleurs
de la télé) n'est pas lue : le curseur règle toujours le volume de l'entité de la télé.

### `reglages.vue3d` (appli 0.42.0)

Retour d'état dans la vue 3D : l'appli envoie à la page l'état allumé ou éteint des lampes avec leur couleur (ou leur
chaleur en kelvins) et celui de la télé et des enceintes. La page reconnaît les objets par les entités de
`carte/3d/` (`lampes.json`, `meubles.json`). Quand Home Assistant appelle une entité autrement que la maquette,
`correspondances` fait le lien. Cette section ne change aucune règle de sécurité.

| Champ | Type | Effet |
|---|---|---|
| `correspondances` | objet | Clé : entité de Home Assistant. Valeur : entité que connaît la maison 3D. Une clé vide ou qui commence par `_` est ignorée. Sans cette clé, chaque entité garde son nom. |

```json
"reglages": {
  "vue3d": {
    "correspondances": {
      "media_player.tele_famille_fictive": "media_player.tele_salon"
    }
  }
}
```

Un toucher sur un objet de la vue 3D renvoie l'entité de la maquette : l'appli retrouve l'appareil de Home Assistant
par la même correspondance, à l'envers. Une lampe indisponible ou inconnue est montrée éteinte, sans couleur périmée.

### `correspondance_pieces` (mesures par pièce, serveur et appli, lot S-L6)

Relie chaque pièce de `carte/pieces.json` (la clé est l'identifiant `id` de la pièce) aux zones de Home Assistant
(les `area_id`, comme dans `zones_protegees`) dont on veut lire la température, l'humidité, le CO2 et les particules
fines. Elle se remplit à la main : le moteur ne devine jamais la pièce d'un capteur. Une clé qui commence par `_` est
ignorée. Une pièce absente de cette liste n'a ni mesure ni pastille.

| Champ | Type | Effet |
|---|---|---|
| clé | texte | Identifiant de la pièce dans `pieces.json`. |
| valeur | liste de textes, ou un texte | Zones de Home Assistant qui forment la pièce. Une pièce ouverte sur une autre (séjour et cuisine) en réunit plusieurs. |

```json
"correspondance_pieces": {
  "sejour_cuisine": ["coin_repas", "salon", "cuisine"],
  "chambre_sacha": ["chambre_1"]
}
```

Un seul gabarit lu sur `/api/template` découvre les capteurs de température, d'humidité, de CO2 (`carbon_dioxide`),
de particules (`pm25`, `pm10`), d'indice de qualité d'air (`aqi`) et de composés organiques volatils, plus la
luminosité pour savoir qu'une pièce n'a que cela. La zone d'un capteur est celle de l'entité, sinon celle de son appareil
dans Home Assistant : il suffit donc que les capteurs soient rangés dans les bonnes zones, aucune entité ne s'écrit
dans la configuration. Plusieurs capteurs de même type dans une pièce : le thermomètre dédié (un appareil qui n'expose
que la température et l'humidité) l'emporte, sinon la moyenne.

Seuils, qui ne se règlent pas dans la configuration : CO2 en ppm, bon sous 800, correct jusqu'à 1000 compris, médiocre
jusqu'à 1500 compris, mauvais au-delà. Particules PM2.5 en µg/m3, mêmes mots à 9, 35,4 et 55,4. Température : frais
sous 19°, agréable de 19° à 24° compris, chaud au-dessus. L'air d'une pièce prend le pire des deux mots, et une alerte
« Aère la pièce X » apparaît dès « médiocre ». Une mesure muette depuis plus de 2 h n'est plus colorée.

Accueil et vue 3D (S-L7) : l'écran d'accueil montre une ligne courte du type « Salon 21°, air bon ». Si une pièce a
l'air médiocre ou mauvais, c'est elle qui parle (la pire, à égalité la première de la liste). Sinon c'est la première
pièce de `correspondance_pieces` qui a quelque chose à dire : **l'ordre de la liste fixe donc la pièce principale**,
mettez-y d'abord celle que vous voulez voir. Une pièce protégée, sans capteur ou muette ne parle jamais. Dans la vue 3D,
chaque pièce porte sa pastille et la pièce touchée un carton avec chaque mesure. Le nom dit dans l'alerte est celui de
`pieces.json`.

Sécurité : une pièce dont l'identifiant, le nom ou une zone figure dans `securite.zones_protegees` ne montre aucune
valeur (« pièce protégée »), que `PROTEGER_OCCUPANT` soit coupé ou non. Le gabarit écarte aussi ces zones dès Home
Assistant, leurs mesures ne quittent donc pas la maison.

## 3. Le dictionnaire commandes.yaml

Le dictionnaire est consulté avant Home Assistant et avant le LLM. Une phrase trouvée donne l'action exacte
en quelques dizaines de millisecondes.

### Format

Quatre sections, toutes facultatives sauf `commandes`.

```yaml
llm:            # ce que voit le LLM, sans rien changer dans Home Assistant
  renommer:
    light.salon_lampe_tele: "Lampe TV (lampe posée près de la télé, ce n'est pas la télé)"
  notes:        # ajoutées en bout de ligne de l'appareil (LLM du serveur et LLM de l'appli, après un nouvel export)
    media_player.tele_salon: "entrées via media_player.select_source"
  masquer:
    - media_player.tele

personnes:      # "ma chambre" selon qui parle, voir plus bas
  defaut: sacha

emplacements:   # listes de valeurs, utilisées par {nom} dans les phrases
  hdmi:
    "1|un": HDMI1
    "2|deux": HDMI2

commandes:
  - phrases: ["(éteins|coupe|ferme) [la] (télé|télévision|tv) [du séjour|du salon]"]
    action: {service: media_player.turn_off, entity_id: media_player.tele_salon}
    reponse: "J'éteins la télé."
  - phrases: ["(mets|passe) [la télé] sur [l'entrée] hdmi {hdmi}"]
    action: {service: media_player.select_source, entity_id: media_player.tele_salon, source: "{hdmi}"}
    reponse: "Je passe la télé sur l'entrée demandée."
```

Syntaxe d'une phrase, celle des phrases personnalisées de Home Assistant :

| Écriture | Sens |
|---|---|
| `(a\|b)` | l'un ou l'autre |
| `[mot]` | facultatif, `[a\|b]` pour un choix facultatif |
| `{nom}` | une valeur de `emplacements.nom` |

Les motifs des emplacements suivent la même syntaxe. Avant la comparaison, tout est mis en minuscules,
sans accents ni ponctuation. Une petite faute de transcription est tolérée (ressemblance de 0,88 au moins,
et chaque mot différent doit rester proche d'un mot de l'autre côté). Les formules de politesse ("est-ce que
tu peux", "s'il te plaît"), l'infinitif ("éteindre" devient "éteins") et les `variantes` du prénom du
propriétaire sont corrigés d'abord.

Une action est un objet, ou une liste d'objets pour plusieurs actions :

| Clé | Effet |
|---|---|
| `service` | Service Home Assistant exact, `domaine.service`. |
| `entity_id` | Une entité, une liste, ou plusieurs entités séparées par des virgules. |
| autres clés | Envoyées telles quelles comme données du service (`brightness_pct`, `source`, `transition`...). |

`{nom}` est remplacé dans toutes les valeurs texte de l'action, y compris l'identifiant
(`entity_id: "script.aspirer_{piece}"`). Les accolades d'une valeur texte sont donc réservées aux
emplacements. `reponse` est dite après coup (par défaut : "C'est fait.").

Les actions du dictionnaire ne passent pas par la liste blanche des services du LLM : elles sont écrites à
la main. Chacune passe par la sécurité en dur avant l'envoi.

Si deux commandes produisent la même phrase, la première du fichier gagne.

### Ajouter une commande

Ajouter un bloc sous `commandes:`, avec ses phrases, son action et sa réponse. Pour une famille de
commandes (une par pièce, une par source), passer par un emplacement plutôt que de répéter le bloc.

Pour l'essayer sans micro ni Home Assistant :

```powershell
.venv\Scripts\python poc/assistant.py --texte "ta phrase" --essai
```

Puis refaire l'export pour l'appli (`.venv\Scripts\python android/outils/exporter_dictionnaire.py`).

### Ajouter une pièce

Une pièce intervient à plusieurs endroits, selon ce qu'on veut en faire :

1. Dans un emplacement, par exemple `piece` de l'exemple, dont la valeur sert de suffixe aux scripts de
   l'aspirateur (`script.aspirer_{piece}`). Les scripts correspondants doivent exister dans Home Assistant :
   ```yaml
   piece:
     "[le] bureau": bureau
   ```
2. Dans l'emplacement `lumiere`, pour régler sa luminosité ("mets le bureau à 50 %").
3. Dans `appareils.ordre_pieces` de `maison.json`, sous son nom Home Assistant.
4. Dans le plan, `carte/pieces.json` (voir la [section 4](#4-le-plan-du-logement)).

### Ajouter un appareil

1. Des commandes pour lui dans `commandes:`.
2. Si le LLM doit le voir autrement : `llm.renommer`, `llm.notes`, ou `llm.masquer` pour un doublon.
3. Pour Assist : `ha.alias` de `maison.json`, puis `python ha-app/configurer-ha.py`.
4. Pour l'appli : `appareils.noms_courts`, et `appareils.sortie_son` pour une enceinte.
5. Pour la vue 3D : une lampe dans `carte/lampes.json`, ou une télé ou une enceinte dans `medias` de
   `carte/meubles.json`.

### Ajouter une personne et "ma chambre"

La section `personnes` dit ce que vise "ma chambre" selon la personne que la tablette reconnaît.

```yaml
personnes:
  defaut: sacha
  inconnu: "Je ne te reconnais pas, donc je ne sais pas de quelle chambre tu parles."
  sans_chambre: "Je ne sais pas quelle chambre est la tienne."
  camille:
    remplacer:
      light.chambre_sacha_plafond: light.chambre_camille_plafonds
      light.chambre_sacha_chevets: light.chambre_camille_chevet
      script.lampes_nuit_eteindre:
        {service: light.turn_off, entity_id: light.chambre_camille_chevet, transition: 5,
         reponse: "J'éteins ton chevet. Bonne nuit."}
```

| Clé | Effet |
|---|---|
| `defaut` | Personne dont la chambre est celle du dictionnaire. Par défaut : `proprietaire.cle`. |
| `inconnu` | Réponse quand la tablette voit une seule personne sans la reconnaître. |
| `sans_chambre` | Réponse quand la personne reconnue n'a pas de chambre déclarée. Par défaut : le texte de `inconnu`. |
| `<personne>.remplacer` | Pour cette personne : entité de la chambre par défaut vers son entité à elle (texte), ou vers une action complète (objet, avec une `reponse` facultative qui remplace celle de la commande). |

La règle, identique dans `poc/dictionnaire.py` et `DictionnaireLocal.kt` :

- Une commande est "personnelle" quand toutes ses cibles sont des clés d'une table `remplacer` et que la
  phrase, une fois normalisée, ne contient pas la valeur de `defaut` comme mot ("la chambre de Sacha"
  garde toujours ses cibles).
- Quand on ne sait pas qui parle (pas de vision, plusieurs personnes, identité pas encore sûre), ou que
  c'est `defaut` qui parle, la commande reste telle quelle.
- Une personne vue mais inconnue reçoit la réponse `inconnu`, rien n'est fait.
- Une personne reconnue avec une table voit ses entités à elle. Une action complète ne remplace qu'une
  action à une seule cible. Une cible sans correspondance donne la réponse `sans_chambre`.
- Une personne reconnue sans table reçoit `sans_chambre`.

Pour ajouter une personne :

1. Lui donner une table `remplacer` ici. La clé est son prénom, comparé sans accent ni majuscule au nom
   de son profil de visage.
2. Enregistrer son visage sur la tablette ("Visages enregistrés" dans les réglages), sous ce prénom.
3. Si elle a son téléphone : `SATELLITE_JETON_<NOM>` dans `poc/.env`, puis
   `gradlew assembleDebug -Putilisateur=<nom>` pour son APK.
4. Si ses affaires sont protégées, `securite.permis_personne` de `maison.json` (voir la
   [section 6](#6-la-sécurité-et-ce-que-la-configuration-en-règle)).

Les cas communs aux deux langages sont dans `poc/tests/cas_personnes.json`.

### Les phrases apprises

Une phrase traitée avec succès par le LLM est rangée dans `commandes_apprises.yaml`, puis reconnue
directement la fois suivante. Ce fichier n'est pas de la configuration : il vit dans le dossier de données
de la machine (`JARVIS_DONNEES`, `poc/` par défaut sur le PC, `/data` dans l'appli Home Assistant).

```yaml
apprises:
- phrase: allume la lampe de la télé en bleu
  action:
  - service: light.turn_on
    entity_id: light.salon_lampe_tele
    color_name: blue
  reponse: La lampe de la télé est bleue.
  appris_le: 2026-10-20 18:42
```

Une phrase apprise ne vaut que mot pour mot (aucune tolérance aux fautes), et le dictionnaire écrit à la
main passe devant en cas de doublon. Ne sont jamais apprises : les phrases d'un seul mot, celles qui
dépendent du moment ("encore", "éteins-la"), les questions et les échecs, ni rien en mode essai. Pour en
retirer une : supprimer son bloc, ou dire "non" ou "annule" dans les 30 s qui suivent.

Les phrases apprises du PC partent aussi vers l'appli (par l'export ci-dessous) et vers Home Assistant (par
`configurer-ha.py`). `deployer.sh` copie celles du PC comme point de départ de l'appli Home Assistant,
qui garde ensuite les siennes dans `/data`.

### L'export à refaire avant de compiler l'APK

L'appli n'a pas de lecteur YAML : elle embarque `genere/android/dictionnaire.json`, avec toutes les formes
développées, la vue du LLM, la section `personnes` et la liste blanche des services. Les phrases apprises
de la machine qui exporte vont dans un second fichier, `genere/android/dictionnaire_appris.json` du dossier
de données (`JARVIS_DONNEES`, `poc/` par défaut, ignoré par git), que la compilation ajoute aux assets
quand il existe (`-PdonneesDossier=...` pour en désigner un autre, `--donnees` côté export). Un chemin relatif
part de la racine du dépôt, pour l'export comme pour la compilation. L'appli les fusionne au dictionnaire,
sans qu'une phrase apprise remplace une phrase de `commandes.yaml`. Les deux fichiers portent le même jeton
`export` : des phrases apprises d'un autre export (fichier périmé, autre machine) ou illisibles sont
ignorées, et l'étape « Dictionnaire » du déroulé de l'appli le dit. Après chaque changement du dictionnaire
ou des phrases apprises :

```powershell
.venv\Scripts\python android/outils/exporter_dictionnaire.py
```

Sans ce fichier, la compilation d'une APK échoue avec la commande à lancer.

Pour l'exemple, `.venv\Scripts\python android/outils/exporter_dictionnaire.py --exemple` exporte le dictionnaire de
`config-exemple/` sans phrase apprise, ni date, ni jeton. Le test `test_export_exemple_a_jour` de
`poc/tests/test_dictionnaire.py` refait cet export dans un dossier temporaire et le compare au fichier
suivi par git, sans jamais le réécrire. S'il échoue, relancer l'export `--exemple` à la main et le committer
avec le `commandes.yaml` d'exemple modifié. Les tests de
l'appli (`DictionnaireTest.kt`) lisent ce même fichier.

## 4. Le plan du logement

Trois fichiers dans `carte/` de la configuration décrivent le logement. Ils servent au plan 2D de
référence et à la vue 3D de la tablette, qui montre les lampes allumées et permet de les toucher.

### Repère et unités

- Unité : le mètre. Repère direct, y vers le haut du plan.
- L'origine et les axes sont libres et décrits en texte dans `pieces.json` (`repere`). Le nord peut rester
  inconnu (`"nord": null`).
- Les hauteurs (`z`) partent du sol.
- Le générateur 3D ne traite correctement que les murs parallèles aux axes x et y. Une cloison en biais
  reste juste dans le plan 2D, pas dans la vue 3D.
- Dans la vue 3D, l'écran d'une télé fait face au sens +y du plan.

### `pieces.json`

| Champ | Contenu |
|---|---|
| `version`, `date` | Version et date du plan, écrites au pied du plan 2D et dans la vue 3D. |
| `logement`, `unite`, `source` | Texte descriptif (méthode du relevé, échelle, contrôles, précision), non interprété. |
| `repere` | `origine`, `axe_x`, `axe_y`, `sens` en texte, `emprise` `{xmin, ymin, xmax, ymax}` qui contient tout le plan, `nord`. |
| `pieces` | Liste des pièces, voir ci-dessous. |
| `portes` | Porte d'entrée : `{id, nom, segment: [[x1, y1], [x2, y2]]}`, dessinée en rouge sur le plan 2D. |
| `pied` | Facultatif, ajouté au pied du plan 2D. |
| `surface_totale_m2` | Recalculée par `generer_plan.py`. |

Une pièce :

| Champ | Contenu |
|---|---|
| `id` | Identifiant stable, sans accent (`chambre_sacha`). |
| `nom` | Nom affiché. |
| `nom_a_confirmer` | Facultatif : vrai ajoute "?" au nom sur le plan 2D. |
| `type` | `sejour`, `circulation`, `chambre` ou `salle_de_bain` (couleur du sol). |
| `confiance` | `haute`, `moyenne`, `basse` ou `estimee` (contour en pointillés). |
| `polygone` | Points `[x, y]` dans l'ordre du contour, sans répéter le premier. |
| `surface_m2` | Recalculée par `generer_plan.py`. |
| `remarque` | Texte libre. |

### `meubles.json`

| Champ | Contenu |
|---|---|
| `version` | Version de la vue 3D, affichée dans la page. |
| `hauteur_plafond` | Hauteur des murs, en mètres. |
| `meubles` | `{id, nom, piece, boite: [x0, y0, x1, y1, z0, z1], couleur}`, un pavé droit par meuble. |
| `ouvertures` | `{id, segment, porte}` : trou dans le mur sur ce segment (à moins de 20 cm du mur). `porte` vrai ajoute un linteau à 2,10 m. |
| `medias` | Télés et enceintes posées sur un meuble : `{entite, nom, type: "tele" ou "enceinte", meuble, alias, ondes}`. `alias` liste d'autres entités du même appareil. `ondes`, en degrés, limite les ondes d'une enceinte contre un mur à un demi-cercle tourné vers la pièce. |
| `groupes_medias` | Entité de groupe vers ses enceintes. |

### `lampes.json`

Une entrée par ampoule. C'est le lien entre la vue 3D et Home Assistant.

| Champ | Contenu |
|---|---|
| `entite` | Entité `light.` de Home Assistant, celle que la page allume et que l'appli pilote au toucher. |
| `nom` | Nom de l'ampoule. |
| `type` | `suspension`, `plafonnier`, `lampe`... |
| `piece` | `id` de la pièce de `pieces.json`. |
| `xyz` | Position en mètres, `z` = hauteur de l'ampoule. |
| `position` | `triangulee`, `deduite` ou `estimee` (une position estimée est signalée dans la page). |

`groupes` (obligatoire, même vide) relie une entité de groupe Home Assistant à ses ampoules :

```json
"groupes": {"light.cuisine_suspensions": ["light.cuisine_suspension_1", "light.cuisine_suspension_2"]}
```

Un état reçu pour le groupe s'applique à toutes ses ampoules. Dans le panneau de la maison en grand, un
groupe dont toutes les ampoules sont dans la même pièce apparaît comme un seul objet.

### Faire le plan à la main

1. Choisir l'origine (un angle intérieur facile à retrouver) et les axes (le long d'un grand mur), et les
   décrire dans `repere`.
2. Mesurer chaque pièce et écrire son contour en mètres dans `pieces.json`. Des pièces voisines partagent
   les mêmes coordonnées de cloison.
3. Poser les meubles en pavés droits (10 à 20 cm près suffisent), les ouvertures et les télés ou enceintes.
4. Placer chaque ampoule avec l'entité Home Assistant exacte (Outils de développement, États), sa pièce et
   sa hauteur.
5. Régénérer (plus bas) et contrôler le plan 2D, qui affiche la surface de chaque pièce.

### Partir d'un relevé

- Plan coté (plan d'architecte, plan de vente) : reporter les cotes dans le repère choisi, en vérifiant
  que la somme des pièces retombe sur les cotes extérieures.
- Photogrammétrie ou balayage 3D (appli de relevé d'un téléphone, nuage de points) : ouvrir le modèle
  dans un visualiseur qui donne des coordonnées, aligner ses axes sur ceux du plan, puis relever les
  angles des pièces, les meubles et la position des ampoules.

Dans les deux cas, noter la méthode et la précision dans `source`, mettre `confiance` à `estimee` pour
une pièce vue seulement depuis la porte, et `position` à `estimee` pour une ampoule placée au jugé.

### Régénérer le plan 2D et la vue 3D

```powershell
.venv\Scripts\python carte/generer_plan.py
```

Recalcule les surfaces dans `pieces.json` (le fichier est réécrit), puis produit `carte/plan.svg` et
`carte/plan.png` (80 pixels par mètre, une balise `<polygon id="...">` par pièce). Demande Pillow. Ce plan
sert de référence, l'appli ne l'affiche pas.

```powershell
.venv\Scripts\python carte/3d/generer_3d.py
```

Produit `carte/modele.glb` (le logement en glTF, chaque ampoule nommée d'après son entité et portée par
`extras.haEntity`) et `genere/android/maison3d/vue3d.html` (page autonome embarquée dans l'APK). Il faut
ensuite recompiler l'APK. Pour l'exemple, régler d'abord la variable `ASSISTANT_VOCAL_CONFIG`, sous
PowerShell :

```powershell
$env:ASSISTANT_VOCAL_CONFIG = "config-exemple"
```

Sous Linux ou macOS, préfixer la commande par `ASSISTANT_VOCAL_CONFIG=config-exemple`. Les commandes de ce
document utilisent le Python de l'environnement virtuel, `.venv/bin/python` hors de Windows.

## 5. Les modules facultatifs

### Santé

Quelques chiffres de santé du propriétaire sur l'accueil de la tablette ("Tu as dormi ...", les pas du
jour) et un panneau Santé (onglets Tendances, Séances, Records et Jour pour l'historique).

Ce qu'il faut côté serveur :

- Le serveur du PC (profil `pc`). L'appli Home Assistant ne sert jamais la santé.
- Un service de santé joignable seulement par Tailscale, à l'adresse `reseau.sante_url` (ou `SANTE_URL`),
  qui répond à `GET /api/resume?jours=8` et `GET /api/commentaire?date=AAAA-MM-JJ` avec le jeton en
  `Authorization: Bearer`. Le relais refuse d'envoyer le jeton si le nom ne se résout pas dans les
  adresses de Tailscale et si la route ne part pas de l'interface Tailscale du PC.
- Pour l'historique, le fichier `data-auto.js` d'un tableau de bord de santé (`reseau.sante_donnees_url`),
  qui contient `window.HEALTHSTATS_AUTO = {...};`, lu sans jeton avec les mêmes contrôles.
- Dans `poc/.env` :

| Variable | Effet |
|---|---|
| `SANTE_JETON` | Jeton du service. Vide : relais et historique éteints. |
| `SANTE_URL` | Remplace `reseau.sante_url`. |
| `SANTE_PERSONNES` | Connexions permises, séparées par des virgules : clé d'un jeton fixe (`proprietaire.cle` pour `SATELLITE_JETON`, le nom en minuscules pour `SATELLITE_JETON_<NOM>`) ou `appareil:<id>` pour un téléphone appairé. Ligne absente : le propriétaire seul. Ligne présente mais vide : personne. |
| `SANTE_SEUIL_PAS` | Seuil d'une journée active (6000 par défaut). |
| `SANTE_SEUIL_NUIT_MIN` | Seuil d'une bonne nuit, en minutes (420 par défaut). |
| `SANTE_FC_MAX` | Fréquence cardiaque maximale de référence pour les zones (entre 100 et 250, sinon pas de bornes). |

Confidentialité :

- Servie seulement sur la liaison chiffrée (wss) et aux connexions permises.
- Rien sur disque ni dans les journaux du serveur, résumé gardé 10 minutes en mémoire.
- Sur la tablette, affichée seulement quand la vision reconnaît le propriétaire, seul et avec assurance,
  sur une image de moins d'une seconde. Le profil de visage doit porter le prénom `proprietaire.nom`. Une
  autre personne ou un inconnu à l'image la cache aussitôt. Jamais en veille, en AOD ni sur fond noir.

Pour l'éteindre : laisser `SANTE_JETON` vide, ou écrire `SANTE_PERSONNES=` sans valeur. Sans vision, rien
ne s'affiche non plus. L'accueil et le panneau perdent alors leurs lignes de santé.

### Météo marine et vent mesuré

La page Mer (prévisions de la journée sur les points en mer) et la page Vent mesuré (balises et stations,
sur une carte) s'ajoutent au panneau Météo de la tablette. Les sources sont publiques et sans clé, aucune
donnée personnelle ne part : les deux profils (PC et Home Assistant) les servent à toute connexion.

Pour les activer :

1. Section `mer` avec `"actif": true` et au moins un point.
2. Section `vent` avec `"actif": true` et un `cadre` de quatre nombres.
3. Le trait de côte et la terre dans `genere/android/`, aux chemins de `vent.carte.cote` et
   `vent.carte.terre`. Ce sont deux fichiers texte contenant un chemin SVG (`M x,y L x,y ...`), en
   coordonnées de la carte : `x = (lon - lon_min) / (lon_max - lon_min) * largeur` et
   `y = (lat_max - lat) / (lat_max - lat_min) * hauteur`. Le script `carte/vent/generer_cote.py` les
   produit depuis un fichier GeoJSON de données ouvertes, voir
   [Régénérer la côte et le plan 3D](#régénérer-la-côte-et-le-plan-3d). Ceux de l'exemple sont une côte
   fictive qui rappelle la rade de Marseille. Pour un vrai plan d'eau, utiliser un trait de côte exact (par
   exemple OpenStreetMap, `natural=coastline`, licence ODbL, à créditer dans `vent.carte.attribution`).
4. Recompiler l'APK, qui refuse de se fabriquer si `vent` est actif sans ces deux fichiers.

L'appli n'affiche les deux pages que si `mer` et `vent` sont actives ensemble. Le serveur, lui, sert la
météo marine avec `mer` seule, et le vent mesuré seulement avec les deux.

Pour les éteindre :

| Moyen | Effet |
|---|---|
| Section `mer` absente, ou `"actif": false` | Serveur : ni météo marine ni vent mesuré. Appli : pages Mer et Vent masquées, aperçu de la mer caché, aucune question classée "mer". |
| Section `vent` absente, ou `"actif": false` | Serveur : vent mesuré éteint, météo marine gardée. Appli : pages Mer et Vent masquées toutes les deux. |
| `METEO_MER=0` dans `poc/.env` (ou `non`, `false`, `off`) | Le serveur ne sert plus ni la météo marine ni le vent mesuré, puisque la page Vent fait partie du panneau Mer. Les pages de l'appli restent si la configuration les active, mais elles ne reçoivent plus rien de ce serveur. |
| `VENT_MESURE=0` dans `poc/.env` | Le serveur ne sert plus le vent mesuré, la météo marine reste servie. |

L'appli demande ces données au serveur du PC s'il les annonce, sinon à l'appli Home Assistant.

### Régénérer la côte et le plan 3D

Les deux fichiers de la carte du vent (côte et terre) et la vue 3D se fabriquent à partir de vos propres
données, sans que le moteur télécharge quoi que ce soit.

Pour la côte, récupérer d'abord un fichier GeoJSON de votre plan d'eau en longitude et latitude WGS84, des
lignes de côte ou des contours. Un export OpenStreetMap (`natural=coastline`, par exemple depuis Overpass
turbo), un découpage IGN ou Natural Earth convient. Puis, sous PowerShell :

```powershell
$env:ASSISTANT_VOCAL_CONFIG = "config"
.venv\Scripts\python carte/vent/generer_cote.py ma_cote.geojson
```

Sous Linux ou macOS : `ASSISTANT_VOCAL_CONFIG=config .venv/bin/python carte/vent/generer_cote.py ma_cote.geojson`.

Le script lit le cadre (`vent.cadre`), la taille de la carte (`vent.carte.largeur` et `hauteur`) et les
chemins de sortie (`vent.carte.cote` et `vent.carte.terre`, sous `genere/android/`) dans `maison.json`. Il
joint les lignes qui se touchent, referme la terre le long du cadre (la terre est à gauche du sens de la
ligne, comme dans OpenStreetMap), et traite les contours fermés comme des îles. Il écrit les deux fichiers et
dit en une ligne ce qu'il a trouvé. Deux exécutions sur la même entrée donnent les mêmes octets. Options :

| Option | Effet |
|---|---|
| `--cadre LAT_MIN LAT_MAX LON_MIN LON_MAX` | Autre cadre que `vent.cadre`. |
| `--taille LARGEUR HAUTEUR` | Autre taille que celle de `vent.carte`. |
| `--sortie DOSSIER` | Autre dossier que `genere/android/`. |
| `--cote CHEMIN`, `--terre CHEMIN` | Autres noms de fichiers que ceux de `vent.carte`. |
| `--marge PIXELS` | Marge tracée hors cadre pour que la côte ne s'arrête pas au bord (60 par défaut). |
| `--tolerance PIXELS` | Allège le tracé (Douglas-Peucker), 0 par défaut pour tout garder. |
| `--terre-a-droite` | Pour une source dont la terre est à droite du sens de la ligne. |

Une entrée illisible, sans côte ou hors du cadre donne un message clair et aucun fichier n'est écrit. La côte
d'exemple se régénère avec
`ASSISTANT_VOCAL_CONFIG=config-exemple python carte/vent/generer_cote.py config-exemple/carte/cote_source.geojson`,
et les fichiers qui en sortent sont ceux du dépôt. Le fichier source de l'exemple est entièrement fictif.

Pour le plan 3D, après avoir décrit le logement dans `carte/` (`pieces.json`, `meubles.json`, `lampes.json`) :

```powershell
.venv\Scripts\python carte/3d/generer_3d.py
```

Il produit `carte/modele.glb` et `genere/android/maison3d/vue3d.html`, avec le dossier de configuration
choisi par `ASSISTANT_VOCAL_CONFIG`. Sur la même description, deux exécutions donnent les mêmes fichiers. Le
détail du plan 2D et de la vue 3D est dans
[Régénérer le plan 2D et la vue 3D](#régénérer-le-plan-2d-et-la-vue-3d). Après l'un ou l'autre, recompiler
l'APK.

### Mot de réveil

Le mot par défaut est "assistant". Le moteur public ne fournit pas son modèle, et le seul modèle qu'openWakeWord
sait détecter sans fichier de la configuration est "Hey Jarvis" (anglais). Tant que `reveil/assistant.onnx` manque,
l'assistant se replie donc sur "Hey Jarvis", affiche ce nom et l'écrit au journal du serveur au démarrage :
`modèle de réveil absent pour le mot assistant (attendu : ...), repli sur Hey Jarvis`. Pour un mot à soi :

1. Obtenir un modèle openWakeWord au format ONNX.
2. Le ranger dans `reveil/<mot>.onnx` du dossier de configuration, avec sa licence dans
   `reveil/<mot>.onnx.LICENSE` (sans elle, la compilation avertit).
3. Le décrire dans la section `reveil` de `maison.json`.
4. Recompiler l'APK, qui range le modèle dans ses assets.

Sur le PC, le mot est cherché dans cet ordre : `reveil.mot` de `maison.json`, puis la variable `MOT_REVEIL` de
`poc/.env` (réglage de secours, qui ne casse pas une installation existante), puis `assistant`. Le nom affiché est
`reveil.nom` quand le mot vient de `maison.json`, sinon le mot avec une majuscule.

À l'écran, les réglages de l'appli proposent le mot de la configuration à côté de "Hey Jarvis", avec sa
langue et sa licence, et le prennent par défaut. L'appli Home Assistant annonce toujours "Hey Jarvis", elle ne
reçoit pas le dossier `reveil/`.

Pour ne guetter que "Hey Jarvis" : retirer la section `reveil` et mettre `MOT_REVEIL=hey_jarvis` dans
`poc/.env`. Une section `reveil` dont le modèle manque fait échouer la compilation de l'APK. L'exemple `config-exemple/` décrit le mot
"assistant" sans fournir son modèle : déposer un modèle dans `reveil/` ou retirer la section avant de compiler.

### Vision des visages

La caméra avant de la tablette trouve les visages et reconnaît les profils enregistrés. Elle sert à savoir
qui parle (pour "ma chambre" et pour `permis_personne`) et à montrer la santé au seul propriétaire.

Aucun réglage dans `maison.json`. Elle s'active dans les réglages de l'appli, carte "Vision" :
"Désactivée" (par défaut), "Sur la tablette" ou "Sur le PC". Les profils se créent dans "Visages
enregistrés". Leurs empreintes restent sur la tablette, aucune image n'est gardée, ni sur la tablette ni
sur le PC. L'analyse sur le PC demande le profil `pc` et les modèles YuNet et SFace dans
`poc/modeles/vision/` (`python poc/outils/telecharger_modeles.py`). Si le PC ne répond pas, l'analyse
repasse sur la tablette.

Le nom d'un profil doit correspondre à `proprietaire.nom` pour la santé, et à la clé de la personne dans
`personnes` et `permis_personne` pour le reste. La caméra filme une pièce commune : l'appli rappelle de ne
l'activer qu'avec l'accord de tous les occupants.

Pour l'éteindre : "Désactivée". Plus aucune santé à l'écran, et "ma chambre" vise toujours la chambre de
`personnes.defaut`.

## 6. La sécurité et ce que la configuration en règle

La sécurité est écrite deux fois, dans `poc/securite.py` et dans `Securite.kt`, avec les mêmes règles. Les
cas communs sont dans `poc/tests/cas_securite.json`, vérifiés par `test_securite.py` et `SecuriteTest.kt`.

### Les règles et leurs drapeaux

| Règle | Drapeau dans le code | État dans cette version | Listes de la configuration |
|---|---|---|---|
| 1. Ne jamais toucher aux affaires de l'occupant protégé (entités, zones, `all`, pièces, phrases qui le nomment) | `PROTEGER_OCCUPANT` | Coupée (`False`) | `nom_occupant`, `mots_proteges`, `mots_pieces`, `zones_protegees`, `entites_protegees` |
| 2. Aucun son dans la pièce de vie pendant les heures calmes, sauf pour baisser ou couper | `HEURE_CALME_ACTIVE` | Coupée (`False`) | `son_salon`, `heures_calmes`, `fuseau` |
| 3. Exception à la règle 1 : l'occupant reconnu, seul devant la tablette, pilote ses lumières | dépend de la règle 1 | Sans effet tant que la règle 1 est coupée | `permis_personne` |

Ces drapeaux ne se règlent pas dans la configuration. Tant qu'ils restent à `False`, les listes ci-dessus
sont lues mais ne changent rien : le LLM voit aussi les appareils de l'occupant, aucune pièce ne porte de
cadenas, et le son passe à toute heure. Remettre une règle demande de repasser son drapeau à `True` dans
`poc/securite.py` et dans `Securite.kt`, puis d'adapter les cas de `cas_securite.json`.

Quand la règle 1 est active :

- Une action est refusée si son service ou l'une de ses entités contient un mot de `mots_proteges` ou
  figure dans `entites_protegees`, si elle vise `all`, ou si elle vise une zone de `zones_protegees`.
- Une phrase qui contient un mot protégé est refusée avant le LLM, sauf si la personne reconnue a une
  entrée dans `permis_personne` (ses actions restent vérifiées une à une).
- Les appareils protégés et ceux des pièces dont le nom contient un mot de `mots_pieces` sont cachés au LLM,
  sauf les `entites` de la personne reconnue.
- Une action permise par `permis_personne` n'est jamais apprise comme phrase.

Pour `permis_personne`, la clé est le prénom en minuscules sans accent. Le prénom reconnu est ramené à la
même forme avant la comparaison. Le droit tient seulement si le service est dans `services` et l'entité
dans `entites`.

Quand la règle 2 est active, entre `heures_calmes.debut` (compris) et `heures_calmes.fin` (exclue), à
l'heure de `fuseau`, un service sur une entité de `son_salon`, ou un script de `son_salon` appelé comme
service, est refusé, sauf `media_player.turn_off`, `media_player.media_pause`, `media_player.media_stop`,
`media_player.volume_down`, `media_player.volume_mute` (pas pour rétablir le son) et `script.turn_off`.
Cette liste de services est écrite dans le code. Le message de refus donne la plage configurée, par exemple
"pas de son dans le salon entre minuit et 9 h (sécurité)", et dit "minuit" pour l'heure 0.

### Le plafond de volume

`securite.plafond_volume` fixe le volume le plus fort que l'assistant envoie, en pourcentage du volume de
l'enceinte. Il est lu au démarrage du serveur et compilé dans l'appli. Après un changement, relancer le
serveur, régénérer le dictionnaire (`python android/outils/exporter_dictionnaire.py`, qui recalcule les services
permis au LLM de l'appli, `volume_up` compris) puis reconstruire l'APK.

| Valeur | Effet |
|---|---|
| absente, `null` ou `100` | Aucun plafond (défaut). `media_player.volume_up` est permis, au LLM du serveur compris. |
| de `0` à moins de `100` | Un `volume_level` de `media_player.volume_set` est ramené entre 0 et cette valeur divisée par 100, quelle que soit la voie (voix, LLM, écrans, passerelle). `media_player.volume_up` est refusé quand il n'a pas pu devenir un volume précis (monter par pas passerait au-dessus). Les pistes de volume de l'appli s'arrêtent au plafond, marqué par un trait. |
| au-dessus de `100`, en dessous de `0` | Ramenée à 100 ou à 0. |
| autre chose (texte, `true`) | Plafond prudent de 50 %, pour qu'une faute de frappe ne lève pas un plafond voulu. |

Un niveau illisible dans une commande (`NaN`, texte) donne toujours 0.

### Le repli Assist

Assist est l'agent intégré de Home Assistant. Il exécute une phrase sans qu'on voie sa cible avant, donc
sans que la sécurité puisse la vérifier. Il est coupé par défaut. `securite.assist_repli` ne l'ouvre que comme
repli, après un échec du LLM (modèle injoignable, clé absente), jamais avant lui. Il est lu au démarrage du
serveur, relancer le serveur après un changement. Seul `true` ouvre le repli (texte ou nombre : coupé).

Ce que le réglage ouvre : une phrase que le LLM n'a pas pu traiter est confiée à Assist, à condition que
`securite.refus_phrase_assist` ne la refuse pas. Ce filtre écarte une phrase qui contient :

- un mot de l'occupant protégé (`nom_occupant`, `mots_proteges`, `mots_pieces`), même si la règle 1 est levée ;
- une serrure, une porte, un portail, un garage, une alarme ou une sirène ;
- un four, une plaque, un appareil de chauffe ou de froid, le chauffage, un thermostat, une température ;
- une visée large ou indéterminée (tout, toutes, partout, la maison, un étage, une étiquette, un appareil) ;
- un script, une scène, une automatisation ou une routine ;
- le volume ou le son, quand `plafond_volume` règle un plafond.

Ce que le réglage n'ouvre jamais : il ne coupe pas `SECURITE_ACTIVE`, il ne contourne aucune règle de
`verifier()` et ne change rien pour le LLM, le dictionnaire ni les routines. Une phrase refusée par le filtre
ne va pas à Assist, quel que soit le réglage. Le filtre travaille sur les mots de la phrase, pas sur la cible
réelle : une fois la phrase confiée à Assist, son effet n'est plus contrôlé. Ne l'ouvrir que si ce risque est
accepté. Le journal des commandes dit pourquoi : `repli coupé par le réglage securite.assist_repli`,
`repli refusé par la sécurité : ...` ou, quand Assist a répondu, la voie `assist (repli après échec du LLM)`.
Hors mode essai seulement.

### Ce qui ne se règle pas

Ces protections sont actives dans cette version et aucune configuration ne les change :

| Protection | Où |
|---|---|
| Un appareil visé par son identifiant brut (`device_id`), un étage (`floor_id`) ou une étiquette (`label_id`) est refusé. | `securite.py`, `Securite.kt` |
| Le LLM ne peut appeler que les services d'une liste blanche, large depuis la version 0.37.0 (tout ce que Home Assistant expose pour les équipements, dont `domaine_tele.launch_app` avec une adresse `https://` seulement, `domaine_tele.send_text_input`, `domaine_tele.set_picture_setting`, `remote.send_command`, `select.select_option`), mais jamais par `device_id`, `floor_id` ou `label_id`, et rien qui ouvre une porte ou désarme une alarme. Il ne voit et n'appelle toutefois que ses domaines habituels (lumières, interrupteurs, ventilateurs, volets, climat, lecteurs, Music Assistant, aspirateur, scènes, scripts, booléens, boutons). Les trois domaines (`domaine_tele`, `remote`, `select`) sont réservés au dictionnaire : le LLM ne les voit pas et ne peut pas les appeler (`DOMAINES_HORS_LLM`). | `SERVICES_PERMIS` de `poc/liste_blanche.py` (réexportée par `poc/assistant.py`), exportée dans `dictionnaire.json` pour l'appli. Section facultative `reglages` de `maison.json` : `applis`, `interrupteurs`, `attributs_refuses` (voir ARCHITECTURE.md) |
| Assist de Home Assistant est sauté (il agit sans qu'on voie sa cible avant) : une phrase hors dictionnaire va directement au LLM. Seul `securite.assist_repli` le rouvre, en repli après un échec du LLM et pour une phrase que le filtre accepte ([le repli Assist](#le-repli-assist)). | `SECURITE_ACTIVE` et `repli_assist` de `securite.py` |

Les actions du dictionnaire échappent à la liste blanche, mais pas à ces vérifications : chacune passe par
la sécurité avant d'être envoyée, avec la personne qui parle.
